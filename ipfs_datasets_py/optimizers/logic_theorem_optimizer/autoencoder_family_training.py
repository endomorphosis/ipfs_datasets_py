"""Shared, masked family-projection learning for typed domain targets.

This auxiliary autoencoder reconstructs structural features of native formulas.
It does not translate source text, synthesize formulas, or establish a proof.
Domain decoders remain responsible for source/IR agreement. Missing projections
are masked, rather than becoming negative training examples. A family's weight
does not depend on its corpus frequency or number of native projection views.

Fresh heads use a deterministic, training-only SVD initialization; continuation
inherits a complete compatible structural head. Neither path changes a legal
text checkpoint or pretends an unrelated feature basis can inherit its weights.
"""
from __future__ import annotations

from collections import Counter
import copy
from functools import wraps
import hashlib
import json
import math
from pathlib import Path
import re
import time

SCHEMA = "native-family-denoising-autoencoder/v1"
MAX_ROWS = 8192
MAX_FEATURES = 4096
MAX_BYTES = 64 * 1024 * 1024
FALSE = {"qualified": False, "admitted": False, "formalized": False,
         "promotion_performed": False}


def _single_threaded(function):
    @wraps(function)
    def bounded(*args, **kwargs):
        import torch
        previous = torch.get_num_threads()
        torch.set_num_threads(1)
        try:
            return function(*args, **kwargs)
        finally:
            torch.set_num_threads(previous)
    return bounded


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _digest(value):
    return _sha(_raw(value))


def _implementation():
    from ...logic.formalization.autoencoder import family_training
    return {"trainer": _sha(Path(__file__).read_bytes()),
            "target_adapter": _sha(Path(family_training.__file__).read_bytes())}


def _atoms(value, path=(), depth=0):
    """Retain AST field/argument positions and tokenize concrete formula text."""
    _require(depth <= 32, "projection exceeds structural depth bound")
    if isinstance(value, dict):
        yield _raw([path, "object", sorted(value)]).decode()
        for key, child in sorted(value.items()):
            yield from _atoms(child, path + (key,), depth + 1)
    elif isinstance(value, list):
        yield _raw([path, "list", len(value)]).decode()
        for index, child in enumerate(value):
            yield from _atoms(child, path + (index,), depth + 1)
    elif isinstance(value, str):
        yield _raw([path, "string"]).decode()
        for index, token in enumerate(re.findall(r"\w+|[^\w\s]", value)):
            yield _raw([path, "token", index, token]).decode()
    else:
        yield _raw([path, "value", value]).decode()


def _reports(reports):
    from ...logic.formalization.autoencoder.family_training import validate_family_training_report
    _require(type(reports) in (list, tuple) and 1 <= len(reports) <= MAX_ROWS,
             "bounded nonempty family reports required")
    rows, identities, domain = [], set(), None
    for report in reports:
        validate_family_training_report(report)
        _require(len(_raw(report)) <= MAX_BYTES, "family report exceeds byte bound")
        domain = domain or report["domain_id"]
        _require(report["domain_id"] == domain, "mixed domain heads are not supported")
        _require(report["source_digest"] not in identities, "duplicate typed source in family batch")
        identities.add(report["source_digest"])
        targets = {}
        for row in report["projections"]:
            if not row["ready_for_training"]:
                continue
            key = row["projection_id"]
            _require(key not in targets, "duplicate native projection")
            descriptor = {name: row.get(name) for name in
                          ("logic_family", "profile", "representation_kind", "producer_id")}
            targets[key] = (descriptor, Counter(_atoms(row["payload"])))
        _require(targets, "no validated native projection targets in source")
        rows.append(targets)
    return domain, rows


def _split_keys(report):
    # Native report source_digest includes typed input. Also exclude identical
    # source bytes when multiple independently typed targets share one source.
    return {report["source_digest"], report.get("source_sha256")} - {None, ""}


def _producer_pins(reports):
    result = {}
    for report in reports:
        for name, digest in report["producer_pins"].items():
            _require(name not in result or result[name] == digest, "native target producers disagree")
            result[name] = digest
    return result


