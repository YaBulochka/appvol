"""``appvold`` — the appvol daemon.

The daemon is the only component that talks to PipeWire and to KWin:

* it registers ``org.appvol.Daemon`` on the session bus and refuses to start
  when the name is already taken (a single instance per session);
* it owns the D-Bus API used by the ``appvol`` client;
* it owns the profiles and registers one KGlobalAccel action per profile, so a
  profile key reaches the daemon without a relaunch;
* it caches the last focus reported by the KWin script;
* it loads the KWin script and reloads it when KWin restarts;
* it keeps a ``pulsectl`` connection alive, reconnecting when pipewire-pulse
  restarts.

Run it with ``python3 -m appvol.daemon`` (or ``bin/appvold``).  Only the
session bus is used, so no root privileges are required.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib, GLibUnix

import pulsectl

from . import __version__
from .apps import group_streams
from .config import Config, load as load_config, save as save_config
from .config import default_path as default_config_path
from .focus import Focus, focus_from_dbus, read_parent_pid
from .icon import resolvable, resolve as resolve_icon
from .match import STEP_DESCENDANT, MatchResult, Stream, match_streams, stream_label
from .osd import Osd
from .profiles import (
    ACTIVE_ID,
    MODE_FOCUS,
    MODE_STREAMS,
    OSD_NAME_AUTO,
    OSD_NAMES,
    Profile,
    ProfileSelection,
    action_name,
    active_profile,
    find as find_profile,
    load as load_profiles,
    match_profile,
    profile_from_action,
    replace_step,
    save as save_profiles,
    validate_id,
)
from .profiles import default_path as default_profiles_path
from .volume import DOWN, UP, absolute, changed, peak, target_channels

log = logging.getLogger("appvol.daemon")

BUS_NAME = "org.appvol.Daemon"
OBJECT_PATH = "/org/appvol/Daemon"
IFACE = "org.appvol.Daemon"

KWIN_SERVICE = "org.kde.KWin"
KWIN_SCRIPTING_PATH = "/Scripting"
KWIN_SCRIPTING_IFACE = "org.kde.kwin.Scripting"
KWIN_SCRIPT_IFACE = "org.kde.kwin.Script"
KWIN_PLUGIN_NAME = "appvol"
KWIN_RETRY_DELAY_MS = 500
KWIN_MAX_RETRIES = 20

KWIN_SCRIPT_NAME = "appvol.js"

KGA_SERVICE = "org.kde.kglobalaccel"
KGA_PATH = "/kglobalaccel"
KGA_IFACE = "org.kde.KGlobalAccel"
KGA_COMPONENT_IFACE = "org.kde.kglobalaccel.Component"

# The one component every appvol action belongs to.  It is registered at run
# time, so no .desktop file and no kbuildsycoca run is needed and Plasma lists it
# in System Settings while the daemon runs.  The volume actions used to live in a
# desktop file of their own, which made System Settings show a second entry next
# to the profiles; the daemon answers them directly now.
KGA_COMPONENT = "appvol"
KGA_COMPONENT_FRIENDLY = "Appvol"

# ``KGlobalAccelD::SetShortcutFlag::SetPresent``.  kglobalacceld grabs a key only
# for a shortcut whose owner has marked it present (``GlobalShortcut::setActive``
# registers the key, ``setIsPresent`` is what reaches it).  A bare ``doRegister``
# leaves the action in the registry with its key from ``kglobalshortcutsrc``, so
# System Settings shows the binding and ``invokeShortcut`` answers, while a real
# key press reaches nobody: the key was never grabbed.
KGA_SET_PRESENT = 2

# The actions of the component that are always there, next to one per profile:
# the name a key press reports and the label System Settings shows for it.  A
# fixed action carries no default key, so appvol takes no combination away from
# anyone; the user assigns them in System Settings like the profile keys.
ACTION_VOLUME_UP = "volume_up"
ACTION_VOLUME_DOWN = "volume_down"
ACTION_VOLUME_MUTE = "volume_mute"
ACTION_NEXT_PROFILE = "next_profile"
ACTION_PREVIOUS_PROFILE = "previous_profile"

FIXED_ACTIONS: tuple[tuple[str, str], ...] = (
    (ACTION_VOLUME_UP, "Volume up"),
    (ACTION_VOLUME_DOWN, "Volume down"),
    (ACTION_VOLUME_MUTE, "Toggle mute"),
    (ACTION_NEXT_PROFILE, "Next profile"),
    (ACTION_PREVIOUS_PROFILE, "Previous profile"),
)

# How often the daemon checks whether the current profile went idle.
PROFILE_CHECK_SECONDS = 10

# Last resort icon for a profile whose own icon and whose streams resolve to
# nothing; the OSD looks better with a volume icon than with none.
PROFILE_FALLBACK_ICON = "audio-volume-high"


def kwin_script_candidates() -> list[Path]:
    """Places the bundled KWin script may live, most specific first.

    A checkout keeps it next to the package (``<checkout>/kwin/appvol.js``); a
    package install puts it in the data directories, which is exactly what
    ``XDG_DATA_DIRS`` describes (``/usr/share/appvol/appvol.js``).
    """
    checkout = Path(__file__).resolve().parent.parent / "kwin" / KWIN_SCRIPT_NAME
    data = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    installed = [Path(item) / "appvol" / KWIN_SCRIPT_NAME for item in data.split(":") if item]
    return [checkout, *installed]


def find_kwin_script(candidates: Iterable[Path] | None = None) -> Path:
    """First existing candidate, or the first one when nothing is installed.

    Returning a missing path keeps the failure visible in the log instead of
    loading some other script by accident.
    """
    paths = list(candidates) if candidates is not None else kwin_script_candidates()
    for path in paths:
        if path.is_file():
            return path
    return paths[0]

PULSE_KEEPALIVE_SECONDS = 15
PULSE_NAME = "appvol"


class PulseManager:
    """Owns the ``pulsectl`` connection and survives pipewire-pulse restarts.

    Every operation goes through :meth:`_call`, which retries once on a fresh
    connection.  ``pulsectl`` runs its own event loop thread, so the calls below
    block the caller for a few milliseconds only.
    """

    def __init__(self) -> None:
        self._pulse: pulsectl.Pulse | None = None
        self._lock = threading.RLock()

    @property
    def connected(self) -> bool:
        pulse = self._pulse
        return bool(pulse is not None and pulse.connected)

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        pulse, self._pulse = self._pulse, None
        if pulse is None:
            return
        try:
            pulse.close()
        except Exception:  # noqa: BLE001 - closing must never raise
            log.debug("ignoring error while closing pulse connection", exc_info=True)

    def _connect_locked(self) -> pulsectl.Pulse:
        if self._pulse is not None:
            self._close_locked()
        log.debug("connecting to pipewire-pulse")
        self._pulse = pulsectl.Pulse(PULSE_NAME)
        return self._pulse

    def _call(self, operation, description: str):
        with self._lock:
            last_error: Exception | None = None
            for attempt in (0, 1):
                pulse = self._pulse if (attempt == 0 and self.connected) else self._connect_locked()
                try:
                    return operation(pulse)
                except Exception as exc:  # noqa: BLE001 - connection errors are expected
                    last_error = exc
                    log.warning(
                        "pulse operation failed (%s, attempt %d): %s: %s",
                        description,
                        attempt + 1,
                        type(exc).__name__,
                        exc,
                    )
                    log.debug("pulse failure details", exc_info=True)
                    self._close_locked()
            raise RuntimeError(f"pulse operation failed: {description}") from last_error

    def keepalive(self) -> None:
        """Reconnect eagerly when the server came back after a restart."""
        try:
            self._call(lambda pulse: pulse.server_info(), "keepalive")
        except RuntimeError:
            log.warning("pipewire-pulse is not reachable yet")

    def streams(self) -> list[Stream]:
        """Snapshot of all sink inputs, with merged client properties."""

        def collect(pulse: pulsectl.Pulse) -> list[Stream]:
            clients: dict[int, dict[str, str]] = {}
            try:
                for client in pulse.client_list():
                    clients[client.index] = dict(client.proplist)
            except pulsectl.PulseError as exc:
                log.debug("cannot list pulse clients: %s", exc)

            result: list[Stream] = []
            for info in pulse.sink_input_list():
                props: dict[str, str] = dict(clients.get(info.client, {}))
                props.update(info.proplist)
                result.append(
                    Stream(
                        index=info.index,
                        props=props,
                        label=stream_label(info.index, props),
                        volume=tuple(float(value) for value in info.volume.values),
                        mute=bool(info.mute),
                    )
                )
            return result

        return self._call(collect, "sink_input_list")

    def set_volume(self, index: int, channels: list[float]) -> None:
        volume = pulsectl.PulseVolumeInfo([float(value) for value in channels])
        self._call(lambda pulse: pulse.sink_input_volume_set(index, volume), f"set volume of {index}")

    def set_mute(self, index: int, mute: bool) -> None:
        self._call(lambda pulse: pulse.sink_input_mute(index, bool(mute)), f"set mute of {index}")


class KWinManager:
    """Loads and reloads the KWin script that pushes window focus to the daemon."""

    def __init__(self, bus: dbus.SessionBus, script_path: Path) -> None:
        self.bus = bus
        self.script_path = Path(script_path)
        self._retries = 0

    def _scripting(self):
        obj = self.bus.get_object(KWIN_SERVICE, KWIN_SCRIPTING_PATH)
        return dbus.Interface(obj, KWIN_SCRIPTING_IFACE)

    def load(self) -> bool:
        """(Re)load the appvol KWin script.  Returns True on success."""
        if not self.script_path.is_file():
            log.error("KWin script not found: %s", self.script_path)
            return False
        try:
            scripting = self._scripting()
            if scripting.isScriptLoaded(KWIN_PLUGIN_NAME):
                log.debug("unloading previously loaded KWin script")
                scripting.unloadScript(KWIN_PLUGIN_NAME)
            # loadScript has two overloads; dbus-python only sees the first one
            # (signature "s"), so the two-argument form must be named explicitly.
            script_id = int(
                scripting.loadScript(str(self.script_path), KWIN_PLUGIN_NAME, signature="ss")
            )
            if script_id < 0:
                log.error("KWin refused to load %s (id %d)", self.script_path, script_id)
                return False
            script = self.bus.get_object(KWIN_SERVICE, f"{KWIN_SCRIPTING_PATH}/Script{script_id}")
            dbus.Interface(script, KWIN_SCRIPT_IFACE).run()
        except dbus.DBusException as exc:
            log.warning("cannot load KWin script yet: %s", exc)
            return False
        log.info("KWin script loaded (id %d) from %s", script_id, self.script_path)
        self._retries = 0
        return True

    def unload(self) -> None:
        try:
            self._scripting().unloadScript(KWIN_PLUGIN_NAME)
        except dbus.DBusException as exc:
            log.debug("cannot unload KWin script: %s", exc)

    def on_name_owner_changed(self, name, _old_owner, new_owner) -> None:
        if name != KWIN_SERVICE or not new_owner:
            return
        log.info("KWin appeared on the bus, (re)loading script")
        self.schedule_load()

    def schedule_load(self) -> None:
        self._retries = 0
        GLib.timeout_add(KWIN_RETRY_DELAY_MS, self._retry_load)

    def _retry_load(self) -> bool:
        if self.load():
            return False
        self._retries += 1
        if self._retries >= KWIN_MAX_RETRIES:
            log.error("giving up on loading the KWin script after %d attempts", self._retries)
            return False
        return True


class ShortcutActions:
    """The KGlobalAccel actions of the daemon: the fixed ones and one per profile.

    Plasma reads the component over D-Bus, so the actions appear in System
    Settings while the daemon runs and no desktop file has to be regenerated.
    The keys the user assigns there live in ``kglobalshortcutsrc`` under the
    component name and survive a restart of the daemon; both were verified on
    Plasma 6.7.5.  Registration failures are logged and ignored, so the CLI still
    works on a session without kglobalacceld.
    """

    def __init__(self, bus: dbus.SessionBus, on_pressed: Callable[[str], None]) -> None:
        self.bus = bus
        self.on_pressed = on_pressed
        self.component_path: str | None = None
        self.actions: tuple[str, ...] = ()
        self._subscribed = False

    def _interface(self):
        return dbus.Interface(self.bus.get_object(KGA_SERVICE, KGA_PATH), KGA_IFACE)

    def sync(self, profiles: Sequence[Profile]) -> None:
        """Register the actions of the component and drop the ones that are gone.

        Registering is two calls per action: ``doRegister`` creates the action
        (and, on the first call, the component), then ``setShortcutKeys`` with
        ``SetPresent`` makes kglobalacceld grab the keys it holds for it.  The
        second call is what turns a key in ``kglobalshortcutsrc`` into a key that
        fires; without it the binding is visible everywhere and dead.
        """
        wanted = dict(FIXED_ACTIONS)
        wanted.update({action_name(profile.id): profile.display_name for profile in profiles})
        try:
            iface = self._interface()
            for action, friendly in wanted.items():
                # A four element action id creates the action and, on the first
                # call, the component itself (kglobalacceld, createComponent).
                action_id = [KGA_COMPONENT, action, KGA_COMPONENT_FRIENDLY, friendly]
                iface.doRegister(action_id)
                # Autoloading, the default: the keys pass through from
                # kglobalshortcutsrc and the ones given here are ignored, so the
                # binding the user assigned survives.  They are read back first
                # because a brand new action is created fresh, where autoloading
                # cannot help yet and the given keys would be the ones stored.
                iface.setShortcutKeys(action_id, iface.shortcutKeys(action_id), KGA_SET_PRESENT)
            for action in set(self.actions) - set(wanted):
                try:
                    iface.unregister(KGA_COMPONENT, action)
                    log.info("removed the shortcut action %s", action)
                except dbus.DBusException as exc:
                    log.debug("cannot unregister %s: %s", action, exc)
            path = str(iface.getComponent(KGA_COMPONENT))
        except dbus.DBusException as exc:
            log.warning("cannot register the shortcut actions: %s", exc)
            return
        self.actions = tuple(wanted)
        self.component_path = path
        self._subscribe()
        log.debug("shortcut actions: %s", ", ".join(self.actions) or "none")

    def _subscribe(self) -> None:
        if self._subscribed or not self.component_path:
            return
        self.bus.add_signal_receiver(
            self._pressed,
            signal_name="globalShortcutPressed",
            dbus_interface=KGA_COMPONENT_IFACE,
            path=self.component_path,
        )
        self._subscribed = True

    def _pressed(self, _component, action, _timestamp) -> None:
        log.debug("shortcut %s pressed", action)
        self.on_pressed(str(action))


class State:
    """Mutable daemon state shared by the D-Bus methods."""

    def __init__(self) -> None:
        self.focus = Focus()
        self.focus_time = 0.0
        self.selection = ProfileSelection()

    def update_focus(self, focus: Focus) -> None:
        self.focus = focus
        self.focus_time = time.monotonic()


class Daemon(dbus.service.Object):
    """D-Bus object implementing ``org.appvol.Daemon``."""

    def __init__(
        self,
        bus: dbus.SessionBus,
        config: Config,
        pulse: PulseManager,
        osd: Osd,
        profiles_path: Path | None = None,
        config_path: Path | None = None,
    ) -> None:
        super().__init__(bus, OBJECT_PATH)
        self.config = config
        self.pulse = pulse
        self.osd = osd
        self.state = State()
        self.profiles: list[Profile] = []
        self.profiles_path = Path(profiles_path) if profiles_path else default_profiles_path()
        self.config_path = Path(config_path) if config_path else default_config_path()
        self.shortcuts = ShortcutActions(bus, self.on_shortcut)
        # The last application the Active profile covered: when the cycle keys
        # land on Active, the OSD shows it instead of nothing.
        self._last_active: tuple[str, str, int] | None = None

    # -- profiles ----------------------------------------------------------

    def load_profiles(self) -> None:
        """Read ``profiles.toml`` and follow the changes in KGlobalAccel."""
        self.profiles = load_profiles(self.profiles_path)
        if find_profile(self.profiles, self.state.selection.current) is None:
            if self.state.selection.current != ACTIVE_ID:
                log.info("profile %s is gone, using %s", self.state.selection.current, ACTIVE_ID)
            self.state.selection.current = ACTIVE_ID
        self.shortcuts.sync(self.profiles)
        log.debug("profiles from %s: %s",
                  self.profiles_path, ", ".join(profile.id for profile in self.profiles) or "none")

    def current_profile(self) -> Profile:
        """The profile the volume keys act on."""
        profile = find_profile(self.profiles, self.state.selection.current)
        return profile if profile is not None else active_profile()

    def resync_shortcuts(self) -> None:
        """Register the profile actions again, after the server came back."""
        self.shortcuts.sync(self.profiles)

    def on_shortcut(self, action: str) -> None:
        """A key of the Appvol component was pressed."""
        if action == ACTION_VOLUME_UP:
            self._adjust(UP, 0.0)
            return
        if action == ACTION_VOLUME_DOWN:
            self._adjust(DOWN, 0.0)
            return
        if action == ACTION_VOLUME_MUTE:
            self._toggle_mute()
            return
        if action in (ACTION_NEXT_PROFILE, ACTION_PREVIOUS_PROFILE):
            self._cycle_profile(-1 if action == ACTION_PREVIOUS_PROFILE else 1)
            return
        profile_id = profile_from_action(action)
        if not profile_id or find_profile(self.profiles, profile_id) is None:
            log.debug("ignoring the unknown shortcut %s", action)
            return
        log.info("switching profile from the %s shortcut", action)
        self._toggle_profile(profile_id)

    def expire_profile(self) -> bool:
        """Move back to Active when the current profile is idle."""
        return self.state.selection.expire(time.monotonic(), self.config.profile_idle_timeout)

    def _profile(self, profile_id: str) -> Profile:
        """Resolve a profile id; an empty id means the current profile."""
        if profile_id == ACTIVE_ID:
            return active_profile()
        if not profile_id:
            return self.current_profile()
        profile = find_profile(self.profiles, profile_id)
        if profile is None:
            raise _invalid_argument(f"no such profile: {profile_id!r}")
        return profile

    def _profiles(self) -> dict:
        return {
            "ok": True,
            "current": self.state.selection.current,
            "idle_timeout": self.config.profile_idle_timeout,
            "config": {
                "step": self.config.step,
                "max_volume": self.config.max_volume,
                "osd": self.config.osd,
            },
            "profiles": [profile.summary() for profile in self.profiles],
        }

    def _toggle_profile(self, profile_id: str, osd: bool = True) -> dict:
        """Switch to a profile, or back to Active when it is already current."""
        self.state.selection.toggle(self._switch_target(profile_id).id, time.monotonic())
        log.info("profile: %s", self.state.selection.current)
        return self._feedback(self.current_profile(), osd)

    def _cycle_profile(self, step: int) -> None:
        """Switch to the next or the previous profile, with the OSD.

        The order is the one the window shows: the built-in Active profile first,
        then the profiles of ``profiles.toml``.  Unlike a profile key this is a
        plain switch, so a second press goes on instead of coming back.
        """
        order = [ACTIVE_ID, *(profile.id for profile in self.profiles)]
        try:
            index = order.index(self.state.selection.current)
        except ValueError:
            index = 0
        target = order[(index + step) % len(order)]
        self.state.selection.select(target, time.monotonic())
        log.info("profile: %s", self.state.selection.current)
        profile = self.current_profile()
        if target == ACTIVE_ID and self._last_active is not None:
            # Landed on Active: show the last application Active covered.
            name, icon, percent = self._last_active
            log.info("cycle on active: last app %r, icon %r, %s%%", name, icon, percent)
            self.osd.volume_changed(percent, icon=icon, name=name)
            return
        self._feedback(profile, osd=True)

    def _switch_target(self, profile_id: str) -> Profile:
        """The profile a switch refers to; an empty id means the built-in one."""
        if profile_id in ("", ACTIVE_ID):
            return active_profile()
        return self._profile(profile_id)

    def _switch_profile(self, profile_id: str, osd: bool = True) -> dict:
        """Make a profile current, the explicit form of the toggle."""
        self.state.selection.select(self._switch_target(profile_id).id, time.monotonic())
        log.info("profile: %s", self.state.selection.current)
        return self._feedback(self.current_profile(), osd)

    def _feedback(self, profile: Profile, osd: bool = True) -> dict:
        """Report what a profile looks like now, for a profile switch."""
        streams, result = self._resolve(profile)
        by_index = {stream.index: stream for stream in streams}
        targets = [by_index[index] for index in result.indices]
        name, icon = self._appearance(profile, result, by_index)
        payload = {
            "ok": True,
            "action": "profile",
            "profile": profile.summary(),
            "current": self.state.selection.current,
            "matched": result.count,
            "match_step": result.step,
            "reason": result.reason,
            "percent": None,
            "osd": {"name": name, "icon": icon},
        }
        if targets:
            percent = int(round(max(peak(stream.volume) for stream in targets) * 100))
            payload["percent"] = percent
            if profile.mode == MODE_FOCUS:
                self._last_active = (name, icon, percent)
            if osd:
                self.osd.volume_changed(percent, icon=icon, name=osd_caption(profile, name))
        elif profile.mode == MODE_FOCUS:
            log.info("nothing to show for %s: %s", profile.id, result.reason)
        elif osd:
            # A profile key press deserves an answer, even a negative one.
            self.osd.text(icon, "no stream")
        return payload

    def _add_profile(
        self,
        profile_id,
        name,
        include,
        exclude,
        step,
        max_volume,
        icon,
        osd_name,
    ) -> dict:
        try:
            identifier = validate_id(profile_id)
        except ValueError as exc:
            raise _invalid_argument(str(exc)) from None
        profile = Profile(
            id=identifier,
            name=str(name).strip(),
            mode=MODE_STREAMS,
            include=_names(include),
            exclude=_names(exclude),
            step=float(step) or None,
            max_volume=float(max_volume) or None,
            icon=str(icon).strip(),
            osd_name=_osd_name(osd_name),
        )
        known = find_profile(self.profiles, identifier) is not None
        if known:
            self.profiles = [profile if item.id == identifier else item for item in self.profiles]
        else:
            self.profiles = [*self.profiles, profile]
        save_profiles(self.profiles, self.profiles_path)
        self.shortcuts.sync(self.profiles)
        log.info("%s profile %s (include %s, exclude %s)",
                 "updated" if known else "added",
                 identifier,
                 list(profile.include) or "everything",
                 list(profile.exclude) or "nothing")
        return self._profiles()

    def _remove_profile(self, profile_id) -> dict:
        identifier = str(profile_id).strip().lower()
        if find_profile(self.profiles, identifier) is None:
            raise _invalid_argument(f"no such profile: {profile_id!r}")
        self.profiles = [item for item in self.profiles if item.id != identifier]
        if self.state.selection.current == identifier:
            self.state.selection.current = ACTIVE_ID
        save_profiles(self.profiles, self.profiles_path)
        self.shortcuts.sync(self.profiles)
        log.info("removed profile %s", identifier)
        return self._profiles()

    def _set_step(self, profile_id: str, step: float) -> dict:
        """Change the step of one profile, or the global one for Active.

        The built-in profile has no entry of its own, so its step is the global
        one in ``config.toml``; a profile carries its own, and a zero step gives
        the override up.
        """
        identifier = profile_id.strip().lower()
        if identifier in ("", ACTIVE_ID):
            if step <= 0:
                raise _invalid_argument(
                    "the global step must be positive; a profile step of 0 means the global one"
                )
            self.config = replace(self.config, step=step)
            save_config(self.config, self.config_path)
            log.info("global step: %g%%", step)
            return self._profiles()

        if find_profile(self.profiles, identifier) is None:
            raise _invalid_argument(f"no such profile: {profile_id!r}")
        self.profiles = replace_step(self.profiles, identifier, step)
        save_profiles(self.profiles, self.profiles_path)
        log.info("profile %s: step %s", identifier, f"{step:g}%" if step else "the global one")
        return self._profiles()

    # -- D-Bus API ---------------------------------------------------------

    @dbus.service.method(IFACE, in_signature="isss", out_signature="i")
    def SetFocus(self, pid, resource_class, desktop_file_name, caption) -> int:  # noqa: N802
        """Called by the KWin script on every window activation."""
        focus = focus_from_dbus(pid, resource_class, desktop_file_name, caption)
        if focus != self.state.focus:
            log.debug("focus: %s", self.focus_summary(focus))
        self.state.update_focus(focus)
        return 0

    @dbus.service.method(IFACE, in_signature="sd", out_signature="s")
    def Adjust(self, direction, step) -> str:  # noqa: N802
        """Move the volume of the current profile by ``step`` percent.

        A ``step`` of zero means "the step of the profile, else the configured
        one", so a client does not have to know which profile is current.
        """
        return json.dumps(self._adjust(_direction(direction), _step(step)))

    @dbus.service.method(IFACE, in_signature="ssd", out_signature="s")
    def AdjustTarget(self, profile_id, direction, step) -> str:  # noqa: N802
        """Move the volume of ``profile_id``, without switching the profile."""
        profile = self._profile(str(profile_id))
        return json.dumps(self._adjust(_direction(direction), _step(step), profile))

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def ToggleMute(self) -> str:  # noqa: N802
        """Toggle mute on the streams of the current profile."""
        return json.dumps(self._toggle_mute())

    @dbus.service.method(IFACE, in_signature="s", out_signature="s")
    def ToggleMuteTarget(self, profile_id) -> str:  # noqa: N802
        """Toggle mute on the streams of ``profile_id``."""
        return json.dumps(self._toggle_mute(self._profile(str(profile_id))))

    @dbus.service.method(IFACE, in_signature="sd", out_signature="s")
    def SetVolume(self, profile_id, percent) -> str:  # noqa: N802
        """Set the volume of ``profile_id`` to ``percent``, without the OSD.

        For a slider that sends a value per movement; the GUI shows its own
        feedback instead of asking for an OSD per pixel.
        """
        profile = self._profile(str(profile_id))
        return json.dumps(self._set_volume(profile, _amount(percent, "percent")))

    @dbus.service.method(IFACE, in_signature="sb", out_signature="s")
    def SetMute(self, profile_id, muted) -> str:  # noqa: N802
        """Set mute on the streams of ``profile_id`` to ``muted``, without the OSD."""
        return json.dumps(self._set_mute(self._profile(str(profile_id)), bool(muted)))

    @dbus.service.method(IFACE, in_signature="sd", out_signature="s")
    def SetStep(self, profile_id, step) -> str:  # noqa: N802
        """Set the step of ``profile_id`` in percent; empty or Active is the global one.

        A step of zero on a stream profile drops its override, so the profile
        follows the global step again.
        """
        return json.dumps(self._set_step(str(profile_id), _step(step)))

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def Applications(self) -> str:  # noqa: N802
        """Report the applications that are playing right now."""
        return json.dumps(self._applications())

    @dbus.service.method(IFACE, in_signature="sb", out_signature="s")
    def SwitchProfile(self, profile_id, osd) -> str:  # noqa: N802
        """Make ``profile_id`` current, without the toggle the keys do.

        ``osd`` asks for the OSD feedback: the tray wants it, a window that shows
        the change already does not need it.
        """
        return json.dumps(self._switch_profile(str(profile_id), bool(osd)))

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def Overview(self) -> str:  # noqa: N802
        """Report every profile with its live volume, mute state and match count."""
        return json.dumps(self._overview())

    @dbus.service.method(IFACE, in_signature="s", out_signature="s")
    def ToggleProfile(self, profile_id) -> str:  # noqa: N802
        """Switch to ``profile_id``, or back to Active when it is current."""
        identifier = str(profile_id).strip().lower()
        if identifier and identifier != ACTIVE_ID:
            self._profile(identifier)
        return json.dumps(self._toggle_profile(identifier))

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def List(self) -> str:  # noqa: N802
        """Report the cached focus, the profiles, all streams and the match."""
        return json.dumps(self._list())

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def Profiles(self) -> str:  # noqa: N802
        """Report the profiles and which one the keys act on."""
        return json.dumps(self._profiles())

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def Reload(self) -> str:  # noqa: N802
        """Read ``profiles.toml`` again, after a hand edit."""
        self.load_profiles()
        return json.dumps(self._profiles())

    @dbus.service.method(IFACE, in_signature="ssasasddss", out_signature="s")
    def AddProfile(  # noqa: N802
        self, profile_id, name, include, exclude, step, max_volume, icon, osd_name
    ) -> str:
        """Create or replace a stream profile and write ``profiles.toml``."""
        return json.dumps(
            self._add_profile(profile_id, name, include, exclude, step, max_volume, icon, osd_name)
        )

    @dbus.service.method(IFACE, in_signature="s", out_signature="s")
    def RemoveProfile(self, profile_id) -> str:  # noqa: N802
        """Remove a profile and its shortcut action."""
        return json.dumps(self._remove_profile(profile_id))

    # -- Implementation ----------------------------------------------------

    def focus_summary(self, focus: Focus) -> dict:
        return {
            "pid": focus.pid,
            "resource_class": focus.resource_class,
            "desktop_file_name": focus.desktop_file_name,
            "caption": focus.caption,
            "label": focus.label,
            "ignored_reason": focus.ignored_reason(),
            "age": round(time.monotonic() - self.state.focus_time, 3) if self.state.focus_time else None,
        }

    def _resolve(self, profile: Profile) -> tuple[list[Stream], MatchResult]:
        streams = self.pulse.streams()
        return streams, self._match(profile, streams)

    def _match(self, profile: Profile, streams: Sequence[Stream]) -> MatchResult:
        """Match a profile against a snapshot of streams, without any I/O."""
        if profile.mode == MODE_FOCUS:
            return match_streams(self.state.focus, streams, parent_of=read_parent_pid)
        return match_profile(profile, streams)

    def _appearance(
        self, profile: Profile, result: MatchResult, by_index: dict[int, Stream]
    ) -> tuple[str, str]:
        """Name and icon a profile resolves to, as the OSD and ``appvol list`` see it.

        The icon of the Active profile comes from the focused window (its
        ``desktopFileName``), the name from the stream, because a stream usually
        carries a nicer ``application.name`` than the reverse-DNS identifier of
        the window.  A descendant match may point at a helper process
        (``ffmpeg``, a crash handler), and then the name of the window itself is
        the useful one.  Whether the OSD also *shows* the name is up to
        ``osd_name`` and decided in :func:`osd_caption`.

        A stream profile carries its own name, and its icon comes from the
        ``icon`` key, from the matched stream or from the ``.desktop`` file of
        the first entry of ``include``.
        """
        if profile.mode != MODE_FOCUS:
            name = profile.display_name if profile.shows_name else ""
            return name, self._profile_icon(profile, result, by_index)

        focus = self.state.focus
        stream_name = ""
        for index in result.indices:
            stream_name = str(by_index[index].props.get("application.name") or "").strip()
            if stream_name:
                break

        if not stream_name or result.step == STEP_DESCENDANT:
            name = focus.label if result.step == STEP_DESCENDANT else (stream_name or focus.label)
        else:
            name = stream_name

        props = by_index[result.indices[0]].props if result.indices else {}
        icon = resolve_icon(
            desktop_file_name=focus.desktop_file_name,
            resource_class=focus.resource_class,
            props=props,
        )
        return name, icon or ""

    def _profile_icon(self, profile: Profile, result: MatchResult, by_index: dict[int, Stream]) -> str:
        """Icon for a stream profile: its own, the streams', or a volume icon."""
        if profile.icon:
            if resolvable(profile.icon):
                return profile.icon
            log.warning("icon %r of profile %s is not in the icon theme", profile.icon, profile.id)
        props = by_index[result.indices[0]].props if result.indices else {}
        hint = profile.include[0] if profile.include else ""
        return resolve_icon(desktop_file_name=hint, props=props) or PROFILE_FALLBACK_ICON

    def _step_of(self, profile: Profile, step_percent: float) -> float:
        """The step to apply: the caller's, else the profile's, else the config's."""
        if step_percent > 0:
            return step_percent
        return profile.step or self.config.step

    def _max_volume_of(self, profile: Profile) -> float:
        return (profile.max_volume or self.config.max_volume) / 100.0

    def _adjust(self, direction: str, step_percent: float, profile: Profile | None = None) -> dict:
        profile = profile or self.current_profile()
        if profile.id == self.state.selection.current:
            # Any key press on the current profile counts as using it.
            self.state.selection.use(time.monotonic())
        step_percent = self._step_of(profile, step_percent)
        streams, result = self._resolve(profile)
        payload = {
            "ok": True,
            "action": direction,
            "step": step_percent,
            "profile": profile.summary(),
            "matched": result.count,
            "match_step": result.step,
            "reason": result.reason,
            "percent": None,
            "osd": {},
            "streams": [],
        }
        if not result.matched:
            log.info("nothing to do: %s", result.reason)
            return payload

        step = step_percent / 100.0
        max_volume = self._max_volume_of(profile)
        by_index = {stream.index: stream for stream in streams}
        peaks: list[float] = []

        for index in result.indices:
            stream = by_index[index]
            old = list(stream.volume) or [0.0]
            new = target_channels(old, direction, step, max_volume)
            peaks.append(peak(new))
            entry = {
                "index": index,
                "label": stream.display_name,
                "from": _percent_tuple(old),
                "to": _percent_tuple(new),
                "muted": stream.mute,
            }
            if changed(old, new):
                self.pulse.set_volume(index, new)
                entry["applied"] = True
                log.info(
                    "%s %s -> %s for %s (stream %d, %s)",
                    direction,
                    _percent_tuple(old),
                    _percent_tuple(new),
                    stream.display_name,
                    index,
                    result.step,
                )
            else:
                entry["applied"] = False
            payload["streams"].append(entry)

        payload["percent"] = int(round(max(peaks) * 100)) if peaks else None
        if payload["percent"] is not None:
            name, icon = self._appearance(profile, result, by_index)
            payload["osd"] = {"name": name, "icon": icon}
            log.debug("osd: %s%% with icon %r (app %r)", payload["percent"], icon, name)
            if profile.mode == MODE_FOCUS:
                self._last_active = (name, icon, payload["percent"] or 0)
            self.osd.volume_changed(payload["percent"], icon=icon, name=osd_caption(profile, name))
        return payload

    def _toggle_mute(self, profile: Profile | None = None) -> dict:
        profile = profile or self.current_profile()
        if profile.id == self.state.selection.current:
            self.state.selection.use(time.monotonic())
        streams, result = self._resolve(profile)
        payload = {
            "ok": True,
            "action": "mute",
            "profile": profile.summary(),
            "matched": result.count,
            "match_step": result.step,
            "reason": result.reason,
            "muted": None,
            "percent": None,
            "streams": [],
        }
        if not result.matched:
            log.info("nothing to do: %s", result.reason)
            return payload

        by_index = {stream.index: stream for stream in streams}
        targets = [by_index[index] for index in result.indices]
        # Aggregate: any audible stream means "mute everything", a fully muted
        # set means "bring it back".
        mute = any(not stream.mute for stream in targets)
        peaks: list[float] = []

        for stream in targets:
            if stream.mute != mute:
                self.pulse.set_mute(stream.index, mute)
            peaks.append(peak(stream.volume))
            payload["streams"].append(
                {
                    "index": stream.index,
                    "label": stream.display_name,
                    "muted": mute,
                    "percent": int(round(peak(stream.volume) * 100)),
                }
            )

        payload["muted"] = mute
        payload["percent"] = int(round(max(peaks) * 100)) if peaks else None
        labels = ", ".join(dict.fromkeys(stream.display_name for stream in targets))
        log.info("%s %s (streams: %s)", "muted" if mute else "unmuted", labels, result.indices)
        name, icon = self._appearance(profile, result, by_index)
        payload["osd"] = {"name": name, "icon": icon}
        name = osd_caption(profile, name)
        if name:
            if mute:
                # Plasma renders "<name> Muted" itself when the value is zero.
                self.osd.volume_changed(0, icon=icon, name=name)
            elif payload["percent"]:
                self.osd.volume_changed(payload["percent"], icon=icon, name=name)
            else:
                self.osd.text(icon, "Unmuted")
        elif mute:
            self.osd.text(icon, "Muted")
        elif payload["percent"]:
            self.osd.volume_changed(payload["percent"], icon=icon)
        else:
            # Nothing to show on the progress bar.
            self.osd.text(icon, "Unmuted")
        return payload

    def _payload(self, action: str, profile: Profile, result: MatchResult) -> dict:
        """Result skeleton shared by the control methods."""
        return {
            "ok": True,
            "action": action,
            "profile": profile.summary(),
            "matched": result.count,
            "match_step": result.step,
            "reason": result.reason,
            "percent": None,
            "muted": None,
            "osd": {},
            "streams": [],
        }

    def _entry(self, stream: Stream, volume: Sequence[float]) -> dict:
        """Per-stream record of the absolute and relative volume methods."""
        return {
            "index": stream.index,
            "label": stream.display_name,
            "from": _percent_tuple(stream.volume or [0.0]),
            "to": _percent_tuple(volume),
            "muted": stream.mute,
        }

    def _set_volume(self, profile: Profile, percent: float) -> dict:
        """Set the volume of a profile to ``percent``, keeping the balance.

        Absolute counterpart of :meth:`_adjust`, and silent on the OSD: a slider
        sends one call per movement, and an OSD per pixel of travel would only
        flicker.  The caller draws its own feedback.
        """
        streams, result = self._resolve(profile)
        payload = self._payload("set", profile, result)
        if not result.matched:
            log.info("nothing to set: %s", result.reason)
            return payload

        by_index = {stream.index: stream for stream in streams}
        ceiling = self._max_volume_of(profile)
        target = min(percent / 100.0, ceiling)
        peaks: list[float] = []
        for index in result.indices:
            stream = by_index[index]
            old = list(stream.volume) or [0.0]
            new = absolute(old, target, ceiling)
            peaks.append(peak(new))
            entry = self._entry(stream, new)
            if changed(old, new):
                self.pulse.set_volume(index, new)
                entry["applied"] = True
            else:
                entry["applied"] = False
            payload["streams"].append(entry)

        payload["percent"] = int(round(max(peaks) * 100)) if peaks else None
        log.info(
            "set %s%% on %s (streams: %s)",
            payload["percent"],
            profile.display_name,
            result.indices,
        )
        return payload

    def _set_mute(self, profile: Profile, muted: bool) -> dict:
        """Set mute on the streams of a profile, unlike the aggregate toggle."""
        streams, result = self._resolve(profile)
        payload = self._payload("mute", profile, result)
        payload["muted"] = muted
        if not result.matched:
            log.info("nothing to set: %s", result.reason)
            return payload

        by_index = {stream.index: stream for stream in streams}
        peaks: list[float] = []
        for index in result.indices:
            stream = by_index[index]
            if stream.mute != muted:
                self.pulse.set_mute(index, muted)
            peaks.append(peak(stream.volume))
            payload["streams"].append(
                {
                    "index": stream.index,
                    "label": stream.display_name,
                    "muted": muted,
                    "percent": int(round(peak(stream.volume) * 100)),
                }
            )

        payload["percent"] = int(round(max(peaks) * 100)) if peaks else None
        log.info(
            "%s %s (streams: %s)",
            "muted" if muted else "unmuted",
            profile.display_name,
            result.indices,
        )
        return payload

    def _applications(self) -> dict:
        """Applications playing right now, for the profile editor and ``appvol apps``."""
        streams = self.pulse.streams()
        by_index = {stream.index: stream for stream in streams}
        entries = []
        for application in group_streams(streams):
            first = by_index[application.indices[0]]
            entries.append({**application.summary(), "icon": resolve_icon(props=first.props) or ""})
        return {"ok": True, "applications": entries, "current": self.state.selection.current}

    def _overview(self) -> dict:
        """The panel the GUI draws: every profile with its live state.

        The built-in Active profile comes first, because it is also a target the
        user switches between.  A dead PipeWire connection is not fatal here: the
        profiles are still worth showing, only the live numbers are missing.
        """
        try:
            streams: list[Stream] | None = self.pulse.streams()
        except RuntimeError as exc:
            log.warning("cannot read the streams for the overview: %s", exc)
            streams = None

        by_index = {stream.index: stream for stream in streams} if streams else {}
        current = self.state.selection.current
        entries = []
        for profile in (active_profile(), *self.profiles):
            entry = {
                **profile.summary(),
                "builtin": profile.id == ACTIVE_ID,
                "current": profile.id == current,
                "matched": None,
                "percent": None,
                "muted": None,
                "reason": "",
            }
            if streams is not None:
                result = self._match(profile, streams)
                targets = [by_index[index] for index in result.indices]
                entry.update(
                    {
                        "matched": result.count,
                        "reason": result.reason,
                        "percent": int(round(max(peak(stream.volume) for stream in targets) * 100))
                        if targets
                        else None,
                        "muted": all(stream.mute for stream in targets) if targets else None,
                    }
                )
            entries.append(entry)

        return {
            "ok": True,
            "current": current,
            "idle_timeout": self.config.profile_idle_timeout,
            "config": {
                "step": self.config.step,
                "max_volume": self.config.max_volume,
                "osd": self.config.osd,
            },
            "profiles": entries,
        }

    def _list(self) -> dict:
        profile = self.current_profile()
        streams, result = self._resolve(profile)
        matched = set(result.indices)
        by_index = {stream.index: stream for stream in streams}
        # Computed even without a match, so `appvol list` can explain which icon
        # the OSD would use for the current window.
        name, icon = self._appearance(profile, result, by_index)
        return {
            "ok": True,
            "config": {
                "step": self.config.step,
                "max_volume": self.config.max_volume,
                "osd": self.config.osd,
                "profile_idle_timeout": self.config.profile_idle_timeout,
            },
            "profile": profile.summary(),
            "current": self.state.selection.current,
            "profiles": [item.summary() for item in self.profiles],
            "focus": self.focus_summary(self.state.focus),
            "match": {"step": result.step, "reason": result.reason, "matched": result.count},
            "osd": {"name": name, "icon": icon},
            "streams": [
                {
                    "index": stream.index,
                    "label": stream.display_name,
                    "pid": stream.pid,
                    "percent": int(round(peak(stream.volume) * 100)),
                    "muted": stream.mute,
                    "matched": stream.index in matched,
                    "application.name": stream.props.get("application.name", ""),
                    "application.process.binary": stream.props.get("application.process.binary", ""),
                    "pipewire.access.portal.app_id": stream.props.get(
                        "pipewire.access.portal.app_id", ""
                    ),
                }
                for stream in streams
            ],
        }


