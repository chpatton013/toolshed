"""Resolve every dotslash asset and record its size and blake3 digest.

This is the one step that needs network and a trusted machine: it decides what
bytes every consumer will subsequently execute. Run it deliberately and review
the `tools.lock.toml` diff.
"""

import pathlib
import sys
import urllib.error
import urllib.request

from toolshed.lock import PlatformPin, load_lock
from toolshed.manifest import PLATFORMS, DotslashTool, Manifest, ManifestError

_TIMEOUT_S = 300


def digest_bytes(data: bytes) -> str:
    try:
        from blake3 import blake3
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise ManifestError(
            "pinning needs the blake3 package; install toolshed[pin]"
        ) from e
    return blake3(data).hexdigest()


def _fetch(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as e:
        raise ManifestError(f"could not fetch {url}: {e}") from e


def pin_platform(tool: DotslashTool, platform: str) -> PlatformPin:
    """Download one platform's asset and identify it.

    The digest covers the asset exactly as served -- the archive, not the binary
    inside it -- because that is what dotslash verifies before unpacking.
    """
    data = _fetch(tool.url_for(platform))
    return PlatformPin(size=len(data), digest=digest_bytes(data))


def pin_tools(
    manifest: Manifest, lock_path: pathlib.Path, tool_names: list[str]
) -> int:
    """Pin the named tools, or every dotslash tool when none are named."""
    candidates = {t.name: t for t in manifest.dotslash_tools()}
    if tool_names:
        unknown = sorted(set(tool_names) - candidates.keys())
        if unknown:
            raise ManifestError(
                f"not dotslash tool(s) in the manifest: {', '.join(unknown)}"
            )
        selected = [candidates[name] for name in tool_names]
    else:
        selected = list(candidates.values())

    lock = load_lock(lock_path).restricted_to(set(candidates))
    for tool in selected:
        for platform in PLATFORMS:
            pin = pin_platform(tool, platform)
            previous = lock.get(tool.name, platform)
            lock = lock.with_pin(tool.name, platform, pin)
            if previous is None:
                state = "pinned"
            elif previous.digest != pin.digest:
                state = f"repinned (was {previous.digest[:12]})"
            else:
                state = "unchanged"
            print(f"{tool.name} {platform}: {pin.digest[:12]} {pin.size} {state}")

    lock_path.write_text(lock.dumps())
    print(f"wrote {lock_path}", file=sys.stderr)
    return 0
