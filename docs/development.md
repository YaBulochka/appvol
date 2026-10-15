# Development

## Layout

```
appvol/focus.py     the target window: pid, resourceClass, desktopFileName, process tree
appvol/match.py     pure function: focus -> sink input indices
appvol/apps.py      pure function: streams -> the applications playing them
appvol/profiles.py  profiles: model, profiles.toml, matcher, current selection
appvol/volume.py    pure volume arithmetic: step, clamp, channel balance
appvol/icon.py      icon name for the OSD, as the mixer resolves it, with a panel fallback
appvol/osd.py       KDE OSD over D-Bus
appvol/config.py    config.toml
appvol/daemon.py    appvold: D-Bus service, pulsectl, KWin script loader, shortcuts
appvol/cli.py       appvol
appvol/gui/         appvol-gui: D-Bus client, QML bridge, window and tray (optional)
kwin/appvol.js      KWin script, pushes the focus
desktop/            template of the window entry and the icon
systemd/            template of the user unit
packaging/          PKGBUILD (split into appvol and appvol-gui) and pacman scriptlets
install.sh          per-user install into ~/.local, no root
bin/                launchers: appvol, appvold, appvol-gui, appvol-release
tests/
docs/
```

The parts that make decisions, matching, grouping and volume arithmetic, are pure
functions in their own modules and are covered by unit tests. Everything that needs
a live session (D-Bus, KWin, PipeWire, the OSD) is kept at the edges. The GUI sits
on the same edge: `appvol/gui/client.py` is the D-Bus client, `bridge.py` is the
QML object, and the QML files only draw.

## Tests

```sh
python3 -m unittest discover -s tests -t .
```

| File | Covers |
| --- | --- |
| `tests/test_match.py` | focus to stream matching, all three steps and the refusal reasons |
| `tests/test_apps.py` | grouping streams into applications, identity, variants, the shell flag |
| `tests/test_profiles.py` | ids, profiles.toml round trip, the profile matcher, the selection and its timeout |
| `tests/test_volume.py` | step, clamping, channel balance, absolute set, mute |
| `tests/test_focus.py` | name normalisation, pid parsing, the `ppid` walk |
| `tests/test_icon.py` | stream properties, theme walk, .desktop fallback |
| `tests/test_config.py` | TOML parsing, bad values, clamping |
| `tests/test_cli.py` | argument parsing and the readable answers |
| `tests/test_gui.py` | the D-Bus client, the key rendering, the QML bridge (skipped without PySide6) |
| `tests/test_osd.py` | the OSD wrapper across a name owner change |
| `tests/test_daemon.py` | KWin script lookup, the shortcut actions, their dispatch, the OSD caption |

No test needs a session: the ones that touch the bus use fakes, and the GUI tests
skip themselves when PySide6 is not installed, so the suite runs on a machine
without Qt.

## Profiles in a live session

The daemon registers the KGlobalAccel actions of the component `Appvol` — the five
fixed ones and one per profile — and an action can be
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

## The GUI in a live session

```sh
bin/appvol-gui             # from the checkout; python3 -m appvol.gui works too
appvold -v                 # in another terminal, the window is only a client
```

The QML files are loaded from the directory (`appvol/gui/qml`), not from a Qt
resource, so a change shows up on the next start of the window and no build step
exists. Rebuild nothing; restart `bin/appvol-gui`.

The Python side is unit tested; the QML side needs eyes, and clicking through it
by hand is the test. Two tricks make that cheaper:

* The client and the bridge can be driven from a plain script, without a window,
  which checks the calls against the running daemon:

  ```sh
  python3 - <<'PY'
  import sys; sys.path.insert(0, ".")
  from appvol.gui.bridge import Bridge
  bridge = Bridge()
  bridge.refresh()
  print([(p["id"], p["percent"], p["key"]) for p in bridge.profiles])
  PY
  ```

* A single sheet can be opened in a throwaway window, which is quicker than
  clicking to it. Put a file next to a small runner that sets the `bridge` context
  property, and import the checkout by URL:

  ```qml
  import "file:///path/to/appvol/appvol/gui/qml"
  Kirigami.ApplicationWindow {
      ProfileEditor { id: editor }
      Component.onCompleted: editor.openFor(null)
  }
  ```

