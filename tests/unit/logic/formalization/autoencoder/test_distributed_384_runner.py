"""Real local journals, worker threads, numerical merging, and CLI replay.

Authored vectors exercise the orchestration contract, not embedding quality or
public transport. The independent exchange suite checks the Hub protocol.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import numpy as np
import pytest

pytest.importorskip("duckdb")
from .test_structured_source_384 import parent, rows
from .test_distributed_384_numerics import grouped
from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as decoder
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import runner
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import contracts as c

REPO = Path(__file__).resolve().parents[5]
CLI = REPO / "scripts/ops/autoencoder/run_distributed_384.py"
SOURCE = dict(schema="ir384-corpus-source/v1", description="Authored unit controls and synthetic vectors",
              redistribution_allowed=False)


@pytest.fixture(scope="module")
def checkpoints(parent):
    return {domain: decoder.train(domain, rows(domain, "train"), rows(domain, "validation"),
        parent_projection=parent)["checkpoint"] for domain in decoder.DOMAINS}


def inputs(tmp_path, checkpoints, domain="intent_ir"):
    root = tmp_path / "input"
    base = c.write_json(root / "base.json", checkpoints[domain])
    train = c.write_json(root / "training.json", {"rows": grouped(domain, "train")})
    validation = c.write_json(root / "validation.json", grouped(domain, "validation"))
    source = c.write_json(root / "source.json", SOURCE)
    return dict(domain=domain, base=base, training=train, validation=validation, source=source)


def prepare(case, output):
    return runner.prepare_round(case["domain"], case["training"], case["validation"], output,
        source_descriptor=SOURCE, base_path=case["base"], shard_size=2, machine_count=2)


def host(tmp_path, index):
    root = tmp_path / ("host-" + str(index))
    return root / "round", root / "journal.duckdb", root / "artifacts"


@pytest.mark.parametrize("domain", decoder.DOMAINS)
def test_two_isolated_hosts_actual_threads_merge_and_restart(domain, checkpoints, tmp_path, monkeypatch):
    case = inputs(tmp_path, checkpoints, domain)
    left, right = host(tmp_path, 0), host(tmp_path, 1)
    a, b = prepare(case, left[0]), prepare(case, right[0])
    assert a["plan_id"] == b["plan_id"] and a["shards"] == 3
    assert prepare(case, left[0]) == a
    assert (left[0] / "base.json").read_bytes() == case["base"].read_bytes()
    assert not left[1].exists() and not right[1].exists()

    # Two separate assigned shards must really execute on distinct local
    # threads. The barrier does not replace their numerical work.
    original_work = runner._work
    barrier = threading.Barrier(2)
    worker_threads = set()
    lock = threading.Lock()
    def synchronized_work(*args):
        with lock:
            worker_threads.add(threading.current_thread().name)
        barrier.wait(timeout=20)
        return original_work(*args)
    monkeypatch.setattr(runner, "_work", synchronized_work)
    first = runner.run_local(*left, machine_index=0, workers=2)
    monkeypatch.setattr(runner, "_work", original_work)
    assert first["computed_shards"] == first["completed_assigned_shards"] == 2
    assert len(worker_threads) == 2 and all(name.startswith("ir384-worker") for name in worker_threads)
    with pytest.raises(ValueError, match="missing or extra shard"):
        runner.merge_round(*left)
    second = runner.run_local(*right, machine_index=1, workers=2)
    assert second["computed_shards"] == second["completed_assigned_shards"] == 1
    assert left[1].is_file() and right[1].is_file() and left[1] != right[1]

    updates = sorted((right[0] / "updates").glob("*.json"))
    assert len(updates) == 1
    merged = runner.merge_round(*left, update_paths=updates + updates)
    checkpoint = c.read_json(merged["checkpoint_path"])
    np.testing.assert_allclose(checkpoint["head_state"]["weights"], checkpoints[domain]["head_state"]["weights"],
        atol=2e-9, rtol=2e-8)
    assert checkpoint["projection_state"] == checkpoints[domain]["projection_state"]
    assert merged["report"]["training_rows"] == 6 and merged["report"]["shards"] == 3
    assert merged["report"]["selected_validation"]["exact_targets"] == 6
    projection = merged["report"]["projection_evidence"]
    assert len(projection["rows"]) == 6 and projection["target_access"] is False
    assert not projection["all_required_families_supported"]
    assert not projection["lake_build_executed"]
    assert all(merged[key] is False for key in c.FALSE)
    assert merged["publication"]["uploaded"] is False

    replayed = runner.run_local(*left, machine_index=0, workers=2)
    assert replayed["computed_shards"] == 0 and replayed["completed_assigned_shards"] == 2
    assert runner.merge_round(*left, update_paths=updates) == merged
    anchor = runner.merge_round(*left, full_anchor=True)
    assert anchor["checkpoint_path"] == merged["checkpoint_path"]
    assert anchor["version_id"] == merged["version_id"]
    assert anchor["publication"]["prefix"].endswith("/anchors")


def test_interrupted_worker_restarts_with_fenced_leases(checkpoints, tmp_path, monkeypatch):
    case = inputs(tmp_path, checkpoints)
    local = host(tmp_path, 0)
    prepare(case, local[0])
    original = runner._work
    def fail(*args):
        raise RuntimeError("simulated worker interruption")
    monkeypatch.setattr(runner, "_work", fail)
    with pytest.raises(RuntimeError, match="worker interruption"):
        runner.run_local(*local, machine_index=0, workers=2)
    monkeypatch.setattr(runner, "_work", original)
    resumed = runner.run_local(*local, machine_index=0, workers=2)
    assert resumed["computed_shards"] == resumed["completed_assigned_shards"] == 2
    assert runner.run_local(*local, machine_index=0, workers=2)["computed_shards"] == 0


def test_projection_evidence_uses_real_predictions_without_gold_targets(checkpoints, tmp_path):
    case = inputs(tmp_path, checkpoints)
    local = host(tmp_path, 0)
    prepare(case, local[0])
    plan = c.read_json(local[0] / "plan.json")
    validation = c.read_json(case["validation"])
    changed = deepcopy(checkpoints["intent_ir"])
    changed["head_state"]["weights"] = np.zeros_like(changed["head_state"]["weights"]).tolist()
    changed["head_state"]["bias"] = np.zeros_like(changed["head_state"]["bias"]).tolist()
    changed["head_sha256"] = decoder.digest(changed["head_state"])
    predicted = decoder.Runtime(changed).infer([{k: row[k] for k in ("id", "source_text", "embedding")}
        for row in validation])["rows"]
    assert any(row["candidate_ir"] != gold["target"] for row, gold in zip(predicted, validation))
    report = runner._projection_evidence(plan, changed, validation)
    for row, candidate in zip(report["rows"], predicted):
        assert row["candidate_sha256"] == c.digest(candidate["candidate_ir"])
        assert row["report"]["candidate_sha256"] == c.digest(candidate["candidate_ir"])
        assert row["head_sha256"] == changed["head_sha256"]
    for row in validation:
        row["target"] = {"invalid_gold_target_must_not_be_accessed": True}
    assert runner._projection_evidence(plan, changed, validation) == report


def test_projection_evidence_rejects_missing_or_misbound_predictions(checkpoints, tmp_path, monkeypatch):
    case = inputs(tmp_path, checkpoints)
    local = host(tmp_path, 0)
    prepare(case, local[0])
    plan = c.read_json(local[0] / "plan.json")
    validation = c.read_json(case["validation"])
    runtime = decoder.Runtime(checkpoints["intent_ir"])
    rows_in = [{k: row[k] for k in ("id", "source_text", "embedding")} for row in validation]
    report = runtime.infer(rows_in)
    class Stub:
        def __init__(self, checkpoint):
            pass
        def infer(self, data):
            return deepcopy(report)
    monkeypatch.setattr(runner.decoder, "Runtime", Stub)
    report["rows"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="provenance differs"):
        runner._projection_evidence(plan, checkpoints["intent_ir"], validation)
    report["rows"].pop()
    with pytest.raises(ValueError, match="identities differ"):
        runner._projection_evidence(plan, checkpoints["intent_ir"], validation)


def test_public_input_upload_requires_explicit_redistribution_permission(checkpoints, tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import exchange
    case = inputs(tmp_path, checkpoints)
    local = host(tmp_path, 0)
    prepare(case, local[0])
    staged = runner.publish_inputs(local[0])
    assert staged["uploaded"] is False and staged["reference"] is None
    monkeypatch.setattr(exchange, "publish_bundle", lambda *a, **k: pytest.fail("publication reached"))
    with pytest.raises(ValueError, match="redistributable provenance"):
        runner.publish_inputs(local[0], upload=True)


@pytest.mark.parametrize("option", ["discover", "upload", "full_anchor"])
def test_merge_rejects_truthy_non_boolean_control_before_io(option):
    with pytest.raises(ValueError, match="boolean"):
        runner.merge_round("missing", "missing", "missing", **{option: "false"})


def test_base_write_rejects_aliased_parent_without_creating_directories(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        runner._write_bytes(link / "must-not-exist" / "base.json", b"{}")
    assert not (actual / "must-not-exist").exists()


def test_cli_prepare_two_machines_work_merge_and_replay(checkpoints, tmp_path):
    case = inputs(tmp_path, checkpoints)
    left, right = host(tmp_path, 0), host(tmp_path, 1)
    env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    def call(*args):
        process = subprocess.run([sys.executable, str(CLI), *map(str, args)], cwd=REPO, env=env,
            capture_output=True, text=True, timeout=60)
        assert process.returncode == 0, process.stderr
        return json.loads(process.stdout)
    for local in (left, right):
        prepared = call("prepare", "--domain", "intent_ir", "--training", case["training"],
            "--validation", case["validation"], "--source", case["source"], "--base", case["base"],
            "--output-dir", local[0], "--machine-count", 2, "--shard-size", 2)
        assert prepared["shards"] == 3
    for index, local in enumerate((left, right)):
        worked = call("work", "--round-dir", local[0], "--database", local[1], "--artifact-root", local[2],
            "--machine-index", index, "--workers", 2)
        assert worked["computed_shards"] == (2 if index == 0 else 1)
    update = next((right[0] / "updates").glob("*.json"))
    output = tmp_path / "cli-result.json"
    args = ("merge", "--round-dir", left[0], "--database", left[1], "--artifact-root", left[2],
            "--update-path", update, "--result", output)
    result = call(*args)
    assert result == c.read_json(output)
    assert result["report"]["training_rows"] == 6
    assert result["report"]["selected_validation"]["exact_targets"] == 6
    assert call(*args) == result
