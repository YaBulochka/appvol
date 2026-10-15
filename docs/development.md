# Development

## Layout

```
appvol/focus.py     the target window: pid, resourceClass, desktopFileName, process tree
appvol/match.py     pure function: focus -> sink input indices
appvol/profiles.py  profiles: model, profiles.toml, matcher, current selection
appvol/volume.py    pure volume arithmetic: step, clamp, channel balance
appvol/icon.py      icon name for the OSD, as the mixer resolves it, with a panel fallback
appvol/osd.py       KDE OSD over D-Bus
appvol/config.py    config.toml
appvol/daemon.py    appvold: D-Bus service, pulsectl, KWin script loader, shortcuts
appvol/cli.py       appvol
kwin/appvol.js      KWin script, pushes the focus
desktop/            template of the KDE shortcut entry
systemd/            template of the user unit
packaging/          PKGBUILD and pacman scriptlets
install.sh          per-user install into ~/.local, no root
bin/                launchers: appvol, appvold, appvol-shortcuts, appvol-release
tests/
docs/
```

The parts that make decisions, matching and volume arithmetic, are pure functions
in their own modules and are covered by unit tests. Everything that needs a live
session (D-Bus, KWin, PipeWire, the OSD) is kept at the edges.

## Tests

```sh
python3 -m unittest discover -s tests -t .
```

| File | Covers |
| --- | --- |
| `tests/test_match.py` | focus to stream matching, all three steps and the refusal reasons |
| `tests/test_profiles.py` | ids, profiles.toml round trip, the profile matcher, the selection and its timeout |
| `tests/test_volume.py` | step, clamping, channel balance, mute |
| `tests/test_focus.py` | name normalisation, pid parsing, the `ppid` walk |
| `tests/test_icon.py` | stream properties, theme walk, .desktop fallback |
| `tests/test_config.py` | TOML parsing, bad values, clamping |
| `tests/test_cli.py` | argument parsing and the readable answers |
| `tests/test_shortcuts.py` | the desktop entry against the client command line |
| `tests/test_osd.py` | the OSD wrapper across a name owner change |
| `tests/test_daemon.py` | KWin script lookup in a checkout and in an installed layout |

No test needs a session: the ones that touch the bus use fakes.

## Profiles in a live session

The daemon registers one KGlobalAccel action per profile, and an action can be
pressed over D-Bus, which tests the whole path from the shortcut server to the
OSD without touching the keyboard:

```sh
appvol profile add spiketest --include spotify --name "Spike"
qdbus6 org.kde.kglobalaccel /component/appvol \
       org.kde.kglobalaccel.Component.invokeShortcut profile_spiketest
appvol profile list          # current: spiketest
qdbus6 org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.getComponent appvol
qdbus6 org.kde.kglobalaccel /component/appvol org.kde.kglobalaccel.Component.shortcutNames
appvol profile rm spiketest  # unregisters the action and drops the key
```

The keys live in `~/.config/kglobalshortcutsrc` under `[appvol]`, one line per
action (`profile_spiketest=Ctrl+Alt+Shift+F9,none,Spike`). They are set in System
Settings and survive a daemon restart, so a test can also assign one with
`setShortcutKeys` and check that a fresh daemon still reports it.

To exercise the idle timeout without waiting five minutes, start the daemon with a
throwaway config: `appvold -v --config /tmp/appvol.toml` with
`profile_idle_timeout = 10`. The return to Active is checked every ten seconds, so
it happens between ten and twenty seconds after the last press, and the log says
`profile <id> idle for 10s, back to active`.

## Release

The version lives in one place, `appvol/__init__.py`, and `bin/appvol-release`
copies it into `pkgver` in `packaging/PKGBUILD`.

```sh
$EDITOR appvol/__init__.py         # bump the version
bin/appvol-release --package       # archive and package (from HEAD in a git checkout)
git tag -a v0.1.0 -m "appvol 0.1.0" && git push --tags
```

What comes out:

* `dist/appvol-<version>.tar.gz` with a `.sha256` next to it. In a git checkout
  it is built with `git archive HEAD`, so the tree has to be clean; the script
  refuses to run otherwise and `--allow-dirty` overrides that.
* `packaging/appvol-<version>.tar.gz`, the same archive, because the package is
  built from it.
* `dist/appvol-<version>-1-any.pkg.tar.zst`, the pacman package.

The script also checks that the archive contains the files the package needs, and
tells you whether HEAD carries the matching tag.

The checksum is deliberately absent from `PKGBUILD`: the archive contains that
same `PKGBUILD`, so no sum written inside it could describe it. `makepkg` runs
with `sha256sums=('SKIP')` and the sum is published as the `.sha256` file.

## Packaging

`packaging/PKGBUILD` installs the module into site-packages, `appvol` and
`appvold` as two-line launchers into `/usr/bin`, `kwin/appvol.js` into
`/usr/share/appvol`, the substituted shortcut entry into
`/usr/share/applications`, and the substituted user unit into
`/usr/lib/systemd/user`. It declares `python`, `python-dbus`, `python-gobject` and
`python-pulsectl` as dependencies, and the Plasma session packages as optional
ones.

Two details are easy to miss when editing it:

* `makepkg` unpacks the archive into `$srcdir` but stays in the directory it was
  started from, so `package()` starts with `cd "$srcdir/$pkgname-$pkgver"`.
* Both templates are substituted with absolute paths. The shortcut server has no
  `~/.local/bin` in `PATH`, and systemd never reads the user's `PATH`.

To look inside a built package:

```sh
bsdtar -tf dist/appvol-<version>-<rel>-any.pkg.tar.zst
bsdtar -xOf dist/appvol-*.pkg.tar.zst .PKGINFO | grep -E '^(depend|optdepend)'
mkdir -p /tmp/root && bsdtar -xf dist/appvol-*.pkg.tar.zst -C /tmp/root
```

Extracting into a temporary root is the cheap way to check the installed layout:
the daemon will find `appvol.js` once `XDG_DATA_DIRS` points at
`/tmp/root/usr/share`, and the launchers work with `PYTHONPATH` pointing at
`/tmp/root/usr/lib/python3.x/site-packages`. Run such a check from a directory
that is not the checkout: with `python3 -m` and `-c`, the current directory comes
before `PYTHONPATH`, so an otherwise valid test can silently import the checkout.

`install.sh` is the same story without a package manager: it copies the package,
the KWin script and the templates into `<prefix>/share/appvol`, links the
launchers into `<prefix>/bin`, writes the substituted unit into
`~/.config/systemd/user` and registers the shortcut entry. `--uninstall` reverses
all of it, and the script refuses to run as root.
