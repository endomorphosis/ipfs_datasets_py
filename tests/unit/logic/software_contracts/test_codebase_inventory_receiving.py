"""Private paired-receiving guards; never numerical/model qualification.

Protocol controls replace native owner/model boundaries explicitly. The native
257-member controls use genuine DuckDB/CAS/source/AST/target replay and an
explicit inert registry/model boundary. No model is fitted or executed here;
the separate admitted pretrained fixture qualifies those owners and weights.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading

import duckdb
import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseCatalogLimits
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_receiving as receive
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as scan
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseIRManifest, CodebaseUnit, RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot, SnapshotEntry
from tests.unit.logic.software_contracts.test_codebase_inventory_resume import completion, page_record, root_body, root_record, stored_chain
from tests.unit.logic.software_contracts.test_codebase_inventory_resume_lineage import inert_target


def protocol(monkeypatch, tmp_path, *, optimized=True, count=3):
    """Real immutable transport; explicitly inert ownership/replay boundaries."""
    cas, root, pages = stored_chain(tmp_path, count=count)
    if not optimized:
        value = root.to_dict()
        value["optimized"] = False
        root = root_record(value)
        cas.put(value)
        # Rebind the complete chain to the reference root.
        prior, rebound = None, []
        for page in pages:
            value = page.to_dict()
            value["root_cid"], value["previous_page_cid"] = root.artifact_cid, prior
            page = page_record(value)
            cas.put_bytes(page._payload)
            rebound.append(page)
            prior = page.artifact_cid
        pages = rebound
    complete = completion(root, pages)
    cas.put(complete.to_dict())
    store = SimpleNamespace(_connection=object(), _lock=object())
    index = SimpleNamespace(artifacts=cas, ingestor=SimpleNamespace(store=store),
                            catalog=SimpleNamespace(_database_path=tmp_path / "source.duckdb", _pid=os.getpid()))
    registry = SimpleNamespace(database_path=tmp_path / "model.duckdb", artifact_root=tmp_path / "models",
        _manager=object(), _lock=object(), _pid=os.getpid(), owner_generation=2, _closed=False)
    registry.database_path.write_bytes(b"inert-db-owner")
    registry.artifact_root.mkdir()
    registry._owner_file = registry.database_path.with_name(registry.database_path.name + ".owner.lock").open("a+b")
    target = inert_target()
    chain = [({"version_id": "inert"}, {"state": {"weights": [1]}}, {"head": {"inert": True}},
              [target], [target], [target], [target])]
    calls = {"entry": 0, "replay": [], "close": 0, "reference": 0, "remaining": 0, "scopes": []}
    control = SimpleNamespace(error=None, close_error=None, close_hook=None)
    lease = SimpleNamespace(released=False)
    signal = threading.Event()
    def remaining():
        calls["remaining"] += 1
        if control.error is not None:
            raise control.error
        return 30.0
    @contextmanager
    def scope(*args, **kwargs):
        calls["scopes"].append(kwargs)
        try:
            remaining()
            yield lease, signal, remaining
            remaining()
        finally:
            lease.released = True
    def entry(*args):
        calls["entry"] += 1
        return object(), object(), chain, b"exact-inert-owner-generation-2"
    def replay(index, root, manifest, receipt, chain, page, inferred, remaining):
        remaining()
        calls["replay"].append((page.artifact_cid, inferred))
    def close(*args):
        calls["close"] += 1
        if control.close_hook is not None:
            control.close_hook()
        if control.close_error is not None:
            raise control.close_error
    def reference(actual, *args, **kwargs):
        calls["reference"] += 1
        assert kwargs["parent_lease"] is lease and kwargs["cancel_event"] is signal
        assert 0 < kwargs["timeout_seconds"] <= 30
        return actual
    monkeypatch.setattr(scan, "_scope", scope)
    monkeypatch.setattr(scan, "_entry", entry)
    monkeypatch.setattr(scan, "_replay_page", replay)
    monkeypatch.setattr(scan, "_close", close)
    monkeypatch.setattr(scan, "validate_current_codebase_scan_completion", reference)
    return SimpleNamespace(cas=cas, root=root, pages=pages, completion=complete, index=index, registry=registry,
                           chain=chain, calls=calls, control=control, lease=lease, signal=signal)


def paired(fixture, **kwargs):
    return receive._paired_current_codebase_scan_completion(fixture.completion, fixture.index, ".",
                    root=fixture.root, registry=fixture.registry, **kwargs)


def test_default_replays_each_page_only_at_entry_and_closes_twice(monkeypatch, tmp_path):
    fixture = protocol(monkeypatch, tmp_path, count=257)
    with paired(fixture, parent_lease="inert-outer", timeout_seconds=45) as close:
        assert len(fixture.calls["replay"]) == len(fixture.pages)
        assert fixture.calls["close"] == 1
        assert close() is fixture.completion
        assert len(fixture.calls["replay"]) == len(fixture.pages)
        assert fixture.calls["close"] == 2
    assert fixture.lease.released and fixture.calls["reference"] == 0
    assert fixture.calls["scopes"][0]["parent_lease"] == "inert-outer"
    assert fixture.calls["scopes"][0]["timeout_seconds"] == 45


def test_optout_calls_public_reference_twice_under_same_operation(monkeypatch, tmp_path):
    fixture = protocol(monkeypatch, tmp_path, optimized=False)
    with paired(fixture) as close:
        assert fixture.calls["reference"] == 1
        assert close() is fixture.completion
    assert fixture.calls["reference"] == 2
    assert fixture.calls["entry"] == fixture.calls["close"] == 0
    assert fixture.calls["replay"] == []


@pytest.mark.parametrize("phase", ["duplicate", "after_exit", "missing"])
def test_closing_gate_is_one_use_and_required_on_normal_exit(monkeypatch, tmp_path, phase):
    fixture = protocol(monkeypatch, tmp_path)
    if phase == "missing":
        with pytest.raises(scan.CodebaseScanResumeError, match="not completed"):
            with paired(fixture):
                pass
    else:
        with paired(fixture) as close:
            close()
            if phase == "duplicate":
                with pytest.raises(scan.CodebaseScanResumeError, match="already used"):
                    close()
        if phase == "after_exit":
            with pytest.raises(scan.CodebaseScanResumeError, match="inactive"):
                close()
    assert fixture.lease.released
    assert fixture.calls["close"] == (1 if phase == "missing" else 2)


@pytest.mark.parametrize("after_close", [False, True])
def test_exception_cleanup_never_replays_after_callback_or_launch(monkeypatch, tmp_path, after_close):
    fixture = protocol(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="caller failure"):
        with paired(fixture) as close:
            if after_close:
                close()
            fixture.control.close_error = AssertionError("cleanup replay")
            raise RuntimeError("caller failure")
    assert fixture.calls["close"] == (2 if after_close else 1)
    assert fixture.lease.released


def test_failed_close_is_consumed_and_releases_lease(monkeypatch, tmp_path):
    fixture = protocol(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="closing source drift"):
        with paired(fixture) as close:
            fixture.control.close_error = RuntimeError("closing source drift")
            try:
                close()
            except RuntimeError:
                with pytest.raises(scan.CodebaseScanResumeError, match="already used"):
                    close()
                raise
    assert fixture.lease.released and fixture.calls["close"] == 2


@pytest.mark.parametrize("phase", ["cancel", "deadline", "released"])
def test_shared_operation_expiry_refuses_before_closing_reads(monkeypatch, tmp_path, phase):
    fixture = protocol(monkeypatch, tmp_path)
    with pytest.raises((RuntimeError, scan.CodebaseScanResumeError), match="cancelled|deadline|ownership"):
        with paired(fixture) as close:
            if phase == "released":
                fixture.lease.released = True
            else:
                fixture.control.error = RuntimeError("cancelled" if phase == "cancel" else "deadline")
            close()
    assert fixture.calls["close"] == 1


def test_gate_cannot_cross_threads(monkeypatch, tmp_path):
    fixture = protocol(monkeypatch, tmp_path)
    errors = []
    with pytest.raises(scan.CodebaseScanResumeError, match="not completed"):
        with paired(fixture) as close:
            def other_thread():
                try:
                    close()
                except BaseException as error:
                    errors.append(error)
            thread = threading.Thread(target=other_thread)
            thread.start()
            thread.join()
    assert len(errors) == 1 and "ownership" in str(errors[0])
    assert fixture.calls["close"] == 1


@pytest.mark.parametrize("record", ["root", "completion", "page"])
def test_late_durable_cas_corruption_fails_before_fresh_native_close(monkeypatch, tmp_path, record):
    fixture = protocol(monkeypatch, tmp_path)
    actual = {"root": fixture.root, "completion": fixture.completion, "page": fixture.pages[0]}[record]
    with pytest.raises(ValueError):
        with paired(fixture) as close:
            fixture.cas.path_for(actual.artifact_cid).write_bytes(b"corrupt immutable payload")
            close()
    assert fixture.calls["close"] == 1


@pytest.mark.parametrize("record", ["root", "completion"])
def test_rehashed_caller_record_replacement_does_not_replace_entry_guard(monkeypatch, tmp_path, record):
    fixture = protocol(monkeypatch, tmp_path)
    actual = getattr(fixture, record)
    with pytest.raises(scan.CodebaseScanResumeError, match="input bytes"):
        with paired(fixture) as close:
            value = actual.to_dict()
            if record == "root":
                value["optimized"] = False
                replaced = root_record(value)
            else:
                value["model_artifact_cid"] = cid_for_bytes(b"other")
                replaced = scan.CodebaseScanResumeCompletion.from_dict(cid_for_structured(value), value)
            fixture.cas.put(value)
            object.__setattr__(actual, "artifact_cid", replaced.artifact_cid)
            object.__setattr__(actual, "_payload", replaced._payload)
            close()


@pytest.mark.parametrize("part", ["row", "saved", "provenance", "target", "batch", "chain"])
def test_forced_local_native_chain_mutation_is_refused(monkeypatch, tmp_path, part):
    fixture = protocol(monkeypatch, tmp_path)
    with pytest.raises(scan.CodebaseScanResumeError, match="chain|ancestry|batch"):
        with paired(fixture) as close:
            if part == "row":
                fixture.chain[0][0]["version_id"] = "forged"
            elif part == "saved":
                fixture.chain[0][1]["state"]["weights"][0] = 2
            elif part == "provenance":
                fixture.chain[0][2]["head"]["inert"] = False
            elif part == "target":
                object.__setattr__(fixture.chain[0][3][0], "canonical_bytes", inert_target(2).canonical_bytes)
            elif part == "batch":
                fixture.chain[0][3].clear()
            else:
                fixture.chain.clear()
            close()
    assert fixture.calls["close"] == 1


def test_mutation_in_native_closing_callback_is_refused(monkeypatch, tmp_path):
    fixture = protocol(monkeypatch, tmp_path)
    with pytest.raises(scan.CodebaseScanResumeError, match="closing callbacks"):
        with paired(fixture) as close:
            fixture.control.close_hook = lambda: fixture.chain[0][1]["state"]["weights"].append(2)
            close()
    assert fixture.calls["close"] == 2


def test_forced_private_registry_baseline_replacement_is_refused(monkeypatch, tmp_path):
    fixture = protocol(monkeypatch, tmp_path)
    with pytest.raises(scan.CodebaseScanResumeError, match="registry baseline"):
        with paired(fixture) as close:
            cells = dict(zip(close.__code__.co_freevars, close.__closure__))
            cells["before"].cell_contents = b"same-generation-forged-registry"
            close()
    assert fixture.calls["close"] == 1


@pytest.mark.parametrize("part", ["store", "connection", "cas", "registry_path", "catalog_path", "manager", "generation", "closed_alias"])
def test_native_owner_object_and_path_substitutions_are_refused(monkeypatch, tmp_path, part):
    fixture = protocol(monkeypatch, tmp_path)
    with pytest.raises(scan.CodebaseScanResumeError, match="owners changed"):
        with paired(fixture) as close:
            if part == "store":
                fixture.index.ingestor.store = SimpleNamespace(_connection=object(), _lock=object())
            elif part == "connection":
                fixture.index.ingestor.store._connection = object()
            elif part == "cas":
                fixture.index.artifacts = ImmutableCAS(tmp_path / "other")
            elif part == "registry_path":
                fixture.registry.database_path = tmp_path / "other.duckdb"
                fixture.registry.database_path.write_bytes(b"inert-db-owner")
                fixture.registry.database_path.with_name(fixture.registry.database_path.name + ".owner.lock").hardlink_to(
                    tmp_path / "model.duckdb.owner.lock")
            elif part == "catalog_path":
                fixture.index.catalog._database_path = tmp_path / "other.duckdb"
            elif part == "manager":
                fixture.registry._manager = object()
            elif part == "generation":
                fixture.registry.owner_generation += 1
            else:
                fixture.registry._closed = 0
            close()
    assert fixture.calls["close"] == 1


@pytest.mark.parametrize("part", ["database", "artifacts", "lock"])
def test_native_model_owner_inode_replacement_is_refused(monkeypatch, tmp_path, part):
    fixture = protocol(monkeypatch, tmp_path)
    with pytest.raises(scan.CodebaseScanResumeError, match="owners changed|lock ownership"):
        with paired(fixture) as close:
            if part == "database":
                path = fixture.registry.database_path
                path.rename(path.with_suffix(".previous"))
                path.write_bytes(b"inert-db-owner")
            elif part == "artifacts":
                path = fixture.registry.artifact_root
                path.rename(path.with_name("previous-models"))
                path.mkdir()
            else:
                path = fixture.registry.database_path.with_name(fixture.registry.database_path.name + ".owner.lock")
                path.rename(path.with_suffix(".previous"))
                path.write_bytes(b"")
            close()
    assert fixture.calls["close"] == 1


def test_receiver_retains_bounded_hashes_not_page_bodies(monkeypatch, tmp_path):
    fixture = protocol(monkeypatch, tmp_path, count=257)
    with paired(fixture) as close:
        cells = {name: cell.cell_contents for name, cell in zip(close.__code__.co_freevars, close.__closure__)}
        assert "manifest" not in cells and "receipt" not in cells
        assert len(cells["page_guards"]) == len(fixture.pages)
        assert all(type(item) is tuple and type(item[0]) is str and type(item[1]) is int
                   and len(item[2]) == 64 for item in cells["page_guards"])
        assert all(type(value) is not bytes for value in cells["page_guards"])
        assert len(scan._wire(cells["page_guards"])) < receive._MAX_METADATA_BYTES
        close()


@pytest.mark.parametrize("phase", ["success", "cancel", "deadline"])
def test_real_nested_resource_lease_spans_callbacks_and_releases_on_all_outcomes(monkeypatch, tmp_path, phase):
    """Native scheduler accounting; source/model work remains a protocol double."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig, ResourceLane, LeaseCancelledError, LeaseTimeoutError)
    actual_scope = scan._scope
    fixture = protocol(monkeypatch, tmp_path)
    monkeypatch.setattr(scan, "_scope", actual_scope)
    monkeypatch.setattr(scan, "_owners", lambda *args: None)
    clock = [100.0]
    monkeypatch.setattr(scan, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig(total_cpu_slots=2, total_memory_mb=4096,
        total_child_process_slots=2, lane_reservations={}, state_path=tmp_path / "scheduler.json",
        auto_renew_leases=False))
    cancel = threading.Event()
    with scheduler.acquire(lane=ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1, memory_mb=2048,
            child_process_slots=2, timeout=1) as parent:
        def operation():
            with paired(fixture, parent_lease=parent, cancel_event=cancel, timeout_seconds=30) as close:
                cells = dict(zip(close.__code__.co_freevars, close.__closure__))
                current = cells["inputs_current"].cell_contents
                child = dict(zip(current.__code__.co_freevars, current.__closure__))["lease"].cell_contents
                assert not child.released and child is not parent
                assert scheduler.snapshot()["active_child_lease_count"] == 1
                if phase == "cancel":
                    cancel.set()
                elif phase == "deadline":
                    clock[0] = 131.0
                close()
        if phase == "success":
            operation()
        else:
            error = LeaseCancelledError if phase == "cancel" else LeaseTimeoutError
            with pytest.raises(error):
                operation()
        assert scheduler.snapshot()["active_child_lease_count"] == 0 and not parent.released
    snapshot = scheduler.snapshot()
    assert snapshot["active_lease_count"] == 0 and snapshot["allocated"]["memory_mb"] == 0


