"""Decoder-aware, fixed-shape native IR autoencoding on local CPU.

This separate lineage learns categorical logits for each exact path/value leaf.
Inputs are existing native compiler structural features, NOT source text. The
immutable native readout validates generated records; its discrete failures are
selection observations, never fabricated differentiable syntax/proof losses.
Only tuning observations select weights. Lake/semantic qualification is external.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
import re
import time

from . import autoencoder_projection_features as features
from . import native_formal_decoder as readout

SCHEMA = "native-formula-checkpoint/v1"
RUNTIME_VERSION = "native_formula_v1"
LINEAGE_ID = RUNTIME_VERSION
OBJECTIVE = {"id": "native-path-value-cross-entropy/v1", "categorical_weight": 1.0,
    "group_reduction": "mean_over_nonconstant_leaf_groups", "numeric_reconstruction_weight": 0.0,
    "syntax_gradient": False, "selection": "tuning_valid_then_exact_projection_then_exact_leaf_then_ce"}
FALSE = {**features.FALSE, "proof_authority": False, "execution_authority": False,
    "source_semantics_verified": False, "source_binding_verified": False, "lake_executed": False,
    "independent_text_to_logic": False, "publication_performed": False}
MAX_ROWS = 256
MAX_FEATURES = 2048
MAX_CORPUS_BYTES = 8 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ROOT = Path(features.__file__).resolve().parents[2]
_BASE_SOURCES = {"native_formula_training.py": Path(__file__),
    "native_formal_decoder.py": Path(readout.__file__),
    "autoencoder_projection_features.py": Path(features.__file__)}
_IMPORTED_SOURCE_HASHES = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                         for name, path in _BASE_SOURCES.items()}


class NativeFormulaError(ValueError):
    """Unsupported shapes, unknown atoms and provenance drift fail closed."""


def _require(condition, message):
    if not condition:
        raise NativeFormulaError(message)


def _raw(value):
    try:
        result = features._raw(value)
    except (ValueError, TypeError, RecursionError) as exc:
        raise NativeFormulaError("finite bounded JSON required") from exc
    _require(len(result) <= MAX_CHECKPOINT_BYTES, "checkpoint byte bound exceeded")
    return result


def _copy(value):
    return json.loads(_raw(value))


def checkpoint_digest(checkpoint):
    return hashlib.sha256(_raw(checkpoint)).hexdigest()


def _pins(domain):
    # Do not retarget an already-imported foreign parser or editable install.
    from ...logic.autoformal.tree_pin import require_workspace_logic_tree, workspace_root
    expected = workspace_root().resolve() / "ipfs_datasets_py"
    _require(_ROOT == expected, "native numerical helpers loaded outside pinned workspace logic tree")
    require_workspace_logic_tree()
    current = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in _BASE_SOURCES.items()}
    _require(current == _IMPORTED_SOURCE_HASHES, "imported native numerical source changed; restart required")
    return {"numerical": current, "validators": readout._validator_sources(domain, space_schema=features.SPACE_SCHEMA)}


def _torch():
    import torch
    _require(torch.get_num_threads() == 1, "native_formula_v1 requires caller-managed torch.set_num_threads(1)")
    return torch


def _targets(values, name):
    _require(type(values) in (list, tuple) and 1 <= len(values) <= MAX_ROWS,
             f"{name} requires 1..{MAX_ROWS} native targets")
    rows = [features._target(value) for value in values]
    _require(len(_raw(rows)) <= MAX_CORPUS_BYTES, f"{name} corpus byte bound exceeded")
    return rows


def _groups(space):
    basis, _ = readout._basis(space)
    groups, offset = [], 0
    for name in space["projection_ids"]:
        for path, candidates in basis[name].items():
            groups.append({"projection_id": name, "path": list(path),
                           "columns": [offset + item[0] for item in candidates]})
        offset += sum(len(values) for values in basis[name].values())
    return groups


def _data(space, head, targets):
    matrix, sources, coverage = features._matrix(space, targets)
    _require(not any(row["unknown_atoms"] for row in coverage),
             "unknown path/value atoms are outside native_formula_v1 training vocabulary")
    labels, expected = [], []
    groups = _groups(space)
    for values, target in zip(matrix, targets):
        projections = {row["projection_id"]: row["expression"] for row in target["projections"]}
        for name in space["projection_ids"]:
            expression = projections[name]
            _require(readout._shape(expression) == head["projections"][name]["shape"],
                     "variable shape requires a separate presence/length decoder")
            # Training targets must themselves satisfy the real native owner.
            readout._validate_expression(space["domain_id"], name, space["projections"][name], expression)
        row_labels = []
        for group in groups:
            chosen = [index for index, column in enumerate(group["columns"]) if values[column] > 0]
            _require(len(chosen) == 1, "each native leaf needs one known categorical value")
            row_labels.append(chosen[0])
        labels.append(row_labels)
        expected.append({name: projections[name] for name in space["projection_ids"]})
    return {"matrix": matrix, "labels": labels, "sources": sources, "coverage": coverage, "expected": expected}


def _config(width, latent_width, learning_rate, batch_size, seed):
    torch = _torch()
    _require(type(latent_width) is int and 1 <= latent_width <= 64, "latent width must be 1..64")
    _require(type(learning_rate) in (int, float) and math.isfinite(learning_rate)
             and 0 < learning_rate <= .1, "learning rate must be within (0,.1]")
    _require(type(batch_size) is int and 1 <= batch_size <= 32, "batch size must be 1..32")
    _require(type(seed) is int and 0 <= seed < 2**31, "bounded deterministic seed required")
    return {"architecture": "native-feature-tanh-linear-categorical/v1", "input_width": width,
        "latent_width": latent_width, "learning_rate": float(learning_rate), "batch_size": batch_size,
        "seed": seed, "device": "cpu", "dtype": "float64", "torch_version": str(torch.__version__),
        "optimizer": "Adam", "betas": [.9, .999], "eps": 1e-8, "temperature": 0,
        "gradient_clip_norm": 5.0, "objective": OBJECTIVE}


def _parameters(config):
    torch = _torch()
    generator = torch.Generator(device="cpu").manual_seed(config["seed"])
    width, latent = config["input_width"], config["latent_width"]
    shapes = {"encoder_weight": (width, latent), "encoder_bias": (latent,),
              "decoder_weight": (latent, width), "decoder_bias": (width,)}
    return {name: (torch.randn(shape, generator=generator, dtype=torch.float64) * .1
                  if len(shape) == 2 else torch.zeros(shape, dtype=torch.float64)).requires_grad_()
            for name, shape in shapes.items()}


def _forward(parameters, inputs):
    latent = (inputs @ parameters["encoder_weight"] + parameters["encoder_bias"]).tanh()
    return latent, latent @ parameters["decoder_weight"] + parameters["decoder_bias"]


def _categorical_loss(logits, labels, groups):
    torch = _torch()
    terms = [torch.nn.functional.cross_entropy(logits[:, group["columns"]], labels[:, index])
             for index, group in enumerate(groups) if len(group["columns"]) > 1]
    _require(bool(terms), "no variable categorical leaves; decoder-aware training would have zero objective")
    return torch.stack(terms).mean()


def _snapshot(parameters, optimizer, progress):
    torch = _torch()
    moments = {}
    for name, parameter in parameters.items():
        item = optimizer.state.get(parameter, {})
        moments[name] = {"step": int(item.get("step", 0)),
            "exp_avg": item.get("exp_avg", torch.zeros_like(parameter)).detach().tolist(),
            "exp_avg_sq": item.get("exp_avg_sq", torch.zeros_like(parameter)).detach().tolist()}
    return {"parameters": {name: value.detach().tolist() for name, value in parameters.items()},
            "adam": moments, "progress": dict(progress)}


def _optimizer(config, parameters):
    torch = _torch()
    return torch.optim.Adam(list(parameters.values()), lr=config["learning_rate"],
                            betas=tuple(config["betas"]), eps=config["eps"], foreach=False)


def build_native_formula_checkpoint(domain, training_targets, tuning_targets, *, projection_ids,
                                    latent_width=16, learning_rate=.01, batch_size=8, seed=1729):
    """Fit exact training-only vocabulary/shapes and initialize fresh weights.

    Both manifests are immutable on resume. Repeated structures under distinct
    source identities are counted openly; this is a reconstruction diagnostic,
    not an independent semantic generalization benchmark.
    """
    _require(domain in {"intent_ir", "security_ir", "ui_ux_ir"}, "unsupported native domain")
    pins = _pins(domain)
    training, tuning = _targets(training_targets, "training"), _targets(tuning_targets, "tuning")
    space = features.build_feature_space(domain, projection_ids, training)
    _require(len(space["columns"]) <= MAX_FEATURES, "native formula feature bound exceeded")
    head = readout.train_formal_decoder(space, training)
    _require(all(row["status"] == "ready" for row in head["projections"].values()),
             "variable shape requires a separate presence/length decoder")
    groups = _groups(space)
    _require(any(len(group["columns"]) > 1 for group in groups), "no variable categorical leaves")
    train, tune = _data(space, head, training), _data(space, head, tuning)
    _require(set(train["sources"]).isdisjoint(tune["sources"]), "training/tuning source leakage")
    config = _config(len(space["columns"]), latent_width, learning_rate, batch_size, seed)
    parameters = _parameters(config)
    state = _snapshot(parameters, _optimizer(config, parameters),
                      {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0, "pending_evaluation": False})
    value = {"schema": SCHEMA, "runtime_version": RUNTIME_VERSION, "lineage_id": LINEAGE_ID, "domain_id": domain,
        "feature_space": space, "decoder_head": head, "groups": groups, "config": config,
        "implementation": pins, "training_manifest_sha256": features.digest(training),
        "tuning_manifest_sha256": features.digest(tuning), "training_count": len(training), "tuning_count": len(tuning),
        "latest": state, "selected": {"parameters": _copy(state["parameters"]), "optimizer_steps": 0,
                                      "metrics": None, "selection_key": None},
        "parent_checkpoint_sha256": None, **FALSE}
    _require(_pins(domain) == pins, "native producer changed during preparation")
    validate_checkpoint(value)
    return value


def _tensor(value, template, *, nonnegative=False):
    torch = _torch()
    def check(items, shape):
        _require(type(items) is list and len(items) == shape[0], "numerical tensor shape differs")
        for item in items:
            if len(shape) > 1:
                check(item, shape[1:])
            else:
                _require(type(item) in (int, float) and math.isfinite(item) and (not nonnegative or item >= 0),
                         "nonfinite or invalid numerical tensor")
    check(value, tuple(template.shape))
    return torch.tensor(value, dtype=torch.float64)


def _restore(checkpoint):
    _require(type(checkpoint) is dict, "native formula checkpoint mapping required")
    _raw(checkpoint)
    keys = {"schema", "runtime_version", "lineage_id", "domain_id", "feature_space", "decoder_head", "groups", "config",
            "implementation", "training_manifest_sha256", "tuning_manifest_sha256", "training_count", "tuning_count",
            "latest", "selected", "parent_checkpoint_sha256", *FALSE}
    _require(set(checkpoint) == keys and checkpoint["schema"] == SCHEMA
             and checkpoint["runtime_version"] == RUNTIME_VERSION and checkpoint["lineage_id"] == LINEAGE_ID,
             "closed native formula checkpoint schema required")
    domain = checkpoint["domain_id"]
    _require(domain in {"intent_ir", "security_ir", "ui_ux_ir"}, "unsupported native domain")
    _require(all(checkpoint[key] is False for key in FALSE), "checkpoint cannot grant authority")
    _require(checkpoint["implementation"] == _pins(domain), "native formula producer provenance changed")
    for key in ("training_manifest_sha256", "tuning_manifest_sha256"):
        _require(type(checkpoint[key]) is str and _SHA.fullmatch(checkpoint[key]), "invalid immutable manifest hash")
    for key in ("training_count", "tuning_count"):
        _require(type(checkpoint[key]) is int and 1 <= checkpoint[key] <= MAX_ROWS, "invalid target count")
    parent = checkpoint["parent_checkpoint_sha256"]
    _require(parent is None or type(parent) is str and _SHA.fullmatch(parent), "invalid parent checkpoint hash")
    space, head = checkpoint["feature_space"], checkpoint["decoder_head"]
    expected_space = {"schema", "domain_id", "projection_ids", "projections", "columns", "training_sources",
                      "excluded_projection_ids", "training_targets_sha256", "normalization", *features.FALSE}
    _require(type(space) is dict and set(space) == expected_space and space["schema"] == features.SPACE_SCHEMA
             and space["domain_id"] == domain and 1 <= len(space["columns"]) <= MAX_FEATURES,
             "invalid native feature space")
    _require(space["normalization"] == "log1p_then_l2_per_projection"
             and all(space[k] is False for k in features.FALSE), "invalid native feature policy")
    _require(type(space["training_sources"]) is list and len(space["training_sources"]) == checkpoint["training_count"]
             and all(type(v) is str and _SHA.fullmatch(v) for v in space["training_sources"])
             and space["training_sources"] == sorted(set(space["training_sources"]))
             and space["training_targets_sha256"] == checkpoint["training_manifest_sha256"], "native training provenance differs")
    readout.validate_decoder(space, head)
    _require(all(row["status"] == "ready" for row in head["projections"].values()), "variable shape decoder unsupported")
    groups = _groups(space)
    _require(checkpoint["groups"] == groups and any(len(g["columns"]) > 1 for g in groups), "categorical group identity differs")
    config = checkpoint["config"]
    _require(type(config) is dict, "native formula config required")
    expected_config = _config(len(space["columns"]), config.get("latent_width"), config.get("learning_rate"),
                              config.get("batch_size"), config.get("seed"))
    _require(config == expected_config, "native formula config or torch version differs")
    parameters = _parameters(config)
    latest = checkpoint["latest"]
    _require(type(latest) is dict and set(latest) == {"parameters", "adam", "progress"}, "closed latest state required")
    progress = latest["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps", "pending_evaluation"},
             "closed progress required")
    _require(all(type(progress[k]) is int and 0 <= progress[k] < 2**31 for k in ("epochs_completed", "row_cursor", "optimizer_steps"))
             and type(progress["pending_evaluation"]) is bool, "invalid optimizer progress")
    count, batch = checkpoint["training_count"], config["batch_size"]
    _require(progress["row_cursor"] < count and progress["row_cursor"] % batch == 0,
             "invalid partial epoch cursor")
    _require(progress["optimizer_steps"] == progress["epochs_completed"] * math.ceil(count / batch)
             + progress["row_cursor"] // batch, "optimizer progress and batch cursor differ")
    _require(not progress["pending_evaluation"] or progress["row_cursor"] == 0 and progress["epochs_completed"] > 0,
             "invalid pending epoch evaluation")
    _require(type(latest["parameters"]) is dict and set(latest["parameters"]) == set(parameters)
             and type(latest["adam"]) is dict and set(latest["adam"]) == set(parameters), "incomplete parameters/Adam state")
    optimizer = _optimizer(config, parameters)
    torch = _torch()
    with torch.no_grad():
        for name, parameter in parameters.items():
            parameter.copy_(_tensor(latest["parameters"][name], parameter))
            item = latest["adam"][name]
            _require(type(item) is dict and set(item) == {"step", "exp_avg", "exp_avg_sq"}
                     and type(item["step"]) is int and item["step"] == progress["optimizer_steps"], "Adam step differs")
            optimizer.state[parameter] = {"step": torch.tensor(float(item["step"]), dtype=torch.float32),
                "exp_avg": _tensor(item["exp_avg"], parameter),
                "exp_avg_sq": _tensor(item["exp_avg_sq"], parameter, nonnegative=True)}
    selected = checkpoint["selected"]
    _require(type(selected) is dict and set(selected) == {"parameters", "optimizer_steps", "metrics", "selection_key"}
             and type(selected["parameters"]) is dict and set(selected["parameters"]) == set(parameters), "invalid selected state")
    _require(type(selected["optimizer_steps"]) is int and 0 <= selected["optimizer_steps"] <= progress["optimizer_steps"],
             "selected state exceeds latest optimizer step")
    for name, parameter in parameters.items():
        _tensor(selected["parameters"][name], parameter)
    if selected["metrics"] is None:
        _require(selected["selection_key"] is None and selected["optimizer_steps"] == 0, "unevaluated selection differs")
    else:
        _require(selected["selection_key"] == _selection_key(selected["metrics"]), "selected metrics/key differ")
        _require(selected["metrics"]["source_count"] == checkpoint["tuning_count"]
                 and selected["metrics"]["projection_count"] == checkpoint["tuning_count"] * len(space["projection_ids"]),
                 "selected observations belong to a different tuning corpus")
    return parameters, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)
    return checkpoint_digest(checkpoint)


def _readout(parameters, checkpoint, data):
    torch = _torch()
    with torch.no_grad():
        inputs = torch.tensor(data["matrix"], dtype=torch.float64)
        latent, logits = _forward(parameters, inputs)
        _require(bool(torch.isfinite(logits).all()), "nonfinite reconstructed logits")
        scores = torch.empty_like(logits)
        for group in checkpoint["groups"]:
            scores[:, group["columns"]] = logits[:, group["columns"]].softmax(dim=1)
        values = scores.tolist()
        labels = torch.tensor(data["labels"], dtype=torch.long)
        loss = float(_categorical_loss(logits, labels, checkpoint["groups"]))
    space = checkpoint["feature_space"]
    state_sha = features.digest({name: p.detach().tolist() for name, p in parameters.items()})
    inference = {"schema": "native-projection-feature-inference/v1", "feature_space_sha256": features.digest(space),
        "state_sha256": state_sha, "training_executed": False, "coverage": data["coverage"], **features.FALSE,
        "rows": [{"source_digest": source, "latent": hidden, "reconstructed_projection_features": {
            name: [row[i] for i, (projection, _) in enumerate(space["columns"]) if projection == name]
            for name in space["projection_ids"]}} for row, source, hidden in zip(values, data["sources"], latent.tolist())]}
    result = readout.decode_formal_features(space, checkpoint["decoder_head"], inference)
    return result, logits, loss


def _evaluate(parameters, checkpoint, data):
    decoded, logits, loss = _readout(parameters, checkpoint, data)
    facets = []
    for index, group in enumerate(checkpoint["groups"]):
        predicted = logits[:, group["columns"]].argmax(dim=1).tolist()
        facets.append({"projection_id": group["projection_id"], "path": group["path"],
            "classes": len(group["columns"]), "correct": sum(value == row[index] for value, row in zip(predicted, data["labels"])),
            "count": len(predicted)})
    exact, invalid, reasons = 0, 0, {}
    per_projection = {name: {"valid": 0, "exact": 0, "count": len(data["sources"])}
                      for name in checkpoint["feature_space"]["projection_ids"]}
    for row, expected in zip(decoded["rows"], data["expected"]):
        for prediction in row["projections"]:
            name = prediction["projection_id"]
            if prediction["status"] != "decoded_candidate":
                invalid += 1
                reason = prediction["reason"]
                reasons[reason] = reasons.get(reason, 0) + 1
                continue
            per_projection[name]["valid"] += 1
            if _raw(prediction["expression"]) == _raw(expected[name]):
                exact += 1
                per_projection[name]["exact"] += 1
    count = len(data["sources"]) * len(per_projection)
    return {"schema": "native-formula-metrics/v1", "categorical_cross_entropy": loss,
        "source_count": len(data["sources"]), "projection_count": count,
        "valid_projection_count": count - invalid, "exact_projection_count": exact,
        "invalid_projection_count": invalid, "invalid_reasons": reasons,
        "leaf_correct": sum(row["correct"] for row in facets), "leaf_count": sum(row["count"] for row in facets),
        "facets": facets, "projections": per_projection, "native_readout_executed": True,
        "family_backend_syntax_checked": False, "heldout_canary": False, **FALSE}


def _selection_key(metrics):
    keys = {"schema", "categorical_cross_entropy", "source_count", "projection_count", "valid_projection_count",
            "exact_projection_count", "invalid_projection_count", "invalid_reasons", "leaf_correct", "leaf_count",
            "facets", "projections", "native_readout_executed", "family_backend_syntax_checked", "heldout_canary", *FALSE}
    _require(type(metrics) is dict and set(metrics) == keys and metrics.get("schema") == "native-formula-metrics/v1"
             and all(metrics.get(key) is False for key in FALSE), "invalid selection metric authority/schema")
    _require(metrics.get("native_readout_executed") is True and metrics.get("heldout_canary") is False
             and metrics.get("family_backend_syntax_checked") is False, "invalid selection validation scope")
    for key in ("source_count", "projection_count", "valid_projection_count", "exact_projection_count",
                "invalid_projection_count", "leaf_correct", "leaf_count"):
        _require(type(metrics.get(key)) is int and 0 <= metrics[key] <= MAX_ROWS * MAX_FEATURES, "invalid metric count")
    _require(0 < metrics["source_count"] <= MAX_ROWS and metrics["projection_count"] > 0
             and 0 <= metrics["exact_projection_count"] <= metrics["valid_projection_count"] <= metrics["projection_count"]
             and metrics["valid_projection_count"] + metrics["invalid_projection_count"] == metrics["projection_count"]
             and 0 <= metrics["leaf_correct"] <= metrics["leaf_count"], "inconsistent decoded metric counts")
    loss = metrics.get("categorical_cross_entropy")
    _require(type(loss) in (int, float) and math.isfinite(loss) and loss >= 0, "invalid categorical metric loss")
    _require(type(metrics["facets"]) is list and 1 <= len(metrics["facets"]) <= MAX_FEATURES
             and type(metrics["projections"]) is dict and bool(metrics["projections"])
             and type(metrics["invalid_reasons"]) is dict, "closed metric detail containers required")
    for row in metrics["facets"]:
        _require(type(row) is dict and set(row) == {"projection_id", "path", "classes", "correct", "count"}
                 and type(row["projection_id"]) is str and row["projection_id"] in metrics["projections"]
                 and type(row["path"]) is list and type(row["classes"]) is int and 1 <= row["classes"] <= MAX_FEATURES
                 and type(row["count"]) is int and row["count"] == metrics["source_count"]
                 and type(row["correct"]) is int and 0 <= row["correct"] <= row["count"], "invalid facet observations")
    _require(sum(row["correct"] for row in metrics["facets"]) == metrics["leaf_correct"]
             and sum(row["count"] for row in metrics["facets"]) == metrics["leaf_count"], "facet totals differ")
    for row in metrics["projections"].values():
        _require(type(row) is dict and set(row) == {"valid", "exact", "count"}
                 and all(type(row[k]) is int for k in row)
                 and 0 <= row["exact"] <= row["valid"] <= row["count"] == metrics["source_count"],
                 "invalid projection observations")
    _require(sum(row["exact"] for row in metrics["projections"].values()) == metrics["exact_projection_count"]
             and sum(row["valid"] for row in metrics["projections"].values()) == metrics["valid_projection_count"]
             and sum(row["count"] for row in metrics["projections"].values()) == metrics["projection_count"],
             "projection totals differ")
    _require(all(type(k) is str and type(v) is int and v > 0 for k, v in metrics["invalid_reasons"].items())
             and sum(metrics["invalid_reasons"].values()) == metrics["invalid_projection_count"], "failure totals differ")
    return [metrics["valid_projection_count"], metrics["exact_projection_count"], metrics["leaf_correct"], -loss]


def train_native_formula(checkpoint, training_targets, tuning_targets, *, epochs=20, max_seconds=60,
                         max_optimizer_steps=None):
    """Backpropagate exact categorical reconstruction and select decoded candidates.

    The monotonic deadline is checked before every batch and tuning evaluation.
    An in-flight batch/evaluation and final checkpoint serialization may finish
    past it. A pending epoch evaluation is resumed before further updates.
    """
    started = time.monotonic()
    _require(type(epochs) is int and 1 <= epochs <= 1000, "epochs must be 1..1000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be within [0,3600]")
    _require(max_optimizer_steps is None or type(max_optimizer_steps) is int and 1 <= max_optimizer_steps <= 100000,
             "invalid optimizer step budget")
    checkpoint = _copy(checkpoint)
    initial_sha = checkpoint_digest(checkpoint)
    parameters, optimizer = _restore(checkpoint)
    parent_sha = initial_sha if checkpoint["latest"]["progress"]["optimizer_steps"] else None
    training, tuning = _targets(training_targets, "training"), _targets(tuning_targets, "tuning")
    _require(features.digest(training) == checkpoint["training_manifest_sha256"]
             and features.digest(tuning) == checkpoint["tuning_manifest_sha256"], "immutable training/tuning manifest differs")
    space, head = checkpoint["feature_space"], checkpoint["decoder_head"]
    train, tune = _data(space, head, training), _data(space, head, tuning)
    _require(set(train["sources"]).isdisjoint(tune["sources"]), "training/tuning source leakage")
    torch = _torch()
    inputs = torch.tensor(train["matrix"], dtype=torch.float64)
    labels = torch.tensor(train["labels"], dtype=torch.long)
    progress = dict(checkpoint["latest"]["progress"])
    initial_progress = dict(progress)
    target_epoch = progress["epochs_completed"] + epochs
    selected = _copy(checkpoint["selected"])
    batches, reports = [], []
    gradient_max, head_gradient_max = 0.0, 0.0
    before, after = None, None
    initial_parameter_sha = features.digest(checkpoint["latest"]["parameters"])
    reason = "epochs_complete"
    def expired():
        return time.monotonic() - started >= max_seconds
    def select(metrics):
        nonlocal selected
        key = _selection_key(metrics)
        # Original best is re-evaluated on resume, so saved observations alone
        # cannot manipulate selection or hide changed readout behavior.
        if selected["selection_key"] is None or key > selected["selection_key"]:
            selected = {"parameters": {name: p.detach().tolist() for name, p in parameters.items()},
                        "optimizer_steps": progress["optimizer_steps"], "metrics": metrics, "selection_key": key}
            return True
        return False
    if not expired():
        selected_parameters = {name: _tensor(selected["parameters"][name], parameter)
                               for name, parameter in parameters.items()}
        selected["metrics"] = _evaluate(selected_parameters, checkpoint, tune)
        selected["selection_key"] = _selection_key(selected["metrics"])
    if not expired():
        before = _evaluate(parameters, checkpoint, train)
    while progress["epochs_completed"] < target_epoch or progress["pending_evaluation"]:
        if expired():
            reason = "deadline"
            break
        if progress["pending_evaluation"]:
            metrics = _evaluate(parameters, checkpoint, tune)
            improved = select(metrics)
            reports.append({"epoch": progress["epochs_completed"], "optimizer_steps": progress["optimizer_steps"],
                            "tuning": metrics, "selected": improved})
            progress["pending_evaluation"] = False
            continue
        if max_optimizer_steps is not None and progress["optimizer_steps"] - initial_progress["optimizer_steps"] >= max_optimizer_steps:
            reason = "optimizer_step_budget"
            break
        order = list(range(len(training)))
        random.Random(checkpoint["config"]["seed"] + progress["epochs_completed"]).shuffle(order)
        batch = order[progress["row_cursor"]:progress["row_cursor"] + checkpoint["config"]["batch_size"]]
        optimizer.zero_grad(set_to_none=True)
        _, logits = _forward(parameters, inputs[batch])
        loss = _categorical_loss(logits, labels[batch], checkpoint["groups"])
        _require(bool(torch.isfinite(loss)), "nonfinite categorical training loss")
        loss.backward()
        _require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in parameters.values()),
                 "missing/nonfinite encoder or decoder gradient")
        gradient = torch.nn.utils.clip_grad_norm_(list(parameters.values()), checkpoint["config"]["gradient_clip_norm"])
        gradient_max = max(gradient_max, float(gradient))
        head_gradient_max = max(head_gradient_max, float(parameters["decoder_weight"].grad.norm()))
        optimizer.step()
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(batch)
        batches.append(float(loss.detach()))
        if progress["row_cursor"] == len(training):
            progress["row_cursor"] = 0
            progress["epochs_completed"] += 1
            progress["pending_evaluation"] = True
    if not expired():
        after = _evaluate(parameters, checkpoint, train)
    checkpoint["latest"] = _snapshot(parameters, optimizer, progress)
    checkpoint["selected"] = selected
    checkpoint["parent_checkpoint_sha256"] = parent_sha
    _require(_pins(checkpoint["domain_id"]) == checkpoint["implementation"], "native producer changed during training")
    validate_checkpoint(checkpoint)
    train_structures = {features.digest(row) for row in train["expected"]}
    report = {"schema": "native-formula-training/v1", "runtime_version": RUNTIME_VERSION, "lineage_id": LINEAGE_ID,
        "parent_checkpoint_sha256": parent_sha, "checkpoint_sha256": checkpoint_digest(checkpoint),
        "initial_checkpoint_sha256": initial_sha,
        "domain_id": checkpoint["domain_id"], "objective": OBJECTIVE,
        "projection_ids": list(space["projection_ids"]), "projection_descriptors": _copy(space["projections"]),
        "excluded_projection_ids": list(space["excluded_projection_ids"]),
        "epochs_requested": epochs, "epochs_completed": progress["epochs_completed"] - initial_progress["epochs_completed"],
        "optimizer_steps": progress["optimizer_steps"] - initial_progress["optimizer_steps"], "progress": progress,
        "selected_optimizer_steps": selected["optimizer_steps"], "selected_tuning": selected["metrics"],
        "training_before": before, "training_after": after, "epoch_reports": reports, "batch_losses": batches,
        "gradient_norm_max": gradient_max, "decoder_gradient_norm_max": head_gradient_max,
        "initial_parameter_sha256": initial_parameter_sha, "final_parameter_sha256": features.digest(checkpoint["latest"]["parameters"]),
        "training_count": len(training), "tuning_count": len(tuning),
        "tuning_structure_overlap_count": sum(features.digest(row) in train_structures for row in tune["expected"]),
        "elapsed_seconds": time.monotonic() - started, "stopped_reason": reason,
        "input_representation": "native_compiler_projection_features_not_raw_text",
        "trained_neural_decoder": progress["optimizer_steps"] > 0,
        "native_readout_used_for_selection": True, "heldout_canary": False,
        "backend_validation_gradient": False, "weights_downloaded": False, "provider_calls": 0,
        "training_executed": bool(batches), **FALSE}
    return {"checkpoint": checkpoint, "report": report}


def checkpoint_binding(checkpoint):
    """Immutable lineage identity for shared registry storage; contains no weights."""
    validate_checkpoint(checkpoint)
    keys = ("schema", "runtime_version", "lineage_id", "domain_id", "config", "implementation",
            "training_manifest_sha256", "tuning_manifest_sha256", "training_count", "tuning_count")
    return {"schema": "native-formula-variant/v1", "checkpoint": {key: _copy(checkpoint[key]) for key in keys},
        "feature_space_sha256": features.digest(checkpoint["feature_space"]),
        "decoder_head_sha256": features.digest(checkpoint["decoder_head"]),
        "groups_sha256": features.digest(checkpoint["groups"]), **FALSE}


def validate_training_result(result):
    """Validate a concrete candidate/report binding before registry publication."""
    _require(type(result) is dict and set(result) == {"checkpoint", "report"}, "closed native training result required")
    checkpoint, report = result["checkpoint"], result["report"]
    sha = validate_checkpoint(checkpoint)
    _require(type(report) is dict and report.get("schema") == "native-formula-training/v1"
             and report.get("lineage_id") == LINEAGE_ID and report.get("runtime_version") == RUNTIME_VERSION,
             "native training report schema/lineage differs")
    _require(report.get("checkpoint_sha256") == sha
             and report.get("parent_checkpoint_sha256") == checkpoint["parent_checkpoint_sha256"]
             and report.get("domain_id") == checkpoint["domain_id"] and report.get("objective") == OBJECTIVE
             and report.get("progress") == checkpoint["latest"]["progress"]
             and report.get("selected_optimizer_steps") == checkpoint["selected"]["optimizer_steps"]
             and report.get("selected_tuning") == checkpoint["selected"]["metrics"], "native training report/checkpoint identity differs")
    _require(all(report.get(key) is False for key in FALSE), "native training report cannot grant authority")
    _require(report.get("heldout_canary") is False and report.get("backend_validation_gradient") is False
             and report.get("weights_downloaded") is False and report.get("provider_calls") == 0
             and report.get("native_readout_used_for_selection") is True, "native training report scope differs")
    _require(type(report.get("optimizer_steps")) is int and 0 <= report["optimizer_steps"] <= report["progress"]["optimizer_steps"]
             and report.get("training_executed") is (report["optimizer_steps"] > 0)
             and report.get("trained_neural_decoder") is (report["progress"]["optimizer_steps"] > 0)
             and report.get("final_parameter_sha256") == features.digest(checkpoint["latest"]["parameters"]),
             "native training report optimizer progress differs")
    _require(report.get("training_count") == checkpoint["training_count"]
             and report.get("tuning_count") == checkpoint["tuning_count"], "native training report manifest sizes differ")
    return sha


def infer_native_formula(checkpoint, targets, *, selected=True):
    """Decode only model logits from structural inputs, without target fallback.

    Native targets provide the structural input vocabulary, as in native_v1.
    They are not independent text inputs; exact-input score targets are never
    passed to the readout. Unknown atoms or changed shapes reject the batch.
    """
    _require(type(selected) is bool, "selected must be a boolean")
    parameters, _ = _restore(checkpoint)
    data = _data(checkpoint["feature_space"], checkpoint["decoder_head"], _targets(targets, "inference"))
    if selected:
        parameters = {name: _tensor(checkpoint["selected"]["parameters"][name], value)
                      for name, value in parameters.items()}
    result, _, _ = _readout(parameters, checkpoint, data)
    result.update(schema="native-formula-inference/v1", runtime_version=RUNTIME_VERSION,
        checkpoint_sha256=checkpoint_digest(checkpoint), selected_weights=selected,
        projection_ids=list(checkpoint["feature_space"]["projection_ids"]),
        excluded_projection_ids=list(checkpoint["feature_space"]["excluded_projection_ids"]),
        optimizer_steps=checkpoint["selected"]["optimizer_steps"] if selected else checkpoint["latest"]["progress"]["optimizer_steps"],
        decoder_kind="learned_native_categorical_logits_with_fixed_shape_readout",
        trained_neural_decoder=(checkpoint["selected"]["optimizer_steps"] if selected else checkpoint["latest"]["progress"]["optimizer_steps"]) > 0,
        training_executed=False, objective=OBJECTIVE, **FALSE)
    _require(_pins(checkpoint["domain_id"]) == checkpoint["implementation"], "native producer changed during inference")
    return result


def save_checkpoint(checkpoint, path):
    """Write bounded JSON exclusively; an archived candidate is never replaced."""
    sha = validate_checkpoint(checkpoint)
    raw = _raw(checkpoint)
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        import os
        os.fsync(stream.fileno())
    return {"path": str(path), "sha256": sha, "bytes": len(raw), "schema": SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    _require(type(expected_sha256) is str and _SHA.fullmatch(expected_sha256), "exact checkpoint SHA-256 required")
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_CHECKPOINT_BYTES + 1)
    _require(len(raw) <= MAX_CHECKPOINT_BYTES and hashlib.sha256(raw).hexdigest() == expected_sha256,
             "checkpoint bytes or SHA-256 differ")
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    _require(_raw(value) == raw, "canonical checkpoint JSON required")
    validate_checkpoint(value)
    return value


__all__ = ["SCHEMA", "RUNTIME_VERSION", "LINEAGE_ID", "OBJECTIVE", "FALSE", "NativeFormulaError", "build_native_formula_checkpoint",
           "train_native_formula", "infer_native_formula", "validate_checkpoint", "checkpoint_digest", "save_checkpoint", "load_checkpoint",
           "checkpoint_binding", "validate_training_result"]
