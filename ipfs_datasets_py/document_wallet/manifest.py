"""Deterministic manifest serialization."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .crypto import sha256_ref


def normalize_for_json(value: Any) -> Any:
    """Convert dataclasses and common Python values to canonical JSON values."""

    if is_dataclass(value):
        return normalize_for_json(asdict(value))
    if isinstance(value, dict):
        return {str(key): normalize_for_json(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [normalize_for_json(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def canonical_json(value: Any) -> str:
    """Return deterministic JSON without insignificant whitespace."""

    return json.dumps(
        normalize_for_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def manifest_ref(value: Any) -> str:
    """Return a stable content reference for a manifest-like object."""

    return sha256_ref(canonical_bytes(value))

