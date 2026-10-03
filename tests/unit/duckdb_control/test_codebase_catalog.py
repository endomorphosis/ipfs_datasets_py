"""Actual DuckDB CAS publication, historical replay and rollback qualification."""

from dataclasses import replace
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import (
    CodebaseCatalog, CodebaseCatalogError, CodebaseCatalogLimits,
    CodebaseHead, CodebaseHeadConflict, CodebaseOperationConflict,
    CodebasePublicationReceipt,
)
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig,
)


@pytest.fixture
def fixture(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    path = tmp_path / "catalog.duckdb"
    connection = duckdb.connect(str(path), config={"threads": 1, "memory_limit": "64MB"})
    artifacts = ImmutableCAS(tmp_path / "artifacts")
    store = DuckDBASTStore(connection=connection)
    catalog = CodebaseCatalog(store, artifacts)
    repo = tmp_path / "source"
    repo.mkdir()
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json",
        proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False,
    ))
    preparer = RepositoryCodebaseIndex(artifacts=artifacts)

    def candidate(n=1, repository_id="fixture"):
        (repo / "unit.py").write_text(f"def count(n):\n    return n + {n}\n")
        manifest = preparer.prepare(repo, repository_id=repository_id, scheduler=scheduler)
        publication = preparer.ingestor.get_publication(manifest.ast_revision_id)
        return manifest, publication.projections

    yield catalog, connection, candidate, path, tmp_path
    connection.close()


def publish(catalog, candidate, operation_id, previous=None):
    manifest, projections = candidate
    return catalog.publish(operation_id=operation_id, manifest=manifest,
                           expected_head=previous, projections=projections)


def test_falsey_callable_cancellation_checkpoint_is_not_discarded(fixture):
    catalog, connection, candidate, _, _ = fixture
    item = candidate()

    class FalseyCancellation:
        def __bool__(self):
            return False

        def __call__(self):
            raise InterruptedError("falsey cancellation remains active")

    with pytest.raises(InterruptedError, match="falsey cancellation"):
        catalog.publish(operation_id="falsey-cancellation", manifest=item[0], expected_head=None,
                        projections=item[1], checkpoint=FalseyCancellation())
    assert catalog.current("fixture") is None
    assert connection.execute("SELECT count(*) FROM codebase_control.operations").fetchone()[0] == 0


def test_exact_head_receipt_replay_and_aba_generation(fixture):
    catalog, connection, candidate, _, _ = fixture
    one = candidate(1)
    first = publish(catalog, one, "first")
    assert first.head.generation == 1
    assert catalog.current("fixture") == first.head
    assert CodebaseHead.from_dict(first.head.to_dict()) == first.head
    assert CodebasePublicationReceipt.from_dict(first.to_dict()) == first
    second = publish(catalog, candidate(2), "second", first.head)
    assert catalog.store.get_by_ast_cid(one[1][0].ast_cid) is None
    before = catalog.store.stats().copy()
    assert publish(catalog, one, "first") == first  # Historical, no AST mutation.
    assert catalog.store.stats() == before
    assert catalog.current("fixture") == second.head
    restored = publish(catalog, one, "restore", second.head)
    assert restored.head.manifest_cid == first.head.manifest_cid
    assert restored.head.generation == 3
    assert restored.head != first.head
    with pytest.raises(CodebaseHeadConflict):
        publish(catalog, candidate(3), "stale", first.head)
    with pytest.raises(CodebaseOperationConflict):
        publish(catalog, one, "first", restored.head)
    assert connection.execute("SELECT count(*) FROM codebase_control.operations").fetchone()[0] == 3


