"""Profiles: named targets for the volume keys.

The keys used to act on one thing only, the audio streams of the focused window.
A profile names another target, so a key can move the volume of an application
without focusing its window.

``mode = "focus"`` keeps the original behaviour.  It is the built-in ``active``
profile, the target the keys use while no profile is switched on.  ``mode =
"streams"`` selects streams by application identifier: ``include`` lists the
applications, and an empty ``include`` means every application stream with the
shell left out.  ``exclude`` removes applications from the set, which is how
"everything but the game" is spelled.

``~/.config/appvol/profiles.toml`` holds the profiles.  The daemon is the only
writer; the CLI and a future GUI go through its D-Bus API.
"""

from __future__ import annotations

import logging
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .config import HARD_MAX_VOLUME
from .focus import PANEL_DESKTOP_FILES, PANEL_RESOURCE_CLASSES
from .match import MatchResult, Stream, name_variants, stream_name_variants

log = logging.getLogger(__name__)

ACTIVE_ID = "active"
ACTIVE_NAME = "Active window"

MODE_FOCUS = "focus"
MODE_STREAMS = "streams"
MODES = (MODE_FOCUS, MODE_STREAMS)

OSD_NAME_AUTO = "auto"
OSD_NAME_ALWAYS = "always"
OSD_NAME_NEVER = "never"
OSD_NAMES = (OSD_NAME_AUTO, OSD_NAME_ALWAYS, OSD_NAME_NEVER)

# The match step reported for a stream profile, next to pid/descendant/name.
STEP_PROFILE = "profile"

ACTION_PREFIX = "profile_"

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")

# Streams that belong to the session, not to an application.  The set filters
# the implicit "every application stream"; an explicit `include` still reaches
# them.
PANEL_STREAM_NAMES = frozenset(
    {
        "bell-window-system",
        "event sounds",
        "kded",
        "kwin",
        "kwin_wayland",
        "notification sounds",
        "plasma",
        "plasmashell",
        "system sounds",
    }
)

HEADER = "# appvol profiles.  Written by appvold, edited with `appvol profile`.\n"


@dataclass(frozen=True)
class Profile:
    """A named target for the volume keys.

    ``step`` and ``max_volume`` are percentages; ``None`` means "whatever the
    global configuration says".
    """

    id: str
    name: str = ""
    mode: str = MODE_STREAMS
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    step: float | None = None
    max_volume: float | None = None
    icon: str = ""
    osd_name: str = OSD_NAME_AUTO

    @property
    def display_name(self) -> str:
        return self.name or self.id

    @property
    def shows_name(self) -> bool:
        """Whether the OSD should caption the volume bar with the name."""
        if self.osd_name == OSD_NAME_ALWAYS:
            return True
        if self.osd_name == OSD_NAME_NEVER:
            return False
        return self.mode != MODE_FOCUS

    def summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.display_name,
            "mode": self.mode,
            "include": list(self.include),
            "exclude": list(self.exclude),
            "step": self.step,
            "max_volume": self.max_volume,
            "icon": self.icon,
            "osd_name": self.osd_name,
        }


def active_profile() -> Profile:
    """The built-in profile: the streams of the focused window."""
    return Profile(id=ACTIVE_ID, name=ACTIVE_NAME, mode=MODE_FOCUS)


