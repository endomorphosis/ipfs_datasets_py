"""Native sequential chunks with real captured sources and numerical children.

The fixtures own bounded DuckDB, catalog, CAS, registry and a separate resource
pool. One setup epoch registers the model; scan and receiving assertions use
actual worker output. Fault injections run after genuine CAS publication and
never substitute a successful native observation or numerical result.
"""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_inventory_chunk_scan as scan
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_chunks as records
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as old
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as training
from ipfs_datasets_py.logic.software_contracts.cache import CacheIntegrityError, ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import (
    CodebaseScanLimits, RepositoryCodebaseIndex, StaleCodebaseError,
)
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStoreIntegrityError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError

MIB = 1024 * 1024


@pytest.fixture
def native(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    pytest.importorskip("torch")
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig,
    )

    owners = []

    def create(count=3):
        directory = tmp_path / str(len(owners))
        directory.mkdir()
        repository = directory / "repository"
        repository.mkdir()
        for number in range(count):
            (repository / f"unit{number:02d}.py").write_text(
                f"def step{number}(n: int) -> int:\n    return n + {number + 1}\n")
        scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
            state_path=directory / "admission.json",
            proof_resource_sampler=lambda: ProofHostResources(4, 4096, 4096),
            total_cpu_slots=4, total_memory_mb=4096, total_child_process_slots=4,
            total_gpu_memory_mb=None, total_unified_memory_mb=None,
            proof_memory_headroom_mb=0, lane_reservations={}, auto_renew_leases=False,
            proof_backoff_seconds=0, poll_interval_seconds=.005,
        ))
        connection = duckdb.connect(str(directory / "source.duckdb"),
                                    config={"threads": 1, "memory_limit": "128MB"})
        registry = None
        try:
            store = DuckDBASTStore(connection=connection)
            cas = ImmutableCAS(directory / "source-artifacts", max_object_bytes=16 * MIB)
            index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),
                artifacts=cas, catalog=CodebaseCatalog(store, cas))
            head = index.prepare_current(repository, repository_id="test:native-chunk-scan",
                operation_id="initial", expected_head=None, scheduler=scheduler,
                limits=CodebaseScanLimits(max_entries=32, max_file_bytes=1024),
                memory_mb=64, timeout_seconds=30, admission_timeout_seconds=2).head
            registry = AutoencoderRegistry(directory / "model.duckdb", directory / "model-artifacts")
            selections = [training.CodebaseTrainingSelection(f"unit{number:02d}.py", role)
                          for number, role in enumerate(("train", "tune", "canary"))]
            model = training.train_current_codebase_features(index, repository, expected_head=head,
                registry=registry, selections=selections, scheduler=scheduler,
                operation_id="setup", epochs=1, learning_rate=.002,
                timeout_seconds=120, admission_timeout_seconds=2, memory_mb=1024)
            current = SimpleNamespace(index=index, repository=repository, head=head, registry=registry,
                connection=connection, scheduler=scheduler, count=count, model=model,
                version_id=model.to_dict()["version_id"])
            owners.append(current)
            return current
        except BaseException:
            if registry is not None:
                registry.close()
            connection.close()
            raise

    try:
        yield create
    finally:
        for current in owners:
            try:
                state = current.scheduler.snapshot()
                assert state["active_lease_count"] == state["waiting_request_count"] == 0
            finally:
                current.registry.close()
                current.connection.close()


def options(current, **changes):
    value = dict(scheduler=current.scheduler, admission_timeout_seconds=2,
                 timeout_seconds=120, memory_mb=1024)
    value.update(changes)
    return value


def start(current, limits, *, optimized=True, chunked=True):
    function = scan.start_current_codebase_chunked_scan if chunked else old.start_current_codebase_scan
    return function(current.index, current.repository, expected_head=current.head,
        registry=current.registry, version_id=current.version_id, limits=limits,
        optimized=optimized, **options(current))


def checkpoint_bytes(current):
    row = current.registry.get_version(current.version_id)
    raw = current.registry.artifact_path(row["artifact"]).read_bytes()
    saved = runtimes._read_candidate(current.registry, row)
    return raw, features.digest(saved["state"]), saved["state"]["completed_epochs"]


