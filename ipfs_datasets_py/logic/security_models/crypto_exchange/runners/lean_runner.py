"""Lean runner stub."""

from __future__ import annotations

from ..claims.base import SecurityClaim
from ..compilers.to_lean import emit_lean_model
from ..ir.schema import SecurityModelIR
from ..runners.base import BaseSecurityRunner


class LeanRunner(BaseSecurityRunner):
    prover_name = 'lean'

    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR):
        _ = emit_lean_model(model)
        return self.unknown_report(claim, model, 'Lean runner stub: proof checking integration is future work')
