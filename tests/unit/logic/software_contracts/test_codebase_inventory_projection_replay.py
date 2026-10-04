"""Real native DuckDB row replay controls; no Git jobs, inference or fitting.

Fixtures publish explicit in-memory captured bytes through the genuine native
AST ingestor/catalog/CAS. They test relational receiving equality, not live
checkout freshness or a large inference qualification.
"""
from dataclasses import replace
from copy import deepcopy
import json
import time

import pytest
import duckdb

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_projection_replay as batch
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.ast_ir import SourceProvenance
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseIRManifest, CodebaseUnit, RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    DuckDBASTStore, DuckDBASTStoreIntegrityError, project_parse_failure,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot, SnapshotEntry
from ipfs_datasets_py.logic.software_contracts import codebase_ir_targets as adapter
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as scan
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_resume_worker as worker


@pytest.fixture
def native(tmp_path):
    owners = []
    def make(count=3, *, include_failure=True):
        directory = tmp_path / str(len(owners))
        directory.mkdir()
        connection = duckdb.connect(str(directory / "source.duckdb"), config={"threads": 1, "memory_limit": "128MB"})
        owners.append(connection)
        store = DuckDBASTStore(connection=connection)
        artifacts = ImmutableCAS(directory / "cas")
        ingestor = DuckDBASTIngestor(store=store)
        index = RepositoryCodebaseIndex(ingestor=ingestor, artifacts=artifacts, catalog=CodebaseCatalog(store, artifacts))
        sources = {f"unit{number:02d}.py": (
            f"from other import helper\nshared = 0\ndef step{number}(n: int) -> int:\n"
            "    global shared\n    shared = n\n    return helper(n) + 1\n").encode() for number in range(count)}
        if include_failure:
            sources["broken.py"] = b"def broken(:\n"
        entries = tuple(SnapshotEntry(path, "source", len(raw), cid_for_bytes(raw), captured_bytes=raw)
                        for path, raw in sources.items())
        snapshot = RepositorySnapshot("native-batch", entries, "filesystem", 65536, 64)
        state = RepositoryScanner(repository_id="native-batch").scan_snapshot(snapshot, sources)
        sealed, receipts, projected = [], [], []
        def seal(publication):
            # Exercise the native intrinsic diagnostic/invalidation branch too.
            # The scanner's ordinary failed ASTRecord has no intrinsic row.
            actual = tuple(project_parse_failure(provenance=SourceProvenance(
                source_cid=row.source_cid, path=row.source_file.path,
                repository_id=publication.repository_id, revision=publication.revision,
                repository_tree_cid=publication.repository_tree_cid),
                language="python", message="fixture parser failure", created_at=1.0)
                if row.source_file.path == "broken.py" else row for row in publication.projections)
            projected.append(actual)
            by_path = {row.source_file.path: row for row in actual}
            units = tuple(CodebaseUnit(entry.source_key, entry.entry_cid,
                by_path[entry.path].ast_cid, by_path[entry.path].ast_blob.parse_status) for entry in snapshot.entries)
            manifest = CodebaseIRManifest(snapshot, state, publication.revision_id, units)
            for raw in sources.values():
                artifacts.put_bytes(raw)
            for projection in actual:
                artifacts.put(json.loads(projection.ast_blob.payload_json))
            artifacts.put(manifest.to_dict())
            sealed.append(manifest)
        def publish(publication):
            receipts.append(index.catalog.publish(operation_id="fixture", manifest=sealed[0], expected_head=None,
                projections=projected[0]))
        publication = ingestor.ingest_snapshot(snapshot, created_at=1.0, before_publish=seal, publish_batch=publish)
        publication = replace(publication, projections=projected[0])
        return index, sealed[0], receipts[0].head, connection, publication
    yield make
    for connection in owners:
        connection.close()


@pytest.mark.parametrize("field", tuple(batch.CodebaseProjectionReplayLimits.__dataclass_fields__))
@pytest.mark.parametrize("value", [0, -1, True, 1.0])
def test_exact_finite_limits(field, value):
    with pytest.raises(batch.CodebaseProjectionReplayError):
        replace(batch.CodebaseProjectionReplayLimits(), **{field: value})


