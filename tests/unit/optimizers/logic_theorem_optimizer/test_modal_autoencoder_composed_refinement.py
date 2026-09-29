"""Controlled optimizer-policy tests; no native semantic or admission claims."""
from types import SimpleNamespace
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import (
    encode_patch,
    replay_patch,
)


def _controlled(monkeypatch, *, validation="same", training="improve", clock_stage=None):
    state = ma.ModalAutoencoderTrainingState(
        legal_ir_view_logits={"ir": 0.0}, feature_embedding_weights={"embedding": [0.0]},
    )
    model = ma.AdaptiveModalAutoencoder(state=state, compute_device="python")
    training_rows = [SimpleNamespace(sample_id="train", normalized_text="train text", embedding_vector=[1.0])]
    validation_rows = [SimpleNamespace(sample_id="validation", normalized_text="validation text", embedding_vector=[-1.0])]
    clock = {"now": 0.0}
    calls = {"updates": [], "evaluations": []}
    monkeypatch.setattr(ma.time, "time", lambda: clock["now"])
    monkeypatch.setattr(model, "_select_hard_examples_for_projection", lambda rows, **_: list(rows))
    monkeypatch.setattr(state, "copy", lambda: pytest.fail("whole-state copy"))

    def evaluate(rows, **kwargs):
        ids = [row.sample_id for row in rows]
        calls["evaluations"].append((ids, dict(kwargs)))
        assert kwargs["use_sample_memory"] is False
        ir = model.state.legal_ir_view_logits["ir"]
        embedding = model.state.feature_embedding_weights["embedding"][0]
        is_validation = ids == ["validation"]
        ce = 1.0 - 0.1 * ir
        cosine = 1.0
        reconstruction = 0.0 if is_validation else 1.0
        if is_validation and embedding:
            if validation == "regress":
                cosine, reconstruction = 0.2, 0.4
            elif validation == "reduce_gain":
                ce += 0.01
            elif validation == "nonfinite":
                reconstruction = float("nan")
            elif validation == "backtrack" and embedding > 0.10:
                cosine, reconstruction = 0.2, 0.4
            if clock_stage == "validation":
                clock["now"] = 61.0
        if not is_validation:
            if embedding and training == "improve":
                reconstruction -= embedding
            elif embedding and training == "nonfinite":
                reconstruction = float("nan")
            elif embedding and training == "nonfinite_cosine":
                reconstruction -= embedding
                cosine = float("nan")
            if embedding and clock_stage == "training":
                clock["now"] = 61.0
            if ir and not embedding and clock_stage == "baseline":
                clock["now"] = 61.0
        return ma.AutoencoderEvaluation(len(rows), cosine, 1.0-cosine, reconstruction, ce, 0.0, 0.0, {},
                                        cross_entropy_excess_loss=ce)

    def update(rows, *, update_targets, learning_rate, **kwargs):
        ids = [row.sample_id for row in rows]
        assert ids == ["train"]  # Validation rows must never be gradient inputs.
        calls["updates"].append((tuple(update_targets), float(learning_rate), ids))
        if update_targets == ("decoded_embedding",):
            # Every trial must restart from the same selected patch.
            assert model.state.legal_ir_view_logits["ir"] == 1.0
            assert model.state.feature_embedding_weights["embedding"][0] == 0.0
            model.state.feature_embedding_weights["embedding"][0] = float(learning_rate)
            if clock_stage == "update" or (
                clock_stage == "second_update"
                and sum(targets == ("decoded_embedding",) for targets, _, _ in calls["updates"]) == 2
            ):
                clock["now"] = 61.0
        else:
            model.state.legal_ir_view_logits["ir"] = 1.0
        return {key: {} for key in ("gradient_norms_by_family", "gradient_norms_by_head",
                                    "head_family_gradient_norms", "head_family_update_norms",
                                    "update_norms_by_family", "update_norms_by_head")}

    monkeypatch.setattr(model, "evaluate", evaluate)
    monkeypatch.setattr(model, "_apply_projection_update_batch", update)
    return model, training_rows, validation_rows, calls


def _train(model, rows, validation, **kwargs):
    options = dict(validation_samples=validation, legal_ir_bridge_names=("deontic_norms",),
                   legal_ir_evaluate_provers=False, epochs=1, max_seconds=60,
                   projection_update_backend="python_sparse_batch",
                   projection_max_update_families=1, max_line_search_attempts=1)
    options.update(kwargs)
    return model.train_generalizable_projection(rows, **options)