def _percent_tuple(channels) -> list[int]:
    return [int(round(value * 100)) for value in channels]


def osd_caption(profile: Profile, name: str) -> str:
    """The caption the OSD receives: empty when the profile hides its name.

    The Active profile defaults to ``osd_name = auto``, which stands for "a
    caption for a stream profile, only the icon for the focus profile", so a
    volume key on the focused window shows the icon and the bar and no name.  The
    name a profile resolves to still travels in the reply, ``appvol list`` prints
    it, and ``osd_name = always`` puts it back into the OSD.
    """
    return name if profile.shows_name else ""


def _direction(value: object) -> str:
    text = str(value)
    if text not in (UP, DOWN):
        raise _invalid_argument(f"direction must be {UP!r} or {DOWN!r}, got {text!r}")
    return text


def _amount(value: object, what: str = "step") -> float:
    """Validate a non-negative number of percent."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise _invalid_argument(f"{what} must be a number, got {value!r}") from None
    if number < 0:
        raise _invalid_argument(f"{what} must not be negative, got {number}")
    return number


def _step(value: object) -> float:
    """Validate a step in percent; zero means "the profile's or the config's"."""
    return _amount(value, "step")


def _names(values: Iterable[object]) -> tuple[str, ...]:
    """Clean a list of application identifiers, keeping the order."""
    cleaned = (str(value).strip() for value in values)
    return tuple(dict.fromkeys(value for value in cleaned if value))


def _osd_name(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return OSD_NAME_AUTO
    if text not in OSD_NAMES:
        log.warning("profile: osd_name %r is not one of %s, using %r",
                    value, ", ".join(OSD_NAMES), OSD_NAME_NEVER)
        return OSD_NAME_AUTO
    return text


def _invalid_argument(message: str) -> dbus.DBusException:
    return dbus.DBusException(message, name="org.appvol.Error.InvalidArgument")


class Appvol:
    """Wires the daemon, the pulse connection and the KWin script together."""

    def __init__(
        self,
        config: Config,
        profiles_path: Path | None = None,
        config_path: Path | None = None,
    ) -> None:
        self.config = config
        self.bus = dbus.SessionBus()
        # do_not_queue: a second daemon must fail instead of waiting for the name.
        self.bus_name = dbus.service.BusName(BUS_NAME, self.bus, do_not_queue=True)
        self.pulse = PulseManager()
        self.osd = Osd(config.osd)
        self.daemon = Daemon(self.bus, config, self.pulse, self.osd, profiles_path, config_path)
        script_path = Path(config.kwin_script).expanduser() if config.kwin_script else find_kwin_script()
        self.kwin = KWinManager(self.bus, script_path)
        self.loop = GLib.MainLoop()
        self._keepalive_id = 0
        self._profile_check_id = 0

    def on_shortcut_server_changed(self, _name, _old_owner, new_owner) -> None:
        if not new_owner:
            return
        # KWin owns org.kde.kglobalaccel.  A restart (or a crash and a D-Bus
        # activation) leaves a registry without our component, and the profile
        # keys stay dead until they are registered again; the KGlobalAccel client
        # library re-registers for the same reason (serviceOwnerChanged).
        log.info("the global shortcut server appeared, registering the profile keys again")
        self.daemon.resync_shortcuts()

    def start(self) -> None:
        self.bus.add_signal_receiver(
            self.kwin.on_name_owner_changed,
            signal_name="NameOwnerChanged",
            dbus_interface="org.freedesktop.DBus",
            bus_name="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
        )
        self.bus.add_signal_receiver(
            self.on_shortcut_server_changed,
            signal_name="NameOwnerChanged",
            dbus_interface="org.freedesktop.DBus",
            bus_name="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            arg0=KGA_SERVICE,
        )
        self.kwin.schedule_load()
        self.pulse.keepalive()
        self.daemon.load_profiles()
        self._keepalive_id = GLib.timeout_add_seconds(PULSE_KEEPALIVE_SECONDS, self._keepalive)
        self._profile_check_id = GLib.timeout_add_seconds(
            PROFILE_CHECK_SECONDS, self._check_profile_timeout
        )
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._stop)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._stop)
        log.info("appvol daemon %s started, step %.1f%%, max %.0f%%, osd %s, profiles %s, config %s",
                 __version__, self.config.step, self.config.max_volume, self.config.osd,
                 self.daemon.profiles_path, self.daemon.config_path)
        log.info("%d profile(s) loaded, idle timeout %.0fs",
                 len(self.daemon.profiles), self.config.profile_idle_timeout)
        self.loop.run()

    def _keepalive(self) -> bool:
        self.pulse.keepalive()
        return True

    def _check_profile_timeout(self) -> bool:
        if self.daemon.expire_profile():
            log.info("the keys are back on the %s profile", self.daemon.state.selection.current)
        return True

    def _stop(self) -> bool:
        log.info("shutting down")
        for source in (self._keepalive_id, self._profile_check_id):
            if source:
                GLib.source_remove(source)
        self._keepalive_id = 0
        self._profile_check_id = 0
        self.kwin.unload()
        self.pulse.close()
        self.loop.quit()
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="appvold", description="appvol daemon")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--config", type=Path, default=None, help="path to config.toml")
    parser.add_argument("--profiles", type=Path, default=None, help="path to profiles.toml")
    parser.add_argument("--kwin-script", type=Path, default=None, help="override the KWin script path")
    parser.add_argument("--version", action="version", version=f"appvold {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose or os.environ.get("APPVOL_VERBOSE") else logging.INFO,
        # The daemon runs for days, so the log needs its own clock: it is read to
        # answer "did that key press arrive at all".
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    config_path = args.config or default_config_path()
    config = load_config(config_path)
    if args.kwin_script is not None:
        config = replace(config, kwin_script=str(args.kwin_script))

    try:
        app = Appvol(config, args.profiles, config_path)
    except dbus.exceptions.NameExistsException:
        log.error("%s is already running, exiting", BUS_NAME)
        return 1
    except dbus.DBusException as exc:
        log.error("cannot connect to the session bus: %s", exc)
        return 1

    try:
        app.start()
    except KeyboardInterrupt:
        pass
    finally:
        app.pulse.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
