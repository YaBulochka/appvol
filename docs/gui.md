# The Window

`appvol-gui` is the optional front end of appvol: a small window for the profiles.
It is a client of the daemon, like the
CLI, so it never touches PipeWire, KWin or `profiles.toml` itself.

```
bin/appvol-gui                          # from a checkout, needs PySide6
appvol-gui                              # after install.sh or the package
python3 -m appvol.gui                   # the module directly
```

## Requirements

| Package (Arch) | Why |
| --- | --- |
| `pyside6` | Qt 6 for Python: the window and the QML engine |
| `kirigami` | the KDE QML components the window is built from |
| `qqc2-desktop-style` | draws the controls in the Breeze style |
| `breeze-icons` | the icons used by the rows and the window |

The daemon and the CLI need none of them, which is why Arch gets two packages:
`appvol` and `appvol-gui`. `install.sh` installs the GUI part only when PySide6 is
importable, and says so when it is not; `--no-gui` skips it in any case.

## The window

The window is one view at a time. A segmented control at the top switches between
**Profiles** and **Running apps**; the choice is the same `mode` of `config.toml`
that `appvol mode` reads and writes, and the toolbar and the list follow it.

The header carries the view switch, then **New profile** (in the profiles view
only), **Refresh**, a **Bind Keys…** button and a **⋮** menu with **OSD App
Name**, **Bind Keys…**, **Reload from File** and **About appvol**. The window
never shows the whole settings panel; the menu keeps the header light.

The built-in **Active window** is pinned in a card above the list, in both views,
and is always visible. The card is the only place the **Step** of the volume keys
is set — it is the global step every application follows. The radio button of the
card marks it as the target of the keys, and its border picks up the accent when
it is the current one.

The list sits in its own area with a scrollbar; the header, the Active card and
the footer never scroll, and the window can be made small. In the profiles view
the section is **PROFILES**, with the number of profiles beside it; in the running
apps view it is **RUNNING APPLICATIONS**, and its caption says that the keys cycle
through these.

A line of the list is one row: a radio button, the icon, the name with a caption,
the volume slider, the percent, a mute button and a **⋮** menu.

* **Radio, icon and name.** The radio makes the target current, exactly as a
  profile key does. The icon is the icon of the profile or of the application.
* **Caption.** It counts the streams that match right now — `1 stream`,
  `3 streams`, or `nothing playing` — and, in the profiles view, names the key
  bound to the profile: `1 stream · Meta+F9`, or `no key · Bind…`, where **Bind…**
  opens System Settings → Shortcuts.
* **Slider.** It shows the volume of the target, which is the loudest of its
  matched streams, the same number the OSD shows. Dragging it moves the live
  streams, and the call is sent once, when the finger lifts. A target with nothing
  playing has a disabled slider.
* **Mute.** Mute is aggregate, like the hotkey: it mutes everything the profile
  covers, and unmutes all of it when all of it is muted.
* **⋮ menu.** In the profiles view it holds **Bind Keys…**, **Step…** (the step of
  that one profile, where `0 %` follows the global step), **Edit…** and
  **Remove**. The running-apps view drops the menu, because an application that is
  playing cannot be edited, keyed or stepped.

The row that the keys act on carries an accent bar on its left and a light tint,
so the current target is visible at a glance; the radio button stays for changing
it.

When no profile exists yet, the profiles view shows a dashed **New profile** row
where the list would be, and the header button does the same. When nothing is
playing, the running-apps view says so.

A one-line footer names when an idle profile returns to Active and the version of
the running installation; the **ⓘ** beside it explains the keys and the idle
return, the long text that used to sit in the footer. When `appvold` is not
running, a banner says so and offers **Try Again**, and the list stays empty
instead of pretending.

The window reads the whole panel with one `Overview()` call and refreshes it when
it gains focus, when a button asks for it, after every write, and every half
second while it is on screen. The timer keeps the sliders in step with the volume
keys and any other application that moves the same streams, so **Refresh** is only
needed after a change the window could not see.

Closing the window quits the GUI. The daemon and the hotkeys run on their own, so
nothing else stops: open the window to change a setting, close it to leave.

A narrow window (under 480 px) drops the slider onto a second line under the
name, hides the caption of **New profile** and the **Bind Keys…** button of the
header, and keeps the whole thing scrollbar-free down to 380 px.

## The editor

**New Profile** and **Edit** open a dialog over the window. The header carries the
title and a close button, the footer carries the actions, and only the body
scrolls, so the buttons never leave the screen however short the window is.

* **Name** is what the OSD and the window show. A new profile takes its
  identifier from the name — "Everything but CS2" is written as
  `everything-but-cs2` — and the caption under the field shows what it becomes.
  The identifier is not an input: renaming an existing profile keeps the id it
  was created with.
* **Applies to** is a switch between **Only these apps** and **All apps except…**.
  Both readings share one chip list, so switching the mode turns "play in Spotify"
  into "play in everything but Spotify" without retyping the list. **Only these
  apps** writes `include`, **All apps except…** writes `exclude`; an empty
  **Only these apps** means every application stream with the shell left out.
* **Playing now** lists what is playing as chips; one click adds the application.
  **Add app…** stays for a name that is not playing yet — a game or a browser
  added before it starts — and opens the same list with a text field.
* **Matches now** is a live line: it names the applications the draft profile
  would select at this moment and counts their streams, so a profile that is too
  wide or too narrow is visible before saving.
* **Step** and **Maximum volume** sit side by side, each with a **Default** box.
  Checked, the profile follows `config.toml`; unchecked, the field next to it
  holds a value of its own. The step takes fractions as well as whole percents:
  `2.5 %` is a valid step, typed with a dot or a comma.
* **Icon** previews the icon the OSD will draw and opens a grid of the theme's
  icons through **Change…**; **Automatic** in that grid clears the choice. Left
  automatic, a profile shows the icon of the application it names: the first
  entry of the list, resolved the way the daemon resolves it. The caption under
  the preview says where the icon comes from ("from the application" or
  "generic: no single application"). Steam game icons are ordinary theme icons
  there (`steam_icon_<appid>`, written by Steam into `hicolor`), so the search
  box finds them by appid even though no `.desktop` file maps the identifier to
  them.

The footer holds **Delete profile** on the left when an existing profile is being
edited, and **Cancel** with **Create profile** or **Save** on the right. Deleting
asks for confirmation first, the same dialog the row menu uses.

The editor writes the profile in one call when the primary button is pressed, so
the file never holds half an edit, and the daemon writes it atomically. Whether
the OSD captions the application name is decided by one switch in the window,
**OSD App Name** in the **⋮** menu, shared by every profile — it is off by
default, so the OSD shows the icon alone.

## What is not here

* Assigning keys. Keyboard shortcuts belong to System Settings, and appvol writes
  nothing to `kglobalshortcutsrc`.
* Per-stream mixing. The window works on profiles; to pick one stream out of three
  of the same application, use the profile of the application.
* The KDE OSD style. appvol shows the stock OSD; the window is its own thing.