@pytest.mark.parametrize("mutation", ["durable_field", "metadata_scalar_type"])
def test_warm_manifest_does_not_hide_candidate_mutation_during_cas_read(fixture, monkeypatch, mutation):
    from types import MappingProxyType
    catalog, connection, candidate, _, _ = fixture
    manifest, projections = candidate()
    artifact = manifest.semantic_state.artifacts[0]
    if mutation == "metadata_scalar_type":
        artifact = replace(artifact, metadata={**artifact.metadata, "typed_probe": True})
        manifest = replace(manifest, semantic_state=replace(manifest.semantic_state,
            artifacts=(artifact, *manifest.semantic_state.artifacts[1:])))
        catalog.artifacts.put(manifest.to_dict())
    cid = manifest.cid
    # Warm the same pure reconstruction used by publication, then mutate only
    # the caller's original frozen graph during its fresh artifact read.
    loader = RepositoryCodebaseIndex(artifacts=catalog.artifacts)
    assert loader.load(cid).cid == cid
    original = catalog._read_artifact
    changed = []
    def read(identity, *args, **kwargs):
        result = original(identity, *args, **kwargs)
        if identity == cid and not changed:
            changed.append(True)
            if mutation == "durable_field":
                object.__setattr__(manifest.semantic_state, "extractor_version", "changed-during-read")
            else:
                object.__setattr__(artifact, "metadata", MappingProxyType({**artifact.metadata, "typed_probe": 1}))
        return result
    monkeypatch.setattr(catalog, "_read_artifact", read)
    with pytest.raises(CodebaseCatalogError, match="sealed canonical artifact"):
        catalog.publish(operation_id="changed", manifest=manifest,
                        expected_head=None, projections=projections)
    assert changed and catalog.current("fixture") is None
    assert connection.execute("SELECT count(*) FROM ast_blobs").fetchone()[0] == 0
    assert loader.load(cid).semantic_state.extractor_version != "changed-during-read"


def test_native_restart_current_and_prior_revision_invalidation(fixture):
    catalog, connection, candidate, path, _ = fixture
    first_candidate, second_candidate = candidate(1), candidate(2)
    first = publish(catalog, first_candidate, "first")
    connection.close()
    import duckdb
    with duckdb.connect(str(path), config={"threads": 1, "memory_limit": "64MB"}) as reopened:
        owner = CodebaseCatalog(DuckDBASTStore(connection=reopened), catalog.artifacts)
        assert owner.current("fixture") == first.head
        assert owner.resolve_operation("first", owner.request_identity(first_candidate[0], None)) == first
        second = publish(owner, second_candidate, "second", first.head)
        assert second.head.generation == 2
        assert owner.store.get_by_ast_cid(first_candidate[1][0].ast_cid) is None
        invalidations = [row for row in owner.store.list_invalidations()
                         if row.revision_id == first.head.ast_revision_id]
        assert any(row.reason == "revision_superseded" for row in invalidations)
        assert owner.current("fixture") == second.head


def test_fresh_process_reads_exact_head_and_historical_receipt(fixture):
    catalog, connection, candidate, path, _ = fixture
    one = candidate()
    receipt = publish(catalog, one, "first")
    request = catalog.request_identity(one[0], None)
    connection.close()
    script = '''
import json, sys, duckdb
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
with duckdb.connect(sys.argv[1], config={'threads':1,'memory_limit':'64MB'}) as cx:
    catalog = CodebaseCatalog(DuckDBASTStore(connection=cx), ImmutableCAS(sys.argv[2]))
    print(json.dumps({'head':catalog.current('fixture').to_dict(),
                      'receipt':catalog.resolve_operation('first',sys.argv[3]).to_dict()}))
'''
    run = subprocess.run([sys.executable, "-c", script, str(path), str(catalog.artifacts.root), request],
                         check=True, text=True, capture_output=True, timeout=30)
    assert json.loads(run.stdout.splitlines()[-1]) == {"head": receipt.head.to_dict(), "receipt": receipt.to_dict()}


def test_sql_failure_rolls_back_head_ast_and_operation(fixture, monkeypatch):
    catalog, connection, candidate, _, _ = fixture
    one, two = candidate(1), candidate(2)
    first = publish(catalog, one, "first")
    original = catalog.store._persist_projection

    def fail_after_writing(projection):
        original(projection)
        raise RuntimeError("injected write failure")

    monkeypatch.setattr(catalog.store, "_persist_projection", fail_after_writing)
    with pytest.raises(RuntimeError, match="injected"):
        publish(catalog, two, "second", first.head)
    assert catalog.current("fixture") == first.head
    assert catalog.store.get_by_ast_cid(one[1][0].ast_cid) == one[1][0]
    assert catalog.store.get_by_ast_cid(two[1][0].ast_cid) is None
    assert catalog.resolve_operation("second", catalog.request_identity(two[0], first.head)) is None
    assert connection.execute("SELECT count(*) FROM invalidations").fetchone()[0] == 0


