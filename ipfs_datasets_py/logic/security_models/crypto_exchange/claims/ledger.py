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
            required_assumptions=['A4', 'A5'],
            severity='blocking',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        accounts = self.iter_accounts(model)
        if not accounts:
            return claim_not_modeled(self, 'account balances are not modeled')
        overdrawn_accounts: list[str] = []
        for account in accounts:
            balance = int(account.get('balance', 0))
            reservations = [int(item) for item in account.get('reservation_requests', account.get('reservations', []))]
            if reservations and sum(reservations) > balance:
                overdrawn_accounts.append(str(account.get('id', '<unknown>')))
        totals = model.metadata.get('ledger_totals', {})
        conservation_violations: list[str] = []
        if isinstance(totals, dict):
            liabilities = totals.get('customer_liabilities', {})
            custody = totals.get('custody_assets', {})
            pending = totals.get('pending_settlements', {})
            losses = totals.get('known_losses', {})
            if all(isinstance(item, dict) for item in (liabilities, custody, pending, losses)):
                for asset_id, liability in liabilities.items():
                    available = int(custody.get(asset_id, 0)) + int(pending.get(asset_id, 0)) - int(losses.get(asset_id, 0))
                    if int(liability) > available:
                        conservation_violations.append(str(asset_id))
        z3 = z3_import()
        policy_record = self.policy_record(model, 'atomic_reservation')
        evidence_refs = self.evidence_refs(policy_record, *accounts)
        soundness_notes = self.heuristic_soundness_note(evidence_refs)
        if not totals:
            soundness_notes.append('Global custody-versus-liability conservation is not modeled in this IR payload.')
        return Z3Compilation(
            claim=self,
            assertions=[],
            property_formula=z3.And(
                z3.BoolVal(self.policy_enabled(model, 'atomic_reservation')),
                z3.Not(z3.BoolVal(bool(overdrawn_accounts))),
                z3.Not(z3.BoolVal(bool(conservation_violations))),
            ),
            compiler_artifact={
                'kind': 'internal_balance_conservation',
                'overdrawn_accounts': overdrawn_accounts,
                'conservation_violations': conservation_violations,
            },
            evidence_refs=evidence_refs,
            soundness_notes=soundness_notes,
        )


class AuditEventExistsForCriticalTransitionClaim(SecurityClaim):
    """Critical state transitions must be audit logged."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='audit_event_exists_for_critical_transition',
            description='Audit event exists for every critical transition.',
            required_assumptions=['A10'],
            severity='medium',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        if not model.events:
            return claim_not_modeled(self, 'event trace is not modeled')
        z3 = z3_import()
        critical_transitions = [
            str(event.get('event'))
            for event in model.events
            if event.get('critical') and event.get('event')
        ]
        if not critical_transitions:
            return claim_not_modeled(self, 'critical transitions are not modeled')
        audited_transitions = {
            str(event.get('transition'))
            for event in model.events
            if event.get('event') == 'audit_logged' and event.get('transition')
        }
        missing_audit_transitions = sorted(
            transition for transition in critical_transitions if transition not in audited_transitions
        )
        policy_record = self.policy_record(model, 'audit_required')
        evidence_refs = self.evidence_refs(policy_record, *model.events)
        return Z3Compilation(
            claim=self,
            assertions=[],
            property_formula=z3.And(
                z3.BoolVal(self.policy_enabled(model, 'audit_required')),
                z3.Not(z3.BoolVal(bool(missing_audit_transitions))),
            ),
            compiler_artifact={
                'kind': 'audit_transition_policy',
                'critical_transitions': critical_transitions,
                'audited_transitions': sorted(audited_transitions),
                'missing_audit': missing_audit_transitions,
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
        )
