"""Deposit finality claims."""

from __future__ import annotations

from .base import SecurityClaim
from ..compilers.to_z3 import Z3Compilation, claim_not_modeled, z3_import
from ..ir.schema import SecurityModelIR


class NoDepositCreditedBeforeFinalityClaim(SecurityClaim):
    """Observed deposits must only be credited after finality."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='no_deposit_before_finality',
            description='Deposits are credited only after finality is reached.',
            required_assumptions=['blockchain finality threshold k is sufficient'],
            severity='high',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        if not model.events:
            return claim_not_modeled(self, 'deposit events are not modeled')
        z3 = z3_import()
        credited = z3.Bool('deposit_credited')
        finalized = z3.Bool('deposit_finalized')
        assertions = []
        if self.policy_enabled(model, 'credit_after_finality_required'):
            assertions.append(z3.Implies(credited, finalized))
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.Implies(credited, finalized),
            violation_formula=z3.And(credited, z3.Not(finalized)),
            compiler_artifact={
                'kind': 'deposit_policy',
                'assertions': [str(expr) for expr in assertions],
            },
        )
