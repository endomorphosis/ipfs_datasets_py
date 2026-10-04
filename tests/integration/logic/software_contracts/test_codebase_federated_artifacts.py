"""Verified inert client snapshots, real fits and durable private receipt replay."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import threading
import time

import duckdb
import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source
from ipfs_datasets_py.logic.software_contracts import codebase_federated_training as federation
from ipfs_datasets_py.logic.software_contracts import codebase_federated_artifacts as artifacts
from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_federated import ClientSpec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    root = tmp_path_factory.mktemp("codebase-artifact-worker")
    repository = root / "repository"
    repository.mkdir()
    for path, value in (("a.py", 1), ("b.py", 2), ("c.py", 3), ("tune.py", 7), ("canary.py", 9)):
        (repository / path).write_text(f"def step(n: int) -> int:\n    return n + {value}\n")
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    source_artifacts = ImmutableCAS(root / "source-artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=source_artifacts,
        catalog=CodebaseCatalog(store, source_artifacts))
    scheduler = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 16384, 16384),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005))
    head = index.prepare_current(repository, repository_id="test:artifact-worker", operation_id="capture",
        expected_head=None, scheduler=scheduler).head
    registry = AutoencoderRegistry(root / "models.duckdb", root / "model-artifacts")
    selections = [source.CodebaseTrainingSelection(path, "train" if path in {"a.py", "b.py", "c.py"} else path[:-3])
                  for path in ("a.py", "b.py", "c.py", "tune.py", "canary.py")]
    parent = source.train_current_codebase_features(index, repository, expected_head=head, registry=registry,
        selections=selections, operation_id="root", epochs=1, learning_rate=.002, scheduler=scheduler)
    limits = source.CodebaseFeatureTrainingLimits()
    base = federation._parent(index, registry, parent.to_dict()["version_id"], limits)
    transfer = ImmutableCAS(root / "transfer-artifacts")
    state = {"root": root, "repository": repository, "index": index, "registry": registry,
             "scheduler": scheduler, "head": head, "parent": parent, "base": base, "transfer": transfer,
             "limits": limits, "connection": connection,
             "clients": [federation.CodebaseFederatedClient("one", ("c.py",)),
                         federation.CodebaseFederatedClient("two", ("a.py", "b.py"))]}
    state["payload"] = prepared(state)
    state["worker"] = artifacts.CodebaseFederatedArtifactWorker(transfer, root / "receipts", scheduler=scheduler)
    state["result"] = state["worker"](task(state["payload"]))
    yield state
    assert scheduler.snapshot()["active_lease_count"] == scheduler.snapshot()["waiting_request_count"] == 0
    registry.close()
    connection.close()


def prepared(native, *, round_id="artifact-round", change=None, context_change=None):
    base, limits = native["base"], native["limits"]
    payloads, _ = federation._capture(native["index"], native["head"], base,
        native["clients"], federation._configuration(), limits)
    if change is not None:
        change(payloads[0])
    row = base["row"]
    adapter = federation._adapter().CodebaseFeatureCheckpoint.from_runtime(federation._runtime(base["saved"]),
        base_sha256=row["artifact"]["sha256"], base_version_id=row["version_id"])
    round_spec = adapter.build_round(round_id, "codebase-source:" + base["origin_version_id"],
        tuple(ClientSpec(item["client_id"], item["sample_count"], features.digest(item)) for item in payloads),
        max_local_steps=1)
    local = payloads[0]
    work = federation._sync().bind_codebase_federated_work(round_spec, base_version_id=row["version_id"],
        source_head=native["head"], client_id=local["client_id"], local_target_sha256=features.digest(local),
        sample_count=local["sample_count"], attempt=1, fence=1)
    context = {"tuning_targets": [item.to_dict() for item in base["tune"]],
               "canary_targets": [item.to_dict() for item in base["canary"]],
               "replay_targets": [item.to_dict() for item in base["replay"]]}
    if context_change is not None:
        context_change(context)
    return artifacts.prepare_codebase_artifact_task(work,
        base_bytes=native["registry"].artifact_path(row["artifact"]).read_bytes(),
        local_payload=local, context=context, artifacts=native["transfer"])


def task(payload, *, attempt=1):
    model = payload["declaration"]["payload"]["work_binding"]["model_id"]
    return {"task_type": artifacts.TASK_TYPE, "model_name": model, "payload": payload,
            "dispatch": {"queue_task_id": "private-task", "queue_attempt": attempt, "worker_id": f"worker-{attempt}",
                         "request_sha256": artifacts.codebase_artifact_request_sha256(payload, model),
                         "deadline_unix_s": time.time() + 120}}


def forbidden(*args, **kwargs):
    pytest.fail("read-only replay or refused task performed work")


def checkpoint(native):
    return json.loads(artifacts.read_codebase_artifact(native["transfer"], native["result"]["local_checkpoint"]))


def test_real_isolated_fit_returns_verified_float64_binary_delta_without_admission(native):
    result = native["result"]
    validated = artifacts.validate_codebase_artifact_result(native["payload"], result, native["transfer"])
    assert native["worker"].numerical_invocations == 1
    assert validated["training_report"]["attempted_epochs"] == 1
    assert validated["training_report"]["training_target_count"] == 1
    assert validated["training_report"]["base_state_sha256"] == features.digest(native["base"]["saved"]["state"])
    assert validated["local_state"]["parameters"] != native["base"]["saved"]["state"]["parameters"]
    assert validated["worker_receipt"]["workspace_cleaned"] is True
    assert all(flag is False for flag in result["authority"].values())
    assert set(result) == {"schema", "request_sha256", "work_sha256", "local_checkpoint", "update", "implementation", "authority"}
    assert native["scheduler"].snapshot()["active_lease_count"] == 0


def test_restart_receipt_replay_has_exact_result_and_no_fit_or_cas_publication(native, monkeypatch):
    restarted = artifacts.CodebaseFederatedArtifactWorker(native["transfer"], native["root"] / "receipts",
        scheduler=native["scheduler"])
    monkeypatch.setattr(source, "_worker", forbidden)
    monkeypatch.setattr(native["transfer"], "put_bytes", forbidden)
    monkeypatch.setattr(native["transfer"], "put", forbidden)
    assert restarted(task(native["payload"], attempt=2)) == native["result"]
    assert restarted.numerical_invocations == 0
    assert native["scheduler"].snapshot()["active_lease_count"] == 0


def test_stored_input_corruption_is_detected_during_cached_replay(native, monkeypatch):
    monkeypatch.setattr(source, "_worker", forbidden)
    reference = native["payload"]["declaration"]["payload"]["artifacts"]["base_checkpoint"]
    path = native["transfer"].path_for(reference["cidv1"], source=True)
    original = path.read_bytes()
    try:
        path.write_bytes(original[:-1] + b" ")
        with pytest.raises(ValueError):
            native["worker"](task(native["payload"], attempt=2))
    finally:
        path.write_bytes(original)


def test_corrupted_private_result_receipt_cannot_trigger_replacement_fit(native, monkeypatch):
    monkeypatch.setattr(source, "_worker", forbidden)
    path = native["worker"].receipt_root / (native["result"]["request_sha256"] + ".json")
    original = path.read_bytes()
    changed = copy.deepcopy(native["result"])
    changed["authority"]["proof_authority"] = True
    try:
        path.write_bytes(source._wire(changed))
        with pytest.raises(source.CodebaseFeatureTrainingError, match="authority"):
            native["worker"](task(native["payload"], attempt=2))
    finally:
        path.write_bytes(original)


def test_declared_fetch_bound_refuses_before_reading_artifact_bytes(native, monkeypatch):
    reference = native["result"]["local_checkpoint"]
    monkeypatch.setattr(native["transfer"], "get_bytes", forbidden)
    with pytest.raises(source.CodebaseFeatureTrainingError, match="byte bound"):
        artifacts.read_codebase_artifact(native["transfer"], reference, maximum=reference["bytes"] - 1)


@pytest.mark.parametrize("field", ["queue_task_id", "queue_attempt", "worker_id", "request_sha256", "deadline_unix_s"])
def test_missing_queue_dispatch_scope_refuses_even_cached_receipt(native, monkeypatch, field):
    monkeypatch.setattr(source, "_worker", forbidden)
    request = task(native["payload"])
    del request["dispatch"][field]
    with pytest.raises(source.CodebaseFeatureTrainingError, match="dispatch"):
        native["worker"](request)


@pytest.mark.parametrize("field,value", [("queue_attempt", True), ("worker_id", ""),
    ("queue_task_id", 3), ("request_sha256", "0" * 64), ("deadline_unix_s", 0), ("deadline_unix_s", float("inf"))])
def test_invalid_dispatch_tokens_refuse_before_fit(native, monkeypatch, field, value):
    monkeypatch.setattr(source, "_worker", forbidden)
    request = task(native["payload"])
    request["dispatch"][field] = value
    with pytest.raises(source.CodebaseFeatureTrainingError, match="dispatch"):
        native["worker"](request)


@pytest.mark.parametrize("edit", ["count", "epochs", "seed", "selection", "tune"])
def test_recommitted_malicious_local_inventories_reject_before_fit(native, monkeypatch, edit):
    monkeypatch.setattr(source, "_worker", forbidden)
    def change(value):
        if edit == "count":
            value["sample_count"] += 1
        elif edit == "epochs":
            value["configuration"]["epochs"] = 2
        elif edit == "seed":
            value["configuration"]["seed"] = -1
        elif edit == "selection":
            value["selections"][0]["path"] = "a.py"
        else:
            value["tuning_targets_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        prepared(native, round_id="malicious-" + edit, change=change)


def test_fixed_tune_context_cannot_be_replaced_with_native_canary(native, monkeypatch):
    monkeypatch.setattr(source, "_worker", forbidden)
    with pytest.raises(source.CodebaseFeatureTrainingError, match="tuning"):
        prepared(native, round_id="bad-context", context_change=lambda value: value.update(tuning_targets=value["canary_targets"]))


@pytest.mark.parametrize("edit", ["authority", "route", "producer", "extra", "bytes"])
def test_changed_artifact_task_scope_rejects_before_fit(native, monkeypatch, edit):
    monkeypatch.setattr(source, "_worker", forbidden)
    payload = copy.deepcopy(native["payload"])
    if edit == "authority":
        payload["declaration"]["authority"]["proof_authority"] = True
    elif edit == "route":
        payload["declaration"]["route"]["task_type"] = "arbitrary-code"
    elif edit == "producer":
        payload["implementation"]["artifact_worker_sha256"] = "0" * 64
    elif edit == "extra":
        payload["executable"] = "arbitrary-code"
    else:
        payload["context_artifact"]["bytes"] += 1
    with pytest.raises(ValueError):
        native["worker"](task(payload))


@pytest.mark.parametrize("edit", ["authority", "request", "work", "producer", "extra", "binary"])
def test_result_reference_scope_and_binary_tamper_reject(native, edit):
    result = copy.deepcopy(native["result"])
    if edit == "authority":
        result["authority"]["proof_authority"] = True
    elif edit == "request":
        result["request_sha256"] = "0" * 64
    elif edit == "work":
        result["work_sha256"] = "0" * 64
    elif edit == "producer":
        result["implementation"]["artifact_worker_sha256"] = "0" * 64
    elif edit == "extra":
        result["admitted"] = True
    else:
        raw = bytearray(artifacts.read_codebase_artifact(native["transfer"], result["update"]))
        raw[-1] ^= 1
        result["update"] = artifacts._put(native["transfer"], bytes(raw))
    with pytest.raises(ValueError):
        artifacts.validate_codebase_artifact_result(native["payload"], result, native["transfer"])


@pytest.mark.parametrize("edit", ["base", "count", "steps", "parameters", "receipt"])
def test_recommitted_local_checkpoint_does_not_bypass_semantic_replay(native, edit):
    changed = checkpoint(native)
    if edit == "base":
        changed["report"]["base_state_sha256"] = "0" * 64
    elif edit == "count":
        changed["report"]["training_target_count"] += 1
    elif edit == "steps":
        changed["report"]["attempted_epochs"] = 0
    elif edit == "parameters":
        changed["state"]["parameters"][1][0] += .01
    else:
        changed["worker_receipt"]["workspace_cleaned"] = False
    result = copy.deepcopy(native["result"])
    result["local_checkpoint"] = artifacts._put(native["transfer"], source._wire(changed))
    with pytest.raises(ValueError):
        artifacts.validate_codebase_artifact_result(native["payload"], result, native["transfer"])


def test_cached_receipt_obeys_inherited_cancel_and_deadline(native, monkeypatch):
    monkeypatch.setattr(source, "_worker", forbidden)
    worker = native["worker"]
    cancelled = threading.Event()
    cancelled.set()
    with worker.execution_context(parent_lease=None, cancel_event=cancelled, remaining=lambda: 100,
            memory_mb=1024, limits=native["limits"]):
        with pytest.raises(source.CodebaseFeatureTrainingError, match="cancelled"):
            worker(task(native["payload"]))
    with worker.execution_context(parent_lease=None, cancel_event=threading.Event(), remaining=lambda: (_ for _ in ()).throw(schedulers.LeaseTimeoutError("expired owner")),
            memory_mb=1024, limits=native["limits"]):
        with pytest.raises(schedulers.LeaseTimeoutError, match="expired owner"):
            worker(task(native["payload"]))


def test_actual_cancellation_removes_process_lease_and_publishes_no_receipt(native, monkeypatch):
    payload = prepared(native, round_id="actual-cancel")
    worker = artifacts.CodebaseFederatedArtifactWorker(native["transfer"], native["root"] / "cancel-receipts",
        scheduler=native["scheduler"])
    event, original = threading.Event(), source._worker
    def cancelled(*args, **kwargs):
        timer = threading.Timer(.05, event.set)
        timer.start()
        try:
            return original(*args, **kwargs)
        finally:
            timer.cancel()
    monkeypatch.setattr(source, "_worker", cancelled)
    with acquire_codebase_resources(scheduler=native["scheduler"], memory_mb=1024) as parent:
        with worker.execution_context(parent_lease=parent, cancel_event=event, remaining=lambda: 100,
                memory_mb=1024, limits=native["limits"]):
            with pytest.raises(schedulers.LeaseCancelledError):
                worker(task(payload))
    assert worker.numerical_invocations == 1
    assert not list(worker.receipt_root.glob("*.json"))
    assert native["scheduler"].snapshot()["active_lease_count"] == 0


def test_concurrent_duplicate_exact_request_fits_only_once(native, monkeypatch):
    payload = prepared(native, round_id="concurrent-duplicate")
    worker = artifacts.CodebaseFederatedArtifactWorker(native["transfer"], native["root"] / "concurrent-receipts",
        scheduler=native["scheduler"])
    entered, released, original = threading.Event(), threading.Event(), source._worker
    def waiting(*args, **kwargs):
        entered.set()
        assert released.wait(timeout=20)
        return original(*args, **kwargs)
    monkeypatch.setattr(source, "_worker", waiting)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker, task(payload))
        assert entered.wait(timeout=20)
        try:
            with pytest.raises(source.CodebaseFeatureTrainingError, match="already executing"):
                worker(task(payload, attempt=2))
        finally:
            released.set()
        result = first.result(timeout=60)
    assert worker.numerical_invocations == 1
    monkeypatch.setattr(source, "_worker", forbidden)
    assert worker(task(payload, attempt=3)) == result
    assert native["scheduler"].snapshot()["active_lease_count"] == 0
