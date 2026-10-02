"""Actual numerical lifecycle through the live default-host parent envelope."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_training_lifecycle as lifecycle
from ipfs_datasets_py.logic.software_contracts import codebase_training_corpus as corpus
from ipfs_datasets_py.logic.software_contracts import codebase_source_384 as source384
from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RUN_LIFECYCLE_SCHEMA, RegistryError
from ipfs_accelerate_py.agent_supervisor.runtime import repository_resource_bridge as bridge
from ipfs_accelerate_py.agent_supervisor.runtime.resource_scheduler import ResourceScheduler, ResourcePolicy


def index_connection(root):
    import duckdb
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
    from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    connection = duckdb.connect(str(root / "source.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    store, artifacts = DuckDBASTStore(connection=connection), ImmutableCAS(root / "cas")
    return connection, RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
                                             catalog=CodebaseCatalog(store, artifacts))


@contextmanager
def envelope(current, concurrent=1):
    local = ResourceScheduler(ResourcePolicy(max_lanes=8))
    with bridge.RepositoryResourceBridge(local).reserve(repository_id="lifecycle-real",
        workspace=current.root, budget=bridge.RepositoryResourceBudget(cpu_slots=concurrent,
            memory_mb=4096*concurrent, process_slots=concurrent, disk_bytes=512*1024**2,
            wall_time_ms=120000)) as parent:
        yield parent
        current.receipts.append(parent.receipt())
    assert parent.receipt()["closed"] and not local.active_leases
    current.receipts.append(parent.receipt())


@pytest.fixture(scope="module")
def current(tmp_path_factory):
    checkpoint = os.environ.get("CODEBASE384_CHECKPOINT")
    if not checkpoint:
        pytest.skip("explicit real shared checkpoint and local embedding snapshot required")
    root = tmp_path_factory.mktemp("lifecycle384")
    repo = root / "repo"; repo.mkdir()
    for arguments in (("init", "-q"), ("config", "user.name", "Fixture"),
                      ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", "-C", str(repo), *arguments], check=True)
    selections = []
    for role, operators in (("train", ("+", "-", "*")), ("validation", ("<", "<=", ">")),
                            ("holdout", (">=", "==", "!="))):
        for i, operator in enumerate(operators):
            path = f"{role}_{i}.py"
            sort = "int" if role == "train" else "bool"
            (repo/path).write_text(f"def calculate(capacity: int, threshold: int) -> {sort}:\n    return capacity {operator} threshold\n")
            selections.append(dict(path=path, role=role, group_id=path))
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "strict operator cohort"], check=True)
    connection, index = index_connection(root)
    registry = AutoencoderRegistry(root/"models.duckdb", root/"models")
    value = SimpleNamespace(root=root, repo=repo, index=index, connection=connection,
        registry=registry, selections=selections, receipts=[], results=[])
    with envelope(value) as parent:
        with parent.phase(bridge.RepositoryPhaseDemand("scan", memory_mb=4096)) as phase:
            value.head = index.prepare_current(repo, repository_id="repository:lifecycle384",
                operation_id="capture", expected_head=None, **phase.native_options()).head
        with parent.phase(bridge.RepositoryPhaseDemand("semantic_index", memory_mb=4096)):
            value.frozen = corpus.freeze_corpus(index, expected_head=value.head, selections=selections)
            path = Path(checkpoint)
            value.parent = source384.register_shared_parent(registry, checkpoint_path=path,
                expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            value.variant = registry.get_version(value.parent)["variant_id"]
            registry.initialize_head("initialize-main", value.variant, "main", value.parent)
            value.model_head = registry.resolve_head(value.variant, "main")
    try:
        yield value
    finally:
        (root/"qualification.json").write_bytes(source384._raw(dict(results=value.results,
            envelopes=value.receipts, model_head=value.registry.resolve_head(value.variant, "main"),
            expected_parent_head=value.model_head, parent_retained=value.registry.resolve_head(value.variant,"main")==value.model_head,
            model_provider_calls=0, training_profile=source384.PROFILE)))
        value.registry.close(); connection.close()


def prepare(current, operation, **policy_changes):
    policy = dict(schema=RUN_LIFECYCLE_SCHEMA, max_attempts=1, wall_time_seconds=100.,
        memory_bytes=4096*1024**2, max_input_bytes=32*1024**2, max_samples=9,
        optimizer_steps=0, head_refits=1, max_checkpoint_bytes=32*1024**2,
        expected_head=deepcopy(current.model_head))
    policy.update(policy_changes)
    return lifecycle.prepare_job(current.index, current.repo, expected_head=current.head,
        frozen_corpus=current.frozen, registry=current.registry, parent_version_id=current.parent,
        branch="main", expected_model_head=current.model_head, operation_id=operation,
        embedding_snapshot=os.environ["CODEBASE384_EMBEDDING_SNAPSHOT"], policy=policy)


def execute(current, parent, job):
    with parent.phase(bridge.RepositoryPhaseDemand("training", memory_mb=4096)) as phase:
        result = lifecycle.execute_job(job, **phase.native_options())
    current.results.append(result)
    return result


def worker_pids():
    import psutil
    result = set()
    for child in psutil.Process().children(recursive=True):
        try:
            if any("codebase_source_384_worker.py" in part for part in child.cmdline()):
                result.add(child.pid)
        except psutil.NoSuchProcess:
            pass
    return result


def wait_worker(future, prior):
    end = time.monotonic()+30
    while time.monotonic() < end:
        pids = worker_pids()-prior
        if pids:
            return pids
        if future.done():
            pytest.fail("child returned before live cancellation: " + repr(future.result()))
        time.sleep(.025)
    pytest.fail("actual numerical subprocess did not start")


def test_actual_fit_lost_finish_reply_replays_without_training_and_retains_parent(current, monkeypatch):
    job = prepare(current, "lost-finish-reply")
    receipt = lifecycle._receipt
    def lose_reply(registry, operation, command, payload, result):
        saved = receipt(registry, operation, command, payload, result)
        if command == "FinishCodebaseTrainingJob":
            raise OSError("injected lost durable finish reply")
        return saved
    with envelope(current) as parent:
        with monkeypatch.context() as patch:
            patch.setattr(lifecycle, "_receipt", lose_reply)
            with pytest.raises(OSError, match="lost durable"):
                execute(current, parent, job)
        def no_fit(*a, **k):
            pytest.fail("read/replay tried to train")
        with monkeypatch.context() as patch:
            patch.setattr(source384, "train_current_source384", no_fit)
            assert lifecycle.inspect_job(job)["status"] == "completed"
            result = execute(current, parent, job)
    assert result["historical_replay"] and not result["training_executed"]
    assert not result["current_source_verified"]
    assert result["evaluation"]["parent_holdout"]["exact_targets"] == 3
    assert result["evaluation"]["child_holdout"]["exact_targets"] == 0
    assert current.registry.get_run(job.to_dict()["native_run_id"])["attempt"] == 1
    assert current.registry.resolve_head(current.variant, "main") == current.model_head
    current.completed_job = job


def test_actual_live_numerical_subprocess_is_cancelled_and_reaped(current):
    job = prepare(current, "cancel-live-child")
    prior = worker_pids()
    with envelope(current) as parent, ThreadPoolExecutor(max_workers=1) as workers:
        future = workers.submit(execute, current, parent, job)
        pids = wait_worker(future, prior)
        before = current.registry.get_run(job.to_dict()["native_run_id"])
        started = time.monotonic()
        stopped = lifecycle.terminate_job(job, reason="live cancellation qualification")
        result = future.result(timeout=20)
    assert stopped["status"] == result["status"] == "cancelled"
    assert result["bounded_child_returned"] and time.monotonic()-started < 20
    assert not pids & worker_pids()
    assert stopped["fence"] == before["fence"]+1
    with pytest.raises(RegistryError, match="terminal"):
        current.registry.claim_run("stale-reclaim", job.to_dict()["native_run_id"], "stale", lease_seconds=10)
    current.results.append(dict(actual_child_pids_count=len(pids), actual_child_reaped=True,
        terminal_status=result["status"], bounded_return_seconds=time.monotonic()-started))


def test_actual_source_change_supersedes_running_child_without_model_attachment(current):
    job = prepare(current, "supersede-live-source")
    path = current.repo/"train_0.py"; original = path.read_bytes()
    prior = worker_pids()
    try:
        with envelope(current) as parent, ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(execute, current, parent, job)
            pids = wait_worker(future, prior)
            path.write_text(original.decode().replace(" + ", " - "))
            result = future.result(timeout=40)
        assert result["status"] == "superseded" and result["bounded_child_returned"]
        assert not pids & worker_pids()
        assert current.registry.get_run_completion(job.to_dict()["native_run_id"]) is None
        assert current.registry.resolve_head(current.variant, "main") == current.model_head
    finally:
        path.write_bytes(original)


def test_two_actual_concurrent_children_share_parent_and_preserve_head(current):
    connection, index = index_connection(current.root)
    second = SimpleNamespace(**vars(current))
    second.index, second.connection = index, connection
    second.frozen = corpus.freeze_corpus(index, expected_head=current.head, selections=current.selections)
    jobs = [prepare(current, "concurrent-a"), prepare(second, "concurrent-b")]
    overlap = False
    try:
        with envelope(current, concurrent=2) as parent, ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(execute, item, parent, job) for item,job in zip((current,second),jobs)]
            while not all(future.done() for future in futures):
                overlap |= len(worker_pids()) >= 2
                time.sleep(.03)
            results = [future.result() for future in futures]
        assert overlap, "two actual numerical subprocesses must overlap"
        assert all(r["status"] == "completed" and r["training_executed"] for r in results)
        assert len({r["native_run_id"] for r in results}) == 2
        assert len({r["numerical_child_version_id"] for r in results}) == 2
        assert current.registry.resolve_head(current.variant, "main") == current.model_head
        current.results.append(dict(actual_concurrent_children=2, observed_subprocess_overlap=overlap,
                                    parent_head_retained=True))
    finally:
        connection.close()


@pytest.mark.parametrize("change,match", [(dict(max_samples=3), "sample budget"),
    (dict(max_input_bytes=1), "input byte budget"), (dict(optimizer_steps=1), "optimizer"),
    (dict(head_refits=2), "head_refits")])
def test_budget_refusal_happens_before_new_run_or_fit(current, change, match):
    with pytest.raises((ValueError, RegistryError), match=match):
        prepare(current, "invalid-budget", **change)


def test_cooperative_prelaunch_cancellation_does_not_create_numerical_child(current):
    import threading
    job = prepare(current, "cancel-before-fit")
    signal = threading.Event(); signal.set()
    result = lifecycle.execute_job(job, cancel_event=signal)
    assert result["status"] == "cancelled" and result["attempt"] == 0
    assert current.registry.get_run_completion(job.to_dict()["native_run_id"]) is None
    current.results.append(result)


def test_actual_wall_deadline_cancels_and_fences_the_numerical_attempt(current):
    job = prepare(current, "deadline-live-child", wall_time_seconds=3.)
    started = time.monotonic()
    with envelope(current) as parent:
        result = execute(current, parent, job)
    assert result["status"] == "cancelled"
    assert result["terminal"]["reason"] == "wall-time budget expired"
    assert time.monotonic()-started < 20
    assert current.registry.get_run_completion(job.to_dict()["native_run_id"]) is None


def test_actual_checkpoint_budget_refuses_candidate_and_retry_budget_refuses_reclaim(current):
    job = prepare(current, "checkpoint-byte-cap", max_checkpoint_bytes=1)
    with envelope(current) as parent:
        with pytest.raises(RegistryError, match="checkpoint.*budget"):
            execute(current, parent, job)
    run = current.registry.get_run(job.to_dict()["native_run_id"])
    assert run["status"] == "failed" and run["attempt"] == 1
    assert current.registry.get_run_completion(run["run_id"]) is None
    with pytest.raises(RegistryError, match="attempt budget"):
        current.registry.claim_run("retry-after-checkpoint-cap", run["run_id"], "stale-retry", lease_seconds=10)
    current.results.append(dict(native_run_id=run["run_id"], checkpoint_byte_budget_refused=True,
        retry_budget_refused=True, status=run["status"], candidate_attached=False))


def test_phase_memory_mismatch_refuses_before_fit(current):
    job = prepare(current, "wrong-memory")
    with pytest.raises(ValueError, match="memory reservations must match"):
        lifecycle.execute_job(job, memory_mb=2048)
    assert lifecycle.inspect_job(job)["attempt"] == 0
    lifecycle.terminate_job(job, reason="unused invalid phase qualification")


def test_completed_job_reconstructed_after_native_owner_restart_has_read_only_replay(current, monkeypatch):
    current.registry.close()
    current.registry = AutoencoderRegistry(current.root/"models.duckdb", current.root/"models")
    job = prepare(current, "lost-finish-reply")
    def no_fit(*a, **k):
        pytest.fail("native restart replay attempted fitting")
    with monkeypatch.context() as patch:
        patch.setattr(source384, "train_current_source384", no_fit)
        result = lifecycle.execute_job(job)
    assert result["status"] == "completed" and result["historical_replay"]
    assert not result["training_executed"] and not result["current_source_verified"]
    assert lifecycle.inspect_job(job)["attempt"] == 1
    current.results.append(result)
