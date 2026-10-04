"""Exact native request-index recovery beyond the legacy queue inventory cap."""
from contextlib import contextmanager
import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import duckdb
import pytest

from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
from ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch import CodebaseQueueDispatcher, CodebaseDispatchError, TASK_TYPE
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source
from ipfs_datasets_py.logic.software_contracts import codebase_federated_training as federation
from ipfs_datasets_py.logic.software_contracts import codebase_dispatched_federation as owner
from ipfs_datasets_py.logic.software_contracts import codebase_indexed_dispatch_recovery as indexed
from ipfs_datasets_py.logic.software_contracts.codebase_federated_artifacts import CodebaseFederatedArtifactWorker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


def _open_state(state):
    root = state["root"]
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    metadata_artifacts = ImmutableCAS(root / "artifacts")
    artifacts = ImmutableCAS(root / "transfer-artifacts")
    state.update(connection=connection, artifacts=artifacts,
        index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=metadata_artifacts,
            catalog=CodebaseCatalog(store, metadata_artifacts)),
        registry=AutoencoderRegistry(root / "models.duckdb", root / "model-artifacts"),
        queue=TaskQueue(str(root / "queue.duckdb")))
    state["worker"] = CodebaseFederatedArtifactWorker(artifacts, root / "worker-receipts", scheduler=state["scheduler"])
    state["dispatcher"] = CodebaseQueueDispatcher(state["queue"], state["worker"])


def _close_state(state):
    state["queue"].close()
    state["registry"].close()
    state["connection"].close()


@pytest.fixture(scope="module")
def retained(tmp_path_factory):
    root = tmp_path_factory.mktemp("codebase-indexed-recovery-native")
    repository = root / "repository"
    repository.mkdir()
    for path, value in (("a.py", 1), ("b.py", 2), ("c.py", 3), ("tune.py", 7), ("canary.py", 9)):
        (repository / path).write_text(f"def step(n: int) -> int:\n    return n + {value}\n")
    scheduler = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 16384, 16384),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005))
    state = {"root": root, "repository": repository, "scheduler": scheduler}
    _open_state(state)
    head = state["index"].prepare_current(repository, repository_id="test:codebase-indexed-recovery",
        operation_id="capture", expected_head=None, scheduler=scheduler).head
    selections = [source.CodebaseTrainingSelection(path, "train" if path in {"a.py", "b.py", "c.py"} else path[:-3])
                  for path in ("a.py", "b.py", "c.py", "tune.py", "canary.py")]
    parent = source.train_current_codebase_features(state["index"], repository, expected_head=head,
        registry=state["registry"], selections=selections, operation_id="root", epochs=1,
        learning_rate=.002, scheduler=scheduler)
    record = owner.train_current_dispatched_codebase_round(state["index"], repository,
        expected_head=head, registry=state["registry"], base_version_id=parent.to_dict()["version_id"],
        clients=[federation.CodebaseFederatedClient("one", ("c.py",)),
                 federation.CodebaseFederatedClient("two", ("a.py", "b.py"))],
        operation_id="retained", dispatcher=state["dispatcher"], worker=state["worker"],
        artifacts=state["artifacts"], scheduler=scheduler, epochs=1, learning_rate=.002)
    state.update(head=head, parent=parent, record=record, version_id=record.to_dict()["version_id"])
    # More than the native list cap precede and follow the retained cohort.
    # Direct bulk population keeps the test focused on persisted SQL history,
    # without invoking 2002 unrelated numerical handlers.
    with state["queue"]._conn_lock:
        connection = state["queue"]._get_conn()
        for side, offset in (("older", 0.0), ("newer", 1e12)):
            connection.execute("""INSERT INTO tasks
                (task_id,task_type,model_name,payload_json,status,assigned_worker,
                 created_at,updated_at,result_json,error,priority,attempt,max_attempts,
                 next_attempt_at,lease_until,heartbeat_at,idempotency_key)
                SELECT ? || CAST(range AS VARCHAR), ?, 'unrelated-model', '{}',
                    'completed', 'unrelated-worker', ? + range, ? + range, '{}', NULL,
                    5, 1, 3, 0, NULL, NULL, NULL FROM range(1001)""",
                ["unrelated:" + side + ":", TASK_TYPE, offset, offset])
    yield state
    assert scheduler.snapshot()["active_lease_count"] == scheduler.snapshot()["waiting_request_count"] == 0
    _close_state(state)


def _load(state, **kwargs):
    return indexed.load_indexed_dispatched_codebase_round(state["index"], state["registry"],
        state["version_id"], queue=state["queue"], artifacts=state["artifacts"], **kwargs)


def _recover(state, **kwargs):
    return indexed.recover_indexed_dispatched_codebase_round(state["index"], state["registry"],
        state["version_id"], queue=state["queue"], artifacts=state["artifacts"], **kwargs)


