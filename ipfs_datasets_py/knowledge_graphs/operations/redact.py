"""Telemetry redaction for knowledge-graph operations (KGP-032).

Scrubs graph property values, raw queries, UCAN tokens, and secrets from
structured logs, metrics labels, and diagnostic payloads by default.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Dict, FrozenSet, Iterable, Optional, Set

from ipfs_datasets_py.knowledge_graphs.auth.contracts import (
    AUDIT_REDACT_KEYS,
    redact_for_audit,
)

OPERATIONS_CONTRACT_VERSION = "kg-operations/v1"

# Extra keys beyond the auth audit surface that must never leave the process.
_EXTRA_REDACT_KEYS: FrozenSet[str] = frozenset(
    {
        "ucan_token",
        "delegation",
        "proof",
        "capability_token",
        "api_key",
        "access_token",
        "refresh_token",
        "password_hash",
        "client_secret",
        "cypher",
        "sparql",
        "graphql_query",
        "query",
        "statement",
        "node_properties",
        "edge_properties",
        "vector",
        "embedding",
        "embeddings",
    }
)

REDACT_KEYS: FrozenSet[str] = frozenset(AUDIT_REDACT_KEYS) | _EXTRA_REDACT_KEYS

_SECRET_SUBSTRINGS = (
    "token",
    "secret",
    "password",
    "credential",
    "authorization",
    "bearer",
    "private_key",
    "api_key",
    "ucan",
    "signature",
)

_REDACTED = "[REDACTED]"
_TRUNCATED = "[TRUNCATED]"

# Metric / log label values are hard-bounded.
MAX_LABEL_CHARS = 128
MAX_MESSAGE_CHARS = 2_048
MAX_NESTED_DEPTH = 8
MAX_LIST_ITEMS = 64
MAX_MAP_KEYS = 64


def is_sensitive_key(key: str) -> bool:
    """Return True when *key* must be scrubbed from telemetry."""
    low = str(key).lower().strip()
    if low in REDACT_KEYS:
        return True
    return any(part in low for part in _SECRET_SUBSTRINGS)


def bound_string(value: str, *, max_chars: int = MAX_LABEL_CHARS) -> str:
    text = value if isinstance(value, str) else str(value)
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - len(_TRUNCATED))] + _TRUNCATED


def redact_value(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact sensitive structures for telemetry emission."""
    if depth > MAX_NESTED_DEPTH:
        return _TRUNCATED
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return None
        return value
    if isinstance(value, str):
        return bound_string(value, max_chars=MAX_MESSAGE_CHARS)
    if isinstance(value, bytes):
        return f"[BYTES:{len(value)}]"
    if isinstance(value, Mapping):
        return redact_mapping(value, depth=depth)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = list(value)[:MAX_LIST_ITEMS]
        out = [redact_value(item, depth=depth + 1) for item in items]
        if len(value) > MAX_LIST_ITEMS:
            out.append(f"[+{len(value) - MAX_LIST_ITEMS}_items]")
        return out
    return bound_string(repr(value), max_chars=MAX_LABEL_CHARS)


def redact_mapping(
    payload: Mapping[str, Any],
    *,
    depth: int = 0,
    extra_keys: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Return a redacted shallow-or-deep copy of *payload*."""
    if depth > MAX_NESTED_DEPTH:
        return {"truncated": True}
    extra: Set[str] = {str(k).lower() for k in (extra_keys or ())}
    out: Dict[str, Any] = {}
    for idx, (key, value) in enumerate(payload.items()):
        if idx >= MAX_MAP_KEYS:
            out["truncated_keys"] = True
            break
        ks = str(key)
        if is_sensitive_key(ks) or ks.lower() in extra:
            out[ks] = _REDACTED
            continue
        out[ks] = redact_value(value, depth=depth + 1)
    return out


def scrub_for_telemetry(
    payload: Mapping[str, Any],
    *,
    extra_keys: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Public entry: redact audit-sensitive fields then apply ops redaction.

    Uses the auth-layer :func:`redact_for_audit` first so UCAN / property /
    query surfaces stay aligned with KGP-022 receipts.
    """
    base = redact_for_audit(dict(payload))
    return redact_mapping(base, extra_keys=extra_keys)


def safe_labels(labels: Optional[Mapping[str, Any]] = None) -> Dict[str, str]:
    """Convert metric labels to string values with redaction and bounds."""
    if not labels:
        return {}
    out: Dict[str, str] = {}
    for key, value in list(labels.items())[:MAX_MAP_KEYS]:
        ks = str(key)
        if is_sensitive_key(ks):
            out[ks] = _REDACTED
            continue
        if value is None:
            out[ks] = ""
        elif isinstance(value, bool):
            out[ks] = "true" if value else "false"
        elif isinstance(value, (int, float)):
            out[ks] = bound_string(str(value), max_chars=MAX_LABEL_CHARS)
        else:
            out[ks] = bound_string(str(value), max_chars=MAX_LABEL_CHARS)
    return out


_CID_RE = re.compile(
    r"(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|b[a-z2-7]{50,120}|bagu[a-z2-7]{50,120})"
)


def looks_like_cid(value: str) -> bool:
    return bool(_CID_RE.fullmatch(value.strip()))


__all__ = [
    "OPERATIONS_CONTRACT_VERSION",
    "REDACT_KEYS",
    "bound_string",
    "is_sensitive_key",
    "looks_like_cid",
    "redact_mapping",
    "redact_value",
    "safe_labels",
    "scrub_for_telemetry",
]
