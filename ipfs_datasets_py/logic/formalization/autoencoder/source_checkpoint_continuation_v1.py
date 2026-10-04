"""Saved-weight continuation of a frozen source-v2 decoder, with fresh Adam.

Planning is stdlib-only. Numerical execution is lazy and must use the original
authenticated source capsule. This owner does not expand vocabulary, refit input
coordinates, consume test rows, or transfer between dimensions or IR families.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat

SCHEMA = "source-checkpoint-continuation/v1"
PARENT_SCHEMA = "shared-source-384-autoencoder/v2"
ARCHITECTURE = "residual-projection-latent-formula-gru/v1"
DOMAINS = ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir")
DIMENSION = 384
MAX_BYTES = 48 * 1024**2
FALSE = {key: False for key in (
    "qualified", "admitted", "proof_authority", "source_semantics_verified",
    "publication_performed",
)}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(
    r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
    r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
    r'|true|false|null|[{}\[\],:]'
)
_OVERRIDES = {
    "strategy", "epochs", "max_seconds", "learning_rate", "batch_size", "seed",
    "patience", "max_optimizer_steps", "reconstruction_weight", "validation_interval",
    "semantic_weight", "constant_weight", "structure_weight",
}
_CONFIG_FIELDS = _OVERRIDES | {
    "max_target_tokens", "input_normalization", "embedding_provenance",
    "hidden_size", "token_embedding_dim", "projection_width",
}
_CHECKPOINT_FIELDS = {
    "schema", "domain_id", "dimension", "architecture", "codec", "config",
    "implementation", "parent_sha256", "parent_binding", "lineage", "model_state",
    "weights_sha256", "input_transform", "semantic_paths", "training_manifest",
    "validation_manifest", "training", *FALSE,
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _witness(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _read_checkpoint(reference):
    _require(type(reference) is dict and set(reference) == {"path", "sha256"},
             "closed source checkpoint reference required")
    _require(type(reference["path"]) is str and Path(reference["path"]).is_absolute(),
             "absolute source checkpoint path required")
    _require(type(reference["sha256"]) is str and _SHA.fullmatch(reference["sha256"]),
             "checkpoint SHA256 required")
    path = Path(reference["path"])
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_BYTES,
             "bounded regular source checkpoint required")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require(stat.S_ISREG(opened.st_mode) and _witness(opened) == _witness(before),
                 "checkpoint changed before read")
        data = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    _require(_witness(before) == _witness(after) == _witness(path.lstat())
             and len(data) == before.st_size, "checkpoint changed during read")
    checksum = hashlib.sha256(data).hexdigest()
    _require(checksum == reference["sha256"], "checkpoint bytes differ")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            _require(key not in value, "duplicate checkpoint JSON key")
            value[key] = item
        return value

    def invalid(_):
        raise ValueError("nonfinite checkpoint JSON value")

    try:
        checkpoint = json.loads(data, object_pairs_hook=unique, parse_constant=invalid)
        _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint JSON exceeds bound")
    except RecursionError as exc:
        raise ValueError("checkpoint JSON nesting exceeds bound") from exc
    return checkpoint, {"path": str(path), "bytes": len(data), "sha256": checksum}


def _config(config, overrides):
    _require(type(config) is dict and set(config) == _CONFIG_FIELDS, "closed saved configuration required")
    _require(config["strategy"] in ("reference_ce", "semantic_v2"), "unknown saved selection strategy")
    _require(overrides is None or type(overrides) is dict and set(overrides) <= _OVERRIDES,
             "protected or unknown continuation option")
    result = deepcopy(config)
    result["strategy"] = "semantic_v2"
    result.update(deepcopy(overrides or {}))
    _require(result["strategy"] in ("reference_ce", "semantic_v2"), "unknown selection strategy")
    _require(result["input_normalization"] in ("none", "center_rms"), "unknown normalization")
    for name, low, high in (
        ("epochs", 1, 2000), ("batch_size", 1, 256), ("seed", 0, 2**31 - 1),
        ("patience", 0, 2000), ("max_target_tokens", 4, 1024),
        ("validation_interval", 1, 1000), ("hidden_size", 8, 128),
        ("token_embedding_dim", 8, 64), ("projection_width", 1, 64),
    ):
        _require(type(result[name]) is int and low <= result[name] <= high, "invalid " + name)
    steps = result["max_optimizer_steps"]
    _require(steps is None or type(steps) is int and 1 <= steps <= 1000000,
             "invalid max_optimizer_steps")
    for name, high in (
        ("max_seconds", 3600), ("learning_rate", .1), ("reconstruction_weight", 100),
        ("semantic_weight", 100), ("constant_weight", 100), ("structure_weight", 100),
    ):
        _require(type(result[name]) in (int, float) and math.isfinite(result[name])
                 and 0 < result[name] <= high, "invalid " + name)
    _require(type(result["embedding_provenance"]) is dict
             and len(_raw(result["embedding_provenance"])) <= 16384, "invalid embedding provenance")
    return result


def _tensor(value, shape, name):
    if not shape:
        _require(type(value) in (int, float) and math.isfinite(value), "invalid tensor " + name)
        return
    _require(type(value) is list and len(value) == shape[0], "tensor shape differs: " + name)
    for child in value:
        _tensor(child, shape[1:], name)


def _state(checkpoint):
    h = checkpoint["config"]["hidden_size"]
    e = checkpoint["config"]["token_embedding_dim"]
    p = checkpoint["config"]["projection_width"]
    v = len(checkpoint["codec"]["target_vocabulary"])
    shapes = {
        "projection_down.weight": (p, DIMENSION), "projection_down.bias": (p,),
        "projection_up.weight": (DIMENSION, p), "projection_up.bias": (DIMENSION,),
        "condition.weight": (h, DIMENSION), "condition.bias": (h,),
        "target_embedding.weight": (v, e), "decoder.weight_ih_l0": (3*h, e),
        "decoder.weight_hh_l0": (3*h, h), "decoder.bias_ih_l0": (3*h,),
        "decoder.bias_hh_l0": (3*h,), "output.weight": (v, h), "output.bias": (v,),
    }
    state = checkpoint["model_state"]
    _require(type(state) is dict and set(state) == set(shapes), "model tensor names differ")
    for name, shape in shapes.items():
        _tensor(state[name], shape, name)
    _require(digest(state) == checkpoint["weights_sha256"], "weight digest differs")


def _parent(checkpoint, domain):
    _require(type(checkpoint) is dict and set(checkpoint) == _CHECKPOINT_FIELDS
             and checkpoint["schema"] == PARENT_SCHEMA, "closed source-v2 checkpoint required")
    _require(checkpoint["domain_id"] == domain, "checkpoint belongs to another domain")
    _require(type(checkpoint["dimension"]) is int and checkpoint["dimension"] == DIMENSION,
             "genuine 384D checkpoint required")
    _require(checkpoint["architecture"] == ARCHITECTURE, "architecture differs")
    _require(all(checkpoint[key] is False for key in FALSE), "checkpoint cannot grant authority")
    _config(checkpoint["config"], None)
    codec = checkpoint["codec"]
    _require(type(codec) is dict and set(codec) == {"schema", "target_vocabulary"}
             and codec["schema"] == "typed-json-lexical/v1", "invalid saved codec")
    vocabulary = codec["target_vocabulary"]
    _require(type(vocabulary) is list and 4 <= len(vocabulary) <= 4096
             and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"]
             and all(type(token) is str and len(token) <= 16384 and _TOKEN.fullmatch(token)
                     for token in vocabulary[3:])
             and vocabulary[3:] == sorted(set(vocabulary[3:])), "invalid saved vocabulary")
    _state(checkpoint)
    transform = checkpoint["input_transform"]
    _require(type(transform) is dict and set(transform) == {"mode", "mean", "scale", "origin"}
             and transform["mode"] == checkpoint["config"]["input_normalization"]
             and transform["origin"] == "training_only", "invalid saved input transform")
    _vector(transform["mean"])
    _require(type(transform["scale"]) in (int, float) and math.isfinite(transform["scale"])
             and .01 <= transform["scale"] <= 1e8, "invalid saved input scale")
    if transform["mode"] == "none":
        _require(transform["mean"] == [0.]*DIMENSION and transform["scale"] == 1., "identity transform differs")
    paths = checkpoint["semantic_paths"]
    _require(type(paths) is list and len(paths) <= 4096
             and all(type(path) is list and len(path) <= 128
                     and all(type(part) in (int, str) for part in path) for path in paths)
             and paths == sorted(paths, key=_raw) and len({_raw(path) for path in paths}) == len(paths),
             "invalid saved semantic paths")
    training = checkpoint["training"]
    _require(type(training) is dict and type(training.get("optimizer_steps")) is int
             and training["optimizer_steps"] > 0 and training.get("test_used_for_selection") is False,
             "invalid original training provenance")
    selected = training.get("selected_optimizer_steps")
    _require(type(selected) is int and 0 <= selected <= training["optimizer_steps"],
             "invalid original selected optimizer step")
    _require(type(checkpoint["implementation"]) is dict and checkpoint["implementation"],
             "saved implementation pins required")
    _require(type(checkpoint["parent_sha256"]) is str and _SHA.fullmatch(checkpoint["parent_sha256"])
             and type(checkpoint["parent_binding"]) is dict
             and type(checkpoint["parent_binding"].get("dimension")) is int
             and checkpoint["parent_binding"]["dimension"] == DIMENSION, "invalid native parent binding")
    manifest_fields = {"id", "source_sha256", "normalized_source_sha256", "embedding_sha256", "target_sha256"}
    for name in ("training_manifest", "validation_manifest"):
        rows = checkpoint[name]
        _require(type(rows) is list and 1 <= len(rows) <= 4096, "invalid split manifest")
        _require(all(type(row) is dict and set(row) == manifest_fields
                     and type(row["id"]) is str and 0 < len(row["id"]) <= 256
                     and all(type(row[key]) is str and _SHA.fullmatch(row[key])
                             for key in manifest_fields - {"id"}) for row in rows), "invalid split manifest row")
        _require(len({row["id"] for row in rows}) == len(rows), "duplicate split manifest ID")
    for key in ("id", "source_sha256", "normalized_source_sha256", "embedding_sha256"):
        _require(not {row[key] for row in checkpoint["training_manifest"]}
                 & {row[key] for row in checkpoint["validation_manifest"]}, "checkpoint split overlap")


def _vector(value):
    _require(type(value) is list and len(value) == DIMENSION
             and all(type(number) in (int, float) and math.isfinite(number)
                     and abs(number) <= 1e6 for number in value),
             "embedding must contain exactly 384 bounded finite numbers")


def _manifest(rows):
    return [{"id": row["id"],
             "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
             "normalized_source_sha256": hashlib.sha256(
                 " ".join(row["source_text"].casefold().split()).encode()).hexdigest(),
             "embedding_sha256": digest(row["embedding"]), "target_sha256": digest(row["target"])}
            for row in rows]


def _rows(rows, checkpoint, manifest_name):
    _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded nonempty rows required")
    seen = set()
    vocabulary = set(checkpoint["codec"]["target_vocabulary"][3:])
    for row in rows:
        _require(type(row) is dict and set(row) == {"id", "source_text", "embedding", "target"},
                 "closed cached training row required")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 256 and row["id"] not in seen,
                 "unique bounded row ID required")
        seen.add(row["id"])
        _require(type(row["source_text"]) is str and 0 < len(row["source_text"]) <= 16384
                 and row["source_text"].strip(), "bounded source provenance required")
        _vector(row["embedding"])
        _require(type(row["target"]) is dict, "typed target object required")
        target = _raw(row["target"]).decode()
        _require(len(target) <= 128 * 1024, "target exceeds bound")
        tokens = _TOKEN.findall(target)
        _require("".join(tokens) == target and all(token in vocabulary for token in tokens),
                 "target token outside saved vocabulary")
        _require(len(tokens) + 2 <= checkpoint["config"]["max_target_tokens"], "target exceeds saved token limit")
    manifest = _manifest(rows)
    _require(type(checkpoint[manifest_name]) is list and manifest == checkpoint[manifest_name],
             "original " + manifest_name + " differs")
    return deepcopy(rows), manifest


def prepare(domain, training_rows, validation_rows, *, source_checkpoint, config=None, binding=None):
    """Validate exact saved assets without importing a numerical/model owner.

    A successful plan is metadata evidence. The numerical adapter must still
    validate the original implementation pins and strictly load actual tensors.
    Unknown legacy IR-schema identity remains null.
    """
    _require(domain in DOMAINS, "unsupported continuation domain")
    checkpoint, pin = _read_checkpoint(source_checkpoint)
    _parent(checkpoint, domain)
    training, fit_manifest = _rows(training_rows, checkpoint, "training_manifest")
    validation, val_manifest = _rows(validation_rows, checkpoint, "validation_manifest")
    for key in ("id", "source_sha256", "normalized_source_sha256", "embedding_sha256"):
        _require(not {row[key] for row in fit_manifest} & {row[key] for row in val_manifest},
                 "training/validation identity, source, or embedding overlap")
    expected = {"ir_family_id": domain, "dimension": DIMENSION, "dimension_role": "input_embedding",
                "schema_version": None, "task_id": "typed_ir_reconstruction", "format_id": "semantic_json"}
    if binding is not None:
        _require(type(binding) is dict and set(binding) == set(expected), "closed decoder binding required")
        _require(all(type(binding[key]) is type(expected[key]) and binding[key] == expected[key]
                     for key in expected if key != "schema_version"), "decoder binding differs")
        _require(binding["schema_version"] is None,
                 "legacy checkpoint has no authenticated IR schema binding")
        expected = deepcopy(binding)
    return {"schema": SCHEMA, "domain_id": domain, "checkpoint": checkpoint,
            "checkpoint_pin": pin, "training_rows": training, "validation_rows": validation,
            "config": _config(checkpoint["config"], config), "binding": expected,
            "prior_selected_optimizer_steps": checkpoint["training"]["selected_optimizer_steps"],
            "numerical_execution": False, **FALSE}


def _observation(value, count, path_count):
    _require(type(value) is dict and type(value.get("count")) is int
             and value["count"] == count, "validation observation cardinality differs")
    for name in ("objective", "token_cross_entropy", "weighted_cross_entropy", "embedding_mse"):
        _require(type(value.get(name)) in (int, float) and math.isfinite(value[name])
                 and value[name] >= 0, "invalid validation " + name)
    for name, high in (("exact_targets", count), ("valid_candidates", count),
                       ("semantic_leaf_correct", count * path_count),
                       ("semantic_leaf_count", count * path_count)):
        _require(type(value.get(name)) is int and 0 <= value[name] <= high,
                 "invalid validation " + name)
    _require(value["exact_targets"] <= value["valid_candidates"]
             and value["semantic_leaf_count"] == count * path_count,
             "incomplete validation observation")
    _require(type(value.get("semantic_leaf_accuracy")) in (int, float)
             and value["semantic_leaf_accuracy"] == value["semantic_leaf_correct"] / max(count * path_count, 1)
             and value.get("free_running_metrics_teacher_forced") is False,
             "free-running validation evidence differs")


def _selection(value, strategy):
    if strategy == "reference_ce":
        return (-value["objective"],)
    return (value["exact_targets"], value["semantic_leaf_accuracy"], -value["objective"])


def _continuation_metrics(checkpoint, metrics, initial_weights_sha256):
    _require(type(metrics) is dict and _raw(metrics) == _raw(checkpoint["training"]), "training metrics differ")
    _require(type(initial_weights_sha256) is str and _SHA.fullmatch(initial_weights_sha256),
             "initial weight SHA256 required")
    _require(metrics.get("fresh_optimizer") is True and metrics.get("exact_optimizer_resume") is False
             and type(metrics.get("initial_optimizer_state_entries")) is int
             and metrics["initial_optimizer_state_entries"] == 0, "fresh optimizer evidence required")
    epochs = checkpoint["config"]["epochs"]
    _require(type(metrics.get("selected_epoch")) is int
             and 0 <= metrics["selected_epoch"] <= epochs, "invalid selected epoch")
    steps = metrics.get("optimizer_steps")
    limit = checkpoint["config"]["max_optimizer_steps"]
    _require(type(steps) is int and steps > 0 and (limit is None or steps <= limit),
             "continuation optimizer step budget differs")
    count = len(checkpoint["validation_manifest"])
    for key in ("before_validation", "selected_validation"):
        _observation(metrics.get(key), count, len(checkpoint["semantic_paths"]))
    selected_steps = metrics["selected_optimizer_steps"]
    if selected_steps == 0:
        _require(metrics["selected_epoch"] == 0 and checkpoint["weights_sha256"] == initial_weights_sha256
                 and _raw(metrics["selected_validation"]) == _raw(metrics["before_validation"]),
                 "selected parent baseline changed")
    else:
        _require(metrics["selected_epoch"] > 0
                 and _selection(metrics["selected_validation"], checkpoint["config"]["strategy"])
                 > _selection(metrics["before_validation"], checkpoint["config"]["strategy"]),
                 "selected continuation did not improve validation")


def warm_start(domain, training_rows, validation_rows, *, source_checkpoint, config=None,
               binding=None, backend=None):
    """Continue a saved decoder with fresh Adam and validation selection.

    ``backend`` is an explicit injection seam for orchestration controls, whose
    synthetic results cannot establish numerical or source-fidelity evidence.
    No default model imports occur before the retained-asset plan is validated.
    """
    plan = prepare(domain, training_rows, validation_rows, source_checkpoint=source_checkpoint,
                   config=config, binding=binding)
    original = deepcopy(plan)
    injected_backend = backend is not None
    if backend is None:
        backend = importlib.import_module(".source_checkpoint_continuation_numeric_v1", __package__).run
    _require(callable(backend), "callable continuation backend required")
    result = backend(deepcopy(plan))
    _require(type(result) is dict and set(result) == {
        "checkpoint", "metrics", "initial_weights_sha256", "final_weights_sha256",
        "numerical_owner_sha256", "numerical_execution",
    }, "closed backend continuation evidence required")
    parent = original["checkpoint"]
    output, metrics = result["checkpoint"], result["metrics"]
    _parent(output, domain)
    for key in _CHECKPOINT_FIELDS - {"model_state", "weights_sha256", "training", "config"}:
        _require(_raw(output[key]) == _raw(parent[key]), "saved checkpoint field changed: " + key)
    _require(_raw(output["config"]) == _raw(original["config"]), "effective training configuration differs")
    _require(result["initial_weights_sha256"] == parent["weights_sha256"], "initial loaded weights differ")
    _require(result["final_weights_sha256"] == output["weights_sha256"], "final weight digest differs")
    _continuation_metrics(output, metrics, parent["weights_sha256"])
    _require(type(result["numerical_execution"]) is bool
             and type(result["numerical_owner_sha256"]) is str
             and _SHA.fullmatch(result["numerical_owner_sha256"]), "numerical owner evidence required")
    if injected_backend:
        _require(result["numerical_execution"] is False,
                 "injected backend cannot establish numerical execution")
    else:
        numeric_path = Path(__file__).with_name("source_checkpoint_continuation_numeric_v1.py")
        _require(result["numerical_execution"] is True
                 and result["numerical_owner_sha256"] == hashlib.sha256(numeric_path.read_bytes()).hexdigest(),
                 "default numerical owner evidence differs")
    observed, after_pin = _read_checkpoint(source_checkpoint)
    _require(after_pin == original["checkpoint_pin"] and _raw(observed) == _raw(parent),
             "original checkpoint changed during continuation")
    envelope = {
        "schema": SCHEMA, "binding": original["binding"], "source_checkpoint": deepcopy(output),
        "training": deepcopy(metrics), "numerical_execution": result["numerical_execution"],
        "producer": {"continuation_owner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                     "numerical_owner_sha256": result["numerical_owner_sha256"]},
        "lineage": {"source_checkpoint_pin": original["checkpoint_pin"],
                    "initial_weights_sha256": result["initial_weights_sha256"],
                    "selected_weights_sha256": result["final_weights_sha256"],
                    "prior_selected_optimizer_steps": original["prior_selected_optimizer_steps"],
                    "prior_run_optimizer_steps": parent["training"]["optimizer_steps"],
                    "random_parameters_used": False, "exact_optimizer_resume": False,
                    "optimizer_state_inherited": False, "original_cached_splits_reused": True},
        **FALSE,
    }
    _require(len(_raw(envelope)) <= MAX_BYTES, "continuation checkpoint exceeds bound")
    return envelope


def load_runtime(reference, *, expected_domain, expected_binding=None,
                 parent_resolver=None, runtime_loader=None):
    """Load the v2 runtime payload from a pinned, genuinely numerical envelope.

    Exact source-owner pins still require the authenticated original capsule.
    Loading does not grant semantic, teacher or proof qualification.
    ``parent_resolver`` can locate a retained local copy when the recorded donor
    path is unavailable; it returns a {path, sha256} reference with the same hash.
    """
    envelope, _ = _read_checkpoint(reference)
    fields = {"schema", "binding", "source_checkpoint", "training", "numerical_execution",
              "producer", "lineage", *FALSE}
    _require(type(envelope) is dict and set(envelope) == fields and envelope["schema"] == SCHEMA,
             "closed continuation envelope required")
    _require(all(envelope[key] is False for key in FALSE) and envelope["numerical_execution"] is True,
             "numerical continuation envelope required")
    _require(expected_domain in DOMAINS, "unsupported continuation domain")
    _parent(envelope["source_checkpoint"], expected_domain)
    binding = envelope["binding"]
    required = {"ir_family_id": expected_domain, "dimension": DIMENSION,
                "dimension_role": "input_embedding", "schema_version": None,
                "task_id": "typed_ir_reconstruction", "format_id": "semantic_json"}
    _require(type(binding) is dict and _raw(binding) == _raw(required), "runtime decoder binding differs")
    if expected_binding is not None:
        _require(_raw(binding) == _raw(expected_binding), "expected decoder binding differs")
    _require(_raw(envelope["training"]) == _raw(envelope["source_checkpoint"]["training"]),
             "envelope training metrics differ")
    producer = envelope["producer"]
    numeric_path = Path(__file__).with_name("source_checkpoint_continuation_numeric_v1.py")
    _require(type(producer) is dict and set(producer) == {
        "continuation_owner_sha256", "numerical_owner_sha256"}, "closed continuation producer required")
    _require(producer["continuation_owner_sha256"] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
             and producer["numerical_owner_sha256"] == hashlib.sha256(numeric_path.read_bytes()).hexdigest(),
             "continuation producer pins differ")
    lineage = envelope["lineage"]
    lineage_fields = {"source_checkpoint_pin", "initial_weights_sha256", "selected_weights_sha256",
                      "prior_selected_optimizer_steps", "prior_run_optimizer_steps",
                      "random_parameters_used", "exact_optimizer_resume",
                      "optimizer_state_inherited", "original_cached_splits_reused"}
    _require(type(lineage) is dict and set(lineage) == lineage_fields
             and lineage.get("random_parameters_used") is False
             and lineage.get("exact_optimizer_resume") is False
             and lineage.get("optimizer_state_inherited") is False
             and lineage.get("original_cached_splits_reused") is True
             and lineage.get("selected_weights_sha256") == envelope["source_checkpoint"]["weights_sha256"],
             "continuation lineage differs")
    parent_pin = lineage["source_checkpoint_pin"]
    _require(type(parent_pin) is dict and set(parent_pin) == {"path", "bytes", "sha256"}
             and type(parent_pin["bytes"]) is int and 0 < parent_pin["bytes"] <= MAX_BYTES
             and type(parent_pin["path"]) is str and Path(parent_pin["path"]).is_absolute()
             and type(parent_pin["sha256"]) is str and _SHA.fullmatch(parent_pin["sha256"]),
             "closed original checkpoint pin required")
    parent_reference = {key: parent_pin[key] for key in ("path", "sha256")}
    if parent_resolver is not None:
        _require(callable(parent_resolver), "callable parent resolver required")
        parent_reference = parent_resolver(deepcopy(parent_pin))
        _require(type(parent_reference) is dict and set(parent_reference) == {"path", "sha256"}
                 and parent_reference["sha256"] == parent_pin["sha256"], "resolved parent pin differs")
    parent, observed_parent_pin = _read_checkpoint(parent_reference)
    _require(observed_parent_pin["sha256"] == parent_pin["sha256"]
             and observed_parent_pin["bytes"] == parent_pin["bytes"], "original parent checkpoint pin differs")
    _parent(parent, expected_domain)
    _require(lineage["initial_weights_sha256"] == parent["weights_sha256"]
             and type(lineage["prior_selected_optimizer_steps"]) is int
             and lineage["prior_selected_optimizer_steps"] == parent["training"]["selected_optimizer_steps"]
             and type(lineage["prior_run_optimizer_steps"]) is int
             and lineage["prior_run_optimizer_steps"] == parent["training"]["optimizer_steps"],
             "original parent progress or weights differ")
    payload = envelope["source_checkpoint"]
    for key in _CHECKPOINT_FIELDS - {"model_state", "weights_sha256", "training", "config"}:
        _require(_raw(payload[key]) == _raw(parent[key]), "saved checkpoint field changed: " + key)
    for key in _CONFIG_FIELDS - _OVERRIDES:
        _require(_raw(payload["config"][key]) == _raw(parent["config"][key]),
                 "saved checkpoint configuration changed: " + key)
    _continuation_metrics(envelope["source_checkpoint"], envelope["training"],
                          lineage.get("initial_weights_sha256"))
    if runtime_loader is None:
        runtime_loader = importlib.import_module(
            ".source_checkpoint_continuation_numeric_v1", __package__).load_runtime_payload
    _require(callable(runtime_loader), "callable runtime loader required")
    runtime = runtime_loader(deepcopy(envelope["source_checkpoint"]))
    _, after_parent_pin = _read_checkpoint(parent_reference)
    _require(after_parent_pin == observed_parent_pin, "original parent changed during runtime load")
    return runtime


__all__ = ["SCHEMA", "PARENT_SCHEMA", "DOMAINS", "prepare", "warm_start", "load_runtime", "digest"]
