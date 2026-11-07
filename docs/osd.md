# OSD and application icons

A hotkey press shows the application icon and a volume bar with the percent, in
the stock KDE OSD. Above 100% the bar gives way to the percentage, see below.

## Methods

[`appvol/osd.py`](../appvol/osd.py) talks to
`org.freedesktop.Notifications /org/kde/osdService org.kde.osdService`:

* `mediaPlayerVolumeChanged(percent, name, icon)` draws `icon` with a progress
  bar and `name` as the caption, and `<name> Muted` at zero percent. In
  `shell/osd.cpp` of plasma-workspace this is `showProgress(icon, percent, 100,
  name)`: the bar is pinned to 100%.
* `volumeChanged(percent)` draws the generic volume icon, and
  `volumeChanged(percent, maximumPercent)` the same against a ceiling of its own.
  The method is overloaded as `(i)` and `(ii)`, so the call always passes an
  explicit signature.
* `showText(icon, text)` draws an icon with a caption, and is what `mute` uses.

appvol prefers the first method whenever the icon is known. Whether the `name`
argument is filled in comes from **OSD App Name**, the one switch in the window:
off by default, the OSD shows the icon alone; on, it captions the
application name — both for stream profiles and for the Active one. A stream profile reads
"Spotify" with the volume bar and "Spotify Muted" at zero percent, while a volume
key on the focused window shows that window's icon and the bar and no name. The
name of the Active profile is still computed, `appvol list` prints it for
diagnostics, and the reply keeps it for a client that wants to show it.

A profile may allow more than 100% (`Maximum volume`, capped at 150). The player
method pins the bar to 100%, so the bar would fill up at 100% and the percentage
would lie while the volume kept going. Whenever the ceiling is not 100% and the
volume is at or below 100%, appvol therefore calls `volumeChanged(percent,
maximum)`: the bar is drawn against the ceiling and the label prints the real
percentage. The price is Plasma's own audio icon (a warning one above 100%)
instead of the application icon, and no caption. At a ceiling of 100% the player
method stays, so the common case keeps the application icon and the name.

Above 100% the ceiling bar is full whatever the value, so it would cost the
application icon for nothing. Plasma has no call that carries both a custom ceiling
and an application icon: `mediaPlayerVolumeChanged` pins the bar to 100%, and
`volumeChanged` draws its own icon. appvol therefore keeps the application icon and
prints the real percentage through `showText(icon, "105%")`, with no bar at all.
Below or at 100% nothing changes.

When no icon is known, the OSD falls back to `volumeChanged(percent)` so the user
still gets feedback:

```
match:  step=pid matched=1 (streams owned by pid 155358)
osd:    icon='spotify' (app 'Spotify')
```

`mute` on a profile with a caption uses the media player form with a value of zero,
which Plasma renders as `<name> Muted`; a profile without one gets
`showText(icon, "Muted")` instead. A ceiling other than 100% drops the caption,
so the mute message is Plasma's generic `Audio Muted`. `unmute` shows the volume
bar, or `Unmuted` through `showText` when the volume is zero and the bar would
stay empty. A profile that matches nothing answers `No stream` instead of staying
silent, because a profile key press is an explicit action on a target the user
chose.

The **Next profile** and **Previous profile** keys skip Active while it matches
no stream, so the cycle does not stop on a target that would only answer `No
stream`. When Active does match, they resolve it against the focus of the
moment, draw the icon and the current level of the focused window, and never
reuse the application it covered on an earlier pass, so an application that
stopped playing cannot keep painting the OSD. Its name stays out of the caption,
because Active covers every stream of the focused window, while a volume key
still follows **OSD App Name**.

A profile takes its icon from, in this order: its own `icon` key, when the theme
can render it; the matched stream, through the same chain as below, when the
profile has an `include`; and the `.desktop` file of the target identifier,
looked up by file name and by `StartupWMClass`. The target is the first `include`
entry, or, for a profile that only excludes applications, the first `exclude`
entry. A `steam_app_<appid>` identifier also reaches the game icon the theme
keeps as `steam_icon_<appid>`. When all of them come up empty the generic volume
icon is used, so the caption is never left without an icon.

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

Two kinds of value do not count as an application icon even when the theme can
render them. The generic audio placeholders (`audio-volume-high` and the other
`audio-volume-*` names, plus the generic audio and application icons such as
`audio-x-generic` or `application-x-executable`) are what Plasma draws for an
application that has no icon of its own. The Wine and Proton loaders
(`wine-preloader`, `wine64-preloader`, `wineserver`, `wine`) are shared by every
Windows game. appvol skips both and lets the window answer instead.

When the stream advertises nothing usable, appvol falls back to the window icon:
`Icon=` of `<desktopFileName>.desktop`, then `<resourceClass>.desktop`, then the
identifier itself when it is not reverse-DNS. Every root is tried, so a user
entry that names an icon the theme does not have cannot hide a system entry that
names a valid one. An application id may itself end in `.desktop` (Telegram is
`org.telegram.desktop`), so its entry is looked up as
`org.telegram.desktop.desktop` as well. An identifier is also matched against the
`StartupWMClass=` of the entries, because a window class rarely names its file:
the Spotify window and its stream identify themselves as `spotify`, while the
entry is `spotify-launcher.desktop` (which declares
`StartupWMClass=spotify`). Applications that do not advertise themselves at all
(Node and Electron players, launcher wrappers) end up with the same icon as the
panel.

A Proton game window is called `steam_app_<appid>` and Steam keeps its icon in
the theme as `steam_icon_<appid>`. The stream only says `wine-preloader`, so the
window class is the direct link to the game icon. When the game is not focused
there is no window to read, so appvol also reads `SteamAppId` from the
environment of the process that owns the stream (Proton exports it to every
process of the game). Either way it resolves the game icon before it settles on
the generic Wine icon.

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
`~/.config/kdeglobals`, then from `~/.config/kdedefaults/kdeglobals` (Plasma 6
keeps the distribution default there), then the theme, its `Inherits` chain and
`hicolor` are searched, along with `XDG_*_DIRS/pixmaps`. Flatpak and Snap icon
exports are searched even when the daemon's `XDG_DATA_DIRS` does not list them.
A theme is the merge of its installs over the XDG roots, so a name added under
`~/.local/share/icons` is found even when the theme itself lives in `/usr/share`
and the user root carries no `index.theme` of its own — this is how the Steam
game icons (`hicolor/<size>/apps/steam_icon_<appid>.png`) become visible to the
daemon and to the window's icon picker. The name is also tried without the last
dash segment.
Results are cached for the lifetime of the daemon, so repeated key presses never
touch the disk.

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
