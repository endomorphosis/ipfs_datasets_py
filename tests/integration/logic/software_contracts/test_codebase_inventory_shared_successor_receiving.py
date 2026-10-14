"""Native controls for the additive paired shared successor receiver.

The fixture explicitly trains a parent and
direct source-successor child beforehand. All receiving assertions retain
actual DuckDB/CAS/registry/source observations and prohibit inference/fitting.
Fault wrappers call the actual native function; no successful native fence is
substituted. This tiny fixture cannot qualify full300 or larger/CUDA heads.
"""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_inventory_shared_successor_receiving as receiving
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_shared_scan as shared
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_shared_chunks as records
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as resume
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_successor as delta
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_successor_model as successor
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_successor_receiving as legacy_receiving
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as training
from ipfs_datasets_py.logic.software_contracts.cache import CacheIntegrityError, ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import (
    CodebaseScanLimits, RepositoryCodebaseIndex, StaleCodebaseError,
)
from ipfs_datasets_py.logic.software_contracts.content import cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStoreIntegrityError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_feature_worker as numerical
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import codebase_inventory_shared_worker as shared_worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseCancelledError
from tests.integration.logic.software_contracts.test_codebase_inventory_shared_scan import native, options

MIB = 1024 * 1024
REFUSALS = (resume.CodebaseScanResumeError, CacheIntegrityError, StaleCodebaseError,
            DuckDBASTStoreIntegrityError, runtimes.RuntimeVersionError, ValueError, OSError)


@pytest.fixture
def selected(native):
    """A genuine published changed source and already-trained direct child."""
    current = native()
    parent_head, parent_version = current.head, current.version_id
    (current.repository / "unit00.py").write_text("def step0(n: int) -> int:\n    return n + 2\n")
    current.head = current.index.prepare_current(current.repository,
        repository_id=parent_head.repository_id, operation_id="child-capture", expected_head=parent_head,
        limits=CodebaseScanLimits(max_entries=32, max_file_bytes=1024),
        scheduler=current.scheduler, memory_mb=64, timeout_seconds=30, admission_timeout_seconds=2).head
    selections = [training.CodebaseTrainingSelection(f"unit{number:02d}.py", role)
                  for number, role in enumerate(("train", "tune", "canary"))]
    child = training.train_current_codebase_features(current.index, current.repository,
        expected_head=current.head, registry=current.registry, parent_version_id=parent_version,
        selections=selections, operation_id="child-training", epochs=1, learning_rate=.002,
        **options(current))
    current.version_id = child.to_dict()["version_id"]
    current.parent_version = parent_version
    current.source_delta = delta.build_current_codebase_source_delta(current.index, current.repository,
        previous_head=parent_head, expected_head=current.head,
        limits=delta.CodebaseSourceDeltaLimits(max_inventory_entries=32, max_union_entries=64, max_file_bytes=1024),
        **options(current))
    return current


def freeze_models(current):
    return {version: current.registry.artifact_path(current.registry.get_version(version)["artifact"]).read_bytes()
            for version in (current.parent_version, current.version_id)}


def assert_idle(current):
    state = current.scheduler.snapshot()
    assert state["active_lease_count"] == state["waiting_request_count"] == 0
    assert not shared.quarantined_codebase_shared_operations()


def completed(current, *, optimized=True):
    limits = resume.CodebaseScanResumeLimits(max_inventory_entries=32, page_entries=2,
        max_pages=16, max_file_bytes=1024)
    selection = successor.start_current_codebase_successor_scan(current.index, current.repository,
        source_delta=current.source_delta, registry=current.registry,
        previous_version_id=current.parent_version, version_id=current.version_id,
        limits=limits, optimized=optimized, **options(current))
    root = resume.load_codebase_scan_resume_root(current.index.artifacts, selection.to_dict()["root_cid"])
    pages, cursor = [], None
    while True:
        page = shared.scan_current_codebase_page_shared(current.index, current.repository,
            root=root, registry=current.registry, cursor=cursor, **options(current))
        pages.append(page)
        cursor = records.CodebaseScanChunkedCursor.from_page(root, page)
        if cursor is None:
            break
    completion = shared.complete_current_codebase_shared_scan(current.index, current.repository,
        root=root, registry=current.registry, tail_page_cid=pages[-1].artifact_cid, **options(current))
    return SimpleNamespace(current=current, selection=selection, root=root, completion=completion, pages=pages)


