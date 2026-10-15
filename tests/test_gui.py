"""Unit tests for the GUI: the D-Bus client, the key rendering and the bridge.

The QML files need a session bus, a window and the QML modules, so they are
checked by running ``bin/appvol-gui``; everything around them is plain Python.
PySide6 is optional, so the tests that import it are skipped without it.
"""

from __future__ import annotations

import json
import unittest

import dbus

from appvol import daemon
from appvol.cli import BUS_NAME as CLI_BUS_NAME
from appvol.cli import IFACE as CLI_IFACE
from appvol.cli import OBJECT_PATH as CLI_OBJECT_PATH
from appvol.gui import client as gui_client
from appvol.gui.client import NOT_RUNNING, Client, DaemonError
from appvol.profiles import action_name

try:
    import PySide6  # noqa: F401

    from appvol.gui import shortcuts as gui_shortcuts
    from appvol.gui.bridge import Bridge

    HAVE_QT = True
except ImportError:  # pragma: no cover - depends on the machine
    gui_shortcuts = None
    Bridge = None
    HAVE_QT = False

KEY_VOLUME_UP = 16777330
KEY_META_ALT_S = 402653267

OVERVIEW = {
    "ok": True,
    "current": "spotify",
    "idle_timeout": 300.0,
    "config": {"step": 5.0, "max_volume": 150.0, "osd": True},
    "profiles": [
        {
            "id": "active",
            "name": "Active window",
            "mode": "focus",
            "include": [],
            "exclude": [],
            "step": 0.0,
            "max_volume": 0.0,
            "icon": "",
            "osd_name": "auto",
            "builtin": True,
            "current": False,
            "matched": 0,
            "percent": None,
            "muted": None,
            "reason": "no window with audio streams",
        },
        {
            "id": "spotify",
            "name": "Spotify",
            "mode": "streams",
            "include": ["spotify"],
            "exclude": [],
            "step": 2.0,
            "max_volume": 120.0,
            "icon": "spotify",
            "osd_name": "always",
            "builtin": False,
            "current": True,
            "matched": 1,
            "percent": 15,
            "muted": False,
            "reason": "",
        },
    ],
}

APPLICATIONS = {
    "ok": True,
    "applications": [
        {
            "id": "spotify",
            "label": "Spotify",
            "variants": ["spotify"],
            "streams": [3],
            "percent": 15,
            "muted": False,
            "panel": False,
            "icon": "spotify",
        }
    ],
    "current": "spotify",
}


class FakeProxy:
    """Stand-in for a dbus proxy: records the calls, replays canned answers."""

    def __init__(self, answers=None, raises=None) -> None:
        self.__dict__["answers"] = dict(answers or {})
        self.__dict__["raises"] = raises
        self.__dict__["calls"] = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name, args))
            if self.raises is not None:
                raise self.raises
            return json.dumps(self.answers.get(name, {"ok": True}))

        return call


class FakeKeys:
    """Stand-in for ShortcutKeys: returns what the test set up."""

    def __init__(self, texts=None) -> None:
        self.texts = dict(texts or {})
        self.asked: list[tuple[str, str]] = []

    def text(self, action: str, name: str) -> str:
        self.asked.append((action, name))
        return self.texts.get(action, "")


def missing_service() -> dbus.DBusException:
    return dbus.DBusException("not found", name="org.freedesktop.DBus.Error.ServiceUnknown")


class ConstantsTests(unittest.TestCase):
    def test_the_gui_speaks_to_the_same_name_as_the_cli(self) -> None:
        self.assertEqual(gui_client.BUS_NAME, CLI_BUS_NAME)
        self.assertEqual(gui_client.OBJECT_PATH, CLI_OBJECT_PATH)
        self.assertEqual(gui_client.IFACE, CLI_IFACE)

    @unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
    def test_the_gui_reads_the_actions_the_daemon_registers(self) -> None:
        self.assertEqual(gui_shortcuts.COMPONENT, daemon.KGA_COMPONENT)
        self.assertEqual(gui_shortcuts.COMPONENT_FRIENDLY, daemon.KGA_COMPONENT_FRIENDLY)


