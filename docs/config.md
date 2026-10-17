# Config

`~/.config/appvol/config.toml`, every key optional:

```toml
step = 5                     # relative step in percent, fractions like 2.5 allowed
max_volume = 100             # upper limit, up to 150
osd = true                   # show the KDE OSD
osd_show_name = false        # caption the application name in the OSD
mode = "profiles"            # "profiles" cycles profiles.toml, "auto" the running applications
profile_idle_timeout = 300   # seconds before a profile returns to Active, 0 disables
# kwin_script = "/path/to/appvol.js"   # override the bundled KWin script
```

The window writes `step`, `osd_show_name` and `mode` here when they are changed
in it; the daemon leaves the rest of the file to you.

The profiles live beside it, in `~/.config/appvol/profiles.toml`, and the daemon
owns that file. The keys of a profile are documented in
[architecture.md](architecture.md), together with the D-Bus API.