def _validate_producer_pins(pins):
    _require(type(pins) is dict and pins, "native target producer pins required")
    for name, digest in pins.items():
        _require(type(name) is str and re.fullmatch(r"ipfs_datasets_py(?:\.[A-Za-z_][A-Za-z_0-9]*)+", name),
                 "invalid native target producer")
        path = Path(__file__).resolve().parents[2].joinpath(*name.split(".")[1:])
        path = path.with_suffix(".py") if path.with_suffix(".py").is_file() else path / "__init__.py"
        _require(path.is_file() and _sha(path.read_bytes()) == digest, "native target producer changed")


def _bind_producers(space, reports):
    observed = _producer_pins(reports)
    _require(all(space["producer_pins"].get(name) == digest for name, digest in observed.items()),
             "target producers differ from fitted feature semantics")


def _space(domain, reports, rows):
    descriptors, tokens = {}, {}
    for row in rows:
        for name, (descriptor, atoms) in row.items():
            _require(name not in descriptors or descriptors[name] == descriptor,
                     "native projection semantics changed between sources")
            descriptors[name] = descriptor
            # Document frequency favors reusable grammar/structure over a
            # source-specific identifier repeated many times in one formula.
            tokens.setdefault(name, Counter()).update(atoms.keys())
    _require(len(tokens) <= MAX_FEATURES, "too many native projections")
    ranked = {name: sorted(counts, key=lambda atom: (-counts[atom], atom))
              for name, counts in tokens.items()}
    selected = {name: [] for name in ranked}
    # Round-robin budgeting gives every real projection a feature namespace.
    # No validation/test text participates in either ranking or truncation.
    active, used, index = sorted(ranked), 0, 0
    while active and used < MAX_FEATURES:
        following = []
        for name in active:
            if used >= MAX_FEATURES:
                break
            selected[name].append(ranked[name][index])
            used += 1
            if index + 1 < len(ranked[name]):
                following.append(name)
        active, index = following, index + 1
    columns = [[name, atom] for name in sorted(selected) for atom in sorted(selected[name])]
    _require(1 <= len(columns) <= MAX_FEATURES, "family vocabulary exceeds feature bound")
    return {"domain_id": domain, "projections": descriptors, "columns": columns,
            "training_sources": sorted(r["source_digest"] for r in reports),
            "training_split_keys": sorted(set().union(*(_split_keys(r) for r in reports))),
            "training_reports_sha256": _digest(reports),
            "feature_selection": {"method": "training_document_frequency_equal_projection_budget",
                "available_atoms": {name: len(value) for name, value in ranked.items()},
                "retained_atoms": {name: len(value) for name, value in selected.items()}},
            "normalization": "log1p_l2_per_native_projection", **FALSE}


def _matrix(space, rows):
    import torch
    names = sorted(space["projections"])
    spans, offset = {}, 0
    for name in names:
        width = sum(column[0] == name for column in space["columns"])
        spans[name] = (offset, offset + width)
        offset += width
    result = torch.zeros((len(rows), len(space["columns"])), dtype=torch.float64)
    masks = torch.zeros((len(rows), len(names)), dtype=torch.bool)
    coverage, unseen = [], set()
    for index, row in enumerate(rows):
        unseen.update(set(row) - set(names))
        for j, name in enumerate(names):
            if name not in row:
                continue
            descriptor, atoms = row[name]
            _require(descriptor == space["projections"][name], "projection identity differs from fitted head")
            start, end = spans[name]
            vocabulary = [column[1] for column in space["columns"][start:end]]
            block = torch.tensor([math.log1p(atoms[atom]) for atom in vocabulary], dtype=torch.float64)
            norm = float(torch.linalg.vector_norm(block))
            known = sum(atoms[atom] for atom in vocabulary)
            coverage.append({"row": index, "projection_id": name, "known_atoms": known,
                             "unknown_atoms": sum(atoms.values()) - known, "has_coverage": norm > 0})
            if norm > 0:
                result[index, start:end] = block / norm
                masks[index, j] = True
    return result, masks, spans, {"projections": coverage, "untrained_projection_ids": sorted(unseen)}


