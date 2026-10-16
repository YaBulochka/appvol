#!/bin/sh
# Refresh the hicolor theme cache after appvol-gui installed or removed its
# icons.  fpm runs this as the .deb maintainer script and as the .rpm
# scriptlet, where a missing gtk-update-icon-cache is not an error.
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
