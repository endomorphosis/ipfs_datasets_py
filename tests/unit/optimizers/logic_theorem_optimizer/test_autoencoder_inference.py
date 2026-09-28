"""Immutable inference and resume tests; no model training, Lake or network."""
from concurrent.futures import Future
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_inference as inference
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as qualification
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    AdaptiveModalAutoencoder, ModalAutoencoderTrainingState,
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sample(section):
    return asdict(SampleRecord.from_dict({"title": "inference-fixture", "section": str(section),
        "text": f"The officer shall retain record {section}."}))


class ImmediateExecutor:
    sizes = []

    def __init__(self, max_workers):
        self.sizes.append(max_workers)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def submit(self, function, *args):
        future = Future()
        try:
            future.set_result(function(*args))
        except BaseException as exc:
            future.set_exception(exc)
        return future


@pytest.fixture
def context(tmp_path, monkeypatch):
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text(ModalAutoencoderTrainingState().to_json() + "\n")
    inputs, validation = tmp_path / "samples.jsonl", tmp_path / "validation.jsonl"
    inputs.write_text("".join(json.dumps(_sample(index)) + "\n" for index in range(3)))
    validation.write_text(json.dumps(_sample("validation")) + "\n")
    def records(path):
        rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
        return [{"record_id": inference.inc._sha(row), "sample": row} for row in rows]
    cli = SimpleNamespace(_pin=lambda: {"test_producer": "fixed"},
                          orchestration_hashes=lambda: {"test_orchestration": "fixed"},
                          local_records=records, _sha=_sha,
                          _write=lambda path, value: inference.inc._write(Path(path), value),
                          PINNED=tmp_path / "protected.json", PINNED_SHA="0" * 64)
    config = {"execution_mode": "inference", "input_jsonl": str(inputs),
              "validation_jsonl": str(validation), "checkpoint": str(checkpoint),
              "state_directory": str(tmp_path / "state"), "cycle_receipt": str(tmp_path / "cycle.json"),
              "lake_timeout_seconds": 1, "workers": 4, "max_parallel_workers": 4,
              "max_batches": 8, "memory_mb": 8192}
    def structural_failure(*args, **kwargs):
        return {"compiler": {"compiler_status": "test_fixture_abstain"},
                **{name: {"passed": False, "rows": [], "reason": "isolated_test_structure", "admitted": False}
                   for name in ("semantic_gate", "family_syntax_gate", "lake_gate")}}
    monkeypatch.setattr(qualification, "_structural_gates", structural_failure)
    ImmediateExecutor.sizes = []
    return config, cli


def _run(context, **kwargs):
    config, cli = context
    capacity = lambda **limits: {"workers": min(limits["max_workers"], limits["pending_count"])}
    return inference.run_inference_cycle(config, cli, executor_factory=ImmediateExecutor,
                                         capacity_callback=kwargs.pop("capacity_callback", capacity), **kwargs)


def _first_pass(context):
    config, cli = context
    checkpoint = Path(config["checkpoint"])
    candidate = {"path": str(checkpoint), "sha256": _sha(checkpoint), "bytes": checkpoint.stat().st_size}
    sample = cli.local_records(config["input_jsonl"])[0]["sample"]
    heldout = [row["sample"] for row in cli.local_records(config["validation_jsonl"])]
    return (candidate, "inference-" + candidate["sha256"], sample, heldout,
            Path(config["state_directory"]) / "direct-pass", 1)


