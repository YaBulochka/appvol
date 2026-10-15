"""Pure matching of a focused window to audio streams (sink inputs).

The daemon adapts ``pulsectl`` objects into :class:`Stream` values and calls
:func:`match_streams`.  Nothing in this module touches D-Bus, PipeWire or the
filesystem, so matching is easy to unit test.

The matcher tries three steps and stops at the first one that yields a result:

1. ``pid`` — the stream reports ``application.process.id`` of the window.
2. ``descendant`` — the stream pid is a descendant of the window pid.
3. ``name`` — an application identifier of the window equals an identifier of
   the stream (case-insensitive, ``org.mozilla.firefox`` matches ``firefox``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping

from .focus import Focus, desktop_file_stem, is_descendant, parse_pid

STEP_PID = "pid"
STEP_DESCENDANT = "descendant"
STEP_NAME = "name"

# Stream properties compared in the name matching step, cheapest first.
STREAM_NAME_KEYS = (
    "pipewire.access.portal.app_id",
    "application.id",
    "application.process.binary",
    "application.name",
)


@dataclass(frozen=True)
class Stream:
    """A sink input, decoupled from ``pulsectl``.

    ``props`` holds the sink input properties merged with the properties of its
    PulseAudio client, because PipeWire puts ``application.process.id`` on the
    client for some applications (Spotify) and on the stream for others
    (Firefox).
    """

    index: int
    props: Mapping[str, str] = field(default_factory=dict)
    label: str = ""
    volume: tuple[float, ...] = ()
    mute: bool = False

    @property
    def pid(self) -> int:
        return parse_pid(self.props.get("application.process.id"))

    @property
    def display_name(self) -> str:
        if self.label:
            return self.label
        return stream_label(self.index, self.props)


@dataclass(frozen=True)
class MatchResult:
    """Outcome of :func:`match_streams`."""

    indices: tuple[int, ...] = ()
    step: str = ""
    reason: str = ""

    @property
    def matched(self) -> bool:
        return bool(self.indices)

    @property
    def count(self) -> int:
        return len(self.indices)


def stream_label(index: int, props: Mapping[str, str]) -> str:
    """Best effort human readable name of a stream."""
    for key in ("application.name", "node.name", "media.name", "application.process.binary", "application.id"):
        value = props.get(key)
        if value:
            return str(value)
    return f"stream {index}"


def name_variants(value: object) -> set[str]:
    """Return the identifiers a name can be matched by.

    ``"org.mozilla.firefox"`` yields both the full name and the ``firefox``
    suffix, so a window can be matched against a bare ``firefox`` binary.
    """
    stem = desktop_file_stem(value)
    if not stem:
        return set()
    variants = {stem}
    if "." in stem:
        tail = stem.rsplit(".", 1)[1]
        if tail:
            variants.add(tail)
    return variants


def focus_name_variants(focus: Focus) -> set[str]:
    """Identifiers advertised by the focused window."""
    variants: set[str] = set()
    for value in (focus.desktop_file_name, focus.resource_class):
        variants |= name_variants(value)
    return variants


def stream_name_variants(stream: Stream) -> set[str]:
    """Identifiers advertised by a stream."""
    variants: set[str] = set()
    for key in STREAM_NAME_KEYS:
        variants |= name_variants(stream.props.get(key))
    return variants


def match_streams(
    focus: Focus,
    streams: Iterable[Stream],
    parent_of: Callable[[int], int | None] | None = None,
) -> MatchResult:
    """Return the streams that belong to ``focus``.

    ``parent_of`` enables the process-tree step; pass ``None`` to compare pids
    only, which is what the unit tests do for the other two steps.
    """
    reason = focus.ignored_reason()
    if reason is not None:
        return MatchResult(reason=reason)

    ordered = list(streams)

    same_pid = [stream for stream in ordered if stream.pid and stream.pid == focus.pid]
    if same_pid:
        return MatchResult(
            indices=tuple(stream.index for stream in same_pid),
            step=STEP_PID,
            reason=f"streams owned by pid {focus.pid}",
        )

    if parent_of is not None:
        children = [
            stream
            for stream in ordered
            if stream.pid and is_descendant(stream.pid, focus.pid, parent_of)
        ]
        if children:
            return MatchResult(
                indices=tuple(stream.index for stream in children),
                step=STEP_DESCENDANT,
                reason=f"streams of processes descending from pid {focus.pid}",
            )

    wanted = focus_name_variants(focus)
    if wanted:
        named = [stream for stream in ordered if stream_name_variants(stream) & wanted]
        if named:
            return MatchResult(
                indices=tuple(stream.index for stream in named),
                step=STEP_NAME,
                reason=f"name match on {', '.join(sorted(wanted))}",
            )

    return MatchResult(reason=f"no stream matched {focus.label!r} (pid {focus.pid})")
