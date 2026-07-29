"""Bounded content-addressed authorization audit receipts (KGP-022).

Allow and deny outcomes for graph UCAN enforcement emit redacted,
content-addressed receipts that bind policy, revision, and request digests.
Receipts **never** embed raw UCAN tokens, signatures, graph property values,
or raw query text.

This module is transport-neutral: MCP++, Python, and CLI share the same
receipt shape when they opt into :class:`~ipfs_datasets_py.knowledge_graphs.auth.service.GraphAuthorizationService`.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Protocol, Union

from ipfs_datasets_py.knowledge_graphs.auth.contracts import (
    AUDIT_EVENT_TYPES,
    AUDIT_REDACT_KEYS,
    CONTRACT_VERSION as UCAN_CONTRACT_VERSION,
    AuthorizationReceipt,
    ChainValidationResult,
    GraphDelegationLink,
    GraphResource,
    build_authorization_receipt,
    content_digest,
    redact_for_audit,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AUDIT_MODULE_VERSION = "kg-auth-audit/v1"

# Hard bound on serialized receipt / event size (bytes of UTF-8 JSON).
DEFAULT_RECEIPT_MAX_BYTES = 16_384
DEFAULT_EVENT_MAX_BYTES = 32_768
DEFAULT_IN_MEMORY_CAP = 10_000

# Keys that may appear on the public receipt surface (bounded allow-list).
RECEIPT_PUBLIC_KEYS = frozenset(
    {
        "decision",
        "principal",
        "resource",
        "ability",
        "reason",
        "error_code",
        "policy_digest",
        "request_digest",
        "chain_digest",
        "revision_digest",
        "contract_version",
        "receipt_cid",
        "operation",
        "request_id",
        "event_type",
        "at",
        "audit_version",
    }
)

JSONDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Protocols / sinks
# ---------------------------------------------------------------------------


class AuditEmitter(Protocol):
    """Minimal sink compatible with :class:`GraphService` audit injection."""

    def emit(self, event: Mapping[str, Any]) -> None:
        ...


class NullAuditEmitter:
    """No-op emitter (default when audit is disabled)."""

    def emit(self, event: Mapping[str, Any]) -> None:
        return None


# ---------------------------------------------------------------------------
# Bounded serialization helpers
# ---------------------------------------------------------------------------


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def bound_payload(
    payload: Mapping[str, Any],
    *,
    max_bytes: int = DEFAULT_RECEIPT_MAX_BYTES,
) -> JSONDict:
    """Return a redacted, size-bounded copy of *payload*.

    If the canonical JSON exceeds *max_bytes*, nested detail maps are dropped
    and a ``truncated`` flag is set. Digests and decision fields are preserved.
    """
    safe = redact_for_audit(payload)
    raw = _canonical_json(safe)
    if len(raw.encode("utf-8")) <= max_bytes:
        return safe

    # Prefer keeping receipt core fields; strip large nested blobs.
    core: JSONDict = {}
    overflow_keys: List[str] = []
    for key, value in safe.items():
        if key in RECEIPT_PUBLIC_KEYS or key in {
            "policy_digest",
            "request_digest",
            "chain_digest",
            "revision_digest",
            "receipt_cid",
            "decision",
            "reason",
            "error_code",
            "principal",
            "resource",
            "ability",
        }:
            if isinstance(value, (dict, list)) and key not in RECEIPT_PUBLIC_KEYS:
                overflow_keys.append(key)
                continue
            core[key] = value
        elif isinstance(value, (str, int, float, bool)) or value is None:
            core[key] = value
        else:
            overflow_keys.append(str(key))

    core["truncated"] = True
    if overflow_keys:
        core["truncated_keys"] = sorted(set(overflow_keys))[:32]
    # Final hard trim of string values if still oversized.
    raw2 = _canonical_json(core)
    while len(raw2.encode("utf-8")) > max_bytes and core:
        # Drop the largest string field that is not a digest/cid.
        candidates = [
            (k, v)
            for k, v in core.items()
            if isinstance(v, str)
            and k
            not in {
                "decision",
                "receipt_cid",
                "policy_digest",
                "request_digest",
                "chain_digest",
                "revision_digest",
                "contract_version",
                "error_code",
                "reason",
                "resource",
                "ability",
                "principal",
            }
        ]
        if not candidates:
            break
        drop_key = max(candidates, key=lambda kv: len(kv[1]))[0]
        core.pop(drop_key, None)
        core.setdefault("truncated_keys", [])
        if drop_key not in core["truncated_keys"]:
            core["truncated_keys"].append(drop_key)
        raw2 = _canonical_json(core)
    return core


def revision_digest(
    revision: Optional[str],
    *,
    target_uri: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> str:
    """Content digest binding the revision (and optional target) for receipts."""
    payload: JSONDict = {
        "revision": revision,
        "target_uri": target_uri,
    }
    if extra:
        payload["extra"] = redact_for_audit(dict(extra))
    return content_digest(payload, domain="kg.ucan.revision")


def policy_revision_digest(
    *,
    policy_id: Optional[str] = None,
    policy_revision: Optional[str] = None,
    contract_version: str = UCAN_CONTRACT_VERSION,
    metadata: Optional[Mapping[str, Any]] = None,
) -> str:
    """Digest of the enforcement policy identity and revision."""
    payload: JSONDict = {
        "policy_id": policy_id,
        "policy_revision": policy_revision,
        "contract_version": contract_version,
    }
    if metadata:
        payload["metadata"] = redact_for_audit(dict(metadata))
    return content_digest(payload, domain="kg.ucan.policy")


# ---------------------------------------------------------------------------
# Enriched receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnrichedAuthorizationReceipt:
    """Authorization receipt plus revision digest and audit envelope metadata.

    The core decision fields match :class:`AuthorizationReceipt` from the
    UCAN contract. ``revision_digest`` binds the graph revision (if known) so
    allow/deny evidence cannot be reused against a different snapshot.
    """

    core: AuthorizationReceipt
    revision_digest: str
    operation: Optional[str] = None
    request_id: Optional[str] = None
    event_type: str = "ucan.allow"
    at: Optional[float] = None
    audit_version: str = AUDIT_MODULE_VERSION
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.event_type not in AUDIT_EVENT_TYPES and self.event_type not in {
            "ucan.allow",
            "ucan.deny",
        }:
            # Allow only the closed audit event types.
            object.__setattr__(
                self,
                "event_type",
                "ucan.allow" if self.core.decision == "allow" else "ucan.deny",
            )
        if self.at is None:
            object.__setattr__(self, "at", time.time())

    @property
    def decision(self) -> str:
        return self.core.decision

    @property
    def receipt_cid(self) -> str:
        return self.core.receipt_cid

    @property
    def receipt_ref(self) -> str:
        """Stable reference used by GraphService ``authorization_receipt_ref``."""
        return self.core.receipt_cid

    def to_json_dict(self, *, max_bytes: int = DEFAULT_RECEIPT_MAX_BYTES) -> JSONDict:
        body: JSONDict = {
            **self.core.to_json_dict(),
            "revision_digest": self.revision_digest,
            "operation": self.operation,
            "request_id": self.request_id,
            "event_type": self.event_type,
            "at": self.at,
            "audit_version": self.audit_version,
        }
        bounded = bound_payload(body, max_bytes=max_bytes)
        if bounded.get("truncated"):
            # Preserve truncated flag on the public surface.
            return bounded
        return bounded

    def to_audit_event(self, *, max_bytes: int = DEFAULT_EVENT_MAX_BYTES) -> JSONDict:
        """Event shape suitable for :class:`AuditEmitter` / GraphService sinks."""
        event = self.to_json_dict(max_bytes=max_bytes)
        event.setdefault("event", "ucan_authorization")
        return bound_payload(event, max_bytes=max_bytes)


def build_enriched_receipt(
    *,
    result: ChainValidationResult,
    resource: Union[GraphResource, str],
    ability: str,
    principal: Optional[str],
    policy: Optional[Mapping[str, Any]] = None,
    request: Optional[Mapping[str, Any]] = None,
    chain: Optional[Sequence[GraphDelegationLink]] = None,
    revision: Optional[str] = None,
    target_uri: Optional[str] = None,
    operation: Optional[str] = None,
    request_id: Optional[str] = None,
    now: Optional[float] = None,
) -> EnrichedAuthorizationReceipt:
    """Build a redacted, content-addressed allow/deny receipt with digests."""
    res_uri = resource if isinstance(resource, str) else resource.uri
    core = build_authorization_receipt(
        result=result,
        resource=resource,
        ability=ability,
        principal=principal,
        policy=policy,
        request=request,
        chain=chain,
    )
    rev_digest = revision_digest(revision, target_uri=target_uri or res_uri)
    event_type = "ucan.allow" if result.allowed else "ucan.deny"
    return EnrichedAuthorizationReceipt(
        core=core,
        revision_digest=rev_digest,
        operation=operation,
        request_id=request_id,
        event_type=event_type,
        at=now if now is not None else time.time(),
    )


# ---------------------------------------------------------------------------
# In-memory / composite audit log
# ---------------------------------------------------------------------------


@dataclass
class AuthorizationAuditLog:
    """Thread-safe, bounded store of authorization audit events and receipts.

    Parameters
    ----------
    max_events:
        Soft cap on retained events (oldest dropped).
    max_event_bytes:
        Per-event serialization bound after redaction.
    sink:
        Optional secondary emitter (e.g. GraphService ``InMemoryAuditSink``).
    """

    max_events: int = DEFAULT_IN_MEMORY_CAP
    max_event_bytes: int = DEFAULT_EVENT_MAX_BYTES
    sink: Optional[AuditEmitter] = None
    _events: Deque[JSONDict] = field(default_factory=deque, repr=False)
    _receipts: Dict[str, JSONDict] = field(default_factory=dict, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def emit(self, event: Mapping[str, Any]) -> None:
        """Implement :class:`AuditEmitter` — redact, bound, and retain."""
        safe = bound_payload(redact_for_audit(event), max_bytes=self.max_event_bytes)
        with self._lock:
            self._events.append(safe)
            while len(self._events) > self.max_events:
                self._events.popleft()
            cid = safe.get("receipt_cid")
            if isinstance(cid, str) and cid:
                self._receipts[cid] = safe
                # Bound receipt index roughly with event cap.
                while len(self._receipts) > self.max_events:
                    # Drop an arbitrary oldest-ish key (insertion order on 3.7+).
                    self._receipts.pop(next(iter(self._receipts)))
        if self.sink is not None:
            try:
                self.sink.emit(safe)
            except Exception:
                # Audit must never break the enforcement path.
                pass

    def record_receipt(self, receipt: EnrichedAuthorizationReceipt) -> JSONDict:
        """Record an enriched receipt and return its bounded audit event."""
        event = receipt.to_audit_event(max_bytes=self.max_event_bytes)
        self.emit(event)
        return event

    def get_receipt(self, receipt_cid: str) -> Optional[JSONDict]:
        with self._lock:
            found = self._receipts.get(receipt_cid)
            return dict(found) if found is not None else None

    def recent(self, n: int = 50) -> List[JSONDict]:
        with self._lock:
            items = list(self._events)
        if n <= 0:
            return []
        return [dict(e) for e in items[-n:]]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._receipts.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._events)


def assert_receipt_safe(payload: Mapping[str, Any]) -> None:
    """Raise ``AssertionError`` if *payload* appears to leak secrets.

    Used by tests and optional runtime checks. Scans string values for
    denylisted key names already redacted and for raw JWT-like blobs.
    """
    redacted = redact_for_audit(payload)
    blob = _canonical_json(redacted).lower()
    for needle in ("begin private key", "eyjhbGciOi".lower()):
        if needle in blob:
            raise AssertionError(f"receipt appears to leak secret material: {needle!r}")
    for key in AUDIT_REDACT_KEYS:
        # Values must not reappear as non-redacted if key path existed.
        pass
    # Ensure known sensitive keys are either absent or redacted.
    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                ks = str(k).lower()
                if ks in AUDIT_REDACT_KEYS or any(
                    n in ks for n in ("token", "secret", "password", "signature", "bearer")
                ):
                    if v != "[REDACTED]" and v is not None:
                        raise AssertionError(
                            f"sensitive key {path}.{k} is not redacted: {v!r}"
                        )
                _walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{path}[{i}]")

    _walk(payload)


__all__ = [
    "AUDIT_MODULE_VERSION",
    "DEFAULT_RECEIPT_MAX_BYTES",
    "DEFAULT_EVENT_MAX_BYTES",
    "RECEIPT_PUBLIC_KEYS",
    "AuditEmitter",
    "NullAuditEmitter",
    "EnrichedAuthorizationReceipt",
    "AuthorizationAuditLog",
    "bound_payload",
    "revision_digest",
    "policy_revision_digest",
    "build_enriched_receipt",
    "assert_receipt_safe",
    # Re-exports for a single audit import surface.
    "redact_for_audit",
    "content_digest",
    "build_authorization_receipt",
    "AuthorizationReceipt",
    "AUDIT_REDACT_KEYS",
    "AUDIT_EVENT_TYPES",
]
