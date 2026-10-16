# appvol

Per-application volume control by hotkey for **KDE Plasma 6.8 (Wayland, PipeWire)**.

Press a key, and appvol changes the volume of every audio stream that belongs to
the application whose window is focused, showing the stock KDE OSD. Profiles
extend that to named targets: one key for the application of your choice, one
for everything except it.

<p align="center">
  <img src="docs/images/demo.gif" alt="appvol changing the volume of the focused window, with the KDE OSD" width="720">
</p>

```
appvol up      # +5% for the focused application
appvol down    # -5%
appvol mute    # toggle mute
appvol list    # streams, cached focus, profiles, and which match step fired
appvol apps    # what is playing right now, with the identifiers profiles use
```

A user daemon on the session bus, a KWin script that reports the focused window,
and a thin client for the hotkeys. No root, no X11 tools. An optional window and
tray icon for the profiles come with the `appvol-gui` package.

## Quick start

Download the packages for your system from the
[latest release](https://github.com/YaBulochka/appvol/releases/latest), install
them ([Install](#install) has the exact command for each distribution), then start
the daemon:

```
systemctl --user daemon-reload
systemctl --user enable --now appvold
```

Open **System Settings → Shortcuts**, search for "appvol" and bind **Volume up**,
**Volume down** and **Toggle mute**. That is all: the daemon registers the actions
itself.

## Requirements

Tested on **KDE Plasma 6.8, Wayland session**. Plasma 5 is not supported.

The session provides: `kwin` (focus), `plasmashell` (OSD), `kglobalacceld` and
System Settings (hotkeys), PipeWire with `pipewire-pulse`.

Python modules for the daemon and the CLI. The distribution packages pull them in;
`install.sh` checks them and prints the command for your distribution:

| Import name | Arch package      | Why                                     |
| ----------- | ----------------- | --------------------------------------- |
| `tomllib`   | `python` (3.11+)  | reads the config                        |
| `dbus`      | `python-dbus`     | session bus: the daemon API and the OSD |
| `gi`        | `python-gobject`  | the GLib main loop the daemon runs in   |
| `pulsectl`  | `python-pulsectl` | stream volume through pipewire-pulse    |

Debian and Fedora call these `python3-dbus`, `python3-gi` (or `python3-gobject`)
and `python3-pulsectl`.

The window and the tray icon are optional and additionally need PySide6 and
Kirigami. On Arch that is `pyside6`, `kirigami`, `qqc2-desktop-style` and
`breeze-icons`; the `.deb` and `.rpm` packages pull the names of their
distribution. The daemon and the CLI never import them, so a minimal install can
leave them out.

## Install

Every release carries the same three things: the pacman packages, the `.deb` and
`.rpm` packages, and the source archive. Download the files for your system from
the [latest release](https://github.com/YaBulochka/appvol/releases/latest) into a
directory, `cd` there, and run the commands below. To fetch them all at once:

```
mkdir appvol-pkg && cd appvol-pkg
gh release download --repo YaBulochka/appvol
```

There are two packages. **`appvol`** is the daemon and the CLI; **`appvol-gui`** is
the window and the tray icon, and depends on `appvol`. Install both, or only
`appvol` for a headless install. Each block below starts the daemon with the
session afterwards.

### Arch Linux

```
sudo pacman -U appvol-*.pkg.tar.zst        # appvol and appvol-gui
systemctl --user daemon-reload
systemctl --user enable --now appvold
```

### Debian / Ubuntu / KDE neon

```
sudo apt install ./appvol_*.deb ./appvol-gui_*.deb
systemctl --user daemon-reload
systemctl --user enable --now appvold
```

### Fedora

```
sudo dnf install ./appvol-*.rpm            # appvol and appvol-gui
systemctl --user daemon-reload
systemctl --user enable --now appvold
```

Plasma 6 is required, which rules out Debian 12 and Ubuntu 24.04.

### Verify the download (optional)

`SHA256SUMS` lists every file of the release:

```
sha256sum -c SHA256SUMS --ignore-missing
```

### Any distribution, no root

The `appvol-X.Y.Z.tar.gz` archive carries the whole project and `install.sh`,
which copies it into `~/.local` and needs no package manager:

```
tar xzf appvol-X.Y.Z.tar.gz
cd appvol-X.Y.Z
./install.sh --service        # into ~/.local; --uninstall reverses it
./install.sh --no-gui         # ... without the window and the tray icon
```

### From the checkout

Without installing anything:

```
bin/appvold                # the daemon, logs to stderr
bin/appvol up              # in another terminal
```

### Uninstall

Stop the daemon first, then remove the packages (or run `./install.sh --uninstall`
for the no-root install):

```
systemctl --user disable --now appvold
sudo pacman -Rns appvol appvol-gui      # Arch
sudo apt remove appvol appvol-gui       # Debian, Ubuntu
sudo dnf remove appvol appvol-gui       # Fedora
```

## Hotkeys

appvol appears in **System Settings → Shortcuts** while the daemon runs, under
the entry **Appvol**, next to the other applications. Nothing has to be installed
or regenerated for it.

Bind **Volume up**, **Volume down**, **Toggle mute**, **Next profile** and
**Previous profile**. No keys are bound by default, and keyboard shortcuts stay in
System Settings; appvol never writes one.

## Profiles

A profile is a named target for the same volume keys. The **Active window**
profile is built in and needs no configuration; the profiles you create select
applications:

```
appvol profile add spotify --include spotify --name Spotify
appvol profile add desktop --exclude spotify --name "Everything but Spotify"
appvol profile toggle spotify   # or press its key; press again to go back
appvol profile list             # what exists, and which profile is current
appvol up --profile spotify     # one call, without switching to it
```

`--include` takes application identifiers; the reverse-DNS name also matches by
its last part, so `firefox` finds `org.mozilla.firefox`. An empty `--include`
means every application stream with the shell left out, and `--exclude` removes
applications, which is how an inversion profile is built. `--step`,
`--max-volume` and `--icon` override the config for that profile.
Profiles live in `~/.config/appvol/profiles.toml`, written by the daemon.

The daemon registers one action per profile in KGlobalAccel, so every profile
shows up in System Settings → Shortcuts under **Appvol**, next to the five fixed
actions. While a profile is current, the volume keys follow it. The OSD shows the
icon and the bar, and can also caption the application name: switch on **Show app
name in OSD** in the window.

**Next profile** and **Previous profile** walk through the built-in Active profile
and your profiles in the order the window lists them, wrapping around. Five
minutes without a key press return the keys to the Active profile.

## Window and tray icon

<p align="center">
  <img src="docs/images/gui.png" alt="The appvol window listing profiles with live volume, scope, bound key and step" width="640">
</p>

`appvol-gui` (or `bin/appvol-gui` from the checkout) opens a small window listing
every profile with its live volume, its scope, the key bound to it and the step of
the volume keys, plus a tray icon with the profiles, the three volume actions and
**Quit**.

- The sliders and the mute switches act on the live streams.
- The step can be changed in the row itself.
- **New Profile** and **Edit** open a form whose application list is what is
  playing right now.
- **Bind Keys…** opens System Settings → Shortcuts. The window shows the binding
  and never sets one.

The window and the tray take their icons from the `hicolor` icon theme
(`appvol` and `appvol-symbolic`), which `install.sh` and the packages install.

Details in [docs/gui.md](docs/gui.md).

## Config

`~/.config/appvol/config.toml`, every key optional:

```toml
step = 5                     # relative step in percent
max_volume = 100             # upper limit, up to 150
osd = true                   # show the KDE OSD
osd_show_name = false        # caption the application name in the OSD
profile_idle_timeout = 300   # seconds before a profile returns to Active, 0 disables
# kwin_script = "/path/to/appvol.js"   # override the bundled KWin script
```

The window writes `step` and `osd_show_name` here when they are changed in it;
the daemon leaves the rest of the file to you.

## Troubleshooting

```
appvol list                        # focus, streams, why nothing matched
appvol apps                        # what is playing, and how appvol names it
appvol profile list                # profiles and the current one
appvold -v                         # verbose daemon log
journalctl --user -u appvold -f    # when it runs under systemd
```

- **Nothing changes:** `appvol list` shows the cached focus. Windows on the panel
  or the desktop are ignored, and so is `plasmashell`. An application that is not
  playing anything has no stream to change yet.
- **The key does nothing:** the daemon is not running, or the key is not bound.
  See `systemctl --user status appvold`.
- **A profile key does nothing:** the action of that profile has no key yet.
  `appvol profile add` registers the action; assign the key in System Settings.
- **A profile matches nothing:** `appvol list` with the profile current shows the
  reason, and `appvol up --profile NAME` answers without switching.
- **No OSD:** check `osd = true` and a normal Plasma session, where `plasmashell`
  owns `org.freedesktop.Notifications`. The daemon logs `cannot show volume OSD`
  when the call fails.
- **The window does not start:** PySide6 is missing, or was installed after the
  last `install.sh`. `python3 -c "import PySide6"` answers it. The tray icon also
  needs a system tray in the panel.

## Documentation

- [docs/architecture.md](docs/architecture.md): components, D-Bus API, matching, lifecycle
- [docs/gui.md](docs/gui.md): the window and the tray icon
- [docs/osd.md](docs/osd.md): the OSD and how the application icon is chosen
- [docs/plasma-notes.md](docs/plasma-notes.md): what Plasma actually does
- [docs/development.md](docs/development.md): layout, tests, release process

## License

MIT, see [LICENSE](LICENSE).
