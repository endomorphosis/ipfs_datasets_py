"""Unit tests for LogicContractMigration@1 (LFP2-009).

Acceptance:

* legacy reads diagnose aliases
* every new write is canonical
* provider / syntax / property / lane labels cannot masquerade as families
* free-form payload routing is dropped with an explicit loss receipt
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.migration_v2 import (
    DEFAULT_CONTRACT_MIGRATION,
    MIGRATION_INTERFACE,
    MIGRATION_MODULE_VERSION,
    MIGRATION_SCHEMA_VERSION,
    CanonicalWriteError,
    FieldAction,
    LogicContractMigration,
    LogicContractMigrationReceipt,
    MigrationDispositionKind,
    canonical_write_identity,
    canonical_write_request_fields,
    dual_read_identity,
    migrate_artifact,
    migrate_legacy_backend_request,
    migrate_provider_descriptor,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BACKEND_REQUEST_V2_INTERFACE,
    BackendRequestV2,
    RequestAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.aliases import MigrationDisposition
from ipfs_datasets_py.logic.families.namespaces import (
    NamespaceKind,
    encoding_id,
    evidence_id,
    notation_id,
    profile_id,
    property_id,
    view_id,
)
from ipfs_datasets_py.logic.families.providers import BASELINE_PROVIDER_CATALOG
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest as LegacyBackendRequest,
    ExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.syntax_core.contracts import content_sha256


def _digest(label: str) -> str:
    return content_sha256(label.encode("utf-8"))


def _legacy_request(
    *,
    logic_family: str = "fol",
    requested_backend_id: str = "z3",
    payload: dict | None = None,
) -> LegacyBackendRequest:
    return LegacyBackendRequest(
        request_id="req:legacy-mig",
        claim_id="claim:legacy",
        declaration_id="decl:legacy",
        claim_digest=_digest("claim:legacy"),
        obligation_id="obl:legacy",
        obligation_digest=_digest("obl:legacy"),
        assumption_ids=(),
        logic_family=logic_family,
        query_kind=QueryKind.SATISFIABILITY,
        bounds=ExecutionBounds(
            timeout_ms=1000,
            max_steps=100,
            max_memory_bytes=1024 * 1024,
            max_output_bytes=64 * 1024,
        ),
        payload=payload or {},
        requested_backend_id=requested_backend_id,
    )


def _lineage_kwargs() -> dict:
    return {
        "document_id": "doc:mig",
        "source_digest": _digest("source"),
        "expression_id": "expr:mig",
        "expression_digest": _digest("expr"),
        "profile": profile_id("qf_bv"),
        "property": property_id("satisfiability"),
        "view": view_id("source"),
        "notation": notation_id("smt_lib2"),
        "encoding": encoding_id("smt_lib2"),
        "evidence_kind": evidence_id("model"),
        "authority_ceiling": RequestAuthorityCeiling.SATISFIABILITY,
    }


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


def test_migration_interface() -> None:
    facade = DEFAULT_CONTRACT_MIGRATION
    assert facade.interface == MIGRATION_INTERFACE
    assert facade.interface == "LogicContractMigration@1"
    assert facade.schema_version == MIGRATION_SCHEMA_VERSION
    assert facade.version == MIGRATION_MODULE_VERSION
    payload = facade.to_dict()
    assert "dual_read" in payload["operations"]
    assert "canonical_write" in payload["operations"]
    assert payload["target_request_interface"] == BACKEND_REQUEST_V2_INTERFACE


# ---------------------------------------------------------------------------
# Dual-read diagnostics
# ---------------------------------------------------------------------------


def test_legacy_family_alias_dual_read_diagnoses_replacement() -> None:
    identity, diagnostic = dual_read_identity(NamespaceKind.FAMILY, "fol")
    assert identity is not None
    assert identity.value == "first_order"
    assert diagnostic.ok
    assert diagnostic.was_alias
    assert diagnostic.disposition is MigrationDisposition.REPLACED
    assert diagnostic.replacement == "first_order"


def test_legacy_protocol_dual_read() -> None:
    identity, diagnostic = dual_read_identity(NamespaceKind.FAMILY, "protocol")
    assert identity is not None
    assert identity.value == "cryptographic_protocol"
    assert diagnostic.was_alias


def test_legacy_provider_alias_dual_read_via_catalog() -> None:
    receipt = migrate_provider_descriptor({"provider_id": "tlc", "family_support": []})
    assert receipt.ok
    assert receipt.canonical_payload["provider_id"] == "tla_tlc"
    assert any(record.was_alias for record in receipt.field_records)


def test_provider_cannot_dual_read_as_family() -> None:
    identity, diagnostic = dual_read_identity(NamespaceKind.FAMILY, "z3")
    assert identity is None
    assert not diagnostic.ok
    assert diagnostic.error_code in {"family_masquerade", "wrong_namespace", "unknown_label"}


def test_syntax_cannot_dual_read_as_family() -> None:
    identity, diagnostic = dual_read_identity(NamespaceKind.FAMILY, "smt")
    assert identity is None
    assert not diagnostic.ok


def test_property_cannot_dual_read_as_family() -> None:
    identity, diagnostic = dual_read_identity(NamespaceKind.FAMILY, "safety")
    assert identity is None
    assert not diagnostic.ok


def test_lane_cannot_dual_read_as_family() -> None:
    identity, diagnostic = dual_read_identity(NamespaceKind.FAMILY, "runtime")
    assert identity is None
    assert not diagnostic.ok


# ---------------------------------------------------------------------------
# Canonical write
# ---------------------------------------------------------------------------


def test_canonical_write_emits_only_canonical_ids() -> None:
    identity = canonical_write_identity(NamespaceKind.FAMILY, "fol")
    assert identity.value == "first_order"
    # Idempotent on canonical form.
    again = canonical_write_identity(NamespaceKind.FAMILY, "first_order")
    assert again.value == "first_order"


def test_canonical_write_rejects_masquerades() -> None:
    with pytest.raises(CanonicalWriteError):
        canonical_write_identity(NamespaceKind.FAMILY, "z3")
    with pytest.raises(CanonicalWriteError):
        canonical_write_identity(NamespaceKind.FAMILY, "smt")
    with pytest.raises(CanonicalWriteError):
        canonical_write_identity(NamespaceKind.FAMILY, "safety")


def test_canonical_write_request_fields() -> None:
    written = canonical_write_request_fields(
        {
            "family_id": "fol",
            "provider_id": "z3",
            "notation": "smt",
            "property_id": "safety",
            "unrelated": "keep-me",
        }
    )
    assert written["family_id"] == "first_order"
    assert written["provider_id"] == "z3"
    assert written["notation"] == "smt_lib2"
    assert written["property_id"] == "safety"
    assert written["unrelated"] == "keep-me"
    # Never write the legacy surface forms.
    assert "fol" not in written.values()
    assert written["notation"] != "smt"


# ---------------------------------------------------------------------------
# Provider descriptor migration
# ---------------------------------------------------------------------------


def test_migrate_provider_descriptor_rewrites_aliases() -> None:
    entry = BASELINE_PROVIDER_CATALOG.get("rocq")
    # Simulate a legacy descriptor that used the coq alias as provider_id.
    legacy = entry.to_dict()
    legacy["provider_id"] = "coq"
    receipt = migrate_provider_descriptor(legacy)
    assert receipt.ok
    assert receipt.disposition in {
        MigrationDispositionKind.MIGRATED,
        MigrationDispositionKind.CANONICAL,
        MigrationDispositionKind.PARTIAL,
    }
    assert receipt.canonical_payload["provider_id"] == "rocq"
    assert any(
        record.field == "provider_id" and record.canonical == "rocq"
        for record in receipt.field_records
    )


def test_migrate_provider_descriptor_rewrites_family_aliases() -> None:
    receipt = migrate_provider_descriptor(
        {
            "provider_id": "z3",
            "provider_version": "baseline-v1",
            "family_support": [
                {"family_id": "fol", "support_level": "native"},
            ],
            "authority_ceiling": "bounded",
        }
    )
    assert receipt.ok
    families = [
        item["family_id"] for item in receipt.canonical_payload["family_support"]
    ]
    assert families == ["first_order"]
    assert any(record.was_alias for record in receipt.field_records)


def test_migrate_provider_rejects_family_masquerade() -> None:
    receipt = migrate_provider_descriptor(
        {
            "provider_id": "z3",
            "provider_version": "baseline-v1",
            "family_support": [
                {"family_id": "smt", "support_level": "native"},
            ],
        }
    )
    # smt cannot be a family — support entry rejected.
    assert receipt.disposition in {
        MigrationDispositionKind.REJECTED,
        MigrationDispositionKind.PARTIAL,
    }
    if receipt.ok:
        assert receipt.canonical_payload.get("family_support") == []
    else:
        assert not receipt.canonical_payload


# ---------------------------------------------------------------------------
# Legacy BackendRequest migration
# ---------------------------------------------------------------------------


def test_migrate_legacy_request_dual_reads_family_alias() -> None:
    legacy = _legacy_request(logic_family="fol", requested_backend_id="z3")
    v2, receipt = migrate_legacy_backend_request(legacy, **_lineage_kwargs())
    assert v2 is not None
    assert isinstance(v2, BackendRequestV2)
    assert v2.interface == BACKEND_REQUEST_V2_INTERFACE
    assert v2.family.value == "first_order"
    assert v2.requested_provider is not None
    assert v2.requested_provider.value == "z3"
    assert receipt.ok
    assert receipt.disposition is MigrationDispositionKind.MIGRATED
    assert any(
        record.field == "logic_family" and record.canonical == "first_order"
        for record in receipt.field_records
    )
    # Canonical write payload never retains "fol".
    family_payload = receipt.canonical_payload["family"]
    assert family_payload["value"] == "first_order"


def test_migrate_legacy_request_drops_payload() -> None:
    legacy = _legacy_request(
        logic_family="first_order",
        payload={"raw_formula": "(assert true)", "family": "smt"},
    )
    v2, receipt = migrate_legacy_backend_request(legacy, **_lineage_kwargs())
    assert v2 is not None
    assert v2.metadata.get("legacy_payload_dropped") is True
    assert any(record.action is FieldAction.DROPPED for record in receipt.field_records)
    assert any("payload" in loss for loss in receipt.losses) or any(
        "payload" in item for item in receipt.deprecations
    )
    # No free-form payload field on v2.
    assert "payload" not in receipt.canonical_payload


def test_migrate_legacy_request_provider_alias() -> None:
    legacy = _legacy_request(
        logic_family="temporal",
        requested_backend_id="tlc",
    )
    v2, receipt = migrate_legacy_backend_request(legacy, **_lineage_kwargs())
    assert v2 is not None
    assert v2.requested_provider is not None
    assert v2.requested_provider.value == "tla_tlc"
    assert receipt.ok


def test_migrate_legacy_request_rejects_unspecified_family() -> None:
    legacy = _legacy_request(logic_family="unspecified")
    v2, receipt = migrate_legacy_backend_request(legacy, **_lineage_kwargs())
    assert v2 is None
    assert not receipt.ok
    assert receipt.disposition is MigrationDispositionKind.REJECTED


def test_migrate_legacy_request_rejects_provider_as_family() -> None:
    legacy = _legacy_request(logic_family="z3")
    v2, receipt = migrate_legacy_backend_request(legacy, **_lineage_kwargs())
    assert v2 is None
    assert not receipt.ok


def test_migrate_legacy_request_rejects_syntax_as_family() -> None:
    legacy = _legacy_request(logic_family="smt")
    v2, receipt = migrate_legacy_backend_request(legacy, **_lineage_kwargs())
    assert v2 is None
    assert not receipt.ok


# ---------------------------------------------------------------------------
# Artifact migration
# ---------------------------------------------------------------------------


def test_migrate_artifact_rewrites_legacy_labels() -> None:
    receipt = migrate_artifact(
        {
            "family_id": "fol",
            "provider_id": "z3",
            "notation": "smt",
            "view": "VC",
            "property_id": "safety",
            "nested": {"lane": "runtime"},
        }
    )
    assert receipt.ok
    payload = receipt.canonical_payload
    assert payload["family_id"] == "first_order"
    assert payload["provider_id"] == "z3"
    assert payload["notation"] == "smt_lib2"
    assert payload["view"] == "verification_condition"
    assert payload["property_id"] == "safety"
    assert payload["nested"]["lane"] == "runtime_monitor"
    # No legacy write values.
    assert payload["family_id"] != "fol"
    assert payload["notation"] != "smt"
    assert payload["view"] != "VC"
    assert any(record.was_alias for record in receipt.field_records)


def test_migrate_artifact_rejects_family_masquerade() -> None:
    receipt = migrate_artifact({"family_id": "z3", "provider_id": "z3"})
    assert not receipt.ok
    assert receipt.disposition is MigrationDispositionKind.REJECTED


def test_receipt_round_trip() -> None:
    receipt = migrate_artifact({"family_id": "fol", "provider_id": "z3"})
    restored = LogicContractMigrationReceipt.from_dict(receipt.to_dict())
    assert restored.receipt_id == receipt.receipt_id
    assert restored.disposition == receipt.disposition
    assert restored.canonical_payload == receipt.canonical_payload


def test_facade_migrate_request() -> None:
    facade = LogicContractMigration()
    legacy = _legacy_request(logic_family="protocol")
    v2, receipt = facade.migrate_request(legacy, **_lineage_kwargs())
    assert v2 is not None
    assert v2.family.value == "cryptographic_protocol"
    assert receipt.ok


def test_every_new_write_is_canonical() -> None:
    """Canonical write surfaces never re-emit known legacy aliases."""

    legacy_forms = {
        "fol",
        "protocol",
        "smt",
        "smtlib2",
        "VC",
        "runtime",
        "coq",
        "tlc",
    }
    written = canonical_write_request_fields(
        {
            "family_id": "fol",
            "notation": "smt",
            "view": "VC",
            "lane": "runtime",
            "provider_id": "coq",
        }
    )
    for value in written.values():
        if isinstance(value, str):
            assert value not in legacy_forms

    receipt = migrate_artifact(
        {
            "family_id": "fol",
            "notation": "smtlib2",
            "view": "VC",
            "provider_id": "tlc",
        }
    )
    assert receipt.ok
    for key in ("family_id", "notation", "view", "provider_id"):
        assert receipt.canonical_payload[key] not in legacy_forms
