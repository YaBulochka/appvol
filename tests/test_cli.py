"""Unit tests for the client: argument parsing and the readable answers."""

from __future__ import annotations

import contextlib
import io
import unittest

from appvol.cli import _print_profiles, _short, build_parser


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

    def test_an_unknown_osd_name_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["profile", "add", "x", "--osd-name", "sometimes"])


def _render(result: dict) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_profiles(result)
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


if __name__ == "__main__":
    unittest.main()
