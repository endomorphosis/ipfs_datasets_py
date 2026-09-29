"""Controlled search and sparse-state tests; these make no native/proof claim."""
from dataclasses import replace
import json
import math
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_adaptive_optimizer as policy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import encode_patch, replay_patch


def _fixture(monkeypatch, *, loss=None, update=None, baseline_invalid=None):
    state = ma.ModalAutoencoderTrainingState(legal_ir_view_logits={"x": 0.0})
    model = ma.AdaptiveModalAutoencoder(state=state, compute_device="python")
    train = [SimpleNamespace(sample_id="train", normalized_text="training text", embedding_vector=[1.0])]
    validation = [SimpleNamespace(sample_id="validation", normalized_text="validation text", embedding_vector=[-1.0])]
    calls = {"rates": [], "evaluations": [], "updates": [], "now": 0.0}
    monkeypatch.setattr(ma.time, "time", lambda: calls["now"])
    monkeypatch.setattr(ma.time, "perf_counter", lambda: calls["now"])
    monkeypatch.setattr(model, "_select_hard_examples_for_projection", lambda rows, **kw: list(rows))
    monkeypatch.setattr(state, "copy", lambda: pytest.fail("whole-state copy is forbidden"))

    def evaluate(rows, **kwargs):
        assert kwargs["use_sample_memory"] is False
        ids = [row.sample_id for row in rows]
        calls["evaluations"].append(ids)
        x = state.legal_ir_view_logits["x"]
        value = loss(x, calls) if loss else (1.0 - x) ** 2
        result = ma.AutoencoderEvaluation(len(rows), 1.0, 0.0, value, 1.0, 0.0, 0.0, {},
                                         cross_entropy_excess_loss=1.0)
        if baseline_invalid is not None and not calls["updates"]:
            result = replace(result, legal_ir_losses={"legal_ir_multiview_total_loss": baseline_invalid})
        calls["now"] += 0.01
        return result

    def nudge(rows, *, update_targets, learning_rate, **kwargs):
        assert [row.sample_id for row in rows] == ["train"]
        calls["rates"].append(learning_rate)
        calls["updates"].append(tuple(update_targets))
        if update:
            update(state, learning_rate, calls)
        else:
            state.legal_ir_view_logits["x"] += learning_rate
        calls["now"] += 0.01
        return {key: {} for key in ("gradient_norms_by_family", "gradient_norms_by_head",
                "head_family_gradient_norms", "head_family_update_norms", "update_norms_by_family", "update_norms_by_head")}

    monkeypatch.setattr(model, "evaluate", evaluate)
    monkeypatch.setattr(model, "_apply_projection_update_batch", nudge)
    return model, train, validation, calls


def _run(fixture, **kwargs):
    model, train, validation, calls = fixture
    options = dict(validation_samples=validation, legal_ir_bridge_names=("deontic_norms",),
                   legal_ir_evaluate_provers=False, epochs=3, max_seconds=60, max_line_search_attempts=2,
                   projection_max_update_families=1, projection_update_backend="python_sparse_batch",
                   projection_optimizer_mode="guarded_adaptive")
    options.update(kwargs)
    return model.train_generalizable_projection(train, **options)


def _attempts(report):
    return [attempt for epoch in report["epoch_reports"] for candidate in epoch["candidate_reports"]
            for attempt in candidate.get("attempt_reports", [candidate])]


def test_fixed_explicit_default_parity_and_honest_epoch_timing(monkeypatch):
    left = _fixture(monkeypatch)
    first = left[0].train_generalizable_projection(
        left[1], validation_samples=left[2], legal_ir_bridge_names=("deontic_norms",),
        legal_ir_evaluate_provers=False, epochs=3, max_seconds=60, max_line_search_attempts=2,
        projection_max_update_families=1, projection_update_backend="python_sparse_batch",
    )
    right = _fixture(monkeypatch)
    second = _run(right, projection_optimizer_mode="fixed", projection_momentum=0.0)
    assert first == second
    assert left[0].state.to_json() == right[0].state.to_json()
    assert "projection_optimizer" not in first
    assert first["epoch_reports"][0]["candidate_holdout_evaluation_count"] == 2
    epoch = first["epoch_reports"][0]
    assert epoch["objective_before"] - epoch["objective_after"] == pytest.approx(epoch["objective_delta"])
    assert epoch["cumulative_training_elapsed_seconds"] > epoch["epoch_elapsed_seconds"] > 0


def test_adaptive_warmstart_growth_ends_head_on_first_guarded_positive(monkeypatch):
    fixture = _fixture(monkeypatch)
    report = _run(fixture)
    assert fixture[3]["rates"] == pytest.approx([0.175, 0.21875, 0.2734375])
    assert report["accepted_epochs"] == 3
    assert all(epoch["adaptive_phase_counts"] == {"guarded_positive": 1, "warm_start": 1}
               for epoch in report["epoch_reports"])
    assert [epoch["candidate_holdout_evaluation_count"] for epoch in report["epoch_reports"]] == [1, 1, 1]
    assert report["projection_optimizer_scope"] == policy.OPTIMIZER_SCOPE
    assert report["optimizer_history_persisted"] is False
    assert not report["projection_optimizer"]["global_minimum_claimed"]
    assert all(attempt["adaptive_optimizer"]["autograd_gradient"] is False for attempt in _attempts(report))


