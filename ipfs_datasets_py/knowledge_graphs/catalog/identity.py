"""Identity and request validation helpers for the graph catalog."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from .errors import CatalogError

# Align with GraphTarget / revision-manifest slug and id rules.
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,62}[a-z0-9])?$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_HOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")

STORAGE_PROFILES = frozenset({"parquet", "ipfs_ipld", "ipfs_kit", "hybrid"})
DEFAULT_BRANCH = "main"
DEFAULT_STORAGE_PROFILE = "parquet"
DEFAULT_GRAPH_KIND = "generic"
BOOTSTRAP_REVISION_PREFIX = "kg-bootstrap"


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp with millisecond precision."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def parse_iso_utc(value: str) -> datetime:
    """Parse catalog timestamps (Z or offset) into aware UTC datetimes."""
    if not value or not isinstance(value, str):
        raise CatalogError("INVALID_REQUEST", "timestamp must be a non-empty string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CatalogError(
            "INVALID_REQUEST",
            f"invalid timestamp: {value!r}",
            details={"value": value},
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_expired(expires_at: str, *, now: Optional[datetime] = None) -> bool:
    current = now or datetime.now(timezone.utc)
    return parse_iso_utc(expires_at) <= current


def require_slug(value: Any, *, field: str) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        code = "INVALID_TARGET"
        if field == "tenant":
            raise CatalogError(code, "tenant must be non-empty", details={"field": field})
        if field == "graph_id":
            raise CatalogError(code, "graph_id must be non-empty", details={"field": field})
        raise CatalogError(code, f"{field} must be non-empty", details={"field": field})
    if not isinstance(value, str):
        raise CatalogError(
            "INVALID_TARGET",
            f"{field} must be a string",
            details={"field": field},
        )
    if value != value.strip():
        raise CatalogError(
            "INVALID_TARGET",
            f"{field} must not have surrounding whitespace",
            details={"field": field, "value": value},
        )
    if not _SLUG_RE.fullmatch(value):
        raise CatalogError(
            "INVALID_TARGET",
            f"{field} failed slug validation",
            details={"field": field, "value": value},
        )
    return value


def require_revision_id(value: Any, *, field: str = "revision_id") -> str:
    if value is None or not isinstance(value, str) or not value:
        raise CatalogError(
            "INVALID_REQUEST",
            f"{field} must be a non-empty string",
            details={"field": field},
        )
    if not _REVISION_RE.fullmatch(value):
        raise CatalogError(
            "INVALID_REQUEST",
            f"{field} failed revision id validation",
            details={"field": field, "value": value},
        )
    return value


def optional_revision_id(value: Any, *, field: str = "revision_id") -> Optional[str]:
    if value is None:
        return None
    return require_revision_id(value, field=field)


def require_storage_profile(value: Any) -> str:
    if value is None:
        return DEFAULT_STORAGE_PROFILE
    if not isinstance(value, str) or value not in STORAGE_PROFILES:
        raise CatalogError(
            "INVALID_TARGET",
            f"storage_profile must be one of {sorted(STORAGE_PROFILES)}",
            details={"value": value},
        )
    return value


def require_graph_kind(value: Any) -> str:
    if value is None:
        return DEFAULT_GRAPH_KIND
    return require_slug(value, field="graph_kind")


def require_idempotency_key(value: Any) -> str:
    if value is None or not isinstance(value, str) or not (1 <= len(value) <= 128):
        raise CatalogError(
            "INVALID_REQUEST",
            "idempotency_key must be a string of length 1–128",
            details={"value": value},
        )
    if not _KEY_RE.fullmatch(value):
        raise CatalogError(
            "INVALID_REQUEST",
            "idempotency_key failed character validation",
            details={"value": value},
        )
    return value


def require_holder(value: Any) -> str:
    if value is None or not isinstance(value, str) or not value:
        raise CatalogError("INVALID_REQUEST", "lease holder must be a non-empty string")
    if not _HOLDER_RE.fullmatch(value):
        raise CatalogError(
            "INVALID_REQUEST",
            "lease holder failed character validation",
            details={"value": value},
        )
    return value


def require_lease_id(value: Any) -> str:
    if value is None or not isinstance(value, str) or not value:
        raise CatalogError("INVALID_REQUEST", "lease_id must be a non-empty string")
    if not _KEY_RE.fullmatch(value):
        raise CatalogError(
            "INVALID_REQUEST",
            "lease_id failed character validation",
            details={"value": value},
        )
    return value


def require_positive_ttl(ttl_seconds: Any) -> float:
    try:
        ttl = float(ttl_seconds)
    except (TypeError, ValueError) as exc:
        raise CatalogError(
            "INVALID_REQUEST",
            "ttl_seconds must be a positive number",
            details={"value": ttl_seconds},
        ) from exc
    if not (ttl > 0.0) or ttl != ttl:  # NaN check
        raise CatalogError(
            "INVALID_REQUEST",
            "ttl_seconds must be a positive number",
            details={"value": ttl_seconds},
        )
    return ttl


def new_lease_id() -> str:
    return f"lease-{uuid.uuid4().hex}"


def new_pin_id() -> str:
    return f"pin-{uuid.uuid4().hex}"


def bootstrap_revision_id(tenant: str, graph_id: str) -> str:
    """Deterministic empty/bootstrap revision id for a graph identity."""
    digest = hashlib.sha256(
        f"{BOOTSTRAP_REVISION_PREFIX}|{tenant}|{graph_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"{BOOTSTRAP_REVISION_PREFIX}-{digest}"


def request_hash(payload: Mapping[str, Any]) -> str:
    """Stable SHA-256 of a canonical JSON request body."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def expires_at_from_ttl(ttl_seconds: float, *, now: Optional[datetime] = None) -> str:
    base = now or datetime.now(timezone.utc)
    # Use time module addition via timestamp for float seconds.
    ts = base.timestamp() + float(ttl_seconds)
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def monotonic_ns() -> int:
    return time.time_ns()


__all__ = [
    "STORAGE_PROFILES",
    "DEFAULT_BRANCH",
    "DEFAULT_STORAGE_PROFILE",
    "DEFAULT_GRAPH_KIND",
    "BOOTSTRAP_REVISION_PREFIX",
    "utc_now_iso",
    "parse_iso_utc",
    "is_expired",
    "require_slug",
    "require_revision_id",
    "optional_revision_id",
    "require_storage_profile",
    "require_graph_kind",
    "require_idempotency_key",
    "require_holder",
    "require_lease_id",
    "require_positive_ttl",
    "new_lease_id",
    "new_pin_id",
    "bootstrap_revision_id",
    "request_hash",
    "expires_at_from_ttl",
    "monotonic_ns",
]
