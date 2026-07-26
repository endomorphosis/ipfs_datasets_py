"""Deterministic serialization for Intent IR artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .schema import IntentIRDocument, validate_intent_ir


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def canonical_intent_ir_json(document: IntentIRDocument) -> str:
    """Return stable, compact JSON for a validated Intent IR document."""

    validated = validate_intent_ir(document)
    return json.dumps(
        _normalize(validated.to_dict()),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_intent_ir_bytes(document: IntentIRDocument) -> bytes:
    """Return canonical UTF-8 bytes for content addressing."""

    return canonical_intent_ir_json(document).encode("utf-8")


def intent_ir_sha256(document: IntentIRDocument) -> str:
    """Return the canonical Intent IR digest as ``sha256:<hex>``."""

    digest = hashlib.sha256(canonical_intent_ir_bytes(document)).hexdigest()
    return f"sha256:{digest}"


__all__ = [
    "canonical_intent_ir_bytes",
    "canonical_intent_ir_json",
    "intent_ir_sha256",
]
