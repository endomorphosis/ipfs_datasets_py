"""Audit hash-chain helpers for wallet events."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List

from .manifest import canonical_bytes
from .models import AuditEvent


def append_audit_event(
    events: List[AuditEvent],
    *,
    wallet_id: str,
    actor_did: str,
    action: str,
    resource: str,
    decision: str,
    details: Dict[str, Any] | None = None,
    grant_id: str | None = None,
) -> AuditEvent:
    hash_prev = events[-1].hash_self if events else "0" * 64
    event_id = f"audit-{uuid.uuid4().hex}"
    payload = {
        "event_id": event_id,
        "wallet_id": wallet_id,
        "actor_did": actor_did,
        "action": action,
        "resource": resource,
        "decision": decision,
        "hash_prev": hash_prev,
        "details": details or {},
        "grant_id": grant_id,
    }
    hash_self = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    event = AuditEvent(
        event_id=event_id,
        wallet_id=wallet_id,
        actor_did=actor_did,
        action=action,
        resource=resource,
        decision=decision,
        hash_prev=hash_prev,
        hash_self=hash_self,
        details=details or {},
        grant_id=grant_id,
    )
    events.append(event)
    return event
