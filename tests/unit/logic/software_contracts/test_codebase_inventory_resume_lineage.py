"""Bounded reuse controls, plus genuine 257-member native target replay.

The protocol controls use explicitly inert owner/model doubles. Native controls
publish real DuckDB/CAS/AST history and exercise the unchanged target producer;
they do not fit a model or qualify retained model lineage/current checkout.
Full pretrained-chain parity belongs to the separate admitted native fixture.
"""
from copy import deepcopy
from dataclasses import replace
import gc
import json
from types import SimpleNamespace
import weakref

import duckdb
import pytest

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseCatalog, CodebaseCatalogLimits
from ipfs_datasets_py.logic.formalization.autoencoder.domain_targets import DomainTargetEnvelope, build_target_envelope
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_lineage as lineage
from ipfs_datasets_py.logic.software_contracts import codebase_inventory_resume as scan
from ipfs_datasets_py.logic.software_contracts import codebase_ir_targets as targets
from ipfs_datasets_py.logic.software_contracts import codebase_source_training as training
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.codebase_ir import CodebaseIRManifest, CodebaseUnit, RepositoryCodebaseIndex
from ipfs_datasets_py.logic.software_contracts.content import cid_for_bytes, cid_for_structured
from ipfs_datasets_py.logic.software_contracts.duckdb_ast_store import DuckDBASTStore
from ipfs_datasets_py.logic.software_contracts.duckdb_ingest import DuckDBASTIngestor
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import RepositorySnapshot, SnapshotEntry


def isolated_context(index=None, *, maximum=40 * 1024 * 1024):
    """Bypass model ownership solely for private cache mechanics/target tests."""
    context = object.__new__(scan._ResumeLineageContext)
    context.index, context.registry = index or object(), object()
    context.limits = training.CodebaseFeatureTrainingLimits()
    context.current_seal = None
    context.checkpoint = lambda: None
    context.max_cache_bytes = maximum
    context.counters = lineage.InventoryLineageCounters()
    context._candidates, context._targets, context._bindings, context._prepared = {}, {}, {}, {}
    context._historical_seal = None
    return context


def inert_target(value=1):
    return build_target_envelope(domain_id="codebase_ir", source_digest="a" * 64,
        projections=[{"projection_id": "fixture", "view_id": "fixture", "representation_kind": "fixture",
            "producer_id": "inert-protocol", "view_role": "fixture", "expression": {"constant": value}}],
        validation=[{"validator_id": "inert-protocol", "status": "passed", "details": {
            "source_binding": {"head": {"repository_id": "inert"}, "path": "unit.py",
                               "content_sha256": "b" * 64}, "authored_contracts": []}}])


def stub_targets(monkeypatch):
    preparations, validations = [], []
    def prepare(index, **kwargs):
        preparations.append(kwargs)
        return inert_target()
    def validate(target):
        validations.append(target.canonical_bytes)
        return DomainTargetEnvelope.from_dict(target.to_dict())
    monkeypatch.setattr(targets, "prepare_codebase_targets", prepare)
    monkeypatch.setattr(training, "_targets_adapter", lambda: SimpleNamespace(validate_codebase_targets=validate))
    monkeypatch.setattr(lineage, "seal_inventory", lambda *args, **kwargs: pytest.fail("legacy256 seal called"))
    return preparations, validations


def test_prepare_reuses_exact_head_path_contract_request_and_detaches_binding(monkeypatch):
    preparations, validations = stub_targets(monkeypatch)
    context = isolated_context()
    head = SimpleNamespace(to_dict=lambda: {"repository_id": "inert", "generation": 1})
    first = context.prepare(head, "unit.py")
    assert context.prepare(head, "unit.py") is first
    assert context.prepare(head, "different.py") is first
    assert context.prepare(SimpleNamespace(to_dict=lambda: {"repository_id": "inert", "generation": 2}), "unit.py") is first
    assert context.prepare(head, "unit.py", (SimpleNamespace(to_dict=lambda: {"contract": "different"}),)) is first
    binding = context.binding(first)
    binding["head"]["repository_id"] = "caller-edit"
    assert context.binding(first)["head"]["repository_id"] == "inert"
    assert len(preparations) == 4 and len(validations) == 1
    assert context.counters.target_preparations == 4
    assert context.counters.target_preparation_cache_hits == 1
    assert context.counters.current_seal_reuses == context.counters.historical_seal_reads == 0
    context._verify_snapshots()


def test_preparation_cache_is_operation_local(monkeypatch):
    preparations, validations = stub_targets(monkeypatch)
    head = SimpleNamespace(to_dict=lambda: {"repository_id": "inert"})
    for _ in range(2):
        context = isolated_context()
        context.prepare(head, "unit.py")
        context.prepare(head, "unit.py")
    assert len(preparations) == len(validations) == 2


