"""Unresolved event requests are sidecars, never implicit temporal declarations."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic import autoformal
from ipfs_datasets_py.logic.autoformal import legal_temporal_event_interpretation as interpretation
from ipfs_datasets_py.logic.autoformal import legal_temporal_event_proposer_v4 as proposer
from ipfs_datasets_py.logic.autoformal.legal_temporal_occurrence_provenance import digest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as q


MEANING_FIELDS = {
    "subject_source_span", "subject_source_text", "state_atom", "event_atom",
    "until_strength", "endpoint", "time_domain", "origin", "modal_scope",
}
UNTIL = "The agency shall retain records until the board issues notice."


def without_sidecars(value):
    if isinstance(value, dict):
        return {key: without_sidecars(item) for key, item in value.items()
                if key != "temporal_occurrence_provenance"}
    if isinstance(value, list):
        return [without_sidecars(item) for item in value]
    return value


def assert_unresolved_inventory(entry):
    inventory = entry["interpretation_requests"]
    assert inventory["schema"] == interpretation.REQUEST_SCHEMA
    assert entry["interpretation_requests_sha256"] == digest(inventory)
    assert inventory["receipt_sha256"] == digest({key: value for key, value in inventory.items()
                                                  if key != "receipt_sha256"})
    assert inventory["occurrence_receipt_sha256"] == entry["receipt"]["receipt_sha256"]
    assert inventory["source_binding"] == entry["receipt"]["source_binding"]
    assert inventory["model_calls"] == 0
    assert all(value is False for value in inventory["authority"].values())
    for request in inventory["requests"]:
        skeleton = request["declaration_skeleton"]
        assert all(skeleton[field] is None for field in MEANING_FIELDS)
        assert skeleton["request_id"] == request["request_id"]
        assert skeleton["request_sha256"] == request["request_sha256"]
        assert skeleton["source_text_sha256"] == inventory["source_binding"]["source_text_sha256"]
        assert all(value is False for value in request["authority"].values())
        assert "temporal_ast" not in request
        assert "tdfol_formula" not in request
        assert "lean_source" not in request
    return inventory


@pytest.mark.parametrize("text", [
    UNTIL,
    "The agency shall file within 10 days of notice.",
    "The agency shall file unless notice arrives before January 1, 2024.",
    "Background until the board issues notice.",
])
def test_requests_leave_default_compiler_and_public_rows_unchanged(text, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("ordinary compilation implicitly prepared a caller declaration")

    monkeypatch.setattr(interpretation, "prepare_event_interpretation", unexpected)
    plain = autoformal.AutoformalSession()
    enabled = autoformal.AutoformalSession(capture_temporal_provenance=True)
    expected = autoformal.compile_span(plain, text, "compatibility")
    actual = autoformal.compile_span(enabled, text, "compatibility")
    assert plain.capture_temporal_provenance is False
    assert plain.temporal_occurrence_report()["artifacts"] == []
    assert "temporal_occurrence_provenance" not in expected
    assert without_sidecars(actual) == expected
    assert [row.public() for row in enabled.rows] == [row.public() for row in plain.rows]
    for entry in enabled.temporal_occurrence_report()["artifacts"]:
        assert_unresolved_inventory(entry)


def test_source_only_until_request_survives_missing_parser_and_compiler_rows(monkeypatch):
    text = "Background until the board issues notice."
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)

    def unexpected(*args, **kwargs):
        pytest.fail("no-parser event request reached document opening or compilation")

    monkeypatch.setattr(session, "open_document", unexpected)
    monkeypatch.setattr(session, "compile_clause", unexpected)
    result = autoformal.compile_span(session, text, "source-only")
    assert result["reason"] == "no_parser_elements"
    assert not session.rows
    inventory = assert_unresolved_inventory(result["temporal_occurrence_provenance"])
    assert inventory["counts"]["awaiting_caller_interpretation"] == 1
    request = inventory["requests"][0]
    assert request["parser_join"]["status"] == "unmatched"
    assert request["parser_join"]["occurrence_id"] is None
    assert request["parser_join"]["candidate_rule_associations"] == []
    assert request["event_source"]["source_text"] == "the board issues notice"


@pytest.mark.parametrize("text,status", [
    ("The agency shall file after the board issues notice.", "unsupported_family"),
    ("The agency shall retain records until the board issues notice and until the board issues notice.", "excluded"),
])
def test_excluded_and_unsupported_requests_remain_unresolved(text, status):
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    result = autoformal.compile_span(session, text, "retained")
    entry = result["temporal_occurrence_provenance"]
    inventory = assert_unresolved_inventory(entry)
    assert any(request["status"] == status for request in inventory["requests"])
    assert len(inventory["requests"]) == len(entry["adapter_diagnostics"]["rows"])
    assert inventory["excluded"] == entry["adapter_diagnostics"]["excluded"]
    assert inventory["issues"] == entry["adapter_diagnostics"]["issues"]
    assert inventory["unmatched_occurrence_ids"] == entry["adapter_diagnostics"]["unmatched_occurrence_ids"]


def test_budget_skip_preserves_whole_source_and_same_explicit_reasons(monkeypatch):
    text = " ".join(["Background until the board issues notice."] * 110)
    assert len(text) > proposer.MAX_SOURCE_CHARACTERS
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)

    def unexpected(*args, **kwargs):
        pytest.fail("oversized inventory reached proposer or interpretation builder")

    monkeypatch.setattr(proposer, "propose", unexpected)
    monkeypatch.setattr(interpretation, "build_interpretation_requests", unexpected)
    entry = session.capture_span_temporal(text, "budget")
    unavailable = entry["interpretation_requests"]
    assert unavailable["schema"] == "legal-temporal-event-interpretation-requests-unavailable/v1"
    assert unavailable["reason_codes"] == entry["adapter_diagnostics"]["reason_codes"]
    assert unavailable["reason_codes"] == ["proposer_source_character_budget_exceeded"]
    assert unavailable["status"] == "not_evaluated"
    assert unavailable["source_truncated"] is False
    assert unavailable["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert entry["receipt"]["source_binding"]["clause_end_in_document"] == len(text)
    assert entry["interpretation_requests_sha256"] == digest(unavailable)
    assert "requests" not in unavailable
    assert "counts" not in unavailable
    assert all(value is False for value in unavailable["authority"].values())


def test_repeated_clause_requests_keep_distinct_exact_document_anchors():
    document = "Préface.\n\n" + UNTIL + "\n\n" + UNTIL
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    opened = session.open_document(document, document_id="repeated-document",
                                   segmenter=lambda value: [UNTIL, UNTIL])
    requests = []
    for clause in opened["clauses"]:
        result = session.compile_clause("repeated-document", clause["id"])
        inventory = assert_unresolved_inventory(result["temporal_occurrence_provenance"])
        request = inventory["requests"][0]
        requests.append(request)
        assert request["source_binding"]["document_text_sha256"] == hashlib.sha256(document.encode()).hexdigest()
        assert request["source_binding"]["clause_start_in_document"] == clause["start"]
        for field in ("temporal_source", "event_source", "cue_source"):
            anchor = request[field]
            assert anchor["document_translation_resolved"]
            a, b = anchor["document_span"]["char_start"], anchor["document_span"]["char_end"]
            assert document[a:b] == anchor["document_text"] == anchor["source_text"]
    assert requests[0]["request_id"] != requests[1]["request_id"]
    assert requests[0]["source_binding"]["source_text_sha256"] == requests[1]["source_binding"]["source_text_sha256"]
    assert requests[0]["temporal_source"]["document_span"] != requests[1]["temporal_source"]["document_span"]


def test_request_document_anchors_follow_whitespace_selector():
    source = "The café shall retain records until the board issues notice."
    document = "Préface.\n\nThe café shall retain records\n  until the board issues notice."
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    opened = session.open_document(document, document_id="whitespace", segmenter=lambda value: [source])
    result = session.compile_clause("whitespace", opened["clauses"][0]["id"])
    request = assert_unresolved_inventory(result["temporal_occurrence_provenance"])["requests"][0]
    binding = request["source_binding"]
    anchor = request["temporal_source"]
    assert anchor["document_translation_resolved"]
    assert anchor["document_span"]["char_start"] != binding["clause_start_in_document"] + anchor["source_span"]["char_start"]
    start, end = anchor["document_span"]["char_start"], anchor["document_span"]["char_end"]
    assert document[start:end] == anchor["document_text"]


def test_returned_requests_and_session_reports_are_independent_copies():
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    opened = session.open_document(UNTIL, document_id="copy", segmenter=lambda value: [value])
    result = session.compile_clause("copy", opened["clauses"][0]["id"])
    expected = deepcopy(session.temporal_occurrence_report())
    entry = result["temporal_occurrence_provenance"]
    entry["interpretation_requests"]["requests"][0]["declaration_skeleton"]["state_atom"] = "invented"
    entry["interpretation_requests"]["authority"]["qualified"] = True
    entry["compiler_rows_at_capture"].clear()
    report = session.temporal_occurrence_report()
    assert report == expected
    report["artifacts"][0]["interpretation_requests"]["requests"].clear()
    assert session.temporal_occurrence_report() == expected


def test_qualification_binds_requests_without_changing_deadline_gates(monkeypatch, tmp_path):
    def unexpected(*args, **kwargs):
        pytest.fail("request inventory invoked declaration preparation or native execution")

    monkeypatch.setattr(interpretation, "prepare_event_interpretation", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    monkeypatch.setattr(subprocess, "Popen", unexpected)
    lock, _, _ = q._statement_lock()
    text = "Company A shall submit backup report within 10 days unless emergency."
    result = q._structural_gates({"title": "5", "section": "1", "text": text},
                                 "deadline", tmp_path, lock, 30)
    assert result["semantic_gate"]["passed"] is True
    assert result["family_coverage_gate"]["passed"] is False
    assert result["lake_gate"]["passed"] is False
    assert result["lake_gate"]["admitted"] is False
    plain = autoformal.AutoformalSession()
    expected = autoformal.compile_span(plain, text, "deadline")
    assert without_sidecars(result["compiler"]) == expected
    assert result["semantic_gate"]["rows"] == [row.public() for row in plain.rows]
    captures = {entry["receipt_sha256"]: entry
                for entry in result["temporal_occurrence_provenance"]["artifacts"]}
    assert result["family_syntax_gate"]["rows"]
    for row in result["family_syntax_gate"]["rows"]:
        binding = row["temporal_occurrence_evidence"]
        entry = captures[binding["receipt_sha256"]]
        assert binding["interpretation_requests_sha256"] == digest(entry["interpretation_requests"])
        assert_unresolved_inventory(entry)
        assert binding["semantic_qualification_passed"] is False
        assert binding["owner_occurrence_resolved"] is False


@pytest.mark.parametrize("change_on_read", [1, 2])
def test_candidate_rejects_interpretation_source_drift_before_loading_model(monkeypatch, tmp_path,
                                                                          change_on_read):
    original = Path.read_bytes
    target = Path(interpretation.__file__).resolve()
    reads = 0

    def changed(path):
        nonlocal reads
        raw = original(path)
        if path.resolve() == target:
            reads += 1
            if reads >= change_on_read:
                return raw + b"\n# simulated concurrent interpretation producer change\n"
        return raw

    def unexpected(*args, **kwargs):
        pytest.fail("drifted interpretation dependency reached model loading or native execution")

    monkeypatch.setattr(Path, "read_bytes", changed)
    monkeypatch.setattr(q, "_load_candidate", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    with pytest.raises(q.CandidateQualificationError, match="source changed"):
        q.qualify_candidate({}, "source-pin-test", [{"title": "5", "section": "1", "text": UNTIL}],
                            tmp_path / "qualification", model_config={"compute_device": "python"})
    assert reads >= change_on_read
    assert not (tmp_path / "qualification/qualification.json").exists()
