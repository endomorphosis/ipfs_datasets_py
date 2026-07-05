"""Datalog compiler stub for the exchange security IR."""

from __future__ import annotations

from ..ir.schema import SecurityModelIR, validate_ir


def emit_datalog_model(model: SecurityModelIR) -> str:
    validate_ir(model)
    return "% TODO: emit authorization and delegation facts from SecurityModelIR.\n% This placeholder is deterministic and must not be treated as a proof artifact.\n"
