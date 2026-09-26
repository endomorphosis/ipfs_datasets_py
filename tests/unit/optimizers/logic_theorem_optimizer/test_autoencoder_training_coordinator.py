"""Durable owner/worker integration without real projection training."""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, execute_training_job
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState


class ImmediateExecutor:
    """Executor contract injection; never represented as native worker evidence."""

    def __init__(self, *, max_workers, mp_context):
        assert mp_context.get_start_method() == "spawn"

    def submit(self, function, *args):
        assert len(args) == 1 and isinstance(args[0], TrainingJobSpec)
        future = Future()
        try:
            future.set_result(function(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, **kwargs):
        pass


def _trainer(model, samples, *, validation_samples, **kwargs):
    model.state.feature_embedding_weights["fixture"] = [0.5, -0.25]
    return {"accepted_epochs": 1, "after": {"legal_ir_target_count": len(samples)},
            "stopped_reason": "synthetic_fixture"}


def _fixture_worker(spec):
    return execute_training_job(spec, trainer=_trainer)


def _prepare(registry, root, index=0, *, training_config=None, spec_digest=None, job_updates=None,
             variant_updates=None):
    base = root / "base.json"
    if not base.exists():
        base.write_text(ModalAutoencoderTrainingState().to_json() + "\n")
    artifact = registry.stage_artifact(base)
    registry.register_variant(f"variant-{index}", f"english-{index}", {
        "source_language": "en", "target_formal_language": "typed_deontic_ir",
        "jurisdiction": "us", "model_variant": "modal_autoencoder", **(variant_updates or {})})
    version = registry.register_version(f"version-{index}", f"english-{index}", artifact)
    registry.initialize_head(f"head-{index}", f"english-{index}", "best", version["version_id"])
    payload = {
        "job_id": f"job-{index}", "run_id": f"run-{index}", "base_version_id": version["version_id"],
        "base_checkpoint": {**artifact, "path": str(registry.artifact_path(artifact))},
        "output_directory": str(root / f"attempt-{index}"), "code_identity": "fixture-code",
        "dataset_snapshot_id": "fixture-data", "split_snapshot_id": "in-sample",
        "samples": [{"title": "5", "section": "1", "text": "The agency shall retain records."}],
        "autoencoder_config": {"compute_device": "python"},
        "training_config": training_config or {},
    }
    payload.update(job_updates or {})
    spec = TrainingJobSpec.from_dict(payload)
    spec_path = root / f"job-{index}.json"
    spec_path.write_text(json.dumps(spec.to_dict(), indent=2))
    spec_artifact = registry.stage_artifact(spec_path)
    registry.create_run(f"create-{index}", spec.run_id, f"english-{index}", version["version_id"],
                        {"job_spec_sha256": spec_digest or spec.canonical_sha256,
                         "job_spec_artifact": spec_artifact})
    return spec


def _sparse_trainer(model, samples, *, validation_samples, **kwargs):
    base_identity = model.state.state_identity()
    with model.state.transaction(label="accepted-fixture") as transaction:
        previous = model.state.feature_embedding_weights.get("fixture", [0.0])[0]
        model.state.feature_embedding_weights["fixture"] = [previous + 0.5, -0.25]
    kwargs["accepted_patch_sink"](transaction.patch, {
        "base_state_identity": base_identity,
        "result_state_identity": model.state.state_identity(),
        "base_revision": transaction.patch.base_revision,
        "result_revision": transaction.patch.result_revision,
        "label": "accepted-fixture",
    })
    return {"accepted_epochs": 1, "after": {"legal_ir_target_count": len(samples)}}


def _sparse_worker(spec):
    return execute_training_job(spec, trainer=_sparse_trainer)


def _prepare_sparse(registry, root):
    state = ModalAutoencoderTrainingState()
    state.feature_embedding_weights["anchor-padding"] = [float(index) / 100 for index in range(2000)]
    (root / "base.json").write_text(state.to_json() + "\n")
    return _prepare(registry, root, job_updates={
        "schema_version": "autoencoder-training-job-v3", "capture_sparse_patches": True,
        "candidate_storage": "sparse"})


def _prepare_child(registry, root, parent, *, index=1, storage="sparse", dependencies=None):
    inputs = coordinator.registered_checkpoint_inputs(registry, parent)
    if dependencies is not None:
        inputs["base_checkpoint_dependencies"] = dependencies
    spec = TrainingJobSpec.from_dict({
        "schema_version": "autoencoder-training-job-v3", "candidate_storage": storage,
        "capture_sparse_patches": True, "job_id": f"job-{index}", "run_id": f"run-{index}",
        "base_version_id": parent, **inputs, "output_directory": str(root / f"attempt-{index}"),
        "code_identity": "fixture-code", "dataset_snapshot_id": "fixture-data", "split_snapshot_id": "in-sample",
        "samples": [{"title": "5", "section": "1", "text": "The agency shall retain records."}],
        "autoencoder_config": {"compute_device": "python"}})
    path = root / f"job-{index}.json"
    path.write_text(json.dumps(spec.to_dict()))
    registry.create_run(f"create-{index}", spec.run_id, "english-0", parent,
                        {"job_spec_sha256": spec.canonical_sha256,
                         "job_spec_artifact": registry.stage_artifact(path)})
    return spec


def _prepare_corpus(registry, root, *, unstaged_source=False, wrong_membership=False):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
        SourceArtifact, SourceSampleRecord, SourceSpan, build_corpus_manifest,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    raw = b"The agency shall retain records."
    path = root / "source.txt"
    path.write_bytes(raw)
    source = SourceArtifact(hashlib.sha256(raw).hexdigest(), len(raw))
    record = SourceSampleRecord(SourceSpan(source, "diagnostic", "fixture-v1", "doc-1", "en",
                                           "diagnostic:1", 0, len(raw)), SampleRecord("5", "1", raw.decode()))
    manifest = build_corpus_manifest([record], training_record_ids=[record.record_id],
                                     validation_record_ids=[record.record_id], mode="diagnostic")
    saved = manifest.save(root / "corpus.manifest.json", resolver=lambda ref: path)
    staged_manifest = registry.stage_artifact(saved["path"], saved["sha256"])
    staged_source = registry.stage_artifact(path, source.sha256)
    sample = asdict(record.sample)
    if wrong_membership:
        sample["text"] = "The officer shall submit the report."
    return _prepare(registry, root, job_updates={
        "schema_version": "autoencoder-training-job-v4",
        "dataset_snapshot_id": manifest.dataset_snapshot_id, "split_snapshot_id": manifest.split_snapshot_id,
        "samples": [sample], "validation_samples": [asdict(record.sample)],
        "corpus_manifest_artifact": {**staged_manifest, "path": str(registry.artifact_path(staged_manifest))},
        "corpus_source_artifacts": [{**staged_source, "path": str(path if unstaged_source else registry.artifact_path(staged_source))}],
    })


def _indexed_corpus_inputs(registry, root, *, production=False, arrow_inputs=False):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_index import (
        IndexScope, SplitPolicy, build_corpus_index,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
        EmbeddingProvenance, SourceArtifact, SourceSampleRecord, SourceSpan, build_corpus_manifest,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord

    records, paths = [], {}
    for number in range(32):
        text = f"The agency shall retain record number {number} for {number + 3} days."
        raw = text.encode()
        path = root / f"indexed-source-{number}.txt"
        path.write_bytes(raw)
        source = SourceArtifact(hashlib.sha256(raw).hexdigest(), len(raw))
        citation = f"5 U.S.C. {number + 1}"
        record = SourceSampleRecord(
            SourceSpan(source, "us_code", "fixture-release-v1", f"doc-{number}", "en",
                       citation, 0, len(raw)),
            SampleRecord("5", str(number + 1), text, citation, "injected-fixture-encoder", (float(number), 0.5)),
            EmbeddingProvenance("injected-fixture-encoder", "c" * 40, "d" * 64),
        )
        records.append(record)
        paths[source.sha256] = path

    if production:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as ep

        # Caller-constructed declarations test integrity plumbing only. These
        # synthetic vectors and runtime labels are not native inference evidence.
        inputs = [ep.EmbeddingInput.from_source_record(record) for record in records]
        resolver = lambda ref: paths[ref["sha256"]]
        production_receipt = ep.build_embedding_production_receipt(
            inputs, results=[{"input_id": item.input_id, "status": "embedded",
                             "tokens": {"input_ids": [101, 102], "attention_mask": [1, 1], "token_type_ids": [0, 0]},
                             "vector": tuple([1.0] + [0.0] * 383)} for item in inputs],
            execution=ep.native_execution_profile(),
            model_assets=[{"name": name, "sha256": "a" * 64, "bytes": 1} for name in sorted((
                "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "modules.json",
                "1_Pooling/config.json", "sentence_bert_config.json", "vocab.txt", "model.safetensors"))],
            producer={"code_sha256": hashlib.sha256(b"synthetic-fixture-no-inference").hexdigest(),
                      "runtime_versions": {key: "synthetic-fixture-no-inference" for key in (
                          "python", "torch", "transformers", "sentence_transformers", "tokenizers")}}, resolver=resolver)
        saved_production = production_receipt.save(root / "production.json", resolver=resolver)
        staged_production = registry.stage_artifact(saved_production["path"], saved_production["sha256"])
        records = production_receipt.to_corpus_records(resolver=resolver)

    # Freeze once before model construction; select from the resulting partitions
    # without changing seeds or resampling to make a particular batch fit.
    index = build_corpus_index(
        records, scope=IndexScope(hashlib.sha256(b"owner-selected-rows").hexdigest(), ("a" * 64,)),
        policy=SplitPolicy("owner-v5-frozen-seed", train=5000, validation=5000, canary=0, holdout=0),
    )
    assert len(set(index.record_groups.values())) == len(records)
    training = list(reversed(index.record_ids_for("train")[:2]))
    validation = list(reversed(index.record_ids_for("validation")[:2]))
    assert len(training) == len(validation) == 2
    lookup = {record.record_id: record for record in records}
    manifest = build_corpus_manifest(
        [lookup[key] for key in training + validation], training_record_ids=training,
        validation_record_ids=validation, mode="corpus",
    )
    saved = manifest.save(root / "indexed-corpus.manifest.json", resolver=lambda ref: paths[ref["sha256"]])
    staged_manifest = registry.stage_artifact(saved["path"], saved["sha256"])
    saved_index = index.save(root / "corpus-index.json")
    staged_index = registry.stage_artifact(saved_index["path"], saved_index["sha256"])
    sources = [registry.stage_artifact(paths[ref["sha256"]], ref["sha256"]) for ref in manifest.source_refs]

    def located(artifact):
        return {**artifact, "path": str(registry.artifact_path(artifact))}

    inputs = {
        "schema_version": "autoencoder-training-job-v5",
        "dataset_snapshot_id": manifest.dataset_snapshot_id, "split_snapshot_id": manifest.split_snapshot_id,
        "samples": [asdict(lookup[key].sample) for key in training],
        "validation_samples": [asdict(lookup[key].sample) for key in validation],
        "corpus_manifest_artifact": located(staged_manifest),
        "corpus_source_artifacts": [located(source) for source in sources],
        "corpus_index_artifact": located(staged_index),
        "corpus_selection_sha256": index.scope.selection_sha256,
    }
    binding = {"selection_sha256": index.scope.selection_sha256, "artifact": staged_index}
    if production:
        inputs.update(schema_version="autoencoder-training-job-v6",
                      embedding_production_artifact=located(staged_production))
    if arrow_inputs:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_arrow_inputs import write_embedding_inputs_ipc
        saved_arrow = write_embedding_inputs_ipc(manifest.records, root / "inputs.arrow", production=production_receipt,
                                                  resolver=lambda ref: paths[ref["sha256"]])
        staged_arrow = registry.stage_artifact(saved_arrow["path"], saved_arrow["sha256"])
        inputs.update(schema_version="autoencoder-training-job-v7", arrow_embedding_inputs_artifact=located(staged_arrow))
    return inputs, binding, index


def _assert_rejected_before_dispatch(registry, spec, monkeypatch, *, match):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid indexed input reached dispatch or claim")

    monkeypatch.setattr(registry, "claim_run", forbidden)
    with pytest.raises(ValueError, match=match):
        coordinator.run_training_jobs(registry, [spec], executor_factory=forbidden, worker_function=forbidden)
    run = registry.get_run(spec.run_id)
    assert run["status"] == "queued"
    assert run["attempt"] == run["fence"] == 0
    assert run["lease"] is None and run["result"] is None
    assert not Path(spec.output_directory).exists()


def test_owner_registers_v5_frozen_index_result_and_preserves_binding_on_restart(tmp_path):
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        inputs, binding, index = _indexed_corpus_inputs(registry, tmp_path)
        spec = _prepare(registry, tmp_path, job_updates=inputs,
                        variant_updates={"corpus_index_binding": binding})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=_fixture_worker)
        assert not result["failed"], result
        assert result["execution_mode"] == "injected_test"
        assert len(result["completed"]) == 1
        completed = result["completed"][0]
        summary = completed["result"]
        verification = summary["corpus_verification"]
        assert summary["corpus_index_artifact"] == inputs["corpus_index_artifact"]
        assert summary["corpus_selection_sha256"] == binding["selection_sha256"]
        assert summary["corpus_index_membership_verified"] is True
        assert summary["dataset_and_split_identity_verified"] is True
        assert summary["sample_count"] == summary["validation_sample_count"] == 2
        assert verification["verification_mode"] == "manifest_source_bytes_and_frozen_index"
        assert verification["source_validation"]["source_selectors_verified"] is True
        index_summary = verification["corpus_index_verification"]
        assert index_summary["index_sha256"] == binding["artifact"]["sha256"]
        assert index_summary["partition_counts"] == index.partition_counts
        assert index_summary["training_record_ids"] == list(reversed(index.record_ids_for("train")[:2]))
        assert index_summary["validation_record_ids"] == list(reversed(index.record_ids_for("validation")[:2]))
        assert index_summary["batch_index_membership_verified"] is True
        assert index_summary["indexed_partition_disjoint_verified"] is True
        assert index_summary["global_holdout_verified"] is False
        assert index_summary["corpus_complete"] is False
        assert summary["heldout_canary_qualified"] is False
        assert result["admitted"] is False and result["promotion_performed"] is False
    with AutoencoderRegistry(database, artifacts) as registry:
        run = registry.get_run(spec.run_id)
        assert run["status"] == "completed"
        assert run["result"] == summary
        assert registry.get_variant("english-0")["manifest"]["corpus_index_binding"] == binding
        assert registry.verify_artifact(binding["artifact"]) == binding["artifact"]
        assert registry.verify_artifact(completed["candidate"]) == completed["candidate"]
        receipt = json.loads(registry.artifact_path(completed["worker_receipt_artifact"]).read_bytes())
        assert receipt["corpus_verification"] == verification
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


@pytest.mark.parametrize("field", ["selection_sha256", "artifact"])
def test_registered_corpus_index_binding_is_immutable(tmp_path, field):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, _ = _indexed_corpus_inputs(registry, tmp_path)
        _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"corpus_index_binding": binding})
        changed = registry.get_variant("english-0")["manifest"]
        if field == "selection_sha256":
            changed["corpus_index_binding"][field] = "0" * 64
        else:
            changed["corpus_index_binding"][field]["sha256"] = "0" * 64
        with pytest.raises(RegistryError, match="variant is immutable"):
            registry.register_variant("replace-index-binding", "english-0", changed)
        assert registry.get_variant("english-0")["manifest"]["corpus_index_binding"] == binding


