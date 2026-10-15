"""The D-Bus side of the GUI.

Every read and every write of the window and the tray goes through
``org.appvol.Daemon``, so the daemon stays the only writer of ``profiles.toml``
and the only component that talks to PipeWire and KWin.  The calls live in one
class with an injectable connection, which keeps them testable without a session
bus.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import dbus

from ..profiles import ACTIVE_ID

log = logging.getLogger(__name__)

BUS_NAME = "org.appvol.Daemon"
OBJECT_PATH = "/org/appvol/Daemon"
IFACE = "org.appvol.Daemon"

NOT_RUNNING = "appvold is not running"


class DaemonError(RuntimeError):
    """The daemon is unreachable or refused the call."""


def session_proxy():
    """Proxy for the daemon, bound to the well-known name."""
    bus = dbus.SessionBus()
    return dbus.Interface(bus.get_object(BUS_NAME, OBJECT_PATH), IFACE)


class Client:
    """Calls ``org.appvol.Daemon`` and decodes the JSON payloads."""

    def __init__(self, connect: Callable[[], Any] | None = None) -> None:
        self._connect = connect or session_proxy
        self._proxy = None

    def call(self, method: str, *args):
        """Call ``method`` and return the decoded answer.

        A failed call drops the cached proxy: the name owner may have changed,
        and dbus-python binds a proxy to the unique name it saw first.
        """
        try:
            answer = getattr(self._proxy_or_connect(), method)(*args)
        except dbus.DBusException as exc:
            self._proxy = None
            name = exc.get_dbus_name()
            if name == "org.freedesktop.DBus.Error.ServiceUnknown":
                raise DaemonError(NOT_RUNNING) from None
            if name == "org.appvol.Error.InvalidArgument":
                raise DaemonError(str(exc.get_dbus_message())) from None
            raise DaemonError(str(exc)) from None
        try:
            return json.loads(answer)
        except (TypeError, ValueError) as exc:
            raise DaemonError(f"cannot read the answer of {method}: {exc}") from None

    def _proxy_or_connect(self):
        if self._proxy is None:
            self._proxy = self._connect()
        return self._proxy

    # -- reads -------------------------------------------------------------

    def overview(self) -> dict:
        """Every profile with its live state, the panel the window draws."""
        return self.call("Overview")

    def applications(self) -> dict:
        """The applications playing right now, for the editor."""
        return self.call("Applications")

    def profiles(self) -> dict:
        """The profiles and which one is current, without touching PipeWire."""
        return self.call("Profiles")

    # -- writes ------------------------------------------------------------

    def switch_profile(self, profile_id: str, osd: bool = False) -> dict:
        """Make a profile current; ``osd`` asks for the OSD feedback."""
        return self.call("SwitchProfile", str(profile_id), bool(osd))

    def toggle_profile(self, profile_id: str) -> dict:
        """The toggle the profile keys do."""
        return self.call("ToggleProfile", str(profile_id))

    def set_volume(self, profile_id: str, percent: float) -> dict:
        """Set the volume of a profile; silent, for a slider."""
        return self.call("SetVolume", str(profile_id), dbus.Double(float(percent)))

    def set_mute(self, profile_id: str, muted: bool) -> dict:
        """Set mute on a profile; silent, for a switch."""
        return self.call("SetMute", str(profile_id), bool(muted))

    def set_step(self, profile_id: str, percent: float) -> dict:
        """Set the step of a profile; the built-in id sets the global step."""
        return self.call("SetStep", str(profile_id), dbus.Double(float(percent)))

    def adjust(self, direction: str, step: float = 0.0) -> dict:
        """One step up or down on the current profile, with the OSD."""
        return self.call("AdjustTarget", "", str(direction), dbus.Double(float(step)))

    def toggle_mute(self, profile_id: str = "") -> dict:
        """Toggle mute, with the OSD."""
        return self.call("ToggleMuteTarget", str(profile_id))

    def add_profile(
        self,
        profile_id: str,
        name: str = "",
        include: Any = (),
        exclude: Any = (),
        step: float = 0.0,
        max_volume: float = 0.0,
        icon: str = "",
        osd_name: str = "never",
    ) -> dict:
        """Create or replace a profile."""
        return self.call(
            "AddProfile",
            str(profile_id),
            str(name),
            [str(value) for value in include],
            [str(value) for value in exclude],
            dbus.Double(float(step)),
            dbus.Double(float(max_volume)),
            str(icon),
            str(osd_name),
        )

    def remove_profile(self, profile_id: str) -> dict:
        """Remove a profile and its shortcut action."""
        return self.call("RemoveProfile", str(profile_id))

    def reload(self) -> dict:
        """Read ``profiles.toml`` again, after a hand edit."""
        return self.call("Reload")


__all__ = ["ACTIVE_ID", "Client", "DaemonError", "NOT_RUNNING", "session_proxy"]