def default_path() -> Path:
    """Return the profile path, honouring ``XDG_CONFIG_HOME``."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "appvol" / "profiles.toml"


def validate_id(value: object) -> str:
    """Return a usable profile id, or raise :class:`ValueError`."""
    text = str(value or "").strip().lower()
    if not ID_PATTERN.match(text):
        raise ValueError(
            f"invalid profile id {value!r}: use lowercase letters, digits, dot, "
            "dash or underscore, at most 40 characters"
        )
    if text == ACTIVE_ID:
        raise ValueError(f"{ACTIVE_ID!r} is the built-in profile, choose another id")
    return text


def action_name(profile_id: str) -> str:
    """Name of the KGlobalAccel action that toggles a profile."""
    return f"{ACTION_PREFIX}{profile_id}"


def profile_from_action(action: str) -> str:
    """Profile id behind an action name, or ``""`` for a foreign action."""
    text = str(action)
    if not text.startswith(ACTION_PREFIX):
        return ""
    return text[len(ACTION_PREFIX) :]


def find(profiles: Iterable[Profile], profile_id: str) -> Profile | None:
    """Return the profile with that id, or ``None``."""
    for profile in profiles:
        if profile.id == profile_id:
            return profile
    return None


def is_panel_stream(stream: Stream) -> bool:
    """True for streams of the shell rather than of an application."""
    variants = stream_name_variants(stream)
    return bool(variants & (PANEL_RESOURCE_CLASSES | PANEL_DESKTOP_FILES | PANEL_STREAM_NAMES))


def match_profile(profile: Profile, streams: Iterable[Stream]) -> MatchResult:
    """Return the streams a stream profile selects.

    Only ``mode = "streams"`` reaches this function; the daemon matches the
    focus profile through :func:`appvol.match.match_streams`.
    """
    ordered = list(streams)
    wanted = _variants(profile.include)
    if wanted:
        selected = [stream for stream in ordered if stream_name_variants(stream) & wanted]
        source = f"include {', '.join(sorted(wanted))}"
    else:
        selected = [stream for stream in ordered if not is_panel_stream(stream)]
        source = "every application stream"

    unwanted = _variants(profile.exclude)
    if unwanted:
        selected = [stream for stream in selected if not stream_name_variants(stream) & unwanted]

    if selected:
        detail = source
        if unwanted:
            detail += f", without {', '.join(sorted(unwanted))}"
        return MatchResult(
            indices=tuple(stream.index for stream in selected),
            step=STEP_PROFILE,
            reason=f"{len(selected)} stream(s) of {detail}",
        )
    if not ordered:
        return MatchResult(reason=f"no audio stream is playing (profile {profile.id!r})")
    return MatchResult(reason=f"no stream matched profile {profile.id!r} ({source})")


def _variants(values: Sequence[str]) -> set[str]:
    variants: set[str] = set()
    for value in values:
        variants |= name_variants(value)
    return variants


@dataclass
class ProfileSelection:
    """Which profile the keys act on, and when it was last used."""

    current: str = ACTIVE_ID
    last_use: float = 0.0

    def use(self, now: float) -> None:
        self.last_use = now

    def select(self, profile_id: str, now: float) -> str:
        """Make ``profile_id`` current; the explicit form of :meth:`toggle`."""
        self.current = profile_id
        self.last_use = now
        return self.current

    def toggle(self, profile_id: str, now: float) -> str:
        """Switch to ``profile_id``, or back to Active when it is current."""
        self.current = ACTIVE_ID if self.current == profile_id else profile_id
        self.last_use = now
        return self.current

    def expire(self, now: float, timeout: float) -> bool:
        """Return True when a timeout moved the selection back to Active."""
        if self.current == ACTIVE_ID or timeout <= 0:
            return False
        if now - self.last_use < timeout:
            return False
        log.info("profile %s idle for %.0fs, back to %s", self.current, timeout, ACTIVE_ID)
        self.current = ACTIVE_ID
        return True


# --------------------------------------------------------------------------- #
# profiles.toml
# --------------------------------------------------------------------------- #


def parse(text: str) -> list[Profile]:
    """Build profiles from TOML text, skipping entries that make no sense."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        log.warning("profiles: cannot parse TOML (%s), ignoring the file", exc)
        return []

    entries = data.get("profile", [])
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        log.warning("profiles: [[profile]] must be a list of tables, ignoring the file")
        return []

    profiles: list[Profile] = []
    for index, entry in enumerate(entries):
        profile = _parse_profile(entry, index)
        if profile is None:
            continue
        if find(profiles, profile.id) is not None:
            log.warning("profiles: duplicate id %r, keeping the first entry", profile.id)
            continue
        profiles.append(profile)
    return profiles


