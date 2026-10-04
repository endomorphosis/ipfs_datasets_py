"""Intake identity and producer claims must never become gold supervision."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/audit_legal_decoder_pilot_dataset.py"
SPEC = importlib.util.spec_from_file_location("legal_decoder_pilot_dataset", SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def row(**changes):
    value = {
        "source_span_id": "span-1", "source_text": "The agency shall retain the record.",
        "formula_text": "O(retain(agency, record))", "legal_id": "usc:test",
        "producer_origin": "source_bridge_target", "producer_record_source_id": "producer-1",
        "view_name": "fol_tdfol.tdfol_formula", "format": "tdfol-formula-records",
        "formula_field": "formula", "decoded_document_json_pointer": "/records/0/formula",
        "source_report_path_in_repo": "reports/one.json.gz", "source_report_revision": "b" * 40,
        "source_report_sha256": "a" * 64, "source_receipt_sha256": "c" * 64,
        "source_document_sha256": "d" * 64, "recorded_document_sha256": "e" * 64,
        "recorded_document_identity_status": "verified", "fallback_origin": None,
        "reported_validation_json": json.dumps([{"reported_validation": {"parse_ok": True}}]),
        "admitted": False, "training_qualified": False, "independent_validation": False,
    }
    value["formula_sha256"] = hashlib.sha256(value["formula_text"].encode()).hexdigest()
    value.update(changes)
    return value


def inspect(value):
    return audit.audit_row(value, line_number=7, raw_line_sha256="f" * 64)


@pytest.mark.parametrize("claim", ["storage_split", "training_qualified", "admitted", "independent_validation"])
def test_claims_and_syntax_never_promote_to_gold(claim):
    result = inspect(row(**{claim: "train" if claim == "storage_split" else True}))
    assert result["training_qualified"] is False
    assert result["verification"]["logic_syntax"] == "not_run"
    assert result["verification"]["lake"] == "not_run"
    assert result["verification"]["semantic_review"] == "not_performed"
    assert result["reported_validation_flags"][0]["value"] is True
    if claim != "storage_split":
        assert result["producer_claims"][claim] is True
        assert "qualification_claim_requires_independent_evidence" in result["intake_issues"]


def test_missing_evidence_is_unknown_and_reported_document_verification_is_not_repeated():
    value = row()
    del value["producer_origin"]
    del value["source_report_revision"]
    del value["reported_validation_json"]
    result = inspect(value)
    assert result["fallback_origin"] is None
    assert result["reported_validation_flags"] == []
    assert result["producer_claims"]["independent_validation"] is False
    assert "producer_origin" in result["missing_provenance_fields"]
    assert "invalid_or_missing_source_report_revision" in result["intake_issues"]
    assert result["verification"]["original_report_and_document_hashes"] == "not_recomputed"
    assert result["provenance"]["recorded_document_identity_status"] == "verified"


def test_exact_identity_strings_and_unicode_source_are_preserved():
    value = row(source_text="116–283, §1847(d)(1)(D)(i), redesignated pars.")
    result = inspect(value)
    assert result["source_text"] == value["source_text"]
    assert result["source_text_sha256"] == hashlib.sha256(value["source_text"].encode()).hexdigest()
    assert result["formula_text"] == value["formula_text"]
    assert result["formula_hash_verified"] is True
    assert result["provenance"]["source_report_revision"] == value["source_report_revision"]
    assert result["line_number"] == 7
    assert result["raw_line_sha256"] == "f" * 64


@pytest.mark.parametrize("bad", ["", None, 123])
def test_missing_or_invalid_formula_does_not_pass_intake(bad):
    result = inspect(row(formula_text=bad))
    assert "missing_or_empty_formula_text" in result["intake_issues"]
    assert result["formula_hash_verified"] is False
    assert result["training_qualified"] is False


def test_known_fragment_failure_is_review_candidate_with_pinned_evidence():
    result = inspect(row(source_text="L.", source_span_id=next(iter(audit._DOCUMENTED_ISSUES))))
    assert result["target_disposition"] == "repair_review_candidate"
    assert result["training_qualified"] is False
    assert audit.REVISION in result["documented_issue_evidence_url"]


@pytest.mark.parametrize("raw", ['{"valid":true,"valid":false}', '{"valid":NaN}', "not json"])
def test_malformed_producer_json_is_preserved_and_flagged(raw):
    result = inspect(row(reported_validation_json=raw))
    assert result["reported_validation_json"] == raw
    assert "malformed_reported_validation_json" in result["intake_issues"]


def test_local_export_cannot_claim_pin_with_different_manifest(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"training_qualified": true}')
    with pytest.raises(audit.AuditError, match="pinned diagnostic export"):
        audit.audit_export(tmp_path / "formulas.jsonl", manifest)


def test_byte_budget_applies_before_fetch_write(tmp_path):
    class Response(io.BytesIO):
        headers = {"Content-Length": "1000", "x-repo-commit": audit.REVISION}

    with pytest.raises(audit.AuditError, match="byte budget"):
        audit.fetch_pinned_export(tmp_path, max_bytes=100, opener=lambda *a, **k: Response(b"x" * 1000))
    assert list(tmp_path.iterdir()) == []


def test_fetch_rejects_unpinned_response(tmp_path):
    class Response(io.BytesIO):
        headers = {"x-repo-commit": "a" * 40}

    with pytest.raises(audit.AuditError, match="different revision"):
        audit.fetch_pinned_export(tmp_path, opener=lambda *a, **k: Response(b"{}"))


def pinned_fixture(tmp_path, monkeypatch):
    """Substitute a small exact hash commitment without making a network call."""
    raw = (json.dumps(row()) + "\n") * 3
    input_path = tmp_path / "formulas.jsonl"
    input_path.write_text(raw)
    manifest = {
        "files": {"jsonl": {"bytes": len(raw.encode()), "sha256": audit.digest(raw.encode())}},
        "counts": {"formula_row_count": 3, "source_span_observations": 1},
    }
    manifest_raw = json.dumps(manifest).encode()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(manifest_raw)
    monkeypatch.setattr(audit, "MANIFEST_SHA256", audit.digest(manifest_raw))
    return input_path, manifest_path


def test_record_limit_counts_only_observed_prefix_and_preserves_repeats(tmp_path, monkeypatch):
    input_path, manifest_path = pinned_fixture(tmp_path, monkeypatch)
    result = audit.audit_export(input_path, manifest_path, max_records=2)
    assert result["counts"]["formula_occurrences_audited"] == 2
    assert result["counts"]["source_span_ids_observed"] == 1
    assert result["sample"]["export_formula_occurrences"] == 3
    assert result["sample"]["truncated_by_record_limit"] is True
    assert [r["line_number"] for r in result["records"]] == [1, 2]
    assert result["counts"]["training_qualified"] == 0


def test_full_export_hash_is_verified_even_for_one_record_sample(tmp_path, monkeypatch):
    input_path, manifest_path = pinned_fixture(tmp_path, monkeypatch)
    with input_path.open("a") as stream:
        stream.write("{}\n")
    with pytest.raises(audit.AuditError, match="JSONL bytes/hash"):
        audit.audit_export(input_path, manifest_path, max_records=1)


def test_total_local_byte_limit_includes_manifest(tmp_path, monkeypatch):
    input_path, manifest_path = pinned_fixture(tmp_path, monkeypatch)
    with pytest.raises(audit.AuditError, match="byte limit"):
        audit.audit_export(input_path, manifest_path, max_bytes=input_path.stat().st_size)


def test_audit_is_deterministic(tmp_path, monkeypatch):
    input_path, manifest_path = pinned_fixture(tmp_path, monkeypatch)
    assert audit.audit_export(input_path, manifest_path) == audit.audit_export(input_path, manifest_path)
