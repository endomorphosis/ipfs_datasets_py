"""Fixed-encoder, family-local refinement of native structural feature heads.

This numerical primitive has no source, solver, or training admission authority.
The validated owner must first authenticate every source projection. Gradients
use training rows only; tuning selects complete independent decoder families.
All families retain the existing masked macro-family objective and tolerance.
The encoder is frozen, so accepting one family's columns cannot change another
family's predictions. Adam's candidate trajectory continues between epochs;
selection stores copies and never resets that trajectory or its momentum.
"""
from __future__ import annotations

import math
import time

from . import autoencoder_family_training as codec
from . import autoencoder_family_training_prepared as prepared

SCHEMA = "native-family-fixed-encoder-refinement/v1"
EPS = prepared.EPS
_require = codec._require


def _check_inputs(torch, initial, training, masks, validation, validation_mask,
                  spans, descriptors):
    _require(type(initial) in (list, tuple) and len(initial) == 4,
             "four structural tensors required")
    panels = (training, validation)
    _require(all(isinstance(t, torch.Tensor) and t.ndim == 2 and t.shape[0] > 0
                 and t.dtype == torch.float64 and t.device.type == "cpu"
                 and bool(torch.isfinite(t).all()) for t in panels),
             "finite nonempty CPU float64 feature panels required")
    width = training.shape[1]
    _require(1 <= width <= codec.MAX_FEATURES and validation.shape[1] == width,
             "matching bounded feature widths required")
    _require(type(spans) is dict and type(descriptors) is dict
             and set(spans) == set(descriptors) and spans,
             "every projection requires its descriptor and span")
    offset = 0
    for name, span in spans.items():
        _require(type(span) in (tuple, list) and len(span) == 2
                 and all(type(value) is int for value in span)
                 and span[0] == offset and span[0] < span[1] <= width,
                 "projection spans must exactly partition feature columns")
        _require(type(descriptors[name]) is dict
                 and type(descriptors[name].get("logic_family")) is str
                 and descriptors[name]["logic_family"], "explicit logic family required")
        offset = span[1]
    _require(offset == width, "projection spans omit feature columns")
    for values, mask in ((training, masks), (validation, validation_mask)):
        _require(isinstance(mask, torch.Tensor) and mask.dtype == torch.bool
                 and mask.device.type == "cpu"
                 and tuple(mask.shape) == (len(values), len(spans))
                 and bool(mask.any(dim=0).all()) and bool(mask.any(dim=1).all()),
                 "every row and projection requires training and tuning coverage")
    _require(all(isinstance(p, torch.Tensor) and p.dtype == torch.float64
                 and p.device.type == "cpu" and bool(torch.isfinite(p).all())
                 for p in initial), "finite CPU float64 parameters required")
    _require(initial[0].ndim == 2, "matrix encoder required")
    latent = initial[0].shape[1]
    _require(1 <= latent <= 64 and [tuple(p.shape) for p in initial] ==
             [(width, latent), (latent,), (latent, width), (width,)],
             "structural parameter shapes differ")
    return latent


def _prediction(latent, parameters):
    return latent @ parameters[2] + parameters[3]


def _select(torch, best, candidate, tuning_latent, tuning, mask, spans, descriptors):
    """Equivalent to prepared._select_decoder_families with cached encodings."""
    _require(all(torch.equal(best[i], candidate[i]) for i in (0, 1)),
             "independent family selection requires an unchanged shared encoder")
    with torch.no_grad():
        _, before = codec._objective(torch, _prediction(tuning_latent, best),
            tuning, mask, spans, descriptors)
        proposed_loss, proposed = codec._objective(torch, _prediction(tuning_latent, candidate),
            tuning, mask, spans, descriptors)
        _require(bool(torch.isfinite(proposed_loss)), "nonfinite decoder tuning objective")
        chosen = {family for family, value in proposed["families"].items()
                  if value < before["families"][family] - EPS}
        regressed = sorted(family for family, value in proposed["families"].items()
                           if value > before["families"][family] + EPS)
        selected = [p.detach().clone() for p in best]
        for name, (start, end) in spans.items():
            if descriptors[name]["logic_family"] in chosen:
                selected[2][:, start:end] = candidate[2][:, start:end]
                selected[3][start:end] = candidate[3][start:end]
        value, after = codec._objective(torch, _prediction(tuning_latent, selected),
            tuning, mask, spans, descriptors)
        _require(bool(torch.isfinite(value)) and all(
            after["families"][family] <= loss + EPS for family, loss in before["families"].items()),
            "selected decoder family regressed")
    return selected, float(value), after, {
        "selected_families": sorted(chosen), "candidate_regressed_families": regressed,
        "candidate_objective": float(proposed_loss), "candidate_families": proposed["families"]}


