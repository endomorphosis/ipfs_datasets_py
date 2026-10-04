"""Bounded parallel native artifact workers, source fencing, and no-fit replay.

The overlap probe observes actual native numerical PIDs and trainer leases.
It neither delays the numerical workers nor substitutes a fake numerical fit.
"""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import threading
import time

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
from ipfs_datasets_py.logic.software_contracts import codebase_parallel_dispatched_federation as parallel
from ipfs_datasets_py.logic.software_contracts.codebase_federated_artifacts import CodebaseFederatedArtifactWorker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


def _open_state(state):
    root = state["root"]
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    metadata = ImmutableCAS(root / "artifacts")
    artifacts = ImmutableCAS(root / "transfer-artifacts")
    state.update(connection=connection, artifacts=artifacts,
        index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=metadata,
            catalog=CodebaseCatalog(store, metadata)),
        registry=AutoencoderRegistry(root / "models.duckdb", root / "model-artifacts"),
        queue=TaskQueue(str(root / "queue.duckdb")))
    state["worker"] = CodebaseFederatedArtifactWorker(artifacts, root / "worker-receipts", scheduler=state["scheduler"])
    state["dispatcher"] = CodebaseQueueDispatcher(state["queue"], state["worker"])


def _close_state(state):
    state["queue"].close()
    state["registry"].close()
    state["connection"].close()


def _build_state(root):
    repository = root / "repository"
    repository.mkdir()
    for path, value in (("a.py", 1), ("b.py", 2), ("c.py", 3), ("tune.py", 7), ("canary.py", 9)):
        (repository / path).write_text(f"def step(n: int) -> int:\n    return n + {value}\n")
    scheduler = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 16384, 16384),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005))
    state = {"root": root, "repository": repository, "scheduler": scheduler}
    _open_state(state)
    head = state["index"].prepare_current(repository, repository_id="test:codebase-parallel-dispatch",
        operation_id="capture", expected_head=None, scheduler=scheduler).head
    selections = [source.CodebaseTrainingSelection(path, "train" if path in {"a.py", "b.py", "c.py"} else path[:-3])
                  for path in ("a.py", "b.py", "c.py", "tune.py", "canary.py")]
    parent = source.train_current_codebase_features(state["index"], repository, expected_head=head,
        registry=state["registry"], selections=selections, operation_id="root", epochs=1,
        learning_rate=.002, scheduler=scheduler)
    # Reverse input order; the retained aggregate must use canonical client order.
    state.update(head=head, parent=parent,
        clients=[federation.CodebaseFederatedClient("two", ("b.py", "a.py")),
                 federation.CodebaseFederatedClient("one", ("c.py",))])
    return state


def _train(state, **changes):
    args = {name: state[name] for name in ("index", "repository", "registry", "scheduler", "clients", "dispatcher", "worker", "artifacts")}
    args.update(expected_head=state["head"], base_version_id=state["parent"].to_dict()["version_id"],
        operation_id="retained", epochs=1, learning_rate=.002)
    args.update(changes)
    return parallel.train_current_parallel_dispatched_codebase_round(**args)


def _load(state, **changes):
    args = dict(queue=state["queue"], artifacts=state["artifacts"])
    args.update(changes)
    return parallel.load_parallel_dispatched_codebase_round(state["index"], state["registry"],
        state["record"].to_dict()["version_id"], **args)


class NativeNumericalProbe:
    """Record actual Popen handles while retaining the production lifecycle."""

    def __init__(self, scheduler, *, on_spawn=None):
        self.scheduler = scheduler
        self.on_spawn = on_spawn
        self.lock = threading.Lock()
        self.processes = []
        self.observations = []
        self.results = []
        self.max_live_processes = 0
        self.max_trainer_leases = 0
        self.peer_started = threading.Event()

    @contextmanager
    def installed(self):
        original = source.run_bounded_stdin_tool
        def observed(argv, stdin, **kwargs):
            payload = json.loads(stdin)
            if payload.get("action") != "train":
                return original(argv, stdin, **kwargs)
            runner = kwargs["runner"]
            launch = runner._executor._popen
            def popen(*args, **launch_kwargs):
                process = launch(*args, **launch_kwargs)
                with self.lock:
                    self.processes.append(process)
                    live = [child.pid for child in self.processes if child.poll() is None]
                    leases = self.scheduler.active_leases()
                    trainers = [lease for lease in leases if lease["lane"] == "trainer"]
                    self.max_live_processes = max(self.max_live_processes, len(live))
                    self.max_trainer_leases = max(self.max_trainer_leases, len(trainers))
                    self.observations.append({"monotonic": time.monotonic(), "pid": process.pid,
                        "live_pids": live, "trainer_lease_ids": [lease["lease_id"] for lease in trainers],
                        "root_reservations": [{key: lease[key] for key in
                            ("lease_id", "cpu_slots", "memory_mb", "child_process_slots")}
                            for lease in leases if lease["parent_lease_id"] is None],
                        "trainer_memory_mb": [lease["memory_mb"] for lease in trainers]})
                    ordinal = len(self.processes)
                    self.peer_started.set()
                if self.on_spawn is not None:
                    self.on_spawn(process, ordinal)
                return process
            runner._executor._popen = popen
            result = original(argv, stdin, **kwargs)
            with self.lock:
                self.results.append(result)
            return result
        source.run_bounded_stdin_tool = observed
        try:
            yield self
        finally:
            source.run_bounded_stdin_tool = original

    def assert_cleaned(self):
        assert self.processes and all(process.poll() is not None for process in self.processes)
        assert len(self.results) == len(self.processes)
        assert all(result.workspace_cleaned for result in self.results)


