"""Authored metadata and file controls; no Torch, model or training is executed."""
from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_f18_conditions_v1 as adapter


def job_mapping(tmp_path, *, steps=2):
    descriptor = lambda name: {"path": str(tmp_path / name), "bytes": 2, "sha256": "1" * 64}
    return {"schema_version": adapter.SCHEMA_VERSION, "run_id": "f18-authored-fixture",
        "output_directory": str(tmp_path / "outputs"), "prepared_inputs": descriptor("prepared.json"),
        "initial_checkpoint": descriptor("initial.json"),
        "physical_assets": [{"role": role, **descriptor(role)} for role in adapter.ASSET_ROLES],
        "source_pins": {name: {"bytes": 1, "sha256": sha or "2" * 64}
                        for name, sha in adapter.REQUIRED_SOURCE_SHA256.items()},
        "margin_weight": 0.25, "max_steps": steps, "max_seconds": 32, "runtime_contract": None}


def progress(steps):
    return {"epochs_completed": steps // 14, "row_cursor": (steps % 14) * 12, "optimizer_steps": steps}


def receipt(spec, *, before=0, completed=None):
    document = spec.to_dict()
    count = document["max_steps"] if completed is None else completed
    complete = count == document["max_steps"]
    output = Path(spec.output_directory)
    return {"schema_version": adapter.RECEIPT_SCHEMA, "run_id": spec.run_id,
        "job_spec_sha256": spec.canonical_sha256, "job_file_sha256": "3" * 64,
        "prepared_inputs_sha256": document["prepared_inputs"]["sha256"],
        "initial_checkpoint_file_sha256": document["initial_checkpoint"]["sha256"],
        "profile_source_sha256": adapter.PROFILE_SHA256, "margin_weight": document["margin_weight"],
        "requested_steps": document["max_steps"], "completed_steps": count,
        "initial_progress": progress(before), "final_progress": progress(before + count),
        "reason": "step_limit" if complete else "deadline_before_batch",
        "status": "completed" if complete else "partial",
        "checkpoint": {"path": str(output / "checkpoint.json"), "bytes": 2, "sha256": "4" * 64},
        "report": {"path": str(output / "report.json"), "bytes": 2, "sha256": "5" * 64},
        "checkpoint_sha256": "6" * 64, "elapsed_seconds": 1.0,
        "training_executed": bool(count), "all_requested_steps_completed": complete,
        "prepared_inputs_integrity_only": True, "runtime_contract_sha256": None,
        **{key: False for key in adapter.FALSE_FIELDS}}


def prepared():
    return {"schema": adapter.PREPARED_INPUTS_SCHEMA, "state": {}, "provenance": {},
        "records": [{} for _ in range(168)], "teacher": {}, "weights": {},
        "expected_bindings": {key: adapter.BINDINGS_SCHEMA if key == "schema" else "7" * 64
                              for key in adapter.BINDING_FIELDS}}


def test_spec_is_pure_detached_frozen_metadata_without_native_or_model_authority(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs): pytest.fail("metadata construction attempted external action")
    monkeypatch.setattr(adapter.os, "open", forbidden)
    monkeypatch.setattr(adapter.importlib, "import_module", forbidden)
    document = job_mapping(tmp_path)
    spec = adapter.F18JobSpec.from_dict(document)
    digest = spec.canonical_sha256
    document["source_pins"].clear()
    detached = spec.to_dict()
    detached["prepared_inputs"]["sha256"] = "8" * 64
    assert spec.canonical_sha256 == digest
    assert spec.legal_ir_parallel_workers == 1 and spec.max_steps == 2
    assert spec.margin_weight == 0.25
    assert "training_config" not in spec.to_dict()
    with pytest.raises(FrozenInstanceError): spec._document = b"{}"


@pytest.mark.parametrize("change", ["schema", "unknown", "hook", "arm", "bool_arm", "steps", "bool_steps",
    "seconds", "nan", "source_sha", "source_path", "missing_source", "roles", "duplicate_role",
    "relative_output", "input_output_overlap", "duplicate_input", "runtime_sha"])
def test_closed_spec_rejects_incompatible_or_executable_authoring(tmp_path, change):
    value = job_mapping(tmp_path)
    if change == "schema": value["schema_version"] = "training-job-v8"
    elif change == "unknown": value["admitted"] = True
    elif change == "hook": value["worker"] = lambda: None
    elif change == "arm": value["margin_weight"] = 0.5
    elif change == "bool_arm": value["margin_weight"] = False
    elif change == "steps": value["max_steps"] = 33
    elif change == "bool_steps": value["max_steps"] = True
    elif change == "seconds": value["max_seconds"] = 33
    elif change == "nan": value["max_seconds"] = float("nan")
    elif change == "source_sha": value["source_pins"][adapter.PROFILE_RELATIVE_PATH]["sha256"] = "0" * 64
    elif change == "source_path": value["source_pins"]["../arbitrary.py"] = {"bytes": 1, "sha256": "0" * 64}
    elif change == "missing_source": value["source_pins"].pop(adapter.PROFILE_RELATIVE_PATH)
    elif change == "roles": value["physical_assets"].pop()
    elif change == "duplicate_role": value["physical_assets"][1]["role"] = value["physical_assets"][0]["role"]
    elif change == "relative_output": value["output_directory"] = "relative"
    elif change == "input_output_overlap": value["prepared_inputs"]["path"] = str(Path(value["output_directory"]) / "input.json")
    elif change == "duplicate_input": value["initial_checkpoint"]["path"] = value["prepared_inputs"]["path"]
    elif change == "runtime_sha": value["runtime_contract"] = {"path": str(tmp_path / "runtime.json"), "bytes": 758, "sha256": "0" * 64}
    with pytest.raises(adapter.F18CampaignError): adapter.F18JobSpec.from_dict(value)


def test_only_original_pinned_optional_runtime_contract_is_metadata_accepted(tmp_path):
    value = job_mapping(tmp_path)
    value["runtime_contract"] = {"path": str(tmp_path / "runtime.json"), "bytes": adapter.RUNTIME_CONTRACT_BYTES,
                                 "sha256": adapter.RUNTIME_CONTRACT_SHA256}
    assert adapter.F18JobSpec.from_dict(value).to_dict()["runtime_contract"] == value["runtime_contract"]


def test_prepared_serializer_is_canonical_closed15_continuity_only():
    value = prepared()
    raw = adapter.encode_prepared_inputs(value)
    assert json.loads(raw) == value
    assert raw == json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    value["expected_bindings"]["automatic_grant"] = True
    with pytest.raises(adapter.F18CampaignError): adapter.encode_prepared_inputs(value)


@pytest.mark.parametrize("kind", ["alias", "cycle", "tuple", "custom", "key", "deep", "integer", "nonfinite", "surrogate"])
def test_plain_json_limits_reject_before_encoder_hooks(kind, monkeypatch):
    class Custom(dict):
        def items(self): pytest.fail("custom type was inspected")
    if kind == "alias":
        child = {}; value = [child, child]
    elif kind == "cycle":
        value = []; value.append(value)
    elif kind == "tuple": value = (1,)
    elif kind == "custom": value = Custom()
    elif kind == "key": value = {1: "not a string key"}
    elif kind == "deep":
        value = 0
        for _ in range(66): value = [value]
    elif kind == "integer": value = 1 << 4096
    elif kind == "nonfinite": value = float("inf")
    else: value = "\ud800"
    monkeypatch.setattr(adapter.json.JSONEncoder, "iterencode", lambda *a, **k: pytest.fail("invalid value reached encoder"))
    with pytest.raises(adapter.F18CampaignError): adapter._canonical(value, maximum=4096)


def test_escaped_utf8_budget_is_enforced_before_whole_string_allocation(monkeypatch):
    value = {"s": "é\n\x00\"𝄞"}
    expected = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert adapter._canonical(value, maximum=len(expected)) == expected
    monkeypatch.setattr(adapter.json.JSONEncoder, "iterencode", lambda *a, **k: pytest.fail("overbudget string reached encoder"))
    with pytest.raises(adapter.F18CampaignError): adapter._canonical(value, maximum=len(expected) - 1)
    monkeypatch.setattr(adapter, "MAX_PREPARED_BYTES", 128)
    with pytest.raises(adapter.F18CampaignError): adapter.encode_prepared_inputs(prepared())


@pytest.mark.parametrize("kind", ["symlink", "parent_symlink", "hardlink", "fifo", "directory", "bytes", "digest"])
def test_bound_reader_refuses_alias_special_or_changed_fixture_inputs(tmp_path, kind):
    path = tmp_path / "input.json"
    path.write_bytes(b"{}")
    descriptor = {"path": str(path), "bytes": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}
    if kind == "symlink":
        target = tmp_path / "target.json"; path.rename(target); path.symlink_to(target)
    elif kind == "parent_symlink":
        real = tmp_path / "real"; real.mkdir(); path.rename(real / "input.json")
        alias = tmp_path / "alias"; alias.symlink_to(real, target_is_directory=True)
        descriptor["path"] = str(alias / "input.json")
    elif kind == "hardlink": os.link(path, tmp_path / "alias.json")
    elif kind == "fifo": path.unlink(); os.mkfifo(path)
    elif kind == "directory": path.unlink(); path.mkdir()
    elif kind == "bytes": descriptor["bytes"] = 1
    else: descriptor["sha256"] = "0" * 64
    with pytest.raises((adapter.F18CampaignError, OSError)):
        adapter._read_descriptor(descriptor, 64)


def test_exclusive_fixture_outputs_are_durable_and_never_overwritten(tmp_path):
    path = tmp_path / "report.json"
    descriptor = adapter._write_new(path, {"authored": True}, 128)
    original = path.read_bytes()
    assert descriptor["sha256"] == hashlib.sha256(original).hexdigest()
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError): adapter._write_new(path, {"authored": False}, 128)
    assert path.read_bytes() == original


