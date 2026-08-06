"""Check a dotslash tool's upstream GitHub releases for a newer version.

`render update` is the only caller; this module has no knowledge of pinning or
of `toolshed.toml` on disk. It answers one question -- "what versions does
upstream offer, and which is newest?" -- from the tool's `url` template alone,
per D5's one-line-bump goal: no `[tool.<name>.update]` schema key is added to
answer it.
"""

import json
import os
import re
import urllib.parse
from dataclasses import dataclass

from toolshed.fetch import fetch
from toolshed.manifest import DotslashTool, ManifestError

_RELEASES_URL = r"https://api.github.com/repos/{owner}/{repo}/releases?per_page=100"
_ASSET_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/releases/download/(?P<rest>.+)$"
)


@dataclass(frozen=True)
class Unsupported:
    """A tool whose upstream cannot be checked, and why."""

    reason: str


@dataclass(frozen=True)
class Source:
    """The GitHub repo and release-tag template a tool's `url` implies."""

    owner: str
    repo: str
    tag_template: str  # e.g. "v{version}", with `{version}` decoded from the URL.


def discover_source(tool: DotslashTool) -> Source | Unsupported:
    r"""Derive the GitHub owner/repo/tag-template a tool's `url` implies.

    The asset filename (the final path segment) never contains a `/`, so
    whatever precedes it in the `releases/download/` path is the release tag,
    still percent-encoded the way it appears in the URL. Percent-decoding it is
    what turns biome's `%40biomejs/biome%40{version}` into
    `@biomejs/biome@{version}` -- the form the releases API reports as
    `tag_name`.
    """
    match = _ASSET_URL_RE.match(tool.url)
    if match is None:
        return Unsupported("url is not a github release asset")

    rest = match.group("rest")
    if "/" not in rest:
        return Unsupported("url has no asset path segment")
    tag_template, _asset = rest.rsplit("/", 1)
    tag_template = urllib.parse.unquote(tag_template)

    if r"{version}" not in tag_template:
        return Unsupported(r"release tag has no {version}")
    other_placeholders = set(re.findall(r"{(\w+)}", tag_template)) - {"version"}
    if other_placeholders:
        return Unsupported(
            f"release tag has per-platform placeholder(s) "
            f"{', '.join(sorted(other_placeholders))}"
        )

    return Source(
        owner=match.group("owner"), repo=match.group("repo"), tag_template=tag_template
    )


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _tag_pattern(tag_template: str) -> re.Pattern[str]:
    """A regex that matches a tag against its template, capturing `version`."""
    parts = tag_template.split(r"{version}")
    escaped = [re.escape(part) for part in parts]
    return re.compile("^" + "(?P<version>.+)".join(escaped) + "$")


def discover_versions(source: Source) -> list[str]:
    """Every release version upstream reports that matches `source.tag_template`.

    Drafts and prereleases are dropped before matching: a draft has no tag to
    match on, and prerelease filtering is `latest_version`'s job (it needs the
    caller's `--allow-prerelease` choice), not this function's.
    """
    url = _RELEASES_URL.format(owner=source.owner, repo=source.repo)
    data = fetch(url, headers=_auth_headers())
    releases = json.loads(data)

    pattern = _tag_pattern(source.tag_template)
    versions = []
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        found = pattern.match(tag)
        if found:
            versions.append(found.group("version"))
    return versions


def _is_prerelease(version: str) -> bool:
    return any(not segment.isdigit() for segment in version.split("."))


def _version_key(version: str) -> tuple[int, ...]:
    """A comparable key: the integer segments split on `.`.

    A non-numeric segment (e.g. the `12-canary` in `1.3.12-canary`) contributes
    its leading digits, so a prerelease still orders sensibly relative to the
    version it precedes -- `_is_prerelease` is what decides whether it is
    offered at all.
    """
    key = []
    for segment in version.split("."):
        found = re.match(r"\d+", segment)
        key.append(int(found.group()) if found else 0)
    return tuple(key)


def latest_version(
    candidates: list[str], current: str, allow_prerelease: bool = False
) -> str | None:
    """The newest candidate that exceeds `current`, or None if none does.

    Comparison is on integer segments split at `.`, not lexical, so `3.9.0` <
    `3.13.1`. A candidate with any non-numeric segment (e.g. `1.3.12-canary`)
    is a prerelease and is dropped unless `allow_prerelease` is set.
    """
    current_key = _version_key(current)
    best: tuple[tuple[int, ...], str] | None = None
    for candidate in candidates:
        if _is_prerelease(candidate) and not allow_prerelease:
            continue
        key = _version_key(candidate)
        if key <= current_key:
            continue
        if best is None or key > best[0]:
            best = (key, candidate)
    return best[1] if best is not None else None


def rewrite_version(text: str, tool_name: str, version: str) -> str:
    """Replace `version = "..."` in `[tool.<tool_name>]` with `version`.

    A surgical text edit rather than a TOML round-trip: `tomllib` cannot write,
    and a writer would discard the comments and taplo formatting that
    `validate` then demands back.
    """
    header_re = re.compile(rf"^\[tool\.{re.escape(tool_name)}\]\n", re.MULTILINE)
    header_match = header_re.search(text)
    if header_match is None:
        raise ManifestError(f"toolshed.toml: no [tool.{tool_name}] table")

    section_start = header_match.end()
    next_header = re.search(r"^\[", text[section_start:], re.MULTILINE)
    section_end = (
        len(text) if next_header is None else section_start + next_header.start()
    )
    section = text[section_start:section_end]

    version_re = re.compile(r'^version\s*=\s*"[^"]*"', re.MULTILINE)
    found = version_re.search(section)
    if found is None:
        raise ManifestError(f"toolshed.toml: [tool.{tool_name}] has no 'version' key")

    new_line = f'version = "{version}"'
    new_section = section[: found.start()] + new_line + section[found.end() :]
    return text[:section_start] + new_section + text[section_end:]
