// appvol KWin script.
//
// Pushes the focused window to the appvol daemon.  The daemon loads this file
// itself through org.kde.kwin.Scripting, so it must stay dependency free and
// must never touch anything but callDBus.
//
// Verified against KWin 6.7.5 (Plasma 6.7.5): workspace.activeWindow exposes
// pid, resourceClass, desktopFileName, caption and windowType, callDBus accepts
// integral JS numbers for D-Bus "i" arguments, and workspace.windowActivated
// exists.  Kept in sync with appvol/daemon.py (SetFocus signature "isss").

const SERVICE = "org.appvol.Daemon";
const PATH = "/org/appvol/Daemon";
const IFACE = "org.appvol.Daemon";

// KWin WindowType enum values that never belong to a normal application window.
const WINDOW_TYPE_DESKTOP = 1;
const WINDOW_TYPE_DOCK = 2;

function reportFocus() {
    const window = workspace.activeWindow;
    if (!window || !window.pid
            || window.windowType === WINDOW_TYPE_DESKTOP
            || window.windowType === WINDOW_TYPE_DOCK) {
        callDBus(SERVICE, PATH, IFACE, "SetFocus", 0, "", "", "");
        return;
    }
    callDBus(SERVICE, PATH, IFACE, "SetFocus",
        Math.round(window.pid),
        String(window.resourceClass || ""),
        String(window.desktopFileName || ""),
        String(window.caption || ""));
}

reportFocus();
workspace.windowActivated.connect(reportFocus);
