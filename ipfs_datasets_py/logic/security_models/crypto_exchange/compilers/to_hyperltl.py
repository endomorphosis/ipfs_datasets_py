"""HyperLTL compiler stub for the exchange security IR."""

from __future__ import annotations

from ..ir.schema import SecurityModelIR, validate_ir


def emit_hyperltl_model(model: SecurityModelIR) -> str:
    validate_ir(model)
    return "# TODO: encode information-flow and multi-trace capability properties in HyperLTL.\n# Placeholder only; no proof support is claimed.\n"