@pytest.mark.parametrize("with_publication_checkpoint", [False, True])
def test_cancellation_after_head_write_rolls_back_entire_commit(fixture, with_publication_checkpoint):
    catalog, connection, candidate, _, _ = fixture
    one, two = candidate(1), candidate(2)
    first = publish(catalog, one, "first")

    def checkpoint():
        # Runs on this owner's thread; inspect tentative rows without another
        # transaction to interrupt precisely after both AST and head mutation.
        row = connection.execute("SELECT operation_id FROM codebase_control.operations WHERE operation_id='cancelled'").fetchone()
        if row is not None:
            raise InterruptedError("cancelled before commit")

    with pytest.raises(InterruptedError):
        catalog.publish(operation_id="cancelled", manifest=two[0], expected_head=first.head,
                        projections=two[1], checkpoint=checkpoint,
                        publication_checkpoint=(lambda: None) if with_publication_checkpoint else None)
    assert catalog.current("fixture") == first.head
    assert catalog.store.get_by_ast_cid(one[1][0].ast_cid) == one[1][0]
    assert catalog.store.get_by_ast_cid(two[1][0].ast_cid) is None
    assert catalog.resolve_operation("cancelled", catalog.request_identity(two[0], first.head)) is None


def test_publication_checkpoint_observes_transaction_boundaries_and_skips_replay(fixture):
    catalog, connection, candidate, _, _ = fixture
    item = candidate()
    observed = []
    cancellations = []

    def observe():
        # Inspect real tentative SQL state, independently of callback position.
        observed.append((connection.execute("SELECT ast_cid FROM ast_blobs WHERE ast_cid=?", [item[1][0].ast_cid]).fetchone() is not None,
            connection.execute("SELECT count(*) FROM codebase_control.heads").fetchone()[0],
            connection.execute("SELECT count(*) FROM codebase_control.operations").fetchone()[0]))

    receipt = catalog.publish(operation_id="fenced", manifest=item[0], expected_head=None,
        projections=item[1], checkpoint=lambda: cancellations.append(True),
        publication_checkpoint=observe)
    assert observed == [(False, 0, 0), (True, 0, 0), (True, 1, 1)]
    assert len(cancellations) > len(observed)
    before = list(observed), list(cancellations)
    assert catalog.publish(operation_id="fenced", manifest=item[0], expected_head=None,
        projections=item[1], checkpoint=lambda: cancellations.append(True),
        publication_checkpoint=observe) == receipt
    assert (observed, cancellations) == before


@pytest.mark.parametrize("boundary", ["before_ast", "before_head", "after_head"])
def test_publication_checkpoint_failure_rolls_back_all_native_rows(fixture, boundary):
    catalog, connection, candidate, _, _ = fixture
    one, two = candidate(1), candidate(2)
    first = publish(catalog, one, "first")

    def refuse():
        applied = connection.execute("SELECT ast_cid FROM ast_blobs WHERE ast_cid=?", [two[1][0].ast_cid]).fetchone() is not None
        written = connection.execute(
            "SELECT operation_id FROM codebase_control.operations WHERE operation_id='refused'").fetchone()
        current = "after_head" if written is not None else "before_head" if applied else "before_ast"
        if current == boundary:
            raise InterruptedError("publication fence refused " + boundary)

    with pytest.raises(InterruptedError, match="publication fence refused " + boundary):
        catalog.publish(operation_id="refused", manifest=two[0], expected_head=first.head,
            projections=two[1], publication_checkpoint=refuse)
    assert catalog.current("fixture") == first.head
    assert catalog.store.get_by_ast_cid(one[1][0].ast_cid) == one[1][0]
    assert catalog.store.get_by_ast_cid(two[1][0].ast_cid) is None
    assert catalog.resolve_operation("refused", catalog.request_identity(two[0], first.head)) is None
    assert connection.execute("SELECT count(*) FROM invalidations").fetchone()[0] == 0


def test_publication_checkpoint_must_be_callable_before_mutation(fixture):
    catalog, connection, candidate, _, _ = fixture
    item = candidate()
    with pytest.raises(CodebaseCatalogError, match="publication_checkpoint must be callable"):
        catalog.publish(operation_id="invalid-hook", manifest=item[0], expected_head=None,
            projections=item[1], publication_checkpoint=3)
    assert connection.execute("SELECT count(*) FROM codebase_control.heads").fetchone()[0] == 0
    assert catalog.store.get_by_ast_cid(item[1][0].ast_cid) is None


