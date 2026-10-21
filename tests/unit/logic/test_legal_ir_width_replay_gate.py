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


# Declared prerequisites are inspectable without touching the deployment or
# admitting the unavailable numerical route. Historical checks above retain
# their original source prefix and validation behavior.
_PREREQUISITE_FLAGS = (
    "input_files_checked", "executable_presence_checked", "reviewed_route_available",
    "executable_presence_sufficient", "completion_allowed", "resource_admission_granted",
    "encoder_executed", "training_executed", "admitted", "formalized", "proof_authority",
)


def _forbid_prerequisite_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("prerequisite inspection performed I/O, imports or replay")

    for name in ("read_bytes", "read_text", "open", "stat", "lstat", "exists", "is_file", "resolve"):
        monkeypatch.setattr(Path, name, forbidden)
    for name in ("owner", "width_replay_owner", "usc_rows", "read_artifacts", "validate",
                 "enrich", "check_board"):
        monkeypatch.setattr(contract, name, forbidden)
    monkeypatch.setattr(contract.importlib, "import_module", forbidden)
    monkeypatch.setattr(contract.importlib.util, "spec_from_file_location", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)


@pytest.mark.parametrize("task_id,dimension", [("LIRAE-WIDTH-08", 8), ("LIRAE-WIDTH-4096", 4096)])
def test_prerequisite_inspector_is_declared_only_and_performs_no_io(task_id, dimension, monkeypatch):
    with monkeypatch.context() as blocked:
        _forbid_prerequisite_side_effects(blocked)
        result = contract.inspect_width_prerequisites(task_id)
    assert set(result) == {
        "schema", "task_id", "dimension", "diagnostic_scope", "input_availability",
        "reviewed_local_dimensions", "source_contract", "required_inputs", "task_constraints",
        "next_actions", *_PREREQUISITE_FLAGS,
    }
    assert result["schema"] == "legal-ir-width-replay-prerequisites/v1"
    assert result["task_id"] == task_id
    assert type(result["dimension"]) is int and result["dimension"] == dimension
    assert result["diagnostic_scope"] == "declared_requirements_only"
    assert result["input_availability"] == "not_inspected"
    assert result["reviewed_local_dimensions"] == [384, 768]
    assert all(type(value) is int for value in result["reviewed_local_dimensions"])
    assert all(result[key] is False for key in _PREREQUISITE_FLAGS)


@pytest.mark.parametrize("task_id", ["LIRAE-WIDTH-08", "LIRAE-WIDTH-4096"])
def test_prerequisites_preserve_both_exact_physical_source_occurrences(task_id):
    source = contract.inspect_width_prerequisites(task_id)["source_contract"]
    assert set(source) == {
        "repository", "revision", "parquet_sha256", "source_text_policy", "offset_contract", "sources",
    }
    assert source["repository"] == "justicedao/ipfs_uscode"
    assert source["revision"] == "5016b86a273ce5e4ffd066c5ae9f5fe494dd417e"
    assert source["parquet_sha256"] == "4d26df1e3814279e4b4df3af0e454b4f64fc89a81879db926989862b6ad7d8b8"
    assert source["source_text_policy"] == "exact_utf8_no_normalization"
    assert source["offset_contract"] == "zero_based_half_open_utf8_bytes"
    assert source["sources"] == [
        {
            "id": "born-alive-10-1059-n", "legal_id": "usc:us:10:1059",
            "parent_sha256": "6e1086c76b41205ed5caafe80a80ff240b68f6c89484b9d6b3d78f8db8c67bf2",
            "parent_bytes": 30787, "byte_start": 14849, "byte_end": 16175,
            "char_start": 14806, "char_end": 16128, "span_bytes": 1326,
            "span_sha256": "bfdabce62b4c822fa39aaa517ab55815501c68b6fb10ee292accb3015e7c9faf",
            "coverage": "complete_literal_subsection", "full_parent_coverage": False,
            "literal_start": "(n) Dependent Child Defined", "literal_end": " (Added Pub. L. 103",
        },
        {
            "id": "born-alive-1-8-b", "legal_id": "usc:us:1:8",
            "parent_sha256": "fb6eb7e04f50bdba72b954864e4cdc9dcf0a0857e6cc9a5b6e1544b234c64c2a",
            "parent_bytes": 1584, "byte_start": 722, "byte_end": 1282,
            "char_start": 721, "char_end": 1281, "span_bytes": 560,
            "span_sha256": "e9b539bd922e3196c8bef902808393b47ce74601d64353fb505625fa0e006851",
            "coverage": "complete_literal_subsection", "full_parent_coverage": False,
            "literal_start": "(b) As used in this section", "literal_end": " (c) Nothing in this section",
        },
    ]
    for row in source["sources"]:
        assert row["byte_end"] - row["byte_start"] == row["span_bytes"]
        assert row["full_parent_coverage"] is False
        assert all(type(row[key]) is int for key in (
            "parent_bytes", "byte_start", "byte_end", "char_start", "char_end", "span_bytes",
        ))


