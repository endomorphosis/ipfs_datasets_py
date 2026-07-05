"""Tamarin compiler stub for the exchange security IR."""

from __future__ import annotations

from ..ir.schema import SecurityModelIR, validate_ir


def emit_tamarin_model(model: SecurityModelIR) -> str:
    validate_ir(model)
    return "/* TODO: translate wallet signing and revocation flows into Tamarin rules. */\n/* This placeholder does not execute Tamarin or claim protocol verification. */\n"
