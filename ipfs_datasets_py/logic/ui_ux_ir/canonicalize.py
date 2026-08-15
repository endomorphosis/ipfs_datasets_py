"""Deterministic canonical bytes for UI/UX IR declarations (UIR-011)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .schema import UIIRDocument, UIIRValidationError, UI_UX_IR_SCHEMA_VERSION


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    return value


def canonicalize_ui_ir(document: UIIRDocument | Mapping[str, Any]) -> bytes:
    """Return deterministic UTF-8 JSON bytes for a validated declaration.

    Canonical identity is independent of optional CID availability. Set-like
    collections are ordered by their declared member keys in the schema layer
    before serialization; ordered collections retain document order.
    """

    if isinstance(document, UIIRDocument):
        payload = document.to_dict()
    elif isinstance(document, Mapping):
        payload = dict(document)
    else:
        raise UIIRValidationError("canonicalize_ui_ir expects a UIIRDocument or mapping")
    version = str(payload.get("schema_version") or "")
    if version and version != UI_UX_IR_SCHEMA_VERSION:
        raise UIIRValidationError(
            f"Cannot canonicalize unsupported schema_version {version!r}; "
            f"expected {UI_UX_IR_SCHEMA_VERSION!r}"
        )
    text = json.dumps(
        _normalize(payload),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return text.encode("utf-8")


def ui_ir_sha256(document: UIIRDocument | Mapping[str, Any]) -> str:
    """Return ``sha256:<hex>`` for the canonical declaration bytes."""

    digest = hashlib.sha256(canonicalize_ui_ir(document)).hexdigest()
    return f"sha256:{digest}"


__all__ = ["canonicalize_ui_ir", "ui_ir_sha256"]
