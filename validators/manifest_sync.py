"""Assert the committed `bin/` still matches `tools.toml`.

`bin/` is generated-and-committed, so it can drift: bump a version, forget to
re-render, and the manifest now describes something the repo does not ship. This
is the guard that makes the committed output trustworthy -- the classic
"generated file out of sync" check.
"""

import pathlib
import threading

from toolshed.lock import load_lock
from toolshed.render import check_bin
from toolshed.validator.base import ValidationResult, Validator
from toolshed.manifest import load_manifest


class ManifestSyncValidator(Validator):
    name = "manifest-sync"
    fixer = False

    # The answer is a property of the whole repo, not of one file, but the
    # validator is configured over several files so that editing any of them
    # triggers it -- including under `--dirty`. Compute once per repo per run.
    _cache: dict[pathlib.Path, tuple[str, ...]] = {}
    _lock = threading.Lock()

    def _problems(self) -> tuple[str, ...]:
        with self._lock:
            if self.repo_root not in self._cache:
                manifest = load_manifest(self.repo_root / "tools.toml")
                lock = load_lock(self.repo_root / "tools.lock.toml")
                self._cache[self.repo_root] = tuple(
                    check_bin(manifest, lock, self.repo_root / "bin")
                )
            return self._cache[self.repo_root]

    def check(self, file: pathlib.Path) -> ValidationResult:
        problems = self._problems()
        if problems:
            return ValidationResult(
                ok=False,
                messages=(
                    *problems,
                    "bin/ is out of sync with tools.toml; run `render`",
                ),
            )
        return ValidationResult(ok=True)
