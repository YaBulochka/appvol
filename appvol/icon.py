"""Resolve the icon name the OSD shows for an application.

Two sources, in this order.

1. **The stream** — the same source the KDE mixer (plasma-pa) uses.  Plasma takes
   the icon of a playing stream from the stream properties: the first one that
   the icon theme can render wins, in the order ``device.icon_name``,
   ``media.icon_name``, ``window.icon_name``, ``application.icon_name``,
   ``application.process.binary``, ``application.name``,
   ``pipewire.access.portal.app_id`` (``PulseAudioQt::PulseObject::iconName()``).
   appvol repeats that chain, so the OSD shows what the mixer shows.  Properties
   of the owning client are merged into the stream properties, as for matching,
   which gives a few extra hits: Spotify keeps ``application.process.binary`` on
   its client, not on the stream.

2. **The window** — when the stream advertises nothing the theme knows, the
   ``Icon=`` of the window's .desktop file is used (the icon the panel shows),
   and as a last resort the identifier itself.

Whether the theme can render a name is decided without Qt, by walking the icon
theme the same way QIcon does: the theme named in ``kdeglobals``, its
``Inherits`` chain, then ``hicolor``, then the unthemed ``pixmaps`` directories.
QIcon also retries a name without its trailing ``-segment`` (``spotify-launcher``
renders as ``spotify``), and :func:`resolvable` mirrors that.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

from .focus import desktop_file_stem

log = logging.getLogger(__name__)

DESKTOP_ENTRY_GROUP = "Desktop Entry"
KDE_GLOBALS_GROUP = "Icons"
ICON_THEME_GROUP = "Icon Theme"
DEFAULT_THEME = "breeze"
FALLBACK_THEME = "hicolor"
ICON_SUFFIXES = (".png", ".svg", ".svgz", ".xpm")

# Property keys of ``PulseAudioQt::PulseObject::iconName()``, in its order.  Both
# spellings are looked up because the pulse and the PipeWire property namespaces
# differ (``application.icon_name`` vs ``application.icon.name``).
STREAM_ICON_KEYS = (
    "device.icon_name",
    "device.icon.name",
    "device.icon-name",
    "media.icon_name",
    "media.icon.name",
    "media.icon-name",
    "window.icon_name",
    "window.icon.name",
    "window.icon-name",
    "application.icon_name",
    "application.icon.name",
    "application.icon-name",
    "application.process.binary",
    "application.name",
    "pipewire.access.portal.app_id",
)

EXTRA_ICON_ROOTS = ("~/.icons",)
EXTRA_APPLICATION_DIRS = (
    "flatpak/exports/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    "/var/lib/snapd/desktop/applications",
)


# --------------------------------------------------------------------------- #
# XDG locations
# --------------------------------------------------------------------------- #


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path("~/.local/share").expanduser())


def _data_dirs() -> list[Path]:
    raw = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(item) for item in raw.split(":") if item]


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path("~/.config").expanduser())


def _unique(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return tuple(result)


@lru_cache(maxsize=1)
def application_dirs() -> tuple[Path, ...]:
    """Directories that may hold ``*.desktop`` files, in lookup order."""
    candidates = [directory / "applications" for directory in (_data_home(), *_data_dirs())]
    candidates.append(_data_home() / EXTRA_APPLICATION_DIRS[0])
    candidates.append(Path(EXTRA_APPLICATION_DIRS[1]))
    candidates.append(Path(EXTRA_APPLICATION_DIRS[2]))
    return _unique(candidates)


@lru_cache(maxsize=1)
def icon_roots() -> tuple[Path, ...]:
    """Directories that hold icon themes, in lookup order."""
    candidates = [directory / "icons" for directory in (_data_home(), *_data_dirs())]
    candidates += [Path(item).expanduser() for item in EXTRA_ICON_ROOTS]
    return _unique(candidates)


@lru_cache(maxsize=1)
def pixmap_dirs() -> tuple[Path, ...]:
    """Unthemed directories QIcon falls back to."""
    return _unique(directory / "pixmaps" for directory in (_data_home(), *_data_dirs()))


@lru_cache(maxsize=1)
def icon_theme() -> str:
    """Icon theme of the session, as configured in ``kdeglobals``."""
    try:
        text = (_config_home() / "kdeglobals").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return DEFAULT_THEME
    for key, value in group_entries(text, KDE_GLOBALS_GROUP):
        if key == "Theme" and value:
            return value
    return DEFAULT_THEME


# --------------------------------------------------------------------------- #
# INI-style parsing (``*.desktop`` and ``index.theme`` are both this format)
# --------------------------------------------------------------------------- #


def group_entries(text: str, group: str) -> Iterator[tuple[str, str]]:
    """Yield ``key, value`` pairs of one group, skipping comments and locals."""
    section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != group or "=" not in line:
            continue
        key, _, value = line.partition("=")
        yield key.strip(), value.strip()


def parse_icon(text: str) -> str | None:
    """Return the ``Icon=`` value of the ``[Desktop Entry]`` group."""
    for key, value in group_entries(text, DESKTOP_ENTRY_GROUP):
        if key == "Icon":
            return value or None
    return None


# --------------------------------------------------------------------------- #
# Icon theme lookup
# --------------------------------------------------------------------------- #


def _first_index_theme(theme: str, roots: Sequence[Path]) -> Path | None:
    for root in roots:
        candidate = root / theme / "index.theme"
        if candidate.is_file():
            return candidate
    return None


def _declared_directories(theme_dir: Path) -> list[Path]:
    """The icon directories one theme install declares, empty without an index."""
    try:
        text = (theme_dir / "index.theme").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    declared: list[Path] = []
    for key, value in group_entries(text, ICON_THEME_GROUP):
        if key == "Directories" and value:
            declared += [theme_dir / item.strip() for item in value.split(",") if item.strip()]
    return declared


@lru_cache(maxsize=64)
def _theme_subdirectories(theme: str, roots: tuple[Path, ...]) -> tuple[Path, ...]:
    """Directories of one theme that may contain icons, across every root.

    A theme is merged over the XDG roots: the user's ``~/.local/share/icons``
    adds icons to a theme installed under ``/usr/share``, often without an
    ``index.theme`` of its own.  Steam, for one, writes its game icons into
    ``hicolor/<size>/apps/steam_icon_<appid>.png`` there.  Every root that holds
    the theme is therefore looked at, not only the first one with an index.
    """
    found: list[Path] = []
    for root in roots:
        theme_dir = root / theme
        if not theme_dir.is_dir():
            continue
        declared = _declared_directories(theme_dir)
        if declared:
            found += declared
            continue
        # No usable index.theme here: look at the usual two levels.
        found.append(theme_dir)
        found += sorted(path for path in theme_dir.glob("*") if path.is_dir())
        found += sorted(path for path in theme_dir.glob("*/*") if path.is_dir())
    return _unique(found)


def _theme_inherits(theme: str, roots: Sequence[Path]) -> list[str]:
    index = _first_index_theme(theme, roots)
    if index is None:
        return []
    try:
        text = index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for key, value in group_entries(text, ICON_THEME_GROUP):
        if key == "Inherits" and value:
            return [item.strip() for item in value.split(",") if item.strip()]
    return []


@lru_cache(maxsize=16)
def theme_chain(theme: str, roots: tuple[Path, ...]) -> tuple[str, ...]:
    """``theme`` followed by the themes it inherits, ``hicolor`` last."""
    chain: list[str] = []
    pending = [theme]
    while pending:
        name = pending.pop(0)
        if not name or name in chain:
            continue
        chain.append(name)
        pending.extend(_theme_inherits(name, roots))
    if FALLBACK_THEME not in chain:
        chain.append(FALLBACK_THEME)
    return tuple(chain)


def has_icon(
    name: str,
    theme: str | None = None,
    roots: Sequence[Path] | None = None,
    pixmaps: Sequence[Path] | None = None,
) -> bool:
    """True when the icon theme holds an icon called ``name``."""
    if not name:
        return False
    if name.startswith("/"):
        return Path(name).is_file()
    if "/" in name:
        return False

    return _has_icon(
        name,
        theme or icon_theme(),
        tuple(roots) if roots is not None else None,
        tuple(pixmaps) if pixmaps is not None else None,
    )


@lru_cache(maxsize=4096)
def _has_icon(
    name: str,
    theme: str,
    roots: tuple[Path, ...] | None,
    pixmaps: tuple[Path, ...] | None,
) -> bool:
    """``has_icon`` behind a cache.

    One lookup walks every directory of the theme chain, hundreds of ``stat``
    calls for a name the theme does not know.  The panel asks for the same
    handful of stream values on every overview, and the window polls for it, so
    the answer is worth remembering.  Like the other theme caches, it lives for
    the session: installing a theme mid-session is the one case it misses.
    """
    theme_roots = roots if roots is not None else icon_roots()
    for candidate_theme in theme_chain(theme, theme_roots):
        for directory in _theme_subdirectories(candidate_theme, theme_roots):
            for suffix in ICON_SUFFIXES:
                if (directory / f"{name}{suffix}").is_file():
                    return True

    for directory in pixmaps if pixmaps is not None else pixmap_dirs():
        for suffix in ICON_SUFFIXES:
            if (directory / f"{name}{suffix}").is_file():
                return True
    return False


def resolvable(
    name: str,
    theme: str | None = None,
    roots: Sequence[Path] | None = None,
    pixmaps: Sequence[Path] | None = None,
) -> bool:
    """True when the theme can render ``name``, QIcon's ``-suffix`` fallback included."""
    candidate = name
    while candidate:
        if has_icon(candidate, theme, roots, pixmaps):
            return True
        if "-" not in candidate:
            break
        candidate = candidate.rsplit("-", 1)[0]
    return False


