"""Datalog runner stub."""

from __future__ import annotations

from ..claims.base import SecurityClaim
from ..compilers.to_datalog import emit_datalog_model
from ..ir.schema import SecurityModelIR
from ..runners.base import BaseSecurityRunner


class DatalogRunner(BaseSecurityRunner):
    prover_name = 'datalog'

    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR):
        _ = emit_datalog_model(model)
        return self.unknown_report(claim, model, 'Datalog runner stub: authorization engine integration is pending')
