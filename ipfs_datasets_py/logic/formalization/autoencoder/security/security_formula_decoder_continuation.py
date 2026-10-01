"""Optional balanced continuation of the frozen SecurityIR production decoder.

This head predicts grammar productions, not security labels or logic families.
All learned tensors start at an existing v2/continuation checkpoint; the Legal
lexical buffer is frozen. Validation selects weights, while test rows are used
only after selection. Native family reconstruction is a separate training lane.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import time

from . import security_formula_decoder_v2 as base
from . import security_formula_grammar_v2 as grammar
from . import security_autoencoder_checkpoint as portable

SCHEMA = "security-formula-production-continuation@1"
REPORT_SCHEMA = "security-learned-formula-continuation-candidate@1"
FILES = base.FILES
MAX_BYTES = 16 * 1024 * 1024
AUTHORITY = base._AUTHORITY
_json = base._json
_sha = base._sha


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _pins():
    return {"continuation_sha256": _sha(Path(__file__).read_bytes()),
            "base_decoder": base._implementation()}


def _parent(checkpoint):
    _require(type(checkpoint) is dict, "explicit pinned parent descriptor required")
    if checkpoint.get("schema") == base.SCHEMA:
        return base.load_security_formula_decoder_v2(checkpoint)
    if checkpoint.get("schema") == SCHEMA:
        return load_security_formula_decoder_continuation(checkpoint)
    raise ValueError("parent must be a frozen v2 production decoder or continuation")


def _history(parent):
    return deepcopy(parent["training"].get("split_history", parent["training"].get("splits")))


def prepare_security_production_samples(samples, *, historical_splits=None):
    """Check exact source and alpha/literal shape roles before any optimization."""
    _require(type(samples) is list and 3 <= len(samples) <= 384, "bounded explicit train/validation/test samples required")
    splits = {key: [] for key in ("train", "validation", "test")}
    observed, identities, source_roles, shape_roles = {}, set(), {}, {}
    history = {key: [] for key in splits}
    if historical_splits is not None:
        _require(type(historical_splits) is dict and set(historical_splits) == set(splits), "invalid historical splits")
        for role, rows in historical_splits.items():
            _require(type(rows) is list and len(rows) <= 4096, "bounded split history required")
            for row in rows:
                for key in ("source_sha256", "program_shape_sha256"):
                    base._digest(row[key])
                source_roles.setdefault(row["source_sha256"], set()).add(role)
                shape_roles.setdefault(row["program_shape_sha256"], set()).add(role)
                history[role].append(deepcopy(row))
    _require(all(len(value) == 1 for value in (*source_roles.values(), *shape_roles.values())), "historical source/shape split leakage")
    for sample in samples:
        _require(type(sample) is dict and set(sample) in ({"id", "split", "source"}, {"id", "split", "source", "source_sha256"}), "closed source sample required")
        identifier, role, source = sample["id"], sample["split"], sample["source"]
        _require(type(identifier) is str and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", identifier) and identifier not in identities, "unique bounded sample id required")
        _require(role in splits and type(source) is str, "explicit sample split and source required")
        raw = source.encode()
        digest, shape = _sha(raw), grammar.source_shape(raw)
        _require(sample.get("source_sha256", digest) == digest, "source hash differs")
        for value, roles in ((digest, source_roles), (shape, shape_roles)):
            _require(not roles.get(value, set()) - {role}, "cross-split source or normalized program shape leakage")
            roles.setdefault(value, set()).add(role)
        item = {"id": identifier, "source_sha256": digest, "program_shape_sha256": shape}
        splits[role].append(item)
        if not any(old["source_sha256"] == digest for old in history[role]):
            history[role].append(item)
        identities.add(identifier)
        observed[identifier] = grammar.parse_formula_source(raw)
    _require(all(splits.values()) and sum(len(row["nodes"]) for row in observed.values()) <= 8192, "nonempty disjoint splits and bounded node count required")
    _require(all(len(rows) <= 4096 for rows in history.values()), "split history exceeds bound")
    return {"observed": observed, "splits": splits, "split_history": history}


def _numeric(prepared, split, lexical):
    values, targets, sizes = [], [], []
    for item in prepared["splits"][split]:
        parsed = prepared["observed"][item["id"]]
        values.extend(base._numeric_rows(parsed, lexical))
        targets.extend(grammar.PRODUCTIONS.index(node["teacher_production"]) for node in parsed["nodes"])
        sizes.extend([len(parsed["nodes"])] * len(parsed["nodes"]))
    return values, targets, sizes


def _metrics(parameters, lexical, prepared, split):
    import torch
    values, labels, _ = _numeric(prepared, split, lexical)
    with torch.no_grad():
        logits = base._forward(torch, torch.tensor(values, dtype=torch.float64), parameters)
        losses = torch.nn.functional.cross_entropy(logits, torch.tensor(labels), reduction="none")
        predicted = logits.argmax(1).tolist()
    classes = sorted(set(labels))
    per_class = {grammar.PRODUCTIONS[c]: float(losses[torch.tensor([label == c for label in labels])].mean()) for c in classes}
    exact = raw_exact = count = total = 0
    loaded = {"weights": {"parameters": [value.detach().tolist() for value in parameters], "lexical": lexical}}
    for item in prepared["splits"][split]:
        observed = prepared["observed"][item["id"]]
        guesses = base._predictions(loaded, observed)
        correct = [guess["production"] == node["teacher_production"] for guess, node in zip(guesses, observed["nodes"])]
        raw_correct = [guess["raw_production"] == node["teacher_production"] for guess, node in zip(guesses, observed["nodes"])]
        count += sum(correct); total += len(correct); exact += all(correct); raw_exact += all(raw_correct)
    return {"programs": len(prepared["splits"][split]), "productions": len(labels),
            "macro_cross_entropy": sum(per_class.values()) / len(per_class), "per_production_cross_entropy": per_class,
            "raw_production_accuracy": sum(a == b for a, b in zip(predicted, labels)) / len(labels),
            "constrained_production_accuracy": count / total,
            "raw_exact_programs": raw_exact, "constrained_exact_programs": exact}


def _balanced_loss(torch, logits, labels, normalized_row_weights, *, label_smoothing):
    """Unbiased minibatch estimate of the globally normalized weighted mean.

    Renormalizing by each minibatch weight sum would erase balancing for a
    singleton minibatch and bias larger minibatches with unequal class mixes.
    """
    per_row = torch.nn.functional.cross_entropy(logits, labels, reduction="none", label_smoothing=label_smoothing)
    return (per_row * normalized_row_weights).mean()


def train_security_formula_decoder_continuation(*, samples, parent_checkpoint, output,
        epochs=24, learning_rate=.003, minibatch_size=128, weight_decay=.0001,
        label_smoothing=.02, regression_tolerance=.02, max_seconds=120., seed=1729):
    """Train weighted production cross-entropy with warmup/cosine AdamW.

    Source length and inverse-square-root production frequency weights are
    computed from training rows only. Validation macro loss selects a state
    only if no observed production exceeds the explicit regression tolerance.
    Parent optimizer moments are not reused: this is a new optimizer recipe.
    """
    _require(type(epochs) is int and 1 <= epochs <= 256, "bounded epoch budget required")
    _require(type(minibatch_size) is int and 1 <= minibatch_size <= 1024, "bounded minibatch size required")
    _require(type(seed) is int and 0 <= seed < 2**31, "bounded seed required")
    for value, low, high, name in ((learning_rate, 0., .1, "learning rate"), (max_seconds, 0., 300., "deadline")):
        _require(type(value) in (int, float) and math.isfinite(value) and low < value <= high, "invalid " + name)
    for value, high, name in ((weight_decay, .1, "weight decay"), (label_smoothing, .2, "label smoothing"), (regression_tolerance, .5, "regression tolerance")):
        _require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= high, "invalid " + name)
    output = portable._namespace(Path(output), fresh=True, excluded=(Path(parent_checkpoint["output"]),))
    parent = _parent(parent_checkpoint)
    prepared = prepare_security_production_samples(samples, historical_splits=_history(parent))
    lexical = deepcopy(parent["weights"]["lexical"])
    values, labels, sizes = _numeric(prepared, "train", lexical)
    counts = Counter(labels)
    row_weights = [1. / (math.sqrt(counts[label]) * size) for label, size in zip(labels, sizes)]
    mean_weight = sum(row_weights) / len(row_weights)
    row_weights = [weight / mean_weight for weight in row_weights]
    import torch
    started = time.monotonic()
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        parameters = [torch.tensor(value, dtype=torch.float64, requires_grad=True) for value in parent["weights"]["parameters"]]
        initial = [value.detach().tolist() for value in parameters]
        initial_sha = _sha(_json(initial))
        optimizer = torch.optim.AdamW(parameters, lr=float(learning_rate), weight_decay=float(weight_decay))
        generator = torch.Generator(device="cpu").manual_seed(seed)
        data, target, weights = torch.tensor(values, dtype=torch.float64), torch.tensor(labels), torch.tensor(row_weights, dtype=torch.float64)
        before = _metrics(parameters, lexical, prepared, "validation")
        best_metrics, best_parameters, selected_epoch = before, initial, 0
        steps_per_epoch = math.ceil(len(values) / minibatch_size)
        planned_steps = epochs * steps_per_epoch
        warmup_steps = max(1, math.ceil(.1 * planned_steps))
        epochs_log, steps, stopped = [], 0, "epoch_budget"
        for epoch in range(epochs):
            order = torch.randperm(len(values), generator=generator)
            losses, norms, rates = [], [], []
            for offset in range(0, len(values), minibatch_size):
                if time.monotonic() - started >= max_seconds:
                    stopped = "deadline"; break
                index = order[offset:offset + minibatch_size]
                progress = (steps - warmup_steps) / max(1, planned_steps - warmup_steps)
                rate = float(learning_rate) * ((steps + 1) / warmup_steps if steps < warmup_steps else .1 + .9 * (1. + math.cos(math.pi * progress)) / 2.)
                for group in optimizer.param_groups: group["lr"] = rate
                optimizer.zero_grad()
                logits = base._forward(torch, data[index], parameters)
                loss = _balanced_loss(torch, logits, target[index], weights[index], label_smoothing=float(label_smoothing))
                _require(bool(torch.isfinite(loss)), "nonfinite production loss")
                loss.backward()
                norm = float(torch.nn.utils.clip_grad_norm_(parameters, 5.))
                _require(math.isfinite(norm), "nonfinite production gradient")
                optimizer.step(); steps += 1
                losses.append(float(loss.detach())); norms.append(norm); rates.append(rate)
            if not losses:
                break
            candidate = _metrics(parameters, lexical, prepared, "validation")
            selected = (stopped != "deadline" and time.monotonic() - started < max_seconds and
                candidate["macro_cross_entropy"] < best_metrics["macro_cross_entropy"] and all(
                value <= before["per_production_cross_entropy"][name] + regression_tolerance
                for name, value in candidate["per_production_cross_entropy"].items()))
            if selected:
                best_metrics, best_parameters, selected_epoch = candidate, [value.detach().tolist() for value in parameters], epoch + 1
            epochs_log.append({"epoch": epoch + 1, "steps": len(losses), "training_loss": sum(losses) / len(losses),
                "max_gradient_norm": max(norms), "learning_rate_first": rates[0], "learning_rate_last": rates[-1],
                "validation": candidate, "selected": selected})
            if stopped == "deadline": break
        _require(steps > 0, "deadline exhausted before any optimization step")
        selected_tensors = [torch.tensor(value, dtype=torch.float64) for value in best_parameters]
        # Test never participates in vocabulary, balancing, gradients, or selection.
        metrics = {split: _metrics(selected_tensors, lexical, prepared, split) for split in ("train", "validation", "test")}
    finally:
        torch.set_num_threads(previous_threads)
    _require(_parent(parent_checkpoint) == parent, "parent changed during continuation")
    base_config = parent["config"].get("base_decoder_config", parent["config"])
    config = {"schema": SCHEMA, "base_decoder_config": base_config, "producer": _pins()}
    weights_state = {"schema": SCHEMA, "parameters": best_parameters, "lexical": lexical}
    training = {"schema": SCHEMA, "parent_descriptor": deepcopy(parent_checkpoint), "parent_modified": False,
        "initial_parameters_sha256": initial_sha, "final_parameters_sha256": _sha(_json(best_parameters)),
        "inherited_lexical_sha256": _sha(_json(lexical)), "weights_sha256": _sha(_json(weights_state)),
        "initialization": "exact complete parent tensors; lexical buffer frozen; new AdamW state",
        "algorithm": {"name": "source_and_production_balanced_AdamW_warmup_cosine/v1", "epochs": epochs,
            "learning_rate": learning_rate, "minibatch_size": minibatch_size, "weight_decay": weight_decay,
            "label_smoothing": label_smoothing, "regression_tolerance": regression_tolerance, "seed": seed,
            "max_seconds": max_seconds, "production_weighting": "inverse_sqrt_train_frequency",
            "source_weighting": "inverse_source_node_count", "selection": "validation_macro_CE_with_each_production_nonregression_against_initial_head"},
        "training_production_counts": {grammar.PRODUCTIONS[key]: value for key, value in sorted(counts.items())},
        "training_row_weights_sha256": _sha(_json(row_weights)), "splits": prepared["splits"], "split_history": prepared["split_history"],
        "before_validation": before, "metrics": metrics, "epochs": epochs_log, "optimizer_steps": steps, "training_executed": True,
        "selected_epoch": selected_epoch, "selected_parameters_changed": initial_sha != _sha(_json(best_parameters)),
        "test_used_for_fit_or_selection": False, "validation_used_for_selection": True,
        "source_bodies_persisted": False, "blind_generalization_claim": False,
        "teacher_fallback_at_inference": False, "logic_family_heads_trained": False,
        "elapsed_seconds": time.monotonic() - started, "stopped_reason": stopped,
        "provider_calls": 0, "download_calls": 0, **AUTHORITY}
    payloads = {"config.json": _json(config), "weights.json": _json(weights_state), "training.json": _json(training)}
    manifest = {"schema": SCHEMA, "files": {name: {"sha256": _sha(raw), "bytes": len(raw)} for name, raw in payloads.items()}, **AUTHORITY}
    raw_manifest = _json(manifest)
    _require(all(len(raw) <= MAX_BYTES for raw in (*payloads.values(), raw_manifest)), "package exceeds artifact bound")
    output.mkdir(parents=True, mode=0o700)
    for name, raw in {**payloads, "manifest.json": raw_manifest}.items(): portable._write(output / name, raw)
    descriptor = {"schema": SCHEMA, "output": str(output), "manifest_sha256": _sha(raw_manifest),
        "weights_sha256": _sha(payloads["weights.json"]), **AUTHORITY}
    load_security_formula_decoder_continuation(descriptor)
    return descriptor


def load_security_formula_decoder_continuation(checkpoint):
    """Load a standalone source-pinned child without requiring its parent files."""
    _require(type(checkpoint) is dict and set(checkpoint) == {"schema", "output", "manifest_sha256", "weights_sha256", *AUTHORITY}, "closed continuation descriptor required")
    _require(checkpoint["schema"] == SCHEMA and all(checkpoint[key] is False for key in AUTHORITY), "invalid continuation identity/authority")
    base._digest(checkpoint["manifest_sha256"]); base._digest(checkpoint["weights_sha256"])
    output = portable._namespace(Path(checkpoint["output"]))
    _require({p.name for p in output.iterdir()} == FILES, "closed continuation package required")
    raw = portable._read(output / "manifest.json", MAX_BYTES)
    _require(_sha(raw) == checkpoint["manifest_sha256"], "manifest drift")
    manifest = portable._decode(raw)
    _require(type(manifest) is dict and set(manifest) == {"schema", "files", *AUTHORITY} and manifest["schema"] == SCHEMA and all(manifest[key] is False for key in AUTHORITY), "invalid manifest")
    _require(type(manifest["files"]) is dict and set(manifest["files"]) == FILES - {"manifest.json"}, "closed artifact list required")
    values = {}
    for name, entry in manifest["files"].items():
        raw = portable._read(output / name, MAX_BYTES)
        _require(type(entry) is dict and set(entry) == {"sha256", "bytes"} and type(entry["bytes"]) is int and len(raw) == entry["bytes"] and _sha(raw) == entry["sha256"], "artifact drift")
        values[name] = portable._decode(raw)
    _require(manifest["files"]["weights.json"]["sha256"] == checkpoint["weights_sha256"], "weight pin differs")
    config, weights, training = values["config.json"], values["weights.json"], values["training.json"]
    _require(type(config) is dict and set(config) == {"schema", "base_decoder_config", "producer"} and config["schema"] == SCHEMA and config["producer"] == _pins(), "continuation producer drift")
    original = config["base_decoder_config"]
    _require(type(original) is dict and original == base._config(original.get("lexical_width"), original.get("latent_width")), "base decoder configuration drift")
    _require(type(weights) is dict and set(weights) == {"schema", "parameters", "lexical"} and weights["schema"] == SCHEMA, "closed weight state required")
    lexical = weights["lexical"]
    _require(type(lexical) is dict and set(lexical) == {"keys", "weights", "width", "initializer_sha256", "parent_checkpoint_sha256", "published_source_pin"}, "closed inherited lexical state required")
    keys = lexical["keys"]
    _require(type(keys) is list and 1 <= len(keys) <= 8192 and keys == sorted(set(keys)) and all(type(key) is str and re.fullmatch(r"token:[a-z0-9]{3,}", key) for key in keys), "invalid lexical keys")
    _require(lexical["width"] == original["lexical_width"], "lexical dimensions differ")
    base._digest(lexical["initializer_sha256"]); base._digest(lexical["parent_checkpoint_sha256"])
    if lexical["published_source_pin"] is not None:
        from .published_legal_initializer import validate_published_legal_source_pin
        pin = validate_published_legal_source_pin(lexical["published_source_pin"])
        _require(pin["state_sha256"] == lexical["parent_checkpoint_sha256"], "published lexical parent differs")
    base._matrix(lexical["weights"], len(keys), lexical["width"])
    latent = original["latent_width"]
    shapes = ((len(grammar.FEATURES) + lexical["width"], latent), (latent, None), (latent, len(grammar.PRODUCTIONS)), (len(grammar.PRODUCTIONS), None))
    _require(type(weights["parameters"]) is list and len(weights["parameters"]) == 4, "four trained tensors required")
    for value, shape in zip(weights["parameters"], shapes): base._matrix(value, *shape)
    training_fields = {"schema", "parent_descriptor", "parent_modified", "initial_parameters_sha256", "final_parameters_sha256",
        "inherited_lexical_sha256", "weights_sha256", "initialization", "algorithm", "training_production_counts",
        "training_row_weights_sha256", "splits", "split_history", "before_validation", "metrics", "epochs",
        "optimizer_steps", "training_executed", "selected_epoch", "selected_parameters_changed", "test_used_for_fit_or_selection",
        "validation_used_for_selection", "source_bodies_persisted", "blind_generalization_claim", "teacher_fallback_at_inference",
        "logic_family_heads_trained", "elapsed_seconds", "stopped_reason", "provider_calls", "download_calls", *AUTHORITY}
    _require(type(training) is dict and set(training) == training_fields and training.get("schema") == SCHEMA and all(training.get(key) is False for key in AUTHORITY), "invalid training authority or receipt schema")
    for key in ("parent_modified", "test_used_for_fit_or_selection", "teacher_fallback_at_inference", "logic_family_heads_trained", "source_bodies_persisted", "blind_generalization_claim"):
        _require(training.get(key) is False, "invalid training scope")
    _require(training.get("weights_sha256") == _sha(_json(weights)) and training.get("final_parameters_sha256") == _sha(_json(weights["parameters"])) and training.get("inherited_lexical_sha256") == _sha(_json(lexical)), "training weight lineage differs")
    _require(type(training.get("optimizer_steps")) is int and training["optimizer_steps"] > 0 and training.get("validation_used_for_selection") is True and training["training_executed"] is True, "actual optimization and selection receipt required")
    return {"descriptor": deepcopy(checkpoint), "manifest": manifest, "config": config, "weights": weights, "training": training}


def decode_security_formula_continuation(*, source_bytes, checkpoint, source_path, model_enabled=True, weight_ablation=None):
    """Use actual selected child tensors; source agreement is checked separately."""
    _require(type(source_bytes) is bytes and type(source_path) is str and 0 < len(source_path) <= 512 and type(model_enabled) is bool, "explicit bytes/path/model selection required")
    _require(weight_ablation in (None, "zero_production_heads"), "unsupported weight ablation")
    loaded = load_security_formula_decoder_continuation(checkpoint)
    report = {"schema": REPORT_SCHEMA, "checkpoint": deepcopy(checkpoint), "source_path": source_path,
        "source_sha256": _sha(source_bytes), "status": "unsupported", "learned_formula_count": 0,
        "predicted_productions": [], "candidate": None, "candidate_source": None,
        "validation": {"source_AST_equivalent": False, "native_lowering_complete": False},
        "frontiers": [], "model_enabled": model_enabled, "weight_ablation": weight_ablation,
        "neural_forward_count": 0, "training_steps": 0, "provider_calls": 0, "download_calls": 0,
        "solver_calls": 0, **AUTHORITY}
    if not model_enabled:
        report["frontiers"] = ["learned model disabled; no production fallback"]
        return report
    try:
        observed = grammar.parse_formula_source(source_bytes)
    except grammar.UnsupportedFormulaSource as exc:
        report["frontiers"] = [str(exc)]; return report
    predictions = base._predictions(loaded, observed, weight_ablation=weight_ablation)
    report.update(predicted_productions=predictions, neural_forward_count=1)
    try:
        candidate, tree = grammar.compose_candidate(observed, [row["production"] for row in predictions])
    except ValueError as exc:
        report.update(status="rejected", frontiers=[str(exc)]); return report
    report.update(status="candidate", candidate=tree, candidate_source=candidate.decode(), frontiers=["source AST agreement only; typed semantic projection and independent contracts remain required"])
    report["validation"]["source_AST_equivalent"] = True
    return report


def validate_security_formula_continuation(report, *, source_bytes, checkpoint):
    expected = decode_security_formula_continuation(source_bytes=source_bytes, checkpoint=checkpoint,
        source_path=report["source_path"], model_enabled=report["model_enabled"], weight_ablation=report["weight_ablation"])
    _require(_json(report) == _json(expected), "continuation decode/source replay differs")
    return expected