def refine_decoder_blocks(torch, initial, training, masks, validation, validation_mask,
        spans, descriptors, *, epochs, learning_rate, minibatch_size, denoising,
        patience, seed, deadline, clock=None):
    """Refine decoder columns only; deadline is the owner's absolute monotonic deadline.

    Validation is a tuning panel, never an independent holdout. No incomplete or
    late epoch can change the returned selection. Every attempted minibatch and
    all family metrics remain visible, even if their proposals are rejected.
    """
    clock = clock or time.monotonic
    started = clock()
    latent_width = _check_inputs(torch, initial, training, masks, validation,
        validation_mask, spans, descriptors)
    prepared._settings(epochs, latent_width, minibatch_size, patience, learning_rate,
        denoising, .001, seed, 120)
    _require(type(deadline) in (int, float) and math.isfinite(deadline),
             "finite absolute monotonic deadline required")
    best = [p.detach().clone() for p in initial]
    with torch.no_grad():
        tuning_latent = torch.tanh(validation @ best[0] + best[1])
        value, after = codec._objective(torch, _prediction(tuning_latent, best),
            validation, validation_mask, spans, descriptors)
    _require(bool(torch.isfinite(value)), "nonfinite initial tuning objective")
    best_loss, baseline = float(value), after["families"].copy()
    parameters = [p.detach().clone().requires_grad_(index >= 2)
                  for index, p in enumerate(best)]
    with torch.no_grad():
        training_latent = torch.tanh(training @ parameters[0] + parameters[1])
    # Only decoder tensors enter Adam or gradient clipping. Frozen encoder
    # tensors remain bit-identical throughout both candidate and selected paths.
    optimizer = torch.optim.Adam(parameters[2:], lr=learning_rate)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    population = (len(training), masks.sum(dim=0).tolist())
    history, steps, selected_epoch, stale = [], 0, 0, 0
    stopped, family_epochs = "epoch_budget", {family: 0 for family in baseline}
    for epoch in range(epochs):
        if clock() >= deadline:
            stopped = "deadline"
            break
        order = torch.randperm(len(training), generator=generator)
        weighted, seen, aborted = 0., 0, False
        for offset in range(0, len(training), minibatch_size):
            if clock() >= deadline:
                aborted = True
                break
            indices = order[offset:offset + minibatch_size]
            clean = training[indices]
            optimizer.zero_grad(set_to_none=True)
            objective = prepared._PreparedObjective(torch, clean, masks[indices],
                spans, descriptors, population)
            clean_loss = objective(_prediction(training_latent[indices], parameters))
            loss = clean_loss
            if denoising:
                corrupted = clean * (torch.rand(clean.shape, generator=generator) >= denoising)
                noisy_latent = torch.tanh(corrupted @ parameters[0] + parameters[1])
                loss = .75 * clean_loss + .25 * objective(_prediction(noisy_latent, parameters))
            _require(bool(torch.isfinite(loss)), "nonfinite decoder training loss")
            loss.backward()
            norm = float(torch.nn.utils.clip_grad_norm_(parameters[2:], 1.))
            _require(math.isfinite(norm), "nonfinite decoder training gradient")
            progress = (epoch + offset / len(training)) / epochs
            rate = learning_rate * min(1., (steps + 1) / 5) * (
                .1 + .9 * (1 + math.cos(math.pi * progress)) / 2)
            optimizer.param_groups[0]["lr"] = rate
            optimizer.step()
            steps += 1
            weighted += float(loss.detach()) * len(indices)
            seen += len(indices)
        if aborted or clock() >= deadline:
            stopped = "deadline_partial_epoch_not_selected" if aborted else "deadline_epoch_not_selected"
            break
        candidate, score, metrics, selection = _select(torch, best, parameters,
            tuning_latent, validation, validation_mask, spans, descriptors)
        # Recheck after tuning and selection; evaluating an epoch can cross the
        # deadline even though all of its minibatches finished in time.
        timely = clock() < deadline
        selected = timely and bool(selection["selected_families"]) and score < best_loss - EPS
        if selected:
            best, best_loss, after = candidate, score, metrics
            selected_epoch, stale = epoch + 1, 0
            for family in selection["selected_families"]:
                family_epochs[family] = epoch + 1
        else:
            stale += 1
        history.append({"epoch": epoch + 1, "training_objective": weighted / seen,
            "validation_objective": selection["candidate_objective"],
            "validation_families": selection["candidate_families"], "selected": selected,
            "selected_objective": best_loss, "selected_families": (
                selection["selected_families"] if selected else []),
            "selected_validation_families": after["families"].copy(),
            "candidate_regressed_families": selection["candidate_regressed_families"],
            "learning_rate": rate, "selection_discarded_due_deadline": not timely})
        if not timely:
            stopped = "deadline_selection_not_selected"
            break
        if stale >= patience:
            stopped = "validation_patience"
            break
    _require(all(torch.equal(best[i], initial[i]) and torch.equal(parameters[i], initial[i])
                 for i in (0, 1)), "shared encoder changed during decoder refinement")
    _require(all(after["families"][family] <= loss + EPS for family, loss in baseline.items()),
             "selected family regressed against refinement initialization")
    return {"parameters": best, "loss": best_loss, "metrics": after, "history": history,
        "steps": steps, "selected_epoch": selected_epoch, "stopped": stopped,
        "elapsed_seconds": clock() - started,
        "selection_diagnostics": {"schema": SCHEMA, "encoder_frozen": True,
            "selection_unit": "all_decoder_columns_for_each_logic_family",
            "candidate_trajectory": "continuous_adam_no_reset_on_selection",
            "clean_latents_cached": True, "training_uses_tuning": False,
            "selection_uses_tuning": True, "independent_holdout_used": False,
            "all_families_evaluated": sorted(baseline), "selected_epoch_by_family": family_epochs,
            "source_text_decoder_trained": False, "global_optimum_established": False,
            "qualified": False, "admitted": False}}


__all__ = ["refine_decoder_blocks", "SCHEMA"]
