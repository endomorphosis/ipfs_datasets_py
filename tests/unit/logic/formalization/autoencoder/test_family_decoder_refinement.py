"""Numerical tests only: no synthetic observation here grants native authority."""
from copy import deepcopy

import pytest
import torch

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_decoder_refinement as api
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_prepared as prepared


@pytest.fixture(autouse=True)
def single_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def panel():
    generator = torch.Generator().manual_seed(17)
    training = torch.rand((6, 6), generator=generator, dtype=torch.float64)
    training[:, :2] = .5
    validation = training[[0, 2, 4]].clone()
    spans = {"fixed": (0, 2), "moving1": (2, 4), "moving2": (4, 6)}
    descriptors = {name: {"logic_family": "already_exact" if name == "fixed" else "learning"}
                   for name in spans}
    masks = torch.ones((len(training), 3), dtype=torch.bool)
    validation_mask = torch.ones((len(validation), 3), dtype=torch.bool)
    encoder = torch.rand((6, 2), generator=generator, dtype=torch.float64) * .2
    initial = [encoder, torch.zeros(2, dtype=torch.float64),
               torch.zeros((2, 6), dtype=torch.float64), torch.full((6,), .1, dtype=torch.float64)]
    initial[3][:2] = .5
    return initial, training, masks, validation, validation_mask, spans, descriptors


def fit(values=None, **options):
    settings = dict(epochs=12, learning_rate=.01, minibatch_size=3,
                    denoising=.05, patience=12, seed=1729, deadline=1e12)
    settings.update(options)
    return api.refine_decoder_blocks(torch, *(values or panel()), **settings)


def test_training_improves_learning_family_without_corrupting_exact_family():
    values = panel()
    original = [p.clone() for p in values[0]]
    result = fit(values)
    assert result["steps"] == 24 and result["selected_epoch"] > 0
    assert result["history"][-1]["training_objective"] < result["history"][0]["training_objective"]
    assert all(torch.equal(result["parameters"][i], original[i]) for i in (0, 1))
    assert torch.equal(result["parameters"][2][:, :2], original[2][:, :2])
    assert torch.equal(result["parameters"][3][:2], original[3][:2])
    assert all(torch.equal(before, after) for before, after in zip(original, values[0]))
    assert result["selection_diagnostics"]["all_families_evaluated"] == ["already_exact", "learning"]
    assert not result["selection_diagnostics"]["qualified"]
    selected_losses = [row["selected_objective"] for row in result["history"]]
    assert all(later <= earlier + api.EPS for earlier, later in zip(selected_losses, selected_losses[1:]))
    for family in result["metrics"]["families"]:
        losses = [row["selected_validation_families"][family] for row in result["history"]]
        assert all(later <= earlier + api.EPS for earlier, later in zip(losses, losses[1:]))
    assert set(result["metrics"]["projections"]) == set(values[-2])


def test_cached_selection_equals_existing_fixed_encoder_selector():
    initial, train, mask, validation, vm, spans, descriptors = panel()
    candidate = [p.clone() for p in initial]
    candidate[3][:2] += .1  # Regress the already-exact family.
    candidate[3][2:] += .2  # Improve the other family.
    latent = torch.tanh(validation @ initial[0] + initial[1])
    actual = api._select(torch, initial, candidate, latent, validation, vm, spans, descriptors)
    expected = prepared._select_decoder_families(torch, initial, candidate, validation, vm, spans, descriptors)
    assert all(torch.equal(a, b) for a, b in zip(actual[0], expected[0]))
    assert actual[1:3] == expected[1:3]
    assert actual[3]["selected_families"] == expected[3]["selected_families"] == ["learning"]
    assert actual[3]["candidate_regressed_families"] == ["already_exact"]
    assert torch.equal(actual[0][3][2:], candidate[3][2:])


def test_selection_rejects_changed_shared_encoder():
    initial, _, _, validation, vm, spans, descriptors = panel()
    candidate = [p.clone() for p in initial]
    candidate[0][0, 0] += .001
    latent = torch.tanh(validation @ initial[0] + initial[1])
    with pytest.raises(ValueError, match="unchanged shared encoder"):
        api._select(torch, initial, candidate, latent, validation, vm, spans, descriptors)