@pytest.mark.parametrize("problem", [
    "missing", "null", "missing_selection", "missing_artifact", "extra_field",
    "artifact_path", "artifact_missing_bytes", "selection_digest", "artifact_digest", "boolean_bytes",
])
def test_owner_requires_exact_registered_v5_index_binding_before_claim(tmp_path, monkeypatch, problem):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, _ = _indexed_corpus_inputs(registry, tmp_path)
        if problem == "missing":
            updates = {}
        elif problem == "null":
            updates = {"corpus_index_binding": None}
        else:
            if problem == "missing_selection":
                binding.pop("selection_sha256")
            elif problem == "missing_artifact":
                binding.pop("artifact")
            elif problem == "extra_field":
                binding["policy"] = "caller-override"
            elif problem == "artifact_path":
                binding["artifact"]["path"] = inputs["corpus_index_artifact"]["path"]
            elif problem == "artifact_missing_bytes":
                binding["artifact"].pop("bytes")
            elif problem == "selection_digest":
                binding["selection_sha256"] = "A" * 64
            elif problem == "artifact_digest":
                binding["artifact"]["sha256"] = "not-a-digest"
            elif problem == "boolean_bytes":
                binding["artifact"]["bytes"] = True
            updates = {"corpus_index_binding": binding}
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates=updates)
        _assert_rejected_before_dispatch(registry, spec, monkeypatch, match="corpus_index_binding")


