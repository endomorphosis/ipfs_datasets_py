"""Withdrawal safety claims."""

from __future__ import annotations

from typing import Any

from .base import SecurityClaim
from ..compilers.to_z3 import Z3Compilation, claim_not_modeled, z3_import
from ..ir.schema import SecurityModelIR


def _get_withdrawal_identity(event: dict[str, Any]) -> str | None:
    value = event.get('withdrawal_id') or event.get('txid')
    return str(value) if value is not None else None


class NoUnauthorizedWithdrawalClaim(SecurityClaim):
    """Broadcasted withdrawals must be derived from modeled request/approval flow."""

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
        requests = self.find_events(model, 'withdrawal_requested')
        approvals = self.find_events(model, 'withdrawal_approved')
        if not requests and not approvals:
            return claim_not_modeled(self, 'withdrawal request/approval events are not modeled')

        z3 = z3_import()
        assertions: list[Any] = []
        checks: list[Any] = []
        violations: list[dict[str, Any]] = []
        frozen_events = self.find_events(model, 'wallet_frozen')
        unfrozen_events = self.find_events(model, 'wallet_unfrozen')
        for index, broadcast in enumerate(broadcasts):
            broadcast_id = str(broadcast.get('id', f'broadcast:{index}'))
            withdrawal_id = _get_withdrawal_identity(dict(broadcast))
            wallet_id = broadcast.get('wallet_id')
            timestamp = broadcast.get('timestamp')
            matching_requests = [event for event in requests if _get_withdrawal_identity(dict(event)) == withdrawal_id]
            matching_approvals = [event for event in approvals if _get_withdrawal_identity(dict(event)) == withdrawal_id]
            has_request = bool(matching_requests)
            has_approval = bool(matching_approvals)
            approval_before_broadcast = any(
                approval.get('timestamp') is None
                or timestamp is None
                or approval.get('timestamp') <= timestamp
                for approval in matching_approvals
            )
            request_wallet_matches = any(event.get('wallet_id') == wallet_id for event in matching_requests) if wallet_id is not None else True
            approval_wallet_matches = any(event.get('wallet_id') == wallet_id for event in matching_approvals) if wallet_id is not None else True
            frozen_before = [
                event for event in frozen_events
                if wallet_id is not None
                and event.get('wallet_id') == wallet_id
                and (event.get('timestamp') is None or timestamp is None or event.get('timestamp') <= timestamp)
            ]
            unfrozen_before = [
                event for event in unfrozen_events
                if wallet_id is not None
                and event.get('wallet_id') == wallet_id
                and (event.get('timestamp') is None or timestamp is None or event.get('timestamp') <= timestamp)
            ]
            freeze_blocks = bool(frozen_before) and len(unfrozen_before) < len(frozen_before)
            nonce_ok = True
            nonce = broadcast.get('nonce')
            if nonce is not None and model.events:
                nonce_ok = any(
                    event.get('event') == 'nonce_reserved' and event.get('nonce') == nonce and _get_withdrawal_identity(dict(event)) == withdrawal_id
                    for event in model.events
                )
            reservation_ok = True
            amount = broadcast.get('amount')
            asset_id = broadcast.get('asset_id', broadcast.get('asset'))
            if amount is not None or asset_id is not None:
                reservation_ok = any(
                    event.get('event') == 'balance_reserved'
                    and _get_withdrawal_identity(dict(event)) == withdrawal_id
                    and (amount is None or event.get('amount') == amount)
                    and (asset_id is None or event.get('asset_id', event.get('asset')) == asset_id)
                    for event in model.events
                )
            condition_values = {
                'has_request': has_request,
                'has_approval': has_approval,
                'approval_before_broadcast': approval_before_broadcast,
                'request_wallet_matches': request_wallet_matches,
                'approval_wallet_matches': approval_wallet_matches,
                'not_frozen': not freeze_blocks,
                'nonce_ok': nonce_ok,
                'reservation_ok': reservation_ok,
            }
            condition_vars = []
            for name, value in condition_values.items():
                condition_var = z3.Bool(f'withdrawal_{index}_{name}')
                assertions.append(condition_var == value)
                condition_vars.append(condition_var)
            checks.append(z3.And(*condition_vars))
            if not all(condition_values.values()):
                violations.append(
                    {
                        'event_id': broadcast_id,
                        'withdrawal_id': withdrawal_id,
                        'wallet_id': wallet_id,
                        'conditions': condition_values,
                    }
                )

        policy_records = [
            self.policy_record(model, 'authorization_required'),
            self.policy_record(model, 'fresh_nonce_required'),
            self.policy_record(model, 'sufficient_balance_required'),
            self.policy_record(model, 'wallet_not_frozen_required'),
        ]
        policy_checks = {
            'authorization_required': self.policy_enabled(model, 'authorization_required'),
            'fresh_nonce_required': self.policy_enabled(model, 'fresh_nonce_required'),
            'sufficient_balance_required': self.policy_enabled(model, 'sufficient_balance_required'),
            'wallet_not_frozen_required': self.policy_enabled(model, 'wallet_not_frozen_required'),
        }
        if not all(policy_checks.values()):
            violations.append(
                {
                    'event_id': 'policy:withdrawal_authorization',
                    'withdrawal_id': None,
                    'wallet_id': None,
                    'conditions': policy_checks,
                }
            )
        evidence_refs = self.evidence_refs(*policy_records, *requests, *approvals, *broadcasts)
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(z3.BoolVal(all(policy_checks.values())), *(checks or [z3.BoolVal(False)])),
            compiler_artifact={
                'kind': 'withdrawal_policy',
                'withdrawal_ids': [item['withdrawal_id'] for item in violations if item.get('withdrawal_id')],
                'violating_withdrawals': [item['withdrawal_id'] for item in violations if item.get('withdrawal_id')],
                'violating_event_ids': [item['event_id'] for item in violations],
                'wallet_ids': [str(item['wallet_id']) for item in violations if item.get('wallet_id') is not None],
                'violations': violations,
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
            violation_scope_explanation='Each broadcast must be justified by prior request/approval and unfrozen wallet state.',
        )
