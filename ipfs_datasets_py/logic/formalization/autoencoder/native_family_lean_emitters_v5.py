"""Extended qualifier dispatch; failed owned semantics never fall through."""
from . import native_family_lean_emitters_v4 as previous
from . import native_legal_qualified_lean, native_ui_confirmation_lean

PRELUDE = previous.PRELUDE
UnsupportedNativeLean = previous.UnsupportedNativeLean
ADDITIONS = (native_legal_qualified_lean, native_ui_confirmation_lean)
PRODUCERS = (*previous.PRODUCERS, *ADDITIONS)


def emit_projection(row, *, report=None):
    for module in ADDITIONS:
        try:
            return module.emit_projection(row, report=report)
        except NotImplementedError:
            continue
    return previous.emit_projection(row, report=report)
