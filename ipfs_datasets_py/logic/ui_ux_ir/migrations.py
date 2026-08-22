"""Explicit ui-ux-ir/v0.1 → ui-ux-ir/v1 migration.

Legacy documents cannot be decoded directly; callers must migrate first.
Migration is loss-aware and never invents interface CIDs or execution grants.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from .decoder import UIIRDecodeError, decode_ui_ir
from .schema import (
    LEGACY_UI_UX_IR_SCHEMA_VERSION,
    UI_UX_IR_SCHEMA_VERSION,
    UIIR_DOCUMENT_FIELDS,
    UIIR_REQUIRED_PATHS,
    UIIRDocument,
    UIIRValidationError,
)


UI_UX_IR_V0_1_TO_V1_MIGRATION_ID = "ui-ux-ir-v0.1-to-v1"


class MigrationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class MigrationDiagnostic:
    code: str
    path: str
    message: str
    severity: MigrationSeverity = MigrationSeverity.INFO
    lossy: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "lossy": self.lossy,
            "message": self.message,
            "path": self.path,
            "severity": self.severity.value,
        }


@dataclass(frozen=True, slots=True)
class UIIRMigrationResult:
    document: UIIRDocument
    source_version: str
    target_version: str
    diagnostics: tuple[MigrationDiagnostic, ...] = ()
    migration_id: str = UI_UX_IR_V0_1_TO_V1_MIGRATION_ID

    @property
    def loss_diagnostics(self) -> tuple[MigrationDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.lossy)

    @property
    def is_lossless(self) -> bool:
        return not self.loss_diagnostics

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document.document_id,
            "is_lossless": self.is_lossless,
            "migration_id": self.migration_id,
            "source_version": self.source_version,
            "target_version": self.target_version,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "lossy_count": len(self.loss_diagnostics),
        }


def _parse_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception as exc:  # noqa: BLE001
            raise UIIRDecodeError(f"payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise UIIRDecodeError("document payload must be a mapping")
    return dict(payload)


def _ensure_list(raw: dict[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    if value is None:
        raw[key] = []
        return raw[key]
    if not isinstance(value, list):
        raise UIIRDecodeError(f"{key} must be an array when present")
    return value


def migrate_ui_ir_payload(payload: Any) -> tuple[dict[str, Any], list[MigrationDiagnostic]]:
    """Return a v1 wire payload + diagnostics (does not decode)."""
    raw = _parse_payload(payload)
    version = str(raw.get("schema_version") or "")
    diagnostics: list[MigrationDiagnostic] = []

    if version == UI_UX_IR_SCHEMA_VERSION:
        diagnostics.append(
            MigrationDiagnostic(
                code="already_v1",
                path="$.schema_version",
                message="Document already declares ui-ux-ir/v1",
                severity=MigrationSeverity.INFO,
            )
        )
        return raw, diagnostics

    if version != LEGACY_UI_UX_IR_SCHEMA_VERSION:
        raise UIIRDecodeError(
            f"Unsupported schema_version for migration {version!r}; "
            f"expected {LEGACY_UI_UX_IR_SCHEMA_VERSION!r} or {UI_UX_IR_SCHEMA_VERSION!r}"
        )

    migrated = dict(raw)
    migrated["schema_version"] = UI_UX_IR_SCHEMA_VERSION
    diagnostics.append(
        MigrationDiagnostic(
            code="schema_version_upgraded",
            path="$.schema_version",
            message=f"Upgraded {LEGACY_UI_UX_IR_SCHEMA_VERSION} → {UI_UX_IR_SCHEMA_VERSION}",
            severity=MigrationSeverity.INFO,
        )
    )

    # Required path presence (legacy may omit empty collections).
    for path in UIIR_REQUIRED_PATHS:
        if path not in migrated:
            if path in {
                "sources",
                "components",
                "entry_components",
                "terminal_outcomes",
            }:
                raise UIIRDecodeError(
                    f"Legacy document missing required path {path!r}; cannot migrate"
                )
            migrated[path] = "" if path in {"title", "document_id"} else []
            diagnostics.append(
                MigrationDiagnostic(
                    code="defaulted_required_path",
                    path=f"$.{path}",
                    message=f"Defaulted missing required path {path}",
                    severity=MigrationSeverity.WARNING,
                    lossy=True,
                )
            )

    # Closed v1 collections: default empty when absent.
    for field_name in UIIR_DOCUMENT_FIELDS:
        if field_name in migrated:
            continue
        if field_name in {
            "schema_version",
            "document_id",
            "title",
            "producer",
            "configuration",
        }:
            if field_name in {"producer", "configuration"}:
                migrated[field_name] = None
            continue
        if field_name == "locale_defaults":
            migrated[field_name] = {
                "default_locale": "en",
                "fallback_locales": [],
                "text_direction": "ltr",
            }
            diagnostics.append(
                MigrationDiagnostic(
                    code="defaulted_locale_defaults",
                    path="$.locale_defaults",
                    message="v0.1 lacked locale_defaults; applied en/ltr defaults",
                    severity=MigrationSeverity.INFO,
                    lossy=False,
                )
            )
            continue
        if field_name == "review":
            migrated[field_name] = {
                "review_status": "unreviewed",
                "reviewer": "",
                "notes": "migrated from ui-ux-ir/v0.1",
            }
            diagnostics.append(
                MigrationDiagnostic(
                    code="defaulted_review",
                    path="$.review",
                    message="v0.1 lacked review binding; marked unreviewed",
                    severity=MigrationSeverity.WARNING,
                    lossy=True,
                )
            )
            continue
        # Collection defaults
        migrated[field_name] = []
        diagnostics.append(
            MigrationDiagnostic(
                code="defaulted_collection",
                path=f"$.{field_name}",
                message=f"v0.1 lacked {field_name}; defaulted to empty collection",
                severity=MigrationSeverity.INFO,
            )
        )

    # Strip unknown top-level keys (lossy when present).
    unknown = sorted(k for k in list(migrated.keys()) if k not in UIIR_DOCUMENT_FIELDS)
    for key in unknown:
        migrated.pop(key, None)
        diagnostics.append(
            MigrationDiagnostic(
                code="dropped_unknown_field",
                path=f"$.{key}",
                message=f"Dropped non-v1 field {key!r} during migration",
                severity=MigrationSeverity.WARNING,
                lossy=True,
            )
        )

    # Normalize list types for required collections
    for key in (
        "sources",
        "components",
        "entry_components",
        "terminal_outcomes",
        "tags",
    ):
        _ensure_list(migrated, key)

    # v0.1 often used interface_cid aliases — keep values but never invent.
    for binding in migrated.get("mcp_idl_bindings") or []:
        if isinstance(binding, dict) and "interface_cid" not in binding:
            binding["interface_cid"] = ""
            diagnostics.append(
                MigrationDiagnostic(
                    code="defaulted_interface_cid",
                    path="$.mcp_idl_bindings",
                    message="Defaulted missing interface_cid to empty (never forged)",
                    severity=MigrationSeverity.INFO,
                )
            )

    return migrated, diagnostics


def migrate_ui_ir(payload: Any) -> UIIRMigrationResult:
    """Migrate legacy payload and decode to a validated v1 document."""
    raw = _parse_payload(payload)
    version = str(raw.get("schema_version") or "")
    if version == UI_UX_IR_SCHEMA_VERSION:
        document = decode_ui_ir(raw)
        return UIIRMigrationResult(
            document=document,
            source_version=version,
            target_version=UI_UX_IR_SCHEMA_VERSION,
            diagnostics=(
                MigrationDiagnostic(
                    code="already_v1",
                    path="$.schema_version",
                    message="No migration required",
                ),
            ),
        )
    migrated, diagnostics = migrate_ui_ir_payload(raw)
    try:
        document = decode_ui_ir(migrated)
    except UIIRValidationError as exc:
        raise UIIRDecodeError(
            f"Migrated payload failed v1 validation: {exc}"
        ) from exc
    return UIIRMigrationResult(
        document=document,
        source_version=LEGACY_UI_UX_IR_SCHEMA_VERSION,
        target_version=UI_UX_IR_SCHEMA_VERSION,
        diagnostics=tuple(diagnostics),
    )


def decode_ui_ir_with_migration(payload: Any) -> UIIRMigrationResult:
    """Decode v1 directly or migrate v0.1 then decode."""
    raw = _parse_payload(payload)
    version = str(raw.get("schema_version") or "")
    if version == UI_UX_IR_SCHEMA_VERSION:
        return migrate_ui_ir(raw)
    if version == LEGACY_UI_UX_IR_SCHEMA_VERSION:
        return migrate_ui_ir(raw)
    raise UIIRDecodeError(
        f"Unsupported schema_version {version!r}; expected "
        f"{UI_UX_IR_SCHEMA_VERSION!r} or {LEGACY_UI_UX_IR_SCHEMA_VERSION!r}"
    )


__all__ = [
    "MigrationDiagnostic",
    "MigrationSeverity",
    "UI_UX_IR_V0_1_TO_V1_MIGRATION_ID",
    "UIIRMigrationResult",
    "decode_ui_ir_with_migration",
    "migrate_ui_ir",
    "migrate_ui_ir_payload",
]
