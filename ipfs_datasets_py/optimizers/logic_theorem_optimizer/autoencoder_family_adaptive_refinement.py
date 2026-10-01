"""Bounded adaptive decoder refinement on complete native feature vocabularies.

No source, proof, or training authority is issued here. The strict owner must
authenticate all original projections before calling this numerical primitive.
The encoder stays fixed. Every family participates in the original masked
macro-family MSE plus 0.1 cosine objective, with unchanged whole-family tuning
selection. Tuning plateaus may reduce individual families' step sizes, never
remove those families. Adam moments continue without reset. Heldouts are not an
argument. Clean full-training monitoring uses the same rows at each epoch;
stochastic minibatch losses remain separately reported.
"""
from __future__ import annotations

import math
import time

from . import autoencoder_family_training as codec
from . import autoencoder_family_training_prepared as prepared
from . import autoencoder_family_decoder_refinement as fixed

SCHEMA = "native-family-adaptive-decoder-refinement/v1"
MAX_FEATURES = 65536
MAX_MEMORY_BUDGET_BYTES = 64 * 1024**3
EPS = prepared.EPS
_require = codec._require


def estimate_numerical_memory(*, training_rows, validation_rows, feature_count,
        projection_count, latent_width, minibatch_size, memory_budget_bytes,
        max_features=MAX_FEATURES):
    """Preflight dense numerical storage from dimensions before feature/SVD allocation."""
    _require(type(max_features) is int and 1 <= max_features <= MAX_FEATURES,
             "bounded explicit feature capacity required")
    _require(type(memory_budget_bytes) is int and 1 <= memory_budget_bytes <= MAX_MEMORY_BUDGET_BYTES,
             "explicit bounded numerical memory budget required")
    for value, limit in ((training_rows, codec.MAX_ROWS), (validation_rows, codec.MAX_ROWS),
            (feature_count, max_features), (projection_count, feature_count),
            (latent_width, 64), (minibatch_size, 1024)):
        _require(type(value) is int and 1 <= value <= limit, "bounded numerical dimensions required")
    width, latent = feature_count, latent_width
    parameter_bytes = (2 * width * latent + latent + width) * 8
    panel_bytes = (training_rows + validation_rows) * width * 8
    input_bytes = panel_bytes + (training_rows + validation_rows) * projection_count + parameter_bytes
    parameter_workspace = 10 * parameter_bytes
    full_panel_workspace = 6 * panel_bytes
    minibatch_workspace = 12 * min(minibatch_size, training_rows) * width * 8
    latent_workspace = 4 * (training_rows + validation_rows + minibatch_size) * latent * 8
    estimated = input_bytes + parameter_workspace + full_panel_workspace + minibatch_workspace + latent_workspace
    _require(estimated <= memory_budget_bytes, "numerical tensor reservation exceeds explicit memory budget")
    return {"input_tensor_bytes": input_bytes, "parameter_workspace_bytes": parameter_workspace,
        "full_panel_workspace_bytes": full_panel_workspace, "minibatch_workspace_bytes": minibatch_workspace,
        "latent_workspace_bytes": latent_workspace, "estimated_tensor_reservation_bytes": estimated,
        "memory_budget_bytes": memory_budget_bytes, "feature_count": width, "max_features": max_features,
        "scope": "conservative_tensor_estimate_excludes_python_torch_allocator_and_process_rss",
        "measured_resident_bytes": None}


def _memory_plan(torch, initial, training, masks, validation, validation_mask,
                 *, minibatch_size, max_features, memory_budget_bytes):
    """Conservative tensor reservation, not an allocator/RSS measurement."""
    _require(type(max_features) is int and 1 <= max_features <= MAX_FEATURES,
             "bounded explicit feature capacity required")
    _require(type(memory_budget_bytes) is int and 1 <= memory_budget_bytes <= MAX_MEMORY_BUDGET_BYTES,
             "explicit bounded numerical memory budget required")
    _require(type(minibatch_size) is int and 1 <= minibatch_size <= 1024,
             "bounded minibatch size required")
    _require(type(initial) in (tuple, list) and len(initial) == 4,
             "four structural parameter tensors required")
    tensors = [training, masks, validation, validation_mask, *initial]
    _require(all(isinstance(value, torch.Tensor) for value in tensors), "tensor inputs required")
    _require(training.ndim == validation.ndim == 2 and initial[0].ndim == 2,
             "feature and encoder matrices required")
    width, latent = training.shape[1], initial[0].shape[1]
    _require(1 <= width <= max_features and validation.shape[1] == width
             and 1 <= latent <= 64 and 1 <= len(training) <= codec.MAX_ROWS
             and 1 <= len(validation) <= codec.MAX_ROWS, "bounded matching feature panels required")
    _require(masks.ndim == 2, "projection presence matrix required")
    return estimate_numerical_memory(training_rows=len(training), validation_rows=len(validation),
        feature_count=width, projection_count=masks.shape[1], latent_width=latent,
        minibatch_size=minibatch_size, memory_budget_bytes=memory_budget_bytes, max_features=max_features)


