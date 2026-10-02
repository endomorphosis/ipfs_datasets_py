"""Native bounded staging: exact inventory, restart, drift and SQL recovery."""

from pathlib import Path
import json
import os
import subprocess
import sys
import threading

import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import (
    RepositoryCodebaseIndex,
)
from ipfs_datasets_py.logic.software_contracts.codebase_paged_staging import (
    CodebasePagedStager,
    CodebaseStagingLimits,
    CodebaseStagingError,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import (
    ProofHostResources,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    ResourceSchedulerConfig,
    LeaseCancelledError,
)


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


@pytest.fixture
def fixture(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Staging Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    (root / "a.py").write_text("def increment(n: int) -> int:\n    return n + 1\n")
    (root / "b.py").write_bytes(
        "def größe(n: int) -> int:\r\n    return n + 2\r\n".encode()
    )
    (root / "c.py").write_text("def broken(:\n")
    (root / "d.txt").write_text("index as captured source only\n")
    (root / "e.large").write_bytes(b"x" * 4096)
    (root / "f.link").symlink_to("a.py")
    (root / "g.py").write_text('raise RuntimeError("do not execute target source")\n')
    git(root, "add", ".")
    git(root, "commit", "-qm", "fixture")
    database = tmp_path / "staging.duckdb"
    cx = duckdb.connect(str(database), config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=cx)
    artifacts = ImmutableCAS(tmp_path / "artifacts")
    index = RepositoryCodebaseIndex(
        ingestor=DuckDBASTIngestor(store=store),
        artifacts=artifacts,
        catalog=CodebaseCatalog(store, artifacts),
    )
    scheduler = GlobalResourceScheduler(
        ResourceSchedulerConfig.for_proof_host(
            state_path=tmp_path / "resources.json",
            proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
            lane_reservations={},
            auto_renew_leases=False,
        )
    )
    stager = CodebasePagedStager(index)

    def prepare(**kwargs):
        return stager.prepare(
            root,
            repository_id="fixture:staging",
            expected_commit=git(root, "rev-parse", "HEAD"),
            expected_tree=git(root, "rev-parse", "HEAD^{tree}"),
            scheduler=scheduler,
            limits=CodebaseStagingLimits(max_file_bytes=512, max_batch_entries=2),
            **kwargs,
        )

    yield root, cx, index, stager, scheduler, prepare, database
    assert scheduler.snapshot()["active_lease_count"] == 0
    cx.close()


def advance(f, state, **kwargs):
    root, _, _, stager, scheduler, _, _ = f
    return stager.advance(
        root,
        generation_cid=state["generation_cid"],
        expected_cursor=state["cursor"],
        scheduler=scheduler,
        **kwargs,
    )


def test_complete_inventory_and_dispositions_without_current_head(fixture):
    root, cx, index, stager, _, prepare, _ = fixture
    state = prepare()
    generation = state["generation_cid"]
    assert state["entry_count"] == 7 and state["cursor"] == 0
    receipts = []
    while not state["complete_inventory_staged"]:
        before = state["cursor"]
        state = advance(fixture, state)
        assert 0 < state["cursor"] - before <= 2
        receipts.append(state["last_receipt_cid"])
    assert state["disposition_counts"] == {
        "captured_ast_ok": 3,
        "captured_ast_failed": 1,
        "captured_unindexed": 1,
        "deferred_large_file": 1,
        "opaque_symlink": 1,
    }
    assert state["pending_entries"] == 0 and state["deferred_entries"] == 1
    assert (
        state["current_head_published"]
        is state["global_graph_resolved"]
        is state["proof_authority"]
        is False
    )
    assert index.current("fixture:staging") is None
    assert index.ingestor.store.stats()["size"] == 0
    assert prepare()["generation_cid"] == generation
    assert stager.status(generation)["cursor"] == 7
    assert len(receipts) == 4


def test_actual_process_restart_resumes_exact_generation(fixture, tmp_path):
    root, cx, index, _, _, prepare, database = fixture
    state = advance(fixture, prepare())
    cx.close()
    script = """
import json,sys
from pathlib import Path
import duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.codebase_paged_staging import CodebasePagedStager
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler,ResourceSchedulerConfig
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
cx=duckdb.connect(sys.argv[1],config={'threads':1,'memory_limit':'64MB'})
store=DuckDBASTStore(connection=cx);cas=ImmutableCAS(sys.argv[2])
index=RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),artifacts=cas,catalog=CodebaseCatalog(store,cas))
stager=CodebasePagedStager(index)
owner=GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(state_path=Path(sys.argv[5]),proof_resource_sampler=lambda:ProofHostResources(8,8192,8192),lane_reservations={},auto_renew_leases=False))
state=stager.status(sys.argv[4]);assert state['cursor']==2
result=stager.advance(sys.argv[3],generation_cid=sys.argv[4],expected_cursor=2,scheduler=owner)
assert owner.snapshot()['active_lease_count']==0
print(json.dumps(result))
"""
    run = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(database),
            str(index.artifacts.root),
            str(root),
            state["generation_cid"],
            str(tmp_path / "child-resources.json"),
        ],
        text=True,
        capture_output=True,
        timeout=45,
        env=dict(os.environ),
    )
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout.splitlines()[-1])
    assert result["cursor"] == 4 and result["generation_cid"] == state["generation_cid"]


