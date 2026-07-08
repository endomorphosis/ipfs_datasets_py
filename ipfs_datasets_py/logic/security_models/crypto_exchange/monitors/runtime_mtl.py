"""Small runtime temporal monitor over event dictionaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any



def _event_identity(event: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = event.get(key)
        if value is not None:
            return value
    return None



def _event_timestamp(event: dict[str, Any]) -> float | None:
    value = event.get('timestamp')
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            try:
                return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
            except ValueError:
                return None
    return None


@dataclass(slots=True)
class RuntimeMTLMonitor:
    """Evaluate simple future-time security properties over event traces."""

    events: list[dict[str, Any]]
    violations: list[dict[str, Any]] = field(default_factory=list)

    def _record_violation(self, property_name: str, index: int, event: dict[str, Any], detail: str | None = None) -> None:
        violation = {'property': property_name, 'index': index, 'event': event}
        if detail:
            violation['detail'] = detail
        self.violations.append(violation)

    def validate_event_ordering(self) -> list[dict[str, Any]]:
        previous_timestamp: float | None = None
        for index, event in enumerate(self.events):
            timestamp = _event_timestamp(event)
            if timestamp is None:
                continue
            if previous_timestamp is not None and timestamp < previous_timestamp:
                self._record_violation('event ordering is monotonic when timestamps exist', index, event)
            previous_timestamp = timestamp
        return self.violations

    def check_no_signing_after_freeze(self) -> list[dict[str, Any]]:
        frozen_wallets: dict[Any, float | None] = {}
        for index, event in enumerate(self.events):
            wallet_id = event.get('wallet_id')
            if event.get('event') == 'wallet_frozen' and wallet_id is not None:
                frozen_wallets[wallet_id] = _event_timestamp(event)
                continue
            if event.get('event') != 'signing_request' or wallet_id not in frozen_wallets:
                continue
            frozen_at = frozen_wallets[wallet_id]
            signed_at = _event_timestamp(event)
            if frozen_at is None or signed_at is None or signed_at >= frozen_at:
                self._record_violation('wallet_frozen -> no future signing_request', index, event)
        return self.violations

    def check_withdrawal_approved_eventually_broadcast_or_cancelled(self) -> list[dict[str, Any]]:
        approvals: dict[Any, tuple[int, dict[str, Any]]] = {}
        completed: set[Any] = set()
        for index, event in enumerate(self.events):
            event_name = event.get('event')
            withdrawal_id = _event_identity(event, 'withdrawal_id', 'txid')
            if withdrawal_id is None:
                continue
            if event_name == 'withdrawal_approved':
                approvals[withdrawal_id] = (index, event)
                continue
            if event_name in {'withdrawal_broadcast', 'withdrawal_cancelled'}:
                completed.add(withdrawal_id)
                approvals.pop(withdrawal_id, None)
        for withdrawal_id, (index, event) in approvals.items():
            self._record_violation(
                'withdrawal_approved -> eventually broadcast_or_cancelled',
                index,
                event,
                detail=f'missing completion for {withdrawal_id}',
            )
        for index, event in enumerate(self.events):
            if event.get('event') != 'withdrawal_approved':
                continue
            withdrawal_id = _event_identity(event, 'withdrawal_id', 'txid')
            if withdrawal_id is None or withdrawal_id not in completed:
                continue
            approved_at = _event_timestamp(event)
            max_seconds = event.get('max_seconds')
            if approved_at is None or max_seconds is None:
                continue
            for future_event in self.events[index + 1 :]:
                if future_event.get('event') not in {'withdrawal_broadcast', 'withdrawal_cancelled'}:
                    continue
                future_id = _event_identity(future_event, 'withdrawal_id', 'txid')
                if future_id != withdrawal_id:
                    continue
                completed_at = _event_timestamp(future_event)
                if completed_at is not None and completed_at - approved_at > float(max_seconds):
                    self._record_violation(
                        'withdrawal_approved -> eventually broadcast_or_cancelled',
                        index,
                        event,
                        detail=f'completion exceeded max_seconds for {withdrawal_id}',
                    )
                break
        return self.violations

    def check_deposit_only_after_finality(self) -> list[dict[str, Any]]:
        finalized_deposits: dict[Any, tuple[int, int | None]] = {}
        for index, event in enumerate(self.events):
            event_name = event.get('event')
            deposit_id = _event_identity(event, 'deposit_id', 'txid')
            if deposit_id is None:
                continue
            if event_name == 'deposit_finalized':
                confirmations = event.get('confirmations')
                finalized_deposits[deposit_id] = (
                    int(confirmations) if isinstance(confirmations, int) else None,
                    int(event.get('finality_threshold')) if isinstance(event.get('finality_threshold'), int) else None,
                )
                continue
            if event_name != 'deposit_credited':
                continue
            finalized = finalized_deposits.get(deposit_id)
            if finalized is None:
                self._record_violation('deposit_observed -> credited only after finality', index, event)
                continue
            finalized_confirmations, finalized_threshold = finalized
            threshold = event.get('finality_threshold', finalized_threshold)
            confirmations = event.get('confirmations', finalized_confirmations)
            if isinstance(threshold, int) and isinstance(confirmations, int) and confirmations < threshold:
                self._record_violation('deposit_observed -> credited only after finality', index, event)
        return self.violations

    def check_no_privileged_action_after_revocation(self) -> list[dict[str, Any]]:
        revoked_capabilities: dict[Any, float | None] = {}
        for index, event in enumerate(self.events):
            capability_id = event.get('capability_id')
            if event.get('event') == 'capability_revoked' and capability_id is not None:
                revoked_capabilities[capability_id] = _event_timestamp(event)
                continue
            if event.get('event') != 'privileged_action' or capability_id not in revoked_capabilities:
                continue
            revoked_at = revoked_capabilities[capability_id]
            acted_at = _event_timestamp(event)
            if revoked_at is None or acted_at is None or acted_at >= revoked_at:
                self._record_violation('capability_revoked -> no privileged action after revocation', index, event)
        return self.violations

    def check_all(self) -> list[dict[str, Any]]:
        self.violations = []
        self.validate_event_ordering()
        self.check_no_signing_after_freeze()
        self.check_withdrawal_approved_eventually_broadcast_or_cancelled()
        self.check_deposit_only_after_finality()
        self.check_no_privileged_action_after_revocation()
        return list(self.violations)



def check_runtime_properties(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convenience wrapper for runtime temporal checks."""

    return RuntimeMTLMonitor(events=events).check_all()