def test_falsey_callable_publication_checkpoint_is_not_discarded(fixture):
    catalog, connection, candidate, _, _ = fixture
    item = candidate()

    class FalseyFence:
        def __bool__(self):
            return False

        def __call__(self):
            raise InterruptedError("falsey publication fence still executes")

    with pytest.raises(InterruptedError, match="falsey publication fence still executes"):
        catalog.publish(operation_id="falsey-hook", manifest=item[0], expected_head=None,
            projections=item[1], publication_checkpoint=FalseyFence())
    assert connection.execute("SELECT count(*) FROM codebase_control.heads").fetchone()[0] == 0
    assert catalog.store.get_by_ast_cid(item[1][0].ast_cid) is None


def test_simultaneous_candidates_cannot_both_win_same_expected_head(fixture):
    catalog, _, candidate, _, _ = fixture
    one, two, three = candidate(1), candidate(2), candidate(3)
    first = publish(catalog, one, "first")
    ready = threading.Barrier(2)

    def contender(item, operation):
        ready.wait(timeout=10)
        try:
            return publish(catalog, item, operation, first.head)
        except CodebaseHeadConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(contender, two, "two")
        b = pool.submit(contender, three, "three")
        receipts = [a.result(timeout=30), b.result(timeout=30)]
    winners = [receipt for receipt in receipts if receipt is not None]
    assert len(winners) == 1
    assert catalog.current("fixture") == winners[0].head
    assert catalog.store.stats()["size"] == 1


@pytest.mark.parametrize("artifact", ["manifest", "source", "ast"])
def test_missing_required_artifacts_reject_before_any_mutation(fixture, artifact):
    catalog, connection, candidate, _, _ = fixture
    item = candidate()
    cid = {"manifest": item[0].cid, "source": item[1][0].source_cid, "ast": item[1][0].ast_cid}[artifact]
    catalog.artifacts.path_for(cid, source=artifact == "source").unlink()
    with pytest.raises(CodebaseCatalogError, match="artifact"):
        publish(catalog, item, "first")
    assert catalog.current("fixture") is None
    assert catalog.store.stats()["size"] == 0
    assert connection.execute("SELECT count(*) FROM codebase_control.operations").fetchone()[0] == 0


def test_projection_set_must_match_complete_manifest(fixture):
    catalog, _, candidate, _, _ = fixture
    item = candidate()
    for projections in ((), item[1] * 2):
        with pytest.raises(CodebaseCatalogError):
            catalog.publish(operation_id="first", manifest=item[0], expected_head=None, projections=projections)
    assert catalog.current("fixture") is None


def test_historical_resolution_does_not_need_still_available_artifacts(fixture):
    catalog, _, candidate, _, _ = fixture
    item = candidate()
    receipt = publish(catalog, item, "first")
    catalog.artifacts.path_for(item[0].cid).unlink()
    assert publish(catalog, item, "first") == receipt
    assert catalog.resolve_operation("first", catalog.request_identity(item[0], None)) == receipt


def test_operation_bound_preserves_history_and_rejects_new_writes(fixture):
    catalog, _, candidate, _, _ = fixture
    catalog = CodebaseCatalog(catalog.store, catalog.artifacts, limits=CodebaseCatalogLimits(max_operations=1))
    one, two = candidate(1), candidate(2)
    first = publish(catalog, one, "first")
    with pytest.raises(CodebaseCatalogError, match="row bound"):
        publish(catalog, two, "second", first.head)
    assert publish(catalog, one, "first") == first
    assert catalog.current("fixture") == first.head


@pytest.mark.parametrize("damage", ["head", "receipt", "schema"])
def test_tampering_fails_closed(fixture, damage):
    catalog, connection, candidate, _, _ = fixture
    publish(catalog, candidate(), "first")
    if damage == "head":
        connection.execute("UPDATE codebase_control.heads SET generation=99")
    elif damage == "receipt":
        connection.execute("UPDATE codebase_control.operations SET receipt='{}'")
    else:
        connection.execute("ALTER TABLE codebase_control.heads ADD COLUMN injected INTEGER")
    with pytest.raises(CodebaseCatalogError):
        catalog.current("fixture")


def test_native_durable_owner_and_process_identity_required(fixture, monkeypatch):
    catalog, _, _, _, _ = fixture
    with pytest.raises(CodebaseCatalogError, match="native"):
        CodebaseCatalog(DuckDBASTStore(), catalog.artifacts)
    import duckdb
    with duckdb.connect() as memory:
        with pytest.raises(CodebaseCatalogError, match="file-backed"):
            CodebaseCatalog(DuckDBASTStore(connection=memory), catalog.artifacts)
    monkeypatch.setattr(catalog, "_pid", os.getpid() - 1)
    with pytest.raises(CodebaseCatalogError, match="another process"):
        catalog.current("fixture")