@lru_cache(maxsize=8)
def _theme_icon_names(
    theme: str, roots: tuple[Path, ...], pixmaps: tuple[Path, ...]
) -> tuple[str, ...]:
    """Icon names of one theme chain, cached; the scan is once per theme."""
    names: set[str] = set()
    for candidate_theme in theme_chain(theme, roots):
        for directory in _theme_subdirectories(candidate_theme, roots):
            for suffix in ICON_SUFFIXES:
                for path in directory.glob(f"*{suffix}"):
                    names.add(path.name[: -len(suffix)])
    for directory in pixmaps:
        for suffix in ICON_SUFFIXES:
            for path in directory.glob(f"*{suffix}"):
                names.add(path.name[: -len(suffix)])
    return tuple(sorted(names))


def theme_icon_names(
    theme: str | None = None,
    roots: Sequence[Path] | None = None,
    pixmaps: Sequence[Path] | None = None,
) -> tuple[str, ...]:
    """Every icon name the theme chain can render, sorted, for an icon chooser."""
    return _theme_icon_names(
        theme or icon_theme(),
        tuple(roots) if roots is not None else icon_roots(),
        tuple(pixmaps) if pixmaps is not None else pixmap_dirs(),
    )


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def stream_icon(
    props: Mapping[str, str] | None,
    theme: str | None = None,
    roots: Sequence[Path] | None = None,
    pixmaps: Sequence[Path] | None = None,
) -> str | None:
    """Icon the KDE mixer shows for a stream, or ``None``."""
    for key in STREAM_ICON_KEYS:
        value = str((props or {}).get(key) or "").strip()
        if value and resolvable(value, theme, roots, pixmaps):
            log.debug("icon %r comes from the stream property %s", value, key)
            return value
    return None


