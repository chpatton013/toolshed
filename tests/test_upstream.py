"""Upstream discovery, version ordering, and version-bump write-back.

`Repo` cases are parametrized directly off the committed `tools.toml`, so a
new dotslash tool whose `url` inference breaks fails this suite rather than
silently shipping an `update` command that can't check it.
"""

import os
import pathlib
import tempfile
import unittest

from toolshed.lock import load_lock
from toolshed.manifest import ManifestError, load_manifest
from toolshed.pin import pin_platform
from toolshed.render import run_update
from toolshed.upstream import (
    Source,
    Unsupported,
    discover_source,
    discover_versions,
    latest_version,
    rewrite_version,
)

_NETWORK = os.environ.get("TOOLSHED_TEST_NETWORK") == "1"
_TOOLS_TOML = pathlib.Path(__file__).resolve().parent.parent / "tools.toml"

# tool name -> (owner, repo, tag_template)
_EXPECTED_SOURCES = {
    "biome": ("biomejs", "biome", r"@biomejs/biome@{version}"),
    "bun": ("oven-sh", "bun", r"bun-v{version}"),
    "gitleaks": ("gitleaks", "gitleaks", r"v{version}"),
    "jq": ("jqlang", "jq", r"jq-{version}"),
    "shellcheck": ("koalaman", "shellcheck", r"v{version}"),
    "shfmt": ("mvdan", "sh", r"v{version}"),
    "taplo": ("tamasfe", "taplo", r"{version}"),
    "uv": ("astral-sh", "uv", r"{version}"),
    "yamlfmt": ("google", "yamlfmt", r"v{version}"),
}


class SourceDiscoveryAgainstTheRealManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = load_manifest(_TOOLS_TOML)
        self.tools = {t.name: t for t in self.manifest.dotslash_tools()}

    def test_every_dotslash_tool_in_the_manifest_has_an_expectation(self):
        # A new tool with no entry above would otherwise pass vacuously.
        self.assertEqual(set(_EXPECTED_SOURCES), set(self.tools))

    def test_each_tool_infers_its_owner_repo_and_tag_template(self):
        for name, (owner, repo, tag_template) in _EXPECTED_SOURCES.items():
            with self.subTest(tool=name):
                source = discover_source(self.tools[name])
                self.assertIsInstance(source, Source)
                self.assertEqual(owner, source.owner)
                self.assertEqual(repo, source.repo)
                self.assertEqual(tag_template, source.tag_template)


class UnsupportedSources(unittest.TestCase):
    def _tool(self, url: str):
        text = f"""
        [tool.thing]
        method = "dotslash"
        version = "1.0.0"
        url = "{url}"
        [tool.thing.platforms]
        macos-aarch64 = {{ asset = "a" }}
        macos-x86_64 = {{ asset = "a" }}
        linux-aarch64 = {{ asset = "a" }}
        linux-x86_64 = {{ asset = "a" }}
        """
        return load_manifest_text(text).tools["thing"]

    def test_a_non_github_url_reports_rather_than_raises(self):
        source = discover_source(self._tool(r"https://example.invalid/thing-{version}"))

        self.assertIsInstance(source, Unsupported)

    def test_a_tag_with_no_version_placeholder_reports(self):
        source = discover_source(
            self._tool(r"https://github.com/o/r/releases/download/latest/thing-{asset}")
        )

        self.assertIsInstance(source, Unsupported)

    def test_a_tag_with_a_per_platform_placeholder_reports(self):
        source = discover_source(
            self._tool(
                r"https://github.com/o/r/releases/download/"
                r"v{version}-{asset}/thing-{asset}"
            )
        )

        self.assertIsInstance(source, Unsupported)

    def test_a_supported_source_still_resolves(self):
        source = discover_source(
            self._tool(r"https://github.com/o/r/releases/download/v{version}/thing")
        )

        self.assertEqual(
            Source(owner="o", repo="r", tag_template=r"v{version}"), source
        )


def load_manifest_text(text: str):
    from toolshed.manifest import parse_manifest

    return parse_manifest(text)


@unittest.skipUnless(_NETWORK, "set TOOLSHED_TEST_NETWORK=1 to query github")
class DiscoverVersionsAgainstRealUpstream(unittest.TestCase):
    def test_shfmt_releases_contain_a_known_version(self):
        source = Source(owner="mvdan", repo="sh", tag_template=r"v{version}")

        versions = discover_versions(source)

        self.assertIn("3.13.1", versions)


