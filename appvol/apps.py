"""Grouping sink inputs into applications, for the profile editor.

PipeWire hands out one sink input per stream: Spotify usually owns one, Firefox
one per playing tab.  A profile selects applications, so the editor needs the
other view, and ``appvol apps`` prints it.

Nothing here touches PipeWire or the filesystem: the daemon adapts ``pulsectl``
objects into :class:`~appvol.match.Stream` values and calls
:func:`group_streams`, so the grouping is unit tested like the matcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .focus import desktop_file_stem
from .match import STREAM_NAME_KEYS, Stream, stream_name_variants, stream_label
from .profiles import MODE_STREAMS, Profile, is_panel_stream
from .volume import peak


# The id of an auto-mode target carries this prefix, so an application can never
# be taken for the built-in ``active`` profile or for one of ``profiles.toml``.
APP_TARGET_PREFIX = "app-"


@dataclass(frozen=True)
class Application:
    """One application as the editor sees it: identity, label and its streams."""

    key: str
    label: str
    variants: frozenset[str]
    indices: tuple[int, ...]
    percent: int = 0
    muted: bool = False
    panel: bool = False

    def summary(self) -> dict:
        return {
            "id": self.key,
            "label": self.label,
            "variants": sorted(self.variants),
            "streams": list(self.indices),
            "percent": self.percent,
            "muted": self.muted,
            "panel": self.panel,
        }


def identity(stream: Stream) -> str:
    """Stable identifier of the application behind a stream.

    The first identifier PipeWire reports, normalised the same way the matcher
    normalises names, so it can be written into a profile unchanged.  A stream
    without any identifier falls back to its index, which keeps it selectable.
    """
    for key in STREAM_NAME_KEYS:
        text = desktop_file_stem(stream.props.get(key))
        if text:
            return text
    return f"stream-{stream.index}"


def label_of(stream: Stream) -> str:
    """Human name: ``application.name`` first, then the generated stream label."""
    name = str(stream.props.get("application.name") or "").strip()
    return name or stream_label(stream.index, stream.props)


def group_streams(streams: Iterable[Stream]) -> tuple[Application, ...]:
    """Group sink inputs by application, in the order the editor shows them.

    Streams that share an identifier belong to one application: PipeWire may
    report ``application.name`` on one stream and ``application.id`` on the next,
    and the matcher compares the same identifier sets, so merging on a shared
    variant keeps the editor and the matcher in agreement.

    The percent is the loudest stream of the group, the number the OSD shows, and
    the mute flag follows the aggregate rule of ``mute``: an application counts
    as muted only when every one of its streams is.  The shell sorts last, because
    a profile rarely targets it.
    """
    ordered = list(streams)
    variants = [stream_name_variants(stream) for stream in ordered]

    parent = list(range(len(ordered)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for first in range(len(ordered)):
        for second in range(first + 1, len(ordered)):
            if variants[first] & variants[second]:
                parent[root(second)] = root(first)

    groups: dict[int, list[Stream]] = {}
    for index, stream in enumerate(ordered):
        groups.setdefault(root(index), []).append(stream)

    applications: list[Application] = []
    for members in groups.values():
        identifiers = [identity(stream) for stream in members]
        merged: set[str] = set()
        for stream in members:
            merged |= stream_name_variants(stream)
        applications.append(
            Application(
                key=min(identifiers, key=len),
                label=label_of(members[0]),
                variants=frozenset(merged),
                indices=tuple(stream.index for stream in members),
                percent=int(round(max(peak(stream.volume) for stream in members) * 100)),
                muted=all(stream.mute for stream in members),
                panel=any(is_panel_stream(stream) for stream in members),
            )
        )

    applications.sort(key=lambda application: (application.panel, application.label.casefold()))
    return tuple(applications)


def application_profile(application: Application) -> Profile:
    """A target that follows one application, for the auto mode.

    ``include`` carries every identifier variant of the group, which is exactly
    what the matcher compares, so the target selects the streams of that
    application and of no other.  The step and the ceiling stay global: the auto
    mode keeps no per-application settings, so there is no file to write them to.
    """
    return Profile(
        id=f"{APP_TARGET_PREFIX}{application.key}",
        name=application.label,
        mode=MODE_STREAMS,
        include=tuple(sorted(application.variants)),
    )


def in_appearance_order(applications: Iterable[Application]) -> tuple[Application, ...]:
    """Applications ordered by their first stream, which is when they appeared.

    PipeWire numbers sink inputs as it creates them, so the smallest index of a
    group is the stream that started it.  Sorting by it puts the applications in
    the order the user started them, and one that stopped and played again moves
    to the end of the cycle.
    """
    return tuple(sorted(applications, key=lambda application: min(application.indices)))