@pytest.mark.parametrize("part", ["page", "chain", "ledger"])
def test_metadata_limits_fail_closed_before_yield(monkeypatch, tmp_path, part):
    fixture = protocol(monkeypatch, tmp_path)
    if part == "ledger":
        monkeypatch.setattr(receive, "_chain_guard", lambda *args: ())
        # The page guards fit but the complete coverage/descriptor ledger does not.
        size = len(scan._wire([(page.artifact_cid, len(page._payload), "a" * 64) for page in fixture.pages]))
        monkeypatch.setattr(receive, "_MAX_METADATA_BYTES", size)
    else:
        monkeypatch.setattr(receive, "_MAX_METADATA_BYTES", 1)
        if part == "chain":
            fixture = protocol(monkeypatch, tmp_path / "empty", count=0)
    with pytest.raises(scan.CodebaseScanResumeError, match="metadata"):
        with paired(fixture):
            pytest.fail("oversize operation yielded a gate")
    assert fixture.lease.released


def test_receiving_helper_is_pinned_without_public_token_api():
    assert receive.__name__ in scan._implementation()["files"]
    assert "_paired_current_codebase_scan_completion" not in scan.__all__


@pytest.fixture(scope="module")
def native_transport257(tmp_path_factory):
    """Real257 membership, one native Python target, 256 explicit unindexed rows."""
    directory = tmp_path_factory.mktemp("paired-receive257")
    connection = duckdb.connect(str(directory / "source.duckdb"), config={"threads": 1, "memory_limit": "128MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(directory / "cas")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
        catalog=CodebaseCatalog(store, artifacts, limits=CodebaseCatalogLimits(max_entries=512)))
    sources = {"unit.py": b"def step(n: int) -> int:\n    return n + 1\n"}
    sources.update({f"text{i:03d}.txt": f"retained exact source {i}\n".encode() for i in range(256)})
    entries = tuple(SnapshotEntry(path, "source", len(raw), cid_for_bytes(raw), captured_bytes=raw)
                    for path, raw in sorted(sources.items()))
    snapshot = RepositorySnapshot("paired-receive257", entries, "filesystem", 65536, 512)
    state = RepositoryScanner(repository_id=snapshot.repository_id).scan_snapshot(snapshot, sources)
    manifests, publications = [], []
    def seal(publication):
        by_path = {item.source_file.path: item for item in publication.projections}
        units = tuple(CodebaseUnit(entry.source_key, entry.entry_cid,
            None if entry.path not in by_path else by_path[entry.path].ast_cid,
            "unindexed" if entry.path not in by_path else by_path[entry.path].ast_blob.parse_status)
            for entry in snapshot.entries)
        manifest = CodebaseIRManifest(snapshot, state, publication.revision_id, units)
        for raw in sources.values():
            artifacts.put_bytes(raw)
        for projection in publication.projections:
            artifacts.put(json.loads(projection.ast_blob.payload_json))
        artifacts.put(manifest.to_dict())
        manifests.append(manifest)
    def publish(publication):
        publications.append(index.catalog.publish(operation_id="paired-fixture257", manifest=manifests[0],
                                                  expected_head=None, projections=publication.projections))
    index.ingestor.ingest_snapshot(snapshot, created_at=1.0, before_publish=seal, publish_batch=publish)
    yield index, manifests[0], publications[0], connection, directory
    connection.close()


def native_fixture(native_transport257, monkeypatch):
    """Preserve genuine source/AST/all13 SQL; replace only model/scope/checkout."""
    index, manifest, publication, connection, directory = native_transport257
    head = publication.head
    target = scan.targets.prepare_codebase_targets(index, expected_head=head, path="unit.py")
    space = scan.features.build_feature_space("codebase_ir",
        [scan.targets.CODEBASE_PROGRAM_PROJECTION, scan.targets.CODEBASE_CONTRACTS_PROJECTION], [target])
    # Deliberately unknown vocabulary: native zero-coverage disposition, no forward.
    space["columns"] = [[name, "not-a-native-atom"] for name in space["projection_ids"]]
    saved = {"contract": {}, "feature_space": space, "state": {"contract_sha256": "1" * 64, "latent_width": 8}}
    raw = scan.training._wire(saved)
    row = {"version_id": "inert-weight-owner", "variant_id": "inert-weight-owner",
           "artifact": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}}
    provenance = {"head": head.to_dict(), "selections": []}
    chain = [(row, saved, provenance, [target], [target], [target], [target])]
    value = root_body()
    value.update(head=head.to_dict(), head_cid=cid_for_structured(head.to_dict()), members=scan._members(manifest),
                 model=scan._model(chain), implementation=scan._implementation(),
                 limits=scan.CodebaseScanResumeLimits(page_entries=64).to_dict())
    value["membership_cid"] = cid_for_structured(value["members"])
    root = root_record(value)
    index.artifacts.put(value)
    previous, pages, counts = None, [], {}
    for start in range(0, 257, 64):
        entries, request = scan._prepare_page(index, root, manifest, publication, chain, start, 0, lambda: 30)
        assert not request["targets"] and not request["member_indices"]
        page_value = {"schema": scan.PAGE_SCHEMA, "root_cid": root.artifact_cid, "head_cid": value["head_cid"],
            "membership_cid": value["membership_cid"], "model_artifact_cid": value["model"]["artifact_cid"],
            "start": start, "end": start + len(entries), "total_entries": 257,
            "page_membership_cid": cid_for_structured(value["members"][start:start + len(entries)]),
            "previous_page_cid": previous, "entries": entries, "inference": None, "worker_receipt": None,
            "coverage": {"inventory_entries": len(entries), "inferred_rows": 0,
                "dispositions": {name: sum(entry["disposition"] == name for entry in entries)
                                  for name in sorted({entry["disposition"] for entry in entries})}},
            "authority": dict(scan._FALSE)}
        page = page_record(page_value)
        index.artifacts.put_bytes(page._payload)
        pages.append(page)
        previous = page.artifact_cid
        for name, number in page_value["coverage"]["dispositions"].items():
            counts[name] = counts.get(name, 0) + number
    value = scan._completion_value(root, [scan._descriptor(page) for page in pages], 257, 0, dict(sorted(counts.items())))
    complete = scan.CodebaseScanResumeCompletion.from_dict(cid_for_structured(value), value)
    index.artifacts.put(value)
    registry = SimpleNamespace(database_path=directory / "explicit-inert-model.duckdb", artifact_root=directory / "inert-models",
        _manager=object(), _lock=object(), _pid=os.getpid(), owner_generation=2, _closed=False)
    registry.database_path.write_bytes(b"explicit inert native-model boundary")
    registry.artifact_root.mkdir(exist_ok=True)
    registry._owner_file = registry.database_path.with_name(registry.database_path.name + ".owner.lock").open("a+b")
    lease, signal = SimpleNamespace(released=False), threading.Event()
    @contextmanager
    def scope(*args, **kwargs):
        lease.released = False
        try:
            yield lease, signal, lambda: 30
        finally:
            lease.released = True
    monkeypatch.setattr(scan, "_scope", scope)
    monkeypatch.setattr(scan, "snapshot_repository", lambda *args, **kwargs: manifest.snapshot)
    monkeypatch.setattr(scan, "_resume_lineage", lambda *args, **kwargs: chain)
    monkeypatch.setattr(scan.legacy, "_registry_inventory", lambda *args: b"inert-owner-generation-2")
    monkeypatch.setattr(scan.legacy, "_model_fence", lambda *args: None)
    monkeypatch.setattr(scan, "_owners", lambda *args: None)
    return SimpleNamespace(root=root, completion=complete, pages=pages, index=index, registry=registry,
                           manifest=manifest, connection=connection, chain=chain)


