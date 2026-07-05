"""TLA+ compiler stub for the exchange security IR."""

from __future__ import annotations

from ..ir.schema import SecurityModelIR, validate_ir


def emit_tla_model(model: SecurityModelIR) -> str:
    validate_ir(model)
    return """---- MODULE CryptoExchangeSecurity ----
\\* TODO: translate the canonical security IR into a TLA+ spec.
\\* This stub only emits a deterministic placeholder and does not claim proof support.
====
"""