def paired(fixture, **changes):
    current = fixture.current
    return receiving._paired_current_codebase_shared_successor_completion(fixture.selection, fixture.completion,
        current.index, current.repository, root=fixture.root, registry=current.registry,
        **options(current, **changes))


@contextmanager
def no_numerical_work():
    def forbidden(*args, **kwargs):
        pytest.fail("native receiving performed fitting, forward inference or numerical dispatch")
    real_popen = subprocess.Popen
    def guarded_popen(command, *args, **kwargs):
        if isinstance(command, (list, tuple)) and any(str(value).endswith((
                "codebase_inventory_shared_worker.py", "codebase_inventory_feature_worker.py",
                "codebase_feature_training_worker.py")) for value in command):
            forbidden()
        return real_popen(command, *args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(subprocess, "Popen", guarded_popen)
        for owner, name in ((shared, "_worker"), (resume, "_worker"), (training, "_worker"),
                (training, "train_current_codebase_features"),
                (features, "train_projection_features"), (features, "infer_projection_features"),
                (numerical._PreparedProjectionEngine, "infer"), (numerical, "execute"),
                (shared_worker, "execute"), (runtimes.NativeRuntime, "train"),
                (runtimes.NativeRuntime, "infer"), (runtimes.SourceBoundCodebaseFeatureRuntime, "train"),
                (runtimes.SourceBoundCodebaseFeatureRuntime, "infer")):
            patch.setattr(owner, name, forbidden)
        yield


@pytest.mark.parametrize("optimized", [True, False])
def test_actual_shared_successor_pair_closes_once_without_fit_forward_or_promotion(selected, optimized):
    f = completed(selected, optimized=optimized)
    before = freeze_models(selected)
    with no_numerical_work(), paired(f) as close:
        assert close() is f.completion
        with pytest.raises(resume.CodebaseScanResumeError, match="consumed"):
            close()
    with pytest.raises(resume.CodebaseScanResumeError, match="inactive"):
        close()
    assert freeze_models(selected) == before
    assert f.completion.to_dict()["coverage"]["inventory_entries"] == 3
    assert f.completion.to_dict()["coverage"]["inferred_rows"] == 3
    assert f.completion.to_dict()["coverage"]["projection_records"] == 6
    assert f.completion.to_dict()["coverage"]["pages"] == 2
    assert all(value is False for value in f.completion.to_dict()["authority"].values())
    assert selected.registry.resolve_head(selected.registry.get_version(selected.version_id)["variant_id"], "main") is None
    assert_idle(selected)


def test_optimized_close_does_not_reconstruct_any_target_after_full_native_entry(selected, monkeypatch):
    f = completed(selected)
    real = shared._prepare_chunks
    calls, after_entry = [], False
    def prepare(*args, **kwargs):
        assert not after_entry, "optimized close repeated native target reconstruction"
        calls.append(args[5])
        return real(*args, **kwargs)
    monkeypatch.setattr(shared, "_prepare_chunks", prepare)
    with no_numerical_work(), paired(f) as close:
        assert len(calls) == 2
        after_entry = True
        assert close() is f.completion
    assert len(calls) == 2
    assert_idle(selected)


def test_reference_runs_both_actual_public_receivers_twice_then_composite_native_close(selected, monkeypatch):
    f = completed(selected, optimized=False)
    events = []
    for owner, name, tag in ((successor, "validate_current_codebase_successor_scan", "successor"),
            (shared, "validate_current_codebase_shared_scan_completion", "shared"),
            (legacy_receiving, "_close_native", "composite")):
        real = getattr(owner, name)
        def wrapper(*args, _real=real, _tag=tag, **kwargs):
            events.append(_tag)
            return _real(*args, **kwargs)
        monkeypatch.setattr(owner, name, wrapper)
    with no_numerical_work(), paired(f) as close:
        assert events == ["successor", "shared", "composite"]
        assert close() is f.completion
    assert events == ["successor", "shared", "composite"] * 2
    assert_idle(selected)


def test_unused_gate_and_caller_exception_release_actual_resources(selected):
    f = completed(selected)
    with no_numerical_work():
        with pytest.raises(resume.CodebaseScanResumeError, match="not completed"):
            with paired(f) as unused:
                pass
        with pytest.raises(resume.CodebaseScanResumeError, match="inactive"):
            unused()
        with pytest.raises(RuntimeError, match="caller failed"):
            with paired(f):
                raise RuntimeError("caller failed")
    assert_idle(selected)


def test_foreign_thread_attempt_consumes_gate_before_ownership_check(selected):
    f = completed(selected)
    errors = []
    def use(close):
        try:
            close()
        except BaseException as error:
            errors.append(error)
    with no_numerical_work(), pytest.raises(resume.CodebaseScanResumeError, match="not completed"):
        with paired(f) as close:
            thread = threading.Thread(target=use, args=(close,))
            thread.start()
            thread.join(timeout=5)
            assert not thread.is_alive() and len(errors) == 1
            assert isinstance(errors[0], resume.CodebaseScanResumeError)
            assert "ownership expired" in str(errors[0])
            with pytest.raises(resume.CodebaseScanResumeError, match="consumed"):
                close()
    assert_idle(selected)


def test_actual_cancellation_between_entry_and_close_is_terminal_and_drained(selected):
    f = completed(selected)
    event = threading.Event()
    with no_numerical_work(), pytest.raises(LeaseCancelledError):
        with paired(f, cancel_event=event) as close:
            event.set()
            close()
    assert_idle(selected)


def test_cancellation_after_close_prevents_successful_native_scope_exit(selected):
    f = completed(selected)
    event = threading.Event()
    with no_numerical_work(), pytest.raises(LeaseCancelledError):
        with paired(f, cancel_event=event) as close:
            assert close() is f.completion
            event.set()
    # A consumer must await successful context exit before accepting work.
    assert_idle(selected)


def test_actual_released_lease_cannot_close_or_be_retried(selected, monkeypatch):
    f = completed(selected)
    real_scope, leases = shared._scope, []
    @contextmanager
    def scope(*args, **kwargs):
        with real_scope(*args, **kwargs) as state:
            leases.append(state[0])
            yield state
    monkeypatch.setattr(shared, "_scope", scope)
    with no_numerical_work(), pytest.raises(resume.CodebaseScanResumeError, match="not completed"):
        with paired(f) as close:
            assert len(leases) == 1 and leases[0].release()
            # The real scheduler's combined signal may observe revocation
            # before the explicit released-lease ownership guard.
            with pytest.raises((LeaseCancelledError, resume.CodebaseScanResumeError)):
                close()
            with pytest.raises(resume.CodebaseScanResumeError, match="consumed"):
                close()
    assert_idle(selected)


@pytest.mark.parametrize("owner", ["catalog_pid", "registry_generation", "source_directory"])
def test_native_owner_replacement_between_entry_and_close_refuses(selected, owner):
    f = completed(selected)
    old_pid, old_generation = selected.index.catalog._pid, selected.registry.owner_generation
    directory = selected.index.artifacts.root
    relocated = directory.with_name(directory.name + ".moved")
    try:
        with no_numerical_work(), pytest.raises(REFUSALS):
            with paired(f) as close:
                if owner == "catalog_pid":
                    selected.index.catalog._pid += 1
                elif owner == "registry_generation":
                    selected.registry.owner_generation += 1
                else:
                    directory.rename(relocated)
                    directory.mkdir()
                close()
    finally:
        selected.index.catalog._pid = old_pid
        selected.registry.owner_generation = old_generation
        if relocated.exists():
            directory.rmdir()
            relocated.rename(directory)
    assert_idle(selected)


def test_valid_foreign_shared_root_completion_cannot_replace_selected_completion(selected):
    left, right = completed(selected, optimized=True), completed(selected, optimized=False)
    assert left.root.artifact_cid != right.root.artifact_cid
    with no_numerical_work(), pytest.raises(REFUSALS):
        with receiving._paired_current_codebase_shared_successor_completion(left.selection, right.completion,
                selected.index, selected.repository, root=left.root, registry=selected.registry,
                **options(selected)):
            pytest.fail("foreign valid completion admitted")
    assert_idle(selected)


def test_same_process_cold_native_owner_reopen_accepts_exact_saved_pair_without_publication(selected, monkeypatch):
    # This is cold native-owner reopening in the same process. Fresh-process
    # replay remains a separately admitted qualification requirement.
    import duckdb
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog
    from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
    from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor

    f = completed(selected)
    old_index, generation = selected.index, selected.registry.owner_generation
    source_db = selected.index.catalog._database_path
    cas_root, model_db, model_root = selected.index.artifacts.root, selected.registry.database_path, selected.registry.artifact_root
    frozen = freeze_models(selected)
    selected.registry.close()
    selected.connection.close()
    selected.connection = duckdb.connect(str(source_db), config={"threads": 1, "memory_limit": "128MB"})
    store = DuckDBASTStore(connection=selected.connection)
    artifacts = ImmutableCAS(cas_root, max_object_bytes=16 * MIB)
    selected.index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store),
        artifacts=artifacts, catalog=CodebaseCatalog(store, artifacts))
    selected.registry = AutoencoderRegistry(model_db, model_root)
    assert selected.index is not old_index and selected.registry.owner_generation == generation + 1
    f.selection = successor.load_codebase_successor_scan(artifacts, f.selection.artifact_cid)
    f.root = resume.load_codebase_scan_resume_root(artifacts, f.root.artifact_cid)
    f.completion = shared.load_codebase_scan_shared_completion(artifacts, f.completion.artifact_cid)
    def forbidden(*args, **kwargs):
        pytest.fail("native receiving published a new artifact")
    monkeypatch.setattr(artifacts, "put", forbidden)
    monkeypatch.setattr(artifacts, "put_bytes", forbidden)
    with no_numerical_work(), paired(f) as close:
        assert close() is f.completion
    assert freeze_models(selected) == frozen
    assert_idle(selected)


