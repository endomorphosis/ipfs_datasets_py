"""Deposit finality claims."""

from __future__ import annotations

from typing import Any

from .base import SecurityClaim
from ..compilers.to_z3 import Z3Compilation, claim_not_modeled, z3_import
from ..ir.schema import SecurityModelIR


def _identity(event: dict[str, Any]) -> str | None:
    value = event.get('deposit_id') or event.get('txid')
    return str(value) if value is not None else None


class NoDepositCreditedBeforeFinalityClaim(SecurityClaim):
    """Observed deposits must only be credited after finality."""

    def __init__(self) -> None:
        super().__init__(
            claim_id='no_deposit_before_finality',
            description='Deposits are credited only after finality is reached.',
            required_assumptions=['A6', 'A9'],
            severity='high',
        )

    def compile_to_z3(self, model: SecurityModelIR) -> Z3Compilation:
        credited_events = self.find_events(model, 'deposit_credited')
        if not credited_events:
            return claim_not_modeled(self, 'credited deposit events are not modeled')
        observed_events = self.find_events(model, 'deposit_observed')
        finalized_events = self.find_events(model, 'deposit_finalized')
        if not observed_events and not finalized_events:
            return claim_not_modeled(self, 'deposit observation/finality events are not modeled')

        z3 = z3_import()
        assertions: list[Any] = []
        checks: list[Any] = []
        violations: list[dict[str, Any]] = []
        reorg_events = self.find_events(model, 'chain_reorg_detected')
        for index, credited in enumerate(credited_events):
            deposit_id = _identity(dict(credited))
            event_id = str(credited.get('id', f'credit:{index}'))
            observed = [event for event in observed_events if _identity(dict(event)) == deposit_id]
            finalized = [event for event in finalized_events if _identity(dict(event)) == deposit_id]
            observed_ok = bool(observed)
            finalized_ok = bool(finalized)
            confirmation_ok = any(
                int(credited.get('confirmations', event.get('confirmations', 0))) >= int(credited.get('finality_threshold', event.get('finality_threshold', 0)))
                for event in finalized
            )
            finalized_before_credit = any(
                event.get('timestamp') is None
                or credited.get('timestamp') is None
                or event.get('timestamp') <= credited.get('timestamp')
                for event in finalized
            )
            domain_fields_ok = any(
                (credited.get('asset_id') in {None, event.get('asset_id')})
                and (credited.get('chain_id') in {None, event.get('chain_id')})
                and (credited.get('account_id') in {None, event.get('account_id')})
                for event in observed
            ) if observed else True
            reorg_ok = not any(
                _identity(dict(event)) == deposit_id
                and (event.get('timestamp') is None or credited.get('timestamp') is None or event.get('timestamp') <= credited.get('timestamp'))
                for event in reorg_events
            )
            condition_values = {
                'observed_ok': observed_ok,
                'finalized_ok': finalized_ok,
                'confirmation_ok': confirmation_ok,
                'finalized_before_credit': finalized_before_credit,
                'domain_fields_ok': domain_fields_ok,
                'reorg_ok': reorg_ok,
            }
            condition_vars = []
            for name, value in condition_values.items():
                condition_var = z3.Bool(f'deposit_{index}_{name}')
                assertions.append(condition_var == value)
                condition_vars.append(condition_var)
            checks.append(z3.And(*condition_vars))
            if not all(condition_values.values()):
                violations.append(
                    {
                        'event_id': event_id,
                        'deposit_id': deposit_id,
                        'txid': credited.get('txid'),
                        'conditions': condition_values,
                    }
                )
        policy_record = self.policy_record(model, 'credit_after_finality_required')
        evidence_refs = self.evidence_refs(policy_record, *credited_events, *observed_events, *finalized_events)
        return Z3Compilation(
            claim=self,
            assertions=assertions,
            property_formula=z3.And(*(checks or [z3.BoolVal(False)])),
            compiler_artifact={
                'kind': 'deposit_policy',
                'deposit_ids': [item['deposit_id'] for item in violations if item.get('deposit_id')],
                'txids': [str(item['txid']) for item in violations if item.get('txid') is not None],
                'violating_event_ids': [item['event_id'] for item in violations],
                'offending_ids': [item['deposit_id'] or item['txid'] for item in violations if item.get('deposit_id') or item.get('txid')],
                'violations': violations,
            },
            evidence_refs=evidence_refs,
            soundness_notes=self.heuristic_soundness_note(evidence_refs),
            violation_scope_explanation='Each credited deposit must have matching observed/finalized events and survive modeled reorg checks.',
        )
