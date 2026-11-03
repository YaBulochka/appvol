/* Appvol for GNOME Shell.
 *
 * Two jobs, both of which have to run inside the shell:
 *
 *  - push the focused window to appvold, the same way the KWin script does on
 *    Plasma, so the built-in Active profile follows the window you look at;
 *  - export org.appvol.GnomeShell, which appvold calls to draw its OSD.  The
 *    shell's own org.gnome.Shell.ShowOSD refuses every client that is not
 *    gnome-settings-daemon or a portal backend, so the extension reaches
 *    Main.osdWindowManager directly and the daemon talks to the extension.
 *
 * appvold is not started from here: it is a systemd user unit (see the README).
 * The current focus is pushed when the extension starts, on every window change
 * and when appvold appears on the bus, so a daemon that starts late or restarts
 * has the focus of this moment instead of an empty one.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const DAEMON_NAME = 'org.appvol.Daemon';
const DAEMON_PATH = '/org/appvol/Daemon';
const DAEMON_IFACE = 'org.appvol.Daemon';

const OSD_NAME = 'org.appvol.GnomeShell';
const OSD_PATH = '/org/appvol/GnomeShell';
const OSD_XML = `<node>
  <interface name="org.appvol.GnomeShell">
    <method name="Show">
      <arg type="s" direction="in" name="icon"/>
      <arg type="s" direction="in" name="label"/>
      <arg type="d" direction="in" name="level"/>
      <arg type="d" direction="in" name="max_level"/>
    </method>
  </interface>
</node>`;

/* The windows worth reporting: an application window, not the shell's own
 * panels, menus, desktops or splash screens.  The daemon ignores a window
 * without a pid on its own, so a type it does not know is left to that check. */
const REPORTED_TYPES = new Set([
    Meta.WindowType.NORMAL,
    Meta.WindowType.DIALOG,
    Meta.WindowType.MODAL_DIALOG,
    Meta.WindowType.UTILITY,
]);

export default class AppvolExtension extends Extension {
    enable() {
        this._focusId = 0;
        this._exports = null;
        this._nameId = 0;
        this._daemonWatchId = 0;

        this._exportOsd();
        this._focusId = global.display.connect('notify::focus-window', () => this._pushFocus());
        // A daemon that starts after the shell must not wait for a window switch
        // to learn what is focused.
        this._daemonWatchId = Gio.DBus.session.signal_subscribe(
            'org.freedesktop.DBus',
            'org.freedesktop.DBus',
            'NameOwnerChanged',
            '/org/freedesktop/DBus',
            DAEMON_NAME,
            Gio.DBusSignalFlags.NONE,
            () => this._pushFocus());
        this._pushFocus();
    }

    disable() {
        if (this._focusId) {
            global.display.disconnect(this._focusId);
            this._focusId = 0;
        }
        if (this._daemonWatchId) {
            Gio.DBus.session.signal_unsubscribe(this._daemonWatchId);
            this._daemonWatchId = 0;
        }
        if (this._exports) {
            this._exports.unexport();
            this._exports = null;
        }
        if (this._nameId) {
            Gio.bus_unown_name(this._nameId);
            this._nameId = 0;
        }
    }

    /* The OSD, called by the daemon. */

    _exportOsd() {
        const interfaceInfo = Gio.DBusNodeInfo.new_for_xml(OSD_XML).interfaces[0];
        this._exports = Gio.DBusExportedObject.wrapJSObject(interfaceInfo, this);
        this._exports.export(Gio.DBus.session, OSD_PATH);
        this._nameId = Gio.bus_own_name_on_connection(
            Gio.DBus.session,
            OSD_NAME,
            Gio.BusNameOwnerFlags.NONE,
            null,
            null);
    }

    Show(icon, label, level, maxLevel) {
        const gicon = this._icon(icon);
        if (!gicon)
            return;
        const hasBar = level >= 0;
        Main.osdWindowManager.showAll(
            gicon,
            label || null,
            hasBar ? level : null,
            hasBar ? maxLevel : undefined);
    }

    _icon(name) {
        for (const candidate of [name, 'audio-volume-high']) {
            if (!candidate)
                continue;
            try {
                return Gio.ThemedIcon.new(candidate);
            } catch (e) {
                log(`appvol: cannot use the icon ${candidate}: ${e.message}`);
            }
        }
        return null;
    }

    /* The focus, pushed to the daemon. */

    _pushFocus() {
        const window = global.display.focus_window;
        let pid = 0;
        let wmClass = '';
        let desktop = '';
        let caption = '';

        if (window && REPORTED_TYPES.has(window.get_window_type())) {
            pid = window.get_pid();
            wmClass = window.get_wm_class() ?? '';
            caption = window.get_title() ?? '';
            const app = Shell.WindowTracker.get_default().get_window_app(window);
            // A window that matches no desktop entry gets a Shell.App with an id
            // like "window:2"; only a real entry is worth sending.
            const appId = app ? app.get_id() : '';
            if (appId.endsWith('.desktop'))
                desktop = appId.slice(0, -'.desktop'.length);
        }

        Gio.DBus.session.call(
            DAEMON_NAME,
            DAEMON_PATH,
            DAEMON_IFACE,
            'SetFocus',
            new GLib.Variant('(isss)', [pid, wmClass, desktop, caption]),
            null,
            Gio.DBusCallFlags.NONE,
            -1,
            null,
            (connection, result) => {
                try {
                    connection.call_finish(result);
                } catch (e) {
                    // appvold is not running yet or was just restarted; the next
                    // window change sends the focus again.
                    console.debug(`appvol: cannot report the focus: ${e.message}`);
                }
            });
    }
}
