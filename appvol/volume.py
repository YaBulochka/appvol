"""Volume math.

Everything here is a pure function over normalised channel values, where
``0.0`` is silence and ``1.0`` is 100 %.  The daemon converts the results into
``pulsectl`` objects.
"""

from __future__ import annotations

from typing import Sequence

UP = "up"
DOWN = "down"
DIRECTIONS = (UP, DOWN)

EPSILON = 1e-9


def peak(channels: Sequence[float]) -> float:
    """Loudest channel of a stream, the value the OSD reports."""
    return max(channels) if channels else 0.0


def percent(channels: Sequence[float]) -> int:
    """Peak channel as a rounded percentage."""
    return int(round(peak(channels) * 100))


def target_channels(
    channels: Sequence[float],
    direction: str,
    step: float,
    max_volume: float,
) -> list[float]:
    """Apply one relative step to every channel, preserving the balance.

    The peak channel moves by ``step`` and all other channels are scaled by the
    same factor, so a non-zero balance (a stream panned to one side) survives
    the change.  The result never leaves ``0..max_volume``.
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction {direction!r}")

    values = [float(value) for value in channels]
    if not values:
        return values

    step = max(0.0, float(step))
    max_volume = max(0.0, float(max_volume))
    current = peak(values)

    if direction == UP:
        target = min(current + step, max_volume)
    else:
        target = max(current - step, 0.0)

    if current <= 0.0:
        # All channels are silent, scaling is undefined; lift them evenly.
        level = target if direction == UP else 0.0
        return [min(level, max_volume)] * len(values)

    scale = target / current
    return [min(value * scale, max_volume) for value in values]


def absolute(
    channels: Sequence[float],
    value: float,
    max_volume: float,
) -> list[float]:
    """Move the peak channel to ``value``, preserving the balance.

    Absolute counterpart of :func:`target_channels`, used by the GUI sliders and
    the ``SetVolume`` call.  Silent channels carry no balance to preserve, so they
    are lifted evenly.
    """
    values = [float(channel) for channel in channels]
    if not values:
        return values

    ceiling = max(0.0, float(max_volume))
    target = min(max(0.0, float(value)), ceiling)
    current = peak(values)

    if current <= 0.0:
        return [target] * len(values)

    scale = target / current
    return [min(channel * scale, ceiling) for channel in values]


def changed(old: Sequence[float], new: Sequence[float]) -> bool:
    """True when two channel lists differ by more than a rounding epsilon."""
    if len(old) != len(new):
        return True
    return any(abs(a - b) > EPSILON for a, b in zip(old, new))
