"""Live, nonvacuous effect checks with two original source identities."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_code_effects_lake as api
from .test_intent_code_effects import fixture


def row(status="satisfied", identity=None):
    inputs = fixture(status)
    return dict(id=identity or status, **dict(zip(("intent_source_text", "intent_candidate_ir",
        "code_source_text", "code_candidate_ir", "input_domains", "association"), inputs)))


def lake():
    value = os.environ.get("IR384_TEST_LAKE_EXECUTABLE")
    if not value:
        pytest.skip("real native Lake required")
    return value


def test_preparation_keeps_distinct_sources_candidates_and_every_disposition():
    rows = [row(value) for value in ("satisfied", "refuted", "no_enabled_cases")]
    before = deepcopy(rows)
    report = api.prepare_intent_code_effects_lean(rows)
    assert rows == before
    assert report["supported_count"] == 3, report["rows"]
    assert [r["effect_status"] for r in report["rows"]] == [r["id"] for r in rows]
    assert [r["enabled_case_count"] for r in report["rows"]] == [9, 9, 0]
    for result, original in zip(report["rows"], rows):
        assert result["intent_source_sha256"] != result["code_source_sha256"]
        assert result["contract"]["intent_candidate_ir"] == original["intent_candidate_ir"]
        assert result["contract"]["code_candidate_ir"] == original["code_candidate_ir"]
        assert result["case_count"] == 9
        assert not result["bounded_effects_satisfied"] and not result["finite_effects_kernel_checked"]
    assert not report["backend_executed"] and not report["all_candidates_checked"]


@pytest.mark.parametrize("change", ["intent_source", "code_source", "intent_candidate", "code_candidate", "association", "domains"])
def test_invalid_contracts_remain_in_the_denominator_without_empty_proofs(change):
    value = row()
    if change.endswith("source"):
        value[change + "_text"] += "\n"
    elif change.endswith("candidate"):
        value[change + "_ir"] = None
    elif change == "association":
        value["association"]["intent_document_sha256"] = "0" * 64
    else:
        value["input_domains"]["left"]["upper"] = 10
    report = api.build_intent_code_effects_lake([value], lake_executable="/absent/lake").to_dict()
    assert report["status"] == "blocked" and report["supported_count"] == 0
    assert len(report["rows"]) == 1 and report["rows"][0]["reason"]
    assert not report["backend_executed"] and not report["bounded_effects_satisfied"]


@pytest.mark.parametrize("change", ["target", "duplicate", "empty", "too_many"])
def test_closed_batch_boundaries(change):
    rows = [row()]
    if change == "target": rows[0]["target"] = rows[0]["code_candidate_ir"]
    elif change == "duplicate": rows += deepcopy(rows)
    elif change == "empty": rows = []
    else: rows = [row(identity=str(i)) for i in range(17)]
    with pytest.raises(ValueError): api.prepare_intent_code_effects_lean(rows)


def test_unavailable_checker_and_saved_receipts_cannot_claim_checked_effects():
    rows = [row()]
    execution = api.build_intent_code_effects_lake(rows, lake_executable="/absent/lake")
    report = api.verify_intent_code_effects_lake(execution, rows)
    assert report["status"] == "unavailable"
    assert not report["all_candidates_checked"] and not report["bounded_effects_satisfied"]
    with pytest.raises(ValueError, match="live issued"):
        api.verify_intent_code_effects_lake(report, rows)
    with pytest.raises(ValueError, match="unissued"):
        api.IntentCodeEffectsLakeExecution().to_dict()
    for key in ("intent_source_text", "code_source_text", "intent_candidate_ir", "code_candidate_ir",
            "input_domains", "association"):
        changed = deepcopy(rows)
        if key.endswith("text"): changed[0][key] += "\n"
        else: changed[0][key] = {}
        with pytest.raises(ValueError, match="identity"):
            api.verify_intent_code_effects_lake(execution, changed)
    report["rows"].clear()
    assert len(execution.to_dict()["rows"]) == 1


def test_loaded_owner_code_drift_is_rejected(monkeypatch):
    api._guard()
    monkeypatch.setattr(api.contracts, "prepare_intent_code_effects", lambda *a: {})
    with pytest.raises(ValueError, match="executed code changed"):
        api._guard()


def test_output_and_tool_boundaries(tmp_path):
    with pytest.raises(ValueError, match="timeout"):
        api.build_intent_code_effects_lake([row()], lake_executable="absent", timeout_seconds=True)
    with pytest.raises(ValueError, match="fresh"):
        api.build_intent_code_effects_lake([row()], lake_executable="absent", output_directory=tmp_path)


def test_real_lake_separates_satisfaction_refutation_and_no_enabled_cases(tmp_path):
    rows = [row(value) for value in ("satisfied", "refuted", "no_enabled_cases")]
    execution = api.build_intent_code_effects_lake(rows, lake_executable=lake(), output_directory=tmp_path / "native")
    report = api.verify_intent_code_effects_lake(execution, rows)
    assert report["status"] == "passed", report.get("execution")
    assert report["all_candidates_checked"] and report["finite_effects_kernel_checked"]
    assert not report["bounded_effects_satisfied"]
    assert [r["bounded_effects_satisfied"] for r in report["rows"]] == [True, False, False]
    assert [r["counterexample_kernel_checked"] for r in report["rows"]] == [False, True, False]
    assert all(r["finite_effects_kernel_checked"] for r in report["rows"])
    assert sum(r["case_count"] for r in report["rows"]) == 27
    assert not report["whole_instruction_verified"] and not report["source_semantics_verified"]
    assert json.loads((tmp_path / "native/receipt.json").read_text()) == report


def test_real_mixed_batch_cannot_hide_invalid_intent_association():
    invalid = row(identity="invalid"); invalid["association"]["action_id"] = "foreign"
    report = api.build_intent_code_effects_lake([row(), invalid], lake_executable=lake()).to_dict()
    assert report["status"] == "partial", report.get("execution")
    assert report["rows"][0]["bounded_effects_satisfied"]
    assert not report["rows"][1]["finite_effects_kernel_checked"]
    assert not report["all_candidates_checked"] and not report["bounded_effects_satisfied"]


def test_cli_prepares_without_model_or_tool_calls(tmp_path):
    inputs = tmp_path / "inputs.json"; inputs.write_text(json.dumps([row()]))
    output = tmp_path / "prepared.json"
    root = Path(__file__).resolve().parents[5]
    result = subprocess.run([sys.executable, str(root / "scripts/ops/autoencoder/run_distributed_384.py"),
        "intent-code-effects", "--rows", str(inputs), "--result", str(output)],
        cwd=root, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report == json.loads(output.read_text())
    assert report["rows"][0]["case_count"] == 9
    assert not report["backend_executed"] and not report["bounded_effects_satisfied"]
