"""Live source-owned retries recover the exact requested native round."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import duckdb
import pytest

from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
from ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch import CodebaseQueueDispatcher, TASK_TYPE
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source
from ipfs_datasets_py.logic.software_contracts import codebase_federated_training as federation
from ipfs_datasets_py.logic.software_contracts import codebase_dispatched_federation as owner
from ipfs_datasets_py.logic.software_contracts import codebase_indexed_dispatch_recovery as indexed
from ipfs_datasets_py.logic.software_contracts import codebase_indexed_dispatched_training as entry
from ipfs_datasets_py.logic.software_contracts.codebase_federated_artifacts import CodebaseFederatedArtifactWorker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_sync import (
    GradientBackendUnavailable,
    TrainingMode,
)


def _train(state, **changes):
    arguments = {name: state[name] for name in ("index", "repository", "registry", "scheduler", "expected_head",
                                               "clients", "dispatcher", "worker", "artifacts")}
    arguments.update(base_version_id=state["parent"].to_dict()["version_id"],
                     operation_id="retained", epochs=1, learning_rate=.002)
    arguments.update(changes)
    return entry.train_current_indexed_dispatched_codebase_round(**arguments)


@pytest.fixture(scope="module")
def retained(tmp_path_factory):
    root = tmp_path_factory.mktemp("codebase-indexed-training-native")
    repository = root / "repository"
    repository.mkdir()
    for path, value in (("a.py", 1), ("b.py", 2), ("c.py", 3), ("tune.py", 7), ("canary.py", 9)):
        (repository / path).write_text(f"def step(n: int) -> int:\n    return n + {value}\n")
    # A retained basetemp may be inside the datasets checkout. Give this small
    # repository its own Git root so native scanning stays inside the fixture.
    subprocess.run(["git", "init", "-q", str(repository)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repository), "add", "a.py", "b.py", "c.py", "tune.py", "canary.py"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repository), "-c", "user.name=CodebaseIR fixture",
                    "-c", "user.email=codebase-fixture@example.invalid", "commit", "-qm", "native indexed training fixture"],
                   check=True, capture_output=True)
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    metadata = ImmutableCAS(root / "artifacts")
    artifacts = ImmutableCAS(root / "transfer-artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=metadata,
        catalog=CodebaseCatalog(store, metadata))
    scheduler = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 16384, 16384),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005))
    head = index.prepare_current(repository, repository_id="test:codebase-indexed-training",
        operation_id="capture", expected_head=None, scheduler=scheduler).head
    registry = AutoencoderRegistry(root / "models.duckdb", root / "model-artifacts")
    selections = [source.CodebaseTrainingSelection(path, "train" if path in {"a.py", "b.py", "c.py"} else path[:-3])
                  for path in ("a.py", "b.py", "c.py", "tune.py", "canary.py")]
    parent = source.train_current_codebase_features(index, repository, expected_head=head,
        registry=registry, selections=selections, operation_id="root", epochs=1,
        learning_rate=.002, scheduler=scheduler)
    queue = TaskQueue(str(root / "queue.duckdb"))
    worker = CodebaseFederatedArtifactWorker(artifacts, root / "worker-receipts", scheduler=scheduler)
    state = {"root": root, "repository": repository, "index": index, "registry": registry,
        "scheduler": scheduler, "expected_head": head, "parent": parent, "queue": queue,
        "connection": connection,
        "worker": worker, "dispatcher": CodebaseQueueDispatcher(queue, worker), "artifacts": artifacts,
        "clients": [federation.CodebaseFederatedClient("one", ("c.py",)),
                    federation.CodebaseFederatedClient("two", ("a.py", "b.py"))]}
    state["record"] = _train(state)
    # Native SQL bulk history surrounds the real retained two-client cohort.
    # None of these unrelated tasks invokes an optimizer or worker handler.
    with queue._conn_lock:
        native = queue._get_conn()
        for side, offset in (("older", 0.0), ("newer", 1e12)):
            native.execute("""INSERT INTO tasks
                (task_id,task_type,model_name,payload_json,status,assigned_worker,
                 created_at,updated_at,result_json,error,priority,attempt,max_attempts,
                 next_attempt_at,lease_until,heartbeat_at,idempotency_key)
                SELECT ? || CAST(range AS VARCHAR), ?, 'unrelated-model', '{}',
                    'completed', 'unrelated-worker', ? + range, ? + range, '{}', NULL,
                    5, 1, 3, 0, NULL, NULL, NULL FROM range(5001)""",
                ["unrelated:" + side + ":", TASK_TYPE, offset, offset])
    yield state
    assert scheduler.snapshot()["active_lease_count"] == scheduler.snapshot()["waiting_request_count"] == 0
    (root / "execution.json").write_text(json.dumps({"schema": "indexed-training-native-qualification@1",
        "head": head.to_dict(), "parent_version_id": parent.to_dict()["version_id"],
        "completed_record": state["record"].to_dict(), "unrelated_queue_tasks": 10002,
        "initial_private_numerical_invocations": 2, "scheduler": scheduler.snapshot()}, sort_keys=True, indent=2))
    state["queue"].close()
    state["registry"].close()
    state["connection"].close()


def _artifact_files(state):
    roots = ("artifacts", "transfer-artifacts", "model-artifacts", "worker-receipts")
    return {name: {str(path.relative_to(state["root"] / name)): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (state["root"] / name).rglob("*") if path.is_file()} for name in roots}


def _forbid_execution(state, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("completed training retry attempted a fit, dispatch, claim or inventory scan")
    for name in ("list", "submit", "submit_once", "claim", "complete"):
        monkeypatch.setattr(state["queue"], name, forbidden)
    for name in ("claim_run", "complete_run", "fail_run", "stage_artifact"):
        monkeypatch.setattr(state["registry"], name, forbidden)
    monkeypatch.setattr(state["dispatcher"], "dispatch", forbidden)
    monkeypatch.setattr(source, "_worker", forbidden)
    monkeypatch.setattr(state["artifacts"], "put", forbidden)
    monkeypatch.setattr(state["artifacts"], "put_bytes", forbidden)


def test_fresh_native_training_retains_old_model_and_sidecar_formats(retained):
    record = retained["record"]
    assert record.observed_live is True
    assert retained["worker"].numerical_invocations == 2
    assert record.to_dict()["schema"] == owner.SCHEMA
    assert all(value is False for value in record.to_dict()["authority"].values())
    model = federation.load_codebase_federated_training(retained["index"], retained["registry"],
                                                       record.to_dict()["version_id"])
    assert model.artifact_cid == record.to_dict()["model_record_cid"]


def test_completed_retry_uses_exact_index_past_ten_thousand_noise_tasks(retained, monkeypatch):
    assert retained["queue"].count(task_types=[TASK_TYPE]) == 10004
    before = _artifact_files(retained)
    native_before = retained["registry"].get_run(retained["record"].to_dict()["native_run_id"])
    _forbid_execution(retained, monkeypatch)
    retried = _train(retained)
    assert retried.to_dict() == retained["record"].to_dict()
    assert retried.artifact_cid == retained["record"].artifact_cid
    assert retried.observed_live is True
    assert retained["worker"].numerical_invocations == 2
    assert retained["registry"].get_run(native_before["run_id"]) == native_before
    assert _artifact_files(retained) == before


def test_completed_retry_can_infer_private_transfer_store_from_dispatcher(retained, monkeypatch):
    _forbid_execution(retained, monkeypatch)
    assert _train(retained, worker=None, artifacts=None).artifact_cid == retained["record"].artifact_cid


def test_opt_out_retains_bounded_legacy_discovery(retained, monkeypatch):
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("legacy retry fitted"))
    monkeypatch.setattr(retained["dispatcher"], "dispatch", lambda *a, **k: pytest.fail("legacy retry dispatched"))
    with pytest.raises(source.CodebaseFeatureTrainingError, match="discovery bound"):
        _train(retained, use_request_index=False)


@pytest.mark.parametrize("policy", [True, False])
@pytest.mark.parametrize("field,value", [("max_features", 1), ("max_training_history", 5)])
def test_narrow_model_bounds_reject_before_run_creation_for_both_policies(retained, monkeypatch, policy, field, value):
    _forbid_execution(retained, monkeypatch)
    def forbidden(*args, **kwargs):
        pytest.fail("out-of-bound candidate created a native run or delegated execution")
    monkeypatch.setattr(retained["registry"], "create_run", forbidden)
    monkeypatch.setattr(owner, "train_current_dispatched_codebase_round", forbidden)
    operation_id = "narrow:" + field + ":" + str(policy)
    queue_count = retained["queue"].count()
    limits = replace(source.CodebaseFeatureTrainingLimits(), **{field: value})
    with pytest.raises(source.CodebaseFeatureTrainingError, match="feature|history"):
        _train(retained, operation_id=operation_id, use_request_index=policy, limits=limits)
    with pytest.raises(RegistryError, match="unknown run"):
        retained["registry"].get_run("codebase-dispatched-fed:" + operation_id)
    assert retained["queue"].count() == queue_count
    assert retained["worker"].numerical_invocations == 2
    assert retained["scheduler"].snapshot()["active_lease_count"] == 0


@pytest.mark.parametrize("policy", [0, 1, None, "true", [], {}])
def test_index_policy_requires_exact_boolean_before_native_mutations(retained, monkeypatch, policy):
    monkeypatch.setattr(retained["registry"], "create_run", lambda *a, **k: pytest.fail("invalid policy created a run"))
    with pytest.raises(source.CodebaseFeatureTrainingError, match="policy"):
        _train(retained, use_request_index=policy)


@pytest.mark.parametrize("changed", ["seed", "epochs", "client_identity", "partition", "base"])
def test_completed_retry_rejects_a_different_requested_round(retained, monkeypatch, changed):
    _forbid_execution(retained, monkeypatch)
    variations = {"seed": {"seed": 2}, "epochs": {"epochs": 2},
        "client_identity": {"clients": [federation.CodebaseFederatedClient("first", ("c.py",)),
                                           federation.CodebaseFederatedClient("two", ("a.py", "b.py"))]},
        "partition": {"clients": [federation.CodebaseFederatedClient("one", ("a.py",)),
                                      federation.CodebaseFederatedClient("two", ("b.py", "c.py"))]},
        "base": {"base_version_id": retained["record"].to_dict()["version_id"]}}
    with pytest.raises(RegistryError, match="operation|payload"):
        _train(retained, **variations[changed])


def test_completed_retry_requires_parent_learning_rate(retained, monkeypatch):
    _forbid_execution(retained, monkeypatch)
    with pytest.raises(source.CodebaseFeatureTrainingError, match="learning rate"):
        _train(retained, learning_rate=.001)


def test_equivalent_client_order_retries_the_same_round(retained, monkeypatch):
    _forbid_execution(retained, monkeypatch)
    assert _train(retained, clients=list(reversed(retained["clients"]))).artifact_cid == retained["record"].artifact_cid


def test_completed_retry_rejects_a_different_source_head(retained, monkeypatch):
    _forbid_execution(retained, monkeypatch)
    head = retained["expected_head"]
    with pytest.raises(StaleCodebaseError):
        _train(retained, expected_head=replace(head, generation=head.generation + 1))


def test_completed_retry_rejects_live_source_changes_without_new_work(retained, monkeypatch):
    _forbid_execution(retained, monkeypatch)
    path = retained["repository"] / "a.py"
    original = path.read_bytes()
    path.write_text("def changed(n: int) -> int:\n    return n + 999\n")
    try:
        with pytest.raises(StaleCodebaseError):
            _train(retained)
    finally:
        path.write_bytes(original)


def test_completed_retry_rejects_pre_cancelled_call(retained, monkeypatch):
    _forbid_execution(retained, monkeypatch)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(schedulers.LeaseCancelledError):
        _train(retained, cancel_event=cancelled)


def test_completed_retry_checks_cancellation_after_metadata_recovery(retained, monkeypatch):
    _forbid_execution(retained, monkeypatch)
    cancelled = threading.Event()
    recover = indexed.recover_indexed_dispatched_codebase_round
    def cancel_after_recovery(*args, **kwargs):
        result = recover(*args, **kwargs)
        cancelled.set()
        return result
    monkeypatch.setattr(indexed, "recover_indexed_dispatched_codebase_round", cancel_after_recovery)
    with pytest.raises(schedulers.LeaseCancelledError):
        _train(retained, cancel_event=cancelled)
    assert retained["scheduler"].snapshot()["active_lease_count"] == 0


def test_completed_retry_explicitly_recovers_missing_metadata_only(retained, monkeypatch):
    _forbid_execution(retained, monkeypatch)
    path = retained["index"].artifacts.path_for(retained["record"].artifact_cid)
    raw = path.read_bytes()
    path.unlink()
    try:
        assert _train(retained).artifact_cid == retained["record"].artifact_cid
        assert path.read_bytes() == raw
    finally:
        if not path.exists():
            path.write_bytes(raw)


def test_completed_retry_does_not_enable_gradient_execution(retained, monkeypatch):
    _forbid_execution(retained, monkeypatch)
    with pytest.raises(GradientBackendUnavailable):
        _train(retained, mode=TrainingMode.GRADIENT_SYNCHRONIZED)


def test_fresh_process_retries_completed_round_without_fit_or_queue_mutation(retained):
    before = _artifact_files(retained)
    retained["queue"].close()
    retained["registry"].close()
    retained["connection"].close()
    request = {"head": retained["expected_head"].to_dict(),
               "base_version_id": retained["parent"].to_dict()["version_id"]}
    script = r'''
import json, sys
from pathlib import Path
import ipfs_accelerate_py
import duckdb
from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
from ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch import CodebaseQueueDispatcher
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source
from ipfs_datasets_py.logic.software_contracts import codebase_federated_training as federation
from ipfs_datasets_py.logic.software_contracts.codebase_indexed_dispatched_training import train_current_indexed_dispatched_codebase_round
from ipfs_datasets_py.logic.software_contracts.codebase_federated_artifacts import CodebaseFederatedArtifactWorker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
root, requested = Path(sys.argv[1]), json.loads(sys.argv[2])
connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
store, metadata, artifacts = DuckDBASTStore(connection=connection), ImmutableCAS(root / "artifacts"), ImmutableCAS(root / "transfer-artifacts")
index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=metadata,
                               catalog=CodebaseCatalog(store, metadata))
scheduler = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
    state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 16384, 16384),
    lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005))
registry, queue = AutoencoderRegistry(root / "models.duckdb", root / "model-artifacts"), TaskQueue(str(root / "queue.duckdb"))
worker = CodebaseFederatedArtifactWorker(artifacts, root / "worker-receipts", scheduler=scheduler)
dispatcher = CodebaseQueueDispatcher(queue, worker)
def forbidden(*args, **kwargs):
    raise AssertionError("fresh-process retry attempted numerical execution or queue mutation")
source._worker = forbidden
dispatcher.dispatch = forbidden
for name in ("list", "submit", "submit_once", "claim", "complete"):
    setattr(queue, name, forbidden)
for name in ("claim_run", "complete_run", "fail_run", "stage_artifact"):
    setattr(registry, name, forbidden)
artifacts.put = artifacts.put_bytes = forbidden
try:
    record = train_current_indexed_dispatched_codebase_round(index, root / "repository",
        expected_head=CodebaseHead.from_dict(requested["head"]), registry=registry,
        base_version_id=requested["base_version_id"],
        clients=[federation.CodebaseFederatedClient("one", ("c.py",)),
                 federation.CodebaseFederatedClient("two", ("a.py", "b.py"))],
        operation_id="retained", dispatcher=dispatcher, scheduler=scheduler)
    result = {"record": record.to_dict(), "observed_live": record.observed_live,
              "numerical_invocations": worker.numerical_invocations,
              "scheduler_active_leases": scheduler.snapshot()["active_lease_count"]}
    (root / "fresh-process-result.json").write_text(json.dumps(result, sort_keys=True, indent=2))
    print(json.dumps(result, sort_keys=True))
finally:
    queue.close()
    registry.close()
    connection.close()
'''
    environment = dict(os.environ)
    datasets = Path(__file__).resolve().parents[4]
    environment["PYTHONPATH"] = str(datasets.parent / "ipfs_accelerate") + os.pathsep + str(datasets)
    try:
        process = subprocess.run([sys.executable, "-c", script, str(retained["root"]), json.dumps(request)],
            env=environment, cwd=datasets.parent.parent, capture_output=True, text=True, timeout=120)
        assert process.returncode == 0, process.stdout + process.stderr
        result = json.loads(process.stdout.strip().splitlines()[-1])
        assert result["record"] == retained["record"].to_dict()
        assert result["observed_live"] is True and result["numerical_invocations"] == 0
        assert result["scheduler_active_leases"] == 0
        assert _artifact_files(retained) == before
    finally:
        root = retained["root"]
        connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
        store, metadata = DuckDBASTStore(connection=connection), ImmutableCAS(root / "artifacts")
        artifacts = ImmutableCAS(root / "transfer-artifacts")
        registry, queue = AutoencoderRegistry(root / "models.duckdb", root / "model-artifacts"), TaskQueue(str(root / "queue.duckdb"))
        worker = CodebaseFederatedArtifactWorker(artifacts, root / "worker-receipts", scheduler=retained["scheduler"])
        retained.update(connection=connection, artifacts=artifacts, registry=registry, queue=queue, worker=worker,
            dispatcher=CodebaseQueueDispatcher(queue, worker),
            index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=metadata,
                catalog=CodebaseCatalog(store, metadata)))