@pytest.mark.parametrize("phase", ["target", "request"])
def test_native_target_or_request_retention_bound_refuses_publication(monkeypatch, phase):
    _, validations = stub_targets(monkeypatch)
    head = SimpleNamespace(to_dict=lambda: {"repository_id": "inert"})
    context = isolated_context(maximum=1 if phase == "target" else 40 * 1024 * 1024)
    if phase == "request":
        checked = context.validated(inert_target())
        context.max_cache_bytes = context.counters.cache_retained_bytes + len(checked.canonical_bytes)
    before = context.counters.cache_retained_bytes
    with pytest.raises(training.CodebaseFeatureTrainingError, match="serialized byte bound"):
        context.prepare(head, "unit.py")
    assert context._prepared == {}
    assert context.counters.cache_retained_bytes == before
    assert len(validations) == 1


@pytest.mark.parametrize("check", ["hit", "closing"])
def test_forced_local_target_mutation_is_refused(monkeypatch, check):
    stub_targets(monkeypatch)
    context = isolated_context()
    head = SimpleNamespace(to_dict=lambda: {"repository_id": "inert"})
    target = context.prepare(head, "unit.py")
    object.__setattr__(target, "canonical_bytes", inert_target(2).canonical_bytes)
    with pytest.raises(training.CodebaseFeatureTrainingError, match="target was mutated"):
        if check == "hit":
            context.prepare(head, "unit.py")
        else:
            context._verify_snapshots()


@pytest.mark.parametrize("part", ["row", "saved"])
def test_closing_snapshot_guard_rejects_last_use_candidate_mutation(part):
    context = isolated_context()
    row, saved = {"version_id": "inert"}, {"state": {"weights": [1]}}
    context._candidates["inert"] = (lineage._wire(row), lineage._wire(saved), row, saved)
    (row if part == "row" else saved)["injected"] = True
    with pytest.raises(training.CodebaseFeatureTrainingError, match="snapshot was mutated"):
        context._verify_snapshots()


@pytest.mark.parametrize("mutation", ["binding", "missing", "extra"])
def test_closing_guard_refuses_private_derived_binding_mutation(monkeypatch, mutation):
    _, validations = stub_targets(monkeypatch)
    context = isolated_context()
    target = context.validated(inert_target())
    if mutation == "binding":
        binding = context.binding(target)
        binding["path"] = "forged-path.py"
        context._bindings[target.canonical_bytes] = lineage._wire(binding)
    elif mutation == "missing":
        del context._bindings[target.canonical_bytes]
    else:
        context._bindings[b"unvalidated-extra-target"] = b"{}"
    with pytest.raises(training.CodebaseFeatureTrainingError, match="binding .*mutated"):
        context._verify_snapshots()
    assert len(validations) == 1  # closing comparison does not revalidate natively


def test_resolver_optout_calls_exact_native_reference_without_context(monkeypatch):
    calls, checkpoints = [], []
    expected = [("native-reference",)]
    def native(*args):
        calls.append(args)
        return expected
    monkeypatch.setattr(training, "_lineage", native)
    monkeypatch.setattr(scan, "_ResumeLineageContext", lambda *args, **kwargs: pytest.fail("optout cache used"))
    limits = training.CodebaseFeatureTrainingLimits()
    assert scan._resume_lineage("index", "registry", "version", limits,
                                lambda: checkpoints.append(True), optimized=False) is expected
    assert calls == [("index", "registry", "version", limits)] and len(checkpoints) == 2


def test_resolver_default_guards_reference_and_discards_context(monkeypatch):
    # Pure receiving protocol double: no native model/candidate is claimed.
    monkeypatch.setattr(training, "_native_owners", lambda *args: None)
    contexts, checkpoints = [], []
    expected = [("inert-model",)]
    def body(index, registry, version, limits, context):
        contexts.append(weakref.ref(context))
        assert context.max_cache_bytes == 40 * 1024 * 1024
        assert context.counters.reference_guard_file_hashes == 2
        return expected
    monkeypatch.setattr(lineage, "_lineage", body)
    assert scan._resume_lineage(object(), object(), "inert", training.CodebaseFeatureTrainingLimits(),
                                lambda: checkpoints.append(True)) is expected
    gc.collect()
    assert contexts[0]() is None and len(checkpoints) >= 2