@pytest.fixture(scope="module")
def retained(tmp_path_factory):
    state = _build_state(tmp_path_factory.mktemp("codebase-parallel-dispatch-native"))
    with NativeNumericalProbe(state["scheduler"]).installed() as probe:
        state["record"] = _train(state)
    probe.assert_cleaned()
    state["probe"] = probe
    yield state
    snapshot = state["scheduler"].snapshot()
    assert snapshot["active_lease_count"] == snapshot["waiting_request_count"] == 0
    _close_state(state)


def _saved(state, record=None):
    record = state["record"] if record is None else record
    version = state["registry"].get_version(record.to_dict()["version_id"])
    return runtimes._read_candidate(state["registry"], version)


def _run(state, operation):
    with state["registry"]._transaction() as connection:
        rows = connection.execute("SELECT run_id FROM autoencoder_control.runs WHERE run_id LIKE ?",
            ["codebase-dispatched-fed:parallel:" + operation + ":%"]).fetchall()
    assert len(rows) == 1
    return state["registry"].get_run(rows[0][0])


def _cohort(state, operation):
    run_id = _run(state, operation)["run_id"]
    with state["queue"]._conn_lock:
        rows = state["queue"]._get_conn().execute("""SELECT task_id FROM tasks WHERE
            json_extract_string(payload_json, '$.declaration.payload.work_binding.round.round_id')=?
            LIMIT 9""", [run_id]).fetchall()
    assert len(rows) <= 8
    return [state["queue"].get(row[0]) for row in rows]


def _version_count(state):
    with state["registry"]._transaction() as connection:
        return connection.execute("SELECT count(*) FROM autoencoder_control.versions").fetchone()[0]


def _assert_failed(state, operation, before):
    run = _run(state, operation)
    assert run["status"] == "failed" and run["lease"] is None
    assert state["registry"].get_run_completion(run["run_id"]) is None
    assert _version_count(state) == before
    snapshot = state["scheduler"].snapshot()
    assert snapshot["active_lease_count"] == snapshot["waiting_request_count"] == 0


def test_default_executes_two_real_numerical_processes_with_native_trainer_overlap(retained):
    probe = retained["probe"]
    assert len(probe.processes) == 2 and len({process.pid for process in probe.processes}) == 2
    assert probe.max_live_processes == probe.max_trainer_leases == 2
    assert any(len(item["live_pids"]) == len(item["trainer_lease_ids"]) == 2 for item in probe.observations)
    assert retained["worker"].numerical_invocations == 2
    assert retained["record"].observed_live is True


def test_weighted_result_is_canonical_and_compatible_with_existing_model_loader(retained):
    record = retained["record"].to_dict()
    saved = _saved(retained)
    report = saved["report"]["codebase_federation"]
    assert record["schema"] == parallel.SCHEMA
    assert [(item["client_id"], item["sample_count"]) for item in report["round"]["clients"]] == [("one", 1), ("two", 2)]
    assert [item["work_binding"]["client_id"] for item in report["clients"]] == ["one", "two"]
    dispatch = retained["index"].artifacts.get(record["compatible_dispatch_record_cid"])
    assert [item["client_id"] for item in dispatch["clients"]] == ["one", "two"]
    assert saved["state"]["completed_epochs"] == 0
    assert all(item["step"] == 0 for item in saved["state"]["adam"])
    assert federation.load_codebase_federated_training(retained["index"], retained["registry"], record["version_id"])
    assert all(value is False for value in record["authority"].values())
    assert retained["registry"].resolve_head(record["variant_id"], "main") is None


