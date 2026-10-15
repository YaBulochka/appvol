# Plasma 6.7.5 notes

Recon on a live system. Every item either contradicted an assumption or refined
one, and the code follows what the system actually does.

## KWin scripting

* `org.kde.KWin /Scripting` offers `loadScript(path, name)` and
  `isScriptLoaded(name)`; `/Scripting` has no `run()`. `loadScript` returns an id,
  and `run()` is called on a separate object `/Scripting/Script<id>` (interface
  `org.kde.kwin.Script`). Loading a second script under a taken name returns
  `-1`, so the daemon calls `unloadScript` first.
* `loadScript` has two overloads and `dbus-python` sees only the first one, so
  the call passes an explicit `signature="ss"`.
* `workspace.activeWindow` exposes `pid`, `resourceClass`, `resourceName`,
  `desktopFileName`, `caption` and `windowType`. `callDBus` is available inside
  the script, integral JS numbers marshal into D-Bus `i` correctly, and the
  signal `workspace.windowActivated` exists.

## OSD

* `org.kde.osdService.volumeChanged` is overloaded as `(i)` and `(ii)`, so the
  call passes an explicit `signature="i"`. `showText` is available.
* The stock `volumeChanged` cannot draw an application icon.
  `mediaPlayerVolumeChanged(percent, name, icon)` can: in `shell/osd.cpp` of
  plasma-workspace it calls `showProgress(icon, percent, 100, name)`, and
  `showText(icon, "%1 Muted")` at zero percent. appvol uses it whenever the icon
  is known, with an empty name for the Active window profile (only the icon on
  screen) and with the profile name otherwise, which also gives a "Spotify
  Muted" caption instead of a plain "Muted". See [osd.md](osd.md) for the icon
  sources.
* An OSD proxy must not be cached as is. `dbus-python` resolves a well-known name
  to the unique name of the current owner and keeps sending there, so a cached
  proxy survives into the next `plasmashell` and every call fails with
  `ServiceUnknown: The name is not activatable` while the volume still changes.
  The fix and its test are described in [osd.md](osd.md).

## Icons

* The KDE mixer (plasma-pa) looks for the icon of a stream in the properties of
  the stream itself (`PulseAudioQt::PulseObject::iconName()`): `device.icon_name`,
  `media.icon_name`, `window.icon_name`, `application.icon_name`,
  `application.process.binary`, `application.name`,
  `pipewire.access.portal.app_id`, first hit in the icon theme wins. For a window
  plasmashell takes `Icon=` of the .desktop file instead. appvol uses the first
  source and keeps the second as a fallback.
* Properties are sensitive to spelling: the pulse layer reports
  `application.icon_name`, PipeWire reports `application.icon-name`, so both
  spellings are read.
* `QIcon::hasThemeIcon()` answers incorrectly outside a running session (the Qt
  theme comes from the platform theme, not from a `setThemeName` call after
  startup), and `QIcon::fromTheme()` has a behaviour worth copying: it drops the
  last segment after a dash, so `spotify-launcher` becomes `spotify`. The
  "is this name in the theme" check therefore walks the theme directories by hand
  and was compared against `kiconfinder6` for 17 names, with no differences.

## Streams and matching

* A Spotify sink input has no `application.process.id`; the pid lives on the
  PulseAudio client (`client.id` to `application.process.id`). Matching therefore
  compares sink-input properties merged with the properties of the client.
* `pulsectl` reports `PA_VOLUME_UI_MAX` (150%) for an index, which matches the
  allowed `max_volume`.
* Spotify started through `spotify-launcher` reports
  `desktopFileName = "spotify-launcher"` to its window but
  `resourceClass = "Spotify"`. The name step therefore compares both fields
  instead of `desktopFileName` alone.

## Hotkeys

* A desktop file with `Actions=` and a non-empty `X-KDE-Shortcuts` (in any group,
  service or action) becomes a component in `kglobalacceld`.
  `KServiceActionComponent::loadSettings` registers one shortcut per action and
  `emitGlobalShortcutEvent` launches the action's `Exec` through
  `KIO::ApplicationLauncherJob`. Scanning follows sycoca changes, so a new entry
  appears in the list at once, without a re-login.