@pytest.mark.parametrize("schema_version", [f"autoencoder-training-job-v{number}" for number in range(1, 5)])
def test_owner_rejects_legacy_job_for_index_bound_variant_before_claim(tmp_path, monkeypatch, schema_version):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        _, binding, _ = _indexed_corpus_inputs(registry, tmp_path)
        spec = _prepare(registry, tmp_path, job_updates={"schema_version": schema_version},
                        variant_updates={"corpus_index_binding": binding})
        _assert_rejected_before_dispatch(registry, spec, monkeypatch, match="legacy downgrade is forbidden")


@pytest.mark.parametrize("schema_version", [f"autoencoder-training-job-v{number}" for number in range(1, 6)])
def test_owner_forbids_downgrade_from_registered_embedding_production_binding(tmp_path, monkeypatch, schema_version):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, _ = _indexed_corpus_inputs(registry, tmp_path)
        updates = {"embedding_production_binding": {"artifact": {"sha256": "a" * 64, "bytes": 1}}}
        if schema_version == "autoencoder-training-job-v5":
            updates["corpus_index_binding"] = binding
        else:
            inputs = {"schema_version": schema_version}
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates=updates)
        _assert_rejected_before_dispatch(registry, spec, monkeypatch, match="legacy downgrade is forbidden")


@pytest.mark.parametrize("problem,match", [
    ("unstaged_index", "corpus inputs must name staged immutable artifacts"),
    ("corrupt_index", "digest|hash|corrupt"),
    ("job_selection_mismatch", "differs from registered corpus_index_binding"),
    ("index_selection_mismatch", "index selection differs"),
    ("index_substitution", "differs from registered corpus_index_binding"),
])
def test_owner_rejects_v5_index_input_changes_before_claim(tmp_path, monkeypatch, problem, match):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, binding, index = _indexed_corpus_inputs(registry, tmp_path)
        if problem == "unstaged_index":
            inputs["corpus_index_artifact"]["path"] = str(tmp_path / "corpus-index.json")
        elif problem == "corrupt_index":
            path = Path(inputs["corpus_index_artifact"]["path"])
            path.write_bytes(path.read_bytes()[:-1] + b"\n")
        elif problem in {"job_selection_mismatch", "index_selection_mismatch"}:
            inputs["corpus_selection_sha256"] = "0" * 64
            if problem == "index_selection_mismatch":
                binding["selection_sha256"] = inputs["corpus_selection_sha256"]
        else:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_index import CorpusIndex

            payload = index.to_dict()
            payload["scope"]["release_manifest_sha256s"] = ["b" * 64]
            replacement = CorpusIndex(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
            assert replacement.assignments == index.assignments
            assert replacement.scope.selection_sha256 == index.scope.selection_sha256
            assert replacement.sha256 != index.sha256
            saved = replacement.save(tmp_path / "replacement-index.json")
            artifact = registry.stage_artifact(saved["path"], saved["sha256"])
            inputs["corpus_index_artifact"] = {**artifact, "path": str(registry.artifact_path(artifact))}
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"corpus_index_binding": binding})
        _assert_rejected_before_dispatch(registry, spec, monkeypatch, match=match)


