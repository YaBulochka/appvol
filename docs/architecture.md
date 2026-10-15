# Architecture

Three parts, one goal: change the volume of the streams of one target, which is
the focused window by default and a named profile otherwise.

```
KWin script --SetFocus(pid, resourceClass, desktopFileName, caption)--> appvold
                                                                            ^
appvol up --AdjustTarget(profile, "up", 0)----------------------------------+
                                                                            |
kglobalacceld --globalShortcutPressed(profile_spotify)----------------------+
                                                                            |
appvol-gui --Overview / SetVolume / SwitchProfile---------------------------+
                                                                            v
                                                     pulsectl -> sink inputs -> OSD
```

## Components

**`appvold`** ([`appvol/daemon.py`](../appvol/daemon.py)) is the only component
that talks to PipeWire and KWin. It holds a `pulsectl` connection to
pipewire-pulse, registers `org.appvol.Daemon` on the session bus, caches the last
focus the KWin script reported, loads `kwin/appvol.js` through
`org.kde.kwin.Scripting`, owns the profiles and shows the OSD. A second instance
refuses to start: the bus name is taken with `do_not_queue`, so the error is
immediate instead of a silent wait.

**The KWin script** ([`kwin/appvol.js`](../kwin/appvol.js)) pushes the focused
window on load exactly as on every `workspace.windowActivated`. It sends `pid`,
`resourceClass`, `desktopFileName` and `caption`, and an empty focus when the
active window is missing, has no pid, or is of type desktop or dock. It must stay
dependency free: the daemon injects the file into KWin, which only gives it
`callDBus`.

**`appvol`** ([`appvol/cli.py`](../appvol/cli.py)) is thin by design. One D-Bus
call, no focus lookup, no KWin, no PipeWire. A key press costs a single round trip
on the session bus, about 35 ms end to end including the interpreter start.

## D-Bus API

Bus name `org.appvol.Daemon`, object `/org/appvol/Daemon`, interface
`org.appvol.Daemon`:

| Method | Signature | Used by | Answer |
| --- | --- | --- | --- |
| `SetFocus(pid, resourceClass, desktopFileName, caption)` | `isss -> i` | KWin script | `0`, the script ignores the answer |
| `Adjust(direction, step)` | `sd -> s` | client | JSON result for the current profile |
| `AdjustTarget(profile, direction, step)` | `ssd -> s` | client, tray | JSON result for one profile, without switching |
| `SetVolume(profile, percent)` | `sd -> s` | window, plugin | JSON result, absolute, without the OSD |
| `ToggleMute()` | ` -> s` | client | JSON result for the current profile |
| `ToggleMuteTarget(profile)` | `s -> s` | client, tray | JSON result for one profile |
| `SetMute(profile, muted)` | `sb -> s` | window | JSON result, absolute, without the OSD |
| `SetStep(profile, step)` | `sd -> s` | window | JSON: the profiles after the change, with the global step for Active |
| `ToggleProfile(profile)` | `s -> s` | client, keys | switch the profile, answer describes the OSD |
| `SwitchProfile(profile, osd)` | `sb -> s` | window, tray | make a profile current, the toggle without the "back" |
| `Profiles()` | ` -> s` | client | JSON: the profiles and the current one |
| `Overview()` | ` -> s` | window, tray | JSON: every profile plus its live volume, mute and match count |
| `Applications()` | ` -> s` | window editor | JSON: the applications playing now |
| `AddProfile(id, name, include, exclude, step, max_volume, icon, osd_name)` | `ssasasddss -> s` | client, window | JSON: the profiles after the change |
| `RemoveProfile(id)` | `s -> s` | client, window | JSON: the profiles after the change |
| `Reload()` | ` -> s` | client | read `profiles.toml` again |
| `List()` | ` -> s` | client | JSON: config, profile, focus, match, streams, OSD appearance |

An empty profile argument means the current profile, except in `ToggleProfile`
where it means the built-in one. Errors: `org.appvol.Error.InvalidArgument` for a
bad direction, a negative step, an unknown profile or an unknown action; the
client prints the message and exits with status 2. When the daemon is not running,
the client prints `appvold is not running (start it with: systemctl --user start
appvold)` and exits with status 1.

