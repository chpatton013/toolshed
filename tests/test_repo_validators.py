"""Tests for this repo's own validators in `validators/`.

They are loaded the way the engine loads them -- by file location through the
registry -- so these tests also exercise the D6 extra-path mechanism against the
real directory rather than a fixture.
"""

import pathlib
import shutil
import subprocess
import tempfile
import unittest

from toolshed.validator.registry import all_validators

_REPO = pathlib.Path(__file__).resolve().parent.parent
_VALIDATORS_DIR = _REPO / "validators"


def _validator(name: str, repo_root: pathlib.Path):
    cls = all_validators([_VALIDATORS_DIR])[name]
    return cls(cls.Config(), repo_root)


def _checkout(tmp: str) -> pathlib.Path:
    """A minimal copy of this repo: manifest, lock, and rendered bin/."""
    root = pathlib.Path(tmp) / "repo"
    root.mkdir()
    for name in ("tools.toml", "tools.lock.toml"):
        shutil.copy(_REPO / name, root / name)
    shutil.copytree(_REPO / "bin", root / "bin")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


class Registration(unittest.TestCase):
    def test_both_repo_validators_register_alongside_the_builtins(self):
        validators = all_validators([_VALIDATORS_DIR])

        self.assertIn("manifest-sync", validators)
        self.assertIn("manifest-pinned", validators)
        self.assertIn("tabs", validators)


class ManifestPinned(unittest.TestCase):
    def test_a_fully_pinned_lock_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _checkout(tmp)

            result = _validator("manifest-pinned", root).check(root / "tools.lock.toml")

            self.assertTrue(result.ok, result.messages)

    def test_a_removed_digest_is_reported_with_the_tool_and_platform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _checkout(tmp)
            lock = root / "tools.lock.toml"
            text = lock.read_text()
            start = text.index('[tool."uv"."linux-x86_64"]')
            end = text.index("[tool.", start + 1)
            lock.write_text(text[:start] + text[end:])

            result = _validator("manifest-pinned", root).check(lock)

            self.assertFalse(result.ok)
            joined = " ".join(result.messages)
            self.assertIn("uv", joined)
            self.assertIn("linux-x86_64", joined)

    def test_an_entirely_absent_tool_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _checkout(tmp)
            lock = root / "tools.lock.toml"
            text = lock.read_text()
            keep = [
                block
                for block in text.split("\n[tool.")
                if not block.startswith('"jq"')
            ]
            lock.write_text("\n[tool.".join(keep))

            result = _validator("manifest-pinned", root).check(lock)

            self.assertFalse(result.ok)
            self.assertIn("jq", " ".join(result.messages))


class ManifestSync(unittest.TestCase):
    def test_a_freshly_rendered_bin_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _checkout(tmp)

            result = _validator("manifest-sync", root).check(root / "tools.toml")

            self.assertTrue(result.ok, result.messages)

    def test_a_version_bumped_without_re_rendering_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _checkout(tmp)
            manifest = root / "tools.toml"
            manifest.write_text(
                manifest.read_text().replace('version = "1.8.1"', 'version = "1.8.2"')
            )

            result = _validator("manifest-sync", root).check(manifest)

            self.assertFalse(result.ok)
            self.assertIn("jq", " ".join(result.messages))

    def test_an_edited_wrapper_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _checkout(tmp)
            wrapper = root / "bin" / "validate"
            wrapper.write_text(wrapper.read_text() + "# hand edit\n")

            result = _validator("manifest-sync", root).check(root / "tools.toml")

            self.assertFalse(result.ok)
            self.assertIn("validate", " ".join(result.messages))

    def test_an_undeclared_file_in_bin_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _checkout(tmp)
            (root / "bin" / "stowaway").write_text("#!/bin/bash\n")

            result = _validator("manifest-sync", root).check(root / "tools.toml")

            self.assertFalse(result.ok)
            self.assertIn("stowaway", " ".join(result.messages))

    def test_the_check_does_not_modify_the_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _checkout(tmp)
            before = {p.name: p.read_bytes() for p in (root / "bin").iterdir()}

            _validator("manifest-sync", root).check(root / "tools.toml")

            after = {p.name: p.read_bytes() for p in (root / "bin").iterdir()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
