import unittest

from toolshed.manifest import ManifestError, parse_manifest

_UV_TOOL = """
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


class RequirementsGroupResolution(unittest.TestCase):
    def test_a_tool_merges_inline_specs_before_group_specs(self):
        manifest = parse_manifest("""
        [requirements.lint]
        packages = ["black", "pyupgrade"]

        [tool.check]
        method = "uv-run"
        module = "check"
        requirement = ["pathspec>=0.12"]
        requirements = ["lint"]
        """)

        self.assertEqual(
            ["pathspec>=0.12", "black", "pyupgrade"],
            manifest.tools["check"].resolved_requirements(manifest),
        )

    def test_groups_resolve_transitively(self):
        manifest = parse_manifest("""
        [requirements.base]
        packages = ["pathspec>=0.12"]

        [requirements.lint]
        packages = ["black"]
        requirements = ["base"]

        [tool.check]
        method = "uv-run"
        module = "check"
        requirements = ["lint"]
        """)

        self.assertEqual(
            ["black", "pathspec>=0.12"],
            manifest.tools["check"].resolved_requirements(manifest),
        )

    def test_a_spec_reached_by_two_paths_appears_once_at_its_first_position(self):
        manifest = parse_manifest("""
        [requirements.base]
        packages = ["pathspec>=0.12"]

        [requirements.lint]
        packages = ["black"]
        requirements = ["base"]

        [tool.check]
        method = "uv-run"
        module = "check"
        requirements = ["base", "lint"]
        """)

        self.assertEqual(
            ["pathspec>=0.12", "black"],
            manifest.tools["check"].resolved_requirements(manifest),
        )

    def test_a_cycle_between_groups_is_rejected(self):
        manifest = parse_manifest("""
        [requirements.a]
        packages = ["pkg-a"]
        requirements = ["b"]

        [requirements.b]
        packages = ["pkg-b"]
        requirements = ["a"]

        [tool.check]
        method = "uv-run"
        module = "check"
        requirements = ["a"]
        """)

        with self.assertRaisesRegex(ManifestError, "cycle"):
            manifest.tools["check"].resolved_requirements(manifest)

    def test_referencing_an_undefined_group_is_rejected(self):
        with self.assertRaisesRegex(ManifestError, "nope"):
            parse_manifest("""
            [tool.check]
            method = "uv-run"
            module = "check"
            requirements = ["nope"]
            """)

    def test_a_group_may_declare_an_override_env_var(self):
        manifest = parse_manifest("""
        [requirements.toolshed]
        packages = ["toolshed @ git+https://example.invalid/toolshed@main"]
        override_env = "TOOLSHED_SOURCE"

        [tool.check]
        method = "uv-run"
        module = "check"
        requirements = ["toolshed"]
        """)

        self.assertEqual(
            "TOOLSHED_SOURCE", manifest.requirements["toolshed"].override_env
        )

    def test_an_overridable_group_may_not_nest_other_groups(self):
        """An override replaces the group wholesale, so nesting would leave it
        ambiguous whether the nested specs survive."""
        with self.assertRaisesRegex(ManifestError, "override_env"):
            parse_manifest("""
            [requirements.base]
            packages = ["pathspec>=0.12"]

            [requirements.toolshed]
            packages = ["toolshed"]
            requirements = ["base"]
            override_env = "TOOLSHED_SOURCE"
            """)

    def test_an_overridable_group_is_kept_separate_from_plain_specs(self):
        """The renderer needs the two apart: plain specs become unconditional
        `--with` args, an overridable group becomes an if/else branch."""
        manifest = parse_manifest("""
        [requirements.lint]
        packages = ["black"]

        [requirements.toolshed]
        packages = ["toolshed @ git+https://example.invalid/toolshed@main"]
        override_env = "TOOLSHED_SOURCE"

        [tool.check]
        method = "uv-run"
        module = "check"
        requirements = ["lint", "toolshed"]
        """)
        tool = manifest.tools["check"]

        self.assertEqual(["black"], tool.resolved_requirements(manifest))
        self.assertEqual(
            [
                (
                    "TOOLSHED_SOURCE",
                    ("toolshed @ git+https://example.invalid/toolshed@main",),
                )
            ],
            tool.overridable_requirements(manifest),
        )


class DotslashTools(unittest.TestCase):
    def test_a_dotslash_tool_exposes_its_platforms(self):
        manifest = parse_manifest(_UV_TOOL)
        tool = manifest.tools["uv"]

        self.assertEqual(
            ["macos-aarch64", "macos-x86_64", "linux-aarch64", "linux-x86_64"],
            sorted(tool.platforms, key=list(tool.platforms).index),
        )
        self.assertEqual("tar.gz", tool.format)

    def test_urls_substitute_version_and_platform_vars(self):
        manifest = parse_manifest(_UV_TOOL)
        tool = manifest.tools["uv"]

        self.assertEqual(
            "https://example.invalid/0.11.7/uv-aarch64-apple-darwin.tar.gz",
            tool.url_for("macos-aarch64"),
        )
        self.assertEqual("uv-aarch64-apple-darwin/uv", tool.path_for("macos-aarch64"))

    def test_a_raw_binary_tool_needs_no_format_and_paths_to_its_own_name(self):
        manifest = parse_manifest("""
        [tool.jq]
        method = "dotslash"
        version = "1.8.1"
        url = "https://example.invalid/jq-{version}/jq-{asset}"
        [tool.jq.platforms]
        macos-aarch64 = { asset = "macos-arm64" }
        macos-x86_64 = { asset = "macos-amd64" }
        linux-aarch64 = { asset = "linux-arm64" }
        linux-x86_64 = { asset = "linux-amd64" }
        """)
        tool = manifest.tools["jq"]

        self.assertIsNone(tool.format)
        self.assertEqual("jq", tool.path_for("macos-aarch64"))

    def test_a_dotslash_tool_must_cover_every_target_platform(self):
        with self.assertRaisesRegex(ManifestError, "linux-x86_64"):
            parse_manifest("""
            [tool.uv]
            method = "dotslash"
            version = "0.11.7"
            url = "https://example.invalid/uv-{triple}"
            [tool.uv.platforms]
            macos-aarch64 = { triple = "aarch64-apple-darwin" }
            macos-x86_64 = { triple = "x86_64-apple-darwin" }
            linux-aarch64 = { triple = "aarch64-unknown-linux-musl" }
            """)

    def test_an_unknown_platform_key_is_rejected(self):
        with self.assertRaisesRegex(ManifestError, "freebsd-x86_64"):
            parse_manifest("""
            [tool.uv]
            method = "dotslash"
            version = "0.11.7"
            url = "https://example.invalid/uv-{triple}"
            [tool.uv.platforms]
            macos-aarch64 = { triple = "aarch64-apple-darwin" }
            macos-x86_64 = { triple = "x86_64-apple-darwin" }
            linux-aarch64 = { triple = "aarch64-unknown-linux-musl" }
            linux-x86_64 = { triple = "x86_64-unknown-linux-musl" }
            freebsd-x86_64 = { triple = "x86_64-unknown-freebsd" }
            """)

    def test_an_unsubstituted_placeholder_is_reported_rather_than_emitted(self):
        manifest = parse_manifest("""
        [tool.uv]
        method = "dotslash"
        version = "0.11.7"
        url = "https://example.invalid/uv-{triple}-{missing}"
        [tool.uv.platforms]
        macos-aarch64 = { triple = "aarch64-apple-darwin" }
        macos-x86_64 = { triple = "x86_64-apple-darwin" }
        linux-aarch64 = { triple = "aarch64-unknown-linux-musl" }
        linux-x86_64 = { triple = "x86_64-unknown-linux-musl" }
        """)

        with self.assertRaisesRegex(ManifestError, "missing"):
            manifest.tools["uv"].url_for("macos-aarch64")


class BunTools(unittest.TestCase):
    def test_a_bun_tool_runs_either_an_entry_or_a_package_but_not_both(self):
        with self.assertRaisesRegex(ManifestError, "entry.*package|package.*entry"):
            parse_manifest("""
            [tool.fmt]
            method = "bun-run"
            entry = "main.ts"
            package = "prettier@3.3.0"
            """)

    def test_a_bun_tool_needs_one_of_entry_or_package(self):
        with self.assertRaisesRegex(ManifestError, "entry.*package|package.*entry"):
            parse_manifest("""
            [tool.fmt]
            method = "bun-run"
            """)


class Schema(unittest.TestCase):
    def test_an_unknown_method_is_rejected(self):
        with self.assertRaisesRegex(ManifestError, "carrier-pigeon"):
            parse_manifest("""
            [tool.nope]
            method = "carrier-pigeon"
            """)

    def test_an_unknown_key_is_rejected_so_typos_do_not_pass_silently(self):
        with self.assertRaisesRegex(ManifestError, "modul"):
            parse_manifest("""
            [tool.check]
            method = "uv-run"
            modul = "check"
            """)

    def test_a_uv_run_tool_needs_a_module(self):
        with self.assertRaisesRegex(ManifestError, "module"):
            parse_manifest("""
            [tool.check]
            method = "uv-run"
            """)

    def test_a_passthrough_tool_carries_no_render_configuration(self):
        manifest = parse_manifest("""
        [tool.hand-written]
        method = "passthrough"
        """)

        self.assertFalse(manifest.tools["hand-written"].is_rendered)

    def test_tools_must_be_sorted_by_name(self):
        with self.assertRaisesRegex(ManifestError, "sorted"):
            parse_manifest("""
            [tool.zebra]
            method = "passthrough"

            [tool.aardvark]
            method = "passthrough"
            """)


if __name__ == "__main__":
    unittest.main()
