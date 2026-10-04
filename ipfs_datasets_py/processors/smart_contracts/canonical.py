"""Deterministic JSON encoding and identity helpers for smart-contract records.

The canonical form is deliberately smaller than a general-purpose object
encoder.  Smart-contract processor records are a long-lived interchange
boundary, so values which are ambiguous across JSON implementations (binary
floats, naive datetimes, bytes, sets, and non-string mapping keys) are rejected
instead of being silently coerced.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any


CANONICAL_IDENTITY_VERSION = "smart-contract-canonical-identity-v1"


class CanonicalEncodingError(ValueError):
    """Raised when a value cannot be represented by the smart-contract JSON profile."""


def format_datetime(value: datetime) -> str:
    """Return a fixed-width UTC RFC 3339 timestamp.

    Fixed microsecond precision avoids two encodings for the same instant.
    """

    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalEncodingError("datetimes must be timezone-aware")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def canonical_value(value: Any) -> Any:
    """Convert *value* to the strict, deterministic smart-contract JSON value set."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise CanonicalEncodingError(
            "binary floats are forbidden; use exact base-unit integers"
        )
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise CanonicalEncodingError(
            "raw bytes are forbidden; use a digest or CID reference"
        )
    if isinstance(value, datetime):
        return format_datetime(value)
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return canonical_value(value.to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return canonical_value(
            {item.name: getattr(value, item.name) for item in fields(value)}
        )
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalEncodingError("JSON mapping keys must be strings")
            result[key] = canonical_value(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [canonical_value(item) for item in value]
    raise CanonicalEncodingError(
        f"unsupported canonical JSON value: {type(value).__name__}"
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Encode *value* as compact UTF-8 JSON with lexicographically sorted keys."""

    try:
        encoded = json.dumps(
            canonical_value(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, CanonicalEncodingError):
            raise
        raise CanonicalEncodingError(str(exc)) from exc
    return encoded.encode("utf-8")


def canonical_json(value: Any) -> str:
    """Return the canonical smart-contract JSON encoding as text."""

    return canonical_json_bytes(value).decode("utf-8")


def content_digest(value: Any) -> str:
    """Return a tagged SHA-256 digest of a canonical value."""

    return f"sha256:{sha256(canonical_json_bytes(value)).hexdigest()}"


def deterministic_id(record_type: str, identity: Mapping[str, Any]) -> str:
    """Build a stable ID from semantic acquisition coordinates.

    Callers must omit observations such as provider pagination, fetch time,
    finality, and mutable metadata from ``identity``.
    """

    if not record_type or not record_type.strip():
        raise CanonicalEncodingError("record_type must not be empty")
    payload = {
        "identity_schema": CANONICAL_IDENTITY_VERSION,
        "record_type": record_type,
        "identity": identity,
    }
    digest = sha256(canonical_json_bytes(payload)).hexdigest()
    return f"urn:smart-contract:{record_type}:sha256:{digest}"


def freeze_json(value: Any) -> Any:
    """Recursively freeze a canonical JSON-compatible value."""

    canonical = canonical_value(value)
    if isinstance(canonical, dict):
        return MappingProxyType(
            {key: freeze_json(item) for key, item in canonical.items()}
        )
    if isinstance(canonical, list):
        return tuple(freeze_json(item) for item in canonical)
    return canonical


def thaw_json(value: Any) -> Any:
    """Return mutable JSON containers for a recursively frozen value."""

    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


__all__ = [
    "CANONICAL_IDENTITY_VERSION",
    "CanonicalEncodingError",
    "canonical_json",
    "canonical_json_bytes",
    "canonical_value",
    "content_digest",
    "deterministic_id",
    "format_datetime",
    "freeze_json",
    "thaw_json",
]