@pytest.mark.parametrize("timing", ["initial", "closing"])
def test_resolver_refuses_native_reference_source_drift(monkeypatch, timing):
    monkeypatch.setattr(training, "_native_owners", lambda *args: None)
    if timing == "initial":
        monkeypatch.setitem(lineage.REFERENCE_SHA256, training.__name__, "0" * 64)
    def body(*args):
        monkeypatch.setitem(lineage.REFERENCE_SHA256, training.__name__, "0" * 64)
        return []
    monkeypatch.setattr(lineage, "_lineage", body)
    with pytest.raises(training.CodebaseFeatureTrainingError, match="reviewed native reference"):
        scan._resume_lineage(object(), object(), "inert", training.CodebaseFeatureTrainingLimits(), lambda: None)


@pytest.mark.parametrize("optimized", [True, False])
def test_resolver_checkpoint_refuses_before_any_model_work(monkeypatch, optimized):
    monkeypatch.setattr(training, "_lineage", lambda *args: pytest.fail("native model replay after cancellation"))
    monkeypatch.setattr(scan, "_ResumeLineageContext", lambda *args, **kwargs: pytest.fail("cache after cancellation"))
    def cancelled():
        raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        scan._resume_lineage(object(), object(), "inert", training.CodebaseFeatureTrainingLimits(), cancelled,
                              optimized=optimized)


def test_resume_implementation_pins_native_lineage_helper():
    assert lineage.__name__ in scan._implementation()["files"]


def test_resolver_new_operation_does_not_reuse_retained_model_candidate(monkeypatch):
    # Explicit inert registry reader: the second operation observes refusal.
    monkeypatch.setattr(training, "_native_owners", lambda *args: None)
    reads = []
    def read(registry, version, limits):
        reads.append(version)
        if len(reads) == 2:
            raise training.CodebaseFeatureTrainingError("fresh model artifact changed")
        return {"version_id": version}, {"state": {"weights": [1]}}
    monkeypatch.setattr(training, "_read_candidate", read)
    monkeypatch.setattr(lineage, "_lineage", lambda index, registry, version, limits, context:
                        [context.read_candidate(version)])
    args = object(), object(), "inert", training.CodebaseFeatureTrainingLimits(), lambda: None
    assert scan._resume_lineage(*args)[0][1]["state"]["weights"] == [1]
    with pytest.raises(training.CodebaseFeatureTrainingError, match="fresh model artifact changed"):
        scan._resume_lineage(*args)
    assert reads == ["inert", "inert"]


@pytest.fixture(scope="module")
def native_large(tmp_path_factory):
    """Real257 sources/history; no model owner, fitting, Git or numerical job."""
    directory = tmp_path_factory.mktemp("resume-lineage257")
    connection = duckdb.connect(str(directory / "source.duckdb"), config={"threads": 1, "memory_limit": "128MB"})
    store = DuckDBASTStore(connection=connection)
    artifacts = ImmutableCAS(directory / "cas")
    index = RepositoryCodebaseIndex(ingestor=DuckDBASTIngestor(store=store), artifacts=artifacts,
        catalog=CodebaseCatalog(store, artifacts, limits=CodebaseCatalogLimits(max_entries=512)))
    sources = {f"unit{i:03d}.py": f"def step(n: int) -> int:\n    return n + {i + 1}\n".encode() for i in range(257)}
    entries = tuple(SnapshotEntry(path, "source", len(raw), cid_for_bytes(raw), captured_bytes=raw)
                    for path, raw in sources.items())
    snapshot = RepositorySnapshot("resume-lineage257", entries, "filesystem", 65536, 512)
    state = RepositoryScanner(repository_id=snapshot.repository_id).scan_snapshot(snapshot, sources)
    sealed, receipts = [], []
    def seal(publication):
        by_path = {item.source_file.path: item for item in publication.projections}
        units = tuple(CodebaseUnit(entry.source_key, entry.entry_cid, by_path[entry.path].ast_cid,
            by_path[entry.path].ast_blob.parse_status) for entry in snapshot.entries)
        manifest = CodebaseIRManifest(snapshot, state, publication.revision_id, units)
        for raw in sources.values():
            artifacts.put_bytes(raw)
        for projection in publication.projections:
            artifacts.put(json.loads(projection.ast_blob.payload_json))
        artifacts.put(manifest.to_dict())
        sealed.append(manifest)
    def publish(publication):
        receipts.append(index.catalog.publish(operation_id="fixture257", manifest=sealed[0], expected_head=None,
                                             projections=publication.projections))
    index.ingestor.ingest_snapshot(snapshot, created_at=1.0, before_publish=seal, publish_batch=publish)
    yield index, sealed[0], receipts[0].head, connection
    connection.close()