def _objective(torch, prediction, target, mask, spans, descriptors, *, population=None):
    """Macro family loss; optional unbiased minibatch frequency correction."""
    family_values, metrics = {}, {}
    for j, (name, (start, end)) in enumerate(spans.items()):
        valid = mask[:, j]
        if not bool(valid.any()):
            continue
        output, expected = prediction[valid, start:end], target[valid, start:end]
        mse = (output - expected).square().mean(dim=1)
        cosine = 1 - torch.nn.functional.cosine_similarity(output, expected, dim=1, eps=1e-8)
        value = (mse + .1 * cosine).mean()
        if population is not None:
            total, counts = population
            value = value * int(valid.sum()) * total / (len(mask) * counts[j])
        family = descriptors[name]["logic_family"]
        family_values.setdefault(family, []).append(value)
        metrics[name] = {"mse": float(mse.mean().detach()), "cosine_loss": float(cosine.mean().detach()),
                         "rows": int(valid.sum())}
    _require(family_values, "no covered native targets available for loss")
    if population is None:
        losses = {family: torch.stack(values).mean() for family, values in family_values.items()}
        objective = torch.stack(list(losses.values())).mean()
    else:
        # Include all training families/projections in the denominator even if
        # a particular minibatch has no example of a rare family.
        counts = Counter(row["logic_family"] for row in descriptors.values())
        losses = {family: sum(values) / counts[family] for family, values in family_values.items()}
        objective = sum(losses.values()) / len(counts)
    return objective, {"families": {k: float(v.detach()) for k, v in losses.items()}, "projections": metrics}


def _read(descriptor):
    _require(type(descriptor) is dict and set(descriptor) == {"schema", "path", "sha256"}
             and descriptor["schema"] == SCHEMA, "native family checkpoint descriptor required")
    path = Path(descriptor["path"])
    _require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES,
             "bounded regular family checkpoint required")
    raw = path.read_bytes()
    _require(_sha(raw) == descriptor["sha256"], "family checkpoint digest mismatch")
    saved = json.loads(raw)
    _require(set(saved) == {"schema", "implementation", "space", "parameters", "report", *FALSE}
             and saved["schema"] == SCHEMA and saved["implementation"] == _implementation(),
             "family checkpoint schema or implementation differs")
    _require(all(saved[k] is False and saved["space"][k] is False for k in FALSE),
             "structural training cannot grant authority")
    _validate_producer_pins(saved["space"]["producer_pins"])
    import torch
    width, latent = len(saved["space"]["columns"]), saved["report"]["latent_width"]
    _require(1 <= width <= MAX_FEATURES and type(latent) is int and 1 <= latent <= 64,
             "invalid family dimensions")
    parameters = [torch.tensor(p, dtype=torch.float64) for p in saved["parameters"]]
    _require(len(parameters) == 4 and [tuple(p.shape) for p in parameters] ==
             [(width, latent), (latent,), (latent, width), (width,)] and
             all(bool(torch.isfinite(p).all()) for p in parameters), "invalid family tensors")
    return saved, parameters


