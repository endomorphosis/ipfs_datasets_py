"""Wallet freeze and signing claims."""

from __future__ import annotations

from .base import SecurityClaim
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
        wallet_frozen = z3.Bool('wallet_frozen')
        signing_request = z3.Bool('signing_request')
        assertions = [z3.Implies(signing_request, z3.Not(wallet_frozen))]
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.Implies(signing_request, z3.Not(wallet_frozen)),
            violation_formula=z3.And(wallet_frozen, signing_request),
            compiler_artifact={
                'kind': 'hsm_freeze_policy',
            },
        )
