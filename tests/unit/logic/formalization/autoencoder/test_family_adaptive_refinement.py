"""Complete-vocabulary numerical optimizer tests; no native proof authority."""
import math

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_adaptive_refinement as api
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_decoder_refinement as fixed
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training as codec


@pytest.fixture(autouse=True)
def one_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def panel(width=6):
    generator = torch.Generator().manual_seed(17)
    training = torch.rand((6, width), generator=generator, dtype=torch.float64)
    training[:, :2] = .5
    validation = training[[0, 2, 4]].clone()
    spans = {"fixed": (0, 2), "moving1": (2, 4), "moving2": (4, width)}
    descriptors = {name: {"logic_family": "already_exact" if name == "fixed" else "learning"} for name in spans}
    masks, vm = torch.ones((6, 3), dtype=torch.bool), torch.ones((3, 3), dtype=torch.bool)
    encoder = torch.rand((width, 2), generator=generator, dtype=torch.float64) * .2
    initial = [encoder, torch.zeros(2, dtype=torch.float64),
        torch.zeros((2, width), dtype=torch.float64), torch.full((width,), .1, dtype=torch.float64)]
    initial[3][:2] = .5
    return initial, training, masks, validation, vm, spans, descriptors


def fit(values=None, **options):
    settings = dict(epochs=8, learning_rate=.01, minibatch_size=3, denoising=.05,
        patience=8, seed=1729, deadline=1e12, memory_budget_bytes=1024**3,
        adaptive_learning_rate=True)
    settings.update(options)
    return api.refine_decoder_blocks_adaptive(torch, *(values or panel()), **settings)


def test_fixed_schedule_matches_previous_decoder_optimizer_exactly():
    values = panel()
    settings = dict(epochs=8, learning_rate=.01, minibatch_size=3, denoising=.05,
        patience=8, seed=1729, deadline=1e12)
    expected = fixed.refine_decoder_blocks(torch, *values, **settings)
    actual = api.refine_decoder_blocks_adaptive(torch, *values, **settings,
        adaptive_learning_rate=False, memory_budget_bytes=1024**3)
    assert actual["loss"] == expected["loss"]
    assert actual["metrics"] == expected["metrics"]
    assert all(torch.equal(a, b) for a, b in zip(actual["parameters"], expected["parameters"]))
    assert [row["training_objective"] for row in actual["history"]] == [
        row["training_objective"] for row in expected["history"]]


def test_clean_monitors_are_exact_full_panel_metrics_of_selected_composite():
    values = panel()
    result = fit(values)
    initial, train, mask, _, _, spans, descriptors = values
    with torch.no_grad():
        latent = torch.tanh(train @ initial[0] + initial[1])
        expected, metrics = codec._objective(torch, fixed._prediction(latent, result["parameters"]),
            train, mask, spans, descriptors)
    assert result["history"][-1]["selected_clean_training_objective"] == float(expected)
    assert result["history"][-1]["selected_clean_training_families"] == metrics["families"]
    assert result["history"][-1]["clean_training_objective"] < result["selection_diagnostics"]["initial_clean_training_objective"]
    for row in result["history"]:
        assert set(row["decoder_gradient_l2_max_by_family"]) == set(result["metrics"]["families"])
        assert set(row["decoder_step_l2_sum_by_family"]) == set(result["metrics"]["families"])
        assert all(math.isfinite(v) and v >= 0 for v in row["decoder_gradient_l2_max_by_family"].values())
    assert all(torch.equal(result["parameters"][i], initial[i]) for i in (0, 1))


def test_plateau_rates_reduce_per_family_never_above_cosine_or_below_declared_ratio():
    result = fit(plateau_patience=1, min_learning_rate_ratio=.25)
    assert result["selection_diagnostics"]["learning_rate_reductions_by_family"]["already_exact"] == 2
    for row in result["history"]:
        assert all(.25 <= value <= 1. for value in row["next_epoch_learning_rate_scale"].values())
        assert all(row["learning_rate"] * .25 <= value <= row["learning_rate"]
                   for value in row["learning_rate_by_family"].values())
        assert "already_exact" in row["validation_families"]
        assert "already_exact" in row["clean_training_families"]
    diagnostics = result["selection_diagnostics"]
    assert diagnostics["optimizer_schedule_uses_tuning"] and not diagnostics["gradient_uses_tuning"]
    assert not diagnostics["independent_holdout_used"] and not diagnostics["qualified"]
    assert not diagnostics["global_optimum_established"]


@pytest.mark.parametrize("width", [4097, 65536])
def test_complete_vocabulary_above_old_limit_is_retained(width):
    result = fit(panel(width), epochs=1, patience=1)
    assert result["parameters"][2].shape[1] == width
    assert result["selection_diagnostics"]["feature_columns_dropped"] == 0
    assert result["selection_diagnostics"]["memory_reservation"]["feature_count"] == width
    assert set(result["metrics"]["projections"]) == {"fixed", "moving1", "moving2"}