def test_growth_never_reports_rate_above_actual_clamp(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: max(0.0, 100.0 - x))
    report = _run(fixture, epochs=12, learning_rate=1.0)
    assert max(fixture[3]["rates"]) == 1.0
    assert report["projection_optimizer"]["learning_rates"]["legal_ir_view_global_logits"] == 1.0


def test_rejected_trial_backoff_then_accepted_rate_warmstart(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: (0.06 - x) ** 2)
    report = _run(fixture, epochs=1)
    assert fixture[3]["rates"] == [0.175, 0.0875]
    assert report["accepted_epochs"] == 1
    assert report["projection_optimizer"]["learning_rates"]["legal_ir_view_global_logits"] == pytest.approx(0.109375)
    assert [a["adaptive_optimizer"]["phase"] for a in _attempts(report)] == ["warm_start", "backoff"]


def test_plateau_has_one_bounded_recovery_and_no_convergence_claim(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: 1.0)
    before = fixture[0].state.to_json()
    report = _run(fixture, epochs=10)
    assert report["stopped_reason"] == "search_stalled"
    assert len(report["epoch_reports"]) == 2
    assert fixture[3]["rates"] == pytest.approx([0.175, 0.0875, 0.04375, 0.021875])
    assert report["epoch_reports"][0]["adaptive_phase"] == "plateau_recovery"
    assert fixture[0].state.to_json() == before


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), None, "bad"])
def test_raw_invalid_candidate_metrics_never_commit_or_gain_objective(monkeypatch, invalid):
    fixture = _fixture(monkeypatch)
    model = fixture[0]
    original = model.evaluate
    def invalid_evaluate(rows, **kwargs):
        result = original(rows, **kwargs)
        return replace(result, legal_ir_losses={"legal_ir_multiview_total_loss":
                                               invalid if model.state.legal_ir_view_logits["x"] else 0.5})
    monkeypatch.setattr(model, "evaluate", invalid_evaluate)
    before = model.state.to_json()
    report = _run(fixture, projection_optimizer_mode="fixed", epochs=1)
    assert report["accepted_epochs"] == 0
    assert model.state.to_json() == before
    assert report["rejection_summary"]["best_rejected_attempt"] == {}
    assert all(attempt["objective_delta"] is None and attempt["finite_validation"] is False
               for attempt in _attempts(report))
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("mode", ["fixed", "guarded_adaptive"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_baseline_rejects_before_weight_updates(monkeypatch, mode, invalid):
    fixture = _fixture(monkeypatch, baseline_invalid=invalid)
    before = fixture[0].state.to_json()
    with pytest.raises(ValueError, match="nonfinite projection baseline"):
        _run(fixture, projection_optimizer_mode=mode)
    assert not fixture[3]["updates"]
    assert fixture[0].state.to_json() == before


def test_invalid_later_candidate_preserves_earlier_guarded_winner(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: float("nan") if 0.0 < x < 0.1 else (1-x)**2)
    report = _run(fixture, projection_optimizer_mode="fixed", epochs=1)
    assert report["accepted_epochs"] == 1
    assert fixture[0].state.legal_ir_view_logits["x"] == 0.175
    assert _attempts(report)[1]["finite_validation"] is False


def test_timeout_during_later_head_preserves_earlier_winner(monkeypatch):
    def update(state, rate, calls):
        state.legal_ir_view_logits["x"] += rate
        if len(calls["updates"]) == 2:
            calls["now"] = 61.0
    fixture = _fixture(monkeypatch, update=update)
    report = _run(fixture, projection_max_update_families=2)
    assert report["stopped_reason"] == "projection_timeout"
    assert report["accepted_epochs"] == 1
    assert fixture[0].state.legal_ir_view_logits["x"] == 0.175
    assert report["epoch_reports"][0]["candidate_holdout_evaluation_count"] == 1
    assert _attempts(report)[1]["validation_evaluation_skipped_reason"] == "projection_timeout"
    assert fixture[0].state._active_state_transaction is None


def test_momentum_carries_only_selected_patch_and_sparse_replay_matches(monkeypatch):
    fixture = _fixture(monkeypatch)
    before = fixture[0].state.to_dict()
    encoded = []
    def sink(patch, context):
        encoded.append(encode_patch(patch, base_state_identity=context["base_state_identity"],
                                   result_state_identity=context["result_state_identity"],
                                   base_version_id="fixture", sequence=len(encoded)))
    report = _run(fixture, projection_momentum=0.5, accepted_patch_sink=sink)
    attempts = _attempts(report)
    assert [attempt["adaptive_optimizer"]["momentum_applied"] for attempt in attempts] == [False, True, True]
    assert attempts[1]["adaptive_optimizer"]["momentum_carry_norm"] == pytest.approx(0.0875)
    restored = ma.ModalAutoencoderTrainingState.from_dict(before)
    for index, patch in enumerate(encoded):
        replay_patch(restored, patch, expected_base_version_id="fixture", expected_sequence=index)
    assert restored.to_json() == fixture[0].state.to_json()
    assert restored.state_revision == fixture[0].state.state_revision


def test_momentum_rejection_plain_fallback_same_rate_inside_budget(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: (0.3-x)**2)
    report = _run(fixture, projection_momentum=0.5, epochs=2)
    attempts = _attempts(report)
    assert [a["adaptive_optimizer"]["phase"] for a in attempts] == ["warm_start", "momentum", "plain_fallback"]
    assert [a["accepted"] for a in attempts] == [True, False, True]
    assert fixture[3]["rates"] == pytest.approx([0.175, 0.21875, 0.21875])
    assert fixture[0].state.legal_ir_view_logits["x"] == pytest.approx(0.39375)
    assert report["projection_optimizer"]["momentum_reset_reasons"]["candidate_rejected"] == 1


def test_second_training_call_resets_optimizer_history(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: 100.0-x)
    first = _run(fixture, projection_momentum=0.5, epochs=2)
    second = _run(fixture, projection_momentum=0.5, epochs=1)
    assert _attempts(first)[1]["adaptive_optimizer"]["momentum_applied"]
    assert not _attempts(second)[0]["adaptive_optimizer"]["momentum_applied"]
    assert _attempts(second)[0]["effective_learning_rate"] == 0.175


def test_candidate_evaluation_exception_rolls_back_sparse_state(monkeypatch):
    fixture = _fixture(monkeypatch)
    before = fixture[0].state.to_json()
    original = fixture[0].evaluate
    def fail(rows, **kwargs):
        if fixture[0].state.legal_ir_view_logits["x"]:
            raise RuntimeError("controlled failure")
        return original(rows, **kwargs)
    monkeypatch.setattr(fixture[0], "evaluate", fail)
    with pytest.raises(RuntimeError, match="controlled failure"):
        _run(fixture, projection_momentum=0.5)
    assert fixture[0].state.to_json() == before
    assert fixture[0].state._active_state_transaction is None


@pytest.mark.parametrize("options", [
    {"projection_optimizer_mode": "other"}, {"projection_optimizer_mode": []},
    {"projection_momentum": -0.1}, {"projection_momentum": 1.0},
    {"projection_momentum": float("nan")}, {"projection_momentum": float("inf")},
    {"projection_momentum": True}, {"projection_momentum": False},
    {"projection_optimizer_mode": "fixed", "projection_momentum": 0.5},
    {"projection_momentum": 0.5, "max_line_search_attempts": 1},
    {"max_line_search_attempts": None}, {"max_line_search_attempts": 11},
    {"max_line_search_attempts": True}, {"epochs": 33}, {"epochs": 0},
    {"max_seconds": None}, {"max_seconds": 0}, {"max_seconds": 301},
    {"max_seconds": float("nan")}, {"max_seconds": float("inf")},
    {"learning_rate": 0}, {"learning_rate": 5e-324}, {"learning_rate": 1.1}, {"learning_rate": float("nan")},
    {"l2_regularization": 0.1}, {"projection_deadband_mode": "shadow"},
    {"projection_prescreen_mode": "enforce"}, {"validation_samples": []},
])
def test_adaptive_invalid_contracts_fail_before_evaluation(monkeypatch, options):
    fixture = _fixture(monkeypatch)
    with pytest.raises(ValueError):
        _run(fixture, **options)
    assert fixture[3]["evaluations"] == []


@pytest.mark.parametrize("attribute", ["sample_id", "normalized_text"])
def test_adaptive_rejects_overlapping_validation(monkeypatch, attribute):
    fixture = _fixture(monkeypatch)
    setattr(fixture[2][0], attribute, getattr(fixture[1][0], attribute))
    with pytest.raises(ValueError, match="disjoint"):
        _run(fixture)


def _commit_delta(state, component, key, value):
    transaction = state.transaction(label="controlled-commit").begin()
    getattr(state, component)[key] = value
    return transaction.commit()


def test_tiny_learning_rate_backoff_never_increases_seed():
    controller = policy.GuardedAdaptiveProjection(1e-30, {"head": 0.5}, 0.5)
    assert controller.backoff("head", 5e-31) <= 5e-31


def test_momentum_skips_inserted_rows_coordinates_sample_memory_and_metadata():
    state = ma.ModalAutoencoderTrainingState(feature_embedding_weights={"old": [0.0]},
                                            feature_family_logits={"old": {"existing": 0.0}},
                                            decoded_embeddings={"memory": [0.0]})
    transaction = state.transaction(label="controlled").begin()
    state.feature_embedding_weights["new"] = [10.0]
    state.feature_embedding_weights["old"][0] = 1.0
    state.feature_family_logits["old"]["new"] = 10.0
    state.feature_family_logits["old"]["existing"] = 1.0
    state.decoded_embeddings["memory"][0] = 100.0
    state.proof_auxiliary_head_logits["proof"] = {"score": 100.0}
    patch = transaction.commit()
    controller = policy.GuardedAdaptiveProjection(0.35, {"head": 0.5}, 0.5)
    controller.committed("head", patch)
    assert len(controller.history) == 2
    assert {key[0] for key in controller.history} == {"feature_embedding_weights", "feature_family_logits"}
    assert all(key[1] == "old" and "new" not in key[2] for key in controller.history)


@pytest.mark.parametrize("direction,reason", [(-0.1, "nonpositive_direction_alignment"), (0.0, "no_current_direction_intersection")])
def test_momentum_restarts_on_reversal_or_flat_step(direction, reason):
    state = ma.ModalAutoencoderTrainingState(legal_ir_view_logits={"x": 0.0})
    patch = _commit_delta(state, "legal_ir_view_logits", "x", 1.0)
    controller = policy.GuardedAdaptiveProjection(0.35, {"head": 0.5}, 0.5)
    controller.committed("head", patch)
    transaction = state.transaction(label="trial").begin()
    state.legal_ir_view_logits["x"] += direction
    report = controller.prepare(state, transaction.capture_patch(), head="head", allow_momentum=True, logit_clip=24.0)
    assert report["momentum_restart_reason"] == reason
    assert not controller.history
    transaction.rollback()
    assert state.legal_ir_view_logits["x"] == 1.0


def test_momentum_carry_is_bounded_by_current_fresh_direction_and_clipping():
    state = ma.ModalAutoencoderTrainingState(legal_ir_view_logits={"x": 0.0})
    patch = _commit_delta(state, "legal_ir_view_logits", "x", 23.9)
    controller = policy.GuardedAdaptiveProjection(0.35, {"head": 0.5}, 0.9)
    controller.committed("head", patch)
    transaction = state.transaction(label="trial").begin()
    state.legal_ir_view_logits["x"] += 0.075
    report = controller.prepare(state, transaction.capture_patch(), head="head", allow_momentum=True, logit_clip=24.0)
    assert report["momentum_carry_norm"] <= 0.9 * 0.075
    assert state.legal_ir_view_logits["x"] == 24.0
    transaction.rollback()
    assert state.legal_ir_view_logits["x"] == 23.9


def test_momentum_stale_postimage_is_not_reused():
    state = ma.ModalAutoencoderTrainingState(legal_ir_view_logits={"x": 0.0})
    patch = _commit_delta(state, "legal_ir_view_logits", "x", 1.0)
    controller = policy.GuardedAdaptiveProjection(0.35, {"head": 0.5}, 0.5)
    controller.committed("head", patch)
    _commit_delta(state, "legal_ir_view_logits", "x", 2.0)
    transaction = state.transaction(label="trial").begin()
    state.legal_ir_view_logits["x"] += 0.1
    report = controller.prepare(state, transaction.capture_patch(), head="head", allow_momentum=True, logit_clip=24)
    assert report["momentum_restart_reason"] == "no_current_direction_intersection"
    assert state.legal_ir_view_logits["x"] == 2.1
    transaction.rollback()


def test_history_memory_is_bounded_deterministically(monkeypatch):
    monkeypatch.setattr(policy, "MAX_MOMENTUM_COORDINATES", 4)
    state = ma.ModalAutoencoderTrainingState(feature_embedding_weights={"x": [0.0]*10})
    patch = _commit_delta(state, "feature_embedding_weights", "x", [1.0]*10)
    controller = policy.GuardedAdaptiveProjection(0.35, {"head": 0.5}, 0.5)
    controller.committed("head", patch)
    assert len(controller.history) == 4
    assert [key[2] for key in controller.history] == [(0,), (1,), (2,), (3,)]
    assert controller.truncated_histories == 1


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), None])
def test_composed_refinement_rejects_invalid_family_metric_before_objective(monkeypatch, invalid):
    fixture = _fixture(monkeypatch)
    model, _train, _validation, _calls = fixture
    model.state.feature_embedding_weights["embedding"] = [0.0]
    original_evaluate = model.evaluate
    original_update = model._apply_projection_update_batch
    def evaluate(rows, **kwargs):
        result = original_evaluate(rows, **kwargs)
        if model.state.feature_embedding_weights["embedding"][0]:
            if rows[0].sample_id == "validation":
                return replace(result, legal_ir_view_family_metrics={"deontic": {"ir_cosine_similarity": invalid}})
            return replace(result, reconstruction_loss=result.reconstruction_loss - 0.1)
        return result
    def update(rows, *, update_targets, **kwargs):
        if update_targets == ("decoded_embedding",):
            model.state.feature_embedding_weights["embedding"][0] = 0.1
            return {key: {} for key in ("gradient_norms_by_family", "gradient_norms_by_head",
                    "head_family_gradient_norms", "head_family_update_norms", "update_norms_by_family", "update_norms_by_head")}
        return original_update(rows, update_targets=update_targets, **kwargs)
    monkeypatch.setattr(model, "evaluate", evaluate)
    monkeypatch.setattr(model, "_apply_projection_update_batch", update)
    report = _run(fixture, epochs=1, projection_max_composed_refinement_attempts=1)
    assert report["accepted_epochs"] == 1
    assert report["epoch_reports"][0]["selected_update"] == "legal_ir_view_global_logits"
    trial = report["epoch_reports"][0]["composed_refinement_reports"][0]
    assert trial["finite_validation"] is False
    assert trial["objective_delta"] is None
    assert "nonfinite_validation_metric" in trial["rejection_reasons"]
    assert model.state.feature_embedding_weights["embedding"] == [0.0]
    json.dumps(report, allow_nan=False)


