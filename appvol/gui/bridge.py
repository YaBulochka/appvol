"""The QML bridge: the properties and slots the window and the tray use.

Everything the QML side can do lands here, and every call ends up in
:class:`appvol.gui.client.Client`.  Keeping the logic in Python leaves the QML
files declarative and short, and decides the states the window can be in (no
daemon, no profiles, nothing playing) in one place.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import Property, QObject, QProcess, Signal, Slot

from .. import __version__
from ..profiles import ACTIVE_ID, action_name
from .client import NOT_RUNNING, Client, DaemonError
from .shortcuts import ShortcutKeys

log = logging.getLogger(__name__)

SETTINGS_COMMANDS = (
    ("systemsettings", ["kcm_keys"]),
    ("kcmshell6", ["kcm_keys"]),
)


class Bridge(QObject):
    """The daemon, seen from QML."""

    profilesChanged = Signal()
    applicationsChanged = Signal()
    configChanged = Signal()
    errorChanged = Signal()

    def __init__(
        self,
        client: Client | None = None,
        keys: ShortcutKeys | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client or Client()
        self.keys = keys or ShortcutKeys()
        self._profiles: list[dict] = []
        self._applications: list[dict] = []
        self._current = ACTIVE_ID
        self._idle_timeout = 0.0
        self._config: dict = {}
        self._error = ""
        self._running = True

    # -- properties --------------------------------------------------------

    @Property("QVariantList", notify=profilesChanged)
    def profiles(self) -> list:
        """Every profile, the built-in Active one first."""
        return self._profiles

    @Property("QVariantList", notify=applicationsChanged)
    def applications(self) -> list:
        """Applications that are playing right now."""
        return self._applications

    @Property(str, notify=profilesChanged)
    def current(self) -> str:
        """Id of the profile the volume keys act on."""
        return self._current

    @Property(float, notify=configChanged)
    def idleTimeout(self) -> float:
        """Seconds before a profile returns to Active; zero means never."""
        return self._idle_timeout

    @Property("QVariantMap", notify=configChanged)
    def config(self) -> dict:
        """Global defaults the profiles fall back to."""
        return self._config

    @Property(bool, notify=configChanged)
    def osdShowName(self) -> bool:
        """Whether the OSD captions the application name; one checkbox for all profiles."""
        return bool(self._config.get("osd_show_name", False))

    @Property(str, notify=configChanged)
    def mode(self) -> str:
        """What the volume keys cycle: the profiles, or the running applications."""
        return str(self._config.get("mode") or "profiles")

    @Property(str, notify=errorChanged)
    def error(self) -> str:
        """The last failure, empty while everything works."""
        return self._error

    @Property(bool, notify=errorChanged)
    def daemonRunning(self) -> bool:
        """False when the last call found no ``appvold`` on the bus."""
        return self._running

    @Property(str, constant=True)
    def version(self) -> str:
        """The version shown in the window footer."""
        return __version__

    # -- slots -------------------------------------------------------------

    @Slot()
    def refresh(self) -> None:
        """Reload the panel and the list of playing applications."""
        overview = self._guard(self.client.overview)
        if overview is not None:
            self._apply_overview(overview)

        applications = self._guard(self.client.applications)
        if applications is not None:
            self._applications = list(applications.get("applications", []))
            self.applicationsChanged.emit()

    @Slot(str, bool)
    def selectProfile(self, profile_id: str, osd: bool = False) -> None:
        """Make a profile current.

        The window passes ``osd=False``, because it shows the change itself; the
        tray passes ``True``, so a switch from the menu answers like a key press.
        """
        self._write(self.client.switch_profile, str(profile_id), bool(osd))

    @Slot(str, float)
    def setVolume(self, profile_id: str, percent: float) -> None:
        """Set the volume of a profile, from a slider."""
        self._write(self.client.set_volume, str(profile_id), float(percent))

    @Slot(str, bool)
    def setMute(self, profile_id: str, muted: bool) -> None:
        """Set mute on a profile, from a switch."""
        self._write(self.client.set_mute, str(profile_id), bool(muted))

    @Slot(str, float)
    def setStep(self, profile_id: str, percent: float) -> None:
        """Set the step of a profile, from the row of the list.

        The built-in Active profile has no entry in ``profiles.toml``: its step is
        the global one, and the daemon writes it to ``config.toml``.
        """
        self._write(self.client.set_step, str(profile_id), float(percent))

    @Slot(bool)
    def setOsdShowName(self, show: bool) -> None:
        """Show or hide the application name in the OSD, from the window checkbox."""
        self._write(self.client.set_osd_show_name, bool(show))

    @Slot(str)
    def setMode(self, mode: str) -> None:
        """Cycle the profiles or the running applications, from the window switch."""
        self._write(self.client.set_mode, str(mode))

    @Slot(str, str, "QVariantList", "QVariantList", float, float, str)
    def saveProfile(
        self,
        profile_id: str,
        name: str,
        include: list,
        exclude: list,
        step: float,
        max_volume: float,
        icon: str,
    ) -> None:
        """Create or replace a profile, from the editor."""
        self._write(
            self.client.add_profile,
            str(profile_id),
            str(name),
            list(include),
            list(exclude),
            float(step),
            float(max_volume),
            str(icon),
        )

    @Slot(str)
    def removeProfile(self, profile_id: str) -> None:
        """Remove a profile and its key binding."""
        self._write(self.client.remove_profile, str(profile_id))

    @Slot()
    def reload(self) -> None:
        """Read ``profiles.toml`` again, after a hand edit."""
        self._write(self.client.reload)

    @Slot(str)
    def adjust(self, direction: str) -> None:
        """One step on the current profile, from the tray, with the OSD."""
        self._write(self.client.adjust, str(direction))

    @Slot()
    def toggleMute(self) -> None:
        """Toggle mute on the current profile, from the tray, with the OSD."""
        self._write(self.client.toggle_mute)

    @Slot()
    def openShortcuts(self) -> None:
        """Open System Settings on the shortcut list, where the profile keys live."""
        for program, arguments in SETTINGS_COMMANDS:
            result = QProcess.startDetached(program, arguments)
            started = result[0] if isinstance(result, tuple) else bool(result)
            if started:
                return
        self._set_error("cannot open System Settings, run `systemsettings kcm_keys` yourself")

    # -- internals ---------------------------------------------------------

    def _apply_overview(self, overview: dict) -> None:
        self._current = str(overview.get("current") or ACTIVE_ID)
        self._idle_timeout = float(overview.get("idle_timeout") or 0.0)
        self._config = dict(overview.get("config") or {})

        profiles = []
        for profile in overview.get("profiles", []):
            entry = dict(profile)
            entry["key"] = self._key_of(entry)
            profiles.append(entry)
        self._profiles = profiles

        self.profilesChanged.emit()
        self.configChanged.emit()

    def _key_of(self, profile: dict) -> str:
        """The key bound to the profile action, for the line under its name.

        The Active profile has no action of its own: it is what the three
        global volume keys do, so it reports no key.
        """
        if profile.get("builtin"):
            return ""
        name = str(profile.get("name") or profile.get("id") or "")
        return self.keys.text(action_name(str(profile.get("id"))), name)

    def _write(self, call: Callable[..., Any], *args) -> bool:
        """Run a write, refresh the panel when it worked, keep the error when not."""
        if self._guard(call, *args) is None:
            return False
        self.refresh()
        return True

    def _guard(self, call: Callable[..., Any], *args):
        """Run a daemon call, turning a failure into the error banner."""
        try:
            result = call(*args)
        except DaemonError as exc:
            self._set_error(str(exc))
            return None
        self._set_error("")
        return result

    def _set_error(self, message: str) -> None:
        running = message != NOT_RUNNING
        if message == self._error and running == self._running:
            return
        self._error = message
        self._running = running
        if message:
            log.warning("gui: %s", message)
        self.errorChanged.emit()