@pytest.mark.parametrize("field", [
    "corpus_index_artifact", "corpus_selection_sha256", "corpus_index_membership_verified", "corpus_verification",
])
def test_owner_rejects_forged_v5_worker_index_receipt_durably(tmp_path, field):
    def forge(spec):
        receipt = _fixture_worker(spec)
        if field == "corpus_index_artifact":
            receipt[field]["sha256"] = "0" * 64
        elif field == "corpus_selection_sha256":
            receipt[field] = "0" * 64
        elif field == "corpus_index_membership_verified":
            receipt[field] = False
        else:
            receipt[field]["corpus_index_verification"]["training_record_ids"].reverse()
        Path(spec.output_directory, "receipt.json").write_text(json.dumps(receipt))
        return receipt

    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        inputs, binding, _ = _indexed_corpus_inputs(registry, tmp_path)
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={"corpus_index_binding": binding})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=forge)
        assert not result["completed"]
        assert len(result["failed"]) == 1
        assert result["failed"][0]["failure_recorded"] is True
        assert f"worker receipt binding mismatch: {field}" in result["failed"][0]["error"]
    with AutoencoderRegistry(database, artifacts) as registry:
        run = registry.get_run(spec.run_id)
        assert run["status"] == "failed"
        assert f"worker receipt binding mismatch: {field}" in run["result"]["error"]
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


def test_owner_preserves_independently_verified_v6_production_binding_on_restart(tmp_path):
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        inputs, index_binding, _ = _indexed_corpus_inputs(registry, tmp_path, production=True)
        production_binding = {"artifact": {key: inputs["embedding_production_artifact"][key] for key in ("sha256", "bytes")}}
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={
            "corpus_index_binding": index_binding, "embedding_production_binding": production_binding})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=_fixture_worker)
        assert not result["failed"], result
        completed = result["completed"][0]
        summary = completed["result"]
        assert summary["embedding_production_artifact"] == inputs["embedding_production_artifact"]
        assert summary["embedding_production_verified"] is True
        verification = summary["embedding_production_verification"]
        assert verification == summary["corpus_verification"]["embedding_production_verification"]
        assert verification["supplied_records_verified"] == 4 and verification["input_count"] == 32
        assert verification["runtime_cryptographically_attested"] is False
        assert verification["runtime_computation_proven"] is False
        assert verification["source_authority_authenticated"] is False
        assert result["execution_mode"] == "injected_test"
        assert result["admitted"] is result["promotion_performed"] is False
        assert summary["corpus_verification"]["global_holdout_verified"] is False
    with AutoencoderRegistry(database, artifacts) as registry:
        assert registry.get_run(spec.run_id)["result"] == summary
        assert registry.get_variant("english-0")["manifest"]["embedding_production_binding"] == production_binding
        assert registry.verify_artifact(production_binding["artifact"]) == production_binding["artifact"]
        persisted = json.loads(registry.artifact_path(completed["worker_receipt_artifact"]).read_bytes())
        assert persisted["embedding_production_verification"] == verification
        assert persisted["execution_mode"] == "injected_test"
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


@pytest.mark.parametrize("problem,match", [
    ("missing", "embedding_production_binding"), ("null", "embedding_production_binding"),
    ("extra", "embedding_production_binding"), ("path", "embedding_production_binding"),
    ("boolean_bytes", "embedding_production_binding"), ("oversized", "embedding_production_binding"),
    ("sha256", "embedding_production_binding"), ("substituted", "differs from registered embedding_production_binding"),
    ("unstaged", "corpus inputs must name staged immutable artifacts"), ("corrupt", "hash|digest|corrupt"),
])
def test_owner_checks_exact_v6_variant_and_staged_production_before_claim(tmp_path, monkeypatch, problem, match):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, index_binding, _ = _indexed_corpus_inputs(registry, tmp_path, production=True)
        production_binding = {"artifact": {key: inputs["embedding_production_artifact"][key] for key in ("sha256", "bytes")}}
        updates = {"corpus_index_binding": index_binding, "embedding_production_binding": production_binding}
        if problem == "missing":
            updates.pop("embedding_production_binding")
        elif problem == "null":
            updates["embedding_production_binding"] = None
        elif problem == "extra":
            production_binding["policy"] = "override"
        elif problem == "path":
            production_binding["artifact"]["path"] = inputs["embedding_production_artifact"]["path"]
        elif problem == "boolean_bytes":
            production_binding["artifact"]["bytes"] = True
        elif problem == "oversized":
            production_binding["artifact"]["bytes"] = 64 * 1024 * 1024 + 1
        elif problem == "sha256":
            production_binding["artifact"]["sha256"] = "not-a-digest"
        elif problem == "substituted":
            production_binding["artifact"]["sha256"] = "0" * 64
        elif problem == "unstaged":
            inputs["embedding_production_artifact"]["path"] = str(tmp_path / "production.json")
        else:
            Path(inputs["embedding_production_artifact"]["path"]).write_bytes(b"changed")
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates=updates)
        _assert_rejected_before_dispatch(registry, spec, monkeypatch, match=match)


@pytest.mark.parametrize("field", ["embedding_production_artifact", "embedding_production_verified",
                                    "embedding_production_verification", "corpus_verification"])
