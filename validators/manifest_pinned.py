"""Assert every dotslash tool is pinned for every target platform.

An unpinned tool is one whose bytes nobody has vouched for. Shipping one would
mean a consumer on that platform either cannot run the tool or runs whatever the
URL serves that day, which defeats the point of the lockfile.
"""

import pathlib

from toolshed.lock import load_lock
from toolshed.manifest import load_manifest
from lint_trap.base import ValidationResult, Validator


class ManifestPinnedValidator(Validator):
    name = "manifest-pinned"
    fixer = False

    def check(self, file: pathlib.Path) -> ValidationResult:
        manifest = load_manifest(self.repo_root / "tools.toml")
        lock = load_lock(self.repo_root / "tools.lock.toml")

        messages = [
            f"{tool.name}: unpinned for {', '.join(absent)}"
            for tool in manifest.dotslash_tools()
            if (absent := lock.missing_platforms(tool.name))
        ]
        if messages:
            return ValidationResult(
                ok=False,
                messages=(*messages, "run `render pin` to fill the lockfile"),
            )
        return ValidationResult(ok=True)