def _files(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def _artifact_files(state):
    return {name: _files(state["root"] / name) for name in ("artifacts", "transfer-artifacts")}


def test_native_inventory_cap_omits_retained_cohort_but_exact_recovery_succeeds(retained):
    assert retained["queue"].count(task_types=[TASK_TYPE]) == 2004
    listed = retained["queue"].list(status="completed", task_types=[TASK_TYPE], limit=10000)
    assert len(listed) == 1000
    ids = {item["task_id"] for item in retained["record"].to_dict()["clients"]}
    assert not ids.intersection(item["task_id"] for item in listed)
    with pytest.raises(source.CodebaseFeatureTrainingError, match="discovery bound"):
        owner.load_dispatched_codebase_round(retained["index"], retained["registry"], retained["version_id"],
            queue=retained["queue"], artifacts=retained["artifacts"])
    recovered = _load(retained)
    assert recovered.artifact_cid == retained["record"].artifact_cid
    assert recovered.to_dict() == retained["record"].to_dict()
    assert recovered.observed_live is False


def test_indexed_historical_load_neither_scans_nor_dispatches_nor_publishes(retained, monkeypatch):
    before = _artifact_files(retained)
    def forbidden(*args, **kwargs):
        pytest.fail("historical indexed recovery invoked a mutation or inventory scan")
    for name in ("list", "submit", "submit_once", "claim", "complete"):
        monkeypatch.setattr(retained["queue"], name, forbidden)
    monkeypatch.setattr(retained["dispatcher"], "dispatch", forbidden)
    monkeypatch.setattr(retained["index"], "prepare_current", forbidden)
    monkeypatch.setattr(source, "_worker", forbidden)
    monkeypatch.setattr(retained["artifacts"], "put", forbidden)
    monkeypatch.setattr(retained["artifacts"], "put_bytes", forbidden)
    monkeypatch.setattr(retained["index"].artifacts, "put", forbidden)
    monkeypatch.setattr(retained["index"].artifacts, "put_bytes", forbidden)
    assert _load(retained).artifact_cid == retained["record"].artifact_cid
    assert indexed.load_indexed_dispatched_codebase_round(retained["index"], retained["registry"],
        retained["version_id"], dispatcher=retained["dispatcher"]).artifact_cid == retained["record"].artifact_cid
    assert _artifact_files(retained) == before


def test_missing_sidecar_is_republished_only_by_explicit_recovery(retained, monkeypatch):
    path = retained["index"].artifacts.path_for(retained["record"].artifact_cid)
    before = path.read_bytes()
    path.unlink()
    try:
        def forbidden(*args, **kwargs):
            pytest.fail("explicit metadata recovery invoked fitting, dispatch, or queue inventory")
        monkeypatch.setattr(source, "_worker", forbidden)
        monkeypatch.setattr(retained["queue"], "list", forbidden)
        monkeypatch.setattr(retained["dispatcher"], "dispatch", forbidden)
        monkeypatch.setattr(retained["artifacts"], "put", forbidden)
        monkeypatch.setattr(retained["artifacts"], "put_bytes", forbidden)
        with pytest.raises(FileNotFoundError):
            _load(retained)
        assert not path.exists()
        restored = _recover(retained)
        assert restored.artifact_cid == retained["record"].artifact_cid and restored.observed_live is False
        assert path.read_bytes() == before
        assert _load(retained).to_dict() == retained["record"].to_dict()
    finally:
        if not path.exists():
            path.write_bytes(before)


@pytest.mark.parametrize("kind", ["task_cid", "result_cid", "queue_row_cid", "model_record_cid"])
def test_missing_retained_snapshot_requires_explicit_publication(retained, monkeypatch, kind):
    value = retained["record"].to_dict()
    cid = value[kind] if kind == "model_record_cid" else value["clients"][0][kind]
    path = retained["index"].artifacts.path_for(cid)
    before = path.read_bytes()
    path.unlink()
    try:
        monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("snapshot recovery fitted"))
        monkeypatch.setattr(retained["queue"], "list", lambda *a, **k: pytest.fail("snapshot recovery scanned"))
        with pytest.raises(FileNotFoundError):
            _load(retained)
        assert not path.exists()
        assert _recover(retained).artifact_cid == retained["record"].artifact_cid
        assert path.read_bytes() == before
    finally:
        if not path.exists():
            path.write_bytes(before)


def test_opt_out_preserves_the_previous_bounded_discovery_policy(retained):
    with pytest.raises(source.CodebaseFeatureTrainingError, match="discovery bound"):
        _load(retained, use_request_index=False)
    with pytest.raises(source.CodebaseFeatureTrainingError, match="discovery bound"):
        _recover(retained, use_request_index=False)


