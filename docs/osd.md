# OSD and application icons

A hotkey press shows the application icon and a volume bar with the percent, in
the stock KDE OSD.

## Methods

[`appvol/osd.py`](../appvol/osd.py) talks to
`org.freedesktop.Notifications /org/kde/osdService org.kde.osdService`:

* `mediaPlayerVolumeChanged(percent, name, icon)` draws `icon` with a progress
  bar and `name` as the caption, and `<name> Muted` at zero percent. In
  `shell/osd.cpp` of plasma-workspace this is `showProgress(icon, percent, 100,
  name)`.
* `volumeChanged(percent)` draws the generic volume icon. It is overloaded as
  `(i)` and `(ii)`, so the call always passes an explicit
  `signature="i"`.
* `showText(icon, text)` draws an icon with a caption, and is what `mute` uses.

appvol prefers the first method whenever the icon is known. The `name` argument
is sent empty: the icon alone looked better than an icon with a caption. The name
is still computed, `appvol list` prints it for diagnostics, and a future GUI
setting can show it. When no icon is known, the OSD falls back to
`volumeChanged(percent)` so the user still gets feedback:

```
match:  step=pid matched=1 (streams owned by pid 155358)
osd:    icon='spotify' (app 'Spotify')
```

`mute` shows the icon with the caption `Muted`, `unmute` shows the icon with the
volume bar (or `Unmuted` when the volume is zero).

## Where the icon comes from

The icon is taken from the same place the KDE mixer (plasma-pa) takes it, the
properties of the audio stream itself. Plasma walks the properties in this order
and keeps the first one that exists in the current icon theme:

1. `device.icon_name` / `media.icon_name` / `window.icon_name`
2. `application.icon_name`
3. `application.process.binary`
4. `application.name`
5. `pipewire.access.portal.app_id`

That is exactly `PulseAudioQt::PulseObject::iconName()`. The properties of the
owning client are merged into the stream properties, as happens during matching:
Spotify, for example, carries `application.process.binary=spotify` on the client
only.

When the stream advertises nothing that the theme knows, appvol falls back to the
window icon: `Icon=` of `<desktopFileName>.desktop`, then
`<resourceClass>.desktop`, then the identifier itself when it is not
reverse-DNS. Applications that do not advertise themselves at all (Node and
Electron players, launcher wrappers) end up with the same icon as the panel.

Divergence from the panel is expected and is not a bug: when an application
publishes an icon that differs from its window icon, the stream wins. Minecraft
announces `application.process.binary=java`, so the mixer and the OSD show the
Java icon instead of the window icon.

## Checking the theme without Qt

`QIcon::hasThemeIcon()` answers incorrectly outside a running session (the Qt
theme comes from the platform theme, not from a `setThemeName` call after
startup), and `QIcon::fromTheme()` has behaviour worth copying: it drops the last
segment after a dash, so `spotify-launcher` resolves to `spotify`. appvol
therefore walks the theme itself
([`appvol/icon.py`](../appvol/icon.py)): the theme name is read from
`kdeglobals` (`[Icons] Theme=`), then the theme, its `Inherits` chain and
`hicolor` are searched, along with `XDG_*_DIRS/pixmaps`. The name is also tried
without the last dash segment. Results are cached for the lifetime of the daemon,
so repeated key presses never touch the disk.

The walk was compared against `kiconfinder6` for 17 names with no differences.
On a Cool-Dark-Icons desktop this yields `spotify` for `spotify-launcher`,
`java` for Minecraft, `firefox-aurora-icon` for Firefox and
`utilities-terminal` for Konsole.

## A stale proxy costs an OSD

A detail worth knowing before editing [`appvol/osd.py`](../appvol/osd.py):
`dbus-python` resolves a well-known name to the unique name of its current owner
and keeps sending there. A cached proxy therefore keeps talking to a
`plasmashell` that is already gone, and every call fails with
`ServiceUnknown: The name is not activatable` while the volume still changes,
which is visible only in the log. The proxy is created with
`follow_name_owner_changes=True` (the call goes to the well-known name and the bus
picks the owner), and a failed call is retried once over a fresh proxy.
[`tests/test_osd.py`](../tests/test_osd.py) pins both down.
