"""Tiny native successor selection and receiving controls.

The module fixture explicitly trains one root and one direct child, one epoch
each. Coordinator/receiver scopes prohibit fitting and forward inference. Only
the ordinary page test runs numerical inference. These are tiny native owners
and test scheduler resources, not a large-repository or execution attestation.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseHead
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as scan
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_successor as delta
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_successor_model as successor
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as training
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import RepositoryCodebaseIndex, CodebaseScanLimits
from ipfs_datasets_py.logic.software_contracts.content import canonical_dag_json_bytes, cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_runtime_registry as runtimes
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig


@contextmanager
def no_numerical_work():
    def forbidden(*args, **kwargs):
        pytest.fail("successor selection/receiving attempted fitting or forward inference")
    with pytest.MonkeyPatch.context() as patch:
        for owner, name in ((training, "train_current_codebase_features"), (training, "_worker"),
                (scan, "_worker"), (scan.features, "train_projection_features"),
                (scan.features, "infer_projection_features"),
                (runtimes.SourceBoundCodebaseFeatureRuntime, "train"),
                (runtimes.SourceBoundCodebaseFeatureRuntime, "infer")):
            patch.setattr(owner, name, forbidden)
        yield


def open_owners(native):
    import duckdb
    native.connection = duckdb.connect(str(native.root / "source.duckdb"),
        config={"threads": 1, "memory_limit": "64MB"})
    store = DuckDBASTStore(connection=native.connection)
    native.cas = ImmutableCAS(native.root / "source-artifacts")
    native.index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=native.cas,
        catalog=CodebaseCatalog(store, native.cas))
    native.registry = AutoencoderRegistry(native.root / "model.duckdb", native.root / "model-artifacts")


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    pytest.importorskip("duckdb")
    root = tmp_path_factory.mktemp("successor-model-tiny-native")
    repo = root / "repository"
    repo.mkdir()
    for path, offset in (("train.py", 1), ("tune.py", 3), ("canary.py", 5)):
        (repo / path).write_text(f"def step(n: int) -> int:\n    return n + {offset}\n")
    owner = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=root / "admission.json", proof_resource_sampler=lambda: ProofHostResources(8, 8192, 8192),
        lane_reservations={}, auto_renew_leases=False, poll_interval_seconds=.005))
    n = SimpleNamespace(root=root, repo=repo, scheduler=owner,
        limits=scan.CodebaseScanResumeLimits(max_inventory_entries=8, page_entries=2, max_pages=4))
    open_owners(n)
    selections = [training.CodebaseTrainingSelection(path, role) for path, role in
        (("train.py", "train"), ("tune.py", "tune"), ("canary.py", "canary"))]
    try:
        n.previous_head = n.index.prepare_current(repo, repository_id="test:successor-model",
            operation_id="capture-root", expected_head=None, limits=CodebaseScanLimits(8, 4096), scheduler=owner).head
        n.parent = training.train_current_codebase_features(n.index, repo, expected_head=n.previous_head,
            registry=n.registry, selections=selections, operation_id="root", epochs=1, learning_rate=.002,
            scheduler=owner)
        n.parent_id = n.parent.to_dict()["version_id"]
        n.parent_row = n.registry.get_version(n.parent_id)
        n.parent_bytes = n.registry.artifact_path(n.parent_row["artifact"]).read_bytes()
        with no_numerical_work():
            n.old_root = scan.start_current_codebase_scan(n.index, repo, expected_head=n.previous_head,
                registry=n.registry, version_id=n.parent_id, limits=n.limits, scheduler=owner)
        (repo / "train.py").write_text("def step(n: int) -> int:\n    return n + 2\n")
        n.current_head = n.index.prepare_current(repo, repository_id=n.previous_head.repository_id,
            operation_id="capture-child", expected_head=n.previous_head,
            limits=CodebaseScanLimits(8, 4096), scheduler=owner).head
        n.child = training.train_current_codebase_features(n.index, repo, expected_head=n.current_head,
            registry=n.registry, selections=selections, operation_id="child", parent_version_id=n.parent_id,
            epochs=1, learning_rate=.002, scheduler=owner)
        n.child_id = n.child.to_dict()["version_id"]
        n.child_row = n.registry.get_version(n.child_id)
        n.source_delta = delta.build_current_codebase_source_delta(n.index, repo,
            previous_head=n.previous_head, expected_head=n.current_head, scheduler=owner)
        with no_numerical_work():
            n.selection = start(n)
        yield n
        assert n.registry.artifact_path(n.parent_row["artifact"]).read_bytes() == n.parent_bytes
        assert n.registry.resolve_head(n.child_row["variant_id"], "main") is None
        assert_idle(n)
    finally:
        n.registry.close()
        n.connection.close()


def start(n, **changes):
    options = dict(source_delta=n.source_delta, registry=n.registry, previous_version_id=n.parent_id,
        version_id=n.child_id, limits=n.limits, scheduler=n.scheduler)
    options.update(changes)
    return successor.start_current_codebase_successor_scan(n.index, n.repo, **options)


def receive(n, record=None):
    return successor.validate_current_codebase_successor_scan(n.selection if record is None else record,
        n.index, n.repo, registry=n.registry, scheduler=n.scheduler)


def assert_idle(n):
    snapshot = n.scheduler.snapshot()
    assert snapshot["active_lease_count"] == snapshot["waiting_request_count"] == 0


def test_native_direct_child_selection_is_fresh_private_and_optout_equivalent(native):
    n = native
    before = scan.legacy._registry_inventory(n.registry, scan.legacy.CodebaseInventoryScanLimits(), lambda: 120)
    with no_numerical_work():
        default, reference = start(n), start(n, optimized=False)
        assert receive(n, default) == default
        assert receive(n, reference) == reference
    left, right = default.to_dict(), reference.to_dict()
    assert left["previous_training_record_cid"] == n.parent.artifact_cid
    assert left["training_record_cid"] == n.child.artifact_cid
    assert left["previous_head"] == n.previous_head.to_dict()
    assert left["current_head"] == n.current_head.to_dict()
    assert left["root_cid"] != n.old_root.artifact_cid
    assert len(left["implementation"]["files"]) == 23
    assert all(flag is False for flag in left["authority"].values())
    assert all(left[name] is False for name in successor._FALSE)
    for key in left.keys() - {"optimized", "root_cid"}:
        assert left[key] == right[key]
    roots = [scan.load_codebase_scan_resume_root(n.cas, item["root_cid"]).to_dict() for item in (left, right)]
    for key in roots[0].keys() - {"optimized"}:
        assert roots[0][key] == roots[1][key]
    assert n.registry.artifact_path(n.parent_row["artifact"]).read_bytes() == n.parent_bytes
    assert scan.legacy._registry_inventory(n.registry, scan.legacy.CodebaseInventoryScanLimits(), lambda: 120) == before
    assert_idle(n)


def test_native_new_root_runs_ordinary_pages_and_complete_receiving_without_more_fits(native):
    n = native
    root = scan.load_codebase_scan_resume_root(n.cas, n.selection.to_dict()["root_cid"])
    pages, cursor = [], None
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(training, "train_current_codebase_features", lambda *a, **k: pytest.fail("scan fitted"))
        patch.setattr(training, "_worker", lambda *a, **k: pytest.fail("scan launched training worker"))
        patch.setattr(scan.features, "train_projection_features", lambda *a, **k: pytest.fail("scan fitted"))
        while True:
            page = scan.scan_current_codebase_page(n.index, n.repo, root=root, registry=n.registry,
                cursor=cursor, scheduler=n.scheduler)
            pages.append(page)
            cursor = page.next_cursor
            if cursor is None:
                break
    assert len(pages) == 2
    assert [page.to_dict()["start"] for page in pages] == [0, 2]
    completion = scan.complete_current_codebase_scan(n.index, n.repo, root=root, registry=n.registry,
        tail_page_cid=pages[-1].artifact_cid, scheduler=n.scheduler)
    assert completion.to_dict()["coverage"] == {"inventory_entries": 3, "inferred_rows": 3,
        "pages": 2, "dispositions": {"inferred": 3}}
    with no_numerical_work():
        assert scan.validate_current_codebase_scan_completion(completion, n.index, n.repo,
            root=root, registry=n.registry, scheduler=n.scheduler) == completion
        assert receive(n) == n.selection
    assert all(flag is False for flag in completion.to_dict()["authority"].values())
    assert_idle(n)


def test_native_same_process_cold_owner_reopen_receives_without_fitting_inference_or_cas_writes(native):
    n = native
    index, generation = n.index, n.registry.owner_generation
    n.registry.close()
    n.connection.close()
    open_owners(n)
    assert n.index is not index and n.registry.owner_generation == generation + 1
    with no_numerical_work(), pytest.MonkeyPatch.context() as patch:
        patch.setattr(n.cas, "put", lambda *a, **k: pytest.fail("receiving published CAS"))
        patch.setattr(n.cas, "put_bytes", lambda *a, **k: pytest.fail("receiving published source CAS"))
        loaded = successor.load_codebase_successor_scan(n.cas, n.selection.artifact_cid)
        assert loaded == n.selection and receive(n, loaded) == loaded
    assert_idle(n)


@pytest.mark.parametrize("previous,current", [("parent", "parent"), ("child", "child"),
    ("unknown", "child"), ("parent", "unknown")])
def test_native_non_direct_or_missing_selection_never_falls_back_to_training(native, previous, current):
    ids = {"parent": native.parent_id, "child": native.child_id, "unknown": "unknown-model"}
    with no_numerical_work(), pytest.raises(ValueError):
        start(native, previous_version_id=ids[previous], version_id=ids[current])
    assert_idle(native)


@pytest.mark.parametrize("side", ["parent", "child"])
def test_native_replayed_model_head_must_match_each_complete_delta_head(native, monkeypatch, side):
    replay = scan._resume_lineage
    def altered(*args, **kwargs):
        chain = replay(*args, **kwargs)
        position = 1 if side == "parent" else 0
        item = list(chain[position])
        item[2] = deepcopy(item[2])
        item[2]["head"] = (native.current_head if side == "parent" else native.previous_head).to_dict()
        chain[position] = tuple(item)
        return chain
    monkeypatch.setattr(scan, "_resume_lineage", altered)
    with no_numerical_work(), pytest.raises(successor.CodebaseSuccessorScanError, match="complete source head"):
        start(native)
    assert_idle(native)


def test_native_old_model_cannot_start_current_scan(native):
    with no_numerical_work(), pytest.raises(ValueError, match="not bound to current head"):
        scan.start_current_codebase_scan(native.index, native.repo, expected_head=native.current_head,
            registry=native.registry, version_id=native.parent_id, limits=native.limits, scheduler=native.scheduler)
    assert_idle(native)


@pytest.mark.parametrize("configuration", [{"memory_mb": 512}, {"timeout_seconds": 0}, {"optimized": 1}])
def test_native_invalid_resource_or_optimization_options_refuse_without_work(native, configuration):
    with no_numerical_work(), pytest.raises(ValueError):
        start(native, **configuration)
    assert_idle(native)


def test_native_post_replay_state_mutation_cannot_change_published_training_record(native, monkeypatch):
    original = successor._native_models
    def changed(*args, **kwargs):
        models, chain = original(*args, **kwargs)
        chain[0][1]["state"]["completed_epochs"] += 1
        return models, chain
    monkeypatch.setattr(successor, "_native_models", changed)
    with no_numerical_work(), pytest.raises((ValueError, OSError)):
        receive(native)
    assert_idle(native)


@pytest.mark.parametrize("mutation", ["checkpoint", "registry"])
def test_native_late_delta_load_mutation_is_followed_by_model_and_registry_fences(native, monkeypatch, mutation):
    n = native
    original = delta.load_codebase_source_delta
    path = n.registry.artifact_path(n.child_row["artifact"])
    checkpoint = path.read_bytes()
    metadata = training._wire(n.child_row["metadata"]).decode()
    calls = []
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        # Receiver load, delta receiving entry/close, then coordinator close.
        if len(calls) == 4:
            if mutation == "checkpoint":
                path.write_bytes(checkpoint + b" ")
            else:
                with n.registry._transaction() as connection:
                    connection.execute("UPDATE autoencoder_control.versions SET metadata=? WHERE version_id=?",
                        [training._wire({**n.child_row["metadata"], "unexpected": True}).decode(), n.child_id])
        return result
    monkeypatch.setattr(delta, "load_codebase_source_delta", changed)
    try:
        with no_numerical_work(), pytest.raises(ValueError):
            receive(n)
        assert len(calls) == 4
    finally:
        path.write_bytes(checkpoint)
        with n.registry._transaction() as connection:
            connection.execute("UPDATE autoencoder_control.versions SET metadata=? WHERE version_id=?", [metadata, n.child_id])
    assert_idle(n)


@pytest.mark.parametrize("mutation", ["checkpoint", "registry"])
def test_native_final_delta_observation_mutation_is_followed_by_model_and_registry_fences(native, monkeypatch, mutation):
    n = native
    original = delta._observe
    path = n.registry.artifact_path(n.child_row["artifact"])
    checkpoint = path.read_bytes()
    metadata = training._wire(n.child_row["metadata"]).decode()
    calls = []
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        # The delta receiver observes twice; the coordinator observes last.
        if len(calls) == 3:
            if mutation == "checkpoint":
                path.write_bytes(checkpoint + b" ")
            else:
                with n.registry._transaction() as connection:
                    connection.execute("UPDATE autoencoder_control.versions SET metadata=? WHERE version_id=?",
                        [training._wire({**n.child_row["metadata"], "unexpected": True}).decode(), n.child_id])
        return result
    monkeypatch.setattr(delta, "_observe", changed)
    try:
        with no_numerical_work(), pytest.raises(ValueError):
            receive(n)
        assert len(calls) == 3
    finally:
        path.write_bytes(checkpoint)
        with n.registry._transaction() as connection:
            connection.execute("UPDATE autoencoder_control.versions SET metadata=? WHERE version_id=?", [metadata, n.child_id])
    assert_idle(n)


def test_native_record_mutation_after_final_source_observation_cannot_escape(native, monkeypatch):
    record = native.selection
    payload, artifact_cid = record._payload, record.artifact_cid
    original, calls = successor._source_exit, []
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        body = record.to_dict()
        body["optimized"] = not body["optimized"]
        object.__setattr__(record, "_payload", canonical_dag_json_bytes(body))
        object.__setattr__(record, "artifact_cid", cid_for_structured(body))
        return result
    monkeypatch.setattr(successor, "_source_exit", changed)
    try:
        with no_numerical_work(), pytest.raises(ValueError):
            receive(native)
        assert len(calls) == 1
    finally:
        object.__setattr__(record, "_payload", payload)
        object.__setattr__(record, "artifact_cid", artifact_cid)
    assert_idle(native)


def test_native_late_model_fence_checkout_edit_is_followed_by_complete_source_observation(native, monkeypatch):
    original = scan.legacy._model_fence
    path = native.repo / "train.py"
    raw, calls = path.read_bytes(), []
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(1)
        if len(calls) == 2:
            path.write_bytes(raw + b"# edit during final model fence\n")
        return result
    monkeypatch.setattr(scan.legacy, "_model_fence", changed)
    try:
        with no_numerical_work(), pytest.raises(ValueError):
            receive(native)
        assert len(calls) == 2
    finally:
        path.write_bytes(raw)
    assert_idle(native)


@pytest.mark.parametrize("name", ["root_cid", "training_record_cid", "source_delta_cid"])
def test_native_missing_or_corrupt_linked_cas_is_not_current(native, name):
    path = native.cas.path_for(native.selection.to_dict()[name])
    raw = path.read_bytes()
    try:
        path.write_bytes(raw + b"\n")
        with no_numerical_work(), pytest.raises(ValueError):
            receive(native)
    finally:
        path.write_bytes(raw)
    assert_idle(native)


def test_native_producer_drift_at_closing_callback_is_not_current(native, monkeypatch):
    original, calls = successor._implementation, []
    def changed():
        result = original()
        calls.append(1)
        if len(calls) >= 3:
            result["files"][successor.__name__] = "0" * 64
            result["sha256"] = scan.features.digest(result["files"])
        return result
    monkeypatch.setattr(successor, "_implementation", changed)
    with no_numerical_work(), pytest.raises(successor.CodebaseSuccessorScanError, match="implementation|producer"):
        receive(native)
    assert len(calls) >= 3
    assert_idle(native)


def pure_body():
    def cid(name):
        return cid_for_structured({"pure_successor_control": name})
    def head(generation):
        snapshot = cid("snapshot" + str(generation))
        return CodebaseHead("pure-successor", generation, cid("manifest" + str(generation)), snapshot,
            "rev:pure-successor:snapshot:" + snapshot, cid("receipt" + str(generation))).to_dict()
    def model(name):
        raw = name.encode()
        artifact = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        return {"version_id": name, "variant_id": "pure-variant", "artifact": artifact,
            "artifact_cid": cid_for_bytes(raw), "contract_sha256": "1" * 64,
            "state_sha256": hashlib.sha256(raw).hexdigest(), "feature_space_sha256": "3" * 64,
            "latent_width": 8, "feature_columns": 2, "projection_ids": ["a", "b"],
            "projection_widths": {"a": 1, "b": 1}, "ancestry": [{"version_id": name, "artifact": artifact}]}
    parent, child = model("pure-parent"), model("pure-child")
    child["ancestry"].extend(deepcopy(parent["ancestry"]))
    files = {"pure.protocol": "4" * 64}
    return {"schema": successor.SCHEMA, "source_delta_cid": cid("delta"), "previous_head": head(1),
        "current_head": head(2), "previous_membership_cid": cid("previous-members"),
        "current_membership_cid": cid("current-members"), "previous_training_record_cid": cid("parent-record"),
        "training_record_cid": cid("child-record"), "previous_model": parent, "model": child,
        "root_cid": cid("root"), "scan_limits": scan.CodebaseScanResumeLimits().to_dict(), "optimized": True,
        "implementation": {"files": files, "sha256": scan.features.digest(files),
            "scope": "listed_local_files_only_not_execution_attestation"}, "authority": dict(scan._FALSE),
        **{name: False for name in successor._FALSE}}


def test_pure_inert_record_is_detached_and_cold_cas_load_has_no_currentness_claim(tmp_path):
    body = pure_body()
    record = successor.CodebaseSuccessorScanRecord.from_dict(cid_for_structured(body), body)
    cas = ImmutableCAS(tmp_path / "cas")
    assert cas.put(body) == record.artifact_cid
    with no_numerical_work():
        assert successor.load_codebase_successor_scan(ImmutableCAS(cas.root), record.artifact_cid) == record
    body["model"]["state_sha256"] = "0" * 64
    record.to_dict()["model"]["state_sha256"] = "0" * 64
    assert record.to_dict()["model"]["state_sha256"] != "0" * 64


@pytest.mark.parametrize("mutation", ["extra", "missing", "schema", "optimized_alias", "generation",
    "same_model", "ancestry", "basis", "raw_record_cid", "implementation_digest"])
def test_pure_rehash_does_not_repair_closed_shape_or_child_bindings(mutation):
    body = pure_body()
    if mutation == "extra":
        body["hidden"] = True
    elif mutation == "missing":
        del body["root_cid"]
    elif mutation == "schema":
        body["schema"] += ":unknown"
    elif mutation == "optimized_alias":
        body["optimized"] = 1
    elif mutation == "generation":
        body["current_head"]["generation"] = 3
    elif mutation == "same_model":
        body["model"] = deepcopy(body["previous_model"])
    elif mutation == "ancestry":
        body["model"]["ancestry"] = body["model"]["ancestry"][:1]
    elif mutation == "basis":
        body["model"]["contract_sha256"] = "0" * 64
    elif mutation == "raw_record_cid":
        body["training_record_cid"] = cid_for_bytes(b"raw")
    else:
        body["implementation"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        successor.CodebaseSuccessorScanRecord.from_dict(cid_for_structured(body), body)


@pytest.mark.parametrize("name", [*scan._FALSE, *successor._FALSE])
def test_pure_every_false_authority_and_work_flag_rejects_integer_alias(name):
    body = pure_body()
    if name in body["authority"]:
        body["authority"][name] = 0
    else:
        body[name] = 0
    with pytest.raises(ValueError):
        successor.CodebaseSuccessorScanRecord.from_dict(cid_for_structured(body), body)
