"""Guarded Intent dispatch; unknown or failed semantics cannot fall through."""
from . import native_family_lean_emitters_v3 as previous
from . import native_intent_guarded_lean as guarded

PRELUDE = previous.PRELUDE
UnsupportedNativeLean = previous.UnsupportedNativeLean
PRODUCERS = (*previous.PRODUCERS, guarded)


def emit_projection(row, *, report=None):
    try:
        return guarded.emit_projection(row, report=report)
    except NotImplementedError:
        return previous.emit_projection(row, report=report)
