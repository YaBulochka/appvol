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