def test_inference_calls_neither_training_registry_nor_hub_and_keeps_weights(context, monkeypatch):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.huggingface import autoencoder_incremental as publication
    from ipfs_datasets_py.huggingface import autoencoder_span_attempts as attempts
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_qualified_training as training
    def forbidden(*args, **kwargs):
        pytest.fail("inference entered a mutating training/control/publication boundary")
    monkeypatch.setattr(AdaptiveModalAutoencoder, "train_generalizable_projection", forbidden)
    monkeypatch.setattr(AutoencoderRegistry, "__init__", forbidden)
    monkeypatch.setattr(worker, "execute_training_job", forbidden)
    monkeypatch.setattr(training, "run_qualified_incremental_training", forbidden)
    monkeypatch.setattr(publication, "publish_sparse_update", forbidden)
    monkeypatch.setattr(publication, "enqueue_sparse_update", forbidden)
    monkeypatch.setattr(attempts, "publish_span_attempt", forbidden)
    before = Path(context[0]["checkpoint"]).read_bytes()
    result = _run(context)
    assert Path(context[0]["checkpoint"]).read_bytes() == before
    assert result["execution_path"] == "inference" and result["training_executed"] is False
    assert result["training"] is None and result["weight_publications"] == []
    assert result["admitted"] is result["formalized"] is result["promotion_performed"] is False
    assert result["dispatched_pass_count"] == 3 and result["pending_pass_count"] == 0
    assert all(row["qualified"] is False for row in result["inference"])
    assert not list(Path(context[0]["state_directory"]).rglob("*.duckdb"))


@pytest.mark.parametrize("update", [
    {"execution_mode": "training"}, {"execution_mode": "automatic"},
    {"input_jsonl": None}, {"validation_jsonl": None},
    {"repository_id": "test/data"}, {"publish_repository": "test/data"},
    {"arrow_feature_weights": "weights.arrow"}, {"shared_targets": "targets.arrow"},
])
def test_invalid_route_or_training_inputs_rejected_before_loading(context, update):
    config, cli = context
    config.update(update)
    cli._pin = lambda: pytest.fail("invalid route loaded producers")
    with pytest.raises(ValueError):
        _run(context)
    assert not Path(config["state_directory"]).exists()


def test_completed_pass_reuse_verifies_evidence_without_requalifying(context, monkeypatch):
    args = _first_pass(context)
    first = inference._pass(*args)
    receipt_before = Path(first["receipt"]).read_bytes()
    monkeypatch.setattr(qualification, "qualify_candidate", lambda *a, **k: pytest.fail("completed pass reran"))
    assert inference._pass(*args) == first
    assert Path(first["receipt"]).read_bytes() == receipt_before