def test_real_native_batched_rows_equal_legacy_lookup_without_owner_mutation(native, record_property):
    index, manifest, head, connection, publication = native(17)
    before = {table: connection.execute('SELECT * FROM "' + table + '" ORDER BY ALL').fetchall()
              for table in batch.ASTS_CATALOG_TABLES}
    expected = {item.source_file.path: item for item in publication.projections}
    legacy_started = time.monotonic()
    for entry in manifest.snapshot.entries:
        assert index.lookup(manifest, entry.path) == expected[entry.path]
    legacy_elapsed = time.monotonic() - legacy_started
    started = time.monotonic()
    receipt = batch.replay_current_inventory_projections(index, manifest, expected_head=head)
    elapsed = time.monotonic() - started
    assert receipt.selected_blobs == receipt.replayed_blobs == 18
    assert receipt.batches == 2 and receipt.preflights == 2 and receipt.metadata_queries == 4
    assert receipt.body_queries == 26
    assert receipt.schema_queries == 4
    assert receipt.largest_batch_bytes <= 32 * 1024 * 1024
    assert receipt.to_dict()["source_execution_attested"] is False
    record_property("native_fixture_members", 18)
    record_property("native_legacy_lookup_seconds", legacy_elapsed)
    record_property("native_batch_replay_seconds", elapsed)
    record_property("native_batch_replay_receipt", json.dumps(receipt.to_dict(), sort_keys=True))
    assert before == {table: connection.execute('SELECT * FROM "' + table + '" ORDER BY ALL').fetchall()
                      for table in batch.ASTS_CATALOG_TABLES}


@pytest.mark.parametrize("table,field", [
    ("source_revisions", "revision"), ("source_files", "path"), ("ast_blobs", "parse_error"),
    ("ast_nodes", "label"), ("scopes", "kind"), ("symbols", "name"), ("imports", "module"),
    ("references", "name"), ("calls", "callee_name"), ("effects", "subject"),
    ("interfaces", "name"), ("diagnostics", "message"), ("invalidations", "detail"),
])
def test_every_native_relational_family_refuses_row_tampering(native, table, field):
    index, manifest, head, connection, _ = native()
    assert connection.execute('SELECT count(*) FROM "' + table + '"').fetchone()[0] > 0
    connection.execute('UPDATE "' + table + '" SET "' + field + '"=\'tampered\'')
    with pytest.raises(DuckDBASTStoreIntegrityError):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head)


@pytest.mark.parametrize("table", batch.ASTS_CATALOG_TABLES)
def test_every_native_relational_family_refuses_missing_rows(native, table):
    index, manifest, head, connection, _ = native()
    connection.execute('DELETE FROM "' + table + '"')
    with pytest.raises(DuckDBASTStoreIntegrityError):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head)


def test_real_duplicate_ast_cid_lookup_is_ambiguous_and_refused(native):
    index, manifest, head, connection, _ = native()
    connection.execute("INSERT INTO ast_blobs SELECT blob_id || ':duplicate',* EXCLUDE(blob_id) FROM ast_blobs LIMIT 1")
    with pytest.raises(batch.CodebaseProjectionReplayError, match="ambiguous"):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head)


def test_real_extra_relation_row_and_extra_schema_column_are_refused(native):
    index, manifest, head, connection, _ = native()
    connection.execute("INSERT INTO scopes SELECT scope_row_id || ':extra',* EXCLUDE(scope_row_id) FROM scopes LIMIT 1")
    with pytest.raises(batch.CodebaseProjectionReplayError, match="scopes"):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head)
    index, manifest, head, connection, _ = native()
    connection.execute("ALTER TABLE ast_blobs ADD COLUMN foreign_field VARCHAR DEFAULT 'foreign'")
    with pytest.raises(batch.CodebaseProjectionReplayError, match="columns"):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head)


