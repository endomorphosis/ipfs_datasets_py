"""Exact finite source-state replay, mixed batches and actual kernel checks."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_state_lake as api
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression


def row(identity="addition", *, operator="+", source_operator=None, temporary=False):
    boolean = operator in {"<", "<=", ">", ">=", "==", "!="}
    source = f"def compute(left: int, right: int) -> {'bool' if boolean else 'int'}:\n"
    expression = f"left {source_operator or operator} right"
    source += (f"    value = {expression}\n    return value\n" if temporary
        else f"    return {expression}\n")
    ids = ("expr:left", "expr:right")
    candidate = dict(kind="program_expression", document=ProgramExpression(
        "expr:result", "binary", "boolean" if boolean else "integer",
        operand_ids=ids, evaluation_order=ids, operator=operator,
        source_ref_ids=("source",)).to_dict())
    return dict(id=identity, source_text=source, candidate_ir=candidate,
        input_domains={"left": {"lower": -1, "upper": 1},
                       "right": {"lower": 0, "upper": 1}})


def tools():
    values = {name: os.environ.get(variable) for name, variable in (
        ("lake_executable", "IR384_TEST_LAKE_EXECUTABLE"),
        ("java_executable", "IR384_TEST_JAVA_EXECUTABLE"),
        ("tla2tools_jar", "IR384_TEST_TLA2TOOLS_JAR"))}
    if not all(values.values()):
        pytest.skip("actual Lake and Java17/SANY tools required")
    return values


def test_preparation_keeps_unchanged_predictions_and_complete_domains():
    rows = [row(temporary=True)]
    before = deepcopy(rows)
    report = api.prepare_source_state_lean(rows)
    assert rows == before
    item = report["rows"][0]
    assert item["status"] == "prepared" and item["case_count"] == 6
    assert item["model"]["candidate_ir"] == rows[0]["candidate_ir"]
    assert item["model"]["source_text"] == rows[0]["source_text"]
    assert report["automatic_operational_model"] and not report["input_domains_inferred"]
    assert not report["candidate_repaired"] and not report["model_inference_performed"]
    assert not report["finite_correspondence_kernel_checked"]
    assert not report["source_executed"] and not report["source_semantics_verified"]
    assert not report["backend_executed"] and not report["proof_authority"]
    assert item["lowering"]["bounded_tla"]["model_text"].startswith("---- MODULE")


@pytest.mark.parametrize("change", ["candidate", "missing_prediction", "source", "domains"])
def test_unsupported_source_candidate_or_domains_remain_visible_without_tools(change):
    invalid = row()
    if change == "candidate":
        invalid["candidate_ir"]["document"]["operator"] = "-"
    elif change == "missing_prediction":
        invalid["candidate_ir"] = None
    elif change == "source":
        invalid["source_text"] += "print('must not execute')\n"
    else:
        invalid["input_domains"]["left"]["upper"] = 1000
    result = api.build_source_state_lake([invalid], lake_executable="/no/lake/selected").to_dict()
    assert result["status"] == "blocked" and result["supported_count"] == 0
    assert len(result["rows"]) == 1 and result["rows"][0]["reason"]
    assert result["rows"][0]["model"] is None
    assert not result["backend_executed"] and not result["all_candidates_checked"]


@pytest.mark.parametrize("change", ["extra_target", "duplicate_id", "empty", "too_many"])
def test_batch_boundaries_reject_ambiguous_or_target_bearing_inputs(change):
    rows = [row()]
    if change == "extra_target": rows[0]["target"] = rows[0]["candidate_ir"]
    elif change == "duplicate_id": rows += deepcopy(rows)
    elif change == "empty": rows = []
    else: rows = [row(str(i)) for i in range(17)]
    with pytest.raises(ValueError):
        api.prepare_source_state_lean(rows)


def test_unavailable_lake_is_not_kernel_evidence():
    rows = [row()]
    report = api.verify_source_state_lake(api.build_source_state_lake(rows,
        lake_executable="/no/lake/selected"), rows)
    assert report["status"] == "unavailable"
    assert not report["all_candidates_checked"]
    assert not report["finite_correspondence_kernel_checked"]
    assert report["rows"][0]["sany_status"] == "not_run"


def test_saved_receipts_and_changed_inputs_cannot_verify_a_live_build():
    rows = [row()]
    execution = api.build_source_state_lake(rows, lake_executable="/no/lake/selected")
    receipt = execution.to_dict()
    with pytest.raises(ValueError, match="live issued"):
        api.verify_source_state_lake(receipt, rows)
    with pytest.raises(ValueError, match="unissued"):
        api.SourceStateLakeExecution().to_dict()
    for key in ("source_text", "candidate_ir", "input_domains"):
        changed = deepcopy(rows)
        if key == "source_text": changed[0][key] += "\n"
        elif key == "candidate_ir": changed[0][key]["document"]["operator"] = "-"
        else: changed[0][key]["left"]["lower"] = 0
        with pytest.raises(ValueError, match="identity"):
            api.verify_source_state_lake(execution, changed)
    receipt["rows"].clear()
    assert len(execution.to_dict()["rows"]) == 1


def test_loaded_emitter_code_changes_are_rejected(monkeypatch):
    api._guard()
    monkeypatch.setattr(api.emitter, "emit_source_state_model", lambda model: ("", {}))
    with pytest.raises(ValueError, match="executed code changed"):
        api._guard()


def test_transitive_native_owners_are_pinned_and_loaded_changes_reject(monkeypatch):
    from ipfs_datasets_py.logic.ir_core import provenance
    names = {module.__name__ for module in api._owners()}
    assert {"ipfs_datasets_py.logic.ir_core.provenance",
        "ipfs_datasets_py.logic.ir_core.canonical",
        "ipfs_datasets_py.logic.ir_core.identity",
        "ipfs_datasets_py.logic.syntax_core.ast",
        "ipfs_datasets_py.logic.software_verification.ir"} <= names
    api._guard()
    monkeypatch.setattr(provenance.SourceRef, "from_dict", classmethod(lambda cls, value: None))
    with pytest.raises(ValueError, match="executed code changed"):
        api._guard()


def test_tool_selection_and_output_boundaries(tmp_path):
    with pytest.raises(ValueError, match="together"):
        api.build_source_state_lake([row()], lake_executable="unused", java_executable="java")
    with pytest.raises(ValueError, match="timeout"):
        api.build_source_state_lake([row()], lake_executable="unused", timeout_seconds=True)
    with pytest.raises(ValueError, match="fresh"):
        api.build_source_state_lake([row()], lake_executable="unused", output_directory=tmp_path)


def test_real_lake_checks_every_case_and_sany_checks_the_same_transition_model(tmp_path):
    rows = [row(temporary=True), row("less", operator="<")]
    handle = api.build_source_state_lake(rows, **tools(), output_directory=tmp_path / "native")
    receipt = api.verify_source_state_lake(handle, rows)
    assert receipt["status"] == "passed", receipt.get("execution")
    assert receipt["all_candidates_checked"] and receipt["finite_correspondence_kernel_checked"]
    assert sum(item["case_count"] for item in receipt["rows"]) == 12
    assert all(item["lake_status"] == item["sany_status"] == "passed" for item in receipt["rows"])
    assert not receipt["source_semantics_verified"] and not receipt["proof_authority"]
    assert not receipt["model_checker_executed"]
    assert json.loads((tmp_path / "native/receipt.json").read_text()) == receipt
    assert len(list((tmp_path / "native").glob("*.tla"))) == 2


def test_real_mixed_batch_does_not_hide_a_missing_prediction():
    rejected = row("rejected"); rejected["candidate_ir"] = None
    report = api.build_source_state_lake([row(), rejected], **tools()).to_dict()
    assert report["status"] == "partial", report.get("execution")
    assert report["supported_count"] == 1 and report["count"] == 2
    assert not report["all_candidates_checked"] and not report["finite_correspondence_kernel_checked"]
    assert report["rows"][0]["finite_correspondence_kernel_checked"]
    assert not report["rows"][1]["finite_correspondence_kernel_checked"]


def test_cli_prepares_exact_original_rows_without_model_or_tool_calls(tmp_path):
    rows_file = tmp_path / "rows.json"; rows_file.write_text(json.dumps([row()]))
    output = tmp_path / "prepared.json"
    root = Path(__file__).resolve().parents[5]
    command = [sys.executable, str(root / "scripts/ops/autoencoder/run_distributed_384.py"),
        "source-state", "--rows", str(rows_file), "--result", str(output)]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report == json.loads(output.read_text())
    assert report["rows"][0]["case_count"] == 6
    assert not report["backend_executed"] and report["provider_calls"] == 0
