"""Deadline request capture preserves source observations without choosing a clock."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest

from ipfs_datasets_py.logic import autoformal
from ipfs_datasets_py.logic.autoformal import legal_temporal_deadline_interpretation as deadline
from ipfs_datasets_py.logic.autoformal import legal_temporal_event_proposer_v4 as proposer
from ipfs_datasets_py.logic.autoformal.legal_temporal_occurrence_provenance import digest
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as q


MEANING_FIELDS = {
    "response_source_span", "response_source_text", "trigger_atom", "response_atom",
    "ticks_per_source_unit", "trigger_scope", "deadline_origin", "lower_inclusive",
    "upper_inclusive", "time_domain", "evaluation_origin", "modal_scope", "response_reuse",
}
SOURCE = "The agency shall file not later than 10 days after the board issues notice."


def without_sidecars(value):
    if isinstance(value, dict):
        return {key: without_sidecars(item) for key, item in value.items()
                if key != "temporal_occurrence_provenance"}
    if isinstance(value, list):
        return [without_sidecars(item) for item in value]
    return value


def assert_unresolved(entry):
    inventory = entry["deadline_interpretation_requests"]
    assert inventory["schema"] == deadline.REQUEST_SCHEMA
    assert entry["deadline_interpretation_requests_sha256"] == digest(inventory)
    assert inventory["receipt_sha256"] == digest({key: value for key, value in inventory.items()
                                                  if key != "receipt_sha256"})
    assert inventory["occurrence_receipt_sha256"] == entry["receipt"]["receipt_sha256"]
    assert inventory["source_binding"] == entry["receipt"]["source_binding"]
    assert all(value is False for value in inventory["authority"].values())
    assert inventory["model_calls"] == 0
    for request in inventory["requests"]:
        skeleton = request["declaration_skeleton"]
        assert all(skeleton[field] is None for field in MEANING_FIELDS)
        assert skeleton["request_id"] == request["request_id"]
        assert skeleton["request_sha256"] == request["request_sha256"]
        assert skeleton["source_text_sha256"] == inventory["source_binding"]["source_text_sha256"]
        assert all(value is False for value in request["authority"].values())
        assert not {"temporal_ast", "tdfol_formula", "lean_source", "deadline_ticks"} & request.keys()
    return inventory


@pytest.mark.parametrize("text", [
    SOURCE,
    SOURCE.replace("not later than", "no later than"),
    "Not later than 10 days after the board issues notice, the agency shall file a report.",
    "The agency shall retain records until the board issues notice.",
])
def test_deadline_capture_leaves_default_compiler_and_public_rows_unchanged(text, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("session capture implicitly prepared a deadline property")

    monkeypatch.setattr(deadline, "prepare_deadline_interpretation", unexpected)
    plain = autoformal.AutoformalSession()
    enabled = autoformal.AutoformalSession(capture_temporal_provenance=True)
    expected = autoformal.compile_span(plain, text, "deadline-compatibility")
    result = autoformal.compile_span(enabled, text, "deadline-compatibility")
    assert without_sidecars(result) == expected
    assert [row.public() for row in enabled.rows] == [row.public() for row in plain.rows]
    assert plain.temporal_occurrence_report()["artifacts"] == []
    assert "temporal_occurrence_provenance" not in expected
    for entry in enabled.temporal_occurrence_report()["artifacts"]:
        assert_unresolved(entry)
        assert entry["interpretation_requests_sha256"] == digest(entry["interpretation_requests"])


def test_source_only_deadline_request_survives_no_parser_fast_return(monkeypatch):
    text = "Background not later than 10 days after the board issues notice."
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)

    def unexpected(*args, **kwargs):
        pytest.fail("no-parser text reached document opening or compilation")

    monkeypatch.setattr(session, "open_document", unexpected)
    monkeypatch.setattr(session, "compile_clause", unexpected)
    result = autoformal.compile_span(session, text, "background-deadline")
    assert result["reason"] == "no_parser_elements"
    assert not session.rows
    inventory = assert_unresolved(result["temporal_occurrence_provenance"])
    assert len(inventory["requests"]) == 1
    request = inventory["requests"][0]
    assert request["status"] == "awaiting_caller_interpretation"
    assert request["parser_join"]["candidate_rule_associations"] == []
    assert request["proposal_family"] == "not_later_than_after"


@pytest.mark.parametrize("text,status", [
    ("The agency shall retain records until the board issues notice.", "unsupported_family"),
    (SOURCE.replace("10 days", "10 months"), "unsupported_surface"),
    (SOURCE.replace("10 days", "31 days"), "unsupported_budget"),
])
def test_unsupported_deadlines_and_other_families_remain_visible(text, status):
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    entry = session.capture_span_temporal(text, "unsupported")
    inventory = assert_unresolved(entry)
    assert inventory["requests"]
    assert any(request["status"] == status for request in inventory["requests"])
    assert len(inventory["requests"]) == len(entry["adapter_diagnostics"]["rows"])
    assert inventory["excluded"] == entry["adapter_diagnostics"]["excluded"]
    assert inventory["issues"] == entry["adapter_diagnostics"]["issues"]


def test_token_budget_exclusions_are_retained_without_an_interpretation():
    text = "word " * 260 + SOURCE
    assert len(text) < proposer.MAX_SOURCE_CHARACTERS
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    entry = session.capture_span_temporal(text, "token-budget")
    inventory = assert_unresolved(entry)
    assert inventory["requests"]
    assert all(request["status"] == "excluded" for request in inventory["requests"])
    assert inventory["issues"] == entry["adapter_diagnostics"]["issues"]
    assert any("source_token_budget_exceeded" in item["reason_codes"] for item in inventory["issues"])


def test_character_budget_skips_both_builders_without_truncation(monkeypatch):
    text = SOURCE * 60
    assert len(text) > proposer.MAX_SOURCE_CHARACTERS
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)

    def unexpected(*args, **kwargs):
        pytest.fail("oversized source reached bounded proposal or deadline builder")

    monkeypatch.setattr(proposer, "propose", unexpected)
    monkeypatch.setattr(deadline, "build_deadline_requests", unexpected)
    entry = session.capture_span_temporal(text, "character-budget")
    unavailable = entry["deadline_interpretation_requests"]
    assert unavailable["status"] == "not_evaluated"
    assert unavailable["reason_codes"] == entry["adapter_diagnostics"]["reason_codes"]
    assert unavailable["reason_codes"] == entry["interpretation_requests"]["reason_codes"]
    assert unavailable["reason_codes"] == ["proposer_source_character_budget_exceeded"]
    assert unavailable["source_truncated"] is False
    assert unavailable["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert entry["receipt"]["source_binding"]["clause_end_in_document"] == len(text)
    assert entry["deadline_interpretation_requests_sha256"] == digest(unavailable)
    assert "requests" not in unavailable
    assert "counts" not in unavailable


def test_deadline_request_outputs_are_detached_from_session_storage():
    session = autoformal.AutoformalSession(capture_temporal_provenance=True)
    entry = session.capture_span_temporal(SOURCE, "copied-deadline")
    expected = deepcopy(session.temporal_occurrence_report())
    request = entry["deadline_interpretation_requests"]["requests"][0]
    request["declaration_skeleton"]["ticks_per_source_unit"] = 1
    request["authority"]["qualified"] = True
    assert session.temporal_occurrence_report() == expected
    report = session.temporal_occurrence_report()
    report["artifacts"][0]["deadline_interpretation_requests"]["requests"].clear()
    assert session.temporal_occurrence_report() == expected


def test_candidate_references_both_request_inventories_without_waiving_gates(monkeypatch, tmp_path):
    def unexpected(*args, **kwargs):
        pytest.fail("candidate deadline diagnostics prepared a property or invoked native execution")

    monkeypatch.setattr(deadline, "prepare_deadline_interpretation", unexpected)
    monkeypatch.setattr(subprocess, "run", unexpected)
    monkeypatch.setattr(subprocess, "Popen", unexpected)
    lock, _, _ = q._statement_lock()
    source = "Company A shall submit backup report within 10 days unless emergency."
    result = q._structural_gates({"title": "5", "section": "1", "text": source},
                                 "candidate-deadline", tmp_path, lock, 30)
    assert result["semantic_gate"]["passed"] is True
    assert result["family_coverage_gate"]["passed"] is False
    assert result["lake_gate"]["passed"] is False
    assert result["lake_gate"]["admitted"] is False
    entries = {entry["receipt_sha256"]: entry
               for entry in result["temporal_occurrence_provenance"]["artifacts"]}
    assert result["family_syntax_gate"]["rows"]
    for row in result["family_syntax_gate"]["rows"]:
        binding = row["temporal_occurrence_evidence"]
        entry = entries[binding["receipt_sha256"]]
        for name in ("interpretation_requests", "deadline_interpretation_requests"):
            assert binding[name + "_sha256"] == entry[name + "_sha256"] == digest(entry[name])
        assert_unresolved(entry)
        assert binding["owner_occurrence_resolved"] is False
        assert binding["semantic_qualification_passed"] is False


@pytest.mark.parametrize("change_on_read", [1, 2])
def test_candidate_rejects_deadline_producer_drift_before_loading_model(monkeypatch, tmp_path,
                                                                     change_on_read):
    original = Path.read_bytes
    target = Path(deadline.__file__).resolve()
    reads = 0

    def changed(path):
        nonlocal reads
        raw = original(path)
        if path.resolve() == target:
            reads += 1
            if reads >= change_on_read:
                return raw + b"\n# simulated deadline producer drift\n"
        return raw

    def unexpected(*args, **kwargs):
        pytest.fail("drifted deadline producer reached model loading")

    monkeypatch.setattr(Path, "read_bytes", changed)
    monkeypatch.setattr(q, "_load_candidate", unexpected)
    with pytest.raises(q.CandidateQualificationError, match="source changed"):
        q.qualify_candidate({}, "deadline-source-pin", [{"title": "5", "section": "1", "text": SOURCE}],
                            tmp_path / "qualification", model_config={"compute_device": "python"})
    assert reads >= change_on_read
    assert not (tmp_path / "qualification/qualification.json").exists()
