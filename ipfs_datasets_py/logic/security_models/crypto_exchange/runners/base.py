"""Base runner contracts for exchange security provers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..claims.base import SecurityClaim
from ..ir.cid import calculate_model_cid
from ..ir.schema import SecurityModelIR
from ..reports.proof_report import ProofReport


class BaseSecurityRunner(ABC):
    """Base class for prover runners."""

    prover_name = 'unknown'

    @abstractmethod
    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR) -> ProofReport:
        """Run *claim* against *model* and return a proof report."""

    def unknown_report(self, claim: SecurityClaim, model: SecurityModelIR, reason: str) -> ProofReport:
        return ProofReport(
            claim_id=claim.claim_id,
            claim_version=claim.claim_version,
            model_cid=calculate_model_cid(model),
            model_schema_version=model.schema_version,
            status='UNKNOWN',
            prover=self.prover_name,
            solver_name=self.prover_name,
            solver_result='unknown',
            reason_unknown=reason,
            proof_or_trace_cid='',
            assumptions=list(claim.required_assumptions),
            compiler_cid='',
            counterexample={'reason': reason},
            risk=claim.severity,
            signatures=[],
        )
