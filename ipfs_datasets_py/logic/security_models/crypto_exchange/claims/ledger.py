"""Ledger safety and audit claims."""

from __future__ import annotations

from typing import Any

from .base import SecurityClaim
from ..compilers.to_z3 import Z3Compilation, claim_not_modeled, z3_import
from ..ir.schema import SecurityModelIR


class NoOverReservedInternalAccountClaim(SecurityClaim):
    """Internal reservations must never exceed modeled account balance."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='no_over_reserved_internal_account',
            description='No internal account is over-reserved.',
            required_assumptions=['A4', 'A5'],
            severity='blocking',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        accounts = self.iter_accounts(model)
        if not accounts:
            return claim_not_modeled(self, 'account balances are not modeled')
        z3 = z3_import()
        assertions: list[Any] = []
        account_checks: list[Any] = []
        violations: list[dict[str, Any]] = []
        known_assets = {asset.get('id') for asset in model.assets}
        known_wallets = {wallet.get('id') for wallet in model.wallets}
        for index, account in enumerate(accounts):
            account_id = str(account.get('id', f'account:{index}'))
            asset_id = account.get('asset_id', account.get('asset'))
            wallet_id = account.get('wallet_id')
            if asset_id is None or wallet_id is None or asset_id not in known_assets or wallet_id not in known_wallets:
                violations.append({'account_id': account_id, 'reason': 'invalid account references'})
                continue
            balance = int(account.get('balance', 0))
            reservations = [int(item) for item in account.get('reservation_requests', account.get('reservations', []))]
            balance_var = z3.Int(f'account_balance_{index}')
            assertions.append(balance_var == balance)
            account_constraints = [balance_var >= 0]
            reservation_vars: list[Any] = []
            for reservation_index, reservation in enumerate(reservations):
                reservation_var = z3.Int(f'account_{index}_reservation_{reservation_index}')
                assertions.append(reservation_var == reservation)
                account_constraints.append(reservation_var >= 0)
                reservation_vars.append(reservation_var)
            total_reservations = z3.Sum(*reservation_vars) if reservation_vars else z3.IntVal(0)
            account_constraints.append(total_reservations <= balance_var)
            account_checks.append(z3.And(*account_constraints))
            if balance < 0:
                violations.append({'account_id': account_id, 'reason': 'negative balance'})
            if any(reservation < 0 for reservation in reservations):
                violations.append({'account_id': account_id, 'reason': 'negative reservation'})
            if reservations and sum(reservations) > balance:
                violations.append({'account_id': account_id, 'reason': 'over-reserved'})
        policy_record = self.policy_record(model, 'atomic_reservation')
        policy_enabled = self.policy_enabled(model, 'atomic_reservation')
        if not policy_enabled:
            violations.append({'account_id': '<policy>', 'reason': 'atomic reservation policy disabled'})
        evidence_refs = self.evidence_refs(policy_record, *accounts)
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(z3.BoolVal(policy_enabled), *(account_checks or [z3.BoolVal(False)])),
            compiler_artifact={
                'kind': 'internal_account_reservations',
                'overdrawn_accounts': sorted({item['account_id'] for item in violations}),
                'account_ids': [str(account.get('id')) for account in accounts if account.get('id') is not None],
                'violations': violations,
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
            violation_scope_explanation='Each account balance/reservation tuple is checked independently.',
        )


class GlobalAssetConservationClaim(SecurityClaim):
    """Customer liabilities must not exceed modeled custody plus pending settlements."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='global_asset_conservation',
            description='Global asset liabilities are covered by custody assets.',
            required_assumptions=['A4', 'A10'],
            severity='blocking',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        ledger_totals = model.metadata.get('ledger_totals')
        if not isinstance(ledger_totals, dict):
            return claim_not_modeled(self, 'metadata.ledger_totals is not modeled')
        liabilities = ledger_totals.get('customer_liabilities')
        custody = ledger_totals.get('custody_assets')
        pending = ledger_totals.get('pending_settlements')
        losses = ledger_totals.get('known_losses')
        if not all(isinstance(bucket, dict) for bucket in (liabilities, custody, pending, losses)):
            return claim_not_modeled(self, 'metadata.ledger_totals buckets are incomplete')
        known_assets = {asset.get('id') for asset in model.assets}
        z3 = z3_import()
        assertions: list[Any] = []
        asset_checks: list[Any] = []
        insolvent_assets: list[str] = []
        for index, asset_id in enumerate(sorted(liabilities)):
            if asset_id not in known_assets:
                insolvent_assets.append(str(asset_id))
                continue
            liability = int(liabilities.get(asset_id, 0))
            available = int(custody.get(asset_id, 0)) + int(pending.get(asset_id, 0)) - int(losses.get(asset_id, 0))
            liability_var = z3.Int(f'liability_{index}')
            available_var = z3.Int(f'available_{index}')
            assertions.extend([liability_var == liability, available_var == available, liability_var >= 0, available_var >= 0])
            asset_checks.append(liability_var <= available_var)
            if liability > available:
                insolvent_assets.append(str(asset_id))
        evidence_refs = self.evidence_refs(*model.accounts, *model.assets)
        if isinstance(model.metadata.get('ledger_totals_evidence_refs'), list):
            evidence_refs.extend(
                dict(reference)
                for reference in model.metadata['ledger_totals_evidence_refs']
                if isinstance(reference, dict) and reference not in evidence_refs
            )
        autoformalization = model.metadata.get('autoformalization')
        if isinstance(autoformalization, dict):
            for reference in autoformalization.get('evidence_refs', []):
                if isinstance(reference, dict) and reference not in evidence_refs:
                    evidence_refs.append(dict(reference))
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(*(asset_checks or [z3.BoolVal(False)])),
            compiler_artifact={
                'kind': 'global_asset_conservation',
                'asset_ids': sorted(str(asset_id) for asset_id in liabilities),
                'violations': sorted(insolvent_assets),
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
            violation_scope_explanation='Each modeled asset bucket is constrained independently.',
        )


