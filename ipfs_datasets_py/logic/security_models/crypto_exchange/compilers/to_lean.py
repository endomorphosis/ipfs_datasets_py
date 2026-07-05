"""Lean compiler stub for the exchange security IR."""

from __future__ import annotations

from ..ir.schema import SecurityModelIR, validate_ir


def emit_lean_model(model: SecurityModelIR) -> str:
    validate_ir(model)
    return "-- TODO: emit Lean theorem skeletons for the canonical security IR.\n-- This stub is deterministic and proof-checking support remains future work.\n"