def test_candidate_helper_read_drift_refuses_without_editing_selected_source_files(selected, monkeypatch):
    f = completed(selected)
    real_read, after_entry = Path.read_bytes, False
    producer = Path(receiving.__file__).resolve()
    def read(path):
        actual = real_read(path)
        if after_entry and path.resolve() == producer:
            return actual + b"\n# controlled candidate source-read drift\n"
        return actual
    monkeypatch.setattr(Path, "read_bytes", read)
    with no_numerical_work(), pytest.raises(resume.CodebaseScanResumeError, match="implementation changed"):
        with paired(f) as close:
            after_entry = True
            close()
    assert_idle(selected)


@pytest.mark.parametrize("optimized", [True, False])
@pytest.mark.parametrize("mutation", ["source", "checkpoint", "sql"])
def test_native_current_source_checkpoint_and_sql_mutations_refuse(selected, optimized, mutation):
    f = completed(selected, optimized=optimized)
    path = selected.repository / "unit00.py"
    source = path.read_bytes()
    checkpoint = selected.registry.artifact_path(selected.registry.get_version(selected.version_id)["artifact"])
    model = checkpoint.read_bytes()
    manifest = selected.index.load(selected.head.manifest_cid)
    projection = selected.index.lookup(manifest, "unit00.py")
    # Capture every symbol row, including parameter rows, for exact restoration.
    symbols = selected.connection.execute("SELECT rowid, name FROM symbols WHERE blob_id=?", [projection.blob_id]).fetchall()
    try:
        with no_numerical_work(), pytest.raises(REFUSALS):
            with paired(f) as close:
                if mutation == "source":
                    path.write_bytes(source.replace(b"n + 2", b"n + 9"))
                elif mutation == "checkpoint":
                    checkpoint.write_bytes(model[:-1] + bytes([model[-1] ^ 1]))
                else:
                    selected.connection.execute("UPDATE symbols SET name='drifted' WHERE blob_id=?", [projection.blob_id])
                close()
    finally:
        path.write_bytes(source)
        checkpoint.write_bytes(model)
        for rowid, name in symbols:
            selected.connection.execute("UPDATE symbols SET name=? WHERE rowid=? AND blob_id=?",
                                        [name, rowid, projection.blob_id])
    assert_idle(selected)


