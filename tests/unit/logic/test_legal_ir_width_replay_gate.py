"""A missing source-bound replay cannot be replaced by asserted WIDTH metrics."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "legal_ir_width_replay_gate_owner",
    ROOT / "scripts/ops/legal_ir/legal_ir_supervisor_contract.py",
)
contract = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = contract
spec.loader.exec_module(contract)


def raw(value):
    return json.dumps(value, sort_keys=True).encode()


def observation(dimension):
    checkpoint = b"arbitrary bytes with no trained tensors or replay"
    row = {
        "dimension": dimension,
        "source_hashes": list(contract.SAMPLE_HASHES),
        "profile_id": "provider-asserted-profile",
        "checkpoint_sha256": contract.sha(checkpoint),
        "status": "observed",
        "training_executed": False,
        "admitted": False,
        "formalized": False,
        "metrics": {"cosine_similarity": .5, "reconstruction_loss": .25},
        "corpus_default": dimension == 384,
        "role": "donor",
        "token_ceiling": 512,
        "encoder_executed": False,
        "development_result": {"successful": 0, "total": 12},
    }
    return {"evidence": {"dimension": dimension}}, {
        "observation": raw(row), "checkpoint": checkpoint,
    }


@pytest.mark.parametrize("dimension", [8, 384, 768, 4096])
@pytest.mark.parametrize("asserted_replay", [False, True])
def test_arbitrary_checkpoint_and_asserted_replay_never_complete(dimension, asserted_replay):
    receipt, data = observation(dimension)
    if asserted_replay:
        data["replay"] = raw({
            "verified": True, "source_hashes": contract.SAMPLE_HASHES,
            "checkpoint_sha256": contract.sha(data["checkpoint"]),
            "metrics": {"cosine_similarity": .5, "reconstruction_loss": .25},
        })
    task_id = "LIRAE-WIDTH-" + ("08" if dimension == 8 else str(dimension))
    with pytest.raises(contract.WidthReplayUnavailable) as raised:
        contract.validate_width(task_id, receipt, data)
    blocker = raised.value.receipt
    assert blocker["reason_code"] == "width_source_bound_replay_unavailable"
    assert blocker["task_id"] == task_id
    assert blocker["dimension"] == dimension
    assert blocker["status"] == "blocked_input"
    assert blocker["completion_allowed"] is False
    assert blocker["retryable"] is True
    assert blocker["source_hashes"] == contract.SAMPLE_HASHES
    assert blocker["encoder_executed"] is False
    assert blocker["training_executed"] is False
    assert blocker["admitted"] is blocker["formalized"] is False


def test_an_executable_with_the_expected_name_cannot_bypass_validation(tmp_path, monkeypatch):
    executable = tmp_path / contract.WIDTH_REPLAY_EXECUTABLE
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    receipt, data = observation(384)
    with pytest.raises(contract.WidthReplayUnavailable):
        contract.validate_width("LIRAE-WIDTH-384", receipt, data)


@pytest.mark.parametrize("change", ["encoder", "development", "training", "sources"])
def test_original_source_and_no_encoder_constraints_are_retained(change):
    receipt, data = observation(4096)
    row = json.loads(data["observation"])
    if change == "encoder":
        row["encoder_executed"] = True
    elif change == "development":
        row["development_result"] = {"successful": 2, "total": 2}
    elif change == "training":
        row["training_executed"] = True
    else:
        row["source_hashes"] = ["historical-authored-cohort"]
    data["observation"] = raw(row)
    with pytest.raises(contract.ContractError) as raised:
        contract.validate_width("LIRAE-WIDTH-4096", receipt, data)
    assert not isinstance(raised.value, contract.WidthReplayUnavailable)


@pytest.mark.parametrize("dimension", ["08", "384", "768", "4096"])
def test_width_declares_missing_capability_without_changing_required_tests(dimension):
    task_id = "LIRAE-WIDTH-" + dimension
    result = contract.task_contract({"task_id": task_id, "predicted_files": []})
    assert result["required_validation_executables"] == [contract.WIDTH_REPLAY_EXECUTABLE]
    assert len(result["validation_commands"]) == 2
    assert "python3 -m pytest " in result["validation_commands"][0]
    assert result["validation_commands"][1].endswith(" --check-task " + task_id)
    assert "test_legal_ir_width_replay_gate.py" not in " ".join(result["allowed_paths"])
    assert "blocked-input" in result["receipt_instructions"]


@pytest.mark.parametrize("task_id,executables", [
    ("LIRAE-USC-T01", []), ("LIRAE-CONST-A1", []),
    ("LIRAE-METHOD-01", ["lake", "lean"]),
])
def test_unrelated_tasks_keep_their_existing_prerequisites(task_id, executables):
    result = contract.task_contract({"task_id": task_id, "predicted_files": []})
    assert result["required_validation_executables"] == executables


def test_cli_emits_typed_temporary_blocker_instead_of_completion(tmp_path, capsys):
    task_id = "LIRAE-WIDTH-4096"
    task_directory = tmp_path / contract.directory(task_id)
    task_directory.mkdir(parents=True)
    receipt, data = observation(4096)
    receipt.update(schema=contract.SCHEMA, task_id=task_id, task_kind="width",
                   status="implemented", authority={"admitted": False, "formalized": False})
    receipt["artifacts"] = []
    for label, content in data.items():
        relative = contract.directory(task_id) / (label + ".json")
        (tmp_path / relative).write_bytes(content)
        receipt["artifacts"].append({"kind": label, "path": relative.as_posix(),
                                     "sha256": contract.sha(content)})
    (task_directory / "receipt.json").write_bytes(raw(receipt))
    plan_path = tmp_path / contract.PLAN
    plan_path.parent.mkdir(parents=True)
    plan_path.write_bytes(raw({"tasks": [{"task_id": task_id}]}))
    assert contract.main(["--root", str(tmp_path), "--check-task", task_id]) == 75
    output = capsys.readouterr()
    assert output.out == ""
    blocker = json.loads(output.err)
    assert blocker["reason_code"] == "width_source_bound_replay_unavailable"
    assert blocker["completion_allowed"] is False
    assert blocker["status"] == "blocked_input"
