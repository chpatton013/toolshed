import pathlib
import tempfile
import unittest

from toolshed.validator.base import Validator
from toolshed.validator.registry import all_validators

_EXTRA = """
import pathlib

from toolshed.validator.base import ValidationResult, Validator


class LocalValidator(Validator):
    name = "repo-local"

    def check(self, file: pathlib.Path) -> ValidationResult:
        return ValidationResult(ok=True)
"""

_CLASHING = _EXTRA.replace('"repo-local"', '"tabs"')


class Builtins(unittest.TestCase):
    def test_the_builtin_validators_load(self):
        validators = all_validators()

        for name in ("tabs", "trailing-newline", "dotslash", "keep-sorted"):
            self.assertIn(name, validators)
            self.assertTrue(issubclass(validators[name], Validator))

    def test_every_builtin_declares_the_name_it_is_registered_under(self):
        for name, cls in all_validators().items():
            self.assertEqual(name, cls.name)

    def test_a_fixer_overrides_fix(self):
        for name, cls in all_validators().items():
            if cls.fixer:
                self.assertIsNot(
                    Validator.fix, cls.fix, f"{name} claims fixer but has no fix()"
                )


class ExtraPaths(unittest.TestCase):
    """D6: the engine merges its builtins with validators a repo defines itself,
    so extracting the engine into its own project later is a move, not a rewrite.
    """

    def test_validators_from_an_extra_path_are_registered(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra = pathlib.Path(tmp)
            (extra / "local.py").write_text(_EXTRA)

            validators = all_validators([extra])

            self.assertIn("repo-local", validators)
            self.assertIn("tabs", validators)

    def test_a_name_clashing_with_a_builtin_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra = pathlib.Path(tmp)
            (extra / "clash.py").write_text(_CLASHING)

            with self.assertRaisesRegex(ValueError, "tabs"):
                all_validators([extra])

    def test_a_missing_extra_path_is_reported(self):
        with self.assertRaisesRegex(ValueError, "absent|not exist"):
            all_validators([pathlib.Path("/nonexistent/validators")])

    def test_dunder_files_in_an_extra_path_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            extra = pathlib.Path(tmp)
            (extra / "__init__.py").write_text("raise AssertionError('imported')\n")
            (extra / "local.py").write_text(_EXTRA)

            self.assertIn("repo-local", all_validators([extra]))


if __name__ == "__main__":
    unittest.main()
