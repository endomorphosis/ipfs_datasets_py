"""Ledger safety and audit claims."""

from __future__ import annotations

from .base import SecurityClaim
from ..compilers.to_z3 import Z3Compilation, claim_not_modeled, z3_import
from ..ir.schema import SecurityModelIR


class NoDoubleSpendInternalBalanceClaim(SecurityClaim):
    """Internal reservations must conserve balance."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='no_double_spend_internal_balance',
            description='No double spend of internal balance.',
            required_assumptions=['database commits are serializable', 'nonce reservation is atomic'],
            severity='blocking',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        if not model.accounts:
            return claim_not_modeled(self, 'account balances are not modeled')
        account = self.find_account(model)
        reservation_requests = list(account.get('reservation_requests', []))
        if len(reservation_requests) < 2:
            return claim_not_modeled(self, 'at least two reservation requests are required')
        z3 = z3_import()
        balance = z3.Int('starting_balance')
        reservation_a = z3.Int('reservation_a')
        reservation_b = z3.Int('reservation_b')
        assertions = [
            balance == int(account.get('balance', 0)),
            reservation_a == int(reservation_requests[0]),
            reservation_b == int(reservation_requests[1]),
            reservation_a >= 0,
            reservation_b >= 0,
        ]
        if self.policy_enabled(model, 'atomic_reservation'):
            assertions.append(reservation_a + reservation_b <= balance)
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=reservation_a + reservation_b <= balance,
            violation_formula=reservation_a + reservation_b > balance,
            compiler_artifact={
                'kind': 'internal_balance_conservation',
                'balance': int(account.get('balance', 0)),
                'reservation_requests': reservation_requests[:2],
            },
        )


class AuditEventExistsForCriticalTransitionClaim(SecurityClaim):
    """Critical state transitions must be audit logged."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='audit_event_exists_for_critical_transition',
            description='Audit event exists for every critical transition.',
            required_assumptions=['audit logs are append-only or tamper-evident'],
            severity='medium',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        if not model.events:
            return claim_not_modeled(self, 'event trace is not modeled')
        z3 = z3_import()
        critical_transition = z3.Bool('critical_transition')
        audit_event = z3.Bool('audit_event')
        assertions = []
        if self.policy_enabled(model, 'audit_required'):
            assertions.append(z3.Implies(critical_transition, audit_event))
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.Implies(critical_transition, audit_event),
            violation_formula=z3.And(critical_transition, z3.Not(audit_event)),
            compiler_artifact={
                'kind': 'audit_transition_policy',
                'policy_enabled': self.policy_enabled(model, 'audit_required'),
            },
        )