Kirigami's `OverlaySheet` logs `Binding loop detected for property
"implicitHeight"` at `OverlaySheet.qml:144` whenever a sheet opens. It comes from
the template, where `y` and `implicitHeight` depend on each other, and the values
settle; the sheets are laid out correctly. Do not chase it.

To look at a window, activate it first and capture only that one, so no other
window of the session ends up in the file:

```sh
kdotool search --name "^appvol$" windowactivate
spectacle -b -n -a -o /tmp/appvol.png      # -a: the active window only
```

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
* `dist/appvol-<version>-1-any.pkg.tar.zst` and
  `dist/appvol-gui-<version>-1-any.pkg.tar.zst`, the two pacman packages.

The script also checks that the archive contains the files the package needs, and
tells you whether HEAD carries the matching tag.

The checksum is deliberately absent from `PKGBUILD`: the archive contains that
same `PKGBUILD`, so no sum written inside it could describe it. `makepkg` runs
with `sha256sums=('SKIP')` and the sum is published as the `.sha256` file.

## Packaging

`packaging/PKGBUILD` is a split package with one source archive:

* **`appvol`** installs the module into site-packages, `appvol` and `appvold` as
  two-line launchers into `/usr/bin`, `kwin/appvol.js` into `/usr/share/appvol`,
  the substituted shortcut entry into `/usr/share/applications`, and the
  substituted user unit into `/usr/lib/systemd/user`. It declares `python`,
  `python-dbus`, `python-gobject` and `python-pulsectl` as dependencies, the
  Plasma session packages as optional ones, and `appvol-gui` as an optional one
  too.
* **`appvol-gui`** installs `appvol/gui/` (the Python files and the QML files
  beside them), the `appvol-gui` launcher, the window entry and the icon under
  `hicolor/scalable/apps`. It depends on `appvol`, `pyside6`, `kirigami`,
  `qqc2-desktop-style` and `breeze-icons`.

Two details are easy to miss when editing it:

* A split PKGBUILD has `pkgbase` and two `package_<name>()` functions, and the
  package-specific variables (`pkgdesc`, `depends`, `optdepends`, `install`) are
  set inside the function that uses them. `$pkgname` is the name of the package
  being built, so `/usr/share/licenses/$pkgname` resolves correctly in both.
* Both templates are substituted with absolute paths. The shortcut server has no
  `~/.local/bin` in `PATH`, and systemd never reads the user's `PATH`. The GUI
  entry gets an absolute path for the same reason.

To look inside a built package:

```sh
bsdtar -tf dist/appvol-<version>-<rel>-any.pkg.tar.zst
bsdtar -tf dist/appvol-gui-<version>-<rel>-any.pkg.tar.zst
bsdtar -xOf dist/appvol-*.pkg.tar.zst .PKGINFO | grep -E '^(depend|optdepend)'
mkdir -p /tmp/root && bsdtar -xf dist/appvol-*.pkg.tar.zst -C /tmp/root
```

`makepkg -si` installs both packages of the split package; to build and install
only one, use `makepkg -si --pkg appvol`.

Extracting into a temporary root is the cheap way to check the installed layout:
the daemon will find `appvol.js` once `XDG_DATA_DIRS` points at
`/tmp/root/usr/share`, and the launchers work with `PYTHONPATH` pointing at
`/tmp/root/usr/lib/python3.x/site-packages`. Run such a check from a directory
that is not the checkout: with `python3 -m` and `-c`, the current directory comes
before `PYTHONPATH`, so an otherwise valid test can silently import the checkout.

`install.sh` is the same story without a package manager: it copies the package,
the KWin script and the templates into `<prefix>/share/appvol`, links the
launchers into `<prefix>/bin`, writes the substituted unit into
`~/.config/systemd/user` and registers the shortcut entry. With PySide6 importable
it also links `appvol-gui` and installs the window entry and the icon into the
user's data directories; `--no-gui` and `--gui` force the decision either way.
`--uninstall` reverses all of it, and the script refuses to run as root.