def test_native257_paired_pages_equal_public_reference_and_replay_once(native_transport257, monkeypatch):
    fixture = native_fixture(native_transport257, monkeypatch)
    native_replay, calls = scan._replay_page, []
    def replay(*args):
        calls.append(args[5].artifact_cid)
        return native_replay(*args)
    monkeypatch.setattr(scan, "_replay_page", replay)
    assert scan.validate_current_codebase_scan_completion(fixture.completion, fixture.index, ".",
                    root=fixture.root, registry=fixture.registry) is fixture.completion
    expected = calls[:]
    calls.clear()
    with paired(fixture) as close:
        assert calls == expected == [page.artifact_cid for page in fixture.pages]
        assert close() is fixture.completion
        assert calls == expected
    assert fixture.completion.to_dict()["coverage"]["dispositions"] == {"feature_incompatible": 1, "unindexed": 256}


@pytest.mark.parametrize("corruption", ["source", "ast", "manifest", "head", "relation"])
def test_native257_late_source_cas_head_and_sql_changes_fail_fresh_close(native_transport257, monkeypatch, corruption):
    fixture = native_fixture(native_transport257, monkeypatch)
    index, manifest, _, connection, _ = native_transport257
    head = index.current(manifest.snapshot.repository_id)
    path, original = None, None
    try:
        with pytest.raises(ValueError):
            with paired(fixture) as close:
                if corruption in {"source", "ast", "manifest"}:
                    python_entry = next(entry for entry in manifest.snapshot.entries if entry.path == "unit.py")
                    python_unit = next(unit for unit in manifest.units if unit.source_key == python_entry.source_key)
                    cid = {"source": python_entry.source_cid, "ast": python_unit.ast_cid,
                           "manifest": manifest.cid}[corruption]
                    path = index.artifacts.path_for(cid, source=corruption == "source")
                    original = path.read_bytes()
                    path.write_bytes(b"late native artifact corruption")
                elif corruption == "head":
                    connection.execute("UPDATE codebase_control.heads SET generation=generation+1 WHERE repository_id=?",
                                       [head.repository_id])
                else:
                    connection.execute("UPDATE source_files SET path='corrupt.py' WHERE path='unit.py'")
                close()
    finally:
        if path is not None:
            path.write_bytes(original)
        elif corruption == "head":
            connection.execute("UPDATE codebase_control.heads SET generation=? WHERE repository_id=?",
                               [head.generation, head.repository_id])
        elif corruption == "relation":
            connection.execute("UPDATE source_files SET path='unit.py' WHERE path='corrupt.py'")
