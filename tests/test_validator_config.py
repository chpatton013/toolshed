import pathlib
import subprocess
import tempfile
import unittest

from toolshed.validator.config import (
    effective_config_for_file,
    load_tomls,
    validator_paths,
)


def _git_repo(tmp: str, files: dict[str, str]) -> pathlib.Path:
    # Resolved because macOS puts temp dirs behind the /var -> /private/var
    # symlink, and validator_paths reports resolved paths.
    root = pathlib.Path(tmp).resolve()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


class ValidatorPaths(unittest.TestCase):
    def test_configured_paths_resolve_against_the_declaring_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_repo(
                tmp, {".validator.toml": '[validators]\npaths = ["validators"]\n'}
            )
            (root / "validators").mkdir()

            self.assertEqual(
                [root / "validators"], validator_paths(load_tomls(root), root)
            )

    def test_no_configuration_means_no_extra_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_repo(tmp, {".validator.toml": "[validator.tabs]\n"})

            self.assertEqual([], validator_paths(load_tomls(root), root))

    def test_paths_from_several_files_accumulate_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_repo(
                tmp,
                {
                    ".validator.toml": '[validators]\npaths = ["validators"]\n',
                    "sub/.validator.toml": '[validators]\npaths = ["extra"]\n',
                },
            )
            (root / "validators").mkdir()
            (root / "sub" / "extra").mkdir()

            self.assertEqual(
                [root / "validators", root / "sub" / "extra"],
                validator_paths(load_tomls(root), root),
            )


class EffectiveConfig(unittest.TestCase):
    def test_an_include_glob_selects_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_repo(
                tmp,
                {
                    ".validator.toml": '[validator.tabs]\ninclude_files = ["**/*.py"]\n',
                    "a.py": "",
                },
            )

            matched, _ = effective_config_for_file(
                load_tomls(root), "tabs", root / "a.py", root
            )

            self.assertTrue(matched)

    def test_an_exclude_glob_overrides_the_include(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_repo(
                tmp,
                {
                    ".validator.toml": (
                        "[validator.tabs]\n"
                        'include_files = ["**"]\n'
                        'exclude_files = ["**/*.md"]\n'
                    ),
                    "a.md": "",
                },
            )

            matched, _ = effective_config_for_file(
                load_tomls(root), "tabs", root / "a.md", root
            )

            self.assertFalse(matched)

    def test_a_validator_with_no_configuration_anywhere_is_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _git_repo(tmp, {".validator.toml": "[validator.tabs]\n", "a.py": ""})

            self.assertIsNone(
                effective_config_for_file(
                    load_tomls(root), "unconfigured", root / "a.py", root
                )
            )


if __name__ == "__main__":
    unittest.main()
