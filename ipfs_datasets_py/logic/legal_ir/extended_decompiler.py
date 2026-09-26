"""Source-withheld candidate realizer for legal-surface-ir/v2.

Supervisor implementation target. Only the typed IR is an input; no source
lookup, caches, packet reading, or reconstruction from provenance is permitted.
"""
from __future__ import annotations

from .extended_contracts import ExtendedLegalIR


def decompile_extended(ir: ExtendedLegalIR) -> str:
    """Render every structured facet without changing statement kind."""
    if type(ir) is not ExtendedLegalIR:
        raise ValueError("typed extended IR required")
    raise NotImplementedError("extended source-withheld realizer is not implemented")
