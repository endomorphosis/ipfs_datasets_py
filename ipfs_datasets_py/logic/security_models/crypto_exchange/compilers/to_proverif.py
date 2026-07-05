"""ProVerif compiler stub for the exchange security IR."""

from __future__ import annotations

from ..ir.schema import SecurityModelIR, validate_ir


def emit_proverif_model(model: SecurityModelIR) -> str:
    validate_ir(model)
    return (
        "(* TODO: translate signing, revocation, and protocol assumptions into ProVerif. *)\n"
        "(* Placeholder only; unsupported output must never be treated as a proof result. *)\n"
    )
