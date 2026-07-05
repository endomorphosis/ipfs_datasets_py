"""HyperLTL runner stub."""

from __future__ import annotations

from ..claims.base import SecurityClaim
from ..compilers.to_hyperltl import emit_hyperltl_model
from ..ir.schema import SecurityModelIR
from ..runners.base import BaseSecurityRunner


class HyperLTLRunner(BaseSecurityRunner):
    prover_name = 'hyperltl'

    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR):
        _ = emit_hyperltl_model(model)
        return self.unknown_report(claim, model, 'HyperLTL runner stub: external hyperproperty checking is pending')
