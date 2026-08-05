import contextlib
import io
import json
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from toolshed.lock import Lock, PlatformPin, load_lock
from toolshed.manifest import ManifestError, load_manifest, parse_manifest
from toolshed.render import RenderError, check_bin, render_tool, run_update, write_bin

_LOCK = Lock(
    {
        "uv": {
            platform: PlatformPin(size=100 + i, digest=f"{i:064x}")
            for i, platform in enumerate(
                ["macos-aarch64", "macos-x86_64", "linux-aarch64", "linux-x86_64"]
            )
        }
    }
)

_UV_MANIFEST = r"""
[tool.uv]
method = "dotslash"
version = "0.11.7"
url = "https://example.invalid/{version}/uv-{triple}.tar.gz"
format = "tar.gz"
archive_path = "uv-{triple}/uv"
[tool.uv.platforms]
macos-aarch64 = { triple = "aarch64-apple-darwin" }
macos-x86_64 = { triple = "x86_64-apple-darwin" }
linux-aarch64 = { triple = "aarch64-unknown-linux-musl" }
linux-x86_64 = { triple = "x86_64-unknown-linux-musl" }
"""


def _render(manifest_text: str, tool_name: str, lock: Lock | None = None) -> str:
    manifest = parse_manifest(manifest_text)
    return render_tool(manifest.tools[tool_name], manifest, lock or Lock({}))


class DotslashRendering(unittest.TestCase):
    def test_the_rendered_file_is_a_dotslash_manifest(self):
        out = _render(_UV_MANIFEST, "uv", _LOCK)

        self.assertTrue(out.startswith("#!/usr/bin/env dotslash\n\n"))
        self.assertIn('"name": "uv"', out)

    def test_every_platform_carries_its_url_size_and_digest(self):
        out = _render(_UV_MANIFEST, "uv", _LOCK)

        self.assertIn(
            "https://example.invalid/0.11.7/uv-aarch64-apple-darwin.tar.gz", out
        )
        self.assertIn('"digest": "' + f"{0:064x}" + '"', out)
        self.assertIn('"size": 100', out)
        self.assertIn('"hash": "blake3"', out)

    def test_the_json_body_parses(self):
        import json

        out = _render(_UV_MANIFEST, "uv", _LOCK)
        body = json.loads(out.split("\n", 1)[1])

        self.assertEqual("uv", body["name"])
        self.assertEqual(4, len(body["platforms"]))
        self.assertEqual(
            "uv-aarch64-apple-darwin/uv", body["platforms"]["macos-aarch64"]["path"]
        )
        self.assertEqual("tar.gz", body["platforms"]["macos-aarch64"]["format"])

    def test_a_raw_binary_omits_the_format_key(self):
        import json

        manifest = _UV_MANIFEST.replace('format = "tar.gz"\n', "").replace(
            r'archive_path = "uv-{triple}/uv"' + "\n", ""
        )
        out = _render(manifest, "uv", _LOCK)
        body = json.loads(out.split("\n", 1)[1])

        self.assertNotIn("format", body["platforms"]["macos-aarch64"])
        self.assertEqual("uv", body["platforms"]["macos-aarch64"]["path"])

    def test_an_unpinned_tool_will_not_render(self):
        with self.assertRaisesRegex(RenderError, "unpinned|not pinned"):
            _render(_UV_MANIFEST, "uv", Lock({}))


class UvRunRendering(unittest.TestCase):
    _MANIFEST = """
    [requirements.lint]
    packages = ["black", "pyupgrade"]

    [requirements.toolshed]
    packages = ["toolshed @ git+https://example.invalid/toolshed@main"]
    override_env = "TOOLSHED_SOURCE"

    [tool.validate]
    method = "uv-run"
    module = "toolshed.validator"
    requirement = ["pathspec>=0.12"]
    requirements = ["lint", "toolshed"]
    """

    def test_the_wrapper_contains_no_path_arithmetic(self):
        """Rendered wrappers must be relocatable, so they may not derive their
        own location from BASH_SOURCE."""
        out = _render(self._MANIFEST, "validate")

        self.assertNotIn("BASH_SOURCE", out)
        self.assertNotIn("readlink", out)
        self.assertNotIn("repo_root", out)

    def test_every_resolved_requirement_becomes_a_with_argument(self):
        out = _render(self._MANIFEST, "validate")

        for spec in ("pathspec>=0.12", "black", "pyupgrade"):
            self.assertIn(f'--with "{spec}"', out)

    def test_an_overridable_group_renders_as_a_conditional(self):
        out = _render(self._MANIFEST, "validate")

        self.assertIn('if [ -n "${TOOLSHED_SOURCE:-}" ]', out)
        self.assertIn('--with "$TOOLSHED_SOURCE"', out)
        self.assertIn(
            '--with "toolshed @ git+https://example.invalid/toolshed@main"', out
        )

    def test_the_runner_prefers_a_designated_bin_dir_over_path(self):
        out = _render(self._MANIFEST, "validate")

        self.assertIn('if [ -n "${TOOLSHED_BIN_DIR:-}" ]', out)
        self.assertIn('uv="$TOOLSHED_BIN_DIR/uv"', out)
        self.assertIn('exec "$uv"', out)

    def test_it_execs_the_declared_module(self):
        out = _render(self._MANIFEST, "validate")

        self.assertIn("python -m toolshed.validator", out)
        self.assertIn('"$@"', out)


