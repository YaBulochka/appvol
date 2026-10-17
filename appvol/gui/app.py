"""The GUI entry point: the window and the application object.

``bin/appvol-gui`` and ``python3 -m appvol.gui`` both end up in :func:`main`.
The window is QML (``appvol/gui/qml``); this module builds the application object
around it, so a second launch raises the window that is already open.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from .bridge import Bridge
from .icons import checkout_icon_path

log = logging.getLogger(__name__)

QML_DIR = Path(__file__).resolve().parent / "qml"
QML_ENTRY = QML_DIR / "Main.qml"

# The icon of the project, as install.sh and the packages name it in the theme:
# the window and the launcher use the plain one.
APP_ICON = "appvol"
# A theme without the project's icon yet still gets a speaker rather than
# nothing.
APP_FALLBACK = "audio-speakers"

# Qt Quick Controls picks the Breeze styled controls of the desktop; without the
# line the window would draw the plain Fusion style even on Plasma.
QUICK_CONTROLS_STYLE = "QT_QUICK_CONTROLS_STYLE"
QUICK_CONTROLS_VALUE = "org.kde.desktop"


def _icon(name: str, fallback: str) -> QIcon:
    """A themed icon, the checkout's file for it, or a generic one.

    ``bin/appvol-gui`` runs from a checkout, where the icons are not in the
    theme yet; the file beside the sources takes over then.  A theme that has
    neither the project's icon nor the file loaded gives the generic fallback,
    so a missing file never keeps the window from starting.
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
    # Closing the window leaves nothing behind: the daemon owns the keys and the
    # OSD, and the window is only the settings surface.
    app.setQuitOnLastWindowClosed(True)

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

    bridge.refresh()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
