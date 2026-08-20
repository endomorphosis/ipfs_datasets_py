"""Deterministic migrations into and out of CanonicalTypedBridge@1.

These migrations compose existing envelopes.  They do not invent a new logic
family, do not re-canonicalize family ASTs, and they fail closed when a
requested inverse would collapse family identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.legal_ir.canonical_contracts import (
    CANONICAL_ROUNDTRIP_IR_INTERFACE,
    CANONICAL_TYPED_BRIDGE_INTERFACE,
    CANONICAL_TYPED_BRIDGE_MIGRATION_INTERFACE,
    CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION,
    CanonicalContractError,
    CanonicalRoundTripIR,
    CanonicalTypedBridge,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_dag_json

from .canonical import (
    FORMALIZATION_ARTIFACT_SCHEMA_ID,
    LEGAL_IR_DOCUMENT_SCHEMA_ID,
    extract_canonical_ir,
    extract_formalization_artifact,
    extract_legal_ir_document,
    wrap_canonical_ir,
    wrap_formalization_artifact,
    wrap_legal_ir_document,
)
from .types import LegalIRDocument, LogicIRView


TYPED_BRIDGE_MIGRATION_SCHEMA_VERSION: Final = (
    "ipfs-datasets.canonical-typed-bridge-migration.v1"
)


class BridgeMigrationSource(str, Enum):
    CANONICAL_ROUNDTRIP_IR = "canonical_roundtrip_ir"
    LEGAL_IR_DOCUMENT = "legal_ir_document"
    FORMALIZATION_ARTIFACT = "formalization_artifact"
    TYPED_BRIDGE = "canonical_typed_bridge"


@dataclass(frozen=True, slots=True)
class TypedBridgeMigrationReceipt:
    """Content-addressed record of one deterministic envelope migration."""

    source_schema: str
    target_schema: str
    source_cid: str
    target_cid: str
    family_id: str
    lossless: bool
    notes: tuple[str, ...] = ()

    def identity_payload(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "interface": CANONICAL_TYPED_BRIDGE_MIGRATION_INTERFACE,
            "lossless": self.lossless,
            "notes": list(self.notes),
            "schema_version": TYPED_BRIDGE_MIGRATION_SCHEMA_VERSION,
            "source_cid": self.source_cid,
            "source_schema": self.source_schema,
            "target_cid": self.target_cid,
            "target_schema": self.target_schema,
        }

    @property
    def receipt_cid(self) -> str:
        return cid_for_dag_json(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "receipt_cid": self.receipt_cid}


def _receipt(
    *,
    source_schema: str,
    target_schema: str,
    source_cid: str,
    target_cid: str,
    family_id: str,
    lossless: bool,
    notes: tuple[str, ...] = (),
) -> TypedBridgeMigrationReceipt:
    return TypedBridgeMigrationReceipt(
        source_schema=source_schema,
        target_schema=target_schema,
        source_cid=source_cid,
        target_cid=target_cid,
        family_id=family_id,
        lossless=lossless,
        notes=notes,
    )


def migrate_canonical_ir(
    ir: CanonicalRoundTripIR | Mapping[str, Any],
    *,
    family_id: str = "canonical_roundtrip",
    source_text: str = "",
) -> tuple[CanonicalTypedBridge, TypedBridgeMigrationReceipt]:
    """Migrate CanonicalRoundTripIR into the typed bridge."""

    canonical = ir if isinstance(ir, CanonicalRoundTripIR) else CanonicalRoundTripIR.from_dict(ir)
    bridge = wrap_canonical_ir(canonical, family_id=family_id, source_text=source_text)
    return bridge, _receipt(
        source_schema=CANONICAL_ROUNDTRIP_IR_INTERFACE,
        target_schema=CANONICAL_TYPED_BRIDGE_INTERFACE,
        source_cid=canonical.ir_cid,
        target_cid=bridge.bridge_cid,
        family_id=family_id,
        lossless=True,
        notes=("canonical IR payload is retained as a named view",),
    )


def migrate_legal_ir_document(
    document: LegalIRDocument | Mapping[str, Any],
    *,
    family_id: str = "legal",
    adapter_name: str = "",
) -> tuple[CanonicalTypedBridge, TypedBridgeMigrationReceipt]:
    """Migrate LegalIRDocument into the typed bridge."""

    if isinstance(document, Mapping):
        views = {
            name: LogicIRView(
                name=str(item.get("name") or name),
                payload=item.get("payload") or {},
                format=str(item.get("format") or ""),
                source_component=str(item.get("source_component") or ""),
                metadata=item.get("metadata") or {},
            )
            for name, item in (document.get("views") or {}).items()
            if isinstance(item, Mapping)
        }
        document = LegalIRDocument(
            document_id=str(document.get("document_id") or ""),
            source_text=str(document.get("source_text") or ""),
            normalized_text=str(document.get("normalized_text") or ""),
            source=str(document.get("source") or "us_code"),
            citation=document.get("citation"),
            views=views,
            frame_logic_triples=tuple(document.get("frame_logic_triples") or ()),
            metadata=document.get("metadata") or {},
            version=str(document.get("version") or "legal-ir-bridge-v1"),
        )
    bridge = wrap_legal_ir_document(
        document,
        family_id=family_id,
        adapter_name=adapter_name,
    )
    return bridge, _receipt(
        source_schema=LEGAL_IR_DOCUMENT_SCHEMA_ID,
        target_schema=CANONICAL_TYPED_BRIDGE_INTERFACE,
        source_cid=document.canonical_hash(),
        target_cid=bridge.bridge_cid,
        family_id=family_id,
        lossless=True,
        notes=("LegalIRDocument remains a distinct view, not a CanonicalRoundTripIR alias",),
    )


def migrate_formalization_artifact(
    artifact: Mapping[str, Any],
    *,
    family_id: str | None = None,
    adapter_name: str = "",
) -> tuple[CanonicalTypedBridge, TypedBridgeMigrationReceipt]:
    """Migrate a FormalizationArtifact payload into the typed bridge."""

    bridge = wrap_formalization_artifact(
        artifact,
        family_id=family_id,
        adapter_name=adapter_name,
    )
    source_cid = str(artifact.get("digest") or artifact.get("declaration_digest") or "")
    if not source_cid:
        source_cid = cid_for_dag_json(dict(artifact))
    return bridge, _receipt(
        source_schema=FORMALIZATION_ARTIFACT_SCHEMA_ID,
        target_schema=CANONICAL_TYPED_BRIDGE_INTERFACE,
        source_cid=source_cid,
        target_cid=bridge.bridge_cid,
        family_id=bridge.family_identity.family_id,
        lossless=True,
        notes=("FormalizationArtifact remains a distinct view",),
    )


def migrate_identity(
    bridge: CanonicalTypedBridge,
) -> tuple[CanonicalTypedBridge, TypedBridgeMigrationReceipt]:
    """No-op v1 identity migration used to pin schema stability."""

    restored = CanonicalTypedBridge.from_dict(bridge.to_dict())
    if restored.bridge_cid != bridge.bridge_cid:
        raise CanonicalContractError("typed bridge identity migration drifted")
    return restored, _receipt(
        source_schema=CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION,
        target_schema=CANONICAL_TYPED_BRIDGE_SCHEMA_VERSION,
        source_cid=bridge.bridge_cid,
        target_cid=restored.bridge_cid,
        family_id=bridge.family_identity.family_id,
        lossless=True,
        notes=("v1 identity migration",),
    )


def export_canonical_ir(
    bridge: CanonicalTypedBridge,
) -> tuple[CanonicalRoundTripIR, TypedBridgeMigrationReceipt]:
    """Export the retained CanonicalRoundTripIR view."""

    ir = extract_canonical_ir(bridge)
    return ir, _receipt(
        source_schema=CANONICAL_TYPED_BRIDGE_INTERFACE,
        target_schema=CANONICAL_ROUNDTRIP_IR_INTERFACE,
        source_cid=bridge.bridge_cid,
        target_cid=ir.ir_cid,
        family_id=bridge.family_identity.family_id,
        lossless=True,
        notes=("export retains the original canonical IR CID",),
    )


def export_legal_ir_document(
    bridge: CanonicalTypedBridge,
) -> tuple[dict[str, Any], TypedBridgeMigrationReceipt]:
    """Export the retained LegalIRDocument payload."""

    payload = extract_legal_ir_document(bridge)
    return payload, _receipt(
        source_schema=CANONICAL_TYPED_BRIDGE_INTERFACE,
        target_schema=LEGAL_IR_DOCUMENT_SCHEMA_ID,
        source_cid=bridge.bridge_cid,
        target_cid=cid_for_dag_json(payload),
        family_id=bridge.family_identity.family_id,
        lossless=True,
        notes=("export retains the LegalIRDocument payload",),
    )


def export_formalization_artifact(
    bridge: CanonicalTypedBridge,
) -> tuple[dict[str, Any], TypedBridgeMigrationReceipt]:
    """Export the retained FormalizationArtifact payload."""

    payload = extract_formalization_artifact(bridge)
    return payload, _receipt(
        source_schema=CANONICAL_TYPED_BRIDGE_INTERFACE,
        target_schema=FORMALIZATION_ARTIFACT_SCHEMA_ID,
        source_cid=bridge.bridge_cid,
        target_cid=str(payload.get("digest") or cid_for_dag_json(payload)),
        family_id=bridge.family_identity.family_id,
        lossless=True,
        notes=("export retains the FormalizationArtifact payload",),
    )


def migrate_from_source(
    source: BridgeMigrationSource,
    payload: Any,
    **kwargs: Any,
) -> tuple[CanonicalTypedBridge, TypedBridgeMigrationReceipt]:
    """Dispatch a source envelope into the typed bridge."""

    if source is BridgeMigrationSource.CANONICAL_ROUNDTRIP_IR:
        return migrate_canonical_ir(payload, **kwargs)
    if source is BridgeMigrationSource.LEGAL_IR_DOCUMENT:
        return migrate_legal_ir_document(payload, **kwargs)
    if source is BridgeMigrationSource.FORMALIZATION_ARTIFACT:
        return migrate_formalization_artifact(payload, **kwargs)
    if source is BridgeMigrationSource.TYPED_BRIDGE:
        if not isinstance(payload, CanonicalTypedBridge):
            payload = CanonicalTypedBridge.from_dict(payload)
        return migrate_identity(payload)
    raise CanonicalContractError(f"unsupported migration source: {source!r}")


__all__ = [
    "BridgeMigrationSource",
    "TYPED_BRIDGE_MIGRATION_SCHEMA_VERSION",
    "TypedBridgeMigrationReceipt",
    "export_canonical_ir",
    "export_formalization_artifact",
    "export_legal_ir_document",
    "migrate_canonical_ir",
    "migrate_formalization_artifact",
    "migrate_from_source",
    "migrate_identity",
    "migrate_legal_ir_document",
]
