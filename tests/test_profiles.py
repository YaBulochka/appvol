"""Unit tests for profiles: the model, the file format and the stream matcher."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from appvol.match import Stream
from appvol.profiles import (
    ACTIVE_ID,
    MODE_FOCUS,
    OSD_NAME_AUTO,
    OSD_NAME_NEVER,
    STEP_PROFILE,
    Profile,
    ProfileSelection,
    action_name,
    active_profile,
    dumps,
    find,
    is_panel_stream,
    load,
    match_profile,
    parse,
    profile_from_action,
    replace_step,
    save,
    validate_id,
)


def stream(index: int, **props: str) -> Stream:
    props = {key: str(value) for key, value in props.items()}
    return Stream(index=index, props=props, label=props.get("application.name", f"stream {index}"))


SPOTIFY = stream(1, **{"application.name": "Spotify", "application.process.binary": "spotify"})
FIREFOX = stream(2, **{"application.id": "org.mozilla.firefox"})
PLASMA = stream(3, **{"application.name": "plasmashell"})
CS2 = stream(4, **{"application.name": "cs2", "application.process.binary": "cs2"})


class IdTests(unittest.TestCase):
    def test_ids_are_lowercased_and_dots_are_allowed(self) -> None:
        self.assertEqual(validate_id("  Spotify  "), "spotify")
        self.assertEqual(validate_id("cs2.game"), "cs2.game")

    def test_rejected_ids(self) -> None:
        for value in ("", "a b", "-leading", ".dot", "x" * 41, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_id(value)

    def test_active_is_reserved(self) -> None:
        with self.assertRaises(ValueError):
            validate_id(ACTIVE_ID)


class ActiveProfileTests(unittest.TestCase):
    def test_active_profile_follows_the_focus_and_hides_the_name(self) -> None:
        profile = active_profile()
        self.assertEqual(profile.id, ACTIVE_ID)
        self.assertEqual(profile.mode, MODE_FOCUS)
        self.assertFalse(profile.shows_name)

    def test_stream_profiles_show_their_name_by_default(self) -> None:
        self.assertTrue(Profile(id="spotify").shows_name)
        self.assertFalse(Profile(id="spotify", osd_name=OSD_NAME_NEVER).shows_name)

    def test_display_name_falls_back_to_the_id(self) -> None:
        self.assertEqual(Profile(id="spotify").display_name, "spotify")
        self.assertEqual(Profile(id="spotify", name="Spotify").display_name, "Spotify")


class ActionNameTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        self.assertEqual(action_name("cs2"), "profile_cs2")
        self.assertEqual(profile_from_action("profile_cs2"), "cs2")

    def test_foreign_actions_are_ignored(self) -> None:
        self.assertEqual(profile_from_action("mute"), "")
        self.assertEqual(profile_from_action(""), "")


class ParseTests(unittest.TestCase):
    def test_minimal_profile(self) -> None:
        profiles = parse('[[profile]]\nid = "spotify"\n')
        self.assertEqual(len(profiles), 1)
        profile = profiles[0]
        self.assertEqual(profile.id, "spotify")
        self.assertEqual(profile.mode, "streams")
        self.assertEqual(profile.include, ())
        self.assertEqual(profile.exclude, ())
        self.assertIsNone(profile.step)
        self.assertEqual(profile.display_name, "spotify")

    def test_full_profile(self) -> None:
        text = """