@pytest.mark.parametrize("change", ["edit", "untracked", "staged", "new_commit"])
def test_changed_source_refuses_resume_without_advancing(fixture, change):
    root, _, _, stager, _, prepare, _ = fixture
    state = advance(fixture, prepare())
    if change == "untracked":
        (root / "new.py").write_text("x=1\n")
    else:
        (root / "a.py").write_text("def changed(): return 99\n")
    if change in {"staged", "new_commit"}:
        git(root, "add", ".")
    if change == "new_commit":
        git(root, "commit", "-qm", "successor")
    with pytest.raises(ValueError):
        advance(fixture, state)
    assert stager.status(state["generation_cid"])["cursor"] == 2


def test_exact_lost_response_retry_and_future_cursor(fixture):
    root, _, _, stager, scheduler, prepare, _ = fixture
    initial = prepare()
    state = advance(fixture, initial)
    replay = stager.advance(
        root,
        generation_cid=initial["generation_cid"],
        expected_cursor=0,
        scheduler=scheduler,
    )
    assert (
        replay["cursor"] == 2
        and replay["last_receipt_cid"] == state["last_receipt_cid"]
        and replay["replayed"]
    )
    with pytest.raises(CodebaseStagingError, match="future"):
        stager.advance(
            root,
            generation_cid=state["generation_cid"],
            expected_cursor=3,
            scheduler=scheduler,
        )
    with pytest.raises(CodebaseStagingError, match="boundary"):
        stager.advance(
            root,
            generation_cid=state["generation_cid"],
            expected_cursor=1,
            scheduler=scheduler,
        )


def test_drift_after_shard_sealing_preserves_cursor(fixture, monkeypatch):
    root, _, index, stager, _, prepare, _ = fixture
    state = prepare()
    original = index.artifacts.put

    def put(value):
        result = original(value)
        if value.get("schema") == "codebase-paged-staging-shard@1":
            (root / "a.py").write_text("x=3\n")
        return result

    monkeypatch.setattr(index.artifacts, "put", put)
    with pytest.raises(ValueError):
        advance(fixture, state)
    assert stager.status(state["generation_cid"])["cursor"] == 0


def test_missing_source_artifact_cannot_be_called_staged(fixture):
    _, _, index, stager, _, prepare, _ = fixture
    state = advance(fixture, prepare())
    receipt = index.artifacts.get(state["last_receipt_cid"])
    source = receipt["units"][0]["source_cid"]
    index.artifacts.path_for(source, source=True).unlink()
    with pytest.raises(FileNotFoundError):
        stager.status(state["generation_cid"])