@unittest.skipUnless(_NETWORK, "set TOOLSHED_TEST_NETWORK=1 to hit real upstreams")
class RenderUpdateComposesAgainstRealUpstreams(unittest.TestCase):
    """The one test that proves discovery, write-back, and pinning compose.

    A copy of the repo under `tmp_path`, deliberately holding an old shfmt
    release, so `render update` is guaranteed to find something newer. The
    lock digests it writes are then checked against a direct `pin_platform`
    call for that same (now-known) version -- the two paths must agree.
    """

    def test_updating_shfmt_matches_a_direct_pin_of_the_same_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest_path = root / "tools.toml"
            lock_path = root / "tools.lock.toml"
            bin_dir = root / "bin"

            # Column-zero headers, matching taplo's formatting of the real
            # tools.toml: rewrite_version's header regex anchors to the start
            # of the line, so an indented table (as a nested triple-quoted
            # string would otherwise produce) would not match.
            manifest_path.write_text(
                "[tool.shfmt]\n"
                'method = "dotslash"\n'
                'version = "3.9.0"\n'
                r'url = "https://github.com/mvdan/sh/releases/download/'
                r'v{version}/shfmt_v{version}_{asset}"' + "\n"
                "[tool.shfmt.platforms]\n"
                'macos-aarch64 = { asset = "darwin_arm64" }\n'
                'macos-x86_64 = { asset = "darwin_amd64" }\n'
                'linux-aarch64 = { asset = "linux_arm64" }\n'
                'linux-x86_64 = { asset = "linux_amd64" }\n'
            )
            lock_path.write_text("")

            status = run_update(
                manifest_path,
                lock_path,
                bin_dir,
                ["shfmt"],
                allow_prerelease=False,
                json_output=False,
                report_path=None,
            )

            self.assertEqual(0, status)

            updated_manifest = load_manifest(manifest_path)
            bumped = updated_manifest.tools["shfmt"]
            self.assertNotEqual("3.9.0", bumped.version)

            lock = load_lock(lock_path)
            for platform in [
                "macos-aarch64",
                "macos-x86_64",
                "linux-aarch64",
                "linux-x86_64",
            ]:
                direct = pin_platform(bumped, platform)
                written = lock.get("shfmt", platform)
                self.assertIsNotNone(written)
                self.assertEqual(direct.digest, written.digest)
                self.assertEqual(direct.size, written.size)


class VersionOrdering(unittest.TestCase):
    def test_ordering_is_numeric_not_lexical(self):
        self.assertEqual("3.13.1", latest_version(["3.9.0", "3.13.1"], current="3.9.0"))

    def test_a_prerelease_is_dropped_by_default(self):
        self.assertIsNone(latest_version(["1.3.12-canary.1"], current="1.3.12"))

    def test_a_prerelease_is_kept_with_the_flag(self):
        self.assertEqual(
            "1.3.12-canary.1",
            latest_version(
                ["1.3.12-canary.1"], current="1.3.12", allow_prerelease=True
            ),
        )

    def test_an_upstream_behind_the_manifest_reports_no_update(self):
        self.assertIsNone(latest_version(["3.9.0"], current="3.13.1"))

    def test_equal_versions_report_no_update(self):
        self.assertIsNone(latest_version(["3.13.1"], current="3.13.1"))


class VersionWriteBack(unittest.TestCase):
    def setUp(self):
        self.text = _TOOLS_TOML.read_text()

    def test_bumping_shfmt_changes_exactly_one_line(self):
        new_text = rewrite_version(self.text, "shfmt", "9.9.9")

        old_lines = self.text.splitlines()
        new_lines = new_text.splitlines()
        diff = [(a, b) for a, b in zip(old_lines, new_lines) if a != b]

        self.assertEqual(len(old_lines), len(new_lines))
        self.assertEqual(1, len(diff))
        self.assertEqual('version = "3.13.1"', diff[0][0])
        self.assertEqual('version = "9.9.9"', diff[0][1])

    def test_the_result_reparses_with_the_new_version(self):
        new_text = rewrite_version(self.text, "shfmt", "9.9.9")

        manifest = load_manifest_text(new_text)

        self.assertEqual("9.9.9", manifest.tools["shfmt"].version)

    def test_bumping_biome_does_not_touch_bun(self):
        new_text = rewrite_version(self.text, "biome", "9.9.9")

        manifest = load_manifest_text(new_text)

        self.assertEqual("1.3.12", manifest.tools["bun"].version)

    def test_an_absent_tool_raises(self):
        with self.assertRaises(ManifestError):
            rewrite_version(self.text, "does-not-exist", "9.9.9")

    def test_an_absent_version_key_raises(self):
        text = """
        [tool.thing]
        method = "passthrough"
        """
        with self.assertRaises(ManifestError):
            rewrite_version(text, "thing", "9.9.9")


if __name__ == "__main__":
    unittest.main()
