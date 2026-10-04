"""Posthoc comparison rejects changed predictions and false build evidence."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/summarize_legal_qualified_decoder_outputs.py"
SPEC = importlib.util.spec_from_file_location("legal_qualified_summary", SCRIPT)
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


def candidate():
    source = "Officer shall file the report if notified unless exempt within 30 days."
    return {"candidate_id": "example", "source_text": source,
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "canonical_ir": {"rules": [{"modality": "O", "actor": "Officer", "action": "file", "object": "report",
                "conditions": ["if notified"], "exceptions": ["unless exempt"], "temporal": ["within 30 days"]}]}}


def test_exact_selection_and_all_qualifiers_are_retained():
    row = candidate()
    source = {"id": row["candidate_id"], "source_text": row["source_text"], "source_sha256": row["source_sha256"]}
    entry = {"candidate": row, "interpretation": summary.expected_interpretation(row)}
    assert summary.verify_selected_entry(source, {"canonical_ir": row["canonical_ir"]}, entry) == row
    formula = entry["interpretation"]["formulas"][0]
    assert formula["temporal"]["source_index"] == 1
    assert formula["temporal"]["source_text"] == "within 30 days"
    assert formula["exceptions"][0]["source_text"] == "unless exempt"


@pytest.mark.parametrize("facet", ["conditions", "exceptions", "temporal"])
def test_dropping_predicted_qualifier_cannot_pass_selection(facet):
    row = candidate()
    source = {"id": row["candidate_id"], "source_text": row["source_text"], "source_sha256": row["source_sha256"]}
    changed = deepcopy(row)
    changed["canonical_ir"]["rules"][0][facet] = []
    entry = {"candidate": changed, "interpretation": summary.expected_interpretation(changed)}
    with pytest.raises(ValueError, match="exact frozen generation"):
        summary.verify_selected_entry(source, {"canonical_ir": row["canonical_ir"]}, entry)


def test_interpretation_binding_cannot_exchange_condition_and_exception():
    row = candidate()
    source = {"id": row["candidate_id"], "source_text": row["source_text"], "source_sha256": row["source_sha256"]}
    interpretation = summary.expected_interpretation(row)
    interpretation["formulas"][0]["conditions"][0]["source_text"] = "unless exempt"
    with pytest.raises(ValueError, match="predicted qualifier"):
        summary.verify_selected_entry(source, {"canonical_ir": row["canonical_ir"]}, {"candidate": row, "interpretation": interpretation})


def test_calendar_literal_has_no_invented_duration():
    row = candidate()
    row["canonical_ir"]["rules"][0]["temporal"] = ["before January 1"]
    with pytest.raises(ValueError, match="calendar"):
        summary.expected_interpretation(row)


def test_omitted_qualifiers_and_reference_mismatch_are_separate_from_compilation():
    wanted = candidate()["canonical_ir"]
    predicted = deepcopy(wanted)
    predicted["rules"][0]["exceptions"] = []
    comparison = summary.compare_ir(predicted, wanted)
    assert comparison["omitted_reference_qualifiers"] == {"conditions": 0, "exceptions": 1, "temporal": 0}
    assert not comparison["exact_authored_reference_match"]
    counts = summary.aggregate([{**comparison, "old_built": False, "new_built": True}])
    assert counts["new_built_count"] == counts["new_compiled_reference_mismatches"] == 1
    assert counts["all_prediction_facets_unchanged_between_profiles"] is True


def test_multi_rule_qualifier_comparison_does_not_flatten_attachments():
    wanted = candidate()["canonical_ir"]
    wanted["rules"].append(deepcopy(wanted["rules"][0]))
    wanted["rules"][1]["conditions"] = []
    predicted = deepcopy(wanted)
    predicted["rules"][1]["conditions"], predicted["rules"][0]["conditions"] = predicted["rules"][0]["conditions"], []
    comparison = summary.compare_ir(predicted, wanted)
    assert not comparison["facet_matches"]["conditions"]
    assert comparison["omitted_reference_qualifiers"]["conditions"] == 1
    assert comparison["additional_predicted_qualifiers"]["conditions"] == 1


def test_incomplete_build_blocks_reference_access(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(summary, "read", lambda path: opened.append(path))
    with pytest.raises(ValueError, match="completed qualified build summary"):
        summary.summarize(tmp_path, tmp_path / "missing", tmp_path, tmp_path / "out.json")
    assert opened == []


def receipt_fixture(tmp_path):
    from ipfs_datasets_py.logic.autoformal import legal_qualified_lake as gate
    row = candidate()
    entries = [{"candidate": row, "interpretation": summary.expected_interpretation(row)}]
    prepared = gate.prepare_qualified_legal(entries, toolchain="leanprover/lean4:v4.34.1")
    manifest = prepared.to_dict()
    for name, body in prepared.files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    (tmp_path / "qualified-manifest.json").write_text(json.dumps(manifest))
    binaries = {}
    for name in ("lake", "lean"):
        path = tmp_path / name
        path.write_bytes(b"\x7fELFfixture")
        binaries[str(path)] = summary.sha(path)
    command = [str(tmp_path / "lake"), "build", "legal"]
    modules = ["LegalQualified.Prelude", "LegalQualified.Candidate0000", "LegalQualified"]
    receipt = {**manifest, "status": "passed", "build_passed": True, "backend_executed": True,
        "manifest_coverage_passed": True, "compiled_modules": modules, "command": command,
        "command_sha256": summary.digest(command), "returncode": 0, "binary_sha256": binaries,
        "binary_pins_match": True, "stdout": "", "stderr": "",
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        "version_probe": {name: {"command": [str(tmp_path / name), "--version"], "stdout": "Lean (version 4.34.1)", "stderr": "", "returncode": 0} for name in ("lake", "lean")},
        "artifact_sha256": {".lake/build/lib/lean/" + module.replace(".", "/") + ".olean": "a" * 64 for module in modules},
        **{flag: False for flag in ("timed_out", "output_truncated", "workspace_limit_exceeded", "resource_exhausted", "unavailable", "cancelled")}}
    return entries, receipt


def write_receipt(tmp_path, receipt):
    receipt = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = summary.digest(receipt)
    path = tmp_path / "qualified-receipt.json"
    path.write_text(json.dumps(receipt))
    return {"path": str(path), "sha256": summary.sha(path)}


def test_receipt_verifier_checks_all_bound_files(tmp_path):
    entries, receipt = receipt_fixture(tmp_path)
    reference = write_receipt(tmp_path, receipt)
    assert summary.verify_receipt(reference, entries, qualified=True)["build_passed"]
    (tmp_path / "LegalQualified/Candidate0000.lean").write_text("changed")
    with pytest.raises(ValueError, match="emitted source differs"):
        summary.verify_receipt(reference, entries, qualified=True)


def test_false_success_without_complete_module_coverage_rejected(tmp_path):
    entries, receipt = receipt_fixture(tmp_path)
    del receipt["artifact_sha256"][".lake/build/lib/lean/LegalQualified/Candidate0000.olean"]
    with pytest.raises(ValueError, match="coverage claim differs"):
        summary.verify_receipt(write_receipt(tmp_path, receipt), entries, qualified=True)


def test_no_backend_execution_cannot_be_success(tmp_path):
    entries, receipt = receipt_fixture(tmp_path)
    receipt["backend_executed"] = False
    with pytest.raises(ValueError, match="lacks execution"):
        summary.verify_receipt(write_receipt(tmp_path, receipt), entries, qualified=True)


def test_changed_executable_pin_rejected(tmp_path):
    entries, receipt = receipt_fixture(tmp_path)
    reference = write_receipt(tmp_path, receipt)
    (tmp_path / "lean").write_bytes(b"different")
    with pytest.raises(ValueError, match="executable hash differs"):
        summary.verify_receipt(reference, entries, qualified=True)