def small_request_limits(current, *, page_entries=None, rows_per_request=2, **changes):
    """Choose a real wire budget after native target replay, without inference."""
    page_entries = current.count if page_entries is None else page_entries
    wide = old.CodebaseScanResumeLimits(max_inventory_entries=32, page_entries=page_entries,
                                        max_file_bytes=1024)
    root = start(current, wide, chunked=False)
    with old._scope(current.index, current.registry, parent_lease=None, cancel_event=None,
            **options(current)) as (_, _, remaining):
        manifest, receipt, chain, before = old._entry(current.index, current.repository,
            root, current.registry, remaining, 1024)
        entries, request = old._prepare_page(current.index, root, manifest, receipt,
                                             chain, 0, 0, remaining)
        assert all(entry["disposition"] == "inferred" for entry in entries)
        empty = {**request, "targets": [], "member_indices": []}
        charges = sorted((len(old._wire(target)) + len(str(index)) + 2
                          for target, index in zip(request["targets"], request["member_indices"])), reverse=True)
        # Padding covers changed decimal widths in the root's smaller limit;
        # it remains tiny relative to one genuine complete target.
        cap = len(old._wire(empty)) + sum(charges[:rows_per_request]) + 64 + 256
        del entries, request, empty, manifest, receipt
        old._close(current.index, current.repository, root, current.registry,
                   chain, before, remaining, 1024)
    assert cap < wide.max_input_bytes
    return replace(wide, max_input_bytes=cap, **changes)


def page(current, root, cursor=None, **changes):
    return scan.scan_current_codebase_page_chunked(current.index, current.repository,
        root=root, registry=current.registry, cursor=cursor, **options(current, **changes))


def all_pages(current, root):
    pages, cursor = [], None
    while True:
        result = page(current, root, cursor)
        pages.append(result)
        cursor = records.CodebaseScanChunkedCursor.from_page(root, result)
        if cursor is None:
            return pages


def numerical_chunks(current, saved_page):
    return [scan.load_codebase_scan_numerical_chunk(current.index.artifacts, row["chunk_cid"])
            for row in saved_page.to_dict()["chunks"]]


def mapped_rows(current, saved_pages):
    mapped = {}
    for saved_page in saved_pages:
        p = saved_page.to_dict()
        chunks = numerical_chunks(current, saved_page)
        records.bind_codebase_scan_chunked_page(saved_page, old.load_codebase_scan_resume_root(
            current.index.artifacts, p["root_cid"]), chunks)
        for entry in p["entries"]:
            if entry["disposition"] != "inferred":
                continue
            body = chunks[entry["chunk_ordinal"]].to_dict()
            row = body["inference"]["rows"][entry["row_index"]]
            assert entry["member_index"] == body["member_indices"][entry["row_index"]]
            assert row["source_digest"] == entry["source_digest"]
            assert entry["member_index"] not in mapped
            mapped[entry["member_index"]] = row
    return mapped


