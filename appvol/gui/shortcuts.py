"""The keys bound to the profile actions, read from KGlobalAccel.

``appvold`` registers one action per profile and Plasma keeps the assigned keys
in ``kglobalshortcutsrc``, so the window can show what a profile is reachable by
without owning the binding itself.  The stored value is a Qt key sequence as an
integer, which :class:`~PySide6.QtGui.QKeySequence` turns back into
``Ctrl+Alt+1``.

The component name and the action name have to match what
:mod:`appvol.daemon` registers; ``tests/test_gui.py`` asserts that they do.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

import dbus
from PySide6.QtGui import QKeySequence

log = logging.getLogger(__name__)

SERVICE = "org.kde.kglobalaccel"
PATH = "/kglobalaccel"
IFACE = "org.kde.KGlobalAccel"

# Must equal KGA_COMPONENT and KGA_COMPONENT_FRIENDLY in appvol/daemon.py.
COMPONENT = "appvol"
COMPONENT_FRIENDLY = "Appvol"


def action_id(action: str, name: str) -> list[str]:
    """The four element action id KGlobalAccel uses for one of our actions."""
    return [COMPONENT, str(action), COMPONENT_FRIENDLY, str(name)]


def key_texts(entries: Iterable[Any]) -> str:
    """Render the bound sequences of ``shortcutKeys`` as one line.

    An unbound action returns an empty entry (all four integers zero), which
    renders as an empty string and is dropped.
    """
    texts = []
    for entry in entries:
        sequence = first_key(entry)
        if sequence is None or sequence == 0:
            continue
        text = QKeySequence(sequence).toString(QKeySequence.SequenceFormat.NativeText)
        if text:
            texts.append(text)
    return ", ".join(texts)


def first_key(entry: Any) -> int | None:
    """Pull the Qt key out of a ``a(ai)`` entry, in any shape D-Bus delivers.

    ``dbus-python`` hands out ``dbus.Struct`` (a tuple) holding ``dbus.Array``
    (a list) of four integers, of which only the first is used; plain lists come
    from the tests.
    """
    value = entry
    while isinstance(value, (list, tuple)):
        if not len(value):
            return None
        value = value[0]
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def kga_proxy():
    """Proxy for the shortcut server."""
    bus = dbus.SessionBus()
    return dbus.Interface(bus.get_object(SERVICE, PATH), IFACE)


class ShortcutKeys:
    """Read-only view of the keys bound to the profile actions."""

    def __init__(self, connect: Callable[[], Any] | None = None) -> None:
        self._connect = connect or kga_proxy
        self._proxy = None

    def _proxy_or_connect(self):
        if self._proxy is None:
            self._proxy = self._connect()
        return self._proxy

    def text(self, action: str, name: str) -> str:
        """Return ``"Ctrl+Alt+1"`` for an action, or ``""`` when nothing is bound."""
        try:
            entries = self._proxy_or_connect().shortcutKeys(action_id(action, name))
        except dbus.DBusException as exc:
            # A session without kglobalaccel is not an error here: the profiles
            # are still usable, they just cannot be reached from the keyboard.
            self._proxy = None
            log.debug("cannot read the keys of %s: %s", action, exc)
            return ""
        return key_texts(entries)