@pytest.mark.parametrize("task_id", ["LIRAE-WIDTH-08", "LIRAE-WIDTH-4096"])
def test_prerequisite_nested_values_are_fresh_detached_declarations(task_id):
    first = contract.inspect_width_prerequisites(task_id)
    original = raw(first)
    blocker = contract.WidthReplayUnavailable(task_id).receipt
    assert raw(blocker["prerequisites"]) == original
    first["source_contract"]["sources"][0]["parent_sha256"] = "caller-change"
    first["source_contract"]["sources"].pop()
    first["reviewed_local_dimensions"].append(8)
    first["required_inputs"].clear()
    first["task_constraints"].clear()
    first["next_actions"].clear()
    blocker["prerequisites"]["completion_allowed"] = True
    blocker["prerequisites"]["source_contract"]["sources"].clear()
    assert raw(contract.inspect_width_prerequisites(task_id)) == original
    assert raw(contract.WidthReplayUnavailable(task_id).receipt["prerequisites"]) == original


class _TaskIDSubclass(str):
    pass


@pytest.mark.parametrize("task_id", [
    None, True, 8, 4096, {}, [], b"LIRAE-WIDTH-08", "", "all", "LIRAE-WIDTH-8",
    "LIRAE-WIDTH-384", "LIRAE-WIDTH-768", "LIRAE-WIDTH-08 ", "LIRAE-WIDTH-0008",
])
def test_prerequisite_api_rejects_nonexact_task_ids(task_id, monkeypatch):
    with monkeypatch.context() as blocked:
        _forbid_prerequisite_side_effects(blocked)
        with pytest.raises(contract.ContractError):
            contract.inspect_width_prerequisites(task_id)


def test_prerequisite_api_rejects_task_id_string_subclasses(monkeypatch):
    with monkeypatch.context() as blocked:
        _forbid_prerequisite_side_effects(blocked)
        with pytest.raises(contract.ContractError):
            contract.inspect_width_prerequisites(_TaskIDSubclass("LIRAE-WIDTH-08"))