def test_productive_adaptive_explores_larger_rate_and_keeps_best_guarded_trial(monkeypatch):
    fixture = _fixture(monkeypatch)
    report = _run(fixture, epochs=1, projection_optimizer_mode="productive_adaptive")
    assert fixture[3]["rates"] == [0.175, 0.35]
    assert fixture[0].state.legal_ir_view_logits["x"] == 0.35
    assert report["accepted_epochs"] == 1
    attempts = _attempts(report)
    assert [trial["adaptive_optimizer"]["phase"] for trial in attempts] == ["warm_start", "expand_after_positive"]
    assert all(trial["strict_accepted"] for trial in attempts)
    assert report["epoch_reports"][0]["objective_delta"] == attempts[1]["objective_delta"]
    assert report["projection_optimizer"]["learning_rates"]["legal_ir_view_global_logits"] == 0.4375
    assert report["projection_optimizer_mode"] == "productive_adaptive"
    assert attempts[0]["productive_search"]["tried_learning_rates"] == [0.175, 0.35]


def test_productive_exact_flat_metrics_allow_larger_probe_to_escape_plateau(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: 1.0 if x <= 0.2 else 0.5)
    report = _run(fixture, epochs=1, projection_optimizer_mode="productive_adaptive")
    assert report["accepted_epochs"] == 1
    assert fixture[3]["rates"] == [0.175, 0.35]
    attempts = _attempts(report)
    assert attempts[0]["adaptive_optimizer"]["exact_flat_guard_metrics"] is True
    assert attempts[1]["adaptive_optimizer"]["phase"] == "expand_after_exact_flat"
    assert report["after"]["reconstruction_loss"] == 0.5