A step of zero means "the step of the profile, else the one from the config", so
a client never has to know which profile is current. `SetStep` records the choice:
on a stream profile it writes that profile's own `step` into `profiles.toml`, and
on the built-in Active profile it writes the global `step`, which is the only key
the daemon puts into `config.toml`. The file comes back in canonical form, so a
comment of a hand edit there does not survive that one change.

`SetVolume` and `SetMute` are the absolute counterparts of `Adjust` and
`ToggleMute`, and they stay quiet on the OSD: a slider sends one call per release
and the window shows the result itself, so an OSD per call would only flicker. The
three keys and the tray keep the OSD through `Adjust` and `ToggleMute`.

`ToggleProfile` is what a key does: a second press returns to Active. The window
and the tray need the explicit form, so `SwitchProfile` sets the profile and never
toggles back. Its `osd` flag says who is watching: the window passes `false`
(it shows the change), the tray passes `true`, so a switch from the tray menu
answers like a key press. `Overview` reads PipeWire once and matches every profile
against that snapshot; an unreachable pipewire-pulse is not fatal there, the
profiles come back with null for the live numbers.

## Matching

[`appvol/match.py`](../appvol/match.py) is a pure function over the focus and the
list of sink inputs; the first step that produces a result stops the search:

1. `application.process.id` of the stream equals the pid of the window:
   the common case.
2. the pid of the stream is a descendant of the window pid, following the `ppid`
   chain through `/proc/<pid>/stat`: Firefox, Chromium, Electron.
3. the application name: `desktopFileName` and `resourceClass` against
   `pipewire.access.portal.app_id`, `application.id`,
   `application.process.binary` and `application.name`. Comparison is
   case-insensitive, the `.desktop` suffix is dropped, and a reverse-DNS name
   also matches by its last segment, so `org.mozilla.firefox` finds a stream
   that calls itself `firefox`.

Stream properties are compared **merged with the properties of the owning
PulseAudio client**. That is not cosmetic: Spotify carries
`application.process.id` and `application.process.binary` on the client only,
so a stream-only comparison finds nothing.

Focus is ignored when [`appvol/focus.py`](../appvol/focus.py) recognises a panel
or desktop window (`plasmashell`, `org.kde.plasmashell`, `org.kde.kdesktop`,
`org.kde.kwin.desktop`) or when there is no pid. With nothing matched, no volume
changes and the command still exits with status 0.

## Profiles

[`appvol/profiles.py`](../appvol/profiles.py) holds the model, the file format
and a pure matcher, so all of it is unit tested without a session.