def test_owner_rejects_forged_v6_production_receipt_durably(tmp_path, field):
    def forge(spec):
        receipt = _fixture_worker(spec)
        if field == "embedding_production_artifact":
            receipt[field]["sha256"] = "0" * 64
        elif field == "embedding_production_verified":
            receipt[field] = False
        elif field == "embedding_production_verification":
            receipt[field]["supplied_records_verified"] += 1
        else:
            receipt[field]["embedding_production_verification"]["runtime_cryptographically_attested"] = True
        Path(spec.output_directory, "receipt.json").write_text(json.dumps(receipt))
        return receipt

    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        inputs, index_binding, _ = _indexed_corpus_inputs(registry, tmp_path, production=True)
        production_binding = {"artifact": {key: inputs["embedding_production_artifact"][key] for key in ("sha256", "bytes")}}
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={
            "corpus_index_binding": index_binding, "embedding_production_binding": production_binding})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor, worker_function=forge)
        assert not result["completed"] and result["failed"][0]["failure_recorded"] is True
        assert f"worker receipt binding mismatch: {field}" in result["failed"][0]["error"]
    with AutoencoderRegistry(database, artifacts) as registry:
        assert registry.get_run(spec.run_id)["status"] == "failed"
        assert f"worker receipt binding mismatch: {field}" in registry.get_run(spec.run_id)["result"]["error"]
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


def test_owner_persists_independent_v7_arrow_verification_and_mapping_observations(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_arrow_inputs as ai
    loaded = []
    original_load = ai.load_embedding_inputs_ipc

    def capture(*args, **kwargs):
        mapping = original_load(*args, **kwargs)
        loaded.append(mapping)
        return mapping

    monkeypatch.setattr(ai, "load_embedding_inputs_ipc", capture)
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        inputs, index_binding, _ = _indexed_corpus_inputs(registry, tmp_path, production=True, arrow_inputs=True)
        production_binding = {"artifact": {key: inputs["embedding_production_artifact"][key] for key in ("sha256", "bytes")}}
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={
            "corpus_index_binding": index_binding, "embedding_production_binding": production_binding})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=_fixture_worker)
        assert not result["failed"], result
        assert len(loaded) == 2 and all(mapping.statistics["closed"] for mapping in loaded)
        summary = result["completed"][0]["result"]
        assert summary["arrow_embedding_inputs_artifact"] == inputs["arrow_embedding_inputs_artifact"]
        assert summary["arrow_embedding_inputs_verified"] is True
        assert summary["embedding_input_storage"] == "arrow_mapped_float32"
        assert summary["arrow_embedding_inputs_verification"] == summary["corpus_verification"]["arrow_embedding_inputs_verification"]
        assert summary["arrow_embedding_inputs_verification"]["whole_training_zero_copy"] is False
        assert summary["arrow_embedding_inputs_statistics_after_samples"]["row_accesses"] == 4
        assert summary["sample_build_seconds_per_sample"] * 4 == pytest.approx(summary["sample_build_seconds"])
        assert summary["embedding_production_verification"]["runtime_computation_proven"] is False
        assert summary["execution_mode"] == "injected_test"
    with AutoencoderRegistry(database, artifacts) as registry:
        assert registry.get_run(spec.run_id)["result"] == summary
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


@pytest.mark.parametrize("problem,match", [("unstaged", "staged immutable"), ("corrupt", "bytes or digest mismatch")])
def test_owner_rejects_v7_arrow_path_or_byte_changes_before_claim(tmp_path, monkeypatch, problem, match):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        inputs, index_binding, _ = _indexed_corpus_inputs(registry, tmp_path, production=True, arrow_inputs=True)
        production_binding = {"artifact": {key: inputs["embedding_production_artifact"][key] for key in ("sha256", "bytes")}}
        if problem == "unstaged":
            inputs["arrow_embedding_inputs_artifact"]["path"] = str(tmp_path / "inputs.arrow")
        else:
            Path(inputs["arrow_embedding_inputs_artifact"]["path"]).write_bytes(b"changed")
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={
            "corpus_index_binding": index_binding, "embedding_production_binding": production_binding})
        _assert_rejected_before_dispatch(registry, spec, monkeypatch, match=match)


@pytest.mark.parametrize("field", [
    "arrow_embedding_inputs_artifact", "arrow_embedding_inputs_verified", "arrow_embedding_inputs_verification",
    "embedding_input_storage", "arrow_embedding_inputs_statistics_before_samples",
    "arrow_embedding_inputs_statistics_after_samples", "arrow_embedding_inputs_statistics_after_training",
    "sample_build_seconds", "sample_build_seconds_per_sample",
])
def test_owner_rejects_forged_v7_arrow_bindings_and_invalid_observations(tmp_path, field):
    def forge(spec):
        receipt = _fixture_worker(spec)
        if field == "arrow_embedding_inputs_artifact":
            receipt[field]["sha256"] = "0" * 64
        elif field == "arrow_embedding_inputs_verified":
            receipt[field] = False
        elif field == "arrow_embedding_inputs_verification":
            receipt[field]["read_only"] = False
        elif field == "embedding_input_storage":
            receipt[field] = "private_json"
        elif field.endswith("before_samples"):
            receipt[field]["row_accesses"] += 1
        elif field.endswith("after_samples"):
            receipt[field]["closed"] = True
        elif field.endswith("after_training"):
            receipt[field]["scalar_accesses"] = -1
        else:
            receipt[field] = -1.0
        Path(spec.output_directory, "receipt.json").write_text(json.dumps(receipt))
        return receipt

    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        inputs, index_binding, _ = _indexed_corpus_inputs(registry, tmp_path, production=True, arrow_inputs=True)
        production_binding = {"artifact": {key: inputs["embedding_production_artifact"][key] for key in ("sha256", "bytes")}}
        spec = _prepare(registry, tmp_path, job_updates=inputs, variant_updates={
            "corpus_index_binding": index_binding, "embedding_production_binding": production_binding})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor, worker_function=forge)
        assert not result["completed"] and result["failed"][0]["failure_recorded"] is True
        assert field in result["failed"][0]["error"]
    with AutoencoderRegistry(database, artifacts) as registry:
        assert registry.get_run(spec.run_id)["status"] == "failed"
        assert field in registry.get_run(spec.run_id)["result"]["error"]


def test_owner_registers_verified_corpus_provenance_and_preserves_it_on_restart(tmp_path):
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        spec = _prepare_corpus(registry, tmp_path)
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=_fixture_worker)
        assert not result["failed"], result
        summary = result["completed"][0]["result"]
        assert summary["dataset_and_split_identity_verified"] is True
        assert summary["corpus_verification"]["verification_mode"] == "manifest_and_source_bytes"
        assert summary["corpus_verification"]["source_validation"]["source_selectors_verified"] is True
        assert summary["corpus_verification"]["global_holdout_verified"] is False
        assert summary["heldout_canary_qualified"] is False
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id
    with AutoencoderRegistry(database, artifacts) as registry:
        assert registry.get_run(spec.run_id)["result"]["corpus_verification"] == summary["corpus_verification"]
        assert registry.verify_artifact({key: spec.corpus_manifest_artifact.__dict__[key] for key in ("sha256", "bytes")})