def test_modified_receipt_fails_unchanged_seal(context):
    args = _first_pass(context)
    first = inference._pass(*args)
    path = Path(first["receipt"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="retained inference evidence changed"):
        inference._pass(*args)


@pytest.mark.parametrize("corruption", ["route", "gate", "row_source", "metrics"])
def test_resealed_tampering_cannot_cross_route_or_qualification_gates(context, corruption):
    args = _first_pass(context)
    first = inference._pass(*args)
    path = Path(first["receipt"])
    receipt = json.loads(path.read_bytes())
    if corruption == "route":
        receipt["training_executed"] = True
    elif corruption == "gate":
        receipt["execution_gate_applied"] = False
    elif corruption == "row_source":
        row = receipt["rows"][0]
        row["source"]["text"] = "Another source sentence."
        row["source_sha256"] = hashlib.sha256(row["source"]["text"].encode()).hexdigest()
    else:
        receipt["qualified"] = True
        for row in receipt["rows"]:
            row["qualified"] = True
            for gate in ("metric_gate", "semantic_gate", "family_syntax_gate", "lake_gate"):
                row[gate]["passed"] = True
            row["metric_gate"].update(embedding_cosine_similarity=.1, reconstruction_loss=.9)
        for name, gate in receipt["gate_results"].items():
            gate["passed"] = True
            receipt[name] = gate
    raw = json.dumps(receipt).encode()
    path.write_bytes(raw)
    inference.inc._write(path.with_name("inference-seal.json"),
                         {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    with pytest.raises(ValueError):
        inference._pass(*args)


def test_unfinished_pass_keeps_partial_artifacts_and_requires_recovery(context):
    args = _first_pass(context)
    directory = args[4]
    directory.mkdir(parents=True)
    marker = directory / "interrupted.txt"
    marker.write_text("not qualification evidence")
    with pytest.raises(ValueError, match="explicit recovery"):
        inference._pass(*args)
    assert marker.read_text() == "not qualification evidence"
    assert not (directory / "inference-seal.json").exists()


@pytest.mark.parametrize("change", ["checkpoint", "sources", "validation", "timeout"])
def test_resume_rejects_changed_semantic_binding(context, change):
    _run(context)
    config, cli = context
    if change == "checkpoint":
        with Path(config["checkpoint"]).open("a") as stream:
            stream.write(" ")
    elif change == "sources":
        cli.orchestration_hashes = lambda: {"test_orchestration": "changed"}
    elif change == "validation":
        Path(config["validation_jsonl"]).write_text(json.dumps(_sample("other-validation")) + "\n")
    else:
        config["lake_timeout_seconds"] = 2
    with pytest.raises(ValueError, match="new state required"):
        _run(context)


def test_zero_capacity_defers_then_resume_changes_hardware_without_changing_pass_identity(context, monkeypatch):
    config, cli = context
    zero = _run(context, capacity_callback=lambda **limits: {"workers": 0})
    assert zero["dispatched_pass_count"] == 0 and zero["pending_pass_count"] == 3
    assert not (Path(config["state_directory"]) / "inference/passes").exists()
    binding_path = Path(config["state_directory"]) / "inference/binding.json"
    binding = binding_path.read_bytes()
    config.update(max_batches=1, workers=1, max_parallel_workers=1)
    first = _run(context)
    assert first["dispatched_pass_count"] == 1 and first["pending_pass_count"] == 2
    saved = first["inference"][0]
    config.update(max_batches=8, workers=32, max_parallel_workers=3, memory_mb=16384)
    second = _run(context)
    assert second["dispatched_pass_count"] == 2 and second["pending_pass_count"] == 0
    assert saved in second["inference"] and binding_path.read_bytes() == binding
    assert ImmediateExecutor.sizes == [1, 2]
    monkeypatch.setattr(qualification, "qualify_candidate", lambda *a, **k: pytest.fail("resume requalified"))
    config.update(workers=2, max_parallel_workers=2)
    last = _run(context)
    assert last["dispatched_pass_count"] == 0 and last["pending_pass_count"] == 0
    assert sorted(last["inference"], key=lambda r: r["receipt"]) == sorted(second["inference"], key=lambda r: r["receipt"])


def test_capacity_is_rechecked_between_waves_without_changing_samples(context):
    calls = []
    def capacity(**limits):
        calls.append(limits)
        return {"workers": 1 if len(calls) == 1 else limits["pending_count"]}
    result = _run(context, capacity_callback=capacity)
    assert [call["pending_count"] for call in calls] == [3, 2]
    assert ImmediateExecutor.sizes == [1, 2]
    assert result["dispatched_pass_count"] == 3 and len(result["inference"]) == 3


def test_machine_shards_cover_inputs_once_independent_of_worker_capacity(context):
    config, cli = context
    observed = []
    def check(candidate, version, sample, heldout, directory, timeout):
        observed.append((config["shard_index"], sample["section"]))
        return {"qualified": False, "admitted": False}
    config.update(shard_count=2, workers=1, max_parallel_workers=1)
    for shard in range(2):
        config["shard_index"] = shard
        _run(context, pass_function=check)
        config.update(workers=8, max_parallel_workers=8)
    assert sorted(section for _, section in observed) == ["0", "1", "2"]
    for shard, section in observed:
        assert int(inference.inc._sha(_sample(section)), 16) % 2 == shard


def test_cli_dispatches_inference_before_training_registry_and_rejects_unknown_mode(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[4] / "scripts/ops/legal_ir/run_incremental_autoencoders.py"
    name = "_test_inference_route_cli"
    spec = importlib.util.spec_from_file_location(name, path)
    cli = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, cli)
    spec.loader.exec_module(cli)
    marker = object()
    calls = []
    def route(config, namespace):
        calls.append((config, namespace))
        return marker
    monkeypatch.setattr(inference, "run_inference_cycle", route)
    monkeypatch.setattr(cli, "_pin", lambda **kwargs: pytest.fail("training producer path entered"))
    config = {"execution_mode": "inference", "state_directory": str(tmp_path / "state")}
    assert cli.run_cycle(config) is marker
    assert calls[0][0] is config
    with pytest.raises(ValueError):
        cli.run_cycle({"execution_mode": "unknown"})