@pytest.mark.parametrize("steps,completed", [(0, 0), (2, 2), (2, 0), (2, 1), (32, 32)])
def test_receipt_preserves_actual_complete_or_deadline_partial_progress_without_authority(tmp_path, steps, completed):
    spec = adapter.F18JobSpec.from_dict(job_mapping(tmp_path, steps=steps))
    value = receipt(spec, completed=completed)
    checked = adapter.validate_receipt(spec, value, job_file_sha256="3" * 64)
    assert checked["completed_steps"] == completed
    assert checked["status"] == ("completed" if completed == steps else "partial")
    assert all(checked[key] is False for key in adapter.FALSE_FIELDS)
    checked["final_progress"]["optimizer_steps"] = 99
    assert value["final_progress"]["optimizer_steps"] == completed


@pytest.mark.parametrize("change", ["unknown", "grant", "false_int", "job", "raw_job", "input", "profile",
    "arm", "false_completed", "counter", "cursor", "cumulative", "reason", "path", "elapsed", "runtime"])
def test_receipt_rejects_wrong_provenance_or_false_completion(tmp_path, change):
    spec = adapter.F18JobSpec.from_dict(job_mapping(tmp_path))
    value = receipt(spec, completed=1)
    if change == "unknown": value["success"] = True
    elif change == "grant": value["admitted"] = True
    elif change == "false_int": value["native_task_completed"] = 0
    elif change == "job": value["job_spec_sha256"] = "0" * 64
    elif change == "raw_job": value["job_file_sha256"] = "0" * 64
    elif change == "input": value["prepared_inputs_sha256"] = "0" * 64
    elif change == "profile": value["profile_source_sha256"] = "0" * 64
    elif change == "arm": value["margin_weight"] = 0.0
    elif change == "false_completed": value.update(status="completed", all_requested_steps_completed=True)
    elif change == "counter": value["completed_steps"] = 2
    elif change == "cursor": value["final_progress"]["row_cursor"] = 99
    elif change == "cumulative": value["final_progress"] = progress(33)
    elif change == "reason": value["reason"] = "step_limit"
    elif change == "path": value["checkpoint"]["path"] = str(tmp_path / "foreign.json")
    elif change == "elapsed": value["elapsed_seconds"] = float("nan")
    else: value["runtime_contract_sha256"] = "0" * 64
    with pytest.raises(adapter.F18CampaignError):
        adapter.validate_receipt(spec, value, job_file_sha256="3" * 64)


