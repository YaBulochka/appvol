"""``appvol`` — the command line client.

The client is deliberately thin: it forwards one D-Bus call to ``appvold`` and
prints the answer.  It never talks to KWin and never queries PipeWire, so a
key press costs a single round trip on the session bus.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import dbus

from . import __version__
from .config import load as load_config

log = logging.getLogger("appvol.cli")

BUS_NAME = "org.appvol.Daemon"
OBJECT_PATH = "/org/appvol/Daemon"
IFACE = "org.appvol.Daemon"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="appvol",
        description="Change the volume of the app whose window is focused.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--json", action="store_true", help="print the raw daemon answer")
    parser.add_argument("--version", action="version", version=f"appvol {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("up", "raise the volume of the focused app"),
        ("down", "lower the volume of the focused app"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument(
            "--step",
            type=float,
            default=None,
            metavar="PERCENT",
            help="relative step in percent (default: value from config)",
        )

    sub.add_parser("mute", help="toggle mute of the focused app")
    sub.add_parser("list", help="show streams, cached focus and the match result")
    return parser


def daemon_proxy():
    bus = dbus.SessionBus()
    return dbus.Interface(bus.get_object(BUS_NAME, OBJECT_PATH), IFACE)


def _short(result: dict) -> str:
    matched = result.get("matched", 0)
    plural = "" if matched == 1 else "s"
    if not matched:
        return f"nothing to do: {result.get('reason', 'no matching streams')}"
    if result.get("action") == "mute":
        state = "muted" if result.get("muted") else "unmuted"
        labels = ", ".join(dict.fromkeys(entry["label"] for entry in result.get("streams", [])))
        return f"{labels}: {state} ({matched} stream{plural})"
    parts = [
        f"{entry['label']} {entry['from'][0]}% -> {entry['to'][0]}%"
        for entry in result.get("streams", [])
    ]
    summary = "; ".join(parts) if parts else "no change"
    return f"{summary} ({matched} stream{plural}, matched by {result.get('match_step')})"


def _print_list(result: dict) -> None:
    focus = result.get("focus", {})
    config = result.get("config", {})
    match = result.get("match", {})

    print(f"config: step {config.get('step')}%, max {config.get('max_volume')}%, osd {config.get('osd')}")
    age = focus.get("age")
    age_text = f"{age:.1f}s ago" if isinstance(age, (int, float)) else "never"
    print(f"focus:  pid {focus.get('pid')} {focus.get('label')!r} ({age_text})")
    if focus.get("resource_class") or focus.get("desktop_file_name"):
        print(f"        resourceClass={focus.get('resource_class')} desktopFileName={focus.get('desktop_file_name')}")
    if focus.get("ignored_reason"):
        print(f"        ignored: {focus['ignored_reason']}")
    print(f"match:  step={match.get('step') or '-'} matched={match.get('matched')} ({match.get('reason')})")
    if result.get("osd"):
        osd = result["osd"]
        app = f" (app {osd['name']!r})" if osd.get("name") else ""
        print(f"osd:    icon={osd.get('icon')!r}{app}")
    print("streams:")
    streams = result.get("streams", [])
    if not streams:
        print("  (none)")
        return
    for stream in streams:
        marker = "*" if stream.get("matched") else " "
        mute = " [muted]" if stream.get("muted") else ""
        print(
            f" {marker} #{stream['index']:<6} {stream['percent']:>3}%"
            f" {stream['label']!r}{mute} pid={stream['pid']}"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose or os.environ.get("APPVOL_VERBOSE") else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    try:
        proxy = daemon_proxy()
    except dbus.DBusException as exc:
        if exc.get_dbus_name() == "org.freedesktop.DBus.Error.ServiceUnknown":
            print("appvol: appvold is not running (start it with: systemctl --user start appvold)", file=sys.stderr)
        else:
            print(f"appvol: cannot reach the session bus: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        if args.command in ("up", "down"):
            step = args.step if args.step is not None else load_config().step
            result = json.loads(proxy.Adjust(args.command, dbus.Double(float(step))))
        elif args.command == "mute":
            result = json.loads(proxy.ToggleMute())
        elif args.command == "list":
            result = json.loads(proxy.List())
        else:  # pragma: no cover - argparse enforces the set
            print(f"appvol: unknown command {args.command}", file=sys.stderr)
            return EXIT_USAGE
    except dbus.exceptions.DBusException as exc:
        if exc.get_dbus_name() == "org.freedesktop.DBus.Error.ServiceUnknown":
            print("appvol: appvold is not running (start it with: systemctl --user start appvold)", file=sys.stderr)
        elif exc.get_dbus_name() == "org.appvol.Error.InvalidArgument":
            print(f"appvol: {exc.get_dbus_message()}", file=sys.stderr)
            return EXIT_USAGE
        else:
            print(f"appvol: daemon call failed: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "list":
        _print_list(result)
    else:
        print(_short(result))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