def test_sql_cursor_tamper_and_cancellation_are_rejected(fixture):
    _, cx, _, stager, _, prepare, _ = fixture
    state = prepare()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(LeaseCancelledError):
        advance(fixture, state, cancel_event=cancel)
    cx.execute("UPDATE codebase_staging_control.generations SET cursor=1")
    with pytest.raises(CodebaseStagingError, match="sealed history"):
        stager.status(state["generation_cid"])


def test_failure_after_cursor_write_rolls_back_both_tables(fixture, monkeypatch):
    _, cx, _, stager, _, prepare, _ = fixture
    state = prepare()
    write = stager._write_shard

    def fail(*args):
        write(*args)
        raise RuntimeError("failure after native writes")

    monkeypatch.setattr(stager, "_write_shard", fail)
    with pytest.raises(RuntimeError, match="native writes"):
        advance(fixture, state)
    assert (
        cx.execute("SELECT count(*) FROM codebase_staging_control.shards").fetchone()[0]
        == 0
    )
    assert stager.status(state["generation_cid"])["cursor"] == 0
    monkeypatch.setattr(stager, "_write_shard", write)
    assert advance(fixture, state)["cursor"] == 2


def test_forged_disposition_cannot_hide_required_source(fixture):
    _, cx, index, stager, _, prepare, _ = fixture
    state = advance(fixture, prepare())
    receipt = index.artifacts.get(state["last_receipt_cid"])
    receipt["units"][0].update(
        disposition="deferred_large_file", source_cid=None, ast_cid=None
    )
    substituted = index.artifacts.put(receipt)
    cx.execute(
        "UPDATE codebase_staging_control.shards SET receipt_cid=?", [substituted]
    )
    cx.execute(
        "UPDATE codebase_staging_control.generations SET receipt_cid=?", [substituted]
    )
    with pytest.raises(CodebaseStagingError, match="disposition"):
        stager.status(state["generation_cid"])


def test_entry_cap_does_not_publish_partial_generation(fixture):
    root, cx, _, stager, scheduler, _, _ = fixture
    with pytest.raises(ValueError, match="entry budget"):
        stager.prepare(
            root,
            repository_id="fixture:too-small",
            expected_commit=git(root, "rev-parse", "HEAD"),
            expected_tree=git(root, "rev-parse", "HEAD^{tree}"),
            scheduler=scheduler,
            limits=CodebaseStagingLimits(max_entries=2),
        )
    assert (
        cx.execute(
            "SELECT count(*) FROM codebase_staging_control.generations"
        ).fetchone()[0]
        == 0
    )


def test_post_commit_cancel_preserves_receipt_for_recovery(fixture, monkeypatch):
    from ipfs_datasets_py.logic.software_contracts import (
        codebase_paged_staging as module,
    )

    _, _, _, stager, _, prepare, _ = fixture
    state = prepare()
    signal = threading.Event()
    original = module._fence

    def fence(*args):
        result = original(*args)
        cursor = stager.cx.execute(
            "SELECT cursor FROM codebase_staging_control.generations"
        ).fetchone()[0]
        if cursor == 2:
            signal.set()
        return result

    monkeypatch.setattr(module, "_fence", fence)
    with pytest.raises(LeaseCancelledError):
        advance(fixture, state, cancel_event=signal)
    result = stager.status(state["generation_cid"])
    assert result["cursor"] == 2
    monkeypatch.setattr(module, "_fence", original)
    signal.clear()
    replay = advance(fixture, state)
    assert (
        replay["replayed"] and replay["last_receipt_cid"] == result["last_receipt_cid"]
    )