@pytest.mark.parametrize("problem", ["unstaged_source", "wrong_membership", "corrupt_source"])
def test_owner_rejects_corpus_binding_before_claim(tmp_path, problem):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_corpus(registry, tmp_path, unstaged_source=problem == "unstaged_source",
                               wrong_membership=problem == "wrong_membership")
        if problem == "corrupt_source":
            Path(spec.corpus_source_artifacts[0].path).write_bytes(b"changed")
        with pytest.raises(ValueError):
            coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                          worker_function=_fixture_worker)
        assert registry.get_run(spec.run_id)["status"] == "queued"
        assert not Path(spec.output_directory).exists()


def test_owner_rejects_worker_corrupting_verified_corpus_summary(tmp_path):
    def run(spec):
        receipt = _fixture_worker(spec)
        receipt["corpus_verification"]["source_count"] += 1
        Path(spec.output_directory, "receipt.json").write_text(json.dumps(receipt))
        return receipt

    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_corpus(registry, tmp_path)
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor, worker_function=run)
        assert not result["completed"]
        assert "corpus_verification" in result["failed"][0]["error"]
        assert registry.get_run(spec.run_id)["status"] == "failed"


def test_sparse_manifest_reopens_resumes_and_compacts_to_exact_full_bytes(tmp_path):
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    policy = coordinator.SparseCheckpointPolicy(max_depth=2)
    with AutoencoderRegistry(database, artifacts) as registry:
        spec = _prepare_sparse(registry, tmp_path)
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=_sparse_worker, sparse_checkpoint_policy=policy)
        assert not result["failed"], result
        first = result["completed"][0]
        assert first["result"]["checkpoint_storage"] == "sparse_manifest"
        assert first["result"]["checkpoint_chain_depth"] == 1
        assert not Path(spec.output_directory, "candidate.state.json").exists()
        assert len(first["result"]["checkpoint_dependencies"]) == 2
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id
    with AutoencoderRegistry(database, artifacts) as registry:
        child = _prepare_child(registry, tmp_path, first["version_id"])
        assert len(child.base_checkpoint_dependencies) == 2
        result = coordinator.run_training_jobs(registry, [child], executor_factory=ImmediateExecutor,
                                               worker_function=_sparse_worker, sparse_checkpoint_policy=policy)
        assert not result["failed"], result
        compacted = result["completed"][0]
        summary = compacted["result"]
        assert summary["checkpoint_storage"] == "full_json"
        assert summary["sparse_compaction_reasons"] == ["max_depth"]
        assert summary["checkpoint_chain_depth"] == 0
        assert summary["checkpoint_dependencies"] == []
        assert compacted["candidate"] == summary["candidate_materialized_checkpoint"]
        raw = registry.artifact_path(compacted["candidate"]).read_bytes()
        assert json.loads(raw)["feature_embedding_weights"]["fixture"] == [1.0, -0.25]
        full = _prepare_child(registry, tmp_path, first["version_id"], index=2, storage="full")
        full_result = coordinator.run_training_jobs(registry, [full], executor_factory=ImmediateExecutor,
                                                    worker_function=_sparse_worker)
        assert not full_result["failed"], full_result
        assert registry.artifact_path(full_result["completed"][0]["candidate"]).read_bytes() == raw
        assert registry.verify_artifact(summary["worker_candidate_artifact"])
    with AutoencoderRegistry(database, artifacts) as registry:
        inputs = coordinator.registered_checkpoint_inputs(registry, compacted["version_id"])
        assert inputs["base_checkpoint_dependencies"] == []
        assert inputs["base_checkpoint"]["sha256"] == compacted["candidate"]["sha256"]


def test_sparse_owner_compacts_at_patch_fraction_threshold(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=_sparse_worker,
                                               sparse_checkpoint_policy=coordinator.SparseCheckpointPolicy(max_patch_fraction=0.001))
        assert not result["failed"], result
        summary = result["completed"][0]["result"]
        assert summary["sparse_compaction_reasons"] == ["patch_fraction"]
        assert summary["checkpoint_storage"] == "full_json"


@pytest.mark.parametrize("change", ["escaped_mutation", "parent", "materialized_digest"])
def test_sparse_owner_rejects_unbound_candidate(tmp_path, change):
    def trainer(model, samples, *, validation_samples, **kwargs):
        report = _sparse_trainer(model, samples, validation_samples=validation_samples, **kwargs)
        if change == "escaped_mutation":
            model.state.feature_embedding_weights["escape"] = [7.0]
        return report

    def run(spec):
        receipt = execute_training_job(spec, trainer=trainer)
        if change == "parent":
            path = Path(receipt["candidate"]["path"])
            value = json.loads(path.read_bytes())
            value["base_version_id"] = "different-parent"
            raw = json.dumps(value).encode()
            path.write_bytes(raw)
            receipt["candidate"].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        elif change == "materialized_digest":
            receipt["candidate_materialized_checkpoint"]["sha256"] = "f" * 64
        Path(spec.output_directory, "receipt.json").write_text(json.dumps(receipt))
        return receipt

    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor, worker_function=run)
        assert not result["completed"]
        assert registry.get_run(spec.run_id)["status"] == "failed"
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


def test_sparse_missing_dependency_cannot_complete(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        first = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                              worker_function=_sparse_worker)["completed"][0]
        child = _prepare_child(registry, tmp_path, first["version_id"], dependencies=[])
        result = coordinator.run_training_jobs(registry, [child], executor_factory=ImmediateExecutor,
                                               worker_function=_sparse_worker)
        assert not result["completed"]
        assert registry.get_run(child.run_id)["status"] == "failed"


def test_registered_sparse_inputs_inventory_does_not_construct_model_state(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        first = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                              worker_function=_sparse_worker)["completed"][0]

        def forbidden(*args, **kwargs):
            raise AssertionError("job input inventory must not construct a model state")

        monkeypatch.setattr(ModalAutoencoderTrainingState, "from_dict", forbidden)
        inputs = coordinator.registered_checkpoint_inputs(registry, first["version_id"])
        assert {key: inputs["base_checkpoint"][key] for key in ("sha256", "bytes")} == first["candidate"]
        dependencies = [{key: ref[key] for key in ("sha256", "bytes")} for ref in inputs["base_checkpoint_dependencies"]]
        assert dependencies == first["result"]["checkpoint_dependencies"]


