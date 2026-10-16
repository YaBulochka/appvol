"""The OSD wrapper has to survive a plasmashell restart.

The regression these tests pin down: ``dbus-python`` binds a proxy to the unique
name of the current owner of a well-known name, so a cached proxy keeps talking
to a plasmashell that is already gone.
"""

from __future__ import annotations

import unittest

import dbus

from appvol.osd import OSD_IFACE, Osd


class FakeProxy:
    """Records the calls that reach it and may fail with a given D-Bus error."""

    def __init__(self, calls: list, error: str | None = None) -> None:
        self._calls = calls
        self._error = error

    def __getattr__(self, method: str):
        def call(*args, **kwargs):
            self._calls.append((method, args, kwargs))
            if self._error is not None:
                raise dbus.DBusException("the name is not activatable", name=self._error)

        return call


class Factory:
    """Hands out prepared proxies, one per connection attempt."""

    def __init__(self, *errors: str | None) -> None:
        self.calls: list = []
        self.proxies: list[FakeProxy] = []
        self._errors = list(errors) or [None]

    def __call__(self) -> FakeProxy:
        error = self._errors[min(len(self.proxies), len(self._errors) - 1)]
        proxy = FakeProxy(self.calls, error)
        self.proxies.append(proxy)
        return proxy


STALE = "org.freedesktop.DBus.Error.ServiceUnknown"
REFUSED = "org.freedesktop.DBus.Error.AccessDenied"


class OsdTest(unittest.TestCase):
    def test_icon_call_uses_the_player_method_with_an_empty_caption(self) -> None:
        factory = Factory()
        Osd(connect=factory).volume_changed(42, icon="spotify")
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "mediaPlayerVolumeChanged")
        self.assertEqual([int(value) for value in args[:1]], [42])
        self.assertEqual(list(args[1:]), ["", "spotify"])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "iss"})

    def test_without_an_icon_the_generic_method_is_used(self) -> None:
        factory = Factory()
        Osd(connect=factory).volume_changed(42)
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "volumeChanged")
        self.assertEqual([int(value) for value in args], [42])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "i"})

    def test_a_ceiling_other_than_100_scales_the_bar(self) -> None:
        factory = Factory()
        Osd(connect=factory).volume_changed(150, icon="vesktop", name="Vesktop", maximum=150)
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "volumeChanged")
        self.assertEqual([int(value) for value in args], [150, 150])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "ii"})

    def test_a_ceiling_below_100_scales_as_well(self) -> None:
        factory = Factory()
        Osd(connect=factory).volume_changed(50, maximum=50)
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "volumeChanged")
        self.assertEqual([int(value) for value in args], [50, 50])

    def test_the_default_ceiling_keeps_the_player_method(self) -> None:
        factory = Factory()
        Osd(connect=factory).volume_changed(42, icon="spotify", name="Spotify", maximum=100)
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "mediaPlayerVolumeChanged")
        self.assertEqual(list(args[1:]), ["Spotify", "spotify"])

    def test_a_name_is_sent_as_the_caption(self) -> None:
        factory = Factory()
        Osd(connect=factory).volume_changed(42, icon="spotify", name="Spotify")
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "mediaPlayerVolumeChanged")
        self.assertEqual([int(value) for value in args[:1]], [42])
        self.assertEqual(list(args[1:]), ["Spotify", "spotify"])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "iss"})

    def test_a_name_without_an_icon_still_uses_the_player_method(self) -> None:
        factory = Factory()
        Osd(connect=factory).volume_changed(0, name="Spotify")
        method, args, _ = factory.calls[0]
        self.assertEqual(method, "mediaPlayerVolumeChanged")
        self.assertEqual(int(args[0]), 0)
        self.assertEqual(list(args[1:]), ["Spotify", ""])

    def test_text_uses_show_text(self) -> None:
        factory = Factory()
        Osd(connect=factory).text("java", "Muted")
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "showText")
        self.assertEqual(list(args), ["java", "Muted"])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "ss"})

    def test_proxy_is_reused_between_calls(self) -> None:
        factory = Factory()
        osd = Osd(connect=factory)
        osd.volume_changed(10, icon="java")
        osd.volume_changed(15, icon="java")
        self.assertEqual(len(factory.proxies), 1)
        self.assertEqual(len(factory.calls), 2)

    def test_a_stale_proxy_is_replaced_and_the_call_repeated(self) -> None:
        factory = Factory(STALE, None)
        with self.assertNoLogs("appvol.osd", level="WARNING"):
            Osd(connect=factory).volume_changed(20, icon="java")
        self.assertEqual(len(factory.proxies), 2)
        self.assertEqual(len(factory.calls), 2)

    def test_a_permanent_failure_is_reported_once(self) -> None:
        factory = Factory(STALE)
        with self.assertLogs("appvol.osd", level="WARNING") as captured:
            Osd(connect=factory).volume_changed(20, icon="java")
        self.assertEqual(len(factory.proxies), 2)
        self.assertEqual(len(captured.output), 1)
        self.assertIn("cannot show volume OSD", captured.output[0])

    def test_a_failure_a_new_proxy_cannot_fix_is_not_retried(self) -> None:
        factory = Factory(REFUSED)
        with self.assertLogs("appvol.osd", level="WARNING") as captured:
            Osd(connect=factory).text("java", "Muted")
        self.assertEqual(len(factory.proxies), 1)
        self.assertIn("cannot show text OSD", captured.output[0])

    def test_a_disabled_osd_never_touches_the_bus(self) -> None:
        factory = Factory()
        osd = Osd(enabled=False, connect=factory)
        osd.volume_changed(20, icon="java")
        osd.text("java", "Muted")
        self.assertEqual(factory.proxies, [])
        self.assertEqual(factory.calls, [])


if __name__ == "__main__":
    unittest.main()
