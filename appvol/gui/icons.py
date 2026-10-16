"""The icon files of the project, for a checkout that has no installation.

The window and the tray name their icons in the theme, ``appvol`` and
``appvol-symbolic``, and a normal install puts them into the user's or the
system's hicolor tree.  ``bin/appvol-gui`` runs from a checkout, where no such
install exists yet, so :func:`checkout_icon_path` maps a theme name back to the
SVG that ships with the sources.  Qt is not imported here, so the lookup can be
tested without PySide6.
"""

from __future__ import annotations

from pathlib import Path

# desktop/icons next to appvol/ in the checkout, and under /opt/appvol in the
# .deb and .rpm packages, which carry the whole tree as well.
ICON_ROOT = Path(__file__).resolve().parents[2] / "desktop" / "icons" / "hicolor"

# The size directories an icon may live in.  The names do not clash: the tray
# asks for the symbolic one, the window for the plain one.
_SIZES = ("symbolic", "scalable")


def checkout_icon_path(name: str) -> Path | None:
    """The checkout's file for a theme name, or None when there is none."""
    for size in _SIZES:
        candidate = ICON_ROOT / size / "apps" / f"{name}.svg"
        if candidate.is_file():
            return candidate
    return None