def _parse_profile(entry: object, index: int) -> Profile | None:
    if not isinstance(entry, dict):
        log.warning("profiles: entry %d is not a table, skipping it", index)
        return None

    try:
        profile_id = validate_id(entry.get("id"))
    except ValueError as exc:
        log.warning("profiles: entry %d: %s", index, exc)
        return None

    mode = _as_choice(entry.get("mode"), MODES, MODE_STREAMS, profile_id, "mode")
    osd_name = _as_choice(entry.get("osd_name"), OSD_NAMES, OSD_NAME_AUTO, profile_id, "osd_name")
    name = entry.get("name")
    icon = entry.get("icon")
    return Profile(
        id=profile_id,
        name=str(name).strip() if isinstance(name, str) else "",
        mode=mode,
        include=_as_names(entry.get("include"), profile_id, "include"),
        exclude=_as_names(entry.get("exclude"), profile_id, "exclude"),
        step=_as_optional_float(entry.get("step"), profile_id, "step"),
        max_volume=_as_optional_float(entry.get("max_volume"), profile_id, "max_volume"),
        icon=str(icon).strip() if isinstance(icon, str) else "",
        osd_name=osd_name,
    )


def _as_choice(
    value: object, choices: Sequence[str], fallback: str, profile_id: str, key: str
) -> str:
    if value is None:
        return fallback
    text = str(value).strip().lower()
    if text not in choices:
        log.warning(
            "profiles: %s: %s %r is not one of %s, using %r",
            profile_id,
            key,
            value,
            ", ".join(choices),
            fallback,
        )
        return fallback
    return text


def _as_names(value: object, profile_id: str, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        log.warning("profiles: %s: %s must be a list of strings, ignoring it", profile_id, key)
        return ()
    names: list[str] = []
    for item in value:
        if not isinstance(item, str):
            log.warning(
                "profiles: %s: %s entry %r is not a string, skipping it", profile_id, key, item
            )
            continue
        text = item.strip()
        if text:
            names.append(text)
    return tuple(names)


def _as_optional_float(value: object, profile_id: str, key: str) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.warning("profiles: %s: %s %r is not a number, ignoring it", profile_id, key, value)
        return None
    if number <= 0:
        log.warning("profiles: %s: %s %s is not positive, ignoring it", profile_id, key, number)
        return None
    if key == "max_volume" and number > HARD_MAX_VOLUME:
        log.warning("profiles: %s: max_volume %s clamped to %s", profile_id, number, HARD_MAX_VOLUME)
        number = HARD_MAX_VOLUME
    return number


def dumps(profiles: Iterable[Profile]) -> str:
    """Render profiles as TOML text."""
    blocks = "".join(_dump_profile(profile) for profile in profiles)
    return HEADER + blocks


def _dump_profile(profile: Profile) -> str:
    lines = ["[[profile]]", f"id = {_quote(profile.id)}"]
    if profile.name:
        lines.append(f"name = {_quote(profile.name)}")
    lines.append(f"mode = {_quote(profile.mode)}")
    lines.append(f"include = {_quote_list(profile.include)}")
    if profile.exclude:
        lines.append(f"exclude = {_quote_list(profile.exclude)}")
    if profile.step is not None:
        lines.append(f"step = {profile.step:g}")
    if profile.max_volume is not None:
        lines.append(f"max_volume = {profile.max_volume:g}")
    if profile.icon:
        lines.append(f"icon = {_quote(profile.icon)}")
    if profile.osd_name != OSD_NAME_AUTO:
        lines.append(f"osd_name = {_quote(profile.osd_name)}")
    return "\n".join(lines) + "\n"


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    # TOML basic strings cannot hold control characters; profile names never
    # need them, so a replacement keeps the file parseable.
    escaped = "".join("?" if ch < " " or ch == "\x7f" else ch for ch in escaped)
    return f'"{escaped}"'


def _quote_list(values: Sequence[str]) -> str:
    return "[" + ", ".join(_quote(value) for value in values) + "]"


def load(path: Path | None = None) -> list[Profile]:
    """Load the profiles, returning an empty list when the file is absent."""
    path = path or default_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        log.warning("profiles: cannot read %s (%s), ignoring the file", path, exc)
        return []
    return parse(text)


def save(profiles: Iterable[Profile], path: Path | None = None) -> Path:
    """Write the profiles, replacing the file in one step."""
    path = Path(path) if path else default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(dumps(profiles), encoding="utf-8")
    os.replace(temporary, path)
    return path
