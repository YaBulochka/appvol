"""``appvold`` — the appvol daemon.

The daemon is the only component that talks to PipeWire and to KWin:

* it registers ``org.appvol.Daemon`` on the session bus and refuses to start
  when the name is already taken (a single instance per session);
* it owns the D-Bus API used by the ``appvol`` client;
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
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib, GLibUnix

import pulsectl

from . import __version__
from .config import Config, load as load_config
from .focus import Focus, focus_from_dbus, read_parent_pid
from .icon import resolve as resolve_icon
from .match import STEP_DESCENDANT, Stream, match_streams, stream_label
from .osd import Osd
from .volume import DOWN, UP, changed, peak, target_channels

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


class State:
    """Mutable daemon state shared by the D-Bus methods."""

    def __init__(self) -> None:
        self.focus = Focus()
        self.focus_time = 0.0

    def update_focus(self, focus: Focus) -> None:
        self.focus = focus
        self.focus_time = time.monotonic()


class Daemon(dbus.service.Object):
    """D-Bus object implementing ``org.appvol.Daemon``."""

    def __init__(self, bus: dbus.SessionBus, config: Config, pulse: PulseManager, osd: Osd) -> None:
        super().__init__(bus, OBJECT_PATH)
        self.config = config
        self.pulse = pulse
        self.osd = osd
        self.state = State()

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
        """Move the volume of the focused application by ``step`` percent."""
        direction = str(direction)
        if direction not in (UP, DOWN):
            raise _invalid_argument(f"direction must be {UP!r} or {DOWN!r}, got {direction!r}")
        try:
            step_value = float(step)
        except (TypeError, ValueError):
            raise _invalid_argument(f"step must be a number, got {step!r}") from None
        if step_value <= 0:
            raise _invalid_argument(f"step must be positive, got {step_value}")
        return json.dumps(self._adjust(direction, step_value))

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def ToggleMute(self) -> str:  # noqa: N802
        """Toggle mute on the streams of the focused application."""
        return json.dumps(self._toggle_mute())

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def List(self) -> str:  # noqa: N802
        """Report the cached focus, all streams and the match result."""
        return json.dumps(self._list())

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

    def _resolve(self) -> tuple[list[Stream], object]:
        streams = self.pulse.streams()
        result = match_streams(self.state.focus, streams, parent_of=read_parent_pid)
        return streams, result

    def _appearance(self, result, by_index: dict[int, Stream]) -> tuple[str, str]:
        """Caption and icon for the OSD, mirroring what plasmashell shows.

        The icon comes from the focused window (its ``desktopFileName``), the
        caption from the stream, because a stream usually carries a nicer
        ``application.name`` than the reverse-DNS identifier of the window.
        A descendant match may point at a helper process (``ffmpeg``, a crash
        handler), and then the name of the window itself is the useful one.
        """
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

    def _adjust(self, direction: str, step_percent: float) -> dict:
        streams, result = self._resolve()
        payload = {
            "ok": True,
            "action": direction,
            "step": step_percent,
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
        max_volume = self.config.max_volume_fraction
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
            name, icon = self._appearance(result, by_index)
            payload["osd"] = {"name": name, "icon": icon}
            log.debug("osd: %s%% with icon %r (app %r)", payload["percent"], icon, name)
            self.osd.volume_changed(payload["percent"], icon=icon)
        return payload

    def _toggle_mute(self) -> dict:
        streams, result = self._resolve()
        payload = {
            "ok": True,
            "action": "mute",
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
        name, icon = self._appearance(result, by_index)
        payload["osd"] = {"name": name, "icon": icon}
        if mute:
            self.osd.text(icon, "Muted")
        elif payload["percent"]:
            self.osd.volume_changed(payload["percent"], icon=icon)
        else:
            # Nothing to show on the progress bar.
            self.osd.text(icon, "Unmuted")
        return payload

    def _list(self) -> dict:
        streams, result = self._resolve()
        matched = set(result.indices)
        by_index = {stream.index: stream for stream in streams}
        # Computed even without a match, so `appvol list` can explain which icon
        # the OSD would use for the current window.
        name, icon = self._appearance(result, by_index)
        return {
            "ok": True,
            "config": {
                "step": self.config.step,
                "max_volume": self.config.max_volume,
                "osd": self.config.osd,
            },
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


def _invalid_argument(message: str) -> dbus.DBusException:
    return dbus.DBusException(message, name="org.appvol.Error.InvalidArgument")


class Appvol:
    """Wires the daemon, the pulse connection and the KWin script together."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.bus = dbus.SessionBus()
        # do_not_queue: a second daemon must fail instead of waiting for the name.
        self.bus_name = dbus.service.BusName(BUS_NAME, self.bus, do_not_queue=True)
        self.pulse = PulseManager()
        self.osd = Osd(config.osd)
        self.daemon = Daemon(self.bus, config, self.pulse, self.osd)
        script_path = Path(config.kwin_script).expanduser() if config.kwin_script else find_kwin_script()
        self.kwin = KWinManager(self.bus, script_path)
        self.loop = GLib.MainLoop()
        self._keepalive_id = 0

    def start(self) -> None:
        self.bus.add_signal_receiver(
            self.kwin.on_name_owner_changed,
            signal_name="NameOwnerChanged",
            dbus_interface="org.freedesktop.DBus",
            bus_name="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
        )
        self.kwin.schedule_load()
        self.pulse.keepalive()
        self._keepalive_id = GLib.timeout_add_seconds(PULSE_KEEPALIVE_SECONDS, self._keepalive)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._stop)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._stop)
        log.info("appvol daemon %s started, step %.1f%%, max %.0f%%, osd %s",
                 __version__, self.config.step, self.config.max_volume, self.config.osd)
        self.loop.run()

    def _keepalive(self) -> bool:
        self.pulse.keepalive()
        return True

    def _stop(self) -> bool:
        log.info("shutting down")
        if self._keepalive_id:
            GLib.source_remove(self._keepalive_id)
            self._keepalive_id = 0
        self.kwin.unload()
        self.pulse.close()
        self.loop.quit()
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="appvold", description="appvol daemon")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--config", type=Path, default=None, help="path to config.toml")
    parser.add_argument("--kwin-script", type=Path, default=None, help="override the KWin script path")
    parser.add_argument("--version", action="version", version=f"appvold {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose or os.environ.get("APPVOL_VERBOSE") else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    config = load_config(args.config)
    if args.kwin_script is not None:
        config = replace(config, kwin_script=str(args.kwin_script))

    try:
        app = Appvol(config)
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
