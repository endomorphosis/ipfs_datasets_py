"""Small runtime temporal monitor over event dictionaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeMTLMonitor:
    """Evaluate simple future-time security properties over event traces."""

    events: list[dict[str, Any]]
    violations: list[dict[str, Any]] = field(default_factory=list)

    def check_no_signing_after_freeze(self) -> list[dict[str, Any]]:
        for index, event in enumerate(self.events):
            if event.get('event') != 'wallet_frozen':
                continue
            wallet_id = event.get('wallet_id')
            for future_index, future_event in enumerate(self.events[index + 1 :], start=index + 1):
                if future_event.get('event') == 'signing_request' and future_event.get('wallet_id') == wallet_id:
                    self.violations.append({'property': 'wallet_frozen -> no future signing_request', 'index': future_index, 'event': future_event})
        return self.violations

    def check_withdrawal_approved_eventually_broadcast_or_cancelled(self) -> list[dict[str, Any]]:
        for index, event in enumerate(self.events):
            if event.get('event') != 'withdrawal_approved':
                continue
            if not any(future.get('event') in {'withdrawal_broadcast', 'withdrawal_cancelled'} for future in self.events[index + 1 :]):
                self.violations.append({'property': 'withdrawal_approved -> eventually broadcast_or_cancelled', 'index': index, 'event': event})
        return self.violations

    def check_deposit_only_after_finality(self) -> list[dict[str, Any]]:
        finalized_txids: set[Any] = set()
        for index, event in enumerate(self.events):
            if event.get('event') == 'deposit_finalized':
                finalized_txids.add(event.get('txid'))
            if event.get('event') == 'deposit_credited' and event.get('txid') not in finalized_txids:
                self.violations.append({'property': 'deposit_observed -> credited only after finality', 'index': index, 'event': event})
        return self.violations

    def check_no_privileged_action_after_revocation(self) -> list[dict[str, Any]]:
        revoked_capabilities = set()
        for index, event in enumerate(self.events):
            if event.get('event') == 'capability_revoked':
                revoked_capabilities.add(event.get('capability_id'))
            if event.get('event') == 'privileged_action' and event.get('capability_id') in revoked_capabilities:
                self.violations.append({'property': 'capability_revoked -> no privileged action after revocation', 'index': index, 'event': event})
        return self.violations

    def check_all(self) -> list[dict[str, Any]]:
        self.check_no_signing_after_freeze()
        self.check_withdrawal_approved_eventually_broadcast_or_cancelled()
        self.check_deposit_only_after_finality()
        self.check_no_privileged_action_after_revocation()
        return self.violations


def check_runtime_properties(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convenience wrapper for runtime temporal checks."""

    return RuntimeMTLMonitor(events=events).check_all()
