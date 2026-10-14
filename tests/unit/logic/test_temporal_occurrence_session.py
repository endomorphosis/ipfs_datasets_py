"""Session integration preserves legacy output and exposes diagnostic evidence only."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic import autoformal
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_temporal_constraint_details
from ipfs_datasets_py.logic.autoformal.legal_temporal_occurrence_provenance import (
    digest,
    validate_occurrence_receipt,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as q


WORKSPACE = Path(__file__).resolve().parents[5]
BASELINE = WORKSPACE / "artifacts/legal-temporal-occurrence-integration-20261005/baseline.json"
BASELINE_SHA256 = "9b6d7ede232cac71cd853ea95e7692986f13c577854934047e1ed133430d7fbf"
DIAGNOSTIC_FIELDS = {"temporal_occurrence_provenance", "temporal_occurrence_provenance_sha256"}


def legacy(value):
    if isinstance(value, dict):
        return {key: legacy(item) for key, item in value.items() if key not in DIAGNOSTIC_FIELDS}
    if isinstance(value, list):
        return [legacy(item) for item in value]
    return value


def deadline_cue_preserved_baseline(baseline):
    """One disclosed repair to immutable evidence, with every other byte checked.

    The historical 4873(b)(2) output lost its deadline relation. Only the
    temporal value, its decompiled suffix and the resulting IR CID may change.
    The source, parser coordinates, rule facets and failed gates stay fixed.
    """
    from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR

    old = "10 days after the secretary provides a waiver under paragraph (1)"
    new = "not later than " + old
    old_rule = baseline["rows"][0]["rule"]
    rule = {key: value for key, value in old_rule.items() if key != "temporal_records"}
    assert rule["temporal"] == [old]
    old_cid = CanonicalRoundTripIR.from_dict({"rules": [rule]}).ir_cid
    new_cid = CanonicalRoundTripIR.from_dict({"rules": [{**rule, "temporal": [new]}]}).ir_cid

    def repaired(value):
        if isinstance(value, dict):
            return {key: repaired(item) for key, item in value.items()}
        if isinstance(value, list):
            return [repaired(item) for item in value]
        if isinstance(value, str):
            if value == old:
                return new
            if value == old_cid:
                return new_cid
            if value.startswith("Secretary must submit ") and value.endswith(" " + old + "."):
                return value[:-len(old + ".")] + new + "."
        return value

    return repaired(baseline)


def unresolved_procedure_baseline(baseline):
    """Declare the waiver example's stricter source-based abstention explicitly.

    Its unresolved after-waiver cue remains evidence even when no supported
    procedure owner can be selected. Source, offsets, and temporal observations
    retain their pinned values; a rule is no longer emitted on the first parse.
    """
    case = baseline["case"]
    assert case["id"] == "usc:us:10:4873-p9"
    assert len(baseline["rows"]) == 1
    reason = "CanonicalErrorCode.UNSUPPORTED_SEMANTICS:procedure"
    row = {**baseline["rows"][0], "rule": None, "decompiled": "",
           "status": "abstain", "reason": reason, "admitted": False}
    component = {
        "component_index": 0, "span_id": case["id"], "clause_id": row["clause_id"],
        "source_text": case["text"], "source_start": 0, "source_end": len(case["text"]),
        "allow_partial": False, "compiler_status": "abstain", "compiler_rows": [row],
        "rows": [row], "rules": [], "roundtrip_report": None,
        "compilation_complete": False, "admitted": False,
    }
    compiler = {
        "compiler_status": "abstain", "reason": reason, "decompiled": "",
        "fields": ["procedure"], "rules": [], "components": [component],
        "compilation_complete": False, "admitted": False,
    }
    return {**baseline, "compiler": compiler, "rows": [row]}


def assert_authority_false(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    for artifact in report["artifacts"]:
        for key in ("receipt", "adapter_diagnostics"):
            receipt = artifact[key]
            assert all(value is False for value in receipt["authority"].values())
            assert receipt["receipt_sha256"] == digest(
                {name: value for name, value in receipt.items() if name != "receipt_sha256"}
            )
        assert artifact["adapter_diagnostics"]["model_calls"] == 0


@pytest.mark.parametrize("case_index", range(16))
def test_frozen_outputs_preserve_declared_source_repairs(case_index):
    if not BASELINE.is_file():
        pytest.skip("workspace-local pre-integration baseline is not installed")
    raw = BASELINE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BASELINE_SHA256
    baseline = json.loads(raw)["cases"][case_index]
    if baseline["case"]["id"] == "usc:us:10:4873-p9":
        baseline = deadline_cue_preserved_baseline(baseline)
        baseline = unresolved_procedure_baseline(baseline)
    case = baseline["case"]
    assert extract_temporal_constraint_details(case["text"]) == baseline["parser_details"]
    for enabled in (False, True):
        session = autoformal.AutoformalSession(capture_temporal_provenance=enabled)
        compiled = autoformal.compile_span(session, case["text"], case["id"])
        assert legacy(compiled) == baseline["compiler"]
        assert [row.public() for row in session.rows] == baseline["rows"]
        assert ("temporal_occurrence_provenance" in compiled) is enabled
        report = session.temporal_occurrence_report()
        assert bool(report["artifacts"]) is enabled
        if enabled:
            assert_authority_false(report)


def test_opt_in_no_parser_keeps_occurrences_without_document_or_compiler(monkeypatch):
    text = "Background before January 1, 2024."
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)

    def unexpected(*args, **kwargs):
        pytest.fail("no-parser text reached document or compiler")

    monkeypatch.setattr(session, "open_document", unexpected)
    monkeypatch.setattr(session, "compile_clause", unexpected)
    monkeypatch.setattr(autoformal, "_compile_text", unexpected)
    result = autoformal.compile_span(session, text, "no-parser")
    assert legacy(result) == {
        "compiler_status": "abstain", "reason": "no_parser_elements", "decompiled": "", "fields": []
    }
    report = session.temporal_occurrence_report()
    assert report["artifacts"][0]["receipt"]["occurrences"]
    assert not session.rows
    assert_authority_false(report)


def test_opt_in_no_clause_is_visible(monkeypatch):
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    monkeypatch.setattr(session, "open_document", lambda *a, **k: {"clauses": []})
    result = autoformal.compile_span(session, "The agency shall file within 10 days.", "no-clause")
    assert result["reason"] == "no_clause"
    assert session.temporal_occurrence_report()["artifacts"][0]["receipt"]["occurrences"]
    assert not session.rows


def test_empty_input_keeps_legacy_abstention_without_inventing_occurrences():
    plain = autoformal.AutoformalSession()
    capture = autoformal.AutoformalSession(capture_temporal_provenance=True)
    prior = autoformal.compile_span(plain, "", "empty")
    result = autoformal.compile_span(capture, "", "empty")
    assert legacy(result) == prior
    unavailable = result["temporal_occurrence_provenance"]
    assert unavailable["status"] == "not_evaluated"
    assert unavailable["reason_codes"] == ["empty_source"]
    assert not capture.rows
    assert capture.temporal_occurrence_report()["artifacts"] == []


def test_oversized_whole_input_retains_full_inventory_without_adapter_truncation():
    text = "\n\n".join(["The agency shall file within 10 days."] * 115)
    assert len(text) > 4096
    prior_session = autoformal.AutoformalSession()
    prior = autoformal.compile_span(prior_session, text, "oversized")
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    result = autoformal.compile_span(session, text, "oversized")
    assert legacy(result) == prior
    assert [row.public() for row in session.rows] == [row.public() for row in prior_session.rows]
    artifact = result["temporal_occurrence_provenance"]
    receipt = artifact["receipt"]
    assert receipt["source_binding"]["source_text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert receipt["source_binding"]["clause_end_in_document"] == len(text)
    assert len(receipt["occurrences"]) == 115
    assert len({row["occurrence_id"] for row in receipt["occurrences"]}) == 115
    assert artifact["adapter_diagnostics"]["status"] == "not_evaluated"
    assert artifact["adapter_diagnostics"]["source_truncated"] is False
    assert "counts" not in artifact["adapter_diagnostics"]
    validate_occurrence_receipt(receipt, source_text=text)


@pytest.mark.parametrize("outcome", ["no_rule", "inactive"])
def test_no_rule_and_inactive_rows_keep_occurrence_sidecars(monkeypatch, outcome):
    text = "The agency shall file within 10 days."
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    opened = session.open_document(text, document_id="retained", segmenter=lambda value: [value])
    clause_id = opened["clauses"][0]["id"]
    clause = session.documents.clause("retained", clause_id)
    if outcome == "inactive":
        clause.disposition = "inactive"
        clause.reason = "repealed"

        def unexpected(*args, **kwargs):
            pytest.fail("inactive clause reached compiler")

        monkeypatch.setattr(autoformal, "_compile_text", unexpected)
    else:
        monkeypatch.setattr(autoformal, "_compile_text", lambda *a, **k: [])
    result = session.compile_clause("retained", clause_id)
    assert result["rows"][0]["rule"] is None
    assert result["rows"][0]["status"] == ("inactive" if outcome == "inactive" else "abstain")
    assert set(result) == {"rows", "temporal_occurrence_provenance"}
    receipt = session.temporal_occurrence_report()["artifacts"][0]["receipt"]
    assert receipt["counts"]["rows_without_rule"] == 1
    assert receipt["occurrences"]
    assert all(not item["candidate_rule_indices"] for item in receipt["occurrences"])
    validate_occurrence_receipt(receipt, source_text=text, document_text=text, rule_rows=result["rows"])


def test_whitespace_selector_preserves_document_offsets_without_offset_addition():
    document = "Préface.\n\nThe café shall file\n  within 10 days."
    # Force a real length-changing normalization; the selector maps this back
    # to the original newline and two spaces rather than adding the clause start.
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    normalized = "The café shall file within 10 days."
    opened = session.open_document(document, document_id="unicode-document",
                                   segmenter=lambda value: [normalized])
    clause = session.documents.clause("unicode-document", opened["clauses"][0]["id"])
    result = session.compile_clause("unicode-document", clause.id)
    receipt = session.temporal_occurrence_report()["artifacts"][0]["receipt"]
    validate_occurrence_receipt(receipt, source_text=normalized, document_text=document,
                                rule_rows=result["rows"])
    occurrence = receipt["occurrences"][0]
    a, b = occurrence["temporal_start_in_document"], occurrence["temporal_end_in_document"]
    assert occurrence["document_translation_resolved"]
    assert document[a:b] == occurrence["exact_document_slice"]
    assert a != clause.start + occurrence["temporal_start_in_clause"]
    assert receipt["source_binding"]["document_translation"] == "validated_whitespace_alignment"


def test_candidate_receipt_does_not_waive_deadline_or_coverage_gates(monkeypatch, tmp_path):
    def unexpected(*args, **kwargs):
        pytest.fail("temporal diagnostics attempted a native subprocess")

    monkeypatch.setattr(subprocess, "run", unexpected)
    monkeypatch.setattr(subprocess, "Popen", unexpected)
    lock, _, _ = q._statement_lock()
    text = "Company A shall submit backup report within 10 days unless emergency."
    result = q._structural_gates({"title": "5", "section": "1", "text": text},
                                 "deadline-diagnostic", tmp_path, lock, 30)
    assert result["semantic_gate"]["passed"]
    assert not result["family_coverage_gate"]["passed"]
    assert not result["lake_gate"]["passed"]
    assert not result["lake_gate"]["admitted"]
    assert_authority_false(result["temporal_occurrence_provenance"])
    captures = {entry["receipt_sha256"]: entry
                for entry in result["temporal_occurrence_provenance"]["artifacts"]}
    for family in result["family_syntax_gate"]["rows"]:
        evidence = family["temporal_occurrence_evidence"]
        capture = captures[evidence["receipt_sha256"]]
        row = capture["receipt"]["rule_rows"][evidence["rule_index"]]
        assert evidence["rule_sha256"] == row["rule_sha256"]
        assert evidence["source_id"] == capture["receipt"]["source_binding"]["source_id"]
        assert evidence["owner_occurrence_resolved"] is False
        assert evidence["semantic_qualification_passed"] is False
    # A co-occurring minimum cannot let a deadline reach native rendering.
    mixed_rule = {"temporal_records": [
        {"temporal_kind": "minimum_duration", "quantity": 20, "value": "20 days"},
        {"temporal_kind": "within_duration", "quantity": 10, "value": "10 days"},
    ]}
    lake = q._lake_gate(mixed_rule, roundtrip_ok=True, output_directory=tmp_path / "lake",
                        timeout_seconds=30, statement_lock=lock)
    assert lake["reason"] == "within_duration_not_renderable"
    assert not lake["admitted"]
    assert not (tmp_path / "lake").exists()


def test_constitution_exclusion_reports_unavailable_without_compiler(monkeypatch, tmp_path):
    def unexpected(*args, **kwargs):
        pytest.fail("excluded constitution source reached the compiler or native build")

    monkeypatch.setattr(autoformal, "compile_span", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    result = q._structural_gates(
        {"title": "Constitution", "section": "Article I", "text": "All legislative Powers..."},
        "constitution", tmp_path, object(), 30,
    )
    assert result["compiler"]["compiler_status"] == "not_evaluated"
    assert all(result[name]["passed"] is False for name in q.STRUCTURAL_GATES)
    diagnostic = result["temporal_occurrence_provenance"]
    assert diagnostic["status"] == "not_evaluated"
    assert "constitution_not_formalized" in diagnostic["reason_codes"]
