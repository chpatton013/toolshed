import argparse
import pathlib
import subprocess
import sys

from toolshed.validator.precommit.hook import run_hook
from toolshed.validator.precommit.install import install_hook


def _find_repo_root() -> pathlib.Path:
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return pathlib.Path(r.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pre-commit",
        description=(
            "Run validators against staged files, or install this tool as the "
            "git pre-commit hook."
        ),
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install this script as the pre-commit hook and exit.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="With --install, overwrite an existing pre-commit hook.",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="VAR=VALUE",
        help=(
            "With --install, have the hook default VAR to VALUE. Repeatable. "
            "A value already exported by the caller still wins."
        ),
    )
    args = parser.parse_args()

    repo_root = _find_repo_root()
    if args.install:
        env = {}
        for assignment in args.env:
            name, separator, value = assignment.partition("=")
            if not separator or not name:
                parser.error(f"--env expects VAR=VALUE, got {assignment!r}")
            env[name] = value
        try:
            return install_hook(repo_root, force=args.force, env=env or None)
        except ValueError as e:
            parser.error(str(e))
    if args.force:
        parser.error("--force requires --install")
    if args.env:
        parser.error("--env requires --install")
    return run_hook(repo_root)


if __name__ == "__main__":
    sys.exit(main())
