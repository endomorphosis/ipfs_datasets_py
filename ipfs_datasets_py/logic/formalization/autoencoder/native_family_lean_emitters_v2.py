"""Versioned owner dispatch; unsupported semantics never fall back to JSON."""
from . import native_family_lean_emitters as previous
from . import native_program_lean, native_intent_lean, native_ui_lean, native_tla_projection

PRELUDE = previous.PRELUDE
UnsupportedNativeLean = previous.UnsupportedNativeLean
PRODUCERS = (previous, native_program_lean, native_intent_lean, native_ui_lean, native_tla_projection)


def emit_projection(row, *, report=None):
    for producer in PRODUCERS[1:]:
        try:
            return producer.emit_projection(row, report=report)
        except NotImplementedError:
            continue
    return previous.emit_projection(row)
