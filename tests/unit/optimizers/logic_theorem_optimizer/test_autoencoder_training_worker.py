"""Worker isolation and provenance tests; no checkpoint campaign or Hub access."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from functools import wraps
import json
import multiprocessing
import os
from pathlib import Path
import pickle

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState


def _job(tmp_path: Path, **updates):
    checkpoint = tmp_path / "base.state.json"
    if not checkpoint.exists():
        state = ModalAutoencoderTrainingState(feature_embedding_weights={"existing": [0.25, -0.5]})
        checkpoint.write_text(state.to_json() + "\n", encoding="utf-8")
    raw = checkpoint.read_bytes()
    result = {
        "job_id": "job-1", "run_id": "run-1", "base_version_id": "version-1",
        "base_checkpoint": {"path": str(checkpoint), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
        "output_directory": str(tmp_path / "attempt-1"),
        "code_identity": "test-source-manifest", "dataset_snapshot_id": "dataset-1", "split_snapshot_id": "split-1",
        "samples": [{"title": "5", "section": "1", "text": "The agency shall retain records."}],
        "autoencoder_config": {"compute_device": "python"},
    }
    result.update(updates)
    return result


def _trainer(model, samples, *, validation_samples, **kwargs):
    assert kwargs["legal_ir_bridge_names"] == worker.BRIDGE_NAMES
    assert kwargs["projection_update_backend"] == "python_sparse_batch"
    assert kwargs["max_line_search_attempts"] == 1
    assert kwargs["max_seconds"] == 180
    assert os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] == "0"
    assert os.environ["IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA"] == "0"
    # A local mutation tests isolated state ownership without running training.
    with model.state.transaction(label="synthetic-accepted-update"):
        model.state.feature_embedding_weights["existing"][0] = 0.75
    return {"accepted_epochs": 1, "before": {"legal_ir_target_count": len(samples)},
            "after": {"legal_ir_target_count": len(samples)}, "stopped_reason": "synthetic_fixture"}


def _spawn_entry(spec, results):
    try:
        receipt = worker.execute_training_job(spec, trainer=_trainer)
        results.put({"pid": receipt["runtime"]["pid"], "candidate": receipt["candidate"],
                     "base_state_identity": receipt["base_state_identity"], "error": ""})
    except Exception as exc:
        results.put({"error": repr(exc)})


def test_refinement_opt_in_preserves_archived_default_job_identity(tmp_path):
    default = worker.TrainingJobSpec.from_dict(_job(tmp_path))
    archived = default.to_dict()
    assert "projection_max_composed_refinement_attempts" not in archived["training_config"]
    assert "projection_max_composed_refinement_attempts" not in default.training_config.projection_kwargs()
    assert worker.TrainingJobSpec.from_dict(archived).canonical_sha256 == default.canonical_sha256
    explicit_zero = {**archived, "training_config": {
        **archived["training_config"], "projection_max_composed_refinement_attempts": 0}}
    assert worker.TrainingJobSpec.from_dict(explicit_zero).canonical_sha256 == default.canonical_sha256
    validation = [{"title": "5", "section": "2", "text": "The officer shall file reports."}]
    old = worker.TrainingJobSpec.from_dict({**archived, "validation_samples": validation})
    enabled = worker.TrainingJobSpec.from_dict({**old.to_dict(), "training_config": {
        **archived["training_config"], "projection_max_composed_refinement_attempts": 3}})
    assert enabled.canonical_sha256 != old.canonical_sha256
    assert enabled.to_dict()["training_config"]["projection_max_composed_refinement_attempts"] == 3
    assert enabled.training_config.projection_kwargs()["projection_max_composed_refinement_attempts"] == 3


@pytest.mark.parametrize("attempts", [-1, 4, True, 1.0, "2"])
def test_refinement_budget_is_explicit_and_bounded(attempts):
    with pytest.raises(worker.TrainingJobValidationError, match="must be 0..3"):
        worker.TrainingConfig(projection_max_composed_refinement_attempts=attempts)


def test_refinement_config_rejects_unqualified_regularization():
    with pytest.raises(worker.TrainingJobValidationError, match="zero l2_regularization"):
        worker.TrainingConfig(projection_max_composed_refinement_attempts=1, l2_regularization=0.1)


@pytest.mark.parametrize("validation", [[], [{"title": "5", "section": "2", "text": " THE AGENCY SHALL   RETAIN RECORDS. "}]])
def test_refinement_job_requires_disjoint_validation(tmp_path, validation):
    with pytest.raises(worker.TrainingJobValidationError, match="disjoint"):
        worker.TrainingJobSpec.from_dict(_job(tmp_path, validation_samples=validation,
            training_config={"projection_max_composed_refinement_attempts": 1}))


def test_worker_writes_private_candidate_and_complete_receipt(tmp_path, monkeypatch):
    payload = _job(tmp_path)
    checkpoint = Path(payload["base_checkpoint"]["path"])
    before = checkpoint.read_bytes()
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "previous")
    spec = worker.TrainingJobSpec.from_dict(payload)
    receipt = worker.execute_training_job(spec, trainer=_trainer)
    assert checkpoint.read_bytes() == before
    assert receipt["admitted"] is False
    assert receipt["promotion_performed"] is False
    assert receipt["optimizer_accepted_epochs"] == 1
    assert receipt["execution_mode"] == "injected_test"
    assert receipt["validation_mode"] == "in_sample"
    assert receipt["heldout_canary_qualified"] is False
    assert receipt["bridge_names"] == list(worker.BRIDGE_NAMES)
    assert receipt["use_sample_memory"] is False
    assert receipt["job_spec"] == spec.to_dict()
    assert receipt["job_spec_canonical_sha256"] == spec.canonical_sha256
    assert receipt["job_file_sha256"] is None
    assert receipt["effective_projection_config"]["projection_prescreen_mode"] == "off"
    assert receipt["effective_autoencoder_config"]["max_token_features"] == 48
    assert receipt["tree_file_sha256"].keys() == worker.SOURCE_MODULE_NAMES
    assert receipt["source_manifest_verified"] is False
    candidate = Path(receipt["candidate"]["path"]).read_bytes()
    assert hashlib.sha256(candidate).hexdigest() == receipt["candidate"]["sha256"]
    assert json.loads(candidate)["feature_embedding_weights"]["existing"][0] == 0.75
    assert json.loads((Path(spec.output_directory) / "receipt.json").read_bytes()) == receipt
    assert os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] == "previous"
    assert "roundtrip_ok" not in receipt


def test_native_worker_enters_explicit_training_gate_without_changing_job_policy(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paths as paths
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
    original_gate = paths.gated_projection_training
    calls = []
    def gate(model, samples, **kwargs):
        calls.append(dict(kwargs))
        return original_gate(model, samples, **kwargs)
    @wraps(AdaptiveModalAutoencoder.train_generalizable_projection)
    def projection(model, samples, **kwargs):
        return _trainer(model, samples, **kwargs)
    monkeypatch.setattr(paths, "gated_projection_training", gate)
    monkeypatch.setattr(AdaptiveModalAutoencoder, "train_generalizable_projection", projection)
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path))
    receipt = worker.execute_training_job(spec)
    assert len(calls) == 1 and calls[0]["execution_mode"] == paths.TRAINING_PATH
    for name, value in spec.training_config.projection_kwargs().items():
        assert calls[0][name] == value
    assert receipt["execution_path"] == "training" and receipt["execution_gate_applied"] is True
    assert receipt["training_report"]["stopped_reason"] == "synthetic_fixture"
    assert receipt["admitted"] is False and receipt["promotion_performed"] is False


def test_worker_ontology_observation_preserves_discarded_batch_recovery_and_training_result(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import ontology_capture, procedure_slot, recipient_reference
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal

    # Keep the real capture loop and optimizer exception boundary. Only the
    # leaf extractors and one deliberate record failure are synthetic fixtures.
    monkeypatch.setattr(ontology_capture, "triples_from_sample", lambda sample: [
        {"subject": "fixture", "predicate": "type", "object": "record"}])
    monkeypatch.setattr(recipient_reference, "recipient_surface_from_sentence", lambda text: "")
    monkeypatch.setattr(procedure_slot, "procedure_from_sentence", lambda text: {
        "events": [], "procedure_id": "", "surface": "", "admitted": False})
    original_record = ontology_capture.ontology_record
    record_calls = []

    def fail_second_record(**kwargs):
        record_calls.append(kwargs["sample_id"])
        if len(record_calls) == 2:
            raise ValueError("synthetic failure after one captured record")
        return original_record(**kwargs)

    monkeypatch.setattr(ontology_capture, "ontology_record", fail_second_record)
    payload = _job(tmp_path, samples=[
        {"title": "5", "section": "1", "text": "The agency shall retain records."},
        {"title": "5", "section": "2", "text": "The officer shall retain the file."},
    ])
    spec = worker.TrainingJobSpec.from_dict(payload)
    captured = {}

    def trainer(model, samples, *, validation_samples, **kwargs):
        captured["samples"] = samples
        captured["discarded"] = modal._capture_ontology(samples)
        captured["recovered"] = modal._capture_ontology(samples)
        captured["report"] = _trainer(model, samples, validation_samples=validation_samples, **kwargs)
        return captured["report"]

    receipt = worker.execute_training_job(spec, trainer=trainer)
    assert captured["discarded"] == []
    assert len(captured["recovered"]) == 2
    assert [row["sample_id"] for row in captured["recovered"]] == [sample.sample_id for sample in captured["samples"]]
    assert all(row["admitted"] is False for row in captured["recovered"])
    assert receipt["training_report"] == captured["report"]
    assert receipt["execution_mode"] == "injected_test"
    observation = receipt["ontology_capture_observation"]
    assert observation["context_closed"] is True
    assert observation["reuse_qualified"] is False
    assert observation["producer_identity_verified"] is False
    assert observation["producer_identity"]["job_spec_sha256"] == spec.canonical_sha256
    batches = [row for row in observation["captures"] if row["name"] == "capture_samples"]
    wrappers = [row for row in observation["captures"] if row["name"] == "optimizer_wrapper"]
    assert len(batches) == len(wrappers) == 2
    assert batches[0]["outcome"] == "aborted"
    assert batches[0]["started_record_count"] == 2
    assert batches[0]["emitted_record_count"] == 1
    assert batches[0]["returned_record_count"] is None
    assert wrappers[0]["outcome"] == "returned_with_observed_error"
    assert wrappers[0]["returned_record_count"] == 0
    assert batches[1]["outcome"] == "returned_without_observed_error"
    assert batches[1]["emitted_record_count"] == batches[1]["returned_record_count"] == 2
    assert wrappers[1]["outcome"] == "returned_without_observed_error"
    assert any(row["stage"] == "capture_call" and row["exception_type"] == "builtins.ValueError"
               and row["disposition"] == "suppressed" for row in observation["errors"])
    assert all(row["reuse_qualified"] is False for row in observation["captures"] + observation["records"])
    persisted = json.loads((Path(spec.output_directory) / "receipt.json").read_bytes())
    assert persisted == receipt
    # A later capture outside the job returns the same records and cannot add
    # observations to the already closed worker context or its saved receipt.
    assert modal._capture_ontology(captured["samples"]) == captured["recovered"]
    assert receipt == persisted
    baseline_spec = worker.TrainingJobSpec.from_dict({**payload, "job_id": "baseline", "run_id": "baseline",
        "output_directory": str(tmp_path / "baseline")})
    baseline = worker.execute_training_job(baseline_spec, trainer=_trainer)
    assert baseline["training_report"] == receipt["training_report"]
    assert baseline["candidate"]["sha256"] == receipt["candidate"]["sha256"]
    assert baseline["ontology_capture_observation"]["captures"] == []
    assert baseline["ontology_capture_observation"]["errors"] == []


def test_worker_ontology_observation_restores_enclosing_context_after_trainer_exception(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_ontology_observation import observe_ontology_captures

    failed_spec = worker.TrainingJobSpec.from_dict(_job(tmp_path))
    original_checkpoint = Path(failed_spec.base_checkpoint.path).read_bytes()

    def interrupted(model, samples, *, validation_samples, **kwargs):
        assert modal._capture_ontology([]) == []
        _trainer(model, samples, validation_samples=validation_samples, **kwargs)
        raise RuntimeError("synthetic trainer interruption")

    with observe_ontology_captures(producer_identity={"fixture": "outer"}) as enclosing:
        with pytest.raises(RuntimeError, match="synthetic trainer interruption"):
            worker.execute_training_job(failed_spec, trainer=interrupted)
        assert enclosing.to_dict()["captures"] == []
        assert not (Path(failed_spec.output_directory) / "receipt.json").exists()
        assert not (Path(failed_spec.output_directory) / "candidate.state.json").exists()
        # This call must now reach the restored enclosing collector, proving
        # that the failed job did not leave its ContextVar installed.
        assert modal._capture_ontology([]) == []
        outer_captures = enclosing.to_dict()["captures"]
        assert [row["name"] for row in outer_captures] == ["optimizer_wrapper", "capture_samples"]
        assert all(row["outcome"] == "returned_without_observed_error" for row in outer_captures)
        next_spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, job_id="next-job", run_id="next-run",
            output_directory=str(tmp_path / "next-attempt")))
        receipt = worker.execute_training_job(next_spec, trainer=_trainer)
        assert enclosing.to_dict()["captures"] == outer_captures
    assert enclosing.to_dict()["context_closed"] is True
    assert Path(failed_spec.base_checkpoint.path).read_bytes() == original_checkpoint
    observation = receipt["ontology_capture_observation"]
    assert observation["context_closed"] is True and observation["reuse_qualified"] is False
    assert observation["captures"] == observation["records"] == observation["errors"] == []
    assert observation["producer_identity"]["job_spec_sha256"] == next_spec.canonical_sha256
    assert receipt["execution_mode"] == "injected_test"
    assert json.loads((Path(next_spec.output_directory) / "receipt.json").read_bytes()) == receipt


def test_job_roundtrip_is_deeply_immutable(tmp_path):
    payload = _job(tmp_path, autoencoder_config={"modal_families": ["deontic"]})
    spec = worker.TrainingJobSpec.from_dict(payload)
    digest = spec.canonical_sha256
    payload["autoencoder_config"]["modal_families"].append("temporal")
    assert spec.autoencoder_config["modal_families"] == ("deontic",)
    with pytest.raises(TypeError):
        spec.autoencoder_config["compute_device"] = "python"
    assert worker.TrainingJobSpec.from_dict(spec.to_dict()).canonical_sha256 == digest


def test_legacy_job_canonical_bytes_do_not_gain_new_default_fields(tmp_path):
    payload = _job(tmp_path, schema_version="autoencoder-training-job-v1")
    spec = worker.TrainingJobSpec.from_dict(payload)
    encoded = spec.to_dict()
    assert not {"target_snapshot_artifact", "capture_sparse_patches", "arrow_feature_weights_artifact"} & set(encoded)
    assert worker.TrainingJobSpec.from_dict(encoded).canonical_sha256 == spec.canonical_sha256
    assert worker.execute_training_job(spec, trainer=_trainer)["job_spec"] == encoded
    payload["capture_sparse_patches"] = True
    with pytest.raises(worker.TrainingJobValidationError, match="v2"):
        worker.TrainingJobSpec.from_dict(payload)


def test_v1_omitted_and_empty_source_manifest_preserve_distinct_archived_bytes_after_pickle(tmp_path):
    payload = _job(tmp_path, schema_version="autoencoder-training-job-v1")
    omitted = worker.TrainingJobSpec.from_dict(payload)
    explicit = worker.TrainingJobSpec.from_dict({**payload, "expected_source_sha256": {}})
    assert "expected_source_sha256" not in omitted.to_dict()
    assert explicit.to_dict()["expected_source_sha256"] == {}
    assert omitted.canonical_sha256 != explicit.canonical_sha256
    for spec in (omitted, explicit):
        encoded = spec.to_dict()
        raw = json.dumps(encoded, sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"), allow_nan=False).encode()
        assert spec.canonical_sha256 == hashlib.sha256(raw).hexdigest()
        for restored in (worker.TrainingJobSpec.from_dict(encoded), pickle.loads(pickle.dumps(spec))):
            assert restored.to_dict() == encoded
            assert restored.canonical_sha256 == spec.canonical_sha256
    constructor_payload = {**payload,
        "base_checkpoint": worker.CheckpointArtifact.from_dict(payload["base_checkpoint"]),
        "samples": tuple(worker.SampleRecord.from_dict(row) for row in payload["samples"])}
    assert worker.TrainingJobSpec(**constructor_payload).to_dict()["expected_source_sha256"] == {}


@pytest.mark.parametrize("schema", ["autoencoder-training-job-v1", "autoencoder-training-job-v2"])
def test_existing_job_schemas_preserve_canonical_hash_without_v3_defaults(tmp_path, schema):
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, schema_version=schema))
    encoded = spec.to_dict()
    assert "candidate_storage" not in encoded
    assert "base_checkpoint_dependencies" not in encoded
    historical_bytes = json.dumps(encoded, sort_keys=True, ensure_ascii=True,
                                  separators=(",", ":"), allow_nan=False).encode()
    assert spec.canonical_sha256 == hashlib.sha256(historical_bytes).hexdigest()
    assert worker.TrainingJobSpec.from_dict(encoded).canonical_sha256 == spec.canonical_sha256


def test_schema_less_json_still_means_v2(tmp_path):
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path))
    assert spec.schema_version == "autoencoder-training-job-v2"


@pytest.mark.parametrize("schema", [f"autoencoder-training-job-v{n}" for n in range(1, 5)])
def test_existing_job_schemas_preserve_canonical_identity_without_v5_fields(tmp_path, schema):
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, schema_version=schema))
    encoded = spec.to_dict()
    assert "corpus_index_artifact" not in encoded
    assert "corpus_selection_sha256" not in encoded
    raw = json.dumps(encoded, sort_keys=True, ensure_ascii=True,
                     separators=(",", ":"), allow_nan=False).encode()
    assert spec.canonical_sha256 == hashlib.sha256(raw).hexdigest()
    assert worker.TrainingJobSpec.from_dict(encoded).canonical_sha256 == spec.canonical_sha256
    receipt = worker.execute_training_job(spec, trainer=_trainer)
    assert not {"corpus_index_artifact", "corpus_selection_sha256", "corpus_index_membership_verified"} & receipt.keys()
    assert "corpus_index_verification" not in receipt["corpus_verification"]


def test_constructor_default_remains_v4(tmp_path):
    payload = _job(tmp_path)
    payload["base_checkpoint"] = worker.CheckpointArtifact.from_dict(payload["base_checkpoint"])
    payload["samples"] = tuple(worker.SampleRecord.from_dict(row) for row in payload["samples"])
    assert worker.TrainingJobSpec(**payload).schema_version == "autoencoder-training-job-v4"


def test_pre_v6_positional_constructor_preserves_final_legacy_schema_argument(tmp_path):
    payload = _job(tmp_path, schema_version=worker.LEGACY_SCHEMA_VERSION, expected_source_sha256={})
    expected = worker.TrainingJobSpec.from_dict(payload)
    # Keep the pre-v6 positional signature explicit so field insertion cannot
    # silently shift the schema argument into a new optional artifact slot.
    restored = worker.TrainingJobSpec(
        expected.job_id, expected.run_id, expected.base_version_id, expected.base_checkpoint,
        expected.output_directory, expected.code_identity, expected.dataset_snapshot_id,
        expected.split_snapshot_id, expected.samples, expected.validation_samples, expected.variant,
        expected.training_config, expected.autoencoder_config, expected.expected_source_sha256,
        expected.target_snapshot_id, expected.target_snapshot_artifact, expected.capture_sparse_patches,
        expected.arrow_feature_weights_artifact, expected.candidate_storage, expected.base_checkpoint_dependencies,
        expected.corpus_manifest_artifact, expected.corpus_source_artifacts, expected.corpus_index_artifact,
        expected.corpus_selection_sha256, worker.LEGACY_SCHEMA_VERSION,
    )
    assert restored.schema_version == worker.LEGACY_SCHEMA_VERSION
    assert restored.embedding_production_artifact is None
    assert restored.to_dict() == expected.to_dict()
    assert restored.canonical_sha256 == expected.canonical_sha256


@pytest.mark.parametrize("schema", ["autoencoder-training-job-v1", "autoencoder-training-job-v2", "autoencoder-training-job-v3"])
def test_existing_job_schemas_preserve_canonical_hash_without_v4_defaults(tmp_path, schema):
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, schema_version=schema))
    encoded = spec.to_dict()
    assert "corpus_manifest_artifact" not in encoded
    assert "corpus_source_artifacts" not in encoded
    if schema == "autoencoder-training-job-v3":
        assert encoded["candidate_storage"] == "full"
        assert encoded["base_checkpoint_dependencies"] == []
    historical_bytes = json.dumps(encoded, sort_keys=True, ensure_ascii=True,
                                  separators=(",", ":"), allow_nan=False).encode()
    assert spec.canonical_sha256 == hashlib.sha256(historical_bytes).hexdigest()
    assert worker.TrainingJobSpec.from_dict(encoded).canonical_sha256 == spec.canonical_sha256


def test_v4_without_manifest_remains_explicitly_unverified(tmp_path):
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, schema_version="autoencoder-training-job-v4"))
    receipt = worker.execute_training_job(spec, trainer=_trainer)
    assert receipt["dataset_and_split_identity_verified"] is False
    assert receipt["corpus_verification"]["verification_mode"] == "legacy_unverified"
    assert receipt["corpus_verification"]["frontend"] == "legacy_us_code"
    assert receipt["heldout_canary_qualified"] is False
    assert receipt["candidate_materialized_checkpoint"] == {key: receipt["candidate"][key] for key in ("sha256", "bytes")}


def _corpus_job(tmp_path, *, mode="diagnostic", source_kind=None):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
        EmbeddingProvenance, SourceArtifact, SourceSampleRecord, SourceSpan, build_corpus_manifest,
    )
    records, sources = [], []
    texts = ["The agency shall retain records.", "The officer shall submit the report."]
    for index, text in enumerate(texts):
        path = tmp_path / f"source-{index}.txt"
        raw = text.encode()
        path.write_bytes(raw)
        ref = SourceArtifact(hashlib.sha256(raw).hexdigest(), len(raw))
        citation = f"5 USC {index + 1}"
        span = SourceSpan(ref, source_kind or ("us_code" if mode == "corpus" else "diagnostic"),
                          "fixture-v1", f"document-{index}", "en", citation, 0, len(raw))
        sample = worker.SampleRecord("5", str(index + 1), text, citation=citation,
                                     embedding_model="fixture-embedding" if mode == "corpus" else "mock:stable-sha256",
                                     embedding_vector=(1.0, 0.0) if mode == "corpus" else None)
        provenance = EmbeddingProvenance("fixture-embedding", "a" * 40, "b" * 64) if mode == "corpus" else None
        records.append(SourceSampleRecord(span, sample, provenance))
        sources.append({"path": str(path), "sha256": ref.sha256, "bytes": ref.bytes})
    train = records[:1] if mode == "corpus" else records
    validation = records[1:] if mode == "corpus" else records
    manifest = build_corpus_manifest(records, training_record_ids=[row.record_id for row in train],
                                     validation_record_ids=[row.record_id for row in validation], mode=mode)
    paths = {item["sha256"]: item["path"] for item in sources}
    saved = manifest.save(tmp_path / "corpus.manifest.json", resolver=lambda ref: paths[ref["sha256"]])
    return _job(tmp_path, schema_version="autoencoder-training-job-v4",
                dataset_snapshot_id=manifest.dataset_snapshot_id, split_snapshot_id=manifest.split_snapshot_id,
                samples=[asdict(row.sample) for row in train], validation_samples=[asdict(row.sample) for row in validation],
                corpus_manifest_artifact={key: saved[key] for key in ("path", "sha256", "bytes")},
                corpus_source_artifacts=sources)


@pytest.mark.parametrize("mode", ["diagnostic", "corpus"])
def test_v4_verifies_exact_source_batch_before_training_without_claiming_global_holdout(tmp_path, mode):
    spec = worker.TrainingJobSpec.from_dict(_corpus_job(tmp_path, mode=mode))
    receipt = worker.execute_training_job(spec, trainer=_trainer)
    qualification = receipt["corpus_verification"]
    assert receipt["dataset_and_split_identity_verified"] is True
    assert receipt["caller_identity_labels_verified"] is False
    assert qualification["verification_mode"] == "manifest_and_source_bytes"
    assert qualification["dataset_snapshot_id"] == spec.dataset_snapshot_id
    assert qualification["split_snapshot_id"] == spec.split_snapshot_id
    assert qualification["source_validation"]["source_selectors_verified"] is True
    assert qualification["batch_split_disjoint"] is (mode == "corpus")
    assert qualification["global_holdout_verified"] is False
    assert qualification["embedding_producer_authenticated"] is False
    assert receipt["heldout_canary_qualified"] is False
    assert receipt["admitted"] is False


@pytest.mark.parametrize("change", ["source_bytes", "manifest_bytes", "dataset_id", "split_id", "sample_order", "validation_leakage", "embedding", "missing_source"])
def test_v4_input_tampering_fails_before_trainer_and_output(tmp_path, change):
    payload = _corpus_job(tmp_path, mode="corpus" if change == "validation_leakage" else "diagnostic")
    if change == "source_bytes":
        Path(payload["corpus_source_artifacts"][0]["path"]).write_bytes(b"changed source")
    elif change == "manifest_bytes":
        path = Path(payload["corpus_manifest_artifact"]["path"])
        path.write_bytes(path.read_bytes() + b"\n")
    elif change in {"dataset_id", "split_id"}:
        payload["dataset_snapshot_id" if change == "dataset_id" else "split_snapshot_id"] = "wrong-identity"
    elif change == "sample_order":
        payload["samples"].reverse()
    elif change == "validation_leakage":
        payload["validation_samples"] = payload["samples"]
    elif change == "embedding":
        payload["samples"][0]["embedding_vector"] = [0.0, -0.0]
    elif change == "missing_source":
        payload["corpus_source_artifacts"].pop()
    spec = worker.TrainingJobSpec.from_dict(payload)
    calls = []
    with pytest.raises(ValueError):
        worker.execute_training_job(spec, trainer=lambda *args, **kwargs: calls.append(True))
    assert calls == []
    assert not Path(spec.output_directory).exists()


def test_manifest_requires_v4_and_exact_unique_source_descriptors(tmp_path):
    payload = _corpus_job(tmp_path)
    payload["schema_version"] = "autoencoder-training-job-v3"
    with pytest.raises(worker.TrainingJobValidationError, match="v4"):
        worker.TrainingJobSpec.from_dict(payload)
    payload["schema_version"] = "autoencoder-training-job-v4"
    payload["corpus_source_artifacts"].append(payload["corpus_source_artifacts"][0])
    with pytest.raises(worker.TrainingJobValidationError, match="duplicate corpus source"):
        worker.TrainingJobSpec.from_dict(payload)


def test_constitution_diagnostic_manifest_preserves_frontend_limitation(tmp_path):
    spec = worker.TrainingJobSpec.from_dict(_corpus_job(tmp_path, source_kind="us_constitution"))
    receipt = worker.execute_training_job(spec, trainer=_trainer)
    assert receipt["corpus_verification"]["source_kind_counts"] == {"us_constitution": 2}
    assert receipt["corpus_verification"]["frontend"] == "legacy_us_code"
    assert receipt["corpus_verification"]["mode"] == "diagnostic"
    assert "roundtrip_ok" not in json.dumps(receipt)
    with pytest.raises(ValueError, match="qualified English us_code"):
        _corpus_job(tmp_path, mode="corpus", source_kind="us_constitution")


def _declared_native_profile_fixture(records, sources, path):
    """Hand-construct caller-declared evidence; this fixture did not run inference.

    The native profile is only a declaration in the integrity codec, never
    runtime attestation. Injected producer execution remains ineligible.
    """
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as ep
    inputs = [ep.EmbeddingInput.from_source_record(record) for record in records]
    resolver = lambda ref: sources[ref["sha256"]]["path"]
    receipt = ep.build_embedding_production_receipt(
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
    return receipt, receipt.save(path, resolver=resolver), receipt.to_corpus_records(resolver=resolver)


def _indexed_corpus_job(tmp_path, *, training_partition="train", validation_partition="validation",
                        mutate_record=False, production=False, record_transform=None, arrow_inputs=False):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as ci
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import (
        EmbeddingProvenance, SourceArtifact, SourceSampleRecord, SourceSpan, build_corpus_manifest,
    )
    records, sources = [], {}
    for number in range(32):
        text = f"The agency shall retain record number {number} for at least {number + 3} days."
        raw = text.encode()
        path = tmp_path / f"indexed-source-{number}.txt"
        path.write_bytes(raw)
        ref = SourceArtifact(hashlib.sha256(raw).hexdigest(), len(raw))
        citation = f"5 USC {number + 1}"
        span = SourceSpan(ref, "us_code", "fixture-v1", f"document-{number}", "en", citation, 0, len(raw))
        sample = worker.SampleRecord("5", str(number + 1), text, citation=citation,
                                     embedding_model="fixture-embedding", embedding_vector=(float(number), -0.0))
        records.append(SourceSampleRecord(span, sample, EmbeddingProvenance("fixture-embedding", "a" * 40, "b" * 64)))
        sources[ref.sha256] = {"path": str(path), "sha256": ref.sha256, "bytes": ref.bytes}
    if production:
        production_receipt, production_artifact, records = _declared_native_profile_fixture(records, sources, tmp_path / "production.json")
    if record_transform is not None:
        records = [record_transform(row) for row in records]
    selection = hashlib.sha256("\n".join(sorted(row.record_id for row in records)).encode()).hexdigest()
    index = ci.build_corpus_index(records,
        scope=ci.IndexScope(selection, (hashlib.sha256(b"fixture-release-root").hexdigest(),)),
        policy=ci.SplitPolicy("worker-index-fixture-v1", train=2500, validation=2500, canary=2500, holdout=2500))
    assert len(set(index.record_groups.values())) == len(records)
    saved_index = index.save(tmp_path / "corpus.index.json")
    lookup = {row.record_id: row for row in records}
    train = [lookup[key] for key in reversed(index.record_ids_for(training_partition)[:2])]
    train_ids = {row.record_id for row in train}
    validation_ids = [key for key in index.record_ids_for(validation_partition) if key not in train_ids]
    validation = [lookup[key] for key in reversed(validation_ids[-2:])]
    assert len(train) == len(validation) == 2
    if mutate_record:
        train[0] = replace(train[0], sample=replace(train[0].sample, embedding_vector=(1.0, 0.0)))
    manifest = build_corpus_manifest(train + validation,
        training_record_ids=[row.record_id for row in train],
        validation_record_ids=[row.record_id for row in validation], mode="corpus")
    saved_manifest = manifest.save(tmp_path / "indexed-batch.manifest.json",
                                    resolver=lambda ref: sources[ref["sha256"]]["path"])
    payload = _job(tmp_path, schema_version="autoencoder-training-job-v5",
        dataset_snapshot_id=manifest.dataset_snapshot_id, split_snapshot_id=manifest.split_snapshot_id,
        samples=[asdict(row.sample) for row in train], validation_samples=[asdict(row.sample) for row in validation],
        corpus_manifest_artifact={key: saved_manifest[key] for key in ("path", "sha256", "bytes")},
        corpus_source_artifacts=[sources[ref["sha256"]] for ref in manifest.source_refs],
        corpus_index_artifact={key: saved_index[key] for key in ("path", "sha256", "bytes")},
        corpus_selection_sha256=selection)
    if production:
        payload.update(schema_version=worker.PRODUCED_SCHEMA_VERSION,
                       embedding_production_artifact=production_artifact)
    if arrow_inputs:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_arrow_inputs import write_embedding_inputs_ipc
        saved = write_embedding_inputs_ipc(manifest.records, tmp_path / "inputs.arrow", production=production_receipt,
                                            resolver=lambda ref: sources[ref["sha256"]]["path"])
        payload.update(schema_version=worker.ARROW_INPUT_SCHEMA_VERSION,
                       arrow_embedding_inputs_artifact={key: saved[key] for key in ("path", "sha256", "bytes")})
    return payload, index, manifest


@pytest.mark.parametrize("field,match", [
    ("corpus_index_artifact", "v5 requires"),
    ("corpus_selection_sha256", "v5 requires"),
    ("corpus_manifest_artifact", "manifest and source artifacts"),
    ("corpus_source_artifacts", "manifest and source artifacts"),
    ("validation_samples", "nonempty validation_samples"),
])
@pytest.mark.parametrize("production", [False, True])
def test_indexed_jobs_require_all_index_and_source_bindings_and_explicit_validation(tmp_path, field, match, production):
    payload, _, _ = _indexed_corpus_job(tmp_path, production=production)
    payload.pop(field)
    with pytest.raises(worker.TrainingJobValidationError, match=match):
        worker.TrainingJobSpec.from_dict(payload)
    assert not Path(payload["output_directory"]).exists()


def test_v5_rejects_explicit_empty_validation(tmp_path):
    payload, _, _ = _indexed_corpus_job(tmp_path)
    payload["validation_samples"] = []
    with pytest.raises(worker.TrainingJobValidationError, match="nonempty validation_samples"):
        worker.TrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize("schema", [f"autoencoder-training-job-v{number}" for number in range(1, 6)])
def test_v1_through_v5_omit_and_reject_embedding_production_binding(tmp_path, schema):
    payload = _indexed_corpus_job(tmp_path)[0] if schema == worker.INDEXED_SCHEMA_VERSION else _job(tmp_path, schema_version=schema)
    spec = worker.TrainingJobSpec.from_dict(payload)
    historical = worker._json_bytes(spec.to_dict())
    assert "embedding_production_artifact" not in spec.to_dict()
    for value in (payload, {**payload, "embedding_production_artifact": None}):
        decoded = worker.TrainingJobSpec.from_dict(value)
        assert worker._json_bytes(decoded.to_dict()) == historical
        assert pickle.loads(pickle.dumps(decoded)).canonical_sha256 == spec.canonical_sha256
    payload["embedding_production_artifact"] = dict(payload["base_checkpoint"])
    with pytest.raises(worker.TrainingJobValidationError, match="v6 job schema"):
        worker.TrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize("value,match", [
    (None, "v6 requires embedding_production_artifact"),
    ({"path": "/synthetic-receipt", "sha256": "a" * 64, "bytes": 64 * 1024 * 1024 + 1}, "byte bound"),
    ({"path": "/synthetic-receipt", "sha256": "a" * 64, "bytes": True}, "numeric"),
])
def test_v6_requires_bounded_production_receipt(tmp_path, value, match):
    payload, _, _ = _indexed_corpus_job(tmp_path)
    payload.update(schema_version=worker.PRODUCED_SCHEMA_VERSION, embedding_production_artifact=value)
    with pytest.raises(worker.TrainingJobValidationError, match=match):
        worker.TrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize("schema", [f"autoencoder-training-job-v{number}" for number in range(1, 7)])
def test_v1_through_v6_keep_arrow_inputs_out_of_canonical_bytes(tmp_path, schema):
    if schema in {worker.INDEXED_SCHEMA_VERSION, worker.PRODUCED_SCHEMA_VERSION}:
        payload, _, _ = _indexed_corpus_job(tmp_path, production=schema == worker.PRODUCED_SCHEMA_VERSION)
    else:
        payload = _job(tmp_path, schema_version=schema)
    spec = worker.TrainingJobSpec.from_dict(payload)
    historical = worker._json_bytes(spec.to_dict())
    assert "arrow_embedding_inputs_artifact" not in spec.to_dict()
    decoded = worker.TrainingJobSpec.from_dict({**payload, "arrow_embedding_inputs_artifact": None})
    assert worker._json_bytes(decoded.to_dict()) == historical
    assert pickle.loads(pickle.dumps(decoded)).canonical_sha256 == spec.canonical_sha256
    payload["arrow_embedding_inputs_artifact"] = dict(payload["base_checkpoint"])
    with pytest.raises(worker.TrainingJobValidationError, match="v7 job schema"):
        worker.TrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize("value,match", [
    (None, "v7 requires arrow_embedding_inputs_artifact"),
    ({"path": "/unused.arrow", "sha256": "a" * 64, "bytes": worker.MAX_ARROW_EMBEDDING_INPUT_BYTES + 1}, "byte bound"),
    ({"path": "/unused.arrow", "sha256": "a" * 64, "bytes": True}, "numeric"),
])
def test_v7_requires_bounded_arrow_inputs(tmp_path, value, match):
    payload, _, _ = _indexed_corpus_job(tmp_path, production=True)
    payload.update(schema_version=worker.ARROW_INPUT_SCHEMA_VERSION, arrow_embedding_inputs_artifact=value)
    with pytest.raises(worker.TrainingJobValidationError, match=match):
        worker.TrainingJobSpec.from_dict(payload)


def test_v7_preserves_verified_mapped_rows_through_training_and_closes_them(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_arrow_inputs as ai
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_samples
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder

    payload, _, manifest = _indexed_corpus_job(tmp_path, production=True, arrow_inputs=True)
    spec = worker.TrainingJobSpec.from_dict(payload)
    mapped, built = [], []
    load, build, initialize = ai.load_embedding_inputs_ipc, legal_samples.build_us_code_sample, AdaptiveModalAutoencoder.__init__

    def checked_load(path, **kwargs):
        assert not Path(spec.output_directory).exists()
        assert kwargs["records"] == manifest.records
        assert kwargs["expected_sha256"] == spec.arrow_embedding_inputs_artifact.sha256
        assert kwargs["expected_size_bytes"] == spec.arrow_embedding_inputs_artifact.bytes
        result = load(path, **kwargs)
        mapped.append(result)
        return result

    @wraps(initialize)
    def checked_initialize(self, *args, **kwargs):
        assert len(mapped) == 1 and mapped[0].statistics["closed"] is False
        return initialize(self, *args, **kwargs)

    def checked_build(**kwargs):
        view = kwargs["embedding_vector"]
        assert type(view) is ai.MappedEmbeddingVector
        sample = build(**kwargs)
        assert sample.embedding_vector is view
        built.append(sample)
        return sample

    def trainer(model, samples, *, validation_samples, **kwargs):
        assert list(samples) + list(validation_samples) == built
        assert all(type(sample.embedding_vector) is ai.MappedEmbeddingVector for sample in built)
        return _trainer(model, samples, validation_samples=validation_samples, **kwargs)

    monkeypatch.setattr(ai, "load_embedding_inputs_ipc", checked_load)
    monkeypatch.setattr(legal_samples, "build_us_code_sample", checked_build)
    monkeypatch.setattr(AdaptiveModalAutoencoder, "__init__", checked_initialize)
    receipt = worker.execute_training_job(spec, trainer=trainer)
    assert mapped[0].statistics["closed"] is True
    with pytest.raises(ValueError):
        built[0].embedding_vector[0]
    assert receipt["embedding_input_storage"] == "arrow_mapped_float32"
    assert receipt["arrow_embedding_inputs_artifact"] == payload["arrow_embedding_inputs_artifact"]
    assert receipt["arrow_embedding_inputs_verified"] is True
    assert receipt["arrow_embedding_inputs_verification"]["whole_training_zero_copy"] is False
    assert receipt["arrow_embedding_inputs_statistics_after_samples"]["row_accesses"] == 4
    assert receipt["arrow_embedding_inputs_statistics_after_training"]["closed"] is False
    assert receipt["sample_build_seconds_per_sample"] * 4 == pytest.approx(receipt["sample_build_seconds"])
    assert pickle.loads(pickle.dumps(spec)).canonical_sha256 == spec.canonical_sha256
    assert receipt["embedding_production_verified"] is receipt["corpus_index_membership_verified"] is True


@pytest.mark.parametrize("problem", ["hash", "bytes", "size", "record_order"])
def test_v7_rejects_invalid_arrow_inputs_before_model_and_output(tmp_path, monkeypatch, problem):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_arrow_inputs as ai
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production import load_embedding_production_receipt
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder

    payload, _, manifest = _indexed_corpus_job(tmp_path, production=True, arrow_inputs=True)
    artifact = payload["arrow_embedding_inputs_artifact"]
    if problem == "hash":
        artifact["sha256"] = "0" * 64
    elif problem == "size":
        artifact["bytes"] += 1
    elif problem == "bytes":
        path = Path(artifact["path"])
        path.write_bytes(path.read_bytes()[:-1])
    else:
        production_ref = payload["embedding_production_artifact"]
        production = load_embedding_production_receipt(production_ref["path"], expected_sha256=production_ref["sha256"],
                                                        expected_size_bytes=production_ref["bytes"])
        sources = {item["sha256"]: item["path"] for item in payload["corpus_source_artifacts"]}
        saved = ai.write_embedding_inputs_ipc(tuple(reversed(manifest.records)), tmp_path / "reordered.arrow",
                                               production=production, resolver=lambda ref: sources[ref["sha256"]])
        payload["arrow_embedding_inputs_artifact"] = {key: saved[key] for key in ("path", "sha256", "bytes")}

    def forbidden(*args, **kwargs):
        pytest.fail("invalid Arrow inputs reached model construction or training")

    monkeypatch.setattr(AdaptiveModalAutoencoder, "__init__", forbidden)
    spec = worker.TrainingJobSpec.from_dict(payload)
    with pytest.raises(ValueError):
        worker.execute_training_job(spec, trainer=forbidden)
    assert not Path(spec.output_directory).exists()


@pytest.mark.parametrize("failure", ["trainer", "mapped_drift"])
def test_v7_closes_mapping_and_cannot_publish_receipt_after_failure(tmp_path, monkeypatch, failure):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_arrow_inputs as ai
    payload, _, _ = _indexed_corpus_job(tmp_path, production=True, arrow_inputs=True)
    spec = worker.TrainingJobSpec.from_dict(payload)
    loaded = []
    original = ai.load_embedding_inputs_ipc

    def capture(*args, **kwargs):
        mapping = original(*args, **kwargs)
        loaded.append(mapping)
        return mapping

    def trainer(model, samples, *, validation_samples, **kwargs):
        if failure == "trainer":
            raise RuntimeError("injected trainer failure")
        # Persistent replacement leaves the existing mapped inode intact but
        # must fail the final artifact identity check before receipt emission.
        path = Path(spec.arrow_embedding_inputs_artifact.path)
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(b"changed")
        os.replace(replacement, path)
        return _trainer(model, samples, validation_samples=validation_samples, **kwargs)

    monkeypatch.setattr(ai, "load_embedding_inputs_ipc", capture)
    with pytest.raises((ValueError, RuntimeError)):
        worker.execute_training_job(spec, trainer=trainer)
    assert loaded[0].statistics["closed"] is True
    assert not Path(spec.output_directory, "receipt.json").exists()


def test_v6_rejects_diagnostic_manifest_before_model(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_manifest import build_corpus_manifest
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder

    payload, _, manifest = _indexed_corpus_job(tmp_path, production=True)
    diagnostic = build_corpus_manifest(manifest.records, training_record_ids=manifest.to_dict()["split"]["training_record_ids"],
                                       validation_record_ids=manifest.to_dict()["split"]["validation_record_ids"], mode="diagnostic")
    paths = {item["sha256"]: item["path"] for item in payload["corpus_source_artifacts"]}
    saved = diagnostic.save(tmp_path / "diagnostic.manifest.json", resolver=lambda ref: paths[ref["sha256"]])
    payload.update(corpus_manifest_artifact={key: saved[key] for key in ("path", "sha256", "bytes")},
                   dataset_snapshot_id=diagnostic.dataset_snapshot_id, split_snapshot_id=diagnostic.split_snapshot_id)

    def forbidden(*args, **kwargs):
        pytest.fail("diagnostic production input reached model construction or training")

    monkeypatch.setattr(AdaptiveModalAutoencoder, "__init__", forbidden)
    spec = worker.TrainingJobSpec.from_dict(payload)
    with pytest.raises(worker.TrainingJobValidationError, match="v6 requires corpus mode"):
        worker.execute_training_job(spec, trainer=forbidden)
    assert not Path(spec.output_directory).exists()


def test_v6_binds_subset_production_before_model_and_keeps_claims_limited(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_production as ep
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder

    payload, _, manifest = _indexed_corpus_job(tmp_path, production=True)
    spec = worker.TrainingJobSpec.from_dict(payload)
    assert pickle.loads(pickle.dumps(spec)).to_dict() == spec.to_dict()
    calls = []
    load, verify = ep.load_embedding_production_receipt, ep.EmbeddingProductionReceipt.verify_records
    initialize = AdaptiveModalAutoencoder.__init__

    def checked_load(path, **kwargs):
        assert not calls and not Path(spec.output_directory).exists()
        assert str(path) == spec.embedding_production_artifact.path
        assert kwargs == {"expected_sha256": spec.embedding_production_artifact.sha256,
                          "expected_size_bytes": spec.embedding_production_artifact.bytes}
        calls.append("load")
        return load(path, **kwargs)

    def checked_verify(production, records, *, resolver):
        assert calls == ["load"] and tuple(records) == manifest.records
        assert len(production.inputs) > len(records)
        checked = verify(production, records, resolver=resolver)
        calls.append("verified")
        return checked

    @wraps(initialize)
    def checked_initialize(self, *args, **kwargs):
        assert calls == ["load", "verified"] and not Path(spec.output_directory).exists()
        calls.append("model")
        return initialize(self, *args, **kwargs)

    monkeypatch.setattr(ep, "load_embedding_production_receipt", checked_load)
    monkeypatch.setattr(ep.EmbeddingProductionReceipt, "verify_records", checked_verify)
    monkeypatch.setattr(AdaptiveModalAutoencoder, "__init__", checked_initialize)
    receipt = worker.execute_training_job(spec, trainer=_trainer)
    assert calls == ["load", "verified", "model"]
    assert receipt["embedding_production_artifact"] == payload["embedding_production_artifact"]
    assert receipt["embedding_production_verified"] is True
    summary = receipt["embedding_production_verification"]
    assert summary == receipt["corpus_verification"]["embedding_production_verification"]
    assert summary["supplied_records_verified"] == 4
    assert summary["input_count"] == 32 and summary["native_execution_profile"] is True
    assert summary["runtime_cryptographically_attested"] is False
    assert summary["runtime_computation_proven"] is False
    assert summary["source_authority_authenticated"] is False
    assert receipt["execution_mode"] == "injected_test"
    assert receipt["corpus_verification"]["global_holdout_verified"] is False
    assert receipt["admitted"] is receipt["promotion_performed"] is False


@pytest.mark.parametrize("problem,match", [
    ("bytes", "byte identity mismatch"), ("sha256", "byte identity mismatch"),
    ("size", "byte identity mismatch"), ("injected", "native embedding production profile"),
    ("old_provenance", "exact embedding production receipt"),
    ("vector", "source/vector/provenance"), ("input", "source/vector/provenance"),
])
def test_v6_rejects_production_mismatch_before_model_training_and_output(tmp_path, monkeypatch, problem, match):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder

    def transform(row):
        if problem == "old_provenance":
            return replace(row, embedding_provenance=replace(row.embedding_provenance, artifact_sha256="b" * 64))
        if problem == "vector":
            return replace(row, sample=replace(row.sample, embedding_vector=(1.0, -0.0, *([0.0] * 382))))
        if problem == "input":
            return replace(row, sample=replace(row.sample, title="6"))
        return row

    payload, _, _ = _indexed_corpus_job(tmp_path, production=True, record_transform=transform)
    artifact = payload["embedding_production_artifact"]
    path = Path(artifact["path"])
    if problem == "bytes":
        path.write_bytes(path.read_bytes()[:-1])
    elif problem == "sha256":
        artifact["sha256"] = "0" * 64
    elif problem == "size":
        artifact["bytes"] += 1
    elif problem == "injected":
        declared = json.loads(path.read_bytes())
        declared["execution"]["kind"] = "injected_fixture"
        raw = worker._json_bytes(declared)
        path.write_bytes(raw)
        artifact.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))

    def forbidden(*args, **kwargs):
        pytest.fail("invalid production evidence reached model construction or training")

    monkeypatch.setattr(AdaptiveModalAutoencoder, "__init__", forbidden)
    spec = worker.TrainingJobSpec.from_dict(payload)
    with pytest.raises(ValueError, match=match):
        worker.execute_training_job(spec, trainer=forbidden)
    assert not Path(spec.output_directory).exists()


def test_v5_verifies_exact_index_before_model_and_output_without_global_claims(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as ci
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
    payload, index, manifest = _indexed_corpus_job(tmp_path)
    spec = worker.TrainingJobSpec.from_dict(payload)
    assert worker.TrainingJobSpec.from_dict(spec.to_dict()).canonical_sha256 == spec.canonical_sha256
    calls = []
    load_index, verify_batch, initialize = ci.load_corpus_index, ci.CorpusIndex.verify_batch, AdaptiveModalAutoencoder.__init__

    def checked_load(path, **kwargs):
        assert calls == []
        assert not Path(spec.output_directory).exists()
        assert str(path) == payload["corpus_index_artifact"]["path"]
        assert kwargs == {"expected_sha256": index.sha256, "expected_size_bytes": len(index.to_bytes())}
        loaded = load_index(path, **kwargs)
        calls.append("index_loaded")
        return loaded

    def checked_verify(loaded, batch):
        assert calls == ["index_loaded"]
        assert not Path(spec.output_directory).exists()
        result = verify_batch(loaded, batch)
        calls.append("membership_verified")
        return result

    @wraps(initialize)
    def checked_initialize(self, *args, **kwargs):
        assert calls == ["index_loaded", "membership_verified"]
        assert not Path(spec.output_directory).exists()
        calls.append("model_constructed")
        return initialize(self, *args, **kwargs)

    def trainer(model, samples, *, validation_samples, **kwargs):
        assert calls == ["index_loaded", "membership_verified", "model_constructed"]
        assert [sample.text for sample in samples] == [row["text"] for row in payload["samples"]]
        assert [sample.text for sample in validation_samples] == [row["text"] for row in payload["validation_samples"]]
        calls.append("trained")
        return _trainer(model, samples, validation_samples=validation_samples, **kwargs)

    monkeypatch.setattr(ci, "load_corpus_index", checked_load)
    monkeypatch.setattr(ci.CorpusIndex, "verify_batch", checked_verify)
    monkeypatch.setattr(AdaptiveModalAutoencoder, "__init__", checked_initialize)
    receipt = worker.execute_training_job(spec, trainer=trainer)
    assert calls == ["index_loaded", "membership_verified", "model_constructed", "trained"]
    assert receipt["corpus_index_artifact"] == payload["corpus_index_artifact"]
    assert receipt["corpus_selection_sha256"] == index.scope.selection_sha256
    assert receipt["corpus_index_membership_verified"] is True
    verification = receipt["corpus_verification"]
    assert verification["verification_mode"] == "manifest_source_bytes_and_frozen_index"
    summary = verification["corpus_index_verification"]
    assert summary["index_id"] == index.index_id
    assert summary["training_record_ids"] == manifest.to_dict()["split"]["training_record_ids"]
    assert summary["validation_record_ids"] == manifest.to_dict()["split"]["validation_record_ids"]
    assert summary["batch_index_membership_verified"] is True
    assert summary["indexed_partition_disjoint_verified"] is True
    for name in ("global_holdout_verified", "corpus_complete", "source_authority_authenticated",
                 "embedding_producer_authenticated", "semantic_duplicate_isolation_verified",
                 "unseen_checkpoint_lineage_verified", "admitted"):
        assert summary[name] is False
    assert receipt["dataset_and_split_identity_verified"] is True
    assert receipt["heldout_canary_qualified"] is False
    assert receipt["admitted"] is receipt["promotion_performed"] is False


@pytest.mark.parametrize("change,match", [
    ("index_bytes", "SHA-256 mismatch"),
    ("selection", "selection differs"),
    ("forged_summary", "exact frozen index summary"),
    ("mutated_record", "exact frozen index summary"),
])
def test_v5_tampering_fails_before_model_trainer_and_output(tmp_path, monkeypatch, change, match):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
    payload, index, manifest = _indexed_corpus_job(tmp_path, mutate_record=change == "mutated_record")
    if change == "index_bytes":
        path = Path(payload["corpus_index_artifact"]["path"])
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + b" ")
    elif change == "selection":
        payload["corpus_selection_sha256"] = "0" * 64
    elif change == "forged_summary":
        data = index.to_dict()
        record_id = manifest.to_dict()["split"]["training_record_ids"][0]
        next(row for row in data["records"] if row["record_id"] == record_id)["sample_payload_sha256"] = "0" * 64
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        path = tmp_path / "forged.index.json"
        path.write_bytes(raw)
        payload["corpus_index_artifact"] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def forbidden(*args, **kwargs):
        pytest.fail("invalid indexed corpus reached model construction or training")

    monkeypatch.setattr(AdaptiveModalAutoencoder, "__init__", forbidden)
    with pytest.raises(ValueError, match=match):
        worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload), trainer=forbidden)
    assert not Path(payload["output_directory"]).exists()


@pytest.mark.parametrize("batch_split,partition", [
    ("training", "validation"), ("training", "canary"), ("training", "holdout"),
    ("validation", "train"), ("validation", "canary"), ("validation", "holdout"),
])
def test_v5_protected_partition_intrusion_fails_before_model_trainer_and_output(tmp_path, monkeypatch,
                                                                             batch_split, partition):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
    payload, _, _ = _indexed_corpus_job(tmp_path, **{batch_split + "_partition": partition})

    def forbidden(*args, **kwargs):
        pytest.fail("protected indexed record reached model construction or training")

    monkeypatch.setattr(AdaptiveModalAutoencoder, "__init__", forbidden)
    operation = "training" if batch_split == "training" else "hparam_selection"
    with pytest.raises(ValueError, match="protected from " + operation):
        worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload), trainer=forbidden)
    assert not Path(payload["output_directory"]).exists()


def _sparse_trainer(model, samples, *, validation_samples, **kwargs):
    base_identity = model.state.state_identity()
    with model.state.transaction(label="accepted-fixture") as transaction:
        model.state.feature_embedding_weights["existing"][0] += 0.125
    kwargs["accepted_patch_sink"](transaction.patch, {
        "base_state_identity": base_identity,
        "result_state_identity": model.state.state_identity(),
        "base_revision": transaction.patch.base_revision,
        "result_revision": transaction.patch.result_revision,
        "label": "accepted-fixture",
    })
    return {"accepted_epochs": 1, "after": {"legal_ir_target_count": len(samples)}}


def _sparse_job(tmp_path, **updates):
    return _job(tmp_path, schema_version="autoencoder-training-job-v3",
                capture_sparse_patches=True, candidate_storage="sparse", **updates)


def _resolve_receipt_checkpoint(payload, receipt):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import (
        artifact_ref, resolve_checkpoint,
    )
    descriptors = [payload["base_checkpoint"], *payload.get("base_checkpoint_dependencies", ()),
                   receipt["candidate"], *receipt["sparse_patch_segments"]]
    references = {item["sha256"]: item for item in descriptors}
    return resolve_checkpoint(artifact_ref(receipt["candidate"]),
                              resolver=lambda ref: Path(references[ref["sha256"]]["path"]))


@pytest.mark.parametrize("arrow_inputs", [False, True])
def test_indexed_sparse_accepted_patch_preserves_exact_index_and_reconstructs_candidate(tmp_path, arrow_inputs):
    payload, index, _ = _indexed_corpus_job(tmp_path, production=arrow_inputs, arrow_inputs=arrow_inputs)
    payload.update(capture_sparse_patches=True, candidate_storage="sparse")
    spec = worker.TrainingJobSpec.from_dict(payload)
    receipt = worker.execute_training_job(spec, trainer=_sparse_trainer)
    resolved = _resolve_receipt_checkpoint(payload, receipt)
    assert receipt["optimizer_accepted_epochs"] == len(receipt["sparse_patch_segments"]) == 1
    assert receipt["candidate_storage"] == "sparse"
    assert receipt["corpus_index_membership_verified"] is True
    assert receipt["corpus_verification"]["corpus_index_verification"]["index_id"] == index.index_id
    assert receipt["corpus_selection_sha256"] == payload["corpus_selection_sha256"]
    assert resolved.materialized_checkpoint == receipt["candidate_materialized_checkpoint"]
    assert resolved.state.feature_embedding_weights["existing"] == [0.375, -0.5]
    assert not (Path(spec.output_directory) / "candidate.state.json").exists()
    assert {item.name for item in Path(spec.output_directory).iterdir()} == {
        "candidate.manifest.json", "accepted-000000.patch.json", "receipt.json"
    }
    assert receipt["admitted"] is receipt["heldout_canary_qualified"] is False
    if arrow_inputs:
        assert receipt["embedding_input_storage"] == "arrow_mapped_float32"
        assert receipt["arrow_embedding_inputs_verified"] is True


def test_sparse_output_writes_only_manifest_and_segments_with_exact_full_candidate_identity(tmp_path):
    payload = _sparse_job(tmp_path)
    spec = worker.TrainingJobSpec.from_dict(payload)
    receipt = worker.execute_training_job(spec, trainer=_sparse_trainer)
    resolved = _resolve_receipt_checkpoint(payload, receipt)
    full_payload = {**payload, "candidate_storage": "full", "output_directory": str(tmp_path / "full-attempt")}
    full = worker.execute_training_job(worker.TrainingJobSpec.from_dict(full_payload), trainer=_sparse_trainer)
    assert receipt["candidate_storage"] == "sparse"
    assert receipt["candidate_materialized_checkpoint"] == {
        key: full["candidate"][key] for key in ("sha256", "bytes")
    }
    assert resolved.materialized_checkpoint == receipt["candidate_materialized_checkpoint"]
    assert resolved.state.to_json().encode() + b"\n" == Path(full["candidate"]["path"]).read_bytes()
    assert receipt["base_materialized_checkpoint"] == {
        key: payload["base_checkpoint"][key] for key in ("sha256", "bytes")
    }
    assert not (Path(spec.output_directory) / "candidate.state.json").exists()
    assert {item.name for item in Path(spec.output_directory).iterdir()} == {
        "candidate.manifest.json", "accepted-000000.patch.json", "receipt.json"
    }
    assert receipt["candidate_state_identity"]["digest"] == full["candidate_state_identity"]["digest"]
    assert receipt["admitted"] is False


def test_sparse_worker_can_resume_exact_explicit_dependency_closure(tmp_path):
    payload = _sparse_job(tmp_path)
    receipt = worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload), trainer=_sparse_trainer)
    dependencies = [payload["base_checkpoint"], *[
        {key: item[key] for key in ("path", "sha256", "bytes")} for item in receipt["sparse_patch_segments"]
    ]]
    resumed = _sparse_job(tmp_path, base_checkpoint=receipt["candidate"],
                          base_checkpoint_dependencies=dependencies,
                          output_directory=str(tmp_path / "resumed"), base_version_id="version-2")
    spec = worker.TrainingJobSpec.from_dict(resumed)
    assert worker.TrainingJobSpec.from_dict(spec.to_dict()) == spec
    result = worker.execute_training_job(spec, trainer=_sparse_trainer)
    resolved = _resolve_receipt_checkpoint(resumed, result)
    assert resolved.state.feature_embedding_weights["existing"] == [0.5, -0.5]
    assert result["base_checkpoint_chain_depth"] == 1
    assert result["base_materialized_checkpoint"] == receipt["candidate_materialized_checkpoint"]
    assert result["base_state_identity"]["revision"] == 0


@pytest.mark.parametrize("change", ["missing", "extra", "corrupt"])
def test_sparse_worker_rejects_incomplete_or_changed_closure_before_training(tmp_path, change):
    payload = _sparse_job(tmp_path)
    receipt = worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload), trainer=_sparse_trainer)
    dependencies = [payload["base_checkpoint"], *[
        {key: item[key] for key in ("path", "sha256", "bytes")} for item in receipt["sparse_patch_segments"]
    ]]
    if change == "missing":
        dependencies.pop()
    elif change == "extra":
        path = tmp_path / "extra.json"
        path.write_bytes(b"{}")
        dependencies.append({"path": str(path), "sha256": hashlib.sha256(b"{}").hexdigest(), "bytes": 2})
    else:
        Path(dependencies[-1]["path"]).write_bytes(b"{}")
    resumed = _sparse_job(tmp_path, base_checkpoint=receipt["candidate"],
                          base_checkpoint_dependencies=dependencies, output_directory=str(tmp_path / "resumed"))
    with pytest.raises(ValueError):
        worker.execute_training_job(worker.TrainingJobSpec.from_dict(resumed),
                                    trainer=lambda *args, **kwargs: pytest.fail("trained"))
    assert not Path(resumed["output_directory"]).exists()


def test_sparse_worker_zero_accepted_epochs_has_verifiable_empty_manifest(tmp_path):
    payload = _sparse_job(tmp_path)
    receipt = worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload),
                                          trainer=lambda *args, **kwargs: {"accepted_epochs": 0})
    resolved = _resolve_receipt_checkpoint(payload, receipt)
    assert receipt["sparse_patch_segments"] == []
    assert resolved.state.feature_embedding_weights["existing"] == [0.25, -0.5]
    assert not (Path(payload["output_directory"]) / "candidate.state.json").exists()


@pytest.mark.parametrize("bind_to_manifest", [False, True])
def test_sparse_base_arrow_binds_materialized_checkpoint_instead_of_manifest(tmp_path, bind_to_manifest):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import (
        MappedFeatureEmbeddingWeights, build_feature_embedding_weights_ipc,
    )
    payload = _sparse_job(tmp_path)
    receipt = worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload), trainer=_sparse_trainer)
    resolved = _resolve_receipt_checkpoint(payload, receipt)
    arrow_path = tmp_path / "resumed-features.arrow"
    arrow = build_feature_embedding_weights_ipc(resolved.state, arrow_path,
        base_checkpoint_sha256=(receipt["candidate"]["sha256"] if bind_to_manifest else
                                receipt["candidate_materialized_checkpoint"]["sha256"]))
    dependencies = [payload["base_checkpoint"], *[
        {key: item[key] for key in ("path", "sha256", "bytes")} for item in receipt["sparse_patch_segments"]
    ]]
    resumed = _sparse_job(tmp_path, base_checkpoint=receipt["candidate"],
        base_checkpoint_dependencies=dependencies, output_directory=str(tmp_path / "resumed"),
        arrow_feature_weights_artifact={"path": str(arrow_path), "sha256": arrow["sha256"], "bytes": arrow["size_bytes"]})
    def trainer(model, samples, **kwargs):
        assert type(model.state.feature_embedding_weights) is MappedFeatureEmbeddingWeights
        return _sparse_trainer(model, samples, **kwargs)
    if bind_to_manifest:
        with pytest.raises(ValueError):
            worker.execute_training_job(worker.TrainingJobSpec.from_dict(resumed), trainer=trainer)
        assert not Path(resumed["output_directory"]).exists()
    else:
        result = worker.execute_training_job(worker.TrainingJobSpec.from_dict(resumed), trainer=trainer)
        assert result["weight_storage"] == "arrow_cow_feature_embeddings"
        assert result["base_materialized_checkpoint"] == receipt["candidate_materialized_checkpoint"]
        assert _resolve_receipt_checkpoint(resumed, result).state.feature_embedding_weights["existing"] == [0.5, -0.5]


def test_worker_uses_verified_arrow_feature_rows_and_closes_mapping(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import (
        MappedFeatureEmbeddingWeights, build_feature_embedding_weights_ipc,
    )
    payload = _job(tmp_path)
    destination = tmp_path / "features.arrow"
    raw_state = json.loads(Path(payload["base_checkpoint"]["path"]).read_bytes())
    descriptor = build_feature_embedding_weights_ipc(raw_state["feature_embedding_weights"], destination,
                         base_checkpoint_sha256=payload["base_checkpoint"]["sha256"])
    payload["arrow_feature_weights_artifact"] = {"path": str(destination), "sha256": descriptor["sha256"], "bytes": descriptor["size_bytes"]}
    seen = []
    def trainer(model, samples, *, validation_samples, **kwargs):
        assert type(model.state.feature_embedding_weights) is MappedFeatureEmbeddingWeights
        seen.append(model.state.feature_embedding_weights)
        return _trainer(model, samples, validation_samples=validation_samples, **kwargs)
    receipt = worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload), trainer=trainer)
    assert receipt["weight_storage"] == "arrow_cow_feature_embeddings"
    assert receipt["arrow_feature_statistics_before_training"]["overlay_rows"] == 0
    assert receipt["arrow_feature_statistics_after_training"]["overlay_rows"] == 1
    with pytest.raises((ValueError, RuntimeError)):
        seen[0]["existing"]


def _shared_target_spec(tmp_path, monkeypatch, *, artifact_format="json", extra_sample=False):
    from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
    from ipfs_datasets_py.logic.bridge.types import LegalIRDocument
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_target_preparation as preparation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig, build_target_snapshot
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
    payload = _job(tmp_path)
    sample = build_us_code_sample(**payload["samples"][0])
    config = TargetSnapshotConfig(worker.BRIDGE_NAMES, False, 1, {"test": "a" * 64})
    target = LegalIRTrainingTarget(worker.BRIDGE_NAMES,
        LegalIRDocument(document_id=sample.sample_id, source_text=sample.text,
                        normalized_text=sample.normalized_text, source=sample.source),
        losses={"legal_ir_multiview_total_loss": 0.25}, view_distribution={"deontic.ir": 1.0})
    targets = [(sample, target, "ready")]
    if extra_sample:
        other = build_us_code_sample(title="5", section="unselected", text="The officer shall retain records.")
        other_target = LegalIRTrainingTarget(worker.BRIDGE_NAMES,
            LegalIRDocument(document_id=other.sample_id, source_text=other.text,
                            normalized_text=other.normalized_text, source=other.source),
            losses={"legal_ir_multiview_total_loss": 0.75})
        targets.append((other, other_target, "ready"))
    if artifact_format == "bundle":
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import write_target_bundle
        saved = write_target_bundle(tmp_path / "targets.bundle", iter(targets), config=config)
    else:
        snapshot = build_target_snapshot([member for member, _, _ in targets],
                                         {member.sample_id: value for member, value, _ in targets}, config=config)
        saved = snapshot.save(tmp_path / "targets.json")
    payload.update(target_snapshot_id=saved["snapshot_id"],
                   target_snapshot_artifact={key: saved[key] for key in ("path", "sha256", "bytes")})
    monkeypatch.setattr(preparation, "target_snapshot_config", lambda _: config)
    return payload, target


@pytest.mark.parametrize("artifact_format", ["json", "bundle"])
def test_worker_injects_complete_verified_shared_targets(tmp_path, monkeypatch, artifact_format):
    payload, target = _shared_target_spec(tmp_path, monkeypatch, artifact_format=artifact_format, extra_sample=True)
    def trainer(model, samples, *, validation_samples, **kwargs):
        assert kwargs["legal_ir_targets"] == {samples[0].sample_id: target}
        result = model.evaluate(samples, legal_ir_targets=kwargs["legal_ir_targets"], use_sample_memory=False)
        assert result.legal_ir_target_count == 1
        assert result.legal_ir_losses["legal_ir_multiview_total_loss"] == 0.25
        return {"accepted_epochs": 0, "after": result.to_dict()}
    spec = worker.TrainingJobSpec.from_dict(payload)
    assert worker.TrainingJobSpec.from_dict(spec.to_dict()) == spec
    receipt = worker.execute_training_job(spec, trainer=trainer)
    assert receipt["shared_targets_verified"] is True
    assert receipt["shared_target_count"] == 1
    assert receipt["target_snapshot_sample_count"] == 2
    assert receipt["target_snapshot_status_counts"] == {"ready": 2}
    assert receipt["shared_target_status_counts"] == {"ready": 1}
    assert receipt["target_artifact_format"] == artifact_format
    assert receipt["target_artifact_verification_seconds"] > 0
    assert receipt["target_hydration_seconds"] > 0
    if artifact_format == "bundle":
        assert receipt["target_storage_statistics"]["sample_count"] == 2
        assert receipt["target_storage_statistics"]["decompressed_shards"] == 1
        assert receipt["target_storage_statistics"]["unique_decompressed_shards"] == 1
        assert "unrequested target semantics not decoded" in receipt["shared_target_verification_scope"]
    assert receipt["target_snapshot_id"] == payload["target_snapshot_id"]
    assert "no cold target-generation claim" in receipt["cache_observation"]


@pytest.mark.parametrize("change", ["sample", "bytes", "snapshot_id"])
@pytest.mark.parametrize("artifact_format", ["json", "bundle"])
def test_worker_refuses_changed_target_bindings_before_training(tmp_path, monkeypatch, change, artifact_format):
    payload, _ = _shared_target_spec(tmp_path, monkeypatch, artifact_format=artifact_format)
    if change == "sample":
        payload["samples"][0]["citation"] = "different source citation"
    elif change == "bytes":
        Path(payload["target_snapshot_artifact"]["path"]).write_bytes(b"{}")
    else:
        payload["target_snapshot_id"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload),
                                    trainer=lambda *args, **kwargs: pytest.fail("trained on changed targets"))
    assert not Path(payload["output_directory"]).exists()


def test_worker_closes_bundle_on_training_failure(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as bundle
    payload, _ = _shared_target_spec(tmp_path, monkeypatch, artifact_format="bundle")
    loader = bundle.load_target_artifact
    closed = []

    def load(*args, **kwargs):
        snapshot = loader(*args, **kwargs)
        close = snapshot.close
        def tracked_close():
            close()
            closed.append(True)
        monkeypatch.setattr(snapshot, "close", tracked_close)
        return snapshot

    monkeypatch.setattr(bundle, "load_target_artifact", load)
    def fail(*args, **kwargs):
        raise RuntimeError("trainer failure")
    with pytest.raises(RuntimeError, match="trainer failure"):
        worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload), trainer=fail)
    assert closed == [True]
    assert not (Path(payload["output_directory"]) / "receipt.json").exists()


def test_worker_target_descriptor_cannot_raise_artifact_byte_bound(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import DEFAULT_MAX_BYTES
    payload, _ = _shared_target_spec(tmp_path, monkeypatch, artifact_format="bundle")
    payload["target_snapshot_artifact"]["bytes"] = DEFAULT_MAX_BYTES + 1
    with pytest.raises(worker.TrainingJobValidationError, match="exceeds worker byte bound"):
        worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload),
                                    trainer=lambda *a, **k: pytest.fail("oversize targets reached trainer"))
    assert not Path(payload["output_directory"]).exists()


def test_sparse_sink_count_mismatch_cannot_create_receipt(tmp_path):
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, capture_sparse_patches=True))
    with pytest.raises(worker.TrainingJobValidationError, match="captured sparse"):
        worker.execute_training_job(spec, trainer=_trainer)
    assert not (Path(spec.output_directory) / "receipt.json").exists()


@pytest.mark.parametrize("updates,match", [
    ({"typo": True}, "unknown job"),
    ({"variant": {"source_language": "fr"}}, "English"),
    ({"variant": {"unknown": "x"}}, "unknown variant"),
    ({"training_config": {"max_seconds": float("nan")}}, "finite"),
    ({"training_config": {"max_seconds": 0}}, "positive"),
    ({"training_config": {"max_line_search_attempts": 0}}, ">= 1"),
    ({"training_config": {"epochs": True}}, "numeric"),
    ({"training_config": {"use_sample_memory": True}}, "use_sample_memory"),
    ({"training_config": {"legal_ir_evaluate_provers": True}}, "provers"),
    ({"training_config": {"legal_ir_bridge_names": []}}, "bridge names"),
    ({"training_config": {"metric_disk_cache": 1}}, "cache"),
    ({"training_config": {"projection_update_backend": "cuda_resident"}}, "backend"),
    ({"training_config": {"typo": 1}}, "unknown training_config"),
    ({"target_snapshot_id": "missing-artifact"}, "supplied together"),
    ({"schema_version": "autoencoder-training-job-v3", "candidate_storage": "other"}, "candidate_storage"),
    ({"schema_version": "autoencoder-training-job-v3", "candidate_storage": "sparse"}, "capture_sparse_patches"),
    ({"schema_version": "autoencoder-training-job-v2", "candidate_storage": "sparse", "capture_sparse_patches": True}, "v3"),
    ({"base_checkpoint_dependencies": {}}, "array"),
    ({"samples": []}, "must not be empty"),
    ({"samples": [{"title": "5", "section": "1", "text": "x", "embedding_model": "download-me"}]}, "supplied vectors"),
])
def test_job_rejects_unsupported_or_unbounded_configuration(tmp_path, updates, match):
    with pytest.raises(worker.TrainingJobValidationError, match=match):
        worker.TrainingJobSpec.from_dict(_job(tmp_path, **updates))


@pytest.mark.parametrize("change,match", [
    ("duplicate", "duplicate"), ("count", "count"), ("size", "byte bound"), ("aggregate", "aggregate"),
])
def test_sparse_base_descriptors_are_bounded_before_loading(tmp_path, change, match):
    payload = _sparse_job(tmp_path)
    base = payload["base_checkpoint"]
    if change == "duplicate":
        dependencies = [base]
    elif change == "count":
        dependencies = [{**base, "sha256": f"{index:064x}"} for index in range(worker.MAX_BASE_DEPENDENCIES + 1)]
    elif change == "size":
        dependencies = [{**base, "sha256": "0" * 64, "bytes": worker.MAX_CHECKPOINT_BYTES + 1}]
    else:
        dependencies = [{**base, "sha256": f"{index:064x}", "bytes": worker.MAX_CHECKPOINT_BYTES} for index in range(9)]
    payload["base_checkpoint_dependencies"] = dependencies
    with pytest.raises(worker.TrainingJobValidationError, match=match):
        worker.TrainingJobSpec.from_dict(payload)


def test_hash_mismatch_fails_before_training_and_output_creation(tmp_path):
    payload = _job(tmp_path)
    payload["base_checkpoint"]["sha256"] = "0" * 64
    spec = worker.TrainingJobSpec.from_dict(payload)
    with pytest.raises(worker.TrainingJobValidationError, match="SHA-256 mismatch"):
        worker.execute_training_job(spec, trainer=lambda *args, **kwargs: pytest.fail("trained"))
    assert not Path(spec.output_directory).exists()


def test_tree_pin_failure_precedes_model_or_artifact_load(tmp_path, monkeypatch):
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path))
    Path(spec.base_checkpoint.path).unlink()

    def drift():
        raise RuntimeError("parser resolved to HACC")

    monkeypatch.setattr(worker, "_require_tree_pin", drift)
    with pytest.raises(RuntimeError, match="HACC"):
        worker.execute_training_job(spec, trainer=_trainer)
    assert not Path(spec.output_directory).exists()


def test_real_tree_pin_rejects_an_already_loaded_drifted_parser(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.autoformal.tree_pin import LogicTreePinError
    from ipfs_datasets_py.logic.deontic.utils import deontic_parser

    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path))
    monkeypatch.setattr(deontic_parser, "__file__", "/home/barberb/HACC/drifted/deontic_parser.py")
    with pytest.raises(LogicTreePinError, match="Resolved outside"):
        worker.execute_training_job(spec, trainer=lambda *args, **kwargs: pytest.fail("trained"))
    assert not Path(spec.output_directory).exists()


def test_existing_output_is_never_overwritten(tmp_path):
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path))
    Path(spec.output_directory).mkdir()
    marker = Path(spec.output_directory) / "candidate.state.json"
    marker.write_text("protected")
    with pytest.raises(FileExistsError):
        worker.execute_training_job(spec, trainer=lambda *args, **kwargs: pytest.fail("trained"))
    assert marker.read_text() == "protected"


def test_unknown_constructor_config_rejected_before_output(tmp_path):
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, autoencoder_config={"hidden_fallback": True}))
    with pytest.raises(worker.TrainingJobValidationError, match="autoencoder_config"):
        worker.execute_training_job(spec, trainer=_trainer)
    assert not Path(spec.output_directory).exists()


def test_job_file_identity_distinguishes_bytes_from_canonical_spec(tmp_path):
    payload = _job(tmp_path)
    path = tmp_path / "job.json"
    raw = json.dumps(payload, indent=2).encode()
    path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    with pytest.raises(worker.TrainingJobValidationError, match="job file"):
        worker.execute_training_job_file(path, "0" * 64, trainer=_trainer)
    receipt = worker.execute_training_job_file(path, sha, trainer=_trainer)
    assert receipt["job_file_sha256"] == sha
    assert receipt["job_spec_canonical_sha256"] != sha


@pytest.mark.parametrize("raw", [b'{"job_id":"a","job_id":"b"}', b'{"max_seconds":NaN}'])
def test_job_json_rejects_ambiguous_or_nonfinite_fields(tmp_path, raw):
    path = tmp_path / "job.json"
    path.write_bytes(raw)
    with pytest.raises(worker.TrainingJobValidationError):
        worker.execute_training_job_file(path, hashlib.sha256(raw).hexdigest(), trainer=_trainer)


def test_distinct_holdout_and_overlap_are_explicit(tmp_path):
    train = {"title": "5", "section": "1", "text": "The agency shall retain records."}
    other = {"title": "5", "section": "2", "text": "The agency shall publish notice."}
    duplicated_text = {**train, "section": "99"}
    for index, (validation, expected) in enumerate([([train], "in_sample"), ([other], "holdout"), ([train, other], "overlapping"), ([duplicated_text], "in_sample")]):
        spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, validation_samples=validation,
                                                    output_directory=str(tmp_path / f"attempt-{index}")))
        receipt = worker.execute_training_job(spec, trainer=_trainer)
        assert receipt["validation_mode"] == expected


def test_failed_attempt_stays_separate_and_cannot_be_reused(tmp_path):
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path))

    def fail(model, *args, **kwargs):
        model.state.feature_embedding_weights["existing"][0] = 99
        raise RuntimeError("interrupted training")

    raw = Path(spec.base_checkpoint.path).read_bytes()
    with pytest.raises(RuntimeError, match="interrupted"):
        worker.execute_training_job(spec, trainer=fail)
    assert Path(spec.base_checkpoint.path).read_bytes() == raw
    assert not (Path(spec.output_directory) / "receipt.json").exists()
    with pytest.raises(FileExistsError):
        worker.execute_training_job(spec, trainer=_trainer)


def test_spawned_workers_share_only_immutable_artifact(tmp_path):
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    specs = [worker.TrainingJobSpec.from_dict(_job(tmp_path, job_id=f"job-{index}",
                output_directory=str(tmp_path / f"worker-{index}"))) for index in range(2)]
    original = Path(specs[0].base_checkpoint.path).read_bytes()
    processes = [context.Process(target=_spawn_entry, args=(spec, results)) for spec in specs]
    try:
        for process in processes:
            process.start()
        receipts = [results.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(timeout=30)
            assert process.exitcode == 0
        assert all(not receipt["error"] for receipt in receipts), receipts
        assert len({receipt["pid"] for receipt in receipts}) == 2
        assert receipts[0]["base_state_identity"] == receipts[1]["base_state_identity"]
        assert receipts[0]["candidate"]["path"] != receipts[1]["candidate"]["path"]
        assert Path(specs[0].base_checkpoint.path).read_bytes() == original
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()


def _source_manifest():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_samples, modal_autoencoder

    paths = {**worker._require_tree_pin(), "autoencoder": modal_autoencoder.__file__,
             "samples": legal_samples.__file__, "worker": worker.__file__}
    return {name: hashlib.sha256(Path(path).read_bytes()).hexdigest() for name, path in paths.items()}


def test_expected_source_manifest_is_verified_and_bound_to_receipt(tmp_path):
    expected = _source_manifest()
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, expected_source_sha256=expected))
    receipt = worker.execute_training_job(spec, trainer=_trainer)
    assert receipt["source_manifest_verified"] is True
    assert receipt["tree_file_sha256"] == expected
    assert receipt["worker_source_sha256"] == expected["worker"]
    assert receipt["caller_identity_labels_verified"] is False
    assert "not bytecode-attested" in receipt["source_verification_scope"]


def test_expected_source_mismatch_stops_before_training(tmp_path):
    expected = {**_source_manifest(), "worker": "0" * 64}
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, expected_source_sha256=expected))
    with pytest.raises(worker.TrainingJobValidationError, match="source manifest"):
        worker.execute_training_job(spec, trainer=lambda *args, **kwargs: pytest.fail("trained"))
    assert not Path(spec.output_directory).exists()


def test_resident_worker_requires_fresh_process_after_source_change(tmp_path, monkeypatch):
    expected = _source_manifest()
    monkeypatch.setattr(worker, "_PROCESS_SOURCE_HASHES", {**expected, "autoencoder": "0" * 64})
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, expected_source_sha256=expected))
    with pytest.raises(worker.TrainingJobValidationError, match="fresh worker process"):
        worker.execute_training_job(spec, trainer=lambda *args, **kwargs: pytest.fail("trained"))


def test_profiler_is_explicit_runtime_argument_not_job_json_object(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.projection_profiler import ProjectionProfiler

    def profiled(model, samples, **kwargs):
        assert isinstance(kwargs["projection_profiler"], ProjectionProfiler)
        assert "profile_projection" not in kwargs
        return _trainer(model, samples, **kwargs)

    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, training_config={"profile_projection": True}))
    receipt = worker.execute_training_job(spec, trainer=profiled)
    assert receipt["profile_projection"] is True
