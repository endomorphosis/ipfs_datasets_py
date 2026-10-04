"""Actual source-owned artifact queue federation and immutable replay."""
import threading

import duckdb
import pytest

from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
from ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch import CodebaseQueueDispatcher, TASK_TYPE
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source
from ipfs_datasets_py.logic.software_contracts import codebase_federated_training as federation
from ipfs_datasets_py.logic.software_contracts import codebase_dispatched_federation as owner
from ipfs_datasets_py.logic.software_contracts.codebase_federated_artifacts import CodebaseFederatedArtifactWorker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


@pytest.fixture(scope="module")
def dispatched(tmp_path_factory):
    root = tmp_path_factory.mktemp("codebase-dispatched-native")
    repository = root / "repository"
    repository.mkdir()
    for path, value in (("a.py", 1), ("b.py", 2), ("c.py", 3), ("tune.py", 7), ("canary.py", 9)):
        (repository / path).write_text(f"def step(n: int) -> int:\n    return n + {value}\n")
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(root / "artifacts")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
        catalog=CodebaseCatalog(store, artifacts))
    scheduler = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 16384, 16384),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005))
    head = index.prepare_current(repository, repository_id="test:codebase-dispatched", operation_id="capture",
        expected_head=None, scheduler=scheduler).head
    registry = AutoencoderRegistry(root / "models.duckdb", root / "model-artifacts")
    selections = [source.CodebaseTrainingSelection(path, "train" if path in {"a.py", "b.py", "c.py"} else path[:-3])
                  for path in ("a.py", "b.py", "c.py", "tune.py", "canary.py")]
    parent = source.train_current_codebase_features(index, repository, expected_head=head, registry=registry,
        selections=selections, operation_id="root", epochs=1, learning_rate=.002, scheduler=scheduler)
    queue = TaskQueue(str(root / "queue.duckdb"))
    worker = CodebaseFederatedArtifactWorker(artifacts, root / "worker-receipts", scheduler=scheduler)
    dispatcher = CodebaseQueueDispatcher(queue, worker)
    state = {"root": root, "repository": repository, "index": index, "registry": registry,
        "scheduler": scheduler, "expected_head": head, "parent": parent, "queue": queue,
        "worker": worker, "dispatcher": dispatcher, "artifacts": artifacts,
        "clients": [federation.CodebaseFederatedClient("one", ("c.py",)),
                    federation.CodebaseFederatedClient("two", ("a.py", "b.py"))]}
    state["round"] = train(state)
    yield state
    assert scheduler.snapshot()["active_lease_count"] == scheduler.snapshot()["waiting_request_count"] == 0
    queue.close()
    registry.close()
    connection.close()


def train(state, **changes):
    args = {name: state[name] for name in ("index", "repository", "registry", "scheduler", "expected_head",
                                         "clients", "dispatcher", "worker", "artifacts")}
    args.update(base_version_id=state["parent"].to_dict()["version_id"], operation_id="round", epochs=1, learning_rate=.002)
    args.update(changes)
    return owner.train_current_dispatched_codebase_round(**args)


def load(state, **changes):
    args = dict(dispatcher=state["dispatcher"], artifacts=state["artifacts"], artifact_cid=state["round"].artifact_cid)
    args.update(changes)
    return owner.load_dispatched_codebase_round(state["index"], state["registry"], state["round"].to_dict()["version_id"], **args)


