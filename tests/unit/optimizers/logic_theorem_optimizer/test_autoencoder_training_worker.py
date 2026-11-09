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


def _complete_reviewed_worker_fixture(tmp_path, *, known_interpretation_id="fixture:act-v1/selected-interpretation"):
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
        "batch_size": 1, "seed": 1729, "token_budgets": budget,
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
        "max_source_tokens": 8192, "max_target_tokens": 32768, "batch_size": 1,
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
        def forward(self, *, input_ids, attention_mask, labels, decoder_input_ids=None):
            assert bool(attention_mask.all())
            self.calls.append({"input_ids": input_ids.detach().cpu().tolist(),
                               "labels": labels.detach().cpu().tolist(),
                               "decoder_input_ids": None if decoder_input_ids is None else decoder_input_ids.detach().cpu().tolist()})
            if self.config.is_encoder_decoder:
                _, hidden = self.encoder(self.embedding(input_ids))
                decoded, _ = self.decoder(self.embedding(decoder_input_ids), hidden)
                logits = self.head(self.dropout(decoded))
                loss = torch.nn.functional.cross_entropy(logits.reshape(-1, 259), labels.reshape(-1))
            else:
                decoded, _ = self.decoder(self.embedding(input_ids))
                logits = self.head(self.dropout(decoded))
                loss = torch.nn.functional.cross_entropy(logits[:, :-1].reshape(-1, 259), labels[:, 1:].reshape(-1))
            return SimpleNamespace(loss=loss)

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
        "governing_context": {"jurisdiction": "fixture:us"}, "interpretation_id": "fixture:one",
        "source_binding": {"source_version_cid": "fixture:source", "occurrence_cid": "fixture:occurrence",
                           "document_revision": "fixture:revision"},
        "definition_uses": [{"fixture_definition": "clerk"}], "cross_references": []}
    source_wire = json.dumps({"profile": "reviewed-source-selection-context/v2",
        "source_text": "A fixture clerk must file.", "governing_context": {"jurisdiction": "fixture:us"},
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
