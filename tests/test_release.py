"""Release and installer contracts for supported platform artifacts."""

import os
import pathlib
import re
import subprocess
import tempfile
import tomllib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent


class ReleaseArtifacts(unittest.TestCase):
    def test_release_workflow_publishes_universal_bin_archive(self):
        workflow = (_ROOT / ".github/workflows/release.yml").read_text()

        self.assertIn("toolshed-bin.tar.gz", workflow)
        self.assertNotIn("toolshed-bin-linux-", workflow)

    def test_installer_uses_universal_asset(self):
        installer = (_ROOT / "install.sh").read_text()

        self.assertIn("toolshed-bin.tar.gz", installer)
        self.assertNotIn("Linux:x86_64", installer)
        self.assertNotIn("Linux:aarch64", installer)

    def test_installer_verifies_the_asset_checksum(self):
        installer = (_ROOT / "install.sh").read_text()

        self.assertIn('curl -fsSL "$base/$asset"', installer)
        self.assertIn("sha256sum --check --ignore-missing SHA256SUMS", installer)
        self.assertIn("shasum -a 256 --check --ignore-missing SHA256SUMS", installer)

    def test_self_reference_uses_the_release_tag(self):
        with (_ROOT / "toolshed.toml").open("rb") as source:
            manifest = tomllib.load(source)
        with (_ROOT / "pyproject.toml").open("rb") as source:
            project = tomllib.load(source)

        spec = manifest["requirements"]["toolshed"]["packages"][0]
        version = project["project"]["version"]
        self.assertEqual(
            f"toolshed @ git+https://github.com/chpatton013/toolshed@v{version}",
            spec,
        )

    def test_release_script_updates_the_self_pin(self):
        script = (_ROOT / "scripts/release.sh").read_text()

        self.assertIn('tag="v$version"', script)
        self.assertIn("toolshed @ git+https://github.com/chpatton013/toolshed@", script)

    def test_toolshed_wrapper_runs_outside_checkout_with_source_override(self):
        wrapper = _ROOT / "bin/toolshed"
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [str(wrapper), "--help"],
                cwd=tmp,
                capture_output=True,
                text=True,
                env={**os.environ, "TOOLSHED_SOURCE": str(_ROOT)},
                timeout=120,
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("usage: toolshed", result.stdout)
        self.assertIn("render", result.stdout)


if __name__ == "__main__":
    unittest.main()
