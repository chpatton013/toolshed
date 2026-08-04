import pathlib
import subprocess

from toolshed.validator.tools import resolve_tool
from toolshed.validator.base import ValidationResult, Validator


class GitleaksValidator(Validator):
    name = "gitleaks"
    fixer = False

    def check(self, file: pathlib.Path) -> ValidationResult:
        bin_path = resolve_tool("gitleaks", self.repo_root)
        r = subprocess.run(
            [
                bin_path,
                "dir",
                "--no-banner",
                "--no-color",
                "--exit-code",
                "1",
                "-l",
                "warn",
                "-v",
                str(file),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            return ValidationResult(ok=True)
        return ValidationResult(
            ok=False,
            messages=tuple(m for m in (r.stdout, r.stderr) if m),
        )