def test_opt_in_refinement_preserves_ir_gain_and_trains_embedding_with_exact_sparse_replay(monkeypatch):
    model, rows, validation, calls = _controlled(monkeypatch)
    before = model.state.to_dict()
    patches = []

    def sink(patch, context):
        patches.append(encode_patch(patch, base_state_identity=context["base_state_identity"],
                                   result_state_identity=context["result_state_identity"],
                                   base_version_id="fixture", sequence=len(patches)))

    report = _train(model, rows, validation, projection_max_composed_refinement_attempts=3,
                    accepted_patch_sink=sink)
    assert report["accepted_epochs"] == len(patches) == 1
    epoch = report["epoch_reports"][0]
    assert epoch["selected_update"] == "legal_ir_view_global_logits+decoded_embedding_refinement:1"
    assert epoch["acceptance_source"] == "strict_composed_refinement"
    assert epoch["training_reconstruction_delta"] == pytest.approx(0.175)
    assert model.state.legal_ir_view_logits["ir"] == 1.0
    assert model.state.feature_embedding_weights["embedding"] == [0.175]
    assert [call[1] for call in calls["updates"][1:]] == [0.175, 0.0875, 0.04375]
    restored = ma.ModalAutoencoderTrainingState.from_dict(before)
    replay_patch(restored, patches[0], expected_base_version_id="fixture", expected_sequence=0)
    assert restored.to_json() == model.state.to_json()
    assert restored.state_revision == model.state.state_revision
    assert model.state._active_state_transaction is None
    for ids, kwargs in calls["evaluations"]:
        if ids == ["validation"]:
            assert kwargs["legal_ir_bridge_names"] == ("deontic_norms",)
        assert kwargs["legal_ir_evaluate_provers"] is False


def test_default_and_explicit_zero_make_identical_calls_state_and_reports(monkeypatch):
    left, rows, validation, left_calls = _controlled(monkeypatch)
    left_report = _train(left, rows, validation)
    right, rows, validation, right_calls = _controlled(monkeypatch)
    right_report = _train(right, rows, validation, projection_max_composed_refinement_attempts=0)
    assert left.state.to_json() == right.state.to_json()
    assert left_calls == right_calls
    assert left_report == right_report
    assert len(left_calls["updates"]) == 1
    assert len(left_calls["evaluations"]) == 3
    assert not left_report["projection_composed_refinement"]["enabled"]


@pytest.mark.parametrize("validation,training,reason", [
    ("regress", "improve", "validation_guardrail_regression"),
    ("reduce_gain", "improve", "validation_objective_not_preserved"),
    ("nonfinite", "improve", "nonfinite_validation_metric"),
    ("same", "same", "no_training_reconstruction_improvement"),
    ("same", "nonfinite", "no_training_reconstruction_improvement"),
    ("same", "nonfinite_cosine", "nonfinite_training_metric"),
])
def test_failed_refinements_leave_original_winner_untouched(monkeypatch, validation, training, reason):
    model, rows, heldout, calls = _controlled(monkeypatch, validation=validation, training=training)
    report = _train(model, rows, heldout, projection_max_composed_refinement_attempts=3)
    assert report["epoch_reports"][0]["selected_update"] == "legal_ir_view_global_logits"
    attempts = report["epoch_reports"][0]["composed_refinement_reports"]
    assert len(attempts) == 3
    assert all(not attempt["accepted"] and reason in attempt["rejection_reasons"] for attempt in attempts)
    json.dumps(report, allow_nan=False)
    assert model.state.legal_ir_view_logits["ir"] == 1.0
    assert model.state.feature_embedding_weights["embedding"] == [0.0]
    assert model.state._active_state_transaction is None


def test_backtracking_keeps_winner_and_selects_first_safe_refinement(monkeypatch):
    model, rows, validation, calls = _controlled(monkeypatch, validation="backtrack")
    report = _train(model, rows, validation, projection_max_composed_refinement_attempts=3)
    assert report["epoch_reports"][0]["selected_update"].endswith("refinement:2")
    assert model.state.feature_embedding_weights["embedding"] == [0.0875]
    assert len(calls["updates"]) == 4


@pytest.mark.parametrize("stage", ["baseline", "update", "validation", "training"])
def test_refinement_deadline_preserves_only_completed_winner(monkeypatch, stage):
    model, rows, validation, calls = _controlled(monkeypatch, clock_stage=stage)
    report = _train(model, rows, validation, projection_max_composed_refinement_attempts=3)
    assert report["stopped_reason"] == "projection_timeout"
    assert report["epoch_reports"][0]["selected_update"] == "legal_ir_view_global_logits"
    assert model.state.feature_embedding_weights["embedding"] == [0.0]
    assert model.state._active_state_transaction is None
    assert len(calls["updates"]) <= 2


