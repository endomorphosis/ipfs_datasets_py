"""Opt-in, numerically identical prepared execution of the v2 family trainer.

Bounded call-local atom serialization and minibatch masks are prepared once.
Unused minibatch metric materialization is omitted; validation metrics, masked
macro-family arithmetic, calibration, clipping and selection remain unchanged.
A distinct source-bound artifact preserves old v1/v2 checkpoint loaders. This
auxiliary head reconstructs native structural features, not source text/formulas.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import copy
import math
from pathlib import Path
import time

from . import autoencoder_family_training as codec
from . import autoencoder_family_training_v2 as reference

SCHEMA = "native-family-calibrated-autoencoder/prepared-v3"
FALSE = dict(codec.FALSE)
EPS = 1e-12
_require, _raw, _sha, _digest = codec._require, codec._raw, codec._sha, codec._digest


def _implementation():
    return {"trainer": _sha(Path(__file__).read_bytes()),
            "reference_trainer": _sha(Path(reference.__file__).read_bytes()),
            "feature_codec": _sha(Path(codec.__file__).read_bytes()),
            "target_adapter": codec._implementation()["target_adapter"]}


_IMPORTED_IMPLEMENTATION = _implementation()


def _verify_implementation():
    _require(_implementation() == _IMPORTED_IMPLEMENTATION,
             "prepared family implementation changed since import")
    return dict(_IMPORTED_IMPLEMENTATION)


def _atom_encoder():
    """A bounded cache whose lifetime is one train/inference invocation."""
    import re

    @lru_cache(maxsize=8192)
    def wire(path, kind, scalar_type, arguments):
        # Type participates in the cache key: Python treats True == 1, while
        # their JSON atoms (and thus feature identities) must stay distinct.
        return _raw([path, kind, *arguments]).decode()

    def atoms(value, path=(), depth=0):
        _require(depth <= 32, "projection exceeds structural depth bound")
        if isinstance(value, dict):
            yield wire(path, "object", "keys", (tuple(sorted(value)),))
            for key, child in sorted(value.items()):
                yield from atoms(child, path + (key,), depth + 1)
        elif isinstance(value, list):
            yield wire(path, "list", "length", (len(value),))
            for index, child in enumerate(value):
                yield from atoms(child, path + (index,), depth + 1)
        elif isinstance(value, str):
            yield wire(path, "string", "string", ())
            for index, token in enumerate(re.findall(r"\w+|[^\w\s]", value)):
                yield wire(path, "token", "token", (index, token))
        else:
            yield wire(path, "value", _raw(value).decode(), (value,))

    return atoms, wire.cache_info


class _PreparedObjective:
    """Reuse identical target slices/masks across clean and noisy forwards."""
    def __init__(self, torch, target, mask, spans, descriptors, population):
        total, counts = population
        self.torch = torch
        self.denominators = Counter(row["logic_family"] for row in descriptors.values())
        self.groups = {}
        for j, (name, (start, end)) in enumerate(spans.items()):
            valid = mask[:, j]
            count = int(valid.sum())
            if count:
                self.groups.setdefault(descriptors[name]["logic_family"], []).append(
                    (start, end, valid, target[valid, start:end], count, total,
                     len(mask) * counts[j]))
        _require(self.groups, "no covered native targets available for loss")

    def __call__(self, prediction):
        torch = self.torch
        losses = []
        for family, blocks in self.groups.items():
            values = []
            for start, end, valid, expected, count, total, denominator in blocks:
                output = prediction[valid, start:end]
                mse = (output - expected).square().mean(dim=1)
                cosine = 1 - torch.nn.functional.cosine_similarity(output, expected, dim=1, eps=1e-8)
                value = (mse + .1 * cosine).mean()
                # Preserve v1/v2 multiplication/division order, including
                # zero-valued absent projections in the population denominator.
                values.append(value * count * total / denominator)
            losses.append(sum(values) / self.denominators[family])
        return sum(losses) / len(self.denominators)


def _reports(reports, *, atoms=None):
    from ...logic.formalization.autoencoder import family_training
    _require(type(reports) in (list, tuple) and 1 <= len(reports) <= codec.MAX_ROWS,
             "bounded nonempty native family reports required")
    atoms = atoms or _atom_encoder()[0]
    domain, identities, rows = None, set(), []
    for report in reports:
        if report.get("schema") == family_training.SCHEMA:
            family_training.validate_family_training_report(report)
        else:
            from ...logic.formalization.autoencoder.family_training_v2 import validate_family_training_report_v2
            validate_family_training_report_v2(report)
        _require(len(_raw(report)) <= codec.MAX_BYTES, "native report exceeds byte bound")
        domain = domain or report["domain_id"]
        _require(report["domain_id"] == domain, "mixed domain feature heads are not supported")
        _require(report["source_digest"] not in identities, "duplicate typed source")
        identities.add(report["source_digest"])
        projections = {}
        for target in report["projections"]:
            if not target["ready_for_training"]:
                continue
            name = target["projection_id"]
            _require(name not in projections, "duplicate native projection")
            descriptor = {key: target.get(key) for key in
                          ("logic_family", "profile", "representation_kind", "producer_id")}
            projections[name] = descriptor, Counter(atoms(target["payload"]))
        _require(projections, "source has no ready native projections")
        rows.append(projections)
    return domain, rows


def _forward(torch, inputs, parameters):
    return torch.tanh(inputs @ parameters[0] + parameters[1]) @ parameters[2] + parameters[3]


def _calibrate_decoder(torch, parameters, training, masks, spans, ridge):
    """Solve a regularized residual fit using training rows and presence only.

    Validation is intentionally not an argument. Each native projection uses
    only the rows where its actual target is present. The prior decoder is the
    ridge center, which preserves unsupported latent directions on continuation.
    """
    result = [value.detach().clone() for value in parameters]
    observations = []
    with torch.no_grad():
        latent = torch.tanh(training @ parameters[0] + parameters[1])
        design = torch.cat((latent, torch.ones((len(training), 1), dtype=latent.dtype)), dim=1)
        for index, (name, (start, end)) in enumerate(spans.items()):
            present = masks[:, index]
            _require(bool(present.any()), "calibration projection lacks training rows")
            x, y = design[present], training[present, start:end]
            prior = torch.cat((parameters[2][:, start:end], parameters[3][None, start:end]))
            residual = y - x @ prior
            gram = x.T @ x / len(x) + ridge * torch.eye(x.shape[1], dtype=x.dtype)
            correction = torch.linalg.solve(gram, x.T @ residual / len(x))
            _require(bool(torch.isfinite(correction).all()), "nonfinite decoder calibration")
            fitted = prior + correction
            result[2][:, start:end] = fitted[:-1]
            result[3][start:end] = fitted[-1]
            observations.append({"projection_id": name, "training_rows": len(x),
                "train_mse_before": float(residual.square().mean()),
                "train_mse_after": float((y - x @ fitted).square().mean()),
                "correction_norm": float(torch.linalg.vector_norm(correction))})
    return result, observations


def _select_decoder_families(torch, initial, candidate, tuning, mask, spans, descriptors):
    """Merge only independently improved decoder blocks with a fixed encoder."""
    _require(all(torch.equal(initial[i], candidate[i]) for i in (0, 1)),
             "family-local selection requires an identical shared encoder")
    with torch.no_grad():
        _, before = codec._objective(torch, _forward(torch, tuning, initial), tuning, mask, spans, descriptors)
        _, proposed = codec._objective(torch, _forward(torch, tuning, candidate), tuning, mask, spans, descriptors)
        chosen = {family for family, loss in proposed["families"].items()
                  if loss < before["families"][family] - EPS}
        result = [p.detach().clone() for p in initial]
        for name, (start, end) in spans.items():
            if descriptors[name]["logic_family"] in chosen:
                result[2][:, start:end] = candidate[2][:, start:end]
                result[3][start:end] = candidate[3][start:end]
        value, after = codec._objective(torch, _forward(torch, tuning, result), tuning, mask, spans, descriptors)
        _require(all(after["families"][family] <= loss + EPS for family, loss in before["families"].items()),
                 "family block selection changed an unrelated reconstruction")
    return result, float(value), after, {"selected_families": sorted(chosen),
        "before": before, "candidate": proposed, "after": after,
        "selection_used_validation": True, "fit_used_validation": False}


def _read(descriptor):
    import json
    import torch
    _require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"},
             "closed native checkpoint descriptor required")
    _verify_implementation()
    if descriptor["schema"] in (codec.SCHEMA, reference.SCHEMA):
        return reference._read(descriptor)
    _require(descriptor["schema"] == SCHEMA, "unsupported family checkpoint schema")
    path = Path(descriptor["path"])
    _require(path.is_absolute() and path.is_file() and not path.is_symlink()
             and path.stat().st_size <= codec.MAX_BYTES, "bounded regular checkpoint required")
    raw = path.read_bytes()
    _require(_sha(raw) == descriptor["sha256"], "family checkpoint digest differs")
    saved = json.loads(raw)
    _require(type(saved) is dict and set(saved) ==
             {"schema", "implementation", "space", "parameters", "report", *FALSE}
             and saved["schema"] == SCHEMA and saved["implementation"] == _implementation(),
             "family v2 schema or numerical producer changed")
    _require(all(saved[key] is False and saved["space"][key] is False for key in FALSE),
             "feature checkpoints cannot grant authority")
    space = saved["space"]
    codec._validate_producer_pins(space["producer_pins"])
    columns = space["columns"]
    _require(type(columns) is list and 1 <= len(columns) <= codec.MAX_FEATURES
             and columns == sorted(columns) and len({tuple(c) for c in columns}) == len(columns)
             and all(type(c) is list and len(c) == 2 and c[0] in space["projections"] and type(c[1]) is str for c in columns),
             "invalid fitted feature columns")
    width, latent = len(columns), saved["report"]["latent_width"]
    _require(type(latent) is int and 1 <= latent <= 64, "invalid latent dimension")
    parameters = [torch.tensor(p, dtype=torch.float64) for p in saved["parameters"]]
    _require(len(parameters) == 4 and [tuple(p.shape) for p in parameters] ==
             [(width, latent), (latent,), (latent, width), (width,)]
             and all(bool(torch.isfinite(p).all()) for p in parameters), "invalid saved numerical tensors")
    _require(saved["report"]["selected_parameters_sha256"] == _digest(saved["parameters"]),
             "saved training parameter identity differs")
    return saved, parameters


def _settings(epochs, latent_width, minibatch_size, patience, learning_rate, denoising, ridge, seed, max_seconds):
    for value, bound in ((epochs, 256), (latent_width, 64), (minibatch_size, 1024), (patience, 256)):
        _require(type(value) is int and 1 <= value <= bound, "bounded integer training settings required")
    _require(type(seed) is int and 0 <= seed < 2**31, "bounded seed required")
    for value, lower, upper in ((learning_rate, 0., .1), (ridge, 0., 1.), (max_seconds, 0., 3600.)):
        _require(type(value) in (int, float) and math.isfinite(value) and lower < value <= upper,
                 "finite positive bounded optimization settings required")
    _require(type(denoising) in (int, float) and math.isfinite(denoising) and 0 <= denoising <= .75,
             "bounded denoising required")


def _feature_panel(matrix, mask):
    groups = {}
    for index, (values, present) in enumerate(zip(matrix.tolist(), mask.tolist())):
        groups.setdefault(_digest([values, present]), []).append(index)
    return {"rows": len(matrix), "distinct_retained_feature_vectors": len(groups),
        "colliding_row_groups": [indices for indices in groups.values() if len(indices) > 1],
        "interpretation": "distinct source identities may become identical after training-vocabulary filtering"}


@codec._single_threaded
def train_family_projection_autoencoder_prepared(training_reports, validation_reports, *, output_dir,
        parent_descriptor=None, epochs=12, latent_width=16, learning_rate=.001,
        minibatch_size=32, denoising=.05, ridge=.001, patience=4, seed=1729, max_seconds=120):
    """Calibrate, refine and save a fresh candidate using no test observations.

    v1 and v2 checkpoint parents are supported on an unchanged feature basis and
    fixed validation panel. Expanded logic-family bases require a fresh head.
    All tensor bytes are inherited on continuation; calibration is a training
    update, not an initialization that replaces the existing latent model.
    """
    import torch
    call_started = time.monotonic()
    producer = _verify_implementation()
    input_digest = _digest([training_reports, validation_reports, parent_descriptor])
    atoms, cache_info = _atom_encoder()
    _settings(epochs, latent_width, minibatch_size, patience, learning_rate, denoising, ridge, seed, max_seconds)
    output = Path(output_dir).absolute()
    _require(not output.exists() and not output.is_symlink(), "fresh v2 family output required")
    domain, training_rows = _reports(training_reports, atoms=atoms)
    other, validation_rows = _reports(validation_reports, atoms=atoms)
    _require(domain == other, "validation domain differs")
    train_keys = set().union(*(codec._split_keys(r) for r in training_reports))
    valid_keys = set().union(*(codec._split_keys(r) for r in validation_reports))
    _require(not train_keys & valid_keys, "training/validation source leakage")
    parent_raw = None
    if parent_descriptor is None:
        space = codec._space(domain, training_reports, training_rows)
        space["producer_pins"] = codec._producer_pins(list(training_reports) + list(validation_reports))
        parameters = None
    else:
        parent, parameters = _read(parent_descriptor)
        parent_raw = Path(parent_descriptor["path"]).read_bytes()
        space = copy.deepcopy(parent["space"])
        _require(space["domain_id"] == domain and parent["report"]["latent_width"] == latent_width,
                 "parent domain or architecture differs")
        _require(not set(space["training_split_keys"]) & valid_keys, "historical source split leakage")
        _require(parent["report"]["validation_reports_sha256"] == _digest(validation_reports),
                 "continuation requires the original validation panel")
        space["training_sources"] = sorted(set(space["training_sources"]) | {r["source_digest"] for r in training_reports})
        space["training_split_keys"] = sorted(set(space["training_split_keys"]) | train_keys)
        space["training_reports_sha256"] = _digest(training_reports)
    codec._bind_producers(space, list(training_reports) + list(validation_reports))
    training, masks, spans, train_coverage = codec._matrix(space, training_rows)
    validation, validation_mask, _, validation_coverage = codec._matrix(space, validation_rows)
    _require(not train_coverage["untrained_projection_ids"], "expanded native families require a new feature head")
    _require(bool(masks.any(dim=1).all()) and bool(validation_mask.any(dim=1).all())
             and bool(masks.any(dim=0).all()), "every source/projection requires training vocabulary coverage")
    started = time.monotonic()
    if parameters is None:
        mean = training.mean(dim=0)
        _, _, vectors = torch.linalg.svd(training - mean, full_matrices=False)
        basis = torch.zeros((training.shape[1], latent_width), dtype=torch.float64)
        rank = min(latent_width, len(vectors))
        basis[:, :rank] = vectors[:rank].T
        parameters = [basis, -(mean @ basis), basis.T.clone(), mean.clone()]
    initial = [p.detach().clone() for p in parameters]
    with torch.no_grad():
        initial_loss, initial_metrics = codec._objective(torch, _forward(torch, validation, initial),
            validation, validation_mask, spans, space["projections"])
    best, best_loss, after = initial, float(initial_loss), initial_metrics
    calibration = {"status": "not_run_deadline", "selected_families": [], "training_projections": []}
    if time.monotonic() - started < max_seconds:
        proposal, calibration_rows = _calibrate_decoder(torch, initial, training, masks, spans, ridge)
        calibration.update(status="discarded_due_deadline", training_projections=calibration_rows, ridge=ridge,
            proposal_parameters_sha256=_digest([p.tolist() for p in proposal]))
        if time.monotonic() - started < max_seconds:
            best, best_loss, after, calibration = _select_decoder_families(torch, initial, proposal,
                validation, validation_mask, spans, space["projections"])
            calibration.update(status="executed", training_projections=calibration_rows, ridge=ridge,
                proposal_parameters_sha256=_digest([p.tolist() for p in proposal]))
    calibration_loss = best_loss
    parameters = [p.detach().clone().requires_grad_() for p in best]
    optimizer = torch.optim.Adam(parameters, lr=learning_rate)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    population = (len(training), masks.sum(dim=0).tolist())
    preparation_seconds = time.monotonic() - call_started
    optimization_started = time.monotonic()
    history, steps, selected_epoch, stale, stopped = [], 0, 0, 0, "epoch_budget"
    for epoch in range(epochs):
        if time.monotonic() - started >= max_seconds:
            stopped = "deadline"
            break
        order = torch.randperm(len(training), generator=generator)
        weighted, seen, aborted = 0., 0, False
        for offset in range(0, len(training), minibatch_size):
            if time.monotonic() - started >= max_seconds:
                aborted = True
                break
            indices = order[offset:offset + minibatch_size]
            clean = training[indices]
            optimizer.zero_grad(set_to_none=True)
            objective = _PreparedObjective(torch, clean, masks[indices], spans, space["projections"], population)
            clean_loss = objective(_forward(torch, clean, parameters))
            loss = clean_loss
            if denoising:
                corrupted = clean * (torch.rand(clean.shape, generator=generator) >= denoising)
                noisy_loss = objective(_forward(torch, corrupted, parameters))
                loss = .75 * clean_loss + .25 * noisy_loss
            _require(bool(torch.isfinite(loss)), "nonfinite native training loss")
            loss.backward()
            norm = float(torch.nn.utils.clip_grad_norm_(parameters, 1.))
            _require(math.isfinite(norm), "nonfinite native training gradient")
            progress = (epoch + offset / len(training)) / epochs
            rate = learning_rate * min(1., (steps + 1) / 5) * (.1 + .9 * (1 + math.cos(math.pi * progress)) / 2)
            optimizer.param_groups[0]["lr"] = rate
            optimizer.step()
            steps += 1
            weighted += float(loss.detach()) * len(indices)
            seen += len(indices)
        if aborted:
            stopped = "deadline_partial_epoch_not_selected"
            break
        with torch.no_grad():
            score, metrics = codec._objective(torch, _forward(torch, validation, parameters), validation,
                validation_mask, spans, space["projections"])
        _require(bool(torch.isfinite(score)), "nonfinite native validation loss")
        selected = time.monotonic() - started < max_seconds and float(score) < best_loss - EPS and all(
            value <= after["families"][family] + EPS for family, value in metrics["families"].items())
        if selected:
            best, best_loss, after = [p.detach().clone() for p in parameters], float(score), metrics
            selected_epoch, stale = epoch + 1, 0
        else:
            stale += 1
        history.append({"epoch": epoch + 1, "training_objective": weighted / seen,
            "validation_objective": float(score), "validation_families": metrics["families"], "selected": selected})
        if stale >= patience:
            stopped = "validation_patience"
            break
    optimization_seconds = time.monotonic() - optimization_started
    _require(parent_raw is None or Path(parent_descriptor["path"]).read_bytes() == parent_raw,
             "parent changed during fitting")
    _require(all(after["families"][family] <= value + EPS for family, value in initial_metrics["families"].items()),
             "selected family regressed against initialization")
    observed = sorted({p["logic_family"] for p in space["projections"].values()})
    state = [p.tolist() for p in best]
    report = {"schema": SCHEMA, "domain_id": domain, "latent_width": latent_width,
        "training_rows": len(training), "validation_rows": len(validation), "epochs_requested": epochs,
        "epochs_completed": len(history), "optimizer_steps": steps, "selected_epoch": selected_epoch,
        "decoder_calibration": calibration, "calibrated_validation_objective": calibration_loss,
        "training_executed": calibration["status"] in ("executed", "discarded_due_deadline") or steps > 0,
        "initialization": "complete_parent_structural_head" if parent_descriptor else "training_only_deterministic_svd",
        "initial_parameters_sha256": _digest([p.tolist() for p in initial]),
        "selected_parameters_sha256": _digest(state), "parent_descriptor": parent_descriptor,
        "parent_modified": False, "vocabulary_scope": "original_training_only", "optimizer_state": "fresh_adam",
        "objective": "masked_macro_family_native_projection_reconstruction",
        "training_objective": "0.75_clean_plus_0.25_denoising_mse_plus_0.1_cosine" if denoising else "clean_mse_plus_0.1_cosine",
        "selection": "validation_family_block_calibration_then_monotone_joint_refinement",
        "before": {"objective": float(initial_loss), **initial_metrics},
        "after": {"objective": best_loss, **after}, "improved": best_loss < float(initial_loss) - EPS,
        "history": history, "stopping": stopped, "elapsed_seconds": time.monotonic() - started,
        "settings": {"learning_rate": learning_rate, "denoising": denoising, "ridge": ridge,
            "minibatch_size": minibatch_size, "patience": patience, "seed": seed, "max_seconds": max_seconds},
        "trained_logic_families": observed, "families_without_validation": sorted(set(observed) - set(after["families"])),
        "training_coverage": train_coverage, "validation_coverage": validation_coverage,
        "effective_feature_panels": {"training": _feature_panel(training, masks),
            "validation": _feature_panel(validation, validation_mask)},
        "training_reports_sha256": _digest(training_reports), "validation_reports_sha256": _digest(validation_reports),
        "feature_selection": space["feature_selection"],
        "frontier": [r["frontier"] for r in list(training_reports) + list(validation_reports)],
        "source_text_decoder_trained": False, "lake_build_executed": False,
        "provider_calls": 0, "download_calls": 0, **FALSE}
    report["prepared_execution"] = {"producer": producer, "reference_schema": reference.SCHEMA,
        "semantics": "same_masked_macro_family_objective_and_selection",
        "atom_cache": cache_info()._asdict(), "preparation_seconds": preparation_seconds,
        "optimization_seconds": optimization_seconds}
    _require(_verify_implementation() == producer, "prepared producer drift during fitting")
    _require(_digest([training_reports, validation_reports, parent_descriptor]) == input_digest,
             "prepared family inputs changed during fitting")
    codec._validate_producer_pins(space["producer_pins"])
    package = {"schema": SCHEMA, "implementation": producer, "space": space,
        "parameters": state, "report": report, **FALSE}
    raw = _raw(package)
    _require(len(raw) <= codec.MAX_BYTES, "prepared family artifact exceeds byte bound")
    output.mkdir(parents=True)
    path = output / "family_checkpoint.json"
    with path.open("xb") as stream:
        stream.write(raw)
    descriptor = {"schema": SCHEMA, "path": str(path), "sha256": _sha(raw)}
    _read(descriptor)
    return {"descriptor": descriptor, "report": report}


@codec._single_threaded
def infer_family_projection_autoencoder_prepared(descriptor, reports):
    import torch
    saved, parameters = _read(descriptor)
    domain, rows = _reports(reports)
    _require(domain == saved["space"]["domain_id"], "inference domain differs")
    codec._bind_producers(saved["space"], reports)
    values, mask, spans, coverage = codec._matrix(saved["space"], rows)
    _require(bool(mask.any(dim=1).all()), "source has no covered projection")
    with torch.no_grad():
        latent = torch.tanh(values @ parameters[0] + parameters[1])
        prediction = latent @ parameters[2] + parameters[3]
        objective, metrics = codec._objective(torch, prediction, values, mask, spans, saved["space"]["projections"])
    _verify_implementation()
    return {"schema": SCHEMA, "domain_id": domain, "checkpoint_sha256": descriptor["sha256"],
        "latent": latent.tolist(), "reconstructed_features": prediction.tolist(), "objective": float(objective),
        **metrics, "coverage": coverage, "formulas_generated": False, "source_text_decoded": False, **FALSE}
