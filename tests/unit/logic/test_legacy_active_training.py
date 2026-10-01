"""The opt-in scheduler preserves old updates and fails closed on late work."""
from copy import deepcopy
from dataclasses import replace
import math

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import active_training as active
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic_view_reuse import (
    ViewReuseCachedLinguisticAutoencoder as Model,
    load_training_checkpoint,
)


def _fixture():
    model = Model(compute_device="cpu", feature_family_logit_scale=1.0)
    training = [model.build_sample(title="fixture", section="train", text="The agency shall submit reports.")]
    tuning = [model.build_sample(title="fixture", section="tune", text="The agency shall submit notices.")]
    return model, training, tuning


def _options(**extra):
    return dict(epochs=1, learning_rate=.01, max_seconds=30, max_line_search_attempts=1,
                growth_factor=1.0, **extra)


def test_direct_family_proposal_matches_frozen_accepted_state_and_preserves_linguistic_ir():
    model, training, tuning = _fixture()
    baseline = Model(state=deepcopy(model.state), compute_device="cpu", feature_family_logit_scale=1.0)
    observations = [model.linguistic_observation(row) for row in training + tuning]
    expected = baseline.train_generalizable_projection(training, validation_samples=tuning,
        epochs=1, learning_rate=.01, max_seconds=30, max_line_search_attempts=1,
        projection_max_update_families=3, projection_update_backend="python_sparse_batch",
        legal_ir_bridge_names=(), legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    report = active.train_active_family_features(model, training, validation_samples=tuning, **_options())
    assert expected["accepted_epochs"] == report["accepted_epochs"] == 1
    assert expected["epoch_reports"][0]["selected_update"] == "family_logits"
    assert model.state.to_dict() == baseline.state.to_dict()
    assert model.state.state_identity() == baseline.state.state_identity()
    assert report["epoch_reports"][0]["update_norms"]["nonzero_update"]
    assert report["after"]["cross_entropy_loss"] < report["before"]["cross_entropy_loss"]
    assert observations == [model.linguistic_observation(row) for row in training + tuning]
    assert not model.state.family_logits and not model.state.decoded_embeddings
    assert model.formula_checkpoint is None
    for field in active._FALSE:
        assert report[field] is False


def test_original_cap_one_cannot_reach_family_head_on_fresh_model():
    model, training, tuning = _fixture()
    before = model.state.to_dict()
    result = model.train_generalizable_projection(training, validation_samples=tuning,
        epochs=1, learning_rate=.01, max_seconds=30, max_line_search_attempts=1,
        projection_max_update_families=1, projection_update_backend="python_sparse_batch",
        legal_ir_bridge_names=(), legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1)
    assert result["candidate_update_order"] == ["legal_ir_view_global_logits"]
    assert result["accepted_epochs"] == 0
    assert model.state.to_dict() == before


def test_rate_growth_applies_only_to_next_cycle_and_has_bound():
    model, training, tuning = _fixture()
    result = active.train_active_family_features(model, training, validation_samples=tuning,
        epochs=3, learning_rate=.01, growth_factor=2.0, max_learning_rate=.03, max_seconds=30)
    assert result["accepted_epochs"] == 3
    assert [row["learning_rate"] for row in result["epoch_reports"]] == [.01, .02, .03]
    assert result["next_learning_rate"] == .03


def test_rejected_candidates_restore_weights_and_state_identity(monkeypatch):
    model, training, tuning = _fixture()
    before, identity = deepcopy(model.state.to_dict()), model.state.state_identity()
    baseline = model.evaluate(tuning, **active._EVALUATE)
    calls = 0
    def observations(_model, _rows):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return baseline
        return replace(baseline, cross_entropy_loss=baseline.cross_entropy_loss + 1,
                       cross_entropy_excess_loss=baseline.cross_entropy_excess_loss + 1)
    monkeypatch.setattr(active, "_evaluation", observations)
    result = active.train_active_family_features(model, training, validation_samples=tuning,
        epochs=2, learning_rate=.02, max_line_search_attempts=2, max_seconds=30)
    assert result["accepted_epochs"] == 0 and result["proposal_count"] == 2
    assert [row["learning_rate"] for row in result["epoch_reports"]] == [.02, .01]
    assert result["next_learning_rate"] == .005
    assert result["stopped_reason"] == "line_search_exhausted"
    assert model.state.to_dict() == before
    assert model.state.state_identity() == identity
    assert model.state._active_state_transaction is None


def test_nonfinite_candidate_and_evaluation_exceptions_roll_back(monkeypatch):
    model, training, tuning = _fixture()
    before, identity = deepcopy(model.state.to_dict()), model.state.state_identity()
    original = model._apply_projection_update_batch
    def corrupt(*args, **kwargs):
        report = original(*args, **kwargs)
        report["finite"] = False
        return report
    monkeypatch.setattr(model, "_apply_projection_update_batch", corrupt)
    with pytest.raises(ValueError, match="nonfinite"):
        active.train_active_family_features(model, training, validation_samples=tuning, **_options())
    assert model.state.to_dict() == before and model.state.state_identity() == identity
    monkeypatch.setattr(model, "_apply_projection_update_batch", original)
    evaluation = active._evaluation
    count = 0
    def fail(model, rows):
        nonlocal count
        count += 1
        if count == 3:
            raise RuntimeError("evaluation failed")
        return evaluation(model, rows)
    monkeypatch.setattr(active, "_evaluation", fail)
    with pytest.raises(RuntimeError, match="evaluation failed"):
        active.train_active_family_features(model, training, validation_samples=tuning, **_options())
    assert model.state.to_dict() == before and model.state.state_identity() == identity
    assert model.state._active_state_transaction is None


@pytest.mark.parametrize("late_phase", ["setup", "proposal", "evaluation"])
def test_deadline_includes_setup_and_rejects_late_candidate(monkeypatch, late_phase):
    model, training, tuning = _fixture()
    before, identity = deepcopy(model.state.to_dict()), model.state.state_identity()
    clock = [0.0]
    monkeypatch.setattr(active.time, "monotonic", lambda: clock[0])
    evaluate = active._evaluation
    count = 0
    def timed_evaluate(owner, rows):
        nonlocal count
        count += 1
        result = evaluate(owner, rows)
        if (late_phase == "setup" and count == 1) or (late_phase == "evaluation" and count == 3):
            clock[0] = 31.0
        return result
    monkeypatch.setattr(active, "_evaluation", timed_evaluate)
    update = model._apply_projection_update_batch
    def timed_update(*args, **kwargs):
        result = update(*args, **kwargs)
        if late_phase == "proposal":
            clock[0] = 31.0
        return result
    monkeypatch.setattr(model, "_apply_projection_update_batch", timed_update)
    result = active.train_active_family_features(model, training, validation_samples=tuning, **_options())
    assert result["accepted_epochs"] == 0
    assert result["stopped_reason"] == "deadline_" + {"setup": "during_setup", "proposal": "after_proposal",
                                                    "evaluation": "after_evaluation"}[late_phase]
    assert model.state.to_dict() == before and model.state.state_identity() == identity
    assert model.state._active_state_transaction is None


def test_source_or_input_drift_before_commit_rolls_back(monkeypatch):
    model, training, tuning = _fixture()
    before = deepcopy(model.state.to_dict())
    evaluation = active._evaluation
    calls = 0
    def drift(owner, rows):
        nonlocal calls
        calls += 1
        result = evaluation(owner, rows)
        if calls == 3:
            tuning[0].parser_trace["changed"] = True
        return result
    monkeypatch.setattr(active, "_evaluation", drift)
    with pytest.raises(ValueError, match="inputs changed"):
        active.train_active_family_features(model, training, validation_samples=tuning, **_options())
    assert model.state.to_dict() == before
    assert model.state._active_state_transaction is None


def test_source_change_since_import_rejected_before_setup(monkeypatch):
    model, training, tuning = _fixture()
    before = deepcopy(model.state.to_dict())
    monkeypatch.setattr(active, "_source_identity", lambda: (0, 0, 0, 0, 0))
    monkeypatch.setattr(active, "_evaluation", lambda *args: pytest.fail("stale producer evaluated samples"))
    with pytest.raises(ValueError, match="changed since import"):
        active.train_active_family_features(model, training, validation_samples=tuning, **_options())
    assert model.state.to_dict() == before


def test_disjoint_sources_and_bounded_settings_required_before_mutation():
    model, training, tuning = _fixture()
    before = deepcopy(model.state.to_dict())
    for options in ({"epochs": 0}, {"max_seconds": 0}, {"max_seconds": math.nan},
                    {"max_line_search_attempts": 0}, {"learning_rate": 2},
                    {"growth_factor": 3}, {"shrink_factor": 1}):
        with pytest.raises(ValueError):
            active.train_active_family_features(model, training, validation_samples=tuning, **options)
    with pytest.raises(ValueError, match="disjoint"):
        active.train_active_family_features(model, training, validation_samples=training)
    with pytest.raises(ValueError, match="explicit preserved"):
        active.train_active_family_features(object(), training, validation_samples=tuning)
    assert model.state.to_dict() == before


def test_checkpoint_resume_uses_explicit_next_rate_and_preserves_original_format(tmp_path):
    model, training, tuning = _fixture()
    uninterrupted = Model(state=deepcopy(model.state), compute_device="cpu", feature_family_logit_scale=1.0)
    whole = active.train_active_family_features(uninterrupted, training, validation_samples=tuning,
        epochs=3, learning_rate=.01, max_seconds=30, growth_factor=1.5)
    first = active.train_active_family_features(model, training, validation_samples=tuning,
        epochs=1, learning_rate=.01, max_seconds=30, growth_factor=1.5)
    destination = tmp_path / "bundle"
    model.save_training_checkpoint(destination)
    left = load_training_checkpoint(destination, profile="cached")
    right = load_training_checkpoint(destination, profile="cached")
    options = dict(epochs=2, learning_rate=first["next_learning_rate"], max_seconds=30)
    a = active.train_active_family_features(left, training, validation_samples=tuning, **options)
    b = active.train_active_family_features(right, training, validation_samples=tuning, **options)
    assert a["accepted_epochs"] == b["accepted_epochs"] == 2
    assert a["next_learning_rate"] == b["next_learning_rate"]
    assert left.state.to_dict() == right.state.to_dict()
    assert left.state.state_identity() == right.state.state_identity()
    assert a["after"] == b["after"]
    assert left.state.to_dict() == uninterrupted.state.to_dict()
    assert a["after"] == whole["after"]
    assert a["next_learning_rate"] == whole["next_learning_rate"]
    assert left.linguistic_observation(tuning[0]) == model.linguistic_observation(tuning[0])
