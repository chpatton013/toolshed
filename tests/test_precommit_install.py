import os
import pathlib
import subprocess
import tempfile
import unittest

from toolshed.validator.precommit.install import install_hook


def _repo(tmp: str) -> pathlib.Path:
    root = pathlib.Path(tmp).resolve()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    wrapper = root / "bin" / "pre-commit"
    wrapper.parent.mkdir()
    wrapper.write_text('#!/bin/bash\necho "SEEN: ${DEMO_VAR:-unset}"\n')
    wrapper.chmod(0o755)
    return root


class SymlinkInstall(unittest.TestCase):
    def test_the_hook_becomes_a_relative_symlink_to_the_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(tmp)

            self.assertEqual(0, install_hook(root))

            hook = root / ".git" / "hooks" / "pre-commit"
            self.assertTrue(hook.is_symlink())
            self.assertEqual("../../bin/pre-commit", os.readlink(hook))

    def test_installing_twice_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(tmp)

            self.assertEqual(0, install_hook(root))
            self.assertEqual(0, install_hook(root))

    def test_an_unrelated_existing_hook_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(tmp)
            hook = root / ".git" / "hooks" / "pre-commit"
            hook.write_text("#!/bin/bash\ntrue\n")

            self.assertEqual(1, install_hook(root))
            self.assertEqual("#!/bin/bash\ntrue\n", hook.read_text())

    def test_force_replaces_an_unrelated_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(tmp)
            hook = root / ".git" / "hooks" / "pre-commit"
            hook.write_text("#!/bin/bash\ntrue\n")

            self.assertEqual(0, install_hook(root, force=True))
            self.assertTrue(hook.is_symlink())


class EnvironmentSeeding(unittest.TestCase):
    """A repo whose wrapper needs a variable set cannot rely on the developer
    remembering to export it before every `git commit`."""

    def test_a_seeded_variable_reaches_the_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(tmp)

            self.assertEqual(0, install_hook(root, env={"DEMO_VAR": "hello"}))

            result = subprocess.run(
                [str(root / ".git" / "hooks" / "pre-commit")],
                capture_output=True,
                text=True,
                cwd=root,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("SEEN: hello", result.stdout)

    def test_a_seeded_hook_is_a_script_rather_than_a_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(tmp)

            install_hook(root, env={"DEMO_VAR": "hello"})

            hook = root / ".git" / "hooks" / "pre-commit"
            self.assertFalse(hook.is_symlink())
            self.assertIn("DEMO_VAR", hook.read_text())

    def test_the_caller_s_own_value_still_wins(self):
        """The seed is a default for interactive use, not an override that would
        stop CI from pointing the wrapper somewhere else."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(tmp)
            install_hook(root, env={"DEMO_VAR": "seeded"})

            result = subprocess.run(
                [str(root / ".git" / "hooks" / "pre-commit")],
                capture_output=True,
                text=True,
                cwd=root,
                env={**os.environ, "DEMO_VAR": "from-caller"},
            )

            self.assertIn("SEEN: from-caller", result.stdout)

    def test_reinstalling_with_a_different_seed_replaces_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(tmp)
            install_hook(root, env={"DEMO_VAR": "first"})

            self.assertEqual(0, install_hook(root, env={"DEMO_VAR": "second"}))

            hook = root / ".git" / "hooks" / "pre-commit"
            self.assertIn("second", hook.read_text())
            self.assertNotIn("first", hook.read_text())

    def test_a_malformed_assignment_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(tmp)

            with self.assertRaises(ValueError):
                install_hook(root, env={"": "novar"})


if __name__ == "__main__":
    unittest.main()