def test_sparse_corrupt_dependency_is_rejected_before_claim(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        first = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                              worker_function=_sparse_worker)["completed"][0]
        child = _prepare_child(registry, tmp_path, first["version_id"])
        Path(child.base_checkpoint_dependencies[0].path).write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="size|digest|hash"):
            coordinator.run_training_jobs(registry, [child], executor_factory=ImmediateExecutor,
                                          worker_function=_sparse_worker)
        assert registry.get_run(child.run_id)["status"] == "queued"


@pytest.mark.parametrize("capture", [False, True])
def test_v3_full_candidate_rejects_different_physical_bytes_even_when_json_equal(tmp_path, capture):
    def run(spec):
        receipt = execute_training_job(spec, trainer=_sparse_trainer if capture else _trainer)
        path = Path(receipt["candidate"]["path"])
        original = path.read_bytes()
        changed = original + b"\n"
        assert json.loads(original) == json.loads(changed)
        path.write_bytes(changed)
        receipt["candidate"].update(sha256=hashlib.sha256(changed).hexdigest(), bytes=len(changed))
        Path(spec.output_directory, "receipt.json").write_text(json.dumps(receipt))
        return receipt

    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path, job_updates={
            "schema_version": "autoencoder-training-job-v3", "candidate_storage": "full",
            "capture_sparse_patches": capture})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor, worker_function=run)
        assert not result["completed"]
        assert "materialized checkpoint byte identity" in result["failed"][0]["error"]
        assert registry.get_run(spec.run_id)["status"] == "failed"
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


@pytest.mark.parametrize("kwargs", [{"max_depth": 0}, {"max_depth": 9}, {"max_depth": True},
                                    {"max_patch_fraction": 0}, {"max_patch_fraction": float("nan")}])
def test_sparse_policy_is_owner_bounded(kwargs):
    with pytest.raises(coordinator.TrainingCoordinationError):
        coordinator.SparseCheckpointPolicy(**kwargs)


def test_owner_replays_and_stages_sparse_chain_before_completing(tmp_path):
    def run(spec):
        return execute_training_job(spec, trainer=_sparse_trainer)
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        spec = _prepare(registry, tmp_path, job_updates={"capture_sparse_patches": True})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor, worker_function=run)
        assert not result["failed"], result
        summary = result["completed"][0]["result"]
        assert summary["sparse_replay_verified"] is True
        assert len(summary["sparse_patch_artifacts"]) == 1
        assert summary["admitted"] is False
    with AutoencoderRegistry(database, artifacts) as reopened:
        saved = reopened.get_run(spec.run_id)["result"]
        assert saved["sparse_replay_verified"] is True
        assert reopened.verify_artifact(saved["sparse_patch_artifacts"][0]) == saved["sparse_patch_artifacts"][0]


def test_owner_rejects_mutation_outside_accepted_patch(tmp_path):
    def escaped(model, samples, *, validation_samples, **kwargs):
        report = _sparse_trainer(model, samples, validation_samples=validation_samples, **kwargs)
        model.state.feature_embedding_weights["unrecorded"] = [99.0]
        return report
    def run(spec):
        return execute_training_job(spec, trainer=escaped)
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path, job_updates={"capture_sparse_patches": True})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor, worker_function=run)
        assert not result["completed"]
        assert "complete candidate" in result["failed"][0]["error"]
        assert registry.get_run(spec.run_id)["status"] == "failed"


def test_owner_does_not_normalize_away_extra_persisted_candidate_fields(tmp_path):
    def run(spec):
        receipt = execute_training_job(spec, trainer=_sparse_trainer)
        path = Path(receipt["candidate"]["path"])
        value = json.loads(path.read_bytes())
        value["untracked_extra_field"] = "must not disappear during owner verification"
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        receipt["candidate"].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        (Path(spec.output_directory) / "receipt.json").write_text(json.dumps(receipt))
        return receipt
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path, job_updates={"capture_sparse_patches": True})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor, worker_function=run)
        assert not result["completed"]
        assert "complete candidate" in result["failed"][0]["error"]


def test_sparse_context_must_match_sealed_segment(tmp_path):
    def run(spec):
        receipt = execute_training_job(spec, trainer=_sparse_trainer)
        receipt["sparse_patch_segments"][0]["capture_context"]["result_revision"] += 1
        (Path(spec.output_directory) / "receipt.json").write_text(json.dumps(receipt))
        return receipt
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path, job_updates={"capture_sparse_patches": True})
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor, worker_function=run)
        assert not result["completed"]
        assert "capture context" in result["failed"][0]["error"]


def test_owner_stages_candidate_and_evidence_without_promoting(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        specs = [_prepare(registry, tmp_path, index) for index in range(2)]
        result = coordinator.run_training_jobs(registry, specs, executor_factory=ImmediateExecutor,
                                               worker_function=_fixture_worker)
        assert not result["failed"]
        assert result["admitted"] is False and result["promotion_performed"] is False
        assert result["execution_mode"] == "injected_test"
        assert result["run_count"] == 2
        for item in result["completed"]:
            run = registry.get_run(item["run_id"])
            assert run["status"] == "completed"
            assert run["result"]["optimizer_accepted_epochs"] == 1
            assert run["result"]["legal_ir_target_count"] == 1
            assert run["result"]["bridge_status"] == "active"
            assert run["result"]["heldout_canary_qualified"] is False
            assert registry.verify_artifact(item["candidate"]) == item["candidate"]
            artifact = item["worker_receipt_artifact"]
            assert registry.verify_artifact(artifact) == artifact
            receipt = json.loads(registry.artifact_path(artifact).read_bytes())
            assert receipt["job_id"] == item["job_id"]
            assert registry.resolve_head(run["variant_id"], "best")["version_id"] == run["base_version_id"]
            assert len(json.dumps(run["result"])) < 65536


def test_real_spawn_pool_keeps_registry_in_owner(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        specs = [_prepare(registry, tmp_path, index) for index in range(2)]
        result = coordinator.run_training_jobs(registry, specs, max_workers=2, worker_function=_fixture_worker)
        assert not result["failed"], result
        assert len(result["completed"]) == 2
        assert result["execution_mode"] == "injected_test"
        assert all(registry.get_run(spec.run_id)["status"] == "completed" for spec in specs)


def test_all_specs_validate_before_any_job_is_claimed(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        specs = [_prepare(registry, tmp_path), _prepare(registry, tmp_path, 1, spec_digest="0" * 64)]
        with pytest.raises(coordinator.TrainingCoordinationError, match="digest"):
            coordinator.run_training_jobs(registry, specs, executor_factory=ImmediateExecutor)
        assert all(registry.get_run(spec.run_id)["status"] == "queued" for spec in specs)
        assert not Path(specs[0].output_directory).exists()


def test_base_must_be_owner_staged_artifact(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path)
        raw = registry.artifact_path(registry.get_version(spec.base_version_id)["artifact"])
        raw.write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="digest|size|hash|corrupt"):
            coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor)
        assert registry.get_run(spec.run_id)["status"] == "queued"


@pytest.mark.parametrize("field,value", [("job_id", "other-job"), ("admitted", True),
                                         ("sample_count", 0), ("metric_disk_cache", 1),
                                         ("dataset_and_split_identity_verified", True),
                                         ("corpus_verification", {"verification_mode": "forged"})])
def test_misbinding_records_failure_without_candidate(tmp_path, field, value):
    def tamper(spec):
        receipt = _fixture_worker(spec)
        receipt[field] = value
        (Path(spec.output_directory) / "receipt.json").write_text(json.dumps(receipt))
        return receipt

    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path)
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=tamper)
        assert result["completed"] == []
        assert result["failed"][0]["failure_recorded"] is True
        assert registry.get_run(spec.run_id)["status"] == "failed"
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


