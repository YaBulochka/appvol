"""Daemon pieces that need no running session bus.

Where the bundled KWin script is looked for, how the shortcut actions are handed
to the shortcut server and dispatched, which caption a profile gives the OSD, and
what the step of a row writes.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import dbus

from appvol import daemon
from appvol.config import Config
from appvol.profiles import MODE_FOCUS, Profile, active_profile
from appvol.profiles import parse as parse_profiles


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

        action_id = ["appvol", "profile_spotify", "Appvol", "Spotify"]
        self.assertEqual(
            interface.calls[-3:],
            [
                ("doRegister", action_id),
                ("shortcutKeys", action_id),
                ("setShortcutKeys", action_id, ["Ctrl+Alt+0"], daemon.KGA_SET_PRESENT),
            ],
        )

    def test_the_same_component_carries_the_volume_and_the_cycling_keys(self) -> None:
        # One entry in System Settings: the volume actions used to live in a
        # desktop file of their own, which Plasma listed next to the profiles.
        interface = RecordingInterface()
        actions = RecordingActions(interface)

        actions.sync([])

        registered = [call[1] for call in interface.calls if call[0] == "doRegister"]
        self.assertEqual(
            registered,
            [
                ["appvol", "volume_up", "Appvol", "Volume up"],
                ["appvol", "volume_down", "Appvol", "Volume down"],
                ["appvol", "volume_mute", "Appvol", "Toggle mute"],
                ["appvol", "next_profile", "Appvol", "Next profile"],
                ["appvol", "previous_profile", "Appvol", "Previous profile"],
            ],
        )
        self.assertEqual(actions.actions, tuple(name for name, _label in daemon.FIXED_ACTIONS))

    def test_the_component_is_named_appvol(self) -> None:
        self.assertEqual(daemon.KGA_COMPONENT, "appvol")
        self.assertEqual(daemon.KGA_COMPONENT_FRIENDLY, "Appvol")

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

        written = {
            call[1][1]: call[2] for call in interface.calls if call[0] == "setShortcutKeys"
        }
        self.assertEqual(written["profile_music"], ["Meta+Alt+S"])
        self.assertTrue(all(keys == ["Meta+Alt+S"] for keys in written.values()))

    def test_the_action_of_a_removed_profile_is_dropped(self) -> None:
        interface = RecordingInterface()
        actions = RecordingActions(interface)
        actions.sync([Profile(id="spotify"), Profile(id="desktop")])

        interface.calls.clear()
        actions.sync([Profile(id="spotify")])

        self.assertIn(("unregister", "appvol", "profile_desktop"), interface.calls)
        self.assertEqual(
            actions.actions,
            (*tuple(name for name, _label in daemon.FIXED_ACTIONS), "profile_spotify"),
        )

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


class ShortcutDispatchTest(unittest.TestCase):
    """Every key of the component is answered by the daemon itself."""

    def daemon_with(self, profiles=()):
        app = mock.Mock()
        app.profiles = list(profiles)
        return app

    def test_the_volume_keys_run_the_volume_code(self) -> None:
        app = self.daemon_with()

        daemon.Daemon.on_shortcut(app, daemon.ACTION_VOLUME_UP)
        app._adjust.assert_called_once_with(daemon.UP, 0.0)

        app._adjust.reset_mock()
        daemon.Daemon.on_shortcut(app, daemon.ACTION_VOLUME_DOWN)
        app._adjust.assert_called_once_with(daemon.DOWN, 0.0)

    def test_the_mute_key_toggles(self) -> None:
        app = self.daemon_with()
        daemon.Daemon.on_shortcut(app, daemon.ACTION_VOLUME_MUTE)
        app._toggle_mute.assert_called_once_with()

    def test_the_cycling_keys_step_in_both_directions(self) -> None:
        app = self.daemon_with()

        daemon.Daemon.on_shortcut(app, daemon.ACTION_NEXT_PROFILE)
        app._cycle_profile.assert_called_once_with(1)

        app._cycle_profile.reset_mock()
        daemon.Daemon.on_shortcut(app, daemon.ACTION_PREVIOUS_PROFILE)
        app._cycle_profile.assert_called_once_with(-1)

    def test_a_profile_key_toggles_its_own_profile(self) -> None:
        app = self.daemon_with([Profile(id="spotify")])
        daemon.Daemon.on_shortcut(app, "profile_spotify")
        app._toggle_profile.assert_called_once_with("spotify")

    def test_an_action_of_a_removed_profile_is_ignored(self) -> None:
        app = self.daemon_with([Profile(id="spotify")])
        daemon.Daemon.on_shortcut(app, "profile_gone")
        app._toggle_profile.assert_not_called()

    def test_an_unknown_action_is_ignored(self) -> None:
        app = self.daemon_with()
        daemon.Daemon.on_shortcut(app, "something_else")
        app._toggle_profile.assert_not_called()
        app._adjust.assert_not_called()


class CycleProfileTest(unittest.TestCase):
    """Next and Previous walk the order the window shows, and wrap around."""

    def make(self, profiles=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = StepDaemon(Path(tmp.name), profiles)
        # The step files are never written here, only the selection moves.
        app._feedback = mock.Mock()
        return app

    def test_next_goes_forward_and_wraps(self) -> None:
        app = self.make([Profile(id="spotify"), Profile(id="cs2")])

        visited = []
        for _ in range(4):
            app._cycle_profile(1)
            visited.append(app.state.selection.current)

        self.assertEqual(visited, ["spotify", "cs2", "active", "spotify"])

    def test_previous_goes_backwards(self) -> None:
        app = self.make([Profile(id="spotify"), Profile(id="cs2")])
        app._cycle_profile(-1)
        self.assertEqual(app.state.selection.current, "cs2")

    def test_cycling_asks_for_the_osd_of_the_profile_it_lands_on(self) -> None:
        app = self.make([Profile(id="spotify"), Profile(id="cs2")])
        app._cycle_profile(1)

        profile, osd = app._feedback.call_args[0][0], app._feedback.call_args[1]["osd"]
        self.assertEqual((profile.id, osd), ("spotify", True))

    def test_a_session_without_profiles_stays_on_active(self) -> None:
        app = self.make([])
        app._cycle_profile(1)
        self.assertEqual(app.state.selection.current, "active")


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
    """The OSD captions the application name only when the global checkbox allows it."""

    def test_the_name_is_hidden_when_the_checkbox_is_off(self) -> None:
        self.assertEqual(daemon.osd_caption(False, "Firefox"), "")

    def test_the_name_is_shown_when_the_checkbox_is_on(self) -> None:
        self.assertEqual(daemon.osd_caption(True, "Firefox"), "Firefox")


class StepDaemon(daemon.Daemon):
    """A ``Daemon`` with the files and the selection, but no session bus."""

    def __init__(self, base: Path, profiles=(), config: Config | None = None) -> None:
        self.config = config or Config()
        self.profiles = list(profiles)
        self.profiles_path = base / "profiles.toml"
        self.config_path = base / "config.toml"
        self.state = daemon.State()
        self._last_active: tuple[str, str, int] | None = None


class SetStepTest(unittest.TestCase):
    """The step of a row: one profile's own, or the global one for Active.

    Both are edits of a file the daemon owns while it runs, so the tests read the
    files back instead of trusting the in-memory copy alone.
    """

    def test_a_profile_step_is_written_to_profiles_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app = StepDaemon(base, [Profile(id="spotify", name="Spotify", step=2.0)])

            answer = app._set_step("spotify", 7.0)

            self.assertEqual(answer["profiles"][0]["step"], 7.0)
            stored = parse_profiles(app.profiles_path.read_text(encoding="utf-8"))
            self.assertEqual(stored[0].step, 7.0)

    def test_a_zero_step_hands_the_choice_back_to_the_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app = StepDaemon(base, [Profile(id="spotify", step=2.0)])

            app._set_step("spotify", 0.0)

            stored = parse_profiles(app.profiles_path.read_text(encoding="utf-8"))
            self.assertIsNone(stored[0].step)

    def test_the_other_profiles_keep_their_own_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app = StepDaemon(
                base, [Profile(id="spotify", step=2.0), Profile(id="cs2", step=10.0)]
            )

            app._set_step("spotify", 0.0)

            stored = parse_profiles(app.profiles_path.read_text(encoding="utf-8"))
            self.assertIsNone(stored[0].step)
            self.assertEqual(stored[1].step, 10.0)

    def test_the_active_profile_writes_the_global_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            app = StepDaemon(base, [Profile(id="spotify")])

            answer = app._set_step("active", 3.0)

            self.assertEqual(app.config.step, 3.0)
            self.assertEqual(answer["config"]["step"], 3.0)
            written = app.config_path.read_text(encoding="utf-8")
            self.assertIn("step = 3", written)
            self.assertEqual(daemon.load_config(app.config_path).step, 3.0)

    def test_the_global_step_keeps_the_rest_of_the_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            config = Config(step=5.0, max_volume=120.0, osd=False, profile_idle_timeout=60.0)
            app = StepDaemon(base, config=config)

            app._set_step("", 4.0)

            stored = daemon.load_config(app.config_path)
            self.assertEqual(
                (stored.step, stored.max_volume, stored.osd, stored.profile_idle_timeout),
                (4.0, 120.0, False, 60.0),
            )

    def test_the_global_step_may_not_be_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = StepDaemon(Path(tmp))

            with self.assertRaises(dbus.DBusException) as caught:
                app._set_step("active", 0.0)

            self.assertEqual(caught.exception.get_dbus_name(), "org.appvol.Error.InvalidArgument")
            self.assertEqual(app.config.step, Config().step)

    def test_an_unknown_profile_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = StepDaemon(Path(tmp), [Profile(id="spotify")])

            with self.assertRaises(dbus.DBusException) as caught:
                app._set_step("cs2", 5.0)

            self.assertEqual(caught.exception.get_dbus_name(), "org.appvol.Error.InvalidArgument")

    def test_a_negative_step_is_refused_before_any_write(self) -> None:
        with self.assertRaises(dbus.DBusException):
            daemon._step(-1.0)
        self.assertEqual(daemon._step(0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
