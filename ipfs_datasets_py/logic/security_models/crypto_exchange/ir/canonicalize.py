"""Deterministic canonicalization for security IR artifacts."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .schema import SecurityModelIR, json_ready, validate_ir


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def canonicalize_ir_json(model: SecurityModelIR | Mapping[str, Any]) -> str:
    """Serialize a security model with stable key ordering."""

    normalized = validate_ir(model)
    payload = _normalize(json_ready(normalized))
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def canonicalize_ir(model: SecurityModelIR | Mapping[str, Any]) -> bytes:
    """Return canonical UTF-8 bytes for a security model."""

    return canonicalize_ir_json(model).encode('utf-8')
