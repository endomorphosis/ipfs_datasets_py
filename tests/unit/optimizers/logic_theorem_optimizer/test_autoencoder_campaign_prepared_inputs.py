"""One-operation campaign metadata reuse; synthetic declared vectors only.

These tests exercise artifact integrity and injected callbacks. They do not run
embedding inference, model training, native qualification or Lean admission.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import pickle

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_job_inputs as campaign
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_produced_record_projection as projection_codec
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_worker import _campaign_job, _artifact


METADATA = (*worker.CAMPAIGN_ARTIFACT_FIELDS, "corpus_manifest_artifact")


def _spec(tmp_path):
    payload, fixture, projection = _campaign_job(tmp_path)
    return worker.TrainingJobSpec.from_dict(payload), fixture, projection


def _forbidden(*args, **kwargs):
    pytest.fail("invalid prepared metadata must fail before selected artifact I/O")


def _consume(spec, prepared):
    return campaign._verify_prepared_campaign_job_inputs(spec, prepared)


def test_prepared_consumer_uses_one_top_level_decode_and_preserves_exact_summary(tmp_path, monkeypatch):
    spec, _, _ = _spec(tmp_path)
    expected = campaign.verify_campaign_job_inputs(spec)
    original = campaign._load
    loads = []

    def observed(loader, artifact, **kwargs):
        loads.append((loader.__name__, artifact.sha256))
        return original(loader, artifact, **kwargs)

    monkeypatch.setattr(campaign, "_load", observed)
    prepared = campaign.preflight_campaign_job_inputs(spec)
    assert [name for name, _ in loads] == ["load_uscode_source_inventory", "load_source_partitions",
        "load_embedding_receipt_set", "load_produced_record_projection", "load_corpus_manifest"]
    frozen_loads = list(loads)
    assert _consume(spec, prepared) == expected
    assert loads == frozen_loads  # Nested codec validation is not claimed removed.
    # A public verification still performs its own independent preflight.
    assert campaign.verify_campaign_job_inputs(spec) == expected
    assert len(loads) == 10


def test_prepared_metadata_views_are_detached_and_context_is_not_transport(tmp_path):
    spec, _, _ = _spec(tmp_path)
    prepared = campaign.preflight_campaign_job_inputs(spec)
    membership, selected = prepared.membership, prepared.selected
    membership["dataset_snapshot_id"] = "forged"
    selected["leaf_receipts"].clear()
    assert prepared.membership["dataset_snapshot_id"] == spec.dataset_snapshot_id
    assert len(prepared.selected["leaf_receipts"]) == 4
    with pytest.raises(FrozenInstanceError):
        prepared._membership_raw = b"{}"
    with pytest.raises(FrozenInstanceError):
        prepared._use.consumed = False
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(prepared)
    verified = _consume(spec, prepared)
    assert verified["produced_record_projection_verification"]["selected_leaf_count"] == 4


@pytest.mark.parametrize("mutation", ["job_id", "output_path", "metadata_path", "leaf_path", "source_path",
    "train_order", "validation_order", "leaf_order", "source_order", "code_identity", "config"])
def test_prepared_context_binds_full_job_paths_and_order_before_any_io(tmp_path, monkeypatch, mutation):
    spec, _, _ = _spec(tmp_path)
    prepared = campaign.preflight_campaign_job_inputs(spec)
    if mutation == "job_id":
        changed = replace(spec, job_id="different-job")
    elif mutation == "output_path":
        changed = replace(spec, output_directory=str(tmp_path / "different-output"))
    elif mutation == "metadata_path":
        changed = replace(spec, source_inventory_artifact=replace(spec.source_inventory_artifact,
            path=str(tmp_path / "different-inventory")))
    elif mutation in {"leaf_path", "source_path"}:
        name = "embedding_receipt_artifacts" if mutation == "leaf_path" else "corpus_source_artifacts"
        refs = list(getattr(spec, name))
        refs[0] = replace(refs[0], path=str(tmp_path / "different-artifact"))
        changed = replace(spec, **{name: refs})
    elif mutation in {"train_order", "validation_order", "leaf_order", "source_order"}:
        name = {"train_order": "samples", "validation_order": "validation_samples",
                "leaf_order": "embedding_receipt_artifacts", "source_order": "corpus_source_artifacts"}[mutation]
        changed = replace(spec, **{name: tuple(reversed(getattr(spec, name)))})
    elif mutation == "code_identity":
        changed = replace(spec, code_identity="different-code-label")
    else:
        changed = replace(spec, training_config=replace(spec.training_config, max_seconds=179))
    monkeypatch.setattr(campaign, "_verify_metadata_bytes", _forbidden)
    with pytest.raises(worker.TrainingJobValidationError, match="exact job or decoded metadata"):
        _consume(changed, prepared)
    with pytest.raises(worker.TrainingJobValidationError, match="already been consumed"):
        _consume(spec, prepared)


@pytest.mark.parametrize("field", ["manifest", "partitions", "receipt_set", "projection",
                                  "_membership_raw", "_selected_raw", "leaf_resolver", "source_resolver"])
def test_dataclass_replacement_cannot_substitute_verified_context_fields(tmp_path, monkeypatch, field):
    spec, _, _ = _spec(tmp_path)
    prepared = campaign.preflight_campaign_job_inputs(spec)
    substitute = b"{}" if field.endswith("_raw") else object()
    changed = replace(prepared, **{field: substitute})
    monkeypatch.setattr(campaign, "_verify_metadata_bytes", _forbidden)
    with pytest.raises(worker.TrainingJobValidationError, match="exact job or decoded metadata"):
        _consume(spec, changed)
    # Replacement shares the same one-use state, so it cannot reset the gate.
    with pytest.raises(worker.TrainingJobValidationError, match="already been consumed"):
        _consume(spec, prepared)


def test_direct_cached_codec_substitution_is_detected_before_io(tmp_path, monkeypatch):
    spec, _, _ = _spec(tmp_path)
    prepared = campaign.preflight_campaign_job_inputs(spec)
    object.__setattr__(prepared.manifest, "_training_record_ids", ())
    monkeypatch.setattr(campaign, "_verify_metadata_bytes", _forbidden)
    with pytest.raises(worker.TrainingJobValidationError, match="exact job or decoded metadata"):
        _consume(spec, prepared)


def test_context_consumption_requires_creating_thread_and_is_single_use(tmp_path):
    spec, _, _ = _spec(tmp_path)
    prepared = campaign.preflight_campaign_job_inputs(spec)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(worker.TrainingJobValidationError, match="another thread"):
            pool.submit(_consume, spec, prepared).result()
    # A wrong-thread attempt does not claim the owner's one-use state.
    first = _consume(spec, prepared)
    assert first["source_campaign_verified"] is True
    with pytest.raises(worker.TrainingJobValidationError, match="already been consumed"):
        _consume(spec, prepared)


@pytest.mark.parametrize("field", METADATA)
@pytest.mark.parametrize("mutation", ["corrupt", "symlink"])
def test_stale_metadata_is_rehashed_before_selected_io(tmp_path, monkeypatch, field, mutation):
    spec, _, _ = _spec(tmp_path)
    prepared = campaign.preflight_campaign_job_inputs(spec)
    path = Path(getattr(spec, field).path)
    if mutation == "corrupt":
        raw = bytearray(path.read_bytes())
        raw[len(raw) // 2] ^= 1
        path.write_bytes(raw)
    else:
        backup = tmp_path / f"original-{field}"
        path.rename(backup)
        path.symlink_to(backup)
    monkeypatch.setattr(projection_codec.ProducedRecordProjection, "verify_batch", _forbidden)
    with pytest.raises(worker.TrainingJobValidationError, match="selected-byte verification failed"):
        _consume(spec, prepared)
    with pytest.raises(worker.TrainingJobValidationError, match="already been consumed"):
        _consume(spec, prepared)


@pytest.mark.parametrize("field", METADATA)
def test_metadata_changed_by_selected_verification_is_rehashed_at_end(tmp_path, monkeypatch, field):
    spec, _, _ = _spec(tmp_path)
    prepared = campaign.preflight_campaign_job_inputs(spec)
    verify = projection_codec.ProducedRecordProjection.verify_batch
    seen = []

    def mutate_after_selected(self, *args, **kwargs):
        result = verify(self, *args, **kwargs)
        seen.append(result["supplied_records_verified"])
        path = Path(getattr(spec, field).path)
        path.write_bytes(path.read_bytes() + b" ")
        return result

    monkeypatch.setattr(projection_codec.ProducedRecordProjection, "verify_batch", mutate_after_selected)
    with pytest.raises(worker.TrainingJobValidationError, match="selected-byte verification failed"):
        _consume(spec, prepared)
    assert seen == [4]


def test_cached_codec_mutation_during_selected_verification_cannot_change_summary(tmp_path, monkeypatch):
    spec, _, _ = _spec(tmp_path)
    prepared = campaign.preflight_campaign_job_inputs(spec)
    verify = projection_codec.ProducedRecordProjection.verify_batch

    def mutate_after_selected(self, *args, **kwargs):
        result = verify(self, *args, **kwargs)
        object.__setattr__(prepared.partitions, "_summary", {"forged": True})
        return result

    monkeypatch.setattr(projection_codec.ProducedRecordProjection, "verify_batch", mutate_after_selected)
    with pytest.raises(worker.TrainingJobValidationError, match="exact job or decoded metadata"):
        _consume(spec, prepared)


@pytest.mark.parametrize("closure", ["embedding_receipt_artifacts", "corpus_source_artifacts"])
def test_prepared_consumption_still_verifies_fresh_selected_bytes(tmp_path, closure):
    spec, _, _ = _spec(tmp_path)
    prepared = campaign.preflight_campaign_job_inputs(spec)
    Path(getattr(spec, closure)[0].path).write_bytes(b"stale")
    with pytest.raises(worker.TrainingJobValidationError, match="selected-byte verification failed"):
        _consume(spec, prepared)


@pytest.mark.parametrize("field", ["source_inventory_artifact", "produced_record_projection_artifact"])
def test_public_schema_limits_precede_preparation(tmp_path, monkeypatch, field):
    spec, _, _ = _spec(tmp_path)
    payload = spec.to_dict()
    payload[field]["bytes"] = (4 if field == "produced_record_projection_artifact" else 64) * 1024**2 + 1
    monkeypatch.setattr(campaign, "_load", _forbidden)
    with pytest.raises(worker.TrainingJobValidationError, match="byte bound"):
        campaign.preflight_campaign_job_inputs(worker.TrainingJobSpec.from_dict(payload))


def test_both_role_guards_still_run_before_preparation_returns(tmp_path, monkeypatch):
    spec, _, projection = _spec(tmp_path)
    data = projection.to_dict()
    data["validation_record_ids"].append(data["training_record_ids"].pop())
    descriptor = _artifact(tmp_path / "forged-projection.json", worker._json_bytes(data))
    changed = replace(spec, produced_record_projection_artifact=worker.CheckpointArtifact.from_dict(descriptor))
    monkeypatch.setattr(projection_codec.ProducedRecordProjection, "verify_batch", _forbidden)
    with pytest.raises(worker.TrainingJobValidationError, match="input verification failed"):
        campaign.preflight_campaign_job_inputs(changed)
