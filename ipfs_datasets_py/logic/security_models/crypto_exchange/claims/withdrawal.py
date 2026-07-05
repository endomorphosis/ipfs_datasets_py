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
        if not model.policies:
            return claim_not_modeled(self, 'authorization policies are not modeled')
        z3 = z3_import()
        broadcast = z3.Bool('withdrawal_broadcast')
        authorized = z3.Bool('withdrawal_authorized')
        nonce_fresh = z3.Bool('withdrawal_nonce_fresh')
        sufficient_balance = z3.Bool('withdrawal_sufficient_balance')
        wallet_not_frozen = z3.Bool('withdrawal_wallet_not_frozen')
        assertions = []
        if self.policy_enabled(model, 'authorization_required'):
            assertions.append(z3.Implies(broadcast, authorized))
        if self.policy_enabled(model, 'fresh_nonce_required'):
            assertions.append(z3.Implies(broadcast, nonce_fresh))
        if self.policy_enabled(model, 'sufficient_balance_required'):
            assertions.append(z3.Implies(broadcast, sufficient_balance))
        if self.policy_enabled(model, 'wallet_not_frozen_required'):
            assertions.append(z3.Implies(broadcast, wallet_not_frozen))
        property_formula = z3.Implies(broadcast, z3.And(authorized, nonce_fresh, sufficient_balance, wallet_not_frozen))
        violation_formula = z3.And(broadcast, z3.Not(authorized))
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=property_formula,
            violation_formula=violation_formula,
            compiler_artifact={
                'kind': 'withdrawal_policy',
                'policies': [policy.get('name') for policy in model.policies],
                'assertions': [str(expr) for expr in assertions],
            },
        )
