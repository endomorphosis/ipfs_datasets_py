"""UIR-011: canonical identity, exact decoding, and migrations."""

from __future__ import annotations

import copy

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.canonicalize import canonicalize_ui_ir, ui_ir_sha256
from ipfs_datasets_py.logic.ui_ux_ir.decoder import UIIRDecodeError, decode_ui_ir
from ipfs_datasets_py.logic.ui_ux_ir.migrations import (
    V0_1_TO_V1_MIGRATION_ID,
    migrate_ui_ir,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import (
    LEGACY_UI_UX_IR_SCHEMA_VERSION,
    ReviewStatus,
    SourceSpan,
    TerminalOutcomeKind,
    UIComponent,
    UIIRDocument,
    UISourceRef,
    UITerminalOutcome,
    UI_UX_IR_SCHEMA_VERSION,
)


def _source() -> UISourceRef:
    return UISourceRef(
        ref_id="source:form-v1",
        source_uri="https://example.test/ui/form",
        source_id="form-v1",
        source_revision="rev-1",
        content_sha256="a" * 64,
        container_uri="ipfs://bafy-fixture/form",
        container_sha256="b" * 64,
        review_status=ReviewStatus.TRUSTED_FIXTURE,
        span=SourceSpan(start_char=0, end_char=120),
    )


def _minimal_document() -> UIIRDocument:
    source = _source()
    root = UIComponent(
        component_id="component:root",
        role="form",
        purpose="Collect a value and submit it.",
        accessible_name_ref="loc:form-title",
        child_ids=("component:submit",),
        source_ref_ids=(source.ref_id,),
    )
    submit = UIComponent(
        component_id="component:submit",
        role="button",
        purpose="Submit the form.",
        parent_id="component:root",
        source_ref_ids=(source.ref_id,),
    )
    return UIIRDocument(
        document_id="doc:form-v1",
        title="Sample form",
        sources=(source,),
        components=(root, submit),
        entry_components=("component:root",),
        terminal_outcomes=(
            UITerminalOutcome(
                outcome_id="outcome:success",
                kind=TerminalOutcomeKind.SUCCESS,
                source_ref_ids=(source.ref_id,),
            ),
        ),
    )


def test_canonicalize_is_deterministic_and_cid_independent() -> None:
    document = _minimal_document()
    first = canonicalize_ui_ir(document)
    second = canonicalize_ui_ir(document)
    assert first == second
    assert ui_ir_sha256(document).startswith("sha256:")
    # Reordered mapping keys must not affect digest once normalized.
    payload = document.to_dict()
    reordered = {k: payload[k] for k in sorted(payload.keys(), reverse=True)}
    assert canonicalize_ui_ir(decode_ui_ir(reordered)) == first


def test_decode_round_trip_and_unknown_version_fails_closed() -> None:
    document = _minimal_document()
    payload = document.to_dict()
    decoded = decode_ui_ir(payload)
    assert decoded.document_id == document.document_id
    assert decoded.schema_version == UI_UX_IR_SCHEMA_VERSION
    bad = copy.deepcopy(payload)
    bad["schema_version"] = "ui-ux-ir/v9"
    with pytest.raises(UIIRDecodeError):
        decode_ui_ir(bad)
    legacy = copy.deepcopy(payload)
    legacy["schema_version"] = LEGACY_UI_UX_IR_SCHEMA_VERSION
    with pytest.raises(UIIRDecodeError, match="migration"):
        decode_ui_ir(legacy)
    unknown_field = copy.deepcopy(payload)
    unknown_field["not_a_field"] = True
    with pytest.raises(UIIRDecodeError):
        decode_ui_ir(unknown_field)


def test_migration_v0_1_to_v1_is_deterministic_and_receipt_bound() -> None:
    document = _minimal_document()
    legacy = document.to_dict()
    legacy["schema_version"] = LEGACY_UI_UX_IR_SCHEMA_VERSION
    legacy["legacy_widget_tree"] = {"div": "button"}
    migrated_a, receipt_a = migrate_ui_ir(legacy)
    migrated_b, receipt_b = migrate_ui_ir(legacy)
    assert migrated_a == migrated_b
    assert receipt_a.to_dict() == receipt_b.to_dict()
    assert receipt_a.migration_id == V0_1_TO_V1_MIGRATION_ID
    assert receipt_a.lossy is True
    assert any("legacy_widget_tree" in loss for loss in receipt_a.losses)
    assert receipt_a.input_digest.startswith("sha256:")
    assert receipt_a.output_digest.startswith("sha256:")
    decoded = decode_ui_ir(migrated_a)
    assert decoded.schema_version == UI_UX_IR_SCHEMA_VERSION
