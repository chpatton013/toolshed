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
    def test_release_workflow_publishes_linux_architecture_assets(self):
        workflow = (_ROOT / ".github/workflows/release.yml").read_text()

        for asset in (
            "toolshed-bin-linux-x86_64.tar.gz",
            "toolshed-bin-linux-aarch64.tar.gz",
        ):
            self.assertIn(asset, workflow)
            self.assertIn(asset, (_ROOT / "install.sh").read_text())

    def test_linux_assets_are_explicit_labels_for_neutral_wrappers(self):
        workflow = (_ROOT / ".github/workflows/release.yml").read_text()

        self.assertIn("architecture-neutral", workflow)
        self.assertEqual(
            2,
            workflow.count("tar czf dist/toolshed-bin-linux-"),
        )

    def test_ci_runs_the_linux_architecture_matrix(self):
        workflow = (_ROOT / ".github/workflows/ci.yml").read_text()

        self.assertIn("ubuntu-latest", workflow)
        self.assertIn("ubuntu-24.04-arm", workflow)

    def test_installer_maps_supported_linux_architectures(self):
        installer = (_ROOT / "install.sh").read_text()

        self.assertIn("Linux:x86_64 | Linux:amd64", installer)
        self.assertIn("Linux:aarch64 | Linux:arm64", installer)
        self.assertIn('asset="toolshed-bin-linux-x86_64.tar.gz"', installer)
        self.assertIn('asset="toolshed-bin-linux-aarch64.tar.gz"', installer)

    def test_installer_verifies_the_selected_asset_checksum(self):
        installer = (_ROOT / "install.sh").read_text()

        self.assertIn('curl -fsSL "$base/$asset"', installer)
        self.assertIn("sha256sum --check --ignore-missing SHA256SUMS", installer)
        self.assertIn("shasum -a 256 --check --ignore-missing SHA256SUMS", installer)

    def test_self_reference_uses_an_immutable_commit(self):
        with (_ROOT / "toolshed.toml").open("rb") as source:
            manifest = tomllib.load(source)

        spec = manifest["requirements"]["toolshed"]["packages"][0]
        self.assertRegex(spec, r"@\s*git\+https://github\.com/.+@[0-9a-f]{40}$")
        self.assertNotRegex(spec, r"@v[0-9]")

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