* `X-KDE-GlobalShortcutType=Service` removes the extra "launch the file itself"
  action that KDE adds by default. `X-KDE-Shortcuts=none` is how KDE spells "no
  key bound": an empty value does not work, because the daemon looks for a
  non-empty one. A non-empty value is also what makes a running `kglobalacceld`
  notice the file at all.
* Changed desktop files are not re-read while the component already exists. Force
  a reload with `bin/appvol-shortcuts --remove`, `kbuildsycoca6 --noincremental`,
  then reinstall the entry.
* The flag `X-KDE-GlobalAccel-CommandShortcut=true`, which the KCM writes for
  Add → Command or Script, makes the KCM label the actions with the raw `Exec`
  string and file the component under "Commands". Without the flag the actions
  keep their `Name`s and a file from `~/.local/share/applications` is shown as an
  application. The appvol entry takes the second route.
* The shortcut server runs `Exec` with the environment of the session, which has
  no `~/.local/bin` in `PATH`. A relative command fails with
  `Could not find the program "appvol"`, which is why every `Exec` line in the
  entry holds an absolute path.
* A component can also be created at run time, with no desktop file at all.
  `org.kde.KGlobalAccel.doRegister([component, action, componentName, actionName])`
  creates the action and, on the first call, the component; `getComponent`
  returns its object path (`/component/appvol`; non-alphanumeric characters
  become `_`) and `Component.invokeShortcut(action)` emits the press. appvol
  registers one action per profile that way, so a new profile needs no
  `kbuildsycoca6` run and the profile list follows the daemon.
* Keys go in through `setShortcutKeys(actionId, keys, flags)`, where `keys` is
  `a(ai)`: one structure per shortcut, holding the ints of one Qt key sequence
  (the first is `key | modifiers`, the three others zero, so `Ctrl+Alt+Shift+F9`
  is `0x0F000038` and `Meta+Alt+S` reads back as `402653267`). `dbus-python`
  wants that structure spelled out on write and hides it on read.
* A key assigned to a component lands in `kglobalshortcutsrc` under a section
  named after it (`[appvol]`, exactly like `[kmix]`) and is restored when the
  component registers again, so the bindings survive a restart of the daemon.
  `unregister(component, action)` removes the action, its key and, when it was
  the last one, the whole section.
* `globalShortcutPressed/Repeated/Released(componentUnique, actionUnique,
  timestamp)` arrive on the component object, with `timestamp` always 0. A
  service component ignores everything but `Pressed`
  (`KServiceActionComponent::emitGlobalShortcutEvent`), and the registry keeps a
  single "last shortcut": pressing another one emits `Released` for the previous
  one, releasing a key emits it for the current one. A held profile key and a
  tapped one are byte-identical, which is why appvol switches the profile on
  press and switches back on the next press.
* There is no deep link into the shortcut list. `systemsettings kcm_keys` opens
  it, and the entries are found by name: "appvol" holds the three volume actions
  from the desktop file, "appvol profiles" holds one action per profile.
* The keys can be read back with `shortcutKeys(actionId)` against
  `/kglobalaccel`, which answers `a(ai)` in the same shape `setShortcutKeys`
  takes: one structure per shortcut, first int `key | modifiers`, three zeros. An
  action with no key answers with a single structure of zeros rather than an empty
  array, so "unbound" has to be tested as `key == 0`. Qt turns the integer back
  into the text the KCM shows, `QKeySequence(16777330).toString()` being
  `Volume Up`, which is how the window labels each profile.

## Audio backend

* Restarting `pipewire-pulse`, verified live: the first call fails with
  `CallError` or `PulseDisconnected`, the daemon closes the connection, creates a
  new one and repeats the operation, so the command reaches its result without
  manual action. Immediately after the restart the streams may still be missing;
  `stream-restore` brings them back within a couple of seconds.
