"""The readable index exposes captured strings, never invented formulas."""
import gzip
import importlib.util
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/export_report_formula_text.py"
spec = importlib.util.spec_from_file_location("report_formula_export", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def publication(tmp_path):
    text = "The agency shall retain records."
    formula = " O(retain(records))\n"
    document = {"views": {"fol/tdfol": {"format": "TDFOL", "metadata": {"validation": {"passed": False}},
        "payload": {"records": [{"source_id": "tdfol:text:abc", "formula": formula,
             "proof_input": formula, "parse_ok": True, "omitted_formula_slots": ["conditions"], "blockers": ["exception"]},
            {"formula": ""}, {"formula": {"predicate": "not a string"}}],
            "triples": [{"subject": "agency", "predicate": "must", "object": "retain"}]}}}}
    raw_doc = module.report._json(document)
    rows = [{"source_span_id": "span1", "sample_id": "sample1", "text": text,
        "source_sha256": module.report._sha(text.encode()), "legal_id": "usc:5:1",
        "admitted": False, "formalized": False, "lake": {"admitted": False},
        "logic_target_observation": {"document": document, "document_bytes": len(raw_doc),
                                      "document_sha256": module.report._sha(raw_doc)}},
        {"source_span_id": "span2", "text": "Missing.", "source_sha256": module.report._sha(b"Missing."),
         "admitted": False, "formalized": False, "logic_target_observation": {"reason": "too large"}}]
    receipt = {"schema_version": "legacy-span-cuda-diagnostic/v1", "admitted": False,
        "formalized": False, "training_executed": False, "requested_span_count": 2,
        "sample_count": 1, "rows": rows}
    source = tmp_path / "receipt.json"; source.write_text(json.dumps(receipt))
    prepared = module.report.prepare_report(source, tmp_path / "reports")
    pub = {"schema": "uscode-full-logic-report-publication/v1", "uploaded": True,
        "repository_id": module.report.REPOSITORY,
        "dry_run": False, "commit_sha": "a" * 40, "manifest": prepared["manifest"],
        "report": prepared["report"], "original": prepared["original"]}
    pub_path = tmp_path / "publication.json"; pub_path.write_text(json.dumps(pub))
    return pub_path, pub, formula


def test_exact_occurrences_pointers_and_flags_not_authority(tmp_path):
    pub, _, formula = publication(tmp_path)
    result = module.export([pub], tmp_path / "out")
    assert result["counts"] == {"available_document_count": 1, "formula_row_count": 2,
        "identity_verified_document_count": 1, "source_span_observations": 2, "unavailable_document_count": 1,
        "fallback_formula_occurrence_count": 2}
    rows = [json.loads(line) for line in Path(result["files"]["jsonl"]["path"]).read_text().splitlines()]
    assert len(rows) == 2
    assert list(rows[0])[:5] == ["source_text", "formula_text", "view_name", "producer_origin", "fallback_origin"]
    for row in rows:
        assert row["formula_text"] == formula
        assert row["fallback_origin"] is True
        assert row["producer_record_source_id"] == "tdfol:text:abc"
        assert row["decoded_document_json_pointer"].startswith("/views/fol~1tdfol/payload/records/0/")
        assert row["independent_validation"] is row["admitted"] is row["learned_formula_generation"] is False
        assert '"parse_ok":true' in row["reported_validation_json"]
        assert '"passed":false' in row["reported_validation_json"]
        assert '"omitted_formula_slots":["conditions"]' in row["reported_validation_json"]
        assert '"blockers":["exception"]' in row["reported_validation_json"]
    table = pq.read_table(result["files"]["parquet"]["path"])
    assert table.column_names[:5] == ["source_text", "formula_text", "view_name", "producer_origin", "fallback_origin"]
    assert table.to_pylist() == rows
    assert module.export([pub, pub], tmp_path / "out") == result


def test_tampered_compressed_or_original_identity_rejected(tmp_path):
    pubpath, pub, _ = publication(tmp_path)
    packed_path = Path(pub["report"]["path"])
    packed_path.write_bytes(packed_path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="hash or byte"):
        module.load_publication(pubpath)


def test_wrong_decompressed_identity_rejected(tmp_path):
    pubpath, pub, _ = publication(tmp_path)
    manifest_path = Path(pub["manifest"]["path"])
    manifest = json.loads(manifest_path.read_text())
    pub["original"]["sha256"] = "b" * 64; manifest["original"] = pub["original"]
    raw = module.report._json(manifest); manifest_path.write_bytes(raw)
    pub["manifest"]["sha256"] = module.report._sha(raw); pub["manifest"]["bytes"] = len(raw)
    pubpath.write_text(json.dumps(pub))
    with pytest.raises(ValueError, match="hash or byte"):
        module.load_publication(pubpath)


def test_nonfinite_json_rejected():
    with pytest.raises(ValueError, match="nonfinite"):
        module.report._load(b'{"formula":"x", "score":NaN}')


def test_byte_and_row_bounds_leave_no_partial_output(tmp_path):
    pub, _, _ = publication(tmp_path)
    for kwargs in ({"max_rows": 1}, {"max_bytes": 10}):
        with pytest.raises(ValueError, match="bound"):
            module.export([pub], tmp_path / "out", **kwargs)
        assert not (tmp_path / "out").exists()


def test_gzip_decompression_bounded_before_parsing(tmp_path, monkeypatch):
    pub, _, _ = publication(tmp_path)
    monkeypatch.setattr(module.report, "MAX_BYTES", 20)
    with pytest.raises(ValueError, match="decompressed byte bound"):
        module.load_publication(pub)


@pytest.mark.parametrize("document", ["publication", "manifest"])
@pytest.mark.parametrize("repository_id", [None, "other-owner/different-dataset"])
def test_wrong_or_missing_repository_rejected_even_with_matching_hashes(tmp_path, document, repository_id):
    pubpath, pub, _ = publication(tmp_path)
    if document == "publication":
        pub["repository_id"] = repository_id
    else:
        manifest_path = Path(pub["manifest"]["path"])
        manifest = json.loads(manifest_path.read_text())
        manifest["repository_id"] = repository_id
        raw = module.report._json(manifest)
        manifest_path.write_bytes(raw)
        pub["manifest"]["sha256"] = module.report._sha(raw)
        pub["manifest"]["bytes"] = len(raw)
    pubpath.write_text(json.dumps(pub))
    with pytest.raises(ValueError, match=document + " repository differs"):
        module.load_publication(pubpath)
