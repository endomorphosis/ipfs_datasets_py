"""Genuine native receiving controls for operation-local inventory resolution.

Small filesystem fixtures use real source capture, SQL, AST replay and CAS;
there are no source-observation doubles, model calls or training. Resource
admission is explicitly isolated within 2 CPU / 2048 MiB / one child slot.
"""
from dataclasses import replace
import threading
from types import SimpleNamespace

import duckdb
import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
from ipfs_datasets_py.logic.software_contracts import codebase_ir as module
from ipfs_datasets_py.logic.software_contracts.codebase_resources import acquire_codebase_resources
from ipfs_datasets_py.logic.software_contracts.cache import CacheIntegrityError, ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import (
    ASTS_CATALOG_TABLES, DuckDBASTStore, DuckDBASTStoreIntegrityError,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, LeaseCancelledError, LeaseTimeoutError, ResourceSchedulerConfig,
)

VIEW = "repository:linear-observation-control"
LIMITS = module.CodebaseScanLimits(max_entries=32, max_file_bytes=1024)


@pytest.fixture
def native(tmp_path):
    connections, schedulers = [], []

    def create(count=3, *, optimized=True):
        directory = tmp_path / str(len(connections))
        directory.mkdir()
        repository = directory / "repository"
        repository.mkdir()
        for number in range(count):
            (repository / f"unit{number:02d}.py").write_text(
                f"def step{number}(n: int) -> int:\n    return n + {number + 1}\n")
        scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
            state_path=directory / "scheduler.json",
            proof_resource_sampler=lambda: ProofHostResources(2, 2048, 2048),
            total_cpu_slots=2, total_memory_mb=2048, total_child_process_slots=1,
            total_gpu_memory_mb=None, total_unified_memory_mb=None,
            proof_memory_headroom_mb=0, lane_reservations={},
            auto_renew_leases=False, proof_backoff_seconds=0,
            poll_interval_seconds=0.005,
        ))
        schedulers.append(scheduler)
        connection = duckdb.connect(str(directory / "source.duckdb"),
                                    config={"threads": 1, "memory_limit": "128MB"})
        connections.append(connection)
        store = DuckDBASTStore(connection=connection)
        artifacts = ImmutableCAS(directory / "source-artifacts")
        index = module.RepositoryCodebaseIndex(
            ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
            catalog=CodebaseCatalog(store, artifacts),
            optimized_observation=optimized,
        )
        publication = index.prepare_current(
            repository, repository_id=VIEW, operation_id="initial", expected_head=None,
            scheduler=scheduler, memory_mb=64, limits=LIMITS,
            timeout_seconds=30, admission_timeout_seconds=2,
        )
        return SimpleNamespace(index=index, connection=connection, repository=repository,
                               scheduler=scheduler, head=publication.head, count=count)

    try:
        yield create
    finally:
        for connection in connections:
            connection.close()
        for scheduler in schedulers:
            state = scheduler.snapshot()
            assert state["active_lease_count"] == state["waiting_request_count"] == 0


def observe(native, **controls):
    return native.index.observe_current(
        native.repository, expected_head=native.head, scheduler=native.scheduler,
        memory_mb=64, timeout_seconds=30, admission_timeout_seconds=2, **controls,
    )


def native_rows(native):
    tables = tuple(ASTS_CATALOG_TABLES) + ("codebase_control.heads", "codebase_control.operations")
    return {name: sorted(native.connection.execute("SELECT * FROM " + ".".join(
                '"' + part + '"' for part in name.split("."))).fetchall(), key=repr)
            for name in tables}


def first_member(native):
    manifest = native.index.load(native.head.manifest_cid)
    entry = manifest.snapshot.entries[0]
    unit = next(unit for unit in manifest.units if unit.source_key == entry.source_key)
    return manifest, entry, unit