@pytest.mark.parametrize("value", [-1, 4, 1.5, True, None])
def test_invalid_refinement_budget_rejected_before_model_calls(monkeypatch, value):
    model, rows, validation, calls = _controlled(monkeypatch)
    with pytest.raises(ValueError, match="integer from 0 to 3"):
        _train(model, rows, validation, projection_max_composed_refinement_attempts=value)
    assert calls == {"evaluations": [], "updates": []}


@pytest.mark.parametrize("seconds", [None, 0, -1, float("inf"), float("nan")])
def test_opt_in_requires_real_deadline(monkeypatch, seconds):
    model, rows, validation, calls = _controlled(monkeypatch)
    with pytest.raises(ValueError, match="finite positive"):
        _train(model, rows, validation, max_seconds=seconds, projection_max_composed_refinement_attempts=1)
    assert calls == {"evaluations": [], "updates": []}


@pytest.mark.parametrize("mode", ["empty", "same_id", "same_text"])
def test_opt_in_requires_disjoint_validation(monkeypatch, mode):
    model, rows, validation, calls = _controlled(monkeypatch)
    if mode == "empty":
        validation = []
    elif mode == "same_id":
        validation[0].sample_id = rows[0].sample_id
    else:
        validation[0].normalized_text = rows[0].normalized_text
    with pytest.raises(ValueError, match="disjoint validation"):
        _train(model, rows, validation, projection_max_composed_refinement_attempts=1)
    assert calls == {"evaluations": [], "updates": []}


def test_trial_exception_rolls_back_every_uncommitted_weight_and_emits_no_patch(monkeypatch):
    model, rows, validation, calls = _controlled(monkeypatch)
    before = model.state.to_json()
    original_update = model._apply_projection_update_batch

    def failed_update(*args, **kwargs):
        result = original_update(*args, **kwargs)
        if kwargs["update_targets"] == ("decoded_embedding",):
            raise RuntimeError("interrupted refinement")
        return result

    monkeypatch.setattr(model, "_apply_projection_update_batch", failed_update)
    with pytest.raises(RuntimeError, match="interrupted refinement"):
        _train(model, rows, validation, projection_max_composed_refinement_attempts=3,
               accepted_patch_sink=lambda *_: pytest.fail("partial patch published"))
    assert model.state.to_json() == before
    assert model.state._active_state_transaction is None


def test_deadband_only_winner_is_never_refined(monkeypatch):
    from dataclasses import replace
    model, rows, validation, calls = _controlled(monkeypatch)
    original_evaluate = model.evaluate

    def deadband_evaluate(*args, **kwargs):
        result = original_evaluate(*args, **kwargs)
        ce = 1.0 + 0.0001 * model.state.legal_ir_view_logits["ir"]
        return replace(result, cross_entropy_loss=ce, cross_entropy_excess_loss=ce)

    monkeypatch.setattr(model, "evaluate", deadband_evaluate)
    monkeypatch.setattr(ma, "_projection_deadband_decision", lambda *a, **k: {"enforced_accepted": True})
    report = _train(model, rows, validation, projection_max_composed_refinement_attempts=3,
                    projection_deadband_mode="enforce")
    assert report["epoch_reports"][0]["acceptance_source"] == "deadband_enforced"
    assert not report["epoch_reports"][0]["strict_accepted"]
    assert len(calls["updates"]) == 1
    assert "composed_refinement_reports" not in report["epoch_reports"][0]


def test_later_refinement_deadline_retains_completed_refinement(monkeypatch):
    model, rows, validation, calls = _controlled(monkeypatch, clock_stage="second_update")
    report = _train(model, rows, validation, projection_max_composed_refinement_attempts=3)
    assert report["stopped_reason"] == "projection_timeout"
    assert report["epoch_reports"][0]["selected_update"].endswith("refinement:1")
    assert model.state.feature_embedding_weights["embedding"] == [0.175]
    assert len(calls["updates"]) == 3
    assert model.state._active_state_transaction is None


@pytest.mark.parametrize("l2", [0.1, -1.0, float("nan"), float("inf")])
def test_opt_in_rejects_unvalidated_l2_before_model_calls(monkeypatch, l2):
    model, rows, validation, calls = _controlled(monkeypatch)
    with pytest.raises(ValueError, match="zero l2_regularization"):
        _train(model, rows, validation, l2_regularization=l2, projection_max_composed_refinement_attempts=1)
    assert calls == {"evaluations": [], "updates": []}


