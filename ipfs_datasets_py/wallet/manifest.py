"""Deterministic serialization helpers for wallet manifests."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def canonical_dumps(value: Any) -> str:
    """Serialize *value* with stable ordering and compact separators."""

    return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_bytes(value: Any) -> bytes:
    return canonical_dumps(value).encode("utf-8")
