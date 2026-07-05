"""Deposit finality claims."""

from __future__ import annotations

from .base import SecurityClaim
from ..monitors.runtime_mtl import RuntimeMTLMonitor
from ..compilers.to_z3 import Z3Compilation, claim_not_modeled, z3_import
from ..ir.schema import SecurityModelIR


class NoDepositCreditedBeforeFinalityClaim(SecurityClaim):
    """Observed deposits must only be credited after finality."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='no_deposit_before_finality',
            description='Deposits are credited only after finality is reached.',
            required_assumptions=['A6', 'A9'],
            severity='high',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        credited_events = self.find_events(model, 'deposit_credited')
        if not credited_events:
            return claim_not_modeled(self, 'credited deposit events are not modeled')
        z3 = z3_import()
        monitor = RuntimeMTLMonitor(events=model.events)
        violations = monitor.check_deposit_only_after_finality()
        violation_events = [violation.get('event', {}) for violation in violations]
        offending_ids = sorted(
            {
                str(event.get('deposit_id') or event.get('txid'))
                for event in violation_events
                if event.get('deposit_id') is not None or event.get('txid') is not None
            }
        )
        policy_record = self.policy_record(model, 'credit_after_finality_required')
        evidence_refs = self.evidence_refs(policy_record, *credited_events, *self.find_events(model, 'deposit_finalized'))
        return Z3Compilation(
            claim=self,
            assertions=[],
            property_formula=z3.And(
                z3.BoolVal(self.policy_enabled(model, 'credit_after_finality_required')),
                z3.Not(z3.BoolVal(bool(offending_ids))),
            ),
            compiler_artifact={
                'kind': 'deposit_policy',
                'credited_events': len(credited_events),
                'offending_ids': offending_ids,
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
        )
