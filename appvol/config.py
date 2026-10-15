"""Configuration loading for appvol.

The configuration lives in ``~/.config/appvol/config.toml``.  A missing file
means defaults, a malformed value means defaults for that single key.
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
    ``profile_idle_timeout`` is the number of seconds a profile may stay idle
    before the keys return to the Active profile (0 disables the return), and
    ``kwin_script`` optionally overrides the bundled KWin script location.
    """

    step: float = DEFAULT_STEP
    max_volume: float = DEFAULT_MAX_VOLUME
    osd: bool = True
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
