import os
import pathlib
import tempfile
import unittest
from unittest import mock

from toolshed.validator.tools import ToolUnavailable, resolve_tool


def _executable(directory: pathlib.Path, name: str) -> pathlib.Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/bash\ntrue\n")
    path.chmod(0o755)
    return path


class Resolution(unittest.TestCase):
    def test_a_designated_bin_dir_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            designated = _executable(root / "designated", "shfmt")
            _executable(root / "bin", "shfmt")

            with mock.patch.dict(
                os.environ, {"TOOLSHED_BIN_DIR": str(root / "designated")}
            ):
                self.assertEqual(str(designated), resolve_tool("shfmt", root))

    def test_the_repo_s_own_bin_beats_path(self):
        """A repo pins tools so every checkout runs the same version; a different
        one already on PATH must not silently take precedence."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            pinned = _executable(root / "bin", "shfmt")
            _executable(root / "elsewhere", "shfmt")

            with mock.patch.dict(
                os.environ, {"PATH": str(root / "elsewhere")}, clear=False
            ):
                os.environ.pop("TOOLSHED_BIN_DIR", None)
                self.assertEqual(str(pinned), resolve_tool("shfmt", root))

    def test_path_is_the_final_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            on_path = _executable(root / "elsewhere", "shfmt")

            with mock.patch.dict(
                os.environ, {"PATH": str(root / "elsewhere")}, clear=False
            ):
                os.environ.pop("TOOLSHED_BIN_DIR", None)
                self.assertEqual(str(on_path), resolve_tool("shfmt", root))

    def test_an_unresolvable_tool_names_itself_in_the_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)

            with mock.patch.dict(os.environ, {"PATH": str(root)}, clear=False):
                os.environ.pop("TOOLSHED_BIN_DIR", None)
                with self.assertRaisesRegex(ToolUnavailable, "shfmt"):
                    resolve_tool("shfmt", root)

    def test_a_non_executable_candidate_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "bin").mkdir()
            (root / "bin" / "shfmt").write_text("not executable\n")
            on_path = _executable(root / "elsewhere", "shfmt")

            with mock.patch.dict(
                os.environ, {"PATH": str(root / "elsewhere")}, clear=False
            ):
                os.environ.pop("TOOLSHED_BIN_DIR", None)
                self.assertEqual(str(on_path), resolve_tool("shfmt", root))


class RunnerSurvivesAnUnavailableTool(unittest.TestCase):
    def test_a_raising_validator_becomes_a_failure_not_a_crash(self):
        import pathlib as _pathlib

        from toolshed.validator.base import ValidationResult, Validator
        from toolshed.validator.runner import Task, _run_check

        class Exploding(Validator):
            name = "exploding"

            def check(self, file: _pathlib.Path) -> ValidationResult:
                raise ToolUnavailable("cannot find 'nope'")

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "a.txt").write_text("x\n")
            task = Task(Exploding(None, root), pathlib.Path("a.txt"))

            result = _run_check(task, root, 60)

            self.assertFalse(result.ok)
            self.assertIn("nope", " ".join(result.messages))


if __name__ == "__main__":
    unittest.main()