class ClientTests(unittest.TestCase):
    def test_an_answer_is_decoded(self) -> None:
        proxy = FakeProxy({"Overview": OVERVIEW})
        client = Client(connect=lambda: proxy)
        self.assertEqual(client.overview()["profiles"][1]["id"], "spotify")

    def test_the_proxy_is_shared_between_calls(self) -> None:
        connects = []

        def connect():
            proxy = FakeProxy({"Profiles": {"ok": True}})
            connects.append(proxy)
            return proxy

        client = Client(connect=connect)
        client.profiles()
        client.profiles()
        self.assertEqual(len(connects), 1)

    def test_a_failed_call_drops_the_proxy(self) -> None:
        good = FakeProxy({"Profiles": {"ok": True}})
        queue = [FakeProxy(raises=missing_service()), good]
        client = Client(connect=lambda: queue.pop(0))

        with self.assertRaises(DaemonError) as caught:
            client.profiles()
        self.assertEqual(str(caught.exception), NOT_RUNNING)
        self.assertEqual(client.profiles(), {"ok": True})

    def test_a_refused_call_keeps_the_message(self) -> None:
        proxy = FakeProxy(
            raises=dbus.DBusException(
                "invalid profile id: 'x'", name="org.appvol.Error.InvalidArgument"
            )
        )
        client = Client(connect=lambda: proxy)
        with self.assertRaises(DaemonError) as caught:
            client.add_profile("x")
        self.assertIn("invalid profile id", str(caught.exception))

    def test_set_volume_sends_a_double(self) -> None:
        proxy = FakeProxy()
        client = Client(connect=lambda: proxy)
        client.set_volume("spotify", 42.5)
        name, args = proxy.calls[0]
        self.assertEqual(name, "SetVolume")
        self.assertEqual(args[0], "spotify")
        self.assertAlmostEqual(float(args[1]), 42.5)
        self.assertIsInstance(args[1], dbus.Double)

    def test_add_profile_sends_plain_lists(self) -> None:
        proxy = FakeProxy()
        client = Client(connect=lambda: proxy)
        client.add_profile("cs2", "CS2", ["cs2", "steam"], ["discord"], 3, 120, "cs2", "always")
        name, args = proxy.calls[0]
        self.assertEqual(name, "AddProfile")
        self.assertEqual(list(args[2]), ["cs2", "steam"])
        self.assertEqual(list(args[3]), ["discord"])
        self.assertAlmostEqual(float(args[4]), 3.0)
        self.assertEqual(args[7], "always")

    def test_switch_profile_carries_the_osd_flag(self) -> None:
        proxy = FakeProxy()
        client = Client(connect=lambda: proxy)
        client.switch_profile("spotify", True)
        name, args = proxy.calls[0]
        self.assertEqual(name, "SwitchProfile")
        self.assertEqual(list(args), ["spotify", True])

    def test_adjust_talks_about_the_current_profile(self) -> None:
        proxy = FakeProxy()
        client = Client(connect=lambda: proxy)
        client.adjust("up")
        name, args = proxy.calls[0]
        self.assertEqual(name, "AdjustTarget")
        self.assertEqual(args[0], "")
        self.assertEqual(args[1], "up")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class ShortcutKeyTests(unittest.TestCase):
    def test_a_sequence_is_rendered_the_way_kde_writes_it(self) -> None:
        self.assertEqual(gui_shortcuts.key_texts([[KEY_META_ALT_S, 0, 0, 0]]), "Meta+Alt+S")

    def test_an_unbound_action_renders_empty(self) -> None:
        self.assertEqual(gui_shortcuts.key_texts([[0, 0, 0, 0]]), "")
        self.assertEqual(gui_shortcuts.key_texts([]), "")

    def test_several_sequences_are_joined(self) -> None:
        entries = [[KEY_VOLUME_UP, 0, 0, 0], [KEY_META_ALT_S, 0, 0, 0]]
        self.assertEqual(gui_shortcuts.key_texts(entries), "Volume Up, Meta+Alt+S")

    def test_the_key_is_taken_from_any_shape_dbus_delivers(self) -> None:
        self.assertEqual(gui_shortcuts.first_key([KEY_VOLUME_UP, 0, 0, 0]), KEY_VOLUME_UP)
        self.assertEqual(gui_shortcuts.first_key(([KEY_VOLUME_UP, 0, 0, 0],)), KEY_VOLUME_UP)
        self.assertIsNone(gui_shortcuts.first_key([]))
        self.assertIsNone(gui_shortcuts.first_key(["Volume Up"]))

    def test_the_action_id_matches_the_daemon_convention(self) -> None:
        self.assertEqual(
            gui_shortcuts.action_id("profile_spotify", "Spotify"),
            ["appvol", "profile_spotify", "appvol profiles", "Spotify"],
        )

    def test_a_missing_shortcut_server_is_not_fatal(self) -> None:
        keys = gui_shortcuts.ShortcutKeys(connect=lambda: FakeProxy(raises=missing_service()))
        self.assertEqual(keys.text("profile_spotify", "Spotify"), "")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class BridgeTests(unittest.TestCase):
    def make(self, answers=None, raises=None, keys=None):
        proxy = FakeProxy(answers or {"Overview": OVERVIEW, "Applications": APPLICATIONS}, raises)
        self.proxy = proxy
        self.keys = keys or FakeKeys({action_name("spotify"): "Ctrl+Alt+1"})
        bridge = Bridge(Client(connect=lambda: proxy), self.keys)
        return bridge

    def test_refresh_fills_the_panel(self) -> None:
        bridge = self.make()
        bridge.refresh()
        self.assertEqual(bridge.current, "spotify")
        self.assertAlmostEqual(bridge.idleTimeout, 300.0)
        self.assertEqual(bridge.config["step"], 5.0)
        self.assertEqual([profile["id"] for profile in bridge.profiles], ["active", "spotify"])
        self.assertEqual(bridge.applications[0]["label"], "Spotify")
        self.assertEqual(bridge.error, "")
        self.assertTrue(bridge.daemonRunning)

    def test_the_key_of_every_profile_is_read(self) -> None:
        bridge = self.make()
        bridge.refresh()
        active, spotify = bridge.profiles
        self.assertEqual(active["key"], "")
        self.assertEqual(spotify["key"], "Ctrl+Alt+1")
        self.assertEqual(self.keys.asked, [(action_name("spotify"), "Spotify")])

    def test_a_missing_daemon_becomes_the_banner(self) -> None:
        bridge = self.make(raises=missing_service())
        bridge.refresh()
        self.assertEqual(bridge.error, NOT_RUNNING)
        self.assertFalse(bridge.daemonRunning)
        self.assertEqual(bridge.profiles, [])

    def test_selecting_a_profile_writes_and_reloads(self) -> None:
        bridge = self.make()
        bridge.refresh()
        bridge.selectProfile("spotify", False)
        self.assertEqual(
            [name for name, _args in self.proxy.calls],
            ["Overview", "Applications", "SwitchProfile", "Overview", "Applications"],
        )
        self.assertEqual(list(self.proxy.calls[2][1]), ["spotify", False])

    def test_a_slider_move_sets_the_volume(self) -> None:
        bridge = self.make()
        bridge.setVolume("spotify", 42.0)
        name, args = self.proxy.calls[0]
        self.assertEqual(name, "SetVolume")
        self.assertEqual(args[0], "spotify")

    def test_saving_a_profile_passes_the_lists_through(self) -> None:
        bridge = self.make()
        bridge.saveProfile("cs2", "CS2", ["cs2"], ["discord"], 3.0, 120.0, "cs2", "never")
        name, args = self.proxy.calls[0]
        self.assertEqual(name, "AddProfile")
        self.assertEqual(args[0], "cs2")
        self.assertEqual(list(args[3]), ["discord"])

    def test_a_failed_write_reports_and_keeps_the_panel(self) -> None:
        proxy = FakeProxy({"Overview": OVERVIEW, "Applications": APPLICATIONS}, missing_service())
        bridge = Bridge(Client(connect=lambda: proxy), FakeKeys())
        bridge.saveProfile("cs2", "CS2", [], [], 0.0, 0.0, "", "auto")
        self.assertEqual(bridge.error, NOT_RUNNING)


if __name__ == "__main__":
    unittest.main()
