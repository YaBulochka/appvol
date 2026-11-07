"""Unit tests for the client: argument parsing and the readable answers."""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from appvol.cli import (
    _print_applications,
    _print_list,
    _print_mode,
    _print_profiles,
    _profile,
    _short,
    build_parser,
)


class ParserTests(unittest.TestCase):
    def test_up_takes_a_step_and_a_profile(self) -> None:
        args = build_parser().parse_args(["up", "--step", "2.5", "--profile", "spotify"])
        self.assertEqual((args.command, args.step, args.profile), ("up", 2.5, "spotify"))

    def test_up_defaults_to_the_profile_step_and_the_current_profile(self) -> None:
        args = build_parser().parse_args(["up"])
        self.assertIsNone(args.step)
        self.assertEqual(args.profile, "")

    def test_mute_takes_a_profile(self) -> None:
        self.assertEqual(build_parser().parse_args(["mute", "--profile", "cs2"]).profile, "cs2")

    def test_apps_takes_no_arguments(self) -> None:
        self.assertEqual(build_parser().parse_args(["apps"]).command, "apps")

    def test_mode_takes_an_optional_value(self) -> None:
        self.assertEqual(build_parser().parse_args(["mode"]).mode, "")
        self.assertEqual(build_parser().parse_args(["mode", "auto"]).mode, "auto")

    def test_profile_add(self) -> None:
        args = build_parser().parse_args(
            ["profile", "add", "cs2", "--include", "cs2,steam", "--exclude", "discord", "--step", "2"]
        )
        self.assertEqual((args.profile_command, args.id), ("add", "cs2"))
        self.assertEqual(args.include, "cs2,steam")
        self.assertEqual(args.exclude, "discord")
        self.assertEqual(args.step, 2.0)

    def test_profile_toggle_and_rm(self) -> None:
        self.assertEqual(
            build_parser().parse_args(["profile", "toggle", "spotify"]).profile_command, "toggle"
        )
        self.assertEqual(build_parser().parse_args(["profile", "rm", "cs2"]).id, "cs2")

    def test_profile_next_and_prev(self) -> None:
        self.assertEqual(
            build_parser().parse_args(["profile", "next"]).profile_command, "next"
        )
        self.assertEqual(
            build_parser().parse_args(["profile", "prev"]).profile_command, "prev"
        )

    def test_an_unknown_osd_name_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["profile", "add", "x", "--osd-name", "sometimes"])


class CycleCommandTests(unittest.TestCase):
    """The cycle the keys use is also reachable from the client."""

    class Proxy:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def NextProfile(self) -> str:
            self.calls.append("next")
            return json.dumps({"ok": True, "action": "profile", "matched": 1})

        def PreviousProfile(self) -> str:
            self.calls.append("prev")
            return json.dumps({"ok": True, "action": "profile", "matched": 1})

    def test_next_and_prev_reach_the_daemon(self) -> None:
        proxy = self.Proxy()

        payload, kind = _profile(proxy, build_parser().parse_args(["profile", "next"]))
        self.assertEqual((payload["action"], kind), ("profile", "short"))

        payload, kind = _profile(proxy, build_parser().parse_args(["profile", "prev"]))
        self.assertEqual((payload["action"], kind), ("profile", "short"))
        self.assertEqual(proxy.calls, ["next", "prev"])


def _render(result: dict) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_profiles(result)
    return buffer.getvalue()


def _render_apps(result: dict) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_applications(result)
    return buffer.getvalue()


def _render_mode(result: dict) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_mode(result)
    return buffer.getvalue()


class AnswerTests(unittest.TestCase):
    ACTIVE = {"id": "active", "name": "Active window"}

    def test_a_volume_step_does_not_repeat_the_active_profile(self) -> None:
        result = {
            "action": "down",
            "matched": 1,
            "match_step": "pid",
            "profile": self.ACTIVE,
            "streams": [{"label": "Spotify", "from": [50], "to": [45]}],
        }
        self.assertEqual(_short(result), "Spotify 50% -> 45% (1 stream, matched by pid)")

    def test_a_volume_step_names_a_stream_profile(self) -> None:
        result = {
            "action": "down",
            "matched": 2,
            "match_step": "profile",
            "profile": {"id": "cs2", "name": "Counter-Strike"},
            "streams": [{"label": "cs2", "from": [50], "to": [48]}],
        }
        self.assertIn("Counter-Strike: cs2 50% -> 48%", _short(result))

    def test_a_mute_is_reported_with_the_labels(self) -> None:
        result = {
            "action": "mute",
            "matched": 1,
            "muted": True,
            "profile": self.ACTIVE,
            "streams": [{"label": "Spotify"}],
        }
        self.assertEqual(_short(result), "Spotify: muted (1 stream)")

    def test_an_empty_match_explains_itself(self) -> None:
        result = {"matched": 0, "reason": "no active window", "profile": self.ACTIVE}
        self.assertEqual(_short(result), "nothing to do: no active window")

    def test_a_profile_switch_is_reported(self) -> None:
        result = {
            "action": "profile",
            "matched": 1,
            "match_step": "profile",
            "current": "spotify",
            "profile": {"id": "spotify", "name": "Spotify"},
            "percent": 40,
        }
        self.assertEqual(_short(result), "Spotify: current profile (1 stream, matched by profile)")