A profile is a named target with one of two modes. `focus` is the built-in
**Active window** profile (`id = "active"`), which is what the keys did before
profiles existed; it cannot be edited or removed. `streams` selects sink inputs
by application: `include` lists identifiers compared the same way as in the name
step above, and an empty list means every application stream. `exclude` removes
applications from the result, which is how an inversion profile ("everything but
the game") is spelled. An empty `include` is the common case, so the matcher drops
the streams of the shell there: `plasmashell`, `kwin`, `kded` and the event and
notification sounds, matched by the same name variants as a window. An explicit
`include` still reaches them, so nothing is unreachable.

`step`, `max_volume`, `icon` and `osd_name` are per profile; an unset value falls
back to `config.toml`. `osd_name` is `auto` (the name for stream profiles, only
the icon for the Active one), `always` or `never`.

Switching is a toggle: a profile key switches to that profile, the same key
switches back to Active, another profile key switches over. The three volume keys
are global and always follow the current profile. Every key press on the current
profile counts as using it, and after `profile_idle_timeout` seconds without one
the daemon returns to Active and logs the return.

The profiles live in `~/.config/appvol/profiles.toml`, which the daemon reads at
start and writes on every change, replacing the file in one step. The CLI and the
window both go through the D-Bus API, so there is a single writer; `Reload()`
exists for hand edits.

```toml
[[profile]]
id = "spotify"
name = "Spotify"
mode = "streams"
include = ["spotify"]
step = 2
```

One action per profile is registered in KGlobalAccel at run time, in the component
`appvol` (friendly name "appvol profiles"), which keeps the keys the user assigns
in System Settings in `kglobalshortcutsrc` across daemon restarts. Every
registration then marks the action *present*, because the shortcut server only
grabs the keys of a present action; [plasma-notes.md](plasma-notes.md) records the
mechanism. The three volume actions stay where they were, in a service component
built from `desktop/org.appvol.desktop.in`.

## GUI

[`appvol/gui/`](../appvol/gui) is optional: it needs PySide6 and the Kirigami QML
modules, which the daemon and the CLI do not, so the pacman package splits into
`appvol` and `appvol-gui`. No module of the daemon imports it.

The window is QML and everything around it is Python:

* `app.py` builds the `QApplication`, loads `qml/Main.qml` and owns the tray icon,
  whose menu is rebuilt from the profile list on every refresh.
* `bridge.py` is the only object QML sees. It keeps the model (the profiles with
  their live numbers, the applications playing now) in properties and wraps every
  daemon call in a slot, so no QML file speaks D-Bus.
* `client.py` builds and decodes those calls. It is free of Qt and unit tested
  against a fake proxy.
* `shortcuts.py` reads the keys bound to the profile actions from KGlobalAccel and
  renders them with `QKeySequence`, so a profile row can show `Ctrl+Alt+1`.
* [`appvol/apps.py`](../appvol/apps.py) groups the live streams into applications
  for that list, with the same identifiers the matcher compares, so what the editor
  offers is what a profile can select. `appvol apps` prints the same grouping.
* The QML files are `Main.qml` (the list), `ProfileRow.qml` (one profile with its
  slider and mute switch), `ProfileEditor.qml` (an overlay sheet) and
  `ApplicationPicker.qml` (what is playing right now).

The window reads through `Overview`, which returns every profile with its live
percent, mute state and match count, and writes through `SetVolume`, `SetMute`,
`SwitchProfile`, `AddProfile` and `RemoveProfile`. A slider sends one call when the
finger lifts, not per movement, and the editor writes a profile in one piece, so
`profiles.toml` never sees a half-finished edit.

The first GUI does not assign keys: it shows the binding and opens
`systemsettings kcm_keys`, and the user binds the profile actions there. No part
of appvol writes to `kglobalshortcutsrc` itself. [gui.md](gui.md) describes what
the window and the tray offer.

## Volume

[`appvol/volume.py`](../appvol/volume.py) is pure arithmetic: the step applies to
every matched stream, channel balance is preserved, and the result is clamped to
`0..max_volume`, which is the profile's value or the global one. `mute` is
aggregate: when any matched stream is audible all of them are muted, and when the
whole set is muted it is unmuted again. The percent shown in the OSD is the
maximum across the matched streams.

## Lifecycle

* **KWin restarts.** The daemon watches `NameOwnerChanged` for `org.kde.KWin`
  and reloads the script, retrying up to 20 times with 500 ms in between.
  The script cannot be loaded twice under the same name, so the daemon unloads it
  first.
* **pipewire-pulse restarts.** A keepalive call runs every 15 seconds. The first
  call after a restart fails with `CallError` or `PulseDisconnected`; the daemon
  closes the connection, opens a new one and repeats the operation, so a hotkey
  still works without manual intervention. Streams may take a moment to come
  back, `stream-restore` restores them within a couple of seconds.
* **Focus is pushed, not polled.** No timer reads KWin: the daemon only knows
  what the script last sent.
* **A profile goes idle.** A timer wakes up every 10 seconds and returns the keys
  to Active after `profile_idle_timeout` seconds without a press on the current
  profile, so the return happens between that timeout and ten seconds later. The
  default is 300; zero disables it.

## Configuration

[`appvol/config.py`](../appvol/config.py) reads `~/.config/appvol/config.toml`
(`XDG_CONFIG_HOME` is honoured). A missing file means defaults; a malformed value
means the default for that key alone, with a warning in the log. `step` and
`max_volume` are percentages, `max_volume` is capped at 150, `osd` toggles the
OSD, `profile_idle_timeout` is the number of seconds before a profile returns to
Active, and `kwin_script` overrides the script location. The command line wins over
the file (`appvol up --step 2`, `appvold --config FILE`, `appvold --profiles FILE`,
`appvold --kwin-script FILE`). The daemon writes the file only for the global `step`,
when the window changes it; every other key stays the user's.
