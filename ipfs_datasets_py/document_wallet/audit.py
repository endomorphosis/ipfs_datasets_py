"""Audit log helpers for document wallets."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .models import AuditEvent, WalletRecord, new_id


def record_audit_event(
    wallet: WalletRecord,
    *,
    actor_did: str,
    action: str,
    resource: str,
    decision: str,
    grant_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditEvent:
    previous_hash = wallet.audit_log[-1].event_hash if wallet.audit_log else None
    event = AuditEvent(
        event_id=new_id("audit"),
        wallet_id=wallet.wallet_id,
        actor_did=actor_did,
        action=action,
        resource=resource,
        decision=decision,
        grant_id=grant_id,
        details=details or {},
        previous_hash=previous_hash,
    )
    wallet.audit_log.append(event)
    wallet.refresh_manifest_head()
    return event


def verify_audit_chain(wallet: WalletRecord) -> bool:
    previous_hash = None
    for event in wallet.audit_log:
        if event.previous_hash != previous_hash:
            return False
        previous_hash = event.event_hash
    return True

