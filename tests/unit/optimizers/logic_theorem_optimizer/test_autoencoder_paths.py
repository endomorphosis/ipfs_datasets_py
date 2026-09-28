"""Inference and training are separate autoencoder calls."""
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paths import (
    AutoencoderExecutionError,
    INFERENCE_PATH,
    TRAINING_PATH,
    gated_evaluate,
    gated_projection_training,
    run_inference,
    run_training,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import AdaptiveModalAutoencoder


def _sample():
    return build_us_code_sample(
        title="5",
        section="1",
        text="The officer shall retain records.",
    )


def test_inference_does_not_train_or_commit_state(monkeypatch) -> None:
    model = AdaptiveModalAutoencoder()

    def fail_train(*_args, **_kwargs):
        raise AssertionError("inference called training")

    monkeypatch.setattr(model, "train_generalizable_projection", fail_train)
    result = run_inference(model, [_sample()])
    assert result["path"] == "inference"
    assert result["state_changed"] is False
    assert result["sample_count"] == 1
    assert result["admitted"] is False
    assert result["formalized"] is False


def test_training_does_not_require_an_inference_call(monkeypatch) -> None:
    model = AdaptiveModalAutoencoder()
    calls = {"evaluate": 0}

    real_evaluate = model.evaluate

    def counting_evaluate(*args, **kwargs):
        calls["evaluate"] += 1
        return real_evaluate(*args, **kwargs)

    monkeypatch.setattr(model, "evaluate", counting_evaluate)
    result = run_training(model, [_sample()])
    assert result["path"] == "training"
    assert result["admitted"] is False
    assert result["formalized"] is False
    assert "state_changed" in result
    # Holdout scoring inside the search is not a separate inference request.
    assert calls["evaluate"] >= 1


@pytest.mark.parametrize("route,mode", [
    (gated_evaluate, TRAINING_PATH), (gated_evaluate, "auto"),
    (gated_evaluate, None), (gated_evaluate, True),
    (gated_projection_training, INFERENCE_PATH), (gated_projection_training, "auto"),
    (gated_projection_training, None), (gated_projection_training, True),
])
def test_crossed_or_unknown_mode_fails_before_model_access(route, mode):
    class UntouchedModel:
        def __getattribute__(self, name):
            raise AssertionError("invalid route accessed model")
    with pytest.raises(AutoencoderExecutionError):
        route(UntouchedModel(), [], execution_mode=mode)


@pytest.mark.parametrize("kwargs", [
    {"legal_ir_evaluate_provers": True}, {"legal_ir_evaluate_provers": None},
    {"use_sample_memory": True}, {"use_sample_memory": None},
])
def test_inference_refuses_conflicting_policy_before_evaluation(kwargs):
    with pytest.raises(AutoencoderExecutionError, match="provers=False"):
        gated_evaluate(object(), [], execution_mode=INFERENCE_PATH, **kwargs)


@pytest.mark.parametrize("kwargs", [
    {"legal_ir_evaluate_provers": True}, {"legal_ir_evaluate_provers": None},
    {"projection_update_backend": "auto"}, {"projection_update_backend": "cuda_resident"},
])
def test_training_refuses_unqualified_backend_or_provers_before_model_call(kwargs):
    with pytest.raises(AutoencoderExecutionError):
        gated_projection_training(object(), [], execution_mode=TRAINING_PATH, **kwargs)


@pytest.mark.parametrize("name", ["epochs", "max_line_search_attempts", "projection_max_update_families", "legal_ir_parallel_workers"])
@pytest.mark.parametrize("value", [None, 0, -1, True, 1.5, float("inf")])
def test_training_refuses_missing_or_nonpositive_integer_bounds_before_model_access(name, value):
    with pytest.raises(AutoencoderExecutionError, match="positive integer"):
        gated_projection_training(object(), [], execution_mode=TRAINING_PATH, **{name: value})


@pytest.mark.parametrize("value", [None, 0, -1, True, float("inf"), float("nan")])
def test_training_refuses_unbounded_seconds_before_model_access(value):
    with pytest.raises(AutoencoderExecutionError, match="finite positive max_seconds"):
        gated_projection_training(object(), [], execution_mode=TRAINING_PATH, max_seconds=value)


def test_training_default_budget_and_explicit_memory_policy_are_bounded():
    calls = []
    def train(samples, *, use_sample_memory=True, **kwargs):
        calls.append({"use_sample_memory": use_sample_memory, **kwargs})
        return {}
    model = SimpleNamespace(train_generalizable_projection=train)
    gated_projection_training(model, [], execution_mode=TRAINING_PATH)
    assert calls[0]["use_sample_memory"] is False
    assert {key: calls[0][key] for key in ("epochs", "max_line_search_attempts", "max_seconds",
                                         "projection_max_update_families", "legal_ir_parallel_workers")} == {
        "epochs": 1, "max_line_search_attempts": 1, "max_seconds": 30.0,
        "projection_max_update_families": 1, "legal_ir_parallel_workers": 1}
    with pytest.raises(AutoencoderExecutionError, match="use_sample_memory=False"):
        gated_projection_training(object(), [], execution_mode=TRAINING_PATH, use_sample_memory=True)


@pytest.mark.parametrize("also_raises", [False, True])
def test_inference_mutation_is_detected_even_when_evaluator_raises(also_raises):
    model = AdaptiveModalAutoencoder()
    def changed(*args, **kwargs):
        model.state.feature_embedding_weights["changed"] = [1.0]
        if also_raises:
            raise ValueError("evaluation interrupted after mutation")
        return object()
    model.evaluate = changed
    with pytest.raises(RuntimeError, match="inference changed"):
        gated_evaluate(model, [], execution_mode=INFERENCE_PATH)


def test_native_evaluation_object_and_inference_telemetry_are_preserved(monkeypatch):
    model = AdaptiveModalAutoencoder()
    payload = {"embedding_cosine_similarity": .8, "cross_entropy_loss": .7,
               "reconstruction_loss": .1, "sample_count": 1, "decoded_embeddings": {"s": [1.]},
               "legal_ir_target_count": 1, "legal_ir_losses": {"ir": .2},
               "legal_ir_view_family_metrics": {"deontic": {"ir_cosine_similarity": .9}}}
    evaluation = SimpleNamespace(**payload, to_dict=lambda: dict(payload))
    calls = []
    def evaluate(samples, **kwargs):
        calls.append(kwargs)
        return evaluation
    model.evaluate = evaluate
    assert gated_evaluate(model, [], execution_mode=INFERENCE_PATH) is evaluation
    monkeypatch.setenv("IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "0")
    result = run_inference(model, [], legal_ir_bridge_names=("deontic_norms",), legal_ir_parallel_workers=2)
    for key, value in payload.items():
        assert result[key] == value
    assert result["bridge_names"] == ["deontic_norms"] and result["cache_enabled"] is False
    assert result["legal_ir_parallel_workers"] == 2
    assert result["training_executed"] is result["qualified"] is result["promotion_performed"] is False
    assert all(call["legal_ir_evaluate_provers"] is False and call["use_sample_memory"] is False for call in calls)


def test_training_preserves_report_stop_reason_and_exact_budgets():
    model = AdaptiveModalAutoencoder()
    report = {"accepted_epochs": 0, "stopped_reason": "projection_timeout",
              "before": {"legal_ir_target_count": 1, "legal_ir_losses": {"ir": .2}},
              "after": {"legal_ir_target_count": 1, "legal_ir_losses": {"ir": .2}},
              "epoch_reports": [{"accepted": False}], "projection_profile": {"seconds": 1.2}}
    calls = []
    def train(samples, **kwargs):
        calls.append(kwargs)
        return report
    model.train_generalizable_projection = train
    assert gated_projection_training(model, [], execution_mode=TRAINING_PATH) is report
    result = run_training(model, [], legal_ir_bridge_names=("deontic_norms",), epochs=2,
                          max_line_search_attempts=3, projection_max_update_families=4, max_seconds=5)
    for key, value in report.items():
        assert result[key] == value
    assert result["stopped_reason"] == "projection_timeout"
    assert result["training_executed"] is True and result["qualified"] is False
    assert {key: calls[-1][key] for key in ("epochs", "max_line_search_attempts", "projection_max_update_families", "max_seconds")} == {
        "epochs": 2, "max_line_search_attempts": 3, "projection_max_update_families": 4, "max_seconds": 5}
    assert calls[-1]["projection_update_backend"] == "python_sparse_batch"
