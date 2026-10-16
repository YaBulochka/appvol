#!/usr/bin/env bash
# Install appvol for the current user, without root.
#
#   ./install.sh                # install or upgrade into ~/.local
#   ./install.sh --service      # ... and start the daemon with the session
#   ./install.sh --prefix DIR   # install into DIR instead of ~/.local
#   ./install.sh --no-gui       # skip the window and the tray icon
#   ./install.sh --uninstall    # remove what this script installed
#   ./install.sh --help
#
# PREFIX and DESTDIR are honoured like they are in a package build: PREFIX
# (or --prefix) is the runtime root, DESTDIR is prepended to every path that is
# written.  A packager stages with  PREFIX=/usr DESTDIR=/tmp/pkg  and gets the
# tree under /tmp/pkg; the unit and the desktop entry still hold the runtime
# paths, so the staged files are ready to be packaged as is.
#
# What it installs:
#
#   <prefix>/share/appvol/                 the package, the KWin script, the templates
#   <prefix>/bin/appvol, appvold, ...      symlinks to the launchers there
#   ~/.config/systemd/user/appvold.service the user unit (ExecStart is absolute)
#
# The global shortcuts (the volume keys, the profile keys) belong to the running
# daemon, so they appear in System Settings while it runs and no desktop file is
# installed for them.
#
# With PySide6 installed it also adds the window and the tray icon:
#
#   ~/.local/share/applications/org.appvol.gui.desktop
#   ~/.local/share/icons/hicolor/scalable/apps/appvol.svg
#   ~/.local/share/icons/hicolor/symbolic/apps/appvol-symbolic.svg
#
# Nothing outside those paths is touched, and no root privileges are needed.
# Arch users may prefer the pacman package instead: see packaging/PKGBUILD.
set -euo pipefail

self="$(readlink -f "${BASH_SOURCE[0]}")"
root="$(dirname "$self")"
python="${PYTHON:-python3}"
prefix="${PREFIX:-$HOME/.local}"
destdir="${DESTDIR:-}"
config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"

install_dir="$prefix/share/appvol"
unit="$config_home/systemd/user/appvold.service"
gui_entry="$data_home/applications/org.appvol.gui.desktop"
gui_icon="$prefix/share/icons/hicolor/scalable/apps/appvol.svg"
gui_symbolic="$prefix/share/icons/hicolor/symbolic/apps/appvol-symbolic.svg"

usage() {
    sed -n '2,34p' "$self" | sed 's/^# \{0,1\}//'
    echo
    echo "Options: --service  --prefix DIR  --no-gui  --uninstall  --help"
}

with_service=no
with_gui=auto
action=install
while [ $# -gt 0 ]; do
    case "$1" in
        --service) with_service=yes ;;
        --no-gui) with_gui=no ;;
        --gui) with_gui=yes ;;
        --uninstall|--remove) action=uninstall ;;
        --prefix)
            [ $# -ge 2 ] || { echo "appvol: --prefix needs a directory" >&2; exit 2; }
            prefix="$2"
            install_dir="$prefix/share/appvol"
            shift
            ;;
        -h|--help) usage; exit 0 ;;
        *) echo "appvol: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

# The pacman package exists for this; a per-user install has no business running
# as root, and doing so would create root-owned files in the user's home.  With
# DESTDIR the script only stages a tree, which a packager runs as root.
if [ -z "$destdir" ] && [ "$(id -u)" -eq 0 ]; then
    echo "appvol: run this as your desktop user, not as root; no root is needed" >&2
    exit 1
fi

missing_modules() {
    local module
    for module in dbus gi pulsectl; do
        "$python" -c "import $module" >/dev/null 2>&1 || echo "$module"
    done
}

# The window and the tray icon need PySide6; the daemon and the CLI do not, so a
# missing PySide6 is not a failure, only a note at the end.
want_gui() {
    case "$with_gui" in
        yes) return 0 ;;
        no) return 1 ;;
    esac
    "$python" -c "import PySide6" >/dev/null 2>&1
}

# A package build stages the tree and leaves the cache to the package manager, so
# this only runs for a per-user install, and a missing tool is not an error.
update_icon_cache() {
    if [ -n "$destdir" ] || ! command -v gtk-update-icon-cache >/dev/null 2>&1; then
        return 0
    fi
    gtk-update-icon-cache -f -t "$1" >/dev/null 2>&1 || true
}