@pytest.mark.parametrize("kind", ["ast", "manifest"])
@pytest.mark.parametrize("mutation", ["remove", "replace"])
def test_parsed_cache_hit_rechecks_exact_artifact_bytes(fixture, kind, mutation):
    _, _, index, stager, _, prepare, _ = fixture
    state = advance(fixture, prepare())
    stager.status(state["generation_cid"])
    if kind == "ast":
        receipt = index.artifacts.get(state["last_receipt_cid"])
        cid = receipt["units"][0]["ast_cid"]
    else:
        cid = state["generation_cid"]
    path = index.artifacts.path_for(cid)
    if mutation == "remove":
        path.unlink()
    else:
        original = path.read_bytes()
        # Same-size replacement must fail as well as truncation/size changes.
        path.write_bytes(b"x" + original[1:])
    with pytest.raises((CodebaseStagingError, FileNotFoundError)):
        stager.status(state["generation_cid"])


@pytest.mark.parametrize("bound", ["entries", "bytes"])
def test_parsed_ast_cache_has_bounded_eviction_and_cold_replay(
    fixture, monkeypatch, bound
):
    from ipfs_datasets_py.logic.software_contracts import (
        codebase_paged_staging as module,
    )

    _, _, _, stager, _, prepare, _ = fixture
    if bound == "entries":
        monkeypatch.setattr(module, "PARSED_AST_CACHE_ENTRIES", 1)
    else:
        monkeypatch.setattr(module, "PARSED_AST_CACHE_BYTES", 1)
    state = advance(fixture, prepare())
    assert stager.status(state["generation_cid"])["cursor"] == 2
    stats = stager.replay_cache_stats()
    assert stats["ast_entries"] <= stats["ast_limit_entries"]
    assert stats["ast_bytes"] <= stats["ast_limit_bytes"]
    if bound == "entries":
        assert stats["ast_evictions"] > 0
    else:
        assert stats["ast_entries"] == 0
    assert stats["ast_parses"] >= 2


def test_cached_inventory_rechecks_producer_identity(fixture, monkeypatch):
    from ipfs_datasets_py.logic.software_contracts import (
        codebase_paged_staging as module,
    )

    _, _, _, stager, _, prepare, _ = fixture
    state = prepare()
    assert stager.replay_cache_stats()["manifest_parses"] == 1
    changed = dict(module._implementation())
    changed["changed.producer"] = "0" * 64
    monkeypatch.setattr(module, "_implementation", lambda: changed)
    with pytest.raises(CodebaseStagingError, match="implementation changed"):
        stager.status(state["generation_cid"])


def test_verified_root_is_reused_without_per_unit_manifest_reconstruction(
    fixture, monkeypatch
):
    from ipfs_datasets_py.logic.software_contracts.semantic_index.chunked_snapshot import (
        ChunkedRepositorySnapshot,
    )

    _, _, _, stager, _, prepare, _ = fixture
    state = prepare()

    def forbidden(_):
        raise AssertionError("the whole verified manifest was rebuilt for a unit")

    monkeypatch.setattr(ChunkedRepositorySnapshot, "snapshot_cid", property(forbidden))
    state = advance(fixture, state)
    assert stager.status(state["generation_cid"])["cursor"] == 2


def test_disposition_and_canonicalization_owners_are_pinned(fixture, monkeypatch, tmp_path):
    import hashlib

    from ipfs_datasets_py.logic.software_contracts import (
        codebase_paged_staging as module,
        content,
        duckdb_ast_store,
    )
    from ipfs_datasets_py.logic.software_contracts.semantic_index import snapshot

    pins = module._implementation()
    for owner in (content, duckdb_ast_store, snapshot):
        assert pins[owner.__name__] == hashlib.sha256(
            Path(owner.__file__).read_bytes()
        ).hexdigest()

    _, _, _, stager, _, prepare, _ = fixture
    state = advance(fixture, prepare())
    stager.status(state["generation_cid"])
    assert stager.replay_cache_stats()["ast_entries"] > 0
    changed_owner = tmp_path / "changed_duckdb_ast_store.py"
    changed_owner.write_bytes(
        Path(duckdb_ast_store.__file__).read_bytes() + b"\n# classifier owner changed\n"
    )
    monkeypatch.setattr(duckdb_ast_store, "__file__", str(changed_owner))
    with pytest.raises(CodebaseStagingError, match="implementation changed"):
        stager.status(state["generation_cid"])