@pytest.mark.parametrize("field", ["family_metric", "flat_loss", "entropy", "target_count"])
def test_productive_zero_objective_with_changed_raw_guard_metrics_is_not_exact_flat(monkeypatch, field):
    fixture = _fixture(monkeypatch, loss=lambda x, _: 1.0)
    model = fixture[0]
    original = model.evaluate
    def evaluate(rows, **kwargs):
        result = original(rows, **kwargs)
        x = model.state.legal_ir_view_logits["x"]
        if field == "family_metric":
            return replace(result, legal_ir_view_family_metrics={"deontic": {"ir_cosine_similarity": x}})
        if field == "flat_loss":
            # An unselected diagnostic still prevents the exact-flat label.
            return replace(result, legal_ir_losses={"diagnostic": x})
        if field == "entropy":
            return replace(result, cross_entropy_entropy_loss=x)
        return replace(result, legal_ir_target_count=int(x > 0.0))
    monkeypatch.setattr(model, "evaluate", evaluate)
    report = _run(fixture, epochs=1, projection_optimizer_mode="productive_adaptive")
    assert fixture[3]["rates"] == [0.175, 0.0875]
    assert all(trial["adaptive_optimizer"]["exact_flat_guard_metrics"] is False for trial in _attempts(report))
    assert report["accepted_epochs"] == 0