class UvRunArgsRendering(unittest.TestCase):
    def test_fixed_args_are_emitted_before_the_caller_s_arguments(self):
        out = _render(
            """
            [tool.test]
            method = "uv-run"
            module = "unittest"
            args = ["discover", "-s", "tests", "-t", "."]
            """,
            "test",
        )

        self.assertIn('python -m unittest "discover" "-s" "tests" "-t" "." "$@"', out)


class BunRunRendering(unittest.TestCase):
    def test_an_entry_tool_runs_the_entry(self):
        out = _render(
            """
            [tool.fmt]
            method = "bun-run"
            entry = "entrypoints/fmt/main.ts"
            """,
            "fmt",
        )

        self.assertIn('exec "$bun" run "entrypoints/fmt/main.ts" "$@"', out)

    def test_a_package_tool_runs_bun_x(self):
        out = _render(
            """
            [tool.cdk]
            method = "bun-run"
            package = "aws-cdk@2.1126.0"
            """,
            "cdk",
        )

        self.assertIn('exec "$bun" x --package "aws-cdk@2.1126.0" cdk "$@"', out)


class WriteBin(unittest.TestCase):
    def _manifest(self):
        return parse_manifest(_UV_MANIFEST + """
            [tool.validate]
            method = "uv-run"
            module = "toolshed.validator"
            """)

    def test_rendered_files_are_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            write_bin(self._manifest(), _LOCK, bin_dir)

            mode = (bin_dir / "validate").stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR)
            self.assertTrue(mode & stat.S_IXGRP)
            self.assertTrue(mode & stat.S_IXOTH)

    def test_rendering_twice_produces_identical_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            write_bin(self._manifest(), _LOCK, bin_dir)
            first = {p.name: p.read_bytes() for p in bin_dir.iterdir()}
            write_bin(self._manifest(), _LOCK, bin_dir)
            second = {p.name: p.read_bytes() for p in bin_dir.iterdir()}

            self.assertEqual(first, second)

    def test_a_passthrough_tool_is_left_untouched(self):
        manifest = parse_manifest("""
        [tool.hand-written]
        method = "passthrough"
        """)
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "hand-written").write_text("#!/bin/bash\necho mine\n")
            write_bin(manifest, Lock({}), bin_dir)

            self.assertEqual(
                "#!/bin/bash\necho mine\n", (bin_dir / "hand-written").read_text()
            )

    def test_a_stale_file_is_removed_so_bin_matches_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "removed-tool").write_text("stale\n")
            write_bin(self._manifest(), _LOCK, bin_dir)

            self.assertFalse((bin_dir / "removed-tool").exists())


