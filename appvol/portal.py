"""Global shortcuts through the xdg-desktop-portal.

GNOME has no KGlobalAccel and gives no other way to grab a key outside the
shell, so the portable contract is ``org.freedesktop.portal.GlobalShortcuts``
(version 2 on GNOME 51).  appvol asks the portal for a session, lists what is
already bound, and shows the portal's binding dialog only for the actions that
are missing.  The portal owns the keys from then on and emits ``Activated``,
which the daemon routes through the same handler the KGlobalAccel keys use.

The protocol is three requests, each answered by a ``Response`` signal on a
request object whose path is derived from the caller's unique name and a token:

* ``CreateSession`` returns the session handle the rest of the calls need;
* ``ListShortcuts`` returns the bindings that survived a restart;
* ``BindShortcuts`` shows the dialog and returns what the user chose.

Nothing here raises to the caller: a desktop without the portal, or a portal
that refuses, leaves :attr:`PortalShortcuts.session` empty and the daemon falls
back to the keys its own desktop offers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

import dbus
from gi.repository import GLib

log = logging.getLogger(__name__)

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_IFACE = "org.freedesktop.portal.GlobalShortcuts"
REGISTRY_IFACE = "org.freedesktop.host.portal.Registry"
REQUEST_IFACE = "org.freedesktop.portal.Request"

# The application id of the daemon in the portal.  It must match the basename of
# a .desktop file, which is why desktop/org.appvol.Daemon.desktop exists; the
# portal keys the bindings of the global shortcuts by it.
APP_ID = "org.appvol.Daemon"

REQUEST_TIMEOUT_SECONDS = 30

# How the portal reports a finished request: 0 success, 1 cancelled by the user,
# 2 anything else.
RESPONSE_OK = 0
RESPONSE_CANCELLED = 1


class PortalShortcuts:
    """The GlobalShortcuts portal, as far as appvol needs it."""

    def __init__(
        self,
        bus,
        on_pressed: Callable[[str], None],
        actions: Callable[[], Sequence[tuple[str, str]]],
    ) -> None:
        self.bus = bus
        self.on_pressed = on_pressed
        self._actions = actions
        self.session = ""
        self.bound: set[str] = set()
        self.error = ""
        self._requests = 0
        self._retries = 0
        self._pending: dict[str, tuple[int, Callable]] = {}
        self._portal = None
        self._sender = ""
        self._subscribed = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Open a session and listen for presses.  A plain desktop is fine."""
        try:
            self._sender = str(self.bus.get_unique_name()).lstrip(":").replace(".", "_")
            self._portal = dbus.Interface(
                self.bus.get_object(PORTAL_SERVICE, PORTAL_PATH), PORTAL_IFACE
            )
        except dbus.DBusException as exc:
            self.error = f"no global shortcuts portal: {exc.get_dbus_message()}"
            log.debug("portal: %s", self.error)
            return
        self._subscribe()
        self._register()
        self._open_session()

    def _register(self) -> None:
        """Give the portal a stable application id before the first portal call.

        Without it xdg-desktop-portal derives the id from the systemd unit of the
        process: empty for a plain daemon, or the terminal's when the daemon is
        started from a terminal.  The id must name a ``.desktop`` file, and
        ``desktop/org.appvol.Daemon.desktop`` is installed with the daemon.
        """
        try:
            registry = dbus.Interface(
                self.bus.get_object(PORTAL_SERVICE, PORTAL_PATH), REGISTRY_IFACE
            )
            registry.Register(
                APP_ID,
                dbus.Dictionary({}, signature="sv"),
                dbus_interface=REGISTRY_IFACE,
                signature="sa{sv}",
            )
            log.debug("portal: registered as %s", APP_ID)
        except dbus.DBusException as exc:
            # An older portal has no registry; the id then comes from the unit.
            log.debug("portal: cannot register %s: %s", APP_ID, exc.get_dbus_message())

    def _open_session(self) -> None:
        # ``session_handle_token`` is required: without it xdg-desktop-portal
        # takes its own NULL-token assert and the service crashes.
        self._request(
            "CreateSession",
            "a{sv}",
            {},
            self._on_session,
            {"session_handle_token": "appvol"},
        )

    def _retry_session(self) -> bool:
        self._open_session()
        return False

    def _schedule_retry(self) -> None:
        if self._retries >= 5:
            return
        self._retries += 1
        # The portal restarts on its own (an upgrade, a crash), and the first
        # request can land while it is activating.
        GLib.timeout_add_seconds(2, self._retry_session)

    def _subscribe(self) -> None:
        if self._subscribed:
            return
        self.bus.add_signal_receiver(
            self._activated,
            signal_name="Activated",
            dbus_interface=PORTAL_IFACE,
            path=PORTAL_PATH,
        )
        self.bus.add_signal_receiver(
            self._portal_changed,
            signal_name="NameOwnerChanged",
            dbus_interface="org.freedesktop.DBus",
            bus_name="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            arg0=PORTAL_SERVICE,
        )
        self._subscribed = True

    def _portal_changed(self, _name, _old_owner, new_owner) -> None:
        if not new_owner:
            return
        log.debug("portal: the service appeared, opening a session")
        self.session = ""
        self.bound = set()
        self._retries = 0
        self._register()
        self._open_session()

    def status(self) -> dict:
        wanted = [action for action, _ in self._actions()]
        return {
            "available": bool(self.session),
            "session": self.session,
            "bound": sorted(self.bound),
            "missing": [action for action in wanted if action not in self.bound],
            "error": self.error,
        }

    # -- requests ----------------------------------------------------------

    def _request(
        self,
        method: str,
        signature: str,
        pre: list,
        callback,
        extra: dict | None = None,
        timeout: int | None = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """Send a portal request and route its ``Response`` to ``callback``.

        ``timeout`` of ``None`` waits forever: the binding dialog stays open until
        the user closes it, which can take minutes, and a stale request answer is
        harmless next to forgetting the bindings.
        """
        token = f"appvol{self._requests}"
        self._requests += 1
        path = f"{PORTAL_PATH}/request/{self._sender}/{token}"
        options = dbus.Dictionary({"handle_token": dbus.String(token)}, signature="sv")
        for key, value in (extra or {}).items():
            options[key] = dbus.String(value)

        def on_response(code, results, *_args) -> None:
            self._finish(path)
            callback(int(code), dict(results))

        self.bus.add_signal_receiver(
            on_response,
            signal_name="Response",
            dbus_interface=REQUEST_IFACE,
            path=path,
        )
        timeout_id = 0
        if timeout is not None:
            timeout_id = GLib.timeout_add_seconds(timeout, self._expire, path, on_response)
        self._pending[path] = (timeout_id, on_response)
        try:
            getattr(self._portal, method)(
                *pre, options, dbus_interface=PORTAL_IFACE, signature=signature
            )
        except dbus.DBusException as exc:
            self._finish(path)
            self.error = f"{method} failed: {exc.get_dbus_message()}"
            log.debug("portal: %s", self.error)
            callback(2, {})

    def _finish(self, path: str) -> None:
        pending = self._pending.pop(path, None)
        if pending is None:
            return
        timeout, receiver = pending
        if timeout:
            GLib.source_remove(timeout)
        self.bus.remove_signal_receiver(
            receiver,
            signal_name="Response",
            dbus_interface=REQUEST_IFACE,
            path=path,
        )

    def _expire(self, path: str, receiver) -> bool:
        log.debug("portal: no answer for %s", path)
        self._pending.pop(path, None)
        self.bus.remove_signal_receiver(
            receiver,
            signal_name="Response",
            dbus_interface=REQUEST_IFACE,
            path=path,
        )
        receiver(2, {}, None)
        return False

    # -- responses ---------------------------------------------------------

    def _on_session(self, code: int, results: dict) -> None:
        if code != RESPONSE_OK:
            self.error = f"the portal refused the session (response {code})"
            log.debug("portal: %s", self.error)
            self._schedule_retry()
            return
        self._retries = 0
        self.error = ""
        self.session = str(results.get("session_handle", ""))
        log.info("portal: global shortcut session %s", self.session)
        self.refresh()

    def refresh(self) -> None:
        """Ask the portal what is bound right now."""
        if not self.session:
            return
        self._request("ListShortcuts", "oa{sv}", [self.session], self._on_list)

    def _on_list(self, code: int, results: dict) -> None:
        if code != RESPONSE_OK:
            log.debug("portal: ListShortcuts answered %d", code)
            return
        self.bound = {str(shortcut[0]) for shortcut in results.get("shortcuts", [])}
        log.debug("portal: bound shortcuts: %s", ", ".join(sorted(self.bound)) or "none")

    def bind(self) -> bool:
        """Show the binding dialog for the actions that are missing.

        The dialog is the portal's, so this returns as soon as the request is
        sent; the answer arrives as a ``Response`` and lands in :attr:`bound`.
        """
        if not self.session:
            self.error = "no portal session; global shortcuts are not available here"
            return False
        missing = [
            (action, friendly)
            for action, friendly in self._actions()
            if action not in self.bound
        ]
        if not missing:
            log.info("portal: every shortcut is already bound")
            return True
        shortcuts = dbus.Array(
            [
                dbus.Struct(
                    (
                        dbus.String(action),
                        dbus.Dictionary(
                            {"description": dbus.String(friendly)}, signature="sv"
                        ),
                    ),
                    signature="(sa{sv})",
                )
                for action, friendly in missing
            ],
            signature="(sa{sv})",
        )
        log.info("portal: asking for %d shortcut(s)", len(missing))
        self._request(
            "BindShortcuts",
            "oa(sa{sv})sa{sv}",
            [self.session, shortcuts, ""],
            self._on_bind,
            timeout=None,
        )
        return True

    def _on_bind(self, code: int, results: dict) -> None:
        if code == RESPONSE_CANCELLED:
            log.info("portal: the binding dialog was cancelled")
            return
        if code != RESPONSE_OK:
            self.error = f"the portal refused the bindings (response {code})"
            log.warning("portal: %s", self.error)
            return
        for shortcut in results.get("shortcuts", []):
            self.bound.add(str(shortcut[0]))
        log.info("portal: bound shortcuts: %s", ", ".join(sorted(self.bound)))

    def _activated(self, session, shortcut_id, _timestamp, _options) -> None:
        if self.session and str(session) != self.session:
            return
        log.debug("portal: shortcut %s pressed", shortcut_id)
        self.on_pressed(str(shortcut_id))
