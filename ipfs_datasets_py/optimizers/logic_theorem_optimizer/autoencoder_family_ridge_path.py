"""Fast, validation-selected regularization paths for all native IR families.

The encoder is inherited or fitted by training-only SVD. Decoder corrections
are fitted on training rows with ridge regression; the tuning split chooses
the regularization and shrinkage separately for each logic family. Projections
with identical presence masks share one eigendecomposition. Test observations
cannot participate in vocabulary fitting, numerical fitting or selection.

This reconstructs supplied native formula features, not source language. It is
an opt-in alternative to iterative Adam, and does not change existing formats.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import time

from . import autoencoder_family_training as codec
from . import autoencoder_family_training_prepared as prepared

SCHEMA = "native-family-ridge-path/v1"
FALSE = dict(codec.FALSE)
_require, _raw, _sha, _digest = codec._require, codec._raw, codec._sha, codec._digest


def _implementation():
    return {"trainer": _sha(Path(__file__).read_bytes()), "prepared": prepared._implementation()}


def _read(descriptor):
    import torch
    if descriptor.get("schema") != SCHEMA:
        return prepared._read(descriptor)
    _require(set(descriptor) == {"schema", "path", "sha256"}, "closed checkpoint descriptor required")
    path = Path(descriptor["path"])
    _require(path.is_absolute() and path.is_file() and not path.is_symlink() and path.stat().st_size <= codec.MAX_BYTES,
             "bounded regular checkpoint required")
    raw = path.read_bytes()
    _require(_sha(raw) == descriptor["sha256"], "checkpoint digest differs")
    saved = json.loads(raw)
    _require(set(saved) == {"schema", "implementation", "space", "parameters", "report", *FALSE}
             and saved["schema"] == SCHEMA and saved["implementation"] == _implementation(),
             "checkpoint implementation differs")
    _require(all(saved[key] is False and saved["space"][key] is False for key in FALSE),
             "reconstruction cannot grant authority")
    codec._validate_producer_pins(saved["space"]["producer_pins"])
    width, latent = len(saved["space"]["columns"]), saved["report"]["latent_width"]
    _require(1 <= width <= codec.MAX_FEATURES and type(latent) is int and 1 <= latent <= 64,
             "bounded architecture required")
    parameters = [torch.tensor(row, dtype=torch.float64) for row in saved["parameters"]]
    _require([tuple(row.shape) for row in parameters] == [(width, latent), (latent,), (latent, width), (width,)]
             and all(bool(torch.isfinite(row).all()) for row in parameters), "invalid numerical tensors")
    _require(_digest(saved["parameters"]) == saved["report"]["selected_parameters_sha256"], "parameter identity differs")
    return saved, parameters


def _corrections(torch, parameters, training, masks, spans, ridges):
    """Factor each observed-row Gram matrix once, across all decoder blocks."""
    design = torch.cat((torch.tanh(training @ parameters[0] + parameters[1]),
                        torch.ones((len(training), 1), dtype=training.dtype)), dim=1)
    grouped = {}
    for index, (name, (start, end)) in enumerate(spans.items()):
        key = tuple(masks[:, index].tolist())
        grouped.setdefault(key, []).append((name, start, end))
    corrections = {ridge: {} for ridge in ridges}
    for key, blocks in grouped.items():
        present = torch.tensor(key, dtype=torch.bool)
        x = design[present]
        _require(len(x) > 0, "every projection requires training rows")
        eigenvalues, eigenvectors = torch.linalg.eigh(x.T @ x / len(x))
        for name, start, end in blocks:
            prior = torch.cat((parameters[2][:, start:end], parameters[3][None, start:end]))
            residual = training[present, start:end] - x @ prior
            projected_rhs = eigenvectors.T @ (x.T @ residual / len(x))
            for ridge in ridges:
                correction = eigenvectors @ (projected_rhs / (eigenvalues[:, None] + ridge))
                _require(bool(torch.isfinite(correction).all()), "nonfinite ridge correction")
                corrections[ridge][name] = correction
    return corrections, len(grouped)


@codec._single_threaded
def train_family_ridge_path(training_reports, validation_reports, *, output_dir,
        parent_descriptor=None, latent_width=8, ridges=(.0001, .001, .01, .1),
        shrinkages=(.25, .5, 1.), required_families=()):
    """Fit a fresh, separately versioned candidate; retain the parent on ties.

    ``required_families`` is a strict floor on actual native training AND tuning
    evidence. All other ready native families also participate in the objective.
    Missing families never become fabricated targets or zero-valued examples.
    """
    import torch
    started = time.perf_counter()
    _require(type(latent_width) is int and 1 <= latent_width <= 64, "bounded latent width required")
    for values, upper in ((ridges, 1.), (shrinkages, 1.)):
        _require(type(values) in (tuple, list) and 1 <= len(values) <= 8 and len(set(values)) == len(values)
                 and all(type(v) in (int, float) and math.isfinite(v) and 0 < v <= upper for v in values),
                 "bounded positive unique regularization/shrinkage grid required")
    _require(type(required_families) in (tuple, list) and all(type(v) is str for v in required_families),
             "explicit canonical required families required")
    output = Path(output_dir).absolute()
    _require(not output.exists(), "fresh ridge path output required")
    producer = _implementation()
    digest = _digest([training_reports, validation_reports])
    atoms, cache = prepared._atom_encoder()
    domain, train_rows = prepared._reports(training_reports, atoms=atoms)
    other, tune_rows = prepared._reports(validation_reports, atoms=atoms)
    _require(domain == other, "validation domain differs")
    train_keys = set().union(*(codec._split_keys(r) for r in training_reports))
    tune_keys = set().union(*(codec._split_keys(r) for r in validation_reports))
    _require(not train_keys & tune_keys, "training/validation source leakage")
    parent_bytes = None
    if parent_descriptor is None:
        space = codec._space(domain, training_reports, train_rows)
        space["producer_pins"] = codec._producer_pins(list(training_reports) + list(validation_reports))
        parameters = None
    else:
        saved, parameters = _read(parent_descriptor)
        parent_bytes = Path(parent_descriptor["path"]).read_bytes()
        space = copy.deepcopy(saved["space"])
        _require(space["domain_id"] == domain and saved["report"]["latent_width"] == latent_width,
                 "parent domain or architecture differs")
        _require(saved["report"]["validation_reports_sha256"] == _digest(validation_reports)
                 and not set(space["training_split_keys"]) & tune_keys, "historical split or tuning panel differs")
        space["training_split_keys"] = sorted(set(space["training_split_keys"]) | train_keys)
        space["training_sources"] = sorted(set(space["training_sources"]) | {r["source_digest"] for r in training_reports})
        space["training_reports_sha256"] = _digest(training_reports)
    codec._bind_producers(space, list(training_reports) + list(validation_reports))
    x, mask, spans, coverage = codec._matrix(space, train_rows)
    tuning, tuning_mask, _, tuning_coverage = codec._matrix(space, tune_rows)
    _require(not coverage["untrained_projection_ids"] and bool(mask.any(dim=0).all())
             and bool(mask.any(dim=1).all()) and bool(tuning_mask.any(dim=1).all()), "uncovered native projections")
    observed = {row["logic_family"] for row in space["projections"].values()}
    with torch.no_grad():
        if parameters is None:
            mean = x.mean(dim=0)
            _, _, vectors = torch.linalg.svd(x - mean, full_matrices=False)
            basis = torch.zeros((x.shape[1], latent_width), dtype=x.dtype)
            rank = min(latent_width, len(vectors))
            basis[:, :rank] = vectors[:rank].T
            parameters = [basis, -(mean @ basis), basis.T.clone(), mean.clone()]
        initial = [p.clone() for p in parameters]
        initial_loss, initial_metrics = codec._objective(torch, prepared._forward(torch, tuning, initial),
            tuning, tuning_mask, spans, space["projections"])
        _require(set(required_families) <= observed & set(initial_metrics["families"]),
                 "required logic family lacks actual training/tuning evidence")
        preparation_seconds = time.perf_counter() - started
        corrections, factorizations = _corrections(torch, initial, x, mask, spans, ridges)
        best = [p.clone() for p in initial]
        best_by_family = dict(initial_metrics["families"])
        selections = {family: {"ridge": None, "shrinkage": 0.} for family in observed}
        history = []
        for ridge in ridges:
            for shrinkage in shrinkages:
                candidate = [p.clone() for p in initial]
                for name, (start, end) in spans.items():
                    change = corrections[ridge][name] * shrinkage
                    candidate[2][:, start:end] += change[:-1]
                    candidate[3][start:end] += change[-1]
                score, metrics = codec._objective(torch, prepared._forward(torch, tuning, candidate),
                    tuning, tuning_mask, spans, space["projections"])
                chosen = {family for family, value in metrics["families"].items()
                          if value < best_by_family[family] - 1e-12}
                for name, (start, end) in spans.items():
                    family = space["projections"][name]["logic_family"]
                    if family in chosen:
                        best[2][:, start:end] = candidate[2][:, start:end]
                        best[3][start:end] = candidate[3][start:end]
                for family in chosen:
                    best_by_family[family] = metrics["families"][family]
                    selections[family] = {"ridge": ridge, "shrinkage": shrinkage}
                history.append({"ridge": ridge, "shrinkage": shrinkage, "validation_objective": float(score)})
        score, metrics = codec._objective(torch, prepared._forward(torch, tuning, best),
            tuning, tuning_mask, spans, space["projections"])
        _require(all(value <= initial_metrics["families"][family] + 1e-12
                     for family, value in metrics["families"].items()), "family selection regressed")
    state = [p.tolist() for p in best]
    report = {"schema": SCHEMA, "domain_id": domain, "latent_width": latent_width,
        "training_rows": len(x), "validation_rows": len(tuning), "training_executed": True,
        "optimizer_steps": 0, "numerical_method": "shared_gram_eigendecomposition_ridge_path",
        "gram_factorizations": factorizations, "candidate_count": len(history),
        "settings": {"ridges": list(ridges), "shrinkages": list(shrinkages)},
        "before": {"objective": float(initial_loss), **initial_metrics},
        "after": {"objective": float(score), **metrics}, "selection": selections, "history": history,
        "initial_parameters_sha256": _digest([p.tolist() for p in initial]),
        "selected_parameters_sha256": _digest(state), "parent_descriptor": parent_descriptor,
        "parent_modified": False, "training_reports_sha256": _digest(training_reports),
        "validation_reports_sha256": _digest(validation_reports),
        "training_coverage": coverage, "validation_coverage": tuning_coverage,
        "trained_logic_families": sorted(observed), "required_families": sorted(set(required_families)),
        "effective_feature_panels": {"training": prepared._feature_panel(x, mask),
            "validation": prepared._feature_panel(tuning, tuning_mask)},
        "preparation_seconds": preparation_seconds, "elapsed_seconds": time.perf_counter() - started,
        "rate_unit": "unique_training_rows_per_full_fit_second_not_SGD_presentations",
        "source_text_decoder_trained": False, "test_used_for_selection": False,
        "frontier": [r["frontier"] for r in training_reports], **FALSE}
    _require(producer == _implementation() and digest == _digest([training_reports, validation_reports]), "training inputs or source drift")
    _require(parent_bytes is None or Path(parent_descriptor["path"]).read_bytes() == parent_bytes, "parent changed")
    package = {"schema": SCHEMA, "implementation": producer, "space": space, "parameters": state, "report": report, **FALSE}
    raw = _raw(package)
    _require(len(raw) <= codec.MAX_BYTES, "checkpoint exceeds byte bound")
    output.mkdir(parents=True)
    path = output / "family_checkpoint.json"
    path.write_bytes(raw)
    descriptor = {"schema": SCHEMA, "path": str(path), "sha256": _sha(raw)}
    _read(descriptor)
    return {"descriptor": descriptor, "report": report}


@codec._single_threaded
def infer_family_ridge_path(descriptor, reports):
    import torch
    saved, parameters = _read(descriptor)
    domain, rows = prepared._reports(reports)
    _require(domain == saved["space"]["domain_id"], "inference domain differs")
    codec._bind_producers(saved["space"], reports)
    values, mask, spans, coverage = codec._matrix(saved["space"], rows)
    with torch.no_grad():
        prediction = prepared._forward(torch, values, parameters)
        score, metrics = codec._objective(torch, prediction, values, mask, spans, saved["space"]["projections"])
    return {"schema": SCHEMA, "domain_id": domain, "checkpoint_sha256": descriptor["sha256"],
        "objective": float(score), **metrics, "coverage": coverage,
        "effective_feature_panel": prepared._feature_panel(values, mask),
        "training_steps": 0, "formulas_generated": False, "source_text_decoded": False, **FALSE}
