"""The QML bridge: the properties and slots the window uses.

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
from ..apps import Application, matching_applications
from ..icon import resolve as resolve_icon, theme_icon_names
from ..profiles import ACTIVE_ID, Profile, action_name, id_from_name
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
        flag stays for a caller that wants the OSD feedback of a key press.
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

    @Slot(str, int, result="QVariantList")
    def searchIcons(self, query: str, limit: int = 240) -> list:
        """Icon names of the theme that contain ``query``, for the editor's picker."""
        names = theme_icon_names()
        needle = str(query).strip().lower()
        if needle:
            names = tuple(name for name in names if needle in name.lower())
        if limit > 0:
            names = names[:limit]
        return list(names)

    @Slot("QVariantList", "QVariantList", result=str)
    def profileIcon(self, include: list, exclude: list) -> str:
        """The automatic icon of a draft profile: its first include, else exclude.

        The editor shows this while no icon is chosen, so the button previews
        what the daemon resolves once the profile is saved.  A playing
        application answers with its own icon; a name that is not playing falls
        back to the ``.desktop`` file of the identifier.
        """
        first = ""
        if include:
            first = str(include[0])
        elif exclude:
            first = str(exclude[0])
        return self._icon_of(first)

    @Slot(str, result=str)
    def applicationIcon(self, identifier: str) -> str:
        """The icon of one application, for the chips of the editor."""
        return self._icon_of(str(identifier))

    @Slot(str, result=str)
    def newProfileId(self, name: str) -> str:
        """The id a new profile takes: its name, slugged and kept unique."""
        taken = [str(profile.get("id") or "") for profile in self._profiles]
        return id_from_name(str(name), taken)

    @Slot(float, result=str)
    def formatStep(self, value: float) -> str:
        """A step in percent as a field shows it: two decimals at most, no zeros."""
        return _format_number(float(value))

    @Slot(str, result=float)
    def parseStep(self, text: str) -> float:
        """The number typed into a step field, tolerant of a comma and the " %" suffix."""
        return _parse_number(str(text))

    @Slot("QVariantList", "QVariantList", result="QVariantMap")
    def matchesNow(self, include: list, exclude: list) -> dict:
        """What a draft profile selects right now, for the editor's live line.

        Empty ``include`` means every application stream with the shell left out,
        and ``exclude`` removes applications again, the rule the daemon applies.
        """
        draft = Profile(
            id="draft",
            include=tuple(str(value) for value in include),
            exclude=tuple(str(value) for value in exclude),
        )
        matched = matching_applications(
            draft, [self._as_application(entry) for entry in self._applications]
        )
        return {
            "labels": [application.label for application in matched],
            "streams": sum(len(application.indices) for application in matched),
        }

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
        config = dict(overview.get("config") or {})
        idle_timeout = float(overview.get("idle_timeout") or 0.0)
        current = str(overview.get("current") or ACTIVE_ID)
        settings_changed = config != self._config or idle_timeout != self._idle_timeout

        profiles = []
        for profile in overview.get("profiles", []):
            entry = dict(profile)
            entry["key"] = self._key_of(entry)
            profiles.append(entry)
        # The window refreshes on a timer: signal only on a real change, so an
        # idle tick neither rebuilds the list nor resets a field being edited.
        profiles_changed = profiles != self._profiles or current != self._current

        self._current = current
        self._idle_timeout = idle_timeout
        self._config = config
        self._profiles = profiles

        if profiles_changed:
            self.profilesChanged.emit()
        if settings_changed:
            self.configChanged.emit()

    def _icon_of(self, identifier: str) -> str:
        """Icon of one application identifier, resolved like the daemon does.

        A streaming application answers with the icon of its live stream; a name
        that is not playing falls back to the ``.desktop`` file, and to nothing
        when even that is unknown.
        """
        name = str(identifier).strip()
        if not name:
            return ""
        for application in self._applications:
            if str(application.get("id") or "") == name:
                return str(application.get("icon") or "")
        return resolve_icon(desktop_file_name=name) or ""

    def _as_application(self, entry: dict) -> Application:
        """A live application, adapted from the daemon reply for the matcher."""
        key = str(entry.get("id") or "")
        return Application(
            key=key,
            label=str(entry.get("label") or key),
            variants=frozenset(str(value) for value in entry.get("variants") or []),
            indices=tuple(int(value) for value in entry.get("streams") or []),
            panel=bool(entry.get("panel")),
        )

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


def _format_number(value: float) -> str:
    """A percentage with two decimals at most and no trailing zeros: 2.5, 5, 12.25."""
    return f"{round(float(value), 2):g}"


def _parse_number(text: str) -> float:
    """The number in a step field, "2,5 %" and "2.5 %" alike; unknown text is zero."""
    cleaned = str(text).replace(",", ".").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0