[[profile]]
id = "cs2"
name = "Counter-Strike"
mode = "streams"
include = ["cs2", "steam"]
exclude = ["discord"]
step = 2.5
max_volume = 120
icon = "input-gaming"
osd_name = "always"
"""
        profile = parse(text)[0]
        self.assertEqual(profile.name, "Counter-Strike")
        self.assertEqual(profile.include, ("cs2", "steam"))
        self.assertEqual(profile.exclude, ("discord",))
        self.assertEqual(profile.step, 2.5)
        self.assertEqual(profile.max_volume, 120.0)
        self.assertEqual(profile.icon, "input-gaming")
        self.assertTrue(profile.shows_name)

    def test_a_single_table_is_accepted(self) -> None:
        self.assertEqual(len(parse('[profile]\nid = "spotify"\n')), 1)

    def test_include_accepts_a_bare_string(self) -> None:
        self.assertEqual(parse('[[profile]]\nid = "x"\ninclude = "spotify"\n')[0].include, ("spotify",))

    def test_broken_toml_yields_no_profiles(self) -> None:
        self.assertEqual(parse("[[profile]\nid = "), [])

    def test_entries_without_a_usable_id_are_skipped(self) -> None:
        text = '[[profile]]\nid = "a b"\n\n[[profile]]\nname = "no id"\n\nprofile = 3\n'
        self.assertEqual(parse(text), [])

    def test_duplicate_ids_keep_the_first_entry(self) -> None:
        text = '[[profile]]\nid = "x"\nname = "first"\n\n[[profile]]\nid = "x"\nname = "second"\n'
        profiles = parse(text)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0].name, "first")

    def test_unknown_choices_fall_back(self) -> None:
        profile = parse('[[profile]]\nid = "x"\nmode = "magic"\nosd_name = "maybe"\n')[0]
        self.assertEqual(profile.mode, "streams")
        self.assertEqual(profile.osd_name, OSD_NAME_AUTO)

    def test_unusable_numbers_are_dropped(self) -> None:
        profile = parse('[[profile]]\nid = "x"\nstep = -1\nmax_volume = "loud"\n')[0]
        self.assertIsNone(profile.step)
        self.assertIsNone(profile.max_volume)

    def test_max_volume_is_clamped(self) -> None:
        self.assertEqual(parse('[[profile]]\nid = "x"\nmax_volume = 400\n')[0].max_volume, 150.0)

    def test_non_string_include_entries_are_dropped(self) -> None:
        profile = parse('[[profile]]\nid = "x"\ninclude = ["spotify", 3]\n')[0]
        self.assertEqual(profile.include, ("spotify",))

    def test_find(self) -> None:
        profiles = parse('[[profile]]\nid = "x"\n')
        self.assertIsNotNone(find(profiles, "x"))
        self.assertIsNone(find(profiles, "y"))


class DumpTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        profiles = [
            Profile(id="spotify", name='Spot "ify"', include=("spotify",), step=2.0),
            Profile(id="cs2", include=(), exclude=("discord",), osd_name=OSD_NAME_NEVER),
        ]
        self.assertEqual(parse(dumps(profiles)), profiles)

    def test_empty_output_is_a_comment_only(self) -> None:
        self.assertEqual(parse(dumps([])), [])

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "profiles.toml"
            profiles, profile = [Profile(id="spotify", include=("spotify",))], Profile(id="spotify", include=("spotify",))
            self.assertEqual(save(profiles, path), path)
            self.assertEqual(load(path), [profile])
            self.assertFalse((path.parent / "profiles.toml.tmp").exists())

    def test_load_without_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load(Path(directory) / "profiles.toml"), [])


class StepTests(unittest.TestCase):
    """Changing one profile's step, as the row of the window does."""

    PROFILES = [Profile(id="spotify", name="Spotify", step=2.0), Profile(id="cs2", step=10.0)]

    def test_only_the_named_profile_changes(self) -> None:
        profiles = replace_step(self.PROFILES, "spotify", 7.0)
        self.assertEqual([profile.step for profile in profiles], [7.0, 10.0])

    def test_a_zero_step_clears_the_override(self) -> None:
        profiles = replace_step(self.PROFILES, "spotify", 0.0)
        self.assertIsNone(profiles[0].step)
        self.assertEqual(profiles[1].step, 10.0)

    def test_an_unknown_id_keeps_every_profile(self) -> None:
        self.assertEqual(replace_step(self.PROFILES, "discord", 5.0), self.PROFILES)

    def test_the_original_list_is_left_alone(self) -> None:
        replace_step(self.PROFILES, "spotify", 7.0)
        self.assertEqual(self.PROFILES[0].step, 2.0)


