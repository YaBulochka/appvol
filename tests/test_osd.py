"""The OSD wrapper has to survive a plasmashell restart, and to keep working
where there is no Plasma OSD at all.

The regression the first group pins down: ``dbus-python`` binds a proxy to the
unique name of the current owner of a well-known name, so a cached proxy keeps
talking to a plasmashell that is already gone.  The second group covers the
fallback: a session without ``org.kde.osdService`` shows the same message through
the freedesktop notification daemon.
"""

from __future__ import annotations

import unittest

import dbus

from appvol.osd import GNOME_IFACE, NOTIFY_IFACE, NOTIFY_TIMEOUT_MS, OSD_IFACE, Osd


class FakeProxy:
    """Records the calls that reach it and may fail with a given D-Bus error."""

    def __init__(self, calls: list, error: str | None = None, answer=None) -> None:
        self._calls = calls
        self._error = error
        self._answer = answer

    def __getattr__(self, method: str):
        def call(*args, **kwargs):
            self._calls.append((method, args, kwargs))
            if self._error is not None:
                raise dbus.DBusException("the name is not activatable", name=self._error)
            return self._answer

        return call


class Factory:
    """Hands out prepared proxies, one per connection attempt."""

    def __init__(self, *errors: str | None, answer=None) -> None:
        self.calls: list = []
        self.proxies: list[FakeProxy] = []
        self._errors = list(errors) or [None]
        self._answer = answer

    def __call__(self) -> FakeProxy:
        error = self._errors[min(len(self.proxies), len(self._errors) - 1)]
        proxy = FakeProxy(self.calls, error, self._answer)
        self.proxies.append(proxy)
        return proxy


def notifications() -> Factory:
    """A working notification daemon: ``Notify`` answers with an id."""
    return Factory(answer=dbus.UInt32(7))


STALE = "org.freedesktop.DBus.Error.ServiceUnknown"
REFUSED = "org.freedesktop.DBus.Error.AccessDenied"


class OsdTest(unittest.TestCase):
    """The Plasma path, and the methods it picks for each kind of value."""

    def osd(self, factory, notify=None, **kwargs) -> Osd:
        return Osd(connect=factory, notify=notify or notifications(), **kwargs)

    def test_icon_call_uses_the_player_method_with_an_empty_caption(self) -> None:
        factory = Factory()
        self.osd(factory).volume_changed(42, icon="spotify")
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "mediaPlayerVolumeChanged")
        self.assertEqual([int(value) for value in args[:1]], [42])
        self.assertEqual(list(args[1:]), ["", "spotify"])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "iss"})

    def test_without_an_icon_the_generic_method_is_used(self) -> None:
        factory = Factory()
        self.osd(factory).volume_changed(42)
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "volumeChanged")
        self.assertEqual([int(value) for value in args], [42])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "i"})

    def test_a_ceiling_other_than_100_scales_the_bar(self) -> None:
        factory = Factory()
        self.osd(factory).volume_changed(80, icon="vesktop", name="Vesktop", maximum=150)
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "volumeChanged")
        self.assertEqual([int(value) for value in args], [80, 150])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "ii"})

    def test_a_ceiling_below_100_scales_as_well(self) -> None:
        factory = Factory()
        self.osd(factory).volume_changed(50, maximum=50)
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "volumeChanged")
        self.assertEqual([int(value) for value in args], [50, 50])

    def test_above_100_keeps_the_application_icon_without_a_bar(self) -> None:
        factory = Factory()
        self.osd(factory).volume_changed(150, icon="vesktop", name="Vesktop", maximum=150)
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "showText")
        self.assertEqual(list(args), ["vesktop", "150%"])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "ss"})

    def test_above_100_without_an_icon_falls_back_to_the_ceiling_bar(self) -> None:
        factory = Factory()
        self.osd(factory).volume_changed(150, maximum=150)
        method, args, _ = factory.calls[0]
        self.assertEqual(method, "volumeChanged")
        self.assertEqual([int(value) for value in args], [150, 150])

    def test_exactly_100_still_scales_the_bar(self) -> None:
        factory = Factory()
        self.osd(factory).volume_changed(100, icon="vesktop", maximum=150)
        method, args, _ = factory.calls[0]
        self.assertEqual(method, "volumeChanged")
        self.assertEqual([int(value) for value in args], [100, 150])

    def test_the_default_ceiling_keeps_the_player_method(self) -> None:
        factory = Factory()
        self.osd(factory).volume_changed(42, icon="spotify", name="Spotify", maximum=100)
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "mediaPlayerVolumeChanged")
        self.assertEqual(list(args[1:]), ["Spotify", "spotify"])

    def test_a_name_is_sent_as_the_caption(self) -> None:
        factory = Factory()
        self.osd(factory).volume_changed(42, icon="spotify", name="Spotify")
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "mediaPlayerVolumeChanged")
        self.assertEqual([int(value) for value in args[:1]], [42])
        self.assertEqual(list(args[1:]), ["Spotify", "spotify"])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "iss"})

    def test_a_name_without_an_icon_still_uses_the_player_method(self) -> None:
        factory = Factory()
        self.osd(factory).volume_changed(0, name="Spotify")
        method, args, _ = factory.calls[0]
        self.assertEqual(method, "mediaPlayerVolumeChanged")
        self.assertEqual(int(args[0]), 0)
        self.assertEqual(list(args[1:]), ["Spotify", ""])

    def test_text_uses_show_text(self) -> None:
        factory = Factory()
        self.osd(factory).text("java", "Muted")
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "showText")
        self.assertEqual(list(args), ["java", "Muted"])
        self.assertEqual(kwargs, {"dbus_interface": OSD_IFACE, "signature": "ss"})

    def test_proxy_is_reused_between_calls(self) -> None:
        factory = Factory()
        osd = self.osd(factory)
        osd.volume_changed(10, icon="java")
        osd.volume_changed(15, icon="java")
        self.assertEqual(len(factory.proxies), 1)
        self.assertEqual(len(factory.calls), 2)

    def test_a_stale_proxy_is_replaced_and_the_call_repeated(self) -> None:
        factory = Factory(STALE, None)
        notify = notifications()
        with self.assertNoLogs("appvol.osd", level="WARNING"):
            self.osd(factory, notify).volume_changed(20, icon="java")
        self.assertEqual(len(factory.proxies), 2)
        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(notify.calls, [])

    def test_a_disabled_osd_never_touches_the_bus(self) -> None:
        factory = Factory()
        notify = notifications()
        osd = self.osd(factory, notify, enabled=False)
        osd.volume_changed(20, icon="java")
        osd.text("java", "Muted")
        self.assertEqual(factory.proxies, [])
        self.assertEqual(notify.proxies, [])


