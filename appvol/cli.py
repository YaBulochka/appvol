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

log = logging.getLogger("appvol.cli")

BUS_NAME = "org.appvol.Daemon"
OBJECT_PATH = "/org/appvol/Daemon"
IFACE = "org.appvol.Daemon"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


def _add_profile_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        default="",
        metavar="ID",
        help="act on this profile for one call, without switching to it",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="appvol",
        description="Change the volume of the focused application, or of a profile.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--json", action="store_true", help="print the raw daemon answer")
    parser.add_argument("--version", action="version", version=f"appvol {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("up", "raise the volume of the current profile"),
        ("down", "lower the volume of the current profile"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument(
            "--step",
            type=float,
            default=None,
            metavar="PERCENT",
            help="relative step in percent (default: the profile's step, else the config's)",
        )
        _add_profile_option(cmd)

    mute = sub.add_parser("mute", help="toggle mute of the current profile")
    _add_profile_option(mute)

    sub.add_parser("list", help="show streams, cached focus, profiles and the match result")
    sub.add_parser("apps", help="applications playing right now, with their identifiers")

    profile = sub.add_parser("profile", help="manage profiles")
    actions = profile.add_subparsers(dest="profile_command", required=True)
    actions.add_parser("list", help="show the profiles and which one is current")
    add = actions.add_parser("add", help="create or replace a profile")
    add.add_argument("id", help="short name without spaces, for example spotify")
    add.add_argument("--name", default="", help="name to show in the OSD")
    add.add_argument(
        "--include",
        default="",
        metavar="APP[,APP]",
        help="applications to control (default: every application stream)",
    )
    add.add_argument(
        "--exclude",
        default="",
        metavar="APP[,APP]",
        help="applications to leave alone, which is how an inversion profile is made",
    )
    add.add_argument("--step", type=float, default=0.0, metavar="PERCENT", help="step in percent")
    add.add_argument(
        "--max-volume", type=float, default=0.0, metavar="PERCENT", help="volume ceiling in percent"
    )
    add.add_argument("--icon", default="", help="icon name override")
    remove = actions.add_parser("rm", help="remove a profile and its key binding")
    remove.add_argument("id")
    toggle = actions.add_parser("toggle", help="switch to a profile, or back to Active")
    toggle.add_argument("id", help="profile id, or active for the built-in profile")
    actions.add_parser("reload", help="read profiles.toml again after a hand edit")
    return parser


def daemon_proxy():
    bus = dbus.SessionBus()
    return dbus.Interface(bus.get_object(BUS_NAME, OBJECT_PATH), IFACE)


def _split(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _short(result: dict) -> str:
    matched = result.get("matched", 0)
    plural = "" if matched == 1 else "s"
    profile = result.get("profile") or {}
    identifier = profile.get("id", "")
    prefix = "" if identifier in ("", "active") else f"{profile.get('name') or identifier}: "
    if not matched:
        return f"{prefix}nothing to do: {result.get('reason', 'no matching streams')}"
    if result.get("action") == "mute":
        state = "muted" if result.get("muted") else "unmuted"
        labels = ", ".join(dict.fromkeys(entry["label"] for entry in result.get("streams", [])))
        return f"{prefix}{labels}: {state} ({matched} stream{plural})"
    if result.get("action") == "profile":
        return f"{prefix}current profile ({matched} stream{plural}, matched by {result.get('match_step')})"
    parts = [
        f"{entry['label']} {entry['from'][0]}% -> {entry['to'][0]}%"
        for entry in result.get("streams", [])
    ]
    summary = "; ".join(parts) if parts else "no change"
    return f"{prefix}{summary} ({matched} stream{plural}, matched by {result.get('match_step')})"


def _print_profiles(result: dict) -> None:
    profiles = result.get("profiles", [])
    current = result.get("current", "")
    timeout = result.get("idle_timeout")
    print(f"current: {current}" + (f", back to active after {timeout:g}s idle" if timeout else ""))
    if not profiles:
        print("profiles: none  (create one with: appvol profile add spotify --include spotify)")
        return
    print("profiles:")
    for profile in profiles:
        scope = ", ".join(profile.get("include", [])) or "every application stream"
        if profile.get("exclude"):
            scope += f" without {', '.join(profile['exclude'])}"
        details = [
            f"step {profile['step']:g}%" if profile.get("step") else "",
            f"max {profile['max_volume']:g}%" if profile.get("max_volume") else "",
            f"icon {profile['icon']}" if profile.get("icon") else "",
        ]
        suffix = f"  ({', '.join(part for part in details if part)})" if any(details) else ""
        marker = "*" if profile.get("id") == current else " "
        print(f" {marker} {profile.get('id'):<12} {profile.get('name')!r} {scope}{suffix}")


def _print_list(result: dict) -> None:
    focus = result.get("focus", {})
    config = result.get("config", {})
    match = result.get("match", {})
    profile = result.get("profile", {})

    print(f"config: step {config.get('step')}%, max {config.get('max_volume')}%, osd {config.get('osd')}")
    if profile.get("mode") == "focus":
        scope = "the focused window"
    else:
        scope = ", ".join(profile.get("include", [])) or "every application stream"
        if profile.get("exclude"):
            scope += f" without {', '.join(profile['exclude'])}"
    print(f"profile: {profile.get('name')!r} [{profile.get('mode')}] {scope}")
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


def _print_applications(result: dict) -> None:
    applications = result.get("applications", [])
    if not applications:
        print("nothing is playing right now")
        return
    print("applications:")
    for application in applications:
        flags = []
        if application.get("muted"):
            flags.append("muted")
        if application.get("panel"):
            flags.append("shell")
        streams = len(application.get("streams", []))
        suffix = f"  ({', '.join(flags)})" if flags else ""
        print(
            f"  {application.get('percent', 0):>3}%  {application.get('label', ''):<22}"
            f" {application.get('id', ''):<22} {streams} stream{'' if streams == 1 else 's'}"
            f"{suffix}"
        )


def _profile(proxy, args) -> tuple[dict, str]:
    """Run a ``profile`` subcommand; returns the payload and how to print it."""
    if args.profile_command == "list":
        return json.loads(proxy.Profiles()), "profiles"
    if args.profile_command == "add":
        payload = proxy.AddProfile(
            args.id,
            args.name,
            _split(args.include),
            _split(args.exclude),
            dbus.Double(float(args.step or 0.0)),
            dbus.Double(float(args.max_volume or 0.0)),
            args.icon,
        )
        return json.loads(payload), "profiles"
    if args.profile_command == "rm":
        return json.loads(proxy.RemoveProfile(args.id)), "profiles"
    if args.profile_command == "reload":
        return json.loads(proxy.Reload()), "profiles"
    if args.profile_command == "toggle":
        return json.loads(proxy.ToggleProfile(args.id)), "short"
    print(f"appvol: unknown profile command {args.profile_command}", file=sys.stderr)
    raise SystemExit(EXIT_USAGE)


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

    kind = "short"
    try:
        if args.command in ("up", "down"):
            result = json.loads(
                proxy.AdjustTarget(
                    str(args.profile), args.command, dbus.Double(float(args.step or 0.0))
                )
            )
        elif args.command == "mute":
            result = json.loads(proxy.ToggleMuteTarget(str(args.profile)))
        elif args.command == "list":
            result = json.loads(proxy.List())
            kind = "list"
        elif args.command == "apps":
            result = json.loads(proxy.Applications())
            kind = "apps"
        elif args.command == "profile":
            result, kind = _profile(proxy, args)
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
    elif kind == "list":
        _print_list(result)
    elif kind == "apps":
        _print_applications(result)
    elif kind == "profiles":
        _print_profiles(result)
    else:
        print(_short(result))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
