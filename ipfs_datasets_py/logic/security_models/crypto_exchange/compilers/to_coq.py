"""Coq compiler stub for the exchange security IR."""

from __future__ import annotations

from ..ir.schema import SecurityModelIR, validate_ir


def emit_coq_model(model: SecurityModelIR) -> str:
    validate_ir(model)
    return "(* TODO: emit Coq definitions and theorem statements from SecurityModelIR. *)\n(* Placeholder only; unsupported output must never be treated as PROVED. *)\n"