@pytest.mark.parametrize("failure", ["regression", "nonfinite", "timeout"])
def test_productive_larger_trial_failure_preserves_earlier_winner(monkeypatch, failure):
    def loss(x, calls):
        if x > 0.2:
            return float("nan") if failure == "nonfinite" else 5.0
        return (0.1-x)**2
    def update(state, rate, calls):
        state.legal_ir_view_logits["x"] += rate
        if failure == "timeout" and len(calls["updates"]) == 2:
            calls["now"] = 61.0
    fixture = _fixture(monkeypatch, loss=loss, update=update)
    before = fixture[0].state.to_dict()
    patches = []
    def sink(patch, context):
        patches.append(encode_patch(patch, base_state_identity=context["base_state_identity"],
                                    result_state_identity=context["result_state_identity"],
                                    base_version_id="fixture", sequence=len(patches)))
    report = _run(fixture, epochs=1, projection_optimizer_mode="productive_adaptive", accepted_patch_sink=sink)
    assert report["accepted_epochs"] == 1
    assert fixture[0].state.legal_ir_view_logits["x"] == 0.175
    assert len(patches) == 1
    restored = ma.ModalAutoencoderTrainingState.from_dict(before)
    replay_patch(restored, patches[0], expected_base_version_id="fixture", expected_sequence=0)
    assert restored.to_json() == fixture[0].state.to_json()
    assert fixture[0].state._active_state_transaction is None
    assert _attempts(report)[0]["strict_accepted"] is True
    assert _attempts(report)[1]["accepted"] is False
    assert report["projection_optimizer"]["learning_rates"]["legal_ir_view_global_logits"] == 0.21875
    if failure == "timeout":
        assert report["stopped_reason"] == "projection_timeout"
        assert report["epoch_reports"][0]["candidate_holdout_evaluation_count"] == 1
    else:
        assert report["epoch_reports"][0]["candidate_holdout_evaluation_count"] == 2
    json.dumps(report, allow_nan=False)


def test_productive_equal_positive_gains_keep_earlier_rate(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: 1.0 if x == 0.0 else 0.5)
    report = _run(fixture, epochs=1, projection_optimizer_mode="productive_adaptive")
    assert fixture[3]["rates"] == [0.175, 0.35]
    assert fixture[0].state.legal_ir_view_logits["x"] == 0.175
    assert report["projection_optimizer"]["learning_rates"]["legal_ir_view_global_logits"] == 0.21875