@pytest.mark.parametrize("training", ["same", "nonfinite", "nonfinite_cosine"])
def test_training_screen_skips_ineligible_bridge_validation_without_inventing_metrics(monkeypatch, training):
    model, rows, validation, calls = _controlled(monkeypatch, training=training)
    report = _train(model, rows, validation, projection_max_composed_refinement_attempts=3)
    attempts = report["epoch_reports"][0]["composed_refinement_reports"]
    assert len(attempts) == 3
    # Initial validation and the ordinary IR candidate still run all bridges.
    # Each optional nudge is screened using training rows before paying for more.
    assert [ids for ids, _ in calls["evaluations"]] == [
        ["validation"], ["train"], ["validation"], ["train"],
        ["train"], ["train"], ["train"],
    ]
    for attempt in attempts:
        assert attempt["training_evaluated"] is True
        assert attempt["evaluation_order"] == "training_before_validation"
        assert attempt["holdout_evaluated"] is False
        assert attempt["objective_delta"] is None
        assert attempt["validation_evaluation_skipped_reason"] == "training_screen_rejected"
        assert "validation_after" not in attempt
        assert "cross_entropy_delta" not in attempt
        assert "validation_objective_delta_required" in attempt
        assert not attempt["accepted"]
    for ids, kwargs in calls["evaluations"][3:]:
        assert ids == ["train"]
        assert kwargs["legal_ir_bridge_names"] == ()
        assert kwargs["legal_ir_targets"] is None
    json.dumps(report, allow_nan=False)


def test_training_improvement_still_requires_bridge_validation_for_every_trial(monkeypatch):
    model, rows, validation, calls = _controlled(monkeypatch)
    report = _train(model, rows, validation, projection_max_composed_refinement_attempts=3)
    attempts = [candidate for candidate in report["epoch_reports"][0]["candidate_reports"]
                if candidate.get("composed_refinement")]
    assert [ids for ids, _ in calls["evaluations"]] == [
        ["validation"], ["train"], ["validation"], ["train"],
        ["train"], ["validation"], ["train"], ["validation"],
        ["train"], ["validation"],
    ]
    assert all(attempt["holdout_evaluated"] and attempt["training_evaluated"] for attempt in attempts)
    assert all("validation_evaluation_skipped_reason" not in attempt for attempt in attempts)
    assert all(attempt["strict_accepted"] for attempt in attempts)
    for ids, kwargs in calls["evaluations"][4:]:
        assert kwargs["legal_ir_bridge_names"] == (("deontic_norms",) if ids == ["validation"] else ())
        assert kwargs["use_sample_memory"] is False


@pytest.mark.parametrize("stage", ["train", "validation"])
def test_screen_or_validation_exception_rolls_back_without_publishing_partial_state(monkeypatch, stage):
    model, rows, validation, calls = _controlled(monkeypatch)
    before = model.state.to_json()
    evaluate = model.evaluate

    def interrupted(rows, **kwargs):
        if rows[0].sample_id == stage and model.state.feature_embedding_weights["embedding"][0]:
            raise RuntimeError("interrupted refinement evaluation")
        return evaluate(rows, **kwargs)

    monkeypatch.setattr(model, "evaluate", interrupted)
    with pytest.raises(RuntimeError, match="interrupted refinement evaluation"):
        _train(model, rows, validation, projection_max_composed_refinement_attempts=3,
               accepted_patch_sink=lambda *_: pytest.fail("partial patch published"))
    assert model.state.to_json() == before
    assert model.state._active_state_transaction is None


@pytest.mark.parametrize("skipped_delta", [None, 0.0, 100.0])
def test_skipped_validation_cannot_outrank_a_measured_negative_objective(skipped_delta):
    measured = {"update": "measured", "accepted": False, "objective_delta": -0.25,
                "holdout_evaluated": True}
    skipped = {"update": "skipped", "accepted": False, "objective_delta": skipped_delta,
               "holdout_evaluated": False}
    summary = ma._projection_rejection_summary([{"candidate_reports": [measured, skipped]}])
    assert summary["attempted_count"] == summary["rejected_attempt_count"] == 2
    assert summary["best_rejected_attempt"]["update"] == "measured"
    assert summary["best_rejected_attempt"]["objective_delta"] == -0.25
    assert ma._projection_rejection_summary([
        {"candidate_reports": [skipped]},
    ])["best_rejected_attempt"] == {}
    # Missing evaluation flags in historical reports retain their interpretation.
    del measured["holdout_evaluated"]
    assert ma._projection_rejection_summary([
        {"candidate_reports": [measured]},
    ])["best_rejected_attempt"]["objective_delta"] == -0.25
