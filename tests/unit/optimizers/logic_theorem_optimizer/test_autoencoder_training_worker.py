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


@pytest.mark.parametrize("mode", ["guarded_adaptive", "productive_adaptive"])
def test_adaptive_optimizer_opt_in_preserves_archived_default_job_identity(tmp_path, mode):
    original = worker.TrainingJobSpec.from_dict(_job(tmp_path))
    archived = original.to_dict()
    assert "projection_optimizer_mode" not in archived["training_config"]
    assert "projection_momentum" not in archived["training_config"]
    explicit = {**archived, "training_config": {**archived["training_config"],
        "projection_optimizer_mode": "fixed", "projection_momentum": 0.0}}
    restored = worker.TrainingJobSpec.from_dict(explicit)
    assert restored.canonical_sha256 == original.canonical_sha256
    assert restored.training_config.projection_kwargs() == original.training_config.projection_kwargs()
    with_validation = worker.TrainingJobSpec.from_dict({**archived, "validation_samples": [
        {"title": "5", "section": "2", "text": "The officer shall file reports."}]})
    adaptive = worker.TrainingJobSpec.from_dict({**with_validation.to_dict(), "training_config": {
        **archived["training_config"], "projection_optimizer_mode": mode,
        "projection_momentum": 0.5, "epochs": 3, "max_line_search_attempts": 2}})
    assert adaptive.canonical_sha256 != with_validation.canonical_sha256
    assert adaptive.training_config.projection_kwargs()["projection_optimizer_mode"] == mode
    assert adaptive.training_config.projection_kwargs()["projection_momentum"] == 0.5
    assert worker.TrainingJobSpec.from_dict(adaptive.to_dict()).canonical_sha256 == adaptive.canonical_sha256


@pytest.mark.parametrize("updates,reason", [
    ({"projection_optimizer_mode": "adam"}, "optimizer_mode"),
    ({"projection_optimizer_mode": True}, "optimizer_mode"),
    ({"projection_momentum": True}, "numeric"),
    ({"projection_momentum": -0.1}, "finite"),
    ({"projection_momentum": 1.0}, "within"),
    ({"projection_momentum": float("nan")}, "finite"),
    ({"projection_momentum": float("inf")}, "finite"),
    ({"projection_momentum": 0.5}, "requires guarded_adaptive"),
    ({"projection_optimizer_mode": "guarded_adaptive", "projection_momentum": 0.5}, "two line search"),
    ({"projection_optimizer_mode": "guarded_adaptive", "l2_regularization": 0.1}, "zero l2"),
    ({"projection_optimizer_mode": "guarded_adaptive", "max_seconds": 301}, "max_seconds"),
    ({"projection_optimizer_mode": "guarded_adaptive", "epochs": 33}, "epochs"),
    ({"projection_optimizer_mode": "guarded_adaptive", "max_line_search_attempts": 11}, "attempts"),
    ({"projection_optimizer_mode": "guarded_adaptive", "learning_rate": 1.1}, "learning_rate"),
])
def test_adaptive_optimizer_worker_configuration_bounds(updates, reason):
    with pytest.raises(worker.TrainingJobValidationError, match=reason):
        worker.TrainingConfig(**updates)


def test_new_adaptive_bounds_do_not_reinterpret_archived_fixed_mode():
    config = worker.TrainingConfig(epochs=40, max_line_search_attempts=12, learning_rate=1.2, max_seconds=400)
    assert config.projection_optimizer_mode == "fixed"
    assert config.to_dict()["epochs"] == 40
    assert "projection_optimizer_mode" not in config.to_dict()


@pytest.mark.parametrize("validation", [[], [{"title": "6", "section": "2", "text": " THE AGENCY SHALL   RETAIN RECORDS. "}]])
@pytest.mark.parametrize("mode", ["guarded_adaptive", "productive_adaptive"])
def test_adaptive_optimizer_requires_disjoint_validation_before_worker(tmp_path, validation, mode):
    with pytest.raises(worker.TrainingJobValidationError, match="disjoint"):
        worker.TrainingJobSpec.from_dict(_job(tmp_path, validation_samples=validation,
            training_config={"projection_optimizer_mode": mode, "max_line_search_attempts": 2}))


@pytest.mark.parametrize("mode,momentum", [("guarded_adaptive", 0.5), ("productive_adaptive", 0.0), ("productive_adaptive", 0.5)])
def test_worker_forwards_job_local_adaptive_settings_without_optimizer_checkpoint_state(tmp_path, mode, momentum):
    calls = []
    def trainer(model, samples, *, validation_samples, **kwargs):
        calls.append(kwargs)
        assert kwargs["epochs"] == 3
        assert kwargs["learning_rate"] == 0.25
        assert kwargs["max_line_search_attempts"] == 2
        assert kwargs["projection_optimizer_mode"] == mode
        assert kwargs["projection_momentum"] == momentum
        return {"accepted_epochs": 0, "stopped_reason": "injected configuration test"}
    spec = worker.TrainingJobSpec.from_dict(_job(tmp_path, validation_samples=[
        {"title": "5", "section": "2", "text": "The officer shall file reports."}],
        training_config={"epochs": 3, "learning_rate": 0.25, "max_line_search_attempts": 2,
            "projection_optimizer_mode": mode, "projection_momentum": momentum}))
    original = Path(spec.base_checkpoint.path).read_bytes()
    receipt = worker.execute_training_job(spec, trainer=trainer)
    assert len(calls) == 1
    assert receipt["projection_optimizer_scope"] == "job_local_reset_per_training_call"
    assert receipt["optimizer_history_persisted"] is False
    assert receipt["optimizer_accepted_epochs"] == 0
    assert Path(spec.base_checkpoint.path).read_bytes() == original
    candidate = json.loads(Path(receipt["candidate"]["path"]).read_bytes())
    assert not any("momentum" in key or "optimizer" in key for key in candidate)


@pytest.mark.parametrize("updates,reason", [
    ({"max_line_search_attempts": 1}, "two line search"),
    ({"epochs": 33}, "epochs"),
    ({"max_line_search_attempts": 11}, "attempts"),
    ({"learning_rate": 1.1}, "learning_rate"),
    ({"max_seconds": 301}, "max_seconds"),
    ({"l2_regularization": 0.1}, "zero l2"),
    ({"projection_momentum": float("nan")}, "finite"),
])
def test_productive_optimizer_preserves_adaptive_bounds_and_requires_exploration_budget(updates, reason):
    config = {"projection_optimizer_mode": "productive_adaptive", "max_line_search_attempts": 2, **updates}
    with pytest.raises(worker.TrainingJobValidationError, match=reason):
        worker.TrainingConfig(**config)


def test_productive_optimizer_is_a_distinct_resume_identity(tmp_path):
    common = _job(tmp_path, validation_samples=[
        {"title": "5", "section": "2", "text": "The officer shall file reports."}],
        training_config={"max_line_search_attempts": 2, "projection_optimizer_mode": "guarded_adaptive"})
    guarded = worker.TrainingJobSpec.from_dict(common)
    productive = worker.TrainingJobSpec.from_dict({**common, "training_config": {
        **common["training_config"], "projection_optimizer_mode": "productive_adaptive"}})
    assert productive.canonical_sha256 != guarded.canonical_sha256
    assert worker.TrainingJobSpec.from_dict(productive.to_dict()).canonical_sha256 == productive.canonical_sha256
    assert productive.training_config.projection_kwargs()["projection_momentum"] == 0.0


def _reviewed_fixed_byte_pipeline(tokenizer):
    """Actual complete byte/config/code fixture identity, with no asset claim."""
    mapping = list(tokenizer.byte_to_id)
    if len(mapping) != 256 or len(set(mapping)) != 256 or any(type(value) is not int for value in mapping):
        raise ValueError("fixed fixture requires complete actual byte mapping")
    payload = {"schema": "reviewed-decoder-tokenizer-pipeline/v1", "kind": "fictional_fixed_byte",
        "backend": {"type": "fixed_utf8_byte", "byte_to_id": mapping, "added_tokens": []},
        "frontend": {"encoding": "utf-8", "errors": "strict", "configuration": dict(tokenizer.frontend_config),
            "bos_token_id": tokenizer.bos_token_id, "eos_token_id": tokenizer.eos_token_id,
            "vocab_size": tokenizer.vocab_size,
            "methods": {name: worker._reviewed_tokenizer_method(getattr(tokenizer, name))
                        for name in ("encode", "decode", "pipeline_serialization")}},
        "implementation": [worker._reviewed_tokenizer_implementation_file(Path(__file__).resolve())],
        "transport": {"body_only": True, "truncation": False, "padding": False}}
    return worker._json_bytes(payload)


class _CompleteReviewedByteTokenizer:
    """Fixed byte transport fixture, never a pretrained tokenizer claim."""
    bos_token_id = 256
    eos_token_id = 257
    vocab_size = 258

    def __init__(self):
        self.byte_to_id = list(range(256))
        self.frontend_config = {"normalizer": "identity", "cleanup": False}

    def encode(self, value):
        if self.frontend_config["normalizer"] == "lowercase":
            value = value.lower()
        return [self.byte_to_id[item] for item in value.encode("utf-8")]

    def decode(self, token_ids):
        inverse = {value: index for index, value in enumerate(self.byte_to_id)}
        return bytes(inverse[value] for value in token_ids).decode("utf-8")

    def pipeline_serialization(self):
        return _reviewed_fixed_byte_pipeline(self)


class _CompleteReviewedSGDBackend:
    """Real analytic softmax updates over every target token; fixture only.

    This tiny source-conditioned unigram cannot establish formalization quality.
    It exercises numerical calls, state transport and exact interruption/resume.
    The new worker is not tested by returning an opaque 'trained=True' flag.
    """
    def __init__(self):
        self.weights = [0.0] * 258
        self.velocity = [0.0] * 258
        self.steps = 0
        self.calls = 0
        self.restores = 0
        self.validations = 0
        self.seen = []
        self.after_update = None

    def identity(self):
        return {"backend_id": "fixture:complete-reviewed-analytic-softmax-sgd/v1",
            "implementation_sha256": "3" * 64, "checkpoint_format": "fixture:finite-softmax-and-momentum-json/v1",
            "target_codec": "complete-reviewed-norm-json/v2", "source_conditioned": True, "pretrained": False}

    def validate_training_records(self, records, *, max_source_tokens, max_target_tokens):
        self.validations += 1
        assert records and all(0 < len(row["source_token_ids"]) <= max_source_tokens and
            0 < len(row["target_token_ids"]) <= max_target_tokens for row in records)
        assert all(set(json.loads(row["target_json"])) == {
            "profile", "typed_expression", "argument_roles", "assumptions", "governing_context",
            "interpretation_id", "source_binding", "definition_uses", "cross_references"} for row in records)

    def inspect_checkpoint(self, model_state, optimizer_state):
        import math
        model, optimizer = json.loads(model_state), json.loads(optimizer_state)
        assert set(model) == {"weights"} and set(optimizer) == {"velocity", "steps"}
        assert len(model["weights"]) == len(optimizer["velocity"]) == 258
        assert all(type(value) in (int, float) and math.isfinite(value)
                   for value in [*model["weights"], *optimizer["velocity"]])
        assert type(optimizer["steps"]) is int and optimizer["steps"] >= 0
        return {"optimizer_steps": optimizer["steps"]}

    def restore_checkpoint(self, model_state, optimizer_state):
        self.inspect_checkpoint(model_state, optimizer_state)
        self.weights = json.loads(model_state)["weights"]
        optimizer = json.loads(optimizer_state)
        self.velocity, self.steps = optimizer["velocity"], optimizer["steps"]
        self.restores += 1

    def restored_checkpoint_matches(self, model_state, optimizer_state):
        return (json.loads(model_state) == {"weights": self.weights} and
                json.loads(optimizer_state) == {"velocity": self.velocity, "steps": self.steps})

    def train_batch(self, records):
        import copy
        import math
        self.seen.append(copy.deepcopy(records))
        gradient = [0.0] * 258
        loss = 0.0
        for row in records:
            # Every byte of all nine target fields contributes to the objective.
            scale = (sum(row["source_token_ids"]) % 11 + 1) / 11
            scores = [value * scale for value in self.weights]
            largest = max(scores)
            masses = [math.exp(value - largest) for value in scores]
            denominator = sum(masses)
            probabilities = [value / denominator for value in masses]
            target_ids = row["target_token_ids"]
            counts = [target_ids.count(index) / len(target_ids) for index in range(258)]
            loss -= sum(count * math.log(probability) for count, probability in zip(counts, probabilities)) / len(records)
            for index in range(258):
                gradient[index] += scale * (probabilities[index] - counts[index]) / len(records)
        for index in range(258):
            self.velocity[index] = 0.5 * self.velocity[index] + gradient[index]
            self.weights[index] -= 0.01 * self.velocity[index]
        self.steps += 1
        self.calls += 1
        if self.after_update:
            self.after_update()
        return {"loss": loss, "gradient_norm": math.sqrt(sum(value * value for value in gradient)),
                "optimizer_steps": self.steps}

    def snapshot_checkpoint(self):
        return {"model_state": worker._json_bytes({"weights": self.weights}),
                "optimizer_state": worker._json_bytes({"velocity": self.velocity, "steps": self.steps})}


def _complete_reviewed_artifact(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _complete_reviewed_worker_fixture(tmp_path, *, known_interpretation_id="fixture:act-v1/selected-interpretation",
                                      batch_size=1):
    from copy import deepcopy
    from types import SimpleNamespace
    from tests.unit.logic import test_autoformal_campaign_training_inputs as fixtures
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as cycle_inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_eval_splits as splits
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    data = fixtures._reviewed_transition_fixture(tmp_path)
    registry = fixtures._ReviewedArtifactRegistry(tmp_path / "reviewed-registry")
    stage_options = fixtures._reviewed_stage_options(data, tmp_path / "reviewed-stage")
    # Preserve an independent heldout history without offering its labels to fit.
    heldout = {"id": "fixture:independent-heldout", "source_text": "A ceramicist decorates an azure vase."}
    example = splits.LegalIRSplitExample.from_sample(heldout)
    frozen = splits.LegalIRSplitManifest(examples=(example,), assignments={example.sample_id: "holdout"},
        config_digest=splits.LegalIREvalSplitConfig(**data.config).digest).to_dict()
    stage_options["history"]["scope_kind"] = "complete_declared_history"
    stage_options["history"]["split_manifests"].append({"manifest": frozen, "sha256": data.fixtures.digest(frozen)})
    stage_options["history"]["records"].append({"id": heldout["id"], "source_text": heldout["source_text"],
        "source_sha256": data.fixtures.source_digest(heldout["source_text"]),
        "split_example": example.to_dict(), "assignment": "holdout"})
    stage_options["expected_history_sha256"] = data.fixtures.digest(stage_options["history"])
    stage = cycle_inputs.stage_reviewed_cycle_inputs(registry, **stage_options)
    exposure = _complete_reviewed_artifact(tmp_path / "reviewed-exposure.json", worker._json_bytes(data.options["exposure_records"]))
    contexts = {"profile": "reviewed-source-selection-context/v2",
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": known_interpretation_id, "selection_mode": "identifier_only"}, "rows": [{"id": row["id"], "unit_id": row["unit_id"],
        "governing_context": deepcopy(row["canonical_ir"]["governing_context"]),
        "source_binding": deepcopy(row["canonical_ir"]["source_binding"])} for row in data.rows]}
    context_ref = _complete_reviewed_artifact(tmp_path / "reviewed-source-contexts.json", worker._json_bytes(contexts))
    backend = _CompleteReviewedSGDBackend()
    snapshot = backend.snapshot_checkpoint()
    model = _complete_reviewed_artifact(tmp_path / "initial-model.json", snapshot["model_state"])
    optimizer = _complete_reviewed_artifact(tmp_path / "initial-optimizer.json", snapshot["optimizer_state"])
    tokenizer_asset = _complete_reviewed_artifact(tmp_path / "fixture-tokenizer.json",
        worker._json_bytes({"fixture": "fixed-UTF8-byte-alphabet", "pretrained": False}))
    license_asset = _complete_reviewed_artifact(tmp_path / "fixture-license.json",
        worker._json_bytes({"fixture_only": True, "real_model_license_verification": "unprovided"}))
    pins = worker._reviewed_decoder_source_pins()
    tokenizer = _CompleteReviewedByteTokenizer()
    budget = {"max_source_tokens": 8192, "max_target_tokens": 32768,
        "tokenizer_contract": cycle_inputs._reviewed_decoder_tokenizer_contract(tokenizer)}
    parent = {"schema": worker.REVIEWED_DECODER_CHECKPOINT_SCHEMA, "checkpoint_lineage_id": "fixture:complete-ir-model-lineage",
        "base_version_id": "fixture:initial-model-version", "backend_identity": backend.identity(),
        "assets": [model, tokenizer_asset, license_asset], "training_binding": None,
        "model_state": model, "optimizer_state": optimizer,
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "batch_size": batch_size, "seed": 1729, "token_budgets": budget,
        "parent_checkpoint_sha256": None, "producer_pins": pins, "qualified": False, "promotion_performed": False}
    parent_ref = _complete_reviewed_artifact(tmp_path / "initial-paired-manifest.json", worker._json_bytes(parent))
    payload = {"schema_version": worker.REVIEWED_DECODER_SCHEMA_VERSION, "job_id": "fixture:reviewed-job",
        "run_id": "fixture:reviewed-run", "base_version_id": parent["base_version_id"],
        "checkpoint_lineage_id": parent["checkpoint_lineage_id"], "output_directory": str(tmp_path / "reviewed-output"),
        "code_identity": "fixture:independently-supplied-current-source-set", "stage_artifact": stage,
        "exposure_artifact": exposure, "source_contexts_artifact": context_ref,
        "model_artifact": model, "tokenizer_artifact": tokenizer_asset, "license_artifact": license_asset,
        "base_model_checkpoint": model, "base_optimizer_checkpoint": optimizer, "parent_checkpoint_artifact": parent_ref,
        "expected_admission_inputs_sha256": consumer.reviewed_admission_inputs_sha256(data.options["admission_inputs"]),
        "split_config": data.config, "expected_split_config_sha256": data.fixtures.digest(data.config),
        "backend_identity": backend.identity(), "expected_source_sha256": pins,
        "max_source_tokens": 8192, "max_target_tokens": 32768, "batch_size": batch_size,
        "max_steps": 1, "max_seconds": 30, "seed": 1729, "allow_fictional_fixture": True}
    guards = []
    def current_admission():
        return data.fixtures.reviewed_public_admission_inputs(data.helper, data.admission, data.case)
    def execution_guard():
        guards.append("fixture existing owner check only; not a genuine resource grant")
    def asset_guard(spec):
        assert spec["backend_identity"]["pretrained"] is False and spec["allow_fictional_fixture"] is True
        guards.append("fictional asset policy fixture; no real model license approval")
    runtime = worker.ReviewedDecoderRuntime(registry, backend, tokenizer,
        current_admission, execution_guard, asset_guard)
    return SimpleNamespace(payload=payload, runtime=runtime, backend=backend, registry=registry,
        data=data, inputs=cycle_inputs, fixtures=fixtures, guards=guards, heldout=heldout, contexts=contexts)


def test_reviewed_decoder_job_file_dispatch_preserves_complete_target_and_updates_checkpoint_pair(tmp_path, monkeypatch):
    fixture = _complete_reviewed_worker_fixture(tmp_path)
    spec = worker.TrainingJobSpec.from_dict(fixture.payload)
    assert type(spec) is worker.ReviewedDecoderTrainingJobSpec
    assert worker.TrainingJobSpec.from_dict(spec.to_dict()).canonical_sha256 == spec.canonical_sha256
    # The maintained _execute entry must choose the new branch before legacy
    # tree/model/sample conversion, not through a separate unreachable path.
    monkeypatch.setattr(worker, "_require_tree_pin", lambda: pytest.fail("legacy model path reached"))
    path = tmp_path / "complete-reviewed-job.json"
    raw = worker._json_bytes(spec.to_dict())
    path.write_bytes(raw)
    receipt = worker.execute_training_job_file(path, hashlib.sha256(raw).hexdigest(), reviewed_runtime=fixture.runtime)
    assert receipt["backend_train_batch_calls"] == receipt["backend_restore_calls"] == 1
    assert fixture.backend.validations == fixture.backend.calls == fixture.backend.restores == 1
    assert receipt["model_bytes_changed"] is receipt["optimizer_bytes_changed"] is True
    assert all(value is False for key, value in receipt.items() if key in {
        "qualified", "admitted", "promotion_performed", "corpus_admitted", "legal_meaning_verified",
        "source_fidelity_proved", "convergence_proved", "physical_model_assets_verified",
        "numerical_update_independently_verified", "optimizer_resume_independently_verified"})
    rows = {row["id"]: row for row in fixture.data.rows}
    for batch in fixture.backend.seen:
        for record in batch:
            assert json.loads(record["target_json"]) == rows[record["id"]]["canonical_ir"]
            assert fixture.heldout["id"] != record["id"]
            assert fixture.heldout["source_text"] not in json.dumps(record)
            source = json.loads(record["source_wire"])
            assert set(source) == {"profile", "source_text", "governing_context", "source_binding", "selection_context"}
            assert "typed_expression" not in source and "definition_uses" not in source
    manifest = json.loads(Path(receipt["candidate"]["path"]).read_bytes())
    assert manifest["model_state"] == receipt["model_checkpoint"]
    assert manifest["optimizer_state"] == receipt["optimizer_checkpoint"]
    assert manifest["parent_checkpoint_sha256"] == fixture.payload["parent_checkpoint_artifact"]["sha256"]
    assert receipt["complete_training_binding"]["fixture_only"] is True
    assert receipt["complete_training_binding"]["production_training_eligible"] is False


def test_reviewed_decoder_exact_resume_matches_uninterrupted_numeric_fixture(tmp_path):
    fixture = _complete_reviewed_worker_fixture(tmp_path)
    whole = worker.TrainingJobSpec.from_dict({**fixture.payload, "max_steps": 2,
        "output_directory": str(tmp_path / "uninterrupted")})
    a = worker.execute_training_job(whole, reviewed_runtime=fixture.runtime)
    first_backend = _CompleteReviewedSGDBackend()
    first_runtime = replace(fixture.runtime, backend=first_backend)
    first = worker.execute_training_job(worker.TrainingJobSpec.from_dict({**fixture.payload,
        "output_directory": str(tmp_path / "interrupted")}), reviewed_runtime=first_runtime)
    second_backend = _CompleteReviewedSGDBackend()
    second_runtime = replace(fixture.runtime, backend=second_backend)
    resumed = worker.TrainingJobSpec.from_dict({**fixture.payload, "job_id": "fixture:resume-job",
        "output_directory": str(tmp_path / "resumed"), "base_model_checkpoint": first["model_checkpoint"],
        "base_optimizer_checkpoint": first["optimizer_checkpoint"], "parent_checkpoint_artifact": first["candidate"]})
    b = worker.execute_training_job(resumed, reviewed_runtime=second_runtime)
    assert Path(a["model_checkpoint"]["path"]).read_bytes() == Path(b["model_checkpoint"]["path"]).read_bytes()
    assert Path(a["optimizer_checkpoint"]["path"]).read_bytes() == Path(b["optimizer_checkpoint"]["path"]).read_bytes()
    assert b["worker_progress"] == a["worker_progress"]
    assert b["initial_progress"]["optimizer_steps"] == 1
    assert b["optimizer_resume_independently_verified"] is False  # fixture is not a pretrained result


@pytest.mark.parametrize("damage", ["no_runtime", "legacy_trainer", "budget", "truncating_tokenizer",
    "source_context_loss", "paired_model_swap", "wrong_backend", "resource_guard", "asset_policy"])
def test_reviewed_decoder_refuses_before_backend_restore_or_fit(tmp_path, damage):
    fixture = _complete_reviewed_worker_fixture(tmp_path)
    payload, runtime = dict(fixture.payload), fixture.runtime
    extra = {}
    if damage == "no_runtime": runtime = None
    elif damage == "legacy_trainer": extra["trainer"] = lambda *args, **kwargs: pytest.fail("legacy fit")
    elif damage == "budget": payload["max_target_tokens"] = 3
    elif damage == "truncating_tokenizer":
        class Truncating(_CompleteReviewedByteTokenizer):
            def encode(self, value): return super().encode(value)[:-1]
        runtime = replace(runtime, tokenizer=Truncating())
    elif damage == "source_context_loss":
        value = json.loads(Path(payload["source_contexts_artifact"]["path"]).read_bytes())
        value["rows"][0]["governing_context"].pop("legal_as_of_utc")
        payload["source_contexts_artifact"] = _complete_reviewed_artifact(tmp_path / "damaged-context.json", worker._json_bytes(value))
    elif damage == "paired_model_swap":
        value = {"weights": [0.25] * 258}
        payload["base_model_checkpoint"] = _complete_reviewed_artifact(tmp_path / "other-model.json", worker._json_bytes(value))
    elif damage == "wrong_backend":
        payload["backend_identity"] = {**payload["backend_identity"], "backend_id": "fixture:another-backend"}
    elif damage == "resource_guard":
        def refused(): raise ValueError("existing owner refused")
        runtime = replace(runtime, execution_guard=refused)
    else:
        def denied(spec): raise ValueError("model use not licensed by supplied policy")
        runtime = replace(runtime, asset_policy_guard=denied)
    spec = worker.TrainingJobSpec.from_dict(payload)
    with pytest.raises(ValueError):
        worker.execute_training_job(spec, reviewed_runtime=runtime, **extra)
    assert fixture.backend.calls == fixture.backend.restores == 0
    assert not Path(spec.output_directory).exists()


def test_reviewed_decoder_current_revocation_after_update_preserves_unpromoted_failure(tmp_path):
    fixture = _complete_reviewed_worker_fixture(tmp_path)
    def revoke():
        fixture.data.case["registry"]["keys"][0]["revoked_at_utc"] = fixture.data.helper.EVALUATED
        fixture.data.helper.reviewed_resign_v2(fixture.data.case)
    fixture.backend.after_update = revoke
    spec = worker.TrainingJobSpec.from_dict(fixture.payload)
    with pytest.raises(ValueError):
        worker.execute_training_job(spec, reviewed_runtime=fixture.runtime)
    assert fixture.backend.calls == 1 and fixture.backend.steps == 1
    failure = json.loads((Path(spec.output_directory) / "failure.json").read_bytes())
    assert failure["caller_owned_backend_may_have_changed"] is True
    assert failure["qualified"] is failure["promotion_performed"] is False
    assert not (Path(spec.output_directory) / "receipt.json").exists()
    assert not (Path(spec.output_directory) / "reviewed-decoder-checkpoint.json").exists()


def test_reviewed_decoder_complete_schema_and_explicit_backend_are_closed(tmp_path):
    fixture = _complete_reviewed_worker_fixture(tmp_path)
    with pytest.raises(worker.TrainingJobValidationError, match="unknown"):
        worker.TrainingJobSpec.from_dict({**fixture.payload, "samples": []})
    with pytest.raises(worker.TrainingJobValidationError, match="explicit reviewed"):
        worker.ReviewedDecoderTrainingJobSpec.from_dict({**fixture.payload, "schema_version": worker.SCHEMA_VERSION})
    with pytest.raises(worker.TrainingJobValidationError, match="execution_guard"):
        replace(fixture.runtime, execution_guard=None)


def test_legacy_job_parser_identity_is_unchanged_and_old_worker_pin_cannot_train_new_generation(tmp_path):
    payload = _job(tmp_path)
    spec = worker.TrainingJobSpec.from_dict(payload)
    assert type(spec) is worker.TrainingJobSpec
    assert worker.TrainingJobSpec.from_dict(spec.to_dict()).to_dict() == spec.to_dict()
    expected = {**_source_manifest(), "worker": "bde3bd327df59f2e7557eac8aa2e0989ceb1128bc39918bf8cf46011e7bd9415"}
    old_source_job = worker.TrainingJobSpec.from_dict({**payload, "expected_source_sha256": expected})
    with pytest.raises(worker.TrainingJobValidationError, match="source manifest"):
        worker.execute_training_job(old_source_job, trainer=lambda *args, **kwargs: pytest.fail("old source trained"))
    assert not Path(old_source_job.output_directory).exists()


# These tests require an explicitly admitted Torch installed-DATA profile.
# They use a tiny fictional model initialized in-process, never downloaded
# weights. Numeric updates exercise the real adapter; they do not qualify a
# pretrained model, a statutory interpretation, semantic fidelity or convergence.

def _torch_reviewed_backend_fixture(architecture="encoder_decoder", *, context_limit=4096):
    import json
    from types import SimpleNamespace
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import (
        ReviewedPretrainedTokenizer, TorchReviewedDecoderBackend)

    class LoadedTokenizer:
        bos_token_id, eos_token_id, vocab_size = 257, 258, 259
        def __init__(self):
            self.byte_to_id = list(range(1, 257))
            self.frontend_config = {"normalizer": "identity", "cleanup": False}
        def encode(self, text, *, add_special_tokens, truncation):
            assert add_special_tokens is False and truncation is False
            if self.frontend_config["normalizer"] == "lowercase":
                text = text.lower()
            return [self.byte_to_id[value] for value in text.encode("utf-8")]
        def decode(self, values, *, skip_special_tokens, clean_up_tokenization_spaces):
            assert skip_special_tokens is False and clean_up_tokenization_spaces is False
            inverse = {value: index for index, value in enumerate(self.byte_to_id)}
            return bytes(inverse[value] for value in values).decode("utf-8")
        def pipeline_serialization(self):
            return _reviewed_fixed_byte_pipeline(self)

    class Config:
        is_encoder_decoder = architecture == "encoder_decoder"
        def to_dict(self):
            return {"is_encoder_decoder": self.is_encoder_decoder, "max_position_embeddings": 65536,
                    "fixture": "tiny_owned_gru_not_pretrained"}

    class TinyOwnedModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.config = Config()
            self.embedding = torch.nn.Embedding(259, 8)
            if self.config.is_encoder_decoder:
                self.encoder = torch.nn.GRU(8, 8, batch_first=True)
            self.decoder = torch.nn.GRU(8, 8, batch_first=True)
            self.dropout = torch.nn.Dropout(.1)
            self.head = torch.nn.Linear(8, 259)
            self.calls = []
        def get_input_embeddings(self):
            return self.embedding
        def get_output_embeddings(self):
            return self.head
        def forward(self, *, input_ids, attention_mask, labels=None, decoder_input_ids=None):
            assert bool(attention_mask.all())
            self.calls.append({"input_ids": input_ids.detach().cpu().tolist(),
                               "labels": None if labels is None else labels.detach().cpu().tolist(),
                               "decoder_input_ids": None if decoder_input_ids is None else decoder_input_ids.detach().cpu().tolist()})
            if self.config.is_encoder_decoder:
                _, hidden = self.encoder(self.embedding(input_ids))
                decoded, _ = self.decoder(self.embedding(decoder_input_ids), hidden)
                logits = self.head(self.dropout(decoded))
                loss = None if labels is None else torch.nn.functional.cross_entropy(logits.reshape(-1, 259), labels.reshape(-1))
            else:
                decoded, _ = self.decoder(self.embedding(input_ids))
                logits = self.head(self.dropout(decoded))
                loss = None if labels is None else torch.nn.functional.cross_entropy(logits[:, :-1].reshape(-1, 259), labels[:, 1:].reshape(-1))
            return SimpleNamespace(loss=loss, logits=logits)

    torch.manual_seed(11)
    model = TinyOwnedModel()
    optimizer = torch.optim.Adam(model.parameters(), lr=.01, foreach=False)
    tokenizer = ReviewedPretrainedTokenizer(LoadedTokenizer(), bos_token_id=257, eos_token_id=258, vocab_size=259,
        allow_fictional_fixture=True)
    backend = TorchReviewedDecoderBackend(model, optimizer, tokenizer, architecture=architecture,
        max_sequence_tokens=context_limit, pretrained=False)
    # The input-owner tests separately use the real fictional V2 admission.
    # This low-level numerical test only transports a full-shaped fixture;
    # it makes no assertion that a fabricated AST has statutory authority.
    target = {"profile": "fixture:v2", "typed_expression": {"fixture_predicate": "file"},
        "argument_roles": ["actor"], "assumptions": [],
        "governing_context": {"jurisdiction": "fixture:us", "instrument_id": "fixture:code",
            "governing_edition": "fixture:edition", "legal_as_of_utc": "2026-01-02T00:00:00Z",
            "valid_from_utc": "2026-01-01T00:00:00Z", "valid_until_utc": None}, "interpretation_id": "fixture:one",
        "source_binding": {"source_version_cid": "fixture:source", "occurrence_cid": "fixture:occurrence",
                           "document_revision": "fixture:revision"},
        "definition_uses": [{"fixture_definition": "clerk"}], "cross_references": []}
    source_wire = json.dumps({"profile": "reviewed-source-selection-context/v2",
        "source_text": "A fixture clerk must file.", "governing_context": {"jurisdiction": "fixture:us", "instrument_id": "fixture:code",
            "governing_edition": "fixture:edition", "legal_as_of_utc": "2026-01-02T00:00:00Z",
            "valid_from_utc": "2026-01-01T00:00:00Z", "valid_until_utc": None},
        "source_binding": {"source_version_cid": "fixture:source", "occurrence_cid": "fixture:occurrence",
                           "document_revision": "fixture:revision"},
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": "fixture:one", "selection_mode": "identifier_only"}}, sort_keys=True, separators=(",", ":"))
    target_json = json.dumps(target, sort_keys=True, separators=(",", ":"))
    wrap = lambda value: [257, *tokenizer.encode(value), 258]
    records = [{"id": "fixture:train", "unit_id": "fixture:norm", "source_wire": source_wire,
                "target_json": target_json, "source_token_ids": wrap(source_wire), "target_token_ids": wrap(target_json)}]
    return torch, backend, records


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_torch_backend_real_teacher_forcing_updates_model_and_adam_state(architecture):
    torch, backend, records = _torch_reviewed_backend_fixture(architecture)
    backend.validate_training_records(records, max_source_tokens=4096, max_target_tokens=4096)
    before = {name: value.detach().clone() for name, value in backend.model.state_dict().items()}
    initial = backend.snapshot_checkpoint()
    assert backend.inspect_checkpoint(initial["model_state"], initial["optimizer_state"]) == {"optimizer_steps": 0}
    result = backend.train_batch(records)
    assert result["optimizer_steps"] == 1 and result["loss"] > 0 and result["gradient_norm"] > 0
    assert result["gradient_parameter_count"] == result["trainable_parameter_count"] > 0
    assert any(not torch.equal(value, backend.model.state_dict()[name]) for name, value in before.items())
    assert backend.optimizer.state_dict()["state"]
    snapshot = backend.snapshot_checkpoint()
    assert backend.inspect_checkpoint(snapshot["model_state"], snapshot["optimizer_state"]) == {"optimizer_steps": 1}
    assert backend.identity()["pretrained"] is False
    call = backend.model.calls[-1]
    source, target = records[0]["source_token_ids"], records[0]["target_token_ids"]
    if architecture == "encoder_decoder":
        assert call["input_ids"] == [source]
        assert call["decoder_input_ids"] == [target[:-1]] and call["labels"] == [target[1:]]
    else:
        assert call["input_ids"] == [source + target]
        assert call["labels"] == [[-100] * (len(source) + 1) + target[1:]]


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_torch_checkpoint_restores_adam_and_dropout_rng_for_next_update(architecture):
    _, uninterrupted, records = _torch_reviewed_backend_fixture(architecture)
    uninterrupted.train_batch(records)
    intermediate = uninterrupted.snapshot_checkpoint()
    expected_loss = uninterrupted.train_batch(records)["loss"]
    expected = uninterrupted.snapshot_checkpoint()
    _, resumed, resumed_records = _torch_reviewed_backend_fixture(architecture)
    resumed.restore_checkpoint(intermediate["model_state"], intermediate["optimizer_state"])
    assert resumed.restored_checkpoint_matches(intermediate["model_state"], intermediate["optimizer_state"])
    assert resumed.train_batch(resumed_records)["loss"] == expected_loss
    assert resumed.restored_checkpoint_matches(expected["model_state"], expected["optimizer_state"])


def test_reviewed_torch_joint_causal_budget_refuses_before_forward_or_optimizer_update():
    _, probe, records = _torch_reviewed_backend_fixture("causal_lm")
    individual = max(len(records[0]["source_token_ids"]), len(records[0]["target_token_ids"]))
    _, backend, records = _torch_reviewed_backend_fixture("causal_lm", context_limit=individual)
    with pytest.raises(worker.TrainingJobValidationError, match="full source and target exceed"):
        backend.validate_training_records(records, max_source_tokens=4096, max_target_tokens=4096)
    assert backend.model.calls == [] and backend.optimizer.state_dict()["state"] == {}
    snapshot = backend.snapshot_checkpoint()
    assert backend.inspect_checkpoint(snapshot["model_state"], snapshot["optimizer_state"]) == {"optimizer_steps": 0}


def test_reviewed_torch_foreign_optimizer_parameter_refuses_before_forward():
    torch, backend, records = _torch_reviewed_backend_fixture()
    backend.optimizer = torch.optim.Adam([torch.nn.Parameter(torch.tensor(1.0))], lr=.01)
    with pytest.raises(worker.TrainingJobValidationError, match="foreign or duplicate"):
        backend.validate_training_records(records, max_source_tokens=4096, max_target_tokens=4096)
    assert backend.model.calls == []


def test_reviewed_torch_nonfinite_pretrained_parameter_refuses_before_forward():
    torch, backend, records = _torch_reviewed_backend_fixture()
    with torch.no_grad():
        backend.model.embedding.weight[0, 0] = float("nan")
    with pytest.raises(worker.TrainingJobValidationError, match="nonfinite"):
        backend.validate_training_records(records, max_source_tokens=4096, max_target_tokens=4096)
    assert backend.model.calls == [] and backend.optimizer.state_dict()["state"] == {}


def test_reviewed_torch_paired_checkpoint_rejects_another_architecture_before_restore():
    _, first, _ = _torch_reviewed_backend_fixture("encoder_decoder")
    checkpoint = first.snapshot_checkpoint()
    _, other, _ = _torch_reviewed_backend_fixture("causal_lm")
    with pytest.raises(worker.TrainingJobValidationError, match="configuration or paired state"):
        other.inspect_checkpoint(checkpoint["model_state"], checkpoint["optimizer_state"])
    assert other.model.calls == [] and other.optimizer.state_dict()["state"] == {}


def test_reviewed_torch_backend_public_job_file_reaches_full_reviewed_forward_and_checkpoint(tmp_path):
    from dataclasses import replace
    from copy import deepcopy
    import random
    fixture = _complete_reviewed_worker_fixture(tmp_path)
    _, backend, _ = _torch_reviewed_backend_fixture(context_limit=65536)
    state = backend.snapshot_checkpoint()
    model = _complete_reviewed_artifact(tmp_path / "torch-initial-model.checkpoint", state["model_state"])
    optimizer = _complete_reviewed_artifact(tmp_path / "torch-initial-optimizer.checkpoint", state["optimizer_state"])
    tokenizer_asset = _complete_reviewed_artifact(tmp_path / "torch-fixture-tokenizer.json",
        worker._json_bytes({"fixture_only": True, "bos_token_id": 257, "eos_token_id": 258, "vocab_size": 259}))
    old_parent = json.loads(Path(fixture.payload["parent_checkpoint_artifact"]["path"]).read_bytes())
    parent = deepcopy(old_parent)
    parent.update(backend_identity=backend.identity(),
        assets=[model, tokenizer_asset, fixture.payload["license_artifact"]], model_state=model,
        optimizer_state=optimizer, token_budgets={"max_source_tokens": 8192, "max_target_tokens": 32768,
            "tokenizer_contract": fixture.inputs._reviewed_decoder_tokenizer_contract(backend.tokenizer)})
    parent_ref = _complete_reviewed_artifact(tmp_path / "torch-initial-paired-manifest.json", worker._json_bytes(parent))
    payload = dict(fixture.payload, backend_identity=backend.identity(), model_artifact=model,
        tokenizer_artifact=tokenizer_asset, base_model_checkpoint=model, base_optimizer_checkpoint=optimizer,
        parent_checkpoint_artifact=parent_ref, output_directory=str(tmp_path / "torch-reviewed-output"))
    runtime = replace(fixture.runtime, backend=backend, tokenizer=backend.tokenizer)
    job = _complete_reviewed_artifact(tmp_path / "torch-reviewed-job.json", worker._json_bytes(payload))
    spec = worker.TrainingJobSpec.from_dict(payload)
    assert type(spec) is worker.ReviewedDecoderTrainingJobSpec
    assert worker.TrainingJobSpec.from_dict(spec.to_dict()).canonical_sha256 == spec.canonical_sha256
    result = worker.execute_training_job_file(job["path"], job["sha256"], reviewed_runtime=runtime)
    assert backend.model.calls and backend._optimizer_steps == 1
    assert result["backend_train_batch_calls"] == 1
    assert result["qualified"] is False and result["promotion_performed"] is False
    # The independently admitted full target is supplied to teacher forcing;
    # no {rules} projection or post-generation metadata fill is used.
    labels = backend.model.calls[0]["labels"][0]
    assert labels[-1] == backend.tokenizer.eos_token_id
    target = json.loads(backend.tokenizer.decode(labels[:-1]))
    assert set(target) == {"profile", "typed_expression", "argument_roles", "assumptions", "governing_context",
        "interpretation_id", "source_binding", "definition_uses", "cross_references"}
    order = list(range(len(fixture.data.rows)))
    random.Random(payload["seed"]).shuffle(order)
    assert target == fixture.data.rows[order[0]]["canonical_ir"]


@pytest.mark.parametrize("remaining_steps", [0, 1])
def test_reviewed_decoder_reserves_progress_capacity_before_checkpoint_inspection_or_fit(tmp_path, remaining_steps, monkeypatch):
    fixture = _complete_reviewed_worker_fixture(tmp_path)
    payload = dict(fixture.payload)
    prepared = fixture.inputs.prepare_reviewed_decoder_training_inputs(fixture.registry,
        stage_artifact=payload["stage_artifact"], expected_stage_sha256=payload["stage_artifact"]["sha256"],
        current_admission_inputs=fixture.runtime.current_admission_provider(),
        expected_admission_inputs_sha256=payload["expected_admission_inputs_sha256"],
        exposure_records=fixture.data.options["exposure_records"], expected_exposure_sha256=payload["exposure_artifact"]["sha256"],
        source_contexts=fixture.contexts, expected_source_contexts_sha256=payload["source_contexts_artifact"]["sha256"],
        split_config=payload["split_config"], expected_split_config_sha256=payload["expected_split_config_sha256"],
        tokenizer=fixture.runtime.tokenizer, max_source_tokens=payload["max_source_tokens"],
        max_target_tokens=payload["max_target_tokens"], allow_fictional_fixture=True)
    # These are valid parent counters, including a nonzero row cursor. The
    # requested two-update window must be refused before inspecting/restoring
    # state because it cannot produce a resumable bounded successor.
    steps = 10**9 - remaining_steps
    epochs, cursor = divmod(steps, len(prepared["records"]))
    optimizer = fixture.backend.snapshot_checkpoint()["optimizer_state"]
    optimizer_value = json.loads(optimizer)
    optimizer_value["steps"] = steps
    optimizer_ref = _complete_reviewed_artifact(tmp_path / "terminal-optimizer.json", worker._json_bytes(optimizer_value))
    parent = json.loads(Path(payload["parent_checkpoint_artifact"]["path"]).read_bytes())
    parent.update(training_binding=prepared["receipt"], optimizer_state=optimizer_ref,
        progress={"epochs_completed": epochs, "row_cursor": cursor, "optimizer_steps": steps})
    parent_ref = _complete_reviewed_artifact(tmp_path / "terminal-parent.json", worker._json_bytes(parent))
    payload.update(base_optimizer_checkpoint=optimizer_ref, parent_checkpoint_artifact=parent_ref, max_steps=2)
    def forbidden_inspect(*args):
        pytest.fail("checkpoint inspection reached after progress capacity exhaustion")
    monkeypatch.setattr(fixture.backend, "inspect_checkpoint", forbidden_inspect)
    spec = worker.TrainingJobSpec.from_dict(payload)
    with pytest.raises(worker.TrainingJobValidationError, match="progress capacity exhausted before update"):
        worker.execute_training_job(spec, reviewed_runtime=fixture.runtime)
    assert fixture.backend.calls == fixture.backend.restores == 0
    assert not Path(spec.output_directory).exists()


def test_reviewed_decoder_partial_restore_failure_records_mutation_attempt(tmp_path, monkeypatch):
    fixture = _complete_reviewed_worker_fixture(tmp_path)
    def partial_restore(model_state, optimizer_state):
        fixture.backend.weights[0] = 123.0
        raise RuntimeError("fictional optimizer restoration failed after model mutation")
    monkeypatch.setattr(fixture.backend, "restore_checkpoint", partial_restore)
    spec = worker.TrainingJobSpec.from_dict(fixture.payload)
    with pytest.raises(RuntimeError, match="after model mutation"):
        worker.execute_training_job(spec, reviewed_runtime=fixture.runtime)
    failure = json.loads((Path(spec.output_directory) / "failure.json").read_bytes())
    assert fixture.backend.weights[0] == 123.0
    assert fixture.backend.calls == fixture.backend.restores == 0
    assert failure["backend_restore_attempts"] == 1
    assert failure["completed_backend_restore_calls"] == 0
    assert failure["caller_owned_backend_may_have_changed"] is True
    assert failure["qualified"] is failure["promotion_performed"] is False
    assert not (Path(spec.output_directory) / "receipt.json").exists()
    assert not (Path(spec.output_directory) / "reviewed-decoder-checkpoint.json").exists()


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_torch_terminal_progress_refuses_before_forward_or_parameter_change(architecture):
    torch, backend, records = _torch_reviewed_backend_fixture(architecture)
    backend._optimizer_steps = 10**9
    before = backend.snapshot_checkpoint()
    with pytest.raises(worker.TrainingJobValidationError, match="progress capacity exhausted before update"):
        backend.train_batch(records)
    assert backend.model.calls == []
    assert backend.optimizer.state_dict()["state"] == {}
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"])


def test_reviewed_torch_versioned_module_metadata_survives_own_checkpoint_restore():
    torch, backend, _ = _torch_reviewed_backend_fixture()
    class VersionedProjection(torch.nn.Linear):
        _version = 7
        def _load_from_state_dict(self, state_dict, prefix, local_metadata, strict,
                                  missing_keys, unexpected_keys, error_msgs):
            if local_metadata.get("version") != self._version:
                raise ValueError("required versioned projection metadata was lost")
            return super()._load_from_state_dict(state_dict, prefix, local_metadata, strict,
                missing_keys, unexpected_keys, error_msgs)
    backend.model.head = VersionedProjection(8, 259)
    backend.optimizer = torch.optim.Adam(backend.model.parameters(), lr=.01, foreach=False)
    before = backend.snapshot_checkpoint()
    model_payload, _ = backend._load_pair(before["model_state"], before["optimizer_state"])
    assert model_payload["state_metadata"]["head"]["version"] == 7
    with torch.no_grad():
        backend.model.head.weight.add_(3.0)
    backend.restore_checkpoint(before["model_state"], before["optimizer_state"])
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"])
    assert backend.model.calls == [] and backend.optimizer.state_dict()["state"] == {}


def test_reviewed_torch_changed_state_metadata_refuses_before_model_restore():
    import io
    torch, backend, _ = _torch_reviewed_backend_fixture()
    before = backend.snapshot_checkpoint()
    model_payload, _ = backend._load_pair(before["model_state"], before["optimizer_state"])
    model_payload["state_metadata"]["head"]["version"] += 1
    stream = io.BytesIO()
    torch.save(model_payload, stream)
    with pytest.raises(worker.TrainingJobValidationError, match="configuration or paired state schema differs"):
        backend.restore_checkpoint(stream.getvalue(), before["optimizer_state"])
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"])
    assert backend.model.calls == []


def test_reviewed_torch_foreign_buffer_device_refuses_before_forward_or_fit():
    torch, backend, records = _torch_reviewed_backend_fixture()
    backend.model.register_buffer("foreign_fixture_buffer", torch.empty(1, device="meta"))
    with pytest.raises(worker.TrainingJobValidationError, match="buffers must share the owned model device"):
        backend.validate_training_records(records, max_source_tokens=4096, max_target_tokens=4096)
    assert backend.model.calls == [] and backend.optimizer.state_dict()["state"] == {}


@pytest.mark.parametrize("metadata_value", [(1, 2), {1: "non-string-key"}])
def test_reviewed_torch_lossy_state_metadata_refuses_before_snapshot_or_forward(metadata_value, monkeypatch):
    _, backend, _ = _torch_reviewed_backend_fixture()
    original = backend.model.state_dict
    def state_with_lossy_metadata(*args, **kwargs):
        state = original(*args, **kwargs)
        state._metadata["head"]["unsupported_fixture_value"] = metadata_value
        return state
    monkeypatch.setattr(backend.model, "state_dict", state_with_lossy_metadata)
    with pytest.raises(worker.TrainingJobValidationError, match="JSON model state-dict metadata"):
        backend.snapshot_checkpoint()
    assert backend.model.calls == [] and backend.optimizer.state_dict()["state"] == {}


# Source-authored v05 tokenizer/checkpoint contracts. UNRUN in the private
# drafting window. These fixtures claim no pretrained, legal or convergence
# qualification; the byte mapping is an explicit fictional transport only.
def _change_reviewed_fixture_pipeline(tokenizer, change):
    delegate = tokenizer.tokenizer if type(tokenizer) is worker.ReviewedPretrainedTokenizer else tokenizer
    if change == "mapping":
        delegate.byte_to_id[0], delegate.byte_to_id[1] = delegate.byte_to_id[1], delegate.byte_to_id[0]
    elif change == "normalizer":
        delegate.frontend_config["normalizer"] = "lowercase"
    elif change == "frontend_configuration":
        delegate.frontend_config["cleanup"] = True
    else:
        raise AssertionError(change)


@pytest.mark.parametrize("change", ["mapping", "normalizer", "frontend_configuration"])
def test_reviewed_torch_same_three_ids_different_pipeline_refuses_paired_restore_before_model_mutation(change):
    _, first, _ = _torch_reviewed_backend_fixture()
    parent = first.snapshot_checkpoint()
    torch, other, _ = _torch_reviewed_backend_fixture()
    _change_reviewed_fixture_pipeline(other.tokenizer, change)
    assert (first.tokenizer.bos_token_id, first.tokenizer.eos_token_id, first.tokenizer.vocab_size) == (
        other.tokenizer.bos_token_id, other.tokenizer.eos_token_id, other.tokenizer.vocab_size)
    before = {name: value.detach().clone() for name, value in other.model.state_dict().items()}
    with pytest.raises(worker.TrainingJobValidationError, match="configuration or paired state"):
        other.restore_checkpoint(parent["model_state"], parent["optimizer_state"])
    assert all(torch.equal(before[name], value) for name, value in other.model.state_dict().items())
    assert other.model.calls == [] and other.optimizer.state_dict()["state"] == {} and other._optimizer_steps == 0


@pytest.mark.parametrize("change", ["mapping", "normalizer", "frontend_configuration"])
def test_reviewed_torch_same_object_pipeline_drift_refuses_fit_before_forward(change):
    _, backend, records = _torch_reviewed_backend_fixture()
    before = backend.identity()
    _change_reviewed_fixture_pipeline(backend.tokenizer, change)
    with pytest.raises(worker.TrainingJobValidationError, match="tokenizer pipeline changed"):
        backend.train_batch(records)
    assert before["backend_id"].startswith("torch-complete-reviewed-decoder/v2:")
    assert backend.model.calls == [] and backend.optimizer.state_dict()["state"] == {} and backend._optimizer_steps == 0


def test_reviewed_tokenizer_binding_metadata_derives_six_fields_from_full_actual_fixture_pipeline():
    _, backend, _ = _torch_reviewed_backend_fixture()
    tokenizer = backend.tokenizer
    raw = tokenizer.pipeline_serialization()
    payload = worker._parse_json(raw)
    binding = tokenizer.binding_metadata()
    contract = backend._pipeline_contract()
    assert set(binding) == {"tokenizer_id", "vocabulary_sha256", "configuration_sha256",
                            "bos_token_id", "eos_token_id", "vocab_size"}
    assert binding["configuration_sha256"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert binding["vocabulary_sha256"] == "sha256:" + hashlib.sha256(worker._json_bytes({
        "byte_to_id": payload["backend"]["byte_to_id"], "added_tokens": []})).hexdigest()
    assert contract["pipeline_sha256"] == hashlib.sha256(raw).hexdigest() and contract["pipeline_bytes"] == len(raw)
    assert contract["schema"] == "reviewed-decoder-tokenizer-contract/v2" and contract["pipeline_kind"] == "fictional_fixed_byte"
    assert backend._configuration()["tokenizer_binding"] == binding
    assert payload["transport"] == {"body_only": True, "truncation": False, "padding": False}
    assert len(payload["backend"]["byte_to_id"]) == 256 and payload["kind"] == "fictional_fixed_byte"


@pytest.mark.parametrize("callback", ["configuration", "train", "zero_grad"])
def test_reviewed_torch_pipeline_change_in_pre_forward_callbacks_never_reaches_model_forward(callback, monkeypatch):
    _, backend, records = _torch_reviewed_backend_fixture()
    backend.identity()
    owner, name = (backend.model, "get_input_embeddings") if callback == "configuration" else (
        (backend.model, "train") if callback == "train" else (backend.optimizer, "zero_grad"))
    original = getattr(owner, name)
    def change_during_callback(*args, **kwargs):
        result = original(*args, **kwargs)
        _change_reviewed_fixture_pipeline(backend.tokenizer, "frontend_configuration")
        return result
    monkeypatch.setattr(owner, name, change_during_callback)
    with pytest.raises(worker.TrainingJobValidationError, match="tokenizer pipeline changed"):
        backend.train_batch(records)
    assert backend.model.calls == [] and backend._optimizer_steps == 0 and backend.optimizer.state_dict()["state"] == {}


@pytest.mark.parametrize("callback", ["forward", "backward"])
def test_reviewed_torch_pipeline_change_during_loss_or_backward_refuses_before_optimizer_step(callback, monkeypatch):
    _, backend, records = _torch_reviewed_backend_fixture()
    backend.identity()
    if callback == "forward":
        original = backend.model.forward
        def forward_with_drift(*args, **kwargs):
            output = original(*args, **kwargs)
            _change_reviewed_fixture_pipeline(backend.tokenizer, "normalizer")
            return output
        monkeypatch.setattr(backend.model, "forward", forward_with_drift)
    else:
        def gradient_with_drift(gradient):
            _change_reviewed_fixture_pipeline(backend.tokenizer, "normalizer")
            return gradient
        backend.model.head.weight.register_hook(gradient_with_drift)
    with pytest.raises(worker.TrainingJobValidationError, match="tokenizer pipeline changed"):
        backend.train_batch(records)
    assert len(backend.model.calls) == 1 and backend._optimizer_steps == 0
    assert backend.optimizer.state_dict()["state"] == {}


def test_reviewed_torch_pipeline_change_during_optimizer_step_is_retained_as_failed_update(monkeypatch):
    _, backend, records = _torch_reviewed_backend_fixture()
    original = backend.optimizer.step
    def step_with_drift(*args, **kwargs):
        result = original(*args, **kwargs)
        _change_reviewed_fixture_pipeline(backend.tokenizer, "frontend_configuration")
        return result
    monkeypatch.setattr(backend.optimizer, "step", step_with_drift)
    with pytest.raises(worker.TrainingJobValidationError, match="tokenizer pipeline changed"):
        backend.train_batch(records)
    assert backend._optimizer_steps == 1 and backend.optimizer.state_dict()["state"]
    with pytest.raises(worker.TrainingJobValidationError, match="tokenizer pipeline changed"):
        backend.snapshot_checkpoint()


@pytest.mark.parametrize("callback", ["model_restore", "optimizer_restore", "snapshot"])
def test_reviewed_torch_pipeline_drift_during_state_callbacks_is_rejected(callback, monkeypatch):
    _, backend, _ = _torch_reviewed_backend_fixture()
    before = backend.snapshot_checkpoint()
    if callback == "snapshot":
        owner, name = backend.optimizer, "state_dict"
    else:
        owner, name = ((backend.model, "load_state_dict") if callback == "model_restore" else
                       (backend.optimizer, "load_state_dict"))
    original = getattr(owner, name)
    def change_during_state_callback(*args, **kwargs):
        result = original(*args, **kwargs)
        _change_reviewed_fixture_pipeline(backend.tokenizer, "frontend_configuration")
        return result
    monkeypatch.setattr(owner, name, change_during_state_callback)
    with pytest.raises(worker.TrainingJobValidationError, match="tokenizer pipeline changed"):
        if callback == "snapshot":
            backend.snapshot_checkpoint()
        else:
            backend.restore_checkpoint(before["model_state"], before["optimizer_state"])
    assert backend.model.calls == [] and backend._optimizer_steps == 0


def test_reviewed_decoder_post_update_pipeline_drift_leaves_unpromoted_failure_not_success(tmp_path, monkeypatch):
    fixture = _complete_reviewed_worker_fixture(tmp_path)
    original = fixture.backend.train_batch
    def update_then_change_pipeline(records):
        result = original(records)
        _change_reviewed_fixture_pipeline(fixture.runtime.tokenizer, "frontend_configuration")
        return result
    monkeypatch.setattr(fixture.backend, "train_batch", update_then_change_pipeline)
    with pytest.raises((worker.TrainingJobValidationError, ValueError), match="changed"):
        worker.execute_training_job(worker.TrainingJobSpec.from_dict(fixture.payload), reviewed_runtime=fixture.runtime)
    output = Path(fixture.payload["output_directory"])
    failure = json.loads((output / "failure.json").read_bytes())
    assert fixture.backend.calls == 1 and failure["completed_backend_calls"] == 1
    assert failure["qualified"] is False and failure["promotion_performed"] is False
    assert not (output / "receipt.json").exists() and not (output / "reviewed-decoder-checkpoint.json").exists()


@pytest.mark.parametrize("value", [object(), {"unknown": object()}, float("nan")])
def test_reviewed_tokenizer_frontend_configuration_refuses_lossy_unknown_or_nonfinite_values(value):
    with pytest.raises(worker.TrainingJobValidationError, match="unsupported|finite"):
        worker._reviewed_tokenizer_configuration(value)


def test_reviewed_tokenizer_typed_frontend_configuration_preserves_integer_keys_tuples_and_nonascii():
    value = {1: ("é", False), "1": ["é", False]}
    encoded = worker._reviewed_tokenizer_configuration(value)
    assert encoded["items"][0][0] == {"type": "int", "value": 1}
    assert encoded["items"][0][1]["type"] == "tuple" and encoded["items"][1][1]["type"] == "list"
    assert b"\\u00e9" in worker._json_bytes(encoded)


def test_reviewed_torch_legacy_three_integer_configuration_pair_cannot_be_silently_upgraded():
    import io
    torch, backend, _ = _torch_reviewed_backend_fixture()
    before = backend.snapshot_checkpoint()
    model, optimizer = backend._load_pair(before["model_state"], before["optimizer_state"])
    old_config = dict(backend._configuration(), schema="torch-complete-reviewed-decoder-configuration/v1",
        tokenizer={"bos_token_id": 257, "eos_token_id": 258, "vocab_size": 259})
    old_config.pop("tokenizer_binding")
    old_signature = worker._digest(worker._json_bytes(old_config))
    model["configuration_sha256"] = optimizer["configuration_sha256"] = old_signature
    model_stream, optimizer_stream = io.BytesIO(), io.BytesIO()
    torch.save(model, model_stream)
    torch.save(optimizer, optimizer_stream)
    with pytest.raises(worker.TrainingJobValidationError, match="configuration or paired state"):
        backend.restore_checkpoint(model_stream.getvalue(), optimizer_stream.getvalue())
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"])
    assert backend.model.calls == [] and backend._optimizer_steps == 0


def _actual_fast_reviewed_backend_fixture():
    """Construct actual local Rust/HF objects; no fitting/loading/download.

    These tests deliberately require the admitted Tokenizers, Transformers and
    Torch installation. A missing/unsupported installation is not a passing skip.
    The model remains a tiny fictional GRU and makes no pretrained claim.
    """
    from tokenizers import Tokenizer, AddedToken, models, pre_tokenizers, decoders
    from transformers import PreTrainedTokenizerFast
    torch, backend, records = _torch_reviewed_backend_fixture()
    alphabet = sorted(pre_tokenizers.ByteLevel.alphabet())
    vocabulary = {"[UNK]": 0, **{value: index + 1 for index, value in enumerate(alphabet)}, "[BOS]": 257, "[EOS]": 258}
    native = Tokenizer(models.BPE(vocab=vocabulary, merges=[], unk_token="[UNK]"))
    native.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)
    native.decoder = decoders.ByteLevel()
    native.add_special_tokens([AddedToken("[BOS]", normalized=False, special=True), AddedToken("[EOS]", normalized=False, special=True)])
    loaded = PreTrainedTokenizerFast(tokenizer_object=native, bos_token="[BOS]", eos_token="[EOS]", unk_token="[UNK]",
        clean_up_tokenization_spaces=False, model_max_length=65536)
    tokenizer = worker.ReviewedPretrainedTokenizer(loaded, bos_token_id=257, eos_token_id=258, vocab_size=259)
    backend.tokenizer = tokenizer
    for row in records:
        row["source_token_ids"] = [257, *tokenizer.encode(row["source_wire"]), 258]
        row["target_token_ids"] = [257, *tokenizer.encode(row["target_json"]), 258]
    return torch, backend, records


def _change_actual_fast_reviewed_pipeline(tokenizer, change):
    from tokenizers import models, normalizers
    loaded = tokenizer.tokenizer
    if change == "mapping":
        vocabulary = loaded.backend_tokenizer.get_vocab(with_added_tokens=False)
        ordinary = sorted(key for key in vocabulary if not key.startswith("["))
        left, right = ordinary[:2]
        vocabulary[left], vocabulary[right] = vocabulary[right], vocabulary[left]
        loaded.backend_tokenizer.model = models.BPE(vocab=vocabulary, merges=[], unk_token="[UNK]")
    elif change == "normalizer":
        loaded.backend_tokenizer.normalizer = normalizers.Lowercase()
    elif change == "frontend_configuration":
        loaded.clean_up_tokenization_spaces = True
    else:
        raise AssertionError(change)


def test_reviewed_actual_fast_pipeline_retains_full_vocab_normalizer_native_assets_and_fixed_transport():
    _, backend, records = _actual_fast_reviewed_backend_fixture()
    tokenizer = backend.tokenizer
    pipeline = json.loads(tokenizer.pipeline_serialization())
    assert pipeline["kind"] == "huggingface_fast"
    assert pipeline["frontend"]["transport_path"] == "direct_actual_tokenizers_Rust_backend/v2"
    assert pipeline["backend"]["serialization"] == json.loads(tokenizer.tokenizer.backend_tokenizer.to_str())
    assert pipeline["backend"]["serialization"]["model"]["vocab"]
    assert {"normalizer", "pre_tokenizer", "post_processor", "decoder", "added_tokens", "truncation", "padding"} <= set(pipeline["backend"]["serialization"])
    assert any(row["path"].endswith((".so", ".pyd")) for row in pipeline["implementation"])
    assert pipeline["transport"] == {"body_only": True, "truncation": False, "padding": False}
    for row in records:
        assert tokenizer.decode(tokenizer.encode(row["source_wire"])) == row["source_wire"]
        assert tokenizer.decode(tokenizer.encode(row["target_json"])) == row["target_json"]
    backend.validate_training_records(records, max_source_tokens=4096, max_target_tokens=4096)
    assert backend.model.calls == [] and backend._optimizer_steps == 0


@pytest.mark.parametrize("change", ["mapping", "normalizer", "frontend_configuration"])
def test_reviewed_actual_fast_same_three_ids_changed_pipeline_refuses_parent_pair_before_model_load(change):
    _, first, _ = _actual_fast_reviewed_backend_fixture()
    parent = first.snapshot_checkpoint()
    torch, other, _ = _actual_fast_reviewed_backend_fixture()
    _change_actual_fast_reviewed_pipeline(other.tokenizer, change)
    assert (first.tokenizer.bos_token_id, first.tokenizer.eos_token_id, first.tokenizer.vocab_size) == (
        other.tokenizer.bos_token_id, other.tokenizer.eos_token_id, other.tokenizer.vocab_size)
    assert first.tokenizer.binding_metadata()["configuration_sha256"] != other.tokenizer.binding_metadata()["configuration_sha256"]
    before = {name: value.detach().clone() for name, value in other.model.state_dict().items()}
    with pytest.raises(worker.TrainingJobValidationError, match="configuration or paired state"):
        other.restore_checkpoint(parent["model_state"], parent["optimizer_state"])
    assert all(torch.equal(before[name], value) for name, value in other.model.state_dict().items())
    assert other.model.calls == [] and other._optimizer_steps == 0 and other.optimizer.state_dict()["state"] == {}


@pytest.mark.parametrize("change", ["mapping", "normalizer", "frontend_configuration"])
def test_reviewed_actual_fast_same_object_pipeline_change_refuses_fit_before_forward(change):
    _, backend, records = _actual_fast_reviewed_backend_fixture()
    backend.identity()
    _change_actual_fast_reviewed_pipeline(backend.tokenizer, change)
    with pytest.raises(worker.TrainingJobValidationError, match="tokenizer pipeline changed"):
        backend.train_batch(records)
    assert backend.model.calls == [] and backend._optimizer_steps == 0 and backend.optimizer.state_dict()["state"] == {}


@pytest.mark.parametrize("phase", ["validation", "train", "restore", "forward"])
def test_reviewed_actual_fast_pipeline_drift_inside_callbacks_refuses_at_next_boundary(phase, monkeypatch):
    _, backend, records = _actual_fast_reviewed_backend_fixture()
    checkpoint = backend.snapshot_checkpoint()
    if phase == "validation":
        owner, name = backend.model, "get_input_embeddings"
    elif phase == "train":
        owner, name = backend.model, "train"
    elif phase == "restore":
        owner, name = backend.model, "load_state_dict"
    else:
        owner, name = backend.model, "forward"
    original = getattr(owner, name)
    def callback_with_real_pipeline_change(*args, **kwargs):
        result = original(*args, **kwargs)
        _change_actual_fast_reviewed_pipeline(backend.tokenizer, "frontend_configuration")
        return result
    monkeypatch.setattr(owner, name, callback_with_real_pipeline_change)
    with pytest.raises(worker.TrainingJobValidationError, match="tokenizer pipeline changed"):
        if phase == "restore":
            backend.restore_checkpoint(checkpoint["model_state"], checkpoint["optimizer_state"])
        else:
            backend.train_batch(records)
    assert len(backend.model.calls) == (1 if phase == "forward" else 0)
    assert backend._optimizer_steps == 0 and backend.optimizer.state_dict()["state"] == {}


def test_reviewed_actual_fast_active_truncation_padding_or_split_special_transport_is_unsupported():
    from tokenizers import Tokenizer, models
    from transformers import PreTrainedTokenizerFast
    native = Tokenizer(models.WordLevel({"[UNK]": 0, "[BOS]": 1, "[EOS]": 2}, unk_token="[UNK]"))
    native.enable_truncation(max_length=3)
    loaded = PreTrainedTokenizerFast(tokenizer_object=native, unk_token="[UNK]", bos_token="[BOS]", eos_token="[EOS]")
    with pytest.raises(worker.TrainingJobValidationError, match="without truncation or padding"):
        worker.ReviewedPretrainedTokenizer(loaded, bos_token_id=1, eos_token_id=2, vocab_size=3)


def test_reviewed_actual_fast_hidden_opaque_frontend_setting_is_explicitly_unsupported_before_fit():
    _, backend, records = _actual_fast_reviewed_backend_fixture()
    backend.tokenizer.tokenizer.unrecognized_mutable_frontend_state = object()
    with pytest.raises(worker.TrainingJobValidationError, match="unsupported non-JSON tokenizer frontend configuration"):
        backend.train_batch(records)
    assert backend.model.calls == [] and backend.optimizer.state_dict()["state"] == {} and backend._optimizer_steps == 0


def test_reviewed_production_wrapper_refuses_unbacked_fixed_byte_object_without_fixture_opt_in():
    # Real production class imports are required in the admitted test profile;
    # a custom encode/decode callback is never silently treated as a fast asset.
    from transformers import PreTrainedTokenizerFast
    assert PreTrainedTokenizerFast is not None
    with pytest.raises(worker.TrainingJobValidationError, match="actual supported Hugging Face fast tokenizer"):
        worker.ReviewedPretrainedTokenizer(_CompleteReviewedByteTokenizer(), bos_token_id=256, eos_token_id=257, vocab_size=258)


# Source-only v06 error-boundary controls; UNRUN. Explicit input validation is
# translated with its cause. Operational callback failures remain the original
# exception objects and never become a readiness/abstention result.
def test_reviewed_torch_foreign_serializer_value_error_propagates_unchanged(monkeypatch):
    _, backend, _ = _torch_reviewed_backend_fixture()
    failure = ValueError("fictional operational serializer failure")
    def failing_serializer():
        raise failure
    monkeypatch.setattr(backend.tokenizer.tokenizer, "pipeline_serialization", failing_serializer)
    with pytest.raises(ValueError) as captured:
        backend.identity()
    assert captured.value is failure and type(captured.value) is ValueError
    assert backend.model.calls == [] and backend._optimizer_steps == 0 and backend.optimizer.state_dict()["state"] == {}


def test_reviewed_decoder_current_prepare_foreign_serializer_value_error_propagates_unchanged(tmp_path, monkeypatch):
    fixture = _complete_reviewed_worker_fixture(tmp_path)
    failure = ValueError("fictional operational current-input serializer failure")
    def failing_serializer():
        raise failure
    monkeypatch.setattr(fixture.runtime.tokenizer, "pipeline_serialization", failing_serializer)
    with pytest.raises(ValueError) as captured:
        worker.execute_training_job(worker.TrainingJobSpec.from_dict(fixture.payload), reviewed_runtime=fixture.runtime)
    assert captured.value is failure and type(captured.value) is ValueError
    assert fixture.backend.calls == fixture.backend.restores == 0
    assert not (Path(fixture.payload["output_directory"]) / "receipt.json").exists()


@pytest.mark.parametrize("phase", ["configuration", "training", "paired_configuration", "restore"])
def test_reviewed_torch_foreign_model_value_error_is_not_reclassified_at_validation_boundaries(phase, monkeypatch):
    _, backend, records = _torch_reviewed_backend_fixture()
    before = backend.snapshot_checkpoint()
    failure = ValueError("fictional operational model callback failure")
    name = "parameters" if phase in {"configuration", "paired_configuration"} else (
        "train" if phase == "training" else "load_state_dict")
    def failing_model_callback(*args, **kwargs):
        raise failure
    monkeypatch.setattr(backend.model, name, failing_model_callback)
    with pytest.raises(ValueError) as captured:
        if phase == "configuration":
            backend.identity()
        elif phase == "training":
            backend.train_batch(records)
        else:
            backend.restore_checkpoint(before["model_state"], before["optimizer_state"])
    assert captured.value is failure and type(captured.value) is ValueError
    assert backend.model.calls == [] and backend._optimizer_steps == 0 and backend.optimizer.state_dict()["state"] == {}


@pytest.mark.parametrize("phase", ["configuration", "paired_configuration"])
def test_reviewed_torch_typed_input_refusal_preserves_explicit_cause_and_phase_diagnostic(phase):
    from ipfs_datasets_py.logic.autoformal.training_cycle_inputs import ReviewedDecoderInputValidationError
    _, backend, _ = _torch_reviewed_backend_fixture()
    before = backend.snapshot_checkpoint()
    _change_reviewed_fixture_pipeline(backend.tokenizer, "frontend_configuration")
    pattern = "tokenizer pipeline changed or unsupported" if phase == "configuration" else "configuration or paired state"
    with pytest.raises(worker.TrainingJobValidationError, match=pattern) as captured:
        if phase == "configuration":
            backend.identity()
        else:
            backend.restore_checkpoint(before["model_state"], before["optimizer_state"])
    cause = captured.value.__cause__
    if phase == "paired_configuration":
        assert type(cause) is worker.TrainingJobValidationError
        cause = cause.__cause__
    assert type(cause) is ReviewedDecoderInputValidationError
    assert "normalization/cleanup" in str(cause)
    assert backend.model.calls == [] and backend._optimizer_steps == 0 and backend.optimizer.state_dict()["state"] == {}


# Exact finite checkpoint state must retain zero's sign bit in the existing
# real Torch fixture's model parameters and legitimate Adam moments.
def test_reviewed_torch_checkpoint_rejects_model_parameter_signed_zero_drift():
    torch, backend, _ = _torch_reviewed_backend_fixture()
    name, parameter = next(backend.model.named_parameters())
    scalar = parameter.view(-1)[0]
    with torch.no_grad():
        scalar.fill_(0.0)
    assert scalar.item() == 0.0 and not bool(torch.signbit(scalar).item())
    checkpoint = backend.snapshot_checkpoint()
    saved_model, _ = backend._load_pair(checkpoint["model_state"], checkpoint["optimizer_state"])
    assert not bool(torch.signbit(saved_model["state"][name].view(-1)[0]).item())
    assert backend.restored_checkpoint_matches(checkpoint["model_state"], checkpoint["optimizer_state"]) is True

    with torch.no_grad():
        scalar.fill_(-0.0)
    assert scalar.item() == 0.0 and bool(torch.signbit(scalar).item())
    assert backend.restored_checkpoint_matches(checkpoint["model_state"], checkpoint["optimizer_state"]) is False


def test_reviewed_torch_checkpoint_rejects_adam_moment_signed_zero_drift():
    torch, backend, records = _torch_reviewed_backend_fixture()
    assert backend.train_batch(records)["optimizer_steps"] == 1
    parameter = backend.optimizer.param_groups[0]["params"][0]
    moment = backend.optimizer.state[parameter]["exp_avg"]
    scalar = moment.view(-1)[0]
    with torch.no_grad():
        scalar.fill_(0.0)
    assert scalar.item() == 0.0 and not bool(torch.signbit(scalar).item())
    checkpoint = backend.snapshot_checkpoint()
    _, saved_optimizer = backend._load_pair(checkpoint["model_state"], checkpoint["optimizer_state"])
    saved_state = saved_optimizer["state"]
    key = saved_state["param_groups"][0]["params"][0]
    assert not bool(torch.signbit(saved_state["state"][key]["exp_avg"].view(-1)[0]).item())
    assert backend.restored_checkpoint_matches(checkpoint["model_state"], checkpoint["optimizer_state"]) is True

    with torch.no_grad():
        scalar.fill_(-0.0)
    assert scalar.item() == 0.0 and bool(torch.signbit(scalar).item())
    assert backend.restored_checkpoint_matches(checkpoint["model_state"], checkpoint["optimizer_state"]) is False


def test_reviewed_tokenizer_wrapper_method_identity_matches_actual_pipeline():
    """Compare live emitted and idle method identities without Torch/model work."""
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs

    delegate = _CompleteReviewedByteTokenizer()
    tokenizer = worker.ReviewedPretrainedTokenizer(
        delegate, bos_token_id=delegate.bos_token_id,
        eos_token_id=delegate.eos_token_id, vocab_size=delegate.vocab_size,
        allow_fictional_fixture=True)
    # Capture the real producer first: pipeline_serialization is itself one of
    # the emitted methods. Idle-only comparisons can miss that execution context.
    pipeline = worker._parse_json(tokenizer.pipeline_serialization())
    emitted = pipeline["frontend"]["wrapper_methods"]
    names = ("encode", "decode", "pipeline_serialization", "binding_metadata", "_fast_backend")
    assert set(emitted) == set(names), "actual wrapper-method field inventory changed"
    differences = {}
    for name in names:
        method = getattr(tokenizer, name)
        producer_idle = worker._reviewed_tokenizer_method(method)
        validator_idle = inputs._reviewed_decoder_fixed_byte_method(method)
        fields = set(emitted[name]) | set(producer_idle) | set(validator_idle)
        changed = {
            field: {"emitted_during_actual_pipeline": emitted[name].get(field),
                    "idle_worker_recipe": producer_idle.get(field),
                    "idle_input_validator_recipe": validator_idle.get(field)}
            for field in sorted(fields)
            if not (field in emitted[name] and field in producer_idle and field in validator_idle
                    and emitted[name][field] == producer_idle[field] == validator_idle[field])
        }
        if changed:
            function = getattr(method, "__func__", method)
            differences[name] = {
                "actual_code_filename": function.__code__.co_filename,
                "actual_freevars": list(function.__code__.co_freevars),
                "fields": changed,
            }
    assert not differences, "actual wrapper method identity differs by method/field: " + json.dumps(
        differences, sort_keys=True, ensure_ascii=True)


def _reviewed_generation_source_records(records):
    # Deliberately strip every target field before crossing the generation API.
    return [{key: row[key] for key in ("id", "unit_id", "source_wire", "source_token_ids")} for row in records]


def _reviewed_generation_script(monkeypatch, torch, backend, records, script):
    original = backend.model.forward
    source_length = len(records[0]["source_token_ids"])
    observed = []
    def scripted_forward(**arguments):
        assert "labels" not in arguments
        assert torch.is_grad_enabled() is False
        assert all(module.training is False for module in backend.model.modules())
        output = original(**arguments)
        prefix = arguments.get("decoder_input_ids")
        position = prefix.shape[1] - 1 if prefix is not None else arguments["input_ids"].shape[1] - source_length - 1
        observed.append({key: value.detach().cpu().tolist() for key, value in arguments.items()})
        # Explicit authored logits control, not trained-model quality evidence.
        logits = torch.full_like(output.logits, -100.0)
        logits[0, -1, script[min(position, len(script) - 1)]] = 100.0
        return type(output)(loss=output.loss, logits=logits)
    monkeypatch.setattr(backend.model, "forward", scripted_forward)
    return observed


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_generation_uses_source_and_autonomous_bos_prefix_without_labels(monkeypatch, architecture):
    torch, backend, training = _torch_reviewed_backend_fixture(architecture)
    source = _reviewed_generation_source_records(training)
    script = [ord("{") + 1, backend.tokenizer.eos_token_id]
    calls = _reviewed_generation_script(monkeypatch, torch, backend, source, script)
    guarded = []
    result = backend.generate_batch(source, max_output_tokens=4, execution_guard=lambda: guarded.append(True))
    assert len(calls) == 2 and len(guarded) >= 5
    assert result[0]["generated_token_ids"] == [257, *script]
    assert result[0]["outcome"] == "invalid" and result[0]["candidate"] is None
    assert result[0]["generated_text"] == "{" and result[0]["reason"] == "invalid_complete_norm_json"
    tokens = source[0]["source_token_ids"]
    if architecture == "encoder_decoder":
        assert calls[0]["input_ids"] == calls[1]["input_ids"] == [tokens]
        assert calls[0]["decoder_input_ids"] == [[257]]
        assert calls[1]["decoder_input_ids"] == [[257, script[0]]]
    else:
        assert calls[0]["input_ids"] == [tokens + [257]]
        assert calls[1]["input_ids"] == [tokens + [257, script[0]]]
        assert all("decoder_input_ids" not in call for call in calls)
    assert all(call["labels"] is None for call in backend.model.calls)
    assert backend._optimizer_steps == 0 and backend.optimizer.state_dict()["state"] == {}


def test_reviewed_generation_retains_complete_nine_field_output_without_target_filling(monkeypatch):
    import json
    torch, backend, training = _torch_reviewed_backend_fixture()
    source = _reviewed_generation_source_records(training)
    payload = {"profile": "fixture", "typed_expression": {"root": {"kind": "predicate"}},
        "argument_roles": [], "assumptions": [], "interpretation_id": "chosen",
        "governing_context": {"jurisdiction": "x", "instrument_id": "x", "governing_edition": "x",
            "legal_as_of_utc": "x", "valid_from_utc": "x", "valid_until_utc": None},
        "source_binding": {"source_version_cid": "x", "occurrence_cid": "x", "document_revision": "x"},
        "definition_uses": [], "cross_references": []}
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    script = [*backend.tokenizer.encode(text), 258]
    _reviewed_generation_script(monkeypatch, torch, backend, source, script)
    result = backend.generate_batch(source, max_output_tokens=len(script) + 1, execution_guard=lambda: None)
    assert result[0]["outcome"] == "complete" and result[0]["candidate"] == payload
    assert result[0]["generated_text"] == text and result[0]["generated_token_ids"] == [257, *script]
    # The emitted context/selector deliberately differ from the input: the
    # numerical transport preserves them; admission/semantic scoring is separate.
    assert result[0]["candidate"]["interpretation_id"] == "chosen"
    assert result[0]["candidate"]["governing_context"]["jurisdiction"] == "x"
    assert "target_json" not in source[0] and "target_token_ids" not in source[0]


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
@pytest.mark.parametrize("script,outcome,reason,expected", [
    ([258], "abstained", "empty_output", [257, 258]),
    ([ord("x") + 1], "incomplete", "output_limit_without_eos", [257, ord("x") + 1, ord("x") + 1]),
    ([257], "invalid", "unexpected_bos_in_output", [257, 257]),
    ([0, 258], "invalid", "invalid_output_transport", [257, 0, 258]),
])
def test_reviewed_generation_eos_budget_and_invalid_transport_keep_dispositions(monkeypatch, architecture,
        script, outcome, reason, expected):
    torch, backend, training = _torch_reviewed_backend_fixture(architecture)
    source = _reviewed_generation_source_records(training)
    _reviewed_generation_script(monkeypatch, torch, backend, source, script)
    result = backend.generate_batch(source, max_output_tokens=3, execution_guard=lambda: None)
    assert len(result) == len(source) == 1
    assert result[0]["outcome"] == outcome and result[0]["reason"] == reason
    assert result[0]["candidate"] is None and result[0]["generated_token_ids"] == expected


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
@pytest.mark.parametrize("fault", ["missing", "shape", "integer", "nonfinite"])
def test_reviewed_generation_rejects_invalid_logits(monkeypatch, architecture, fault):
    from types import SimpleNamespace
    torch, backend, training = _torch_reviewed_backend_fixture(architecture)
    source = _reviewed_generation_source_records(training)
    original = backend.model.forward
    def broken(**arguments):
        output = original(**arguments)
        if fault == "missing":
            return SimpleNamespace()
        logits = output.logits
        if fault == "shape":
            logits = logits[:, :, :-1]
        elif fault == "integer":
            logits = logits.to(dtype=torch.long)
        else:
            logits = logits.clone()
            logits[0, -1, 0] = float("nan")
        return SimpleNamespace(logits=logits)
    monkeypatch.setattr(backend.model, "forward", broken)
    with pytest.raises(worker.TrainingJobValidationError, match="finite full-prefix generation logits"):
        backend.generate_batch(source, max_output_tokens=3, execution_guard=lambda: None)
    assert len(backend.model.calls) == 1 and backend._optimizer_steps == 0


@pytest.mark.parametrize("failure", [False, True])
def test_reviewed_generation_preserves_numeric_state_grad_aliases_rng_and_mixed_modes(monkeypatch, failure):
    import copy
    torch, backend, training = _torch_reviewed_backend_fixture()
    backend.train_batch(training)
    backend.model.train()
    backend.model.dropout.eval()
    parameters = tuple(backend.model.parameters())
    for index, parameter in enumerate(parameters):
        parameter.grad = torch.full_like(parameter, index + 1.0) if index % 2 == 0 else None
    gradients = [(parameter.grad, None if parameter.grad is None else parameter.grad.clone()) for parameter in parameters]
    modes = [(module, module.training) for module in backend.model.modules()]
    model = copy.deepcopy(backend.model.state_dict())
    optimizer = copy.deepcopy(backend.optimizer.state_dict())
    rng = torch.get_rng_state().clone()
    source = _reviewed_generation_source_records(training)
    original = backend.model.forward
    marker = RuntimeError("authored generation callback failed")
    def invasive(**arguments):
        output = original(**arguments)
        torch.rand(7)
        with torch.no_grad():
            parameters[0].add_(1)
            backend.optimizer.state[parameters[0]]["exp_avg"].add_(1)
            parameters[0].grad.add_(1)
        if failure:
            raise marker
        output.logits.fill_(-100)
        output.logits[0, -1, 258] = 100
        return output
    monkeypatch.setattr(backend.model, "forward", invasive)
    if failure:
        with pytest.raises(RuntimeError) as captured:
            backend.generate_batch(source, max_output_tokens=3, execution_guard=lambda: None)
        assert captured.value is marker
    else:
        assert backend.generate_batch(source, max_output_tokens=3, execution_guard=lambda: None)[0]["outcome"] == "abstained"
    assert all(torch.equal(value, backend.model.state_dict()[name]) for name, value in model.items())
    assert backend._same(optimizer, backend.optimizer.state_dict()) and backend._optimizer_steps == 1
    assert torch.equal(rng, torch.get_rng_state())
    assert all(module.training is training for module, training in modes)
    for parameter, (original_grad, saved) in zip(parameters, gradients):
        assert parameter.grad is original_grad
        if original_grad is not None:
            assert torch.equal(parameter.grad, saved)


def test_reviewed_generation_pipeline_mutation_refuses_and_restores_numeric_state(monkeypatch):
    torch, backend, training = _torch_reviewed_backend_fixture()
    source = _reviewed_generation_source_records(training)
    model = {name: value.clone() for name, value in backend.model.state_dict().items()}
    rng = torch.get_rng_state().clone()
    original = backend.model.forward
    def changes_pipeline(**arguments):
        output = original(**arguments)
        _change_reviewed_fixture_pipeline(backend.tokenizer, "frontend_configuration")
        torch.rand(3)
        return output
    monkeypatch.setattr(backend.model, "forward", changes_pipeline)
    with pytest.raises(worker.TrainingJobValidationError, match="tokenizer pipeline changed"):
        backend.generate_batch(source, max_output_tokens=3, execution_guard=lambda: None)
    assert len(backend.model.calls) == 1 and backend._optimizer_steps == 0
    assert torch.equal(rng, torch.get_rng_state()) and backend.model.training is True
    assert all(torch.equal(value, backend.model.state_dict()[name]) for name, value in model.items())


@pytest.mark.parametrize("fault", ["guard", "record"])
def test_reviewed_generation_rechecks_guard_and_source_after_forward(monkeypatch, fault):
    torch, backend, training = _torch_reviewed_backend_fixture()
    source = _reviewed_generation_source_records(training)
    original = backend.model.forward
    failure = RuntimeError("original execution admission withdrawn")
    rng = torch.get_rng_state().clone()
    def changes_source(**arguments):
        output = original(**arguments)
        if fault == "record":
            source[0]["source_token_ids"][1] += 1
        return output
    def guard():
        if fault == "guard" and backend.model.calls:
            raise failure
    monkeypatch.setattr(backend.model, "forward", changes_source)
    with pytest.raises(RuntimeError if fault == "guard" else worker.TrainingJobValidationError) as captured:
        backend.generate_batch(source, max_output_tokens=3, execution_guard=guard)
    if fault == "guard":
        assert captured.value is failure
    assert len(backend.model.calls) == 1 and backend._optimizer_steps == 0
    assert torch.equal(rng, torch.get_rng_state()) and backend.model.training is True


@pytest.mark.parametrize("fault", ["target", "prefix", "bool_id", "source_mismatch", "context_limit", "guard"])
def test_reviewed_generation_refuses_target_or_invalid_source_before_forward(fault):
    torch, backend, training = _torch_reviewed_backend_fixture()
    source = _reviewed_generation_source_records(training)
    guard = lambda: None
    if fault == "target":
        source[0]["target_json"] = training[0]["target_json"]
    elif fault == "prefix":
        source[0]["decoder_input_ids"] = [257]
    elif fault == "bool_id":
        source[0]["source_token_ids"][1] = True
    elif fault == "source_mismatch":
        source[0]["source_token_ids"][1] += 1
    elif fault == "context_limit":
        backend.max_sequence_tokens = 3
    else:
        guard = None
    with pytest.raises(worker.TrainingJobValidationError):
        backend.generate_batch(source, max_output_tokens=3, execution_guard=guard)
    assert backend.model.calls == [] and backend._optimizer_steps == 0
    assert backend.optimizer.state_dict()["state"] == {}


def test_reviewed_generation_parameter_replacement_cannot_claim_exact_restoration(monkeypatch):
    torch, backend, training = _torch_reviewed_backend_fixture()
    source = _reviewed_generation_source_records(training)
    original = backend.model.forward
    parameter = backend.model.embedding.weight
    def replaces_parameter(**arguments):
        output = original(**arguments)
        backend.model.embedding.weight = torch.nn.Parameter(parameter.detach().clone())
        return output
    monkeypatch.setattr(backend.model, "forward", replaces_parameter)
    with pytest.raises(worker.TrainingJobValidationError, match="identity changed"):
        backend.generate_batch(source, max_output_tokens=3, execution_guard=lambda: None)
    assert len(backend.model.calls) == 1
    assert backend.model.embedding.weight is not parameter


def test_reviewed_generation_silent_load_hook_refuses_exact_restoration_and_keeps_failure_context(monkeypatch):
    torch, backend, training = _torch_reviewed_backend_fixture()
    source = _reviewed_generation_source_records(training)
    original = backend.model.forward
    parameter = next(backend.model.parameters())
    before = parameter.detach().clone()
    failure = RuntimeError("original generation forward failed after mutation")
    def mutates_then_fails(**arguments):
        original(**arguments)
        with torch.no_grad():
            parameter.add_(1)
        raise failure
    def silently_does_not_load(state, strict=True):
        return None
    monkeypatch.setattr(backend.model, "forward", mutates_then_fails)
    monkeypatch.setattr(backend.model, "load_state_dict", silently_does_not_load)
    with pytest.raises(worker.TrainingJobValidationError, match="numeric state did not restore exactly") as captured:
        backend.generate_batch(source, max_output_tokens=3, execution_guard=lambda: None)
    assert captured.value.__context__ is failure
    # The API refuses rather than claiming it reversed an uncooperative hook.
    assert not torch.equal(before, parameter)
    assert len(backend.model.calls) == 1 and backend._optimizer_steps == 0


def test_reviewed_generation_optimizer_parameter_replacement_cannot_claim_exact_restoration(monkeypatch):
    torch, backend, training = _torch_reviewed_backend_fixture()
    source = _reviewed_generation_source_records(training)
    original = backend.model.forward
    owned_parameter = backend.optimizer.param_groups[0]["params"][0]
    foreign_parameter = torch.nn.Parameter(owned_parameter.detach().clone())
    def replaces_optimizer_parameter(**arguments):
        output = original(**arguments)
        backend.optimizer.param_groups[0]["params"][0] = foreign_parameter
        return output
    monkeypatch.setattr(backend.model, "forward", replaces_optimizer_parameter)
    with pytest.raises(worker.TrainingJobValidationError, match="identity changed; exact restoration unavailable"):
        backend.generate_batch(source, max_output_tokens=3, execution_guard=lambda: None)
    assert len(backend.model.calls) == 1
    # load_state_dict preserves current group parameter objects. The API must
    # retain that unexpected state and refuse, rather than assert exact rollback.
    assert backend.optimizer.param_groups[0]["params"][0] is foreign_parameter
    assert next(backend.model.parameters()) is owned_parameter


@pytest.mark.parametrize("fault", ["nested_gold_context", "target_in_binding", "missing_context_field"])
def test_reviewed_generation_rejects_nonclosed_nested_source_context_before_forward(fault):
    import json
    torch, backend, training = _torch_reviewed_backend_fixture()
    source = _reviewed_generation_source_records(training)
    wire = json.loads(source[0]["source_wire"])
    if fault == "nested_gold_context":
        wire["governing_context"]["gold_ast"] = {"root": {"kind": "predicate"}}
    elif fault == "target_in_binding":
        wire["source_binding"]["reference_target"] = training[0]["target_json"]
    else:
        del wire["governing_context"]["governing_edition"]
    text = json.dumps(wire, sort_keys=True, separators=(",", ":"))
    source[0]["source_wire"] = text
    source[0]["source_token_ids"] = [257, *backend.tokenizer.encode(text), 258]
    with pytest.raises(worker.TrainingJobValidationError, match="closed scalar source-known v2 context"):
        backend.generate_batch(source, max_output_tokens=3, execution_guard=lambda: None)
    assert backend.model.calls == [] and backend._optimizer_steps == 0
    assert backend.optimizer.state_dict()["state"] == {}


# Reviewed local decoder reconstruction is an opt-in caller operation. These
# source-authored tests grant no model/license/native or legal authority.
def _reviewed_local_loader_denial_inputs(tmp_path):
    from types import SimpleNamespace
    recipe = {"schema": "reviewed-local-decoder-recipe/v1", "architecture": "encoder_decoder",
        "model_type": "t5", "max_sequence_tokens": 4096, "pretrained": False,
        "gradient_clip": 1.0, "optimizer": {"learning_rate": .001, "betas": [.9, .999],
        "eps": 1e-8, "weight_decay": .01}, "tokenizer": {"bos_token": "[BOS]",
        "eos_token": "[EOS]", "unk_token": "[UNK]", "pad_token": "[PAD]",
        "model_max_length": 4096, "clean_up_tokenization_spaces": False}}
    config = {"model_type": "t5", "vocab_size": 260, "d_model": 8, "d_kv": 4,
        "d_ff": 16, "num_layers": 1, "num_decoder_layers": 1, "num_heads": 2,
        "dropout_rate": 0.0, "tie_word_embeddings": False, "bos_token_id": 257,
        "eos_token_id": 0, "pad_token_id": 259, "decoder_start_token_id": 257}
    tokenizer = {"version": "1.0", "truncation": None, "padding": None,
        "added_tokens": [], "normalizer": None, "pre_tokenizer": None,
        "post_processor": None, "decoder": None,
        "model": {"type": "WordLevel", "vocab": {"[EOS]": 0, "[BOS]": 1,
        "[UNK]": 2, "[PAD]": 3}, "unk_token": "[UNK]"}}
    data = {"recipe_artifact": worker._json_bytes(recipe),
        "model_config_artifact": worker._json_bytes(config),
        "tokenizer_artifact": worker._json_bytes(tokenizer),
        "license_artifact": worker._json_bytes({"fictional_fixture_only": True}),
        "model_checkpoint": b"guard-denied-unread-model-state",
        "optimizer_checkpoint": b"guard-denied-unread-optimizer-state"}
    artifacts = {name: worker.CheckpointArtifact.from_dict(_complete_reviewed_artifact(
        tmp_path / (name + ".fixture"), body)) for name, body in data.items()}
    def no_registry(*args, **kwargs):
        pytest.fail("denied local loading touched a target or training registry")
    return {**artifacts, "registry": SimpleNamespace(read_artifact=no_registry, artifact_path=no_registry),
        "expected_backend_identity": {"backend_id": "fixture:guard-denied-local-decoder",
            "implementation_sha256": hashlib.sha256(Path(worker.__file__).read_bytes()).hexdigest(),
            "checkpoint_format": "torch-weights-only-complete-reviewed-state-pair/v2",
            "target_codec": "complete-reviewed-norm-json/v2", "source_conditioned": True,
            "pretrained": False}, "expected_source_sha256": worker._reviewed_decoder_source_pins(),
        "expected_admission_inputs_sha256": "0" * 64, "max_model_bytes": 64 * 1024**2}


def test_reviewed_local_loader_execution_denial_precedes_model_import_and_preserves_error(tmp_path, monkeypatch):
    import builtins
    options = _reviewed_local_loader_denial_inputs(tmp_path)
    class OriginalExecutionDenied(RuntimeError):
        pass
    denied = OriginalExecutionDenied("original caller execution permission denied")
    calls = []
    def execution_guard():
        calls.append("execution")
        raise denied
    def forbidden_policy(*args, **kwargs):
        pytest.fail("denied execution reached asset or admission policy")
    original_import = builtins.__import__
    def no_model_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("model package imported before original execution denial: " + name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_model_import)
    with pytest.raises(OriginalExecutionDenied) as captured:
        worker.load_local_reviewed_decoder_runtime(**options, execution_guard=execution_guard,
            asset_policy_guard=forbidden_policy, current_admission_provider=forbidden_policy)
    assert captured.value is denied and calls == ["execution"]


def _reviewed_local_loader_fixed_schema_bpe(vocabulary):
    """Lossless fixed schema subwords, never fitted to query/source/gold data.

    Every pattern is an ordinary JSON/IR field name, punctuation or grammar
    tag. No input data, corpus, reference, predicate or answer enters this
    function. This small tokenizer fixture makes complete structural records
    practical under the same fixed context-token bound; it drops no bytes.
    """
    fields = ("profile schema typed_expression argument_roles assumptions governing_context "
        "interpretation_id source_binding definition_uses cross_references jurisdiction instrument_id "
        "governing_edition legal_as_of_utc valid_from_utc valid_until_utc source_version_cid "
        "occurrence_cid document_revision unit_id source_text source_link selection_role retrieved_example "
        "definition_unit_id defined_predicate use_unit_id use_occurrence_cid target_typed_paths "
        "applicability evidence_refs node_id kind symbol name sort arguments binders body variable "
        "predicate quantifier operator root nodes reference id content permitted retrieved context mode "
        "rich_full_ast role roles predicate_symbol argument_index parameter_index binding_id typed_path "
        "start_char end_char start_utf8 end_utf8 source_sha256 artifact_id sha256").split()
    patterns = [*fields, *("\"" + field + "\":" for field in fields),
        "\":", "\",\"", "},{", "}}", "]}", "],", "null", "true", "false",
        "forall", "implies", "iff", "atom", "modal", "not"]
    ranks, merges = {}, []

    def existing_pieces(text):
        pieces = list(text)
        while len(pieces) > 1:
            choices = [(ranks[tuple(pieces[index:index + 2])], index)
                       for index in range(len(pieces) - 1)
                       if tuple(pieces[index:index + 2]) in ranks]
            if not choices:
                break
            _, index = min(choices)
            pieces[index:index + 2] = ["".join(pieces[index:index + 2])]
        return pieces

    for pattern in patterns:
        pieces = existing_pieces(pattern)
        while len(pieces) > 1:
            pair = tuple(pieces[:2])
            assert pair not in ranks and all(part in vocabulary for part in pair)
            joined = "".join(pair)
            if joined not in vocabulary:
                vocabulary[joined] = len(vocabulary)
            ranks[pair] = len(merges)
            merges.append(pair)
            pieces[:2] = [joined]
    assert len(merges) < 1024 and len(vocabulary) < 2048
    return merges


def _reviewed_local_loader_fixed_typed_schema_bpe(vocabulary):
    """Additional public AST schema words; no source, predicate or target input.

    Add independently reusable schema suffixes and grammar tags to the original
    compound patterns. Inputs are only public format names, retaining every
    input byte and the original tokenizer fixture as its unchanged baseline.
    """
    merges=_reviewed_local_loader_fixed_schema_bpe(vocabulary)
    ranks={tuple(pair):index for index,pair in enumerate(merges)}
    fields=("content_digest expression_id schema_version family interface metadata signature signature_id "
        "sorts symbols result_sort argument_sorts parameter_sorts return_sort binder_kind namespace value "
        "source_kind declaration_id symbol_kind arity variadic predicate constant function connective "
        "extension symbol_declaration source_range start end line column offset annotations parameters "
        "scope_id bound_variables free_variables logical_profile signature_digest encoding_version "
        "Object EventFrame TimeFrame Formula Prop Bool tdfol tdfol_default logic identity typed "
        "expression digest version source binding argument roles definition uses references occurrence "
        "governing context interpretation policy artifact relation semantic entity structural mapping").split()
    patterns=list(dict.fromkeys(piece for field in fields for piece in field.split("_")))
    # Exhaustive lowercase ASCII/digit triples are an input-independent codec,
    # including arbitrary provenance hashes; they never inspect a source/target.
    from itertools import product
    patterns.extend("".join(chars) for chars in product("0123456789abcdefghijklmnopqrstuvwxyz",repeat=3))
    # Public serialization syntax only. No fixture, legal text, predicate,
    # selected interpretation, reference payload or corpus enters this scan.
    import ast as python_ast
    import re
    from ipfs_datasets_py.logic.syntax_core import ast as syntax_ast, signatures
    from ipfs_datasets_py.logic.legal_ir import canonical_contracts
    literals=set(fields)
    for owner in (syntax_ast,signatures,canonical_contracts):
        tree=python_ast.parse(Path(owner.__file__).read_text())
        literals.update(node.value for node in python_ast.walk(tree)
            if isinstance(node,python_ast.Constant) and type(node.value) is str
            and 1<=len(node.value)<=80 and re.fullmatch(r"[A-Za-z0-9_.:/-]+",node.value))
    for literal in sorted(literals):
        patterns.extend((literal,'"'+literal+'"','"'+literal+'":'))

    for pattern in patterns:
        pieces=list(pattern)
        while len(pieces)>1:
            available=[(ranks[tuple(pieces[i:i+2])],i) for i in range(len(pieces)-1)
                       if tuple(pieces[i:i+2]) in ranks]
            if not available:break
            _,i=min(available);pieces[i:i+2]=["".join(pieces[i:i+2])]
        while len(pieces)>1:
            pair=tuple(pieces[:2]);joined="".join(pair)
            if joined not in vocabulary:vocabulary[joined]=len(vocabulary)
            if pair not in ranks:
                ranks[pair]=len(merges);merges.append(pair)
            pieces[:2]=[joined]
    assert len(merges)<65536 and len(vocabulary)<65536
    return merges


def _reviewed_local_loader_hf_fixture(tmp_path, architecture="encoder_decoder", *, admission_provider=None,
        max_sequence_tokens=2048, fixed_json_schema_subwords=False, fixed_typed_schema_subwords=False,
        local_model_profile=None):
    """Independent actual built-in HF checkpoint, never loaded or trained by the loader.

    A genuine fixture AdamW update creates nontrivial moments. Afterwards the
    real model parameters are zeroed, retaining that Adam history: actual raw
    head logits tie at zero and EOS token zero wins argmax without a scripted
    forward or reference answer. This is an abstention fixture, not model gain.
    """
    from copy import deepcopy
    from types import SimpleNamespace
    import torch
    from tokenizers import Tokenizer, AddedToken, models, pre_tokenizers, decoders
    from transformers import PreTrainedTokenizerFast, T5Config, T5ForConditionalGeneration, GPT2Config, GPT2LMHeadModel
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    assert type(max_sequence_tokens) is int and 2048 <= max_sequence_tokens <= 4096
    assert type(fixed_json_schema_subwords) is bool
    assert type(fixed_typed_schema_subwords) is bool and (not fixed_typed_schema_subwords or fixed_json_schema_subwords)
    assert local_model_profile in (None, "builtin-llama-bfloat16/v1", "builtin-qwen2-bfloat16/v1")
    qwen2 = local_model_profile == "builtin-qwen2-bfloat16/v1"
    assert local_model_profile is None or architecture == "causal_lm"
    directory = tmp_path / architecture
    directory.mkdir()
    torch.manual_seed(1701)
    vocabulary = {"[EOS]": 0, **{value: index + 1 for index, value in enumerate(sorted(pre_tokenizers.ByteLevel.alphabet()))},
                  "[BOS]": 257, "[UNK]": 258, "[PAD]": 259}
    merges = (_reviewed_local_loader_fixed_typed_schema_bpe(vocabulary) if fixed_typed_schema_subwords
              else _reviewed_local_loader_fixed_schema_bpe(vocabulary) if fixed_json_schema_subwords else [])
    vocab_size = len(vocabulary)
    native = (Tokenizer(models.Unigram([(token,-1.0) for token,index in
        sorted(vocabulary.items(),key=lambda pair:pair[1])],unk_id=258)) if fixed_typed_schema_subwords
        else Tokenizer(models.BPE(vocab=vocabulary, merges=merges, unk_token="[UNK]")))
    native.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)
    native.decoder = decoders.ByteLevel()
    native.add_special_tokens([AddedToken(value, normalized=False, special=True)
                               for value in ("[EOS]", "[BOS]", "[UNK]", "[PAD]")])
    token_options = {"bos_token": "[BOS]", "eos_token": "[EOS]", "unk_token": "[UNK]",
        "pad_token": "[PAD]", "model_max_length": max_sequence_tokens, "clean_up_tokenization_spaces": False}
    frontend = PreTrainedTokenizerFast(tokenizer_object=native, **token_options)
    tokenizer = worker.ReviewedPretrainedTokenizer(frontend, bos_token_id=257, eos_token_id=0, vocab_size=vocab_size)
    if architecture == "encoder_decoder":
        configuration = T5Config(vocab_size=vocab_size, d_model=8, d_kv=4, d_ff=16, num_layers=1,
            num_decoder_layers=1, num_heads=2, dropout_rate=0.0, tie_word_embeddings=fixed_typed_schema_subwords,
            bos_token_id=257, eos_token_id=0, pad_token_id=259, decoder_start_token_id=257)
        model_class = T5ForConditionalGeneration
    elif qwen2:
        from transformers import Qwen2Config, Qwen2ForCausalLM
        configuration = Qwen2Config(vocab_size=vocab_size+8, hidden_size=8, intermediate_size=16,
            num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, max_position_embeddings=max_sequence_tokens,
            attention_dropout=0.0, use_sliding_window=False, tie_word_embeddings=True,
            bos_token_id=257, eos_token_id=0, pad_token_id=259, dtype="bfloat16")
        model_class = Qwen2ForCausalLM
    elif local_model_profile is not None:
        from transformers import LlamaConfig, LlamaForCausalLM
        configuration = LlamaConfig(vocab_size=vocab_size, hidden_size=8, intermediate_size=16,
            num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1, max_position_embeddings=max_sequence_tokens,
            attention_dropout=0.0, attention_bias=False, mlp_bias=False, tie_word_embeddings=True,
            bos_token_id=257, eos_token_id=0, pad_token_id=259, dtype="bfloat16")
        model_class = LlamaForCausalLM
    else:
        configuration = GPT2Config(vocab_size=vocab_size, n_positions=max_sequence_tokens, n_ctx=max_sequence_tokens, n_embd=8,
            n_layer=1, n_head=2, resid_pdrop=0.0, embd_pdrop=0.0, attn_pdrop=0.0,
            tie_word_embeddings=False, bos_token_id=257, eos_token_id=0, pad_token_id=259)
        model_class = GPT2LMHeadModel
    configuration._attn_implementation = "eager"
    model = model_class(configuration).to(device="cpu", dtype=torch.bfloat16 if local_model_profile else torch.float32)
    if local_model_profile is not None:
        from transformers.models.llama.modeling_llama import LlamaRotaryEmbedding
        if qwen2:
            from transformers.models.qwen2.modeling_qwen2 import Qwen2RotaryEmbedding
            independent_rope = Qwen2RotaryEmbedding(configuration)
        else:
            independent_rope = LlamaRotaryEmbedding(configuration)
        for name in ("inv_freq", "original_inv_freq"):
            model.model.rotary_emb._buffers[name] = independent_rope._buffers[name].detach().clone()
    optimizer_options = {"learning_rate": .001, "betas": [.9, .999], "eps": 1e-8, "weight_decay": .01}
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, betas=(.9, .999), eps=1e-8,
        weight_decay=.01, amsgrad=False, maximize=False, foreach=False, capturable=False,
        differentiable=False, fused=False)
    input_ids = torch.tensor([[257, 65, 66, 0]], dtype=torch.long)
    labels = torch.tensor([[67, 0]], dtype=torch.long) if architecture == "encoder_decoder" else input_ids.clone()
    loss = model(input_ids=input_ids, attention_mask=torch.ones_like(input_ids), labels=labels).loss
    assert bool(torch.isfinite(loss))
    loss.backward()
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)
    assert optimizer.state and any(bool(value["exp_avg"].ne(0).any()) for value in optimizer.state.values())
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
    backend = worker.TorchReviewedDecoderBackend(model, optimizer, tokenizer, architecture=architecture,
        max_sequence_tokens=max_sequence_tokens, pretrained=False, gradient_clip=1.0,
        **({"model_profile": local_model_profile} if qwen2 else {}))
    backend._optimizer_steps = 1  # The independent fixture performed the real update above.
    torch.manual_seed(271828)
    checkpoint = backend.snapshot_checkpoint()
    pair_rng = torch.get_rng_state().clone()
    def artifact(name, body):
        return worker.CheckpointArtifact.from_dict(_complete_reviewed_artifact(directory / name, body))
    recipe = {"schema": "reviewed-local-decoder-recipe/v1", "architecture": architecture,
        "model_type": "t5" if architecture == "encoder_decoder" else "gpt2", "max_sequence_tokens": max_sequence_tokens,
        "pretrained": False, "gradient_clip": 1.0, "optimizer": optimizer_options, "tokenizer": token_options}
    if local_model_profile is not None:
        recipe.update(schema="reviewed-local-decoder-recipe/v2", model_type="qwen2" if qwen2 else "llama", parameter_dtype="bfloat16")
    artifacts = {"recipe_artifact": artifact("recipe.json", worker._json_bytes(recipe)),
        "model_config_artifact": artifact("config.json", worker._json_bytes(model.config.to_dict())),
        "tokenizer_artifact": artifact("tokenizer.json", native.to_str().encode()),
        "license_artifact": artifact("license.json", worker._json_bytes({"fictional_fixture_only": True,
            "pretrained_license_or_model_quality_authorized": False})),
        "model_checkpoint": artifact("model.pt", checkpoint["model_state"]),
        "optimizer_checkpoint": artifact("optimizer.pt", checkpoint["optimizer_state"])}
    generation = {"current_fixture_generation": 0}
    provider = admission_provider if admission_provider is not None else lambda: deepcopy(generation)
    guards = {"execution": 0, "asset": 0}
    def execution():
        guards["execution"] += 1
    def asset_policy(policy):
        guards["asset"] += 1
        assert policy["training_requested"] is False
        assert all(policy.get(name, False) is False for name in ("downloads_requested", "resource_grant_requested"))
    def no_registry(*args, **kwargs):
        pytest.fail("local inference loader accessed a target or training registry")
    options = {**artifacts, "registry": SimpleNamespace(read_artifact=no_registry, artifact_path=no_registry),
        "current_admission_provider": provider, "execution_guard": execution, "asset_policy_guard": asset_policy,
        "expected_backend_identity": backend.identity(), "expected_source_sha256": worker._reviewed_decoder_source_pins(),
        "expected_admission_inputs_sha256": consumer.reviewed_admission_inputs_sha256(provider()),
        "max_model_bytes": 64 * 1024**2}
    if local_model_profile is not None:
        options["runtime_profile"] = local_model_profile
    return SimpleNamespace(torch=torch, backend=backend, checkpoint=checkpoint, pair_rng=pair_rng,
        model_class=model_class, options=options, generation=generation, guards=guards, artifact=artifact)


def _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture):
    import transformers
    import huggingface_hub
    import transformers.utils.hub
    def forbidden(*args, **kwargs):
        pytest.fail("local reviewed reconstruction entered download, remote-code, from_pretrained or training")
    for name in ("PreTrainedModel", "PreTrainedTokenizerBase", "AutoConfig", "AutoTokenizer",
                 "AutoModelForSeq2SeqLM", "AutoModelForCausalLM"):
        monkeypatch.setattr(getattr(transformers, name), "from_pretrained", forbidden)
    for module in (huggingface_hub, transformers.utils.hub):
        monkeypatch.setattr(module, "hf_hub_download", forbidden)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", forbidden)
    monkeypatch.setattr(fixture.torch.optim.AdamW, "step", forbidden)
    monkeypatch.setattr(worker.TorchReviewedDecoderBackend, "train_batch", forbidden)


def _reviewed_local_loader_source_record(tokenizer):
    source = {"profile": "reviewed-source-selection-context/v2", "source_text": "A fixture clerk must file.",
        "governing_context": {"jurisdiction": "fixture:us", "instrument_id": "fixture:act",
            "governing_edition": "fixture:v1", "legal_as_of_utc": "2026-01-02T00:00:00Z",
            "valid_from_utc": "2026-01-01T00:00:00Z", "valid_until_utc": None},
        "source_binding": {"source_version_cid": "fixture:source", "occurrence_cid": "fixture:span",
            "document_revision": "fixture:v1"},
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": "fixture:independent", "selection_mode": "identifier_only"}}
    wire = worker._json_bytes(source).decode()
    return {"id": "fixture:one", "unit_id": "fixture:norm", "source_wire": wire,
        "source_token_ids": [tokenizer.bos_token_id, *tokenizer.encode(wire), tokenizer.eos_token_id]}


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_local_loader_restores_independent_builtin_checkpoint_and_generates_from_bos(tmp_path, monkeypatch, architecture):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, architecture)
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    fixture.torch.manual_seed(987654)
    from copy import deepcopy
    expected_configuration = deepcopy(fixture.backend._configuration())
    expected_tokenizer_pipeline = worker._parse_json(fixture.backend.tokenizer.pipeline_serialization())
    actual_identity_observations = []
    real_identity = worker.TorchReviewedDecoderBackend.identity
    def observe_real_identity(backend):
        actual_configuration = deepcopy(backend._configuration())
        identity = real_identity(backend)
        if backend is not fixture.backend:
            actual_identity_observations.append((actual_configuration, deepcopy(identity),
                worker._parse_json(backend.tokenizer.pipeline_serialization())))
        return identity
    monkeypatch.setattr(worker.TorchReviewedDecoderBackend, "identity", observe_real_identity)
    try:
        runtime, receipt = worker.load_local_reviewed_decoder_runtime(**fixture.options)
    except worker.TrainingJobValidationError as error:
        if str(error) != "local constructed decoder backend identity differs":
            raise
        if not actual_identity_observations:
            pytest.fail("local constructed identity refused without an observed real configuration", pytrace=False)
        actual_configuration, actual_identity, actual_tokenizer_pipeline = actual_identity_observations[-1]
        pytest.fail("original loader identity guard refused; bounded independent configuration DIFF: " +
            _reviewed_local_loader_configuration_difference(
                {"backend_configuration": expected_configuration, "tokenizer_pipeline": expected_tokenizer_pipeline},
                {"backend_configuration": actual_configuration, "tokenizer_pipeline": actual_tokenizer_pipeline},
                fixture.options["expected_backend_identity"], actual_identity), pytrace=False)
    assert type(runtime) is worker.ReviewedDecoderRuntime and type(runtime.backend.model) is fixture.model_class
    assert runtime.backend is not fixture.backend and runtime.backend.model is not fixture.backend.model
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"]) is True
    assert fixture.torch.equal(fixture.torch.get_rng_state(), fixture.pair_rng)
    assert receipt["checkpoint_restored"] is receipt["matched_pair"] is True and receipt["optimizer_steps"] == 1
    assert receipt["loaded_backend_identity"] == fixture.options["expected_backend_identity"]
    assert receipt["attention_implementation"] == "eager" and receipt["device"] == "cpu" and receipt["dtype"] == "float32"
    assert all(receipt[name] is False for name in ("training_performed", "downloads_performed", "resource_granted",
        "license_bytes_are_permission", "pretrained_quality_verified", "legal_meaning_verified", "proof_authority", "convergence_proved"))
    assert 0 < receipt["model_unique_tensor_bytes"] <= fixture.options["max_model_bytes"]
    assert any(bool(value["exp_avg"].ne(0).any()) for value in runtime.backend.optimizer.state.values())
    record = _reviewed_local_loader_source_record(runtime.tokenizer)
    calls = []
    def observe_forward(module, args, kwargs):
        calls.append({name: value.detach().cpu().tolist() for name, value in kwargs.items() if fixture.torch.is_tensor(value)})
        assert "labels" not in kwargs
    hook = runtime.backend.model.register_forward_pre_hook(observe_forward, with_kwargs=True)
    try:
        outputs = runtime.backend.generate_batch([record], max_output_tokens=3, execution_guard=runtime.execution_guard)
    finally:
        hook.remove()
    assert len(calls) == 1 and outputs[0]["generated_token_ids"] == [257, 0]
    assert outputs[0]["outcome"] == "abstained" and outputs[0]["candidate"] is None
    if architecture == "encoder_decoder":
        assert calls[0]["input_ids"] == [record["source_token_ids"]]
        assert calls[0]["decoder_input_ids"] == [[257]]
    else:
        assert calls[0]["input_ids"] == [[*record["source_token_ids"], 257]]
    assert runtime.backend._optimizer_steps == 1 and runtime.backend.restored_checkpoint_matches(
        fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"]) is True


def test_reviewed_local_loader_asset_denial_precedes_model_import_and_preserves_error(tmp_path, monkeypatch):
    import builtins
    options = _reviewed_local_loader_denial_inputs(tmp_path)
    denied = PermissionError("original independent asset policy denied")
    def asset_policy(policy):
        raise denied
    original_import = builtins.__import__
    def no_model_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("model package imported before original asset denial: " + name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_model_import)
    with pytest.raises(PermissionError) as captured:
        worker.load_local_reviewed_decoder_runtime(**options, execution_guard=lambda: None,
            asset_policy_guard=asset_policy, current_admission_provider=lambda: pytest.fail("admission read after asset denial"))
    assert captured.value is denied


@pytest.mark.parametrize("field", ["model_config_artifact", "tokenizer_artifact", "license_artifact", "model_checkpoint"])
def test_reviewed_local_loader_changed_asset_refuses_before_model_and_preserves_cpu_rng(tmp_path, monkeypatch, field):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path)
    entry = fixture.torch.get_rng_state().clone()
    path = Path(fixture.options[field].path)
    path.write_bytes(path.read_bytes() + b" ")
    monkeypatch.setattr(fixture.model_class, "__init__", lambda *args, **kwargs: pytest.fail("changed asset reached model constructor"))
    with pytest.raises(worker.TrainingJobValidationError):
        worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert fixture.torch.equal(fixture.torch.get_rng_state(), entry)


def test_reviewed_local_loader_changed_source_refuses_before_model_import(tmp_path, monkeypatch):
    import builtins
    options = _reviewed_local_loader_denial_inputs(tmp_path)
    options["expected_source_sha256"]["inputs"] = "0" * 64
    original_import = builtins.__import__
    def no_model_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("changed producer Source reached model package import: " + name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_model_import)
    with pytest.raises(worker.TrainingJobValidationError) as captured:
        worker.load_local_reviewed_decoder_runtime(**options, execution_guard=lambda: None,
            asset_policy_guard=lambda policy: None, current_admission_provider=lambda: {})
    assert "source" in str(captured.value).lower()


def test_reviewed_local_loader_fresh_late_admission_change_refuses_and_preserves_cpu_rng(tmp_path, monkeypatch):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path)
    entry = fixture.torch.get_rng_state().clone()
    original = fixture.torch.nn.Module.to_empty
    calls = []
    def allocate_then_change(module, *args, **kwargs):
        result = original(module, *args, **kwargs)
        calls.append(True)
        fixture.generation["current_fixture_generation"] += 1
        return result
    monkeypatch.setattr(fixture.torch.nn.Module, "to_empty", allocate_then_change)
    with pytest.raises(worker.TrainingJobValidationError):
        worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert calls and fixture.torch.equal(fixture.torch.get_rng_state(), entry)


def test_reviewed_local_loader_model_byte_bound_refuses_before_cpu_allocation(tmp_path, monkeypatch):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path)
    fixture.options["max_model_bytes"] = 1
    entry = fixture.torch.get_rng_state().clone()
    monkeypatch.setattr(fixture.torch.nn.Module, "to_empty", lambda *args, **kwargs: pytest.fail("over-budget model allocated CPU storage"))
    with pytest.raises(worker.TrainingJobValidationError):
        worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert fixture.torch.equal(fixture.torch.get_rng_state(), entry)


@pytest.mark.parametrize("architecture,dimension", [("encoder_decoder", "num_layers"), ("causal_lm", "n_positions")])
def test_reviewed_local_loader_huge_dimensions_refuse_before_model_constructor(tmp_path, monkeypatch, architecture, dimension):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, architecture)
    config = json.loads(Path(fixture.options["model_config_artifact"].path).read_bytes())
    config[dimension] = 10**9
    fixture.options["model_config_artifact"] = fixture.artifact("huge-config.json", worker._json_bytes(config))
    entry = fixture.torch.get_rng_state().clone()
    monkeypatch.setattr(fixture.model_class, "__init__", lambda *args, **kwargs: pytest.fail("huge dimension reached model constructor"))
    with pytest.raises(worker.TrainingJobValidationError):
        worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert fixture.torch.equal(fixture.torch.get_rng_state(), entry)


@pytest.mark.parametrize("alias,value", [("_attn_implementation", "kernels-community/flash-attn"), ("attn_implementation", "sdpa")])
def test_reviewed_local_loader_non_eager_attention_refuses_before_model_constructor(tmp_path, monkeypatch, alias, value):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path)
    config = json.loads(Path(fixture.options["model_config_artifact"].path).read_bytes())
    config[alias] = value
    fixture.options["model_config_artifact"] = fixture.artifact("non-eager-config.json", worker._json_bytes(config))
    entry = fixture.torch.get_rng_state().clone()
    monkeypatch.setattr(fixture.model_class, "__init__", lambda *args, **kwargs: pytest.fail("non-eager kernel path reached model constructor"))
    with pytest.raises(worker.TrainingJobValidationError):
        worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert fixture.torch.equal(fixture.torch.get_rng_state(), entry)


def test_reviewed_local_loader_incompatible_optimizer_configuration_refuses_and_preserves_cpu_rng(tmp_path):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path)
    fixture.backend.optimizer.param_groups[0]["lr"] = .002
    changed = fixture.backend.snapshot_checkpoint()
    fixture.options["optimizer_checkpoint"] = fixture.artifact("incompatible-optimizer.pt", changed["optimizer_state"])
    entry = fixture.torch.get_rng_state().clone()
    with pytest.raises(worker.TrainingJobValidationError):
        worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert fixture.torch.equal(fixture.torch.get_rng_state(), entry)


def test_reviewed_local_loader_real_t5_flows_into_signed_heldout_evaluation_without_gold(tmp_path, monkeypatch):
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    consumer_helper, helper, admission, current, rows, consumer_options, evaluation_options = evaluation._producer_public_heldout_case()
    def fresh():
        return deepcopy(consumer_helper.reviewed_public_admission_inputs(helper, admission, current))
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, admission_provider=fresh)
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    runtime, load_receipt = worker.load_local_reviewed_decoder_runtime(**fixture.options)
    declaration = current["declaration"]
    contexts = {"profile": "reviewed-source-selection-context/v2",
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": declaration["interpretation_id"], "selection_mode": "identifier_only"},
        "rows": [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
            "governing_context": deepcopy(declaration["governing_context"]),
            "source_binding": {"source_version_cid": unit["source_version"]["record_cid"],
                "occurrence_cid": unit["occurrence"]["record_cid"], "document_revision": unit["document_revision"]}}
            for unit in declaration["units"]]}
    producer = worker.make_reviewed_decoder_source_producer(runtime, binding=evaluation_options["binding"], rows=rows,
        split_manifest=consumer_options["split_manifest"], exposure_records=consumer_options["exposure_records"],
        source_contexts=contexts, expected_source_contexts_sha256=evaluation._producer_digest(contexts),
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(fresh()),
        backend_identity=fixture.options["expected_backend_identity"],
        assets=tuple(fixture.options[name] for name in ("recipe_artifact", "model_config_artifact", "tokenizer_artifact", "license_artifact")),
        model_checkpoint=fixture.options["model_checkpoint"], optimizer_checkpoint=fixture.options["optimizer_checkpoint"],
        max_source_tokens=2048, max_output_tokens=3, allow_heldout_evaluation=True)
    artifact = producer.evaluate(compiler_commit="fixture:local-loader-signed-source-evaluation",
        checkpoint_declarations={"encoder": {"id": "fixture:source-encoder-declaration-only", "sha256": "1" * 64},
            "decoder": {"id": fixture.options["expected_backend_identity"]["backend_id"],
                "sha256": fixture.options["model_checkpoint"].sha256}})
    payload = evaluation._producer_payload(artifact)
    report = artifact.to_dict()["metrics"]["complete_norm_payload"]
    observation = producer.observation()
    assert load_receipt["matched_pair"] is True
    assert report["denominator"] == report["outcome_counts"]["abstained"] == 3
    assert report["metric_numerators"]["full_nine_payload_exact"] == 0
    assert all(item["generated_token_ids"] == [257, 0] and item["candidate"] is None
               for item in observation["last_call"]["raw_generation_outputs"])
    assert observation["last_call"]["input_receipt"]["target_access_performed"] is False
    assert observation["last_call"]["entry_pair_match"] is observation["last_call"]["exit_pair_match"] is True
    assert payload["admission_before"]["training_mask"] == payload["admission_after"]["evaluation_gold_mask"] == 0
    assert payload["configuration"]["input_profile"]["profile_id"] == observation["input_profile_id"]
    assert all(payload[key] is False for key in ("producer_authenticity_verified", "loaded_checkpoint_identity_verified",
        "native_proof_verified", "source_fidelity_proved", "semantic_equivalence_proved", "corpus_admitted", "token_budget_enforced"))



def _reviewed_local_loader_configuration_difference(expected, actual, expected_identity, actual_identity):
    """Bounded type-aware diagnostics only; never normalize or repair identity."""
    differences = []
    state = {"nodes": 0, "truncated": False}
    def summary(value):
        rendered = repr(value)
        return {"type": type(value).__name__, "repr": rendered[:180]}
    def note(path, left, right, reason):
        if len(differences) >= 48:
            state["truncated"] = True
            return
        differences.append({"path": path[:512], "reason": reason,
            "expected": summary(left), "actual": summary(right)})
    def visit(left, right, path, depth):
        state["nodes"] += 1
        if state["nodes"] > 20000 or depth > 32 or len(differences) >= 48:
            state["truncated"] = True
            return
        if type(left) is not type(right):
            note(path, left, right, "different Python value types")
        elif isinstance(left, dict):
            left_keys = {(type(key).__name__, repr(key)): key for key in left}
            right_keys = {(type(key).__name__, repr(key)): key for key in right}
            for token in sorted(set(left_keys) | set(right_keys)):
                child = path + "/" + token[0] + ":" + token[1]
                if token not in left_keys:
                    note(child, "<missing key>", right[right_keys[token]], "actual-only typed key")
                elif token not in right_keys:
                    note(child, left[left_keys[token]], "<missing key>", "expected-only typed key")
                else:
                    visit(left[left_keys[token]], right[right_keys[token]], child, depth + 1)
                if len(differences) >= 48:
                    state["truncated"] = True
                    break
        elif isinstance(left, (list, tuple)):
            if len(left) != len(right):
                note(path + "/length", len(left), len(right), "different sequence length")
            for index, (one, two) in enumerate(zip(left, right)):
                visit(one, two, path + "/" + str(index), depth + 1)
                if len(differences) >= 48:
                    state["truncated"] = True
                    break
        elif left != right:
            note(path, left, right, "different value")
    visit(expected, actual, "$", 0)
    report = {"expected_identity": expected_identity, "real_actual_identity": actual_identity,
        "expected_configuration_sha256": hashlib.sha256(worker._json_bytes(expected)).hexdigest(),
        "actual_configuration_sha256": hashlib.sha256(worker._json_bytes(actual)).hexdigest(),
        "differences": differences, "visited_nodes": state["nodes"], "truncated": state["truncated"]}
    rendered = json.dumps(report, sort_keys=True, ensure_ascii=True, allow_nan=False)
    return rendered[:16000]



def test_reviewed_local_loader_recipe_json_member_order_does_not_change_fixed_constructor(tmp_path, monkeypatch):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path)
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    original = json.loads(Path(fixture.options["recipe_artifact"].path).read_bytes())
    reversed_recipe = {name: original[name] for name in reversed(original)}
    reversed_recipe["tokenizer"] = {name: original["tokenizer"][name] for name in reversed(original["tokenizer"])}
    raw = json.dumps(reversed_recipe, sort_keys=False, indent=2, ensure_ascii=True, allow_nan=False).encode()
    parsed = json.loads(raw)
    assert parsed == original
    assert list(parsed) == list(reversed(original)) and list(parsed) != list(original)
    assert list(parsed["tokenizer"]) == list(reversed(original["tokenizer"]))
    assert list(parsed["tokenizer"]) != list(original["tokenizer"])
    fixture.options["recipe_artifact"] = fixture.artifact("recipe-reversed-member-order.json", raw)
    expected_pipeline = worker._parse_json(fixture.backend.tokenizer.pipeline_serialization())
    runtime, receipt = worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert runtime.backend.identity() == fixture.options["expected_backend_identity"]
    assert worker._parse_json(runtime.tokenizer.pipeline_serialization()) == expected_pipeline
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"]) is True
    assert fixture.torch.equal(fixture.torch.get_rng_state(), fixture.pair_rng)
    assert receipt["matched_pair"] is True and receipt["checkpoint_restored"] is True
    recipe_identity = receipt["json_artifact_identities"]["recipe"]
    assert recipe_identity["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert recipe_identity["canonical_json_sha256"] == hashlib.sha256(worker._json_bytes(original)).hexdigest()



def test_reviewed_tokenizer_method_fingerprint_is_stable_across_hash_seeds(tmp_path):
    """Execute only pinned fingerprint definitions in two sequential stdlib processes."""
    import subprocess
    import sys
    import time
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import resource_operation_deadline

    worker_path = Path(worker.__file__).resolve(strict=True)
    worker_sha256 = hashlib.sha256(worker_path.read_bytes()).hexdigest()
    probe_source = r"""
import __future__, ast, hashlib, json, math, marshal, sys, types
from pathlib import Path
worker_path, expected_sha256 = sys.argv[1:]
raw = Path(worker_path).read_bytes()
assert hashlib.sha256(raw).hexdigest() == expected_sha256, 'pinned worker changed'
required = {'TrainingJobValidationError', '_digest', '_reviewed_tokenizer_configuration', '_reviewed_tokenizer_method'}
selected = [node for node in ast.parse(raw, filename=worker_path).body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef))
            and node.name in required | {'_reviewed_tokenizer_code_bytes'}]
assert required <= {node.name for node in selected}
namespace = dict(__name__='reviewed_hash_seed_fixture', hashlib=hashlib, math=math,
                 marshal=marshal, types=types, MAX_REVIEWED_TOKENIZER_PIPELINE_BYTES=32*1024*1024)
exec(compile(ast.Module(body=selected, type_ignores=[]), worker_path, 'exec',
             flags=__future__.annotations.compiler_flag, dont_inherit=True), namespace)
sample_namespace = {'__name__': 'reviewed_hash_seed_sample'}
sample_source = 'def sample(value=None):\n    return value in {"amber-one", "birch-two", "cedar-three", "dahlia-four", "elm-five", "fir-six", "ginkgo-seven", "hazel-eight", "iris-nine", "juniper-ten", "kelp-eleven", "larch-twelve", "maple-thirteen", "nettle-fourteen", "oak-fifteen", "pine-sixteen"}\n'
exec(compile(sample_source, '<reviewed-hash-seed-sample>', 'exec', dont_inherit=True), sample_namespace)
sample = sample_namespace['sample']
assert any(type(item) is frozenset and len(item) >= 12 for item in sample.__code__.co_consts)
fingerprint = namespace['_reviewed_tokenizer_method'](sample)
assert fingerprint['module'] == 'reviewed_hash_seed_sample' and fingerprint['qualname'] == 'sample'
assert fingerprint['kind'] == 'python_code'
assert not any(name.split('.')[0] in {'torch', 'transformers', 'tokenizers', 'ipfs_datasets_py'} for name in sys.modules)
print(json.dumps({'worker_sha256': expected_sha256, 'fingerprint': fingerprint}, sort_keys=True, allow_nan=False))
"""
    probe = tmp_path / "reviewed-tokenizer-hash-seed-probe.py"
    with probe.open("x", encoding="utf-8") as stream:
        stream.write(probe_source)
        stream.flush()
        os.fsync(stream.fileno())
    deadline = time.monotonic() + 20.0
    original_deadline = resource_operation_deadline()
    if original_deadline is not None:
        deadline = min(deadline, original_deadline.work_deadline_monotonic)
    fingerprints = []
    for seed in ("1", "2"):
        remaining = deadline - time.monotonic()
        assert remaining > 0, "original operation deadline expired before fingerprint probe"
        result = subprocess.run([sys.executable, "-S", "-B", str(probe), str(worker_path), worker_sha256],
            cwd=tmp_path, env={"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONHASHSEED": seed},
            capture_output=True, text=True, check=False, timeout=remaining)
        assert result.returncode == 0, (seed, result.returncode, result.stdout, result.stderr)
        observation = json.loads(result.stdout)
        assert observation["worker_sha256"] == worker_sha256
        fingerprints.append(observation["fingerprint"])
    assert fingerprints[0] == fingerprints[1], json.dumps(
        {"seed_1": fingerprints[0], "seed_2": fingerprints[1]}, sort_keys=True)


# Prospective P5 context-wire control: this is only caller-owned low-level
# fictional Torch transport. It supplies no admission or context permission.
@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_generation_explicit_train_context_reaches_real_encoder_without_query_targets(architecture):
    torch, backend, training = _torch_reviewed_backend_fixture(architecture, context_limit=8192)
    original = _reviewed_generation_source_records(training)
    source_only = json.loads(original[0]["source_wire"])
    eos, bos = backend.tokenizer.eos_token_id, backend.tokenizer.bos_token_id
    # Real finite TinyOwnedModel forwards, with an explicit fictional EOS head.
    # No substituted logits, model download, update or claimed learned quality.
    with torch.no_grad():
        backend.model.head.weight.zero_()
        backend.model.head.bias.zero_()
        backend.model.head.bias[eos] = 5.0
    before = backend.snapshot_checkpoint()
    baseline = backend.generate_batch(original, max_output_tokens=2, execution_guard=lambda: None)
    assert baseline[0]["outcome"] == "abstained"
    assert baseline[0]["generated_token_ids"] == [bos, eos]
    base_input = backend.model.calls[-1]["input_ids"]
    observed = []
    for actor in ("fictional auditor alpha", "fictional auditor beta"):
        # Independently authored example content; never copied from target_json.
        # The admitted context route must separately replay actual TRAIN review,
        # split/exposure/source exclusions and a trusted context-policy guard.
        example_ir = {
            "profile": "fictional-independent-context/v1",
            "typed_expression": {"kind": "fictional_norm", "actor": actor,
                                 "action": "inspect", "object": "fixture log"},
            "argument_roles": [{"argument": actor, "role": "actor"}],
            "assumptions": [],
            "governing_context": {"jurisdiction": "fixture:context-jurisdiction",
                "instrument_id": "fixture:context-instrument", "governing_edition": "fixture:context-edition",
                "legal_as_of_utc": "2026-01-02T00:00:00Z", "valid_from_utc": "2026-01-01T00:00:00Z",
                "valid_until_utc": None},
            "interpretation_id": "fixture:context-only-choice",
            "source_binding": {"source_version_cid": "fixture:context-source",
                "occurrence_cid": "fixture:context-occurrence", "document_revision": "fixture:context-revision"},
            "definition_uses": [], "cross_references": [],
        }
        context = {"profile": "reviewed-decoder-training-context/v1", "mode": "rich_full_ast",
            "permitted": [], "retrieved": [{"id": "fixture:independent-train-example", "content": {
                "id": "fixture:independent-train-example", "unit_id": "fixture:independent-train-unit",
                "source_text": actor + " may inspect a fixture log.", "canonical_ir": example_ir,
                "source_link": dict(example_ir["source_binding"]), "selection_role": "retrieved_example"}}]}
        wire = json.dumps({**source_only, "profile": "reviewed-source-with-training-context/v1",
                           "context": context}, sort_keys=True, separators=(",", ":"))
        assert training[0]["target_json"] not in wire
        assert "fixture_predicate" not in wire and "fixture_definition" not in wire
        tokens = [bos, *backend.tokenizer.encode(wire), eos]
        assert len(tokens) + 2 <= backend.max_sequence_tokens
        record = {**original[0], "source_wire": wire, "source_token_ids": tokens}
        # Current canonical generation rejects this versioned context profile;
        # this prospective property must reach the actual model after adoption.
        result = backend.generate_batch([record], max_output_tokens=2, execution_guard=lambda: None)
        call = backend.model.calls[-1]
        assert backend.tokenizer.decode(tokens[1:-1]) == wire
        assert json.loads(wire)["context"] == context  # Complete, untruncated AST/source.
        if architecture == "encoder_decoder":
            assert call["input_ids"] == [tokens] and call["decoder_input_ids"] == [[bos]]
        else:
            assert call["input_ids"] == [tokens + [bos]] and call["decoder_input_ids"] is None
        assert call["labels"] is None
        assert result[0]["generated_token_ids"] == [bos, eos]
        assert result[0]["outcome"] == "abstained" and result[0]["candidate"] is None
        observed.append(call["input_ids"])
    assert observed[0] != observed[1] and all(value != base_input for value in observed)
    assert len(backend.model.calls) == 3  # One source-only and two context forwards.
    assert backend._optimizer_steps == 0 and backend.optimizer.state_dict()["state"] == {}
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"]) is True


def _reviewed_context_generation_wire_fixture(architecture="encoder_decoder", *, context_limit=8192):
    # Low-level transport only; no admission or legal-context permission.
    torch, backend, training = _torch_reviewed_backend_fixture(architecture, context_limit=context_limit)
    source = _reviewed_generation_source_records(training)[0]
    value = json.loads(source["source_wire"])
    value.update(profile="reviewed-source-with-training-context/v1", context={
        "profile": "reviewed-decoder-training-context/v1", "mode": "rich_full_ast",
        "permitted": [], "retrieved": [{"id": "fixture:independent-context", "content": {
            "source_text": "An independent fictional auditor may inspect a log.",
            "typed_training_example": {"actor": "auditor", "action": "inspect", "object": "log"}}}]})
    return torch, backend, source, value


def _reviewed_context_generation_pack(backend, source, value):
    wire = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {**source, "source_wire": wire, "source_token_ids": [backend.tokenizer.bos_token_id,
        *backend.tokenizer.encode(wire), backend.tokenizer.eos_token_id]}


@pytest.mark.parametrize("fault", ["source_extra", "context_extra", "missing_profile", "bad_profile",
    "bad_mode", "unhashable_mode", "permitted_mapping", "retrieved_null", "empty_records", "record_extra",
    "missing_content", "boolean_id", "empty_id", "control_id", "duplicate_id", "query_id", "query_unit",
    "content_array", "content_empty", "nonfinite_content", "non_utf8_content", "nested_query_id", "nested_query_key"])
def test_reviewed_generation_context_rejects_closed_shape_and_ID_faults_before_forward(fault):
    _, backend, source, value = _reviewed_context_generation_wire_fixture()
    context = value["context"]
    record = context["retrieved"][0]
    if fault == "source_extra": value["reference"] = {}
    elif fault == "context_extra": context["permission"] = True
    elif fault == "missing_profile": context.pop("profile")
    elif fault == "bad_profile": context["profile"] = "unknown:v1"
    elif fault == "bad_mode": context["mode"] = "implicit"
    elif fault == "unhashable_mode": context["mode"] = []
    elif fault == "permitted_mapping": context["permitted"] = {}
    elif fault == "retrieved_null": context["retrieved"] = None
    elif fault == "empty_records": context["retrieved"] = []
    elif fault == "record_extra": record["target_json"] = "hidden"
    elif fault == "missing_content": record.pop("content")
    elif fault == "boolean_id": record["id"] = True
    elif fault == "empty_id": record["id"] = ""
    elif fault == "control_id": record["id"] = "bad\nname"
    elif fault == "duplicate_id": context["permitted"] = [json.loads(json.dumps(record))]
    elif fault == "query_id": record["id"] = source["id"]
    elif fault == "query_unit": record["id"] = source["unit_id"]
    elif fault == "content_array": record["content"] = []
    elif fault == "content_empty": record["content"] = {}
    elif fault == "nonfinite_content": record["content"]["invalid"] = float("nan")
    elif fault == "non_utf8_content": record["content"]["invalid"] = "\ud800"
    elif fault == "nested_query_id": record["content"]["nested"] = [source["id"]]
    elif fault == "nested_query_key": record["content"]["nested"] = {source["id"]: "not allowed"}
    else: raise AssertionError(fault)
    packed = _reviewed_context_generation_pack(backend, source, value)
    before = backend.snapshot_checkpoint()
    with pytest.raises(worker.TrainingJobValidationError):
        backend.generate_batch([packed], max_output_tokens=2, execution_guard=lambda: None)
    assert backend.model.calls == [] and backend._optimizer_steps == 0
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"]) is True


@pytest.mark.parametrize("field", ["query_target", "query_canonical_ir", "target_json", "target_token_ids",
    "decoder_input_ids", "labels", "gold_target", "teacher_forced_prefix"])
def test_reviewed_generation_context_reserved_target_and_prefix_fields_never_reach_forward(field):
    _, backend, source, value = _reviewed_context_generation_wire_fixture()
    value["context"]["retrieved"][0]["content"]["nested"] = {field: "fictional forbidden target"}
    packed = _reviewed_context_generation_pack(backend, source, value)
    before = backend.snapshot_checkpoint()
    with pytest.raises(worker.TrainingJobValidationError, match="target or decoder-prefix"):
        backend.generate_batch([packed], max_output_tokens=2, execution_guard=lambda: None)
    assert backend.model.calls == []
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"]) is True


@pytest.mark.parametrize("fault", ["changed_body_id", "missing_bos", "boolean_token"])
def test_reviewed_generation_context_token_transport_is_exact_before_forward(fault):
    _, backend, source, value = _reviewed_context_generation_wire_fixture()
    packed = _reviewed_context_generation_pack(backend, source, value)
    if fault == "changed_body_id": packed["source_token_ids"][1] += 1
    elif fault == "missing_bos": packed["source_token_ids"][0] = 1
    else: packed["source_token_ids"][1] = True
    before = backend.snapshot_checkpoint()
    with pytest.raises(worker.TrainingJobValidationError):
        backend.generate_batch([packed], max_output_tokens=2, execution_guard=lambda: None)
    assert backend.model.calls == []
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"]) is True


@pytest.mark.parametrize("fault", ["context_tokens", "context_bytes", "full_causal_budget"])
def test_reviewed_generation_context_subbounds_never_add_to_full_model_allowance(fault):
    _, backend, source, value = _reviewed_context_generation_wire_fixture("causal_lm", context_limit=32768)
    if fault == "context_tokens":
        value["context"]["retrieved"][0]["content"] = {"payload": "x" * 4096}
        pattern = "fixed token sub-bound"
    elif fault == "context_bytes":
        value["context"]["retrieved"][0]["content"] = {"payload": "x" * (16 * 1024)}
        pattern = "fixed byte sub-bound"
    else: pattern = "full generation budget"
    packed = _reviewed_context_generation_pack(backend, source, value)
    if fault == "full_causal_budget": backend.max_sequence_tokens = len(packed["source_token_ids"]) + 1
    before = backend.snapshot_checkpoint()
    with pytest.raises(worker.TrainingJobValidationError, match=pattern):
        backend.generate_batch([packed], max_output_tokens=2, execution_guard=lambda: None)
    assert backend.model.calls == []
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"]) is True


def test_reviewed_generation_context_fixed_token_boundary_preserves_complete_payload():
    torch, backend, source, value = _reviewed_context_generation_wire_fixture()
    content = value["context"]["retrieved"][0]["content"] = {"payload": ""}
    context_json = lambda: json.dumps(value["context"], sort_keys=True, separators=(",", ":"))
    empty_tokens = len(backend.tokenizer.encode(context_json())) + 2
    content["payload"] = "x" * (worker.REVIEWED_GENERATION_CONTEXT_MAX_TOKENS - empty_tokens)
    assert len(backend.tokenizer.encode(context_json())) + 2 == worker.REVIEWED_GENERATION_CONTEXT_MAX_TOKENS
    packed = _reviewed_context_generation_pack(backend, source, value)
    with torch.no_grad():
        backend.model.head.weight.zero_()
        backend.model.head.bias.zero_()
        backend.model.head.bias[backend.tokenizer.eos_token_id] = 5.0
    before = backend.snapshot_checkpoint()
    output = backend.generate_batch([packed], max_output_tokens=2, execution_guard=lambda: None)
    assert output[0]["outcome"] == "abstained" and len(backend.model.calls) == 1
    assert backend.tokenizer.decode(packed["source_token_ids"][1:-1]) == packed["source_wire"]
    content["payload"] += "x"
    overflow = _reviewed_context_generation_pack(backend, source, value)
    with pytest.raises(worker.TrainingJobValidationError, match="fixed token sub-bound"):
        backend.generate_batch([overflow], max_output_tokens=2, execution_guard=lambda: None)
    assert len(backend.model.calls) == 1
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"]) is True


@pytest.mark.parametrize("fault", ["wire_mutation", "original_guard_error"])
def test_reviewed_generation_context_late_fault_restores_state_RNG_gradients_and_modes(fault, monkeypatch):
    torch, backend, source, value = _reviewed_context_generation_wire_fixture()
    records = [_reviewed_context_generation_pack(backend, source, value)]
    backend.model.embedding.train(False)
    parameter = next(backend.model.parameters())
    gradient = parameter.grad = torch.ones_like(parameter)
    modes = [(module, module.training) for module in backend.model.modules()]
    before = backend.snapshot_checkpoint()
    cpu_rng = torch.get_rng_state().clone()
    original_forward = backend.model.forward
    failure = ValueError("original fictional context-policy execution guard")
    def forward_then_mutate(**arguments):
        output = original_forward(**arguments)
        changed = json.loads(records[0]["source_wire"])
        changed["context"]["retrieved"][0]["content"]["source_text"] = "late changed context"
        records[0]["source_wire"] = json.dumps(changed, sort_keys=True, separators=(",", ":"))
        return output
    def guard():
        if backend.model.calls and fault == "original_guard_error": raise failure
    if fault == "wire_mutation": monkeypatch.setattr(backend.model, "forward", forward_then_mutate)
    expected = worker.TrainingJobValidationError if fault == "wire_mutation" else ValueError
    with pytest.raises(expected) as captured:
        backend.generate_batch(records, max_output_tokens=2, execution_guard=guard)
    if fault == "original_guard_error": assert captured.value is failure
    assert len(backend.model.calls) == 1 and backend._optimizer_steps == 0
    assert parameter.grad is gradient and torch.equal(gradient, torch.ones_like(gradient))
    assert all(module.training is state for module, state in modes)
    assert torch.equal(torch.get_rng_state(), cpu_rng)
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"]) is True


@pytest.mark.parametrize("fault", ["context_record_id", "nested_unit_reference"])
def test_reviewed_generation_context_excludes_every_query_identity_in_the_batch(fault):
    _, backend, source, value = _reviewed_context_generation_wire_fixture()
    second_source = {**source, "id": "fixture:other-query", "unit_id": "fixture:other-query-unit"}
    second_value = json.loads(json.dumps(value))
    if fault == "context_record_id": value["context"]["retrieved"][0]["id"] = second_source["id"]
    else: value["context"]["retrieved"][0]["content"]["nested"] = {"unit": second_source["unit_id"]}
    records = [_reviewed_context_generation_pack(backend, source, value),
               _reviewed_context_generation_pack(backend, second_source, second_value)]
    before = backend.snapshot_checkpoint()
    with pytest.raises(worker.TrainingJobValidationError, match="query"):
        backend.generate_batch(records, max_output_tokens=2, execution_guard=lambda: None)
    assert backend.model.calls == []
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"]) is True


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_generation_context_actual_local_HF_accepts_complete_wire_and_restores_pair(tmp_path, monkeypatch, architecture):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, architecture)
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    runtime, receipt = worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert type(runtime.backend.model) is fixture.model_class
    assert receipt["matched_pair"] is True and receipt["checkpoint_restored"] is True
    source = _reviewed_local_loader_source_record(runtime.tokenizer)
    value = json.loads(source["source_wire"])
    # Independently authored context DATA, never a query reference or a legal
    # permission. The admitted producer/factory remains source-only for now.
    example = {"profile": "fixture:independent-context", "typed_expression": {
        "kind": "fixture_norm", "actor": "auditor", "action": "inspect", "object": "log"},
        "argument_roles": [{"argument": "auditor", "role": "actor"}], "assumptions": [],
        "governing_context": {"jurisdiction": "fixture:ctx", "instrument_id": "fixture:ctx",
            "governing_edition": "fixture:v1", "legal_as_of_utc": "2026-01-02T00:00:00Z",
            "valid_from_utc": "2026-01-01T00:00:00Z", "valid_until_utc": None},
        "interpretation_id": "fixture:ctx", "source_binding": {"source_version_cid": "ctx:source",
            "occurrence_cid": "ctx:span", "document_revision": "ctx:v1"},
        "definition_uses": [], "cross_references": []}
    value.update(profile="reviewed-source-with-training-context/v1", context={
        "profile": "reviewed-decoder-training-context/v1", "mode": "rich_full_ast", "permitted": [],
        "retrieved": [{"id": "ctx:independent-train-example", "content": {
            "source_text": "An auditor may inspect a log.", "canonical_ir": example}}]})
    wire = worker._json_bytes(value).decode()
    tokens = [runtime.tokenizer.bos_token_id, *runtime.tokenizer.encode(wire), runtime.tokenizer.eos_token_id]
    assert len(tokens) + 3 <= runtime.backend.max_sequence_tokens
    record = {**source, "source_wire": wire, "source_token_ids": tokens}
    rng = fixture.torch.get_rng_state().clone()
    modes = [(module, module.training) for module in runtime.backend.model.modules()]
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"]) is True
    outputs = runtime.backend.generate_batch([record], max_output_tokens=3, execution_guard=runtime.execution_guard)
    assert runtime.tokenizer.decode(tokens[1:-1]) == wire
    assert json.loads(wire)["context"] == value["context"]
    assert len(outputs) == 1 and outputs[0]["outcome"] == "abstained" and outputs[0]["candidate"] is None
    assert outputs[0]["generated_token_ids"] == [runtime.tokenizer.bos_token_id, runtime.tokenizer.eos_token_id]
    assert runtime.backend._optimizer_steps == 1  # Only the independent fixture's prior update.
    assert fixture.torch.equal(fixture.torch.get_rng_state(), rng)
    assert all(module.training is state for module, state in modes)
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"]) is True
    assert receipt["training_performed"] is receipt["downloads_performed"] is receipt["resource_granted"] is False


def _reviewed_component_worker_fixture(tmp_path, *, batch_size):
    from types import SimpleNamespace
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer

    legacy = _complete_reviewed_worker_fixture(tmp_path, batch_size=batch_size)
    data, registry = legacy.data, legacy.registry
    options = legacy.fixtures._reviewed_component_successor_options(
        data, registry, legacy.payload["stage_artifact"], tmp_path / "component-stage")
    rows = options["successor_rows"]
    stage = legacy.inputs.stage_reviewed_cycle_inputs(registry, **options)
    selections = {"fixture:reviewed-act-v1": "fixture:act-v1/selected-interpretation",
        "fixture:reviewed-harbor-reports-act": "fixture:harbor-reports-act/selected-interpretation"}
    contexts = {"profile": legacy.inputs.REVIEWED_COMPONENT_DECODER_CONTEXT_PROFILE,
        "component_selection_contexts": {key: {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": interpretation, "selection_mode": "identifier_only"}
            for key, interpretation in selections.items()},
        "rows": [{"id": row["id"], "unit_id": row["unit_id"],
            "governing_context": data.deepcopy(row["canonical_ir"]["governing_context"]),
            "source_binding": data.deepcopy(row["canonical_ir"]["source_binding"])} for row in rows]}
    exposure_ref = _complete_reviewed_artifact(tmp_path / "component-exposure.json",
        worker._json_bytes(options["exposure_records"]))
    context_ref = _complete_reviewed_artifact(tmp_path / "component-source-contexts.json", worker._json_bytes(contexts))
    admission = options["admission_inputs"]
    payload = dict(legacy.payload, stage_artifact=stage, exposure_artifact=exposure_ref,
        source_contexts_artifact=context_ref, expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(admission),
        output_directory=str(tmp_path / "component-output"), max_seconds=120)
    runtime = replace(legacy.runtime, current_admission_provider=lambda: data.deepcopy(admission))
    return SimpleNamespace(legacy=legacy, payload=payload, runtime=runtime, rows=rows, selections=selections)


def test_reviewed_component_decoder_worker_dispatches_v9_job_file_and_publishes_exact_binding(tmp_path, monkeypatch):
    fixture = _reviewed_component_worker_fixture(tmp_path, batch_size=6)
    spec = worker.TrainingJobSpec.from_dict(fixture.payload)
    assert type(spec) is worker.ReviewedDecoderTrainingJobSpec
    assert spec.schema_version == "autoencoder-training-job-v9-reviewed-legal-ir"
    monkeypatch.setattr(worker, "_require_tree_pin", lambda: pytest.fail("legacy model path reached"))
    path = tmp_path / "component-v9-job.json"
    raw = worker._json_bytes(spec.to_dict())
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    receipt = worker.execute_training_job_file(path, digest, reviewed_runtime=fixture.runtime)
    assert receipt["job_file_sha256"] == digest and receipt["job_spec_sha256"] == spec.canonical_sha256
    assert receipt["schema_version"] == "reviewed-legal-ir-decoder-worker-receipt/v1"
    assert receipt["backend_train_batch_calls"] == receipt["backend_restore_calls"] == 1
    assert receipt["model_bytes_changed"] is receipt["optimizer_bytes_changed"] is True
    checkpoint = json.loads(Path(receipt["candidate"]["path"]).read_bytes())
    binding = receipt["complete_training_binding"]
    assert checkpoint["schema"] == "reviewed-legal-ir-decoder-checkpoint/v1"
    assert checkpoint["training_binding"] == binding
    assert binding["schema"] == "reviewed-decoder-training-input-receipt/v3"
    assert binding["fixture_only"] is True and binding["training_mask"] == 0
    assert binding["production_training_eligible"] is False
    assert all(receipt[key] is False for key in ("qualified", "admitted", "promotion_performed", "corpus_admitted"))
    assert set(binding["current_admission_custody"]) == set(fixture.selections)
    rows = {row["id"]: row for row in fixture.rows}
    batch, = fixture.runtime.backend.seen
    assert len(batch) == 6 and {record["id"] for record in batch} == set(rows)
    assert fixture.legacy.heldout["source_text"] not in worker._json_bytes(batch).decode("utf-8")
    for record in batch:
        assert json.loads(record["target_json"]) == rows[record["id"]]["canonical_ir"]
        source = json.loads(record["source_wire"])
        assert set(source) == {"profile", "source_text", "governing_context", "source_binding", "selection_context"}
    assert {json.loads(record["source_wire"])["selection_context"]["interpretation_id"]
            for record in batch} == set(fixture.selections.values())


def test_reviewed_component_decoder_worker_exact_resume_matches_uninterrupted_numeric_fixture(tmp_path):
    fixture = _reviewed_component_worker_fixture(tmp_path, batch_size=4)

    def execute(backend, **updates):
        spec = worker.TrainingJobSpec.from_dict(dict(fixture.payload, **updates))
        return worker.execute_training_job(spec, reviewed_runtime=replace(fixture.runtime, backend=backend))

    whole_backend = _CompleteReviewedSGDBackend()
    whole = execute(whole_backend, output_directory=str(tmp_path / "whole"), max_steps=2)
    first_backend = _CompleteReviewedSGDBackend()
    first = execute(first_backend, output_directory=str(tmp_path / "first"))
    resumed_backend = _CompleteReviewedSGDBackend()
    resumed = execute(resumed_backend, output_directory=str(tmp_path / "resumed"),
        base_model_checkpoint=first["model_checkpoint"], base_optimizer_checkpoint=first["optimizer_checkpoint"],
        parent_checkpoint_artifact=first["candidate"])
    assert first["worker_progress"] == {"epochs_completed": 0, "row_cursor": 4, "optimizer_steps": 1}
    assert resumed["initial_progress"] == first["worker_progress"]
    assert resumed["worker_progress"] == whole["worker_progress"] == {
        "epochs_completed": 1, "row_cursor": 0, "optimizer_steps": 2}
    assert whole_backend.seen == first_backend.seen + resumed_backend.seen
    assert [len(batch) for batch in whole_backend.seen] == [4, 2]
    assert resumed["complete_training_binding"] == first["complete_training_binding"] == whole["complete_training_binding"]
    for key in ("model_checkpoint", "optimizer_checkpoint"):
        assert Path(resumed[key]["path"]).read_bytes() == Path(whole[key]["path"]).read_bytes()


@pytest.mark.parametrize("first_profile", ("v2", "v3"), ids=("v2-parent-v3-job", "v3-parent-v2-job"))
def test_reviewed_component_decoder_worker_refuses_progressed_parent_from_other_profile(tmp_path, first_profile, monkeypatch):
    fixture = _reviewed_component_worker_fixture(tmp_path, batch_size=1)
    jobs = {"v2": (fixture.legacy.payload, fixture.legacy.runtime), "v3": (fixture.payload, fixture.runtime)}
    first_payload, first_runtime = jobs[first_profile]
    target_payload, target_runtime = jobs["v3" if first_profile == "v2" else "v2"]
    parent = worker.execute_training_job(worker.TrainingJobSpec.from_dict(first_payload), reviewed_runtime=first_runtime)
    assert parent["complete_training_binding"]["schema"].endswith("/" + first_profile)
    assert parent["worker_progress"] == {"epochs_completed": 0, "row_cursor": 1, "optimizer_steps": 1}
    target_backend = _CompleteReviewedSGDBackend()
    monkeypatch.setattr(target_backend, "inspect_checkpoint", lambda *args: pytest.fail("checkpoint inspection reached"))
    output = tmp_path / "cross-profile"
    target = worker.TrainingJobSpec.from_dict(dict(target_payload, output_directory=str(output),
        base_model_checkpoint=parent["model_checkpoint"], base_optimizer_checkpoint=parent["optimizer_checkpoint"],
        parent_checkpoint_artifact=parent["candidate"]))
    with pytest.raises(worker.TrainingJobValidationError, match="reviewed decoder exact-resume identities differ"):
        worker.execute_training_job(target, reviewed_runtime=replace(target_runtime, backend=target_backend))
    assert target_backend.validations == 1
    assert target_backend.restores == target_backend.calls == 0
    assert not output.exists()


def _reviewed_local_loader_runtime_state_diagnostics(error):
    """Retain the existing checkpoint wrapper and inspect its original cause."""
    values = []
    while error is not None:
        values.append(str(error))
        error = error.__cause__
    return values


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
@pytest.mark.parametrize("experts", ["absent", "eager", "none"])
def test_reviewed_local_loader_runtime_state_preserves_complete_configuration(tmp_path, monkeypatch, architecture, experts):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, architecture)
    if experts != "absent":
        fixture.backend.model.config._experts_implementation = "eager" if experts == "eager" else None
    expected = fixture.backend._configuration()
    checkpoint = fixture.backend.snapshot_checkpoint()
    fixture.options.update(
        model_config_artifact=fixture.artifact("explicit-config.json", worker._json_bytes(expected["model_config"])),
        model_checkpoint=fixture.artifact("explicit-model.pt", checkpoint["model_state"]),
        optimizer_checkpoint=fixture.artifact("explicit-optimizer.pt", checkpoint["optimizer_state"]),
        expected_backend_identity=fixture.backend.identity())
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    runtime, receipt = worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert runtime.backend._configuration() == expected
    assert runtime.backend.identity() == fixture.options["expected_backend_identity"]
    assert runtime.backend.restored_checkpoint_matches(checkpoint["model_state"], checkpoint["optimizer_state"])
    original = dict(fixture.backend.model.named_buffers())
    actual = dict(runtime.backend.model.named_buffers())
    assert set(original) == set(actual)
    for name, expected_buffer in original.items():
        assert fixture.torch.equal(actual[name], expected_buffer)
        assert fixture.torch.equal(actual[name].reshape(-1).view(fixture.torch.uint8),
                                   expected_buffer.reshape(-1).view(fixture.torch.uint8))
    if architecture == "causal_lm":
        nonpersistent = {module_name + "." + name for module_name, module in fixture.backend.model.named_modules()
                         for name in module._non_persistent_buffers_set}
        assert receipt["reconstructed_deterministic_nonpersistent_buffers"] == sorted(nonpersistent)
    else:
        assert receipt["reconstructed_deterministic_nonpersistent_buffers"] == []


@pytest.mark.parametrize("damage", ["upper-triangle", "lower-triangle", "masked-bias", "missing-buffer", "unknown-buffer"])
def test_reviewed_local_loader_runtime_state_refuses_changed_nonpersistent_semantics(tmp_path, damage):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm")
    model = fixture.backend.model
    attention = model.transformer.h[0].attn
    if not {"bias", "masked_bias"} <= attention._non_persistent_buffers_set:
        pytest.skip("This runtime implements GPT2 causal masking without nonpersistent buffers")
    rng = fixture.torch.get_rng_state().clone()
    if damage == "upper-triangle":
        attention.bias[0, 0, 0, 1] = True
    elif damage == "lower-triangle":
        attention.bias[0, 0, 1, 0] = False
    elif damage == "masked-bias":
        attention.masked_bias.fill_(-9999)
    elif damage == "missing-buffer":
        del attention._buffers["bias"]
    else:
        model.register_buffer("unreviewed_runtime_state", fixture.torch.ones(1), persistent=False)
    for operation in (fixture.backend.identity, fixture.backend.snapshot_checkpoint,
                      lambda: fixture.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"],
                                                                          fixture.checkpoint["optimizer_state"])):
        with pytest.raises(worker.TrainingJobValidationError) as captured:
            operation()
        assert any("causal buffer" in message or "nonpersistent buffers" in message
                   for message in _reviewed_local_loader_runtime_state_diagnostics(captured.value))
    assert fixture.torch.equal(fixture.torch.get_rng_state(), rng)


def test_reviewed_local_loader_runtime_state_refuses_unknown_meta_buffers_before_cpu_allocation(tmp_path, monkeypatch):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm")
    import transformers.models.gpt2.modeling_gpt2 as gpt2
    original = gpt2.GPT2Attention.__init__
    def changed_constructor(module, *args, **kwargs):
        original(module, *args, **kwargs)
        module.register_buffer("unreviewed_runtime_state", fixture.torch.ones(1), persistent=False)
    monkeypatch.setattr(gpt2.GPT2Attention, "__init__", changed_constructor)
    monkeypatch.setattr(fixture.torch.nn.Module, "to_empty",
        lambda *args, **kwargs: pytest.fail("unknown nonpersistent state reached CPU allocation"))
    rng = fixture.torch.get_rng_state().clone()
    with pytest.raises(worker.TrainingJobValidationError, match="unsupported built-in GPT2 nonpersistent buffer constructor"):
        worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert fixture.torch.equal(fixture.torch.get_rng_state(), rng)


@pytest.mark.parametrize("damage", ["upper-triangle", "lower-triangle", "masked-bias"])
def test_reviewed_local_loader_runtime_state_same_pair_refuses_changed_causal_values(tmp_path, damage):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm")
    # The same exact pair must accept the original model without changing any
    # buffer. The subsequent refusal therefore detects the causal mutation.
    buffers = {name: value.detach().clone() for name, value in fixture.backend.model.named_buffers()}
    assert fixture.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"],
                                                      fixture.checkpoint["optimizer_state"]) is True
    after = dict(fixture.backend.model.named_buffers())
    assert set(after) == set(buffers)
    assert all(fixture.torch.equal(after[name], value) for name, value in buffers.items())
    attention = fixture.backend.model.transformer.h[0].attn
    if not {"bias", "masked_bias"} <= attention._non_persistent_buffers_set:
        pytest.skip("This runtime implements GPT2 causal masking without nonpersistent buffers")
    if damage == "upper-triangle":
        attention.bias[0, 0, 0, 1] = True
    elif damage == "lower-triangle":
        attention.bias[0, 0, 1, 0] = False
    else:
        attention.masked_bias.fill_(-9999)
    try:
        matched = fixture.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"],
                                                             fixture.checkpoint["optimizer_state"])
    except worker.TrainingJobValidationError as error:
        assert any("deterministic causal buffer values differ" in message
                   for message in _reviewed_local_loader_runtime_state_diagnostics(error))
    else:
        assert matched is False, "changed causal semantics reused an exact-checkpoint match"


@pytest.mark.parametrize("positions,layers", [(65537, 0), (262144, 0), (8, 129)])
def test_reviewed_torch_injected_gpt2_dimensions_keep_backend_context_contract(positions, layers):
    """Already owned models retain the generic backend's original context range."""
    from transformers import GPT2Config, GPT2LMHeadModel
    torch, fixture, _ = _torch_reviewed_backend_fixture("causal_lm")
    config = GPT2Config(vocab_size=259, n_positions=positions, n_ctx=positions,
        n_embd=2, n_inner=2, n_layer=layers, n_head=1, bos_token_id=257,
        eos_token_id=258, pad_token_id=0, resid_pdrop=0.0, embd_pdrop=0.0, attn_pdrop=0.0)
    config._attn_implementation = "eager"
    # Zero-layer long-context cases allocate only a small position embedding;
    # the 129-layer case has 8x8 causal masks even in older Transformers.
    model = GPT2LMHeadModel(config)
    optimizer = torch.optim.Adam(model.parameters(), lr=.001, foreach=False)
    backend = worker.TorchReviewedDecoderBackend(model, optimizer, fixture.tokenizer,
        architecture="causal_lm", max_sequence_tokens=positions, pretrained=False)
    buffers = {name: value.detach().clone() for name, value in model.named_buffers()}
    rng = torch.get_rng_state().clone()
    configuration = backend._configuration()
    assert configuration["max_sequence_tokens"] == positions
    assert configuration["model_config"] == config.to_dict()
    identity = backend.identity()
    checkpoint = backend.snapshot_checkpoint()
    assert backend.restored_checkpoint_matches(checkpoint["model_state"], checkpoint["optimizer_state"])
    assert backend.identity() == identity
    assert torch.equal(torch.get_rng_state(), rng)
    assert set(dict(model.named_buffers())) == set(buffers)
    assert all(torch.equal(value, buffers[name]) for name, value in model.named_buffers())


@pytest.mark.parametrize("dimension,value", [("n_positions", 65537), ("n_layer", 129), ("n_layer", 0)])
def test_reviewed_local_loader_dimension_profile_stays_bounded_before_model_constructor(tmp_path, monkeypatch,
                                                                                       dimension, value):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm")
    config = json.loads(Path(fixture.options["model_config_artifact"].path).read_bytes())
    config[dimension] = value
    fixture.options["model_config_artifact"] = fixture.artifact("outside-profile-config.json", worker._json_bytes(config))
    entry = fixture.torch.get_rng_state().clone()
    monkeypatch.setattr(fixture.model_class, "__init__",
        lambda *args, **kwargs: pytest.fail("dimension outside loader profile reached model constructor"))
    with pytest.raises(worker.TrainingJobValidationError,
                       match="bounded built-in model dimensions required before meta construction: " + dimension):
        worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert fixture.torch.equal(fixture.torch.get_rng_state(), entry)


# Explicit mixed-admission execution is a sibling of the unchanged V9 path.
# All artifacts, signatures, numerical state and outputs below are private DATA.
def _reviewed_mixed_worker_fixture(tmp_path, *, batch_size=1, backend=None, tokenizer=None, two_components=True):
    from types import SimpleNamespace
    from tests.unit.logic import test_autoformal_campaign_training_inputs as fixtures
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer

    old = _reviewed_component_worker_fixture(tmp_path, batch_size=batch_size)
    mixed_root = tmp_path / 'mixed-fixture'
    mixed_root.mkdir()
    data = fixtures._reviewed_mixed_cycle_fixture(mixed_root, stage=False)
    if two_components:
        fixtures._reviewed_mixed_cycle_second_component(data)
    inputs = old.legacy.inputs
    stage = inputs.stage_reviewed_mixed_cycle_inputs_v4(data.registry, **data.options)
    tokenizer = tokenizer if tokenizer is not None else old.runtime.tokenizer
    backend = backend if backend is not None else _CompleteReviewedSGDBackend()
    snapshot = backend.snapshot_checkpoint()
    model = _complete_reviewed_artifact(tmp_path / 'mixed-initial-model.checkpoint', snapshot['model_state'])
    optimizer = _complete_reviewed_artifact(tmp_path / 'mixed-initial-optimizer.checkpoint', snapshot['optimizer_state'])
    exposure = _complete_reviewed_artifact(tmp_path / 'mixed-exposure.json', worker._json_bytes(data.options['exposure_records']))
    contexts = _complete_reviewed_artifact(tmp_path / 'mixed-source-contexts.json', worker._json_bytes(data.kwargs['source_contexts']))
    pins = worker._reviewed_decoder_source_pins(admission_profile=inputs.REVIEWED_MIXED_ADMISSION_PROFILE)
    payload = dict(old.payload, schema_version=worker.REVIEWED_MIXED_DECODER_SCHEMA_VERSION,
        admission_profile=inputs.REVIEWED_MIXED_ADMISSION_PROFILE,
        stage_artifact=stage, exposure_artifact=exposure, source_contexts_artifact=contexts,
        model_artifact=model, base_model_checkpoint=model, base_optimizer_checkpoint=optimizer,
        backend_identity=backend.identity(), expected_source_sha256=pins,
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(data.options['admission_inputs']),
        output_directory=str(tmp_path / 'mixed-output'), max_seconds=120)
    parent = json.loads(Path(old.payload['parent_checkpoint_artifact']['path']).read_bytes())
    parent.update(model_state=model, optimizer_state=optimizer, backend_identity=backend.identity(),
        assets=[model, payload['tokenizer_artifact'], payload['license_artifact']], producer_pins=pins,
        token_budgets={'max_source_tokens': payload['max_source_tokens'], 'max_target_tokens': payload['max_target_tokens'],
            'tokenizer_contract': inputs._reviewed_decoder_tokenizer_contract(tokenizer)})
    payload['parent_checkpoint_artifact'] = _complete_reviewed_artifact(tmp_path / 'mixed-initial-pair.json', worker._json_bytes(parent))
    runtime = replace(old.runtime, registry=data.registry, backend=backend, tokenizer=tokenizer,
        current_admission_provider=lambda: data.deepcopy(data.options['admission_inputs']))
    return SimpleNamespace(old=old, data=data, payload=payload, runtime=runtime, inputs=inputs)


def test_reviewed_mixed_v10_dispatch_preserves_complete_targets_and_component_custody(tmp_path, monkeypatch):
    fixture = _reviewed_mixed_worker_fixture(tmp_path, batch_size=6)
    spec = worker.TrainingJobSpec.from_dict(fixture.payload)
    assert type(spec) is worker.ReviewedMixedDecoderTrainingJobSpec
    assert spec.schema_version == 'autoencoder-training-job-v10-reviewed-mixed-legal-ir'
    assert spec.admission_profile == 'complete-reviewed-mixed-sort-norm-admission/v3'
    assert worker.TrainingJobSpec.from_dict(spec.to_dict()).canonical_sha256 == spec.canonical_sha256
    monkeypatch.setattr(worker, '_require_tree_pin', lambda: pytest.fail('legacy projection path reached'))
    path = tmp_path / 'mixed-v10-job.json'
    raw = worker._json_bytes(spec.to_dict())
    path.write_bytes(raw)
    result = worker.execute_training_job_file(path, hashlib.sha256(raw).hexdigest(), reviewed_runtime=fixture.runtime)
    assert result['schema_version'] == worker.REVIEWED_MIXED_DECODER_RECEIPT_SCHEMA
    assert result['admission_profile'] == spec.admission_profile
    binding = result['complete_training_binding']
    assert binding['schema'] == 'reviewed-decoder-training-input-receipt/v4'
    assert binding['admission_profile'] == spec.admission_profile
    assert set(binding['current_admission_custody']) == set(fixture.data.options['admission_inputs'])
    assert binding['training_mask'] == 0 and binding['production_training_eligible'] is False
    assert all(result[key] is False for key in ('qualified', 'admitted', 'promotion_performed', 'corpus_admitted'))
    checkpoint = json.loads(Path(result['candidate']['path']).read_bytes())
    assert checkpoint['schema'] == worker.REVIEWED_DECODER_CHECKPOINT_SCHEMA
    assert checkpoint['training_binding'] == binding
    records, = fixture.runtime.backend.seen
    rows = {row['id']: row for row in fixture.data.options['successor_rows']}
    assert len(records) == len(rows) == 6
    assert any(row['canonical_ir']['profile'] == 'authored-many-sorted-relational-deontic/v1' for row in rows.values())
    full_fields = {'profile', 'typed_expression', 'argument_roles', 'assumptions', 'governing_context',
        'interpretation_id', 'source_binding', 'definition_uses', 'cross_references'}
    for record in records:
        target = json.loads(record['target_json'])
        assert set(target) == full_fields and target == rows[record['id']]['canonical_ir']
        source = json.loads(record['source_wire'])
        assert set(source) == {'profile', 'source_text', 'governing_context', 'source_binding', 'selection_context'}
        assert source['source_text'] == rows[record['id']]['source_text']
        assert 'typed_expression' not in source and 'target_json' not in source and 'assumptions' not in source
        assert record['target_token_ids'][0] == fixture.runtime.tokenizer.bos_token_id
        assert record['target_token_ids'][-1] == fixture.runtime.tokenizer.eos_token_id
        assert fixture.runtime.tokenizer.decode(record['target_token_ids'][1:-1]) == record['target_json']
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_adjudication_v1, legal_reviewed_norm_admission_v3
    assert result['producer_pins']['admission'] == hashlib.sha256(Path(legal_reviewed_norm_admission_v3.__file__).read_bytes()).hexdigest()
    assert fixture.old.payload['expected_source_sha256']['admission'] == hashlib.sha256(Path(legal_norm_content_adjudication_v1.__file__).read_bytes()).hexdigest()
    assert 'admission_profile' not in worker.ReviewedDecoderTrainingJobSpec.from_dict(fixture.old.payload).to_dict()


@pytest.mark.parametrize('profile', [None, 'complete-reviewed-norm-admission/v2', 'v3', True])
def test_reviewed_mixed_v10_requires_explicit_exact_admission_profile(tmp_path, profile):
    payload = {'schema_version': worker.REVIEWED_MIXED_DECODER_SCHEMA_VERSION}
    if profile is not None:
        payload['admission_profile'] = profile
    with pytest.raises(worker.TrainingJobValidationError, match='explicit mixed-sort admission V3 profile required'):
        worker.TrainingJobSpec.from_dict(payload)
    with pytest.raises(worker.TrainingJobValidationError):
        worker.ReviewedDecoderTrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize('budget', ['max_source_tokens', 'max_target_tokens'])
def test_reviewed_mixed_v10_complete_budgets_refuse_before_backend_or_output(tmp_path, monkeypatch, budget):
    fixture = _reviewed_mixed_worker_fixture(tmp_path)
    for method in ('validate_training_records', 'inspect_checkpoint', 'restore_checkpoint', 'train_batch'):
        monkeypatch.setattr(fixture.runtime.backend, method, lambda *a, **k: pytest.fail('over-budget input reached backend'))
    spec = worker.TrainingJobSpec.from_dict(dict(fixture.payload, **{budget: 3}))
    with pytest.raises(worker.TrainingJobValidationError, match='current reviewed decoder inputs changed or unsupported'):
        worker.execute_training_job(spec, reviewed_runtime=fixture.runtime)
    assert not Path(spec.output_directory).exists()


def test_reviewed_mixed_v10_prepared_v4_is_refused_by_v9_before_backend(tmp_path, monkeypatch):
    fixture = _reviewed_mixed_worker_fixture(tmp_path)
    old = dict(fixture.payload, schema_version=worker.REVIEWED_DECODER_SCHEMA_VERSION,
        expected_source_sha256=worker._reviewed_decoder_source_pins())
    old.pop('admission_profile')
    for method in ('validate_training_records', 'inspect_checkpoint', 'restore_checkpoint', 'train_batch'):
        monkeypatch.setattr(fixture.runtime.backend, method, lambda *a, **k: pytest.fail('legacy V9 accepted prepared V4'))
    with pytest.raises(ValueError, match='closed reviewed decoder stage artifact required'):
        worker.execute_training_job(worker.TrainingJobSpec.from_dict(old), reviewed_runtime=fixture.runtime)
    assert not Path(old['output_directory']).exists()


@pytest.mark.parametrize('first_profile,target_profile', [('v2', 'v4'), ('v3', 'v4'), ('v4', 'v2'), ('v4', 'v3')])
def test_reviewed_mixed_v10_progressed_cross_profile_parents_refuse_before_restore(tmp_path, monkeypatch, first_profile, target_profile):
    fixture = _reviewed_mixed_worker_fixture(tmp_path, batch_size=1)
    profiles = {'v2': (fixture.old.legacy.payload, fixture.old.legacy.runtime),
        'v3': (fixture.old.payload, fixture.old.runtime), 'v4': (fixture.payload, fixture.runtime)}
    payload, runtime = profiles[first_profile]
    first = worker.execute_training_job(worker.TrainingJobSpec.from_dict(payload), reviewed_runtime=runtime)
    assert first['complete_training_binding']['schema'].endswith('/' + first_profile)
    assert first['worker_progress']['optimizer_steps'] == 1
    payload, runtime = profiles[target_profile]
    backend = _CompleteReviewedSGDBackend()
    monkeypatch.setattr(backend, 'inspect_checkpoint', lambda *a, **k: pytest.fail('cross-profile parent reached inspection'))
    output = tmp_path / 'cross-profile-output'
    spec = worker.TrainingJobSpec.from_dict(dict(payload, output_directory=str(output),
        base_model_checkpoint=first['model_checkpoint'], base_optimizer_checkpoint=first['optimizer_checkpoint'],
        parent_checkpoint_artifact=first['candidate']))
    with pytest.raises(worker.TrainingJobValidationError, match='reviewed decoder exact-resume identities differ'):
        worker.execute_training_job(spec, reviewed_runtime=replace(runtime, backend=backend))
    assert backend.validations == 1 and backend.restores == backend.calls == 0
    assert not output.exists()


def test_reviewed_mixed_v10_real_torch_fresh_and_exact_resume_match_complete_window(tmp_path):
    torch, base_backend, _ = _torch_reviewed_backend_fixture(context_limit=65536)
    fixture = _reviewed_mixed_worker_fixture(tmp_path, batch_size=2, backend=base_backend,
        tokenizer=base_backend.tokenizer, two_components=False)
    before = base_backend.snapshot_checkpoint()
    def execute(backend, **changes):
        spec = worker.TrainingJobSpec.from_dict(dict(fixture.payload, **changes))
        return worker.execute_training_job(spec, reviewed_runtime=replace(fixture.runtime,
            backend=backend, tokenizer=backend.tokenizer))
    whole = execute(base_backend, output_directory=str(tmp_path / 'torch-whole'), max_steps=2)
    _, first_backend, _ = _torch_reviewed_backend_fixture(context_limit=65536)
    first = execute(first_backend, output_directory=str(tmp_path / 'torch-first'))
    _, resumed_backend, _ = _torch_reviewed_backend_fixture(context_limit=65536)
    resumed = execute(resumed_backend, output_directory=str(tmp_path / 'torch-resumed'),
        base_model_checkpoint=first['model_checkpoint'], base_optimizer_checkpoint=first['optimizer_checkpoint'],
        parent_checkpoint_artifact=first['candidate'])
    whole_pair = {key: Path(whole[reference]['path']).read_bytes() for key, reference in
        [('model_state', 'model_checkpoint'), ('optimizer_state', 'optimizer_checkpoint')]}
    assert base_backend.restored_checkpoint_matches(before['model_state'], before['optimizer_state']) is False
    assert resumed_backend.restored_checkpoint_matches(whole_pair['model_state'], whole_pair['optimizer_state']) is True
    assert first['worker_progress'] == {'epochs_completed': 0, 'row_cursor': 2, 'optimizer_steps': 1}
    assert resumed['initial_progress'] == first['worker_progress']
    assert resumed['worker_progress'] == whole['worker_progress'] == {'epochs_completed': 1, 'row_cursor': 0, 'optimizer_steps': 2}
    assert whole['backend_reported_metrics'] == first['backend_reported_metrics'] + resumed['backend_reported_metrics']
    assert whole['complete_training_binding'] == first['complete_training_binding'] == resumed['complete_training_binding']
    assert base_backend.model.calls == first_backend.model.calls + resumed_backend.model.calls
    # The encoder only receives the exact source-only wire; complete target IDs
    # enter the separate supervised decoder path, with neither truncation nor repair.
    prepared = fixture.inputs.prepare_reviewed_mixed_decoder_training_inputs_v4(fixture.data.registry,
        **dict(fixture.data.kwargs, tokenizer=base_backend.tokenizer,
            stage_artifact=fixture.payload['stage_artifact'], expected_stage_sha256=fixture.payload['stage_artifact']['sha256'],
            max_source_tokens=fixture.payload['max_source_tokens'], max_target_tokens=fixture.payload['max_target_tokens']))
    by_source = {tuple(row['source_token_ids']): row for row in prepared['records']}
    assert {tuple(call['input_ids'][0]) for call in base_backend.model.calls} == set(by_source)
    assert len(base_backend.model.calls) == len(prepared['records']) == 3
    assert any(json.loads(row['target_json'])['profile'] == 'authored-many-sorted-relational-deontic/v1'
               for row in prepared['records'])
    for call in base_backend.model.calls:
        record = by_source[tuple(call['input_ids'][0])]
        assert call['labels'][0] == record['target_token_ids'][1:]
        assert call['decoder_input_ids'][0] == record['target_token_ids'][:-1]
        assert json.loads(record['target_json']) in [row['canonical_ir'] for row in fixture.data.options['successor_rows']]
    assert all(whole[key] is False for key in ('qualified', 'admitted', 'promotion_performed', 'pretrained_quality_verified'))


# Explicit admission V3 source-only inference; numerical machinery stays shared.
def _reviewed_mixed_source_producer_fixture(tmp_path, architecture="encoder_decoder", *, operation="heldout_evaluation"):
    from copy import deepcopy
    from types import SimpleNamespace
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    consumer_helper, helper, admission, case, rows, consumer_options, evaluation_options = evaluation._producer_public_mixed_case(operation=operation)
    def fresh():
        return deepcopy(consumer_helper.reviewed_public_admission_inputs(helper.fixture, admission, case))
    local = _reviewed_local_loader_hf_fixture(tmp_path, architecture, admission_provider=fresh)
    runtime = worker.ReviewedDecoderRuntime(local.options["registry"], local.backend, local.backend.tokenizer,
        fresh, local.options["execution_guard"], local.options["asset_policy_guard"])
    declaration = case["declaration"]
    contexts = {"profile": "reviewed-source-selection-context/v2",
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": declaration["interpretation_id"], "selection_mode": "identifier_only"},
        "rows": [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
            "governing_context": deepcopy(declaration["governing_context"]),
            "source_binding": {"source_version_cid": unit["source_version"]["record_cid"],
                "occurrence_cid": unit["occurrence"]["record_cid"], "document_revision": unit["document_revision"]}}
            for unit in declaration["units"]]}
    options = dict(binding=evaluation_options["binding"], rows=rows,
        split_manifest=consumer_options["split_manifest"], exposure_records=consumer_options["exposure_records"],
        source_contexts=contexts, expected_source_contexts_sha256=evaluation._producer_digest(contexts),
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(fresh()),
        backend_identity=local.backend.identity(),
        assets=tuple(local.options[key] for key in ("recipe_artifact", "model_config_artifact", "tokenizer_artifact", "license_artifact")),
        model_checkpoint=local.options["model_checkpoint"], optimizer_checkpoint=local.options["optimizer_checkpoint"],
        max_source_tokens=4096, max_output_tokens=3, allow_heldout_evaluation=operation == "heldout_evaluation")
    def declarations():
        return {"encoder": {"id": "fixture:encoder-declaration-only", "sha256": "1" * 64},
            "decoder": {"id": options["backend_identity"]["backend_id"], "sha256": options["model_checkpoint"].sha256}}
    return SimpleNamespace(local=local, runtime=runtime, options=options, declarations=declarations,
        fresh=fresh, helper=helper, admission=admission, case=case, rows=rows, consumer=consumer, evaluation=evaluation)


def test_reviewed_mixed_source_v3_legacy_factory_refuses_genuine_prepared_binding(tmp_path):
    fixture = _reviewed_mixed_source_producer_fixture(tmp_path)
    with pytest.raises(ValueError, match="admission contract"):
        worker.make_reviewed_decoder_source_producer(fixture.runtime, **fixture.options)
    assert fixture.local.backend.restored_checkpoint_matches(
        fixture.local.checkpoint["model_state"], fixture.local.checkpoint["optimizer_state"]) is True


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
@pytest.mark.parametrize("operation", ["hparam_selection", "heldout_evaluation"])
def test_reviewed_mixed_source_v3_real_local_forward_scores_full_targets_without_encoder_gold(tmp_path, monkeypatch, architecture, operation):
    from copy import deepcopy
    fixture = _reviewed_mixed_source_producer_fixture(tmp_path, architecture, operation=operation)
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture.local)
    original = deepcopy(fixture.rows)
    calls, records = [], []
    forward = fixture.local.backend.model.forward
    generate = fixture.local.backend.generate_batch
    def actual_forward(**arguments):
        calls.append({key: value.detach().clone() for key, value in arguments.items()})
        assert "labels" not in arguments
        return forward(**arguments)
    def source_generation(offered, **kwargs):
        records.extend(deepcopy(offered))
        assert all(set(row) == {"id", "unit_id", "source_wire", "source_token_ids"} for row in offered)
        for offered_row, gold in zip(offered, fixture.rows, strict=True):
            source = json.loads(offered_row["source_wire"])
            assert set(source) == {"profile", "source_text", "governing_context", "source_binding", "selection_context"}
            assert source["source_text"] == gold["source_text"]
            assert "typed_expression" not in source and "canonical_ir" not in source
            assert json.dumps(gold["canonical_ir"], sort_keys=True) not in offered_row["source_wire"]
            assert offered_row["source_token_ids"][0] == fixture.local.backend.tokenizer.bos_token_id
            assert offered_row["source_token_ids"][-1] == fixture.local.backend.tokenizer.eos_token_id
        return generate(offered, **kwargs)
    monkeypatch.setattr(fixture.local.backend.model, "forward", actual_forward)
    monkeypatch.setattr(fixture.local.backend, "generate_batch", source_generation)
    entry_rng = fixture.local.torch.get_rng_state().clone()
    model = fixture.local.backend.model
    model.train(True)
    next(iter(model.modules())).training = False
    modes = [(module, module.training) for module in model.modules()]
    parameter = next(model.parameters())
    parameter.grad = fixture.local.torch.ones_like(parameter)
    original_gradient = parameter.grad
    producer = worker.make_reviewed_decoder_source_producer_v3(fixture.runtime, **fixture.options)
    artifact = producer.evaluate(compiler_commit="fixture:admission-v3-real-source-only",
        checkpoint_declarations=fixture.declarations())
    payload = fixture.evaluation._producer_payload(artifact)
    report = artifact.to_dict()["metrics"]["complete_norm_payload"]
    observation = producer.observation()
    assert observation["schema"] == "reviewed-decoder-source-producer-observation/v2"
    assert observation["admission_profile"] == worker.REVIEWED_MIXED_ADMISSION_PROFILE
    assert observation["input_commitment"]["schema"] == "reviewed-decoder-source-producer-policy/v2"
    assert observation["input_commitment"]["admission_profile"] == worker.REVIEWED_MIXED_ADMISSION_PROFILE
    assert observation["input_profile_id"].startswith("reviewed-decoder-source-producer/v2:")
    assert observation["input_commitment"]["source_sha256"]["admission"] == hashlib.sha256(Path(fixture.admission.__file__).read_bytes()).hexdigest()
    assert observation["last_call"]["entry_pair_match"] is observation["last_call"]["exit_pair_match"] is True
    assert observation["last_call"]["input_receipt"]["target_access_performed"] is False
    assert len(calls) == len(records) == report["denominator"] == report["outcome_counts"]["abstained"] == 3
    assert all(row["generated_token_ids"] == [257, 0] and row["candidate"] is None for row in observation["last_call"]["raw_generation_outputs"])
    for call, source in zip(calls, records, strict=True):
        offered = call["input_ids"].tolist()[0]
        assert offered == source["source_token_ids"] + ([257] if architecture == "causal_lm" else [])
        if architecture == "encoder_decoder":
            assert call["decoder_input_ids"].tolist() == [[257]]
    assert payload["reference_population"] == fixture.rows == original
    assert all(len(row["canonical_ir"]) == 9 for row in payload["reference_population"])
    assert payload["reference_population"][2]["canonical_ir"]["profile"] == fixture.helper.relational.MIXED_PROFILE
    assert payload["admission_before"]["schema"] == payload["admission_after"]["schema"] == fixture.consumer.REVIEWED_V3_SCHEMA
    assert payload["admission_before"]["training_mask"] == payload["admission_after"]["evaluation_gold_mask"] == 0
    assert all(module.training == mode for module, mode in modes)
    assert parameter.grad is original_gradient and bool(parameter.grad.eq(1).all())
    assert fixture.local.torch.equal(fixture.local.torch.get_rng_state(), entry_rng)
    assert fixture.local.backend.restored_checkpoint_matches(fixture.local.checkpoint["model_state"], fixture.local.checkpoint["optimizer_state"]) is True
    assert all(payload[key] is False for key in ("producer_authenticity_verified", "loaded_checkpoint_identity_verified",
        "native_proof_verified", "source_fidelity_proved", "semantic_equivalence_proved", "corpus_admitted", "token_budget_enforced"))


@pytest.mark.parametrize("damage", ["v2-binding", "relabelled-v3"])
def test_reviewed_mixed_source_v3_domain_refuses_before_runtime_callbacks(tmp_path, damage):
    from dataclasses import replace
    fixture = _reviewed_mixed_source_producer_fixture(tmp_path)
    if damage == "v2-binding":
        _, _, _, _, _, _, old = fixture.evaluation._producer_public_heldout_case()
        fixture.options["binding"] = old["binding"]
    else:
        object.__setattr__(fixture.options["binding"], "_admission_version", "v2")
    def forbidden(*args):
        pytest.fail("domain mismatch reached an external runtime callback")
    runtime = replace(fixture.runtime, current_admission_provider=forbidden, execution_guard=forbidden, asset_policy_guard=forbidden)
    with pytest.raises(ValueError, match="admission contract"):
        worker.make_reviewed_decoder_source_producer_v3(runtime, **fixture.options)


@pytest.mark.parametrize("field", ["context_profile", "current_context_inputs_provider", "expected_context_inputs_sha256", "context_policy_guard", "wrong_operation", "wrong_context_profile"])
def test_reviewed_mixed_source_v3_rich_train_context_refuses_before_any_provider(field):
    """A real reviewed binding; invalid opt-ins must not reach any model owner."""
    from types import SimpleNamespace
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    _,_,_,_,rows,consumer_options,evaluation_options=evaluation._producer_public_mixed_case()
    calls=[]
    def forbidden(*args,**kwargs):
        calls.append("unexpected_external_callback")
        pytest.fail("unsupported V3 rich TRAIN context reached a provider or policy")
    # This backend is negative-only. Every protocol operation is forbidden;
    # no positive numerical/checkpoint assertion is made from its presence.
    tokenizer=object()
    backend=SimpleNamespace(tokenizer=tokenizer,**{name:forbidden for name in
        ("identity","validate_training_records","inspect_checkpoint","restore_checkpoint",
         "restored_checkpoint_matches","train_batch","snapshot_checkpoint","generate_batch")})
    registry=SimpleNamespace(read_artifact=forbidden,artifact_path=forbidden)
    runtime=worker.ReviewedDecoderRuntime(registry,backend,tokenizer,forbidden,forbidden,forbidden)
    options=dict(binding=evaluation_options["binding"],rows=rows,
        split_manifest=consumer_options["split_manifest"],exposure_records=consumer_options["exposure_records"],
        source_contexts=None,expected_source_contexts_sha256="0"*64,
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(consumer_options["admission_inputs"]),
        backend_identity=None,assets=(),model_checkpoint=None,optimizer_checkpoint=None,
        max_source_tokens=4096,max_output_tokens=3,allow_heldout_evaluation=True)
    if field in ("wrong_operation","wrong_context_profile"):
        options.update(context_profile=consumer.REVIEWED_V3_HELDOUT_CONTEXT_PROFILE,
            current_context_inputs_provider=forbidden,expected_context_inputs_sha256="1"*64,context_policy_guard=forbidden)
        if field=="wrong_operation":options["allow_heldout_evaluation"]=False
        else:options["context_profile"]=consumer.REVIEWED_HELDOUT_CONTEXT_PROFILE
    else:
        options[field]=("reviewed-rich-TRAIN-context-hparam/v1" if field=="context_profile" else
                        "1"*64 if field=="expected_context_inputs_sha256" else forbidden)
    with pytest.raises(worker.TrainingJobValidationError,match="V3 rich TRAIN context"):
        worker.make_reviewed_decoder_source_producer_v3(runtime,**options)
    assert calls==[]


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_mixed_source_v3_fresh_late_revocation_rejects_after_actual_forward(tmp_path, monkeypatch, architecture):
    fixture = _reviewed_mixed_source_producer_fixture(tmp_path, architecture)
    producer = worker.make_reviewed_decoder_source_producer_v3(fixture.runtime, **fixture.options)
    forward = fixture.local.backend.model.forward
    calls = []
    def revoke(**arguments):
        result = forward(**arguments)
        calls.append(True)
        fixture.case["registry"]["keys"][0]["revoked_at_utc"] = fixture.helper.fixture.EVALUATED
        fixture.case["registry"]["revocation_generation"] += 1
        return result
    monkeypatch.setattr(fixture.local.backend.model, "forward", revoke)
    with pytest.raises(worker.TrainingJobValidationError, match="admission inputs changed"):
        producer.evaluate(compiler_commit="fixture:v3-late-revocation", checkpoint_declarations=fixture.declarations())
    assert len(calls) == 1 and producer.observation()["last_call"]["completed"] is False
    assert fixture.local.backend.restored_checkpoint_matches(fixture.local.checkpoint["model_state"], fixture.local.checkpoint["optimizer_state"]) is True


@pytest.mark.parametrize("damage", ["target-role", "source-context", "asset-bytes", "checkpoint-bytes", "admission-source-pin"])
def test_reviewed_mixed_source_v3_late_input_damage_cannot_publish(tmp_path, monkeypatch, damage):
    fixture = _reviewed_mixed_source_producer_fixture(tmp_path)
    producer = worker.make_reviewed_decoder_source_producer_v3(fixture.runtime, **fixture.options)
    forward = fixture.local.backend.model.forward
    source_pins = worker._reviewed_decoder_source_pins
    changed, saved = [], {}
    def alter(**arguments):
        result = forward(**arguments)
        changed.append(True)
        if damage == "target-role":
            fixture.rows[0]["canonical_ir"]["argument_roles"] = []
        elif damage == "source-context":
            fixture.options["source_contexts"]["rows"][0]["source_binding"]["document_revision"] += ":changed"
        elif damage in {"asset-bytes", "checkpoint-bytes"}:
            ref = fixture.options["assets"][-1] if damage == "asset-bytes" else fixture.options["model_checkpoint"]
            path = Path(ref.path); saved[path] = path.read_bytes(); path.write_bytes(saved[path] + b" ")
        else:
            def different(**kwargs):
                result = source_pins(**kwargs); result["admission"] = "0" * 64; return result
            monkeypatch.setattr(worker, "_reviewed_decoder_source_pins", different)
        return result
    monkeypatch.setattr(fixture.local.backend.model, "forward", alter)
    try:
        with pytest.raises(worker.TrainingJobValidationError):
            producer.evaluate(compiler_commit="fixture:v3-late-input-damage", checkpoint_declarations=fixture.declarations())
        assert changed and producer.observation()["last_call"]["completed"] is False
    finally:
        for path, raw in saved.items():
            path.write_bytes(raw)
    assert fixture.local.backend.restored_checkpoint_matches(fixture.local.checkpoint["model_state"], fixture.local.checkpoint["optimizer_state"]) is True


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_mixed_source_v3_forward_original_baseexception_closes_pair_and_rng(tmp_path, monkeypatch, architecture):
    fixture = _reviewed_mixed_source_producer_fixture(tmp_path, architecture)
    producer = worker.make_reviewed_decoder_source_producer_v3(fixture.runtime, **fixture.options)
    class ActualForwardExit(BaseException):
        pass
    original = ActualForwardExit("original actual source-only forward exit")
    def fail(**arguments):
        fixture.local.torch.rand(3)
        raise original
    monkeypatch.setattr(fixture.local.backend.model, "forward", fail)
    entry = fixture.local.torch.get_rng_state().clone()
    with pytest.raises(ActualForwardExit) as captured:
        producer.evaluate(compiler_commit="fixture:v3-original-forward-exit", checkpoint_declarations=fixture.declarations())
    assert captured.value is original
    assert fixture.local.torch.equal(fixture.local.torch.get_rng_state(), entry)
    assert producer.observation()["last_call"]["exit_pair_match"] is True
    assert fixture.local.backend.restored_checkpoint_matches(fixture.local.checkpoint["model_state"], fixture.local.checkpoint["optimizer_state"]) is True


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_mixed_source_v3_complete_output_budget_refuses_before_any_forward(tmp_path, monkeypatch, architecture):
    fixture = _reviewed_mixed_source_producer_fixture(tmp_path, architecture)
    fixture.options["max_output_tokens"] = 4096 if architecture == "causal_lm" else 4097
    producer = worker.make_reviewed_decoder_source_producer_v3(fixture.runtime, **fixture.options)
    def forbidden(**kwargs):
        pytest.fail("over-budget V3 output reached actual forward")
    monkeypatch.setattr(fixture.local.backend.model, "forward", forbidden)
    arguments = tuple({"id": row["id"], "source_text": row["source_text"], "context": {"permitted": [], "retrieved": []}} for row in fixture.rows)
    with pytest.raises(worker.TrainingJobValidationError, match="full generation budget"):
        producer(arguments)
    assert producer.observation()["last_call"]["entry_pair_match"] is producer.observation()["last_call"]["exit_pair_match"] is True
    assert fixture.local.backend.restored_checkpoint_matches(fixture.local.checkpoint["model_state"], fixture.local.checkpoint["optimizer_state"]) is True


@pytest.mark.parametrize("damage", ["target-key", "retrieved-target"])
def test_reviewed_mixed_source_v3_reference_target_in_source_arguments_refuses_before_builder(tmp_path, monkeypatch, damage):
    from copy import deepcopy
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    fixture = _reviewed_mixed_source_producer_fixture(tmp_path)
    producer = worker.make_reviewed_decoder_source_producer_v3(fixture.runtime, **fixture.options)
    arguments = [{"id": row["id"], "source_text": row["source_text"], "context": {"permitted": [], "retrieved": []}} for row in fixture.rows]
    if damage == "target-key":
        arguments[0]["canonical_ir"] = deepcopy(fixture.rows[0]["canonical_ir"])
    else:
        arguments[0]["context"]["retrieved"] = [deepcopy(fixture.rows[0]["canonical_ir"])]
    def forbidden(*args, **kwargs):
        pytest.fail("reference-bearing argument reached pure source-only builder")
    monkeypatch.setattr(inputs, "prepare_reviewed_decoder_generation_inputs", forbidden)
    with pytest.raises(worker.TrainingJobValidationError, match="exact source arguments"):
        producer(tuple(arguments))
    assert producer.observation()["last_call"]["exit_pair_match"] is True


@pytest.fixture(scope="module")
def reviewed_mixed_rich_v3_local_template(tmp_path_factory):
    """One existing tiny local checkpoint; no downloaded or corpus-trained asset."""
    from copy import deepcopy
    from types import SimpleNamespace
    import uuid
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    ch,options,populations,replays,components=evaluation._rich_v3_heldout_case()
    path=tmp_path_factory.mktemp("mixed-rich-local-"+uuid.uuid4().hex, numbered=False)
    local=_reviewed_local_loader_hf_fixture(path,"encoder_decoder",max_sequence_tokens=4096,
        fixed_json_schema_subwords=True,fixed_typed_schema_subwords=True)
    declaration=components["holdout"]["declaration"]
    contexts={"profile":"reviewed-source-selection-context/v2",
        "selection_context":{"schema":"caller-known-interpretation-selection/v1",
            "interpretation_id":declaration["interpretation_id"],"selection_mode":"identifier_only"},
        "rows":[{"id":"reviewed:"+u["unit_id"],"unit_id":u["unit_id"],
            "governing_context":deepcopy(declaration["governing_context"]),
            "source_binding":{"source_version_cid":u["source_version"]["record_cid"],
                "occurrence_cid":u["occurrence"]["record_cid"],"document_revision":u["document_revision"]}}
            for u in declaration["units"]]}
    return SimpleNamespace(local=local,evaluation=evaluation,consumer=consumer,options=options,
        populations=populations,contexts=contexts)


@pytest.mark.parametrize("mode",["healthy","train_revoked","query_revoked","policy_denied"])
def test_reviewed_mixed_rich_v3_numerical_transport(reviewed_mixed_rich_v3_local_template,monkeypatch,mode):
    from copy import deepcopy
    template=reviewed_mixed_rich_v3_local_template
    local,evaluation,consumer=template.local,template.evaluation,template.consumer
    _reviewed_local_loader_no_remote_or_training(monkeypatch,local)
    options=template.options
    query_inputs=deepcopy(options["admission_inputs"])
    original_context=options["reviewed_training_context"]
    context={key:(value if key=="binding" else deepcopy(value)) for key,value in original_context.items()}
    state={"train_revoked":False,"query_revoked":False}
    def fresh_query():
        current=deepcopy(query_inputs)
        if state["query_revoked"]:current["registry"]["keys"][0]["revoked_at_utc"]="2026-01-01T00:00:00Z"
        return current
    def fresh_context():
        value={key:(item if key=="binding" else deepcopy(item)) for key,item in context.items()}
        if state["train_revoked"]:value["admission_inputs"]["registry"]["keys"][0]["revoked_at_utc"]="2026-01-01T00:00:00Z"
        return value
    profile=consumer.REVIEWED_V3_HELDOUT_CONTEXT_PROFILE
    def context_digest(value):
        return evaluation._producer_digest({"schema":"reviewed-decoder-rich-context-inputs/v1","profile":profile,
            "binding_receipt_sha256":evaluation._producer_digest(value["binding"].receipt()),
            "training_rows_sha256":evaluation._producer_digest(value["training_rows"]),
            "split_manifest_sha256":evaluation._producer_digest(value["split_manifest"]),
            "admission_inputs_sha256":consumer.reviewed_admission_inputs_sha256(value["admission_inputs"]),
            "exposure_records_sha256":evaluation._producer_digest(value["exposure_records"]),
            "query_rows_sha256":evaluation._producer_digest(value["query_rows"]),
            "retrieval_rows_sha256":evaluation._producer_digest(value["retrieval_rows"])})
    def policy(value):
        assert value["context_profile"]==profile and value["heldout_requested"] is True
        if mode=="policy_denied":raise PermissionError("explicit fictional rich model context denial")
    runtime=worker.ReviewedDecoderRuntime(local.options["registry"],local.backend,local.backend.tokenizer,
        fresh_query,local.options["execution_guard"],local.options["asset_policy_guard"])
    kwargs=dict(binding=options["binding"],rows=deepcopy(options["rows"]),
        split_manifest=deepcopy(options["split_manifest"]),exposure_records=deepcopy(options["exposure_records"]),
        source_contexts=deepcopy(template.contexts),expected_source_contexts_sha256=evaluation._producer_digest(template.contexts),
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(fresh_query()),
        backend_identity=local.backend.identity(),assets=tuple(local.options[k] for k in
            ("recipe_artifact","model_config_artifact","tokenizer_artifact","license_artifact")),
        model_checkpoint=local.options["model_checkpoint"],optimizer_checkpoint=local.options["optimizer_checkpoint"],
        max_source_tokens=4096,max_output_tokens=3,allow_heldout_evaluation=True,
        context_profile=profile,current_context_inputs_provider=fresh_context,
        expected_context_inputs_sha256=context_digest(fresh_context()),context_policy_guard=policy)
    if mode=="healthy":
        from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as source_inputs
        source_arguments=[dict(id=r["id"],source_text=r["source_text"],context={"permitted":[],
            "retrieved":deepcopy(options["retrieved_examples"][r["id"]])}) for r in kwargs["rows"]]
        context_population=[dict(id=r["id"],context=r["context"]) for r in source_arguments]
        try:
            source_inputs.prepare_reviewed_decoder_context_generation_inputs(source_arguments,
                source_contexts=kwargs["source_contexts"],expected_source_contexts_sha256=kwargs["expected_source_contexts_sha256"],
                expected_context_records_sha256=evaluation._producer_digest(context_population),
                tokenizer=local.backend.tokenizer,max_source_tokens=kwargs["max_source_tokens"])
        except ValueError as error:
            values=[{"id":r["id"],"context_bytes":len(worker._json_bytes({"profile":worker.REVIEWED_GENERATION_CONTEXT_PROFILE,
                "mode":"rich_full_ast",**r["context"]}))} for r in source_arguments]
            error.add_note("Complete original context sizes: "+json.dumps(values,sort_keys=True))
            raise
    forwards=[]
    def observe(module,args,keywords,result):
        forwards.append({k:v.detach().clone() for k,v in keywords.items() if hasattr(v,"detach")})
        if mode in state:state[mode]=True
        return None
    hook=local.backend.model.register_forward_hook(observe,with_kwargs=True)
    rng=local.torch.get_rng_state().clone()
    try:
        if mode=="policy_denied":
            with pytest.raises(PermissionError,match="rich model context denial"):
                worker.make_reviewed_decoder_source_producer_v3(runtime,**kwargs)
            assert forwards==[]
        else:
            producer=worker.make_reviewed_decoder_source_producer_v3(runtime,**kwargs)
            declarations={"encoder":{"id":"fixture:encoder-declaration-only","sha256":"1"*64},
                "decoder":{"id":kwargs["backend_identity"]["backend_id"],"sha256":kwargs["model_checkpoint"].sha256}}
            if mode!="healthy":
                with pytest.raises(ValueError):producer.evaluate(compiler_commit="fixture:mixed-rich-local",checkpoint_declarations=declarations)
                assert forwards
            else:
                result=producer.evaluate(compiler_commit="fixture:mixed-rich-local",checkpoint_declarations=declarations)
                payload=evaluation._producer_payload(result);metrics=result.to_dict()["metrics"]["complete_norm_payload"]
                assert metrics["denominator"]==metrics["outcome_counts"]["abstained"]==len(forwards)==3
                assert producer.observation()["context"]["profile"]==profile
                for call,row in zip(forwards,kwargs["rows"],strict=True):
                    assert "labels" not in call and call["decoder_input_ids"].tolist()==[[257]]
                    source=json.loads(local.backend.tokenizer.decode(call["input_ids"].tolist()[0][1:-1]))
                    assert source["source_text"]==row["source_text"]
                    assert "canonical_ir" not in source and "typed_expression" not in source
                    assert {e["id"] for e in source["context"]["retrieved"]}=={r["id"] for r in
                        (template.populations["train"][0],template.populations["train"][2])}
                    for example in source["context"]["retrieved"]:
                        expected=next(r for r in template.populations["train"] if r["id"]==example["id"])
                        assert example["content"]["canonical_ir"]==expected["canonical_ir"]
                assert payload["heldout_generalization_established"] is payload["corpus_admitted"] is False
    finally:
        hook.remove()
    assert local.backend.restored_checkpoint_matches(local.checkpoint["model_state"],local.checkpoint["optimizer_state"]) is True
    assert local.torch.equal(local.torch.get_rng_state(),rng)


# Admission V3 loading is explicit; the V2 loader keeps its original defaults.
@pytest.mark.parametrize("profile", [None, "complete-reviewed-norm-admission/v2", []])
def test_reviewed_local_loader_v3_closed_profile_refuses_before_callbacks(tmp_path, profile):
    options = _reviewed_local_loader_denial_inputs(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("invalid V3 loader profile reached a live callback")
    with pytest.raises(worker.TrainingJobValidationError, match="explicit mixed-sort admission V3 load profile"):
        worker.load_local_reviewed_decoder_runtime_v3(**options, admission_profile=profile,
            execution_guard=forbidden, asset_policy_guard=forbidden, current_admission_provider=forbidden)


@pytest.mark.parametrize("domain", ["legacy-with-v3-pins", "v3-with-legacy-pins"])
def test_reviewed_local_loader_v3_domain_swap_refuses_before_asset_or_model_import(tmp_path, monkeypatch, domain):
    import builtins
    options = _reviewed_local_loader_denial_inputs(tmp_path)
    load = worker.load_local_reviewed_decoder_runtime
    profile_options = {}
    if domain == "legacy-with-v3-pins":
        options["expected_source_sha256"] = worker._reviewed_decoder_source_pins(
            admission_profile=worker.REVIEWED_MIXED_ADMISSION_PROFILE)
    else:
        load = worker.load_local_reviewed_decoder_runtime_v3
        profile_options["admission_profile"] = worker.REVIEWED_MIXED_ADMISSION_PROFILE
    calls = []
    def execution(): calls.append("execution")
    def forbidden(*args, **kwargs):
        pytest.fail("loader admission-domain swap reached assets or current admission")
    original_import = builtins.__import__
    def no_model_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("loader admission-domain swap reached a model import")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_model_import)
    with pytest.raises(worker.TrainingJobValidationError, match="source changed"):
        load(**options, **profile_options, execution_guard=execution,
            asset_policy_guard=forbidden, current_admission_provider=forbidden)
    assert calls == ["execution"]


def test_reviewed_local_loader_v3_original_asset_denial_preserves_error_before_model_import(tmp_path, monkeypatch):
    import builtins
    options = _reviewed_local_loader_denial_inputs(tmp_path)
    options["expected_source_sha256"] = worker._reviewed_decoder_source_pins(
        admission_profile=worker.REVIEWED_MIXED_ADMISSION_PROFILE)
    denial = PermissionError("original asset policy independently denied V3 loading")
    policies = []
    def deny(policy):
        policies.append(policy)
        raise denial
    def forbidden(*args, **kwargs):
        pytest.fail("denied V3 loader read current admission")
    original_import = builtins.__import__
    def no_model_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("denied V3 loader imported a model package")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_model_import)
    with pytest.raises(PermissionError) as captured:
        worker.load_local_reviewed_decoder_runtime_v3(**options,
            admission_profile=worker.REVIEWED_MIXED_ADMISSION_PROFILE,
            execution_guard=lambda: None, asset_policy_guard=deny, current_admission_provider=forbidden)
    assert captured.value is denial and len(policies) == 1
    assert policies[0]["schema"] == "reviewed-local-decoder-load-policy/v2"
    assert policies[0]["admission_profile"] == worker.REVIEWED_MIXED_ADMISSION_PROFILE
    assert policies[0]["training_requested"] is policies[0]["downloads_requested"] is policies[0]["resource_grant_requested"] is False


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_local_loader_v3_restores_exact_builtin_pair_in_explicit_domain(tmp_path, monkeypatch, architecture):
    fixture = _reviewed_mixed_source_producer_fixture(tmp_path, architecture)
    local = fixture.local
    _reviewed_local_loader_no_remote_or_training(monkeypatch, local)
    options = dict(local.options)
    options["expected_source_sha256"] = worker._reviewed_decoder_source_pins(
        admission_profile=worker.REVIEWED_MIXED_ADMISSION_PROFILE)
    policies = []
    original_asset_guard = options["asset_policy_guard"]
    def asset_policy(policy):
        original_asset_guard(policy)
        policies.append(policy)
    options["asset_policy_guard"] = asset_policy
    runtime, receipt = worker.load_local_reviewed_decoder_runtime_v3(**options,
        admission_profile=worker.REVIEWED_MIXED_ADMISSION_PROFILE)
    assert receipt["schema"] == "reviewed-local-decoder-runtime-load/v2"
    assert receipt["admission_profile"] == worker.REVIEWED_MIXED_ADMISSION_PROFILE
    assert receipt["producer_pins"] == options["expected_source_sha256"]
    assert receipt["producer_pins"]["admission"] != worker._reviewed_decoder_source_pins()["admission"]
    assert receipt["checkpoint_restored"] is receipt["matched_pair"] is True
    assert runtime.backend.identity() == local.backend.identity() == receipt["loaded_backend_identity"]
    assert runtime.backend.restored_checkpoint_matches(local.checkpoint["model_state"], local.checkpoint["optimizer_state"]) is True
    assert runtime.backend._optimizer_steps == 1 and local.torch.equal(local.torch.get_rng_state(), local.pair_rng)
    assert policies and all(policy["admission_profile"] == worker.REVIEWED_MIXED_ADMISSION_PROFILE for policy in policies)
    assert all(policy["schema"] == "reviewed-local-decoder-load-policy/v2" for policy in policies)
    assert all(receipt[name] is False for name in ("training_performed", "downloads_performed", "resource_granted",
        "license_bytes_are_permission", "pretrained_quality_verified", "legal_meaning_verified", "proof_authority",
        "convergence_proved", "corpus_admitted", "automatic_old_source_checkpoint_migration"))



def _reviewed_mixed_rich_v3_complete_input_capacity():
    """Real fixed tokenizer and canonical builder, with no model or file output."""
    from copy import deepcopy
    from tokenizers import Tokenizer,AddedToken,models,pre_tokenizers,decoders
    from transformers import PreTrainedTokenizerFast
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    _,options,populations,_,components=evaluation._rich_v3_heldout_case()
    vocabulary={"[EOS]":0,**{v:i+1 for i,v in enumerate(sorted(pre_tokenizers.ByteLevel.alphabet()))},
        "[BOS]":257,"[UNK]":258,"[PAD]":259}
    _reviewed_local_loader_fixed_typed_schema_bpe(vocabulary)
    native=Tokenizer(models.Unigram([(token,-1.0) for token,index in sorted(vocabulary.items(),key=lambda p:p[1])],unk_id=258))
    native.pre_tokenizer=pre_tokenizers.ByteLevel(add_prefix_space=False,use_regex=False);native.decoder=decoders.ByteLevel()
    native.add_special_tokens([AddedToken(v,normalized=False,special=True) for v in ("[EOS]","[BOS]","[UNK]","[PAD]")])
    frontend=PreTrainedTokenizerFast(tokenizer_object=native,bos_token="[BOS]",eos_token="[EOS]",
        unk_token="[UNK]",pad_token="[PAD]",model_max_length=4096,clean_up_tokenization_spaces=False)
    tokenizer=worker.ReviewedPretrainedTokenizer(frontend,bos_token_id=257,eos_token_id=0,vocab_size=len(vocabulary))
    declaration=components["holdout"]["declaration"]
    contexts={"profile":"reviewed-source-selection-context/v2",
        "selection_context":{"schema":"caller-known-interpretation-selection/v1",
            "interpretation_id":declaration["interpretation_id"],"selection_mode":"identifier_only"},
        "rows":[{"id":"reviewed:"+u["unit_id"],"unit_id":u["unit_id"],
            "governing_context":deepcopy(declaration["governing_context"]),
            "source_binding":{"source_version_cid":u["source_version"]["record_cid"],
                "occurrence_cid":u["occurrence"]["record_cid"],"document_revision":u["document_revision"]}}
            for u in declaration["units"]]}
    arguments=[dict(id=r["id"],source_text=r["source_text"],context={"permitted":[],
        "retrieved":deepcopy(options["retrieved_examples"][r["id"]])}) for r in options["rows"]]
    context_population=[dict(id=r["id"],context=r["context"]) for r in arguments]
    prepared=inputs.prepare_reviewed_decoder_context_generation_inputs(arguments,
        source_contexts=contexts,expected_source_contexts_sha256=evaluation._producer_digest(contexts),
        expected_context_records_sha256=evaluation._producer_digest(context_population),
        tokenizer=tokenizer,max_source_tokens=4096)
    assert len(prepared["records"])==3 and prepared["receipt"]["target_access_performed"] is False
    token_counts=[]
    for original,record in zip(arguments,prepared["records"],strict=True):
        decoded=tokenizer.decode(record["source_token_ids"][1:-1]);assert decoded==record["source_wire"]
        source=json.loads(decoded)
        assert source["source_text"]==original["source_text"] and source["context"]["retrieved"]==original["context"]["retrieved"]
        for example in source["context"]["retrieved"]:
            expected=next(r for r in populations["train"] if r["id"]==example["id"])
            assert example["content"]["canonical_ir"]==expected["canonical_ir"]
        assert len(record["source_token_ids"])<=4096
        token_counts.append(len(record["source_token_ids"]))
    # The same complete examples must still refuse the original byte/schema
    # baseline when its token stream exceeds the unchanged budget.
    old_vocab={"[EOS]":0,**{v:i+1 for i,v in enumerate(sorted(pre_tokenizers.ByteLevel.alphabet()))},
        "[BOS]":257,"[UNK]":258,"[PAD]":259}
    old_merges=_reviewed_local_loader_fixed_schema_bpe(old_vocab)
    old_native=Tokenizer(models.BPE(vocab=old_vocab,merges=old_merges,unk_token="[UNK]"))
    old_native.pre_tokenizer=pre_tokenizers.ByteLevel(add_prefix_space=False,use_regex=False);old_native.decoder=decoders.ByteLevel()
    old_native.add_special_tokens([AddedToken(v,normalized=False,special=True) for v in ("[EOS]","[BOS]","[UNK]","[PAD]")])
    old_frontend=PreTrainedTokenizerFast(tokenizer_object=old_native,bos_token="[BOS]",eos_token="[EOS]",
        unk_token="[UNK]",pad_token="[PAD]",model_max_length=4096,clean_up_tokenization_spaces=False)
    old_tokenizer=worker.ReviewedPretrainedTokenizer(old_frontend,bos_token_id=257,eos_token_id=0,vocab_size=len(old_vocab))
    with pytest.raises(inputs.ReviewedDecoderInputValidationError,match="token"):
        inputs.prepare_reviewed_decoder_context_generation_inputs(arguments,
            source_contexts=contexts,expected_source_contexts_sha256=evaluation._producer_digest(contexts),
            expected_context_records_sha256=evaluation._producer_digest(context_population),
            tokenizer=old_tokenizer,max_source_tokens=4096)
    return {"rows":3,"complete_source_token_counts":token_counts,"vocabulary_size":len(vocabulary),
        "byte_limit":worker.REVIEWED_GENERATION_CONTEXT_MAX_BYTES,"context_token_limit":worker.REVIEWED_GENERATION_CONTEXT_MAX_TOKENS,
        "tokenizer_sha256":hashlib.sha256(tokenizer.pipeline_serialization()).hexdigest(),
        "all_source_and_train_ast_bytes_preserved":True,"legacy_over_budget_tokenizer_refused":True,"model_loaded":False,"model_inference_performed":False}


def test_reviewed_mixed_rich_v3_lossless_input_capacity():
    result=_reviewed_mixed_rich_v3_complete_input_capacity()
    assert result["rows"]==3 and result["all_source_and_train_ast_bytes_preserved"] is True


def _run_actual_GTE_ranked_decoder_case(tmp_path, monkeypatch, *, transport="shared_json_v1",
        ranking_modes=("lexical", "raw", "joint")):
    """Complete ranked context capacity; separate actual source-only T5 baseline."""
    from copy import deepcopy
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    from tests.unit.optimizers.logic_theorem_optimizer import test_autoencoder_embedding_runtime as embeddings
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_structured_retrieval as rich
    from tests.unit.logic.formalization.autoencoder import test_alignment_relation_mask_handoff as pairs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as source_inputs
    shorttag = transport == "shared_json_v2"
    pack_context = source_inputs.pack_reviewed_context_json_v2 if shorttag else source_inputs.pack_reviewed_context_json_v1
    unpack_context = source_inputs.unpack_reviewed_context_json_v2 if shorttag else source_inputs.unpack_reviewed_context_json_v1
    source_profile = (worker.REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V2 if shorttag
                      else worker.REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE)
    encoder_path = tmp_path / "actual-encoder"
    encoder_path.mkdir()
    actual = embeddings._run_actual_GTE_fixed_heldout_case(encoder_path)
    # The encoder stage has returned only immutable receipts/data and its tiny
    # projection. Reclaim unreachable vendor-model cycles before allocating the
    # next model; preserve the original checkpoint, full tokens and RSS limit.
    import gc
    before_collection = worker._memory_observation()
    collected = gc.collect(2)
    after_collection = worker._memory_observation()
    trim_supported, trim_result = False, None
    import sys
    if sys.platform == "linux":
        import ctypes
        libc = ctypes.CDLL(None)
        if hasattr(libc, "malloc_trim"):
            trim_supported = True
            libc.malloc_trim.argtypes = [ctypes.c_size_t]
            libc.malloc_trim.restype = ctypes.c_int
            trim_result = libc.malloc_trim(0)
    actual["save"]("actual-GTE-decoder-stage-memory.json", dict(
        before_collection=before_collection, after_collection=after_collection,
        after_allocator_trim=worker._memory_observation(), allocator_trim_supported=trim_supported,
        allocator_trim_result=trim_result, unreachable_objects_collected=collected,
        model_or_token_budget_changed=False))
    options, populations = actual["options"], actual["populations"]
    local_path = tmp_path / "local-decoder"
    local_path.mkdir()
    local = _reviewed_local_loader_hf_fixture(local_path, "encoder_decoder", max_sequence_tokens=4096,
        fixed_json_schema_subwords=True, fixed_typed_schema_subwords=True)
    _reviewed_local_loader_no_remote_or_training(monkeypatch, local)
    runtime = worker.ReviewedDecoderRuntime(local.options["registry"], local.backend, local.backend.tokenizer,
        lambda: deepcopy(actual["replays"]["holdout"]), local.options["execution_guard"], local.options["asset_policy_guard"])
    declaration = actual["components"]["holdout"]["declaration"]
    contexts = {"profile": "reviewed-source-selection-context/v2",
        "selection_context": {"schema": "caller-known-interpretation-selection/v1",
            "interpretation_id": declaration["interpretation_id"], "selection_mode": "identifier_only"},
        "rows": [{"id": "reviewed:" + unit["unit_id"], "unit_id": unit["unit_id"],
            "governing_context": deepcopy(declaration["governing_context"]),
            "source_binding": {"source_version_cid": unit["source_version"]["record_cid"],
                "occurrence_cid": unit["occurrence"]["record_cid"], "document_revision": unit["document_revision"]}}
            for unit in declaration["units"]]}
    offered = rich._rich_consumer_inputs(pairs, actual["case"], version="v3")
    reports, arm_tokens, forwards = {}, {}, []
    state = {"revoked": False, "revoke_after_forward": False}
    def observe(module, args, keywords, result):
        forwards.append({key: value.detach().clone() for key, value in keywords.items() if hasattr(value, "detach")})
        if state["revoke_after_forward"]: state["revoked"] = True
    hook = local.backend.model.register_forward_hook(observe, with_kwargs=True)
    try:
        for mode in ranking_modes:
            retrieval_inputs = {**actual["kwargs"], **actual["common"], "mode": mode}
            prepared = structured.prepare_reviewed_ranked_training_context_v3(actual["model"], actual["queries"],
                *actual["args"], retrieval_inputs=retrieval_inputs, example_consumer_inputs=offered)
            context = prepared["context_inputs"]
            def fresh_context(context=context):
                value = {key: (item if key == "binding" else deepcopy(item)) for key, item in context.items()}
                if state["revoked"]:
                    value["admission_inputs"]["registry"]["keys"][0]["revoked_at_utc"] = "2026-01-01T00:00:00Z"
                return value
            profile = consumer.REVIEWED_V3_HELDOUT_CONTEXT_PROFILE
            def context_digest(value):
                return evaluation._producer_digest({"schema": "reviewed-decoder-rich-context-inputs/v1", "profile": profile,
                    "binding_receipt_sha256": evaluation._producer_digest(value["binding"].receipt()),
                    "training_rows_sha256": evaluation._producer_digest(value["training_rows"]),
                    "split_manifest_sha256": evaluation._producer_digest(value["split_manifest"]),
                    "admission_inputs_sha256": consumer.reviewed_admission_inputs_sha256(value["admission_inputs"]),
                    "exposure_records_sha256": evaluation._producer_digest(value["exposure_records"]),
                    "query_rows_sha256": evaluation._producer_digest(value["query_rows"]),
                    "retrieval_rows_sha256": evaluation._producer_digest(value["retrieval_rows"])})
            def allow_context(offered_policy):
                assert offered_policy["context_transport"] == transport
                assert offered_policy["shared_context_schema"] == (source_inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2
                    if shorttag else source_inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA)
                assert offered_policy["max_context_tokens"] == 4096
                assert offered_policy["max_expanded_context_bytes"] == source_inputs.REVIEWED_SHARED_CONTEXT_MAX_EXPANDED_BYTES
            kwargs = dict(binding=options["binding"], rows=deepcopy(options["rows"]),
                split_manifest=deepcopy(options["split_manifest"]), exposure_records=deepcopy(options["exposure_records"]),
                source_contexts=contexts, expected_source_contexts_sha256=evaluation._producer_digest(contexts),
                expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(actual["replays"]["holdout"]),
                backend_identity=local.backend.identity(), assets=tuple(local.options[key] for key in
                    ("recipe_artifact", "model_config_artifact", "tokenizer_artifact", "license_artifact")),
                model_checkpoint=local.options["model_checkpoint"], optimizer_checkpoint=local.options["optimizer_checkpoint"],
                max_source_tokens=4096, max_output_tokens=3, allow_heldout_evaluation=True,
                context_profile=profile, current_context_inputs_provider=fresh_context,
                expected_context_inputs_sha256=context_digest(fresh_context()), context_policy_guard=allow_context,
                context_transport=transport)
            producer = worker.make_reviewed_decoder_source_producer_v3(runtime, **kwargs)
            declarations = {"encoder": {"id": "fixture:actual-GTE-reviewed-projection", "sha256": actual["checkpoint_sha"]},
                "decoder": {"id": local.backend.identity()["backend_id"], "sha256": local.options["model_checkpoint"].sha256}}
            start = len(forwards)
            artifact = producer.evaluate(compiler_commit="fixture:actual-GTE-to-local-T5", checkpoint_declarations=declarations)
            actual["save"]("actual-GTE-local-T5-" + mode + "-producer-attempt.json", dict(
                artifact=artifact.to_dict(), observation=producer.observation(), actual_forward_count=len(forwards)-start))
            payload = evaluation._producer_payload(artifact)
            arguments = payload["producer_arguments"]
            base = source_inputs.prepare_reviewed_decoder_generation_inputs([
                dict(id=row["id"], source_text=row["source_text"], context=dict(permitted=[], retrieved=[]))
                for row in arguments], source_contexts=contexts,
                expected_source_contexts_sha256=evaluation._producer_digest(contexts),
                tokenizer=local.backend.tokenizer, max_source_tokens=4096)
            complete_inputs = []
            for argument, record in zip(arguments, base["records"], strict=True):
                wire = json.loads(record["source_wire"])
                wire["profile"] = source_profile
                wire["context"] = pack_context(argument["context"])
                text = worker._json_bytes(wire).decode()
                encoded = local.backend.tokenizer.encode(text)
                assert local.backend.tokenizer.decode(encoded) == text
                complete_inputs.append(dict(id=argument["id"], source_wire=text,
                    source_token_ids=[257, *encoded, 0], source_tokens=len(encoded)+2))
            capacity_available = all(row["source_tokens"] <= 4096 for row in complete_inputs)
            observation = producer.observation()
            metrics = artifact.to_dict()["metrics"]["complete_norm_payload"]
            if not capacity_available:
                assert len(forwards) == start and payload["producer_exception_type"] == "ReviewedDecoderInputValidationError"
                assert metrics["denominator"] == metrics["outcome_counts"]["error"] == 3
                with pytest.raises(source_inputs.ReviewedDecoderInputValidationError,
                        match="complete source with rich context token budget exceeded"):
                    source_inputs.prepare_reviewed_decoder_context_generation_inputs(arguments,
                        source_contexts=contexts, expected_source_contexts_sha256=evaluation._producer_digest(contexts),
                        expected_context_records_sha256=evaluation._producer_digest([
                            dict(id=row["id"],context=row["context"]) for row in arguments]),
                        tokenizer=local.backend.tokenizer, max_source_tokens=4096, context_transport=transport)
                reports[mode] = dict(status="complete_population_capacity_refused", producer=artifact.to_dict(),
                    observation=observation, ranking_provenance=prepared["selection_provenance"],
                    complete_inputs=complete_inputs, actual_forwards=0)
                continue
            assert len(forwards) - start == 3
            successful = (producer, kwargs, declarations)
            assert metrics["denominator"] == metrics["outcome_counts"]["abstained"] == 3
            assert observation["last_call"]["entry_pair_match"] is observation["last_call"]["exit_pair_match"] is True
            for call, query in zip(forwards[start:], populations["holdout"], strict=True):
                assert "labels" not in call and call["decoder_input_ids"].tolist() == [[257]]
                tokens = call["input_ids"].tolist()[0]
                wire = json.loads(local.backend.tokenizer.decode(tokens[1:-1]))
                assert wire["profile"] == source_profile
                # Expand the existing lossless shared codec, never a parallel decoder.
                expanded = unpack_context(wire["context"])
                assert wire["source_text"] == query["source_text"] and "canonical_ir" not in wire
                examples = expanded["retrieved"]
                assert len(examples) == 3
                for example in examples:
                    original = next(row for row in populations["train"] if row["id"] == example["id"])
                    assert example["content"]["canonical_ir"] == original["canonical_ir"]
                    assert example["content"]["source_text"] == original["source_text"]
                assert all(example["id"] != query["id"] for example in examples)
                assert json.dumps(query["canonical_ir"], sort_keys=True) not in json.dumps(wire, sort_keys=True)
            arm_tokens[mode] = [call["input_ids"].shape[1] for call in forwards[start:]]
            assert [call["input_ids"].tolist()[0] for call in forwards[start:]] == [row["source_token_ids"] for row in complete_inputs]
            reports[mode] = dict(status="model_generated", producer=artifact.to_dict(), observation=observation,
                ranking_provenance=prepared["selection_provenance"], input_tokens=arm_tokens[mode],
                complete_inputs=complete_inputs, actual_forwards=3)
        if shorttag:
            assert set(reports) == set(ranking_modes) and all(row["status"] == "model_generated" for row in reports.values())
            assert len(forwards) == 3 * len(ranking_modes)
            for report in reports.values():
                commitment = report["observation"]["input_commitment"]
                assert commitment["context_transport"] == "shared_json_v2"
                assert commitment["shared_context_schema"] == source_inputs.REVIEWED_SHARED_CONTEXT_JSON_SCHEMA_V2
            producer, kwargs, declarations = successful
            state["revoke_after_forward"] = True
            start = len(forwards)
            with pytest.raises(ValueError):
                producer.evaluate(compiler_commit="fixture:shorttag-late-TRAIN-revocation", checkpoint_declarations=declarations)
            assert len(forwards) > start and state["revoked"]
            late_observation = producer.observation()
            assert late_observation["last_call"]["completed"] is False
            state.update(revoked=False, revoke_after_forward=False)
            def deny(_): raise PermissionError("shorttag context policy denied")
            start = len(forwards)
            with pytest.raises(PermissionError, match="shorttag context policy denied"):
                worker.make_reviewed_decoder_source_producer_v3(runtime, **{**kwargs, "context_policy_guard": deny})
            assert len(forwards) == start
            assert local.backend.restored_checkpoint_matches(local.checkpoint["model_state"], local.checkpoint["optimizer_state"])
            actual["save"]("actual-GTE-shorttag-to-local-T5-" + ranking_modes[0] + ".json", dict(
                schema="actual-GTE-shorttag-local-decoder-transport/v1", arms=reports,
                common_queries=3, common_candidate_views=4, common_unique_TRAIN_units=3,
                common_max_source_tokens=4096, common_max_output_tokens=3,
                common_decoder_checkpoint_sha256=local.options["model_checkpoint"].sha256,
                full_context_model_forwards=3*len(ranking_modes), complete_outputs=0,
                abstentions=3*len(ranking_modes), capacity_refused_queries=0,
                late_TRAIN_revocation_rejected_after_forward=True, late_failure_observation=late_observation,
                policy_denied_before_forward=True, pretrained_quality_verified=False,
                semantic_relevance_metrics=None, legal_applicability_metrics=None, fictional_fixture=True))
            return
        assert len(reports) == 3 and all(row["status"] == "complete_population_capacity_refused" for row in reports.values())
        assert forwards == []
        # Separate pure source-only numerical baseline, with no TRAIN example
        # or hidden reference prefix. It does not qualify rich-context dispatch.
        baseline_inputs = deepcopy(base["records"])
        generated = local.backend.generate_batch(baseline_inputs, max_output_tokens=3,
            execution_guard=local.options["execution_guard"])
        assert len(forwards) == len(generated) == 3
        assert all(row["outcome"] == "abstained" and row["generated_token_ids"] == [257,0] for row in generated)
        for record, call, query in zip(baseline_inputs, forwards, populations["holdout"], strict=True):
            assert call["input_ids"].tolist() == [record["source_token_ids"]]
            assert call["decoder_input_ids"].tolist() == [[257]] and "labels" not in call
            wire = json.loads(record["source_wire"])
            assert wire["source_text"] == query["source_text"] and "context" not in wire and "canonical_ir" not in wire
        state["revoked"] = True
        start = len(forwards)
        with pytest.raises(ValueError):
            worker.make_reviewed_decoder_source_producer_v3(runtime, **kwargs)
        assert len(forwards) == start
        state.update(revoked=False, revoke_after_forward=False)
        def deny(_): raise PermissionError("actual GTE context policy denied")
        with pytest.raises(PermissionError, match="actual GTE context policy denied"):
            worker.make_reviewed_decoder_source_producer_v3(runtime, **{**kwargs, "context_policy_guard": deny})
        assert len(forwards) == start
        assert local.backend.restored_checkpoint_matches(local.checkpoint["model_state"], local.checkpoint["optimizer_state"])
        actual["save"]("actual-GTE-to-local-T5-three-ranking-transports.json", dict(
            schema="actual-GTE-local-decoder-transport-comparison/v1", arms=reports, common_queries=3,
            common_candidate_views=4, common_unique_TRAIN_units=3, common_max_source_tokens=4096,
            common_max_output_tokens=3, common_decoder_checkpoint_sha256=local.options["model_checkpoint"].sha256,
            TRAIN_revocation_rejected_before_forward=True, policy_denied_before_forward=True,
            pretrained_quality_verified=False, semantic_relevance_metrics=None, legal_applicability_metrics=None,
            full_context_model_forwards=0, complete_outputs=0, capacity_refused_queries=9,
            source_only_numerical_baseline=dict(records=baseline_inputs, generated=generated, actual_forwards=3,
                reviewed_rich_evaluation_qualified=False),
            capacity_refusal_is_not_semantic_error=True, fictional_fixture=True))
    finally:
        hook.remove()


def test_actual_GTE_ranked_context_capacity_and_source_only_T5_baseline(tmp_path, monkeypatch):
    _run_actual_GTE_ranked_decoder_case(tmp_path, monkeypatch)


@pytest.mark.parametrize("mode", ["lexical", "raw", "joint"])
def test_actual_GTE_shorttag_complete_context_reaches_local_T5(tmp_path, monkeypatch, mode):
    _run_actual_GTE_ranked_decoder_case(tmp_path, monkeypatch,
        transport="shared_json_v2", ranking_modes=(mode,))


def _reviewed_complete_decoder_capacity_preflight(tmp_path, descriptor, model_profile, *, framed_output_budget=None, candidate_metadata_descriptor=None):
    from tokenizers import Tokenizer
    import math
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_semantic_metrics as metrics

    def load(reference):
        path = Path(reference["path"])
        assert not path.is_symlink()
        raw = path.read_bytes()
        assert set(reference) == {"path", "bytes", "sha256"}
        assert len(raw) == reference["bytes"] and hashlib.sha256(raw).hexdigest() == reference["sha256"]
        return json.loads(raw)

    bundle = load(json.loads(descriptor))
    assert bundle["schema"] == "complete-decoder-capacity-frozen-input/v1"
    prior = load(bundle["physical_qualification"])
    assert prior["cases"] == 5 and prior["original_ranked_context_dispatch_exact"]
    close = load(bundle["physical_closeout"])
    assert close["source_closed"] and close["original_owner_custody"]["returncode"] == 0
    assert close["original_owner_custody"]["storage_released_and_durable"]
    request, evaluation, generation = (load(bundle[key]) for key in ("request", "evaluation", "generation"))
    assert hashlib.sha256(Path(bundle["request"]["path"]).read_bytes()).hexdigest() == load(bundle["parent"])["request_sha256"]
    payload = evaluation["compiler_artifact"]["reviewed_source_span_producer_evaluation"]
    contexts, training = load(request["source_contexts_artifact"]), load(request["training_context"]["rows_artifact"])
    assert bundle["source_contexts"] == request["source_contexts_artifact"] and bundle["training_rows"] == request["training_context"]["rows_artifact"]
    configuration, pipeline = load(bundle["model_config"]), load(bundle["tokenizer"])
    if model_profile == "cached_gpt2":
        assert configuration["model_type"] == "gpt2" and configuration["n_positions"] == configuration["n_ctx"] == 1024
        assert configuration["bos_token_id"] == configuration["eos_token_id"] == 50256
        positions, bos, eos = 1024, 50256, 50256
    else:
        assert model_profile == "pinned_smollm2"
        assert configuration["model_type"] == "llama" and configuration["max_position_embeddings"] == 8192
        assert configuration["bos_token_id"] == 1 and configuration["eos_token_id"] == 2
        assert configuration["torch_dtype"] == "bfloat16" and configuration["tie_word_embeddings"] is True
        positions, bos, eos = 8192, 1, 2
    native = Tokenizer.from_str(json.dumps(pipeline))
    fixture = Tokenizer.from_str(json.dumps(load(bundle["physical_tokenizer"])))
    assert native.get_vocab_size(with_added_tokens=True) == configuration["vocab_size"]
    assert native.truncation is None and native.padding is None
    contract = None
    if model_profile == "cached_gpt2":
        # Shared BOS/EOS remains unsupported; never assign an ordinary body token.
        with pytest.raises(worker.TrainingJobValidationError, match="special IDs"):
            worker.ReviewedPretrainedTokenizer(None, bos_token_id=bos, eos_token_id=eos, vocab_size=configuration["vocab_size"])
    else:
        from transformers import PreTrainedTokenizerFast
        options = load(bundle["tokenizer_config"])
        frontend = PreTrainedTokenizerFast(tokenizer_object=native, bos_token=options["bos_token"],
            eos_token=options["eos_token"], unk_token=options["unk_token"], pad_token=options["pad_token"],
            model_max_length=positions, clean_up_tokenization_spaces=False)
        transport = worker.ReviewedPretrainedTokenizer(frontend, bos_token_id=bos, eos_token_id=eos,
            vocab_size=native.get_vocab_size(with_added_tokens=True))
        contract = inputs._reviewed_decoder_tokenizer_contract(transport)
    wire = inputs._reviewed_wire
    digest = lambda value: hashlib.sha256(wire(value)).hexdigest()
    def count(text):
        ids = native.encode(text, add_special_tokens=False).ids
        assert native.decode(ids, skip_special_tokens=False) == text
        assert bos not in ids and eos not in ids
        if contract is not None:
            assert inputs._reviewed_decoder_tokens(transport, text, contract, 65536, "capacity diagnostic") == [bos, *ids, eos]
        return {"utf8_bytes": len(text.encode("utf-8")), "wire_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "native_body_tokens": len(ids), "boundary_inclusive_tokens": len(ids) + 2}
    rows, records = [], []
    for argument, context, reference in zip(payload["producer_arguments"], contexts["rows"], payload["reference_population"], strict=True):
        assert argument["id"] == context["id"] == reference["id"] and argument["source_text"] == reference["source_text"]
        source = dict(profile=inputs.REVIEWED_DECODER_SOURCE_PROFILE, source_text=argument["source_text"],
            governing_context=context["governing_context"], source_binding=context["source_binding"], selection_context=contexts["selection_context"])
        source_only = count(wire(source).decode())
        source.update(profile=worker.REVIEWED_GENERATION_SHARED_CONTEXT_SOURCE_PROFILE_V2,
                      context=inputs.pack_reviewed_context_json_v2(argument["context"]))
        rich_wire = wire(source).decode()
        ids = [257, *fixture.encode(rich_wire, add_special_tokens=False).ids, 0]
        assert fixture.decode(ids[1:-1], skip_special_tokens=False) == rich_wire
        records.append(dict(id=argument["id"], unit_id=context["unit_id"], source_wire=rich_wire, source_token_ids=ids))
        target = reference["canonical_ir"]
        assert set(target) == inputs._REVIEWED_DECODER_TARGET_FIELDS
        assert metrics._complete_norm_payload_shape(target)
        target_count, rich = count(wire(target).decode()), count(rich_wire)
        rows.append(dict(id=argument["id"], source_only=source_only, rich_source=rich, complete_target=target_count,
            source_only_causal_positions=source_only["boundary_inclusive_tokens"]+target_count["boundary_inclusive_tokens"],
            rich_causal_positions=rich["boundary_inclusive_tokens"]+target_count["boundary_inclusive_tokens"],
            source_only_fits_1024=source_only["boundary_inclusive_tokens"]+target_count["boundary_inclusive_tokens"]<=1024,
            rich_fits_1024=rich["boundary_inclusive_tokens"]+target_count["boundary_inclusive_tokens"]<=1024))
    call = generation["last_call"]
    assert len(rows) == 3 and digest(records) == call["source_records_sha256"] == call["input_receipt"]["prepared_records_sha256"]
    train_targets = []
    for row in training:
        assert set(row["canonical_ir"]) == inputs._REVIEWED_DECODER_TARGET_FIELDS
        assert metrics._complete_norm_payload_shape(row["canonical_ir"])
        train_targets.append(dict(id=row["id"], complete_target=count(wire(row["canonical_ir"]).decode())))
    assert len(train_targets) == 3
    report = dict(schema="actual-cached-gpt2-full-target-capacity/v1" if model_profile == "cached_gpt2" else "actual-pinned-Smollm2-full-target-capacity/v1", input_bundle=json.loads(descriptor),
        heldout=rows, training_targets=train_targets, complete_target_denominator=6, heldout_query_denominator=3,
        original_physical_dispatch_exactly_reconstructed=True, tokenizer_roundtrips_exact=True,
        reviewed_transport_admitted=False, refusal="native shared BOS/EOS is unsupported by current reviewed contract",
        source_only_fitting_queries=sum(row["source_only_fits_1024"] for row in rows),
        rich_fitting_queries=sum(row["rich_fits_1024"] for row in rows), model_positions=1024,
        model_weights_loaded=False, model_forward_or_fit_performed=False, pretrained_quality_verified=False,
        targets_shortened=False, labels_or_legal_meaning_created=False, runtime_or_token_limits_changed=False)
    if model_profile == "pinned_smollm2":
        header = load(bundle["tensor_header"])
        tensors = [value for key, value in header.items() if key != "__metadata__"]
        assert tensors and all(set(row) == {"dtype", "shape", "data_offsets"} and row["dtype"] == "BF16" for row in tensors)
        parameters = sum(math.prod(row["shape"]) for row in tensors)
        ordered = sorted(tensors, key=lambda row: row["data_offsets"][0])
        offset = 0
        for tensor in ordered:
            assert tensor["data_offsets"] == [offset, offset + 2 * math.prod(tensor["shape"])]
            offset = tensor["data_offsets"][1]
        assert parameters == 134515008 and offset == 2 * parameters
        assert bundle["model_file_bytes"] == 8 + bundle["header_bytes"] + offset
        metadata = load(bundle["metadata_receipt"])
        assert metadata["revision"] == "12fd25f77366fa6b3b4b768ec3050bf629380bac" and metadata["license_label"] == "apache-2.0"
        assert not metadata["weights_payload_downloaded"]
        assert load(bundle["metadata_closeout"])["original_owner_custody"]["storage_released_and_durable"]
        for row in rows:
            row["source_only_fits_model"] = row["source_only_causal_positions"] <= positions
            row["rich_fits_model"] = row["rich_causal_positions"] <= positions
            row["rich_source_fits_4096_profile"] = row["rich_source"]["boundary_inclusive_tokens"] <= 4096
        report.update(model_positions=positions, source_only_fitting_queries=sum(row["source_only_fits_model"] for row in rows),
            rich_fitting_queries=sum(row["rich_fits_model"] for row in rows),
            rich_sources_fitting_current_4096_profile=sum(row["rich_source_fits_4096_profile"] for row in rows),
            reviewed_tokenizer_contract_compatible=True, tokenizer_contract=contract,
            refusal="existing physical loader supports float32 T5/GPT2 only; no Llama/BF16 recipe admitted",
            stored_tensor_dtype="BF16", stored_parameter_count=parameters, stored_tensor_bytes=offset,
            float32_tensor_bytes=4*parameters, existing_checkpoint_byte_bound=worker.MAX_REVIEWED_DECODER_STATE_BYTES,
            stored_tensors_fit_checkpoint_bound=offset <= worker.MAX_REVIEWED_DECODER_STATE_BYTES,
            float32_tensors_fit_checkpoint_bound=4*parameters <= worker.MAX_REVIEWED_DECODER_STATE_BYTES,
            source_or_output_budget_authority_granted=False, model_weights_downloaded=False)
    if framed_output_budget is not None:
        assert model_profile == "pinned_smollm2" and type(framed_output_budget) is int and framed_output_budget == 3500
        # Independently use the pinned vendor template, not the runtime's
        # capacity calculation. Every complete source wire remains intact.
        frontend.chat_template = options["chat_template"]
        instruction = ("Translate the supplied source and permitted context into one complete LegalIR object. "
            "Output only canonical JSON with these keys: argument_roles, assumptions, cross_references, "
            "definition_uses, governing_context, interpretation_id, profile, source_binding, typed_expression. "
            "Use complete-reviewed-norm-json/v2 and TypedExpression@1. Preserve actors, modalities, ordered "
            "arguments, typed binders, conditions, exceptions, quantities, time, definitions and scope. "
            "Use no facts outside the supplied data. If required meaning or dependencies are missing, emit no body and end.")
        framed = []
        for row, record in zip(rows, records, strict=True):
            source_text = record["source_wire"]
            text = frontend.apply_chat_template([{"role": "system", "content": instruction},
                {"role": "user", "content": source_text}], tokenize=False, add_generation_prompt=True)
            assert text == ("<|im_start|>system\n" + instruction + "<|im_end|>\n"
                "<|im_start|>user\n" + source_text + "<|im_end|>\n<|im_start|>assistant\n")
            ids = native.encode(text, add_special_tokens=False).ids
            assert native.decode(ids, skip_special_tokens=False) == text
            assert ids.count(bos) == 3 and ids.count(eos) == 2
            # The frame already contains the assistant start marker. Reserve
            # the whole BOS-to-EOS answer ceiling without using target length.
            reserved = len(ids) + framed_output_budget - 1
            known_complete = len(ids) + row["complete_target"]["boundary_inclusive_tokens"] - 1
            framed.append(dict(id=row["id"], complete_source_wire_sha256=row["rich_source"]["wire_sha256"],
                framed_wire_sha256=hashlib.sha256(text.encode()).hexdigest(), framed_input_tokens=len(ids),
                output_budget=framed_output_budget, reserved_model_positions=reserved,
                required_positions_for_known_complete_reference=known_complete,
                output_reservation_fits_model=reserved <= positions,
                known_complete_reference_fits_model=known_complete <= positions))
        report["framed_complete_output_capacity"] = dict(
            schema="native-chatml-full-rich-output-reservation/v1", queries=framed,
            model_position_limit=positions, complete_output_budget=framed_output_budget,
            query_denominator=len(framed), fitting_queries=sum(x["output_reservation_fits_model"] for x in framed),
            required_model_positions_for_whole_population=max(x["reserved_model_positions"] for x in framed),
            tokenizer_vendor_template_used=True, runtime_allocation_or_forward_performed=False,
            complete_context_and_targets_preserved=True, software_cap_increase_sufficient=False)
    if candidate_metadata_descriptor is not None:
        assert framed_output_budget == 3500
        candidate_bundle = load(json.loads(candidate_metadata_descriptor))
        assert set(candidate_bundle) == {"schema", "metadata_receipt", "metadata_closeout", "metadata_request"}
        assert candidate_bundle["schema"] == "pinned-Qwen25-candidate-capacity-input/v1"
        receipt = load(candidate_bundle["metadata_receipt"])
        closeout = load(candidate_bundle["metadata_closeout"])
        metadata_request = load(candidate_bundle["metadata_request"])
        custody = closeout["original_owner_custody"]
        assert closeout["source_closed"] and custody["returncode"] == 0 and not custody["errors"] and not custody["source_drift"]
        assert all(custody[key] for key in ("genuine_wait_completed", "original_native_compute_closed",
            "original_source_exit_lifecycle_closed", "all_observed_identities_gone", "storage_released_and_durable")), "candidate metadata original custody is open"
        assert closeout["request_sha256"] == candidate_bundle["metadata_request"]["sha256"], "candidate metadata original request join differs"
        assert candidate_bundle["metadata_receipt"]["path"] == str(Path(metadata_request["attempt_directory"]) / "exports/metadata-receipt.json")
        assert receipt["repository"] == "Qwen/Qwen2.5-0.5B-Instruct" and receipt["license_label"] == "apache-2.0"
        assert not receipt["weights_payload_downloaded"] and not receipt["model_or_tokenizer_executed"] and not receipt["authority_granted"]
        api = load({key: receipt["api"][key] for key in ("path", "bytes", "sha256")})
        discovery = load({key: receipt["revision_resolution"][key] for key in ("path", "bytes", "sha256")})
        assert api["sha"] == discovery["sha"] == receipt["revision"]
        assert api["id"] == receipt["repository"] and api["gated"] is False and api["cardData"]["license"] == "apache-2.0"
        assets = receipt["assets"]
        asset_bytes = {}
        assert sum(item["bytes"] for item in assets.values()) <= 24 * 1024**2
        for name, item in assets.items():
            path = Path(item["path"])
            assert not path.is_symlink() and path.stat().st_nlink == 1 and path.is_file()
            assert path.stat().st_size == item["bytes"] <= 20 * 1024**2
            raw = path.read_bytes()
            asset_bytes[name] = raw
            assert len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
            assert "/resolve/" + receipt["revision"] + "/" in item["transport"]["url"]
        def candidate_json(name):
            return json.loads(asset_bytes[name])
        config = candidate_json("config.json")
        assert config["model_type"] == "qwen2" and config["architectures"] == ["Qwen2ForCausalLM"] and not config.get("auto_map")
        assert config["max_position_embeddings"] == 32768 and config["torch_dtype"] == "bfloat16"
        assert config["bos_token_id"] == 151643 and config["eos_token_id"] == 151645
        assert "Apache License" in asset_bytes["LICENSE"].decode()
        candidate_native = Tokenizer.from_str(asset_bytes["tokenizer.json"].decode())
        assert candidate_native.truncation is None and candidate_native.padding is None
        options = candidate_json("tokenizer_config.json")
        from transformers import PreTrainedTokenizerFast
        candidate_frontend = PreTrainedTokenizerFast(tokenizer_object=candidate_native,
            bos_token=options.get("bos_token"), eos_token=options["eos_token"],
            unk_token=options.get("unk_token"), pad_token=options["pad_token"],
            chat_template=options["chat_template"], model_max_length=config["max_position_embeddings"],
            clean_up_tokenization_spaces=False)
        assert candidate_native.token_to_id("<|im_start|>") == 151644
        assert candidate_native.token_to_id("<|im_end|>") == config["eos_token_id"]
        candidate_queries = []
        for row, record, reference in zip(rows, records, payload["reference_population"], strict=True):
            text = candidate_frontend.apply_chat_template([{"role": "system", "content": instruction},
                {"role": "user", "content": record["source_wire"]}], tokenize=False, add_generation_prompt=True)
            expected = ("<|im_start|>system\n" + instruction + "<|im_end|>\n<|im_start|>user\n" +
                record["source_wire"] + "<|im_end|>\n<|im_start|>assistant\n")
            assert text == expected
            ids = candidate_native.encode(text, add_special_tokens=False).ids
            assert ids == candidate_frontend.encode(text, add_special_tokens=False)
            assert candidate_native.decode(ids, skip_special_tokens=False) == text
            assert ids.count(151644) == 3 and ids.count(151645) == 2
            target_wire = wire(reference["canonical_ir"]).decode()
            target_ids = candidate_native.encode(target_wire, add_special_tokens=False).ids
            assert candidate_native.decode(target_ids, skip_special_tokens=False) == target_wire
            # Conservative capacity only: reserve all3500 new tokens. No
            # candidate BOS/conditioning/runtime profile is implicitly granted.
            reserved = len(ids) + framed_output_budget
            candidate_queries.append(dict(id=row["id"], complete_source_wire_sha256=row["rich_source"]["wire_sha256"],
                framed_wire_sha256=hashlib.sha256(text.encode()).hexdigest(), framed_input_tokens=len(ids),
                complete_reference_body_tokens=len(target_ids), complete_reference_with_two_boundaries=len(target_ids)+2,
                full_new_token_reservation=framed_output_budget, reserved_model_positions=reserved,
                fits_model=reserved <= config["max_position_embeddings"]))
        candidate_train_targets = []
        for row in training:
            text = wire(row["canonical_ir"]).decode(); ids = candidate_native.encode(text, add_special_tokens=False).ids
            assert candidate_native.decode(ids, skip_special_tokens=False) == text
            candidate_train_targets.append(dict(id=row["id"], complete_target_with_two_boundaries=len(ids)+2))
        header = candidate_json("safetensors-header.json")
        tensors = sorted((v for k,v in header.items() if k != "__metadata__"), key=lambda x: x["data_offsets"][0])
        offset = 0; parameters = 0
        for tensor in tensors:
            assert tensor["dtype"] == "BF16" and tensor["data_offsets"] == [offset, offset+2*math.prod(tensor["shape"])]
            parameters += math.prod(tensor["shape"]); offset = tensor["data_offsets"][1]
        assert receipt["model_file_bytes"] == 8 + receipt["header_bytes"] + offset
        report["candidate_complete_capacity"] = dict(schema="pinned-Qwen25-complete-rich-capacity/v1",
            metadata_input=json.loads(candidate_metadata_descriptor), repository=receipt["repository"], revision=receipt["revision"],
            model_positions=config["max_position_embeddings"], queries=candidate_queries, training_targets=candidate_train_targets,
            heldout_query_denominator=3, complete_target_denominator=6,
            fitting_queries=sum(row["fits_model"] for row in candidate_queries),
            stored_parameter_count_from_header=parameters, stored_BF16_tensor_bytes=offset,
            existing_checkpoint_byte_bound=worker.MAX_REVIEWED_DECODER_STATE_BYTES,
            tensors_fit_existing_checkpoint_bound=offset <= worker.MAX_REVIEWED_DECODER_STATE_BYTES,
            metadata_license_label="apache-2.0", complete_context_and_targets_preserved=True,
            current_Llama_BOS_marker_assumption_matches=config["bos_token_id"] == candidate_native.token_to_id("<|im_start|>"),
            current_runtime_integration_qualified=False, model_payload_hash_verified=False,
            weights_downloaded=False, forward_or_fit_performed=False, quality_or_legal_meaning_verified=False,
            runtime_or_resource_limits_changed=False)
    (tmp_path / "complete-target-capacity.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def test_reviewed_cached_gpt2_complete_target_preflight(tmp_path):
    """Complete native GPT2 targets are measured before any model fitting."""
    descriptor = os.environ.get("IPFS_DATASETS_TEST_DECODER_CAPACITY_INPUT")
    if descriptor is None:
        pytest.skip("explicit pinned decoder capacity DATA descriptor required")
    _reviewed_complete_decoder_capacity_preflight(tmp_path, descriptor, "cached_gpt2")


def test_reviewed_actual_fast_pinned_Smollm2_complete_target_preflight(tmp_path):
    """Check actual immutable tokenizer and tensor metadata, without weights."""
    descriptor = os.environ.get("IPFS_DATASETS_TEST_LONG_CONTEXT_CAPACITY_INPUT")
    if descriptor is None:
        pytest.skip("explicit pinned long-context capacity DATA descriptor required")
    _reviewed_complete_decoder_capacity_preflight(tmp_path, descriptor, "pinned_smollm2")


def test_reviewed_local_loader_llama_bfloat16_restores_pair_and_generates(tmp_path, monkeypatch):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", local_model_profile="builtin-llama-bfloat16/v1")
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    runtime, receipt = worker.load_local_reviewed_decoder_runtime(**fixture.options)
    torch = fixture.torch
    assert receipt["dtype"] == "bfloat16" and receipt["runtime_profile"] == "builtin-llama-bfloat16/v1"
    assert receipt["checkpoint_restored"] and receipt["matched_pair"] and receipt["optimizer_steps"] == 1
    assert all(p.dtype == torch.bfloat16 for p in runtime.backend.model.parameters())
    assert all(b.dtype == torch.float32 for _, b in runtime.backend.model.named_buffers())
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])
    assert torch.equal(torch.get_rng_state(), fixture.pair_rng)
    for name, original in fixture.backend.model.named_buffers():
        assert torch.equal(dict(runtime.backend.model.named_buffers())[name], original)
    record = _reviewed_local_loader_source_record(runtime.tokenizer)
    observed = []
    hook = runtime.backend.model.register_forward_pre_hook(lambda model, args, kwargs: observed.append(
        {key: value.detach().cpu().tolist() for key, value in kwargs.items() if torch.is_tensor(value)}), with_kwargs=True)
    try:
        outputs = runtime.backend.generate_batch([record], max_output_tokens=3, execution_guard=runtime.execution_guard)
    finally:
        hook.remove()
    assert len(observed) == 1 and observed[0]["input_ids"] == [[*record["source_token_ids"], 257]] and "labels" not in observed[0]
    assert outputs[0]["outcome"] == "abstained" and outputs[0]["generated_token_ids"] == [257, 0]
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])
    assert all(not receipt[key] for key in ("training_performed", "downloads_performed", "resource_granted", "pretrained_quality_verified", "legal_meaning_verified"))
    (tmp_path / "llama-BF16-runtime.json").write_text(json.dumps(dict(receipt=receipt, source=record,
        observed_forward=observed, outputs=outputs, real_fixture_checkpoint_restored=True, model_or_optimizer_fitted_by_loader=False), indent=2) + "\n")


@pytest.mark.parametrize("fault", ["default_profile", "v1_schema", "parameter_dtype", "config_dtype", "dynamic_rope", "remote_map", "huge_width", "byte_bound"])
def test_reviewed_local_loader_llama_bfloat16_bad_profile_refuses_before_allocation(tmp_path, monkeypatch, fault):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", local_model_profile="builtin-llama-bfloat16/v1")
    options = dict(fixture.options)
    if fault == "default_profile":
        options.pop("runtime_profile")
    elif fault in {"v1_schema", "parameter_dtype"}:
        recipe = json.loads(Path(options["recipe_artifact"].path).read_bytes())
        recipe.update({"schema": "reviewed-local-decoder-recipe/v1"} if fault == "v1_schema" else {"parameter_dtype": "float32"})
        options["recipe_artifact"] = fixture.artifact("damaged-recipe.json", worker._json_bytes(recipe))
    elif fault == "byte_bound":
        options["max_model_bytes"] = 1
    else:
        config = json.loads(Path(options["model_config_artifact"].path).read_bytes())
        if fault == "config_dtype":
            config["dtype"] = "float32"
        elif fault == "dynamic_rope":
            config["rope_parameters"] = {"rope_type": "linear", "rope_theta": 10000.0, "factor": 2.0}
        elif fault == "remote_map":
            config["auto_map"] = {"AutoModelForCausalLM": "fixture.remote.Model"}
        else:
            config["hidden_size"] = 10**9
        options["model_config_artifact"] = fixture.artifact("damaged-config.json", worker._json_bytes(config))
    entry = fixture.torch.get_rng_state().clone()
    monkeypatch.setattr(fixture.model_class, "__init__", lambda *args, **kwargs: pytest.fail("invalid Llama profile reached model construction"))
    monkeypatch.setattr(fixture.torch.nn.Module, "to_empty", lambda *args, **kwargs: pytest.fail("invalid Llama profile allocated CPU tensors"))
    with pytest.raises(worker.TrainingJobValidationError):
        worker.load_local_reviewed_decoder_runtime(**options)
    assert fixture.torch.equal(fixture.torch.get_rng_state(), entry)


def test_reviewed_local_loader_llama_bfloat16_original_policy_sees_dtype_before_import(tmp_path, monkeypatch):
    import builtins
    options = _reviewed_local_loader_denial_inputs(tmp_path)
    denied = PermissionError("original BF16 asset policy denied")
    def policy(value):
        assert value["dtype"] == "bfloat16" and value["runtime_profile"] == "builtin-llama-bfloat16/v1"
        assert not value["training_requested"] and not value["downloads_requested"]
        raise denied
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"torch", "transformers", "tokenizers"}:
            pytest.fail("BF16 loader imported a model package before original policy denial")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(PermissionError) as caught:
        worker.load_local_reviewed_decoder_runtime(**options, runtime_profile="builtin-llama-bfloat16/v1",
            execution_guard=lambda: None, asset_policy_guard=policy,
            current_admission_provider=lambda: pytest.fail("admission read after original asset denial"))
    assert caught.value is denied


@pytest.mark.parametrize("buffer", ["inv_freq", "original_inv_freq"])
def test_reviewed_local_loader_llama_bfloat16_changed_rotary_recipe_refuses(tmp_path, buffer):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", local_model_profile="builtin-llama-bfloat16/v1")
    target = dict(fixture.backend.model.named_buffers())["model.rotary_emb." + buffer]
    original = target.detach().clone()
    target.add_(0.125)
    with pytest.raises(worker.TrainingJobValidationError, match="deterministic rotary buffer"):
        fixture.backend._configuration()
    target.copy_(original)
    assert fixture.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])


def test_reviewed_local_loader_llama_bfloat16_unknown_meta_buffer_refuses_before_materialization(tmp_path, monkeypatch):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", local_model_profile="builtin-llama-bfloat16/v1")
    real = fixture.model_class.__init__
    def constructor(model, *args, **kwargs):
        real(model, *args, **kwargs)
        model.register_buffer("uncheckpointed_unknown", fixture.torch.ones(1), persistent=False)
    monkeypatch.setattr(fixture.model_class, "__init__", constructor)
    monkeypatch.setattr(fixture.torch.nn.Module, "to_empty", lambda *args, **kwargs: pytest.fail("unknown rotary state reached CPU allocation"))
    entry = fixture.torch.get_rng_state().clone()
    with pytest.raises(worker.TrainingJobValidationError, match="nonpersistent buffers"):
        worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert fixture.torch.equal(fixture.torch.get_rng_state(), entry)


@pytest.mark.parametrize("fault", ["rotary", "original_guard"])
def test_reviewed_local_loader_llama_bfloat16_post_forward_failure_restores_numeric_state(tmp_path, monkeypatch, fault):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", local_model_profile="builtin-llama-bfloat16/v1")
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    runtime, receipt = worker.load_local_reviewed_decoder_runtime(**fixture.options)
    before = {name: value.detach().clone() for name, value in runtime.backend.model.named_buffers()}
    ran = []
    def mutation(model, args, output):
        model.model.rotary_emb.inv_freq.add_(0.125)
        ran.append(True)
    hook = runtime.backend.model.register_forward_hook(mutation)
    denied = PermissionError("original caller denied after actual Llama forward")
    def guard():
        if ran and fault == "original_guard":
            raise denied
        runtime.execution_guard()
    try:
        with pytest.raises(PermissionError if fault == "original_guard" else worker.TrainingJobValidationError) as caught:
            runtime.backend.generate_batch([_reviewed_local_loader_source_record(runtime.tokenizer)],
                max_output_tokens=3, execution_guard=guard)
        if fault == "original_guard":
            assert caught.value is denied
        else:
            assert "deterministic rotary buffer" in str(caught.value)
    finally:
        hook.remove()
    assert ran == [True]
    assert all(fixture.torch.equal(value, before[name]) for name, value in runtime.backend.model.named_buffers())
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])
    assert fixture.torch.equal(fixture.torch.get_rng_state(), fixture.pair_rng)


def test_reviewed_local_loader_llama_bfloat16_v3_domain_restores_exact_pair(tmp_path, monkeypatch):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", local_model_profile="builtin-llama-bfloat16/v1")
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    options = dict(fixture.options)
    options["expected_source_sha256"] = worker._reviewed_decoder_source_pins(admission_profile=worker.REVIEWED_MIXED_ADMISSION_PROFILE)
    runtime, receipt = worker.load_local_reviewed_decoder_runtime_v3(**options, admission_profile=worker.REVIEWED_MIXED_ADMISSION_PROFILE)
    assert receipt["admission_profile"] == worker.REVIEWED_MIXED_ADMISSION_PROFILE and receipt["dtype"] == "bfloat16"
    assert receipt["producer_pins"] == options["expected_source_sha256"]
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])


@pytest.mark.parametrize("long_source", [False, True])
def test_reviewed_generation_llama_last_position_preserves_nonzero_logits_and_full_source(tmp_path, long_source):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", max_sequence_tokens=4096,
        local_model_profile="builtin-llama-bfloat16/v1")
    torch = fixture.torch
    torch.manual_seed(1729)
    with torch.no_grad():
        for parameter in fixture.backend.model.parameters():
            parameter.copy_(torch.randn_like(parameter) * 0.125)
    model = fixture.backend.model
    model.eval()
    record = _reviewed_local_loader_source_record(fixture.backend.tokenizer)
    if long_source:
        value = json.loads(record["source_wire"])
        value["source_text"] += " A" * 1024
        record["source_wire"] = worker._json_bytes(value).decode()
        record["source_token_ids"] = [257, *fixture.backend.tokenizer.encode(record["source_wire"]), 0]
    ids = torch.tensor([[*record["source_token_ids"], 257]], dtype=torch.long)
    with torch.no_grad():
        complete = model(input_ids=ids, attention_mask=torch.ones_like(ids)).logits
        selected = model(input_ids=ids, attention_mask=torch.ones_like(ids), logits_to_keep=1).logits
    assert complete.shape == (1, ids.shape[1], fixture.backend.tokenizer.vocab_size)
    assert selected.shape == (1, 1, fixture.backend.tokenizer.vocab_size)
    assert torch.equal(complete[:, -1:], selected) and bool(selected.ne(0).any())
    expected = int(complete[0, -1].argmax())
    checkpoint = fixture.backend.snapshot_checkpoint()
    inputs, head_shapes = [], []
    def observe(model, args, kwargs):
        assert kwargs["logits_to_keep"] == 1 and "labels" not in kwargs
        inputs.append(kwargs["input_ids"].detach().cpu().tolist())
    def observe_head(module, args):
        head_shapes.append(tuple(args[0].shape))
    input_hook = model.register_forward_pre_hook(observe, with_kwargs=True)
    head_hook = model.lm_head.register_forward_pre_hook(observe_head)
    try:
        outputs = fixture.backend.generate_batch([record], max_output_tokens=3, execution_guard=lambda: None)
    finally:
        input_hook.remove()
        head_hook.remove()
    assert inputs[0] == ids.tolist() and outputs[0]["generated_token_ids"][1] == expected
    assert inputs and len(inputs) == len(head_shapes) and all(shape[1] == 1 for shape in head_shapes)
    assert fixture.backend.restored_checkpoint_matches(checkpoint["model_state"], checkpoint["optimizer_state"])
    (tmp_path / "llama-last-position-parity.json").write_text(json.dumps(dict(long_source=long_source,
        full_source_tokens=len(record["source_token_ids"]), native_full_logits_shape=list(complete.shape),
        native_last_logits_shape=list(selected.shape), native_nonzero_logits_bit_equal=True,
        generated_first_token_matches_native=True, output_head_input_shapes=head_shapes,
        full_source_dispatched=True, checkpoint_restored=True, parameters_or_budget_changed=False), indent=2) + "\n")


@pytest.mark.parametrize("model_profile", ["t5", "gpt2", "llama_bfloat16"])
def test_reviewed_local_loader_restore_drops_decoded_model_before_independent_verification(tmp_path, monkeypatch, model_profile):
    """Actual restore must free its decoded model before reloading the pair.

    The saved bytes and the independent post-restore comparison remain intact;
    keeping two deserialized models alive made the real 135M loader exceed RSS.
    """
    import weakref
    fixture = _reviewed_local_loader_hf_fixture(tmp_path,
        "encoder_decoder" if model_profile == "t5" else "causal_lm",
        local_model_profile="builtin-llama-bfloat16/v1" if model_profile == "llama_bfloat16" else None)
    backend = fixture.backend
    original = backend._load_pair
    prior_model_tensors = []
    loads = []
    def observe(model_bytes, optimizer_bytes):
        if prior_model_tensors:
            assert all(item() is None for item in prior_model_tensors), "first decoded model overlaps independent verification load"
        model, optimizer = original(model_bytes, optimizer_bytes)
        prior_model_tensors[:] = [weakref.ref(value) for value in model["state"].values()]
        loads.append(1)
        return model, optimizer
    monkeypatch.setattr(backend, "_load_pair", observe)
    backend.restore_checkpoint(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])
    assert len(loads) == 2 and all(item() is None for item in prior_model_tensors)
    monkeypatch.setattr(backend, "_load_pair", original)
    assert backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])
    assert fixture.torch.equal(fixture.torch.get_rng_state(), fixture.pair_rng)
    assert backend._optimizer_steps == 1 and backend.optimizer.state


@pytest.mark.parametrize("long_source", [False, True])
def test_reviewed_generation_llama_dynamic_cache_matches_nonzero_native_prefix_and_is_row_private(tmp_path, long_source):
    import weakref
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm",
        max_sequence_tokens=4096 if long_source else 2048,
        local_model_profile="builtin-llama-bfloat16/v1")
    torch, backend = fixture.torch, fixture.backend
    torch.manual_seed(445566)
    with torch.no_grad():
        for parameter in backend.model.parameters():
            parameter.normal_(0, .05)
        # Avoid an immediate empty-output fixture; no forward or token is scripted.
        backend.model.model.embed_tokens.weight[backend.tokenizer.bos_token_id].zero_()
        backend.model.model.embed_tokens.weight[backend.tokenizer.eos_token_id].zero_()
    records = []
    for index in range(2):
        row = _reviewed_local_loader_source_record(backend.tokenizer)
        source = json.loads(row["source_wire"])
        source["source_text"] = ("A fixture clerk must file. " * (80 if long_source else 1)) + str(index)
        row.update(id="fixture:cache:"+str(index), unit_id="fixture:cache-norm:"+str(index),
            source_wire=worker._json_bytes(source).decode())
        row["source_token_ids"] = [backend.tokenizer.bos_token_id,
            *backend.tokenizer.encode(row["source_wire"]), backend.tokenizer.eos_token_id]
        records.append(row)
    before = backend.snapshot_checkpoint()
    reference = []
    modes = [(module, module.training) for module in backend.model.modules()]
    backend.model.eval()
    with torch.no_grad():
        for row in records:
            generated = [backend.tokenizer.bos_token_id]
            for _ in range(7):
                ids = torch.tensor([row["source_token_ids"]+generated], dtype=torch.long)
                logits = backend.model(input_ids=ids, attention_mask=torch.ones_like(ids),
                    logits_to_keep=1, use_cache=False).logits
                generated.append(int(logits[0,-1].argmax()))
                if generated[-1] in (backend.tokenizer.bos_token_id, backend.tokenizer.eos_token_id):
                    break
            reference.append(generated)
    for module, mode in modes:
        module.training = mode
    assert all(len(row) == 8 for row in reference)
    observed = []
    cache_refs = []
    def observe(module, args, kwargs):
        cache = kwargs.get("past_key_values")
        if cache is not None:
            cache_refs.append(weakref.ref(cache))
        observed.append(dict(input_ids=kwargs["input_ids"].tolist(),
            attention_mask=kwargs["attention_mask"].tolist(),
            position_ids=None if kwargs.get("position_ids") is None else kwargs["position_ids"].tolist(),
            prior_cache_tokens=None if cache is None else cache.get_seq_length(),
            use_cache=kwargs.get("use_cache")))
    hook = backend.model.register_forward_pre_hook(observe, with_kwargs=True)
    try:
        baseline = backend.generate_batch(records, max_output_tokens=8, execution_guard=lambda: None)
        full_calls = list(observed); observed.clear()
        assert [row["generated_token_ids"] for row in baseline] == reference
        result = backend.generate_batch(records, max_output_tokens=8, execution_guard=lambda: None,
            generation_profile="builtin-llama-dynamic-kv/v1")
    finally:
        hook.remove()
    assert [row["generated_token_ids"] for row in result] == reference
    assert backend.restored_checkpoint_matches(before["model_state"], before["optimizer_state"])
    assert cache_refs and all(item() is None for item in cache_refs)
    cursor = 0
    for row, tokens in zip(records, reference, strict=True):
        for index in range(7):
            call = observed[cursor]; cursor += 1
            assert call["input_ids"] == [row["source_token_ids"]+[tokens[0]]] if index == 0 else call["input_ids"] == [[tokens[index]]]
            assert call["prior_cache_tokens"] == (0 if index == 0 else len(row["source_token_ids"])+index)
            assert call["attention_mask"] == [[1]*(len(row["source_token_ids"])+index+1)]
            assert call["position_ids"] == [list(range(len(row["source_token_ids"])+1))] if index == 0 else call["position_ids"] == [[len(row["source_token_ids"])+index]]
            assert call["use_cache"] is True
    assert cursor == len(observed) == len(full_calls) == 14
    full_positions = sum(len(x["input_ids"][0]) for x in full_calls)
    cached_positions = sum(len(x["input_ids"][0]) for x in observed)
    assert cached_positions < full_positions
    (tmp_path/"native-dynamic-cache-parity.json").write_text(json.dumps(dict(
        source_lengths=[len(x["source_token_ids"]) for x in records], reference_tokens=reference,
        original_full_prefix_positions=full_positions, cached_positions=cached_positions,
        full_calls=full_calls, cached_calls=observed, selected_nonzero_greedy_tokens_equal=True,
        universal_logit_or_greedy_equivalence_claimed=False, exact_state_restored=True), indent=2)+"\n")


@pytest.mark.parametrize("profile", [None, False, "", "builtin-llama-dynamic-kv/v2"])
def test_reviewed_generation_llama_dynamic_cache_invalid_profile_is_data_only(monkeypatch, profile):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".",1)[0] in ("torch", "transformers"):
            pytest.fail("invalid generation profile reached native import")
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,"__import__",guarded)
    backend = object.__new__(worker.TorchReviewedDecoderBackend)
    with pytest.raises(worker.TrainingJobValidationError, match="generation profile"):
        backend.generate_batch([], max_output_tokens=8, execution_guard=lambda: pytest.fail("invalid profile reached guard"),
            generation_profile=profile)


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_generation_llama_dynamic_cache_rejects_other_native_models(tmp_path, architecture):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, architecture)
    hook = fixture.backend.model.register_forward_pre_hook(lambda *args: pytest.fail("unsupported cache profile reached forward"))
    try:
        with pytest.raises(worker.TrainingJobValidationError, match="generation profile"):
            fixture.backend.generate_batch([_reviewed_local_loader_source_record(fixture.backend.tokenizer)],
                max_output_tokens=8, execution_guard=lambda: None, generation_profile="builtin-llama-dynamic-kv/v1")
    finally:
        hook.remove()


@pytest.mark.parametrize("fault", ["missing_cache", "replacement_cache", "cropped_cache", "wrong_layer", "guard_denied"])
def test_reviewed_generation_llama_dynamic_cache_fault_restores_owned_state(tmp_path, fault):
    from transformers.cache_utils import DynamicCache
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", local_model_profile="builtin-llama-bfloat16/v1")
    backend = fixture.backend
    ran = []
    denied = PermissionError("original cached-generation caller denied after forward")
    def alter(module, args, output):
        ran.append(True)
        if fault == "missing_cache": output.past_key_values = None
        elif fault == "replacement_cache": output.past_key_values = DynamicCache(config=module.config)
        elif fault == "cropped_cache": output.past_key_values.layers[0].keys = output.past_key_values.layers[0].keys[..., :-1, :]
        elif fault == "wrong_layer": output.past_key_values.layers[0] = object()
    def guard():
        if ran and fault == "guard_denied": raise denied
    hook = backend.model.register_forward_hook(alter)
    try:
        with pytest.raises(PermissionError if fault == "guard_denied" else worker.TrainingJobValidationError) as caught:
            backend.generate_batch([_reviewed_local_loader_source_record(backend.tokenizer)], max_output_tokens=8,
                execution_guard=guard, generation_profile="builtin-llama-dynamic-kv/v1")
        if fault == "guard_denied": assert caught.value is denied
    finally:
        hook.remove()
    assert ran == [True]
    assert backend.restored_checkpoint_matches(fixture.checkpoint["model_state"],fixture.checkpoint["optimizer_state"])


@pytest.mark.parametrize("model_profile", ["t5", "gpt2", "llama_bfloat16"])
@pytest.mark.parametrize("denial", [None, "before_first_decode", "before_verification"])
def test_reviewed_local_loader_restore_current_guard_orders_decode_and_preserves_denial(tmp_path, monkeypatch, model_profile, denial):
    import weakref
    fixture = _reviewed_local_loader_hf_fixture(tmp_path,
        "encoder_decoder" if model_profile == "t5" else "causal_lm",
        local_model_profile="builtin-llama-bfloat16/v1" if model_profile == "llama_bfloat16" else None)
    backend = fixture.backend
    original = backend._load_pair
    events, decoded_refs = [], []
    denied = PermissionError("original restoration caller denied at "+str(denial))
    def observe(model_bytes, optimizer_bytes):
        events.append("decode")
        model, optimizer = original(model_bytes, optimizer_bytes)
        decoded_refs[:] = [weakref.ref(value) for value in model["state"].values()]
        return model, optimizer
    def guard():
        stage = "before_first_decode" if not events else "before_verification"
        if stage == "before_verification":
            assert all(ref() is None for ref in decoded_refs), "guard runs while first decoded model is still owned"
        events.append("guard")
        if denial == stage:
            raise denied
    monkeypatch.setattr(backend, "_load_pair", observe)
    if denial is None:
        backend.restore_checkpoint(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"], execution_guard=guard)
        assert events == ["guard", "decode", "guard", "decode"]
    else:
        with pytest.raises(PermissionError) as caught:
            backend.restore_checkpoint(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"], execution_guard=guard)
        assert caught.value is denied
        assert events == (["guard"] if denial == "before_first_decode" else ["guard", "decode", "guard"])
    monkeypatch.setattr(backend, "_load_pair", original)
    assert backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])


@pytest.mark.parametrize("guard", [False, 7, "callback"])
def test_reviewed_local_loader_restore_current_guard_invalid_is_data_only(monkeypatch, guard):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".",1)[0] in ("torch", "transformers"):
            pytest.fail("invalid restoration guard reached native import")
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,"__import__",guarded)
    backend=object.__new__(worker.TorchReviewedDecoderBackend)
    with pytest.raises(worker.TrainingJobValidationError,match="restoration execution guard"):
        backend.restore_checkpoint(b"not a checkpoint",b"not a checkpoint",execution_guard=guard)


def test_reviewed_local_loader_forwards_current_guard_at_each_restore_decode(tmp_path, monkeypatch):
    fixture=_reviewed_local_loader_hf_fixture(tmp_path,"causal_lm",local_model_profile="builtin-llama-bfloat16/v1")
    original=worker.TorchReviewedDecoderBackend._load_pair
    seen=[]
    def observe(backend,*args):
        if backend is not fixture.backend:
            seen.append(fixture.guards["execution"])
        return original(backend,*args)
    monkeypatch.setattr(worker.TorchReviewedDecoderBackend,"_load_pair",observe)
    runtime,receipt=worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert receipt["checkpoint_restored"] and receipt["matched_pair"]
    assert len(seen)>=4 and all(a<b for a,b in zip(seen,seen[1:])), "each independent decode needs a fresh original execution/source/asset/admission guard"
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"],fixture.checkpoint["optimizer_state"])


@pytest.mark.parametrize("dtype_name", ["float32", "bfloat16", "complex128"])
@pytest.mark.parametrize("layout", ["contiguous", "strided", "expanded"])
def test_reviewed_local_loader_finite_state_bounds_temporary_tensor_elements(monkeypatch, dtype_name, layout):
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    dtype = getattr(torch, dtype_name)
    if layout == "expanded":
        value = torch.ones((1, 513), dtype=dtype).expand(513, 513)
    else:
        value = torch.ones((513, 1026 if layout == "strided" else 513), dtype=dtype)
        if layout == "strided": value = value[:, ::2]
    original, visited = torch.isfinite, []
    def bounded(item):
        assert item.numel() <= 65536, "finite-state validation materializes an unbounded full-tensor temporary"
        visited.append(item.numel())
        return original(item)
    monkeypatch.setattr(torch, "isfinite", bounded)
    backend = object.__new__(worker.TorchReviewedDecoderBackend)
    backend._finite_state({"state": [value]})
    assert sum(visited) == value.numel() and len(visited) > 1
    assert torch.equal(value, torch.ones_like(value))


@pytest.mark.parametrize("nonfinite", [float("inf"), float("nan")], ids=["inf", "nan"])
@pytest.mark.parametrize("position", [(0, 0), (512, 512)], ids=["first", "last"])
def test_reviewed_local_loader_finite_state_chunk_boundary_nonfinite_refuses(monkeypatch, nonfinite, position):
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    base = torch.zeros((513, 1026), dtype=torch.bfloat16)
    value = base[:, ::2]
    value[position] = nonfinite
    original = torch.isfinite
    def bounded(item):
        assert item.numel() <= 65536, "nonfinite scan allocates a full-tensor temporary"
        return original(item)
    monkeypatch.setattr(torch, "isfinite", bounded)
    backend = object.__new__(worker.TorchReviewedDecoderBackend)
    with pytest.raises(worker.TrainingJobValidationError, match="nonfinite or oversized"):
        backend._finite_state({"state": value})
    assert not bool(original(value[position]))


def test_reviewed_local_loader_finite_state_preserves_empty_scalar_and_nested_types():
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    backend = object.__new__(worker.TorchReviewedDecoderBackend)
    backend._finite_state({"empty": torch.empty((0, 200000)), "scalar": torch.tensor(-0.),
        "nested": [torch.ones(3, dtype=torch.bool), (torch.arange(8), None, "metadata", 1, True, 1.25)]})
    for value in (float("inf"), float("nan"), object(), {object(): 1}):
        with pytest.raises(worker.TrainingJobValidationError): backend._finite_state(value)
    deep = None
    for _ in range(66): deep = [deep]
    with pytest.raises(worker.TrainingJobValidationError, match="nesting bound"):
        backend._finite_state(deep)


def test_reviewed_local_loader_finite_state_preserves_aggregate_byte_bound_before_scan(monkeypatch):
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    backend = object.__new__(worker.TorchReviewedDecoderBackend)
    monkeypatch.setattr(worker, "MAX_REVIEWED_DECODER_STATE_BYTES", 16)
    calls = []
    original = torch.isfinite
    def observe(item):
        calls.append(item.numel())
        return original(item)
    monkeypatch.setattr(torch, "isfinite", observe)
    with pytest.raises(worker.TrainingJobValidationError, match="nonfinite or oversized"):
        backend._finite_state([torch.ones(3), torch.ones(2)])
    assert calls == [3]



def _reviewed_chatml_llama_fixture(*, model_profile="builtin-llama-bfloat16/v1", context_tokens=2048):
    assert model_profile in ("builtin-llama-bfloat16/v1", "builtin-qwen2-bfloat16/v1")
    qwen2 = model_profile == "builtin-qwen2-bfloat16/v1"
    """Untrained native CPU BF16 model and exact byte-level ChatML tokenizer."""
    from types import SimpleNamespace
    import torch
    from tokenizers import Tokenizer, AddedToken, models, pre_tokenizers, decoders
    from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast
    from transformers.models.llama.modeling_llama import LlamaRotaryEmbedding
    vocabulary = {"<|endoftext|>" if qwen2 else "[UNK]": 0, "<|im_start|>": 1, "<|im_end|>": 2, "[PAD]": 3,
        **{value: index + 4 for index, value in enumerate(sorted(pre_tokenizers.ByteLevel.alphabet()))}}
    native = Tokenizer(models.BPE(vocab=vocabulary, merges=[], unk_token=None if qwen2 else "[UNK]"))
    native.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)
    native.decoder = decoders.ByteLevel()
    native.add_special_tokens([AddedToken(value, normalized=False, special=True)
        for value in ("<|endoftext|>" if qwen2 else "[UNK]", "<|im_start|>", "<|im_end|>", "[PAD]")])
    frontend = PreTrainedTokenizerFast(tokenizer_object=native, bos_token="<|endoftext|>" if qwen2 else "<|im_start|>",
        eos_token="<|im_end|>", unk_token=None if qwen2 else "[UNK]", pad_token="<|endoftext|>" if qwen2 else "[PAD]", model_max_length=context_tokens,
        clean_up_tokenization_spaces=False)
    tokenizer = worker.ReviewedPretrainedTokenizer(frontend, bos_token_id=0 if qwen2 else 1, eos_token_id=2, vocab_size=260)
    torch.manual_seed(890123)
    if qwen2:
        from transformers import Qwen2Config as Config, Qwen2ForCausalLM as Model
        from transformers.models.qwen2.modeling_qwen2 import Qwen2RotaryEmbedding as Rotary
    else:
        Config, Model, Rotary = LlamaConfig, LlamaForCausalLM, LlamaRotaryEmbedding
    config = Config(vocab_size=268 if qwen2 else 260, hidden_size=8, intermediate_size=16,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1,
        max_position_embeddings=context_tokens, attention_dropout=0.0, tie_word_embeddings=False,
        **({"use_sliding_window": False} if qwen2 else {"attention_bias": False, "mlp_bias": False}), bos_token_id=0 if qwen2 else 1, eos_token_id=2,
        pad_token_id=0 if qwen2 else 3, dtype="bfloat16")
    config._attn_implementation = "eager"
    model = Model(config).to(device="cpu", dtype=torch.bfloat16)
    rope = Rotary(config)
    for name in ("inv_freq", "original_inv_freq"):
        model.model.rotary_emb._buffers[name] = rope._buffers[name].detach().clone()
    with torch.no_grad():
        for parameter in model.parameters(): parameter.normal_(0, .05)
        if qwen2:
            model.lm_head.weight[0].zero_()
            model.lm_head.weight[260:].zero_()
            model.lm_head.weight[132:260].copy_(-model.lm_head.weight[4:132])
        model.lm_head.weight[1].zero_()
        model.lm_head.weight[2].zero_()
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001, foreach=False, fused=False)
    backend = worker.TorchReviewedDecoderBackend(model, optimizer, tokenizer, architecture="causal_lm",
        max_sequence_tokens=context_tokens, pretrained=False,
        **({"model_profile": model_profile} if qwen2 else {}))
    return SimpleNamespace(torch=torch, backend=backend, frontend=frontend)


def _reviewed_chatml_native_test_frame(frontend, wire, *, public_layouts=False):
    # Independent native template oracle; literal format matches the pinned
    # SmolLM2 tokenizer_config, not a production rendering helper.
    template = "{% for message in messages %}{% if loop.first and messages[0]['role'] != 'system' %}{{ '<|im_start|>system\\nYou are a helpful AI assistant named SmolLM, trained by Hugging Face<|im_end|>\\n' }}{% endif %}{{'<|im_start|>' + message['role'] + '\\n' + message['content'] + '<|im_end|>' + '\\n'}}{% endfor %}{% if add_generation_prompt %}{{ '<|im_start|>assistant\\n' }}{% endif %}"
    # Python holds actual newlines in the vendor template's quoted strings.
    template = template.replace("\\n", "\n")
    instruction = ("Translate the supplied source and permitted context into one complete LegalIR object. "
        "Output only canonical JSON with these keys: argument_roles, assumptions, cross_references, "
        "definition_uses, governing_context, interpretation_id, profile, source_binding, typed_expression. "
        "Use complete-reviewed-norm-json/v2 and TypedExpression@1. Preserve actors, modalities, ordered "
        "arguments, typed binders, conditions, exceptions, quantities, time, definitions and scope. "
        "Use no facts outside the supplied data. If required meaning or dependencies are missing, emit no body and end.")
    if public_layouts:
        instruction += ' Public field layouts (type notation, not answer values): argument_roles is an array of objects {"symbol":string,"roles":[string]}, never an array of strings. assumptions is an array. governing_context and source_binding have exactly the fields provided in the user source wire; interpretation_id is the supplied selection identifier. typed_expression is a complete TypedExpression@1 object: interface, schema_version, expression_id, root, signature, family, profile, content_digest, metadata, and optional range; root is a typed LogicNode with kind, symbol, arguments, binders, sort, node_id, schema_version, metadata, and optional range. definition_uses entries have definition_unit_id, defined_predicate, use_unit_id, use_occurrence_cid, target_typed_paths (nonempty string array), applicability, interpretation_id, evidence_refs. cross_references entries have from_unit_id, dependency_artifact_id, dependency_sha256, version, evidence_refs. Each evidence_refs entry has artifact_id and sha256. Copy no example answer. Do not invent dependencies, identities, symbols or missing meaning, and do not emit repeated filler. Missing required facts require an empty body and EOS. Canonical JSON uses lexicographically sorted keys and no insignificant whitespace, comments or Markdown.'
    return frontend.apply_chat_template([{"role": "system", "content": instruction},
        {"role": "user", "content": wire}], chat_template=template, tokenize=True, add_generation_prompt=True, return_dict=False)


@pytest.mark.parametrize("profile", [False, None, 7, "unknown"])
def test_reviewed_generation_chatml_invalid_profile_is_data_only(monkeypatch, profile):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".",1)[0] in ("torch", "transformers"):
            pytest.fail("invalid conditioning profile imported native code")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    backend = object.__new__(worker.TorchReviewedDecoderBackend)
    with pytest.raises(worker.TrainingJobValidationError, match="conditioning profile"):
        backend.generate_batch([], max_output_tokens=4, execution_guard=lambda: pytest.fail("guard called"),
            conditioning_profile=profile)


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-llama-dynamic-kv/v1"])
def test_reviewed_generation_chatml_matches_independent_native_frame_and_greedy_body(generation_profile):
    fixture = _reviewed_chatml_llama_fixture()
    torch, backend = fixture.torch, fixture.backend
    rows = []
    for index in range(2):
        row = _reviewed_local_loader_source_record(backend.tokenizer)
        source = json.loads(row["source_wire"])
        source["source_text"] = "A fixture clerk must file a café record. " + str(index)
        row.update(id="fixture:chatml:"+str(index), unit_id="fixture:chatml-unit:"+str(index),
            source_wire=worker._json_bytes(source).decode())
        row["source_token_ids"] = [1, *backend.tokenizer.encode(row["source_wire"]), 2]
        rows.append(row)
    frames = [_reviewed_chatml_native_test_frame(fixture.frontend, row["source_wire"]) for row in rows]
    modes = [(module, module.training) for module in backend.model.modules()]
    backend.model.eval()
    expected = []
    with torch.no_grad():
        for frame in frames:
            body = []
            for _ in range(4):
                ids = torch.tensor([frame+body], dtype=torch.long)
                output = backend.model(input_ids=ids, attention_mask=torch.ones_like(ids), logits_to_keep=1, use_cache=False)
                body.append(int(output.logits[0,-1].argmax()))
            expected.append([1, *body])
    for module, training in modes: module.training = training
    assert all(1 not in tokens[1:] and 2 not in tokens[1:] for tokens in expected)
    before = backend.snapshot_checkpoint()
    observed = []
    def observe(module, args, kwargs):
        cache = kwargs.get("past_key_values")
        observed.append(dict(ids=kwargs["input_ids"].tolist(), mask=kwargs["attention_mask"].tolist(),
            positions=None if "position_ids" not in kwargs else kwargs["position_ids"].tolist(),
            prior=None if cache is None else cache.get_seq_length(), keep=kwargs.get("logits_to_keep")))
    hook = backend.model.register_forward_pre_hook(observe, with_kwargs=True)
    try:
        result = backend.generate_batch(rows, max_output_tokens=5, execution_guard=lambda: None,
            generation_profile=generation_profile, conditioning_profile="chatml-complete-legal-ir/v1")
    finally: hook.remove()
    assert [x["generated_token_ids"] for x in result] == expected
    assert all(x["outcome"]=="incomplete" and x["reason"]=="output_limit_without_eos"
        and x["candidate"] is None and x["generated_text"] is None for x in result)
    assert len(observed)==8
    for r, frame in enumerate(frames):
        for step in range(4):
            call = observed[r*4+step]
            prefix = frame+expected[r][1:1+step]
            assert call["ids"] == ([prefix] if generation_profile=="full-prefix/v1" or step==0 else [[expected[r][step]]])
            assert call["mask"] == [[1]*len(prefix)] and call["keep"]==1
            if generation_profile=="builtin-llama-dynamic-kv/v1":
                assert call["prior"] == (0 if step==0 else len(prefix)-1)
                assert call["positions"] == ([list(range(len(frame)))] if step==0 else [[len(prefix)-1]])
    after = backend.snapshot_checkpoint()
    assert before==after and all(module.training is training for module, training in modes)


def test_reviewed_generation_chatml_default_remains_raw_source_plus_bos():
    fixture = _reviewed_chatml_llama_fixture()
    backend = fixture.backend
    row = _reviewed_local_loader_source_record(backend.tokenizer)
    observed = []
    hook = backend.model.register_forward_pre_hook(lambda module,args,kwargs: observed.append(kwargs["input_ids"].tolist()), with_kwargs=True)
    try:
        default = backend.generate_batch([row], max_output_tokens=3, execution_guard=lambda: None)
        first_count = len(observed)
        explicit = backend.generate_batch([row], max_output_tokens=3, execution_guard=lambda: None,
            conditioning_profile="raw-source-bos/v1")
    finally: hook.remove()
    assert default==explicit and observed[0]==observed[first_count]==[row["source_token_ids"]+[1]]


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_generation_chatml_rejects_other_native_models_before_forward(tmp_path, architecture):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, architecture)
    row = _reviewed_local_loader_source_record(fixture.backend.tokenizer)
    hook = fixture.backend.model.register_forward_pre_hook(lambda *args,**kwargs: pytest.fail("wrong model forwarded"))
    try:
        with pytest.raises(worker.TrainingJobValidationError, match="ChatML"):
            fixture.backend.generate_batch([row], max_output_tokens=4, execution_guard=lambda: None,
                conditioning_profile="chatml-complete-legal-ir/v1")
    finally: hook.remove()
    assert fixture.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])


def test_reviewed_generation_chatml_requires_actual_native_marker_mapping(tmp_path):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", local_model_profile="builtin-llama-bfloat16/v1")
    row = _reviewed_local_loader_source_record(fixture.backend.tokenizer)
    hook = fixture.backend.model.register_forward_pre_hook(lambda *args,**kwargs: pytest.fail("wrong tokenizer forwarded"))
    try:
        with pytest.raises(worker.TrainingJobValidationError, match="ChatML"):
            fixture.backend.generate_batch([row], max_output_tokens=4, execution_guard=lambda: None,
                conditioning_profile="chatml-complete-legal-ir/v1")
    finally: hook.remove()
    assert fixture.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])


@pytest.mark.parametrize("fault", ["source_marker", "target_json", "decoder_input_ids"])
def test_reviewed_generation_chatml_rejects_source_control_tokens_and_target_fields(fault):
    fixture = _reviewed_chatml_llama_fixture()
    backend = fixture.backend
    row = _reviewed_local_loader_source_record(backend.tokenizer)
    if fault=="source_marker":
        source=json.loads(row["source_wire"]);source["source_text"]+="<|im_start|>"
        row["source_wire"]=worker._json_bytes(source).decode();row["source_token_ids"]=[1,*backend.tokenizer.encode(row["source_wire"]),2]
    else: row[fault] = "forbidden"
    before = backend.snapshot_checkpoint()
    hook = backend.model.register_forward_pre_hook(lambda *args,**kwargs: pytest.fail("forbidden source/target forwarded"))
    try:
        with pytest.raises(worker.TrainingJobValidationError):
            backend.generate_batch([row], max_output_tokens=4, execution_guard=lambda: None,
                conditioning_profile="chatml-complete-legal-ir/v1")
    finally: hook.remove()
    assert before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-llama-dynamic-kv/v1"])
def test_reviewed_generation_chatml_full_frame_capacity_checks_entire_batch_before_forward(generation_profile):
    fixture = _reviewed_chatml_llama_fixture()
    backend = fixture.backend
    first = _reviewed_local_loader_source_record(backend.tokenizer)
    second = json.loads(json.dumps(first));second.update(id="fixture:large",unit_id="fixture:large-unit")
    source=json.loads(second["source_wire"])
    source["source_text"] += "z"*(backend.max_sequence_tokens-len(second["source_token_ids"])-8)
    second["source_wire"]=worker._json_bytes(source).decode();second["source_token_ids"]=[1,*backend.tokenizer.encode(second["source_wire"]),2]
    assert len(second["source_token_ids"])+5 <= backend.max_sequence_tokens
    assert len(_reviewed_chatml_native_test_frame(fixture.frontend,second["source_wire"]))+4 > backend.max_sequence_tokens
    before=backend.snapshot_checkpoint()
    hook=backend.model.register_forward_pre_hook(lambda *args,**kwargs: pytest.fail("oversized framed batch forwarded"))
    try:
        with pytest.raises(worker.TrainingJobValidationError,match="full generation budget"):
            backend.generate_batch([first,second],max_output_tokens=5,execution_guard=lambda:None,
                generation_profile=generation_profile,conditioning_profile="chatml-complete-legal-ir/v1")
    finally:hook.remove()
    assert before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-llama-dynamic-kv/v1"])
def test_reviewed_generation_chatml_preserves_original_post_forward_denial_and_state(generation_profile):
    fixture=_reviewed_chatml_llama_fixture();backend=fixture.backend
    row=_reviewed_local_loader_source_record(backend.tokenizer);before=backend.snapshot_checkpoint();ran=[]
    denied=PermissionError("original framed generation denial")
    hook=backend.model.register_forward_pre_hook(lambda *args,**kwargs:ran.append(True))
    def guard():
        if ran:raise denied
    try:
        with pytest.raises(PermissionError) as caught:
            backend.generate_batch([row],max_output_tokens=4,execution_guard=guard,
                generation_profile=generation_profile,conditioning_profile="chatml-complete-legal-ir/v1")
        assert caught.value is denied
    finally:hook.remove()
    assert ran==[True] and before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("response", ["", "assistant\n"])
@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-llama-dynamic-kv/v1"])
def test_reviewed_generation_chatml_authored_eos_controls_do_not_strip_generated_headers(response,generation_profile):
    fixture=_reviewed_chatml_llama_fixture();backend=fixture.backend
    row=_reviewed_local_loader_source_record(backend.tokenizer);script=[*backend.tokenizer.encode(response),2];calls=[]
    def authored_logits(module,args,output):
        # Explicit transport control after a genuine native forward; this is
        # not learned correctness or a reference-target prediction.
        index=len(calls);calls.append(True);output.logits.zero_();output.logits[0,-1,script[index]]=1
    before=backend.snapshot_checkpoint();hook=backend.model.register_forward_hook(authored_logits)
    try:
        result=backend.generate_batch([row],max_output_tokens=len(script)+1,execution_guard=lambda:None,
            generation_profile=generation_profile,conditioning_profile="chatml-complete-legal-ir/v1")[0]
    finally:hook.remove()
    assert result["generated_token_ids"]==[1,*script] and len(calls)==len(script)
    assert result["outcome"]==("abstained" if not response else "invalid") and result["candidate"] is None
    assert result["reason"]==("empty_output" if not response else "invalid_complete_norm_json")
    assert result["generated_text"]==(None if not response else response)
    assert before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("seconds", [False, 0, -1, float("nan"), float("inf"), "10", 10**1000], ids=["bool", "zero", "negative", "nan", "infinity", "text", "integer_overflow"])
def test_reviewed_generation_time_invalid_budget_is_data_only(monkeypatch, seconds):
    import builtins
    original=builtins.__import__
    def guarded(name,*args,**kwargs):
        if name.split(".",1)[0] in ("torch","transformers"):pytest.fail("invalid time budget imported native code")
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,"__import__",guarded)
    backend=object.__new__(worker.TorchReviewedDecoderBackend)
    with pytest.raises(worker.TrainingJobValidationError,match="generation time"):
        backend.generate_batch([],max_output_tokens=4,execution_guard=lambda:pytest.fail("guard called"),max_generation_seconds=seconds)


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-llama-dynamic-kv/v1"])
@pytest.mark.parametrize("conditioning_profile", ["raw-source-bos/v1", "chatml-complete-legal-ir/v1"])
def test_reviewed_generation_time_returns_each_whole_source_prefix_as_incomplete(monkeypatch,generation_profile,conditioning_profile):
    from types import SimpleNamespace
    fixture=_reviewed_chatml_llama_fixture();backend=fixture.backend
    rows=[_reviewed_local_loader_source_record(backend.tokenizer) for _ in range(2)]
    for i,row in enumerate(rows):row.update(id="fixture:timed:"+str(i),unit_id="fixture:timed-unit:"+str(i))
    frames=[_reviewed_chatml_native_test_frame(fixture.frontend,row["source_wire"]) if conditioning_profile=="chatml-complete-legal-ir/v1" else row["source_token_ids"]+[1] for row in rows]
    before=backend.snapshot_checkpoint();observed=[];ticks=iter([0.,0.,1.,10.,10.,11.]);clock_calls=[]
    def clock():
        value=next(ticks);clock_calls.append(value);return value
    hook=backend.model.register_forward_pre_hook(lambda module,args,kwargs:observed.append(kwargs["input_ids"].tolist()),with_kwargs=True)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(worker,"time",SimpleNamespace(monotonic=clock))
            result=backend.generate_batch(rows,max_output_tokens=5,execution_guard=lambda:None,
                generation_profile=generation_profile,conditioning_profile=conditioning_profile,max_generation_seconds=1.)
    finally:hook.remove()
    assert clock_calls==[0.,0.,1.,10.,10.,11.] and observed==[[frame] for frame in frames]
    assert [r["id"] for r in result]==[r["id"] for r in rows]
    assert all(r["outcome"]=="incomplete" and r["reason"]=="generation_time_limit_without_eos" and r["candidate"] is None
        and r["generated_text"] is None and len(r["generated_token_ids"])==2 and r["generated_token_ids"][0]==1
        and r["generated_token_ids"][1] not in (1,2) for r in result)
    assert before==backend.snapshot_checkpoint()


def test_reviewed_generation_time_none_keeps_legacy_behavior_without_clock_calls(monkeypatch):
    from types import SimpleNamespace
    fixture=_reviewed_chatml_llama_fixture();backend=fixture.backend;rows=[_reviewed_local_loader_source_record(backend.tokenizer)]
    before=backend.snapshot_checkpoint();baseline=backend.generate_batch(rows,max_output_tokens=3,execution_guard=lambda:None)
    with monkeypatch.context() as patch:
        patch.setattr(worker,"time",SimpleNamespace(monotonic=lambda:pytest.fail("disabled budget read clock")))
        explicit=backend.generate_batch(rows,max_output_tokens=3,execution_guard=lambda:None,max_generation_seconds=None)
    assert baseline==explicit and before==backend.snapshot_checkpoint()


def test_reviewed_generation_time_does_not_admit_oversized_full_budget_before_clock(monkeypatch):
    from types import SimpleNamespace
    fixture=_reviewed_chatml_llama_fixture();backend=fixture.backend;rows=[_reviewed_local_loader_source_record(backend.tokenizer)]
    before=backend.snapshot_checkpoint();hook=backend.model.register_forward_pre_hook(lambda *args,**kwargs:pytest.fail("oversized request forwarded"))
    try:
        with monkeypatch.context() as patch:
            patch.setattr(worker,"time",SimpleNamespace(monotonic=lambda:pytest.fail("capacity failure read generation clock")))
            with pytest.raises(worker.TrainingJobValidationError,match="full generation budget"):
                backend.generate_batch(rows,max_output_tokens=2048,execution_guard=lambda:None,
                    conditioning_profile="chatml-complete-legal-ir/v1",generation_profile="builtin-llama-dynamic-kv/v1",max_generation_seconds=.000001)
    finally:hook.remove()
    assert before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("error_type", ["permission", "native_resource"])
def test_reviewed_generation_time_preserves_original_post_forward_denial(monkeypatch,error_type):
    from types import SimpleNamespace
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources import ValidationResourceError
    fixture=_reviewed_chatml_llama_fixture();backend=fixture.backend;row=_reviewed_local_loader_source_record(backend.tokenizer)
    before=backend.snapshot_checkpoint();ran=[]
    denied=(PermissionError("original timed permission denial") if error_type=="permission" else ValidationResourceError("original timed native resource denial"))
    def guard():
        if ran:raise denied
    hook=backend.model.register_forward_pre_hook(lambda *args,**kwargs:ran.append(True))
    try:
        with monkeypatch.context() as patch:
            patch.setattr(worker,"time",SimpleNamespace(monotonic=lambda:100. if ran else 0.))
            with pytest.raises(type(denied)) as caught:
                backend.generate_batch([row],max_output_tokens=5,execution_guard=guard,
                    conditioning_profile="chatml-complete-legal-ir/v1",generation_profile="builtin-llama-dynamic-kv/v1",max_generation_seconds=1.)
            assert caught.value is denied
    finally:hook.remove()
    assert ran==[True] and before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-llama-dynamic-kv/v1"])
def test_reviewed_generation_time_keeps_completed_eos_from_last_cooperative_forward(monkeypatch,generation_profile):
    from types import SimpleNamespace
    fixture=_reviewed_chatml_llama_fixture();backend=fixture.backend;row=_reviewed_local_loader_source_record(backend.tokenizer)
    before=backend.snapshot_checkpoint();ran=[];clock_calls=[]
    def clock():
        value=100. if ran else 0.;clock_calls.append(value);return value
    def authored_eos(module,args,output):
        # Controlled EOS after a genuine forward. The clock would now report
        # overrun; cooperative stopping does not erase an already observed EOS.
        ran.append(True);output.logits.zero_();output.logits[0,-1,2]=1
    hook=backend.model.register_forward_hook(authored_eos)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(worker,"time",SimpleNamespace(monotonic=clock))
            result=backend.generate_batch([row],max_output_tokens=5,execution_guard=lambda:None,
                conditioning_profile="chatml-complete-legal-ir/v1",generation_profile=generation_profile,max_generation_seconds=1.)[0]
    finally:hook.remove()
    assert clock_calls==[0.,0.] and ran==[True] and result["generated_token_ids"]==[1,2]
    assert result["outcome"]=="abstained" and result["reason"]=="empty_output" and before==backend.snapshot_checkpoint()


def test_reviewed_generation_time_can_expire_before_first_forward_after_preflight(monkeypatch):
    from types import SimpleNamespace
    fixture=_reviewed_chatml_llama_fixture();backend=fixture.backend;row=_reviewed_local_loader_source_record(backend.tokenizer)
    before=backend.snapshot_checkpoint();ticks=iter([0.,2.]);guards=[]
    hook=backend.model.register_forward_pre_hook(lambda *args,**kwargs:pytest.fail("expired row forwarded"))
    try:
        with monkeypatch.context() as patch:
            patch.setattr(worker,"time",SimpleNamespace(monotonic=lambda:next(ticks)))
            result=backend.generate_batch([row],max_output_tokens=5,execution_guard=lambda:guards.append(True),max_generation_seconds=1.)[0]
    finally:hook.remove()
    assert len(guards)>=4 and result["generated_token_ids"]==[1] and result["outcome"]=="incomplete"
    assert result["reason"]=="generation_time_limit_without_eos" and before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("architecture", ["encoder_decoder", "causal_lm"])
def test_reviewed_generation_time_stops_actual_t5_and_gpt2_without_losing_state(tmp_path,monkeypatch,architecture):
    from types import SimpleNamespace
    fixture=_reviewed_local_loader_hf_fixture(tmp_path,architecture);backend=fixture.backend;torch=fixture.torch
    torch.manual_seed(456123)
    with torch.no_grad():
        for parameter in backend.model.parameters():parameter.normal_(0,.05)
        for token in (backend.tokenizer.bos_token_id,backend.tokenizer.eos_token_id):backend.model.get_output_embeddings().weight[token].zero_()
    row=_reviewed_local_loader_source_record(backend.tokenizer);before=backend.snapshot_checkpoint();ticks=iter([0.,0.,1.]);calls=[]
    hook=backend.model.register_forward_pre_hook(lambda *args,**kwargs:calls.append(True))
    try:
        with monkeypatch.context() as patch:
            patch.setattr(worker,"time",SimpleNamespace(monotonic=lambda:next(ticks)))
            result=backend.generate_batch([row],max_output_tokens=5,execution_guard=lambda:None,max_generation_seconds=1.)[0]
    finally:hook.remove()
    assert calls==[True] and result["outcome"]=="incomplete" and result["reason"]=="generation_time_limit_without_eos"
    assert len(result["generated_token_ids"])==2 and before==backend.snapshot_checkpoint()



def _reviewed_profiled_generation_policy():
    return {"schema":"reviewed-decoder-generation-policy/v1","generation_profile":"builtin-llama-dynamic-kv/v1",
        "conditioning_profile":"chatml-complete-legal-ir/v1","max_generation_seconds":1.0}


@pytest.mark.parametrize("damage",["none","bool","list","schema","generation","conditioning","zero","budget_bool","overflow","nan","extra"])
def test_reviewed_profiled_generation_policy_rejects_closed_data_before_native_import(monkeypatch,damage):
    import builtins
    value=_reviewed_profiled_generation_policy()
    if damage=="none":value=None
    elif damage=="bool":value=False
    elif damage=="list":value=[]
    elif damage=="schema":value["schema"]="unknown"
    elif damage=="generation":value["generation_profile"]="full-prefix/v1"
    elif damage=="conditioning":value["conditioning_profile"]="raw-source-bos/v1"
    elif damage=="zero":value["max_generation_seconds"]=0
    elif damage=="budget_bool":value["max_generation_seconds"]=True
    elif damage=="overflow":value["max_generation_seconds"]=10**1000
    elif damage=="nan":value["max_generation_seconds"]=float("nan")
    elif damage=="extra":value["decoder_input_ids"]=[1]
    original=builtins.__import__
    def no_native(name,*args,**kwargs):
        if name.split(".",1)[0] in ("torch","transformers","tokenizers"):pytest.fail("policy DATA imported native code")
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,"__import__",no_native)
    with pytest.raises(worker.TrainingJobValidationError,match="generation policy"):
        worker._reviewed_decoder_generation_policy(value)


def _reviewed_profiled_source_fixture(tmp_path, *, model_profile="builtin-llama-bfloat16/v1"):
    from types import SimpleNamespace
    base=_reviewed_mixed_source_producer_fixture(tmp_path)
    native=_reviewed_chatml_llama_fixture(model_profile=model_profile);backend=native.backend
    backend.max_sequence_tokens=4096;backend.model.config.max_position_embeddings=4096
    if model_profile=="builtin-qwen2-bfloat16/v1":
        from transformers.models.qwen2.modeling_qwen2 import Qwen2RotaryEmbedding as Rotary
    else:
        from transformers.models.llama.modeling_llama import LlamaRotaryEmbedding as Rotary
    backend.model.model.rotary_emb=Rotary(backend.model.config)
    native.frontend.model_max_length=4096;native.frontend.init_kwargs["model_max_length"]=4096
    checkpoint=backend.snapshot_checkpoint();directory=tmp_path/'profiled-assets';directory.mkdir()
    def artifact(name,raw):
        return worker.CheckpointArtifact.from_dict(_complete_reviewed_artifact(directory/name,raw))
    assets=tuple(artifact(name,raw) for name,raw in (("recipe.json",worker._json_bytes({"fixture":"profiled-source-only"})),
        ("config.json",worker._json_bytes(backend.model.config.to_dict())),
        ("tokenizer.json",native.frontend.backend_tokenizer.to_str().encode()),
        ("license.json",worker._json_bytes({"fictional_fixture_only":True}))))
    options=dict(base.options);options.update(backend_identity=backend.identity(),assets=assets,
        model_checkpoint=artifact('model.pt',checkpoint['model_state']),optimizer_checkpoint=artifact('optimizer.pt',checkpoint['optimizer_state']))
    policies=[]
    def asset(policy):policies.append(json.loads(worker._json_bytes(policy)))
    runtime=worker.ReviewedDecoderRuntime(base.runtime.registry,backend,backend.tokenizer,base.fresh,lambda:None,asset)
    return SimpleNamespace(base=base,native=native,backend=backend,runtime=runtime,options=options,policies=policies,checkpoint=checkpoint)


@pytest.mark.parametrize("mode",["healthy","denied","mutated"])
def test_reviewed_profiled_generation_source_factory_binds_forwards_and_preserves_denial(tmp_path,monkeypatch,mode):
    fixture=_reviewed_profiled_source_fixture(tmp_path);policy=_reviewed_profiled_generation_policy();backend=fixture.backend
    denied=PermissionError("original profiled producer policy denied")
    if mode!='healthy':
        def guard(offered):
            assert offered['schema']=='reviewed-decoder-source-producer-policy/v3' and offered['generation_policy']==policy
            if mode=='denied':raise denied
            policy['max_generation_seconds']=2.0
        fixture.runtime=worker.ReviewedDecoderRuntime(fixture.runtime.registry,backend,backend.tokenizer,fixture.base.fresh,lambda:None,guard)
        with pytest.raises(PermissionError if mode=='denied' else worker.TrainingJobValidationError) as caught:
            worker.make_reviewed_decoder_source_producer_v3(fixture.runtime,**fixture.options,generation_policy=policy)
        if mode=='denied':assert caught.value is denied
        assert backend.restored_checkpoint_matches(fixture.checkpoint['model_state'],fixture.checkpoint['optimizer_state'])
        return
    producer=worker.make_reviewed_decoder_source_producer_v3(fixture.runtime,**fixture.options,generation_policy=policy)
    other={**policy,'max_generation_seconds':2.0}
    second=worker.make_reviewed_decoder_source_producer_v3(fixture.runtime,**fixture.options,generation_policy=other)
    assert producer.input_profile_id!=second.input_profile_id
    fixture.policies.clear()
    calls=[];original=backend.generate_batch
    def observe(records,**options):
        assert all(set(row)=={'id','unit_id','source_wire','source_token_ids'} for row in records)
        calls.append({key:options[key] for key in ('generation_profile','conditioning_profile','max_generation_seconds')})
        return original(records,**options)
    monkeypatch.setattr(backend,'generate_batch',observe)
    declarations=fixture.base.declarations()
    declarations['decoder']={'id':fixture.options['backend_identity']['backend_id'],'sha256':fixture.options['model_checkpoint'].sha256}
    artifact=producer.evaluate(compiler_commit='fixture:profiled-source',checkpoint_declarations=declarations)
    observed=producer.observation();assert observed['schema']=='reviewed-decoder-source-producer-observation/v3'
    assert observed['input_commitment']['generation_policy']==policy and observed['input_profile_id']==producer.input_profile_id
    assert calls==[{key:policy[key] for key in ('generation_profile','conditioning_profile','max_generation_seconds')}]
    assert all(row['schema']=='reviewed-decoder-source-producer-policy/v3' and row['generation_policy']==policy for row in fixture.policies[:-1])
    assert observed['last_call']['completed'] and observed['last_call']['entry_pair_match'] and observed['last_call']['exit_pair_match']
    assert artifact.to_dict()['metrics']['complete_norm_payload']['denominator']==3
    assert backend.restored_checkpoint_matches(fixture.checkpoint['model_state'],fixture.checkpoint['optimizer_state'])



def _reviewed_chatml_local_asset_fixture(tmp_path, architecture="causal_lm", *, max_sequence_tokens=4096,
        local_model_profile="builtin-llama-bfloat16/v1", fixed_json_schema_subwords=False,
        fixed_typed_schema_subwords=False, training_conditioning_profile=None):
    """Independent native EOS fixture, not pretrained output or a legal target."""
    from types import SimpleNamespace
    from transformers.models.llama.modeling_llama import LlamaRotaryEmbedding
    assert architecture == "causal_lm" and max_sequence_tokens in (4096, 8192)
    assert type(fixed_json_schema_subwords) is bool
    assert type(fixed_typed_schema_subwords) is bool and (not fixed_typed_schema_subwords or fixed_json_schema_subwords)
    assert local_model_profile in ("builtin-llama-bfloat16/v1", "builtin-qwen2-bfloat16/v1")
    qwen2 = local_model_profile == "builtin-qwen2-bfloat16/v1"
    native = _reviewed_chatml_llama_fixture(model_profile=local_model_profile)
    backend, torch = native.backend, native.torch
    backend.max_sequence_tokens = max_sequence_tokens
    backend.model.config.max_position_embeddings = max_sequence_tokens
    if qwen2:
        from transformers.models.qwen2.modeling_qwen2 import Qwen2RotaryEmbedding
        backend.model.model.rotary_emb = Qwen2RotaryEmbedding(backend.model.config)
    else:
        backend.model.model.rotary_emb = LlamaRotaryEmbedding(backend.model.config)
    from transformers import PreTrainedTokenizerFast
    from tokenizers import Tokenizer
    native.frontend = PreTrainedTokenizerFast(
        tokenizer_object=Tokenizer.from_str(native.frontend.backend_tokenizer.to_str()),
        bos_token="<|endoftext|>" if qwen2 else "<|im_start|>", eos_token="<|im_end|>",
        unk_token=None if qwen2 else "[UNK]", pad_token="<|endoftext|>" if qwen2 else "[PAD]",
        model_max_length=max_sequence_tokens, clean_up_tokenization_spaces=False)
    if fixed_json_schema_subwords:
        from tokenizers import AddedToken, models, pre_tokenizers, decoders
        if qwen2:
            from transformers import Qwen2Config as Config, Qwen2ForCausalLM as Model
            from transformers.models.qwen2.modeling_qwen2 import Qwen2RotaryEmbedding as Rotary
        else:
            from transformers import LlamaConfig as Config, LlamaForCausalLM as Model
            Rotary = LlamaRotaryEmbedding
        vocabulary = native.frontend.get_vocab()
        merges = (_reviewed_local_loader_fixed_typed_schema_bpe(vocabulary) if fixed_typed_schema_subwords
            else _reviewed_local_loader_fixed_schema_bpe(vocabulary))
        lexicon = (Tokenizer(models.Unigram([(token, -1.0) for token, index in
            sorted(vocabulary.items(), key=lambda pair: pair[1])], unk_id=None if qwen2 else 0)) if fixed_typed_schema_subwords
            else Tokenizer(models.BPE(vocab=vocabulary, merges=merges, unk_token=None if qwen2 else "[UNK]")))
        lexicon.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)
        lexicon.decoder = decoders.ByteLevel()
        lexicon.add_special_tokens([AddedToken(value, normalized=False, special=True)
            for value in ("<|endoftext|>" if qwen2 else "[UNK]", "<|im_start|>", "<|im_end|>", "[PAD]")])
        native.frontend = PreTrainedTokenizerFast(tokenizer_object=lexicon,
            bos_token="<|endoftext|>" if qwen2 else "<|im_start|>", eos_token="<|im_end|>",
            unk_token=None if qwen2 else "[UNK]", pad_token="<|endoftext|>" if qwen2 else "[PAD]",
            model_max_length=max_sequence_tokens, clean_up_tokenization_spaces=False)
        # The first native frontend constructor installs its postprocessor.
        # Start from that complete serialization before binding an identity;
        # the local loader reconstructs the same actual native processor.
        native.frontend = PreTrainedTokenizerFast(
            tokenizer_object=Tokenizer.from_str(native.frontend.backend_tokenizer.to_str()),
            bos_token="<|endoftext|>" if qwen2 else "<|im_start|>", eos_token="<|im_end|>",
            unk_token=None if qwen2 else "[UNK]", pad_token="<|endoftext|>" if qwen2 else "[PAD]",
            model_max_length=max_sequence_tokens, clean_up_tokenization_spaces=False)
        config_data = backend.model.config.to_dict()
        config_data["vocab_size"] = len(vocabulary) + (8 if qwen2 else 0)
        config = Config.from_dict(config_data)
        config._attn_implementation = "eager"
        model = Model(config).to(device="cpu", dtype=torch.bfloat16)
        model.model.rotary_emb = Rotary(config)
        optimizer = torch.optim.AdamW(model.parameters(), lr=.001, foreach=False, fused=False)
        backend = worker.TorchReviewedDecoderBackend(model, optimizer,
            worker.ReviewedPretrainedTokenizer(native.frontend, bos_token_id=0 if qwen2 else 1, eos_token_id=2,
                vocab_size=len(vocabulary)), architecture=architecture,
            max_sequence_tokens=max_sequence_tokens, pretrained=False,
            **({"model_profile": local_model_profile} if qwen2 else {}))
    else:
        backend.tokenizer = worker.ReviewedPretrainedTokenizer(native.frontend,
            bos_token_id=0 if qwen2 else 1, eos_token_id=2, vocab_size=260)
    if training_conditioning_profile is not None:
        old=backend
        backend=worker.TorchReviewedDecoderBackend(old.model,old.optimizer,old.tokenizer,
            architecture=old.architecture,max_sequence_tokens=old.max_sequence_tokens,pretrained=old.pretrained,
            model_profile=old.model_profile,training_conditioning_profile=training_conditioning_profile)
    # A real native forward selects EOS for every token. No hook, target or
    # scripted forward supplies the result; the retained optimizer is empty.
    with torch.no_grad():
        for parameter in backend.model.parameters():
            parameter.zero_()
        backend.model.model.embed_tokens.weight[:, 0] = 1
        backend.model.model.norm.weight.fill_(1)
        backend.model.lm_head.weight[2, 0] = 1
    torch.manual_seed(271828)
    checkpoint = backend.snapshot_checkpoint()
    directory = tmp_path / architecture
    directory.mkdir()
    def artifact(name, raw):
        return worker.CheckpointArtifact.from_dict(_complete_reviewed_artifact(directory / name, raw))
    recipe = {"schema": "reviewed-local-decoder-recipe/v2", "architecture": architecture,
        "model_type": "qwen2" if qwen2 else "llama", "max_sequence_tokens": max_sequence_tokens, "pretrained": False,
        "gradient_clip": 1.0, "parameter_dtype": "bfloat16",
        "optimizer": {"learning_rate": .001, "betas": [.9, .999], "eps": 1e-8, "weight_decay": .01},
        "tokenizer": {"bos_token": "<|endoftext|>" if qwen2 else "<|im_start|>", "eos_token": "<|im_end|>",
            "unk_token": None if qwen2 else "[UNK]", "pad_token": "<|endoftext|>" if qwen2 else "[PAD]", "model_max_length": max_sequence_tokens, "clean_up_tokenization_spaces": False}}
    if training_conditioning_profile is not None:
        recipe.update(schema="reviewed-local-decoder-recipe/v3",training_conditioning_profile=training_conditioning_profile)
    assets = {"recipe_artifact": artifact("recipe.json", worker._json_bytes(recipe)),
        "model_config_artifact": artifact("config.json", worker._json_bytes(backend.model.config.to_dict())),
        "tokenizer_artifact": artifact("tokenizer.json", native.frontend.backend_tokenizer.to_str().encode()),
        "license_artifact": artifact("license.json", worker._json_bytes({"fictional_fixture_only": True,
            "pretrained_license_or_model_quality_authorized": False})),
        "model_checkpoint": artifact("model.pt", checkpoint["model_state"]),
        "optimizer_checkpoint": artifact("optimizer.pt", checkpoint["optimizer_state"])}
    return SimpleNamespace(options={**assets, "expected_backend_identity": backend.identity()},backend=backend,torch=torch)



@pytest.mark.parametrize("byte_count", [4 * 1024**2, 8 * 1024**2])
def test_reviewed_decoder_artifact_materialization_avoids_second_full_payload(tmp_path, byte_count):
    import tracemalloc
    raw = bytes(range(256)) * (byte_count // 256)
    reference = worker.CheckpointArtifact.from_dict(_complete_reviewed_artifact(tmp_path / "whole.bin", raw))
    assert not tracemalloc.is_tracing()
    tracemalloc.start()
    try:
        result = worker._reviewed_decoder_artifact(reference)
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert type(result) is bytes and result == raw
    # This concrete CPython read must not retain a complete chunk inventory
    # alongside another full returned payload. Include generous chunk slack.
    assert peak <= byte_count * 3 // 2 + 1024**2, (byte_count, current, peak)


@pytest.mark.parametrize("mode", ["short-reads", "verify-only", "bad-digest", "changed-mid-read", "grown-mid-read"])
def test_reviewed_decoder_artifact_buffer_preserves_complete_authentication(tmp_path, monkeypatch, mode):
    import os
    raw = bytes(range(256)) * 19
    path = tmp_path / "whole.bin"
    reference = worker.CheckpointArtifact.from_dict(_complete_reviewed_artifact(path, raw))
    if mode == "bad-digest":
        reference = worker.CheckpointArtifact(path=reference.path, bytes=reference.bytes, sha256="0"*64)
    identity = path.stat()
    original_read = os.read
    reads = []
    mutated = []
    def bounded_read(fd, maximum):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (identity.st_dev, identity.st_ino):
            return original_read(fd, maximum)
        part = original_read(fd, min(maximum, 113))
        reads.append(len(part))
        if part and not mutated and mode in ("changed-mid-read", "grown-mid-read"):
            changed = raw[:300] + bytes([raw[300] ^ 1]) + raw[301:] if mode == "changed-mid-read" else raw + b"growth"
            path.write_bytes(changed)
            mutated.append(True)
        return part
    monkeypatch.setattr(os, "read", bounded_read)
    if mode in ("bad-digest", "changed-mid-read", "grown-mid-read"):
        with pytest.raises(worker.TrainingJobValidationError):
            worker._reviewed_decoder_artifact(reference)
    else:
        result = worker._reviewed_decoder_artifact(reference, load=mode != "verify-only")
        assert result == (None if mode == "verify-only" else raw)
        assert sum(reads) == len(raw) and reads[-1] == 0 and len(reads) > 2



@pytest.mark.parametrize("architecture,runtime_profile", [("encoder_decoder", None),
    ("causal_lm", None), ("causal_lm", "builtin-llama-bfloat16/v1")])
@pytest.mark.parametrize("outcome", ["loaded", "denied"])
def test_reviewed_local_loader_retires_parsed_tokenizer_before_numerical_loading(
        tmp_path, monkeypatch, architecture, runtime_profile, outcome):
    import weakref
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, architecture, local_model_profile=runtime_profile)
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    tokenizer_raw = Path(fixture.options["tokenizer_artifact"].path).read_bytes()
    original_parse = worker._parse_json
    observations = []
    class ObservedDict(dict):
        pass
    def parse(raw):
        value = original_parse(raw)
        if raw == tokenizer_raw:
            value = ObservedDict(value)
            observations.append(weakref.ref(value))
        return value
    monkeypatch.setattr(worker, "_parse_json", parse)
    original_guard = fixture.options["execution_guard"]
    checked = []
    denial = PermissionError("original guard denial after retired tokenizer parsing data")
    def guard():
        original_guard()
        if observations:
            assert all(value() is None for value in observations), "parsed tokenizer JSON retained past its last use"
            checked.append(True)
            if outcome == "denied":
                raise denial
    options = dict(fixture.options, execution_guard=guard)
    entry_rng = fixture.torch.get_rng_state().clone()
    if outcome == "denied":
        with pytest.raises(PermissionError) as caught:
            worker.load_local_reviewed_decoder_runtime(**options)
        assert caught.value is denial
        assert fixture.torch.equal(fixture.torch.get_rng_state(), entry_rng)
    else:
        runtime, receipt = worker.load_local_reviewed_decoder_runtime(**options)
        assert receipt["checkpoint_restored"] and receipt["matched_pair"]
        assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])
    assert observations and checked and all(value() is None for value in observations)


def test_reviewed_actual_Smollm2_full_rich_chatml_reservation_requires_longer_context(tmp_path):
    """The full unchanged answer budget must fit before any pretrained forward."""
    descriptor = os.environ.get("IPFS_DATASETS_TEST_LONG_CONTEXT_CAPACITY_INPUT")
    if descriptor is None:
        pytest.skip("explicit pinned complete-context capacity DATA descriptor required")
    report = _reviewed_complete_decoder_capacity_preflight(tmp_path, descriptor, "pinned_smollm2",
        framed_output_budget=3500)
    capacity = report["framed_complete_output_capacity"]
    assert capacity["query_denominator"] == 3 and capacity["fitting_queries"] == 0
    assert capacity["required_model_positions_for_whole_population"] > capacity["model_position_limit"] == 8192
    assert all(row["output_budget"] == 3500 and row["framed_input_tokens"] > 4096
        and row["reserved_model_positions"] > 8192 for row in capacity["queries"])
    assert not report["model_weights_loaded"] and not report["model_forward_or_fit_performed"]
    assert not report["targets_shortened"] and not report["runtime_or_token_limits_changed"]


def test_reviewed_pinned_Qwen25_candidate_complete_rich_capacity_without_weights(tmp_path):
    original = os.environ.get("IPFS_DATASETS_TEST_LONG_CONTEXT_CAPACITY_INPUT")
    candidate = os.environ.get("IPFS_DATASETS_TEST_QWEN25_CAPACITY_INPUT")
    if original is None or candidate is None:
        pytest.skip("explicit original-population and pinned candidate metadata descriptors required")
    report = _reviewed_complete_decoder_capacity_preflight(tmp_path, original, "pinned_smollm2",
        framed_output_budget=3500, candidate_metadata_descriptor=candidate)
    result = report["candidate_complete_capacity"]
    assert result["fitting_queries"] == result["heldout_query_denominator"] == 3
    assert result["complete_target_denominator"] == 6
    assert all(row["full_new_token_reservation"] == 3500 and row["complete_reference_with_two_boundaries"] <= 3500
        for row in result["queries"])
    assert all(row["complete_target_with_two_boundaries"] <= 3500 for row in result["training_targets"])
    assert not result["tensors_fit_existing_checkpoint_bound"]
    assert not result["current_Llama_BOS_marker_assumption_matches"]
    assert not result["weights_downloaded"] and not result["forward_or_fit_performed"]
    assert [row["complete_source_wire_sha256"] for row in result["queries"]] == [
        row["complete_source_wire_sha256"] for row in report["framed_complete_output_capacity"]["queries"]]


@pytest.mark.parametrize("damage", ["request_join", "open_owner", "input_digest"])
def test_reviewed_pinned_Qwen25_candidate_capacity_refuses_broken_metadata_chain(tmp_path, damage):
    original = os.environ.get("IPFS_DATASETS_TEST_LONG_CONTEXT_CAPACITY_INPUT")
    candidate = os.environ.get("IPFS_DATASETS_TEST_QWEN25_CAPACITY_INPUT")
    if original is None or candidate is None:
        pytest.skip("explicit original-population and pinned candidate metadata descriptors required")
    descriptor = json.loads(candidate)
    raw = Path(descriptor["path"]).read_bytes()
    assert len(raw) == descriptor["bytes"] and hashlib.sha256(raw).hexdigest() == descriptor["sha256"]
    bundle = json.loads(raw)
    def materialize(name, value):
        path = tmp_path / name; raw = worker._json_bytes(value); path.write_bytes(raw)
        return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    expected = None
    if damage == "input_digest":
        descriptor["sha256"] = "0" * 64
    else:
        closeout = json.loads(Path(bundle["metadata_closeout"]["path"]).read_bytes())
        if damage == "request_join":
            closeout["request_sha256"] = "0" * 64
            expected = "candidate metadata original request join differs"
        else:
            closeout["original_owner_custody"]["storage_released_and_durable"] = False
            expected = "candidate metadata original custody is open"
        bundle["metadata_closeout"] = materialize("changed-closeout.json", closeout)
        descriptor = materialize("changed-candidate-input.json", bundle)
    with pytest.raises(AssertionError, match=expected):
        _reviewed_complete_decoder_capacity_preflight(tmp_path, original, "pinned_smollm2",
            framed_output_budget=3500, candidate_metadata_descriptor=json.dumps(descriptor))


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-qwen2-dynamic-kv/v1"])
def test_reviewed_local_loader_Qwen2_bfloat16_padded_pair_and_native_generation(tmp_path, monkeypatch, generation_profile):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", local_model_profile="builtin-qwen2-bfloat16/v1")
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    runtime, receipt = worker.load_local_reviewed_decoder_runtime(**fixture.options)
    assert receipt["runtime_profile"] == "builtin-qwen2-bfloat16/v1" and receipt["dtype"] == "bfloat16"
    assert receipt["checkpoint_restored"] and receipt["matched_pair"] and receipt["optimizer_steps"] == 1
    assert receipt["supported_profile"]["max_model_bytes"] == 2*1024**3
    assert runtime.backend.model.config.vocab_size == runtime.tokenizer.vocab_size+8
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"], fixture.checkpoint["optimizer_state"])
    assert all(p.dtype == fixture.torch.bfloat16 for p in runtime.backend.model.parameters())
    assert all(p.dtype == fixture.torch.float32 for _,p in runtime.backend.model.named_buffers())
    observed = []
    hook = runtime.backend.model.register_forward_hook(lambda model, args, kwargs, output: observed.append({
        "input_ids": kwargs["input_ids"].tolist(), "logits_shape": list(output.logits.shape),
        "labels_present": "labels" in kwargs}), with_kwargs=True)
    try:
        record = _reviewed_local_loader_source_record(runtime.tokenizer)
        outputs = runtime.backend.generate_batch([record], max_output_tokens=3,
            execution_guard=runtime.execution_guard, generation_profile=generation_profile)
    finally:
        hook.remove()
    assert len(observed) == 1 and observed[0]["logits_shape"] == [1,1,runtime.backend.model.config.vocab_size]
    assert not observed[0]["labels_present"] and observed[0]["input_ids"] == [record["source_token_ids"]+[257]]
    assert outputs[0]["outcome"] == "abstained" and outputs[0]["generated_token_ids"] == [257,0]
    assert runtime.backend.restored_checkpoint_matches(fixture.checkpoint["model_state"],fixture.checkpoint["optimizer_state"])
    assert fixture.torch.equal(fixture.torch.get_rng_state(),fixture.pair_rng)
    (tmp_path/"qwen2-runtime.json").write_text(json.dumps(dict(receipt=receipt, observed=observed, outputs=outputs,
        actual_pretrained_weights=False, legal_quality_verified=False),indent=2)+"\n")


@pytest.mark.parametrize("fault", ["padded_argmax", "rotary", "original_guard"])
def test_reviewed_local_loader_Qwen2_generation_failure_restores_exact_state(tmp_path, monkeypatch, fault):
    fixture = _reviewed_local_loader_hf_fixture(tmp_path, "causal_lm", local_model_profile="builtin-qwen2-bfloat16/v1")
    _reviewed_local_loader_no_remote_or_training(monkeypatch, fixture)
    runtime, _ = worker.load_local_reviewed_decoder_runtime(**fixture.options)
    torch = fixture.torch; model = runtime.backend.model
    if fault == "padded_argmax":
        with torch.no_grad():
            model.model.embed_tokens.weight[:,0]=1
            model.model.norm.weight.fill_(1)
            model.lm_head.weight[runtime.tokenizer.vocab_size,0]=2
    before = runtime.backend.snapshot_checkpoint(); seen=[]
    buffers={name:value.detach().clone() for name,value in model.named_buffers()}
    def observed(model,args,kwargs,output):
        seen.append(int(output.logits[0,-1].argmax()))
        if fault == "rotary":
            with torch.no_grad():model.model.rotary_emb.inv_freq.add_(.125)
    hook=model.register_forward_hook(observed,with_kwargs=True)
    denied=PermissionError("original Qwen2 guard denied after native forward")
    def guard():
        if seen and fault=="original_guard":raise denied
        runtime.execution_guard()
    try:
        with pytest.raises(PermissionError if fault=="original_guard" else worker.TrainingJobValidationError) as caught:
            runtime.backend.generate_batch([_reviewed_local_loader_source_record(runtime.tokenizer)],
                max_output_tokens=3, execution_guard=guard, generation_profile="builtin-qwen2-dynamic-kv/v1")
        if fault=="original_guard":assert caught.value is denied
        if fault=="padded_argmax":
            assert "outside tokenizer token domain" in str(caught.value)
            assert seen==[runtime.tokenizer.vocab_size]
        if fault=="rotary":assert "rotary" in str(caught.value)
    finally:hook.remove()
    assert seen and runtime.backend.restored_checkpoint_matches(before["model_state"],before["optimizer_state"])
    assert all(torch.equal(value,buffers[name])for name,value in model.named_buffers())
    assert torch.equal(torch.get_rng_state(),fixture.pair_rng)


@pytest.mark.parametrize("damage", ["sliding_window", "dynamic_rope", "parameter_dtype", "vocabulary", "byte_bound"])
def test_reviewed_local_loader_Qwen2_bad_profile_refuses_before_allocation(tmp_path,monkeypatch,damage):
    fixture=_reviewed_local_loader_hf_fixture(tmp_path,"causal_lm",local_model_profile="builtin-qwen2-bfloat16/v1")
    options=dict(fixture.options)
    config=json.loads(Path(options["model_config_artifact"].path).read_bytes())
    if damage=="sliding_window":config["use_sliding_window"]=True;config["layer_types"]=["sliding_attention"]
    elif damage=="dynamic_rope":config["rope_parameters"]={"rope_type":"linear","rope_theta":10000.0,"factor":2.0}
    elif damage=="parameter_dtype":config["dtype"]="float32"
    elif damage=="vocabulary":config["vocab_size"]=fixture.backend.tokenizer.vocab_size-1
    else:options["max_model_bytes"]=1
    if damage!="byte_bound":options["model_config_artifact"]=fixture.artifact("changed-config.json",worker._json_bytes(config))
    entry=fixture.torch.get_rng_state().clone()
    monkeypatch.setattr(fixture.model_class,"__init__",lambda *a,**k:pytest.fail("bad Qwen2 profile reached model constructor"))
    monkeypatch.setattr(fixture.torch.nn.Module,"to_empty",lambda *a,**k:pytest.fail("bad Qwen2 profile allocated tensors"))
    with pytest.raises(worker.TrainingJobValidationError):worker.load_local_reviewed_decoder_runtime(**options)
    assert fixture.torch.equal(fixture.torch.get_rng_state(),entry)


def test_reviewed_local_loader_Qwen2_original_policy_denies_before_vendor_import(monkeypatch,tmp_path):
    import builtins
    options=_reviewed_local_loader_denial_inputs(tmp_path);denied=PermissionError("original Qwen2 asset denial")
    def policy(value):
        assert value["runtime_profile"]=="builtin-qwen2-bfloat16/v1" and value["dtype"]=="bfloat16"
        raise denied
    original=builtins.__import__
    def guarded(name,*a,**k):
        if name.split(".",1)[0]in{"torch","transformers","tokenizers"}:pytest.fail("Qwen2 vendor import before policy")
        return original(name,*a,**k)
    monkeypatch.setattr(builtins,"__import__",guarded)
    with pytest.raises(PermissionError)as caught:
        worker.load_local_reviewed_decoder_runtime(**options,runtime_profile="builtin-qwen2-bfloat16/v1",
            current_admission_provider=lambda:pytest.fail("admission after denial"),execution_guard=lambda:None,asset_policy_guard=policy)
    assert caught.value is denied


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-qwen2-dynamic-kv/v1"])
def test_reviewed_generation_Qwen2_chatml_matches_native_frame_and_greedy_body(generation_profile):
    fixture=_reviewed_chatml_llama_fixture(model_profile="builtin-qwen2-bfloat16/v1")
    backend,torch=fixture.backend,fixture.torch;rows=[]
    for index in range(2):
        row=_reviewed_local_loader_source_record(backend.tokenizer);source=json.loads(row["source_wire"])
        source["source_text"]="A fixture clerk must file a café record. "+str(index)
        row.update(id="fixture:qwen2:"+str(index),unit_id="fixture:qwen2-unit:"+str(index),source_wire=worker._json_bytes(source).decode())
        row["source_token_ids"]=[0,*backend.tokenizer.encode(row["source_wire"]),2];rows.append(row)
    # The explicit system/user ChatML path is shared by the two pinned vendor
    # templates. Its native oracle never uses a generated/reference answer.
    frames=[_reviewed_chatml_native_test_frame(fixture.frontend,row["source_wire"])for row in rows]
    assert all(frame.count(1)==3 and frame.count(2)==2 and 0 not in frame for frame in frames)
    modes=[(x,x.training)for x in backend.model.modules()];backend.model.eval();expected=[]
    with torch.no_grad():
        for frame in frames:
            body=[]
            for _ in range(4):
                ids=torch.tensor([frame+body],dtype=torch.long)
                logits=backend.model(input_ids=ids,attention_mask=torch.ones_like(ids),logits_to_keep=1,use_cache=False).logits
                body.append(int(logits[0,-1].argmax()))
            expected.append([0,*body])
    for module,training in modes:module.training=training
    assert all(all(3<=x<260 for x in row[1:])for row in expected)
    before=backend.snapshot_checkpoint();observed=[]
    def observe(model,args,kwargs):
        cache=kwargs.get("past_key_values")
        observed.append(dict(ids=kwargs["input_ids"].tolist(),mask=kwargs["attention_mask"].tolist(),
            positions=None if "position_ids"not in kwargs else kwargs["position_ids"].tolist(),
            prior=None if cache is None else cache.get_seq_length(),keep=kwargs.get("logits_to_keep")))
    hook=backend.model.register_forward_pre_hook(observe,with_kwargs=True)
    try:result=backend.generate_batch(rows,max_output_tokens=5,execution_guard=lambda:None,
        generation_profile=generation_profile,conditioning_profile="qwen2-chatml-complete-legal-ir/v1")
    finally:hook.remove()
    assert [x["generated_token_ids"]for x in result]==expected
    assert all(x["outcome"]=="incomplete"and x["reason"]=="output_limit_without_eos"for x in result)
    assert len(observed)==8
    for r,frame in enumerate(frames):
        for step in range(4):
            call=observed[4*r+step];prefix=frame+expected[r][1:1+step]
            assert call["ids"]==([prefix]if generation_profile=="full-prefix/v1"or step==0 else [[expected[r][step]]])
            assert call["mask"]==[[1]*len(prefix)]and call["keep"]==1
            if generation_profile!="full-prefix/v1":assert call["prior"]==(0 if step==0 else len(prefix)-1)
    assert before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-qwen2-dynamic-kv/v1"])
def test_reviewed_generation_Qwen2_chatml_full_batch_capacity_before_forward(generation_profile):
    fixture=_reviewed_chatml_llama_fixture(model_profile="builtin-qwen2-bfloat16/v1");backend=fixture.backend
    first=_reviewed_local_loader_source_record(backend.tokenizer);second=json.loads(json.dumps(first))
    second.update(id="fixture:large",unit_id="fixture:large-unit");source=json.loads(second["source_wire"])
    source["source_text"]+="z"*(backend.max_sequence_tokens-len(second["source_token_ids"])-8)
    second["source_wire"]=worker._json_bytes(source).decode();second["source_token_ids"]=[0,*backend.tokenizer.encode(second["source_wire"]),2]
    assert len(second["source_token_ids"])+5<=backend.max_sequence_tokens
    assert len(_reviewed_chatml_native_test_frame(fixture.frontend,second["source_wire"]))+4>backend.max_sequence_tokens
    before=backend.snapshot_checkpoint();hook=backend.model.register_forward_pre_hook(lambda *a,**k:pytest.fail("oversized Qwen2 frame reached forward"))
    try:
        with pytest.raises(worker.TrainingJobValidationError,match="full generation budget exceeds actual decoder context"):
            backend.generate_batch([first,second],max_output_tokens=5,execution_guard=lambda:None,
                generation_profile=generation_profile,conditioning_profile="qwen2-chatml-complete-legal-ir/v1")
    finally:hook.remove()
    assert before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-qwen2-dynamic-kv/v1"])
def test_reviewed_generation_Qwen2_chatml_preserves_original_denial(generation_profile):
    fixture=_reviewed_chatml_llama_fixture(model_profile="builtin-qwen2-bfloat16/v1");backend=fixture.backend
    before=backend.snapshot_checkpoint();ran=[];denied=PermissionError("original Qwen2 framed denial")
    hook=backend.model.register_forward_pre_hook(lambda *a,**k:ran.append(True))
    def guard():
        if ran:raise denied
    try:
        with pytest.raises(PermissionError)as caught:
            backend.generate_batch([_reviewed_local_loader_source_record(backend.tokenizer)],max_output_tokens=4,
                execution_guard=guard,generation_profile=generation_profile,conditioning_profile="qwen2-chatml-complete-legal-ir/v1")
        assert caught.value is denied
    finally:hook.remove()
    assert ran==[True]and before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("damage", ["bos_in_source","start_in_source","end_in_source","target_fields","marker_mapping","foreign_model"])
def test_reviewed_generation_Qwen2_chatml_bad_boundaries_refuse_before_forward(damage):
    fixture=_reviewed_chatml_llama_fixture(model_profile="builtin-llama-bfloat16/v1"if damage=="foreign_model"else"builtin-qwen2-bfloat16/v1")
    backend=fixture.backend
    if damage=="marker_mapping":
        from tokenizers import Tokenizer
        from transformers import PreTrainedTokenizerFast
        native=Tokenizer.from_str(fixture.frontend.backend_tokenizer.to_str().replace("<|im_start|>","<|fixture_start|>"))
        frontend=PreTrainedTokenizerFast(tokenizer_object=native,bos_token="<|endoftext|>",eos_token="<|im_end|>",
            unk_token=None,pad_token="<|endoftext|>",model_max_length=2048,clean_up_tokenization_spaces=False)
        backend.tokenizer=worker.ReviewedPretrainedTokenizer(frontend,bos_token_id=0,eos_token_id=2,vocab_size=260)
    row=_reviewed_local_loader_source_record(backend.tokenizer)
    if damage.endswith("_in_source"):
        source=json.loads(row["source_wire"]);source["source_text"]+={"bos_in_source":"<|endoftext|>","start_in_source":"<|im_start|>","end_in_source":"<|im_end|>"}[damage]
        row["source_wire"]=worker._json_bytes(source).decode();row["source_token_ids"]=[0,*backend.tokenizer.encode(row["source_wire"]),2]
    elif damage=="target_fields":row["target_json"]="{}"
    message=("complete generation source transport differs"if damage in("bos_in_source","end_in_source")else
        "closed source-only generation record"if damage=="target_fields"else"Qwen2 ChatML")
    before=backend.snapshot_checkpoint();hook=backend.model.register_forward_pre_hook(lambda *a,**k:pytest.fail("bad Qwen2 boundary reached forward"))
    try:
        with pytest.raises(worker.TrainingJobValidationError,match=message):backend.generate_batch([row],max_output_tokens=4,
            execution_guard=lambda:None,conditioning_profile="qwen2-chatml-complete-legal-ir/v1")
    finally:hook.remove()
    assert before==backend.snapshot_checkpoint()


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-qwen2-dynamic-kv/v1"])
def test_reviewed_local_loader_Qwen2_native_chatml_unknown_none_and_eos(tmp_path,generation_profile):
    from types import SimpleNamespace
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    fixture=_reviewed_chatml_local_asset_fixture(tmp_path,local_model_profile="builtin-qwen2-bfloat16/v1")
    def forbidden(*a,**k):pytest.fail("inference loader accessed target/training registry")
    options=dict(fixture.options,registry=SimpleNamespace(read_artifact=forbidden,artifact_path=forbidden),
        current_admission_provider=lambda:{},execution_guard=lambda:None,asset_policy_guard=lambda policy:None,
        expected_source_sha256=worker._reviewed_decoder_source_pins(),
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256({}),
        max_model_bytes=64*1024**2,runtime_profile="builtin-qwen2-bfloat16/v1")
    runtime,receipt=worker.load_local_reviewed_decoder_runtime(**options)
    assert runtime.tokenizer.bos_token_id==0 and runtime.tokenizer.eos_token_id==2
    assert runtime.tokenizer.tokenizer.unk_token is None
    assert runtime.tokenizer.tokenizer.backend_tokenizer.token_to_id("<|im_start|>")==1
    before=runtime.backend.snapshot_checkpoint()
    result=runtime.backend.generate_batch([_reviewed_local_loader_source_record(runtime.tokenizer)],max_output_tokens=4,
        execution_guard=runtime.execution_guard,generation_profile=generation_profile,
        conditioning_profile="qwen2-chatml-complete-legal-ir/v1")
    assert result[0]["outcome"]=="abstained"and result[0]["generated_token_ids"]==[0,2]
    assert before==runtime.backend.snapshot_checkpoint()and receipt["matched_pair"]
    (tmp_path/"qwen2-chatml-loader.json").write_text(json.dumps(dict(receipt=receipt,outputs=result,
        tiny_native_fixture_only=True,pretrained_quality=False),indent=2)+"\n")


def _reviewed_Qwen2_generation_policy():
    return dict(schema="reviewed-decoder-generation-policy/v2",generation_profile="builtin-qwen2-dynamic-kv/v1",
        conditioning_profile="qwen2-chatml-complete-legal-ir/v1",max_generation_seconds=1.0,
        context_budget_profile="qwen2-full-context-8192/v1")


@pytest.mark.parametrize("damage",[None,"schema","cache","conditioning","context","missing_context","extra","bool","overflow"])
def test_reviewed_Qwen2_generation_policy_is_closed_data(monkeypatch,damage):
    import builtins
    value=_reviewed_Qwen2_generation_policy()
    if damage=="schema":value["schema"]="reviewed-decoder-generation-policy/v1"
    elif damage=="cache":value["generation_profile"]="builtin-llama-dynamic-kv/v1"
    elif damage=="conditioning":value["conditioning_profile"]="chatml-complete-legal-ir/v1"
    elif damage=="context":value["context_budget_profile"]="unknown"
    elif damage=="missing_context":value.pop("context_budget_profile")
    elif damage=="extra":value["target_json"]="forbidden"
    elif damage=="bool":value["max_generation_seconds"]=False
    elif damage=="overflow":value["max_generation_seconds"]=10**1000
    original=builtins.__import__
    def no_native(name,*a,**k):
        if name.split(".",1)[0]in("torch","transformers","tokenizers"):pytest.fail("generation DATA imported native code")
        return original(name,*a,**k)
    monkeypatch.setattr(builtins,"__import__",no_native)
    if damage is None:
        loaded=worker._reviewed_decoder_generation_policy(value);assert loaded==value and loaded is not value
    else:
        with pytest.raises(worker.TrainingJobValidationError,match="generation policy"):worker._reviewed_decoder_generation_policy(value)


@pytest.mark.parametrize("mode",["healthy","denied","mutated"])
def test_reviewed_Qwen2_source_factory_binds_runtime_and_context_budget(tmp_path,monkeypatch,mode, *, conditioning_profile="qwen2-chatml-complete-legal-ir/v1"):
    fixture=_reviewed_profiled_source_fixture(tmp_path,model_profile="builtin-qwen2-bfloat16/v1")
    policy=_reviewed_Qwen2_generation_policy();policy["conditioning_profile"]=conditioning_profile;backend=fixture.backend;denied=PermissionError("original Qwen2 reviewed policy denied")
    if mode!="healthy":
        ran=[]
        def guard(offered):
            ran.append(True)
            assert offered["schema"]=="reviewed-decoder-source-producer-policy/v4"
            assert offered["runtime_profile"]=="builtin-qwen2-bfloat16/v1"and offered["generation_policy"]==policy
            if mode=="denied":raise denied
            policy["max_generation_seconds"]=2.0
        runtime=worker.ReviewedDecoderRuntime(fixture.runtime.registry,backend,backend.tokenizer,fixture.base.fresh,lambda:None,guard)
        with pytest.raises(PermissionError if mode=="denied"else worker.TrainingJobValidationError)as caught:
            worker.make_reviewed_decoder_source_producer_v3(runtime,**fixture.options,generation_policy=policy)
        assert ran==[True]
        if mode=="denied":assert caught.value is denied
        assert backend.restored_checkpoint_matches(fixture.checkpoint["model_state"],fixture.checkpoint["optimizer_state"])
        return
    producer=worker.make_reviewed_decoder_source_producer_v3(fixture.runtime,**fixture.options,generation_policy=policy)
    if conditioning_profile != "qwen2-chatml-complete-legal-ir/v1":
        legacy = worker.make_reviewed_decoder_source_producer_v3(fixture.runtime, **fixture.options,
            generation_policy={**policy, "conditioning_profile": "qwen2-chatml-complete-legal-ir/v1"})
        assert producer.input_profile_id != legacy.input_profile_id
    other={**policy,"max_generation_seconds":2.0}
    second=worker.make_reviewed_decoder_source_producer_v3(fixture.runtime,**fixture.options,generation_policy=other)
    assert producer.input_profile_id!=second.input_profile_id
    calls=[];original=backend.generate_batch
    def observe(records,**options):
        assert all(set(row)=={"id","unit_id","source_wire","source_token_ids"}for row in records)
        calls.append({k:options[k]for k in("generation_profile","conditioning_profile","max_generation_seconds","context_budget_profile")})
        return original(records,**options)
    monkeypatch.setattr(backend,"generate_batch",observe)
    declarations=fixture.base.declarations();declarations["decoder"]={"id":fixture.options["backend_identity"]["backend_id"],"sha256":fixture.options["model_checkpoint"].sha256}
    forwards=[]
    def native_forward(model,args,kwargs):
        assert "labels" not in kwargs
        forwards.append(dict(input_tokens=kwargs["input_ids"].shape[1],labels_present=False))
    hook=backend.model.register_forward_pre_hook(native_forward,with_kwargs=True)
    try:
        artifact=producer.evaluate(compiler_commit="fixture:Qwen2-reviewed",checkpoint_declarations=declarations)
    finally:hook.remove()
    observed=producer.observation()
    outputs=observed["last_call"]["raw_generation_outputs"]
    assert len(outputs)==len(fixture.options["rows"]) and all(len(x["generated_token_ids"])>=2 for x in outputs)
    assert len(forwards)==sum(len(x["generated_token_ids"])-1 for x in outputs)
    (tmp_path/"Qwen2-reviewed-source-forward-witness.json").write_text(json.dumps(dict(
        schema="observed-native-Qwen2-reviewed-source-forwards/v1",forward_count=len(forwards),row_count=len(outputs),
        forwards=forwards,outputs=outputs,source_records_sha256=observed["last_call"]["source_records_sha256"],
        entry_pair_match=observed["last_call"]["entry_pair_match"],exit_pair_match=observed["last_call"]["exit_pair_match"],
        actual_pretrained_or_legal_quality=False),indent=2)+"\n")
    assert observed["schema"]=="reviewed-decoder-source-producer-observation/v4"
    assert observed["input_commitment"]["runtime_profile"]=="builtin-qwen2-bfloat16/v1"
    assert observed["input_commitment"]["generation_policy"]==policy
    assert observed["input_profile_id"]==producer.input_profile_id
    assert producer.input_profile_id.startswith("reviewed-decoder-qwen2-profiled-producer/v1:")
    assert calls==[{k:policy[k]for k in("generation_profile","conditioning_profile","max_generation_seconds","context_budget_profile")}]
    assert observed["last_call"]["entry_pair_match"]and observed["last_call"]["exit_pair_match"]
    assert artifact.metrics["complete_norm_payload"]["denominator"]==len(fixture.options["rows"])


@pytest.mark.parametrize("profile",[False,8192,{},"unknown"])
def test_reviewed_Qwen2_native_context_budget_profile_rejects_before_import(monkeypatch,profile):
    import builtins
    original=builtins.__import__
    def no_native(name,*a,**k):
        if name.split(".",1)[0]in("torch","transformers","tokenizers"):pytest.fail("invalid context budget imported native code")
        return original(name,*a,**k)
    monkeypatch.setattr(builtins,"__import__",no_native)
    backend=object.__new__(worker.TorchReviewedDecoderBackend)
    with pytest.raises(worker.TrainingJobValidationError,match="context budget profile"):
        backend.generate_batch([],max_output_tokens=4,execution_guard=lambda:pytest.fail("invalid context budget called guard"),
            conditioning_profile="qwen2-chatml-complete-legal-ir/v1",context_budget_profile=profile)


def test_reviewed_Qwen2_native_context_budget_preserves_original_early_denial(monkeypatch):
    import builtins
    denied=PermissionError("original context profile guard denial");original=builtins.__import__
    def no_native(name,*a,**k):
        if name.split(".",1)[0]in("torch","transformers","tokenizers"):pytest.fail("native import before original denial")
        return original(name,*a,**k)
    monkeypatch.setattr(builtins,"__import__",no_native)
    backend=object.__new__(worker.TorchReviewedDecoderBackend)
    def guard():raise denied
    with pytest.raises(PermissionError)as caught:backend.generate_batch([],max_output_tokens=4,execution_guard=guard,
        conditioning_profile="qwen2-chatml-complete-legal-ir/v1",context_budget_profile="qwen2-full-context-8192/v1")
    assert caught.value is denied


@pytest.mark.parametrize("mode",["accepted","context_too_large","source_too_small"])
def test_reviewed_Qwen2_complete_context_budget_is_explicit_and_lossless(mode):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    fixture=_reviewed_chatml_llama_fixture(model_profile="builtin-qwen2-bfloat16/v1");tokenizer=fixture.backend.tokenizer
    row=_reviewed_local_loader_source_record(tokenizer);source=json.loads(row["source_wire"])
    text="z"*(8500 if mode=="context_too_large"else 5000)
    context={"permitted":[],"retrieved":[{"id":"fixture:complete-data-text","content":{"fictional_complete_text":text}}]}
    arguments=[dict(id=row["id"],source_text=source["source_text"],context=context)]
    contexts=dict(profile="reviewed-source-selection-context/v2",selection_context=source["selection_context"],
        rows=[dict(id=row["id"],unit_id=row["unit_id"],governing_context=source["governing_context"],source_binding=source["source_binding"])])
    digest=lambda x:hashlib.sha256(inputs._reviewed_wire(x)).hexdigest()
    options=dict(source_contexts=contexts,expected_source_contexts_sha256=digest(contexts),
        expected_context_records_sha256=digest([dict(id=row["id"],context=context)]),tokenizer=tokenizer,
        max_source_tokens=4096 if mode=="source_too_small"else 12288,context_transport="shared_json_v2")
    with pytest.raises(inputs.ReviewedDecoderInputValidationError,match="token"):
        inputs.prepare_reviewed_decoder_context_generation_inputs(arguments,**options)
    options["context_budget_profile"]="qwen2-full-context-8192/v1"
    if mode!="accepted":
        with pytest.raises(inputs.ReviewedDecoderInputValidationError,match="token"):
            inputs.prepare_reviewed_decoder_context_generation_inputs(arguments,**options)
        return
    prepared=inputs.prepare_reviewed_decoder_context_generation_inputs(arguments,**options);receipt=prepared["receipt"]
    assert receipt["schema"]=="reviewed-decoder-context-generation-input-receipt/v2"
    assert receipt["max_context_tokens"]==8192 and receipt["context_budget_profile"]==options["context_budget_profile"]
    assert 4096<receipt["row_commitments"][0]["context_tokens_including_bos_eos"]<=8192
    decoded=json.loads(prepared["records"][0]["source_wire"])
    assert inputs.unpack_reviewed_context_json_v2(decoded["context"])==context
    assert not receipt["target_access_performed"]and not receipt["context_use_permission_verified"]and not receipt["backend_execution_authorized"]


@pytest.mark.parametrize("profile",[False,8192,{},"unknown"])
def test_reviewed_Qwen2_input_context_budget_is_closed_data(profile):
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    with pytest.raises(inputs.ReviewedDecoderInputValidationError,match="context budget profile"):
        inputs.prepare_reviewed_decoder_context_generation_inputs([],source_contexts={},expected_source_contexts_sha256="0"*64,
            expected_context_records_sha256="0"*64,tokenizer=None,max_source_tokens=8192,context_budget_profile=profile)


@pytest.mark.parametrize("damage", [None, "llama", "target", "unknown"])
def test_reviewed_Qwen2_public_layout_policy_is_closed_data(monkeypatch, damage):
    import builtins
    value = _reviewed_Qwen2_generation_policy()
    value["conditioning_profile"] = "qwen2-chatml-field-layouts/v1"
    if damage == "llama":
        value = {k: v for k, v in value.items() if k != "context_budget_profile"}
        value.update(schema="reviewed-decoder-generation-policy/v1", generation_profile="builtin-llama-dynamic-kv/v1")
    elif damage == "target": value["public_schema"] = {"query_target": "forbidden"}
    elif damage == "unknown": value["conditioning_profile"] = "qwen2-chatml-field-layouts/v2"
    original = builtins.__import__
    def no_native(name, *args, **kwargs):
        if name.split(".", 1)[0] in ("torch", "transformers", "tokenizers"):
            pytest.fail("closed layout policy imported a native runtime")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_native)
    if damage is None:
        assert worker._reviewed_decoder_generation_policy(value) == value
    else:
        with pytest.raises(worker.TrainingJobValidationError, match="generation policy"):
            worker._reviewed_decoder_generation_policy(value)


@pytest.mark.parametrize("generation_profile", ["full-prefix/v1", "builtin-qwen2-dynamic-kv/v1"])
def test_reviewed_generation_Qwen2_public_layouts_exact_native_frame(monkeypatch, generation_profile):
    fixture = _reviewed_chatml_llama_fixture(model_profile="builtin-qwen2-bfloat16/v1", context_tokens=4096)
    torch, backend = fixture.torch, fixture.backend
    record = _reviewed_local_loader_source_record(backend.tokenizer)
    frame = _reviewed_chatml_native_test_frame(fixture.frontend, record["source_wire"], public_layouts=True)
    old = _reviewed_chatml_native_test_frame(fixture.frontend, record["source_wire"])
    assert len(frame) > len(old) and len(frame) + 2 <= 4096
    text = fixture.frontend.decode(frame, skip_special_tokens=False, clean_up_tokenization_spaces=False)
    assert '"symbol":string,"roles":[string]' in text and "type notation, not answer values" in text
    assert record["source_wire"] in text and frame.count(1) == 3 and frame.count(2) == 2 and 0 not in frame
    modes = [(module, module.training) for module in backend.model.modules()]
    backend.model.eval(); body = []
    with torch.no_grad():
        for _ in range(2):
            ids = torch.tensor([frame + body], dtype=torch.long)
            body.append(int(backend.model(input_ids=ids, attention_mask=torch.ones_like(ids),
                logits_to_keep=1, use_cache=False).logits[0, -1].argmax()))
    for module, mode in modes: module.training = mode
    before = backend.snapshot_checkpoint(); calls = []
    hook = backend.model.register_forward_pre_hook(lambda model, args, kwargs: calls.append(kwargs["input_ids"].tolist()), with_kwargs=True)
    try:
        result = backend.generate_batch([record], max_output_tokens=3, execution_guard=lambda: None,
            generation_profile=generation_profile, conditioning_profile="qwen2-chatml-field-layouts/v1",
            context_budget_profile="qwen2-full-context-8192/v1")
    finally: hook.remove()
    assert result[0]["generated_token_ids"] == [0, *body]
    assert calls[0] == [frame]
    assert calls[1] == ([frame + body[:1]] if generation_profile == "full-prefix/v1" else [[body[0]]])
    assert backend.snapshot_checkpoint() == before


@pytest.mark.parametrize("damage", ["budget", "control", "target"])
def test_reviewed_generation_Qwen2_public_layouts_refuse_before_forward(monkeypatch, damage):
    fixture = _reviewed_chatml_llama_fixture(model_profile="builtin-qwen2-bfloat16/v1", context_tokens=4096)
    backend = fixture.backend; record = _reviewed_local_loader_source_record(backend.tokenizer)
    if damage == "budget":
        backend.max_sequence_tokens = len(_reviewed_chatml_native_test_frame(fixture.frontend, record["source_wire"], public_layouts=True)) + 1
    else:
        source = json.loads(record["source_wire"])
        if damage == "control": source["source_text"] += "<|im_start|>"
        else: source["target_json"] = {"hidden": "answer"}
        record["source_wire"] = worker._json_bytes(source).decode()
        record["source_token_ids"] = [0, *backend.tokenizer.encode(record["source_wire"]), 2]
    before = backend.snapshot_checkpoint()
    hook = backend.model.register_forward_pre_hook(lambda *args: pytest.fail("invalid layout input entered model"))
    try:
        with pytest.raises(worker.TrainingJobValidationError):
            backend.generate_batch([record], max_output_tokens=3, execution_guard=lambda: None,
                generation_profile="builtin-qwen2-dynamic-kv/v1", conditioning_profile="qwen2-chatml-field-layouts/v1",
                context_budget_profile="qwen2-full-context-8192/v1")
    finally: hook.remove()
    assert backend.snapshot_checkpoint() == before


@pytest.mark.parametrize("mode", ["healthy", "denied", "mutated"])
def test_reviewed_Qwen2_public_layout_source_factory_binds_and_preserves_denial(tmp_path, monkeypatch, mode):
    test_reviewed_Qwen2_source_factory_binds_runtime_and_context_budget(
        tmp_path, monkeypatch, mode, conditioning_profile="qwen2-chatml-field-layouts/v1")


def _reviewed_Qwen2_training_conditioning_fixture(profile=None):
    fixture=_reviewed_chatml_llama_fixture(model_profile="builtin-qwen2-bfloat16/v1",context_tokens=8192)
    _,_,rows=_torch_reviewed_backend_fixture("causal_lm")
    for row in rows:
        row["source_token_ids"]=[0,*fixture.backend.tokenizer.encode(row["source_wire"]),2]
        row["target_token_ids"]=[0,*fixture.backend.tokenizer.encode(row["target_json"]),2]
    if profile is not None:
        old=fixture.backend
        fixture.backend=worker.TorchReviewedDecoderBackend(old.model,old.optimizer,old.tokenizer,
            architecture=old.architecture,max_sequence_tokens=old.max_sequence_tokens,pretrained=old.pretrained,
            model_profile=old.model_profile,training_conditioning_profile=profile)
    return fixture,rows


def test_reviewed_Qwen2_training_default_retains_raw_prompt_before_chatml_opt_in():
    fixture,rows=_reviewed_Qwen2_training_conditioning_fixture();backend=fixture.backend;seen=[]
    def capture(model,args,kwargs):
        seen.append({key:kwargs[key].detach().clone()for key in ("input_ids","labels")})
    hook=backend.model.register_forward_pre_hook(capture,with_kwargs=True)
    try:result=backend.train_batch(rows)
    finally:hook.remove()
    source,target=rows[0]["source_token_ids"],rows[0]["target_token_ids"]
    assert seen[0]["input_ids"].tolist()==[source+target]
    assert seen[0]["labels"].tolist()==[[-100]*(len(source)+1)+target[1:]]
    frame=_reviewed_chatml_native_test_frame(fixture.frontend,rows[0]["source_wire"],public_layouts=True)
    assert seen[0]["input_ids"].tolist()[0][:len(frame)]!=frame
    assert "training_conditioning_profile"not in backend._configuration()
    assert result["optimizer_steps"]==1 and result["loss"]>0


@pytest.mark.parametrize("profile",["qwen2-chatml-complete-legal-ir/v1","qwen2-chatml-field-layouts/v1"])
def test_reviewed_Qwen2_training_selected_chatml_matches_native_frame_and_labels(profile):
    fixture,rows=_reviewed_Qwen2_training_conditioning_fixture(profile);backend=fixture.backend;seen=[]
    frame=_reviewed_chatml_native_test_frame(fixture.frontend,rows[0]["source_wire"],
        public_layouts=profile=="qwen2-chatml-field-layouts/v1")
    target=rows[0]["target_token_ids"];inputs=frame+target[1:];labels=[-100]*len(frame)+target[1:]
    assert 0 not in frame and frame.count(1)==3 and frame.count(2)==2
    backend.model.eval()
    with fixture.torch.no_grad():
        expected=float(backend.model(input_ids=fixture.torch.tensor([inputs]),
            attention_mask=fixture.torch.ones((1,len(inputs)),dtype=fixture.torch.long),
            labels=fixture.torch.tensor([labels])).loss)
    before={name:value.detach().clone()for name,value in backend.model.state_dict().items()}
    def capture(model,args,kwargs):
        seen.append({key:kwargs[key].detach().clone()for key in ("input_ids","labels","attention_mask")})
    hook=backend.model.register_forward_pre_hook(capture,with_kwargs=True)
    try:result=backend.train_batch(rows)
    finally:hook.remove()
    assert len(seen)==1 and seen[0]["input_ids"].tolist()==[inputs] and seen[0]["labels"].tolist()==[labels]
    assert seen[0]["attention_mask"].tolist()==[[1]*len(inputs)]
    assert result["loss"]==expected and result["optimizer_steps"]==1 and result["gradient_norm"]>0
    assert any(not fixture.torch.equal(value,backend.model.state_dict()[name])for name,value in before.items())
    config=backend._configuration();assert config["training_conditioning_profile"]==profile
    assert config["schema"]=="torch-complete-reviewed-decoder-configuration/v4"


@pytest.mark.parametrize("profile",[False,1,{},"unknown","chatml-complete-legal-ir/v1"])
def test_reviewed_Qwen2_training_invalid_profile_refuses_without_native_import(monkeypatch,profile):
    import builtins
    original=builtins.__import__
    def guarded(name,*a,**k):
        if name.split(".",1)[0]in{"torch","transformers","tokenizers"}:pytest.fail("invalid training profile imported native code")
        return original(name,*a,**k)
    monkeypatch.setattr(builtins,"__import__",guarded)
    with pytest.raises(worker.TrainingJobValidationError,match="training conditioning profile"):
        worker._reviewed_training_conditioning_profile(profile,"causal_lm","builtin-qwen2-bfloat16/v1")


@pytest.mark.parametrize("architecture,model_profile",[("encoder_decoder","builtin-qwen2-bfloat16/v1"),("causal_lm",None)])
def test_reviewed_Qwen2_training_profile_rejects_other_architecture_or_runtime(architecture,model_profile):
    with pytest.raises(worker.TrainingJobValidationError,match="training conditioning profile"):
        worker._reviewed_training_conditioning_profile("qwen2-chatml-field-layouts/v1",architecture,model_profile)


@pytest.mark.parametrize("damage",["budget","late-target","message-marker"])
def test_reviewed_Qwen2_training_preflights_complete_batch_before_mutation(monkeypatch,damage):
    from copy import deepcopy
    fixture,rows=_reviewed_Qwen2_training_conditioning_fixture("qwen2-chatml-field-layouts/v1");backend=fixture.backend
    if damage=="budget":
        frame=_reviewed_chatml_native_test_frame(fixture.frontend,rows[0]["source_wire"],public_layouts=True)
        backend.max_sequence_tokens=len(frame)+len(rows[0]["target_token_ids"])-2
        assert sum(len(rows[0][key])for key in("source_token_ids","target_token_ids"))<backend.max_sequence_tokens
    elif damage=="late-target":
        rows.append(deepcopy(rows[0]));rows[1]["id"]+="-late";rows[1]["target_token_ids"]=rows[1]["target_token_ids"][:-1]
    else:
        source=json.loads(rows[0]["source_wire"]);source["source_text"]+=" <|im_start|>"
        rows[0]["source_wire"]=worker._json_bytes(source).decode();rows[0]["source_token_ids"]=[0,*backend.tokenizer.encode(rows[0]["source_wire"]),2]
    before=backend.snapshot_checkpoint()
    def forbidden(*a,**k):pytest.fail("invalid complete batch reached model mutation or forward")
    monkeypatch.setattr(backend.model,"forward",forbidden);monkeypatch.setattr(backend.model,"train",forbidden)
    monkeypatch.setattr(backend.optimizer,"step",forbidden);monkeypatch.setattr(backend.optimizer,"zero_grad",forbidden)
    with pytest.raises(worker.TrainingJobValidationError):backend.train_batch(rows)
    assert backend._optimizer_steps==0 and backend.optimizer.state_dict()["state"]=={}
    assert backend.restored_checkpoint_matches(before["model_state"],before["optimizer_state"])


def test_reviewed_Qwen2_training_profile_mutation_after_forward_refuses_before_backward():
    fixture,rows=_reviewed_Qwen2_training_conditioning_fixture("qwen2-chatml-field-layouts/v1");backend=fixture.backend;seen=[]
    before={n:v.detach().clone()for n,v in backend.model.state_dict().items()}
    def mutate(model,args,output):
        seen.append(True);backend.training_conditioning_profile="qwen2-chatml-complete-legal-ir/v1"
    hook=backend.model.register_forward_hook(mutate)
    try:
        with pytest.raises(worker.TrainingJobValidationError,match="conditioning profile changed"):backend.train_batch(rows)
    finally:hook.remove()
    assert seen==[True] and backend._optimizer_steps==0 and backend.optimizer.state_dict()["state"]=={}
    assert all(p.grad is None for p in backend.model.parameters())
    assert all(fixture.torch.equal(v,backend.model.state_dict()[n])for n,v in before.items())


def test_reviewed_Qwen2_training_profile_checkpoint_identity_and_exact_resume():
    profile="qwen2-chatml-field-layouts/v1";fixture,rows=_reviewed_Qwen2_training_conditioning_fixture(profile);backend=fixture.backend
    raw,rawrows=_reviewed_Qwen2_training_conditioning_fixture();old=raw.backend.snapshot_checkpoint()
    assert backend.identity()!=raw.backend.identity()
    with pytest.raises(worker.TrainingJobValidationError):backend.inspect_checkpoint(old["model_state"],old["optimizer_state"])
    backend.train_batch(rows);saved=backend.snapshot_checkpoint();assert backend.inspect_checkpoint(saved["model_state"],saved["optimizer_state"])=={"optimizer_steps":1}
    expected=backend.train_batch(rows);whole=backend.snapshot_checkpoint()
    resumed,resumed_rows=_reviewed_Qwen2_training_conditioning_fixture(profile)
    resumed.backend.restore_checkpoint(saved["model_state"],saved["optimizer_state"])
    assert resumed.backend.train_batch(resumed_rows)==expected
    assert resumed.backend.restored_checkpoint_matches(whole["model_state"],whole["optimizer_state"])


def _reviewed_Qwen2_training_local_options(fixture):
    from types import SimpleNamespace
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    def no_registry(*a,**k):pytest.fail("training-recipe reconstruction read a registry")
    def policy(value):assert value["training_requested"]is False and value["downloads_requested"]is False
    return dict(fixture.options,registry=SimpleNamespace(read_artifact=no_registry,artifact_path=no_registry),
        current_admission_provider=lambda:{},execution_guard=lambda:None,asset_policy_guard=policy,
        expected_source_sha256=worker._reviewed_decoder_source_pins(),
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256({}),
        max_model_bytes=64*1024**2,runtime_profile="builtin-qwen2-bfloat16/v1")


@pytest.mark.parametrize("profile",["qwen2-chatml-complete-legal-ir/v1","qwen2-chatml-field-layouts/v1"])
def test_reviewed_Qwen2_training_recipe_restores_profile_without_training(tmp_path,monkeypatch,profile):
    fixture=_reviewed_chatml_local_asset_fixture(tmp_path,max_sequence_tokens=8192,
        local_model_profile="builtin-qwen2-bfloat16/v1",training_conditioning_profile=profile)
    options=_reviewed_Qwen2_training_local_options(fixture)
    monkeypatch.setattr(worker.TorchReviewedDecoderBackend,"train_batch",lambda *a,**k:pytest.fail("loader trained"))
    runtime,receipt=worker.load_local_reviewed_decoder_runtime(**options)
    assert runtime.backend.training_conditioning_profile==profile and runtime.backend.identity()==fixture.backend.identity()
    assert runtime.backend._configuration()["schema"]=="torch-complete-reviewed-decoder-configuration/v4"
    pair={key:Path(options[name].path).read_bytes()for key,name in(("model_state","model_checkpoint"),("optimizer_state","optimizer_checkpoint"))}
    assert runtime.backend.restored_checkpoint_matches(pair["model_state"],pair["optimizer_state"])
    assert receipt["checkpoint_restored"]and receipt["optimizer_steps"]==0


@pytest.mark.parametrize("damage",["unknown","null","missing","v2-with-field"])
def test_reviewed_Qwen2_training_recipe_refuses_closed_data_before_allocation(tmp_path,monkeypatch,damage):
    fixture=_reviewed_chatml_local_asset_fixture(tmp_path,max_sequence_tokens=8192,
        local_model_profile="builtin-qwen2-bfloat16/v1",training_conditioning_profile="qwen2-chatml-field-layouts/v1")
    options=_reviewed_Qwen2_training_local_options(fixture);recipe=json.loads(Path(options["recipe_artifact"].path).read_bytes())
    if damage=="unknown":recipe["training_conditioning_profile"]="unknown"
    elif damage=="null":recipe["training_conditioning_profile"]=None
    elif damage=="missing":del recipe["training_conditioning_profile"]
    else:recipe["schema"]="reviewed-local-decoder-recipe/v2"
    options["recipe_artifact"]=worker.CheckpointArtifact.from_dict(_complete_reviewed_artifact(tmp_path/"bad-recipe.json",worker._json_bytes(recipe)))
    monkeypatch.setattr(type(fixture.backend.model),"__init__",lambda *a,**k:pytest.fail("invalid recipe allocated a model"))
    with pytest.raises(worker.TrainingJobValidationError):worker.load_local_reviewed_decoder_runtime(**options)


def test_reviewed_Qwen2_training_profile_existing_mixed_job_preserves_complete_targets(tmp_path):
    asset_root=tmp_path/"assets";asset_root.mkdir()
    fixture=_reviewed_chatml_local_asset_fixture(asset_root,max_sequence_tokens=8192,
        local_model_profile="builtin-qwen2-bfloat16/v1",fixed_json_schema_subwords=True,
        fixed_typed_schema_subwords=True,training_conditioning_profile="qwen2-chatml-field-layouts/v1")
    runtime,_=worker.load_local_reviewed_decoder_runtime(**_reviewed_Qwen2_training_local_options(fixture))
    job_root=tmp_path/"job";job_root.mkdir()
    mixed=_reviewed_mixed_worker_fixture(job_root,backend=runtime.backend,tokenizer=runtime.tokenizer,two_components=False)
    seen=[]
    def capture(model,args,kwargs):seen.append((kwargs["input_ids"].tolist()[0],kwargs["labels"].tolist()[0]))
    hook=runtime.backend.model.register_forward_pre_hook(capture,with_kwargs=True)
    try:result=worker.execute_training_job(worker.TrainingJobSpec.from_dict(mixed.payload),reviewed_runtime=mixed.runtime)
    finally:hook.remove()
    assert result["backend_train_batch_calls"]==1 and len(seen)==1
    assert all(result[key]is False for key in("qualified","admitted","promotion_performed","corpus_admitted"))
    prepared=mixed.inputs.prepare_reviewed_mixed_decoder_training_inputs_v4(mixed.data.registry,
        **dict(mixed.data.kwargs,tokenizer=runtime.tokenizer,stage_artifact=mixed.payload["stage_artifact"],
            expected_stage_sha256=mixed.payload["stage_artifact"]["sha256"],max_source_tokens=mixed.payload["max_source_tokens"],max_target_tokens=mixed.payload["max_target_tokens"]))
    matches=[]
    for row in prepared["records"]:
        frame=_reviewed_chatml_native_test_frame(runtime.tokenizer.tokenizer,row["source_wire"],public_layouts=True)
        if seen[0]==(frame+row["target_token_ids"][1:],[-100]*len(frame)+row["target_token_ids"][1:]):matches.append(row)
    # Match actual native tensors to exactly one complete admitted record;
    # do not assume or reproduce the worker's seeded row permutation.
    assert len(matches)==1
    row=matches[0]
    assert runtime.tokenizer.decode(row["target_token_ids"][1:-1])==row["target_json"]
    checkpoint=json.loads(Path(result["candidate"]["path"]).read_bytes())
    assert checkpoint["backend_identity"]==runtime.backend.identity()
    assert result["complete_training_binding"]["production_training_eligible"]is False


def _aggregate_v4_context_commitment_fixture(value, profile):
    """Independent caller commitment; exact evidence bytes use existing owner."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    return {"schema":"reviewed-decoder-rich-context-inputs/v4","profile":profile,
        "components":[{"admission_id":item["admission_id"],
            "binding_receipt_sha256":worker._digest(worker._json_bytes(item["binding"].receipt())),
            "training_rows_sha256":worker._digest(worker._json_bytes(item["training_rows"])),
            "admission_inputs_sha256":consumer.reviewed_admission_inputs_sha256(item["admission_inputs"]),
            "exposure_records_sha256":worker._digest(worker._json_bytes(item["exposure_records"]))}
            for item in value["components"]],
        "split_manifest_sha256":worker._digest(worker._json_bytes(value["split_manifest"])),
        "query_rows_sha256":worker._digest(worker._json_bytes(value["query_rows"])),
        "retrieval_rows_sha256":worker._digest(worker._json_bytes(value["retrieval_rows"])),
        "admission_inputs_sha256":worker._digest(worker._json_bytes([
            {"admission_id":item["admission_id"],"admission_inputs_sha256":consumer.reviewed_admission_inputs_sha256(item["admission_inputs"])}
            for item in value["components"]]))}


class _AggregateV4StructuralBackend:
    """Non-neural transport fixture; no model training, restoration or inference."""
    def __init__(self, tokenizer, pair):
        self.tokenizer=tokenizer;self.pair=pair;self.calls=[];self.mutate=None
    def identity(self):
        return dict(backend_id="fixture:structural-aggregate-v4",implementation_sha256="a"*64,
            checkpoint_format="fictional-opaque-pair/v1",target_codec="complete-reviewed-norm-json/v2",
            source_conditioned=True,pretrained=False)
    def restored_checkpoint_matches(self,model,optimizer):return (model,optimizer)==self.pair
    def _forbidden(self,*args,**kwargs):raise AssertionError("structural fixture must not restore, inspect, train, snapshot or read registry assets")
    validate_training_records=inspect_checkpoint=restore_checkpoint=train_batch=snapshot_checkpoint=_forbidden
    def generate_batch(self,records,*,max_output_tokens,execution_guard):
        execution_guard();self.calls.append(json.loads(worker._json_bytes(records)))
        if self.mutate:self.mutate()
        execution_guard()
        return [dict(id=row["id"],unit_id=row["unit_id"],outcome="abstained",candidate=None,
            generated_token_ids=[],generated_text="",reason="fictional non-neural transport abstention") for row in records]


def _aggregate_v4_structural_factory_case(tmp_path, *, tokenizer=None):
    from copy import deepcopy
    from types import SimpleNamespace
    from tests.unit.optimizers.logic_theorem_optimizer import test_legal_ir_evaluation_artifacts as evaluation
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_structured_retrieval as structured
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consumer_binding as consumer
    ch,options,payload=evaluation._aggregate_v4_heldout_case()
    context=options["reviewed_training_context"];state={"policy_revoked":False};policies=[]
    def artifact(name,raw):
        path=tmp_path/name;path.write_bytes(raw)
        return worker.CheckpointArtifact(path=str(path),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
    pair=(b"FICTIONAL structural model bytes; not a neural checkpoint",b"FICTIONAL structural optimizer bytes; not optimizer state")
    model=artifact("fictional-model.txt",pair[0]);optimizer=artifact("fictional-optimizer.txt",pair[1])
    asset=artifact("fictional-asset.txt",b"FICTIONAL test asset; no downloaded model or tokenizer")
    tokenizer=_CompleteReviewedByteTokenizer() if tokenizer is None else tokenizer
    backend=_AggregateV4StructuralBackend(tokenizer,pair)
    registry=SimpleNamespace(read_artifact=backend._forbidden,artifact_path=backend._forbidden)
    runtime=worker.ReviewedDecoderRuntime(registry,backend,tokenizer,lambda:deepcopy(options["admission_inputs"]),lambda:None,lambda _:None)
    references=options["rows"]
    source_contexts=dict(profile="reviewed-source-selection-context/v2",selection_context=dict(
        schema="caller-known-interpretation-selection/v1",interpretation_id=references[0]["canonical_ir"]["interpretation_id"],
        selection_mode="identifier_only"),rows=[dict(id=row["id"],unit_id=row["unit_id"],
            governing_context=deepcopy(row["canonical_ir"]["governing_context"]),
            source_binding=deepcopy(row["canonical_ir"]["source_binding"])) for row in references])
    profile=structured.AGGREGATE_CONTEXT_V4_PROFILE
    def policy(value):
        policies.append(deepcopy(value))
        if state["policy_revoked"]:raise PermissionError("fictional aggregate context policy revoked")
    kwargs=dict(binding=options["binding"],rows=references,split_manifest=options["split_manifest"],
        exposure_records=options["exposure_records"],source_contexts=source_contexts,
        expected_source_contexts_sha256=evaluation._producer_digest(source_contexts),
        expected_admission_inputs_sha256=consumer.reviewed_admission_inputs_sha256(options["admission_inputs"]),
        backend_identity=backend.identity(),assets=(asset,),model_checkpoint=model,optimizer_checkpoint=optimizer,
        max_source_tokens=65536,max_output_tokens=3,allow_heldout_evaluation=True,
        context_profile=profile,current_context_inputs_provider=lambda:context,
        expected_context_inputs_sha256=evaluation._producer_digest(_aggregate_v4_context_commitment_fixture(context,profile)),
        context_policy_guard=policy,context_transport="shared_json_v2")
    return SimpleNamespace(runtime=runtime,backend=backend,kwargs=kwargs,options=options,context=context,
        state=state,policies=policies,evaluation=evaluation,payload=payload)


def test_aggregate_v4_structural_factory_retains_complete_byte_context_refusal(tmp_path):
    fixture=_aggregate_v4_structural_factory_case(tmp_path)
    producer=worker.make_reviewed_decoder_source_producer_v3(fixture.runtime,**fixture.kwargs)
    arguments=tuple(dict(id=row["id"],source_text=row["source_text"],context=dict(permitted=[],
        retrieved=fixture.options["retrieved_examples"][row["id"]])) for row in fixture.options["rows"])
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    with pytest.raises(inputs.ReviewedDecoderInputValidationError,match="complete rich context token budget exceeded"):
        producer(arguments)
    assert fixture.backend.calls==[]
    assert producer.observation()["last_call"]["exit_pair_match"] is True
    declarations=dict(encoder=dict(id="fixture:declared-encoder",sha256="b"*64),
        decoder=dict(id=fixture.backend.identity()["backend_id"],sha256=fixture.kwargs["model_checkpoint"].sha256))
    artifact=producer.evaluate(compiler_commit="fixture:structural-aggregate-source",checkpoint_declarations=declarations)
    payload=fixture.evaluation._producer_payload(artifact)
    assert payload["comparison"]["outcome_counts"]["error"]==3
    assert payload["comparison"]["outcome_counts"]["complete"]==0
    assert payload["producer_exception_type"]=="ReviewedDecoderInputValidationError"
    assert fixture.backend.calls==[]
    assert producer.observation()["training_or_restore_performed"] is False


@pytest.mark.parametrize("damage",["unknown-profile","no-heldout","wrong-commitment","query-revoked","checkpoint-bytes"])
def test_aggregate_v4_structural_factory_refuses_before_backend_on_invalid_custody(tmp_path,damage):
    from copy import deepcopy
    fixture=_aggregate_v4_structural_factory_case(tmp_path)
    options=dict(fixture.kwargs);runtime=fixture.runtime
    if damage=="unknown-profile":options["context_profile"]="unknown-aggregate-profile"
    elif damage=="no-heldout":options["allow_heldout_evaluation"]=False
    elif damage=="wrong-commitment":options["expected_context_inputs_sha256"]="0"*64
    elif damage=="checkpoint-bytes":Path(options["model_checkpoint"].path).write_bytes(b"Changed fictional checkpoint bytes")
    else:
        def revoked():
            current=deepcopy(fixture.options["admission_inputs"])
            current["registry"]["keys"][0]["revoked_at_utc"]="2026-01-01T00:00:00Z"
            return current
        runtime=worker.ReviewedDecoderRuntime(runtime.registry,runtime.backend,runtime.tokenizer,
            revoked,runtime.execution_guard,runtime.asset_policy_guard)
    with pytest.raises(ValueError):worker.make_reviewed_decoder_source_producer_v3(runtime,**options)
    assert fixture.backend.calls==[]


def _aggregate_v4_existing_public_fast_tokenizer():
    """Existing public fixed-schema Unigram fixture; no model or download."""
    from tokenizers import Tokenizer,AddedToken,models,pre_tokenizers,decoders
    from transformers import PreTrainedTokenizerFast
    vocabulary={"[EOS]":0,**{value:index+1 for index,value in enumerate(sorted(pre_tokenizers.ByteLevel.alphabet()))},
        "[BOS]":257,"[UNK]":258,"[PAD]":259}
    # Reuse the existing fixed typed-schema builder, never fit to this panel.
    _reviewed_local_loader_fixed_typed_schema_bpe(vocabulary)
    native=Tokenizer(models.Unigram([(token,-1.0) for token,index in
        sorted(vocabulary.items(),key=lambda pair:pair[1])],unk_id=258))
    native.pre_tokenizer=pre_tokenizers.ByteLevel(add_prefix_space=False,use_regex=False)
    native.decoder=decoders.ByteLevel()
    native.add_special_tokens([AddedToken(value,normalized=False,special=True)
                               for value in ("[EOS]","[BOS]","[UNK]","[PAD]")])
    frontend=PreTrainedTokenizerFast(tokenizer_object=native,bos_token="[BOS]",eos_token="[EOS]",
        unk_token="[UNK]",pad_token="[PAD]",model_max_length=4096,clean_up_tokenization_spaces=False)
    return worker.ReviewedPretrainedTokenizer(frontend,bos_token_id=257,eos_token_id=0,vocab_size=len(vocabulary))


def test_aggregate_v4_public_fast_tokenizer_factory_reaches_structural_backend_with_complete_context(tmp_path):
    """Run only through the original resource owner; tokenizer, not a model."""
    tokenizer=_aggregate_v4_existing_public_fast_tokenizer()
    fixture=_aggregate_v4_structural_factory_case(tmp_path,tokenizer=tokenizer)
    producer=worker.make_reviewed_decoder_source_producer_v3(fixture.runtime,**fixture.kwargs)
    arguments=tuple(dict(id=row["id"],source_text=row["source_text"],context=dict(permitted=[],
        retrieved=fixture.options["retrieved_examples"][row["id"]])) for row in fixture.options["rows"])
    direct=producer(arguments)
    assert len(direct)==3 and all(row["outcome"]=="abstained" for row in direct)
    declarations=dict(encoder=dict(id="fixture:declared-encoder",sha256="b"*64),
        decoder=dict(id=fixture.backend.identity()["backend_id"],sha256=fixture.kwargs["model_checkpoint"].sha256))
    artifact=producer.evaluate(compiler_commit="fixture:public-tokenizer-structural-aggregate",checkpoint_declarations=declarations)
    assert len(fixture.backend.calls)==2 and all(len(records)==3 for records in fixture.backend.calls)
    from ipfs_datasets_py.logic.autoformal import training_cycle_inputs as inputs
    observed=[]
    for index,record in enumerate(fixture.backend.calls[0]):
        decoded=tokenizer.decode(record["source_token_ids"][1:-1]);assert decoded==record["source_wire"]
        source=json.loads(decoded);expected=arguments[index]
        assert source["source_text"]==expected["source_text"]
        assert "canonical_ir" not in source and "typed_expression" not in source
        context=inputs.unpack_reviewed_context_json_v2(source["context"])
        assert context==expected["context"]
        assert {row["content"]["admission_id"] for row in context["retrieved"]}==(
            {"fixture:train:A","fixture:train:B"} if index<2 else {"fixture:train:A"})
        wire=worker._reviewed_generation_context_wire(source,{row["id"] for row in arguments})
        context_count=len(tokenizer.encode(wire))+2
        assert context_count<=worker.REVIEWED_GENERATION_CONTEXT_MAX_TOKENS==4096
        assert len(wire.encode("utf-8"))<=worker.REVIEWED_GENERATION_CONTEXT_MAX_BYTES==16384
        observed.append(dict(id=record["id"],complete_source_tokens=len(record["source_token_ids"]),
            complete_context_tokens=context_count,context_bytes=len(wire.encode("utf-8")),
            examples=len(context["retrieved"])))
    payload=fixture.evaluation._producer_payload(artifact)
    assert payload["comparison"]["outcome_counts"]["abstained"]==3
    assert payload["comparison"]["outcome_counts"]["error"]==0
    assert producer.observation()["training_or_restore_performed"] is False
    assert producer.observation()["last_call"]["completed"] is True
    (tmp_path/"public-tokenizer-structural-observation.json").write_text(json.dumps(dict(
        schema="public-tokenizer-structural-factory-mechanics/v1",rows=observed,
        model_weights_loaded=False,model_inference=False,training=False,
        actual_pretrained_capacity_or_quality=False),indent=2)+"\n")