def test_productive_growth_only_for_selected_head_unselected_warms_at_measured_rate(monkeypatch):
    fixture = _fixture(monkeypatch)
    report = _run(fixture, epochs=1, projection_optimizer_mode="productive_adaptive", projection_max_update_families=2)
    # Both mocked heads have the same effect; stable ordering selects the first.
    assert report["epoch_reports"][0]["selected_update"] == "legal_ir_view_global_logits"
    assert report["projection_optimizer"]["learning_rates"]["legal_ir_view_global_logits"] == 0.4375
    assert report["projection_optimizer"]["learning_rates"]["legal_ir_view_logits"] == 0.35
    assert report["epoch_reports"][0]["adaptive_phase_counts"]["selected_head_rate_growth"] == 1
    assert report["projection_optimizer"]["next_epoch_growth_scope"] == "selected_committed_head_only"


def test_productive_deduplicates_clamped_plain_rates_without_extra_evaluation(monkeypatch):
    fixture = _fixture(monkeypatch)
    report = _run(fixture, epochs=1, learning_rate=1.0, max_line_search_attempts=5,
                  projection_optimizer_mode="productive_adaptive")
    assert fixture[3]["rates"] == [0.5, 1.0]
    assert report["epoch_reports"][0]["candidate_holdout_evaluation_count"] == 2
    assert _attempts(report)[0]["productive_search"]["duplicate_trials_skipped"] == 1
    assert report["projection_optimizer"]["phase_counts"]["clamped_expansion_skipped"] == 1
    assert fixture[0].state.legal_ir_view_logits["x"] == 1.0


def test_productive_momentum_rejection_prioritizes_same_rate_plain_fallback(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: (0.6-x)**2)
    report = _run(fixture, epochs=2, projection_optimizer_mode="productive_adaptive", projection_momentum=0.5)
    assert fixture[3]["rates"] == [0.175, 0.35, 0.4375, 0.4375]
    attempts = _attempts(report)
    assert [a["adaptive_optimizer"]["phase"] for a in attempts] == [
        "warm_start", "expand_after_positive", "momentum", "plain_fallback"]
    assert [a["accepted"] for a in attempts] == [True, True, False, True]
    assert report["accepted_epochs"] == 2
    assert fixture[0].state.legal_ir_view_logits["x"] == pytest.approx(0.7875)
    assert report["projection_optimizer"]["momentum_reset_reasons"]["candidate_rejected"] == 1
    assert all(e["candidate_holdout_evaluation_count"] == 2 for e in report["epoch_reports"])


@pytest.mark.parametrize("momentum", [0.0, 0.5])
def test_productive_requires_two_attempts_before_evaluation(monkeypatch, momentum):
    fixture = _fixture(monkeypatch)
    with pytest.raises(ValueError, match="productive_adaptive requires at least two"):
        _run(fixture, max_line_search_attempts=1, projection_optimizer_mode="productive_adaptive", projection_momentum=momentum)
    assert not fixture[3]["evaluations"]


def test_productive_top_delta_history_keeps_dominant_global_updates(monkeypatch):
    monkeypatch.setattr(policy, "MAX_MOMENTUM_COORDINATES", 4)
    state = ma.ModalAutoencoderTrainingState(feature_embedding_weights={"flood": [0.0]*10},
                                            legal_ir_view_logits={"global": 0.0, "dominant": 0.0})
    transaction = state.transaction(label="controlled").begin()
    state.feature_embedding_weights["flood"] = [0.01]*10
    state.legal_ir_view_logits["global"] = 1.0
    state.legal_ir_view_logits["dominant"] = 2.0
    patch = transaction.commit()
    old = policy.GuardedAdaptiveProjection(0.35, {"head": 0.5}, 0.5)
    new = policy.GuardedAdaptiveProjection(0.35, {"head": 0.5}, 0.5, mode="productive_adaptive")
    old.committed("head", patch)
    new.committed("head", patch)
    assert {key[0] for key in old.history} == {"feature_embedding_weights"}
    assert {key[1] for key in new.history if key[0] == "legal_ir_view_logits"} == {"global", "dominant"}
    assert len(new.history) == 4 and new.truncated_histories == 1
    report = new.report()["projection_optimizer"]
    assert report["momentum_history_eligible_coordinate_count"] == 12
    assert report["momentum_history_parameter_delta_norm_coverage"] > 0.999
    assert report["momentum_history_components"] == {"feature_embedding_weights": 2, "legal_ir_view_logits": 2}
    trial = state.transaction(label="trial").begin()
    state.feature_embedding_weights["flood"] = [0.02]*10
    state.legal_ir_view_logits["global"] += 0.1
    state.legal_ir_view_logits["dominant"] += 0.2
    carry = new.prepare(state, trial.capture_patch(), head="head", allow_momentum=True, logit_clip=24.0)
    assert carry["momentum_applied"]
    assert carry["momentum_fresh_intersection_norm_coverage"] > 0.99
    assert carry["momentum_carry_norm"] <= 0.5 * carry["momentum_fresh_intersection_norm"] + 1e-15
    trial.rollback()


