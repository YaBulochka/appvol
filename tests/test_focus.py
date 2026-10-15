"""Unit tests for focus helpers (name normalisation and process ancestry)."""

from __future__ import annotations

import os
import unittest

from appvol.focus import (
    Focus,
    desktop_file_stem,
    focus_from_dbus,
    is_descendant,
    parse_pid,
    read_parent_pid,
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
