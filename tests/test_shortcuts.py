"""The KDE shortcut entry must stay in sync with the client it calls."""

from __future__ import annotations

import unittest
from pathlib import Path

from appvol.cli import build_parser

PROJECT = Path(__file__).resolve().parent.parent
TEMPLATE = PROJECT / "desktop" / "org.appvol.desktop.in"
INSTALLER = PROJECT / "bin" / "appvol-shortcuts"
CLIENT = "/opt/appvol/bin/appvol"
PLACEHOLDER = "@APPVOL@"
ENTRY = "Desktop Entry"
ACTION = "Desktop Action "
COMMANDS = {"VolumeUp": "up", "VolumeDown": "down", "Mute": "mute"}


def parse_groups(text: str) -> dict[str, dict[str, str]]:
    """Turn an INI-style desktop file into ``{group: {key: value}}``."""
    groups: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = groups.setdefault(line[1:-1], {})
            continue
        if current is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        current[key.strip()] = value.strip()
    return groups


def rendered() -> str:
    """The template as the installer writes it."""
    return TEMPLATE.read_text(encoding="utf-8").replace(PLACEHOLDER, CLIENT)


class ShortcutEntryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.groups = parse_groups(rendered())
        self.entry = self.groups[ENTRY]

    def test_is_a_hidden_service_entry(self) -> None:
        self.assertEqual(self.entry["Type"], "Application")
        self.assertEqual(self.entry["NoDisplay"], "true")
        self.assertTrue(self.entry["Name"])
        self.assertTrue(self.entry["Icon"])

    def test_has_no_launch_action(self) -> None:
        # "Service" keeps KDE from adding a "launch the file" action next to the
        # named ones: appvol is not started, it is called.
        self.assertEqual(self.entry["X-KDE-GlobalShortcutType"], "Service")

    def test_is_not_a_command_shortcut(self) -> None:
        # With this flag KDE labels every action with the raw Exec line and files
        # the component under "Commands"; without it the actions keep their Names
        # and KDE lists the component as an application.
        self.assertNotIn("X-KDE-GlobalAccel-CommandShortcut", self.entry)

    def test_declares_no_default_keys_but_stays_visible(self) -> None:
        # A running kglobalaccel only picks up the file when X-KDE-Shortcuts is
        # not empty, and "none" is how KDE spells "no key bound": appvol shows up
        # in the shortcut list without taking a combination away from anyone.
        self.assertEqual(self.entry["X-KDE-Shortcuts"], "none")

    def test_actions_match_the_declared_list(self) -> None:
        declared = [name for name in self.entry["Actions"].split(";") if name]
        self.assertEqual(sorted(declared), sorted(COMMANDS))
        self.assertEqual(
            sorted(name for name in self.groups if name.startswith(ACTION)),
            sorted(ACTION + name for name in declared),
        )

    def test_every_action_runs_the_client_by_absolute_path(self) -> None:
        for name, command in COMMANDS.items():
            action = self.groups[ACTION + name]
            self.assertEqual(action["Exec"], f"{CLIENT} {command}")
            self.assertTrue(action["Name"])
        self.assertEqual(self.entry["Exec"], f"{CLIENT} mute")

    def test_no_placeholder_left_behind(self) -> None:
        self.assertNotIn(PLACEHOLDER, rendered())

    def test_every_command_is_accepted_by_the_client(self) -> None:
        parser = build_parser()
        for command in COMMANDS.values():
            parser.parse_args([command])


class InstallerTest(unittest.TestCase):
    def test_installer_is_executable_and_uses_the_template(self) -> None:
        self.assertTrue(INSTALLER.stat().st_mode & 0o111, INSTALLER)
        text = INSTALLER.read_text(encoding="utf-8")
        self.assertIn(TEMPLATE.name, text)
        self.assertIn("org.appvol.desktop", text)


if __name__ == "__main__":
    unittest.main()