def test_tiny_memory_budget_fails_before_optimizer_or_parameter_clones(monkeypatch):
    def never(*args, **kwargs):
        raise AssertionError("budget check must precede work allocations")
    monkeypatch.setattr(torch.optim, "Adam", never)
    with pytest.raises(ValueError, match="memory budget"):
        fit(memory_budget_bytes=1)


def test_dimension_preflight_matches_runtime_memory_reservation():
    result = fit(epochs=1)
    expected = api.estimate_numerical_memory(training_rows=6, validation_rows=3,
        feature_count=6, projection_count=3, latent_width=2, minibatch_size=3,
        memory_budget_bytes=1024**3)
    assert expected == result["selection_diagnostics"]["memory_reservation"]
    assert expected["measured_resident_bytes"] is None


def test_monitor_crossing_deadline_cannot_select_candidate(monkeypatch):
    clock, calls = [0.], [0]
    original = api._clean_score
    def late(*args, **kwargs):
        value = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 3:
            clock[0] = 2.
        return value
    monkeypatch.setattr(api, "_clean_score", late)
    values = panel()
    result = fit(values, deadline=1., clock=lambda: clock[0])
    assert result["steps"] == 2 and result["selected_epoch"] == 0
    assert result["stopped"] == "deadline_monitor_not_selected"
    assert all(torch.equal(a, b) for a, b in zip(values[0], result["parameters"]))


def test_selected_composite_monitor_crossing_deadline_discards_selection(monkeypatch):
    clock, calls = [0.], [0]
    original = api._clean_score
    def late(*args, **kwargs):
        value = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 4:
            clock[0] = 2.
        return value
    monkeypatch.setattr(api, "_clean_score", late)
    values = panel()
    result = fit(values, deadline=1., clock=lambda: clock[0])
    assert result["selected_epoch"] == 0 and result["stopped"] == "deadline_selection_not_selected"
    assert result["history"][0]["selection_discarded_due_deadline"]
    assert all(torch.equal(a, b) for a, b in zip(values[0], result["parameters"]))


def test_partial_epoch_is_not_selected(monkeypatch):
    clock = [0.]
    original = torch.optim.Adam.step
    def late(*args, **kwargs):
        value = original(*args, **kwargs); clock[0] = 2.
        return value
    monkeypatch.setattr(torch.optim.Adam, "step", late)
    result = fit(deadline=1., clock=lambda: clock[0], minibatch_size=1)
    assert result["steps"] == 1 and result["selected_epoch"] == 0 and not result["history"]
    assert result["stopped"] == "deadline_partial_epoch_not_selected"


def test_fixed_schedule_training_trajectory_does_not_read_tuning():
    left = panel()
    right = list(panel()); right[3] = right[3] * .7
    a, b = fit(left, adaptive_learning_rate=False), fit(right, adaptive_learning_rate=False)
    assert [r["training_objective"] for r in a["history"]] == [r["training_objective"] for r in b["history"]]
    assert [r["clean_training_objective"] for r in a["history"]] == [r["clean_training_objective"] for r in b["history"]]


@pytest.mark.parametrize("option,value", [("max_features", 65537), ("max_features", True),
    ("memory_budget_bytes", True), ("memory_budget_bytes", 64 * 1024**3 + 1),
    ("adaptive_learning_rate", 1), ("plateau_patience", 0), ("plateau_patience", True),
    ("plateau_factor", 0), ("plateau_factor", float("nan")), ("min_learning_rate_ratio", 1),
    ("min_learning_rate_ratio", True), ("deadline", True), ("epochs", 0)])
def test_invalid_settings_fail_closed(option, value):
    with pytest.raises(ValueError):
        fit(**{option: value})


def test_projection_coverage_and_masked_objective_remain_strict():
    values = list(panel()); values[2][:, 1] = False
    with pytest.raises(ValueError, match="coverage"):
        fit(values)
    values = list(panel()); values[-2]["moving2"] = (4, 5)
    with pytest.raises(ValueError, match="omit feature"):
        fit(values)


def test_public_setting_validation_can_precede_allocations():
    api.validate_settings(epochs=2, latent_width=4, minibatch_size=2, patience=2,
        learning_rate=.001, denoising=.05, seed=1729, memory_budget_bytes=1024**3)
    with pytest.raises(ValueError, match="plateau"):
        api.validate_settings(epochs=2, latent_width=4, minibatch_size=2, patience=2,
            learning_rate=.001, denoising=.05, seed=1729, memory_budget_bytes=1024**3,
            plateau_factor=1.)