@pytest.mark.parametrize("policy", [0, 1, None, "true", [], {}])
@pytest.mark.parametrize("operation", [_load, _recover])
def test_request_index_policy_requires_an_exact_boolean(retained, policy, operation):
    with pytest.raises(source.CodebaseFeatureTrainingError, match="policy"):
        operation(retained, use_request_index=policy)


@pytest.mark.parametrize("policy", [True, False])
def test_explicit_sidecar_cid_uses_retained_ids_without_index_or_scan(retained, monkeypatch, policy):
    monkeypatch.setattr(indexed._history(), "find_codebase_federated_task",
        lambda *a, **k: pytest.fail("CID-addressed recovery used the request index"))
    monkeypatch.setattr(retained["queue"], "list", lambda *a, **k: pytest.fail("CID-addressed recovery scanned"))
    assert _load(retained, artifact_cid=retained["record"].artifact_cid,
        use_request_index=policy).artifact_cid == retained["record"].artifact_cid


def test_root_source_model_is_rejected_as_a_dispatched_candidate(retained):
    with pytest.raises(source.CodebaseFeatureTrainingError, match="dispatched"):
        indexed.load_indexed_dispatched_codebase_round(retained["index"], retained["registry"],
            retained["parent"].to_dict()["version_id"], queue=retained["queue"], artifacts=retained["artifacts"])


def test_wrong_native_queue_is_missing_evidence_without_creating_work(retained, tmp_path):
    queue = TaskQueue(str(tmp_path / "unrelated.duckdb"))
    try:
        with pytest.raises(source.CodebaseFeatureTrainingError, match="absent"):
            indexed.load_indexed_dispatched_codebase_round(retained["index"], retained["registry"],
                retained["version_id"], queue=queue, artifacts=retained["artifacts"])
        assert queue.count() == 0
    finally:
        queue.close()


def test_untyped_transfer_store_is_rejected(retained):
    with pytest.raises(source.CodebaseFeatureTrainingError, match="artifact store"):
        indexed.load_indexed_dispatched_codebase_round(retained["index"], retained["registry"],
            retained["version_id"], queue=retained["queue"], artifacts={})


def test_historical_indexed_recovery_does_not_claim_live_source_observation(retained, monkeypatch):
    path = retained["repository"] / "a.py"
    before = path.read_bytes()
    path.write_text("def changed(n: int) -> int:\n    return n + 999\n")
    try:
        monkeypatch.setattr(retained["index"], "prepare_current",
            lambda *a, **k: pytest.fail("historical recovery observed live source"))
        result = _load(retained)
        assert result.to_dict() == retained["record"].to_dict()
        assert result.observed_live is False
    finally:
        path.write_bytes(before)


@contextmanager
def _changed_queue_row(state, **columns):
    task_id = state["record"].to_dict()["clients"][0]["task_id"]
    with state["queue"]._conn_lock:
        connection = state["queue"]._get_conn()
        original = {name: connection.execute("SELECT " + name + " FROM tasks WHERE task_id=?", [task_id]).fetchone()[0]
                    for name in columns}
        for name, value in columns.items():
            connection.execute("UPDATE tasks SET " + name + "=? WHERE task_id=?", [value, task_id])
    try:
        yield
    finally:
        with state["queue"]._conn_lock:
            connection = state["queue"]._get_conn()
            for name, value in original.items():
                connection.execute("UPDATE tasks SET " + name + "=? WHERE task_id=?", [value, task_id])


@pytest.mark.parametrize("column,value", [
    ("idempotency_key", "f" * 64), ("task_type", "other-task"), ("model_name", "other-model"),
    ("status", "failed"), ("assigned_worker", None), ("attempt", 0),
    ("error", "changed terminal result"), ("payload_json", "{}"), ("result_json", "{}"),
])
def test_changed_native_indexed_row_rejects(retained, column, value):
    with _changed_queue_row(retained, **{column: value}):
        with pytest.raises((source.CodebaseFeatureTrainingError, CodebaseDispatchError)):
            _load(retained)
    assert _load(retained).artifact_cid == retained["record"].artifact_cid


@pytest.mark.parametrize("artifact", ["base", "local", "context", "checkpoint", "update"])
def test_changed_input_or_result_artifact_rejects(retained, monkeypatch, artifact):
    row = retained["queue"].get(retained["record"].to_dict()["clients"][0]["task_id"])
    refs = row["payload"]["declaration"]["payload"]["artifacts"]
    cid = {"base": refs["base_checkpoint"]["cidv1"], "local": refs["local_payload"]["cidv1"],
        "context": row["payload"]["context_artifact"]["cidv1"],
        "checkpoint": row["result"]["local_checkpoint"]["cidv1"], "update": row["result"]["update"]["cidv1"]}[artifact]
    original = retained["artifacts"].get_bytes
    def corrupt(value):
        raw = original(value)
        return raw[:-1] + bytes([raw[-1] ^ 1]) if value == cid else raw
    monkeypatch.setattr(retained["artifacts"], "get_bytes", corrupt)
    with pytest.raises(source.CodebaseFeatureTrainingError, match="artifact bytes"):
        _load(retained)


