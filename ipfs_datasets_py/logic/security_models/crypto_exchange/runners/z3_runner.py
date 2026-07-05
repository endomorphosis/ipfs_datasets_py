"""Z3-backed proof runner for exchange security claims."""

from __future__ import annotations

import importlib.util
from typing import Any

from ..claims.base import SecurityClaim
from ..compilers.to_z3 import Z3Compilation
from ..ir.cid import calculate_model_cid
from ..ir.schema import SecurityModelIR
from ..reports.counterexample_report import CounterexampleReport
from ..reports.proof_report import ProofReport
from ..runners.base import BaseSecurityRunner


class Z3Runner(BaseSecurityRunner):
    """Evaluate supported claims with the Z3 Python bindings."""

    prover_name = 'z3'

    def __init__(self, timeout_ms: int = 5_000) -> None:
        self.timeout_ms = timeout_ms

    @staticmethod
    def is_available() -> bool:
        return importlib.util.find_spec('z3') is not None

    def _solver(self) -> Any:
        import z3
        solver = z3.Solver()
        solver.set('timeout', self.timeout_ms)
        return solver

    def _counterexample(self, claim: SecurityClaim, solver_model: Any) -> CounterexampleReport:
        witness = {
            declaration.name(): str(solver_model[declaration])
            for declaration in solver_model.decls()
        }
        return CounterexampleReport(
            claim_id=claim.claim_id,
            message='Z3 found a satisfying violation trace.',
            witness=witness,
        )

    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR) -> ProofReport:
        if not self.is_available():
            return self.unknown_report(claim, model, 'Z3 is not installed')
        compilation: Z3Compilation = claim.compile_to_z3(model)
        if not compilation.modeled:
            return ProofReport(
                claim_id=claim.claim_id,
                model_cid=calculate_model_cid(model),
                status='NOT_MODELED',
                prover=self.prover_name,
                proof_or_trace_cid='',
                assumptions=list(claim.required_assumptions),
                compiler_cid='',
                counterexample={'reason': compilation.not_modeled_reason},
                risk=claim.severity,
                signatures=[],
            )
        import z3
        violation_solver = self._solver()
        violation_solver.add(*compilation.assertions)
        violation_solver.add(compilation.violation_formula)
        violation_result = violation_solver.check()
        compiler_cid = ProofReport.content_cid(compilation.compiler_artifact)
        if violation_result == z3.sat:
            counterexample = self._counterexample(claim, violation_solver.model())
            return ProofReport(
                claim_id=claim.claim_id,
                model_cid=calculate_model_cid(model),
                status='DISPROVED',
                prover=self.prover_name,
                proof_or_trace_cid=counterexample.cid,
                assumptions=list(claim.required_assumptions),
                compiler_cid=compiler_cid,
                counterexample=counterexample.to_dict(),
                risk=claim.severity,
                signatures=[],
            )
        if violation_result == z3.unknown:
            return self.unknown_report(claim, model, violation_solver.reason_unknown())
        proof_solver = self._solver()
        proof_solver.add(*compilation.assertions)
        proof_solver.add(z3.Not(compilation.property_formula))
        proof_result = proof_solver.check()
        if proof_result == z3.unsat:
            proof_payload = {
                'claim_id': claim.claim_id,
                'result': 'unsat-violation',
                'prover': self.prover_name,
            }
            return ProofReport(
                claim_id=claim.claim_id,
                model_cid=calculate_model_cid(model),
                status='PROVED',
                prover=self.prover_name,
                proof_or_trace_cid=ProofReport.content_cid(proof_payload),
                assumptions=list(claim.required_assumptions),
                compiler_cid=compiler_cid,
                counterexample=None,
                risk=claim.severity,
                signatures=[],
            )
        if proof_result == z3.sat:
            counterexample = self._counterexample(claim, proof_solver.model())
            return ProofReport(
                claim_id=claim.claim_id,
                model_cid=calculate_model_cid(model),
                status='DISPROVED',
                prover=self.prover_name,
                proof_or_trace_cid=counterexample.cid,
                assumptions=list(claim.required_assumptions),
                compiler_cid=compiler_cid,
                counterexample=counterexample.to_dict(),
                risk=claim.severity,
                signatures=[],
            )
        return self.unknown_report(claim, model, proof_solver.reason_unknown())
