"""Explicit bounded UI event-calculus qualification; prior emitters stay pinned."""
from . import native_family_lean_emitters_v6 as previous
from . import native_ui_bounded_event_calculus as events

PRELUDE = previous.PRELUDE
UnsupportedNativeLean = previous.UnsupportedNativeLean
PRODUCERS = (*previous.PRODUCERS, events)


def emit_projection(row, *, report=None):
    try:
        return events.emit_projection(row, report=report)
    except NotImplementedError:
        return previous.emit_projection(row, report=report)


__all__ = ["emit_projection", "PRODUCERS", "PRELUDE", "UnsupportedNativeLean"]