class NotificationFallbackTest(unittest.TestCase):
    """A desktop without the Plasma OSD still gets feedback."""

    def osd(self, plasma, notify, gnome=None, **kwargs) -> Osd:
        return Osd(connect=plasma, notify=notify, gnome=gnome or Factory(STALE), **kwargs)

    def notify_args(self, factory: Factory) -> tuple:
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "Notify")
        self.assertEqual(kwargs, {"dbus_interface": NOTIFY_IFACE, "signature": "susssasa{sv}i"})
        return args

    def test_a_missing_plasma_osd_shows_a_notification(self) -> None:
        plasma, notify = Factory(STALE), notifications()
        self.osd(plasma, notify).volume_changed(42, icon="spotify", name="Spotify")

        app_name, _replace, icon, summary, body, _actions, hints, timeout = self.notify_args(notify)
        self.assertEqual((str(app_name), int(_replace)), ("Appvol", 0))
        self.assertEqual((str(icon), str(summary), str(body)), ("spotify", "Spotify", "42%"))
        self.assertEqual(int(hints["value"]), 42)
        self.assertEqual(int(timeout), NOTIFY_TIMEOUT_MS)
        self.assertEqual(len(plasma.proxies), 2)

    def test_the_fallback_replaces_its_own_notification(self) -> None:
        plasma, notify = Factory(STALE), notifications()
        osd = self.osd(plasma, notify)
        osd.volume_changed(40, icon="spotify")
        osd.volume_changed(45, icon="spotify")

        first = int(self.notify_args(notify)[1])
        second = int(notify.calls[1][1][1])
        self.assertEqual(first, 0)
        self.assertEqual(second, 7)

    def test_mute_reads_like_the_plasma_caption(self) -> None:
        plasma, notify = Factory(STALE), notifications()
        self.osd(plasma, notify).volume_changed(0, icon="spotify", name="Spotify")

        _app, _replace, _icon, summary, body = self.notify_args(notify)[:5]
        self.assertEqual((str(summary), str(body)), ("Spotify", "Muted"))

    def test_a_status_line_becomes_the_headline(self) -> None:
        plasma, notify = Factory(STALE), notifications()
        self.osd(plasma, notify).text("java", "Muted")

        _app, _replace, icon, summary, body = self.notify_args(notify)[:5]
        self.assertEqual((str(icon), str(summary), str(body)), ("java", "Muted", ""))

    def test_a_fallback_is_quiet(self) -> None:
        plasma, notify = Factory(STALE), notifications()
        osd = self.osd(plasma, notify)
        with self.assertNoLogs("appvol.osd", level="WARNING"):
            osd.volume_changed(40, icon="spotify")
            osd.volume_changed(45, icon="spotify")

        self.assertEqual(len(notify.calls), 2)

    def test_plasma_wins_again_as_soon_as_it_answers(self) -> None:
        # Two failed attempts (the first call and its retry), then the service
        # comes back: the next key press goes to the OSD again, not to a popup.
        plasma, notify = Factory(STALE, STALE, None), notifications()
        osd = self.osd(plasma, notify)

        osd.volume_changed(40, icon="spotify")
        self.assertEqual(len(notify.calls), 1)

        osd.volume_changed(45, icon="spotify")
        self.assertEqual(len(notify.calls), 1)
        self.assertEqual(plasma.calls[-1][0], "mediaPlayerVolumeChanged")

    def test_a_refused_plasma_call_does_not_fall_back(self) -> None:
        plasma, notify = Factory(REFUSED), notifications()
        with self.assertLogs("appvol.osd", level="WARNING") as captured:
            self.osd(plasma, notify).text("java", "Muted")

        self.assertEqual(len(plasma.proxies), 1)
        self.assertEqual(notify.calls, [])
        self.assertIn("cannot show text OSD", captured.output[0])

    def test_a_pinned_plasma_backend_never_falls_back(self) -> None:
        plasma, notify = Factory(STALE), notifications()
        with self.assertLogs("appvol.osd", level="WARNING") as captured:
            self.osd(plasma, notify, backend="plasma").volume_changed(20, icon="java")

        self.assertEqual(notify.calls, [])
        self.assertIn("plasma is not on the bus", captured.output[0])

    def test_a_pinned_notification_backend_skips_plasma(self) -> None:
        plasma, notify = Factory(), notifications()
        self.osd(plasma, notify, backend="notifications").volume_changed(42, icon="spotify")

        self.assertEqual(plasma.calls, [])
        self.assertEqual(len(notify.calls), 1)


