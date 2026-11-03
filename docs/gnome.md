# GNOME

> **Experimental.** This is support written against one GNOME Shell 51.1
> session. It is not covered by the project's tests and is maintained on a
> best-effort basis; KDE Plasma is the supported desktop. The parts it depends on
> (an extension, `org.freedesktop.portal.GlobalShortcuts`,
> `org.gnome.Settings.GlobalShortcutsProvider`) can change between GNOME
> releases.

appvol runs on GNOME 45 and newer through one extension in
[`contrib/gnome/`](../contrib/gnome). The daemon, the CLI and the window do not
change: the extension only supplies the two things a GNOME session refuses to
give a plain client, the focused window and the native OSD.

```
appvol@… (inside gnome-shell) --SetFocus(pid, wmClass, appId, title)--> appvold
                                                                          ^
appvold --Show(icon, label, level, max_level)--> org.appvol.GnomeShell ----+
                                                                          |
appvol up / a bound key -> appvold -> pipewire-pulse ---------------------+
```

## Focus

GNOME reports the focus to extensions only. The extension listens to
`notify::focus-window` on the shell's display, keeps the windows a user can act
on (normal, dialog, modal dialog, utility), and pushes four fields the daemon
already accepts from the KWin script:

| field | source |
| --- | --- |
| `pid` | `Meta.Window.get_pid()` |
| `resourceClass` | `Meta.Window.get_wm_class()`, the Wayland `app_id` |
| `desktopFileName` | `Shell.WindowTracker.get_window_app(window).get_id()` without `.desktop` |
| `caption` | `Meta.Window.get_title()` |

A window the extension does not report, or no window at all, sends an empty
focus, which is what the KWin script does for a panel or the desktop. The
daemon matches the window against the streams with the same code as on Plasma:
pid, then process tree, then the application name.

A `Shell.App` that matches no desktop entry has an id like `window:2`, so only an
id that ends in `.desktop` is sent; the window class still names the
application.

`appvold` is not started by the extension. Enable the user unit once:

```
systemctl --user enable --now appvold
```

The focus is sent when the extension starts, on every window change, and when
`appvold` appears on the bus: the extension watches `NameOwnerChanged` for
`org.appvol.Daemon`. A daemon that starts late or restarts therefore has the
focus of this moment instead of an empty one.

## OSD

The shell's `org.gnome.Shell.ShowOSD` is callable only by
`org.gnome.Settings`, `org.gnome.SettingsDaemon.MediaKeys` and the portal
backend; every other client gets `AccessDenied`. The extension runs inside the
shell, so it exports its own object and draws the OSD through
`Main.osdWindowManager`, the component behind the volume OSD everyone knows:

```
org.appvol.GnomeShell /org/appvol/GnomeShell
  Show(icon: s, label: s, level: d, max_level: d)
```

`level` is a fraction of 100% that the bar is drawn against, with `max_level` as
its end (`0.42` and `1.5` for 42% of a profile that allows 150%); a negative
level hides the bar and the shell shows the icon and the label alone. A muted
stream sends `label = "Muted"` and no bar, which is what the shell's own mute OSD
looks like. The fractions are not cosmetic: the shell's `BarLevel` declares its
value as 0 to 2, and a percentage is out of range, which drops every eased update
and leaves the OSD on its first value.

The daemon picks it with `osd_backend = "auto"` (the default): Plasma's OSD
first, then this one, then the freedesktop notification daemon. The order costs
one failed call on a session that does not have the earlier backend, which is
why nothing is cached: a shell that restarts repaints within one key press.
`osd_backend = "gnome"` pins it.

## Install

From a checkout:

```
./contrib/gnome/install.sh          # copy into ~/.local/share/gnome-shell/extensions
./contrib/gnome/install.sh --link   # symlink the checkout, for working on it
./contrib/gnome/install.sh --remove
```

A start of the shell scans the extensions folder once. The installer enables the
extension itself when the shell already knows it; otherwise it writes the uuid
into `enabled-extensions`, so the next login turns it on. On Wayland the shell
cannot be reloaded, so log out and back in after the first install.

Check that it runs:

```
gnome-extensions info appvol@yabulochka.github.io   # State: ENABLED
```

The extension logs its errors to the journal of the session, under
`gnome-shell`.

## Shortcuts

GNOME has no KGlobalAccel. The portable way to a global key there is
`org.freedesktop.portal.GlobalShortcuts`, which GNOME 51 implements in version 2
and whose backend is part of `xdg-desktop-portal-gnome`. appvol uses it, and the
daemon keeps routing every press through the same `on_shortcut` the Plasma keys
use, so a key, a profile key and a CLI command are one code path.

