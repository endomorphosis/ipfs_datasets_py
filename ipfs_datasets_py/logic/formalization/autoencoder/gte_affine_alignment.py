"""Training-only, centered ridge alignment of 768D and 384D vector spaces.

Only the affine boundary is fitted. The caller must authenticate paired rows
and their training split before supplying them; this numerical helper never
loads an encoder, decoder, optimizer, or validation selection policy. Torch is
imported lazily, and all solves use one CPU thread and float64 arithmetic.

The objective is sum_i ||x_i W.T + b - y_i||^2 + lambda ||W||_F^2.
The intercept is not regularized. Lambda therefore uses the summed residual
convention, rather than a mean residual convention. All reported predictive
metrics evaluate the exported float32 boundary, without output normalization.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math


SCHEMA = "gte-affine-ridge-fit/v1"
METRICS_SCHEMA = "gte-affine-alignment-metrics/v1"
INPUT_DIMENSION = 768
OUTPUT_DIMENSION = 384
MAX_ROWS = 4096
MIN_REGULARIZATION = 1e-8
MAX_REGULARIZATION = 1e6
L2_TOLERANCE = 1e-4
MAX_SOLVE_RELATIVE_RESIDUAL = 1e-6
OBJECTIVE = "sum_squared_l2_residual_plus_lambda_frobenius_weight_squared"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _finite_number(value, label, *, absolute_limit=1e8):
    _require(type(value) in (int, float), "finite numeric " + label + " required")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("finite bounded " + label + " required") from exc
    _require(math.isfinite(number) and abs(number) <= absolute_limit,
             "finite bounded " + label + " required")
    return number


def _regularization(value):
    number = _finite_number(value, "regularization", absolute_limit=MAX_REGULARIZATION)
    _require(MIN_REGULARIZATION <= number <= MAX_REGULARIZATION,
             "regularization must be between 1e-8 and 1e6")
    return number


def _vectors(value, dimension, label, *, allow_empty):
    _require(type(value) is list and (allow_empty or bool(value)) and len(value) <= MAX_ROWS,
             "bounded " + label + " row list required")
    rows = []
    for row in value:
        _require(type(row) is list and len(row) == dimension,
                 "exact " + str(dimension) + "D " + label + " rows required")
        numbers = [_finite_number(item, label + " coordinate", absolute_limit=1.001)
                   for item in row]
        norm = math.sqrt(math.fsum(item * item for item in numbers))
        _require(abs(norm - 1.) <= L2_TOLERANCE,
                 "unit L2-normalized " + label + " vectors required")
        rows.append(numbers)
    return rows


def _paired_vectors(inputs, targets, *, allow_empty):
    left = _vectors(inputs, INPUT_DIMENSION, "input", allow_empty=allow_empty)
    right = _vectors(targets, OUTPUT_DIMENSION, "target", allow_empty=allow_empty)
    _require(len(left) == len(right), "matching paired input and target row counts required")
    return left, right


def _model_state(value):
    _require(type(value) is dict and set(value) == {"weight", "bias"},
             "closed affine weight/bias state required")
    weight = value["weight"]
    _require(type(weight) is list and len(weight) == OUTPUT_DIMENSION,
             "exact 384 by 768 affine weight matrix required")
    result = []
    for row in weight:
        _require(type(row) is list and len(row) == INPUT_DIMENSION,
                 "exact 384 by 768 affine weight matrix required")
        result.append([_finite_number(item, "weight") for item in row])
    bias = value["bias"]
    _require(type(bias) is list and len(bias) == OUTPUT_DIMENSION,
             "exact 384D affine bias required")
    return {"weight": result, "bias": [_finite_number(item, "bias") for item in bias]}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _torch():
    import torch
    return torch


@contextmanager
def _numerical_context(torch):
    previous_threads = torch.get_num_threads()
    try:
        if previous_threads != 1:
            torch.set_num_threads(1)
        with torch.random.fork_rng(devices=[]), torch.no_grad():
            yield
    finally:
        if torch.get_num_threads() != previous_threads:
            torch.set_num_threads(previous_threads)


def _empty_metrics():
    return {"schema": METRICS_SCHEMA, "status": "unavailable", "reason": "no_rows",
            "rows": 0, "input_dimension": INPUT_DIMENSION,
            "output_dimension": OUTPUT_DIMENSION, "prediction_dtype": "float32",
            "metric_accumulation_dtype": "float64", "coordinate_mse": None,
            "mean_squared_l2": None, "min_squared_l2": None, "max_squared_l2": None,
            "cosine_error_mean": None, "cosine_error_max": None,
            "cosine_available_rows": 0, "cosine_unavailable_rows": 0,
            "adapter_outputs_normalized": False}


def _metrics(torch, model_state, inputs, targets):
    if not inputs:
        return _empty_metrics()
    weight = torch.tensor(model_state["weight"], dtype=torch.float32, device="cpu")
    bias = torch.tensor(model_state["bias"], dtype=torch.float32, device="cpu")
    data = torch.tensor(inputs, dtype=torch.float32, device="cpu")
    target = torch.tensor(targets, dtype=torch.float32, device="cpu").double()
    # This is the deployment boundary, not a float64 prediction from the solver.
    prediction = torch.nn.functional.linear(data, weight, bias)
    _require(bool(torch.isfinite(prediction).all()), "nonfinite exported float32 prediction")
    prediction = prediction.double()
    squared_l2 = (prediction - target).square().sum(dim=1)
    prediction_norm = prediction.norm(dim=1)
    target_norm = target.norm(dim=1)
    cosine_available = (prediction_norm > 0.) & (target_norm > 0.)
    count = int(cosine_available.sum().item())
    cosine_errors = None
    if count:
        cosine = (prediction[cosine_available] * target[cosine_available]).sum(dim=1) / (
            prediction_norm[cosine_available] * target_norm[cosine_available])
        cosine_errors = 1. - cosine.clamp(min=-1., max=1.)
    _require(bool(torch.isfinite(squared_l2).all())
             and (cosine_errors is None or bool(torch.isfinite(cosine_errors).all())),
             "nonfinite affine alignment metrics")
    return {"schema": METRICS_SCHEMA, "status": "available", "reason": None,
            "rows": len(inputs), "input_dimension": INPUT_DIMENSION,
            "output_dimension": OUTPUT_DIMENSION, "prediction_dtype": "float32",
            "metric_accumulation_dtype": "float64",
            "coordinate_mse": float(squared_l2.mean().item()) / OUTPUT_DIMENSION,
            "mean_squared_l2": float(squared_l2.mean().item()),
            "min_squared_l2": float(squared_l2.min().item()),
            "max_squared_l2": float(squared_l2.max().item()),
            "cosine_error_mean": None if not count else float(cosine_errors.mean().item()),
            "cosine_error_max": None if not count else float(cosine_errors.max().item()),
            "cosine_available_rows": count, "cosine_unavailable_rows": len(inputs) - count,
            "adapter_outputs_normalized": False}


def score_affine_ridge(model_state, inputs768, targets384):
    """Score an exported boundary without changing it or selecting a candidate.

    Empty paired lists return explicit unavailable metrics. Inputs and targets
    retain their own vector-space dimensions; predictions are never L2-scaled.
    A zero prediction has undefined cosine, counted separately from valid rows.
    """
    state = _model_state(model_state)
    inputs, targets = _paired_vectors(inputs768, targets384, allow_empty=True)
    if not inputs:
        return _empty_metrics()
    torch = _torch()
    with _numerical_context(torch):
        return _metrics(torch, state, inputs, targets)


def fit_affine_ridge(train_inputs768, train_targets384, *, regularization):
    """Fit only the caller-supplied training pairs; return a JSON-safe boundary.

    Centering gives an unregularized intercept. For N < 768, the N by N dual
    solve avoids the larger primal solve. Diagnostics report the centered rank
    upper bound, not an expensive SVD or an unauthenticated exact rank claim.
    Validation rows are deliberately absent from this interface; callers score
    each candidate separately and must not refit with validation data.
    """
    ridge = _regularization(regularization)
    inputs, targets = _paired_vectors(train_inputs768, train_targets384, allow_empty=False)
    torch = _torch()
    with _numerical_context(torch):
        data = torch.tensor(inputs, dtype=torch.float64, device="cpu")
        target = torch.tensor(targets, dtype=torch.float64, device="cpu")
        input_mean, target_mean = data.mean(dim=0), target.mean(dim=0)
        centered_input = data - input_mean
        centered_target = target - target_mean
        if len(inputs) < INPUT_DIMENSION:
            solver = "centered_dual"
            system = centered_input @ centered_input.T
            system.diagonal().add_(ridge)
            right_hand_side = centered_target
            coefficients = torch.linalg.solve(system, right_hand_side)
            transposed_weight = centered_input.T @ coefficients
        else:
            solver = "centered_primal"
            system = centered_input.T @ centered_input
            system.diagonal().add_(ridge)
            right_hand_side = centered_input.T @ centered_target
            coefficients = torch.linalg.solve(system, right_hand_side)
            transposed_weight = coefficients
        bias = target_mean - input_mean @ transposed_weight
        _require(bool(torch.isfinite(transposed_weight).all()) and bool(torch.isfinite(bias).all()),
                 "nonfinite ridge solution")
        relative_residual = (system @ coefficients - right_hand_side).norm() / max(
            float(right_hand_side.norm().item()), 1e-300)
        residual_value = float(relative_residual.item())
        _require(math.isfinite(residual_value) and 0. <= residual_value <= MAX_SOLVE_RELATIVE_RESIDUAL,
                 "ridge solve residual exceeds the numerical acceptance threshold")
        state = {"weight": transposed_weight.T.contiguous().float().tolist(),
                 "bias": bias.float().tolist()}
        state = _model_state(state)
        metrics = _metrics(torch, state, inputs, targets)
        weight_squared_l2 = float(torch.tensor(state["weight"], dtype=torch.float64).square().sum())
        return {"schema": SCHEMA, "model_state": state, "weights_sha256": _digest(state),
                "regularization": ridge, "objective": OBJECTIVE,
                "objective_residual_reduction": "sum", "intercept_regularized": False,
                "train_metrics": metrics,
                "exported_weight_squared_l2": weight_squared_l2,
                "exported_training_objective": metrics["mean_squared_l2"] * len(inputs)
                    + ridge * weight_squared_l2,
                "diagnostics": {"solver": solver, "solve_dtype": "float64",
                    "export_dtype": "float32", "device": "cpu", "numerical_threads": 1,
                    "training_rows": len(inputs), "system_dimension": system.shape[0],
                    "centered_rank_upper_bound": min(len(inputs) - 1, INPUT_DIMENSION),
                    "exact_rank": None, "rank_estimation_performed": False,
                    "solve_relative_residual": residual_value,
                    "max_solve_relative_residual": MAX_SOLVE_RELATIVE_RESIDUAL,
                    "solver_numerics_passed": True},
                "validation_used_for_fit": False, "input_partition_authenticated": False,
                "affine_alignment_fitted": True, "optimizer_steps": 0,
                "encoder_numerics_verified": False, "semantic_qualification": False,
                "adapted_outputs_are_gte_small": False}
