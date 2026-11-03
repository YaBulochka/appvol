# appvol (unreleased)

## Added

- **Global shortcuts on GNOME** through `org.freedesktop.portal.GlobalShortcuts`
  (version 2 on GNOME 51). The daemon opens a portal session at start, listens
  for `Activated` and routes the action ids through the same code the KGlobalAccel
  keys use. `appvol shortcuts` reports what is bound, `appvol shortcuts bind`
  opens the desktop's binding sheet for the actions that are missing, including
  one per profile. The session is recreated when the portal restarts, and a
  refused session is retried while the portal activates.

- The daemon registers itself with `org.freedesktop.host.portal.Registry` as
  `org.appvol.Daemon` before its first portal call, and again when the portal
  restarts. The portal stores the global shortcuts of an application under that
  id, so the bindings no longer follow the terminal the daemon was started from;
  `desktop/org.appvol.Daemon.desktop` is installed with the daemon because the id
  must name a desktop entry.

- **GNOME 45 and newer**, through the extension in `contrib/gnome`. It reports
  the focused window to `appvold`, so the Active profile, auto mode and the
  window's sliders follow the window you look at, and it exports the shell's own
  OSD, which the shell refuses to a plain client. `osd_backend = "auto"` now
  tries Plasma's OSD, then the GNOME one, then notifications.
  [docs/gnome.md](docs/gnome.md) has the install and the shortcut plan.

- On a desktop without KWin the daemon no longer retries the KWin script, and a
  missing KGlobalAccel is a debug line instead of a warning, so a GNOME session
  starts clean. `gnome-shell` is filtered out of "every application stream" like
  `plasmashell` on Plasma.

- The OSD falls back to the freedesktop notification daemon when the Plasma OSD
  is not on the bus, so a session without Plasma (or one whose plasmashell just
  restarted) still gets feedback from `appvol up`, a profile key or `appvol
  profile next`. The notification replaces itself instead of stacking, carries
  the application icon, the percentage as its progress hint, and says "Muted" at
  zero. `osd_backend` in `config.toml` pins a display: `auto` (Plasma, then
  notifications), `plasma` or `notifications`.

- `appvol profile next` and `appvol profile prev` walk the targets the keys
  cycle, the built-in Active profile first, wrapping around, with the OSD
  feedback of the target they land on. They reach the same order as **Next
  profile** and **Previous profile** through the new `CycleProfile(direction)`
  D-Bus method, so a desktop without KGlobalAccel can bind its own keys to them.

## Fixed

- The GNOME portal client keeps the bound keys alive across a restart of
  `appvold`: the new session claims the ids the provider already stores, which
  opens no dialog, instead of leaving every key dead until the next bind.
- `appvol shortcuts bind` opens the dialog again after the first time. GNOME
  accepts one `BindShortcuts` per session and refused the second request with
  `response 2`; the client now switches to `ConfigureShortcuts`, which is also
  the only way to fill a row that was left empty. A profile added later still
  goes through a fresh session, because its id is not in the store yet.

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