def test_native_invalidation_removes_active_projection_and_refuses_manifest(native):
    index, manifest, head, _, publication = native()
    index.ingestor.store.invalidate(blob_id=publication.projections[0].blob_id, reason="manual", actor_id="test")
    with pytest.raises(batch.CodebaseProjectionReplayError, match="missing"):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head)


def test_native_payload_preflight_refuses_oversize_before_body_fetch(native, monkeypatch):
    index, manifest, head, connection, _ = native()
    connection.execute("UPDATE ast_blobs SET payload_json=repeat('x',33554433) WHERE ast_cid=?", [manifest.units[0].ast_cid])
    monkeypatch.setattr(batch, "_bodies", lambda *args: pytest.fail("oversized SQL payload reached body fetch"))
    with pytest.raises(batch.CodebaseProjectionReplayError, match="individual"):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head)


def test_native_row_preflight_splits_batches_without_skipping_members(native):
    index, manifest, head, _, _ = native(3)
    reference = batch.replay_current_inventory_projections(index, manifest, expected_head=head,
        limits=batch.CodebaseProjectionReplayLimits(max_blobs=1))
    bounded = batch.replay_current_inventory_projections(index, manifest, expected_head=head,
        limits=batch.CodebaseProjectionReplayLimits(max_rows=reference.largest_batch_rows))
    assert bounded.selected_blobs == bounded.replayed_blobs == 4
    assert bounded.preflights > bounded.batches
    assert bounded.batches == 4 and bounded.body_queries == 52
    assert bounded.largest_batch_rows <= reference.largest_batch_rows


def test_real_canonical_payload_byte_change_is_refused(native):
    index, manifest, head, connection, _ = native()
    connection.execute("UPDATE ast_blobs SET payload_json=' ' || payload_json")
    with pytest.raises(batch.CodebaseProjectionReplayError, match="payload"):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head)


def test_native_batch_current_head_and_owner_substitution_are_refused(native):
    index, manifest, head, connection, _ = native()
    connection.execute("UPDATE codebase_control.heads SET generation=generation+1")
    with pytest.raises(ValueError):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head)
    index, manifest, head, _, _ = native()
    index.catalog.artifacts = ImmutableCAS(index.artifacts.root / "foreign")
    with pytest.raises(batch.CodebaseProjectionReplayError, match="owner"):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head)


def test_native_batch_cancellation_callback_closes_owned_transaction(native):
    index, manifest, head, connection, _ = native()
    calls = []
    def cancel():
        calls.append(1)
        if len(calls) == 4:
            raise RuntimeError("controlled cancellation")
    with pytest.raises(RuntimeError, match="cancellation"):
        batch.replay_current_inventory_projections(index, manifest, expected_head=head, checkpoint=cancel)
    assert connection.execute("SELECT 1").fetchone() == (1,)
    # An independent transaction succeeds, demonstrating rollback/release.
    connection.execute("BEGIN TRANSACTION")
    connection.execute("ROLLBACK")


def test_real_native_worker_replay_reuse_matches_reference_binding_and_rejects_forged_bytes(native, monkeypatch):
    """Genuine adapter replay only; this does not qualify worker inference."""
    index, manifest, head, _, _ = native()
    target = adapter.prepare_codebase_targets(index, expected_head=head, path="unit00.py")
    value = target.to_dict()
    untouched = deepcopy(value)
    real_validate, calls = adapter.validate_codebase_targets, []
    def observed_validate(envelope):
        calls.append(envelope.canonical_bytes)
        return real_validate(envelope)
    monkeypatch.setattr(adapter, "validate_codebase_targets", observed_validate)
    optimized = worker._replay_target(value, True)
    assert len(calls) == 1
    calls.clear()
    reference = worker._replay_target(value, False)
    assert len(calls) == 2
    assert optimized[0].canonical_bytes == reference[0].canonical_bytes == target.canonical_bytes
    assert optimized[1:] == reference[1:] and value == untouched
    binding = optimized[2]
    assert binding["head"] == head.to_dict()
    member = next(entry for entry in manifest.snapshot.entries if entry.path == "unit00.py")
    assert binding["entry"]["entry_cid"] == member.entry_cid and binding["source_cid"] == member.source_cid
    binding["head"]["generation"] += 1
    assert value == untouched and optimized[0].canonical_bytes == target.canonical_bytes
    forged = deepcopy(value)
    forged["validation"][0]["details"]["source_binding"]["head"]["generation"] += 1
    with pytest.raises(adapter.CodebaseTargetError):
        worker._replay_target(forged, True)