def desktop_file_icon(stem: str, dirs: Sequence[Path] | None = None) -> str | None:
    """``Icon=`` of ``<stem>.desktop``, or ``None`` when no file matches."""
    stem = desktop_file_stem(stem)
    if not stem:
        return None
    search_dirs = tuple(dirs) if dirs is not None else application_dirs()
    for directory in search_dirs:
        path = directory / f"{stem}.desktop"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        icon = parse_icon(text)
        if icon:
            return icon
        log.debug("desktop file %s has no Icon= entry", path)
    return None


def resolve(
    desktop_file_name: str = "",
    resource_class: str = "",
    props: Mapping[str, str] | None = None,
    dirs: Sequence[Path] | None = None,
    theme: str | None = None,
    roots: Sequence[Path] | None = None,
    pixmaps: Sequence[Path] | None = None,
) -> str | None:
    """Icon name for the application that owns the matched streams."""
    icon = stream_icon(props, theme, roots, pixmaps)
    if icon:
        return icon

    stems = [desktop_file_stem(desktop_file_name), desktop_file_stem(resource_class)]
    for stem in stems:
        icon = desktop_file_icon(stem, dirs)
        if icon and resolvable(icon, theme, roots, pixmaps):
            return icon

    for stem in stems:
        if stem and "." not in stem and resolvable(stem, theme, roots, pixmaps):
            # A bare name such as "mpv" is often a theme icon itself; reverse-DNS
            # names ("org.kde.konsole") are desktop file names only.
            return stem
    return None
