"""Wallet freeze and signing claims."""

from __future__ import annotations

from .base import SecurityClaim
from ..monitors.runtime_mtl import RuntimeMTLMonitor
from ..compilers.to_z3 import Z3Compilation, claim_not_modeled, z3_import
from ..ir.schema import SecurityModelIR


class NoSigningAfterWalletFreezeClaim(SecurityClaim):
    """Frozen wallets must not produce new signing requests."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='no_signing_request_after_wallet_freeze',
            description='No signing request after wallet freeze.',
            required_assumptions=['A3', 'A8'],
            severity='high',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        frozen_events = self.find_events(model, 'wallet_frozen')
        if not frozen_events:
            return claim_not_modeled(self, 'wallet freeze events are not modeled')
        z3 = z3_import()
        violations = RuntimeMTLMonitor(events=model.events).check_no_signing_after_freeze()
        policy_record = self.policy_record(model, 'wallet_not_frozen_required')
        evidence_refs = self.evidence_refs(policy_record, *frozen_events, *self.find_events(model, 'signing_request'))
        return Z3Compilation(
            claim=self,
            assertions=[],
            property_formula=z3.And(
                z3.BoolVal(self.policy_enabled(model, 'wallet_not_frozen_required')),
                z3.Not(z3.BoolVal(bool(violations))),
            ),
            compiler_artifact={
                'kind': 'hsm_freeze_policy',
                'violations': [dict(item) for item in violations],
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
        )