def test_oversized_receipt_rejected_before_hydration(fixture):
    catalog, connection, candidate, _, _ = fixture
    publish(catalog, candidate(), "first")
    connection.execute("UPDATE codebase_control.operations SET receipt=repeat('x', ?)", [catalog.limits.max_receipt_bytes + 1])
    with pytest.raises(CodebaseCatalogError, match="bound"):
        catalog.current("fixture")


def test_two_native_connections_rollback_the_losing_transaction(fixture, monkeypatch):
    """Actual DuckDB MVCC conflicts cannot publish half a revision/head pair."""
    import duckdb

    catalog, _, candidate, path, _ = fixture
    one, two, three = candidate(1), candidate(2), candidate(3)
    first = publish(catalog, one, "first")
    barrier = threading.Barrier(2)
    with duckdb.connect(str(path), config={"threads": 1, "memory_limit": "64MB"}) as other_connection:
        other = CodebaseCatalog(DuckDBASTStore(connection=other_connection), catalog.artifacts)
        for store in (catalog.store, other.store):
            original = store._persist_projection

            def after_projection(projection, original=original):
                original(projection)
                barrier.wait(timeout=10)

            monkeypatch.setattr(store, "_persist_projection", after_projection)

        def contender(owner, item, operation):
            try:
                return publish(owner, item, operation, first.head)
            except (CodebaseHeadConflict, duckdb.TransactionException):
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(contender, catalog, two, "two")
            b = pool.submit(contender, other, three, "three")
            receipts = [a.result(timeout=30), b.result(timeout=30)]
        winners = [receipt for receipt in receipts if receipt is not None]
        assert len(winners) == 1
        assert catalog.current("fixture") == other.current("fixture") == winners[0].head
        for item, operation in ((two, "two"), (three, "three")):
            receipt = catalog.resolve_operation(operation, catalog.request_identity(item[0], first.head))
            active_ast = catalog.store.get_by_ast_cid(item[1][0].ast_cid)
            assert (receipt is None) == (active_ast is None)
        assert catalog.store.stats()["size"] == 1


def test_foreign_partial_catalog_schema_is_rejected(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    with duckdb.connect(str(tmp_path / "foreign.duckdb"), config={"threads": 1}) as connection:
        connection.execute("CREATE SCHEMA codebase_control")
        connection.execute("CREATE TABLE codebase_control.heads (fake INTEGER)")
        with pytest.raises(CodebaseCatalogError, match="schema"):
            CodebaseCatalog(DuckDBASTStore(connection=connection), ImmutableCAS(tmp_path / "cas"))


def test_artifact_root_binding_cannot_change_after_restart(fixture):
    catalog, _, _, _, tmp_path = fixture
    with pytest.raises(CodebaseCatalogError, match="binding"):
        CodebaseCatalog(catalog.store, ImmutableCAS(tmp_path / "different"))


def test_head_bound_prevents_oversized_row_hydration(fixture):
    catalog, connection, candidate, _, _ = fixture
    publish(catalog, candidate(), "first")
    connection.execute("UPDATE codebase_control.heads SET manifest_cid=repeat('x', ?)", [catalog.limits.max_receipt_bytes + 1])
    with pytest.raises(CodebaseCatalogError, match="bound"):
        catalog.current("fixture")


def test_forged_schema_metadata_cannot_hide_removed_constraints(fixture):
    """A self-reported catalog hash cannot authenticate fake physical tables."""
    from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured

    catalog, connection, _, _, _ = fixture
    connection.execute("DROP TABLE codebase_control.heads")
    connection.execute("CREATE TABLE codebase_control.heads (repository_id VARCHAR NOT NULL, generation BIGINT NOT NULL, manifest_cid VARCHAR NOT NULL, snapshot_cid VARCHAR NOT NULL, ast_revision_id VARCHAR NOT NULL, receipt_cid VARCHAR NOT NULL)")
    rows = connection.execute("SELECT table_name, sql FROM duckdb_tables() WHERE schema_name='codebase_control' ORDER BY table_name").fetchall()
    connection.execute("UPDATE codebase_control.meta SET catalog_cid=?", [cid_for_structured([list(row) for row in rows])])
    with pytest.raises(CodebaseCatalogError, match="constraints"):
        CodebaseCatalog(catalog.store, catalog.artifacts)