def test_retained_policy_binds_default_control_and_worker_capacity(retained):
    policy = retained["index"].artifacts.get(retained["record"].to_dict()["policy_cid"])
    assert policy["schema"] == parallel.POLICY_SCHEMA
    assert policy["parallel"] is True and policy["use_request_index"] is True
    assert policy["max_workers"] == policy["workers"] == policy["client_count"] == 2
    assert policy["worker_memory_mb"] == policy["control_memory_mb"] == 1024
    assert policy["total_memory_mb"] == 3072 and policy["cpu_slots"] == policy["child_process_slots"] == 3
    assert policy["reduction_order"] == "committed_source_client_order"
    assert all(value is False for value in policy["authority"].values())
    for observed in retained["probe"].observations:
        assert len(observed["root_reservations"]) == 1
        root = observed["root_reservations"][0]
        assert root["cpu_slots"] == root["child_process_slots"] == 3 and root["memory_mb"] == 3072
        assert set(observed["trainer_memory_mb"]) == {1024}


def test_historical_load_is_read_only_with_index_enabled_by_default(retained, monkeypatch):
    before = _artifacts_digest(retained)
    def forbidden(*args, **kwargs):
        pytest.fail("historical replay fitted, dispatched, scanned, or published")
    for owner, names in ((retained["dispatcher"], ("dispatch",)), (retained["queue"], ("list", "submit", "submit_once", "claim", "complete")),
                         (retained["artifacts"], ("put", "put_bytes")), (retained["index"].artifacts, ("put", "put_bytes")),
                         (retained["index"], ("prepare_current", "observe_current")), (source, ("_worker",))):
        for name in names:
            monkeypatch.setattr(owner, name, forbidden)
    result = _load(retained)
    assert result.to_dict() == retained["record"].to_dict() and result.observed_live is False
    assert _artifacts_digest(retained) == before


def test_missing_parallel_sidecar_requires_explicit_no_fit_recovery(retained, monkeypatch):
    record = retained["record"]
    path = retained["index"].artifacts.path_for(record.artifact_cid)
    original = path.read_bytes()
    path.unlink()
    def forbidden(*args, **kwargs):
        pytest.fail("parallel sidecar recovery fitted, dispatched, or scanned queue history")
    for item, name in ((source, "_worker"), (retained["dispatcher"], "dispatch"), (retained["queue"], "list")):
        monkeypatch.setattr(item, name, forbidden)
    try:
        with pytest.raises(FileNotFoundError):
            _load(retained)
        assert not path.exists()
        restored = parallel.recover_parallel_dispatched_codebase_round(retained["index"], retained["registry"],
            record.to_dict()["version_id"], queue=retained["queue"], artifacts=retained["artifacts"])
        assert restored.artifact_cid == record.artifact_cid and restored.observed_live is False
        assert path.read_bytes() == original
    finally:
        if not path.exists():
            path.write_bytes(original)


def test_same_operation_rejects_changed_execution_policy_without_new_work(retained, monkeypatch):
    before = retained["queue"].count()
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("changed policy fitted"))
    monkeypatch.setattr(retained["dispatcher"], "dispatch", lambda *a, **k: pytest.fail("changed policy dispatched"))
    with pytest.raises(RegistryError, match="operation|payload"):
        _train(retained, parallel=False)
    assert retained["queue"].count() == before


def _artifacts_digest(state):
    return {str(path.relative_to(state["root"])): hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in ("artifacts", "transfer-artifacts", "model-artifacts", "worker-receipts")
            for path in (state["root"] / folder).rglob("*") if path.is_file()}