def test_productive_top_delta_ties_are_independent_of_mapping_insertion_order(monkeypatch):
    monkeypatch.setattr(policy, "MAX_MOMENTUM_COORDINATES", 2)
    histories = []
    for keys in (("z", "a", "m"), ("m", "z", "a")):
        state = ma.ModalAutoencoderTrainingState(feature_family_logits={"row": dict.fromkeys(keys, 0.0)})
        patch = _commit_delta(state, "feature_family_logits", "row", dict.fromkeys(keys, 1.0))
        controller = policy.GuardedAdaptiveProjection(0.35, {"head": 0.5}, 0.5, mode="productive_adaptive")
        controller.committed("head", patch)
        histories.append(list(controller.history))
    assert histories[0] == histories[1]
    assert [key[2] for key in histories[0]] == [("a",), ("m",)]


def test_productive_history_excludes_unknown_initialization_and_memory(monkeypatch):
    monkeypatch.setattr(policy, "MAX_MOMENTUM_COORDINATES", 3)
    state = ma.ModalAutoencoderTrainingState(feature_family_logits={"old": {"known": 0.0}},
                                            decoded_embeddings={"memory": [0.0]})
    transaction = state.transaction(label="controlled").begin()
    state.feature_family_logits["old"]["known"] = 0.01
    state.feature_family_logits["old"]["inserted"] = 1000.0
    state.feature_family_logits["new"] = {"inserted": 1000.0}
    state.decoded_embeddings["memory"][0] = 1000.0
    state.proof_auxiliary_head_logits["proof"] = {"score": 1000.0}
    patch = transaction.commit()
    controller = policy.GuardedAdaptiveProjection(0.35, {"head": 0.5}, 0.5, mode="productive_adaptive")
    controller.committed("head", patch)
    assert list(controller.history) == [("feature_family_logits", "old", ("known",))]
    assert controller.report()["projection_optimizer"]["momentum_history_eligible_coordinate_count"] == 1


@pytest.mark.parametrize("direction,stale,expected", [
    (-0.1, False, "nonpositive_direction_alignment"),
    (0.0, False, "no_current_direction_intersection"),
    (0.1, True, "no_current_direction_intersection"),
])
def test_productive_top_delta_keeps_restart_and_stale_state_guards(direction, stale, expected):
    state = ma.ModalAutoencoderTrainingState(legal_ir_view_logits={"x": 0.0})
    patch = _commit_delta(state, "legal_ir_view_logits", "x", 1.0)
    controller = policy.GuardedAdaptiveProjection(0.35, {"head": 0.5}, 0.5, mode="productive_adaptive")
    controller.committed("head", patch)
    if stale:
        _commit_delta(state, "legal_ir_view_logits", "x", 2.0)
    before = state.to_json()
    transaction = state.transaction(label="trial").begin()
    state.legal_ir_view_logits["x"] += direction
    report = controller.prepare(state, transaction.capture_patch(), head="head", allow_momentum=True, logit_clip=24.0)
    assert report["momentum_restart_reason"] == expected
    assert not controller.history
    assert controller.report()["projection_optimizer"]["momentum_history_eligible_coordinate_count"] == 0
    transaction.rollback()
    assert state.to_json() == before


@pytest.mark.parametrize("outcome", ["carried_rejected", "carried_best", "plain_best_both_positive"])
def test_productive_cap_compares_carried_and_plain_once_each_and_retains_best(monkeypatch, outcome):
    if outcome == "carried_rejected":
        loss = lambda x, _: (1.6-x)**2
    elif outcome == "plain_best_both_positive":
        loss = lambda x, _: (2.1-x)**2
    else:
        loss = lambda x, _: 100.0-x
    fixture = _fixture(monkeypatch, loss=loss)
    report = _run(fixture, epochs=2, learning_rate=1.0, max_line_search_attempts=5,
                  projection_optimizer_mode="productive_adaptive", projection_momentum=0.5)
    second = report["epoch_reports"][1]["candidate_reports"][0]
    trials = second["attempt_reports"]
    assert len(trials) == 2
    assert trials[0]["adaptive_optimizer"]["phase"] == "momentum"
    assert trials[1]["accepted"] is True
    assert fixture[3]["rates"] == [0.5, 1.0, 1.0, 1.0]
    if outcome == "carried_rejected":
        assert trials[0]["accepted"] is False
        assert trials[1]["adaptive_optimizer"]["phase"] == "plain_fallback"
    else:
        assert trials[0]["accepted"] is True
        assert trials[1]["adaptive_optimizer"]["phase"] == "plain_at_rate_cap"
    expected = 2.5 if outcome == "carried_best" else 2.0
    assert fixture[0].state.legal_ir_view_logits["x"] == expected
    assert second["productive_search"]["duplicate_trials_skipped"] == 1
    assert report["epoch_reports"][1]["candidate_holdout_evaluation_count"] == len(trials)



