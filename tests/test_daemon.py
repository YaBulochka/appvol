"""Daemon pieces that need no running session bus.

Where the bundled KWin script is looked for, how the profile shortcuts are handed
to the shortcut server, and which caption a profile gives the OSD.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from appvol import daemon
from appvol.profiles import MODE_FOCUS, OSD_NAME_ALWAYS, OSD_NAME_NEVER, Profile, active_profile


class FindKwinScriptTest(unittest.TestCase):
    def test_the_first_existing_candidate_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            missing = base / "kwin" / "appvol.js"
            found = base / "share" / "appvol" / "appvol.js"
            found.parent.mkdir(parents=True)
            found.write_text("// script\n", encoding="utf-8")
            self.assertEqual(daemon.find_kwin_script([missing, found]), found)

    def test_a_missing_script_reports_the_first_candidate(self) -> None:
        first = Path("/nonexistent/kwin/appvol.js")
        second = Path("/nonexistent/share/appvol/appvol.js")
        self.assertEqual(daemon.find_kwin_script([first, second]), first)

    def test_the_checkout_is_looked_at_before_the_data_dirs(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_DATA_DIRS": "/usr/local/share:/usr/share"}):
            candidates = daemon.kwin_script_candidates()
        checkout = Path(daemon.__file__).resolve().parent.parent / "kwin" / "appvol.js"
        self.assertEqual(
            candidates,
            [checkout, Path("/usr/local/share/appvol/appvol.js"), Path("/usr/share/appvol/appvol.js")],
        )

    def test_the_default_data_dirs_are_used_when_the_variable_is_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            candidates = daemon.kwin_script_candidates()
        self.assertEqual(
            candidates[1:], [Path("/usr/local/share/appvol/appvol.js"), Path("/usr/share/appvol/appvol.js")]
        )

    def test_an_empty_entry_in_the_variable_is_skipped(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_DATA_DIRS": ":/usr/share:"}):
            candidates = daemon.kwin_script_candidates()
        self.assertEqual(candidates[1:], [Path("/usr/share/appvol/appvol.js")])


class RecordingInterface:
    """Stands in for ``/kglobalaccel`` and writes down every call."""

    def __init__(self, keys: list[str] | None = None) -> None:
        self.keys = list(keys or [])
        self.calls: list[tuple] = []

    def doRegister(self, action_id):  # noqa: N802 - the D-Bus name
        self.calls.append(("doRegister", action_id))

    def shortcutKeys(self, action_id):  # noqa: N802
        self.calls.append(("shortcutKeys", action_id))
        return list(self.keys)

    def setShortcutKeys(self, action_id, keys, flags):  # noqa: N802
        self.calls.append(("setShortcutKeys", action_id, keys, flags))
        return list(keys)

    def unregister(self, component, action):
        self.calls.append(("unregister", component, action))

    def getComponent(self, component):  # noqa: N802
        return "/component/appvol"


class RecordingBus:
    def __init__(self) -> None:
        self.receivers: list[tuple] = []

    def add_signal_receiver(self, handler, **kwargs) -> None:
        self.receivers.append((handler, kwargs))


class RecordingActions(daemon.ShortcutActions):
    """``ShortcutActions`` that talks to a recording interface, not to D-Bus."""

    def __init__(self, interface: RecordingInterface, on_pressed=None) -> None:
        super().__init__(RecordingBus(), on_pressed or (lambda action: None))
        self.interface = interface

    def _interface(self):
        return self.interface


class ShortcutRegistrationTest(unittest.TestCase):
    """Registering an action is not enough: the server grabs a *present* one.

    kglobalacceld keeps an action and its key from ``kglobalshortcutsrc`` after a
    bare ``doRegister``, so System Settings shows the binding while the key was
    never grabbed and a press reaches nobody.  ``SetPresent`` is what registers
    the keys with the compositor.
    """

    def test_a_profile_key_is_registered_and_then_marked_present(self) -> None:
        interface = RecordingInterface(["Ctrl+Alt+0"])
        actions = RecordingActions(interface)

        actions.sync([Profile(id="spotify", name="Spotify")])

        action_id = ["appvol", "profile_spotify", "appvol profiles", "Spotify"]
        self.assertEqual(
            interface.calls,
            [
                ("doRegister", action_id),
                ("shortcutKeys", action_id),
                ("setShortcutKeys", action_id, ["Ctrl+Alt+0"], daemon.KGA_SET_PRESENT),
            ],
        )

    def test_the_present_flag_keeps_its_wire_value(self) -> None:
        # KGlobalAccelD::SetShortcutFlag::SetPresent; the number is what the
        # shortcut server reads as "the owner is here, grab the keys".
        self.assertEqual(daemon.KGA_SET_PRESENT, 2)

    def test_the_keys_written_back_are_the_ones_the_server_holds(self) -> None:
        # The server autoloads the key the user assigned; reading it first keeps
        # a brand new action from being stored with no key at all.
        interface = RecordingInterface(["Meta+Alt+S"])
        actions = RecordingActions(interface)

        actions.sync([Profile(id="music")])

        written = [call for call in interface.calls if call[0] == "setShortcutKeys"]
        self.assertEqual(written[0][2], ["Meta+Alt+S"])

    def test_the_action_of_a_removed_profile_is_dropped(self) -> None:
        interface = RecordingInterface()
        actions = RecordingActions(interface)
        actions.sync([Profile(id="spotify"), Profile(id="desktop")])

        interface.calls.clear()
        actions.sync([Profile(id="spotify")])

        self.assertIn(("unregister", "appvol", "profile_desktop"), interface.calls)
        self.assertEqual(actions.actions, ("profile_spotify",))

    def test_a_press_reaches_the_callback(self) -> None:
        pressed: list[str] = []
        actions = RecordingActions(RecordingInterface(), pressed.append)
        actions.sync([Profile(id="spotify")])

        actions._pressed("appvol", "profile_spotify", 0)

        self.assertEqual(pressed, ["profile_spotify"])

    def test_the_component_object_is_watched_for_presses(self) -> None:
        actions = RecordingActions(RecordingInterface())
        actions.sync([Profile(id="spotify")])

        handler, rule = actions.bus.receivers[0]
        self.assertEqual(handler, actions._pressed)
        self.assertEqual(rule["signal_name"], "globalShortcutPressed")
        self.assertEqual(rule["path"], "/component/appvol")


class ShortcutServerRestartTest(unittest.TestCase):
    """KWin owns the shortcut server; its restart drops our registration."""

    def test_the_profile_keys_are_registered_again(self) -> None:
        app = mock.Mock()
        daemon.Appvol.on_shortcut_server_changed(app, "org.kde.kglobalaccel", ":1.1", ":1.2")
        app.daemon.resync_shortcuts.assert_called_once_with()

    def test_a_vanishing_server_registers_nothing(self) -> None:
        app = mock.Mock()
        daemon.Appvol.on_shortcut_server_changed(app, "org.kde.kglobalaccel", ":1.2", "")
        app.daemon.resync_shortcuts.assert_not_called()


class OsdCaptionTest(unittest.TestCase):
    """The Active profile shows the icon alone; the reply keeps the name."""

    def test_the_active_profile_hides_the_name(self) -> None:
        self.assertEqual(daemon.osd_caption(active_profile(), "Firefox"), "")

    def test_a_stream_profile_shows_its_name(self) -> None:
        profile = Profile(id="spotify", name="Spotify")
        self.assertEqual(daemon.osd_caption(profile, "Spotify"), "Spotify")

    def test_always_puts_the_name_back_on_a_focus_profile(self) -> None:
        profile = Profile(id="focus", mode=MODE_FOCUS, osd_name=OSD_NAME_ALWAYS)
        self.assertEqual(daemon.osd_caption(profile, "Firefox"), "Firefox")

    def test_never_silences_a_stream_profile(self) -> None:
        profile = Profile(id="spotify", name="Spotify", osd_name=OSD_NAME_NEVER)
        self.assertEqual(daemon.osd_caption(profile, "Spotify"), "")


if __name__ == "__main__":
    unittest.main()
