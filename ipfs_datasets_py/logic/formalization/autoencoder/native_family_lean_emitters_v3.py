"""Additive native semantic dispatch; unsupported owners cannot fall through."""
from . import native_family_lean_emitters_v2 as previous
from . import native_security_lean, native_intent_semantic_lean, native_qualified_lean

PRELUDE = previous.PRELUDE
UnsupportedNativeLean = previous.UnsupportedNativeLean
ADDITIONS = (native_security_lean, native_intent_semantic_lean, native_qualified_lean)
PRODUCERS = (*previous.PRODUCERS, *ADDITIONS)


def emit_projection(row, *, report=None):
    for module in ADDITIONS:
        try:
            return module.emit_projection(row, report=report)
        except NotImplementedError:
            continue
    return previous.emit_projection(row, report=report)
