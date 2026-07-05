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
            required_assumptions=['HSM/key manager obeys its interface contract'],
            severity='high',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        if not model.events:
            return claim_not_modeled(self, 'freeze and signing events are not modeled')
        z3 = z3_import()
        if not any(event.get('event') == 'wallet_frozen' for event in model.events):
            return claim_not_modeled(self, 'wallet freeze events are not modeled')
        policy_enabled = z3.Bool('wallet_not_frozen_required')
        signing_after_freeze = z3.Bool('signing_request_after_wallet_freeze')
        violations = RuntimeMTLMonitor(events=model.events).check_no_signing_after_freeze()
        assertions = [
            policy_enabled == self.policy_enabled(model, 'wallet_not_frozen_required'),
            signing_after_freeze == bool(violations),
        ]
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(policy_enabled, z3.Not(signing_after_freeze)),
            violation_formula=z3.Or(z3.Not(policy_enabled), signing_after_freeze),
            compiler_artifact={
                'kind': 'hsm_freeze_policy',
                'violations': [dict(item) for item in violations],
                'assertions': [str(expr) for expr in assertions],
            },
        )
