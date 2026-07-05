"""ProVerif runner stub."""

from __future__ import annotations

from ..claims.base import SecurityClaim
from ..compilers.to_proverif import emit_proverif_model
from ..ir.schema import SecurityModelIR
from ..runners.base import BaseSecurityRunner


class ProVerifRunner(BaseSecurityRunner):
    prover_name = 'proverif'

    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR):
        _ = emit_proverif_model(model)
        return self.unknown_report(claim, model, 'ProVerif runner stub: protocol proof execution is not implemented yet')