def _check_inputs(torch, initial, training, masks, validation, validation_mask, spans, descriptors):
    _require(all(value.dtype == torch.float64 and value.device.type == "cpu"
                 and bool(torch.isfinite(value).all()) for value in [training, validation, *initial]),
             "finite CPU float64 features and parameters required")
    width, latent = training.shape[1], initial[0].shape[1]
    _require([tuple(value.shape) for value in initial] ==
             [(width, latent), (latent,), (latent, width), (width,)], "parameter shapes differ")
    _require(type(spans) is dict and type(descriptors) is dict and spans
             and set(spans) == set(descriptors), "every projection requires a span and descriptor")
    offset, groups = 0, {}
    for name, span in spans.items():
        _require(type(span) in (tuple, list) and len(span) == 2
                 and all(type(value) is int for value in span)
                 and span[0] == offset and span[0] < span[1] <= width,
                 "projection spans must exactly partition every feature")
        family = descriptors[name].get("logic_family") if type(descriptors[name]) is dict else None
        _require(type(family) is str and bool(family), "explicit logic family required")
        groups.setdefault(family, []).append(tuple(span))
        offset = span[1]
    _require(offset == width, "projection spans omit feature columns")
    for value, mask in ((training, masks), (validation, validation_mask)):
        _require(mask.dtype == torch.bool and mask.device.type == "cpu"
                 and tuple(mask.shape) == (len(value), len(spans))
                 and bool(mask.any(dim=0).all()) and bool(mask.any(dim=1).all()),
                 "every row and projection requires training and tuning coverage")
    return groups


def _norms(torch, weight, bias, groups):
    return {family: math.sqrt(sum(float(weight[:, begin:end].square().sum())
        + float(bias[begin:end].square().sum()) for begin, end in blocks))
        for family, blocks in groups.items()}


def _clean_score(torch, latent, parameters, target, mask, spans, descriptors):
    with torch.no_grad():
        value, metrics = codec._objective(torch, fixed._prediction(latent, parameters),
            target, mask, spans, descriptors)
    _require(bool(torch.isfinite(value)), "nonfinite clean full-training objective")
    return float(value), metrics


def _plateau_settings(adaptive_learning_rate, plateau_patience, plateau_factor, min_learning_rate_ratio):
    _require(type(adaptive_learning_rate) is bool and type(plateau_patience) is int
             and 1 <= plateau_patience <= 256, "explicit bounded plateau policy required")
    for value in (plateau_factor, min_learning_rate_ratio):
        _require(type(value) in (int, float) and math.isfinite(value) and 0 < value < 1,
                 "plateau factor and learning-rate floor must lie strictly between zero and one")


def validate_settings(*, epochs, latent_width, minibatch_size, patience, learning_rate,
        denoising, seed, memory_budget_bytes, max_features=MAX_FEATURES, ridge=.001,
        max_seconds=120, adaptive_learning_rate=False, plateau_patience=3,
        plateau_factor=.5, min_learning_rate_ratio=.05):
    """Validate public owner settings before target allocation or SVD initialization."""
    prepared._settings(epochs, latent_width, minibatch_size, patience, learning_rate,
        denoising, ridge, seed, max_seconds)
    _plateau_settings(adaptive_learning_rate, plateau_patience, plateau_factor, min_learning_rate_ratio)
    _require(type(max_features) is int and 1 <= max_features <= MAX_FEATURES,
             "bounded explicit feature capacity required")
    _require(type(memory_budget_bytes) is int and 1 <= memory_budget_bytes <= MAX_MEMORY_BUDGET_BYTES,
             "explicit bounded numerical memory budget required")