class NoDoubleSpendInternalBalanceClaim(SecurityClaim):
    """Backward-compatible combined ledger safety claim."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='no_double_spend_internal_balance',
            description='No double spend of internal balance.',
            required_assumptions=['A4', 'A5'],
            severity='blocking',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        z3 = z3_import()
        reservation = NoOverReservedInternalAccountClaim().compile_to_z3(model)
        conservation = GlobalAssetConservationClaim().compile_to_z3(model)
        if not reservation.modeled and not conservation.modeled:
            return claim_not_modeled(self, 'ledger reservations and global conservation are not modeled')
        assertions = list(reservation.assertions) + list(conservation.assertions)
        evidence_refs = list(reservation.evidence_refs) + [ref for ref in conservation.evidence_refs if ref not in reservation.evidence_refs]
        soundness_notes = list(reservation.soundness_notes) + [note for note in conservation.soundness_notes if note not in reservation.soundness_notes]
        property_terms = []
        if reservation.modeled:
            property_terms.append(reservation.property_formula)
        if conservation.modeled:
            property_terms.append(conservation.property_formula)
        compiler_artifact = {
            'kind': 'combined_ledger_safety',
            'overdrawn_accounts': reservation.compiler_artifact.get('overdrawn_accounts', []),
            'conservation_violations': conservation.compiler_artifact.get('violations', []),
            'account_ids': reservation.compiler_artifact.get('account_ids', []),
            'asset_ids': conservation.compiler_artifact.get('asset_ids', []),
            'violations': [
                *reservation.compiler_artifact.get('violations', []),
                *conservation.compiler_artifact.get('violations', []),
            ],
        }
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(*(property_terms or [z3.BoolVal(False)])),
            compiler_artifact=compiler_artifact,
            evidence_refs=evidence_refs,
            soundness_notes=soundness_notes,
            violation_scope_explanation='Combined compatibility view over reservation safety and global conservation.',
        )


class AuditEventExistsForCriticalTransitionClaim(SecurityClaim):
    """Critical state transitions must be audit logged with event-specific linkage."""

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
        critical_events = [event for event in model.events if event.get('critical')]
        if not critical_events:
            return claim_not_modeled(self, 'critical transitions are not modeled')
        audit_events = [event for event in model.events if event.get('event') == 'audit_logged']
        assertions: list[Any] = []
        checks: list[Any] = []
        missing_audit: list[str] = []
        for index, event in enumerate(critical_events):
            event_id = str(event.get('id', f'critical:{index}'))
            expected_targets = {
                ('target_event_id', event.get('id')),
                ('target_withdrawal_id', event.get('withdrawal_id')),
                ('target_deposit_id', event.get('deposit_id')),
                ('target_txid', event.get('txid')),
            }
            matched = False
            for audit in audit_events:
                if any(value is not None and audit.get(field_name) == value for field_name, value in expected_targets):
                    matched = True
                    break
            match_var = z3.Bool(f'audit_match_{index}')
            assertions.append(match_var == matched)
            checks.append(match_var)
            if not matched:
                missing_audit.append(event_id)
        policy_record = self.policy_record(model, 'audit_required')
        evidence_refs = self.evidence_refs(policy_record, *model.events)
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(*(checks or [z3.BoolVal(False)])),
            compiler_artifact={
                'kind': 'audit_transition_policy',
                'critical_event_ids': [str(event.get('id')) for event in critical_events if event.get('id') is not None],
                'violating_event_ids': missing_audit,
                'missing_audit': missing_audit,
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
            violation_scope_explanation='Each critical event must be covered by an audit event referencing that event or domain id.',
        )
