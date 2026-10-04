"""Synthetic alignment fixtures; these never qualify real encoder outputs.

Sparse fixtures use authored zero coordinates to verify closed-form algebra;
they are not padding, conversion, or production embedding-generation recipes.
"""
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
MODULE = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_affine_alignment.py"
spec = importlib.util.spec_from_file_location("gte_affine_alignment_test_subject", MODULE)
subject = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = subject
spec.loader.exec_module(subject)
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def bounded_test_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def basis(index, dimension):
    row = [0.] * dimension
    row[index] = 1.
    return row


def normalized_dense(index, dimension, phase):
    row = [math.sin((index + 1) * (coordinate + 1) * .013 + phase)
           + math.cos((index + 3) * (coordinate + 7) * .019 - phase)
           for coordinate in range(dimension)]
    norm = math.sqrt(math.fsum(value * value for value in row))
    return [value / norm for value in row]


@pytest.fixture(scope="module")
def dense_case():
    inputs = [normalized_dense(index, 768, .1) for index in range(20)]
    targets = [normalized_dense(index, 384, .7) for index in range(20)]
    train = subject.fit_affine_ridge(inputs[:16], targets[:16], regularization=1e-6)
    return inputs, targets, train


@pytest.fixture(scope="module")
def two_row_fit():
    return subject.fit_affine_ridge([basis(0, 768), basis(1, 768)],
        [basis(0, 384), basis(1, 384)], regularization=1.)


def zero_state():
    return {"weight": [[0.] * 768 for _ in range(384)], "bias": [0.] * 384}


