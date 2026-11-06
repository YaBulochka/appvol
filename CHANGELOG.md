# appvol 0.8.0 (2026-11-06)

This release closes the two follow-ups to 0.7.3: a focused application no longer
appears twice in the running-apps view, and the OSD icon falls back to the window
when the stream only advertises a placeholder or a shared Wine/Proton loader.

## Fixed

### Auto mode

- The application of the focused window is no longer listed twice. Active already
  covers its streams, so that application stays in the Active card and is left
  out of the running-applications list and of the cycle. One application now
  appears once, and **Next profile** / **Previous profile** no longer contain an
  Active step and an application step that do the same thing.
- A selected application that becomes focused returns the selection to Active,
  and `Overview()`, `Profiles()` and `appvol profile list` report that new
  selection immediately instead of the stale target for one refresh.
- The profile editor still receives every playing application through
  `Applications()`, including the focused one, so it remains available as a chip.

### Icons

- Placeholder names no longer count as an application icon: `audio-volume-*`,
  `audio-x-generic`, `application-x-executable` and the other generic audio and
  application icons are skipped, and the window entry answers instead.
- Shared Wine and Proton loaders (`wine-preloader`, `wine64-preloader`,
  `wineserver`, `wine`) no longer win over the application icon.
- A Proton game window (`steam_app_<appid>`) reaches its
  `steam_icon_<appid>`: through the window class when the game is focused, and
  through `SteamAppId` in the environment of the process that owns its stream
  when it is not.
- A user `.desktop` entry whose `Icon=` the theme cannot render no longer hides a
  valid system entry with the same name.
- An application id that itself ends in `.desktop` (Telegram is
  `org.telegram.desktop`) is looked up as `org.telegram.desktop.desktop`, not as
  `org.telegram`, so Telegram draws its own icon instead of the generic volume
  one.

### Theme lookup

- The icon theme is read from `~/.config/kdedefaults/kdeglobals` when
  `~/.config/kdeglobals` has no `[Icons] Theme`, so the daemon uses the theme the
  panel actually draws instead of falling back to `breeze`.
- Flatpak and Snap icon exports are searched even when the daemon's
  `XDG_DATA_DIRS` does not list them.

# appvol 0.7.3 (2026-11-03)

## Fixed

- `appvol list` prints the id of the current target, and `appvol profile list`
  reports the auto targets while the auto mode cycles them. An auto target
  (`app-spotify`) carries the same name and scope as a file profile (`spotify`),
  and the two were indistinguishable in both commands.
- An application icon is also looked up by `StartupWMClass`, so a window class
  that is named after the application finds the entry that is named after its
  launcher. Spotify (`spotify` → `spotify-launcher.desktop`) and Konsole
  (`konsole` → `org.kde.konsole.desktop`) now draw their own icon in the OSD
  instead of the generic volume one.

# appvol 0.7.2 (2026-10-21)

## Fixed

- **Next profile** and **Previous profile** no longer repaint the last
  application Active covered after its stream is gone. Landing on Active resolves
  the focused window again, so a stale icon and level cannot stay in the OSD; a
  window with no sink input answers `no stream` instead of leaving the previous
  panel on screen. This showed up in auto mode as a Wine entry that had already
  left `appvol list` and the KDE mixer but kept appearing in the cycle.

# appvol 0.7.1 (2026-10-17)

## Added

- The window re-reads the panel twice a second while it is on screen, so the
  sliders follow the volume keys and any other application that moves the same
  streams without pressing **Refresh**. An idle poll rebuilds nothing and draws
  nothing, and the window stops polling when it is hidden.

## Changed

- **Step** accepts fractional values: the field takes `2.5 %`, typed with a dot or
  a comma, and the buttons next to it move by half a percent. `config.toml` and a
  profile's `step` in `profiles.toml` already held a float, so no file changes.

## Fixed

- Icon lookup is cached. Resolving the icon of a stream walked the whole icon
  theme for every name the theme does not know, over a hundred milliseconds per
  overview with a handful of profiles and streams. Reading the panel now costs
  well under a millisecond.

# appvol 0.7.0 (2026-10-17)

## Changed

- The profile editor is a dialog now: the header and the footer stay put and only
  the body scrolls. The identifier is no longer an input field — a new profile
  derives it from its name, and the caption under the field shows what it becomes.
- **Include** and **Exclude** are one chip list with an **Applies to** switch
  between "Only these apps" and "All apps except…", so the mode says what the list
  means. What is playing appears as chips that add the application in one click,
  and a live **Matches now** line names the applications the draft profile selects
  and counts their streams before it is saved.
- **Step** and **Maximum volume** sit side by side, each with a **Default** box
  that follows `config.toml` when checked.
- The icon row previews the icon the OSD will draw and opens a searchable grid of
  the theme's icons through **Change…**; **Automatic** clears the choice and
  previews the icon of the first application the profile covers, the same icon the
  daemon draws on the OSD. The caption says where an automatic icon comes from.
- The OSD icon of an exclude profile ("everything but CS2") now comes from the
  excluded application instead of an arbitrary stream that happened to be playing.
- **Delete profile** moved into the dialog, with the same confirmation the row menu
  uses.

## Fixed

- Icon lookup merges a theme over every XDG root. A name added under
  `~/.local/share/icons` is now found even when the theme itself is installed
  under `/usr/share` and the user root has no `index.theme` of its own. This is
  where Steam keeps its game icons, so `steam_icon_<appid>` shows up in the icon
  picker and in the OSD instead of the generic volume icon.

## Removed

- The tray icon. The window is the only GUI now: open it to change a setting and
  close it to leave. The daemon and the hotkeys never depended on the tray, and
  the three volume actions and the profile switches stay on the keyboard. The
  symbolic `appvol-symbolic` icon and the `AdjustTarget`/`ToggleMuteTarget`
  helpers of the GUI client are gone with it.

# appvol 0.6.1 (2026-10-16)

## Fixed

- OSD: when switching to an application whose streams are muted, the OSD now shows "<name> Muted" (or plain "Muted") instead of its last volume level. The same applies when changing the volume of a muted application: Plasma renders the muted caption instead of a progress bar the app does not actually have.

# appvol 0.6.0 (2026-10-16)

## Window redesign

The window is a new one, with two views and their own layouts:

### Profiles view

Each row carries the radio, icon, name+caption, slider, percent, mute and menu; Bind Keys / Step / Edit / Remove live in the menu; the current row shows an accent bar and a hairline; narrow windows drop the slider onto a second line.  The empty state uses a dashed outline for "New profile".

### Auto mode view

A segmented control switches between Profiles and Running apps (the same `mode` config key).  Active apps pin in a card above the list, with the global Step bar shared; per-row actions live in the ⋮ menu.

### Header and footer

The header holds "New profile" (outline button), Refresh, Bind Keys and a menu with OSD name / Reload from File / About appvol.  The footer carries summary and version.

### Architecture

The daemon stays the only source of truth: the window is still a D-Bus client of `org.appvol.Daemon` through the bridge, and nothing new writes to disk from QML.

## Documentation

- README: lead with hotkeys / profiles / auto mode; split screenshots into per-view images; drop "No root" section.
- docs/config.md: key definitions moved out of architecture.md.
- docs/troubleshooting.md: error messages and fixes moved out of troubleshooting in README.
- docs/gui.md: updated to describe the new window layout.