@pytest.mark.parametrize("optimized", [True, False])
def test_native_observe_keeps_cas_replay_and_chooses_default_batch_or_optout_lookup(native, monkeypatch, optimized):
    """Native SQL/CAS equality; checkout observation is an explicit fixture double."""
    index, manifest, head, _, _ = native(include_failure=False)
    real_batch, real_lookup = batch.replay_current_inventory_projections, RepositoryCodebaseIndex.lookup
    batches, lookups, members = [], [], []
    def observed_batch(*args, **kwargs):
        batches.append(real_batch(*args, **kwargs))
        return batches[-1]
    def observed_lookup(owner, captured, path):
        lookups.append(path)
        return real_lookup(owner, captured, path)
    real_member = scan._member_native
    def observed_member(*args, **kwargs):
        members.append(args[2].source_key)
        return real_member(*args, **kwargs)
    monkeypatch.setattr(batch, "replay_current_inventory_projections", observed_batch)
    monkeypatch.setattr(RepositoryCodebaseIndex, "lookup", observed_lookup)
    monkeypatch.setattr(scan, "_member_native", observed_member)
    monkeypatch.setattr(scan, "snapshot_repository", lambda *args, **kwargs: manifest.snapshot)
    kwargs = {} if optimized else {"optimized": False}
    observed, receipt = scan._observe(index, ".", head, scan.CodebaseScanResumeLimits(), lambda: 30, 1024, **kwargs)
    assert observed == manifest and receipt.head == head
    assert members == [entry.source_key for entry in manifest.snapshot.entries]
    assert len(batches) == int(optimized)
    assert lookups == ([] if optimized else [entry.path for entry in manifest.snapshot.entries])
    entry = manifest.snapshot.entries[0]
    index.artifacts.path_for(entry.source_cid, source=True).write_bytes(b"corrupted cached source")
    with pytest.raises(ValueError):
        scan._observe(index, ".", head, scan.CodebaseScanResumeLimits(), lambda: 30, 1024, **kwargs)


def native_snapshot_property_observer(monkeypatch):
    """Instrument the genuine immutable snapshot property, preserving its work."""
    original_property, original_load = RepositorySnapshot.snapshot_cid, RepositoryCodebaseIndex.load
    observed, loaded = {}, []
    def counted(snapshot):
        if id(snapshot) in observed:
            observed[id(snapshot)] += 1
        return original_property.fget(snapshot)
    def tracked_load(owner, artifact_cid):
        manifest = original_load(owner, artifact_cid)
        observed[id(manifest.snapshot)] = 0
        loaded.append(manifest)
        return manifest
    monkeypatch.setattr(RepositorySnapshot, "snapshot_cid", property(counted))
    monkeypatch.setattr(RepositoryCodebaseIndex, "load", tracked_load)
    return observed, loaded


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("count", [3, 17])
def test_native_observation_hashes_full_snapshot_a_constant_number_by_default(native, monkeypatch, optimized, count):
    """Real source/CAS/AST work; only fresh checkout capture is doubled."""
    index, manifest, head, _, _ = native(count, include_failure=False)
    observed, loaded = native_snapshot_property_observer(monkeypatch)
    monkeypatch.setattr(scan, "snapshot_repository", lambda *args, **kwargs: manifest.snapshot)
    current, receipt = scan._observe(index, ".", head, scan.CodebaseScanResumeLimits(), lambda: 30, 1024,
                                     optimized=optimized)
    assert current == manifest and receipt.head == head
    # Fresh load/manifest/canonical-byte/head checks still run. Only the two
    # full-inventory property calls per native AST are removed by default.
    assert len(loaded) == 1
    assert observed[id(current.snapshot)] == (7 if optimized else 5 + 2 * count)


