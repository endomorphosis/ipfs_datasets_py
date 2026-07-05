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
            required_assumptions=['blockchain finality threshold k is sufficient'],
            severity='high',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        if not model.events:
            return claim_not_modeled(self, 'deposit events are not modeled')
        z3 = z3_import()
        credited_events = [event for event in model.events if event.get('event') == 'deposit_credited']
        if not credited_events:
            return claim_not_modeled(self, 'credited deposit events are not modeled')
        policy_enabled = z3.Bool('credit_after_finality_required')
        credited_before_finality = z3.Bool('credited_before_finality')
        violations = RuntimeMTLMonitor(events=model.events).check_deposit_only_after_finality()
        offending_txids = sorted(
            {
                str(event.get('txid'))
                for event in (violation.get('event', {}) for violation in violations)
                if event.get('txid') is not None
            }
        )
        assertions = [
            policy_enabled == self.policy_enabled(model, 'credit_after_finality_required'),
            credited_before_finality == bool(violations),
        ]
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(policy_enabled, z3.Not(credited_before_finality)),
            violation_formula=z3.Or(z3.Not(policy_enabled), credited_before_finality),
            compiler_artifact={
                'kind': 'deposit_policy',
                'credited_events': len(credited_events),
                'offending_txids': offending_txids,
                'assertions': [str(expr) for expr in assertions],
            },
        )