check_dependencies() {
    local missing
    missing="$(missing_modules)"
    if [ -z "$missing" ]; then
        return 0
    fi
    cat >&2 <<EOF
appvol: missing Python modules: ${missing//$'\n'/ }
        Arch:   sudo pacman -S python-dbus python-gobject python-pulsectl
        Debian: sudo apt install python3-dbus python3-gi python3-pulsectl
        Fedora: sudo dnf install python3-dbus python3-gobject python3-pulsectl
        If your distribution has no package for one of them (pulsectl is the
        usual case), install it with: $python -m pip install --user <name>
EOF
    return 1
}

uninstall() {
    if [ -z "$destdir" ] && command -v systemctl >/dev/null 2>&1; then
        systemctl --user disable --now appvold >/dev/null 2>&1 || true
    fi
    if [ -f "$destdir$unit" ]; then
        rm -f "$destdir$unit"
        if [ -z "$destdir" ] && command -v systemctl >/dev/null 2>&1; then
            systemctl --user daemon-reload || true
        fi
    fi
    local name
    for name in appvol appvold appvol-gui; do
        rm -f "$destdir$prefix/bin/$name"
    done
    rm -f "$destdir$gui_entry" "$destdir$gui_icon" "$destdir$gui_symbolic"
    rm -rf "$destdir$install_dir"
    # Only succeeds when nothing else lives there.
    rmdir "$destdir$prefix/bin" "$destdir$prefix/share" 2>/dev/null || true
    echo "appvol: removed from $destdir$prefix, together with the unit and the shortcut entry"
    exit 0
}

report_unit() {
    # A staged tree has nothing to enable; the package manager does that later.
    if [ -n "$destdir" ]; then
        echo "appvol: staged under $destdir$prefix (PREFIX=$prefix, DESTDIR=$destdir)"
        return 0
    fi
    if [ "$with_service" = yes ]; then
        systemctl --user daemon-reload
        systemctl --user enable --now appvold
        echo "appvol: daemon enabled and started (systemctl --user status appvold)"
    else
        echo "appvol: start the daemon with the session:"
        echo "        systemctl --user daemon-reload && systemctl --user enable --now appvold"
        echo "        or run $install_dir/bin/appvold in a terminal"
    fi
    echo "appvol: bind the keys in System Settings -> Shortcuts, entry \"Appvol\":"
    echo "        Volume up, Volume down, Toggle mute, Next profile, Previous profile,"
    echo "        and one action per profile. The entry appears while the daemon runs."
}

if [ "$action" = uninstall ]; then
    uninstall
fi

check_dependencies || exit 1

if [ ! -f "$root/appvol/__init__.py" ]; then
    echo "appvol: $self does not look like the appvol checkout" >&2
    exit 1
fi
if [ -e "$destdir$install_dir" ] && [ ! -f "$destdir$install_dir/appvol/__init__.py" ]; then
    echo "appvol: $destdir$install_dir exists and does not look like an appvol install" >&2
    echo "        move it away first, or use --prefix" >&2
    exit 1
fi

# Replace, do not merge: an upgrade must not leave modules behind that the new
# version dropped.
rm -rf "$destdir$install_dir"
install -d "$destdir$install_dir"
for item in appvol kwin desktop bin; do
    cp -r "$root/$item" "$destdir$install_dir/$item"
done
rm -rf "$destdir$install_dir/appvol/__pycache__"
chmod 755 "$destdir$install_dir/bin"/*
echo "appvol: files installed in $destdir$install_dir"

install -d "$destdir$prefix/bin"
for name in appvol appvold; do
    ln -sfn "$install_dir/bin/$name" "$destdir$prefix/bin/$name"
done
if want_gui; then
    ln -sfn "$install_dir/bin/appvol-gui" "$destdir$prefix/bin/appvol-gui"
fi
echo "appvol: launchers linked into $destdir$prefix/bin"

install -d "$destdir$(dirname "$unit")"
sed "s|@APPVOLD@|$install_dir/bin/appvold|" "$root/systemd/appvold.service.in" >"$destdir$unit"
echo "appvol: systemd user unit installed as $destdir$unit"

if want_gui; then
    install -d "$destdir$(dirname "$gui_entry")"
    sed "s|@APPVOL_GUI@|$install_dir/bin/appvol-gui|g" \
        "$root/desktop/org.appvol.gui.desktop.in" >"$destdir$gui_entry"
    # The app icon belongs with the desktop entry; the tray icon is symbolic, so
    # Plasma recolours it with the rest of the panel.
    install -Dm644 "$root/desktop/icons/hicolor/scalable/apps/appvol.svg" \
        "$destdir$gui_icon"
    install -Dm644 "$root/desktop/icons/hicolor/symbolic/apps/appvol-symbolic.svg" \
        "$destdir$gui_symbolic"
    update_icon_cache "$prefix/share/icons/hicolor"
    echo "appvol: window and tray icon installed (appvol-gui)"
elif [ "$with_gui" = auto ]; then
    echo "appvol: note: PySide6 is missing, so the window and the tray icon were skipped"
    echo "        install it (Arch: sudo pacman -S pyside6) and run this script again"
fi

if [ -z "$destdir" ]; then
    case ":$PATH:" in
        *":$prefix/bin:"*) ;;
        *) echo "appvol: note: $prefix/bin is not in PATH, so plain 'appvol' needs the full path" ;;
    esac
fi

report_unit
