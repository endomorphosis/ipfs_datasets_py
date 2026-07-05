"""Tamarin runner stub."""

from __future__ import annotations

from ..claims.base import SecurityClaim
from ..compilers.to_tamarin import emit_tamarin_model
from ..ir.schema import SecurityModelIR
from ..runners.base import BaseSecurityRunner


class TamarinRunner(BaseSecurityRunner):
    prover_name = 'tamarin'

    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR):
        _ = emit_tamarin_model(model)
        return self.unknown_report(claim, model, 'Tamarin runner stub: cryptographic protocol execution is not implemented yet')
