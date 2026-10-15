# appvol

Volume control for the audio streams of the focused window, on KDE Plasma 6
(Wayland, PipeWire). Press a hotkey, and appvol changes the volume of every
audio stream that belongs to the application whose window is focused, showing
the stock KDE OSD.

```sh
appvol up      # +5% for the focused application
appvol down    # -5%
appvol mute    # toggle mute
appvol list    # streams, cached focus, and which match step fired
```

A user daemon on the session bus, a KWin script that reports the focused window,
and a thin client for the hotkeys. No root, no X11 tools, no GUI.

## Requirements

| Package (Arch) | Import name | Why |
| --- | --- | --- |
| `python` (3.11+) | — | `tomllib` for the config |
| `python-dbus` | `dbus` | session bus: the daemon API and the OSD |
| `python-gobject` | `gi` | the GLib main loop the daemon runs in |
| `python-pulsectl` | `pulsectl` | stream volume through pipewire-pulse |

The rest is the session appvol drives, and your distribution provides it: KDE
Plasma 6 on Wayland (`kwin` for the focus, `plasmashell` for the OSD),
`kglobalacceld` and System Settings for the hotkeys, PipeWire with
`pipewire-pulse`. `install.sh` checks the Python modules and names the packages
for your distribution.

## Install

pacman package (Arch), which declares the dependencies and installs into `/usr`:

```sh
bin/appvol-release --package           # build dist/*.pkg.tar.zst
sudo pacman -U dist/appvol-*.pkg.tar.zst
systemctl --user daemon-reload && systemctl --user enable --now appvold
```

Per user, any distribution, no root:

```sh
./install.sh --service     # into ~/.local; --uninstall reverts it
```

From the checkout, without installing anything:

```sh
bin/appvold                # the daemon, logs to stderr
bin/appvol up              # in another terminal
```

## Hotkeys

appvol appears in System Settings → Shortcuts on its own, like an application or
a system service. The pacman package puts its desktop entry into
`/usr/share/applications`; from the checkout or after `install.sh` use:

```sh
bin/appvol-shortcuts            # install or refresh the entry
bin/appvol-shortcuts --remove   # remove it
```

Search for "appvol", then bind **Volume up**, **Volume down** and **Toggle
mute**. No keys are bound by default. The `Exec` lines hold absolute paths on
purpose: the shortcut server has no `~/.local/bin` in `PATH`, so an entry added
by hand as `appvol up` (Add → Command or Script) fails with
`Could not find the program "appvol"`. Remove such entries if you made them.

## Config

`~/.config/appvol/config.toml`, every key optional:

```toml
step = 5          # relative step in percent
max_volume = 100  # upper limit, up to 150
osd = true        # show the KDE OSD
# kwin_script = "/path/to/appvol.js"   # override the bundled KWin script
```

## Troubleshooting

```sh
appvol list                        # focus, streams, why nothing matched
appvold -v                         # verbose daemon log
journalctl --user -u appvold -f    # when it runs under systemd
```

* Nothing changes: `appvol list` shows the cached focus. Windows on the panel or
  the desktop are ignored, and so is `plasmashell`. An application that is not
  playing anything has no stream to change yet.
* No OSD: check `osd = true` and a normal Plasma session, where `plasmashell`
  owns `org.freedesktop.Notifications`. The daemon logs `cannot show volume OSD`
  when the call fails.
* The key does nothing: the daemon is not running, or the key is not bound. See
  `systemctl --user status appvold`.

## Documentation

* [docs/architecture.md](docs/architecture.md) — components, D-Bus API, matching, lifecycle
* [docs/osd.md](docs/osd.md) — the OSD and how the application icon is chosen
* [docs/plasma-notes.md](docs/plasma-notes.md) — what Plasma 6.7.5 actually does
* [docs/development.md](docs/development.md) — layout, tests, release process

## License

MIT, see [LICENSE](LICENSE).