def test_selected_protocol_maps_preserve_six_physical_roles_and_distinct_canonical_mask(tmp_path):
    assets = [{"role": role, "path": str(tmp_path / role), **dict(adapter.SELECTED_PHYSICAL_INPUTS[role])}
              for role in adapter.ASSET_ROLES]
    result = adapter.validate_selected_input_bindings(dict(adapter.SELECTED_INPUT_BINDINGS), assets)
    assert result["selected_protocol_matches"] is True
    assert result["issuer_authenticated"] is result["runtime_grant"] is False
    assert all(result[key] is False for key in adapter.FALSE_FIELDS)
    assert adapter.SELECTED_INPUT_BINDINGS["training_mask_certificate_sha256"] != assets[-1]["sha256"]


@pytest.mark.parametrize("change", ["wrong_role", "swapped_role_hashes", "wrong_expected", "raw_mask_as_canonical", "fabricated_map"])
def test_selected_protocol_rejects_unrelated_inputs_or_candidate_fabricated_links(tmp_path, change):
    assets = [{"role": role, "path": str(tmp_path / role), **dict(adapter.SELECTED_PHYSICAL_INPUTS[role])}
              for role in adapter.ASSET_ROLES]
    bindings = dict(adapter.SELECTED_INPUT_BINDINGS)
    if change == "wrong_role": assets[1]["role"] = assets[0]["role"]
    elif change == "swapped_role_hashes":
        assets[0]["sha256"], assets[1]["sha256"] = assets[1]["sha256"], assets[0]["sha256"]
    elif change == "wrong_expected": bindings["teacher_capture_sha256"] = "0" * 64
    elif change == "raw_mask_as_canonical": bindings["training_mask_certificate_sha256"] = assets[-1]["sha256"]
    else:
        bindings["donor_checkpoint_sha256"] = "0" * 64
        assets[0]["sha256"] = "0" * 64
    with pytest.raises(adapter.F18CampaignError): adapter.validate_selected_input_bindings(bindings, assets)


