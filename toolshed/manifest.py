"""Parse and schema-validate `tools.toml`.

The manifest is the single source of truth for every executable toolshed ships.
One `[tool.<name>]` table per executable; `method` selects the template that
renders it and which other keys that table may carry.

`[requirements.<group>]` tables name reusable dependency sets so related tools
can share specs without a requirements file - nothing a rendered executable
needs may live in a sibling file, since rendered executables are relocatable.
"""

import pathlib
import string
import tomllib
from dataclasses import dataclass, field

# The dotslash platform strings toolshed targets. Every dotslash tool must cover
# all four: one rendered file has to work on every target, and dotslash picks the
# entry at run time.
PLATFORMS = ("macos-aarch64", "macos-x86_64", "linux-aarch64", "linux-x86_64")

_BASE_TOOL_KEYS = frozenset({"method"})
_RUNNER_TOOL_KEYS = _BASE_TOOL_KEYS | {"requirement", "requirements"}
_METHOD_KEYS = {
    "dotslash": _BASE_TOOL_KEYS
    | {"version", "url", "format", "archive_path", "platforms"},
    "uv-run": _RUNNER_TOOL_KEYS | {"module", "args"},
    # bun resolves its own dependencies -- from the entry's package.json, or from
    # the `bun x` package spec -- so it takes no requirements of ours.
    "bun-run": _BASE_TOOL_KEYS | {"entry", "package"},
    "passthrough": _BASE_TOOL_KEYS,
}
_GROUP_KEYS = frozenset({"packages", "requirements", "override_env"})


class ManifestError(Exception):
    """A manifest is malformed, inconsistent, or references something absent."""


def _substitute(template: str, values: dict[str, str], what: str) -> str:
    names = {
        name for _, name, _, _ in string.Formatter().parse(template) if name is not None
    }
    missing = sorted(names - values.keys())
    if missing:
        raise ManifestError(
            f"{what}: no substitution for {', '.join(missing)} "
            f"(have: {', '.join(sorted(values))})"
        )
    return template.format_map(values)


@dataclass(frozen=True)
class RequirementsGroup:
    """A named, reusable set of dependency specs."""

    name: str
    packages: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    override_env: str | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    method: str

    @property
    def is_rendered(self) -> bool:
        """Whether `render` emits this tool's file, or leaves it hand-written."""
        return True


@dataclass(frozen=True)
class PassthroughTool(Tool):
    """A hand-written executable. Committed as-is; validated but never rendered."""

    @property
    def is_rendered(self) -> bool:
        return False


@dataclass(frozen=True)
class RunnerTool(Tool):
    """A tool that execs a language runner against dependencies from the manifest."""

    requirement: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()

    def _walk(
        self, manifest: "Manifest", group_names: tuple[str, ...], seen: set[str]
    ) -> tuple[list[str], list[tuple[str, tuple[str, ...]]]]:
        specs: list[str] = []
        overridable: list[tuple[str, tuple[str, ...]]] = []
        for group_name in group_names:
            if group_name in seen:
                continue
            seen.add(group_name)
            group = manifest.requirements[group_name]
            if group.override_env is not None:
                overridable.append((group.override_env, group.packages))
                continue
            specs.extend(group.packages)
            nested_specs, nested_overridable = self._walk(
                manifest, group.requirements, seen
            )
            specs.extend(nested_specs)
            overridable.extend(nested_overridable)
        return specs, overridable

    def _resolve(
        self, manifest: "Manifest"
    ) -> tuple[list[str], list[tuple[str, tuple[str, ...]]]]:
        path: set[str] = set()
        self._detect_cycle(manifest, self.requirements, path, ())
        specs, overridable = self._walk(manifest, self.requirements, set())
        ordered: list[str] = []
        for spec in [*self.requirement, *specs]:
            if spec not in ordered:
                ordered.append(spec)
        return ordered, overridable

    def _detect_cycle(
        self,
        manifest: "Manifest",
        group_names: tuple[str, ...],
        active: set[str],
        trail: tuple[str, ...],
    ) -> None:
        for group_name in group_names:
            if group_name in active:
                cycle = " -> ".join([*trail, group_name])
                raise ManifestError(f"tool '{self.name}': requirements cycle: {cycle}")
            active.add(group_name)
            self._detect_cycle(
                manifest,
                manifest.requirements[group_name].requirements,
                active,
                (*trail, group_name),
            )
            active.discard(group_name)

    def resolved_requirements(self, manifest: "Manifest") -> list[str]:
        """Dependency specs to pass unconditionally, inline first then groups.

        Order is preserved and duplicates collapse to their first position, so a
        spec reached by two group paths is passed once.
        """
        return self._resolve(manifest)[0]

    def overridable_requirements(
        self, manifest: "Manifest"
    ) -> list[tuple[str, tuple[str, ...]]]:
        """`(env var, specs)` for each group a caller may redirect at run time.

        The renderer emits these as a conditional rather than a plain `--with`,
        which is how a checkout points a released wrapper at its own source.
        """
        return self._resolve(manifest)[1]


@dataclass(frozen=True)
class UvRunTool(RunnerTool):
    module: str = ""
    # Fixed arguments the module always needs, ahead of the caller's own. Any
    # path here resolves against the working directory, so a tool that uses one
    # is inherently repo-local rather than relocatable.
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class BunRunTool(Tool):
    entry: str | None = None
    package: str | None = None


