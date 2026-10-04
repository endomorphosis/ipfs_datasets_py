"""Native tiny source/SQL/CAS deltas and pure receiving protocol controls.

No model registry, forward pass, fitting, isolated worker or large-repository
qualification occurs. Scheduler leases are real; the configured test scheduler
is not the separate conservative host-resource qualification profile.
"""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import threading

import duckdb
import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseCatalogLimits
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_successor as delta
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as scan
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, CodebaseScanLimits
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig, ResourceLane, LeaseCancelledError, LeaseTimeoutError)


@pytest.fixture(autouse=True)
def prohibit_model_and_numerical_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("source delta opened a model registry or executed numerical work")
    monkeypatch.setattr(AutoencoderRegistry, "__init__", forbidden)
    monkeypatch.setattr(scan.features, "train_projection_features", forbidden)
    monkeypatch.setattr(scan.features, "infer_projection_features", forbidden)
    monkeypatch.setattr(scan.training, "train_current_codebase_features", forbidden)
    monkeypatch.setattr(scan, "_worker", forbidden)


@pytest.fixture
def native(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    sources = {"keep.py": b"def keep(n: int) -> int:\n    return n + 1\n",
        "change.py": b"def change(n: int) -> int:\n    return n + 1\n",
        "remove.py": b"def remove(n: int) -> int:\n    return n + 1\n",
        "rename.py": b"def rename(n: int) -> int:\n    return n + 1\n",
        "note.txt": b"complete unindexed inventory member\n"}
    for path, raw in sources.items():
        (repo / path).write_bytes(raw)
    (repo / "opaque.py").symlink_to("absent-target")
    connection = duckdb.connect(str(tmp_path / "source.duckdb"), config={"threads": 1, "memory_limit": "128MB"})
    store = DuckDBASTStore(connection=connection)
    cas = ImmutableCAS(tmp_path / "cas")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=cas,
        catalog=CodebaseCatalog(store, cas, limits=CodebaseCatalogLimits(max_entries=32)))
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(total_cpu_slots=2, total_memory_mb=4096,
        total_child_process_slots=2, lane_reservations={}, state_path=tmp_path / "scheduler.json",
        auto_renew_leases=False))
    capture = CodebaseScanLimits(max_entries=16, max_file_bytes=4096)
    old = index.prepare_current(repo, repository_id="native-successor", operation_id="old", expected_head=None,
        limits=capture, scheduler=scheduler, memory_mb=1024)
    (repo / "change.py").write_bytes(b"def change(n: int) -> int:\n    return n + 2\n")
    (repo / "remove.py").unlink()
    (repo / "rename.py").rename(repo / "renamed.py")
    (repo / "added.py").write_bytes(b"def added(n: int) -> int:\n    return n + 3\n")
    new = index.prepare_current(repo, repository_id=old.repository_id, operation_id="new", expected_head=old.head,
        limits=capture, scheduler=scheduler, memory_mb=1024)
    fixture = SimpleNamespace(index=index, repo=repo, old=old, new=new, scheduler=scheduler,
        connection=connection, capture=capture)
    yield fixture
    assert scheduler.snapshot()["active_lease_count"] == 0
    connection.close()


def build(fixture, **kwargs):
    return delta.build_current_codebase_source_delta(fixture.index, fixture.repo,
        previous_head=fixture.old.head, expected_head=fixture.new.head, scheduler=fixture.scheduler, **kwargs)


def receive(fixture, record, **kwargs):
    return delta.validate_current_codebase_source_delta(record, fixture.index, fixture.repo,
        scheduler=fixture.scheduler, **kwargs)


def rehashed(value):
    return delta.CodebaseSourceDeltaRecord.from_dict(cid_for_structured(value), value)


def test_native_complete_union_default_reference_and_global_ast_rebind(native):
    record = build(native)
    value = record.to_dict()
    assert value["coverage"]["classifications"] == {"retained": 3, "changed": 1, "added": 2, "removed": 2}
    assert value["coverage"]["previous_entries"] == value["coverage"]["current_entries"] == 6
    assert value["coverage"]["union_entries"] == 8
    rows = {row["source_key"]: row for row in value["ledger"]}
    kept = rows["raw:" + b"keep.py".hex()]
    assert kept["classification"] == "retained" and kept["source_bytes_comparison"] == "equal"
    assert kept["ast_identity_comparison"] == "different"
    opaque = rows["raw:" + b"opaque.py".hex()]
    assert opaque["classification"] == "retained" and opaque["source_bytes_comparison"] == "unavailable"
    assert opaque["ast_identity_comparison"] == "unavailable"
    # A rename remains two exact path events, not an inferred correspondence.
    assert rows["raw:" + b"rename.py".hex()]["classification"] == "removed"
    assert rows["raw:" + b"renamed.py".hex()]["classification"] == "added"
    reference = build(native, optimized=False).to_dict()
    assert reference.pop("optimized") is False and value.pop("optimized") is True
    assert reference == value
    assert delta.load_codebase_source_delta(native.index.artifacts, record.artifact_cid)._payload == record._payload
    assert receive(native, record) is record
    detached = record.to_dict()
    detached["ledger"].clear()
    assert len(record.to_dict()["ledger"]) == 8


