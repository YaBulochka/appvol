"""The focus target: the window the compositor currently reports as active.

The KWin script pushes four fields of ``workspace.activeWindow`` to the daemon:
``pid``, ``resourceClass``, ``desktopFileName`` and ``caption``.  This module
turns them into a :class:`Focus` value object and provides the helpers used to
decide whether a focus is worth acting on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# resourceClass / desktopFileName values that never belong to an application.
PANEL_RESOURCE_CLASSES = frozenset({"plasmashell"})
PANEL_DESKTOP_FILES = frozenset(
    {
        "org.kde.plasmashell",
        "org.kde.kdesktop",
        "org.kde.kwin.desktop",
        "org.kde.kwin",
    }
)

MAX_ANCESTOR_DEPTH = 64


def parse_pid(value: object) -> int:
    """Return a non-negative pid, or ``0`` when the value is unusable."""
    try:
        pid = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return pid if pid > 0 else 0


def desktop_file_stem(value: object) -> str:
    """Normalise an application identifier: lowercase and without ``.desktop``.

    ``"org.mozilla.firefox"`` and ``"firefox.desktop"`` stay distinguishable,
    but ``"Firefox.Desktop"`` becomes ``"firefox"``.
    """
    if not value:
        return ""
    text = str(value).strip().lower()
    if text.endswith(".desktop"):
        text = text[: -len(".desktop")]
    return text


@dataclass(frozen=True)
class Focus:
    """The active window as reported by KWin."""

    pid: int = 0
    resource_class: str = ""
    desktop_file_name: str = ""
    caption: str = ""

    def is_empty(self) -> bool:
        """True when no window is active at all."""
        return (
            self.pid <= 0
            and not self.resource_class
            and not self.desktop_file_name
            and not self.caption
        )

    def ignored_reason(self) -> str | None:
        """Return why the focus must be ignored, or ``None`` when usable."""
        if self.is_empty():
            return "no active window"
        if self.pid <= 0:
            return "active window has no pid"
        if desktop_file_stem(self.resource_class) in PANEL_RESOURCE_CLASSES:
            return f"panel or desktop window ({self.resource_class})"
        if desktop_file_stem(self.desktop_file_name) in PANEL_DESKTOP_FILES:
            return f"panel or desktop window ({self.desktop_file_name})"
        if desktop_file_stem(self.resource_class) in PANEL_DESKTOP_FILES:
            return f"panel or desktop window ({self.resource_class})"
        return None

    @property
    def label(self) -> str:
        """Human readable name used in logs and in ``appvol list``."""
        return self.desktop_file_name or self.resource_class or self.caption or "unknown"


def read_parent_pid(pid: int) -> int | None:
    """Read ``PPid`` for ``pid`` from ``/proc/<pid>/stat``.

    ``/proc/<pid>/stat`` puts the executable name, which may contain spaces and
    parentheses, into the second field.  Splitting on the last ``)`` is the only
    reliable way to reach the numeric fields.
    """
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as handle:
            data = handle.read()
    except (OSError, ValueError):
        return None
    try:
        fields = data.rsplit(b")", 1)[1].split()
        return int(fields[1])
    except (IndexError, ValueError):
        return None


def is_descendant(
    pid: int,
    ancestor: int,
    parent_of: Callable[[int], int | None] = read_parent_pid,
    max_depth: int = MAX_ANCESTOR_DEPTH,
) -> bool:
    """True when ``pid`` is a strict descendant of ``ancestor``.

    Firefox, Chromium and Electron spawn separate audio processes, so the
    window pid is only the root of the process tree that owns the stream.
    """
    if pid <= 0 or ancestor <= 0 or pid == ancestor:
        return False
    current = pid
    seen = {current}
    for _ in range(max_depth):
        parent = parent_of(current)
        if parent is None or parent <= 1:
            return False
        if parent == ancestor:
            return True
        if parent in seen:
            return False
        seen.add(parent)
        current = parent
    return False


def focus_from_dbus(
    pid: object = 0,
    resource_class: object = "",
    desktop_file_name: object = "",
    caption: object = "",
) -> Focus:
    """Build a :class:`Focus` from the raw D-Bus arguments."""
    return Focus(
        pid=parse_pid(pid),
        resource_class=str(resource_class or ""),
        desktop_file_name=str(desktop_file_name or ""),
        caption=str(caption or ""),
    )
