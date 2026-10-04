"""Experimental fixed-schema typed IR decoder over a trained Legal 384D encoder.

A frozen inherited residual projection feeds parallel learned scalar classifiers.
Training consensus supplies constants and the exact typed JSON tree. Inference
combines independently predicted scalar classes, never retrieves whole targets.
This intentionally rejects variable schemas, array lengths, and unseen classes.
Native validation and held-out accuracy do not grant semantic or proof authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import time

from . import source_training_v2 as shared
from ....optimizers.logic_theorem_optimizer import domain_384_autoencoder as native
from ....optimizers.logic_theorem_optimizer import modal_latent_formula as legal

SCHEMA = "structured-source-384-autoencoder/v1"
DOMAINS, DIMENSION, FALSE = shared.DOMAINS, 384, native.FALSE
MAX_BYTES = native.MAX_BYTES
RIDGES = (.0001, .001, .01, .1)
PROJECTION_KEYS = ("projection_down.weight", "projection_down.bias", "projection_up.weight", "projection_up.bias")
_require, _raw, digest = native._require, native._raw, native.digest


@contextmanager
def _numeric():
    import numpy as np
    # Explicitly bound BLAS work without permanently changing caller settings.
    try:
        from threadpoolctl import threadpool_limits
    except ImportError:
        yield np
    else:
        with threadpool_limits(limits=1, user_api="blas"):
            yield np


def _implementation():
    return {"runtime_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "shared_runtime": shared._implementation()}


def _shape(value):
    if type(value) is dict:
        return {"kind": "object", "fields": [[key, _shape(value[key])] for key in sorted(value)]}
    if type(value) is list:
        return {"kind": "array", "items": [_shape(item) for item in value]}
    names = {str: "string", bool: "boolean", int: "integer", float: "float", type(None): "null"}
    _require(type(value) in names, "non-JSON target scalar")
    return {"kind": names[type(value)]}


def _scalar_leaves(value, path=()):
    if type(value) is dict:
        return {key: leaf for field in sorted(value) for key, leaf in _scalar_leaves(value[field], (*path, field)).items()}
    if type(value) is list:
        return {key: leaf for index, item in enumerate(value) for key, leaf in _scalar_leaves(item, (*path, index)).items()}
    return {path: value}


def _replace(document, path, value):
    _require(path, "root scalar IR is unsupported")
    target = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = deepcopy(value)


def _fit_schema(rows):
    shape = _shape(rows[0]["target"])
    _require(all(_shape(row["target"]) == shape for row in rows),
             "fixed typed JSON tree required; array lengths, keys, and scalar types may not vary")
    leaves = [_scalar_leaves(row["target"]) for row in rows]
    template, slots = deepcopy(rows[0]["target"]), []
    for path in sorted(leaves[0], key=lambda item: _raw(list(item))):
        classes = {_raw(row[path]): row[path] for row in leaves}
        if len(classes) > 1:
            _require(len(classes) <= 512, "too many training classes for one scalar")
            slots.append({"path": list(path), "classes": [deepcopy(classes[key]) for key in sorted(classes)]})
            _replace(template, path, None)
    _require(1 <= len(slots) <= 256, "one to 256 varying training scalar slots required")
    return {"schema": "fixed-typed-json-consensus/v1", "shape": shape, "template": template,
            "slots": slots, "origin": "training_only", "whole_target_memory": False}


def _targets(np, rows, schema):
    target_ids, width = [], sum(len(slot["classes"]) for slot in schema["slots"])
    _require(width <= 4096, "total training class vocabulary exceeds bound")
    one_hot = np.zeros((len(rows), width), dtype=np.float64)
    for row_index, row in enumerate(rows):
        _require(_shape(row["target"]) == schema["shape"], "target fixed typed JSON tree differs")
        leaves, ids, offset = _scalar_leaves(row["target"]), [], 0
        masked = deepcopy(row["target"])
        for slot in schema["slots"]:
            path = tuple(slot["path"])
            classes = [_raw(value) for value in slot["classes"]]
            value = _raw(leaves[path])
            _require(value in classes, "target scalar outside training vocabulary")
            index = classes.index(value)
            ids.append(index)
            one_hot[row_index, offset+index] = 1.
            offset += len(classes)
            _replace(masked, slot["path"], None)
        _require(_raw(masked) == _raw(schema["template"]), "target differs from training consensus constants")
        target_ids.append(ids)
    return one_hot, target_ids


def _project(np, rows, projection, *, zero_residual=False):
    values = np.asarray([row["embedding"] for row in rows], dtype=np.float64)
    if zero_residual:
        return values
    down = np.asarray(projection["projection_down.weight"], dtype=np.float64)
    down_bias = np.asarray(projection["projection_down.bias"], dtype=np.float64)
    up = np.asarray(projection["projection_up.weight"], dtype=np.float64)
    up_bias = np.asarray(projection["projection_up.bias"], dtype=np.float64)
    projected = values + np.tanh(values @ down.T + down_bias) @ up.T + up_bias
    _require(bool(np.isfinite(projected).all()), "nonfinite projected embedding")
    return projected


def _projection(parent):
    state = {key: deepcopy(parent["model_state"][key]) for key in PROJECTION_KEYS}
    _validate_projection(state, parent["config"]["projection_width"])
    return state


def _validate_projection(state, width):
    import numpy as np
    _require(type(width) is int and 1 <= width <= 64, "invalid inherited projection width")
    _require(type(state) is dict and set(state) == set(PROJECTION_KEYS), "closed inherited projection required")
    expected = dict(zip(PROJECTION_KEYS, ((width, DIMENSION), (width,), (DIMENSION, width), (DIMENSION,))))
    for name, shape in expected.items():
        try:
            value = np.asarray(state[name], dtype=np.float64)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid projection tensor") from exc
        _require(value.shape == shape and bool(np.isfinite(value).all()), "projection tensor shape or finiteness differs")


def _normalize(np, projected, transform=None):
    if transform is None:
        mean = projected.mean(0)
        scale = max(float(np.sqrt(np.mean(np.sum((projected-mean)**2, axis=1)))), .01)
        transform = {"mean": mean.tolist(), "scale": scale, "origin": "training_projected_embeddings_only"}
    return (projected-np.asarray(transform["mean"])) / transform["scale"], transform


def _assemble(domain, scores, schema):
    reports = []
    for score in scores:
        target, predicted, offset = deepcopy(schema["template"]), [], 0
        for slot in schema["slots"]:
            width = len(slot["classes"])
            index = int(score[offset:offset+width].argmax())
            predicted.append(index)
            _replace(target, slot["path"], slot["classes"][index])
            offset += width
        candidate, reason = None, None
        try:
            candidate = shared.validate_target(domain, target)["canonical_ir"]
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            reason = str(exc)[:512]
        reports.append({"candidate_ir": candidate, "predicted_classes": predicted, "reason": reason})
    return reports


def _score(domain, scores, rows, target_ids, schema):
    generated = _assemble(domain, scores, schema)
    slot_correct = sum(sum(actual == expected for actual, expected in zip(row["predicted_classes"], gold))
                  for row, gold in zip(generated, target_ids))
    correct = sum(sum(actual == expected for actual, expected in zip(row["predicted_classes"], gold))
                  for row, gold in zip(generated, target_ids) if row["candidate_ir"] is not None)
    count = len(rows)*len(schema["slots"])
    return {"exact_targets": sum(row["candidate_ir"] is not None and _raw(row["candidate_ir"]) == _raw(gold["target"])
                for row, gold in zip(generated, rows)),
            "valid_candidates": sum(row["candidate_ir"] is not None for row in generated), "count": len(rows),
            "semantic_leaf_correct": correct, "semantic_leaf_count": count,
            "semantic_leaf_accuracy": correct/max(count, 1),
            "classifier_slot_correct": slot_correct, "classifier_slot_accuracy": slot_correct/max(count, 1),
            "semantic_metric_scope": "correct_variable_leaves_only_for_native_valid_candidates", "teacher_forcing": False}


def _manifest(rows):
    return [{"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
        "normalized_source_sha256": hashlib.sha256(" ".join(row["source_text"].casefold().split()).encode()).hexdigest(),
        "embedding_sha256": digest(row["embedding"]), "target_sha256": digest(row["target"])} for row in rows]


def train(domain, training_rows, validation_rows, *, parent_projection, config=None):
    """Fit parallel classifiers on training data; tuning selects a fixed ridge grid."""
    started = time.monotonic()
    options = {"ridges": list(RIDGES), "embedding_provenance": {"model_id": "caller_supplied", "verified_by_runtime": False}}
    _require(config is None or type(config) is dict and set(config) <= set(options), "unknown structured training option")
    options.update(config or {})
    _require(type(options["ridges"]) is list and 1 <= len(options["ridges"]) <= 16
        and all(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 100 for value in options["ridges"])
        and options["ridges"] == sorted(set(options["ridges"])), "finite increasing positive ridge grid required")
    _require(type(options["embedding_provenance"]) is dict and len(_raw(options["embedding_provenance"])) <= 16384,
             "bounded embedding provenance required")
    training = shared._rows(domain, training_rows, training=True)
    validation = shared._rows(domain, validation_rows, training=True)
    _require(len(training) <= 2048, "dual ridge training is bounded to 2048 rows")
    for key in (lambda row: row["id"], lambda row: " ".join(row["source_text"].casefold().split()), lambda row: digest(row["embedding"])):
        _require(not {key(row) for row in training} & {key(row) for row in validation},
                 "training/validation identity, source, or embedding overlap")
    parent, parent_sha, parent_file = shared._parent(parent_projection)
    with native._cpu():
        legal.validate_checkpoint(parent)
    _require(parent["binding"]["dimension"] == DIMENSION and parent["progress"]["optimizer_steps"] > 0,
             "trained 384D Legal parent required")
    projection = _projection(parent)
    schema = _fit_schema(training)
    with _numeric() as np:
        train_targets, _ = _targets(np, training, schema)
        _, validation_ids = _targets(np, validation, schema)
        train_x, transform = _normalize(np, _project(np, training, projection))
        validation_x, _ = _normalize(np, _project(np, validation, projection), transform)
        bias = train_targets.mean(0)
        centered_targets = train_targets-bias
        gram = train_x @ train_x.T
        initial = _score(domain, np.zeros((len(validation), train_targets.shape[1])), validation, validation_ids, schema)
        selected, best_rank, best_weights, history = None, None, None, []
        fit_started = time.monotonic()
        factorization_seconds = validation_seconds = 0.
        for ridge in options["ridges"]:
            tick = time.monotonic()
            # One solve handles every class of every semantic slot. There is
            # no independent factorization per classifier or target document.
            dual = np.linalg.solve(gram + float(ridge)*np.eye(len(training)), centered_targets)
            weights = train_x.T @ dual
            factorization_seconds += time.monotonic()-tick
            _require(bool(np.isfinite(weights).all()), "nonfinite learned decoder weights")
            tick = time.monotonic()
            observed = _score(domain, validation_x @ weights + bias, validation, validation_ids, schema)
            validation_seconds += time.monotonic()-tick
            rank = (observed["exact_targets"], observed["semantic_leaf_correct"])
            chosen = best_rank is None or rank > best_rank
            history.append({"ridge": ridge, **observed, "selected_at_step": chosen})
            if chosen:
                selected, best_rank, best_weights, best = ridge, rank, weights.copy(), observed
        elapsed = time.monotonic()-fit_started
        state = {"weights": best_weights.tolist(), "bias": bias.tolist()}
        metrics = {"selected_ridge": selected, "selected_validation": best, "initial_zero_head_validation": initial,
            "history": history, "factorizations": len(options["ridges"]), "factorization_seconds": factorization_seconds,
            "validation_seconds": validation_seconds, "fit_seconds": elapsed,
            "unique_training_examples": len(training), "fit_unique_examples_per_second": len(training)/max(elapsed, 1e-9),
            "pre_checkpoint_seconds": time.monotonic()-started, "test_used_for_selection": False,
            "selection": "free_running_exact_then_variable_leaf_accuracy_first_ridge_on_ties",
            "optimizer_steps": 0, "gradient_training_used": False}
    checkpoint = {"schema": SCHEMA, "domain_id": domain, "dimension": DIMENSION,
        "implementation": _implementation(), "config": options, "parent_sha256": parent_sha,
        "parent_binding": deepcopy(parent["binding"]), "projection_width": parent["config"]["projection_width"],
        "projection_state": projection, "projection_sha256": digest(projection), "input_transform": transform,
        "target_schema": schema, "head_state": state, "head_sha256": digest(state),
        "training_manifest": _manifest(training), "validation_manifest": _manifest(validation), "training": metrics,
        "lineage": {"parent_encoder_frozen": True, "projection_tensors_inherited_exactly": list(PROJECTION_KEYS),
                    "parent_modified": False, "random_parameters_used": False}, **FALSE}
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds bound")
    if parent_file:
        _require(parent_file[0].read_bytes() == parent_file[1], "parent changed during training")
    Runtime(checkpoint)
    return {"checkpoint": checkpoint, "metrics": deepcopy(metrics)}


class Runtime:
    """Independent learned scalar predictions assembled through a fixed schema."""
    def __init__(self, checkpoint):
        fields = {"schema", "domain_id", "dimension", "implementation", "config", "parent_sha256", "parent_binding",
            "projection_width", "projection_state", "projection_sha256", "input_transform", "target_schema",
            "head_state", "head_sha256", "training_manifest", "validation_manifest", "training", "lineage", *FALSE}
        _require(type(checkpoint) is dict and set(checkpoint) == fields and checkpoint["schema"] == SCHEMA,
                 "closed structured source checkpoint required")
        _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds bound")
        _require(checkpoint["domain_id"] in DOMAINS and type(checkpoint["dimension"]) is int and checkpoint["dimension"] == DIMENSION,
                 "checkpoint requires genuine 384D domain")
        _require(all(checkpoint[key] is False for key in FALSE), "checkpoint cannot grant authority")
        _require(checkpoint["implementation"] == _implementation(), "implementation pins differ")
        _require(type(checkpoint["parent_sha256"]) is str and native._SHA.fullmatch(checkpoint["parent_sha256"])
            and type(checkpoint["parent_binding"]) is dict and checkpoint["parent_binding"].get("dimension") == DIMENSION,
                 "invalid parent binding")
        _require(digest(checkpoint["projection_state"]) == checkpoint["projection_sha256"], "projection digest differs")
        _validate_projection(checkpoint["projection_state"], checkpoint["projection_width"])
        transform = checkpoint["input_transform"]
        _require(type(transform) is dict and set(transform) == {"mean", "scale", "origin"}
            and transform["origin"] == "training_projected_embeddings_only", "invalid input transform")
        native._vector(transform["mean"])
        _require(type(transform["scale"]) in (int, float) and math.isfinite(transform["scale"]) and .01 <= transform["scale"] <= 1e8,
                 "invalid input scale")
        schema = checkpoint["target_schema"]
        _require(type(schema) is dict and set(schema) == {"schema", "shape", "template", "slots", "origin", "whole_target_memory"}
            and schema["schema"] == "fixed-typed-json-consensus/v1" and schema["origin"] == "training_only"
            and schema["whole_target_memory"] is False and type(schema["template"]) is dict, "invalid fixed target schema")
        slots = schema["slots"]
        _require(type(slots) is list and 1 <= len(slots) <= 256, "invalid varying scalar slots")
        candidate, seen = deepcopy(schema["template"]), set()
        canonical_paths = set(_scalar_leaves(schema["template"]))
        for slot in slots:
            _require(type(slot) is dict and set(slot) == {"path", "classes"} and type(slot["path"]) is list
                and 1 <= len(slot["path"]) <= 128 and all(type(part) in (int, str) for part in slot["path"]), "invalid scalar path")
            _require(tuple(slot["path"]) in canonical_paths, "noncanonical scalar path")
            path = _raw(slot["path"])
            _require(path not in seen, "duplicate scalar path")
            seen.add(path)
            classes = slot["classes"]
            _require(type(classes) is list and 2 <= len(classes) <= 512
                and all(type(value) in (str, int, float, bool, type(None)) for value in classes)
                and all(type(value) is type(classes[0]) for value in classes)
                and [_raw(value) for value in classes] == sorted(set(_raw(value) for value in classes)), "invalid scalar classes")
            try:
                existing = schema["template"]
                for part in slot["path"]:
                    existing = existing[part]
                _require(existing is None, "varying scalar must use an empty template slot")
                _replace(candidate, slot["path"], classes[0])
            except (TypeError, KeyError, IndexError) as exc:
                raise ValueError("scalar path outside schema") from exc
        _require(_shape(candidate) == schema["shape"], "stored typed target shape differs")
        width = sum(len(slot["classes"]) for slot in slots)
        _require(width <= 4096, "total class vocabulary exceeds bound")
        state = checkpoint["head_state"]
        _require(type(state) is dict and set(state) == {"weights", "bias"} and digest(state) == checkpoint["head_sha256"], "head digest differs")
        with _numeric() as np:
            weights, bias = np.asarray(state["weights"], dtype=np.float64), np.asarray(state["bias"], dtype=np.float64)
            _require(weights.shape == (DIMENSION, width) and bias.shape == (width,)
                and bool(np.isfinite(weights).all()) and bool(np.isfinite(bias).all()), "invalid head tensor shape or finiteness")
        for name in ("training_manifest", "validation_manifest"):
            rows = checkpoint[name]
            _require(type(rows) is list and 1 <= len(rows) <= 4096, "invalid split manifest")
            _require(all(type(row) is dict and set(row) == {"id", "source_sha256", "normalized_source_sha256", "embedding_sha256", "target_sha256"}
                and type(row["id"]) is str and 0 < len(row["id"]) <= 256
                and all(type(row[key]) is str and native._SHA.fullmatch(row[key]) for key in row if key != "id") for row in rows), "invalid split row")
            _require(len({row["id"] for row in rows}) == len(rows), "duplicate split ID")
        for key in ("id", "source_sha256", "normalized_source_sha256", "embedding_sha256"):
            _require(not {row[key] for row in checkpoint["training_manifest"]} & {row[key] for row in checkpoint["validation_manifest"]}, "checkpoint split overlap")
        options = checkpoint["config"]
        _require(type(options) is dict and set(options) == {"ridges", "embedding_provenance"}
            and type(options["ridges"]) is list and 1 <= len(options["ridges"]) <= 16
            and all(type(value) in (int, float) and math.isfinite(value) and 0 < value <= 100 for value in options["ridges"])
            and options["ridges"] == sorted(set(options["ridges"])) and type(options["embedding_provenance"]) is dict,
                 "invalid structured config")
        training = checkpoint["training"]
        _require(type(training) is dict and training.get("selected_ridge") in options["ridges"]
            and training.get("test_used_for_selection") is False and training.get("gradient_training_used") is False,
                 "invalid training provenance")
        lineage = checkpoint["lineage"]
        _require(lineage == {"parent_encoder_frozen": True, "projection_tensors_inherited_exactly": list(PROJECTION_KEYS),
                "parent_modified": False, "random_parameters_used": False}, "invalid transfer lineage")
        self.checkpoint = deepcopy(checkpoint)
        self.weights, self.bias = weights, bias

    def describe(self):
        return {"schema": SCHEMA, "domain_id": self.checkpoint["domain_id"], "dimension": DIMENSION,
            "input_representation": "source_embedding_384", "source_text_is_neural_input": False,
            "output_scope": "fixed_typed_json_schema_and_training_scalar_vocabulary",
            "generation": "independent_learned_scalar_classes_assembled_through_training_consensus_schema",
            "sample_memory_used": False, "whole_target_retrieval": False,
            "head_sha256": self.checkpoint["head_sha256"], "projection_sha256": self.checkpoint["projection_sha256"],
            "zero_projection_ablation": "zero_residual_branch_identity_embedding_retained",
            "shuffle_embeddings_ablation": "cyclic_rotation_of_supplied_embedding_batch",
            "independent_source_fidelity_check_required": True, **FALSE}

    def infer(self, rows, *, weight_ablation=None):
        rows = shared._rows(self.checkpoint["domain_id"], rows, training=False)
        _require(weight_ablation in (None, "zero_head", "zero_projection", "shuffle_embeddings"), "unknown weight ablation")
        if weight_ablation == "shuffle_embeddings":
            _require(len(rows) > 1, "embedding shuffle requires at least two rows")
            original = [row["embedding"] for row in rows]
            for index, row in enumerate(rows):
                row["embedding"] = original[(index+1) % len(rows)]
        with _numeric() as np:
            projected = _project(np, rows, self.checkpoint["projection_state"], zero_residual=weight_ablation == "zero_projection")
            data, _ = _normalize(np, projected, self.checkpoint["input_transform"])
            scores = (np.zeros((len(rows), len(self.bias))) if weight_ablation == "zero_head" else data @ self.weights + self.bias)
            _require(bool(np.isfinite(scores).all()), "nonfinite classifier scores")
            generated = _assemble(self.checkpoint["domain_id"], scores, self.checkpoint["target_schema"])
        reports = []
        for row, prediction, embedding in zip(rows, generated, projected):
            reports.append({"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                **prediction, "status": "unqualified_candidate" if prediction["candidate_ir"] is not None else "fail_open_invalid_output",
                "projected_embedding": embedding.tolist(), "weight_ablation": weight_ablation,
                "head_sha256": self.checkpoint["head_sha256"], "projection_sha256": self.checkpoint["projection_sha256"],
                "target_access": False, "teacher_forcing": False, "continue_planning": True, **FALSE})
        return {"schema": SCHEMA, "domain_id": self.checkpoint["domain_id"], "dimension": DIMENSION, "rows": reports, **FALSE}


def evaluate(checkpoint, rows, *, weight_ablation=None):
    """Count every gold row, including targets outside the fitted decoder scope."""
    gold = shared._rows(checkpoint["domain_id"], rows, training=True)
    coverage = []
    with _numeric() as np:
        for row in gold:
            try:
                _targets(np, [row], checkpoint["target_schema"])
                coverage.append((True, None))
            except ValueError as exc:
                coverage.append((False, str(exc)))
    report = Runtime(checkpoint).infer([{key: row[key] for key in ("id", "source_text", "embedding")} for row in gold], weight_ablation=weight_ablation)
    correct = slot_correct = 0
    for actual, expected, (supported, reason) in zip(report["rows"], gold, coverage):
        actual["exact_target"] = actual["candidate_ir"] is not None and _raw(actual["candidate_ir"]) == _raw(expected["target"])
        actual["within_training_coverage"], actual["target_coverage_reason"] = supported, reason
        leaves = _scalar_leaves(expected["target"])
        for slot, predicted in zip(checkpoint["target_schema"]["slots"], actual["predicted_classes"]):
            path = tuple(slot["path"])
            matches = path in leaves and _raw(slot["classes"][predicted]) == _raw(leaves[path])
            slot_correct += matches
            correct += matches and actual["candidate_ir"] is not None
    count = len(gold)*len(checkpoint["target_schema"]["slots"])
    return {**report, "count": len(gold), "exact_targets": sum(row["exact_target"] for row in report["rows"]),
        "valid_candidates": sum(row["candidate_ir"] is not None for row in report["rows"]),
        "within_training_coverage": sum(supported for supported, _ in coverage),
        "outside_training_coverage": sum(not supported for supported, _ in coverage),
        "semantic_leaf_correct": correct, "semantic_leaf_count": count, "semantic_leaf_accuracy": correct/max(count, 1),
        "classifier_slot_correct": slot_correct, "classifier_slot_accuracy": slot_correct/max(count, 1),
        "semantic_metric_scope": "correct_variable_leaves_only_for_native_valid_candidates"}


def load_checkpoint(path, *, expected_sha256, expected_domain):
    path = Path(path)
    _require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= MAX_BYTES, "bounded regular checkpoint required")
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint bytes differ")
    checkpoint = native._parse(raw)
    _require(type(checkpoint) is dict and checkpoint.get("domain_id") == expected_domain, "checkpoint belongs to another domain")
    return Runtime(checkpoint)


__all__ = ["SCHEMA", "DOMAINS", "DIMENSION", "RIDGES", "train", "Runtime", "evaluate", "load_checkpoint"]
