"""Unit tests for focus helpers (name normalisation and process ancestry)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from appvol.focus import (
    Focus,
    desktop_file_stem,
    focus_from_dbus,
    is_descendant,
    parse_pid,
    parse_steam_app_id,
    read_parent_pid,
    read_steam_app_id,
)


class NormalisationTests(unittest.TestCase):
    def test_parse_pid(self) -> None:
        self.assertEqual(parse_pid(1234), 1234)
        self.assertEqual(parse_pid("1234"), 1234)
        self.assertEqual(parse_pid(0), 0)
        self.assertEqual(parse_pid(-3), 0)
        self.assertEqual(parse_pid(""), 0)
        self.assertEqual(parse_pid(None), 0)
        self.assertEqual(parse_pid("abc"), 0)

    def test_desktop_file_stem(self) -> None:
        self.assertEqual(desktop_file_stem("Firefox.Desktop"), "firefox")
        self.assertEqual(desktop_file_stem("org.mozilla.firefox"), "org.mozilla.firefox")
        self.assertEqual(desktop_file_stem("  MPV  "), "mpv")
        self.assertEqual(desktop_file_stem(None), "")
        self.assertEqual(desktop_file_stem(""), "")

    def test_focus_from_dbus_coerces_types(self) -> None:
        focus = focus_from_dbus(42.0, None, "org.kde.konsole", None)
        self.assertEqual(focus.pid, 42)
        self.assertEqual(focus.resource_class, "")
        self.assertEqual(focus.desktop_file_name, "org.kde.konsole")
        self.assertEqual(focus.caption, "")

    def test_is_empty(self) -> None:
        self.assertTrue(Focus().is_empty())
        self.assertFalse(Focus(pid=1).is_empty())
        self.assertFalse(Focus(desktop_file_name="x").is_empty())

    def test_label(self) -> None:
        self.assertEqual(Focus(desktop_file_name="org.kde.konsole").label, "org.kde.konsole")
        self.assertEqual(Focus(caption="Konsole").label, "Konsole")

    def test_an_empty_focus_has_no_label(self) -> None:
        self.assertEqual(Focus().label, "")
        self.assertEqual(Focus(pid=1).label, "unknown")


class SteamAppIdTests(unittest.TestCase):
    """The Steam app id of a stream owner, for a game that is not focused."""

    def test_steam_app_id_is_read_from_the_environment(self) -> None:
        data = b"HOME=/home/u\0SteamAppId=24240\0SteamGameId=24240\0"
        self.assertEqual(parse_steam_app_id(data), "24240")

    def test_steam_game_id_is_the_fallback(self) -> None:
        self.assertEqual(parse_steam_app_id(b"SteamGameId=730\0"), "730")

    def test_a_missing_or_non_numeric_id_is_empty(self) -> None:
        self.assertEqual(parse_steam_app_id(b"HOME=/home/u\0"), "")
        self.assertEqual(parse_steam_app_id(b"SteamAppId=not-a-number\0"), "")
        self.assertEqual(parse_steam_app_id(b"SteamAppId=\0"), "")

    def test_the_id_is_read_from_proc(self) -> None:
        with mock.patch("appvol.focus.open", mock.mock_open(read_data=b"SteamAppId=730\0")):
            self.assertEqual(read_steam_app_id(123), "730")

    def test_an_unreadable_process_has_no_id(self) -> None:
        self.assertEqual(read_steam_app_id(999999999), "")


class ProcessTreeTests(unittest.TestCase):
    def test_parent_of_current_process(self) -> None:
        self.assertEqual(read_parent_pid(os.getpid()), os.getppid())

    def test_parent_of_missing_process(self) -> None:
        self.assertIsNone(read_parent_pid(999999999))

    def test_is_descendant_of_parent(self) -> None:
        self.assertTrue(is_descendant(os.getpid(), os.getppid()))

    def test_is_not_descendant_of_itself(self) -> None:
        self.assertFalse(is_descendant(os.getpid(), os.getpid()))

    def test_is_descendant_chain(self) -> None:
        parents = {300: 200, 200: 100, 100: 1}
        self.assertTrue(is_descendant(300, 100, parent_of=lambda pid: parents.get(pid)))
        self.assertFalse(is_descendant(300, 999, parent_of=lambda pid: parents.get(pid)))

    def test_is_descendant_stops_on_cycle(self) -> None:
        parents = {300: 200, 200: 300}
        self.assertFalse(is_descendant(300, 999, parent_of=lambda pid: parents.get(pid)))

    def test_is_descendant_respects_max_depth(self) -> None:
        parents = {n: n - 1 for n in range(2, 100)}
        self.assertTrue(is_descendant(50, 40, parent_of=lambda pid: parents.get(pid)))
        self.assertFalse(
            is_descendant(50, 40, parent_of=lambda pid: parents.get(pid), max_depth=3)
        )


if __name__ == "__main__":
    unittest.main()