class PanelFilterTests(unittest.TestCase):
    def test_the_shell_is_recognised(self) -> None:
        self.assertTrue(is_panel_stream(PLASMA))
        self.assertTrue(is_panel_stream(stream(5, **{"application.name": "Event Sounds"})))

    def test_applications_are_not(self) -> None:
        self.assertFalse(is_panel_stream(SPOTIFY))


class MatchTests(unittest.TestCase):
    def test_include_selects_the_application(self) -> None:
        profile = Profile(id="spotify", include=("spotify",))
        result = match_profile(profile, [SPOTIFY, FIREFOX])
        self.assertEqual(result.indices, (1,))
        self.assertEqual(result.step, STEP_PROFILE)
        self.assertIn("spotify", result.reason)

    def test_include_matches_reverse_dns_ids(self) -> None:
        profile = Profile(id="browser", include=("firefox",))
        self.assertEqual(match_profile(profile, [FIREFOX]).indices, (2,))

    def test_empty_include_means_every_application(self) -> None:
        profile = Profile(id="everything")
        result = match_profile(profile, [SPOTIFY, FIREFOX, PLASMA])
        self.assertEqual(result.indices, (1, 2))
        self.assertIn("every application stream", result.reason)

    def test_exclude_makes_an_inversion_profile(self) -> None:
        profile = Profile(id="desktop", exclude=("cs2",))
        result = match_profile(profile, [SPOTIFY, CS2, PLASMA])
        self.assertEqual(result.indices, (1,))
        self.assertIn("without cs2", result.reason)

    def test_an_explicit_include_reaches_the_shell(self) -> None:
        profile = Profile(id="shell", include=("plasmashell",))
        self.assertEqual(match_profile(profile, [SPOTIFY, PLASMA]).indices, (3,))

    def test_a_profile_that_matches_nothing_says_so(self) -> None:
        result = match_profile(Profile(id="spotify", include=("spotify",)), [FIREFOX])
        self.assertFalse(result.matched)
        self.assertIn("no stream matched", result.reason)

    def test_no_streams_at_all(self) -> None:
        result = match_profile(Profile(id="everything"), [])
        self.assertIn("no audio stream is playing", result.reason)


class SelectionTests(unittest.TestCase):
    def test_toggle_switches_and_switches_back(self) -> None:
        selection = ProfileSelection()
        self.assertEqual(selection.toggle("spotify", 10.0), "spotify")
        self.assertEqual(selection.current, "spotify")
        self.assertEqual(selection.toggle("spotify", 20.0), ACTIVE_ID)

    def test_toggle_between_profiles_switches_directly(self) -> None:
        selection = ProfileSelection()
        selection.toggle("spotify", 1.0)
        self.assertEqual(selection.toggle("cs2", 2.0), "cs2")

    def test_expire_returns_to_active_after_the_timeout(self) -> None:
        selection = ProfileSelection()
        selection.toggle("spotify", 100.0)
        self.assertFalse(selection.expire(200.0, 300.0))
        self.assertEqual(selection.current, "spotify")
        self.assertTrue(selection.expire(400.0, 300.0))
        self.assertEqual(selection.current, ACTIVE_ID)

    def test_using_the_profile_pushes_the_timeout_away(self) -> None:
        selection = ProfileSelection()
        selection.toggle("spotify", 100.0)
        selection.use(500.0)
        self.assertFalse(selection.expire(600.0, 300.0))

    def test_a_zero_timeout_never_expires(self) -> None:
        selection = ProfileSelection()
        selection.toggle("spotify", 0.0)
        self.assertFalse(selection.expire(10_000.0, 0.0))
        self.assertEqual(selection.current, "spotify")

    def test_active_never_expires(self) -> None:
        self.assertFalse(ProfileSelection().expire(10_000.0, 300.0))


if __name__ == "__main__":
    unittest.main()