class ProfileTableTests(unittest.TestCase):
    def test_the_table_marks_the_current_profile(self) -> None:
        text = _render(
            {
                "current": "spotify",
                "idle_timeout": 300.0,
                "profiles": [
                    {
                        "id": "spotify",
                        "name": "Spotify",
                        "include": ["spotify"],
                        "exclude": [],
                        "step": 2.0,
                        "max_volume": None,
                        "icon": "",
                    },
                    {
                        "id": "cs2",
                        "name": "Counter-Strike",
                        "include": [],
                        "exclude": ["discord"],
                        "step": None,
                        "max_volume": 120.0,
                        "icon": "input-gaming",
                    },
                ],
            }
        )
        self.assertIn("current: spotify, back to active after 300s idle", text)
        self.assertIn("* spotify", text)
        self.assertIn("every application stream without discord", text)
        self.assertIn("max 120%", text)

    def test_no_profiles_yet_says_how_to_create_one(self) -> None:
        text = _render({"current": "active", "idle_timeout": 300.0, "profiles": []})
        self.assertIn("appvol profile add", text)

    def test_an_empty_auto_list_does_not_offer_a_file_profile(self) -> None:
        text = _render(
            {
                "current": "active",
                "idle_timeout": 300.0,
                "config": {"mode": "auto"},
                "profiles": [],
            }
        )
        self.assertIn("no application is playing", text)
        self.assertNotIn("appvol profile add", text)

    def test_the_table_marks_the_current_auto_target(self) -> None:
        text = _render(
            {
                "current": "app-spotify",
                "idle_timeout": 300.0,
                "config": {"mode": "auto"},
                "profiles": [
                    {
                        "id": "app-spotify",
                        "name": "Spotify",
                        "include": ["spotify"],
                        "exclude": [],
                        "step": None,
                        "max_volume": None,
                        "icon": "",
                    }
                ],
            }
        )
        self.assertIn("current: app-spotify", text)
        self.assertIn("* app-spotify", text)


class ListTests(unittest.TestCase):
    def render(self, profile: dict) -> str:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            _print_list(
                {
                    "config": {"step": 2.5, "max_volume": 100.0, "osd": True, "mode": "auto"},
                    "profile": profile,
                    "focus": {},
                    "match": {},
                    "osd": {},
                    "streams": [],
                }
            )
        return buffer.getvalue()

    def test_the_current_auto_target_shows_its_id(self) -> None:
        # The same name and scope as the file profile "spotify"; only the id tells
        # the two apart.
        text = self.render(
            {"id": "app-spotify", "name": "Spotify", "mode": "streams", "include": ["spotify"]}
        )
        self.assertIn("profile: app-spotify 'Spotify' [streams] spotify", text)

    def test_the_active_profile_shows_its_id(self) -> None:
        text = self.render({"id": "active", "name": "Active window", "mode": "focus"})
        self.assertIn("profile: active 'Active window' [focus] the focused window", text)

    def test_no_active_window_has_no_unknown_application(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            _print_list(
                {
                    "config": {"step": 5, "max_volume": 100, "osd": True, "mode": "auto"},
                    "profile": {"id": "active", "name": "Active window", "mode": "focus"},
                    "focus": {
                        "pid": 0,
                        "label": "",
                        "age": 1.4,
                        "ignored_reason": "no active window",
                    },
                    "match": {"step": "", "reason": "no active window", "matched": 0},
                    "osd": {"name": "", "icon": ""},
                    "streams": [],
                }
            )
        text = buffer.getvalue()

        self.assertIn("focus:  none (1.4s ago)", text)
        self.assertIn("osd:    No stream", text)
        self.assertNotIn("unknown", text)
        self.assertNotIn("pid 0", text)


class ModeTests(unittest.TestCase):
    def test_the_mode_is_spelled_out(self) -> None:
        self.assertIn("mode: auto", _render_mode({"config": {"mode": "auto"}}))
        self.assertIn("running applications", _render_mode({"config": {"mode": "auto"}}))
        self.assertIn("profiles.toml", _render_mode({"config": {"mode": "profiles"}}))

    def test_a_payload_without_a_mode_reads_as_the_profiles(self) -> None:
        self.assertIn("mode: profiles", _render_mode({}))


class ApplicationTableTests(unittest.TestCase):
    def test_the_table_lists_applications_with_their_identifiers(self) -> None:
        text = _render_apps(
            {
                "applications": [
                    {
                        "id": "spotify",
                        "label": "Spotify",
                        "percent": 45,
                        "muted": False,
                        "panel": False,
                        "streams": [1],
                    },
                    {
                        "id": "plasmashell",
                        "label": "plasmashell",
                        "percent": 30,
                        "muted": True,
                        "panel": True,
                        "streams": [4, 5],
                    },
                ]
            }
        )
        self.assertIn("Spotify", text)
        self.assertIn("spotify", text)
        self.assertIn("1 stream", text)
        self.assertIn("2 streams", text)
        self.assertIn("muted", text)
        self.assertIn("shell", text)

    def test_an_empty_table_says_so(self) -> None:
        self.assertIn("nothing", _render_apps({"applications": []}))


if __name__ == "__main__":
    unittest.main()
