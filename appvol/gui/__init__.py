"""The appvol GUI: a Kirigami window and a tray icon for the same profiles.

Optional, and packaged apart from the daemon (``appvol-gui``), because it needs
PySide6 while the daemon and the CLI need neither Qt nor a display.  The GUI is a
thin client of ``org.appvol.Daemon``: it never talks to PipeWire, KWin or
``profiles.toml`` itself, so the daemon stays the only writer.
"""
