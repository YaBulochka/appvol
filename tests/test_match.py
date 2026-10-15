"""Unit tests for the pure window -> streams matcher."""

from __future__ import annotations

import unittest

from appvol.focus import Focus
from appvol.match import STEP_DESCENDANT, STEP_NAME, STEP_PID, Stream, match_streams


def stream(index: int, **props: str) -> Stream:
    props = {key: str(value) for key, value in props.items()}
    return Stream(index=index, props=props, label=props.get("application.name", f"stream {index}"))


def no_parents(_pid: int) -> None:
    return None


class FocusGuardTests(unittest.TestCase):
    def test_empty_focus_is_ignored(self) -> None:
        result = match_streams(Focus(), [stream(1, **{"application.process.id": "1"})])
        self.assertFalse(result.matched)
        self.assertEqual(result.reason, "no active window")

    def test_panel_focus_is_ignored(self) -> None:
        focus = Focus(pid=42, resource_class="plasmashell", desktop_file_name="org.kde.plasmashell")
        result = match_streams(focus, [stream(1, **{"application.process.id": "42"})])
        self.assertFalse(result.matched)
        self.assertIn("panel", result.reason)

    def test_window_without_pid_is_ignored(self) -> None:
        focus = Focus(pid=0, resource_class="firefox")
        result = match_streams(focus, [stream(1, **{"application.name": "Firefox"})])
        self.assertFalse(result.matched)
        self.assertIn("pid", result.reason)


class PidStepTests(unittest.TestCase):
    def test_direct_pid_match(self) -> None:
        focus = Focus(pid=100, resource_class="spotify", desktop_file_name="org.mozilla.firefox")
        streams = [
            stream(1, **{"application.process.id": "100", "application.name": "Spotify"}),
            stream(2, **{"application.process.id": "200", "application.name": "Firefox"}),
        ]
        result = match_streams(focus, streams, parent_of=no_parents)
        self.assertEqual(result.step, STEP_PID)
        self.assertEqual(result.indices, (1,))

    def test_pid_match_beats_name_match(self) -> None:
        focus = Focus(pid=100, desktop_file_name="org.mozilla.firefox")
        streams = [
            stream(1, **{"application.process.id": "999", "application.name": "Firefox"}),
            stream(2, **{"application.process.id": "100", "application.name": "something else"}),
        ]
        result = match_streams(focus, streams, parent_of=no_parents)
        self.assertEqual(result.step, STEP_PID)
        self.assertEqual(result.indices, (2,))

    def test_all_streams_of_the_pid_are_returned(self) -> None:
        focus = Focus(pid=100)
        streams = [
            stream(1, **{"application.process.id": "100"}),
            stream(2, **{"application.process.id": "100"}),
            stream(3, **{"application.process.id": "101"}),
        ]
        result = match_streams(focus, streams, parent_of=no_parents)
        self.assertEqual(result.indices, (1, 2))


class DescendantStepTests(unittest.TestCase):
    def test_child_process_of_the_window(self) -> None:
        focus = Focus(pid=100, resource_class="firefox")
        streams = [stream(7, **{"application.process.id": "300"})]
        parents = {300: 200, 200: 100, 100: 1}
        result = match_streams(focus, streams, parent_of=lambda pid: parents.get(pid))
        self.assertEqual(result.step, STEP_DESCENDANT)
        self.assertEqual(result.indices, (7,))

    def test_unrelated_process_is_not_matched(self) -> None:
        focus = Focus(pid=100, resource_class="firefox")
        streams = [stream(7, **{"application.process.id": "300"})]
        parents = {300: 250, 250: 1}
        result = match_streams(focus, streams, parent_of=lambda pid: parents.get(pid))
        self.assertEqual(result.indices, ())


class NameStepTests(unittest.TestCase):
    def test_desktop_file_matches_binary(self) -> None:
        focus = Focus(pid=500, desktop_file_name="org.mozilla.firefox")
        streams = [stream(3, **{"application.process.binary": "firefox", "application.name": "Firefox"})]
        result = match_streams(focus, streams, parent_of=no_parents)
        self.assertEqual(result.step, STEP_NAME)
        self.assertEqual(result.indices, (3,))

    def test_resource_class_matches_application_name(self) -> None:
        focus = Focus(pid=500, resource_class="Spotify")
        streams = [stream(4, **{"application.name": "Spotify"})]
        result = match_streams(focus, streams, parent_of=no_parents)
        self.assertEqual(result.step, STEP_NAME)
        self.assertEqual(result.indices, (4,))

    def test_portal_app_id_matches(self) -> None:
        focus = Focus(pid=500, desktop_file_name="org.mozilla.firefox")
        streams = [stream(5, **{"pipewire.access.portal.app_id": "org.mozilla.firefox"})]
        result = match_streams(focus, streams, parent_of=no_parents)
        self.assertEqual(result.step, STEP_NAME)
        self.assertEqual(result.indices, (5,))

    def test_flatpak_style_suffix_match(self) -> None:
        focus = Focus(pid=500, desktop_file_name="com.spotify.Client")
        streams = [stream(6, **{"application.id": "com.spotify.Client"})]
        result = match_streams(focus, streams, parent_of=no_parents)
        self.assertEqual(result.indices, (6,))

    def test_case_insensitive(self) -> None:
        focus = Focus(pid=500, resource_class="MPV")
        streams = [stream(8, **{"application.process.binary": "mpv"})]
        result = match_streams(focus, streams, parent_of=no_parents)
        self.assertEqual(result.indices, (8,))

    def test_no_match_reports_reason(self) -> None:
        focus = Focus(pid=500, resource_class="konsole", desktop_file_name="org.kde.konsole")
        streams = [stream(9, **{"application.name": "Firefox"})]
        result = match_streams(focus, streams, parent_of=no_parents)
        self.assertFalse(result.matched)
        self.assertIn("no stream matched", result.reason)

    def test_stream_without_any_identifier_is_skipped(self) -> None:
        focus = Focus(pid=500, resource_class="Spotify")
        streams = [stream(10)]
        result = match_streams(focus, streams, parent_of=no_parents)
        self.assertFalse(result.matched)

    def test_none_parent_of_disables_descendant_step(self) -> None:
        focus = Focus(pid=100, resource_class="firefox")
        streams = [stream(11, **{"application.process.id": "300"})]
        result = match_streams(focus, streams, parent_of=None)
        self.assertFalse(result.matched)


if __name__ == "__main__":
    unittest.main()