def test_import_loads_no_numerical_dependency():
    code = """import importlib.util, sys
spec = importlib.util.spec_from_file_location('isolated_alignment', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch', 'transformers', 'numpy'))
try:
    module.fit_affine_ridge([], [], regularization=1.)
except ValueError:
    pass
else:
    raise AssertionError('empty fit accepted')
assert 'torch' not in sys.modules
state = {'weight': [[0.] * 768 for _ in range(384)], 'bias': [0.] * 384}
assert module.score_affine_ridge(state, [], [])['status'] == 'unavailable'
assert 'torch' not in sys.modules
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(MODULE)], check=True)


def test_two_row_centered_closed_form_and_unregularized_intercept(two_row_fit):
    state = two_row_fit["model_state"]
    assert state["weight"][0][:2] == [.25, -.25]
    assert state["weight"][1][:2] == [-.25, .25]
    assert all(value == 0. for row in state["weight"] for value in row[2:])
    assert all(value == 0. for row in state["weight"][2:] for value in row)
    assert state["bias"][:2] == [.5, .5]
    assert all(value == 0. for value in state["bias"][2:])
    assert two_row_fit["objective_residual_reduction"] == "sum"
    assert two_row_fit["objective"] == subject.OBJECTIVE
    assert two_row_fit["intercept_regularized"] is False
    assert two_row_fit["exported_weight_squared_l2"] == .25
    assert two_row_fit["exported_training_objective"] == .5
    assert two_row_fit["diagnostics"]["solver"] == "centered_dual"
    assert two_row_fit["diagnostics"]["system_dimension"] == 2
    assert two_row_fit["diagnostics"]["centered_rank_upper_bound"] == 1
    assert two_row_fit["diagnostics"]["exact_rank"] is None
    assert two_row_fit["diagnostics"]["rank_estimation_performed"] is False
    assert two_row_fit["diagnostics"]["solve_relative_residual"] < 1e-14


def test_metrics_keep_coordinate_and_vector_units_separate(two_row_fit):
    metrics = two_row_fit["train_metrics"]
    assert metrics["mean_squared_l2"] == .125
    assert metrics["coordinate_mse"] == .125 / 384
    assert metrics["min_squared_l2"] == metrics["max_squared_l2"] == .125
    expected_cosine_error = 1. - .75 / math.sqrt(.75**2 + .25**2)
    assert metrics["cosine_error_mean"] == pytest.approx(expected_cosine_error, abs=1e-14)
    assert metrics["adapter_outputs_normalized"] is False
    assert metrics["prediction_dtype"] == "float32"
    assert metrics["metric_accumulation_dtype"] == "float64"
    assert metrics["cosine_available_rows"] == 2
    assert metrics["cosine_unavailable_rows"] == 0


def test_single_row_is_intercept_only_with_no_penalty():
    target = normalized_dense(7, 384, .7)
    fitted = subject.fit_affine_ridge([basis(7, 768)], [target], regularization=1e6)
    assert all(value == 0. for row in fitted["model_state"]["weight"] for value in row)
    assert fitted["model_state"]["bias"] == torch.tensor(target, dtype=torch.float32).tolist()
    assert fitted["train_metrics"]["mean_squared_l2"] == 0.
    assert fitted["exported_training_objective"] == 0.
    assert fitted["diagnostics"]["centered_rank_upper_bound"] == 0


def test_dense_interpolation_scores_heldout_without_using_it_for_fit(dense_case):
    inputs, targets, fitted = dense_case
    state_before = deepcopy(fitted["model_state"])
    validation = subject.score_affine_ridge(fitted["model_state"], inputs[16:], targets[16:])
    assert fitted["train_metrics"]["mean_squared_l2"] < 1e-9
    assert validation["rows"] == 4
    assert validation["mean_squared_l2"] > fitted["train_metrics"]["mean_squared_l2"]
    assert fitted["diagnostics"]["training_rows"] == 16
    assert fitted["validation_used_for_fit"] is False
    assert fitted["input_partition_authenticated"] is False
    assert fitted["model_state"] == state_before
    assert subject.score_affine_ridge(fitted["model_state"], inputs[:16], targets[:16]) == fitted["train_metrics"]


def test_solver_selects_primal_for_768_training_rows():
    inputs = [basis(index % 384, 768) for index in range(768)]
    targets = [basis(index % 384, 384) for index in range(768)]
    fitted = subject.fit_affine_ridge(inputs, targets, regularization=.1)
    assert fitted["diagnostics"]["solver"] == "centered_primal"
    assert fitted["diagnostics"]["system_dimension"] == 768
    assert fitted["diagnostics"]["centered_rank_upper_bound"] == 767
    assert fitted["diagnostics"]["solve_relative_residual"] < 1e-12
    assert fitted["train_metrics"]["mean_squared_l2"] < .003


def test_row_permutation_preserves_solution_with_rounding_tolerance(dense_case):
    inputs, targets, fitted = dense_case
    permuted = subject.fit_affine_ridge(inputs[:16][::-1], targets[:16][::-1], regularization=1e-6)
    assert torch.allclose(torch.tensor(permuted["model_state"]["weight"]),
        torch.tensor(fitted["model_state"]["weight"]), atol=1e-7, rtol=1e-6)
    assert torch.allclose(torch.tensor(permuted["model_state"]["bias"]),
        torch.tensor(fitted["model_state"]["bias"]), atol=1e-7, rtol=1e-6)


def test_score_uses_exported_float32_forward_not_higher_precision(dense_case):
    inputs, targets, fitted = dense_case
    state = fitted["model_state"]
    x = torch.tensor(inputs[16:], dtype=torch.float32)
    y = torch.tensor(targets[16:], dtype=torch.float32).double()
    predicted = torch.nn.functional.linear(x, torch.tensor(state["weight"], dtype=torch.float32),
        torch.tensor(state["bias"], dtype=torch.float32)).double()
    expected = float((predicted - y).square().sum(dim=1).mean())
    assert subject.score_affine_ridge(state, inputs[16:], targets[16:])["mean_squared_l2"] == expected


def test_state_is_exactly_float32_export_and_json_finite(dense_case):
    _, _, fitted = dense_case
    for key in ("weight", "bias"):
        state = fitted["model_state"][key]
        assert torch.tensor(state, dtype=torch.float64).tolist() == torch.tensor(state, dtype=torch.float32).double().tolist()
    assert json.loads(json.dumps(fitted, allow_nan=False)) == fitted
    assert fitted["affine_alignment_fitted"] is True
    assert fitted["optimizer_steps"] == 0
    assert fitted["encoder_numerics_verified"] is False
    assert fitted["semantic_qualification"] is False
    assert fitted["adapted_outputs_are_gte_small"] is False


def test_fit_and_score_preserve_inputs_rng_threads_and_global_flags():
    inputs = [normalized_dense(index, 768, .1) for index in range(3)]
    targets = [normalized_dense(index, 384, .7) for index in range(3)]
    original = deepcopy((inputs, targets))
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    rng = torch.get_rng_state().clone()
    deterministic = torch.are_deterministic_algorithms_enabled()
    try:
        first = subject.fit_affine_ridge(inputs, targets, regularization=.01)
        second = subject.fit_affine_ridge(inputs, targets, regularization=.01)
        subject.score_affine_ridge(first["model_state"], inputs, targets)
        assert first == second
        assert (inputs, targets) == original
        assert torch.equal(torch.get_rng_state(), rng)
        assert torch.get_num_threads() == 2
        assert torch.are_deterministic_algorithms_enabled() == deterministic
        assert torch.is_grad_enabled()
    finally:
        torch.set_num_threads(previous_threads)


def test_failure_restores_threads_and_rng(monkeypatch):
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    rng = torch.get_rng_state().clone()

    def fail(*args, **kwargs):
        assert torch.get_num_threads() == 1
        torch.rand(4)
        raise RuntimeError("synthetic solve failure")

    monkeypatch.setattr(torch.linalg, "solve", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic solve failure"):
            subject.fit_affine_ridge([basis(0, 768)], [basis(0, 384)], regularization=1.)
        assert torch.equal(torch.get_rng_state(), rng)
        assert torch.get_num_threads() == 2
    finally:
        torch.set_num_threads(previous_threads)


@pytest.mark.parametrize("bad_solution", ["zero", "nonfinite"])
def test_rejects_bad_solver_output_before_returning_a_fit(monkeypatch, bad_solution):
    def fail_numerically(system, right_hand_side):
        if bad_solution == "zero":
            return torch.zeros_like(right_hand_side)
        return torch.full_like(right_hand_side, float("nan"))

    monkeypatch.setattr(torch.linalg, "solve", fail_numerically)
    with pytest.raises(ValueError, match="residual|nonfinite"):
        subject.fit_affine_ridge([basis(0, 768), basis(1, 768)],
            [basis(0, 384), basis(1, 384)], regularization=1.)


def test_empty_validation_is_explicitly_unavailable(two_row_fit):
    metrics = subject.score_affine_ridge(two_row_fit["model_state"], [], [])
    assert metrics["status"] == "unavailable" and metrics["reason"] == "no_rows"
    assert metrics["rows"] == 0
    assert metrics["coordinate_mse"] is None and metrics["mean_squared_l2"] is None
    assert metrics["cosine_error_mean"] is None


def test_zero_prediction_has_defined_error_and_undefined_cosine():
    metrics = subject.score_affine_ridge(zero_state(), [basis(0, 768)], [basis(0, 384)])
    assert metrics["status"] == "available"
    assert metrics["mean_squared_l2"] == 1.
    assert metrics["coordinate_mse"] == 1. / 384
    assert metrics["cosine_error_mean"] is None and metrics["cosine_error_max"] is None
    assert metrics["cosine_available_rows"] == 0 and metrics["cosine_unavailable_rows"] == 1


@pytest.mark.parametrize("ridge", [0., -1., 1e-9, 1e7, True, "1", None, float("nan"), float("inf")])
def test_rejects_invalid_regularization(ridge):
    with pytest.raises(ValueError):
        subject.fit_affine_ridge([basis(0, 768)], [basis(0, 384)], regularization=ridge)


@pytest.mark.parametrize("side", ["input", "target"])
@pytest.mark.parametrize("bad_row", [[], [0.], [0.] * 8, "row", (), None])
def test_rejects_wrong_row_dimensions_and_types(side, bad_row):
    inputs, targets = [basis(0, 768)], [basis(0, 384)]
    (inputs if side == "input" else targets)[0] = bad_row
    with pytest.raises(ValueError):
        subject.fit_affine_ridge(inputs, targets, regularization=1.)


@pytest.mark.parametrize("side", ["input", "target"])
@pytest.mark.parametrize("coordinate", [True, "0", None, float("nan"), float("inf"), 10**1000])
def test_rejects_nonfinite_or_nonnumeric_coordinates(side, coordinate):
    inputs, targets = [basis(0, 768)], [basis(0, 384)]
    (inputs if side == "input" else targets)[0][1] = coordinate
    with pytest.raises(ValueError):
        subject.fit_affine_ridge(inputs, targets, regularization=1.)


@pytest.mark.parametrize("side", ["input", "target"])
@pytest.mark.parametrize("magnitude", [0., .5, 2.])
def test_rejects_vectors_without_unit_normalization(side, magnitude):
    inputs, targets = [basis(0, 768)], [basis(0, 384)]
    (inputs if side == "input" else targets)[0][0] = magnitude
    with pytest.raises(ValueError, match="normalized|bounded"):
        subject.fit_affine_ridge(inputs, targets, regularization=1.)


@pytest.mark.parametrize("inputs,targets", [([], []), ([basis(0, 768)], []),
    ([], [basis(0, 384)]), (None, None), ((basis(0, 768),), (basis(0, 384),))])
def test_rejects_missing_training_rows_or_mismatched_pairs(inputs, targets):
    with pytest.raises(ValueError):
        subject.fit_affine_ridge(inputs, targets, regularization=1.)


def test_rejects_more_than_4096_rows_before_numerical_import(monkeypatch):
    monkeypatch.setattr(subject, "_torch", lambda: pytest.fail("Torch loaded for invalid row count"))
    with pytest.raises(ValueError):
        subject.fit_affine_ridge([basis(0, 768)] * 4097, [basis(0, 384)] * 4097, regularization=1.)


@pytest.mark.parametrize("mutation", ["extra", "missing", "weight_rows", "weight_width",
    "bias_width", "weight_bool", "bias_nan", "weight_huge"])
def test_rejects_malformed_model_state(mutation):
    state = zero_state()
    if mutation == "extra":
        state["optimizer"] = {}
    elif mutation == "missing":
        del state["bias"]
    elif mutation == "weight_rows":
        state["weight"].pop()
    elif mutation == "weight_width":
        state["weight"][0].pop()
    elif mutation == "bias_width":
        state["bias"].pop()
    elif mutation == "weight_bool":
        state["weight"][0][0] = True
    elif mutation == "bias_nan":
        state["bias"][0] = float("nan")
    elif mutation == "weight_huge":
        state["weight"][0][0] = 1e9
    with pytest.raises(ValueError):
        subject.score_affine_ridge(state, [basis(0, 768)], [basis(0, 384)])


def test_score_rejects_mismatched_empty_pairs(two_row_fit):
    with pytest.raises(ValueError):
        subject.score_affine_ridge(two_row_fit["model_state"], [], [basis(0, 384)])
