"""KDE OSD glue.

Plasma exposes its on-screen display over D-Bus at
``org.freedesktop.Notifications /org/kde/osdService org.kde.osdService``.

The proxy stays bound to the well-known name (``follow_name_owner_changes``), and
a failed call is retried once on a fresh proxy.  Both are needed because
``dbus-python`` otherwise resolves the name to the unique name of its current
owner and keeps sending there: after plasmashell restarts, a cached proxy points
at a dead connection and every call fails with ``ServiceUnknown``.

Methods (verified against ``shell/osd.cpp`` of plasma-workspace and live on
Plasma 6.8):

* ``volumeChanged(percent)`` renders the generic volume icon;
* ``mediaPlayerVolumeChanged(percent, name, iconName)`` renders ``iconName`` with
  the progress bar and ``name`` as the caption, and ``<name> Muted`` when the
  percent is zero;
* ``showText(iconName, text)`` renders an icon with a free-form caption.

appvol prefers the second method whenever the application icon is known, so the
OSD looks like the entry of that application on the panel.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import dbus

log = logging.getLogger(__name__)

OSD_SERVICE = "org.freedesktop.Notifications"
OSD_PATH = "/org/kde/osdService"
OSD_IFACE = "org.kde.osdService"

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


def _connect():
    """Proxy for the OSD service, bound to the well-known name."""
    bus = dbus.SessionBus()
    try:
        return bus.get_object(OSD_SERVICE, OSD_PATH, follow_name_owner_changes=True)
    except RuntimeError:
        # "no main loop": a one-shot client.  Resolving the name once is fine
        # there, the proxy lives for a single call anyway.
        return bus.get_object(OSD_SERVICE, OSD_PATH)


class Osd:
    """Thin wrapper around the Plasma OSD service."""

    def __init__(self, enabled: bool = True, connect: Callable[[], object] | None = None) -> None:
        self.enabled = enabled
        self._connect = connect or _connect
        self._object = None

    def _proxy(self, refresh: bool = False):
        if self._object is None or refresh:
            self._object = self._connect()
        return self._object

    def _call(self, method: str, signature: str, args: list, description: str) -> None:
        """Run one OSD method, retrying once after reconnecting."""
        if not self.enabled:
            return
        for attempt in (0, 1):
            try:
                getattr(self._proxy(refresh=attempt > 0), method)(
                    *args, dbus_interface=OSD_IFACE, signature=signature
                )
                return
            except dbus.DBusException as exc:
                if attempt or exc.get_dbus_name() not in RETRYABLE:
                    log.warning("cannot show %s OSD: %s", description, exc)
                    return
                log.debug(
                    "%s OSD failed (%s), retrying over a fresh proxy",
                    description,
                    exc.get_dbus_name(),
                )

    def volume_changed(self, value: int, icon: str = "", name: str = "") -> None:
        """Show the volume OSD for an application.

        ``icon`` comes from :mod:`appvol.icon`, ``name`` is the caption the
        profile feature uses.  Plasma then renders the OSD like a media player
        entry, and writes ``<name> Muted`` when the value is zero.  Without an
        icon and without a name the generic volume OSD is used, so the user still
        gets feedback.
        """
        percent = dbus.Int32(int(value))
        if icon or name:
            # Explicit signature: the interface also declares plain
            # volumeChanged overloads and dbus-python picks the wrong one when it
            # has to guess.
            self._call("mediaPlayerVolumeChanged", "iss", [percent, str(name), str(icon)], "volume")
        else:
            self._call("volumeChanged", "i", [percent], "volume")

    def text(self, icon: str, text: str) -> None:
        """Show the application icon with a short status caption."""
        self._call("showText", "ss", [str(icon), str(text)], "text")
