"""Pinning tests.

The cross-check against chiiiirrus is the point of this file. Those digests were
maintained by hand in a different repo and are known to run, so reproducing them
byte-for-byte proves our hashing and our URL substitution are both right. A
disagreement means this code is wrong -- investigate before assuming upstream
moved.
"""

import os
import unittest

from toolshed.manifest import parse_manifest
from toolshed.pin import pin_platform

_NETWORK = os.environ.get("TOOLSHED_TEST_NETWORK") == "1"

# tool name -> (manifest text, platform, expected size, expected blake3 digest)
_KNOWN_GOOD = {
    "shfmt": (
        r"""
        [tool.shfmt]
        method = "dotslash"
        version = "3.13.1"
        url = "https://github.com/mvdan/sh/releases/download/v{version}/shfmt_v{version}_{asset}"
        [tool.shfmt.platforms]
        macos-aarch64 = { asset = "darwin_arm64" }
        macos-x86_64 = { asset = "darwin_amd64" }
        linux-aarch64 = { asset = "linux_arm64" }
        linux-x86_64 = { asset = "linux_amd64" }
        """,
        "macos-aarch64",
        2975650,
        "b205ddbbbae9aeed80f89f12b9d4c200a47bcafe8d9c3e56e8ef1f8a2a1af31e",
    ),
    "uv": (
        r"""
        [tool.uv]
        method = "dotslash"
        version = "0.11.7"
        url = "https://github.com/astral-sh/uv/releases/download/{version}/uv-{triple}.tar.gz"
        format = "tar.gz"
        archive_path = "uv-{triple}/uv"
        [tool.uv.platforms]
        macos-aarch64 = { triple = "aarch64-apple-darwin" }
        macos-x86_64 = { triple = "x86_64-apple-darwin" }
        linux-aarch64 = { triple = "aarch64-unknown-linux-musl" }
        linux-x86_64 = { triple = "x86_64-unknown-linux-musl" }
        """,
        "macos-aarch64",
        20839135,
        "fe05177d55ebc6455da370ac23ee9663ee970de73ea933b0f14d0668a5f7cadf",
    ),
}


@unittest.skipUnless(_NETWORK, "set TOOLSHED_TEST_NETWORK=1 to download assets")
class DigestsMatchKnownGoodValues(unittest.TestCase):
    def _assert_matches(self, tool_name: str) -> None:
        text, platform, size, digest = _KNOWN_GOOD[tool_name]
        tool = parse_manifest(text).tools[tool_name]

        pin = pin_platform(tool, platform)

        self.assertEqual(size, pin.size)
        self.assertEqual(digest, pin.digest)

    def test_a_raw_binary_asset_hashes_to_the_known_digest(self):
        self._assert_matches("shfmt")

    def test_an_archived_asset_hashes_to_the_known_digest(self):
        """The digest covers the archive as downloaded, not its contents."""
        self._assert_matches("uv")


class Hashing(unittest.TestCase):
    def test_the_digest_is_blake3_of_the_raw_bytes(self):
        from toolshed.pin import digest_bytes

        # blake3 of the empty input, per the reference implementation's vectors.
        self.assertEqual(
            "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262",
            digest_bytes(b""),
        )


if __name__ == "__main__":
    unittest.main()
