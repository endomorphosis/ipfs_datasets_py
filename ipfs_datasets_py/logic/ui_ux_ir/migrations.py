"""Deterministic UI/UX IR schema migrations (UIR-011)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final, Mapping

from .canonicalize import canonicalize_ui_ir, ui_ir_sha256
from .decoder import decode_ui_ir
from .schema import (
    LEGACY_UI_UX_IR_SCHEMA_VERSION,
    UIIRValidationError,
    UI_UX_IR_SCHEMA_VERSION,
)

V0_1_TO_V1_MIGRATION_ID: Final = "ui-ux-ir-v0.1-to-v1"


@dataclass(frozen=True, slots=True)
class MigrationReceipt:
    """Bound receipt for one deterministic migration execution."""

    migration_id: str
    source_version: str
    target_version: str
    input_digest: str
    output_digest: str
    lossy: bool
    losses: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_digest": self.input_digest,
            "lossy": self.lossy,
            "losses": list(self.losses),
            "migration_id": self.migration_id,
            "output_digest": self.output_digest,
            "source_version": self.source_version,
            "target_version": self.target_version,
        }


def _payload_digest(payload: Mapping[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def migrate_ui_ir(
    payload: Mapping[str, Any],
    *,
    target_version: str = UI_UX_IR_SCHEMA_VERSION,
) -> tuple[dict[str, Any], MigrationReceipt]:
    """Migrate a UI/UX IR payload to ``target_version`` with an explicit receipt.

    Paths are deterministic and cycle-free. Unknown versions fail closed. The
    v0.1 → v1 path is intentionally lossy only for fields that no longer exist
    in the closed v1 envelope.
    """

    if not isinstance(payload, Mapping):
        raise UIIRValidationError("migrate_ui_ir expects a mapping payload")
    source_version = str(payload.get("schema_version") or "")
    if not source_version:
        raise UIIRValidationError("Migration payload missing schema_version")
    if source_version == target_version:
        # Identity migration: re-encode through the decoder for digest stability.
        document = decode_ui_ir(payload)
        out = document.to_dict()
        digest = ui_ir_sha256(document)
        receipt = MigrationReceipt(
            migration_id="ui-ux-ir-identity",
            source_version=source_version,
            target_version=target_version,
            input_digest=digest,
            output_digest=digest,
            lossy=False,
        )
        return out, receipt
    if (
        source_version == LEGACY_UI_UX_IR_SCHEMA_VERSION
        and target_version == UI_UX_IR_SCHEMA_VERSION
    ):
        return _migrate_v0_1_to_v1(dict(payload))
    raise UIIRValidationError(
        f"No migration path from {source_version!r} to {target_version!r}"
    )


def _migrate_v0_1_to_v1(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], MigrationReceipt]:
    input_digest = _payload_digest(payload)
    losses: list[str] = []
    migrated = dict(payload)
    migrated["schema_version"] = UI_UX_IR_SCHEMA_VERSION
    # Drop known legacy-only keys with explicit loss notes.
    for legacy_key in ("legacy_widget_tree", "pixel_layout", "callback_registry"):
        if legacy_key in migrated:
            migrated.pop(legacy_key)
            losses.append(f"dropped_legacy_field:{legacy_key}")
    # Ensure required v1 collections exist.
    migrated.setdefault("composition_edges", [])
    migrated.setdefault("extensions", [])
    document = decode_ui_ir(migrated)
    out = document.to_dict()
    output_digest = ui_ir_sha256(document)
    receipt = MigrationReceipt(
        migration_id=V0_1_TO_V1_MIGRATION_ID,
        source_version=LEGACY_UI_UX_IR_SCHEMA_VERSION,
        target_version=UI_UX_IR_SCHEMA_VERSION,
        input_digest=input_digest,
        output_digest=output_digest,
        lossy=bool(losses),
        losses=tuple(losses),
    )
    return out, receipt


__all__ = [
    "MigrationReceipt",
    "V0_1_TO_V1_MIGRATION_ID",
    "migrate_ui_ir",
]
