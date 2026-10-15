"""Configuration loading for appvol.

The configuration lives in ``~/.config/appvol/config.toml``.  A missing file
means defaults, a malformed value means defaults for that single key.  The
daemon writes the file only when the window changes the global step; every other
edit is the user's.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_STEP = 5.0
DEFAULT_MAX_VOLUME = 100.0
HARD_MAX_VOLUME = 150.0
DEFAULT_PROFILE_IDLE_TIMEOUT = 300.0


def default_path() -> Path:
    """Return the configuration path, honouring ``XDG_CONFIG_HOME``."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "appvol" / "config.toml"


@dataclass(frozen=True)
class Config:
    """Runtime configuration.

    ``step`` and ``max_volume`` are percentages, ``osd`` toggles the KDE OSD,
    ``osd_show_name`` decides whether the OSD captions the application name,
    ``profile_idle_timeout`` is the number of seconds a profile may stay idle
    before the keys return to the Active profile (0 disables the return), and
    ``kwin_script`` optionally overrides the bundled KWin script location.
    """

    step: float = DEFAULT_STEP
    max_volume: float = DEFAULT_MAX_VOLUME
    osd: bool = True
    osd_show_name: bool = False
    profile_idle_timeout: float = DEFAULT_PROFILE_IDLE_TIMEOUT
    kwin_script: str | None = None

    @property
    def step_fraction(self) -> float:
        return self.step / 100.0

    @property
    def max_volume_fraction(self) -> float:
        return self.max_volume / 100.0


def _as_float(value: object, fallback: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.warning("config: %r is not a number, using %s", value, fallback)
        return fallback


def _as_bool(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    log.warning("config: %r is not a boolean, using %s", value, fallback)
    return fallback


def parse(text: str) -> Config:
    """Build a :class:`Config` from TOML text."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        log.warning("config: cannot parse TOML (%s), using defaults", exc)
        return Config()

    config = Config()

    step = _as_float(data.get("step", config.step), config.step)
    if step <= 0:
        log.warning("config: step %s is not positive, using %s", step, config.step)
        step = config.step

    max_volume = _as_float(data.get("max_volume", config.max_volume), config.max_volume)
    if max_volume <= 0:
        log.warning("config: max_volume %s is not positive, using %s", max_volume, config.max_volume)
        max_volume = config.max_volume
    if max_volume > HARD_MAX_VOLUME:
        log.warning("config: max_volume %s clamped to %s", max_volume, HARD_MAX_VOLUME)
        max_volume = HARD_MAX_VOLUME

    script = data.get("kwin_script")
    if script is not None and not isinstance(script, str):
        log.warning("config: kwin_script is not a string, ignoring it")
        script = None

    timeout = _as_float(
        data.get("profile_idle_timeout", config.profile_idle_timeout), config.profile_idle_timeout
    )
    if timeout < 0:
        log.warning(
            "config: profile_idle_timeout %s is negative, disabling the return to Active", timeout
        )
        timeout = 0.0

    return replace(
        config,
        step=step,
        max_volume=max_volume,
        osd=_as_bool(data.get("osd", config.osd), config.osd),
        osd_show_name=_as_bool(data.get("osd_show_name", config.osd_show_name), config.osd_show_name),
        profile_idle_timeout=timeout,
        kwin_script=script,
    )


def load(path: Path | None = None) -> Config:
    """Load the configuration, returning defaults when the file is absent."""
    path = path or default_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config()
    except OSError as exc:
        log.warning("config: cannot read %s (%s), using defaults", path, exc)
        return Config()
    return parse(text)


HEADER = "# appvol configuration.  Written by appvold when the window changes the global step.\n"


def dumps(config: Config) -> str:
    """Render a configuration as TOML text, one key per line."""
    lines = [
        f"step = {config.step:g}",
        f"max_volume = {config.max_volume:g}",
        f"osd = {str(config.osd).lower()}",
        f"osd_show_name = {str(config.osd_show_name).lower()}",
        f"profile_idle_timeout = {config.profile_idle_timeout:g}",
    ]
    if config.kwin_script:
        lines.append(f"kwin_script = {_quote(config.kwin_script)}")
    return HEADER + "\n".join(lines) + "\n"


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    escaped = "".join("?" if ch < " " or ch == "\x7f" else ch for ch in escaped)
    return f'"{escaped}"'


def save(config: Config, path: Path | None = None) -> Path:
    """Write the configuration, replacing the file in one step.

    The file comes back in canonical form, so a comment of a hand edit does not
    survive a change made from the window.
    """
    path = Path(path) if path else default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(dumps(config), encoding="utf-8")
    os.replace(temporary, path)
    return path
