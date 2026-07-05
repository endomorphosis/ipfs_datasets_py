"""Coq runner stub."""

from __future__ import annotations

from ..claims.base import SecurityClaim
from ..compilers.to_coq import emit_coq_model
from ..ir.schema import SecurityModelIR
from ..runners.base import BaseSecurityRunner


class CoqRunner(BaseSecurityRunner):
    prover_name = 'coq'

    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR):
        _ = emit_coq_model(model)
        return self.unknown_report(claim, model, 'Coq runner stub: proof kernel integration is future work')