def test_productive_flat_head_warms_at_largest_measured_rate_across_epochs(monkeypatch):
    def update(state, rate, calls):
        if calls["updates"][-1] == ("legal_ir_view_global_logits",):
            state.legal_ir_view_logits["flat"] += rate
        else:
            state.legal_ir_view_logits["x"] += rate
    fixture = _fixture(monkeypatch, loss=lambda x, _: 100.0-x, update=update)
    fixture[0].state.legal_ir_view_logits["flat"] = 0.0
    report = _run(fixture, epochs=3, projection_optimizer_mode="productive_adaptive", projection_max_update_families=2)
    flat_heads = [epoch["candidate_reports"][0] for epoch in report["epoch_reports"]]
    assert [head["productive_search"]["tried_learning_rates"] for head in flat_heads] == [
        [0.175, 0.35], [0.35, 0.7], [0.7, 1.0]]
    assert [head["productive_search"]["flat_warm_start_rate"] for head in flat_heads] == [0.35, 0.7, 1.0]
    assert all(head["productive_search"]["flat_warm_start_reason"] ==
               "all_completed_plain_trials_exact_finite_flat" for head in flat_heads)
    assert all(len(head["attempt_reports"]) <= 2 for epoch in report["epoch_reports"] for head in epoch["candidate_reports"])
    assert report["projection_optimizer"]["learning_rates"]["legal_ir_view_global_logits"] == 1.0
    assert report["accepted_epochs"] == 3


@pytest.mark.parametrize("failure", ["regression", "nonfinite", "timeout"])
def test_productive_mixed_flat_failure_does_not_reuse_flat_warm_start(monkeypatch, failure):
    def loss(x, calls):
        return (float("nan") if failure == "nonfinite" else 2.0) if x > 0.2 else 1.0
    def update(state, rate, calls):
        state.legal_ir_view_logits["x"] += rate
        if failure == "timeout" and len(calls["updates"]) == 2:
            calls["now"] = 61.0
    fixture = _fixture(monkeypatch, loss=loss, update=update)
    before = fixture[0].state.to_json()
    report = _run(fixture, epochs=1, projection_optimizer_mode="productive_adaptive")
    head = report["epoch_reports"][0]["candidate_reports"][0]
    assert head["productive_search"]["tried_learning_rates"] == [0.175, 0.35]
    assert head["productive_search"]["flat_warm_start_rate"] is None
    assert head["productive_search"]["flat_warm_start_reason"] is None
    assert report["projection_optimizer"]["learning_rates"]["legal_ir_view_global_logits"] == 0.175
    assert report["accepted_epochs"] == 0
    assert fixture[0].state.to_json() == before
    assert len(_attempts(report)) == 2
    json.dumps(report, allow_nan=False)



def test_productive_all_flat_epochs_continue_to_untried_rate_and_escape(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: 1.0 if x < 0.9 else 0.5)
    report = _run(fixture, epochs=3, projection_optimizer_mode="productive_adaptive")
    assert fixture[3]["rates"] == [0.175, 0.35, 0.35, 0.7, 0.7, 1.0]
    assert [epoch["accepted"] for epoch in report["epoch_reports"]] == [False, False, True]
    assert [epoch["adaptive_phase"] for epoch in report["epoch_reports"][:2]] == ["plateau_exploration", "plateau_exploration"]
    assert all(epoch["objective_before"] == epoch["objective_after"] for epoch in report["epoch_reports"][:2])
    assert fixture[0].state.legal_ir_view_logits["x"] == 1.0
    assert report["accepted_epochs"] == 1
    assert report["after"]["reconstruction_loss"] == 0.5
    assert report["epoch_reports"][1]["productive_flat_seed_advances"] == {
        "legal_ir_view_global_logits": {"before": 0.35, "after": 0.7}}


def test_productive_all_flat_stops_once_measured_rates_reach_cap(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: 1.0)
    before = fixture[0].state.to_json()
    report = _run(fixture, epochs=32, projection_optimizer_mode="productive_adaptive")
    assert fixture[3]["rates"] == [0.175, 0.35, 0.35, 0.7, 0.7, 1.0, 1.0]
    assert len(report["epoch_reports"]) == 4
    assert report["stopped_reason"] == "search_stalled"
    assert report["accepted_epochs"] == 0
    assert fixture[0].state.to_json() == before
    assert report["projection_optimizer"]["phase_counts"]["plateau_exploration"] == 2
    assert report["projection_optimizer"]["phase_counts"]["plateau_sweep"] == 2
    json.dumps(report, allow_nan=False)


def test_productive_flat_exploration_respects_requested_epoch_budget(monkeypatch):
    fixture = _fixture(monkeypatch, loss=lambda x, _: 1.0)
    report = _run(fixture, epochs=1, projection_optimizer_mode="productive_adaptive")
    assert len(_attempts(report)) == 2
    assert len(report["epoch_reports"]) == 1
    assert report["stopped_reason"] == "epoch_budget_exhausted"
    assert report["accepted_epochs"] == 0



def test_productive_fully_evaluated_flat_trial_past_deadline_cannot_warm_seed(monkeypatch):
    def loss(x, calls):
        if x > 0.2:
            calls["now"] = 61.0
        return 1.0
    fixture = _fixture(monkeypatch, loss=loss)
    report = _run(fixture, epochs=3, projection_optimizer_mode="productive_adaptive")
    assert report["stopped_reason"] == "projection_timeout"
    assert report["epoch_reports"][0]["candidate_holdout_evaluation_count"] == 2
    head = report["epoch_reports"][0]["candidate_reports"][0]
    assert head["productive_search"]["flat_warm_start_rate"] is None
    assert report["accepted_epochs"] == 0