@pytest.mark.parametrize("role", ["selection", "root", "delta", "completion", "page", "chunk"])
def test_exact_original_dag_json_and_raw_custody_refuse_durable_edits(selected, role):
    f = completed(selected)
    chosen, source = {
        "selection": (f.selection, False), "root": (f.root, False), "delta": (selected.source_delta, False),
        "completion": (f.completion, True), "page": (f.pages[0], True),
        "chunk": (shared.load_codebase_scan_shared_numerical_chunk(selected.index.artifacts,
                    f.pages[0].to_dict()["chunks"][0]["chunk_cid"]), True),
    }[role]
    path = ImmutableCAS.path_for(selected.index.artifacts, chosen.artifact_cid, source=source)
    raw = path.read_bytes()
    try:
        with no_numerical_work(), pytest.raises(REFUSALS):
            with paired(f) as close:
                path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
                close()
    finally:
        path.write_bytes(raw)
    assert_idle(selected)


@pytest.mark.parametrize("role", ["selection", "delta"])
def test_reference_last_shared_callback_cannot_mutate_prior_durable_successor_bytes(selected, monkeypatch, role):
    f = completed(selected, optimized=False)
    chosen = f.selection if role == "selection" else selected.source_delta
    path = ImmutableCAS.path_for(selected.index.artifacts, chosen.artifact_cid, source=False)
    raw, real, after_entry, fired = path.read_bytes(), shared.validate_current_codebase_shared_scan_completion, False, False
    def receive(*args, **kwargs):
        nonlocal fired
        actual = real(*args, **kwargs)
        if after_entry and not fired:
            fired = True
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        return actual
    monkeypatch.setattr(shared, "validate_current_codebase_shared_scan_completion", receive)
    try:
        with no_numerical_work(), pytest.raises(REFUSALS):
            with paired(f) as close:
                after_entry = True
                close()
    finally:
        path.write_bytes(raw)
    assert fired
    assert_idle(selected)


