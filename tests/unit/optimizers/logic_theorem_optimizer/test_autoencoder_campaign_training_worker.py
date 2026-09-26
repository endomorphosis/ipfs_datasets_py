"""V8 campaign jobs using declared-native synthetic vectors, never inference.

Injected workers exercise provenance and private output contracts only; none of
these fixtures attest model production, train a model, or admit a legal span.
"""
from dataclasses import asdict, fields, replace
import hashlib
import json
from pathlib import Path
import pickle

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_job_inputs as campaign
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_manifest as cm
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as ci
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_produced_record_projection as prp
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_produced_record_projection import _prepared
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_worker import _job, _trainer, _indexed_corpus_job


def _artifact(path, raw):
    path = Path(path)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _campaign_job(tmp_path, *, groups=None):
    """Reusable exact v8 job fixture: (JSON payload, ProjectionCase, projection)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture = _prepared(tmp_path, groups=groups)
    projection = fixture.build()
    manifest = fixture.manifest
    selected = projection.selected_artifacts()
    data = manifest.to_dict()
    by_id = {record.record_id: record for record in manifest.records}
    payload = _job(tmp_path, schema_version=worker.CAMPAIGN_SCHEMA_VERSION,
        dataset_snapshot_id=manifest.dataset_snapshot_id, split_snapshot_id=manifest.split_snapshot_id,
        samples=[asdict(by_id[key].sample) for key in data["split"]["training_record_ids"]],
        validation_samples=[asdict(by_id[key].sample) for key in data["split"]["validation_record_ids"]],
        corpus_manifest_artifact=_artifact(tmp_path / "batch.json", manifest.to_bytes()),
        corpus_source_artifacts=[{"path": str(fixture.case.source_paths[ref["sha256"]]), **ref}
                                 for ref in selected["source_artifacts"]],
        source_inventory_artifact=_artifact(tmp_path / "inventory.json", fixture.case.partitions.inventory.to_bytes()),
        source_partitions_artifact=_artifact(tmp_path / "partitions.json", fixture.case.partitions.to_bytes()),
        embedding_receipt_set_artifact=_artifact(tmp_path / "receipt-set.json", fixture.receipt_set.to_bytes()),
        produced_record_projection_artifact=_artifact(tmp_path / "projection.json", projection.to_bytes()),
        embedding_receipt_artifacts=[{"path": str(fixture.case.leaf_paths[ref["sha256"]]), **ref}
                                     for ref in selected["leaf_receipts"]])
    return payload, fixture, projection


def _forbidden(*args, **kwargs):
    pytest.fail("invalid campaign must fail before selected-byte I/O or model construction")


def test_v8_exact_multileaf_verification_preserves_campaign_and_leaf_claims(tmp_path, monkeypatch):
    payload, fixture, projection = _campaign_job(tmp_path)
    spec = worker.TrainingJobSpec.from_dict(payload)
    monkeypatch.setattr(ci, "build_corpus_index", _forbidden)
    monkeypatch.setattr(ci, "load_corpus_index", _forbidden)
    summary = worker.verify_corpus_job_inputs(spec)
    assert summary["source_campaign_verified"] is summary["produced_record_projection_verified"] is True
    assert summary["dataset_and_split_identity_verified"] is True
    assert summary["global_holdout_verified"] is False
    assert summary["frontend"] == "legacy_us_code"
    root = summary["source_campaign_verification"]
    for field, key in (("source_inventory_artifact", "source_inventory"),
                       ("source_partitions_artifact", "source_partitions"),
                       ("embedding_receipt_set_artifact", "embedding_receipt_set")):
        assert root[key] == {name: payload[field][name] for name in ("sha256", "bytes")}
    assert root["source_partition_verification"] == fixture.case.partitions.verification_summary()
    assert root["receipt_set_verification"] == fixture.receipt_set.summary()
    checked = summary["produced_record_projection_verification"]
    assert checked["selected_artifacts"] == projection.selected_artifacts()
    assert checked["supplied_records_verified"] == checked["selected_leaf_count"] == 4
    for name in ("current_selected_leaf_bytes_verified", "current_selected_source_bytes_verified", "supplied_manifest_verified"):
        assert checked[name] is True
    for name in ("training_eligible", "runtime_cryptographically_attested", "source_authority_authenticated", "admitted"):
        assert checked[name] is False
    assert "corpus_index_membership_verified" not in summary
    assert "embedding_production_verified" not in summary
    assert pickle.loads(pickle.dumps(spec)).to_dict() == spec.to_dict()
    assert worker.TrainingJobSpec.from_dict(spec.to_dict()).canonical_sha256 == spec.canonical_sha256


def test_v8_metadata_preflight_never_opens_selected_bytes(tmp_path, monkeypatch):
    payload, _, _ = _campaign_job(tmp_path)
    for ref in [*payload["corpus_source_artifacts"], *payload["embedding_receipt_artifacts"]]:
        Path(ref["path"]).unlink()
    monkeypatch.setattr(cm.CorpusManifest, "validate_sources", _forbidden)
    monkeypatch.setattr(prp.ProducedRecordProjection, "verify_batch", _forbidden)
    prepared = campaign.preflight_campaign_job_inputs(worker.TrainingJobSpec.from_dict(payload))
    assert len(prepared.manifest.records) == 4


@pytest.mark.parametrize("closure", ["embedding_receipt_artifacts", "corpus_source_artifacts"])
@pytest.mark.parametrize("mutation", ["extra", "missing", "size", "sha256"])
def test_v8_exact_selected_closure_rejected_before_any_selected_io(tmp_path, monkeypatch, closure, mutation):
    payload, fixture, _ = _campaign_job(tmp_path)
    refs = payload[closure]
    if mutation == "missing":
        refs.pop()
    elif mutation == "extra":
        if closure == "embedding_receipt_artifacts":
            ref = next(ref for ref in fixture.case.descriptors if ref["sha256"] not in {item["sha256"] for item in refs})
            refs.append({**ref, "path": str(fixture.case.leaf_paths[ref["sha256"]])})
        else:
            digest = next(digest for digest in fixture.case.source_paths if digest not in {item["sha256"] for item in refs})
            path = fixture.case.source_paths[digest]
            refs.append({"sha256": digest, "bytes": path.stat().st_size, "path": str(path)})
    elif mutation == "size":
        refs[0]["bytes"] += 1
    else:
        refs[0]["sha256"] = "0" * 64
    monkeypatch.setattr(cm.CorpusManifest, "validate_sources", _forbidden)
    monkeypatch.setattr(prp.ProducedRecordProjection, "verify_batch", _forbidden)
    with pytest.raises(worker.TrainingJobValidationError, match="exact projection closure"):
        worker.verify_corpus_job_inputs(worker.TrainingJobSpec.from_dict(payload))


@pytest.mark.parametrize("field", worker.CAMPAIGN_JOB_FIELDS)
def test_v8_requires_every_campaign_binding(tmp_path, field):
    payload, _, _ = _campaign_job(tmp_path)
    payload.pop(field)
    with pytest.raises(worker.TrainingJobValidationError, match="v8 requires"):
        worker.TrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize("field", ["corpus_manifest_artifact", "corpus_source_artifacts", "validation_samples"])
def test_v8_requires_manifest_source_and_explicit_validation(tmp_path, field):
    payload, _, _ = _campaign_job(tmp_path)
    payload.pop(field)
    with pytest.raises(worker.TrainingJobValidationError):
        worker.TrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize("field", ["corpus_index_artifact", "corpus_selection_sha256", "embedding_production_artifact", "arrow_embedding_inputs_artifact"])
def test_v8_rejects_old_binding_keys_even_null(tmp_path, field):
    payload, _, _ = _campaign_job(tmp_path)
    payload[field] = None
    with pytest.raises(worker.TrainingJobValidationError, match="v8 forbids"):
        worker.TrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize("version", range(1, 8))
@pytest.mark.parametrize("field", worker.CAMPAIGN_JOB_FIELDS)
def test_older_schemas_reject_new_fields_even_explicit_null(tmp_path, version, field):
    # This rejects on the version contract before any other schema requirement.
    payload = _job(tmp_path, schema_version=f"autoencoder-training-job-v{version}")
    payload[field] = None
    with pytest.raises(worker.TrainingJobValidationError, match="v8 job schema"):
        worker.TrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize("version", range(1, 8))
def test_older_canonical_bytes_and_positional_tail_do_not_change(tmp_path, version):
    schema = f"autoencoder-training-job-v{version}"
    if version >= 5:
        payload, _, _ = _indexed_corpus_job(tmp_path, production=version >= 6, arrow_inputs=version >= 7)
    else:
        payload = _job(tmp_path, schema_version=schema, expected_source_sha256={})
    spec = worker.TrainingJobSpec.from_dict(payload)
    legacy = spec.to_dict()
    assert not set(legacy).intersection(worker.CAMPAIGN_JOB_FIELDS)
    # Independent pre-v8 serialized field contract: exact keys/values retain hash.
    ordered_fields = [field.name for field in fields(worker.TrainingJobSpec)]
    assert ordered_fields[-7:] == ["embedding_production_artifact", "arrow_embedding_inputs_artifact", *worker.CAMPAIGN_JOB_FIELDS]
    restored = worker.TrainingJobSpec(*[getattr(spec, name) for name in ordered_fields[:-5]])
    assert restored.to_dict() == legacy
    assert restored.canonical_sha256 == hashlib.sha256(worker._json_bytes(legacy)).hexdigest()
    assert worker.TrainingJobSpec.from_dict(legacy).to_dict() == legacy


@pytest.mark.parametrize("field", worker.CAMPAIGN_ARTIFACT_FIELDS)
def test_campaign_root_byte_bounds_are_enforced_before_io(tmp_path, field):
    payload, _, _ = _campaign_job(tmp_path)
    payload[field]["bytes"] = (4 if field == "produced_record_projection_artifact" else 64) * 1024**2 + 1
    with pytest.raises(worker.TrainingJobValidationError, match="byte bound"):
        worker.TrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize("closure,mutation", [("embedding_receipt_artifacts", "count"),
    ("embedding_receipt_artifacts", "aggregate"), ("embedding_receipt_artifacts", "duplicate"),
    ("corpus_source_artifacts", "aggregate")])
def test_campaign_selected_closure_bounds(tmp_path, closure, mutation):
    payload, _, _ = _campaign_job(tmp_path)
    refs = payload[closure]
    if mutation == "count":
        payload[closure] = [{"path": refs[0]["path"], "sha256": f"{index:064x}", "bytes": 1} for index in range(257)]
    elif mutation == "duplicate":
        refs.append(dict(refs[0]))
    else:
        refs[0]["bytes"] = refs[1]["bytes"] = 33 * 1024**2
    with pytest.raises(worker.TrainingJobValidationError):
        worker.TrainingJobSpec.from_dict(payload)


@pytest.mark.parametrize("field", [*worker.CAMPAIGN_ARTIFACT_FIELDS, "corpus_manifest_artifact"])
def test_root_corruption_rejected_before_leaf_source_or_trainer(tmp_path, monkeypatch, field):
    payload, _, _ = _campaign_job(tmp_path)
    Path(payload[field]["path"]).write_bytes(b"corrupt")
    monkeypatch.setattr(cm.CorpusManifest, "validate_sources", _forbidden)
    monkeypatch.setattr(prp.ProducedRecordProjection, "verify_batch", _forbidden)
    with pytest.raises(worker.TrainingJobValidationError):
        worker.verify_corpus_job_inputs(worker.TrainingJobSpec.from_dict(payload))


@pytest.mark.parametrize("mutation", ["dataset", "split", "train_order", "validation_order", "vector"])
def test_exact_snapshot_and_ordered_job_rows_precede_selected_byte_io(tmp_path, monkeypatch, mutation):
    payload, _, _ = _campaign_job(tmp_path)
    if mutation in {"dataset", "split"}:
        payload[f"{mutation}_snapshot_id"] = "sha256:" + "0" * 64
    elif mutation == "train_order":
        payload["samples"].reverse()
    elif mutation == "validation_order":
        payload["validation_samples"].reverse()
    else:
        payload["samples"][0]["embedding_vector"] = [0.5] * 384
    monkeypatch.setattr(cm.CorpusManifest, "validate_sources", _forbidden)
    monkeypatch.setattr(prp.ProducedRecordProjection, "verify_batch", _forbidden)
    with pytest.raises(worker.TrainingJobValidationError):
        worker.verify_corpus_job_inputs(worker.TrainingJobSpec.from_dict(payload))


@pytest.mark.parametrize("closure", ["embedding_receipt_artifacts", "corpus_source_artifacts"])
def test_selected_byte_corruption_rejected_before_model_or_output(tmp_path, monkeypatch, closure):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder
    payload, _, _ = _campaign_job(tmp_path)
    Path(payload[closure][0]["path"]).write_bytes(b"corrupt")
    monkeypatch.setattr(AdaptiveModalAutoencoder, "__init__", _forbidden)
    spec = worker.TrainingJobSpec.from_dict(payload)
    with pytest.raises(worker.TrainingJobValidationError, match="selected-byte verification"):
        worker.execute_training_job(spec, trainer=_forbidden)
    assert not Path(spec.output_directory).exists()


def test_v8_worker_receipt_preserves_private_candidate_and_limited_claims(tmp_path):
    payload, _, _ = _campaign_job(tmp_path)
    spec = worker.TrainingJobSpec.from_dict(payload)
    before = Path(spec.base_checkpoint.path).read_bytes()
    receipt = worker.execute_training_job(spec, trainer=_trainer)
    assert receipt["source_campaign_verified"] is receipt["produced_record_projection_verified"] is True
    for field in worker.CAMPAIGN_JOB_FIELDS:
        assert receipt[field] == payload[field]
    for field in ("corpus_index_artifact", "corpus_selection_sha256", "embedding_production_artifact",
                  "embedding_production_verified", "arrow_embedding_inputs_artifact"):
        assert field not in receipt
    assert receipt["execution_mode"] == "injected_test"
    assert receipt["heldout_canary_qualified"] is receipt["admitted"] is receipt["promotion_performed"] is False
    assert receipt["corpus_verification"]["source_campaign_verification"]["receipt_set_verification"]["training_eligible"] is False
    assert receipt["job_spec_canonical_sha256"] == spec.canonical_sha256
    assert Path(spec.base_checkpoint.path).read_bytes() == before
    assert "roundtrip_ok" not in json.dumps(receipt)


def test_v8_keeps_shared_targets_sparse_candidates_dependencies_and_arrow_features_opt_in(tmp_path):
    payload, _, _ = _campaign_job(tmp_path)
    ref = dict(payload["base_checkpoint"])
    ref["sha256"] = "a" * 64
    payload.update(target_snapshot_id="fixture-target-snapshot", target_snapshot_artifact=ref,
        capture_sparse_patches=True, candidate_storage="sparse", base_checkpoint_dependencies=[ref],
        arrow_feature_weights_artifact=ref)
    spec = worker.TrainingJobSpec.from_dict(payload)
    restored = worker.TrainingJobSpec.from_dict(spec.to_dict())
    assert restored.capture_sparse_patches and restored.candidate_storage == "sparse"
    assert restored.target_snapshot_id == "fixture-target-snapshot"
    assert restored.arrow_feature_weights_artifact is not None
    assert restored.base_checkpoint_dependencies == spec.base_checkpoint_dependencies
    assert worker.SCHEMA_VERSION == "autoencoder-training-job-v4"


@pytest.mark.parametrize("mutation", ["validation_from_train", "training_from_validation", "dataset", "split", "train_order", "validation_order", "record_summary"])
def test_projection_metadata_mismatch_and_role_escalation_fail_before_selected_io(tmp_path, monkeypatch, mutation):
    payload, _, projection = _campaign_job(tmp_path)
    data = projection.to_dict()
    if mutation == "validation_from_train":
        data["validation_record_ids"].append(data["training_record_ids"].pop())
    elif mutation == "training_from_validation":
        data["training_record_ids"].append(data["validation_record_ids"].pop())
    elif mutation in {"dataset", "split"}:
        data[f"{mutation}_snapshot_id"] = "sha256:" + "0" * 64
    elif mutation in {"train_order", "validation_order"}:
        data["training_record_ids" if mutation == "train_order" else "validation_record_ids"].reverse()
    else:
        data["records"][0]["record_summary"]["sample_payload_sha256"] = "0" * 64
    payload["produced_record_projection_artifact"] = _artifact(tmp_path / "projection.json", worker._json_bytes(data))
    monkeypatch.setattr(cm.CorpusManifest, "validate_sources", _forbidden)
    monkeypatch.setattr(prp.ProducedRecordProjection, "verify_batch", _forbidden)
    with pytest.raises(worker.TrainingJobValidationError):
        campaign.preflight_campaign_job_inputs(worker.TrainingJobSpec.from_dict(payload))


def test_v8_shared_leaf_checks_only_selected_sources_and_preserves_original_provenance(tmp_path):
    payload, fixture, _ = _campaign_job(tmp_path, groups=[list(range(32))])
    selected = {ref["sha256"] for ref in payload["corpus_source_artifacts"]}
    for digest, path in fixture.case.source_paths.items():
        if digest not in selected:
            path.unlink()
    checked = worker.verify_corpus_job_inputs(worker.TrainingJobSpec.from_dict(payload))
    projection = checked["produced_record_projection_verification"]
    assert projection["selected_leaf_count"] == 1
    assert projection["supplied_records_verified"] == 4
    assert projection["unselected_source_bytes_reverified"] is False
    leaf = payload["embedding_receipt_artifacts"][0]["sha256"]
    assert all(record.embedding_provenance.artifact_sha256 == leaf for record in fixture.manifest.records)
