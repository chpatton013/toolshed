"""Locate the pinned tools that subprocess-backed validators shell out to.

Resolution order, most specific first:

1. `$TOOLSHED_BIN_DIR` -- a wrapper managing a bin directory designated it.
2. `<repo_root>/bin` -- the repo under validation pins its own tools, and those
   pins are the whole point: a different version already on PATH must not
   silently decide how this repo gets formatted.
3. `PATH` -- for a consumer who installed the tools themselves.
"""

import os
import pathlib
import shutil

BIN_DIR_ENV = "TOOLSHED_BIN_DIR"


class ToolUnavailable(Exception):
    """A validator's underlying tool could not be found."""


def _usable(path: pathlib.Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def resolve_tool(name: str, repo_root: pathlib.Path) -> str:
    designated = os.environ.get(BIN_DIR_ENV)
    candidates = []
    if designated:
        candidates.append(pathlib.Path(designated) / name)
    candidates.append(repo_root / "bin" / name)

    for candidate in candidates:
        if _usable(candidate):
            return str(candidate)

    found = shutil.which(name)
    if found is not None:
        return found

    raise ToolUnavailable(
        f"cannot find '{name}': not in ${BIN_DIR_ENV}, {repo_root / 'bin'}, or PATH"
    )
