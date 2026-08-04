import pathlib
import subprocess

from toolshed.validator.tools import resolve_tool
from toolshed.validator.base import ValidationResult, Validator


class TaploValidator(Validator):
    name = "taplo"
    fixer = True
    priority = 20

    def check(self, file: pathlib.Path) -> ValidationResult:
        bin_path = resolve_tool("taplo", self.repo_root)
        r = subprocess.run(
            [bin_path, "format", "--check", "--diff", str(file)],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            return ValidationResult(ok=True)
        return ValidationResult(
            ok=False,
            messages=tuple(m for m in (r.stdout, r.stderr) if m),
        )

    def fix(self, file: pathlib.Path) -> ValidationResult:
        bin_path = resolve_tool("taplo", self.repo_root)
        before = file.read_bytes()
        r = subprocess.run(
            [bin_path, "format", str(file)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return ValidationResult(
                ok=False,
                messages=tuple(m for m in (r.stdout, r.stderr) if m),
            )
        return ValidationResult(ok=True, fixed=file.read_bytes() != before)