def no_numerical_calls(monkeypatch):
    """Fail on any numerical launch or forward/fit during native receiving."""
    real_popen = subprocess.Popen

    def popen(command, *args, **kwargs):
        if isinstance(command, (list, tuple)) and any(
                "codebase_inventory_resume_worker.py" in str(value) for value in command):
            pytest.fail("receiving launched a numerical child")
        return real_popen(command, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("receiving performed forward inference or fitting")

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(training, "_worker", forbidden)
    monkeypatch.setattr(features, "train_projection_features", forbidden)
    monkeypatch.setattr(features, "infer_projection_features", forbidden)


@pytest.mark.parametrize("count", [3, 17])
def test_real_chunk_requests_restore_coverage_and_match_reference_without_after_fit(native, count):
    current = native(count)
    limits = small_request_limits(current)
    before = checkpoint_bytes(current)
    original_root = start(current, limits, chunked=False)
    original = old.scan_current_codebase_page(current.index, current.repository,
        root=original_root, registry=current.registry, **options(current))
    assert 0 < original.to_dict()["coverage"]["inferred_rows"] < count
    assert any(entry["reason"] == "page_worker_input_byte_budget" for entry in original.to_dict()["entries"])

    results = []
    for optimized in (True, False):
        root = start(current, limits, optimized=optimized)
        pages = all_pages(current, root)
        assert len(pages) == 1
        p = pages[0].to_dict()
        assert p["coverage"]["inventory_entries"] == p["coverage"]["inferred_rows"] == count
        assert p["coverage"]["projection_records"] == 2 * count
        assert p["coverage"]["chunks"] > 1
        assert all(entry["disposition"] == "inferred" for entry in p["entries"])
        chunks = numerical_chunks(current, pages[0])
        assert sum(len(chunk.to_dict()["inference"]["rows"]) for chunk in chunks) == count
        for chunk in chunks:
            body = chunk.to_dict()
            assert body["worker_receipt"]["input_bytes"] <= limits.max_input_bytes
            assert body["worker_receipt"]["output_bytes"] <= limits.max_output_bytes
            assert len(chunk._payload) <= limits.max_output_bytes
            assert body["worker_counters"]["rows"] == len(body["member_indices"])
            assert body["worker_counters"]["training_calls"] == 0
            assert all(flag is False for flag in body["authority"].values())
        completion = scan.complete_current_codebase_chunked_scan(current.index, current.repository,
            root=root, registry=current.registry, tail_page_cid=pages[-1].artifact_cid, **options(current))
        assert completion.to_dict()["coverage"]["inferred_rows"] == count
        assert records.validate_codebase_scan_chunked_completion_refs(completion.advisory_refs(root)) == completion.advisory_refs(root)
        results.append(mapped_rows(current, pages))
    assert results[0].keys() == results[1].keys() == set(range(count))
    for index in results[0]:
        assert results[0][index]["source_digest"] == results[1][index]["source_digest"]
        assert results[0][index]["latent"] == pytest.approx(results[1][index]["latent"], rel=1e-12, abs=1e-12)
        for projection, values in results[0][index]["reconstructed_projection_features"].items():
            assert values == pytest.approx(results[1][index]["reconstructed_projection_features"][projection], rel=1e-12, abs=1e-12)
    assert checkpoint_bytes(current) == before and before[2] == 1


def test_native_page_boundary_reload_resume_and_receiving_perform_no_forward(native, monkeypatch):
    current = native()
    limits = small_request_limits(current, page_entries=2, rows_per_request=1)
    root = start(current, limits)
    first = page(current, root)
    assert first.to_dict()["coverage"]["chunks"] == 2
    reopened = ImmutableCAS(current.index.artifacts.root, max_object_bytes=16 * MIB)
    root = old.load_codebase_scan_resume_root(reopened, root.artifact_cid)
    first = scan.load_codebase_scan_chunked_page(reopened, first.artifact_cid)
    cursor = records.CodebaseScanChunkedCursor.from_dict(json.loads(json.dumps(
        records.CodebaseScanChunkedCursor.from_page(root, first).to_dict())))
    assert cursor.next_offset == 2
    final = page(current, root, cursor)
    assert [entry["member_index"] for entry in final.to_dict()["entries"]] == [2]
    assert records.CodebaseScanChunkedCursor.from_page(root, final) is None
    completion = scan.complete_current_codebase_chunked_scan(current.index, current.repository,
        root=root, registry=current.registry, tail_page_cid=final.artifact_cid, **options(current))
    completion = scan.load_codebase_scan_chunked_completion(reopened, completion.artifact_cid)
    frozen = checkpoint_bytes(current)
    no_numerical_calls(monkeypatch)
    assert scan.validate_current_codebase_chunked_scan_page(final, current.index, current.repository,
        root=root, registry=current.registry, **options(current)) is final
    assert scan.validate_current_codebase_chunked_scan_completion(completion, current.index, current.repository,
        root=root, registry=current.registry, **options(current)) is completion
    assert checkpoint_bytes(current) == frozen


@pytest.mark.parametrize("kind", ["source", "sql", "checkpoint", "producer-read"])
def test_real_post_chunk_publication_drift_withholds_accepted_page(native, monkeypatch, kind):
    current = native()
    limits = small_request_limits(current, rows_per_request=1)
    root = start(current, limits)
    real_put = current.index.artifacts.put_bytes
    path = current.repository / "unit00.py"
    source_raw = path.read_bytes()
    model_path = current.registry.artifact_path(current.registry.get_version(current.version_id)["artifact"])
    model_raw = model_path.read_bytes()
    projection = current.index.lookup(current.index.load(current.head.manifest_cid), "unit00.py")
    symbols = current.connection.execute("SELECT rowid, name FROM symbols WHERE blob_id=?", [projection.blob_id]).fetchall()
    published, fired = [], False
    real_read = Path.read_bytes
    producer = Path(scan.__file__).resolve()

    def read_bytes(file):
        # Inject a changed producer read; do not modify shared source files.
        if kind == "producer-read" and fired and file.resolve() == producer:
            return real_read(file) + b"\n# controlled producer read drift\n"
        return real_read(file)

    def put_bytes(raw):
        nonlocal fired
        result = real_put(raw)
        body = json.loads(raw)
        if body.get("schema") == records.CHUNK_SCHEMA:
            published.append(result)
            if not fired:
                fired = True
                if kind == "source":
                    path.write_bytes(source_raw.replace(b"+ 1", b"+ 999"))
                elif kind == "sql":
                    current.connection.execute("UPDATE symbols SET name='drifted' WHERE blob_id=?", [projection.blob_id])
                elif kind == "checkpoint":
                    model_path.write_bytes(b"corrupted owned checkpoint")
        return result

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(current.index.artifacts, "put_bytes", put_bytes)
    expected = StaleCodebaseError if kind == "source" else DuckDBASTStoreIntegrityError if kind == "sql" else ValueError
    try:
        with pytest.raises(expected):
            page(current, root)
        assert fired and published
    finally:
        path.write_bytes(source_raw)
        model_path.write_bytes(model_raw)
        if kind == "sql":
            for rowid, name in symbols:
                current.connection.execute("UPDATE symbols SET name=? WHERE rowid=? AND blob_id=?",
                                           [name, rowid, projection.blob_id])


@pytest.mark.parametrize("kind", ["singleton", "global-rows"])
def test_native_hard_budgets_remain_explicit_without_unbounded_retry(native, monkeypatch, kind):
    current = native()
    if kind == "singleton":
        limits = old.CodebaseScanResumeLimits(max_inventory_entries=32, page_entries=3,
            max_file_bytes=1024, max_input_bytes=1)
    else:
        limits = small_request_limits(current, rows_per_request=1, max_inferred_rows=1)
    root = start(current, limits)
    if kind == "singleton":
        no_numerical_calls(monkeypatch)
    result = page(current, root)
    p = result.to_dict()
    assert p["coverage"]["inventory_entries"] == 3
    assert p["coverage"]["inferred_rows"] == (0 if kind == "singleton" else 1)
    assert p["coverage"]["chunks"] == (0 if kind == "singleton" else 1)
    reasons = [entry["reason"] for entry in p["entries"] if entry["disposition"] == "deferred_budget"]
    assert len(reasons) == (3 if kind == "singleton" else 2)
    assert set(reasons) == ({"single_target_worker_input_byte_budget"} if kind == "singleton" else {"global_inferred_row_budget"})


@pytest.mark.parametrize("phase", ["chunk", "completion"])
def test_native_late_cancellation_after_cas_publication_returns_no_accepted_record(native, monkeypatch, phase):
    current = native()
    root = start(current, small_request_limits(current, rows_per_request=1))
    final = None if phase == "chunk" else page(current, root)
    event = threading.Event()
    real_put = current.index.artifacts.put_bytes
    target_schema = records.CHUNK_SCHEMA if phase == "chunk" else records.COMPLETION_SCHEMA
    published = []

    def put_bytes(raw):
        result = real_put(raw)
        if json.loads(raw).get("schema") == target_schema:
            published.append(result)
            event.set()
        return result

    monkeypatch.setattr(current.index.artifacts, "put_bytes", put_bytes)
    with pytest.raises(LeaseCancelledError):
        if phase == "chunk":
            page(current, root, cancel_event=event)
        else:
            scan.complete_current_codebase_chunked_scan(current.index, current.repository,
                root=root, registry=current.registry, tail_page_cid=final.artifact_cid,
                **options(current, cancel_event=event))
    assert published and event.is_set()


def test_native_receiver_rereads_chunk_bytes_and_refuses_corruption_without_forward(native, monkeypatch):
    current = native()
    root = start(current, small_request_limits(current, rows_per_request=1))
    final = page(current, root)
    completion = scan.complete_current_codebase_chunked_scan(current.index, current.repository,
        root=root, registry=current.registry, tail_page_cid=final.artifact_cid, **options(current))
    chunk_cid = final.to_dict()["chunks"][0]["chunk_cid"]
    path = current.index.artifacts.path_for(chunk_cid, source=True)
    original = path.read_bytes()
    path.write_bytes(b"corrupted durable numerical chunk")
    no_numerical_calls(monkeypatch)
    try:
        with pytest.raises((CacheIntegrityError, old.CodebaseScanResumeError)):
            scan.validate_current_codebase_chunked_scan_completion(completion, current.index, current.repository,
                root=root, registry=current.registry, **options(current))
    finally:
        path.write_bytes(original)


def test_native_incomplete_prefix_cannot_become_completion(native, monkeypatch):
    current = native()
    root = start(current, small_request_limits(current, page_entries=2, rows_per_request=1))
    first = page(current, root)
    assert first.next_cursor is not None
    no_numerical_calls(monkeypatch)
    with pytest.raises(old.CodebaseScanResumeError, match="incomplete|complete"):
        scan.complete_current_codebase_chunked_scan(current.index, current.repository,
            root=root, registry=current.registry, tail_page_cid=first.artifact_cid, **options(current))


@pytest.mark.parametrize("boundary", ["guard-read", "after-native-close"])
def test_native_closing_byte_guards_cannot_hide_owned_source_or_chunk_drift(native, monkeypatch, boundary):
    current = native()
    root = start(current, small_request_limits(current, rows_per_request=1))
    source = current.repository / "unit00.py"
    original_source = source.read_bytes()
    real_put = current.index.artifacts.put_bytes
    real_get = current.index.artifacts.get_bytes
    real_close = old._close
    chunk_paths, ready, fired = [], False, False

    def put(raw):
        nonlocal ready
        result = real_put(raw)
        schema = json.loads(raw).get("schema")
        if schema == records.CHUNK_SCHEMA:
            chunk_paths.append(current.index.artifacts.path_for(result, source=True))
        if schema == records.PAGE_SCHEMA:
            ready = True
        return result

    def close(*args, **kwargs):
        nonlocal fired
        result = real_close(*args, **kwargs)
        if boundary == "after-native-close" and ready and not fired:
            fired = True
            chunk_paths[0].write_bytes(b"late owned numerical chunk corruption")
        return result

    # path_for uses CID-derived sharding; compare the actual first CID instead
    # of assuming any filename convention in the CAS implementation.
    first_chunk = []
    def tracked_put(raw):
        result = put(raw)
        if json.loads(raw).get("schema") == records.CHUNK_SCHEMA and not first_chunk:
            first_chunk.append(result)
        return result
    def tracked_get(identity):
        nonlocal fired
        raw = real_get(identity)
        if boundary == "guard-read" and ready and not fired and first_chunk and identity == first_chunk[0]:
            fired = True
            source.write_bytes(original_source + b"\n# late guard source drift\n")
        return raw

    monkeypatch.setattr(current.index.artifacts, "put_bytes", tracked_put)
    monkeypatch.setattr(current.index.artifacts, "get_bytes", tracked_get)
    monkeypatch.setattr(old, "_close", close)
    try:
        with pytest.raises((StaleCodebaseError, old.CodebaseScanResumeError)):
            page(current, root)
        assert fired
    finally:
        source.write_bytes(original_source)


@pytest.mark.parametrize("renewal", ["refused", "error"])
def test_native_cleanup_quarantine_holds_reservations_and_drains_despite_renewal_failure(native, monkeypatch, renewal):
    from ipfs_datasets_py.logic.backends import process as lifecycle
    current = native()
    root = start(current, small_request_limits(current, rows_per_request=1))
    failing = threading.Event()
    failing.set()
    actual_group = lifecycle.NativeToolCleanupHandle._group_members
    actual_renew = current.scheduler.renew

    def group(handle):
        members, errors = actual_group(handle)
        if failing.is_set():
            errors = errors + ["controlled native group observation refusal"]
        return members, errors

    def renew(*args, **kwargs):
        if failing.is_set():
            if renewal == "error":
                raise OSError("controlled renewal state write failure")
            return False
        return actual_renew(*args, **kwargs)

    monkeypatch.setattr(lifecycle.NativeToolCleanupHandle, "_group_members", group)
    monkeypatch.setattr(current.scheduler, "renew", renew)
    try:
        with pytest.raises(lifecycle.OwnedToolCleanupError):
            page(current, root)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            quarantines = scan.quarantined_codebase_chunk_operations()
            if quarantines and any(item["error"] for item in quarantines):
                break
            time.sleep(.01)
        assert quarantines and any(item["error"] for item in quarantines)
        assert all(item["pending_children"] == 1 and item["parent_released"] is False for item in quarantines)
        state = current.scheduler.snapshot()
        assert state["active_lease_count"] == 2
        assert state["allocated"]["memory_mb"] >= 1024
    finally:
        failing.clear()
        deadline = time.monotonic() + 8
        while scan.quarantined_codebase_chunk_operations() and time.monotonic() < deadline:
            time.sleep(.01)
        assert not scan.quarantined_codebase_chunk_operations()
        assert current.scheduler.snapshot()["active_lease_count"] == 0


def test_precancelled_receiving_does_not_read_stored_page_before_admission(native, monkeypatch):
    current = native()
    root = start(current, small_request_limits(current, rows_per_request=2))
    saved = page(current, root)
    event = threading.Event()
    event.set()

    def forbidden(*args, **kwargs):
        pytest.fail("pre-cancelled receiving read CAS before admission")

    monkeypatch.setattr(current.index.artifacts, "get_bytes", forbidden)
    monkeypatch.setattr(current.index.artifacts, "get", forbidden)
    with pytest.raises(LeaseCancelledError):
        scan.validate_current_codebase_chunked_scan_page(saved, current.index, current.repository,
            root=root, registry=current.registry, **options(current, cancel_event=event))
