"""Deterministic serialization for UI/UX IR artifacts.

Canonical identity is independent of optional CID availability and matches the
SwissKnife TypeScript codec (``canonicalizeUiIr``).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .schema import (
    UI_UX_IR_SCHEMA_VERSION,
    UIIRDocument,
    UIIRValidationError,
    validate_ui_ir,
)


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


def ui_ir_to_dict(document: UIIRDocument | Mapping[str, Any]) -> dict[str, Any]:
    """Emit the closed envelope payload (TypeScript ``uiIrToDict`` parity)."""
    if isinstance(document, UIIRDocument):
        return document.to_dict()
    # Mapping path: decode/validate first so closed fields are complete.
    from .decoder import decode_ui_ir

    return decode_ui_ir(document).to_dict()


def canonicalize_ui_ir_json(document: UIIRDocument | Mapping[str, Any]) -> str:
    """Return stable, compact JSON for a validated UI/UX IR document."""
    if isinstance(document, UIIRDocument):
        validated = validate_ui_ir(document)
        payload = validated.to_dict()
    elif isinstance(document, Mapping):
        # Allow already-normalized closed dicts used during identity checks.
        version = str(document.get("schema_version") or "")
        if version and version != UI_UX_IR_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Cannot canonicalize unsupported schema_version {version!r}; "
                f"expected {UI_UX_IR_SCHEMA_VERSION!r}"
            )
        # Prefer full decode when possible for cross-field defaults.
        try:
            from .decoder import decode_ui_ir

            payload = decode_ui_ir(document).to_dict()
        except Exception:
            payload = dict(document)
            if str(payload.get("schema_version") or "") != UI_UX_IR_SCHEMA_VERSION:
                raise
    else:
        raise UIIRValidationError("document must be UIIRDocument or mapping")

    version = str(payload.get("schema_version") or "")
    if version and version != UI_UX_IR_SCHEMA_VERSION:
        raise UIIRValidationError(
            f"Cannot canonicalize unsupported schema_version {version!r}; "
            f"expected {UI_UX_IR_SCHEMA_VERSION!r}"
        )
    return json.dumps(
        _normalize(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonicalize_ui_ir(document: UIIRDocument | Mapping[str, Any]) -> bytes:
    """Return canonical UTF-8 bytes for content addressing."""
    return canonicalize_ui_ir_json(document).encode("utf-8")


# Public aliases (TypeScript / snake_case parity)
canonicalize_uiir = canonicalize_ui_ir
canonical_ui_ir_bytes = canonicalize_ui_ir
canonical_ui_ir_json = canonicalize_ui_ir_json


def ui_ir_sha256(document: UIIRDocument | Mapping[str, Any]) -> str:
    """Return the canonical UI/UX IR digest as ``sha256:<hex>``."""
    digest = hashlib.sha256(canonicalize_ui_ir(document)).hexdigest()
    return f"sha256:{digest}"


def ui_ir_identity(
    document: UIIRDocument | Mapping[str, Any],
) -> dict[str, Any]:
    """Convenience: schema version + digest + byte length."""
    raw = canonicalize_ui_ir(document)
    return {
        "schema_version": UI_UX_IR_SCHEMA_VERSION,
        "digest": f"sha256:{hashlib.sha256(raw).hexdigest()}",
        "byte_length": len(raw),
    }


__all__ = [
    "canonical_ui_ir_bytes",
    "canonical_ui_ir_json",
    "canonicalize_ui_ir",
    "canonicalize_ui_ir_json",
    "canonicalize_uiir",
    "ui_ir_identity",
    "ui_ir_sha256",
    "ui_ir_to_dict",
]
