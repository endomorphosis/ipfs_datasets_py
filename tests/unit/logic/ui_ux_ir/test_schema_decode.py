"""Unit tests for ipfs_datasets_py.logic.ui_ux_ir core codec."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.ui_ux_ir import (
    LEGACY_UI_UX_IR_SCHEMA_VERSION,
    UI_UX_IR_SCHEMA_VERSION,
    UIIR_DOCUMENT_FIELDS,
    UIIRDecodeError,
    UIIRValidationError,
    canonicalize_ui_ir,
    decode_ui_ir,
    ui_ir_sha256,
    ui_ir_to_dict,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "ui_ux_ir"
    / "v1"
    / "golden_vectors.json"
)


def minimal_document_payload() -> dict:
    """Shared fixture matching SwissKnife ui-ux-ir-codec.test.ts."""
    return {
        "schema_version": UI_UX_IR_SCHEMA_VERSION,
        "document_id": "doc:form-v1",
        "title": "Sample form",
        "sources": [
            {
                "ref_id": "source:form-v1",
                "source_uri": "https://example.test/ui/form",
                "source_id": "form-v1",
                "source_revision": "rev-1",
                "content_sha256": SHA_A,
                "container_uri": "ipfs://bafy-fixture/form",
                "container_sha256": SHA_B,
                "content_cid": "",
                "license_expression": "",
                "review_status": "trusted_fixture",
                "span": {"start_char": 0, "end_char": 120},
            }
        ],
        "components": [
            {
                "component_id": "component:root",
                "role": "form",
                "purpose": "Collect a value and submit it.",
                "accessible_name_ref": "loc:form-title",
                "accessible_description_ref": "",
                "parent_id": "",
                "child_ids": ["component:submit"],
                "modality_binding_ids": [],
                "data_binding_ids": [],
                "program_binding_ids": [],
                "feedback_ids": [],
                "privacy_sensitivity": "none",
                "presentation_classification": "interactive",
                "source_ref_ids": ["source:form-v1"],
            },
            {
                "component_id": "component:submit",
                "role": "button",
                "purpose": "Submit the form.",
                "accessible_name_ref": "",
                "accessible_description_ref": "",
                "parent_id": "component:root",
                "child_ids": [],
                "modality_binding_ids": [],
                "data_binding_ids": [],
                "program_binding_ids": [],
                "feedback_ids": [],
                "privacy_sensitivity": "none",
                "presentation_classification": "interactive",
                "source_ref_ids": ["source:form-v1"],
            },
        ],
        "entry_components": ["component:root"],
        "terminal_outcomes": [
            {
                "outcome_id": "outcome:success",
                "kind": "success",
                "description": "",
                "source_ref_ids": ["source:form-v1"],
            }
        ],
    }


def test_decode_minimal_valid_document() -> None:
    decoded = decode_ui_ir(minimal_document_payload())
    assert decoded.document_id == "doc:form-v1"
    assert decoded.schema_version == UI_UX_IR_SCHEMA_VERSION
    assert len(decoded.components) == 2
    assert list(decoded.entry_components) == ["component:root"]


def test_to_dict_emits_closed_field_set() -> None:
    decoded = decode_ui_ir(minimal_document_payload())
    wire = ui_ir_to_dict(decoded)
    assert sorted(wire.keys()) == sorted(UIIR_DOCUMENT_FIELDS)


def test_reject_unknown_schema_version() -> None:
    bad = {**minimal_document_payload(), "schema_version": "ui-ux-ir/v9"}
    with pytest.raises(UIIRDecodeError, match="Unsupported schema_version"):
        decode_ui_ir(bad)


def test_reject_legacy_requires_migration() -> None:
    legacy = {
        **minimal_document_payload(),
        "schema_version": LEGACY_UI_UX_IR_SCHEMA_VERSION,
    }
    with pytest.raises(UIIRDecodeError, match="migration"):
        decode_ui_ir(legacy)


def test_reject_unknown_top_level_fields() -> None:
    unknown = {**minimal_document_payload(), "not_a_field": True}
    with pytest.raises(UIIRDecodeError, match="unknown UIIRDocument field"):
        decode_ui_ir(unknown)


def test_reject_missing_required_paths() -> None:
    missing = dict(minimal_document_payload())
    del missing["title"]
    with pytest.raises(UIIRDecodeError, match="missing required"):
        decode_ui_ir(missing)


def test_reject_dangling_entry_component() -> None:
    dangling = minimal_document_payload()
    dangling["entry_components"] = ["component:root", "component:missing"]
    with pytest.raises(UIIRDecodeError, match="unknown ids"):
        decode_ui_ir(dangling)


def test_reject_executable_callback_keys() -> None:
    bad = minimal_document_payload()
    bad["components"][0]["on_click"] = "alert(1)"
    with pytest.raises(UIIRDecodeError, match="executable callback"):
        decode_ui_ir(bad)


def test_reject_non_object_payload() -> None:
    with pytest.raises(UIIRDecodeError):
        decode_ui_ir("[]")
    with pytest.raises(UIIRDecodeError):
        decode_ui_ir(42)


def test_decode_error_is_validation_error_subclass() -> None:
    err = UIIRDecodeError("x")
    assert isinstance(err, UIIRValidationError)


def test_canonical_sha256_stable() -> None:
    decoded = decode_ui_ir(minimal_document_payload())
    digest_a = ui_ir_sha256(decoded)
    digest_b = ui_ir_sha256(minimal_document_payload())
    assert digest_a == digest_b
    assert digest_a.startswith("sha256:")
    raw = canonicalize_ui_ir(decoded)
    assert isinstance(raw, (bytes, bytearray))
    assert len(raw) > 0


def test_migrate_v0_1_to_v1() -> None:
    from ipfs_datasets_py.logic.ui_ux_ir import (
        LEGACY_UI_UX_IR_SCHEMA_VERSION,
        migrate_ui_ir,
        decode_ui_ir_with_migration,
    )

    legacy = minimal_document_payload()
    legacy["schema_version"] = LEGACY_UI_UX_IR_SCHEMA_VERSION
    # drop a v1-only closed collection so migration defaults it
    legacy.pop("program_bindings", None)
    result = migrate_ui_ir(legacy)
    assert result.source_version == LEGACY_UI_UX_IR_SCHEMA_VERSION
    assert result.target_version == UI_UX_IR_SCHEMA_VERSION
    assert result.document.schema_version == UI_UX_IR_SCHEMA_VERSION
    assert result.document.document_id == "doc:form-v1"
    # direct decode of legacy must still fail closed
    with pytest.raises(UIIRDecodeError, match="migration"):
        decode_ui_ir(legacy)
    # with_migration accepts both
    again = decode_ui_ir_with_migration(legacy)
    assert again.document.document_id == "doc:form-v1"


def test_projection_inventory_discovers_typescript_peers() -> None:
    from ipfs_datasets_py.logic.ui_ux_ir.projections import (
        inventory_projection_capabilities,
    )

    inv = inventory_projection_capabilities()
    assert inv.get("available") is True
    peers = (inv.get("typescript_peers") or {}).get("peers") or {}
    assert peers.get("codec", {}).get("available") is True
    kinds = {c["target_kind"] for c in inv.get("capabilities") or []}
    assert "web" in kinds
    assert "declaration_identity" in kinds


def test_golden_vectors_if_present() -> None:
    if not FIXTURES.is_file():
        pytest.skip("golden_vectors.json not yet written")
    golden = json.loads(FIXTURES.read_text(encoding="utf-8"))
    assert golden.get("interface") == "UIIRCrossLanguageParity@1"
    for vector in golden.get("vectors") or []:
        if vector.get("kind") == "valid_document":
            decoded = decode_ui_ir(vector["document"])
            assert ui_ir_sha256(decoded) == vector["canonical_sha256"]
            raw = canonicalize_ui_ir(decoded)
            if "canonical_utf8_length" in vector:
                assert len(raw) == vector["canonical_utf8_length"]
        elif vector.get("kind") == "invalid_document":
            with pytest.raises(UIIRDecodeError):
                decode_ui_ir(vector["document"])