def test_completed_retry_after_restart_uses_exact_index_beyond_history_cap(retained, monkeypatch):
    _close_state(retained)
    _open_state(retained)
    with retained["queue"]._conn_lock:
        connection = retained["queue"]._get_conn()
        for side, offset in (("older", 0.0), ("newer", 1e12)):
            connection.execute("""INSERT INTO tasks
                (task_id,task_type,model_name,payload_json,status,assigned_worker,
                 created_at,updated_at,result_json,error,priority,attempt,max_attempts,
                 next_attempt_at,lease_until,heartbeat_at,idempotency_key)
                SELECT ? || CAST(range AS VARCHAR), ?, 'unrelated', '{}',
                    'completed', 'unrelated', ?+range, ?+range, '{}', NULL,
                    5, 1, 3, 0, NULL, NULL, NULL FROM range(1001)""",
                ["unrelated:parallel:" + side + ":", TASK_TYPE, offset, offset])
    dispatch = retained["index"].artifacts.get(retained["record"].to_dict()["compatible_dispatch_record_cid"])
    ids = {item["task_id"] for item in dispatch["clients"]}
    listed = retained["queue"].list(status="completed", task_types=[TASK_TYPE], limit=10000)
    assert len(listed) == 1000 and not ids.intersection(item["task_id"] for item in listed)
    before = _artifacts_digest(retained)
    def forbidden(*args, **kwargs):
        pytest.fail("completed retry fitted, dispatched, or scanned queue history")
    monkeypatch.setattr(source, "_worker", forbidden)
    monkeypatch.setattr(retained["dispatcher"], "dispatch", forbidden)
    monkeypatch.setattr(retained["queue"], "list", forbidden)
    record = _train(retained)
    assert record.artifact_cid == retained["record"].artifact_cid
    assert record.observed_live is True and retained["worker"].numerical_invocations == 0
    assert _load(retained).to_dict() == retained["record"].to_dict()
    assert _artifacts_digest(retained) == before


def test_parallel_opt_out_runs_actual_workers_sequentially(retained):
    with NativeNumericalProbe(retained["scheduler"]).installed() as probe:
        record = _train(retained, operation_id="optout", parallel=False)
    probe.assert_cleaned()
    assert len(probe.processes) == 2 and probe.max_live_processes == probe.max_trainer_leases == 1
    assert federation.load_codebase_federated_training(retained["index"], retained["registry"], record.to_dict()["version_id"])


def test_three_clients_never_exceed_two_inflight_numerical_workers(retained):
    counts = []
    def observe_cohort(process, ordinal):
        counts.append(sum(row["status"] in {"queued", "running"}
                          for row in _cohort(retained, "bounded-three")))
    clients = [federation.CodebaseFederatedClient(name, (path,))
               for name, path in (("one", "a.py"), ("two", "b.py"), ("three", "c.py"))]
    with NativeNumericalProbe(retained["scheduler"], on_spawn=observe_cohort).installed() as probe:
        record = _train(retained, operation_id="bounded-three", clients=clients, max_workers=2)
    probe.assert_cleaned()
    assert len(probe.processes) == 3 and probe.max_live_processes == probe.max_trainer_leases == 2
    assert counts and max(counts) <= 2
    assert [item["work_binding"]["client_id"] for item in _saved(retained, record)["report"]["codebase_federation"]["clients"]] == ["one", "three", "two"]


@pytest.mark.parametrize("name,value", [("parallel", 1), ("parallel", None), ("max_workers", True),
    ("max_workers", 0), ("max_workers", 9), ("worker_memory_mb", True), ("worker_memory_mb", 511),
    ("control_memory_mb", 511), ("use_request_index", 1)])
def test_invalid_parallel_policies_refuse_without_queue_or_fit(retained, monkeypatch, name, value):
    before = retained["queue"].count()
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("invalid bounds fitted"))
    with pytest.raises((source.CodebaseFeatureTrainingError, TypeError, ValueError)):
        _train(retained, operation_id="invalid:" + name, **{name: value})
    assert retained["queue"].count() == before


def test_narrow_parent_bounds_refuse_before_any_worker_submission(retained, monkeypatch):
    before = retained["queue"].count()
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("over-bound lineage fitted"))
    with pytest.raises(source.CodebaseFeatureTrainingError, match="depth|ancestry"):
        _train(retained, operation_id="depth-refused", limits=replace(source.CodebaseFeatureTrainingLimits(), max_ancestry=1))
    assert retained["queue"].count() == before


def test_prospective_history_bound_refuses_before_run_fit_or_candidate(retained, monkeypatch):
    tasks, versions = retained["queue"].count(), _version_count(retained)
    monkeypatch.setattr(source, "_worker", lambda *a, **k: pytest.fail("prospective over-bound history fitted"))
    monkeypatch.setattr(retained["dispatcher"], "dispatch", lambda *a, **k: pytest.fail("prospective over-bound history dispatched"))
    with pytest.raises(source.CodebaseFeatureTrainingError, match="history"):
        _train(retained, operation_id="history-refused", limits=replace(source.CodebaseFeatureTrainingLimits(), max_training_history=5))
    with retained["registry"]._transaction() as connection:
        jobs = connection.execute("SELECT count(*) FROM autoencoder_control.runs WHERE run_id LIKE ?",
            ["codebase-dispatched-fed:parallel:history-refused:%"]).fetchone()[0]
    assert jobs == 0 and _version_count(retained) == versions
    assert retained["queue"].count() == tasks
    assert retained["scheduler"].snapshot()["active_lease_count"] == 0


