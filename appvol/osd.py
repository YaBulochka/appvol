"""On-screen display backends.

Plasma has an OSD of its own, on D-Bus at
``org.freedesktop.Notifications /org/kde/osdService org.kde.osdService``.  Every
other desktop, and every tiling setup with a notification daemon (dunst, mako,
swaync, GNOME Shell), answers at
``org.freedesktop.Notifications /org/freedesktop/Notifications``.  appvol picks
the first when it is there and the second otherwise, and ``config.toml`` can pin
either one.  A future backend for another desktop is one more class with the two
methods :class:`Osd` calls, so nothing outside this module has to know which
display is in use.

The Plasma proxy stays bound to the well-known name (``follow_name_owner_changes``),
and a failed call is retried once on a fresh proxy.  Both are needed because
``dbus-python`` otherwise resolves the name to the unique name of its current
owner and keeps sending there: after plasmashell restarts, a cached proxy points
at a dead connection and every call fails with ``ServiceUnknown``.

Plasma methods (verified against ``shell/osd.cpp`` of plasma-workspace and live on
Plasma 6.8):

* ``volumeChanged(percent)`` renders the generic volume icon;
* ``volumeChanged(percent, maximumPercent)`` is the same, with the progress bar
  drawn against ``maximumPercent`` instead of 100;
* ``mediaPlayerVolumeChanged(percent, name, iconName)`` renders ``iconName`` with
  the progress bar and ``name`` as the caption, and ``<name> Muted`` when the
  percent is zero;
* ``showText(iconName, text)`` renders an icon with a free-form caption.

appvol prefers the player method whenever the application icon is known, so the
OSD looks like the entry of that application on the panel.  That method pins the
bar to 100%, so a profile with a ceiling of its own falls back to the two-argument
``volumeChanged`` while the volume stays at or below 100%: a correct bar at the
price of the generic icon and the caption.  Above 100% that bar would be full
whatever the value, so appvol keeps the icon and prints the real percentage through
``showText`` instead, with no bar.  Plasma has no call that carries both a custom
ceiling and an application icon, so one of the two has to go.

The notification fallback is one notification per appvol process: every update
passes the id of the previous one as ``replaces_id``, so a held volume key moves
one notification instead of stacking a hundred.  The ``value`` hint is the
progress bar dunst, mako and GNOME Shell draw from it, and the timeout keeps the
message as short-lived as the OSD it stands in for.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import dbus

from .config import (
    OSD_BACKEND_AUTO,
    OSD_BACKEND_GNOME,
    OSD_BACKEND_NOTIFICATIONS,
    OSD_BACKEND_PLASMA,
)

log = logging.getLogger(__name__)

OSD_SERVICE = "org.freedesktop.Notifications"
OSD_PATH = "/org/kde/osdService"
OSD_IFACE = "org.kde.osdService"

NOTIFY_PATH = "/org/freedesktop/Notifications"
NOTIFY_IFACE = "org.freedesktop.Notifications"
NOTIFY_APP_NAME = "Appvol"
NOTIFY_TIMEOUT_MS = 1500

# The object the GNOME Shell extension exports.  The shell's own ShowOSD is
# callable only by gnome-settings-daemon and the portals, so appvol goes through
# its extension, which runs inside the shell and reaches the same OSD.
GNOME_SERVICE = "org.appvol.GnomeShell"
GNOME_PATH = "/org/appvol/GnomeShell"
GNOME_IFACE = "org.appvol.GnomeShell"
GNOME_FALLBACK_ICON = "audio-volume-high"

# Errors that mean "the name or the object is not there right now": a second
# attempt over a freshly resolved proxy can help.  Anything else (a bad argument,
# a refused call) would only repeat itself.
RETRYABLE = frozenset(
    {
        "org.freedesktop.DBus.Error.ServiceUnknown",
        "org.freedesktop.DBus.Error.NameHasNoOwner",
        "org.freedesktop.DBus.Error.NoReply",
        "org.freedesktop.DBus.Error.UnknownObject",
        "org.freedesktop.DBus.Error.UnknownMethod",
    }
)


class MissingService(Exception):
    """The service a backend needs is not on the session bus."""


def _connect(service: str, path: str) -> Callable[[], object]:
    """A proxy factory for one well-known name and object path."""

    def connect() -> object:
        bus = dbus.SessionBus()
        try:
            # introspect=False: every call names its interface and signature, so
            # the extra round trip is wasted, and dbus-python logs its failure at
            # ERROR when the service is simply missing.
            return bus.get_object(
                service, path, introspect=False, follow_name_owner_changes=True
            )
        except RuntimeError:
            # "no main loop": a one-shot client.  Resolving the name once is fine
            # there, the proxy lives for a single call anyway.
            return bus.get_object(service, path, introspect=False)

    return connect


def _connect_plasma() -> object:
    return _connect(OSD_SERVICE, OSD_PATH)()


def _connect_notifications() -> object:
    return _connect(OSD_SERVICE, NOTIFY_PATH)()


def _connect_gnome() -> object:
    return _connect(GNOME_SERVICE, GNOME_PATH)()


class PlasmaOsd:
    """The native on-screen display of a Plasma session."""

    def __init__(self, connect: Callable[[], object] | None = None) -> None:
        self._connect = connect or _connect_plasma
        self._object = None

    def _proxy(self, refresh: bool = False):
        if self._object is None or refresh:
            self._object = self._connect()
        return self._object

    def _call(self, method: str, signature: str, args: list, description: str) -> None:
        """Run one OSD method, retrying once after reconnecting.

        Raises :class:`MissingService` when the object or the method is not there
        even after the retry: that is what makes the caller fall back to the
        notification daemon.  Any other error is logged and swallowed, because a
        second attempt would only repeat it.
        """
        for attempt in (0, 1):
            try:
                getattr(self._proxy(refresh=attempt > 0), method)(
                    *args, dbus_interface=OSD_IFACE, signature=signature
                )
                return
            except dbus.DBusException as exc:
                missing = exc.get_dbus_name() in RETRYABLE
                if attempt or not missing:
                    if missing:
                        raise MissingService(str(exc)) from None
                    log.warning("cannot show %s OSD: %s", description, exc)
                    return
                log.debug(
                    "%s OSD failed (%s), retrying over a fresh proxy",
                    description,
                    exc.get_dbus_name(),
                )

    def volume_changed(self, value: int, icon: str = "", name: str = "", maximum: int = 100) -> None:
        """Show the volume OSD for an application.

        ``icon`` comes from :mod:`appvol.icon`, ``name`` is the caption the
        profile feature uses.  Plasma then renders the OSD like a media player
        entry, and writes ``<name> Muted`` when the value is zero.  Without an
        icon and without a name the generic volume OSD is used, so the user still
        gets feedback.

        ``maximum`` is the ceiling the progress bar is drawn against, in percent.
        A profile may allow more than 100%: Plasma then draws the bar against
        that ceiling and prints the real percentage. ``mediaPlayerVolumeChanged``
        pins the bar to 100%, so any other ceiling has to go through
        ``volumeChanged(percent, maximumPercent)``.  That method draws the generic
        volume icon and carries no caption, which is the price of a correct bar.

        Above 100% that bar is full whatever the value, so it buys nothing and
        still costs the icon.  Plasma has no call that carries both a custom
        ceiling and an application icon, so appvol keeps the icon and prints the
        real percentage through :meth:`text`, with no bar.
        """
        percent = dbus.Int32(int(value))
        limit = dbus.Int32(int(maximum))
        if percent > 100 and icon:
            self.text(icon, f"{int(percent)}%")
        elif limit != 100:
            self._call("volumeChanged", "ii", [percent, limit], "volume")
        elif icon or name:
            # Explicit signature: the interface also declares plain
            # volumeChanged overloads and dbus-python picks the wrong one when it
            # has to guess.
            self._call("mediaPlayerVolumeChanged", "iss", [percent, str(name), str(icon)], "volume")
        else:
            self._call("volumeChanged", "i", [percent], "volume")

    def text(self, icon: str, text: str) -> None:
        """Show the application icon with a short status caption."""
        self._call("showText", "ss", [str(icon), str(text)], "text")


class GnomeOsd:
    """The GNOME Shell OSD, reached through the appvol extension.

    The shell's own ``org.gnome.Shell.ShowOSD`` refuses every caller that is not
    gnome-settings-daemon or a portal backend, so the extension exports the same
    look under ``org.appvol.GnomeShell`` and calls
    ``Main.osdWindowManager`` from inside the shell.  The message is the one the
    shell draws: an icon, a label and a bar whose level runs to ``max_level``,
    with a negative level and no label for a plain status.
    """

    def __init__(self, connect: Callable[[], object] | None = None) -> None:
        self._connect = connect or _connect_gnome
        self._object = None

    def _proxy(self, refresh: bool = False):
        if self._object is None or refresh:
            self._object = self._connect()
        return self._object

    def _call(self, icon: str, label: str, level: float, max_level: float) -> None:
        """Run one ``Show`` call, retrying once after the extension reloads."""
        for attempt in (0, 1):
            try:
                self._proxy(refresh=attempt > 0).Show(
                    str(icon or GNOME_FALLBACK_ICON),
                    str(label),
                    dbus.Double(level),
                    dbus.Double(max_level),
                    dbus_interface=GNOME_IFACE,
                    signature="ssdd",
                )
                return
            except dbus.DBusException as exc:
                missing = exc.get_dbus_name() in RETRYABLE
                if attempt or not missing:
                    if missing:
                        raise MissingService(str(exc)) from None
                    log.warning("cannot show the GNOME OSD: %s", exc)
                    return
                log.debug(
                    "GNOME OSD failed (%s), retrying over a fresh proxy",
                    exc.get_dbus_name(),
                )

    def volume_changed(self, value: int, icon: str = "", name: str = "", maximum: int = 100) -> None:
        """Show the volume of an application the way the shell does.

        ``level`` and ``max_level`` are fractions of 100%, the scale the shell's
        ``BarLevel`` declares (0 to 2, which leaves room for a 150% ceiling).  A
        percentage there is out of range and the eased update would be dropped,
        which shows up as an OSD stuck on its first value.
        """
        percent = int(value)
        # Zero is this codebase's mute message, the convention the Plasma caption
        # follows.  The shell has no "<name> Muted" form, so the label says it and
        # the bar goes away.
        muted = percent == 0
        label = "Muted" if muted else str(name)
        level = -1.0 if muted else percent / 100.0
        self._call(icon, label, level, float(maximum) / 100.0)

    def text(self, icon: str, text: str) -> None:
        """Show a short status, without a bar."""
        self._call(icon, str(text), -1.0, -1.0)


class NotificationOsd:
    """The freedesktop notification daemon, the fallback of every desktop.

    It is what dunst, mako, swaync, GNOME Shell and Plasma's own notification
    service implement, so the same call reaches a native-looking popup everywhere
    that has one.
    """

    def __init__(self, connect: Callable[[], object] | None = None) -> None:
        self._connect = connect or _connect_notifications
        self._object = None
        self._replaces_id = 0

    def _proxy(self, refresh: bool = False):
        if self._object is None or refresh:
            self._object = self._connect()
        return self._object

    def _show(self, summary: str, body: str, icon: str, value: int | None = None) -> None:
        hints = dbus.Dictionary({"urgency": dbus.Byte(0)}, signature="sv")
        if value is not None:
            hints["value"] = dbus.Int32(max(0, min(100, int(value))))
        args = [
            NOTIFY_APP_NAME,
            dbus.UInt32(self._replaces_id),
            str(icon),
            str(summary),
            str(body),
            dbus.Array([], signature="s"),
            hints,
            dbus.Int32(NOTIFY_TIMEOUT_MS),
        ]
        for attempt in (0, 1):
            try:
                proxy = self._proxy(refresh=attempt > 0)
                answer = proxy.Notify(*args, dbus_interface=NOTIFY_IFACE, signature="susssasa{sv}i")
                self._replaces_id = int(answer)
                return
            except dbus.DBusException as exc:
                if attempt or exc.get_dbus_name() not in RETRYABLE:
                    log.warning("cannot show the OSD as a notification: %s", exc)
                    return
                log.debug(
                    "notification OSD failed (%s), retrying over a fresh proxy",
                    exc.get_dbus_name(),
                )

    def volume_changed(self, value: int, icon: str = "", name: str = "", maximum: int = 100) -> None:
        """Show the volume as a notification bearing the application's icon."""
        percent = int(value)
        # Plasma answers "<name> Muted" at zero, so the fallback says the same.
        muted = percent == 0 and bool(name)
        self._show(str(name) or "Volume", "Muted" if muted else f"{percent}%", icon, percent)

    def text(self, icon: str, text: str) -> None:
        """Show a short status as the headline of a notification."""
        self._show(str(text), "", icon)