**The portal, in practice.** At start the daemon opens a portal session,
subscribes to `Activated` and asks `ListShortcuts` what is already bound. It
never opens the binding dialog on its own. A session starts unbound and the
backend grabs nothing until `BindShortcuts` is called, so the daemon also claims
the ids the provider already stores for `org.appvol.Daemon`
(`org.gnome.settings-daemon.global-shortcuts.application`): offering ids the
provider knows opens no dialog, and the session grabs their keys. That is what
keeps every bound key alive across a restart of `appvold`.

One command opens the dialog:

```
appvol shortcuts        # what is bound and what is not
appvol shortcuts bind   # the desktop's binding dialog
```

The portal accepts a single `BindShortcuts` per session and answers `response 2`
to a second one. `appvol shortcuts bind` therefore switches to
`ConfigureShortcuts` once the session is bound: the dialog shows the stored
entries, including a row the user left empty, and saving rebinds the session. A
profile added after the first dialog is not in the store yet, so the daemon opens
a fresh session for that case and `BindShortcuts` offers the new action
prefilled with the known ones.

The bindings survive a restart of `appvold` and of the session. `appvol
shortcuts` reports the same from the terminal.

The daemon creates the session again when the portal restarts
(`NameOwnerChanged` on `org.freedesktop.portal.Desktop`), and retries a session
that the portal refused a few times, because the first request can land while the
portal is still activating. `session_handle_token` is mandatory in
`CreateSession`: without it xdg-desktop-portal trips its own assertion and the
service crashes, which is why it is passed explicitly.

**Where the bindings live.** The dialog belongs to gnome-control-center, which
exports `org.gnome.Settings.GlobalShortcutsProvider` on the bus
(xdg-desktop-portal-gnome forwards to it), and it stores the result in GSettings.
The schema `org.gnome.settings-daemon.global-shortcuts` keeps the list of
applications, and the relocatable
`org.gnome.settings-daemon.global-shortcuts.application` keeps one entry per
application id:

```
gsettings get org.gnome.settings-daemon.global-shortcuts applications
gsettings get org.gnome.settings-daemon.global-shortcuts.application:/org/gnome/settings-daemon/global-shortcuts/org.appvol.Daemon/ shortcuts
dconf dump /org/gnome/settings-daemon/global-shortcuts/
```

The daemon registers that id, `org.appvol.Daemon`, with
`org.freedesktop.host.portal.Registry` before its first portal call, and again
whenever the portal restarts. Without the registration the portal derives the id
from the systemd unit of the process: empty for a plain service, or the
terminal's scope when the daemon is started from a terminal, which is how
bindings once ended up under `org.kde.konsole`. The id has to name a `.desktop`
file, so [`desktop/org.appvol.Daemon.desktop.in`](../desktop/org.appvol.Daemon.desktop.in)
is installed with the daemon.

**Numpad keys.** The dialog accepts what `gtk_accelerator_valid` accepts, and GTK
works on key values, not on key codes. With NumLock off, keypad 8 arrives as
`KP_Up`, the navigation key, and is refused; with NumLock on it is `KP_8` and
binds, but then it only fires while NumLock stays on. KDE keeps a separate Num
modifier and GTK does not, so a numpad digit is never as portable as a modified
combination. `KP_Add`, `KP_Subtract`, `KP_Divide` and `KP_Page_Up` do not depend
on NumLock and bind in either state.

**Where there is no portal.** Plasma answers through KGlobalAccel instead, and a
tiling setup has neither. There the actions are GNOME custom shortcuts, or the
equivalent of the desktop, pointing at the CLI:

| name | command |
| --- | --- |
| Appvol volume up | `appvol up` |
| Appvol volume down | `appvol down` |
| Appvol mute | `appvol mute` |
| Appvol next target | `appvol profile next` |
| Appvol Spotify | `appvol profile toggle spotify` |

Settings → Keyboard → Custom Shortcuts takes them, one entry each. The commands
`appvol profile prev` and `appvol profile toggle <id>` work the same way, so a
profile can have a key of its own. A press costs a process start, about 60 ms,
and the daemon answers in one round trip.

**Not planned: keybindings inside the extension.** `Main.wm.addKeybinding` needs
a GSettings schema, and a key per profile needs a relocatable schema plus a
preferences window, while the keys would still not appear in the desktop's own
shortcut list. The portal gives the same speed without that.
