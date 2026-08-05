"""The one urllib call every network-touching module in toolshed goes through."""

import urllib.error
import urllib.request

from toolshed.manifest import ManifestError

_TIMEOUT_S = 300


def fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as e:
        raise ManifestError(f"could not fetch {url}: {e}") from e
