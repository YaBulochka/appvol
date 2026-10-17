"""Unit tests for grouping sink inputs into applications."""

from __future__ import annotations

import unittest

from appvol.apps import (
    application_profile,
    group_streams,
    identity,
    in_appearance_order,
    label_of,
    matching_applications,
)
from appvol.match import Stream
from appvol.profiles import Profile, match_profile


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


class AutoTargetTests(unittest.TestCase):
    """The targets the auto mode builds from the applications."""

    def test_a_target_names_the_application_and_prefixes_its_id(self) -> None:
        profile = application_profile(group_streams([SPOTIFY])[0])

        self.assertEqual(profile.id, "app-spotify")
        self.assertEqual(profile.name, "Spotify")
        self.assertEqual(profile.mode, "streams")
        self.assertIn("spotify", profile.include)

    def test_a_target_follows_the_global_step_and_ceiling(self) -> None:
        profile = application_profile(group_streams([SPOTIFY])[0])

        self.assertIsNone(profile.step)
        self.assertIsNone(profile.max_volume)

    def test_a_target_selects_the_streams_of_its_application_only(self) -> None:
        firefox = application_profile(group_streams([FIREFOX_TAB_A, FIREFOX_TAB_B])[0])

        result = match_profile(firefox, [SPOTIFY, FIREFOX_TAB_A, FIREFOX_TAB_B])

        self.assertEqual(result.indices, (2, 3))

    def test_the_cycle_follows_the_first_stream_not_the_label(self) -> None:
        applications = group_streams([SPOTIFY, FIREFOX_TAB_A])

        # The editor sorts by label, the cycle by the stream that started the
        # application, and Spotify started first.
        self.assertEqual([item.key for item in applications], ["firefox", "spotify"])
        self.assertEqual(
            [item.key for item in in_appearance_order(applications)], ["spotify", "firefox"]
        )

    def test_an_application_that_restarted_moves_to_the_end(self) -> None:
        restarted = group_streams([stream(9, **SPOTIFY_PROPS), FIREFOX_TAB_A])

        self.assertEqual(
            [item.key for item in in_appearance_order(restarted)], ["firefox", "spotify"]
        )


class MatchingApplicationsTests(unittest.TestCase):
    """The application view of a match, used by the editor's live line."""

    def applications(self):
        return group_streams([SPOTIFY, FIREFOX_TAB_A, FIREFOX_TAB_B, PLASMA])

    def test_an_empty_include_takes_every_application_but_the_shell(self) -> None:
        matched = matching_applications(Profile(id="p"), self.applications())
        self.assertEqual([application.label for application in matched], ["Firefox", "Spotify"])

    def test_an_include_selects_the_named_application(self) -> None:
        matched = matching_applications(Profile(id="p", include=("spotify",)), self.applications())
        self.assertEqual([application.label for application in matched], ["Spotify"])

    def test_an_exclude_removes_the_named_application(self) -> None:
        matched = matching_applications(Profile(id="p", exclude=("firefox",)), self.applications())
        self.assertEqual([application.label for application in matched], ["Spotify"])

    def test_a_shell_stream_can_be_included_explicitly(self) -> None:
        matched = matching_applications(
            Profile(id="p", include=("plasmashell",)), self.applications()
        )
        self.assertEqual([application.label for application in matched], ["plasmashell"])

    def test_the_count_matches_the_streams_of_the_groups(self) -> None:
        matched = matching_applications(Profile(id="p", include=("firefox",)), self.applications())
        self.assertEqual(sum(len(application.indices) for application in matched), 2)

    def test_nothing_playing_matches_nothing(self) -> None:
        self.assertEqual(matching_applications(Profile(id="p"), ()), ())


if __name__ == "__main__":
    unittest.main()