@pytest.mark.parametrize("count", [3, 17])
@pytest.mark.parametrize("optimized", [True, False])
def test_fresh_observations_hash_inventory_constantly_and_replay_every_member(native, monkeypatch, count, optimized):
    current = native(count, optimized=optimized)
    real_load = current.index.load
    real_property = RepositorySnapshot.snapshot_cid
    real_source = current.index.artifacts.get_bytes
    real_ast = current.index.artifacts.get
    real_sql = current.index.ingestor.store.get_by_ast_cid
    real_lookup = current.index.lookup
    real_ast_lookup = current.index.load_ast_artifact
    calls, source_reads, ast_reads, sql_reads = {}, [], [], []
    public_lookups, public_ast_lookups = [], []

    def counted(snapshot):
        if id(snapshot) in calls:
            calls[id(snapshot)] += 1
        return real_property.fget(snapshot)

    loaded = []

    def load(cid):
        manifest = real_load(cid)
        calls[id(manifest.snapshot)] = 0
        loaded.append(manifest)
        return manifest

    def source(cid):
        source_reads.append(cid)
        return real_source(cid)

    def artifact(cid, **kwargs):
        if kwargs.get("expected_schema") != module.CODEBASE_IR_SCHEMA:
            ast_reads.append(cid)
        return real_ast(cid, **kwargs)

    def sql(cid):
        sql_reads.append(cid)
        return real_sql(cid)

    def lookup(manifest, path):
        public_lookups.append(path)
        return real_lookup(manifest, path)

    def ast_lookup(manifest, path):
        public_ast_lookups.append(path)
        return real_ast_lookup(manifest, path)

    monkeypatch.setattr(RepositorySnapshot, "snapshot_cid", property(counted))
    monkeypatch.setattr(current.index, "load", load)
    monkeypatch.setattr(current.index.artifacts, "get_bytes", source)
    monkeypatch.setattr(current.index.artifacts, "get", artifact)
    monkeypatch.setattr(current.index.ingestor.store, "get_by_ast_cid", sql)
    monkeypatch.setattr(current.index, "lookup", lookup)
    monkeypatch.setattr(current.index, "load_ast_artifact", ast_lookup)
    before = native_rows(current)
    first, second = observe(current), observe(current)
    assert first == second
    assert len(loaded) == 2 and loaded[0] is not loaded[1]
    # Count after each freshly verified load: initial binding and final fence.
    expected_hashes = 2 if optimized else count + 2
    assert [calls[id(manifest.snapshot)] for manifest in loaded] == [expected_hashes] * 2
    assert len(source_reads) == len(ast_reads) == len(sql_reads) == count * 2
    assert len(public_lookups) == len(public_ast_lookups) == (0 if optimized else count * 2)
    assert native_rows(current) == before


def test_observation_matches_public_member_replay_and_current_capture(native):
    current = native()
    before = native_rows(current)
    manifest = current.index.load(current.head.manifest_cid)
    for entry in manifest.snapshot.entries:
        current.index.artifacts.get_bytes(entry.source_cid)
        assert current.index.lookup(manifest, entry.path).ast_cid == (
            current.index.load_ast_artifact(manifest, entry.path).cid)
    captured = module.snapshot_repository(
        current.repository, repository_id=VIEW, max_entries=LIMITS.max_entries,
        max_file_bytes=LIMITS.max_file_bytes, exclusions=manifest.snapshot.exclusions,
    )
    optimized_result = observe(current)
    current.index.optimized_observation = False
    reference_result = observe(current)
    assert optimized_result == reference_result
    assert optimized_result.head == current.head and optimized_result.manifest == manifest
    assert captured.snapshot_cid == current.head.snapshot_cid
    assert native_rows(current) == before


@pytest.mark.parametrize("value", [0, None, "true"])
def test_malformed_optimization_flag_rejected_before_constructor_side_effects(monkeypatch, value):
    def forbidden(*args, **kwargs):
        pytest.fail("malformed optimization flag constructed a native owner")
    monkeypatch.setattr(module, "DuckDBASTIngestor", forbidden)
    with pytest.raises(module.CodebaseIRError, match="exact bool"):
        module.RepositoryCodebaseIndex(optimized_observation=value)


