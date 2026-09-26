"""Lexical root reuse preserves fresh job/source checks and immutable artifacts.

Only synthetic declared vectors and isolated registries are used. No model,
embedding inference, native trainer, dispatch, publication or Lean admit runs.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import wraps
import inspect
from pathlib import Path
import pickle
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_batches as batches
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_job_inputs as campaign
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as index
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as manifest_codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as production
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_receipt_set as receipts
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_produced_record_projection as projection_codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_source_partitions as partitions
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_import as importer
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_inventory as inventory
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_batches import (
    ERRORS, _selected, _template,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_shared_sparse_arrow import _forbid_native
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_worker import _artifact, _campaign_job
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_produced_record_projection import _prepared, _summary


ROOT_FIELDS = ("source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact")


@pytest.fixture(autouse=True)
def no_native_execution(monkeypatch):
    _forbid_native(monkeypatch)


def _forbidden(*args, **kwargs):
    pytest.fail("invalid scoped metadata reached selected I/O or registration")


def _spec(tmp_path, *, shared_leaf=False):
    payload, fixture, projection = _campaign_job(tmp_path,
        groups=[list(range(32))] if shared_leaf else None)
    return worker.TrainingJobSpec.from_dict(payload), fixture, projection


def _scope(spec):
    # Scope lifetime tests need only owner identity; authoritative CAS binding
    # is separately exercised with real registries below.
    return campaign._CampaignRootScope(SimpleNamespace(artifact_root=Path(spec.base_checkpoint.path).parent))


def _preflight(spec, scope):
    return campaign._preflight_campaign_job_inputs(spec, root_scope=scope)


def _consume(spec, prepared):
    return campaign._verify_prepared_campaign_job_inputs(spec, prepared)


def _generate(registry, template, fixture, root, *, reuse=True, **kwargs):
    output = root / "generated"
    output.mkdir(exist_ok=True)
    return batches._prepare_campaign_batches(registry, template.run_id,
        receipt_resolver=kwargs.pop("receipt_resolver", fixture.case.receipt_resolver),
        source_resolver=kwargs.pop("source_resolver", fixture.case.source_resolver),
        output_root=output, training_batch_size=2, validation_batch_size=2,
        max_batches=3, reuse_root_metadata=reuse, **kwargs)


def _count_loaders(monkeypatch):
    counts = Counter()
    for module, name in ((inventory, "load_uscode_source_inventory"),
                         (partitions, "load_source_partitions"),
                         (receipts, "load_embedding_receipt_set")):
        original = getattr(module, name)
        def install(original=original, name=name):
            @wraps(original)
            def observed(*args, **kwargs):
                counts[name] += 1
                return original(*args, **kwargs)
            return observed
        observed = install()
        monkeypatch.setattr(module, name, observed)
        if hasattr(batches, name):
            monkeypatch.setattr(batches, name, observed)
    return counts


def _counts(number):
    return {"load_uscode_source_inventory": number,
            "load_source_partitions": number, "load_embedding_receipt_set": number}


def test_three_jobs_reuse_one_triplet_and_recompute_eight_with_exact_artifact_parity(tmp_path, monkeypatch):
    counts = _count_loaders(monkeypatch)
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        assert len(_selected(fixture, "train")) >= 6
        counts.clear()
        recomputed = _generate(registry, template, fixture, tmp_path, reuse=False)
        assert counts == _counts(8)
        snapshots = {name: registry.artifact_path(recomputed[name]).read_bytes()
                     for name in ("generation_artifact", "plan_artifact")}
        expected = {run_id: coordinator.registered_corpus_job_inputs(registry, run_id)["corpus_verification"]
                    for run_id in recomputed["run_ids"]}
        counts.clear()
        reused = _generate(registry, template, fixture, tmp_path)
        assert counts == _counts(1)
        assert reused == recomputed
        assert {name: registry.artifact_path(reused[name]).read_bytes() for name in snapshots} == snapshots
        with campaign._CampaignRootScope(registry) as scope:
            for run_id in reused["run_ids"]:
                checked = coordinator._registered_corpus_job_inputs(registry, run_id, root_scope=scope)
                assert checked["corpus_verification"] == expected[run_id]
        counts.clear()
        checked = coordinator.registered_corpus_job_inputs(registry, reused["run_ids"][0])
        assert counts == _counts(1)
        assert worker.verify_corpus_job_inputs(checked["spec"]) == expected[reused["run_ids"][0]]
        assert counts == _counts(2), "public worker verification must perform its own fresh root decoding"
        queued = {run_id: registry.get_run(run_id) for run_id in reused["run_ids"]}
    with AutoencoderRegistry(database, artifacts) as registry:
        counts.clear()
        assert _generate(registry, template, fixture, tmp_path) == recomputed
        assert counts == _counts(1), "a restarted owner must create a fresh scope"
        assert {run_id: registry.get_run(run_id) for run_id in queued} == queued


def test_each_scoped_job_has_fresh_full_spec_context_and_identical_summary(tmp_path):
    spec, _, _ = _spec(tmp_path)
    other = replace(spec, job_id="another-job", run_id="another-run",
        output_directory=str(tmp_path / "other-worker-output"))
    expected = worker.verify_corpus_job_inputs(spec)
    with _scope(spec) as scope:
        first, second = _preflight(spec, scope), _preflight(other, scope)
        assert first is not second and first._use is not second._use
        assert first.receipt_set is second.receipt_set
        assert first.manifest is not second.manifest and first.projection is not second.projection
        assert _consume(spec, first) == _consume(other, second) == expected
    assert scope._root is None and scope._decoded == ()


@pytest.mark.parametrize("failure", ["wrong_job", "double_consume"])
def test_prepared_failure_invalidates_whole_scope_without_retargeting(tmp_path, failure):
    spec, _, _ = _spec(tmp_path)
    scope = _scope(spec).__enter__()
    try:
        prepared = _preflight(spec, scope)
        if failure == "double_consume":
            _consume(spec, prepared)
            target = spec
        else:
            target = replace(spec, job_id="wrong-job")
        with pytest.raises(worker.TrainingJobValidationError):
            _consume(target, prepared)
        assert prepared._use.consumed is True
        with pytest.raises(worker.TrainingJobValidationError):
            scope.roots_for(spec)
    finally:
        scope.close()


@pytest.mark.parametrize("substitution", ["foreign_object", "none", "another_scope"])
def test_tampered_prepared_scope_consumes_original_use_and_invalidates_original_owner(tmp_path, monkeypatch, substitution):
    spec, _, _ = _spec(tmp_path)
    monkeypatch.setattr(projection_codec.ProducedRecordProjection, "verify_batch", _forbidden)
    original, other = _scope(spec).__enter__(), _scope(spec).__enter__()
    try:
        prepared = _preflight(spec, original)
        substitute = {"foreign_object": object(), "none": None, "another_scope": other}[substitution]
        object.__setattr__(prepared, "_scope", substitute)
        with pytest.raises(worker.TrainingJobValidationError):
            _consume(spec, prepared)
        assert prepared._use.consumed is True
        assert original._active is False and original._root is None
        other.check()  # A substituted unrelated scope is not the failing owner.
        object.__setattr__(prepared, "_scope", original)
        with pytest.raises(worker.TrainingJobValidationError, match="already been consumed"):
            _consume(spec, prepared)
    finally:
        original.close()
        other.close()


def test_scope_expiry_prevents_consumption_reentry_and_serialization(tmp_path):
    spec, _, _ = _spec(tmp_path)
    with _scope(spec) as scope:
        prepared = _preflight(spec, scope)
        with pytest.raises(TypeError, match="cannot be serialized"):
            pickle.dumps(scope)
    with pytest.raises(worker.TrainingJobValidationError):
        _consume(spec, prepared)
    with pytest.raises(worker.TrainingJobValidationError):
        scope.__enter__()
    with _scope(spec) as fresh:
        assert _consume(spec, _preflight(spec, fresh)) == worker.verify_corpus_job_inputs(spec)


def test_wrong_thread_expires_scope_and_retained_prepared_context(tmp_path):
    spec, _, _ = _spec(tmp_path)
    scope = _scope(spec).__enter__()
    try:
        prepared = _preflight(spec, scope)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with pytest.raises(worker.TrainingJobValidationError):
                pool.submit(scope.roots_for, spec).result()
        with pytest.raises(worker.TrainingJobValidationError):
            _consume(spec, prepared)
    finally:
        scope.close()


def test_another_owner_cannot_borrow_scope_even_with_same_artifact_root(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, _ = _template(registry, tmp_path / "inputs")
        scope = campaign._CampaignRootScope(registry).__enter__()
        try:
            coordinator._registered_corpus_job_inputs(registry, template.run_id, root_scope=scope)
            other = SimpleNamespace(artifact_root=registry.artifact_root, get_run=_forbidden)
            with pytest.raises(ERRORS):
                coordinator._registered_corpus_job_inputs(other, template.run_id, root_scope=scope)
            with pytest.raises(worker.TrainingJobValidationError):
                scope.check()
        finally:
            scope.close()


@pytest.mark.parametrize("field", ROOT_FIELDS)
@pytest.mark.parametrize("attribute", ["path", "sha256", "bytes"])
def test_root_descriptor_cannot_change_between_jobs(tmp_path, field, attribute):
    spec, _, _ = _spec(tmp_path)
    scope = _scope(spec).__enter__()
    try:
        scope.roots_for(spec)
        original = getattr(spec, field)
        value = {"path": str(tmp_path / "another-root.json"), "sha256": "f" * 64, "bytes": original.bytes + 1}[attribute]
        if attribute == "path":
            Path(value).write_bytes(Path(original.path).read_bytes())
        changed = replace(spec, **{field: replace(original, **{attribute: value})})
        with pytest.raises(worker.TrainingJobValidationError, match="root paths or identities"):
            scope.roots_for(changed)
        with pytest.raises(worker.TrainingJobValidationError):
            scope.roots_for(spec)
    finally:
        scope.close()


@pytest.mark.parametrize("field", ROOT_FIELDS)
@pytest.mark.parametrize("mutation", ["bytes", "symlink"])
def test_cached_root_requires_current_exact_bytes_between_jobs(tmp_path, field, mutation):
    spec, _, _ = _spec(tmp_path)
    scope = _scope(spec).__enter__()
    try:
        _consume(spec, _preflight(spec, scope))
        path = Path(getattr(spec, field).path)
        if mutation == "bytes":
            value = bytearray(path.read_bytes())
            value[len(value) // 2] ^= 1
            path.write_bytes(value)
        else:
            backup = path.with_suffix(".original")
            path.rename(backup)
            path.symlink_to(backup)
        with pytest.raises(ERRORS):
            _preflight(replace(spec, job_id="next-job"), scope)
        assert scope._root is None
    finally:
        scope.close()


@pytest.mark.parametrize("mutation", ["root", "partitions", "inventory", "receipt_limits", "partition_limits", "inventory_limits", "scope_limits"])
def test_decoded_nodes_and_nested_limits_cannot_be_replaced_or_mutated(tmp_path, mutation):
    spec, _, _ = _spec(tmp_path)
    scope = _scope(spec).__enter__()
    try:
        root_inventory, root_partitions, root = scope.roots_for(spec)
        if mutation == "root":
            object.__setattr__(scope, "_root", object())
        elif mutation == "partitions":
            object.__setattr__(root, "partitions", replace(root_partitions))
        elif mutation == "inventory":
            object.__setattr__(root_inventory, "_raw", b"{}")
        elif mutation == "scope_limits":
            object.__setattr__(scope, "_limits", tuple(replace(value) for value in scope._limits))
        else:
            limits = {"receipt_limits": root.limits, "partition_limits": root_partitions.limits,
                      "inventory_limits": root_inventory.limits}[mutation]
            name = next(iter(vars(limits)))
            object.__setattr__(limits, name, getattr(limits, name) - 1)
        with pytest.raises(worker.TrainingJobValidationError):
            scope.check(spec)
        assert scope._root is None
    finally:
        scope.close()


@pytest.mark.parametrize("mutation", ["loader", "method", "function_code", "source_hash"])
def test_runtime_code_and_bounded_producer_source_drift_expires_reuse(tmp_path, monkeypatch, mutation):
    spec, _, _ = _spec(tmp_path)
    changed = [False]
    source_hash = campaign._scope_source_sha256
    def observed_hash(path):
        if changed[0] and Path(path) == Path(inventory.__file__):
            return "0" * 64
        return source_hash(path)
    monkeypatch.setattr(campaign, "_scope_source_sha256", observed_hash)
    scope = _scope(spec).__enter__()
    try:
        scope.roots_for(spec)
        if mutation == "loader":
            monkeypatch.setattr(inventory, "load_uscode_source_inventory", _forbidden)
        elif mutation == "method":
            monkeypatch.setattr(partitions.SourcePartitions, "authorize", _forbidden)
        elif mutation == "function_code":
            monkeypatch.setattr(inventory._sha, "__code__", _forbidden.__code__)
        else:
            changed[0] = True
        with pytest.raises(worker.TrainingJobValidationError, match="code changed"):
            scope.roots_for(spec)
        assert scope._root is None
    finally:
        scope.close()


@pytest.mark.parametrize("closure", ["corpus_source_artifacts", "embedding_receipt_artifacts"])
def test_each_scoped_job_rechecks_selected_sources_and_leaves(tmp_path, closure):
    spec, _, _ = _spec(tmp_path, shared_leaf=True)
    scope = _scope(spec).__enter__()
    try:
        _consume(spec, _preflight(spec, scope))
        Path(getattr(spec, closure)[0].path).write_bytes(b"changed between selected jobs")
        another = replace(spec, job_id="another-job")
        prepared = _preflight(another, scope)
        with pytest.raises(worker.TrainingJobValidationError):
            _consume(another, prepared)
        assert scope._root is None
    finally:
        scope.close()


def test_unexpected_selected_callback_failure_invalidates_scope(tmp_path, monkeypatch):
    spec, _, _ = _spec(tmp_path)
    reads = []
    def interrupted(*args, **kwargs):
        reads.append(args[0])
        raise RuntimeError("injected selected-reader interruption")
    monkeypatch.setattr(production, "_read_verified", interrupted)
    scope = _scope(spec).__enter__()
    try:
        prepared = _preflight(spec, scope)
        with pytest.raises(RuntimeError, match="selected-reader interruption"):
            _consume(spec, prepared)
        assert reads and prepared._use.consumed is True
        assert scope._active is False and scope._root is None
        with pytest.raises(worker.TrainingJobValidationError):
            scope.roots_for(spec)
    finally:
        scope.close()


@pytest.mark.parametrize("changed_artifact", ["earlier_source", "shared_leaf"])
def test_later_source_callback_cannot_hide_earlier_artifact_mutation(tmp_path, monkeypatch, changed_artifact):
    spec, _, _ = _spec(tmp_path, shared_leaf=True)
    selected = {Path(ref.path) for ref in spec.corpus_source_artifacts}
    first, changed = [], [False]
    read_verified = manifest_codec._read_verified
    def observed(path, reference, maximum):
        value = read_verified(path, reference, maximum)
        if Path(path) in selected:
            if not first:
                first.append(Path(path))
            elif Path(path) != first[0] and not changed[0]:
                target = first[0] if changed_artifact == "earlier_source" else Path(spec.embedding_receipt_artifacts[0].path)
                target.write_bytes(b"changed by a later selected source callback")
                changed[0] = True
        return value
    monkeypatch.setattr(manifest_codec, "_read_verified", observed)
    monkeypatch.setattr(production, "_read_verified", observed)
    scope = _scope(spec).__enter__()
    try:
        with pytest.raises(worker.TrainingJobValidationError):
            _consume(spec, _preflight(spec, scope))
        assert changed[0] and scope._root is None
    finally:
        scope.close()


@pytest.mark.parametrize("split", ["canary", "holdout"])
def test_cached_campaign_still_authorizes_both_roles_before_selected_reads(tmp_path, monkeypatch, split):
    spec, _, _ = _spec(tmp_path / "template")
    policy = index.SplitPolicy("scoped-protected-inputs", **{
        name: 10000 if name == split else 0 for name in ("train", "validation", "canary", "holdout")})
    fixture = _prepared(tmp_path / "protected", policy=policy)
    root, manifest = fixture.receipt_set, fixture.manifest
    data = manifest.to_dict()
    records = {record.record_id: record for record in manifest.records}
    def artifact(name, value):
        return worker.CheckpointArtifact.from_dict(_artifact(tmp_path / name, value))
    projection = {"schema_version": "autoencoder-produced-record-projection-v1",
        "receipt_set": {"sha256": root.sha256, "bytes": len(root.to_bytes())},
        "source_partitions": {"sha256": root.partitions.sha256, "bytes": len(root.partitions.to_bytes())},
        "corpus_manifest": {"sha256": manifest.sha256, "bytes": len(manifest.to_bytes())},
        "dataset_snapshot_id": manifest.dataset_snapshot_id, "split_snapshot_id": manifest.split_snapshot_id,
        "training_record_ids": data["split"]["training_record_ids"], "validation_record_ids": data["split"]["validation_record_ids"],
        "records": [{"record_summary": _summary(record), **root.binding_for(entry)}
            for record, entry in zip(manifest.records, fixture.entry_cids, strict=True)]}
    leaves = root.selected_leaf_artifacts(fixture.entry_cids)
    spec = replace(spec, source_inventory_artifact=artifact("protected-inventory.json", root.partitions.inventory.to_bytes()),
        source_partitions_artifact=artifact("protected-partitions.json", root.partitions.to_bytes()),
        embedding_receipt_set_artifact=artifact("protected-set.json", root.to_bytes()),
        corpus_manifest_artifact=artifact("protected-manifest.json", manifest.to_bytes()),
        produced_record_projection_artifact=artifact("protected-projection.json", worker._json_bytes(projection)),
        dataset_snapshot_id=manifest.dataset_snapshot_id, split_snapshot_id=manifest.split_snapshot_id,
        samples=tuple(records[key].sample for key in data["split"]["training_record_ids"]),
        validation_samples=tuple(records[key].sample for key in data["split"]["validation_record_ids"]),
        embedding_receipt_artifacts=tuple(worker.CheckpointArtifact.from_dict({**ref,
            "path": str(fixture.case.leaf_paths[ref["sha256"]])}) for ref in leaves),
        corpus_source_artifacts=tuple(worker.CheckpointArtifact.from_dict({**ref,
            "path": str(fixture.case.source_paths[ref["sha256"]])}) for ref in manifest.source_refs))
    selected_paths = {Path(ref.path) for ref in (*spec.embedding_receipt_artifacts, *spec.corpus_source_artifacts)}
    verified_file = importer._verified_file
    def metadata_only(path, *args, **kwargs):
        if Path(path) in selected_paths:
            _forbidden()
        return verified_file(path, *args, **kwargs)
    monkeypatch.setattr(importer, "_verified_file", metadata_only)
    monkeypatch.setattr(manifest_codec, "_read_verified", _forbidden)
    monkeypatch.setattr(production, "_read_verified", _forbidden)
    scope = _scope(spec).__enter__()
    try:
        scope.roots_for(spec)
        with pytest.raises(worker.TrainingJobValidationError):
            _preflight(spec, scope)
        assert scope._root is None
    finally:
        scope.close()


@pytest.mark.parametrize("kind", ["source", "leaf"])
def test_invalid_last_generated_batch_is_rejected_before_first_create_run(tmp_path, monkeypatch, kind):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        last_entry = _selected(fixture, "train")[5][1]
        record = fixture.records_by_entry[last_entry]
        path = (fixture.case.source_paths[record.source.artifact.sha256] if kind == "source" else
                fixture.case.leaf_paths[record.embedding_provenance.artifact_sha256])
        path.write_bytes(b"corrupt member of final requested batch")
        monkeypatch.setattr(registry, "create_run", _forbidden)
        with pytest.raises(ERRORS):
            _generate(registry, template, fixture, tmp_path)
        assert registry.get_run(template.run_id)["attempt"] == 0


@pytest.mark.parametrize("barrier", [1, 2, 3, 4])
def test_all_four_registration_barriers_recheck_scoped_producer_code(tmp_path, monkeypatch, barrier):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        template, fixture = _template(registry, tmp_path / "inputs")
        drift, direct_rehashes, registrations = [False], [], []
        source_hash, rehash, create = campaign._scope_source_sha256, receipts._rehash, registry.create_run
        def observed_hash(path):
            return "0" * 64 if drift[0] and Path(path) == Path(inventory.__file__) else source_hash(path)
        def observed_rehash(*args, **kwargs):
            value = rehash(*args, **kwargs)
            caller = inspect.currentframe().f_back
            direct = caller.f_code.co_name == "final_inputs" and caller.f_globals is batches.__dict__
            del caller
            if direct:
                direct_rehashes.append(1)
                if len(direct_rehashes) == 2 * barrier:
                    drift[0] = True
            return value
        def observed_create(*args, **kwargs):
            result = create(*args, **kwargs)
            registrations.append(result["run_id"])
            return result
        monkeypatch.setattr(campaign, "_scope_source_sha256", observed_hash)
        monkeypatch.setattr(receipts, "_rehash", observed_rehash)
        monkeypatch.setattr(registry, "create_run", observed_create)
        with pytest.raises(ERRORS, match="code changed"):
            _generate(registry, template, fixture, tmp_path)
        assert drift[0] and len(direct_rehashes) == 2 * barrier
        assert len(registrations) == (0 if barrier <= 2 else 3)
        assert registry.resolve_head("english-0", "best")["version_id"] == template.base_version_id
        for run_id in registrations:
            run = registry.get_run(run_id)
            assert run["status"] == "queued" and run["attempt"] == run["fence"] == 0
            assert run["lease"] is run["result"] is None