def test_native257_full_target_preparation_bindings_and_cache_equal_reference(native_large, monkeypatch, record_property):
    index, manifest, head, _ = native_large
    context = isolated_context(index)
    real_prepare, real_validate = targets.prepare_codebase_targets, targets.validate_codebase_targets
    calls = {"prepare": 0, "validate": 0}
    def prepare(*args, **kwargs):
        calls["prepare"] += 1
        return real_prepare(*args, **kwargs)
    def validate(*args, **kwargs):
        calls["validate"] += 1
        return real_validate(*args, **kwargs)
    monkeypatch.setattr(targets, "prepare_codebase_targets", prepare)
    monkeypatch.setattr(targets, "validate_codebase_targets", validate)
    reference = real_prepare(index, expected_head=head, path="unit000.py")
    first = context.prepare(head, "unit000.py")
    equal = DomainTargetEnvelope.from_dict(deepcopy(reference.to_dict()))
    assert context.validated(equal) is first and context.prepare(head, "unit000.py") is first
    assert first.canonical_bytes == reference.canonical_bytes
    assert context.binding(first) == targets.source_binding_from_target(reference)
    assert len(first.to_dict()["validation"][0]["details"]["manifest"]["snapshot"]["entries"]) == 257
    assert calls == {"prepare": 1, "validate": 2}  # one context replay + independent reference binding replay
    assert context.counters.target_native_validations == context.counters.target_preparations == 1
    assert context.counters.historical_seal_reads == 0
    context._verify_snapshots()
    record_property("native_members", len(manifest.snapshot.entries))
    record_property("operation_cache_counters", json.dumps(context.counters.to_dict(), sort_keys=True))


@pytest.mark.parametrize("corruption", ["source", "ast", "manifest"])
def test_native257_new_operation_refuses_current_cas_corruption(native_large, corruption):
    index, manifest, head, _ = native_large
    context = isolated_context(index)
    context.prepare(head, "unit000.py")
    cid = {"source": manifest.snapshot.entries[0].source_cid, "ast": manifest.units[0].ast_cid,
           "manifest": head.manifest_cid}[corruption]
    path = index.artifacts.path_for(cid, source=corruption == "source")
    original = path.read_bytes()
    try:
        path.write_bytes(b"corrupt native captured artifact")
        with pytest.raises(ValueError):
            isolated_context(index).prepare(head, "unit000.py")
    finally:
        path.write_bytes(original)


def test_native257_wrong_head_binding_and_forged_complete_target_fail(native_large):
    index, _, head, _ = native_large
    with pytest.raises(ValueError, match="bind"):
        isolated_context(index).prepare(replace(head, snapshot_cid=cid_for_structured({"wrong": True})), "unit000.py")
    target = targets.prepare_codebase_targets(index, expected_head=head, path="unit000.py")
    value = target.to_dict()
    value["validation"][0]["details"]["source_binding"]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        isolated_context(index).validated(DomainTargetEnvelope.from_dict(value))


def test_native257_closing_derived_binding_guard_uses_validated_bytes(native_large, monkeypatch):
    index, _, head, _ = native_large
    context = isolated_context(index)
    checked = context.prepare(head, "unit000.py")
    real_validate, validations = targets.validate_codebase_targets, []
    def validate(target):
        validations.append(target.canonical_bytes)
        return real_validate(target)
    monkeypatch.setattr(targets, "validate_codebase_targets", validate)
    context._verify_snapshots()
    binding = context.binding(checked)
    binding["content_sha256"] = "0" * 64
    context._bindings[checked.canonical_bytes] = lineage._wire(binding)
    with pytest.raises(training.CodebaseFeatureTrainingError, match="target binding was mutated"):
        context._verify_snapshots()
    assert validations == []


def test_native257_cached_target_does_not_replace_fresh_closing_source_cas(native_large):
    index, manifest, head, _ = native_large
    context = isolated_context(index)
    context.prepare(head, "unit000.py")
    path = index.artifacts.path_for(manifest.snapshot.entries[0].source_cid, source=True)
    original = path.read_bytes()
    try:
        path.write_bytes(b"changed source after lineage reuse")
        with pytest.raises(ValueError):
            # Genuine native SQL/CAS replay refuses before any checkout I/O.
            scan._observe(index, None, head, scan.CodebaseScanResumeLimits(), lambda: None, 1024)
    finally:
        path.write_bytes(original)


def test_native257_historical_target_cache_does_not_replace_current_head_fence(native_large):
    index, _, head, connection = native_large
    context = isolated_context(index)
    context.prepare(head, "unit000.py")
    try:
        connection.execute("UPDATE codebase_control.heads SET generation=generation+1 WHERE repository_id=?",
                           [head.repository_id])
        with pytest.raises(ValueError):
            scan._observe(index, None, head, scan.CodebaseScanResumeLimits(), lambda: None, 1024)
    finally:
        connection.execute("UPDATE codebase_control.heads SET generation=? WHERE repository_id=?",
                           [head.generation, head.repository_id])