@_single_threaded
def train_family_projection_autoencoder(training_reports, validation_reports, *, output_dir,
        epochs=24, latent_width=16, learning_rate=.005, minibatch_size=32, denoising=.15,
        seed=1729, max_seconds=120, parent_descriptor=None):
    """Fit real native targets, select on validation, and save a standalone head.

    Validation never expands the feature vocabulary. No test input is accepted.
    Per-family nonregression is measured against the untouched initial head.
    This API returns ``{descriptor, report}``; inference requires the descriptor.
    """
    import torch
    _require(type(epochs) is int and 1 <= epochs <= 1000 and type(latent_width) is int and 1 <= latent_width <= 64
             and type(minibatch_size) is int and 1 <= minibatch_size <= 1024,
             "bounded integer training settings required")
    _require(type(seed) is int and 0 <= seed < 2**31, "invalid seed")
    for value, bound in ((learning_rate, .1), (denoising, .75), (max_seconds, 3600)):
        _require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= bound,
                 "finite bounded numerical settings required")
    _require(learning_rate > 0 and max_seconds > 0, "positive learning rate and deadline required")
    output = Path(output_dir).absolute()
    _require(not output.exists() and not output.is_symlink(), "fresh family output directory required")
    domain, train_rows = _reports(training_reports)
    other_domain, validation_rows = _reports(validation_reports)
    _require(domain == other_domain, "validation domain differs")
    train_keys = set().union(*(_split_keys(r) for r in training_reports))
    validation_keys = set().union(*(_split_keys(r) for r in validation_reports))
    _require(not train_keys & validation_keys, "training/validation source leakage")
    parent_raw = None
    if parent_descriptor is None:
        space = _space(domain, training_reports, train_rows)
        # Validation may bind producer identity but never contributes features.
        space["producer_pins"] = _producer_pins(list(training_reports) + list(validation_reports))
        parent = None
    else:
        parent, parameters = _read(parent_descriptor)
        parent_raw = Path(parent_descriptor["path"]).read_bytes()
        space = parent["space"]
        _require(space["domain_id"] == domain and parent["report"]["latent_width"] == latent_width,
                 "parent family architecture differs")
        _require(not set(space["training_split_keys"]) & validation_keys,
                 "historical training/validation source leakage")
        _require(parent["report"]["validation_reports_sha256"] == _digest(validation_reports),
                 "continuation requires the fixed original validation panel")
        space = copy.deepcopy(space)
        space["training_sources"] = sorted(set(space["training_sources"]) | {r["source_digest"] for r in training_reports})
        space["training_split_keys"] = sorted(set(space["training_split_keys"]) | train_keys)
        space["training_reports_sha256"] = _digest(training_reports)
    _bind_producers(space, list(training_reports) + list(validation_reports))
    training, masks, spans, train_coverage = _matrix(space, train_rows)
    tuning, tune_mask, _, coverage = _matrix(space, validation_rows)
    _require(not train_coverage["untrained_projection_ids"], "new family basis requires a fresh head")
    _require(bool(masks.any(dim=1).all()) and bool(tune_mask.any(dim=1).all()),
             "source has no vocabulary coverage in this head")
    _require(bool(masks.any(dim=0).all()), "every fitted projection needs training support")
    started = time.monotonic()
    generator = torch.Generator(device="cpu").manual_seed(seed)
    if parent is None:
        mean = training.mean(dim=0)
        centered = training - mean
        # SVD sees training data only. Pad with zero directions if rank is small.
        _, _, vectors = torch.linalg.svd(centered, full_matrices=False)
        basis = torch.zeros((training.shape[1], latent_width), dtype=torch.float64)
        rank = min(latent_width, vectors.shape[0])
        basis[:, :rank] = vectors[:rank].T
        parameters = [basis, -(mean @ basis), basis.T.clone(), mean.clone()]
    parameters = [p.detach().clone().requires_grad_() for p in parameters]
    initial = [p.detach().clone() for p in parameters]
    optimizer = torch.optim.AdamW(parameters, lr=learning_rate, weight_decay=.0001)
    forward = lambda x: torch.tanh(x @ parameters[0] + parameters[1]) @ parameters[2] + parameters[3]
    with torch.no_grad():
        baseline, before = _objective(torch, forward(tuning), tuning, tune_mask, spans, space["projections"])
    best_loss, best, after, selected = float(baseline), initial, before, 0
    history, steps = [], 0
    population = (len(training), masks.sum(dim=0).tolist())
    stopped = "epoch_budget"
    for epoch in range(epochs):
        if time.monotonic() - started >= max_seconds:
            stopped = "deadline"
            break
        permutation = torch.randperm(len(training), generator=generator)
        weighted, seen, aborted, maximum_gradient = 0., 0, False, 0.
        for offset in range(0, len(training), minibatch_size):
            if time.monotonic() - started >= max_seconds:
                aborted = True
                break
            indices = permutation[offset:offset + minibatch_size]
            clean = training[indices]
            corrupted = clean * (torch.rand(clean.shape, generator=generator) >= denoising)
            # Warmup followed by cosine decay, independent of validation scores.
            progress = (epoch + offset / len(training)) / epochs
            rate = min(1., (steps + 1) / 5) * (.1 + .9 * (1 + math.cos(math.pi * progress)) / 2)
            optimizer.param_groups[0]["lr"] = learning_rate * rate
            optimizer.zero_grad(set_to_none=True)
            loss, _ = _objective(torch, forward(corrupted), clean, masks[indices], spans,
                                 space["projections"], population=population)
            _require(bool(torch.isfinite(loss)), "nonfinite family loss")
            loss.backward()
            gradient = float(torch.nn.utils.clip_grad_norm_(parameters, 1.))
            _require(math.isfinite(gradient), "nonfinite family gradient")
            optimizer.step()
            steps += 1
            maximum_gradient = max(maximum_gradient, gradient)
            weighted += float(loss.detach()) * len(indices)
            seen += len(indices)
        if aborted:
            stopped = "deadline_partial_epoch_not_selected"
            break
        with torch.no_grad():
            score, metrics = _objective(torch, forward(tuning), tuning, tune_mask, spans, space["projections"])
        _require(bool(torch.isfinite(score)), "nonfinite family validation")
        eligible = (time.monotonic() - started < max_seconds and float(score) < best_loss and all(
            value <= before["families"][family] + 1e-9 for family, value in metrics["families"].items()))
        if eligible:
            best_loss, best, after, selected = float(score), [p.detach().clone() for p in parameters], metrics, epoch + 1
        history.append({"epoch": epoch + 1, "train_objective": weighted / seen,
                        "validation_objective": float(score), "selected": eligible,
                        "gradient_norm_max": maximum_gradient, "family_losses": metrics["families"]})
    _require(parent_raw is None or Path(parent_descriptor["path"]).read_bytes() == parent_raw,
             "parent checkpoint changed during training")
    observed = sorted({p["logic_family"] for p in space["projections"].values()})
    report = {"schema": SCHEMA, "domain_id": domain, "latent_width": latent_width,
        "training_rows": len(training), "validation_rows": len(tuning), "training_executed": steps > 0,
        "epochs_requested": epochs, "epochs_completed": len(history), "selected_epoch": selected,
        "optimizer_steps": steps, "stopping": stopped, "elapsed_seconds": time.monotonic() - started,
        "learning_rate": learning_rate, "minibatch_size": minibatch_size, "denoising": denoising, "seed": seed,
        "initialization": "complete_parent_structural_head" if parent else "training_only_deterministic_svd",
        "parent_descriptor": parent_descriptor, "parent_modified": False,
        "optimizer_state": "fresh_adamw", "vocabulary_scope": "original_training_only",
        "objective": "masked_macro_family_mse_plus_0.1_cosine_native_projection_features",
        "selection": "validation_macro_loss_with_each_family_nonregression_against_initial_head",
        "before": {"objective": float(baseline), **before}, "after": {"objective": best_loss, **after},
        "improved": selected > 0, "history": history, "trained_logic_families": observed,
        "families_without_validation": sorted(set(observed) - set(before["families"])),
        "training_coverage": train_coverage, "validation_coverage": coverage,
        "validation_reports_sha256": _digest(validation_reports),
        "training_reports_sha256": _digest(training_reports),
        "frontier": [r["frontier"] for r in list(training_reports) + list(validation_reports)],
        "feature_selection": space["feature_selection"],
        "source_text_decoder_trained": False, "lake_build_executed": False,
        "provider_calls": 0, "download_calls": 0, **FALSE}
    package = {"schema": SCHEMA, "implementation": _implementation(), "space": space,
               "parameters": [p.tolist() for p in best], "report": report, **FALSE}
    raw = _raw(package)
    _require(len(raw) <= MAX_BYTES, "family checkpoint exceeds byte bound")
    output.mkdir(parents=True)
    path = output / "family_checkpoint.json"
    with path.open("xb") as stream:
        stream.write(raw)
    descriptor = {"schema": SCHEMA, "path": str(path), "sha256": _sha(raw)}
    _read(descriptor)
    return {"descriptor": descriptor, "report": report}


@_single_threaded
def infer_family_projection_autoencoder(descriptor, reports):
    """Use saved weights to reconstruct features of validated native targets."""
    import torch
    saved, parameters = _read(descriptor)
    domain, rows = _reports(reports)
    _require(domain == saved["space"]["domain_id"], "inference domain differs")
    _bind_producers(saved["space"], reports)
    values, mask, spans, coverage = _matrix(saved["space"], rows)
    _require(bool(mask.any(dim=1).all()), "source has no covered projection in this head")
    with torch.no_grad():
        latent = torch.tanh(values @ parameters[0] + parameters[1])
        prediction = latent @ parameters[2] + parameters[3]
        loss, metrics = _objective(torch, prediction, values, mask, spans, saved["space"]["projections"])
    return {"schema": SCHEMA, "domain_id": domain, "checkpoint_sha256": descriptor["sha256"],
            "latent": latent.tolist(), "reconstructed_features": prediction.tolist(),
            "objective": float(loss), **metrics, "coverage": coverage,
            "formulas_generated": False, "source_text_decoded": False, **FALSE}