@pytest.mark.parametrize("mutation", ["source", "checkpoint"])
def test_late_actual_page_callback_is_closed_by_fresh_native_observations(selected, monkeypatch, mutation):
    f = completed(selected)
    source_path = selected.repository / "unit00.py"
    model_path = selected.registry.artifact_path(selected.registry.get_version(selected.version_id)["artifact"])
    source, model = source_path.read_bytes(), model_path.read_bytes()
    real_get, after_entry, fired = selected.index.artifacts.get_bytes, False, False
    def get(identity):
        nonlocal fired
        actual = real_get(identity)
        if after_entry and not fired and identity == f.pages[-1].artifact_cid:
            fired = True
            if mutation == "source":
                source_path.write_bytes(source.replace(b"n + 2", b"n + 9"))
            else:
                model_path.write_bytes(model[:-1] + bytes([model[-1] ^ 1]))
        return actual
    monkeypatch.setattr(selected.index.artifacts, "get_bytes", get)
    try:
        with no_numerical_work(), pytest.raises(REFUSALS):
            with paired(f) as close:
                after_entry = True
                close()
    finally:
        source_path.write_bytes(source)
        model_path.write_bytes(model)
    assert fired
    assert_idle(selected)


def test_late_actual_model_fence_cannot_rewrite_previously_read_raw_chunk(selected, monkeypatch):
    f = completed(selected)
    identity = f.pages[0].to_dict()["chunks"][0]["chunk_cid"]
    path = ImmutableCAS.path_for(selected.index.artifacts, identity, source=True)
    raw, real, after_entry, fired = path.read_bytes(), resume.legacy._model_fence, False, False
    def fence(*args, **kwargs):
        nonlocal fired
        actual = real(*args, **kwargs)
        if after_entry and not fired:
            fired = True
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        return actual
    monkeypatch.setattr(resume.legacy, "_model_fence", fence)
    try:
        with no_numerical_work(), pytest.raises(REFUSALS):
            with paired(f) as close:
                after_entry = True
                close()
    finally:
        path.write_bytes(raw)
    assert fired
    assert_idle(selected)