def test_streaming_parent_input_guard_is_integrity_only_and_imports_no_profile(tmp_path, monkeypatch):
    document = job_mapping(tmp_path)
    for key in ("prepared_inputs", "initial_checkpoint"):
        path = Path(document[key]["path"]); path.write_bytes(b"{}")
        document[key].update(bytes=2, sha256=hashlib.sha256(b"{}").hexdigest())
    for asset in document["physical_assets"]:
        Path(asset["path"]).write_bytes(b"{}")
        asset.update(bytes=2, sha256=hashlib.sha256(b"{}").hexdigest())
    for relative, pin in document["source_pins"].items():
        raw = (adapter._ROOT / relative).read_bytes()
        pin.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    spec = adapter.F18JobSpec.from_dict(document)
    monkeypatch.setattr(adapter.importlib, "import_module", lambda *a, **k: pytest.fail("byte guard imported model/profile"))
    checked = adapter.validate_job_inputs(spec)
    assert checked["input_bytes_verified"] is True and checked["prepared_inputs_integrity_only"] is True
    assert checked["issuer_authenticated"] is checked["runtime_grant"] is False
    assert all(checked[key] is False for key in adapter.FALSE_FIELDS)
    Path(document["physical_assets"][0]["path"]).write_bytes(b"[]")
    with pytest.raises(adapter.F18CampaignError): adapter.validate_job_inputs(spec)