@dataclass(frozen=True)
class DotslashTool(Tool):
    """A prebuilt binary fetched, verified, and exec'd by the dotslash runtime."""

    version: str = ""
    url: str = ""
    format: str | None = None
    archive_path: str | None = None
    platforms: dict[str, dict[str, str]] = field(default_factory=dict)

    def _values(self, platform: str) -> dict[str, str]:
        return {"version": self.version, **self.platforms[platform]}

    def url_for(self, platform: str) -> str:
        return _substitute(
            self.url, self._values(platform), f"tool '{self.name}' url ({platform})"
        )

    def path_for(self, platform: str) -> str:
        """Path to the binary within the asset.

        For a raw binary (no `format`) dotslash treats this as the filename it
        caches the download under, so the tool's own name is the right default.
        """
        if self.archive_path is None:
            return self.name
        return _substitute(
            self.archive_path,
            self._values(platform),
            f"tool '{self.name}' archive_path ({platform})",
        )


@dataclass(frozen=True)
class Manifest:
    tools: dict[str, Tool]
    requirements: dict[str, RequirementsGroup]

    def dotslash_tools(self) -> list[DotslashTool]:
        return [t for t in self.tools.values() if isinstance(t, DotslashTool)]


def _reject_unknown_keys(table: dict, allowed: frozenset[str], what: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ManifestError(
            f"{what}: unknown key(s) {', '.join(unknown)} "
            f"(allowed: {', '.join(sorted(allowed))})"
        )


def _require_sorted(names: list[str], what: str) -> None:
    if names != sorted(names):
        raise ManifestError(f"{what} must be sorted by name; found {', '.join(names)}")


def _parse_group(name: str, table: dict) -> RequirementsGroup:
    what = f"requirements group '{name}'"
    if not isinstance(table, dict):
        raise ManifestError(f"{what}: expected a table")
    _reject_unknown_keys(table, _GROUP_KEYS, what)
    override_env = table.get("override_env")
    nested = tuple(table.get("requirements", ()))
    if override_env is not None and nested:
        # An override replaces the group's specs wholesale. Letting it also pull
        # in nested groups would make it ambiguous whether those survive the
        # override, so require such a group to be flat.
        raise ManifestError(
            f"{what}: a group with override_env cannot declare requirements; "
            f"list its specs in packages instead"
        )
    return RequirementsGroup(
        name=name,
        packages=tuple(table.get("packages", ())),
        requirements=nested,
        override_env=override_env,
    )


def _parse_dotslash(name: str, table: dict) -> DotslashTool:
    what = f"tool '{name}'"
    for key in ("version", "url"):
        if key not in table:
            raise ManifestError(f"{what}: dotslash method requires '{key}'")

    platforms = table.get("platforms", {})
    unknown = sorted(set(platforms) - set(PLATFORMS))
    if unknown:
        raise ManifestError(
            f"{what}: unknown platform(s) {', '.join(unknown)} "
            f"(expected: {', '.join(PLATFORMS)})"
        )
    absent = [p for p in PLATFORMS if p not in platforms]
    if absent:
        raise ManifestError(f"{what}: missing platform(s) {', '.join(absent)}")

    return DotslashTool(
        name=name,
        method="dotslash",
        version=str(table["version"]),
        url=table["url"],
        format=table.get("format"),
        archive_path=table.get("archive_path"),
        platforms={p: dict(platforms[p]) for p in PLATFORMS},
    )


def _parse_tool(name: str, table: dict) -> Tool:
    what = f"tool '{name}'"
    if not isinstance(table, dict):
        raise ManifestError(f"{what}: expected a table")
    method = table.get("method")
    if method is None:
        raise ManifestError(f"{what}: missing 'method'")
    if method not in _METHOD_KEYS:
        raise ManifestError(
            f"{what}: unknown method '{method}' "
            f"(known: {', '.join(sorted(_METHOD_KEYS))})"
        )
    _reject_unknown_keys(table, frozenset(_METHOD_KEYS[method]), what)

    if method == "dotslash":
        return _parse_dotslash(name, table)

    if method == "passthrough":
        return PassthroughTool(name=name, method=method)

    if method == "uv-run":
        if "module" not in table:
            raise ManifestError(f"{what}: uv-run method requires 'module'")
        return UvRunTool(
            name=name,
            method=method,
            requirement=tuple(table.get("requirement", ())),
            requirements=tuple(table.get("requirements", ())),
            module=table["module"],
            args=tuple(table.get("args", ())),
        )

    entry, package = table.get("entry"), table.get("package")
    if (entry is None) == (package is None):
        raise ManifestError(
            f"{what}: bun-run method requires exactly one of 'entry' or 'package'"
        )
    return BunRunTool(name=name, method=method, entry=entry, package=package)


def parse_manifest(text: str) -> Manifest:
    data = tomllib.loads(text)
    _reject_unknown_keys(data, frozenset({"tool", "requirements"}), "manifest")

    group_tables = data.get("requirements", {})
    _require_sorted(list(group_tables), "requirements groups")
    requirements = {
        name: _parse_group(name, table) for name, table in group_tables.items()
    }

    tool_tables = data.get("tool", {})
    _require_sorted(list(tool_tables), "tools")
    tools = {name: _parse_tool(name, table) for name, table in tool_tables.items()}

    for name, group in requirements.items():
        for nested in group.requirements:
            if nested not in requirements:
                raise ManifestError(
                    f"requirements group '{name}': undefined group '{nested}'"
                )
    for tool in tools.values():
        if isinstance(tool, RunnerTool):
            for group_name in tool.requirements:
                if group_name not in requirements:
                    raise ManifestError(
                        f"tool '{tool.name}': undefined requirements "
                        f"group '{group_name}'"
                    )

    return Manifest(tools=tools, requirements=requirements)


def load_manifest(path: pathlib.Path) -> Manifest:
    try:
        return parse_manifest(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{path}: {e}") from e