def refine_decoder_blocks_adaptive(torch, initial, training, masks, validation, validation_mask,
        spans, descriptors, *, epochs, learning_rate, minibatch_size, denoising,
        patience, seed, deadline, memory_budget_bytes, max_features=MAX_FEATURES,
        plateau_patience=3, plateau_factor=.5, min_learning_rate_ratio=.05,
        adaptive_learning_rate=False, clock=None):
    """Train all decoder blocks; adapt step scales only from declared tuning data.

    Set ``adaptive_learning_rate=False`` for the matched fixed-schedule control.
    The tensor reservation is checked before allocating caches, optimizer state,
    or parameter copies. The monotonic absolute deadline includes monitoring and
    selection. Partial or late epochs never update the selected artifact.
    """
    clock = clock or time.monotonic
    started = clock()
    memory = _memory_plan(torch, initial, training, masks, validation, validation_mask,
        minibatch_size=minibatch_size, max_features=max_features, memory_budget_bytes=memory_budget_bytes)
    groups = _check_inputs(torch, initial, training, masks, validation, validation_mask, spans, descriptors)
    prepared._settings(epochs, initial[0].shape[1], minibatch_size, patience, learning_rate,
        denoising, .001, seed, 120)
    _plateau_settings(adaptive_learning_rate, plateau_patience, plateau_factor, min_learning_rate_ratio)
    _require(type(deadline) in (int, float) and math.isfinite(deadline), "finite absolute deadline required")
    best = [p.detach().clone() for p in initial]
    with torch.no_grad():
        training_latent = torch.tanh(training @ best[0] + best[1])
        tuning_latent = torch.tanh(validation @ best[0] + best[1])
    initial_clean, initial_clean_metrics = _clean_score(torch, training_latent, best,
        training, masks, spans, descriptors)
    best_loss, after = _clean_score(torch, tuning_latent, best, validation, validation_mask, spans, descriptors)
    baseline, selected_clean, selected_clean_metrics = after["families"].copy(), initial_clean, initial_clean_metrics
    parameters = [p.detach().clone().requires_grad_(index >= 2) for index, p in enumerate(best)]
    optimizer = torch.optim.Adam(parameters[2:], lr=learning_rate)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    population = (len(training), masks.sum(dim=0).tolist())
    scales = {family: 1. for family in groups}
    plateaus = {family: 0 for family in groups}
    reductions = {family: 0 for family in groups}
    family_epochs = {family: 0 for family in groups}
    history, steps, selected_epoch, stale, stopped = [], 0, 0, 0, "epoch_budget"
    for epoch in range(epochs):
        if clock() >= deadline:
            stopped = "deadline"
            break
        order = torch.randperm(len(training), generator=generator)
        weighted, seen, aborted = 0., 0, False
        gradient_max = dict.fromkeys(groups, 0.)
        step_norm_sum = dict.fromkeys(groups, 0.)
        active_scales = dict(scales)
        for offset in range(0, len(training), minibatch_size):
            if clock() >= deadline:
                aborted = True
                break
            indices = order[offset:offset + minibatch_size]
            clean = training[indices]
            objective = prepared._PreparedObjective(torch, clean, masks[indices], spans, descriptors, population)
            optimizer.zero_grad(set_to_none=True)
            clean_loss = objective(fixed._prediction(training_latent[indices], parameters))
            loss = clean_loss
            if denoising:
                noisy = clean * (torch.rand(clean.shape, generator=generator) >= denoising)
                latent = torch.tanh(noisy @ parameters[0] + parameters[1])
                loss = .75 * clean_loss + .25 * objective(fixed._prediction(latent, parameters))
            _require(bool(torch.isfinite(loss)), "nonfinite decoder training loss")
            loss.backward()
            norm = float(torch.nn.utils.clip_grad_norm_(parameters[2:], 1.))
            _require(math.isfinite(norm), "nonfinite decoder gradient")
            gradients = _norms(torch, parameters[2].grad, parameters[3].grad, groups)
            for family in groups:
                gradient_max[family] = max(gradient_max[family], gradients[family])
            progress = (epoch + offset / len(training)) / epochs
            rate = learning_rate * min(1., (steps + 1) / 5) * (
                .1 + .9 * (1 + math.cos(math.pi * progress)) / 2)
            optimizer.param_groups[0]["lr"] = rate
            before_weight, before_bias = [p.detach().clone() for p in parameters[2:]]
            optimizer.step()
            with torch.no_grad():
                weight_delta = parameters[2] - before_weight
                bias_delta = parameters[3] - before_bias
                for family, blocks in groups.items():
                    for begin, end in blocks:
                        # Keep the ratio-one control bit-identical to Adam.
                        if active_scales[family] != 1.:
                            weight_delta[:, begin:end] *= active_scales[family]
                            bias_delta[begin:end] *= active_scales[family]
                            parameters[2][:, begin:end] = before_weight[:, begin:end] + weight_delta[:, begin:end]
                            parameters[3][begin:end] = before_bias[begin:end] + bias_delta[begin:end]
                actual_steps = _norms(torch, parameters[2] - before_weight,
                    parameters[3] - before_bias, groups)
            for family in groups:
                step_norm_sum[family] += actual_steps[family]
            steps += 1
            weighted += float(loss.detach()) * len(indices)
            seen += len(indices)
        if aborted or clock() >= deadline:
            stopped = "deadline_partial_epoch_not_selected" if aborted else "deadline_epoch_not_selected"
            break
        clean_objective, clean_metrics = _clean_score(torch, training_latent, parameters,
            training, masks, spans, descriptors)
        if clock() >= deadline:
            stopped = "deadline_monitor_not_selected"
            break
        candidate, score, metrics, selection = fixed._select(torch, best, parameters,
            tuning_latent, validation, validation_mask, spans, descriptors)
        # Monitor the exact selected composite, not a single family's last epoch.
        candidate_clean, candidate_clean_metrics = _clean_score(torch, training_latent, candidate,
            training, masks, spans, descriptors)
        timely = clock() < deadline
        selected = timely and bool(selection["selected_families"]) and score < best_loss - EPS
        chosen = selection["selected_families"] if selected else []
        if selected:
            best, best_loss, after = candidate, score, metrics
            selected_clean, selected_clean_metrics = candidate_clean, candidate_clean_metrics
            selected_epoch, stale = epoch + 1, 0
        else:
            stale += 1
        reduced = []
        if timely:
            for family in groups:
                if family in chosen:
                    family_epochs[family], plateaus[family] = epoch + 1, 0
                else:
                    plateaus[family] += 1
                if adaptive_learning_rate and plateaus[family] >= plateau_patience:
                    next_scale = max(min_learning_rate_ratio, scales[family] * plateau_factor)
                    if next_scale < scales[family]:
                        scales[family] = next_scale
                        reductions[family] += 1
                        reduced.append(family)
                    plateaus[family] = 0
        history.append({"epoch": epoch + 1, "training_objective": weighted / seen,
            "clean_training_objective": clean_objective, "clean_training_families": clean_metrics["families"],
            "selected_clean_training_objective": selected_clean,
            "selected_clean_training_families": selected_clean_metrics["families"].copy(),
            "validation_objective": selection["candidate_objective"],
            "validation_families": selection["candidate_families"], "selected": selected,
            "selected_objective": best_loss, "selected_families": chosen,
            "selected_validation_families": after["families"].copy(),
            "candidate_regressed_families": selection["candidate_regressed_families"],
            "learning_rate": rate, "learning_rate_by_family": {family: rate * active_scales[family] for family in groups},
            "next_epoch_learning_rate_scale": dict(scales), "plateau_counters": dict(plateaus),
            "learning_rate_reduced_families": reduced, "decoder_gradient_l2_max_by_family": gradient_max,
            "decoder_step_l2_sum_by_family": step_norm_sum, "selection_discarded_due_deadline": not timely})
        if not timely:
            stopped = "deadline_selection_not_selected"
            break
        if stale >= patience:
            stopped = "validation_patience"
            break
    _require(all(torch.equal(best[i], initial[i]) and torch.equal(parameters[i], initial[i])
                 for i in (0, 1)), "shared encoder changed")
    _require(all(after["families"][family] <= value + EPS for family, value in baseline.items()),
             "selected family regressed against initialization")
    return {"parameters": best, "loss": best_loss, "metrics": after, "history": history,
        "steps": steps, "selected_epoch": selected_epoch, "stopped": stopped,
        "elapsed_seconds": clock() - started,
        "selection_diagnostics": {"schema": SCHEMA, "encoder_frozen": True,
            "selection_unit": "all_decoder_columns_for_each_logic_family",
            "candidate_trajectory": "continuous_adam_no_reset_on_selection_or_rate_reduction",
            "adaptive_learning_rate": adaptive_learning_rate,
            "plateau_settings": {"patience": plateau_patience, "factor": plateau_factor,
                "minimum_ratio": min_learning_rate_ratio},
            "rate_controller_signal": "per_family_tuning_selection_plateau",
            "rate_cap": "original_warmup_cosine_learning_rate",
            "gradient_norm_scope": "per_family_maximum_after_global_decoder_gradient_clip_at_1",
            "step_norm_scope": "per_family_sum_of_applied_minibatch_update_l2_norms",
            "clean_monitor_scope": "same_full_training_rows_and_original_presence_masks_without_denoising",
            "learning_rate_reductions_by_family": reductions,
            "initial_clean_training_objective": initial_clean,
            "initial_clean_training_families": initial_clean_metrics["families"],
            "selected_clean_training_objective": selected_clean,
            "all_families_evaluated": sorted(groups), "selected_epoch_by_family": family_epochs,
            "memory_reservation": memory, "feature_columns_dropped": 0,
            "gradient_uses_tuning": False, "optimizer_schedule_uses_tuning": adaptive_learning_rate,
            "selection_uses_tuning": True, "independent_holdout_used": False,
            "source_text_decoder_trained": False, "global_optimum_established": False,
            "qualified": False, "admitted": False}}


__all__ = ["refine_decoder_blocks_adaptive", "estimate_numerical_memory", "validate_settings",
           "SCHEMA", "MAX_FEATURES"]