def test_source_edit_after_successful_close_has_no_late_native_cleanup_replay(selected):
    f = completed(selected)
    path = selected.repository / "unit00.py"
    raw = path.read_bytes()
    try:
        with no_numerical_work(), paired(f) as close:
            assert close() is f.completion
            # Represents a caller action after the final gate, before release.
            # That action receives no proof/currentness credit from this test.
            path.write_bytes(raw.replace(b"n + 2", b"n + 8"))
    finally:
        path.write_bytes(raw)
    assert_idle(selected)


def test_oversized_inventory_profile_refuses_before_native_scope_or_cas_reads(selected, monkeypatch):
    f = completed(selected)
    body = f.root.to_dict()
    body["limits"] = replace(resume.CodebaseScanResumeLimits.from_dict(body["limits"]),
                             max_inventory_entries=513, max_pages=257).to_dict()
    foreign_root = resume.CodebaseScanResumeRoot.from_dict(cid_for_structured(body), body)
    def forbidden(*args, **kwargs):
        pytest.fail("oversized shared profile reached native scope or CAS")
    monkeypatch.setattr(shared, "_scope", forbidden)
    monkeypatch.setattr(selected.index.artifacts, "get", forbidden)
    monkeypatch.setattr(selected.index.artifacts, "get_bytes", forbidden)
    with pytest.raises(resume.CodebaseScanResumeError, match="at most 512"):
        with receiving._paired_current_codebase_shared_successor_completion(f.selection, f.completion,
                selected.index, selected.repository, root=foreign_root, registry=selected.registry,
                **options(selected)):
            pytest.fail("oversized shared root admitted")
    assert_idle(selected)


def test_larger_actual_immutable_inputs_require_real_serialized_reservation():
    # Inputs at their existing legal caps exceed a quarter of 1024 MiB even
    # before any metadata, so default admission must refuse rather than reuse
    # the old 248 MiB estimate or silently increase the reservation.
    inputs = (("selection", 256 * 1024, "sha"), ("root", 4 * MIB, "sha"),
              ("completion", 16 * MIB, "sha"))
    delta_guard = ("delta", 8 * MIB, "sha")
    with pytest.raises(resume.CodebaseScanResumeError, match="exceed reservation"):
        receiving._retention_charge(1024, inputs, delta_guard, None, None, None, None)
    charged = receiving._retention_charge(2048, inputs, delta_guard, None, None, None, None)
    assert charged > 256 * MIB
    with pytest.raises(resume.CodebaseScanResumeError, match="exact"):
        receiving._retention_charge(True, inputs, delta_guard, None, None, None, None)
