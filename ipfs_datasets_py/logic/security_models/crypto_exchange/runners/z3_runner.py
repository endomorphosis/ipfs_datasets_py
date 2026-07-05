"""Z3-backed proof runner for exchange security claims."""

from __future__ import annotations

import importlib.util
import json
from typing import Any

from ..claims.base import SecurityClaim
from ..compilers.to_z3 import Z3Compilation
from ..ir.cid import calculate_model_cid
from ..ir.schema import SecurityModelIR, evidence_review_statuses
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

    @staticmethod
    def _matching_records(
        records: list[dict[str, Any]],
        *,
        key_names: tuple[str, ...],
        values: list[str],
    ) -> list[dict[str, Any]]:
        """Return model records whose identifying keys match violation-scope values."""

        wanted = {value for value in values if value}
        if not wanted:
            return []
        matches: list[dict[str, Any]] = []
        for record in records:
            for key_name in key_names:
                candidate = record.get(key_name)
                if candidate is not None and str(candidate) in wanted:
                    matches.append(dict(record))
                    break
        return matches

    def _source_facts(self, model: SecurityModelIR, compilation: Z3Compilation) -> list[dict[str, Any]]:
        """Extract concrete IR records that explain the violating counterexample scope."""

        artifact = compilation.compiler_artifact
        source_facts: list[dict[str, Any]] = []
        source_facts.extend(
            self._matching_records(
                model.events,
                key_names=('withdrawal_id', 'deposit_id', 'txid', 'capability_id', 'wallet_id', 'id'),
                values=[
                    *[str(item) for item in artifact.get('violating_withdrawals', [])],
                    *[str(item) for item in artifact.get('offending_ids', [])],
                    *[str(item) for item in artifact.get('violations', [])],
                ],
            )
        )
        source_facts.extend(
            self._matching_records(
                model.capabilities,
                key_names=('id',),
                values=[str(item) for item in artifact.get('violations', [])],
            )
        )
        source_facts.extend(
            self._matching_records(
                model.accounts,
                key_names=('id',),
                values=[str(item) for item in artifact.get('overdrawn_accounts', [])],
            )
        )
        for violation in artifact.get('violations', []):
            if isinstance(violation, dict):
                source_facts.append(dict(violation))
                event = violation.get('event')
                if isinstance(event, dict):
                    source_facts.append(dict(event))
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for fact in source_facts:
            key = json.dumps(fact, sort_keys=True, default=str)
            if key in seen:
                continue
            deduped.append(fact)
            seen.add(key)
        return deduped

    def _counterexample(
        self,
        claim: SecurityClaim,
        model: SecurityModelIR,
        compilation: Z3Compilation,
        solver_model: Any,
    ) -> CounterexampleReport:
        if solver_model is None:
            raise ValueError(f'Z3 did not return a model for claim {claim.claim_id}')
        witness = {
            declaration.name(): str(solver_model[declaration])
            for declaration in solver_model.decls()
        }
        artifact = compilation.compiler_artifact
        return CounterexampleReport(
            claim_id=claim.claim_id,
            message='Z3 found a satisfying violation trace.',
            witness=witness,
            violating_event_ids=[str(item) for item in artifact.get('violating_event_ids', [])],
            withdrawal_ids=[str(item) for item in artifact.get('withdrawal_ids', artifact.get('violating_withdrawals', []))],
            deposit_ids=[str(item) for item in artifact.get('deposit_ids', [])],
            txids=[str(item) for item in artifact.get('txids', [])],
            capability_ids=[str(item) for item in artifact.get('capability_ids', artifact.get('violations', [])) if item is not None],
            wallet_ids=[str(item) for item in artifact.get('wallet_ids', [])],
            account_ids=[str(item) for item in artifact.get('account_ids', artifact.get('overdrawn_accounts', []))],
            source_facts=self._source_facts(model, compilation),
            evidence_refs=list(compilation.evidence_refs),
            soundness_notes=list(compilation.soundness_notes),
            compiler_artifact=dict(artifact),
        )

    def _report(
        self,
        claim: SecurityClaim,
        model: SecurityModelIR,
        *,
        status: str,
        solver_result: str,
        proof_or_trace_cid: str,
        compiler_cid: str,
        counterexample: dict[str, Any] | None,
        compilation: Z3Compilation,
        reason_unknown: str | None = None,
    ) -> ProofReport:
        import z3

        soundness_notes = list(compilation.soundness_notes)
        if claim.severity == 'blocking' and 'heuristic' in evidence_review_statuses(compilation.evidence_refs):
            soundness_notes.append('Blocking proof depends on heuristic evidence and should not be treated as production-grade without review.')
        return ProofReport(
            claim_id=claim.claim_id,
            claim_version=claim.claim_version,
            model_cid=calculate_model_cid(model),
            model_schema_version=model.schema_version,
            status=status,
            prover=self.prover_name,
            solver_name=self.prover_name,
            solver_version=getattr(z3, 'get_full_version', lambda: 'unknown')(),
            solver_result=solver_result,
            timeout_ms=self.timeout_ms,
            reason_unknown=reason_unknown,
            proof_or_trace_cid=proof_or_trace_cid,
            assumptions=list(claim.required_assumptions),
            compiler_cid=compiler_cid,
            counterexample=counterexample,
            risk=claim.severity,
            signatures=[],
            assertion_count=len(compilation.assertions),
            evidence_refs=list(compilation.evidence_refs),
            soundness_notes=soundness_notes,
        )

    def run_claim(self, claim: SecurityClaim, model: SecurityModelIR) -> ProofReport:
        if not self.is_available():
            return self.unknown_report(claim, model, 'Z3 is not installed')
        compilation: Z3Compilation = claim.compile_to_z3(model)
        if not compilation.modeled:
            return ProofReport(
                claim_id=claim.claim_id,
                claim_version=claim.claim_version,
                model_cid=calculate_model_cid(model),
                model_schema_version=model.schema_version,
                status='NOT_MODELED',
                prover=self.prover_name,
                solver_name=self.prover_name,
                solver_result='not-modeled',
                proof_or_trace_cid='',
                assumptions=list(claim.required_assumptions),
                compiler_cid='',
                counterexample={'reason': compilation.not_modeled_reason},
                risk=claim.severity,
                signatures=[],
                evidence_refs=list(compilation.evidence_refs),
                soundness_notes=list(compilation.soundness_notes),
            )
        import z3

        violation_solver = self._solver()
        violation_solver.add(*compilation.assertions)
        violation_solver.add(compilation.violation_formula)
        violation_result = violation_solver.check()
        compiler_cid = ProofReport.content_cid(compilation.compiler_artifact)
        if violation_result == z3.sat:
            counterexample = self._counterexample(claim, model, compilation, violation_solver.model())
            return self._report(
                claim,
                model,
                status='DISPROVED',
                solver_result='sat',
                proof_or_trace_cid=counterexample.cid,
                compiler_cid=compiler_cid,
                counterexample=counterexample.to_dict(),
                compilation=compilation,
            )
        if violation_result == z3.unknown:
            return self._report(
                claim,
                model,
                status='UNKNOWN',
                solver_result='unknown',
                proof_or_trace_cid='',
                compiler_cid=compiler_cid,
                counterexample={'reason': violation_solver.reason_unknown()},
                compilation=compilation,
                reason_unknown=violation_solver.reason_unknown(),
            )
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
            return self._report(
                claim,
                model,
                status='PROVED',
                solver_result='unsat',
                proof_or_trace_cid=ProofReport.content_cid(proof_payload),
                compiler_cid=compiler_cid,
                counterexample=None,
                compilation=compilation,
            )
        if proof_result == z3.sat:
            counterexample = self._counterexample(claim, model, compilation, proof_solver.model())
            return self._report(
                claim,
                model,
                status='DISPROVED',
                solver_result='sat',
                proof_or_trace_cid=counterexample.cid,
                compiler_cid=compiler_cid,
                counterexample=counterexample.to_dict(),
                compilation=compilation,
            )
        return self._report(
            claim,
            model,
            status='UNKNOWN',
            solver_result='unknown',
            proof_or_trace_cid='',
            compiler_cid=compiler_cid,
            counterexample={'reason': proof_solver.reason_unknown()},
            compilation=compilation,
            reason_unknown=proof_solver.reason_unknown(),
        )