@pytest.mark.parametrize("value", [0, None, "true"])
def test_changed_malformed_optimization_flag_rejected_before_admission(native, monkeypatch, value):
    from ipfs_datasets_py.logic.software_contracts import codebase_resources
    current = native()
    current.index.optimized_observation = value
    def forbidden(*args, **kwargs):
        pytest.fail("malformed optimization flag reached resource admission")
    monkeypatch.setattr(codebase_resources, "acquire_codebase_resources", forbidden)
    with pytest.raises(module.CodebaseIRError, match="exact bool"):
        observe(current)


def test_public_ast_method_recomputes_snapshot_once_per_call(native, monkeypatch):
    current = native()
    manifest, entry, _ = first_member(current)
    real_property = RepositorySnapshot.snapshot_cid
    calls = []

    def counted(snapshot):
        if snapshot is manifest.snapshot:
            calls.append(snapshot)
        return real_property.fget(snapshot)

    monkeypatch.setattr(RepositorySnapshot, "snapshot_cid", property(counted))
    first = current.index.load_ast_artifact(manifest, entry.path)
    second = current.index.load_ast_artifact(manifest, entry.path)
    assert first == second and len(calls) == 2


@pytest.mark.parametrize("kind", ["source", "ast", "manifest"])
def test_each_observation_rereads_and_refuses_corrupted_cas(native, kind):
    current = native()
    observe(current)
    manifest, entry, unit = first_member(current)
    target = (current.index.artifacts.path_for(entry.source_cid, source=True) if kind == "source"
              else current.index.artifacts.path_for(unit.ast_cid if kind == "ast" else manifest.cid))
    target.write_bytes(b"corrupted native evidence")
    before = native_rows(current)
    with pytest.raises(CacheIntegrityError):
        observe(current)
    assert native_rows(current) == before


@pytest.mark.parametrize("kind", ["alter-symbol", "missing-ast", "invalidate"])
def test_each_observation_replays_native_sql_integrity(native, kind):
    current = native()
    observe(current)
    manifest, entry, unit = first_member(current)
    projection = current.index.lookup(manifest, entry.path)
    if kind == "alter-symbol":
        current.connection.execute("UPDATE symbols SET name='tampered' WHERE blob_id=?", [projection.blob_id])
        expected = DuckDBASTStoreIntegrityError
    elif kind == "missing-ast":
        current.connection.execute("DELETE FROM ast_blobs WHERE ast_cid=?", [unit.ast_cid])
        expected = module.CodebaseIRError
    else:
        current.index.ingestor.store.invalidate(blob_id=projection.blob_id, reason="manual")
        expected = module.CodebaseIRError
    before = native_rows(current)
    with pytest.raises(expected):
        observe(current)
    assert native_rows(current) == before


def test_public_ast_replay_rejects_valid_cas_with_another_snapshot_provenance(native):
    current = native()
    manifest, entry, unit = first_member(current)
    record = current.index.load_ast_artifact(manifest, entry.path)
    foreign_cid = cid_for_structured({"schema": "foreign-snapshot-control@1"})
    foreign = replace(record, provenance=replace(
        record.provenance, revision="snapshot:" + foreign_cid, repository_tree_cid=foreign_cid))
    foreign_ast_cid = current.index.artifacts.put(foreign.to_dict())
    changed_unit = replace(unit, ast_cid=foreign_ast_cid)
    changed_manifest = replace(manifest, units=tuple(
        changed_unit if item.source_key == unit.source_key else item for item in manifest.units))
    before = native_rows(current)
    with pytest.raises(module.CodebaseIRError, match="AST artifact does not match"):
        current.index.load_ast_artifact(changed_manifest, entry.path)
    assert native_rows(current) == before


