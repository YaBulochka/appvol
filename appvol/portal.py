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
from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_IFACE = "org.freedesktop.portal.GlobalShortcuts"
SESSION_IFACE = "org.freedesktop.portal.Session"
REGISTRY_IFACE = "org.freedesktop.host.portal.Registry"
REQUEST_IFACE = "org.freedesktop.portal.Request"

# The application id of the daemon in the portal.  It must match the basename of
# a .desktop file, which is why desktop/org.appvol.Daemon.desktop exists; the
# portal keys the bindings of the global shortcuts by it.
APP_ID = "org.appvol.Daemon"

# Where gnome-control-center keeps the shortcuts it bound for an application.
# A new session starts unbound and grabs nothing until BindShortcuts is called,
# and the portal refuses it once the session is bound; reading the store is how
# appvol knows which ids it may claim silently and which need the dialog.
APP_SETTINGS_SCHEMA = "org.gnome.settings-daemon.global-shortcuts.application"
APP_SETTINGS_PATH = f"/org/gnome/settings-daemon/global-shortcuts/{APP_ID}/"

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
        # Whether BindShortcuts was sent for the current session: the portal
        # refuses a second one, and ConfigureShortcuts is the way after that.
        self._bound = False
        self._claim_on_open = True

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

    def _open_session(self, claim: bool = True) -> None:
        # ``claim`` takes over the bindings the portal already stores, without a
        # dialog.  ``session_handle_token`` is required: without it
        # xdg-desktop-portal takes its own NULL-token assert and crashes.
        self._claim_on_open = claim
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
        if self._claim_on_open:
            self._claim()

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

    def _stored_ids(self) -> set[str]:
        """The ids gnome-control-center already stores for this application.

        A stored id is one the user has seen in a dialog, even if the row was
        left without a key; an id that is not here has never been offered.
        """
        try:
            settings = Gio.Settings.new_with_path(APP_SETTINGS_SCHEMA, APP_SETTINGS_PATH)
            value = settings.get_value("shortcuts")
        except (GLib.Error, TypeError, AttributeError):
            return set()
        ids = set()
        for item in value:
            # PyGObject unpacks each (sa{sv}) element into a Python tuple.
            try:
                shortcut_id = item[0]
            except (IndexError, TypeError):
                continue
            ids.add(str(shortcut_id))
        return ids

    def _claim(self) -> None:
        """Grab the bindings the portal already stores, without a dialog.

        A session starts unbound and the backend grabs nothing until
        BindShortcuts is called, so without this every key would be dead after a
        restart of the daemon.  Only known ids are passed: an unknown one makes
        the provider open its dialog.
        """
        stored = self._stored_ids()
        known = [(action, friendly) for action, friendly in self._actions() if action in stored]
        if not known:
            log.debug("portal: nothing stored to claim yet")
            return
        log.debug("portal: claiming %s", ", ".join(action for action, _ in known))
        self._bind_actions(known)

    def _bind_actions(self, actions: Sequence[tuple[str, str]], timeout: int | None = None) -> None:
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
                for action, friendly in actions
            ],
            signature="(sa{sv})",
        )
        self._bound = True
        self._request(
            "BindShortcuts",
            "oa(sa{sv})sa{sv}",
            [self.session, shortcuts, ""],
            self._on_bind,
            timeout=timeout,
        )

    def _reopen(self, claim: bool) -> None:
        """Close the session and open a fresh one: a session binds only once."""
        self._close_session()
        self.session = ""
        self.bound = set()
        self._bound = False
        self._open_session(claim=claim)

    def _close_session(self) -> None:
        if not self.session:
            return
        try:
            session = dbus.Interface(
                self.bus.get_object(PORTAL_SERVICE, self.session), SESSION_IFACE
            )
            session.Close(dbus_interface=SESSION_IFACE, signature="")
        except dbus.DBusException as exc:
            log.debug("portal: cannot close the session: %s", exc.get_dbus_message())

    def bind(self) -> bool:
        """Open the dialog that gives the actions their keys.

        The portal accepts one BindShortcuts per session and nothing else, and
        the provider skips the dialog when every id it is offered is already
        stored.  So a new action, a profile added since the last time, starts a
        fresh session, while a session that already knows every action edits the
        stored bindings through ConfigureShortcuts: that is also the only way to
        fill a row the user left empty.
        """
        if not self.session:
            self.error = "no portal session; global shortcuts are not available here"
            return False
        stored = self._stored_ids()
        unknown = [action for action, _ in self._actions() if action not in stored]
        if unknown and self._bound:
            log.info("portal: %d new shortcut(s), opening a fresh session", len(unknown))
            self._reopen(claim=False)
            return True
        if self._bound:
            log.info("portal: asking the desktop to configure the shortcuts")
            self._request(
                "ConfigureShortcuts",
                "osa{sv}",
                [self.session, ""],
                self._on_configure,
                timeout=None,
            )
            return True
        self._bind_actions(self._actions())
        return True

    def _on_bind(self, code: int, results: dict) -> None:
        if code == RESPONSE_CANCELLED:
            log.info("portal: the binding dialog was cancelled")
            # The session that asked is marked bound and grabs nothing, so come
            # back with the bindings that were stored before the dialog.
            self._reopen(claim=True)
            return
        if code != RESPONSE_OK:
            self.error = f"the portal refused the bindings (response {code})"
            log.warning("portal: %s", self.error)
            return
        for shortcut in results.get("shortcuts", []):
            self.bound.add(str(shortcut[0]))
        log.info("portal: bound shortcuts: %s", ", ".join(sorted(self.bound)))

    def _on_configure(self, code: int, results: dict) -> None:
        if code == RESPONSE_CANCELLED:
            log.info("portal: the configuration dialog was cancelled")
            return
        if code != RESPONSE_OK:
            self.error = f"the portal refused the configuration (response {code})"
            log.warning("portal: %s", self.error)
            return
        log.info("portal: shortcuts configured")
        self.refresh()

    def _activated(self, session, shortcut_id, _timestamp, _options) -> None:
        if self.session and str(session) != self.session:
            return
        log.debug("portal: shortcut %s pressed", shortcut_id)
        self.on_pressed(str(shortcut_id))
