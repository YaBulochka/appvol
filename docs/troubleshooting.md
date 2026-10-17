# Troubleshooting

```
appvol list                        # focus, streams, why nothing matched
appvol apps                        # what is playing, and how appvol names it
appvol profile list                # profiles and the current one
appvold -v                         # verbose daemon log
journalctl --user -u appvold -f    # when it runs under systemd
```

- **Nothing changes:** `appvol list` shows the cached focus. Windows on the panel
  or the desktop are ignored, and so is `plasmashell`. An application that is not
  playing anything has no stream to change yet.
- **The key does nothing:** the daemon is not running, or the key is not bound.
  See `systemctl --user status appvold`.
- **A profile key does nothing:** the action of that profile has no key yet.
  `appvol profile add` registers the action; assign the key in System Settings.
- **A profile key does nothing in the auto mode:** it is meant to. `appvol mode
  profiles` goes back, and the switch in the window does the same.
- **A profile matches nothing:** `appvol list` with the profile current shows the
  reason, and `appvol up --profile NAME` answers without switching.
- **No OSD:** check `osd = true` and a normal Plasma session, where `plasmashell`
  owns `org.freedesktop.Notifications`. The daemon logs `cannot show volume OSD`
  when the call fails.
- **The window does not start:** PySide6 is missing, or was installed after the
  last `install.sh`. `python3 -c "import PySide6"` answers it.