def test_cached_forward_has_same_decoder_gradients_as_reference_with_presence_masks():
    initial, train, mask, _, _, spans, descriptors = panel()
    mask[0, 1] = False
    mask[1, 2] = False
    left = [p.clone().requires_grad_(i >= 2) for i, p in enumerate(initial)]
    right = [p.clone().requires_grad_(i >= 2) for i, p in enumerate(initial)]
    objective = prepared._PreparedObjective(torch, train, mask, spans, descriptors,
        (len(train), mask.sum(dim=0).tolist()))
    objective(prepared._forward(torch, train, left)).backward()
    latent = torch.tanh(train @ right[0] + right[1])
    objective(api._prediction(latent, right)).backward()
    for index in (2, 3):
        assert torch.equal(left[index].grad, right[index].grad)
    assert all(p.grad is None for p in right[:2])


def test_tuning_does_not_change_training_trajectory_or_momentum():
    original = panel()
    changed = list(panel())
    changed[3] = changed[3] * .7
    left, right = fit(original), fit(changed)
    assert [row["training_objective"] for row in left["history"]] == [
        row["training_objective"] for row in right["history"]]
    assert left["selection_diagnostics"]["candidate_trajectory"] == "continuous_adam_no_reset_on_selection"
    assert not left["selection_diagnostics"]["training_uses_tuning"]


def test_identical_seed_is_reproducible():
    left, right = fit(), fit()
    assert left["history"] == right["history"]
    assert all(torch.equal(a, b) for a, b in zip(left["parameters"], right["parameters"]))


def test_expired_deadline_keeps_initial_parameters():
    values = panel()
    result = fit(values, deadline=0, clock=lambda: 1.)
    assert result["steps"] == result["selected_epoch"] == 0 and not result["history"]
    assert result["stopped"] == "deadline"
    assert all(torch.equal(a, b) for a, b in zip(values[0], result["parameters"]))


def test_partial_epoch_cannot_select_weights(monkeypatch):
    clock = [0.]
    original = torch.optim.Adam.step
    def step(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = 2.
        return result
    monkeypatch.setattr(torch.optim.Adam, "step", step)
    values = panel()
    result = fit(values, deadline=1., clock=lambda: clock[0], minibatch_size=1)
    assert result["steps"] == 1 and result["selected_epoch"] == 0 and not result["history"]
    assert result["stopped"] == "deadline_partial_epoch_not_selected"
    assert all(torch.equal(a, b) for a, b in zip(values[0], result["parameters"]))


def test_selection_crossing_deadline_is_discarded(monkeypatch):
    clock = [0.]
    original = api._select
    def select(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = 2.
        return result
    monkeypatch.setattr(api, "_select", select)
    values = panel()
    result = fit(values, deadline=1., clock=lambda: clock[0])
    assert result["steps"] == 2 and result["selected_epoch"] == 0
    assert result["stopped"] == "deadline_selection_not_selected"
    assert result["history"][0]["selection_discarded_due_deadline"]
    assert not result["history"][0]["selected_families"]
    assert all(torch.equal(a, b) for a, b in zip(values[0], result["parameters"]))


@pytest.mark.parametrize("option,value", [("epochs", 0), ("learning_rate", float("nan")),
    ("learning_rate", True), ("deadline", float("inf")), ("deadline", True),
    ("denoising", 1), ("minibatch_size", 0), ("seed", True)])
def test_invalid_settings_are_rejected(option, value):
    with pytest.raises(ValueError):
        fit(**{option: value})


@pytest.mark.parametrize("mutation", ["missing_descriptor", "uncovered_feature", "missing_train",
    "missing_tune", "overlapping_spans", "nonfinite", "shape"])
def test_incomplete_or_invalid_projection_panels_are_rejected(mutation):
    values = list(panel())
    if mutation == "missing_descriptor":
        values[-1].pop("moving2")
    elif mutation == "uncovered_feature":
        values[-2]["moving2"] = (4, 5)
    elif mutation == "missing_train":
        values[2][:, 1] = False
    elif mutation == "missing_tune":
        values[4][:, 2] = False
    elif mutation == "overlapping_spans":
        values[-2]["moving2"] = (3, 6)
    elif mutation == "nonfinite":
        values[1][0, 0] = float("nan")
    elif mutation == "shape":
        values[0][2] = values[0][2][:1]
    with pytest.raises(ValueError):
        fit(values)
