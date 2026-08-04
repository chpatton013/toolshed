import unittest

from toolshed.lock import Lock, PlatformPin, parse_lock
from toolshed.manifest import PLATFORMS, ManifestError


def _full_pins(tool: str) -> Lock:
    return Lock({tool: {p: PlatformPin(size=1, digest="ab") for p in PLATFORMS}})


class Pinning(unittest.TestCase):
    def test_a_tool_with_all_four_platforms_is_pinned(self):
        self.assertTrue(_full_pins("uv").is_pinned("uv"))
        self.assertEqual([], _full_pins("uv").missing_platforms("uv"))

    def test_a_tool_missing_a_platform_is_not_pinned(self):
        lock = Lock(
            {"uv": {p: PlatformPin(size=1, digest="ab") for p in PLATFORMS[:3]}}
        )

        self.assertFalse(lock.is_pinned("uv"))
        self.assertEqual(["linux-x86_64"], lock.missing_platforms("uv"))

    def test_an_absent_tool_is_not_pinned(self):
        self.assertFalse(Lock({}).is_pinned("uv"))
        self.assertEqual(list(PLATFORMS), Lock({}).missing_platforms("uv"))


class RoundTrip(unittest.TestCase):
    def test_a_dumped_lock_parses_back_to_the_same_pins(self):
        original = Lock(
            {
                "uv": {p: PlatformPin(size=i, digest=f"{i:064x}")
                       for i, p in enumerate(PLATFORMS)},
                "jq": {p: PlatformPin(size=9, digest="f" * 64) for p in PLATFORMS},
            }
        )

        reparsed = parse_lock(original.dumps())

        for tool in ("uv", "jq"):
            for platform in PLATFORMS:
                self.assertEqual(
                    original.get(tool, platform), reparsed.get(tool, platform)
                )

    def test_dumping_is_stable_regardless_of_insertion_order(self):
        """`render pin` must not produce a churning diff."""
        forward = Lock(
            {
                "aaa": {p: PlatformPin(size=1, digest="a") for p in PLATFORMS},
                "zzz": {p: PlatformPin(size=2, digest="z") for p in PLATFORMS},
            }
        )
        backward = Lock(
            {
                "zzz": {p: PlatformPin(size=2, digest="z") for p in reversed(PLATFORMS)},
                "aaa": {p: PlatformPin(size=1, digest="a") for p in reversed(PLATFORMS)},
            }
        )

        self.assertEqual(forward.dumps(), backward.dumps())

    def test_a_tool_name_with_a_dash_survives_the_round_trip(self):
        lock = Lock({"pre-commit": {p: PlatformPin(1, "a") for p in PLATFORMS}})

        self.assertTrue(parse_lock(lock.dumps()).is_pinned("pre-commit"))


class Errors(unittest.TestCase):
    def test_an_unknown_platform_in_the_lock_is_rejected(self):
        with self.assertRaisesRegex(ManifestError, "freebsd-x86_64"):
            parse_lock('[tool.uv.freebsd-x86_64]\nsize = 1\ndigest = "a"\n')

    def test_a_pin_missing_its_digest_is_rejected(self):
        with self.assertRaisesRegex(ManifestError, "digest"):
            parse_lock("[tool.uv.macos-aarch64]\nsize = 1\n")


class Restriction(unittest.TestCase):
    def test_pins_for_undeclared_tools_are_dropped(self):
        lock = Lock(
            {
                "uv": {p: PlatformPin(1, "a") for p in PLATFORMS},
                "gone": {p: PlatformPin(1, "a") for p in PLATFORMS},
            }
        )

        restricted = lock.restricted_to({"uv"})

        self.assertTrue(restricted.is_pinned("uv"))
        self.assertFalse(restricted.is_pinned("gone"))


if __name__ == "__main__":
    unittest.main()
