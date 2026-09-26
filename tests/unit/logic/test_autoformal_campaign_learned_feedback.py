"""Synthetic receipt declarations and fake model observations; no native inference.

Actual input and checkpoint codecs still verify fixture bytes. Declared native
execution labels below only exercise the observer's required receipt contract.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import learned_feedback, training_cycle_inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder, legal_samples
from tests.unit.logic.test_autoformal_campaign_training_inputs import _spec


def _write(path, value):
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _case(tmp_path, monkeypatch, *, schema="v8"):
    spec = _spec(tmp_path / "input", schema)
    state = modal_autoencoder.ModalAutoencoderTrainingState.from_dict(json.loads(Path(spec.base_checkpoint.path).read_bytes()))
    receipt = {"schema_version": "autoencoder-training-worker-receipt-v1", "execution_mode": "native_training",
        "admitted": False, "promotion_performed": False, "use_sample_memory": False,
        "job_spec": spec.to_dict(), "job_spec_canonical_sha256": spec.canonical_sha256, "job_id": spec.job_id,
        "candidate": asdict(spec.base_checkpoint), "candidate_state_identity": {"digest": state.state_identity()},
        "effective_autoencoder_config": {"compute_device": "python"}, "tree_file_sha256": {}}
    path = tmp_path / "synthetic-declared-native-receipt.json"
    samples, constructions = [], []

    class FakeModel:
        def __init__(self, *, state, compute_device="python"):
            self.state, self.compute_device = state, compute_device
            constructions.append(self)

        def introspect_sample(self, sample, **kwargs):
            assert kwargs == {"use_sample_memory": False, "top_k": 4, "include_causal_attribution": False}
            return SimpleNamespace(sample_id=sample.sample_id, sample_memory_used=False,
                                   cosine_similarity=0.25, reconstruction_loss=0.75)

        def compiler_guidance_for_sample(self, sample, **kwargs):
            assert kwargs["use_sample_memory"] is False
            return {"sample_id": sample.sample_id, "sample_memory_used": False,
                    "family_distribution": {"deontic": 1.0}, "feature_groups": {}}

    def fake_sample(**kwargs):
        samples.append(kwargs)
        return SimpleNamespace(sample_id="fixture:" + hashlib.sha256(kwargs["text"].encode()).hexdigest())

    monkeypatch.setattr(modal_autoencoder, "AdaptiveModalAutoencoder", FakeModel)
    monkeypatch.setattr(legal_samples, "build_us_code_sample", fake_sample)
    return spec, receipt, path, samples, constructions


@pytest.mark.parametrize("schema", ["v6", "v8"])
@pytest.mark.parametrize("subset", [False, True])
def test_observer_consumes_only_exact_ordered_inline_training_records(tmp_path, monkeypatch, schema, subset):
    spec, receipt, path, samples, constructions = _case(tmp_path, monkeypatch, schema=schema)
    checked = training_cycle_inputs.verify_cycle_inputs(spec)
    ids = [record.record_id for record in checked.training_records]
    chosen = list(reversed(ids))[:1] if subset else ids
    result = learned_feedback.observe_checkpoint(path, _write(path, receipt), record_ids=chosen if subset else None)
    assert len(constructions) == 1
    assert [row["source_span_id"] for row in result["observations"]] == chosen
    expected = {record.record_id: asdict(record.sample) for record in checked.training_records}
    assert samples == [expected[key] for key in chosen]
    assert not set(chosen).intersection(checked.verification["validation_record_ids"])
    assert result["observation_count"] == len(chosen)
    assert result["counts_as_validation"] is result["symbolic_decoder_output"] is result["admitted"] is False
    assert result["state_changed"] is result["formalized"] is False
    helper_hash = hashlib.sha256(Path(training_cycle_inputs.__file__).read_bytes()).hexdigest()
    assert result["input_helper_source_sha256"] == result["code_hashes"]["cycle_inputs"] == helper_hash
    # This helper was not among the native worker's historical implementation
    # hashes; absence is not reported as observed post-training source drift.
    assert "cycle_inputs" not in result["code_changed_since_training"]


@pytest.mark.parametrize("schema", ["v6", "v8"])
def test_observer_rejects_validation_selection_before_model_construction(tmp_path, monkeypatch, schema):
    spec, receipt, path, samples, constructions = _case(tmp_path, monkeypatch, schema=schema)
    validation = training_cycle_inputs.verify_cycle_inputs(spec).verification["validation_record_ids"]
    with pytest.raises(ValueError, match="training members"):
        learned_feedback.observe_checkpoint(path, _write(path, receipt), record_ids=validation)
    assert samples == constructions == []


@pytest.mark.parametrize("field,value", [("execution_mode", "injected_test"), ("admitted", True),
    ("promotion_performed", True), ("use_sample_memory", True), ("job_id", "foreign-job"),
    ("job_spec_canonical_sha256", "0" * 64)])
def test_native_receipt_guards_still_precede_any_feedback_model(tmp_path, monkeypatch, field, value):
    _, receipt, path, samples, constructions = _case(tmp_path, monkeypatch)
    receipt[field] = value
    with pytest.raises(ValueError, match="native|identity"):
        learned_feedback.observe_checkpoint(path, _write(path, receipt))
    assert samples == constructions == []


@pytest.mark.parametrize("problem", ["candidate_bytes", "state_identity", "configuration", "mapped_transport"])
def test_candidate_state_configuration_and_inline_contract_guards_remain(tmp_path, monkeypatch, problem):
    _, receipt, path, samples, constructions = _case(tmp_path, monkeypatch,
        schema="v7" if problem == "mapped_transport" else "v8")
    if problem == "candidate_bytes":
        receipt["candidate"]["sha256"] = "0" * 64
    elif problem == "state_identity":
        receipt["candidate_state_identity"]["digest"] = "0" * 64
    elif problem == "configuration":
        receipt["effective_autoencoder_config"]["compute_device"] = "cpu"
    with pytest.raises(ValueError):
        learned_feedback.observe_checkpoint(path, _write(path, receipt))
    assert samples == []
    assert len(constructions) == (1 if problem == "configuration" else 0)


def test_helper_change_during_input_verification_fails_before_model(tmp_path, monkeypatch):
    _, receipt, path, samples, constructions = _case(tmp_path, monkeypatch)
    verify = training_cycle_inputs.verify_cycle_inputs

    def changed(*args, **kwargs):
        result = verify(*args, **kwargs)
        monkeypatch.setattr(training_cycle_inputs, "__file__", learned_feedback.__file__)
        return result

    monkeypatch.setattr(training_cycle_inputs, "verify_cycle_inputs", changed)
    with pytest.raises(ValueError, match="input helper changed"):
        learned_feedback.observe_checkpoint(path, _write(path, receipt))
    assert samples == constructions == []


def test_helper_change_during_observation_fails_final_guard(tmp_path, monkeypatch):
    _, receipt, path, samples, constructions = _case(tmp_path, monkeypatch)
    guidance = learned_feedback.compact_guidance

    def changed(*args, **kwargs):
        result = guidance(*args, **kwargs)
        monkeypatch.setattr(training_cycle_inputs, "__file__", learned_feedback.__file__)
        return result

    monkeypatch.setattr(learned_feedback, "compact_guidance", changed)
    with pytest.raises(ValueError, match="input helper changed"):
        learned_feedback.observe_checkpoint(path, _write(path, receipt))
    assert len(constructions) == 1 and samples