def test_actual_private_artifact_jobs_have_weighted_round_and_compatible_model(dispatched):
    record = dispatched["round"].to_dict()
    assert record["schema"] == owner.SCHEMA and dispatched["round"].observed_live is True
    assert dispatched["worker"].numerical_invocations == 2
    assert len(record["clients"]) == 2
    model = federation.load_codebase_federated_training(dispatched["index"], dispatched["registry"], record["version_id"])
    assert model.artifact_cid == record["model_record_cid"]
    saved = runtimes._read_candidate(dispatched["registry"], dispatched["registry"].get_version(record["version_id"]))
    report = saved["report"]["codebase_federation"]
    assert [(item["client_id"], item["sample_count"]) for item in report["round"]["clients"]] == [("one", 1), ("two", 2)]
    assert saved["state"]["completed_epochs"] == 0
    assert all(item["step"] == 0 for item in saved["state"]["adam"])
    for local, sidecar in zip(report["clients"], record["clients"]):
        row = dispatched["queue"].get(sidecar["task_id"])
        assert row["status"] == "completed" and row["task_type"] == TASK_TYPE and row["attempt"] == 1
        assert set(row["payload"]) == {"schema", "declaration", "context_artifact", "implementation"}
        assert "local_state" not in row["result"] and "parameters" not in row["payload"]
        assert row["payload"]["declaration"]["payload"]["work_binding"] == local["work_binding"]
        assert local["work_binding"]["attempt"] == record["native_attempt"]
        assert local["work_binding"]["fence"] == record["native_fence"]
    assert all(flag is False for flag in record["authority"].values())
    assert dispatched["registry"].resolve_head(record["variant_id"], "main") is None


def test_historical_sidecar_load_is_read_only_and_never_dispatches(dispatched, monkeypatch):
    monkeypatch.setattr(dispatched["dispatcher"], "dispatch", lambda *a, **k: pytest.fail("historical dispatch"))
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("historical fit"))
    monkeypatch.setattr(dispatched["artifacts"], "put", lambda *a, **k: pytest.fail("historical publication"))
    monkeypatch.setattr(dispatched["artifacts"], "put_bytes", lambda *a, **k: pytest.fail("historical raw publication"))
    assert load(dispatched).to_dict() == dispatched["round"].to_dict()
    assert load(dispatched).observed_live is False


def test_completed_retry_and_explicit_recovery_do_not_refit(dispatched, monkeypatch):
    monkeypatch.setattr(dispatched["dispatcher"], "dispatch", lambda *a, **k: pytest.fail("completed round dispatch"))
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("completed round fit"))
    assert train(dispatched).artifact_cid == dispatched["round"].artifact_cid
    restored = owner.recover_dispatched_codebase_round(dispatched["index"], dispatched["registry"],
        dispatched["round"].to_dict()["version_id"], queue=dispatched["queue"], artifacts=dispatched["artifacts"])
    assert restored.artifact_cid == dispatched["round"].artifact_cid and restored.observed_live is False
    with pytest.raises(RegistryError, match="operation|payload"):
        train(dispatched, seed=2)


def test_queue_corruption_rejects_even_when_model_remains_valid(dispatched, monkeypatch):
    original = dispatched["queue"].get
    task_id = dispatched["round"].to_dict()["clients"][0]["task_id"]
    def changed(value):
        row = original(value)
        if value == task_id:
            row["attempt"] += 1
        return row
    monkeypatch.setattr(dispatched["queue"], "get", changed)
    with pytest.raises(source.CodebaseFeatureTrainingError, match="sidecar|snapshot"):
        load(dispatched)


def test_corrupt_worker_artifact_rejects_sidecar_replay(dispatched, monkeypatch):
    row = dispatched["queue"].get(dispatched["round"].to_dict()["clients"][0]["task_id"])
    artifact_cid = row["result"]["local_checkpoint"]["cidv1"]
    original = dispatched["artifacts"].get_bytes
    def changed(cid):
        raw = original(cid)
        return raw[:-1] + b" " if cid == artifact_cid else raw
    monkeypatch.setattr(dispatched["artifacts"], "get_bytes", changed)
    with pytest.raises(source.CodebaseFeatureTrainingError, match="artifact bytes"):
        load(dispatched)