def test_actual_parallel_cancellation_terminates_both_peers_before_return(retained):
    cancelled = threading.Event()
    before = _version_count(retained)
    def cancel_on_second(process, ordinal):
        if ordinal == 2:
            cancelled.set()
    with NativeNumericalProbe(retained["scheduler"], on_spawn=cancel_on_second).installed() as probe:
        with pytest.raises(Exception, match="cancel|incomplete|worker failed"):
            _train(retained, operation_id="actual-cancel", cancel_event=cancelled)
    probe.assert_cleaned()
    assert probe.max_live_processes == 2
    assert all(result.cancelled and result.process_tree_terminated for result in probe.results)
    _assert_failed(retained, "actual-cancel", before)
    assert all(row["status"] != "completed" for row in _cohort(retained, "actual-cancel"))


def test_worker_failure_cancels_and_joins_already_running_numerical_peer(retained, monkeypatch):
    before = _version_count(retained)
    original = source._worker
    probe = NativeNumericalProbe(retained["scheduler"])
    def failed(runtime, train, *args, **kwargs):
        if kwargs["action"] == "train" and len(train) == 1:
            assert probe.peer_started.wait(15), "peer numerical process did not start"
            raise RuntimeError("injected parallel client failure")
        return original(runtime, train, *args, **kwargs)
    monkeypatch.setattr(source, "_worker", failed)
    with probe.installed():
        with pytest.raises(Exception, match="injected parallel client failure|cancel"):
            _train(retained, operation_id="peer-failed")
    probe.assert_cleaned()
    assert len(probe.processes) == 1 and probe.results[0].cancelled and probe.results[0].process_tree_terminated
    _assert_failed(retained, "peer-failed", before)
    assert all(row["status"] != "completed" for row in _cohort(retained, "peer-failed"))


def test_source_change_during_real_fit_prevents_queue_or_model_completion(retained):
    before = _version_count(retained)
    path = retained["repository"] / "c.py"
    previous = path.read_bytes()
    def change_source(process, ordinal):
        if ordinal == 1:
            path.write_text("def step(n: int) -> int:\n    return n + 99\n")
    try:
        with NativeNumericalProbe(retained["scheduler"], on_spawn=change_source).installed() as probe:
            with pytest.raises(Exception, match="head|source|repository|changed|differs|cancel"):
                _train(retained, operation_id="changed-source")
        probe.assert_cleaned()
    finally:
        path.write_bytes(previous)
    _assert_failed(retained, "changed-source", before)
    assert all(row["status"] != "completed" for row in _cohort(retained, "changed-source"))


def test_reclaimed_native_round_fence_blocks_stale_parallel_completion(retained):
    before = _version_count(retained)
    replacement = []
    def replace_owner(process, ordinal):
        if ordinal == 1:
            run = _run(retained, "stale-fence")
            retained["registry"].fail_run("test:revoke-native-parallel", run["lease"], {"admitted": False})
            newer = retained["registry"].claim_run("test:replacement-native-parallel", run["run_id"], "replacement-owner")["lease"]
            assert newer["fence"] > run["lease"]["fence"]
            replacement.append(newer)
    try:
        with NativeNumericalProbe(retained["scheduler"], on_spawn=replace_owner).installed() as probe:
            with pytest.raises(Exception, match="stale|lease|fence|cancel"):
                _train(retained, operation_id="stale-fence")
        probe.assert_cleaned()
        assert replacement and _run(retained, "stale-fence")["lease"] == replacement[0]
        assert retained["registry"].get_run_completion(_run(retained, "stale-fence")["run_id"]) is None
        assert _version_count(retained) == before
        assert all(row["status"] != "completed" for row in _cohort(retained, "stale-fence"))
        assert retained["scheduler"].snapshot()["active_lease_count"] == 0
    finally:
        if replacement:
            retained["registry"].fail_run("test:replacement-parallel-cleanup", replacement[0], {"admitted": False})


def test_pre_cancelled_parallel_round_never_submits_artifact_work(retained):
    cancelled = threading.Event()
    cancelled.set()
    before = retained["queue"].count()
    with pytest.raises(schedulers.LeaseCancelledError):
        _train(retained, operation_id="pre-cancelled", cancel_event=cancelled)
    assert retained["queue"].count() == before