@pytest.mark.parametrize("optimized", [True, False])
def test_native_historical_replay_hashes_once_for_all_members_and_closes_identity(native, monkeypatch, optimized):
    index, manifest, historical, _, publication = native(5, include_failure=False)
    current = index.catalog.publish(operation_id="advance", manifest=manifest, expected_head=historical,
                                    projections=publication.projections).head
    assert current.generation == historical.generation + 1
    observed, loaded = native_snapshot_property_observer(monkeypatch)
    # This control does not fit/qualify a model: lineage selection is explicit.
    monkeypatch.setattr(scan.legacy, "_history_heads", lambda chain: [historical])
    scan._history_fence(index, [], current, scan.CodebaseScanResumeLimits(), lambda: 30, optimized=optimized)
    assert len(loaded) == 1 and loaded[0] == manifest
    assert observed[id(loaded[0].snapshot)] == (3 if optimized else 3 + 2 * 5)
    assert index.current(current.repository_id) == current
    entry = manifest.snapshot.entries[0]
    index.artifacts.path_for(entry.source_cid, source=True).write_bytes(b"corrupted historical source")
    with pytest.raises(ValueError):
        scan._history_fence(index, [], current, scan.CodebaseScanResumeLimits(), lambda: 30, optimized=optimized)


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("historical", [False, True])
def test_native_same_local_manifest_mutation_cannot_hide_behind_reused_snapshot_cid(native, monkeypatch, optimized, historical):
    index, manifest, head, _, publication = native(include_failure=False)
    current = head
    if historical:
        current = index.catalog.publish(operation_id="advance", manifest=manifest, expected_head=head,
                                        projections=publication.projections).head
        monkeypatch.setattr(scan.legacy, "_history_heads", lambda chain: [head])
    observed, loaded = native_snapshot_property_observer(monkeypatch)
    monkeypatch.setattr(scan, "snapshot_repository", lambda *args, **kwargs: manifest.snapshot)
    real_member, mutated = scan._member_native, []
    def mutate_after_real_member(*args, **kwargs):
        result = real_member(*args, **kwargs)
        if not mutated:
            # Deliberately breach frozen native metadata after its validation;
            # the same-object closing hash must refuse this local substitution.
            object.__setattr__(args[1].snapshot, "exclusions", ("forged-exclusion",))
            mutated.append(True)
        return result
    monkeypatch.setattr(scan, "_member_native", mutate_after_real_member)
    with pytest.raises(scan.CodebaseScanResumeError, match="manifest changed|bindings differ"):
        if historical:
            scan._history_fence(index, [], current, scan.CodebaseScanResumeLimits(), lambda: 30, optimized=optimized)
        else:
            scan._observe(index, ".", head, scan.CodebaseScanResumeLimits(), lambda: 30, 1024, optimized=optimized)
    assert mutated and loaded
    assert index.current(current.repository_id) == current
    # The mutation affected this ephemeral Python object, never immutable CAS.
    assert RepositoryCodebaseIndex.load(index, head.manifest_cid) == manifest


@pytest.mark.parametrize("optimized", [True, False])
def test_native_same_manifest_closing_guard_follows_fresh_checkout_observation(native, monkeypatch, optimized):
    index, manifest, head, _, _ = native(include_failure=False)
    _, loaded = native_snapshot_property_observer(monkeypatch)
    def capture_and_mutate(*args, **kwargs):
        assert len(loaded) == 1
        object.__setattr__(loaded[0].snapshot, "exclusions", ("late-capture-substitution",))
        return manifest.snapshot
    monkeypatch.setattr(scan, "snapshot_repository", capture_and_mutate)
    with pytest.raises(scan.CodebaseScanResumeError, match="manifest changed"):
        scan._observe(index, ".", head, scan.CodebaseScanResumeLimits(), lambda: 30, 1024, optimized=optimized)
    assert index.current(head.repository_id) == head
