"""Emit one executable per manifest tool into `bin/`.

`bin/` is generated-and-committed, like a lockfile: a consumer can clone and put
it on PATH with no render step, and a reviewer sees the diff a version bump
causes. `render --check` is what keeps the two honest.

Rendered files carry no path arithmetic, so any one of them can be copied
anywhere and still work (see D3 in the design note). That is what makes a
consumer able to take some tools from a release and others from a checkout.
"""

import argparse
import difflib
import json
import pathlib
import sys
import tempfile

import jinja2

from toolshed.lock import Lock, load_lock
from toolshed.manifest import (
    PLATFORMS,
    BunRunTool,
    DotslashTool,
    Manifest,
    ManifestError,
    RunnerTool,
    Tool,
    UvRunTool,
    load_manifest,
)

DOTSLASH_SHEBANG = "#!/usr/bin/env dotslash"
_TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent / "templates"
_MODE = 0o755


class RenderError(Exception):
    """A tool cannot be rendered from the manifest as it stands."""


def _environment() -> jinja2.Environment:
    # Shell-friendly delimiters: `${...}` and `$(...)` are everywhere in the
    # templates, so the default `{{ }}`/`{% %}` would need escaping throughout.
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
        variable_start_string="<<",
        variable_end_string=">>",
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="<#",
        comment_end_string="#>",
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )


def _render_dotslash(tool: DotslashTool, lock: Lock) -> str:
    """Serialize a dotslash manifest.

    JSON gets a canonical serializer rather than a template: `json.dumps` with a
    two-space indent already matches what biome produces, so there is no
    formatting for `--check` and the `dotslash` validator to disagree about.
    """
    absent = lock.missing_platforms(tool.name)
    if absent:
        raise RenderError(
            f"tool '{tool.name}' is unpinned for {', '.join(absent)}; "
            f"run `render pin {tool.name}`"
        )

    platforms: dict[str, dict[str, object]] = {}
    for platform in PLATFORMS:
        pin = lock.get(tool.name, platform)
        assert pin is not None  # guarded by missing_platforms above
        entry: dict[str, object] = {
            "size": pin.size,
            "hash": "blake3",
            "digest": pin.digest,
        }
        if tool.format is not None:
            entry["format"] = tool.format
        entry["path"] = tool.path_for(platform)
        entry["providers"] = [{"url": tool.url_for(platform)}]
        platforms[platform] = entry

    body = json.dumps({"name": tool.name, "platforms": platforms}, indent=2)
    return f"{DOTSLASH_SHEBANG}\n\n{body}\n"


def render_tool(tool: Tool, manifest: Manifest, lock: Lock) -> str:
    """The full text of `bin/<tool.name>`."""
    if not tool.is_rendered:
        raise RenderError(f"tool '{tool.name}' is not rendered")

    if isinstance(tool, DotslashTool):
        return _render_dotslash(tool, lock)

    if isinstance(tool, UvRunTool):
        template = _environment().get_template("uv-run.sh.j2")
        return template.render(
            tool=tool,
            requirements=tool.resolved_requirements(manifest),
            overridable=tool.overridable_requirements(manifest),
        )

    if isinstance(tool, BunRunTool):
        return _environment().get_template("bun-run.sh.j2").render(tool=tool)

    raise RenderError(f"tool '{tool.name}': no template for method '{tool.method}'")


def _rendered_texts(manifest: Manifest, lock: Lock) -> dict[str, str]:
    return {
        name: render_tool(tool, manifest, lock)
        for name, tool in manifest.tools.items()
        if tool.is_rendered
    }


def write_bin(manifest: Manifest, lock: Lock, bin_dir: pathlib.Path) -> list[str]:
    """Write every rendered tool into `bin_dir`; return the names that changed.

    Files in `bin_dir` that the manifest no longer declares are deleted, so the
    directory always matches the manifest exactly. Passthrough tools are left
    alone -- they are hand-written and merely declared.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    texts = _rendered_texts(manifest, lock)

    changed = []
    for name, text in texts.items():
        path = bin_dir / name
        existed = path.exists()
        if not existed or path.read_text() != text:
            path.write_text(text)
            changed.append(name)
        path.chmod(_MODE)

    for path in bin_dir.iterdir():
        if path.name not in manifest.tools:
            path.unlink()
            changed.append(path.name)

    return sorted(changed)


def check_bin(manifest: Manifest, lock: Lock, bin_dir: pathlib.Path) -> list[str]:
    """Diffs between the committed `bin_dir` and what the manifest renders to.

    Renders into a scratch directory rather than comparing in place, so a check
    never mutates the tree it is checking.
    """
    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp) / "bin"
        write_bin(manifest, lock, scratch)
        expected = {p.name: p.read_text() for p in scratch.iterdir()}

    problems = []
    for name in sorted(expected):
        path = bin_dir / name
        if not path.exists():
            problems.append(f"{name}: absent from {bin_dir}")
            continue
        actual = path.read_text()
        if actual != expected[name]:
            diff = "".join(
                difflib.unified_diff(
                    actual.splitlines(keepends=True),
                    expected[name].splitlines(keepends=True),
                    fromfile=f"{bin_dir}/{name} (committed)",
                    tofile=f"{name} (rendered)",
                )
            )
            problems.append(diff)
        elif path.stat().st_mode & 0o777 != _MODE:
            problems.append(f"{name}: mode is not {_MODE:o}")

    for path in sorted(bin_dir.iterdir()) if bin_dir.is_dir() else []:
        tool = manifest.tools.get(path.name)
        if tool is None:
            problems.append(f"{path.name}: not declared in the manifest")
        elif not tool.is_rendered and not path.stat().st_mode & 0o100:
            problems.append(f"{path.name}: passthrough tool is not executable")

    return problems


def _paths(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    return root / "tools.toml", root / "tools.lock.toml", root / "bin"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="render",
        description="Render bin/ from tools.toml.",
    )
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
        help="Directory holding tools.toml (default: the working directory).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report drift between the committed bin/ and the manifest; write nothing.",
    )
    subparsers = parser.add_subparsers(dest="command")
    pin_parser = subparsers.add_parser(
        "pin", help="Download assets and record their size and digest."
    )
    pin_parser.add_argument(
        "tools", nargs="*", help="Tools to pin (default: every dotslash tool)."
    )
    args = parser.parse_args(argv)

    manifest_path, lock_path, bin_dir = _paths(args.root)
    try:
        manifest = load_manifest(manifest_path)
    except (ManifestError, OSError) as e:
        print(f"render: {e}", file=sys.stderr)
        return 1

    if args.command == "pin":
        from toolshed.pin import pin_tools

        try:
            return pin_tools(manifest, lock_path, args.tools)
        except (ManifestError, RenderError) as e:
            print(f"render pin: {e}", file=sys.stderr)
            return 1

    try:
        lock = load_lock(lock_path)
        if args.check:
            problems = check_bin(manifest, lock, bin_dir)
            for problem in problems:
                sys.stderr.write(problem if problem.endswith("\n") else problem + "\n")
            if problems:
                print(
                    "render --check: bin/ does not match tools.toml; run `render`",
                    file=sys.stderr,
                )
            return 1 if problems else 0

        for name in write_bin(manifest, lock, bin_dir):
            print(f"rendered {name}")
    except (ManifestError, RenderError, OSError) as e:
        print(f"render: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
