"""The GlobalShortcuts portal client, against a fake portal on a fake bus."""

from __future__ import annotations

import unittest
from unittest import mock

import dbus

from appvol import portal


class FakePortal:
    """Records the requests the client sends."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, method: str):
        def call(*args, **kwargs):
            self.calls.append((method, args, kwargs))

        return call


class FakeBus:
    """Keeps the Response receivers by request path, so a test can answer."""

    def __init__(self) -> None:
        self.receivers: dict[str, object] = {}
        self.activated = None

    def get_unique_name(self) -> str:
        return ":1.42"

    def get_object(self, _service: str, _path: str):
        return object()

    def add_signal_receiver(self, handler, **kwargs) -> None:
        if kwargs.get("signal_name") == "Activated":
            self.activated = handler
            return
        self.receivers[kwargs["path"]] = handler

    def remove_signal_receiver(self, _handler, **kwargs) -> None:
        self.receivers.pop(kwargs.get("path"), None)

    def response(self, token: int, code: int, results: dict) -> None:
        path = f"/org/freedesktop/portal/desktop/request/1_42/appvol{token}"
        self.receivers[path](code, results)


ACTIONS = [("volume_up", "Volume up"), ("volume_down", "Volume down")]


class PortalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.portal_gate = FakePortal()
        self.bus = FakeBus()
        self.pressed: list[str] = []
        patcher = mock.patch.object(portal.dbus, "Interface", return_value=self.portal_gate)
        patcher.start()
        self.addCleanup(patcher.stop)
        timers = mock.patch.object(portal.GLib, "timeout_add_seconds", return_value=1)
        self.timers = timers.start()
        self.addCleanup(timers.stop)
        removed = mock.patch.object(portal.GLib, "source_remove", return_value=True)
        removed.start()
        self.addCleanup(removed.stop)
        self.client = portal.PortalShortcuts(self.bus, self.pressed.append, lambda: ACTIONS)

    def started(self) -> portal.PortalShortcuts:
        self.client.start()
        self.bus.response(0, 0, {"session_handle": "/org/freedesktop/portal/session/1"})
        return self.client

    def call(self, method: str) -> tuple:
        return next(call for call in self.portal_gate.calls if call[0] == method)

    def test_start_registers_the_app_id_before_anything_else(self) -> None:
        self.client.start()

        method, args, kwargs = self.portal_gate.calls[0]
        self.assertEqual(method, "Register")
        self.assertEqual(str(args[0]), portal.APP_ID)
        self.assertEqual(kwargs["signature"], "sa{sv}")

    def test_start_opens_a_session_and_listens(self) -> None:
        self.client.start()

        method, args, kwargs = self.call("CreateSession")
        self.assertEqual(kwargs["signature"], "a{sv}")
        self.assertIn("handle_token", args[0])
        self.assertEqual(str(args[0]["session_handle_token"]), "appvol")
        self.assertIsNotNone(self.bus.activated)

    def test_a_failed_session_is_retried(self) -> None:
        self.client.start()
        self.timers.reset_mock()
        self.bus.response(0, 2, {})

        delay, retry = self.timers.call_args[0][:2]
        self.assertEqual(delay, 2)
        retry()
        self.assertEqual(self.portal_gate.calls[-1][0], "CreateSession")
        self.assertEqual(self.client.session, "")

    def test_the_session_answer_is_kept_and_listed(self) -> None:
        client = self.started()

        self.assertEqual(client.session, "/org/freedesktop/portal/session/1")
        method, args, kwargs = self.call("ListShortcuts")
        self.assertEqual(kwargs["signature"], "oa{sv}")
        self.assertEqual(args[0], client.session)

    def test_the_list_records_what_the_desktop_has(self) -> None:
        client = self.started()
        self.bus.response(1, 0, {"shortcuts": [("volume_up", {}), ("volume_down", {})]})

        self.assertEqual(client.bound, {"volume_up", "volume_down"})
        self.assertEqual(client.status()["missing"], [])

    def test_bind_sends_only_the_missing_actions(self) -> None:
        client = self.started()
        client.bound = {"volume_up"}

        self.assertTrue(client.bind())

        method, args, kwargs = self.call("BindShortcuts")
        self.assertEqual(kwargs["signature"], "oa(sa{sv})sa{sv}")
        session, shortcuts, parent, _options = args
        self.assertEqual((str(session), str(parent)), (client.session, ""))
        self.assertEqual([str(shortcut[0]) for shortcut in shortcuts], ["volume_down"])
        self.assertEqual(str(shortcuts[0][1]["description"]), "Volume down")

    def test_binding_everything_does_not_open_the_dialog(self) -> None:
        client = self.started()
        client.bound = {"volume_up", "volume_down"}
        calls = len(self.portal_gate.calls)

        self.assertTrue(client.bind())
        self.assertEqual(len(self.portal_gate.calls), calls)

    def test_a_successful_bind_adds_the_ids(self) -> None:
        client = self.started()
        client.bind()
        self.bus.response(2, 0, {"shortcuts": [("volume_up", {}), ("volume_down", {})]})

        self.assertEqual(client.bound, {"volume_up", "volume_down"})

    def test_a_cancelled_dialog_keeps_the_bindings(self) -> None:
        client = self.started()
        client.bind()
        self.bus.response(2, 1, {})

        self.assertEqual(client.bound, set())
        self.assertEqual(client.status()["missing"], ["volume_up", "volume_down"])

    def test_a_press_is_forwarded(self) -> None:
        client = self.started()
        self.bus.activated(client.session, "volume_up", 0, {})

        self.assertEqual(self.pressed, ["volume_up"])

    def test_a_press_of_another_session_is_ignored(self) -> None:
        client = self.started()
        self.bus.activated("/some/other/session", "volume_up", 0, {})

        self.assertEqual(self.pressed, [])

    def test_status_before_a_session_names_every_action(self) -> None:
        status = self.client.status()

        self.assertFalse(status["available"])
        self.assertEqual(status["missing"], ["volume_up", "volume_down"])
        self.assertEqual(status["bound"], [])

    def test_a_desktop_without_the_portal_is_reported(self) -> None:
        with mock.patch.object(
            portal.dbus, "Interface", side_effect=dbus.DBusException("no portal")
        ):
            self.client.start()

        self.assertEqual(self.client.session, "")
        self.assertIn("no portal", self.client.error)
        self.assertFalse(self.client.bind())


if __name__ == "__main__":
    unittest.main()