@pytest.mark.parametrize("kind", ["edit", "add", "delete"])
def test_fresh_source_drift_is_not_hidden_by_local_inventory_identity(native, kind):
    current = native()
    observe(current)
    path = current.repository / "unit00.py"
    if kind == "edit":
        path.write_text("def changed(n):\n    return n + 99\n")
    elif kind == "add":
        (current.repository / "added.py").write_text("answer = 42\n")
    else:
        path.unlink()
    before = native_rows(current)
    with pytest.raises(module.StaleCodebaseError):
        observe(current)
    assert native_rows(current) == before


@pytest.mark.parametrize("during", [False, True])
def test_catalog_successor_is_refused_before_or_at_final_fence(native, monkeypatch, during):
    current = native()
    manifest = current.index.load(current.head.manifest_cid)
    projections = tuple(current.index.lookup(manifest, entry.path) for entry in manifest.snapshot.entries)

    def advance():
        # Genuine native CAS/head transaction over already prepared evidence.
        # The during case uses the live observation's admitted CPU/memory;
        # it neither opens an independent resource pool nor launches a child.
        return current.index.catalog.publish(
            operation_id="successor", manifest=manifest, expected_head=current.head,
            projections=projections,
        )

    if during:
        original = module.snapshot_repository
        armed = [True]

        def captured_then_advance(*args, **kwargs):
            captured = original(*args, **kwargs)
            if armed[0]:
                armed[0] = False
                advance()
            return captured

        monkeypatch.setattr(module, "snapshot_repository", captured_then_advance)
    else:
        with acquire_codebase_resources(scheduler=current.scheduler, memory_mb=64, timeout_seconds=2):
            advance()
    with pytest.raises(module.StaleCodebaseError, match="catalog head changed"):
        observe(current)
    assert current.index.current(VIEW).generation == current.head.generation + 1


def test_final_fence_refuses_in_memory_inventory_mutation(native, monkeypatch):
    current = native()
    original_load, original_source = current.index.load, current.index.artifacts.get_bytes
    loaded = []

    def load(cid):
        manifest = original_load(cid)
        loaded.append(manifest)
        return manifest

    def changed_after_read(cid):
        raw = original_source(cid)
        object.__setattr__(loaded[0].snapshot, "max_entries", LIMITS.max_entries + 1)
        return raw

    monkeypatch.setattr(current.index, "load", load)
    monkeypatch.setattr(current.index.artifacts, "get_bytes", changed_after_read)
    before = native_rows(current)
    with pytest.raises(module.CodebaseIRError, match="captured snapshot changed"):
        observe(current)
    assert native_rows(current) == before


@pytest.mark.parametrize("stage", ["member", "close"])
@pytest.mark.parametrize("failure", ["cancel", "deadline"])
def test_member_and_final_checkpoints_refuse_and_release_native_lease(native, monkeypatch, stage, failure):
    current = native()
    cancelled = threading.Event()
    clock = [module.time.monotonic()]
    if failure == "deadline":
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def refuse():
        if failure == "cancel":
            cancelled.set()
        else:
            clock[0] += 31

    if stage == "member":
        original = current.index.artifacts.get_bytes

        def after_member(cid):
            raw = original(cid)
            refuse()
            return raw

        monkeypatch.setattr(current.index.artifacts, "get_bytes", after_member)
    else:
        original = module.snapshot_repository

        def after_capture(*args, **kwargs):
            captured = original(*args, **kwargs)
            refuse()
            return captured

        monkeypatch.setattr(module, "snapshot_repository", after_capture)
    before = native_rows(current)
    expected = LeaseCancelledError if failure == "cancel" else LeaseTimeoutError
    with pytest.raises(expected):
        observe(current, cancel_event=cancelled)
    assert native_rows(current) == before
    assert current.scheduler.snapshot()["active_lease_count"] == 0
