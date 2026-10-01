"""Prepared scheduling preserves strict legacy updates and completed resumes."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import active_training as active
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import feature_training_session as reference
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import prepared_feature_training as module
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_view_reuse import ViewReuseCachedLinguisticAutoencoder as Model


def fixture(cls=module.PreparedFeatureTrainingSession, **kwargs):
    model = Model(compute_device="cpu", feature_family_logit_scale=1.0)
    training = [model.build_sample(title="fixture", section="training", text="The agency shall submit reports.")]
    tuning = [model.build_sample(title="fixture", section="tuning", text="The board shall submit notices.")]
    return cls(model, training, validation_samples=tuning, proposal_budget=12, **kwargs), training, tuning


def restore(receipt, training, tuning):
    return module.load_training_session(receipt["path"], expected_sha256=receipt["sha256"],
                                        samples=training, validation_samples=tuning)


def test_twelve_proposals_exact_states_metrics_rates_with_fewer_evaluations(monkeypatch):
    original, training, tuning = fixture(reference.FeatureTrainingSession)
    prepared, _, _ = fixture()
    calls = []
    evaluate = active._evaluation
    def counted(model, rows):
        calls.append(len(rows))
        return evaluate(model, rows)
    monkeypatch.setattr(active, "_evaluation", counted)
    expected = original.advance(max_proposals=12, max_seconds=60)
    original_calls = len(calls)
    calls.clear()
    actual = prepared.advance(max_proposals=12, max_seconds=60)
    assert expected["accepted_updates"] == actual["accepted_updates"] == 12
    assert original_calls == 36 and len(calls) == 14
    for key in ("proposal_reports", "before", "after", "state", "stopped_reason"):
        assert actual[key] == expected[key]
    assert prepared.model.state.to_dict() == original.model.state.to_dict()
    assert actual["after"] == prepared.model.evaluate(tuning, **active._EVALUATE).to_dict()
    for flag in reference._FALSE:
        assert actual[flag] is False


def test_split_calls_and_persisted_resume_match_uninterrupted(tmp_path):
    whole, training, tuning = fixture()
    split, _, _ = fixture()
    observations = [whole.model.linguistic_observation(row) for row in training+tuning]
    expected = whole.advance(max_proposals=12, max_seconds=60)
    first = split.advance(max_proposals=5, max_seconds=60)
    saved = split.save(tmp_path / "generation")
    resumed = restore(saved, training, tuning)
    assert resumed.state == split.state
    second = resumed.advance(max_proposals=7, max_seconds=60)
    assert first["proposal_reports"]+second["proposal_reports"] == expected["proposal_reports"]
    assert second["after"] == expected["after"]
    assert resumed.state == whole.state
    assert resumed.model.state.to_dict() == whole.model.state.to_dict()
    assert [resumed.model.linguistic_observation(row) for row in training+tuning] == observations
    assert resumed.advance(max_proposals=1)["proposal_count"] == 0
    assert not resumed.model.state.family_logits and not resumed.model.state.decoded_embeddings
    assert resumed.model.formula_checkpoint is None


def test_rejections_shrink_match_reference_and_resume(tmp_path, monkeypatch):
    original, training, tuning = fixture(reference.FeatureTrainingSession, max_consecutive_rejections=3)
    prepared, _, _ = fixture(max_consecutive_rejections=3)
    identity = prepared.model.state.state_identity()
    # Reject every speculative tuning evaluation by recognizing the actual
    # active sparse transaction, independent of the differing evaluation count.
    evaluate = active._evaluation
    def rejected(model, rows):
        value = evaluate(model, rows)
        return (replace(value, cross_entropy_loss=value.cross_entropy_loss+1,
                        cross_entropy_excess_loss=value.cross_entropy_excess_loss+1)
                if model.state._active_state_transaction is not None else value)
    monkeypatch.setattr(active, "_evaluation", rejected)
    expected = original.advance(max_proposals=12)
    first = prepared.advance(max_proposals=1)
    saved = prepared.save(tmp_path / "rejected")
    resumed = restore(saved, training, tuning)
    second = resumed.advance(max_proposals=12)
    assert first["proposal_reports"]+second["proposal_reports"] == expected["proposal_reports"]
    assert resumed.state == original.state
    assert resumed.model.state.state_identity() == identity
    assert second["stopped_reason"] == "plateau"


@pytest.mark.parametrize("phase", ["setup", "proposal", "evaluation"])
def test_deadline_rolls_back_preserves_lr_and_spends_only_attempted_work(tmp_path, monkeypatch, phase):
    prepared, training, tuning = fixture()
    before = prepared.model.state.state_identity()
    clock = [0.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    evaluate, update = active._evaluation, prepared.model._apply_projection_update_batch
    calls = 0
    def measured(model, rows):
        nonlocal calls
        calls += 1
        value = evaluate(model, rows)
        if (phase == "setup" and calls == 1) or (phase == "evaluation" and calls == 3):
            clock[0] = 31.0
        return value
    def timed_update(*args, **kwargs):
        value = update(*args, **kwargs)
        if phase == "proposal":
            clock[0] = 31.0
        return value
    monkeypatch.setattr(active, "_evaluation", measured)
    monkeypatch.setattr(prepared.model, "_apply_projection_update_batch", timed_update)
    result = prepared.advance(max_proposals=12, max_seconds=30)
    assert result["stopped_reason"] == "deadline"
    progress = prepared.state["progress"]
    assert progress["accepted_updates"] == progress["consecutive_rejections"] == 0
    assert progress["next_learning_rate"] == .01
    assert progress["proposals_used"] == (0 if phase == "setup" else 1)
    assert prepared.model.state.state_identity() == before
    assert restore(prepared.save(tmp_path / phase), training, tuning).state == prepared.state


@pytest.mark.parametrize("drift", ["source", "input"])
def test_precommit_drift_rolls_back_and_poisoned_session_cannot_save(monkeypatch, tmp_path, drift):
    prepared, training, tuning = fixture()
    identity = prepared.model.state.state_identity()
    original = prepared.model._apply_projection_update_batch
    def mutate(*args, **kwargs):
        value = original(*args, **kwargs)
        if drift == "source":
            monkeypatch.setattr(module, "_source_identity", lambda: ())
        else:
            tuning[0].parser_trace["changed"] = True
        return value
    monkeypatch.setattr(prepared.model, "_apply_projection_update_batch", mutate)
    with pytest.raises(ValueError, match="source changed|input or model configuration changed"):
        prepared.advance(max_proposals=1)
    assert prepared.model.state.state_identity() == identity
    assert prepared._failed
    with pytest.raises(ValueError):
        prepared.save(tmp_path / "poisoned")


def test_exception_after_first_acceptance_cannot_publish_ambiguous_progress(tmp_path, monkeypatch):
    prepared, training, tuning = fixture()
    saved = prepared.save(tmp_path / "prior")
    initial = prepared.model.state.state_identity()
    original = prepared.model._apply_projection_update_batch
    calls = 0
    def failed(*args, **kwargs):
        nonlocal calls
        calls += 1
        value = original(*args, **kwargs)
        if calls == 2:
            raise RuntimeError("failed after speculative update")
        return value
    monkeypatch.setattr(prepared.model, "_apply_projection_update_batch", failed)
    with pytest.raises(RuntimeError, match="speculative"):
        prepared.advance(max_proposals=2)
    assert prepared.model.state.state_identity() != initial
    assert prepared.model.state._active_state_transaction is None
    with pytest.raises(ValueError, match="requires reload"):
        prepared.advance(max_proposals=1)
    with pytest.raises(ValueError, match="requires reload"):
        prepared.save(tmp_path / "ambiguous")
    assert restore(saved, training, tuning).model.state.state_identity() == initial


def test_publication_exclusive_failure_preserves_old_checkpoint(tmp_path, monkeypatch):
    prepared, training, tuning = fixture()
    saved = prepared.save(tmp_path / "old")
    initial = (tmp_path / "old/prepared-session.json").read_bytes()
    with pytest.raises(FileExistsError):
        prepared.save(tmp_path / "old")
    link = module.os.link
    def fail_final(source, target):
        if str(target).endswith("prepared-session.json"):
            raise OSError("final marker failure")
        return link(source, target)
    monkeypatch.setattr(module.os, "link", fail_final)
    with pytest.raises(OSError, match="marker failure"):
        prepared.save(tmp_path / "incomplete")
    assert not (tmp_path / "incomplete/prepared-session.json").exists()
    assert (tmp_path / "old/prepared-session.json").read_bytes() == initial
    assert restore(saved, training, tuning).state == prepared.state


def test_prepared_manifest_source_and_digest_and_input_binding(tmp_path):
    prepared, training, tuning = fixture()
    saved = prepared.save(tmp_path / "saved")
    with pytest.raises(ValueError, match="digest differs"):
        restore(dict(saved, sha256="0"*64), training, tuning)
    with pytest.raises(ValueError, match="input/model binding differs"):
        restore(saved, training, [replace(tuning[0], citation="changed")])
    path = tmp_path / "saved/prepared-session.json"
    data = json.loads(path.read_text())
    data["runtime_sources"]["prepared_feature_training"] = "0"*64
    payload = reference._raw(data)
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="source/schema/authority"):
        restore(dict(saved, sha256=hashlib.sha256(payload).hexdigest()), training, tuning)


def test_external_weight_mutation_rejected_before_any_proposal():
    prepared, _, _ = fixture()
    prepared.model.state.feature_family_logits["external"] = {"deontic": .5}
    with pytest.raises(ValueError, match="outside feature session"):
        prepared.advance(max_proposals=1)
