"""Withdrawal safety claims."""

from __future__ import annotations

from .base import SecurityClaim
from ..compilers.to_z3 import Z3Compilation, claim_not_modeled, z3_import
from ..ir.schema import SecurityModelIR


class NoUnauthorizedWithdrawalClaim(SecurityClaim):
    """Broadcasted withdrawals must satisfy authorization controls."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='no_unauthorized_withdrawal',
            description='No withdrawal broadcast occurs without authorization.',
            required_assumptions=['A3', 'A4', 'A5', 'A8'],
            severity='blocking',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        broadcasts = self.find_events(model, 'withdrawal_broadcast')
        if not broadcasts:
            return claim_not_modeled(self, 'withdrawal broadcast events are not modeled')
        policy_records = [
            self.policy_record(model, 'authorization_required'),
            self.policy_record(model, 'fresh_nonce_required'),
            self.policy_record(model, 'sufficient_balance_required'),
            self.policy_record(model, 'wallet_not_frozen_required'),
        ]
        z3 = z3_import()
        violating_withdrawals: list[str] = []
        for event in broadcasts:
            withdrawal_id = str(event.get('withdrawal_id') or event.get('txid'))
            if self.policy_enabled(model, 'authorization_required') and not bool(event.get('authorized', False)):
                violating_withdrawals.append(withdrawal_id)
                continue
            if self.policy_enabled(model, 'fresh_nonce_required') and not bool(event.get('nonce_fresh', False)):
                violating_withdrawals.append(withdrawal_id)
                continue
            if self.policy_enabled(model, 'sufficient_balance_required') and not bool(event.get('sufficient_balance', False)):
                violating_withdrawals.append(withdrawal_id)
                continue
            if self.policy_enabled(model, 'wallet_not_frozen_required') and not bool(event.get('wallet_not_frozen', False)):
                violating_withdrawals.append(withdrawal_id)
        property_formula = z3.And(
            z3.BoolVal(self.policy_enabled(model, 'authorization_required')),
            z3.BoolVal(self.policy_enabled(model, 'fresh_nonce_required')),
            z3.BoolVal(self.policy_enabled(model, 'sufficient_balance_required')),
            z3.BoolVal(self.policy_enabled(model, 'wallet_not_frozen_required')),
            z3.Not(z3.BoolVal(bool(violating_withdrawals))),
        )
        evidence_refs = self.evidence_refs(*policy_records, *broadcasts)
        soundness_notes = self.heuristic_soundness_note(evidence_refs)
        return Z3Compilation(
            claim=self,
            assertions=[],
            property_formula=property_formula,
            compiler_artifact={
                'kind': 'withdrawal_policy',
                'withdrawal_ids': [event.get('withdrawal_id') or event.get('txid') for event in broadcasts],
                'violating_withdrawals': violating_withdrawals,
            },
            evidence_refs=evidence_refs,
            soundness_notes=soundness_notes,
        )