class RenderedWrapperExecutes(unittest.TestCase):
    """The end-to-end proof of relocatability: a rendered wrapper must run
    correctly from a directory unrelated to the repo it was rendered in."""

    def test_a_wrapper_runs_from_an_unrelated_directory(self):
        manifest = parse_manifest("""
        [tool.shout]
        method = "uv-run"
        module = "shout"
        """)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bin_dir = root / "somewhere" / "bin"
            write_bin(manifest, Lock({}), bin_dir)

            # A fake `uv` stands in for the real one: it proves the wrapper
            # resolved a runner from TOOLSHED_BIN_DIR and passed the expected
            # argv, without downloading anything.
            fake_bin = root / "fake"
            fake_bin.mkdir()
            fake_uv = fake_bin / "uv"
            fake_uv.write_text('#!/bin/bash\necho "ARGS: $*"\n')
            fake_uv.chmod(0o755)

            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            result = subprocess.run(
                [str(bin_dir / "shout"), "--flag"],
                cwd=elsewhere,
                capture_output=True,
                text=True,
                env={**os.environ, "TOOLSHED_BIN_DIR": str(fake_bin)},
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("python -m shout --flag", result.stdout)

    def test_a_wrapper_falls_back_to_the_runner_on_path(self):
        manifest = parse_manifest("""
        [tool.shout]
        method = "uv-run"
        module = "shout"
        """)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bin_dir = root / "bin"
            write_bin(manifest, Lock({}), bin_dir)

            path_dir = root / "onpath"
            path_dir.mkdir()
            fake_uv = path_dir / "uv"
            fake_uv.write_text('#!/bin/bash\necho "FROM PATH: $*"\n')
            fake_uv.chmod(0o755)

            result = subprocess.run(
                [str(bin_dir / "shout")],
                capture_output=True,
                text=True,
                env={**os.environ, "PATH": str(path_dir)},
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("FROM PATH:", result.stdout)

    def test_an_override_env_redirects_the_group_at_run_time(self):
        manifest = parse_manifest("""
        [requirements.toolshed]
        packages = ["toolshed @ git+https://example.invalid/toolshed@main"]
        override_env = "TOOLSHED_SOURCE"

        [tool.shout]
        method = "uv-run"
        module = "shout"
        requirements = ["toolshed"]
        """)
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bin_dir = root / "bin"
            write_bin(manifest, Lock({}), bin_dir)

            path_dir = root / "onpath"
            path_dir.mkdir()
            fake_uv = path_dir / "uv"
            fake_uv.write_text('#!/bin/bash\necho "ARGS: $*"\n')
            fake_uv.chmod(0o755)
            # The suite itself runs with TOOLSHED_SOURCE set, so the "unset"
            # case has to clear it explicitly rather than inherit it.
            base_env = {**os.environ, "PATH": str(path_dir)}
            base_env.pop("TOOLSHED_SOURCE", None)

            pinned = subprocess.run(
                [str(bin_dir / "shout")],
                capture_output=True,
                text=True,
                env=base_env,
            )
            overridden = subprocess.run(
                [str(bin_dir / "shout")],
                capture_output=True,
                text=True,
                env={**base_env, "TOOLSHED_SOURCE": "/local/checkout"},
            )

            self.assertIn("git+https://example.invalid/toolshed@main", pinned.stdout)
            self.assertNotIn("/local/checkout", pinned.stdout)
            self.assertIn("--with /local/checkout", overridden.stdout)
            self.assertNotIn("git+https", overridden.stdout)


class TwoOverrideGroupsRendering(unittest.TestCase):
    """A wrapper may carry more than one overridable requirements group at
    once (e.g. TOOLSHED_SOURCE and LINT_TRAP_SOURCE side by side). Nothing
    before this test exercised that shape."""

    _MANIFEST = """
    [requirements.alpha]
    packages = ["alpha-pkg @ git+https://example.invalid/alpha@main"]
    override_env = "ALPHA_SOURCE"

    [requirements.beta]
    packages = ["beta-pkg @ git+https://example.invalid/beta@main"]
    override_env = "BETA_SOURCE"

    [tool.shout]
    method = "uv-run"
    module = "shout"
    requirements = ["alpha", "beta"]
    """

    def test_both_conditionals_render_in_declaration_order(self):
        out = self._render()

        alpha_at = out.index('if [ -n "${ALPHA_SOURCE:-}" ]')
        beta_at = out.index('if [ -n "${BETA_SOURCE:-}" ]')
        self.assertLess(alpha_at, beta_at)
        # The fixed uv_args seeding (bash 3.2: never expand an empty array
        # under set -u) still comes first, ahead of either conditional.
        self.assertLess(out.index("uv_args=(run --no-project)"), alpha_at)

    def test_neither_env_var_set_resolves_both_pinned_specs(self):
        out = self._render()

        self.assertIn(
            '--with "alpha-pkg @ git+https://example.invalid/alpha@main"', out
        )
        self.assertIn('--with "beta-pkg @ git+https://example.invalid/beta@main"', out)

    def test_one_group_overridden_resolves_one_of_each(self):
        out = self._run(alpha="/local/alpha")

        self.assertIn("--with /local/alpha", out)
        self.assertIn("--with beta-pkg @ git+https://example.invalid/beta@main", out)
        self.assertNotIn("alpha-pkg @ git+https", out)

    def test_both_groups_overridden_resolves_both_locally(self):
        out = self._run(alpha="/local/alpha", beta="/local/beta")

        self.assertIn("--with /local/alpha", out)
        self.assertIn("--with /local/beta", out)
        self.assertNotIn("git+https", out)

    def _render(self) -> str:
        manifest = parse_manifest(self._MANIFEST)
        return render_tool(manifest.tools["shout"], manifest, Lock({}))

    def _run(self, alpha: str | None = None, beta: str | None = None) -> str:
        """Render the wrapper and run it against a fake `uv` that echoes its
        argv, from a directory unrelated to the repo -- proof that resolution
        happens at run time, not at render time."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            bin_dir = root / "bin"
            manifest = parse_manifest(self._MANIFEST)
            write_bin(manifest, Lock({}), bin_dir)

            fake_bin = root / "fake"
            fake_bin.mkdir()
            fake_uv = fake_bin / "uv"
            fake_uv.write_text('#!/bin/bash\necho "ARGS: $*"\n')
            fake_uv.chmod(0o755)

            env = {**os.environ, "PATH": str(fake_bin)}
            env.pop("ALPHA_SOURCE", None)
            env.pop("BETA_SOURCE", None)
            if alpha is not None:
                env["ALPHA_SOURCE"] = alpha
            if beta is not None:
                env["BETA_SOURCE"] = beta

            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            result = subprocess.run(
                [str(bin_dir / "shout")],
                cwd=elsewhere,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            return result.stdout


class Cli(unittest.TestCase):
    def test_check_combined_with_pin_is_rejected(self):
        """Otherwise `render --check pin` would silently pin and report nothing."""
        from toolshed.render import main

        with self.assertRaises(SystemExit):
            main(["--check", "pin"])

    def test_check_combined_with_update_is_rejected(self):
        from toolshed.render import main

        with self.assertRaises(SystemExit):
            main(["--check", "update"])


# One line per tool, "$NAME" and "$VERSION" swapped in, so the URL's brace
# placeholders don't collide with an f-string's.
_UPDATE_TOOL_TEMPLATE = r"""
[tool.$NAME]
method = "dotslash"
version = "$VERSION"
url = "https://github.com/o/$NAME/releases/download/v{version}/$NAME-{asset}"

[tool.$NAME.platforms]
macos-aarch64 = { asset = "macos-aarch64" }
macos-x86_64 = { asset = "macos-x86_64" }
linux-aarch64 = { asset = "linux-aarch64" }
linux-x86_64 = { asset = "linux-x86_64" }
"""

_UPDATE_PLATFORMS = ["macos-aarch64", "macos-x86_64", "linux-aarch64", "linux-x86_64"]

# Upstream versions a stubbed discover_versions() offers per (fake) repo.
_UPDATE_VERSIONS = {
    "alpha": ["1.0.0", "2.0.0"],  # has an update
    "beta": ["1.0.0"],  # already current
    "gamma": ["1.0.0", "2.0.0"],  # has an update, but one platform 404s
}


def _tool_toml(name: str, version: str) -> str:
    return _UPDATE_TOOL_TEMPLATE.replace("$NAME", name).replace("$VERSION", version)


class UpdateCommand(unittest.TestCase):
    """`render update`, with upstream discovery and asset fetches stubbed out.

    `discover_source` stays real -- it is pure URL parsing, no network -- so
    this also exercises T1's inference against the URL shapes above. Only the
    two network calls (`discover_versions`, the asset fetch inside
    `pin_platform`) are stubbed.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.manifest_path = self.root / "tools.toml"
        self.lock_path = self.root / "tools.lock.toml"
        self.bin_dir = self.root / "bin"

        self.manifest_path.write_text(
            "".join(_tool_toml(name, "1.0.0") for name in sorted(_UPDATE_VERSIONS))
        )

        # Pre-pin every tool at its current version, so write_bin can render
        # a tool that `update` decides not to touch (beta) or rolls back
        # (gamma) without tripping the missing-platform check.
        lock = Lock({})
        for name in _UPDATE_VERSIONS:
            for i, platform in enumerate(_UPDATE_PLATFORMS):
                lock = lock.with_pin(
                    name, platform, PlatformPin(size=10 + i, digest=f"{i:064x}")
                )
        self.lock_path.write_text(lock.dumps())
        write_bin(load_manifest(self.manifest_path), lock, self.bin_dir)

        self.original_manifest_text = self.manifest_path.read_text()

    def _fake_discover_versions(self, source):
        return _UPDATE_VERSIONS[source.repo]

    def _fake_fetch(self, url, headers=None):
        if "/gamma/" in url and "v2.0.0" in url and "linux-x86_64" in url:
            raise ManifestError("simulated 404")
        return f"asset bytes for {url}".encode()

    def _run(self, tool_names=(), **kwargs):
        with (
            mock.patch(
                "toolshed.upstream.discover_versions",
                side_effect=self._fake_discover_versions,
            ),
            mock.patch("toolshed.pin.fetch", side_effect=self._fake_fetch),
        ):
            return run_update(
                self.manifest_path,
                self.lock_path,
                self.bin_dir,
                list(tool_names),
                allow_prerelease=False,
                json_output=kwargs.get("json_output", False),
                report_path=kwargs.get("report_path"),
            )

    def test_a_successful_bump_changes_one_line_lock_and_bin(self):
        status = self._run()

        new_text = self.manifest_path.read_text()
        old_lines = self.original_manifest_text.splitlines()
        new_lines = new_text.splitlines()
        diff = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]
        self.assertEqual(1, len(diff))
        self.assertEqual('version = "1.0.0"', diff[0][0])
        self.assertEqual('version = "2.0.0"', diff[0][1])

        lock = load_lock(self.lock_path)
        for platform in _UPDATE_PLATFORMS:
            pin = lock.get("alpha", platform)
            self.assertIsNotNone(pin)
            # setUp seeded every pin's digest as a zero-padded index; a real
            # re-pin replaces it with the (fake) asset's own digest.
            self.assertNotEqual(f"{_UPDATE_PLATFORMS.index(platform):064x}", pin.digest)

        rendered = (self.bin_dir / "alpha").read_text()
        body = json.loads(rendered.split("\n", 1)[1])
        self.assertIn(
            "v2.0.0", body["platforms"]["macos-aarch64"]["providers"][0]["url"]
        )

        self.assertNotEqual(0, status)  # gamma still fails in this same run

    def test_render_check_is_clean_afterward(self):
        self._run()

        manifest = load_manifest(self.manifest_path)
        lock = load_lock(self.lock_path)
        problems = check_bin(manifest, lock, self.bin_dir)

        self.assertEqual([], problems)

    def test_a_platform_fetch_failure_rolls_back_that_tool_only(self):
        status = self._run()

        new_text = self.manifest_path.read_text()
        # gamma's line is untouched; only alpha's changed.
        self.assertIn('[tool.gamma]\nmethod = "dotslash"\nversion = "1.0.0"', new_text)

        old_lock_text = load_lock(self.lock_path)
        for platform in _UPDATE_PLATFORMS:
            pin = old_lock_text.get("gamma", platform)
            self.assertIsNotNone(pin)
            self.assertEqual(f"{_UPDATE_PLATFORMS.index(platform):064x}", pin.digest)

        self.assertEqual(1, status)  # a failure makes the run report non-zero

    def test_beta_reports_current_with_no_change(self):
        self._run()

        # beta had no update available, so its manifest line and pins are
        # exactly what setUp wrote.
        self.assertIn(
            '[tool.beta]\nmethod = "dotslash"\nversion = "1.0.0"',
            self.manifest_path.read_text(),
        )

    def test_report_marks_the_failed_tool(self):
        # `pin_tools` prints its own per-platform progress to stdout, so the
        # report line assertions read from `--report <path>` instead, to keep
        # this test from depending on that unrelated output.
        report_path = self.root / "report.txt"
        self._run(report_path=report_path)

        report = report_path.read_text()
        self.assertIn("alpha: 1.0.0 -> 2.0.0 (updated)", report)
        self.assertIn("beta: 1.0.0 (current)", report)
        self.assertIn("gamma: 1.0.0 -> 2.0.0 (failed:", report)

    def test_report_path_writes_to_a_file_instead_of_stdout(self):
        report_path = self.root / "report.txt"

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self._run(report_path=report_path)

        # The summary line goes only to the file; stdout still carries
        # `pin_tools`'s own per-platform progress, which is unrelated output.
        self.assertNotIn("alpha: 1.0.0 -> 2.0.0 (updated)", buf.getvalue())
        self.assertIn("alpha: 1.0.0 -> 2.0.0 (updated)", report_path.read_text())

    def test_json_report_is_parseable(self):
        report_path = self.root / "report.json"
        self._run(json_output=True, report_path=report_path)

        records = {r["name"]: r for r in json.loads(report_path.read_text())}
        self.assertEqual("updated", records["alpha"]["outcome"])
        self.assertEqual("2.0.0", records["alpha"]["newest"])
        self.assertEqual("current", records["beta"]["outcome"])
        self.assertIsNone(records["beta"]["newest"])
        self.assertTrue(records["gamma"]["outcome"].startswith("failed:"))

    def test_an_unknown_tool_name_errors_like_render_pin_does(self):
        with self.assertRaises(ManifestError):
            self._run(tool_names=["not-a-tool"])


if __name__ == "__main__":
    unittest.main()