class GnomeOsdTest(unittest.TestCase):
    """The GNOME extension draws the shell's own OSD, so the daemon sends the
    same three things the shell draws: an icon, a label and a bar."""

    def show(self, factory: Factory) -> tuple:
        method, args, kwargs = factory.calls[0]
        self.assertEqual(method, "Show")
        self.assertEqual(kwargs, {"dbus_interface": GNOME_IFACE, "signature": "ssdd"})
        return args

    def test_a_gnome_session_uses_the_extension_when_plasma_is_missing(self) -> None:
        plasma, gnome, notify = Factory(STALE), Factory(), notifications()
        Osd(connect=plasma, gnome=gnome, notify=notify).volume_changed(
            42, icon="spotify", name="Spotify", maximum=150
        )

        icon, label, level, maximum = self.show(gnome)
        self.assertEqual((str(icon), str(label)), ("spotify", "Spotify"))
        self.assertEqual((float(level), float(maximum)), (0.42, 1.5))
        self.assertEqual(notify.calls, [])

    def test_a_mute_drops_the_bar_and_says_so(self) -> None:
        gnome = Factory()
        Osd(gnome=gnome, backend="gnome").volume_changed(0, icon="spotify", name="Spotify")

        icon, label, level, _maximum = self.show(gnome)
        self.assertEqual((str(icon), str(label)), ("spotify", "Muted"))
        self.assertEqual(float(level), -1.0)

    def test_a_status_needs_no_bar(self) -> None:
        gnome = Factory()
        Osd(gnome=gnome, backend="gnome").text("java", "no stream")

        icon, label, level, _maximum = self.show(gnome)
        self.assertEqual((str(icon), str(label)), ("java", "no stream"))
        self.assertEqual(float(level), -1.0)

    def test_a_missing_icon_gets_the_volume_one(self) -> None:
        gnome = Factory()
        Osd(gnome=gnome, backend="gnome").text("", "Muted")

        self.assertEqual(str(self.show(gnome)[0]), "audio-volume-high")

    def test_without_the_extension_notifications_are_used(self) -> None:
        plasma, gnome, notify = Factory(STALE), Factory(STALE), notifications()
        Osd(connect=plasma, gnome=gnome, notify=notify).volume_changed(42, icon="spotify")

        self.assertEqual(len(gnome.proxies), 2)
        self.assertEqual(len(notify.calls), 1)


if __name__ == "__main__":
    unittest.main()
