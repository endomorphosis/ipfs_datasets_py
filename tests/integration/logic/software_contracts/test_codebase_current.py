"""Native adversarial qualification of durable structural heads and source fences."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_ir as module
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, StaleCodebaseError
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

VIEW = "repository:current-head-fixture"


def git(repository, *arguments):
    return subprocess.check_output(["git", "-C", str(repository), *arguments], text=True).strip()


@pytest.fixture
def repository(tmp_path):
    path = tmp_path / "source"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "Current Head Fixture")
    git(path, "config", "user.email", "fixture@example.invalid")
    (path / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 1\n")
    (path / "other.py").write_text("def unchanged():\n    return True\n")
    git(path, "add", ".")
    git(path, "commit", "-qm", "fixture")
    return path


@pytest.fixture
def scheduler(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192)
    pressure = [healthy]
    config = schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "admission.json", proof_resource_sampler=lambda: pressure[0],
        lane_reservations={}, auto_renew_leases=False,
        proof_backoff_seconds=0.02, poll_interval_seconds=0.005,
    )
    owner = schedulers.GlobalResourceScheduler(config)
    yield owner, pressure, healthy
    state = owner.snapshot()
    assert state["active_lease_count"] == state["waiting_request_count"] == 0


@pytest.fixture
def current_index(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    database = tmp_path / "current.duckdb"
    connection = duckdb.connect(str(database), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(tmp_path / "artifacts")
    ingestor = DuckDBASTIngestor(store=store)
    index = RepositoryCodebaseIndex(ingestor=ingestor, artifacts=artifacts,
                                   catalog=CodebaseCatalog(store, artifacts))
    yield index, connection, database
    connection.close()


def publish(index, repository, owner, operation, expected=None):
    return index.prepare_current(repository, repository_id=VIEW, operation_id=operation,
                                 expected_head=expected, scheduler=owner)


def rows(connection):
    tables = connection.execute(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_schema IN ('main', 'codebase_control') ORDER BY table_schema, table_name"
    ).fetchall()
    def quoted(value):
        return '"' + value.replace('"', '""') + '"'
    return {(schema, table): sorted(connection.execute(
        "SELECT * FROM " + quoted(schema) + "." + quoted(table)).fetchall(), key=repr)
        for schema, table in tables}


def change(repository, number=2):
    (repository / "counter.py").write_text(f"def increment(n: int) -> int:\n    return n + {number}\n")


def test_durable_current_head_and_observation_replay_in_fresh_process(repository, current_index, scheduler, tmp_path):
    index, connection, database = current_index
    owner, _, _ = scheduler
    receipt = publish(index, repository, owner, "initial")
    observation = index.observe_current(repository, expected_head=receipt.head, scheduler=owner)
    expected_ast = index.lookup(observation.manifest, "counter.py").ast_cid
    connection.close()
    script = '''
import json, sys
from pathlib import Path
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.python_frontend import PythonASTExtractor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources

def forbidden(*args, **kwargs):
    raise AssertionError("observation unexpectedly parsed source")
PythonASTExtractor.extract_from_source = forbidden
connection = duckdb.connect(sys.argv[1], config={'threads': 1, 'memory_limit': '64MB'})
store = DuckDBASTStore(connection=connection)
artifacts = ImmutableCAS(sys.argv[2])
index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts, catalog=CodebaseCatalog(store, artifacts))
owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(state_path=Path(sys.argv[4])/'child-admission.json', proof_resource_sampler=lambda: ProofHostResources(8,8192,8192), lane_reservations={}, auto_renew_leases=False))
head = index.current(sys.argv[5])
observation = index.observe_current(sys.argv[3], expected_head=head, scheduler=owner)
print(json.dumps({'generation': head.generation, 'manifest_cid': observation.manifest.cid, 'ast_cid': index.lookup(observation.manifest, 'counter.py').ast_cid, 'receipt_cid': head.receipt_cid, 'leases': owner.snapshot()['active_lease_count']}))
connection.close()
'''
    run = subprocess.run([sys.executable, "-c", script, str(database), str(tmp_path / "artifacts"),
                          str(repository), str(tmp_path), VIEW], capture_output=True, text=True,
                         timeout=45, env=dict(os.environ))
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout.splitlines()[-1]) == {
        "generation": receipt.head.generation, "manifest_cid": receipt.head.manifest_cid,
        "ast_cid": expected_ast, "receipt_cid": receipt.head.receipt_cid, "leases": 0,
    }


@pytest.mark.parametrize("mutation", ["edit", "untracked", "delete", "staged"])
def test_same_git_head_does_not_make_changed_source_current(repository, current_index, scheduler, mutation):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    receipt = publish(index, repository, owner, "initial")
    commit = git(repository, "rev-parse", "HEAD")
    before = rows(connection)
    if mutation == "edit":
        change(repository)
    elif mutation == "untracked":
        (repository / "new.py").write_text("def new_function():\n    return 3\n")
    elif mutation == "delete":
        (repository / "counter.py").unlink()
    else:
        change(repository)
        git(repository, "add", "counter.py")
    assert git(repository, "rev-parse", "HEAD") == commit
    with pytest.raises(StaleCodebaseError, match="repository differs"):
        index.observe_current(repository, expected_head=receipt.head, scheduler=owner)
    assert index.current(VIEW) == receipt.head
    assert rows(connection) == before


def test_exact_old_operation_retry_is_historical_and_cannot_restore_old_active_asts(repository, current_index, scheduler):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    old_manifest = index.load(first.head.manifest_cid)
    change(repository)
    second = publish(index, repository, owner, "second", first.head)
    latest_manifest = index.load(second.head.manifest_cid)
    git(repository, "checkout", "--", "counter.py")
    before = rows(connection)
    replay = publish(index, repository, owner, "first")
    assert replay == first
    assert index.current(VIEW) == second.head
    assert rows(connection) == before
    assert index.lookup(latest_manifest, "counter.py") is not None
    with pytest.raises(module.CodebaseIRError, match="missing or invalidated"):
        index.lookup(old_manifest, "counter.py")
    with pytest.raises(StaleCodebaseError, match="catalog head"):
        index.observe_current(repository, expected_head=replay.head, scheduler=owner)
    # A later legitimate publication still compares against the durable head,
    # regardless of the ingestor's local history after the historical replay.
    change(repository, 3)
    third = publish(index, repository, owner, "third", second.head)
    assert third.head.generation == second.head.generation + 1
    assert index.observe_current(repository, expected_head=third.head, scheduler=owner).manifest.cid == third.head.manifest_cid


def test_stale_expected_head_and_reused_operation_leave_successor_untouched(repository, current_index, scheduler):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHeadConflict, CodebaseOperationConflict
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    change(repository)
    second = publish(index, repository, owner, "second", first.head)
    change(repository, 3)
    before = rows(connection)
    with pytest.raises(CodebaseHeadConflict):
        publish(index, repository, owner, "stale", first.head)
    with pytest.raises(CodebaseOperationConflict):
        publish(index, repository, owner, "second", second.head)
    assert rows(connection) == before
    assert index.current(VIEW) == second.head


def test_same_snapshot_new_operation_keeps_active_projections(repository, current_index, scheduler):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    second = publish(index, repository, owner, "new-operation", first.head)
    assert second.head.generation == first.head.generation + 1
    assert second.head.snapshot_cid == first.head.snapshot_cid
    assert second.head.ast_revision_id == first.head.ast_revision_id
    observation = index.observe_current(repository, expected_head=second.head, scheduler=owner)
    assert index.lookup(observation.manifest, "counter.py") is not None
    before = rows(connection)
    assert publish(index, repository, owner, "new-operation", first.head) == second
    assert rows(connection) == before


def test_restoring_source_does_not_restore_old_generation_authority(repository, current_index, scheduler):
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHeadConflict
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    change(repository)
    second = publish(index, repository, owner, "second", first.head)
    git(repository, "checkout", "--", "counter.py")
    restored = publish(index, repository, owner, "restored", second.head)
    assert restored.head.generation == first.head.generation + 2
    assert restored.head.snapshot_cid == first.head.snapshot_cid
    assert restored.head.ast_revision_id == first.head.ast_revision_id
    assert restored.head.receipt_cid != first.head.receipt_cid
    assert index.observe_current(repository, expected_head=restored.head,
                                 scheduler=owner).manifest.cid == restored.head.manifest_cid
    before = rows(connection)
    with pytest.raises(StaleCodebaseError, match="catalog head"):
        index.observe_current(repository, expected_head=first.head, scheduler=owner)
    with pytest.raises(CodebaseHeadConflict):
        publish(index, repository, owner, "stale-after-restore", first.head)
    assert index.current(VIEW) == restored.head
    assert rows(connection) == before


def test_distinct_worktree_views_keep_independent_current_asts(repository, current_index, scheduler, tmp_path):
    index, _, _ = current_index
    owner, _, _ = scheduler
    second_tree = tmp_path / "second-worktree"
    git(repository, "worktree", "add", "--detach", str(second_tree), "HEAD")
    first = publish(index, repository, owner, "first")
    second_view = VIEW + ":second-worktree"
    second = index.prepare_current(second_tree, repository_id=second_view,
                                   operation_id="second-view", expected_head=None, scheduler=owner)
    assert first.head.repository_id != second.head.repository_id
    assert first.head.ast_revision_id != second.head.ast_revision_id
    change(repository)
    changed = publish(index, repository, owner, "first-view-edit", first.head)
    assert index.current(VIEW) == changed.head
    assert index.current(second_view) == second.head
    untouched = index.observe_current(second_tree, expected_head=second.head, scheduler=owner)
    assert index.lookup(untouched.manifest, "counter.py") is not None
    updated = index.observe_current(repository, expected_head=changed.head, scheduler=owner)
    assert index.lookup(updated.manifest, "counter.py").ast_cid != index.lookup(untouched.manifest, "counter.py").ast_cid


def test_sql_failure_rolls_back_head_receipt_and_all_ast_rows(repository, current_index, scheduler, monkeypatch):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    original = index.ingestor.store._persist_projection
    change(repository)
    before = rows(connection)
    def fail_after_write(projection):
        original(projection)
        raise OSError("injected SQL publication fault")
    monkeypatch.setattr(index.ingestor.store, "_persist_projection", fail_after_write)
    with pytest.raises(OSError, match="publication fault"):
        publish(index, repository, owner, "second", first.head)
    assert rows(connection) == before
    assert index.current(VIEW) == first.head
    assert index.lookup(index.load(first.head.manifest_cid), "counter.py") is not None
    monkeypatch.setattr(index.ingestor.store, "_persist_projection", original)
    recovered = publish(index, repository, owner, "second", first.head)
    assert recovered.head.generation == first.head.generation + 1


def test_failure_after_head_and_receipt_writes_rolls_back_every_table(repository, current_index, scheduler, monkeypatch):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    original = index.ingestor.store.apply_batch
    change(repository)
    before = rows(connection)
    saw_candidate_head = []
    def fail_after_catalog_writes(projections, invalidations=(), **hooks):
        commit_hook = hooks["before_commit"]
        def reject_commit(cx):
            commit_hook(cx)
            saw_candidate_head.extend(cx.execute(
                "SELECT generation FROM codebase_control.heads WHERE repository_id=?", [VIEW]
            ).fetchone())
            assert cx.execute("SELECT count(*) FROM codebase_control.operations").fetchone()[0] == 2
            raise OSError("injected post-head-write fault")
        hooks["before_commit"] = reject_commit
        return original(projections, invalidations, **hooks)
    monkeypatch.setattr(index.ingestor.store, "apply_batch", fail_after_catalog_writes)
    with pytest.raises(OSError, match="post-head-write fault"):
        publish(index, repository, owner, "second", first.head)
    assert saw_candidate_head == [first.head.generation + 1]
    assert rows(connection) == before
    assert index.current(VIEW) == first.head
    assert index.lookup(index.load(first.head.manifest_cid), "counter.py") is not None
    monkeypatch.setattr(index.ingestor.store, "apply_batch", original)
    recovered = publish(index, repository, owner, "second", first.head)
    assert recovered.head.generation == first.head.generation + 1


def test_cancellation_after_ast_write_rolls_back_before_head_commit(repository, current_index, scheduler, monkeypatch):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    original = index.ingestor.store._persist_projection
    change(repository)
    cancelled = threading.Event()
    before = rows(connection)
    def write_then_cancel(projection):
        original(projection)
        cancelled.set()
    monkeypatch.setattr(index.ingestor.store, "_persist_projection", write_then_cancel)
    with pytest.raises(schedulers.LeaseCancelledError):
        index.prepare_current(repository, repository_id=VIEW, operation_id="second",
                              expected_head=first.head, scheduler=owner, cancel_event=cancelled)
    assert rows(connection) == before
    assert index.current(VIEW) == first.head
    assert index.lookup(index.load(first.head.manifest_cid), "counter.py") is not None


def test_post_commit_cancellation_recovers_exact_operation_without_republishing(repository, current_index, scheduler, monkeypatch):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    change(repository)
    cancelled = threading.Event()
    original = index.ingestor.store.apply_batch
    commits = []
    def commit_then_lose_response(*args, **kwargs):
        result = original(*args, **kwargs)
        commits.append(True)
        cancelled.set()
        return result
    monkeypatch.setattr(index.ingestor.store, "apply_batch", commit_then_lose_response)
    with pytest.raises(schedulers.LeaseCancelledError):
        index.prepare_current(repository, repository_id=VIEW, operation_id="second",
                              expected_head=first.head, scheduler=owner, cancel_event=cancelled)
    durable = index.current(VIEW)
    assert durable.generation == first.head.generation + 1
    assert durable.snapshot_cid != first.head.snapshot_cid
    assert connection.execute(
        "SELECT receipt_cid FROM codebase_control.operations WHERE operation_id='second'"
    ).fetchone() == (durable.receipt_cid,)
    assert connection.execute("SELECT count(*) FROM codebase_control.operations").fetchone()[0] == 2
    before = rows(connection)
    # A fresh signal and the original expected head resolve the already committed
    # operation. A second apply_batch would both change this counter and cancel.
    cancelled.clear()
    recovered = index.prepare_current(repository, repository_id=VIEW, operation_id="second",
                                      expected_head=first.head, scheduler=owner, cancel_event=cancelled)
    assert recovered.head == durable
    assert recovered.cid == durable.receipt_cid
    assert commits == [True]
    assert rows(connection) == before
    assert index.observe_current(repository, expected_head=durable, scheduler=owner).head == durable


@pytest.mark.parametrize("artifact", ["manifest", "source", "active_ast"])
def test_observation_rejects_corrupted_evidence_without_mutation(repository, current_index, scheduler, artifact):
    from ipfs_datasets_py.logic.software_contracts.cache import CacheIntegrityError
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStoreIntegrityError
    index, connection, _ = current_index
    owner, _, _ = scheduler
    receipt = publish(index, repository, owner, "first")
    manifest = index.load(receipt.head.manifest_cid)
    entry = next(item for item in manifest.snapshot.entries if item.path == "counter.py")
    if artifact == "manifest":
        index.artifacts.path_for(manifest.cid).write_bytes(b"{}")
        expected_error = CacheIntegrityError
    elif artifact == "source":
        index.artifacts.path_for(entry.source_cid, source=True).write_bytes(b"corrupted source bytes")
        expected_error = CacheIntegrityError
    else:
        projection = index.lookup(manifest, entry.path)
        other = next(item for item in manifest.snapshot.entries if item.path == "other.py")
        connection.execute("UPDATE ast_blobs SET source_cid=? WHERE ast_cid=?",
                           [other.source_cid, projection.ast_cid])
        expected_error = DuckDBASTStoreIntegrityError
    before = rows(connection)
    with pytest.raises(expected_error):
        index.observe_current(repository, expected_head=receipt.head, scheduler=owner)
    assert index.current(VIEW) == receipt.head
    assert rows(connection) == before


def test_cancellation_during_manifest_sealing_does_not_advance_head(repository, current_index, scheduler, monkeypatch):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    change(repository)
    cancelled = threading.Event()
    original = index.artifacts.put
    before = rows(connection)
    def seal_then_cancel(value):
        result = original(value)
        if value.get("schema") == module.CODEBASE_IR_SCHEMA:
            cancelled.set()
        return result
    monkeypatch.setattr(index.artifacts, "put", seal_then_cancel)
    with pytest.raises(schedulers.LeaseCancelledError):
        index.prepare_current(repository, repository_id=VIEW, operation_id="second",
                              expected_head=first.head, scheduler=owner, cancel_event=cancelled)
    assert rows(connection) == before
    assert index.current(VIEW) == first.head


def test_source_edit_after_extraction_is_rejected_before_atomic_publication(repository, current_index, scheduler, monkeypatch):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    change(repository)
    original = index.artifacts.put
    before = rows(connection)
    def edit_while_sealing(value):
        result = original(value)
        if value.get("schema") == module.CODEBASE_IR_SCHEMA:
            change(repository, 3)
        return result
    monkeypatch.setattr(index.artifacts, "put", edit_while_sealing)
    with pytest.raises(StaleCodebaseError, match="before head publication"):
        publish(index, repository, owner, "second", first.head)
    assert rows(connection) == before
    assert index.current(VIEW) == first.head


def test_pressure_blocks_observation_before_source_read(repository, current_index, scheduler, monkeypatch):
    index, connection, _ = current_index
    owner, pressure, healthy = scheduler
    first = publish(index, repository, owner, "first")
    before = rows(connection)
    pressure[0] = replace(healthy, memory_stall_percent=10)
    def forbidden(*args, **kwargs):
        pytest.fail("observation captured source while host pressure denied admission")
    monkeypatch.setattr(module, "snapshot_repository", forbidden)
    with pytest.raises(schedulers.LeaseTimeoutError):
        index.observe_current(repository, expected_head=first.head, scheduler=owner,
                              admission_timeout_seconds=0.01)
    assert rows(connection) == before


def test_observation_checks_cancellation_after_snapshot(repository, current_index, scheduler, monkeypatch):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    first = publish(index, repository, owner, "first")
    before = rows(connection)
    original = module.snapshot_repository
    cancelled = threading.Event()
    def cancel_after_capture(*args, **kwargs):
        result = original(*args, **kwargs)
        cancelled.set()
        return result
    monkeypatch.setattr(module, "snapshot_repository", cancel_after_capture)
    with pytest.raises(schedulers.LeaseCancelledError):
        index.observe_current(repository, expected_head=first.head, scheduler=owner, cancel_event=cancelled)
    assert rows(connection) == before


def test_observation_batches_sql_without_omitting_cas_or_provenance(repository, current_index, scheduler, monkeypatch):
    index, connection, _ = current_index
    owner, _, _ = scheduler
    for number in range(33):
        (repository / f"extra{number:02}.py").write_text(f"def value():\n    return {number}\n")
    head = publish(index, repository, owner, "batch-inventory").head
    before = rows(connection)
    store = index.ingestor.store
    batch, identities, provenance = store.get_many_by_ast_cid, store.require_active_identities, index.load_ast_artifact
    sizes, fenced, paths = [], [], []

    def read_many(cids, **kwargs):
        sizes.append(len(cids))
        return batch(cids, **kwargs)

    def fence(projections, **kwargs):
        fenced.append(len(projections))
        return identities(projections, **kwargs)

    def read_artifact(manifest, path):
        paths.append(path)
        return provenance(manifest, path)

    monkeypatch.setattr(store, "get_many_by_ast_cid", read_many)
    monkeypatch.setattr(store, "require_active_identities", fence)
    monkeypatch.setattr(index, "load_ast_artifact", read_artifact)
    observed = index.observe_current(repository, expected_head=head, scheduler=owner)
    assert sizes == fenced == [32, 3]
    assert paths == [entry.path for entry in observed.manifest.snapshot.entries]
    assert rows(connection) == before


def test_observation_splits_oversized_batches_before_loading_next_part(repository, current_index, scheduler, monkeypatch):
    from ipfs_datasets_py.logic.software_contracts import duckdb_ast_store as ast_store

    index, connection, _ = current_index
    owner, _, _ = scheduler
    head = publish(index, repository, owner, "split-inventory").head
    before = rows(connection)
    store = index.ingestor.store
    batch, fence = store.get_many_by_ast_cid, store.require_active_identities
    calls = []

    def read_many(cids, **kwargs):
        calls.append(("read", len(cids)))
        return batch(cids, **kwargs)

    def require_active(projections, **kwargs):
        calls.append(("fence", len(projections)))
        return fence(projections, **kwargs)

    # Both source ASTs fit individually, but their combined payload does not.
    sizes = connection.execute("SELECT octet_length(encode(payload_json)) FROM ast_blobs").fetchall()
    assert len(sizes) == 2
    monkeypatch.setattr(ast_store, "MAX_BATCH_PAYLOAD_BYTES", max(row[0] for row in sizes))
    monkeypatch.setattr(store, "get_many_by_ast_cid", read_many)
    monkeypatch.setattr(store, "require_active_identities", require_active)
    assert index.observe_current(repository, expected_head=head, scheduler=owner).head == head
    assert calls == [("read", 2), ("read", 1), ("fence", 1), ("read", 1), ("fence", 1)]
    assert rows(connection) == before


def test_observation_rejects_invalidation_during_chunk_cas_reads(repository, current_index, scheduler, monkeypatch):
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStoreIntegrityError

    index, _, _ = current_index
    owner, _, _ = scheduler
    head = publish(index, repository, owner, "cas-race").head
    selected = index.lookup(index.load(head.manifest_cid), "counter.py")
    original = index.load_ast_artifact

    def invalidate_after_read(manifest, path):
        record = original(manifest, path)
        if path == "counter.py":
            index.ingestor.store.invalidate(blob_id=selected.blob_id, reason="manual")
        return record

    monkeypatch.setattr(index, "load_ast_artifact", invalidate_after_read)
    with pytest.raises(DuckDBASTStoreIntegrityError, match="no longer active"):
        index.observe_current(repository, expected_head=head, scheduler=owner)
    assert index.current(VIEW) == head


@pytest.mark.parametrize('profile,explicit,work,expected', [
    (None, None, 120, 30), ('local-benchmark@1', None, 120, 90),
    ('local-benchmark@1', 0, 120, 0), ('local-benchmark@1', .01, 120, .01),
    ('local-benchmark@1', None, 7, 7),
])
def test_profile_admission_defaults_reach_prepare_and_observe_without_expanding_work(
    repository, current_index, scheduler, monkeypatch, profile, explicit, work, expected,
):
    """Real index/catalog operations must forward the selected bounded wait."""
    index, _, _ = current_index
    owner, _, _ = scheduler
    if profile is None:
        monkeypatch.delenv(schedulers.DEFAULT_PROOF_PROFILE_ENV, raising=False)
    else:
        monkeypatch.setenv(schedulers.DEFAULT_PROOF_PROFILE_ENV, profile)
    acquired = []
    native_acquire = owner.acquire
    def acquire(*args, **kwargs):
        acquired.append(kwargs['timeout'])
        return native_acquire(*args, **kwargs)
    monkeypatch.setattr(owner, 'acquire', acquire)
    controls = dict(scheduler=owner, admission_timeout_seconds=explicit, timeout_seconds=work)
    receipt = index.prepare_current(repository, repository_id=VIEW, operation_id='profile-default',
                                    expected_head=None, **controls)
    observation = index.observe_current(repository, expected_head=receipt.head, **controls)
    assert observation.manifest.cid == receipt.head.manifest_cid
    assert len(acquired) == 2
    if expected == work:
        assert all(0 < wait <= work for wait in acquired)
    else:
        assert acquired == [expected, expected]
