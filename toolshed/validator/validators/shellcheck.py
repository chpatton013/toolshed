import pathlib
import subprocess

from toolshed.validator.tools import resolve_tool
from toolshed.validator.base import ValidationResult, Validator


class ShellcheckValidator(Validator):
    name = "shellcheck"
    fixer = False

    def check(self, file: pathlib.Path) -> ValidationResult:
        bin_path = resolve_tool("shellcheck", self.repo_root)
        r = subprocess.run(
            [bin_path, str(file)],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            return ValidationResult(ok=True)
        return ValidationResult(
            ok=False,
            messages=tuple(m for m in (r.stdout, r.stderr) if m),
        )
