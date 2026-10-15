"""Unit tests for grouping sink inputs into applications."""

from __future__ import annotations

import unittest

from appvol.apps import group_streams, identity, label_of
from appvol.match import Stream


def stream(index: int, volume=(0.5, 0.5), mute: bool = False, **props: str) -> Stream:
    props = {key: str(value) for key, value in props.items()}
    return Stream(
        index=index,
        props=props,
        label=props.get("application.name", f"stream {index}"),
        volume=tuple(volume),
        mute=mute,
    )


SPOTIFY_PROPS = {"application.name": "Spotify", "application.process.binary": "spotify"}
FIREFOX_PROPS = {"application.name": "Firefox", "application.process.binary": "firefox"}

SPOTIFY = stream(1, volume=(0.15, 0.15), **SPOTIFY_PROPS)
FIREFOX_TAB_A = stream(2, volume=(0.6, 0.6), **FIREFOX_PROPS)
FIREFOX_TAB_B = stream(3, volume=(1.0, 1.0), **FIREFOX_PROPS)
PLASMA = stream(4, volume=(0.3, 0.3), **{"application.name": "plasmashell"})


class IdentityTests(unittest.TestCase):
    def test_the_first_known_identifier_wins(self) -> None:
        self.assertEqual(identity(SPOTIFY), "spotify")
        props = {"application.id": "org.mozilla.firefox", "application.name": "Firefox"}
        self.assertEqual(identity(stream(9, **props)), "org.mozilla.firefox")

    def test_the_desktop_suffix_is_dropped(self) -> None:
        self.assertEqual(identity(stream(9, **{"application.name": "Spotify.desktop"})), "spotify")

    def test_a_stream_without_identifiers_falls_back_to_its_index(self) -> None:
        self.assertEqual(identity(stream(7)), "stream-7")

    def test_label_prefers_application_name(self) -> None:
        self.assertEqual(label_of(SPOTIFY), "Spotify")
        self.assertEqual(label_of(stream(7)), "stream 7")


class GroupTests(unittest.TestCase):
    def test_streams_of_one_application_become_one_entry(self) -> None:
        applications = group_streams([FIREFOX_TAB_A, SPOTIFY, FIREFOX_TAB_B])
        self.assertEqual([application.key for application in applications], ["firefox", "spotify"])
        firefox = applications[0]
        self.assertEqual(firefox.label, "Firefox")
        self.assertEqual(firefox.indices, (2, 3))
        self.assertEqual(firefox.percent, 100)

    def test_the_percent_is_the_loudest_stream(self) -> None:
        applications = group_streams([SPOTIFY, FIREFOX_TAB_A])
        self.assertEqual([application.percent for application in applications], [60, 15])

    def test_an_application_is_muted_only_when_all_of_its_streams_are(self) -> None:
        half = [stream(1, mute=True, **FIREFOX_PROPS), FIREFOX_TAB_B]
        self.assertFalse(group_streams(half)[0].muted)

        whole = [stream(1, mute=True, **FIREFOX_PROPS), stream(2, mute=True, **FIREFOX_PROPS)]
        self.assertTrue(group_streams(whole)[0].muted)

    def test_the_shell_sorts_last_and_is_flagged(self) -> None:
        applications = group_streams([SPOTIFY, PLASMA])
        self.assertEqual([application.key for application in applications], ["spotify", "plasmashell"])
        self.assertTrue(applications[1].panel)
        self.assertFalse(applications[0].panel)

    def test_variants_are_merged(self) -> None:
        applications = group_streams(
            [
                stream(1, **{"application.name": "Firefox"}),
                stream(2, **{"application.id": "org.mozilla.firefox"}),
            ]
        )
        self.assertEqual(applications[0].variants, frozenset({"firefox", "org.mozilla.firefox"}))
        self.assertIn("firefox", applications[0].summary()["variants"])

    def test_no_streams(self) -> None:
        self.assertEqual(group_streams([]), ())


if __name__ == "__main__":
    unittest.main()
