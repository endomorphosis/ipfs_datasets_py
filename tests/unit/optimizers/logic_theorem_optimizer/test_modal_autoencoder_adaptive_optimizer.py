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
