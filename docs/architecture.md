# Architecture

Three parts, one goal: change the volume of the streams of the focused window.

```
KWin script --SetFocus(pid, resourceClass, desktopFileName, caption)--> appvold
                                                                            |
appvol up --Adjust("up", 5)-----------------------------------------------> |
                                                                            v
                                                     pulsectl -> sink inputs -> OSD
```

## Components

**`appvold`** ([`appvol/daemon.py`](../appvol/daemon.py)) is the only component
that talks to PipeWire and KWin. It holds a `pulsectl` connection to
pipewire-pulse, registers `org.appvol.Daemon` on the session bus, caches the last
focus the KWin script reported, loads `kwin/appvol.js` through
`org.kde.kwin.Scripting`, and shows the OSD. A second instance refuses to start:
the bus name is taken with `do_not_queue`, so the error is immediate instead of a
silent wait.

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
| `Adjust(direction, step)` | `sd -> s` | client | JSON result, `direction` is `up` or `down` |
| `ToggleMute()` | ` -> s` | client | JSON result |
| `List()` | ` -> s` | client | JSON: config, focus, match, streams, OSD appearance |

Errors: `org.appvol.Error.InvalidArgument` for a bad direction or a non-positive
step. When the daemon is not running, the client prints `appvold is not running
(start it with: systemctl --user start appvold)` and exits with status 1.

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

## Volume

[`appvol/volume.py`](../appvol/volume.py) is pure arithmetic: the step applies to
every matched stream, channel balance is preserved, and the result is clamped to
`0..max_volume`. `mute` toggles the mute flag of all matched streams. The percent
shown in the OSD is the maximum across the streams that changed.

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

## Configuration

[`appvol/config.py`](../appvol/config.py) reads `~/.config/appvol/config.toml`
(`XDG_CONFIG_HOME` is honoured). A missing file means defaults; a malformed value
means the default for that key alone, with a warning in the log. `step` and
`max_volume` are percentages, `max_volume` is capped at 150, `osd` toggles the
OSD, and `kwin_script` overrides the script location. The command line wins over
the file (`appvol up --step 2`, `appvold --config FILE`, `appvold --kwin-script
FILE`).