def test_native_historical_invalidated_ast_is_replayed_from_captured_cas(native):
    previous = native.index.load(native.old.manifest_cid)
    with pytest.raises(ValueError, match="invalidated"):
        native.index.lookup(previous, "keep.py")
    assert build(native).to_dict()["previous_head"] == native.old.head.to_dict()


@pytest.mark.parametrize("mutation", ["extra", "prefix", "duplicate", "order", "class", "comparison", "opaque",
    "member", "entry", "coverage", "coverage_bool", "membership", "receipt", "head", "numerical", "model", "authority",
    "physical_absence", "removal_scope"])
def test_pure_rehashed_constructor_rejects_incomplete_or_forged_protocol(native, mutation):
    value = build(native).to_dict()
    if mutation == "extra": value["latent"] = [0]
    elif mutation == "prefix": value["ledger"].pop()
    elif mutation == "duplicate": value["ledger"].append(deepcopy(value["ledger"][0]))
    elif mutation == "order": value["ledger"].reverse()
    elif mutation == "class": value["ledger"][0]["classification"] = "retained"
    elif mutation == "comparison": value["ledger"][0]["source_bytes_comparison"] = "equal"
    elif mutation == "opaque":
        next(row for row in value["ledger"] if row["source_key"] == "raw:" + b"opaque.py".hex())["source_bytes_comparison"] = "equal"
    elif mutation == "member":
        next(row["current"] for row in value["ledger"] if row["current"])["member"]["source_size_bytes"] += 1
    elif mutation == "entry":
        next(row["current"] for row in value["ledger"] if row["current"])["entry"]["size_bytes"] += 1
    elif mutation == "coverage": value["coverage"]["union_entries"] += 1
    elif mutation == "coverage_bool": value["coverage"]["classifications"]["changed"] = True
    elif mutation == "membership": value["current_membership_cid"] = value["previous_membership_cid"]
    elif mutation == "receipt": value["current_publication_receipt"]["previous_head"] = None
    elif mutation == "head": value["current_head"]["generation"] = True
    elif mutation == "numerical": value["numerical_reuse"] = 0
    elif mutation == "model": value["model_advanced"] = True
    elif mutation == "authority": value["authority"]["proof_authority"] = 0
    elif mutation == "physical_absence": value["physical_absence_verified"] = 0
    elif mutation == "removal_scope": value["removal_scope"] = "deleted_from_filesystem"
    with pytest.raises(ValueError):
        rehashed(value)


@pytest.mark.parametrize("part", ["old_source", "new_source", "old_ast", "new_ast", "record", "sql"])
def test_native_source_cas_and_relational_corruption_refused(native, part):
    record = build(native)
    path, original = None, None
    if part == "sql":
        row = native.connection.execute("SELECT symbol_row_id,name FROM symbols WHERE name='keep' ORDER BY symbol_row_id DESC LIMIT 1").fetchone()
        native.connection.execute("UPDATE symbols SET name='corrupted' WHERE symbol_row_id=?", [row[0]])
    else:
        manifest = native.index.load(native.old.manifest_cid if part.startswith("old") else native.new.manifest_cid)
        entry = next(entry for entry in manifest.snapshot.entries if entry.path == "change.py")
        unit = next(unit for unit in manifest.units if unit.source_key == entry.source_key)
        cid = record.artifact_cid if part == "record" else unit.ast_cid if part.endswith("ast") else entry.source_cid
        path = native.index.artifacts.path_for(cid, source=part.endswith("source"))
        original = path.read_bytes()
        path.write_bytes(original + b" ")
    try:
        with pytest.raises(ValueError): receive(native, record)
    finally:
        if path is not None: path.write_bytes(original)
        else: native.connection.execute("UPDATE symbols SET name=? WHERE symbol_row_id=?", [row[1], row[0]])
    assert receive(native, record) is record


def test_native_late_source_mutation_is_refused_by_closing_observation(native, monkeypatch):
    original_observe = delta._observe
    calls = []
    source = native.repo / "keep.py"
    original = source.read_bytes()
    def mutate(*args, **kwargs):
        result = original_observe(*args, **kwargs)
        calls.append(1)
        if len(calls) == 1:
            source.write_bytes(original + b"# mutation after entry\n")
        return result
    monkeypatch.setattr(delta, "_observe", mutate)
    try:
        with pytest.raises(ValueError, match="source|current"):
            build(native)
    finally:
        source.write_bytes(original)
    assert len(calls) == 1


