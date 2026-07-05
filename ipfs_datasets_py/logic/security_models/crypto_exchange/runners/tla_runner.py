"""TLA+ runner stub."""

from __future__ import annotations

from ..claims.base import SecurityClaim
from ..compilers.to_tla import emit_tla_model
from ..ir.schema import SecurityModelIR
from ..runners.base import BaseSecurityRunner


class TLARunner(BaseSecurityRunner):
    prover_name = 'tla'

    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR):
        _ = emit_tla_model(model)
        return self.unknown_report(claim, model, 'TLA+ runner stub: external model checking is not implemented yet')
