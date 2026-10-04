"""Native repository capture, exact AST lookup and independent-process replay."""

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
from ipfs_datasets_py.logic.software_contracts.codebase_ir import (
    CodebaseIRError, CodebaseIRManifest, CodebaseScanLimits, RepositoryCodebaseIndex,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "target"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 1\n")
    (root / "remove.py").write_text("def obsolete():\n    return 0\n")
    (root / "README.txt").write_text("bounded repository fixture\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    return root


@pytest.fixture
def scheduler(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192)
    current = [healthy]
    config = schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json", proof_resource_sampler=lambda: current[0],
        lane_reservations={}, auto_renew_leases=False, proof_backoff_seconds=0.02,
        poll_interval_seconds=0.005,
    )
    return schedulers.GlobalResourceScheduler(config), healthy, current


@pytest.fixture
def index(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(str(tmp_path / "ast.duckdb"), config={"threads": 1, "memory_limit": "64MB"})
    result = RepositoryCodebaseIndex(
        ingestor=DuckDBASTIngestor(store=DuckDBASTStore(connection=connection)),
        artifacts=ImmutableCAS(tmp_path / "artifacts"),
    )
    yield result, connection
    connection.close()


def assert_idle(owner):
    state = owner.snapshot()
    assert state["active_lease_count"] == state["waiting_request_count"] == 0


def test_dirty_overlay_changes_identity_and_projects_actual_bytes(repository, index, scheduler):
    prepared, _ = index
    owner, _, _ = scheduler
    first = prepared.prepare(repository, scheduler=owner)
    commit = git(repository, "rev-parse", "HEAD")
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 2\n")
    (repository / "remove.py").unlink()
    (repository / "new.py").write_text("def newly_added():\n    return 7\n")
    changed = prepared.prepare(repository, scheduler=owner, previous=first)
    assert git(repository, "rev-parse", "HEAD") == commit
    assert changed.snapshot.mode == "git-working"
    assert first.cid != changed.cid
    assert first.ast_revision_id != changed.ast_revision_id
    projected = prepared.lookup(changed, "counter.py")
    assert projected is not None
    assert projected.source_cid == next(e.source_cid for e in changed.snapshot.entries if e.path == "counter.py")
    assert prepared.artifacts.get_bytes(projected.source_cid) == (repository / "counter.py").read_bytes()
    assert prepared.lookup(changed, "new.py") is not None
    assert prepared.lookup(changed, "remove.py") is None
    assert prepared.lookup(changed, "README.txt") is None
    assert changed.coverage["inventory_entries"] == 4
    assert changed.coverage["opaque_entries"] == 1
    assert changed.coverage["unindexed_entries"] == 1
    assert changed.coverage["checked_properties"] == 0
    assert changed.to_dict()["authority"] == "structural_only"
    with pytest.raises(CodebaseIRError, match="missing or invalidated"):
        prepared.lookup(first, "counter.py")
    historical = prepared.load_ast_artifact(first, "counter.py")
    assert historical.provenance.source_cid != projected.source_cid
    assert prepared.artifacts.get_bytes(historical.provenance.source_cid).endswith(b"return n + 1\n")
    again = prepared.prepare(repository, scheduler=owner, previous=changed)
    assert again.cid == changed.cid
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 3\n")
    third = prepared.prepare(repository, scheduler=owner, previous=again)
    assert third.cid != changed.cid
    assert third.snapshot.git_commit == changed.snapshot.git_commit
    assert_idle(owner)


def test_manifest_and_native_ast_replay_in_fresh_process(repository, index, scheduler, tmp_path):
    prepared, connection = index
    owner, _, _ = scheduler
    manifest = prepared.prepare(repository, scheduler=owner)
    expected = prepared.lookup(manifest, "counter.py").ast_cid
    connection.close()
    script = """
import json, sys, duckdb
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
connection = duckdb.connect(sys.argv[1], config={'threads':1, 'memory_limit':'64MB'})
index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=DuckDBASTStore(connection=connection)), artifacts=ImmutableCAS(sys.argv[2]))
manifest = index.load(sys.argv[3])
projection = index.lookup(manifest, 'counter.py')
print(json.dumps({'manifest':manifest.cid, 'ast':projection.ast_cid, 'coverage':manifest.coverage}))
connection.close()
"""
    run = subprocess.run([sys.executable, "-c", script, str(tmp_path / "ast.duckdb"),
                          str(tmp_path / "artifacts"), manifest.cid],
                         capture_output=True, text=True, timeout=30, env=dict(os.environ))
    assert run.returncode == 0, run.stderr
    replayed = json.loads(run.stdout.splitlines()[-1])
    assert replayed == {"manifest": manifest.cid, "ast": expected, "coverage": manifest.coverage}
    assert_idle(owner)


def test_default_admission_and_manifest_roundtrip(repository, index, scheduler, monkeypatch):
    prepared, _ = index
    owner, _, _ = scheduler
    from ipfs_datasets_py.logic.software_contracts import codebase_resources
    monkeypatch.setattr(codebase_resources, "get_global_resource_scheduler", lambda: owner)
    original = module.snapshot_repository
    def observe(*args, **kwargs):
        assert owner.config.proof_safety_enabled
        assert owner.snapshot()["active_root_lease_count"] == 1
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "snapshot_repository", observe)
    manifest = prepared.prepare(repository)
    assert CodebaseIRManifest.from_dict(manifest.to_dict()).cid == manifest.cid
    assert prepared.load(manifest.cid).cid == manifest.cid
    assert_idle(owner)


def test_nested_resources_preserve_parent(repository, index, scheduler, monkeypatch):
    prepared, _ = index
    owner, _, _ = scheduler
    with owner.acquire("orchestration", cpu_slots=2, memory_mb=1024, child_process_slots=2, timeout=0) as parent:
        allocated = owner.snapshot()["allocated"]
        original = module.snapshot_repository
        def observe(*args, **kwargs):
            active = owner.snapshot()
            assert active["active_root_lease_count"] == 1
            assert active["active_lease_count"] == 2
            assert active["allocated"] == allocated
            return original(*args, **kwargs)
        monkeypatch.setattr(module, "snapshot_repository", observe)
        prepared.prepare(repository, parent_lease=parent)
        assert not parent.released
        assert owner.snapshot()["active_lease_count"] == 1
    assert_idle(owner)


def test_pressure_blocks_before_any_source_read(repository, index, scheduler, monkeypatch):
    prepared, _ = index
    owner, healthy, current = scheduler
    current[0] = replace(healthy, memory_stall_percent=10)
    def forbidden(*args, **kwargs):
        pytest.fail("snapshot started under external memory pressure")
    monkeypatch.setattr(module, "snapshot_repository", forbidden)
    with pytest.raises(schedulers.LeaseTimeoutError):
        prepared.prepare(repository, scheduler=owner, admission_timeout_seconds=0.01)
    assert prepared.ingestor.store.stats()["size"] == 0
    assert not list(prepared.artifacts.structured_root.rglob("baf*"))
    assert_idle(owner)


def test_cancellation_after_capture_prevents_ast_publication(repository, index, scheduler, monkeypatch):
    prepared, _ = index
    owner, _, _ = scheduler
    cancelled = threading.Event()
    original = module.snapshot_repository
    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        cancelled.set()
        return result
    monkeypatch.setattr(module, "snapshot_repository", capture)
    with pytest.raises(schedulers.LeaseCancelledError):
        prepared.prepare(repository, scheduler=owner, cancel_event=cancelled)
    assert prepared.ingestor.store.stats()["size"] == 0
    assert_idle(owner)


@pytest.mark.parametrize("mutation", ["authority", "coverage", "units", "state", "extra"])
def test_manifest_rejects_forged_bindings(repository, index, scheduler, mutation):
    prepared, _ = index
    owner, _, _ = scheduler
    manifest = prepared.prepare(repository, scheduler=owner)
    value = manifest.to_dict()
    if mutation == "authority": value["authority"] = "proved"
    elif mutation == "coverage": value["coverage"]["checked_properties"] = 1
    elif mutation == "units": value["units"].pop()
    elif mutation == "state": value["ast_revision_id"] += ":other"
    else: value["proof"] = True
    with pytest.raises(CodebaseIRError):
        CodebaseIRManifest.from_dict(value)
    assert_idle(owner)


def test_limits_reject_before_admission_or_scan(repository, index, scheduler, monkeypatch):
    prepared, _ = index
    owner, _, _ = scheduler
    def forbidden(*args, **kwargs):
        pytest.fail("unbounded snapshot started")
    monkeypatch.setattr(module, "snapshot_repository", forbidden)
    with pytest.raises(CodebaseIRError, match="memory envelope"):
        prepared.prepare(repository, scheduler=owner, limits=CodebaseScanLimits(10000, 1024 * 1024))
    assert_idle(owner)


def test_nonexecuting_capture_and_explicit_unsupported_entries(repository, index, scheduler):
    prepared, _ = index
    owner, _, _ = scheduler
    marker = repository.parent / "must-not-exist"
    (repository / "trap.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")
    (repository / "broken.py").write_text("def unfinished(\n")
    (repository / "large.py").write_bytes(b"#" * (64 * 1024 + 1))
    manifest = prepared.prepare(repository, scheduler=owner)
    assert not marker.exists()
    assert manifest.coverage["ast_failed"] == 1
    assert manifest.coverage["opaque_entries"] == 1
    assert prepared.lookup(manifest, "large.py") is None
    assert prepared.lookup(manifest, "broken.py").ast_blob.parse_status == "failed"
    assert_idle(owner)


def test_restored_snapshot_has_active_native_rows(repository, index, scheduler):
    prepared, _ = index
    owner, _, _ = scheduler
    first = prepared.prepare(repository, scheduler=owner)
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 5\n")
    changed = prepared.prepare(repository, scheduler=owner, previous=first)
    git(repository, "checkout", "--", "counter.py")
    restored = prepared.prepare(repository, scheduler=owner, previous=changed)
    assert restored.cid == first.cid
    assert prepared.lookup(restored, "counter.py") is not None
    assert_idle(owner)


def test_manifest_rejects_old_symbols_with_new_snapshot_evidence(repository, index, scheduler):
    prepared, _ = index
    owner, _, _ = scheduler
    first = prepared.prepare(repository, scheduler=owner)
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 9\n")
    changed = prepared.prepare(repository, scheduler=owner, previous=first)
    mixed = replace(changed.semantic_state, symbols=first.semantic_state.symbols)
    with pytest.raises(CodebaseIRError, match="semantic symbol"):
        replace(changed, semantic_state=mixed)
    assert_idle(owner)


@pytest.mark.parametrize("failure", ["io", "cancel"])
def test_manifest_seal_failure_preserves_previous_ast_and_retry_recovers(
    repository, index, scheduler, monkeypatch, failure,
):
    prepared, _ = index
    owner, _, _ = scheduler
    first = prepared.prepare(repository, scheduler=owner)
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 4\n")
    cancelled = threading.Event()
    original = prepared.artifacts.put
    def fail(value):
        if value.get("schema") != module.CODEBASE_IR_SCHEMA:
            return original(value)
        if failure == "io":
            raise OSError("injected manifest storage failure")
        result = original(value)
        cancelled.set()
        return result
    monkeypatch.setattr(prepared.artifacts, "put", fail)
    expected = OSError if failure == "io" else schedulers.LeaseCancelledError
    with pytest.raises(expected):
        prepared.prepare(repository, scheduler=owner, previous=first, cancel_event=cancelled)
    assert prepared.lookup(first, "counter.py") is not None
    assert_idle(owner)
    monkeypatch.setattr(prepared.artifacts, "put", original)
    cancelled.clear()
    repaired = prepared.prepare(repository, scheduler=owner, previous=first, cancel_event=cancelled)
    assert repaired.cid != first.cid
    assert prepared.lookup(repaired, "counter.py") is not None
    assert_idle(owner)


def test_cold_and_incremental_manifests_agree(repository, index, scheduler):
    prepared, _ = index
    owner, _, _ = scheduler
    first = prepared.prepare(repository, scheduler=owner)
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 8\n")
    incremental = prepared.prepare(repository, scheduler=owner, previous=first)
    cold = RepositoryCodebaseIndex().prepare(repository, scheduler=owner)
    assert cold.cid == incremental.cid
    assert_idle(owner)


def test_cancel_after_sql_commit_recovers_idempotently(repository, index, scheduler, monkeypatch):
    prepared, _ = index
    owner, _, _ = scheduler
    first = prepared.prepare(repository, scheduler=owner)
    (repository / "counter.py").write_text("def increment(n: int) -> int:\n    return n + 6\n")
    cancelled = threading.Event()
    original = prepared.ingestor.ingest_snapshot
    def commit_then_cancel(*args, **kwargs):
        result = original(*args, **kwargs)
        cancelled.set()
        return result
    monkeypatch.setattr(prepared.ingestor, "ingest_snapshot", commit_then_cancel)
    with pytest.raises(schedulers.LeaseCancelledError):
        prepared.prepare(repository, scheduler=owner, previous=first, cancel_event=cancelled)
    # The commit is complete even though delivery of the receipt was cancelled.
    with pytest.raises(CodebaseIRError, match="missing or invalidated"):
        prepared.lookup(first, "counter.py")
    before_retry = prepared.ingestor.store.stats()["puts"]
    monkeypatch.setattr(prepared.ingestor, "ingest_snapshot", original)
    cancelled.clear()
    recovered = prepared.prepare(repository, scheduler=owner, previous=first, cancel_event=cancelled)
    assert prepared.load(recovered.cid).cid == recovered.cid
    assert prepared.lookup(recovered, "counter.py") is not None
    assert prepared.ingestor.store.stats()["puts"] == before_retry
    assert_idle(owner)


@pytest.mark.parametrize("unborn", [False, True])
def test_filesystem_and_unborn_capture_without_fake_git_identity(tmp_path, scheduler, unborn):
    owner, _, _ = scheduler
    repository = tmp_path / "ungrounded"
    repository.mkdir()
    if unborn:
        git(repository, "init", "-q")
    (repository / "one.py").write_text("value = 1\n")
    prepared = RepositoryCodebaseIndex()
    manifest = prepared.prepare(repository, scheduler=owner, repository_id="fixture-repository")
    assert manifest.snapshot.mode == ("git-unborn" if unborn else "filesystem")
    assert manifest.snapshot.git_commit is None
    assert manifest.snapshot.snapshot_cid in manifest.ast_revision_id
    assert prepared.lookup(manifest, "one.py") is not None
    assert_idle(owner)
