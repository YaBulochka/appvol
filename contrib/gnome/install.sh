#!/usr/bin/env bash
# Install the Appvol GNOME Shell extension for the current user.
#
#   ./install.sh            copy the extension into the GNOME extensions folder
#   ./install.sh --link     symlink it instead, for work on the checkout
#   ./install.sh --remove   disable it and delete the installed copy
set -euo pipefail

uuid=appvol@yabulochka.github.io
here=$(cd "$(dirname "$0")" && pwd)
target=${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$uuid

enable_later() {
    python3 - "$uuid" <<'PY'
import sys

from gi.repository import Gio

uuid = sys.argv[1]
settings = Gio.Settings.new("org.gnome.shell")
items = list(settings.get_strv("enabled-extensions"))
if uuid in items:
    print(f"{uuid} is enabled; log out and back in to load it")
    raise SystemExit(0)
items.append(uuid)
settings.set_strv("enabled-extensions", items)
print(f"enabled {uuid} for the next login: log out and back in (Wayland cannot reload the shell)")
PY
}

if command -v gnome-extensions >/dev/null 2>&1; then
    have_gnome_extensions=1
else
    have_gnome_extensions=0
fi

case "${1:-}" in
    --remove|--uninstall)
        [ "$have_gnome_extensions" = 1 ] && gnome-extensions disable "$uuid" 2>/dev/null || true
        rm -rf "$target"
        echo "removed $uuid from $target"
        exit 0
        ;;
    --link|"")
        ;;
    *)
        echo "usage: $0 [--link|--remove]" >&2
        exit 2
        ;;
esac

mkdir -p "$(dirname "$target")"
rm -rf "$target"
if [ "${1:-}" = "--link" ]; then
    ln -s "$here/$uuid" "$target"
    echo "linked $target -> $here/$uuid"
else
    cp -r "$here/$uuid" "$target"
    echo "installed $uuid in $target"
fi

if [ "$have_gnome_extensions" = 1 ] && gnome-extensions enable "$uuid" 2>/dev/null; then
    echo "enabled $uuid"
elif [ "$have_gnome_extensions" = 1 ] && gnome-extensions info "$uuid" >/dev/null 2>&1; then
    echo "installed; enable it in the Extensions app"
else
    # A session that started before the directory existed has not scanned it, and
    # on Wayland the shell cannot be reloaded.  Write the uuid into the enabled
    # list so the next login turns the extension on by itself.
    enable_later
fi