def test_worker_exception_is_durable_and_other_job_completes(tmp_path):
    def selected_failure(spec):
        if spec.job_id == "job-0":
            raise RuntimeError("worker failed visibly")
        return _fixture_worker(spec)

    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        specs = [_prepare(registry, tmp_path, index) for index in range(2)]
        result = coordinator.run_training_jobs(registry, specs, executor_factory=ImmediateExecutor,
                                               worker_function=selected_failure)
        assert len(result["completed"]) == len(result["failed"]) == 1
        assert registry.get_run("run-0")["status"] == "failed"
        assert registry.get_run("run-1")["status"] == "completed"
        assert "worker failed visibly" in result["failed"][0]["error"]


def test_pending_worker_lease_is_renewed_before_expiry(tmp_path, monkeypatch):
    now = [1_800_000_000.0]
    future = Future()
    work = []
    polls = [0]
    renewals = []

    class DeferredExecutor(ImmediateExecutor):
        def submit(self, function, *args):
            work.append((function, args))
            return future

    def progress_wait(futures, *, timeout, return_when):
        now[0] += 0.12
        polls[0] += 1
        if polls[0] == 3:
            function, args = work[0]
            future.set_result(function(*args))
            return {future}, set()
        return set(), {future}

    monkeypatch.setattr(coordinator, "wait", progress_wait)
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts", clock=lambda: now[0]) as registry:
        spec = _prepare(registry, tmp_path, training_config={"max_seconds": 0.2})
        original = registry.renew_lease

        def renewal(*args, **kwargs):
            renewals.append(future.done())
            return original(*args, **kwargs)

        monkeypatch.setattr(registry, "renew_lease", renewal)
        result = coordinator.run_training_jobs(registry, [spec], lease_seconds=0.3, poll_seconds=0.01,
                                               executor_factory=DeferredExecutor, worker_function=_fixture_worker,
                                               clock=lambda: now[0])
        assert result["failed"] == []
        assert False in renewals  # At least one heartbeat preceded worker completion.
        assert result["completed"][0]["lease_renewal_count"] >= 3


def test_unbounded_lease_relation_rejected_before_dispatch(tmp_path):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path)
        with pytest.raises(coordinator.TrainingCoordinationError, match="max_seconds"):
            coordinator.run_training_jobs(registry, [spec], lease_seconds=10, executor_factory=ImmediateExecutor)
        assert registry.get_run(spec.run_id)["status"] == "queued"


@pytest.mark.parametrize("method_name", ["claim_run", "renew_lease", "complete_run", "fail_run"])
def test_response_loss_after_commit_resolves_original_operation(tmp_path, monkeypatch, method_name):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path)
        original = getattr(registry, method_name)
        calls = []

        def lose_response(*args, **kwargs):
            calls.append(args[0])
            receipt = original(*args, **kwargs)
            if len(calls) == 1:
                raise OSError("response lost after durable commit")
            return receipt

        monkeypatch.setattr(registry, method_name, lose_response)

        def failing_worker(spec):
            raise RuntimeError("synthetic worker failure")

        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=failing_worker if method_name == "fail_run" else _fixture_worker)
        assert result["resolved_operation_count"] == 1
        if method_name == "fail_run":
            assert len(result["failed"]) == 1
            assert result["failed"][0]["failure_recorded"] is True
            assert registry.get_run(spec.run_id)["status"] == "failed"
        else:
            assert result["failed"] == []
            assert len(result["completed"]) == 1
            assert registry.get_run(spec.run_id)["status"] == "completed"


def test_same_operation_is_retried_when_response_and_ledger_read_are_lost(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path)
        original = registry.complete_run
        payloads = []

        def lose_first_response(*args):
            payloads.append(json.dumps(args, sort_keys=True))
            receipt = original(*args)
            if len(payloads) == 1:
                raise OSError("committed completion response lost")
            return receipt

        def unavailable_ledger(*args):
            raise OSError("ledger lookup temporarily unavailable")

        monkeypatch.setattr(registry, "complete_run", lose_first_response)
        monkeypatch.setattr(registry, "resolve_operation", unavailable_ledger)
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=_fixture_worker)
        assert result["failed"] == []
        assert payloads[0] == payloads[1]
        assert result["mutation_retry_count"] == 1
        assert registry.get_run(spec.run_id)["status"] == "completed"


def test_inconclusive_completion_response_never_overwrites_completed_status(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare(registry, tmp_path)
        original = registry.complete_run

        def lose_every_response(*args):
            original(*args)
            raise OSError("every completion response lost")

        def unavailable_ledger(*args):
            raise OSError("ledger lookup unavailable")

        monkeypatch.setattr(registry, "complete_run", lose_every_response)
        monkeypatch.setattr(registry, "resolve_operation", unavailable_ledger)
        monkeypatch.setattr(registry, "fail_run", lambda *args: pytest.fail("cannot fail completed work"))
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor,
                                               worker_function=_fixture_worker)
        assert result["failed"] == []
        assert result["completed"][0]["completion_receipt_resolved"] is False
        assert registry.get_run(spec.run_id)["status"] == "completed"
