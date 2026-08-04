import os
import pathlib
import stat
import subprocess
import tempfile
import unittest

from toolshed.lock import Lock, PlatformPin
from toolshed.manifest import parse_manifest
from toolshed.render import RenderError, render_tool, write_bin

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


if __name__ == "__main__":
    unittest.main()