def test_native_same_head_checkout_mutation_during_closing_cas_read_is_refused(native, monkeypatch):
    record = build(native)
    original_load, calls = delta.load_codebase_source_delta, []
    source = native.repo / "keep.py"
    original = source.read_bytes()
    def mutate(*args, **kwargs):
        loaded = original_load(*args, **kwargs)
        calls.append(1)
        if len(calls) == 2:
            source.write_bytes(original + b"# same catalog head, changed checkout\n")
        return loaded
    monkeypatch.setattr(delta, "load_codebase_source_delta", mutate)
    try:
        with pytest.raises(ValueError, match="source|current"):
            receive(native, record)
    finally:
        source.write_bytes(original)
    assert len(calls) == 2


def test_native_policy_change_and_non_immediate_previous_head_refused(native):
    newer = native.index.prepare_current(native.repo, repository_id=native.old.repository_id,
        operation_id="newer", expected_head=native.new.head, limits=CodebaseScanLimits(17, 4096),
        scheduler=native.scheduler, memory_mb=1024)
    with pytest.raises(ValueError, match="immediate"):
        delta.build_current_codebase_source_delta(native.index, native.repo, previous_head=native.old.head,
            expected_head=newer.head, scheduler=native.scheduler)
    with pytest.raises(ValueError, match="policy"):
        delta.build_current_codebase_source_delta(native.index, native.repo, previous_head=native.new.head,
            expected_head=newer.head, scheduler=native.scheduler)


@pytest.mark.parametrize("field", tuple(delta.CodebaseSourceDeltaLimits.__dataclass_fields__))
@pytest.mark.parametrize("bad", [0, -1, True, 1.0])
def test_pure_limits_require_positive_exact_bounded_integers(field, bad):
    with pytest.raises(ValueError): replace(delta.CodebaseSourceDeltaLimits(), **{field: bad})


@pytest.mark.parametrize("cap", ["inventory", "union", "manifest", "output"])
def test_native_serialized_and_union_bounds_are_not_partial_absence(native, cap):
    limits = delta.CodebaseSourceDeltaLimits()
    field = {"inventory": "max_inventory_entries", "union": "max_union_entries",
             "manifest": "max_manifest_bytes", "output": "max_delta_bytes"}[cap]
    limits = replace(limits, **{field: 1})
    with pytest.raises(ValueError): build(native, limits=limits)


@pytest.mark.parametrize("phase", ["cancel", "deadline", "success"])
def test_real_child_lease_and_one_deadline_release_on_all_paths(native, monkeypatch, phase):
    cancel = threading.Event()
    clock = [100.0]
    monkeypatch.setattr(delta, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    original_ledger = delta._ledger
    def checkpoint(*args):
        assert native.scheduler.snapshot()["active_child_lease_count"] == 1
        if phase == "cancel": cancel.set()
        elif phase == "deadline": clock[0] = 131.0
        return original_ledger(*args)
    monkeypatch.setattr(delta, "_ledger", checkpoint)
    with native.scheduler.acquire(lane=ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=2, memory_mb=2048,
            child_process_slots=2, timeout=1) as parent:
        options = dict(previous_head=native.old.head, expected_head=native.new.head, parent_lease=parent,
                       cancel_event=cancel, timeout_seconds=30)
        if phase == "success": delta.build_current_codebase_source_delta(native.index, native.repo, **options)
        else:
            with pytest.raises(LeaseCancelledError if phase == "cancel" else LeaseTimeoutError):
                delta.build_current_codebase_source_delta(native.index, native.repo, **options)
        assert native.scheduler.snapshot()["active_child_lease_count"] == 0 and not parent.released


def test_pure_prefix_or_scan_root_cannot_substitute_for_source_head(native):
    with pytest.raises(ValueError, match="heads"):
        delta.build_current_codebase_source_delta(native.index, native.repo,
            previous_head={"partial_prefix": 1}, expected_head=native.new.head, scheduler=native.scheduler)


def test_native_fully_rehashed_membership_omission_is_refused_by_receiving(native):
    value = build(native).to_dict()
    value["ledger"].pop()
    value["coverage"] = delta._coverage(value["ledger"])
    for side in ("previous", "current"):
        value[side + "_membership_cid"] = cid_for_structured(
            [row[side]["member"] for row in value["ledger"] if row[side] is not None])
    forged = rehashed(value)
    native.index.artifacts.put(value)
    with pytest.raises(ValueError, match="ledger"):
        receive(native, forged)
