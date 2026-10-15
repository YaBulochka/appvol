# Window and Tray Icon

`appvol-gui` is the optional front end of appvol: a small window for the profiles
and a tray icon for the quick switches. It is a client of the daemon, like the
CLI, so it never touches PipeWire, KWin or `profiles.toml` itself.

```
bin/appvol-gui                          # from a checkout, needs PySide6
appvol-gui                              # after install.sh or the package
python3 -m appvol.gui                   # the module directly
```

## Requirements

| Package (Arch) | Why |
| --- | --- |
| `pyside6` | Qt 6 for Python: the window, the tray, the QML engine |
| `kirigami` | the KDE QML components the window is built from |
| `qqc2-desktop-style` | draws the controls in the Breeze style |
| `breeze-icons` | the icons used by the rows and the tray menu |

The daemon and the CLI need none of them, which is why Arch gets two packages:
`appvol` and `appvol-gui`. `install.sh` installs the GUI part only when PySide6 is
importable, and says so when it is not; `--no-gui` skips it in any case.

## The window

The window lists the profiles, the built-in **Active window** first, then the ones
from `profiles.toml`, each with the profile that is current marked in the radio
button on the left:

* **Name, icon and scope.** The scope line spells out what the profile covers:
  "Only spotify", "Everything except spotify", "Every application, except the
  shell". The line on the right counts the streams that match right now, or says
  "nothing playing".
* **Slider.** It shows the volume of the profile, which is the loudest of its
  matched streams, the same number the OSD shows. Dragging it moves the live
  streams, and the call is sent once, when the finger lifts. A profile with
  nothing playing has a disabled slider, because there is nothing to change.
* **Mute switch, Edit and Remove.** Mute is aggregate, like the hotkey: it mutes
  everything the profile covers, and unmutes all of it when all of it is muted.
  Edit opens the editor below, Remove asks first. Both are disabled for the
  built-in profile.
* **Keys.** The line under the slider shows the key bound to that profile, or
  "No key bound". **Bind Keys…** opens System Settings → Shortcuts, where every
  action of appvol is listed under **Appvol**. The window shows the binding but
  never sets one.
* **Step.** The value the volume keys move by sits in the same row, so it can be
  changed without opening the editor. The row always shows the number the keys
  really use, 5 % by default; the first change writes that step into the profile,
  and the Active row writes it to `config.toml`. The editor keeps the extra option
  of 0, "follow the global step".
* **Footer.** When the keys return to Active after `profile_idle_timeout`, and the
  version of the running installation.

The window reads the whole panel with one `Overview()` call and refreshes it when
it gains focus, when a button asks for it, and after every write. When `appvold`
is not running, a banner says so and offers **Try Again**, and the profile list
stays empty instead of pretending.

## The editor

**New Profile** and **Edit** open a sheet with the fields of
[`profiles.toml`](../docs/architecture.md#profiles):

* **Identifier** is the key of the profile in the file. It can only be set while
  creating one; renaming means creating a new profile.
* **Name** is what the OSD and the window show.
* **Include** and **Exclude** hold application identifiers. **Add…** opens the list
  of what is playing right now — grouped by application, with the icon and the
  live percent — and writes the identifier that the daemon reports, so the profile
  matches by construction. A name that is not playing can be typed instead, which
  is how a game or a browser is added before it starts. An empty **Include** means
  every application stream with the shell left out; a name in **Exclude** turns the
  profile into "everything except this".
* **Step** and **Maximum volume** are per profile; a step of 0 follows
  `config.toml`, which is the value the Active row of the list edits.
* **Icon** overrides the icon of the OSD and of the row. Whether the OSD
  captions the application name is decided by one checkbox in the window,
  “Show app name in OSD”, shared by every profile — it is off by default, so
  the OSD shows the icon alone.

The editor writes the profile in one call when **Save** is pressed, so the file
never holds half an edit, and the daemon writes it atomically.

## The tray icon

The tray icon stays when the window is closed and closes the application only with
**Quit**. Its menu:

* **Open appvol** — the same as a left click on the icon.
* one entry per profile, the current one ticked. Clicking switches, with the OSD,
  so the tray answers like a key press.
* **Bind keys…**
* **Volume up**, **Volume down**, **Toggle mute** — they act on the current
  profile, exactly like the three keys, OSD included.
* **Quit**.

## What is not here

* Assigning keys. Keyboard shortcuts belong to System Settings, and appvol writes
  nothing to `kglobalshortcutsrc`.
* Per-stream mixing. The window works on profiles; to pick one stream out of three
  of the same application, use the profile of the application.
* The KDE OSD style. appvol shows the stock OSD; the window is its own thing.