@pytest.mark.parametrize("task_id,expected_ids", [
    ("LIRAE-WIDTH-08", ["LIRAE-WIDTH-08"]),
    ("LIRAE-WIDTH-4096", ["LIRAE-WIDTH-4096"]),
    ("all", ["LIRAE-WIDTH-08", "LIRAE-WIDTH-4096"]),
])
def test_prerequisite_cli_succeeds_without_accessing_root_or_validation(task_id, expected_ids, monkeypatch, capsys):
    with monkeypatch.context() as blocked:
        _forbid_prerequisite_side_effects(blocked)
        assert contract.main([
            "--root", "/declared-only-prerequisite-root-does-not-exist",
            "--inspect-width-prerequisites", task_id,
        ]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    if task_id == "all":
        assert set(result) == {"schema", "diagnostic_scope", "diagnostics", "completion_allowed"}
        assert result["schema"] == "legal-ir-width-replay-prerequisite-bundle/v1"
        assert result["diagnostic_scope"] == "declared_requirements_only"
        assert result["completion_allowed"] is False
        diagnostics = result["diagnostics"]
    else:
        diagnostics = [result]
    assert [row["task_id"] for row in diagnostics] == expected_ids
    assert all(row == contract.inspect_width_prerequisites(row["task_id"]) for row in diagnostics)


def test_prerequisite_cli_rejects_other_width_routes(monkeypatch, capsys):
    with monkeypatch.context() as blocked:
        _forbid_prerequisite_side_effects(blocked)
        with pytest.raises(SystemExit) as raised:
            contract.main(["--inspect-width-prerequisites", "LIRAE-WIDTH-384"])
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid choice" in captured.err


@pytest.mark.parametrize("task_id", ["LIRAE-WIDTH-384", "LIRAE-WIDTH-768"])
def test_existing_local_width_blocker_payloads_are_unchanged(task_id):
    assert contract.WidthReplayUnavailable(task_id).receipt == {
        "schema": "legal-ir-width-replay-capability-blocker/v1", "task_id": task_id,
        "dimension": int(task_id.rsplit("-", 1)[1]), "status": "blocked_input",
        "reason_code": "width_source_bound_replay_unavailable",
        "required_capability": contract.WIDTH_REPLAY_EXECUTABLE,
        "source_hashes": list(contract.SAMPLE_HASHES), "retryable": True,
        "completion_allowed": False, "encoder_executed": False, "training_executed": False,
        "admitted": False, "formalized": False,
    }


@pytest.mark.parametrize("task_id,dimension", [("LIRAE-WIDTH-08", 8), ("LIRAE-WIDTH-4096", 4096)])
def test_prerequisite_requirements_preserve_original_input_and_producer_boundaries(task_id, dimension):
    result = contract.inspect_width_prerequisites(task_id)
    required = result["required_inputs"]
    assert set(required) == {"vectors", "producer", "checkpoint", "replay"}
    assert required["vectors"] == {
        "dimension": dimension,
        "ordered_source_ids": ["born-alive-10-1059-n", "born-alive-1-8-b"],
        "coordinates": "finite_original_native_coordinates_no_padding_truncation_or_relabelling",
        "source_binding": "exact_parent_and_span_hashes_bytes_offsets_and_source_identity",
        "evidence": "original_preserved_vector_bytes_and_authenticated_producer_receipt",
    }
    producer_fields = ["profile_id", "revision", "config_sha256", "core_sha256", "coordinate_contract"]
    if dimension == 4096:
        producer_fields += ["model_sha256", "worker_sha256", "library_sha256", "tokenizer_policy",
                            "pooling", "normalization", "worker_source_sha256", "owner_source_sha256",
                            "vocabulary_owner_source_sha256", "token_ids_and_count"]
    assert type(required["producer"]["identity_fields"]) is list
    assert len(required["producer"]["identity_fields"]) == len(producer_fields)
    assert set(required["producer"]["identity_fields"]) == set(producer_fields)
    expected_producer = {
        "identity_fields": required["producer"]["identity_fields"],
        "compatibility": "matching_preserved_donor_or_decoder_context_contract",
        "authentication": "original_producer_bytes_and_receipt_not_caller_assertion",
    }
    if dimension == 4096:
        expected_producer["source_contract"] = {
            "model_sha256": "4668fd2a6d2764de250489852230e96238eb5c0d7495866eb3b9c6c4fac5c7da",
            "single_sequence": True, "untruncated": True,
            "max_source_tokens_including_special": 512, "pooling": "last", "normalization": "l2",
        }
    assert required["producer"] == expected_producer
    if dimension == 4096:
        producer_source = required["producer"]["source_contract"]
        assert producer_source["single_sequence"] is producer_source["untruncated"] is True
        assert type(producer_source["max_source_tokens_including_special"]) is int
    assert required["checkpoint"] == {
        "identity": "exact_saved_checkpoint_bytes_and_sha256",
        "interface": "compatible_native_input_projection_decoder_head_core_and_coordinate_contract",
    }
    assert required["replay"] == {
        "owner": "scripts/ops/legal_ir/replay_born_alive_width.py",
        "required_route": "explicit_source_bound_dimension_replay_and_independent_verifier",
        "reviewed": False,
    }
    constraints = result["task_constraints"]
    assert constraints["new_training_permitted"] is False
    assert constraints["different_authored_cohort_may_complete"] is False
    assert constraints["source_selection_may_change"] is False
    if dimension == 8:
        assert set(constraints) == {
            "new_training_permitted", "different_authored_cohort_may_complete", "source_selection_may_change",
            "role", "corpus_default", "vector_acquisition",
        }
        assert constraints["role"] == "donor"
        assert constraints["corpus_default"] is False
        assert constraints["vector_acquisition"] == "preserved_compatible_vectors_or_preserved_compatible_source_to8_producer"
    else:
        assert set(constraints) == {
            "new_training_permitted", "different_authored_cohort_may_complete", "source_selection_may_change",
            "new_encoder_execution_permitted", "vector_acquisition", "development_result",
        }
        assert constraints["new_encoder_execution_permitted"] is False
        assert constraints["vector_acquisition"] == "independently_preserved_saved_vectors_only"
        assert constraints["development_result"] == {"successful": 0, "total": 12}
        assert all(type(value) is int for value in constraints["development_result"].values())
    assert type(result["next_actions"]) is list and result["next_actions"]
    assert all(type(action) is str and action.strip() for action in result["next_actions"])