class Osd:
    """The on-screen display of the session, native first, notifications after."""

    # The order ``auto`` tries: the Plasma OSD, then the GNOME one, then the
    # notification daemon every desktop has.  Each miss costs one failed call on
    # the session bus, so a GNOME session does not pay for Plasma twice.
    AUTO_ORDER = (OSD_BACKEND_PLASMA, OSD_BACKEND_GNOME, OSD_BACKEND_NOTIFICATIONS)

    def __init__(
        self,
        enabled: bool = True,
        backend: str = OSD_BACKEND_AUTO,
        connect: Callable[[], object] | None = None,
        notify: Callable[[], object] | None = None,
        gnome: Callable[[], object] | None = None,
    ) -> None:
        self.enabled = enabled
        self.backend = backend
        self.backends: dict[str, PlasmaOsd | GnomeOsd | NotificationOsd] = {
            OSD_BACKEND_PLASMA: PlasmaOsd(connect),
            OSD_BACKEND_GNOME: GnomeOsd(gnome),
            OSD_BACKEND_NOTIFICATIONS: NotificationOsd(notify),
        }
        self.order = self.AUTO_ORDER if backend == OSD_BACKEND_AUTO else (backend,)

    def _show(self, call) -> None:
        """Ask the first backend that answers, in the order of the session."""
        for name in self.order:
            try:
                call(self.backends[name])
                return
            except MissingService as exc:
                if len(self.order) == 1:
                    log.warning("cannot show the OSD, %s is not on the bus: %s", name, exc)
                    return
                log.debug("the %s OSD is not on the bus: %s", name, exc)

    def volume_changed(self, value: int, icon: str = "", name: str = "", maximum: int = 100) -> None:
        if not self.enabled:
            return
        self._show(
            lambda backend: backend.volume_changed(value, icon=icon, name=name, maximum=maximum)
        )

    def text(self, icon: str, text: str) -> None:
        if not self.enabled:
            return
        self._show(lambda backend: backend.text(icon, text))
