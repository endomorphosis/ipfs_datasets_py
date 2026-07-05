"""Wallet freeze and signing claims."""

from __future__ import annotations

from typing import Any

from .base import SecurityClaim
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
        signing_events = self.find_events(model, 'signing_request')
        frozen_events = self.find_events(model, 'wallet_frozen')
        if not signing_events and not frozen_events:
            return claim_not_modeled(self, 'wallet freeze/signing events are not modeled')
        z3 = z3_import()
        assertions: list[Any] = []
        checks: list[Any] = []
        violations: list[dict[str, Any]] = []
        wallets = {wallet.get('id'): wallet for wallet in model.wallets}
        unfrozen_events = self.find_events(model, 'wallet_unfrozen')
        for index, signing in enumerate(signing_events):
            wallet_id = signing.get('wallet_id')
            timestamp = signing.get('timestamp')
            event_id = str(signing.get('id', f'signing:{index}'))
            wallet_exists = wallet_id in wallets
            prior_freezes = [
                event for event in frozen_events
                if event.get('wallet_id') == wallet_id and (event.get('timestamp') is None or timestamp is None or event.get('timestamp') <= timestamp)
            ]
            prior_unfreezes = [
                event for event in unfrozen_events
                if event.get('wallet_id') == wallet_id and (event.get('timestamp') is None or timestamp is None or event.get('timestamp') <= timestamp)
            ]
            not_frozen = len(prior_freezes) <= len(prior_unfreezes)
            transaction_reference = signing.get('txid') is not None or signing.get('approved_tx_bytes') is not None
            hsm_evidence_present = bool(signing.get('evidence_refs'))
            condition_values = {
                'wallet_exists': wallet_exists,
                'not_frozen': not_frozen,
                'transaction_reference': transaction_reference,
            }
            condition_vars = []
            for name, value in condition_values.items():
                condition_var = z3.Bool(f'signing_{index}_{name}')
                assertions.append(condition_var == value)
                condition_vars.append(condition_var)
            checks.append(z3.And(*condition_vars))
            if not all(condition_values.values()):
                violations.append({'event_id': event_id, 'wallet_id': wallet_id, 'conditions': condition_values})
            if not hsm_evidence_present:
                condition_vars.append(z3.BoolVal(True))
        policy_record = self.policy_record(model, 'wallet_not_frozen_required')
        evidence_refs = self.evidence_refs(policy_record, *frozen_events, *signing_events)
        soundness_notes = self.heuristic_soundness_note(evidence_refs)
        if any(not event.get('evidence_refs') for event in signing_events):
            soundness_notes.append('Signing request evidence is incomplete; attach HSM or key-manager evidence before production proof use.')
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(*(checks or [z3.BoolVal(False)])),
            compiler_artifact={
                'kind': 'hsm_freeze_policy',
                'violating_event_ids': [item['event_id'] for item in violations],
                'wallet_ids': [str(item['wallet_id']) for item in violations if item.get('wallet_id') is not None],
                'violations': violations,
            },
            evidence_refs=evidence_refs,
            soundness_notes=soundness_notes,
            violation_scope_explanation='Each signing request is checked against modeled freeze/unfreeze history.',
        )