def test_coherently_changed_context_cannot_redirect_the_committed_request_index(retained):
    row = retained["queue"].get(retained["record"].to_dict()["clients"][0]["task_id"])
    payload = row["payload"]
    payload["context_artifact"] = payload["declaration"]["payload"]["artifacts"]["local_payload"]
    from ipfs_accelerate_py.p2p_tasks.codebase_federated_dispatch import codebase_dispatch_request_sha256
    changed_key = codebase_dispatch_request_sha256(payload, row["model_name"])
    with _changed_queue_row(retained, payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                            idempotency_key=changed_key):
        with pytest.raises((source.CodebaseFeatureTrainingError, CodebaseDispatchError)):
            _load(retained)


@pytest.mark.parametrize("change", ["fence", "candidate"])
def test_changed_native_model_completion_rejects(retained, monkeypatch, change):
    original = retained["registry"].get_run_completion
    run_id = retained["record"].to_dict()["native_run_id"]
    def altered(value):
        completion = original(value)
        if value == run_id:
            completion = copy.deepcopy(completion)
            if change == "fence":
                completion["run"]["lease"]["fence"] += 1
            else:
                completion["candidate_version"]["parent_version_id"] = completion["candidate_version"]["version_id"]
        return completion
    monkeypatch.setattr(retained["registry"], "get_run_completion", altered)
    with pytest.raises(source.CodebaseFeatureTrainingError):
        _load(retained)


@pytest.mark.parametrize("field", ["max_selections", "max_targets", "max_features", "max_ancestry",
    "max_training_history", "max_target_bytes", "max_candidate_bytes", "max_ancestry_bytes"])
def test_indexed_recovery_retains_native_source_and_artifact_bounds(retained, field):
    limits = replace(source.CodebaseFeatureTrainingLimits(), **{field: 1})
    with pytest.raises(source.CodebaseFeatureTrainingError):
        _load(retained, limits=limits)


def test_fresh_process_reconstructs_identical_provenance_without_fit_or_publication(retained):
    before = _artifact_files(retained)
    _close_state(retained)
    script = r'''
import json, sys
sys.path.insert(0, sys.argv[3])
from pathlib import Path
import duckdb
from ipfs_accelerate_py.p2p_tasks.task_queue import TaskQueue
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as source
from ipfs_datasets_py.logic.software_contracts.codebase_indexed_dispatch_recovery import load_indexed_dispatched_codebase_round
root = Path(sys.argv[1])
connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
store = DuckDBASTStore(connection=connection)
metadata_artifacts = ImmutableCAS(root / "artifacts")
artifacts = ImmutableCAS(root / "transfer-artifacts")
index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=metadata_artifacts, catalog=CodebaseCatalog(store, metadata_artifacts))
registry = AutoencoderRegistry(root / "models.duckdb", root / "model-artifacts")
queue = TaskQueue(str(root / "queue.duckdb"))
def forbidden(*args, **kwargs):
    raise AssertionError("restart historical recovery mutated, fitted, or scanned")
queue.list = queue.submit = queue.submit_once = forbidden
source._worker = artifacts.put = artifacts.put_bytes = index.prepare_current = forbidden
metadata_artifacts.put = metadata_artifacts.put_bytes = forbidden
record = load_indexed_dispatched_codebase_round(index, registry, sys.argv[2], queue=queue, artifacts=artifacts)
queue.close(); registry.close(); connection.close()
print(json.dumps({"cid": record.artifact_cid, "value": record.to_dict(), "observed_live": record.observed_live}, sort_keys=True))
'''
    try:
        env = dict(os.environ)
        accelerate_root = str(Path(sys.modules[TaskQueue.__module__].__file__).resolve().parents[2])
        datasets_root = str(Path(source.__file__).resolve().parents[3])
        env["PYTHONPATH"] = os.pathsep.join((accelerate_root, datasets_root))
        result = subprocess.run([sys.executable, "-c", script, str(retained["root"]), retained["version_id"], accelerate_root],
            env=env, text=True, capture_output=True, timeout=120)
        assert result.returncode == 0, result.stderr
        value = json.loads(result.stdout.splitlines()[-1])
        assert value == {"cid": retained["record"].artifact_cid, "value": retained["record"].to_dict(), "observed_live": False}
        assert _artifact_files(retained) == before
    finally:
        _open_state(retained)
