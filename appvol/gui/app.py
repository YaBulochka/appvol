"""The GUI entry point: the window, the tray icon and the application object.

``bin/appvol-gui`` and ``python3 -m appvol.gui`` both end up in :func:`main`.
The window is QML (``appvol/gui/qml``), everything else lives here: the tray
menu in Qt because it has to be built from live data, and the application
object, so that closing the window leaves the tray running.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLocalServer, QLocalSocket, QUrl
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .bridge import Bridge
from .icons import checkout_icon_path

log = logging.getLogger(__name__)

QML_DIR = Path(__file__).resolve().parent / "qml"
QML_ENTRY = QML_DIR / "Main.qml"

# The icons of the project, as install.sh and the packages name them in the
# theme.  The tray wants the symbolic one, which Plasma recolours, the window
# and the launcher the plain one.
APP_ICON = "appvol"
TRAY_ICON = "appvol-symbolic"
# A theme without the project's icons yet still gets a speaker rather than
# nothing, for the window and for the tray.
APP_FALLBACK = "audio-speakers"
TRAY_FALLBACK = "audio-volume-high"

# Qt Quick Controls picks the Breeze styled controls of the desktop; without the
# line the window would draw the plain Fusion style even on Plasma.
QUICK_CONTROLS_STYLE = "QT_QUICK_CONTROLS_STYLE"
QUICK_CONTROLS_VALUE = "org.kde.desktop"


def _icon(name: str, fallback: str) -> QIcon:
    """A themed icon, the checkout's file for it, or a generic one.

    ``bin/appvol-gui`` runs from a checkout, where the icons are not in the
    theme yet; the file beside the sources takes over then.  A theme that has
    neither the project's icon nor the file loaded gives the generic fallback,
    so a missing file never keeps the window or the tray from starting.
    """
    icon = QIcon.fromTheme(name)
    if not icon.isNull():
        return icon
    path = checkout_icon_path(name)
    if path is not None:
        return QIcon(str(path))
    return QIcon.fromTheme(fallback)


def app_icon() -> QIcon:
    """The window icon: the plain ``appvol``."""
    return _icon(APP_ICON, APP_FALLBACK)


def tray_icon() -> QIcon:
    """The tray icon: the symbolic ``appvol-symbolic``, recoloured by the theme."""
    return _icon(TRAY_ICON, TRAY_FALLBACK)


def themed(name: str) -> QIcon:
    """A small themed icon for a menu entry, empty when the theme lacks it."""
    return QIcon.fromTheme(name)


class Tray(QSystemTrayIcon):
    """The tray icon: the window, the profiles and the volume actions.

    The menu is rebuilt whenever the profiles change, because the profile list
    and the tick that marks the current one both come from the daemon.
    """

    def __init__(self, bridge: Bridge, on_open, on_quit, parent=None) -> None:
        super().__init__(tray_icon(), parent)
        self.bridge = bridge
        self._on_open = on_open
        self._on_quit = on_quit
        self._menu = QMenu()
        self.setContextMenu(self._menu)
        self.setToolTip("appvol")
        self.activated.connect(self._activated)
        bridge.profilesChanged.connect(self._build)
        self._build()

    def _build(self) -> None:
        self._menu.clear()
        group = QActionGroup(self._menu)
        group.setExclusive(True)

        open_action = QAction("Open appvol", self._menu)
        open_action.triggered.connect(lambda: self._on_open())
        self._menu.addAction(open_action)
        self._menu.addSeparator()

        profiles = self.bridge.profiles
        if not profiles:
            empty = QAction("No profiles yet", self._menu)
            empty.setEnabled(False)
            self._menu.addAction(empty)
        for profile in profiles:
            action = QAction(str(profile.get("name") or profile.get("id")), self._menu)
            action.setCheckable(True)
            action.setChecked(bool(profile.get("current")))
            action.triggered.connect(
                lambda _checked=False, identifier=str(profile.get("id")): self.bridge.selectProfile(
                    identifier, True
                )
            )
            group.addAction(action)
            self._menu.addAction(action)

        self._menu.addSeparator()
        bind = QAction("Bind keys…", self._menu)
        bind.triggered.connect(lambda: self.bridge.openShortcuts())
        self._menu.addAction(bind)
        self._menu.addSeparator()

        for label, icon_name, direction in (
            ("Volume up", "audio-volume-high", "up"),
            ("Volume down", "audio-volume-low", "down"),
        ):
            action = QAction(themed(icon_name), label, self._menu)
            action.triggered.connect(
                lambda _checked=False, value=direction: self.bridge.adjust(value)
            )
            self._menu.addAction(action)

        mute = QAction(themed("audio-volume-muted"), "Toggle mute", self._menu)
        mute.triggered.connect(lambda: self.bridge.toggleMute())
        self._menu.addAction(mute)

        self._menu.addSeparator()
        quit_action = QAction(themed("application-exit"), "Quit", self._menu)
        quit_action.triggered.connect(lambda: self._on_quit())
        self._menu.addAction(quit_action)

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_open()


# Local socket name for the single-instance check; scoped to the user so two
# users on the same machine never collide.
INSTANCE_SOCKET = f"appvol-gui-{os.getuid()}"


def _tell_running_instance_to_show() -> bool:
    """Connect to an already running GUI and ask it to show its window.

    Returns True when a running instance was found and notified.
    """
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_SOCKET)
    if not sock.waitForConnected(500):
        return False
    sock.write(b"show")
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


def main(argv: list[str] | None = None) -> int:
    """Run the GUI; returns the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    os.environ.setdefault(QUICK_CONTROLS_STYLE, QUICK_CONTROLS_VALUE)

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("appvol")
    app.setApplicationDisplayName("appvol")
    app.setDesktopFileName("org.appvol.gui")
    app.setWindowIcon(app_icon())
    # The tray keeps the process alive, so the last window may close freely.
    app.setQuitOnLastWindowClosed(False)

    # Single instance: if another GUI is already running, ask it to show its
    # window and exit instead of opening a second one.
    if _tell_running_instance_to_show():
        return 0

    bridge = Bridge()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.load(QUrl.fromLocalFile(str(QML_ENTRY)))
    if not engine.rootObjects():
        log.error("cannot load %s", QML_ENTRY)
        return 1

    window = engine.rootObjects()[0]

    def show_window() -> None:
        window.show()
        window.raise_()
        window.requestActivate()

    # Accept "show" requests from later launches and focus the window.
    server = QLocalServer()
    QLocalServer.removeServer(INSTANCE_SOCKET)
    if not server.listen(INSTANCE_SOCKET):
        log.error("cannot listen on instance socket %s", INSTANCE_SOCKET)

    def handle_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.waitForReadyRead(500)
            show_window()
            conn.disconnectFromServer()

    server.newConnection.connect(handle_connection)

    tray = Tray(bridge, show_window, app.quit)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.warning("no system tray on this desktop, the window is the only way in")
    tray.show()

    bridge.refresh()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