def test_lost_sidecar_publication_recovers_from_native_history_without_fit(dispatched, monkeypatch):
    original = dispatched["artifacts"].put
    def lost(value):
        if value.get("schema") == owner.SCHEMA:
            raise RuntimeError("lost sidecar publication response")
        return original(value)
    with monkeypatch.context() as patch:
        patch.setattr(dispatched["artifacts"], "put", lost)
        with pytest.raises(RuntimeError, match="lost sidecar"):
            train(dispatched, operation_id="lost-publication")
    completion = dispatched["registry"].get_run_completion("codebase-dispatched-fed:lost-publication")
    assert completion is not None
    version_id = completion["candidate_version"]["version_id"]
    with pytest.raises(FileNotFoundError):
        owner.load_dispatched_codebase_round(dispatched["index"], dispatched["registry"], version_id,
            queue=dispatched["queue"], artifacts=dispatched["artifacts"])
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("native completion recovery fitted"))
    recovered = train(dispatched, operation_id="lost-publication")
    assert recovered.to_dict()["version_id"] == version_id
    assert owner.load_dispatched_codebase_round(dispatched["index"], dispatched["registry"], version_id,
        queue=dispatched["queue"], artifacts=dispatched["artifacts"], artifact_cid=recovered.artifact_cid)


def test_failed_queue_worker_cleans_native_run_and_shared_resource_lease(dispatched, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("injected local worker failure")
    monkeypatch.setattr(source, "_worker", fail)
    with pytest.raises(RuntimeError, match="injected local"):
        train(dispatched, operation_id="worker-failed")
    row = dispatched["registry"].get_run("codebase-dispatched-fed:worker-failed")
    assert row["status"] == "failed" and row["lease"] is None
    assert dispatched["registry"].get_run_completion(row["run_id"]) is None
    assert dispatched["scheduler"].snapshot()["active_lease_count"] == 0
    failed_tasks = [item for item in dispatched["queue"].list(task_types=[TASK_TYPE])
                    if item["payload"]["declaration"]["payload"]["work_binding"]["round"]["round_id"].endswith(":worker-failed")]
    assert len(failed_tasks) == 1 and failed_tasks[0]["status"] == "queued" and failed_tasks[0]["assigned_worker"] is None


def test_new_dispatched_round_can_inherit_the_compatible_aggregate(dispatched):
    child = train(dispatched, base_version_id=dispatched["round"].to_dict()["version_id"], operation_id="second")
    assert child.to_dict()["parent_version_id"] == dispatched["round"].to_dict()["version_id"]
    assert child.to_dict()["origin_version_id"] == dispatched["parent"].to_dict()["version_id"]
    assert federation.load_codebase_federated_training(dispatched["index"], dispatched["registry"], child.to_dict()["version_id"])


def test_source_change_during_artifact_fit_cannot_complete_queue_or_model(dispatched, monkeypatch):
    path = dispatched["repository"] / "c.py"
    previous = path.read_bytes()
    numerical = source._worker
    def changed(*args, **kwargs):
        result = numerical(*args, **kwargs)
        path.write_text("def step(n: int) -> int:\n    return n + 99\n")
        return result
    monkeypatch.setattr(source, "_worker", changed)
    try:
        with pytest.raises(Exception, match="head|source|repository|changed|differs"):
            train(dispatched, operation_id="changed-source")
    finally:
        path.write_bytes(previous)
    run = dispatched["registry"].get_run("codebase-dispatched-fed:changed-source")
    assert run["status"] == "failed" and run["lease"] is None
    assert dispatched["registry"].get_run_completion(run["run_id"]) is None
    rows = [row for row in dispatched["queue"].list(task_types=[TASK_TYPE])
            if row["payload"]["declaration"]["payload"]["work_binding"]["round"]["round_id"] == run["run_id"]]
    assert len(rows) == 1 and rows[0]["status"] != "completed"


def test_cancelled_round_refuses_before_queue_submission(dispatched):
    cancelled = threading.Event()
    cancelled.set()
    before = dispatched["queue"].count(task_types=[TASK_TYPE])
    with pytest.raises(schedulers.LeaseCancelledError):
        train(dispatched, operation_id="cancelled", cancel_event=cancelled)
    assert dispatched["queue"].count(task_types=[TASK_TYPE]) == before
