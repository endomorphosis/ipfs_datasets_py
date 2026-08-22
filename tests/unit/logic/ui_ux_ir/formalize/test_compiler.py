"""Tests for UI/UX IR multi-view formalization compilers."""

from __future__ import annotations

from ipfs_datasets_py.logic.ui_ux_ir import (
    UI_UX_IR_SCHEMA_VERSION,
    compile_ui_formalization,
    decode_ui_ir,
    decompile_ui_formalization,
    evaluate_semantic_roundtrip,
)
from ipfs_datasets_py.logic.ui_ux_ir.formalize import (
    compile_dcec,
    compile_event_calculus,
    compile_flogic,
    compile_tdfol,
)

SHA_A = "a" * 64


def _doc_payload(**overrides):
    base = {
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
                "review_status": "trusted_fixture",
            }
        ],
        "components": [
            {
                "component_id": "component:root",
                "role": "form",
                "purpose": "Collect a value",
                "accessible_name_ref": "loc:form-title",
                "child_ids": ["component:submit"],
                "source_ref_ids": ["source:form-v1"],
            },
            {
                "component_id": "component:submit",
                "role": "button",
                "purpose": "Submit",
                "parent_id": "component:root",
                "source_ref_ids": ["source:form-v1"],
            },
        ],
        "entry_components": ["component:root"],
        "terminal_outcomes": [
            {
                "outcome_id": "outcome:success",
                "kind": "success",
                "source_ref_ids": ["source:form-v1"],
            }
        ],
        "program_bindings": [
            {
                "binding_id": "program:submit",
                "target_kind": "mcp_idl_interface_method_schema",
                "target_ref": "form.submit",
                "confirmation_class": "none",
                "risk_class": "low",
                "source_ref_ids": ["source:form-v1"],
            }
        ],
    }
    base.update(overrides)
    return base


def test_flogic_compiles_components():
    doc = decode_ui_ir(_doc_payload())
    view, coverage = compile_flogic(doc)
    assert view.logic_family == "flogic"
    assert any("HasRole" in f.text for f in view.formulas)
    assert coverage


def test_event_calculus_entry_and_bindings():
    doc = decode_ui_ir(_doc_payload())
    view, coverage = compile_event_calculus(doc)
    assert view.logic_family == "event_calculus"
    assert any("Initially" in f.text for f in view.formulas)
    assert coverage


def test_tdfol_and_dcec():
    doc = decode_ui_ir(_doc_payload())
    tview, _ = compile_tdfol(doc)
    dview, _ = compile_dcec(doc)
    assert tview.logic_family == "tdfol"
    assert dview.logic_family == "dcec"
    assert any("Permitted" in f.text or "Obligated" in f.text for f in tview.formulas)
    assert any("Perceives" in f.text or "Intends" in f.text for f in dview.formulas)


def test_integrated_compiler_and_roundtrip():
    doc = decode_ui_ir(_doc_payload())
    art = compile_ui_formalization(doc)
    assert len(art.views) == 4
    assert art.grants_execution_authority is False
    assert art.coverage_summary().get("represented", 0) > 0
    recon = decompile_ui_formalization(art)
    assert "component:root" in recon.component_ids
    report = evaluate_semantic_roundtrip(doc, artifact=art)
    assert report.passed, report.to_dict()


def test_high_risk_confirmation_non_weakening():
    payload = _doc_payload(
        program_bindings=[
            {
                "binding_id": "program:wipe",
                "target_kind": "mcp_idl_interface_method_schema",
                "target_ref": "danger.wipe",
                "confirmation_class": "explicit",
                "risk_class": "high",
                "source_ref_ids": ["source:form-v1"],
            }
        ]
    )
    doc = decode_ui_ir(payload)
    art = compile_ui_formalization(doc)
    tdfol = next(v for v in art.views if v.logic_family == "tdfol")
    texts = " ".join(f.text for f in tdfol.formulas)
    assert "Obligated(Confirm" in texts or "Prohibited(AutoInvoke" in texts
    report = evaluate_semantic_roundtrip(doc, artifact=art)
    assert report.deontic_non_weakening
