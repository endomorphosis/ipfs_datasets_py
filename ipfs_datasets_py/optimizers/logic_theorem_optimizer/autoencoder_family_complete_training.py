"""Matched Adam/ridge training on complete compositional native feature bases.

Both strategies consume the exact same training-only vocabulary and masked
macro-family objective. Existing checkpoint formats and trainers are untouched.
This is structural reconstruction; source-language decoders are separate.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import time

from . import autoencoder_family_training as codec
from . import autoencoder_family_training_prepared as prepared
from . import autoencoder_family_ridge_path as ridge
from . import autoencoder_family_complete_features as features

SCHEMA = "native-family-complete-autoencoder/v1"
MAX_BYTES = 256 * 1024 * 1024


def _pins():
    return {"trainer": codec._sha(Path(__file__).read_bytes()),
        "features": codec._sha(Path(features.__file__).read_bytes()),
        "ridge_kernel": ridge._implementation()}


def _score(torch, parameters, panel):
    return codec._objective(torch, prepared._forward(torch, panel["validation"], parameters),
        panel["validation"], panel["validation_mask"], panel["spans"], panel["space"]["projections"])


def _select(torch, prior, candidate, panel):
    return prepared._select_decoder_families(torch, prior, candidate, panel["validation"],
        panel["validation_mask"], panel["spans"], panel["space"]["projections"])


@codec._single_threaded
def train_complete_family_autoencoder(training_reports, validation_reports, *, output_dir,
        strategy="ridge_path", latent_width=8, epochs=24, minibatch_size=6, seed=1729,
        required_families=(), max_features=features.MAX_FEATURES):
    import torch
    started = time.perf_counter()
    codec._require(strategy in {"ridge_path", "adam"}, "explicit ridge_path or adam strategy required")
    codec._require(all(type(value) is int and 1 <= value <= limit for value, limit in (
        (latent_width, 64), (epochs, 256), (minibatch_size, 1024))) and type(seed) is int and 0 <= seed < 2**31,
        "bounded architecture/training settings required")
    output = Path(output_dir).absolute()
    codec._require(not output.exists(), "fresh complete family output required")
    producer = _pins()
    input_sha = codec._digest([training_reports, validation_reports])
    panel = features.prepare(training_reports, validation_reports, max_features=max_features)
    x, mask, space = panel["training"], panel["training_mask"], panel["space"]
    codec._require(bool(mask.any(dim=0).all()) and bool(mask.any(dim=1).all())
        and bool(panel["validation_mask"].any(dim=1).all()), "uncovered native source or projection")
    mean = x.mean(dim=0)
    _, _, vectors = torch.linalg.svd(x - mean, full_matrices=False)
    basis = torch.zeros((x.shape[1], latent_width), dtype=x.dtype)
    rank = min(latent_width, len(vectors))
    basis[:, :rank] = vectors[:rank].T
    initial = [basis, -(mean @ basis), basis.T.clone(), mean.clone()]
    with torch.no_grad():
        before, before_metrics = _score(torch, initial, panel)
    observed = {row["logic_family"] for row in space["projections"].values()}
    codec._require(set(required_families) <= observed & set(before_metrics["families"]),
                   "required family missing actual training/tuning evidence")
    best, best_loss, best_metrics = [p.clone() for p in initial], float(before), before_metrics
    history, steps, presented = [], 0, 0
    preparation_seconds = time.perf_counter() - started
    with torch.no_grad():
        penalties = (.0001, .001, .01, .1) if strategy == "ridge_path" else (.001,)
        shrinkages = (.25, .5, 1.) if strategy == "ridge_path" else (1.,)
        corrections, factorizations = ridge._corrections(torch, initial, x, mask, panel["spans"], penalties)
        for penalty in penalties:
            for shrinkage in shrinkages:
                proposal = [p.clone() for p in initial]
                for name, (start, end) in panel["spans"].items():
                    correction = corrections[penalty][name] * shrinkage
                    proposal[2][:, start:end] += correction[:-1]
                    proposal[3][start:end] += correction[-1]
                best, best_loss, best_metrics, selection = _select(torch, best, proposal, panel)
                history.append({"ridge": penalty, "shrinkage": shrinkage,
                    "validation_objective": best_loss, "selected_families": selection["selected_families"]})
    if strategy == "adam":
        parameters = [p.clone().requires_grad_() for p in best]
        optimizer = torch.optim.Adam(parameters, lr=.001)
        generator = torch.Generator().manual_seed(seed)
        population = (len(x), mask.sum(dim=0).tolist())
        for epoch in range(epochs):
            order = torch.randperm(len(x), generator=generator)
            for offset in range(0, len(x), minibatch_size):
                indices = order[offset:offset + minibatch_size]
                clean = x[indices]
                objective = prepared._PreparedObjective(torch, clean, mask[indices], panel["spans"], space["projections"], population)
                optimizer.zero_grad(set_to_none=True)
                noisy = clean * (torch.rand(clean.shape, generator=generator) >= .05)
                loss = .75 * objective(prepared._forward(torch, clean, parameters)) + .25 * objective(prepared._forward(torch, noisy, parameters))
                codec._require(bool(torch.isfinite(loss)), "nonfinite training loss")
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(parameters, 1.)
                codec._require(bool(torch.isfinite(norm)), "nonfinite gradient")
                progress = (epoch + offset / len(x)) / epochs
                optimizer.param_groups[0]["lr"] = .001 * min(1., (steps + 1) / 5) * (.1 + .9 * (1 + math.cos(math.pi * progress)) / 2)
                optimizer.step()
                steps += 1
                presented += len(indices)
            with torch.no_grad():
                score, metrics = _score(torch, parameters, panel)
                codec._require(bool(torch.isfinite(score)), "nonfinite validation loss")
                selected = float(score) < best_loss - 1e-12 and all(
                    value <= best_metrics["families"][family] + 1e-12 for family, value in metrics["families"].items())
                if selected:
                    best, best_loss, best_metrics = [p.detach().clone() for p in parameters], float(score), metrics
                history.append({"epoch": epoch + 1, "validation_objective": float(score), "selected": selected})
    codec._require(all(value <= before_metrics["families"][family] + 1e-12
        for family, value in best_metrics["families"].items()), "validation family regressed")
    state = [p.tolist() for p in best]
    report = {"schema": SCHEMA, "domain_id": space["domain_id"], "strategy": strategy,
        "latent_width": latent_width, "feature_count": len(space["columns"]), "training_executed": True,
        "training_rows": len(x), "validation_rows": len(panel["validation"]),
        "trained_logic_families": sorted(observed), "required_families": sorted(set(required_families)),
        "training_coverage": panel["training_coverage"], "validation_coverage": panel["validation_coverage"],
        "training_reports_sha256": codec._digest(training_reports), "validation_reports_sha256": codec._digest(validation_reports),
        "initial_parameters_sha256": codec._digest([p.tolist() for p in initial]),
        "selected_parameters_sha256": codec._digest(state), "training_atoms_pruned": 0,
        "before": {"objective": float(before), **before_metrics},
        "after": {"objective": best_loss, **best_metrics}, "history": history,
        "optimizer_steps": steps, "optimizer_row_presentations": presented, "gram_factorizations": factorizations,
        "preparation_seconds": preparation_seconds, "fit_seconds": time.perf_counter() - started,
        "effective_feature_panels": {"training": prepared._feature_panel(x, mask),
            "validation": prepared._feature_panel(panel["validation"], panel["validation_mask"])},
        "source_text_decoder_trained": False, "test_used_for_selection": False,
        "frontier": [row["frontier"] for row in training_reports], **codec.FALSE}
    codec._require(producer == _pins() and input_sha == codec._digest([training_reports, validation_reports]), "source or input drift")
    package = {"schema": SCHEMA, "implementation": producer, "space": space, "parameters": state, "report": report, **codec.FALSE}
    raw = codec._raw(package)
    codec._require(len(raw) <= MAX_BYTES, "checkpoint exceeds byte limit")
    output.mkdir(parents=True)
    path = output / "family_checkpoint.json"
    path.write_bytes(raw)
    descriptor = {"schema": SCHEMA, "path": str(path), "sha256": codec._sha(raw)}
    load_complete_family_checkpoint(descriptor)
    return {"descriptor": descriptor, "report": report}


def load_complete_family_checkpoint(descriptor):
    import torch
    codec._require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"}
        and descriptor["schema"] == SCHEMA, "closed complete family descriptor required")
    path = Path(descriptor["path"])
    codec._require(path.is_absolute() and path.is_file() and not path.is_symlink()
        and path.stat().st_size <= MAX_BYTES, "bounded regular checkpoint required")
    raw = path.read_bytes()
    codec._require(codec._sha(raw) == descriptor["sha256"], "checkpoint digest differs")
    saved = json.loads(raw)
    codec._require(set(saved) == {"schema", "implementation", "space", "parameters", "report", *codec.FALSE}
        and saved["schema"] == SCHEMA and saved["implementation"] == _pins(), "checkpoint schema or producer differs")
    codec._require(all(saved[key] is False and saved["space"][key] is False for key in codec.FALSE), "checkpoint cannot grant authority")
    space, latent = saved["space"], saved["report"]["latent_width"]
    columns = space["columns"]
    codec._require(space["schema"] == features.SCHEMA and type(latent) is int and 1 <= latent <= 64
        and 1 <= len(columns) <= features.MAX_FEATURES and columns == sorted(columns)
        and len({tuple(row) for row in columns}) == len(columns), "invalid feature architecture")
    codec._validate_producer_pins(space["producer_pins"])
    parameters = [torch.tensor(row, dtype=torch.float64) for row in saved["parameters"]]
    width = len(columns)
    codec._require([tuple(row.shape) for row in parameters] == [(width, latent), (latent,), (latent, width), (width,)]
        and all(bool(torch.isfinite(row).all()) for row in parameters), "invalid numerical tensors")
    codec._require(codec._digest(saved["parameters"]) == saved["report"]["selected_parameters_sha256"], "parameter identity differs")
    return saved, parameters


@codec._single_threaded
def infer_complete_family_autoencoder(descriptor, reports):
    import torch
    saved, parameters = load_complete_family_checkpoint(descriptor)
    x, mask, spans, coverage = features.encode_reports(saved["space"], reports)
    codec._require(bool(mask.any(dim=1).all()), "source has no covered projection")
    with torch.no_grad():
        output = prepared._forward(torch, x, parameters)
        score, metrics = codec._objective(torch, output, x, mask, spans, saved["space"]["projections"])
    return {"schema": SCHEMA, "domain_id": saved["space"]["domain_id"], "objective": float(score),
        **metrics, "coverage": coverage, "effective_feature_panel": prepared._feature_panel(x, mask),
        "checkpoint_sha256": descriptor["sha256"], "training_steps": 0,
        "source_text_decoded": False, "formulas_generated": False, **codec.FALSE}
