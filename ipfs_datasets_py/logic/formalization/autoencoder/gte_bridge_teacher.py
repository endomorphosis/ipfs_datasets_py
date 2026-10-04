"""Stdlib binding of an immutable 384D sequence teacher for bridge preparation.

This inspector verifies serialized geometry and a listed source-file closure.
It never executes those sources, imports Torch, loads a numerical model, or
turns archived tuning metrics into independent teacher qualification.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat

SCHEMA = "gte-bridge-teacher-binding/v1"
CHECKPOINT_SCHEMA = "shared-source-384-autoencoder/v2"
ARCHITECTURE = "residual-projection-latent-formula-gru/v1"
SOURCE_REPRESENTATION_ID = (
    "thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd:"
    "d384:pool=mean:norm=l2:precision=float32:input_policy=exact_source_no_truncation"
)
DIMENSION = 384
MAX_CHECKPOINT_BYTES = 48 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
DOMAINS = ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(
    r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"'
    r'|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
    r'|true|false|null|[{}\[\],:]'
)
_FLAGS = {"qualified", "admitted", "proof_authority", "source_semantics_verified", "publication_performed"}
_CHECKPOINT_FIELDS = {
    "schema", "domain_id", "dimension", "architecture", "codec", "config", "implementation",
    "parent_sha256", "parent_binding", "lineage", "model_state", "weights_sha256",
    "input_transform", "semantic_paths", "training_manifest", "validation_manifest", "training", *_FLAGS,
}
_CONFIG_FIELDS = {
    "strategy", "epochs", "max_seconds", "learning_rate", "batch_size", "seed", "patience",
    "max_optimizer_steps", "reconstruction_weight", "max_target_tokens", "validation_interval",
    "semantic_weight", "constant_weight", "structure_weight", "input_normalization",
    "embedding_provenance", "hidden_size", "token_embedding_dim", "projection_width",
}
_NATIVE_MODULE_PATHS = {
    "ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula":
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_latent_formula.py",
    "ipfs_datasets_py.logic.intent_ir.decoder": "ipfs_datasets_py/logic/intent_ir/decoder.py",
    "ipfs_datasets_py.logic.intent_ir.schema": "ipfs_datasets_py/logic/intent_ir/schema.py",
    "ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar": "ipfs_datasets_py/logic/intent_ir/formalize/rich_grammar.py",
    "ipfs_datasets_py.logic.security_ir.model": "ipfs_datasets_py/logic/security_ir/model.py",
    "ipfs_datasets_py.logic.software_verification.program": "ipfs_datasets_py/logic/software_verification/program.py",
    "ipfs_datasets_py.logic.ui_ux_ir.decoder": "ipfs_datasets_py/logic/ui_ux_ir/decoder.py",
    "ipfs_datasets_py.logic.ui_ux_ir.schema": "ipfs_datasets_py/logic/ui_ux_ir/schema.py",
}
_NUMERICAL_PATHS = {
    "canonical_contracts.py": "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py",
    "tree_pin.py": "ipfs_datasets_py/logic/autoformal/tree_pin.py",
    "legal_formula_codec.py": "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_formula_codec.py",
    "legal_ir_grammar_decoder.py": "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_ir_grammar_decoder.py",
    "modal_latent_formula.py": "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_latent_formula.py",
}


def _load_helper(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("_gte_bridge_" + name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load stdlib bridge helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_IO = _load_helper("gte_worker_contract")
_INVENTORY = _load_helper("gte_migration_inventory")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _fields(value, fields, label):
    _require(type(value) is dict and set(value) == fields, "closed " + label + " fields required")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _hash(value, label):
    _require(type(value) is str and _SHA.fullmatch(value) is not None, label + " must be a lowercase SHA256")
    return value


def _number(value, label, *, minimum=0., maximum=1e8):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum
    except OverflowError:
        valid = False
    _require(valid, "bounded finite " + label + " required")
    return value


def _integer(value, label, *, minimum=0, maximum=1000000):
    _require(type(value) is int and minimum <= value <= maximum, "bounded integer " + label + " required")
    return value


def _ordinary_path(value, label):
    _require(isinstance(value, (str, os.PathLike)), label + " path required")
    path = Path(os.path.abspath(value))
    _require(".." not in Path(value).parts, label + " path cannot contain traversal")
    for component in (*reversed(path.parents), path):
        _require(not stat.S_ISLNK(component.lstat().st_mode), label + " path cannot contain symlinks")
    return path


def _source_receipt(path, expected):
    path = _ordinary_path(path, "implementation source")
    raw, receipt, _ = _IO._read_stable(path, expected_sha256=expected, max_bytes=MAX_SOURCE_BYTES)
    _require(bool(raw), "implementation source must be nonempty")
    _ordinary_path(path, "implementation source")
    return receipt


def _source_pins(checkpoint):
    implementation = checkpoint["implementation"]
    _fields(implementation, {"runtime_sha256", "native", "numerical", "legal_codec_sha256"}, "implementation")
    native, numerical = implementation["native"], implementation["numerical"]
    _fields(native, {"runtime", "dependencies", "scope"}, "native implementation")
    _fields(numerical, {"files", "scope"}, "numerical implementation")
    _require(native["scope"] == "listed_numerical_and_native_validator_modules_only", "native implementation scope differs")
    _require(numerical["scope"] == "listed_latent_decoder_and_grammar_sources_only", "numerical implementation scope differs")
    _fields(native["dependencies"], set(_NATIVE_MODULE_PATHS), "native dependencies")
    _fields(numerical["files"], set(_NUMERICAL_PATHS), "numerical files")
    pins = {}

    def add(path, pin):
        _hash(pin, "implementation pin")
        _require(path not in pins or pins[path] == pin, "conflicting implementation source pins")
        pins[path] = pin

    add("ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py", implementation["runtime_sha256"])
    add("ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py", native["runtime"])
    for name, path in _NATIVE_MODULE_PATHS.items():
        add(path, native["dependencies"][name])
    for name, path in _NUMERICAL_PATHS.items():
        add(path, numerical["files"][name])
    add(_NUMERICAL_PATHS["legal_formula_codec.py"], implementation["legal_codec_sha256"])
    return pins


def _config(checkpoint):
    config = checkpoint["config"]
    _fields(config, _CONFIG_FIELDS, "teacher configuration")
    for name, low, high in (("hidden_size", 8, 128), ("token_embedding_dim", 8, 64),
                            ("projection_width", 1, 64), ("epochs", 1, 2000),
                            ("batch_size", 1, 256), ("seed", 0, 2**31 - 1),
                            ("patience", 0, 2000), ("max_target_tokens", 4, 1024),
                            ("validation_interval", 1, 1000)):
        _integer(config[name], name, minimum=low, maximum=high)
    _require(config["strategy"] in ("reference_ce", "semantic_v2"), "unknown teacher strategy")
    _require(config["input_normalization"] in ("none", "center_rms"), "unknown teacher normalization")
    if config["max_optimizer_steps"] is not None:
        _integer(config["max_optimizer_steps"], "max_optimizer_steps", minimum=1)
    for name, high in (("max_seconds", 3600), ("learning_rate", .1),
                       ("reconstruction_weight", 100), ("semantic_weight", 100),
                       ("constant_weight", 100), ("structure_weight", 100)):
        _number(config[name], name, minimum=0, maximum=high)
        _require(config[name] > 0, name + " must be positive")
    provenance = config["embedding_provenance"]
    _require(type(provenance) is dict, "source embedding provenance required")
    expected = {"model_id": "thenlper/gte-small", "revision": "17e1f347d17fe144873b1201da91788898c639cd",
                "dimension": 384, "dtype": "float32", "normalized": True, "truncated": False}
    _require(all(type(provenance.get(key)) is type(value) and provenance[key] == value
                 for key, value in expected.items()), "teacher source representation differs from paired GTE-small corpus")
    return config


def _transform(checkpoint):
    transform = checkpoint["input_transform"]
    _fields(transform, {"mode", "mean", "scale", "origin"}, "teacher input transform")
    _require(transform["mode"] == checkpoint["config"]["input_normalization"]
             and transform["origin"] == "training_only", "teacher input transform mode or origin differs")
    mean = transform["mean"]
    _require(type(mean) is list and len(mean) == DIMENSION, "teacher mean requires 384 coordinates")
    for value in mean:
        _number(value, "teacher mean", minimum=-1e6, maximum=1e6)
    _number(transform["scale"], "teacher scale", minimum=.01)
    if transform["mode"] == "none":
        _require(mean == [0.] * DIMENSION and transform["scale"] == 1., "identity teacher transform differs")
    return transform


def _codec(checkpoint):
    codec = checkpoint["codec"]
    _fields(codec, {"schema", "target_vocabulary"}, "teacher codec")
    vocabulary = codec["target_vocabulary"]
    _require(codec["schema"] == "typed-json-lexical/v1", "teacher codec schema differs")
    _require(type(vocabulary) is list and 4 <= len(vocabulary) <= 4096
             and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"], "teacher vocabulary special tokens differ")
    _require(all(type(token) is str and len(token) <= 16384 and _TOKEN.fullmatch(token) is not None
                 for token in vocabulary[3:]), "teacher vocabulary requires exact JSON lexical tokens")
    _require(vocabulary[3:] == sorted(set(vocabulary[3:])), "teacher vocabulary must be unique and sorted")
    return codec


def _archived_tuning(checkpoint):
    training = checkpoint["training"]
    _require(type(training) is dict and training.get("test_used_for_selection") is False,
             "training provenance must declare no test selection")
    _integer(training.get("optimizer_steps"), "optimizer_steps", minimum=1)
    selected_epoch = _integer(training.get("selected_epoch"), "selected_epoch", maximum=checkpoint["config"]["epochs"])
    selected_steps = _integer(training.get("selected_optimizer_steps"), "selected_optimizer_steps",
                              maximum=training["optimizer_steps"])
    observed = training.get("selected_validation")
    _require(type(observed) is dict, "archived selected tuning metrics required")
    fields = ("objective", "token_cross_entropy", "valid_candidates", "exact_targets", "count",
              "semantic_leaf_correct", "semantic_leaf_count", "semantic_leaf_accuracy")
    count = _integer(observed.get("count"), "tuning count", minimum=1, maximum=4096)
    _require(count == len(checkpoint["validation_manifest"]), "archived tuning count differs from validation manifest")
    for name in ("valid_candidates", "exact_targets"):
        _integer(observed.get(name), name, maximum=count)
    _require(observed["exact_targets"] <= observed["valid_candidates"], "exact target count exceeds valid candidate count")
    leaf_count = _integer(observed.get("semantic_leaf_count"), "semantic_leaf_count", maximum=4096 * 4096)
    leaf_correct = _integer(observed.get("semantic_leaf_correct"), "semantic_leaf_correct", maximum=leaf_count)
    for name in ("objective", "token_cross_entropy"):
        _number(observed.get(name), "archived " + name)
    accuracy = _number(observed.get("semantic_leaf_accuracy"), "semantic_leaf_accuracy", maximum=1.)
    _require(math.isclose(accuracy, leaf_correct / max(leaf_count, 1), rel_tol=1e-12, abs_tol=1e-12),
             "archived semantic accuracy differs from counts")
    return selected_epoch, selected_steps, {field: observed[field] for field in fields}


def _provenance(checkpoint):
    _hash(checkpoint["parent_sha256"], "teacher parent SHA256")
    _require(type(checkpoint["parent_binding"]) is dict
             and type(checkpoint["parent_binding"].get("dimension")) is int
             and checkpoint["parent_binding"]["dimension"] == DIMENSION, "teacher parent dimension differs")
    _require(type(checkpoint["lineage"]) is dict, "teacher lineage declaration required")
    paths = checkpoint["semantic_paths"]
    _require(type(paths) is list and len(paths) <= 4096
             and all(type(path) is list and len(path) <= 128
                     and all(type(part) in (int, str) for part in path) for path in paths),
             "bounded teacher semantic paths required")
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=True, allow_nan=False).encode()
    _require(paths == sorted(paths, key=canonical) and len({canonical(path) for path in paths}) == len(paths),
             "teacher semantic paths must be unique and sorted")
    fields = {"id", "source_sha256", "normalized_source_sha256", "embedding_sha256", "target_sha256"}
    for name in ("training_manifest", "validation_manifest"):
        rows = checkpoint[name]
        _require(type(rows) is list and 1 <= len(rows) <= 4096, "bounded nonempty " + name + " required")
        for row in rows:
            _fields(row, fields, "teacher split row")
            _require(type(row["id"]) is str and 0 < len(row["id"]) <= 256, "bounded teacher split ID required")
            for key in fields - {"id"}:
                _hash(row[key], "teacher split " + key)
        _require(len({row["id"] for row in rows}) == len(rows), "duplicate teacher split ID")
    for key in ("id", "source_sha256", "normalized_source_sha256", "embedding_sha256"):
        _require(not {row[key] for row in checkpoint["training_manifest"]}
                 & {row[key] for row in checkpoint["validation_manifest"]}, "teacher training/tuning split overlap")


def inspect_teacher(path, *, expected_sha256, domain_id="legal_ir", repository_root=None):
    """Bind a pinned local sequence teacher without loading or qualifying it.

    Missing files, changed pins, malformed schemas or geometry raise ValueError.
    Tuning results are archived development observations, not independent
    source-fidelity evaluation. The source representation remains a declaration.
    """
    _hash(expected_sha256, "expected checkpoint SHA256")
    _require(type(domain_id) is str and domain_id in DOMAINS, "supported teacher domain required")
    try:
        checkpoint_path = _ordinary_path(path, "checkpoint")
    except OSError as error:
        raise ValueError("ordinary checkpoint path is missing or inaccessible") from error
    checkpoint, receipt = _IO.read_pinned_json(checkpoint_path, expected_sha256=expected_sha256,
                                               max_bytes=MAX_CHECKPOINT_BYTES)
    _ordinary_path(checkpoint_path, "checkpoint")
    _fields(checkpoint, _CHECKPOINT_FIELDS, "teacher checkpoint")
    _require(checkpoint["schema"] == CHECKPOINT_SCHEMA, "unsupported teacher checkpoint schema")
    _require(checkpoint["domain_id"] == domain_id and type(checkpoint["dimension"]) is int
             and checkpoint["dimension"] == DIMENSION, "teacher domain or dimension differs")
    _require(checkpoint["architecture"] == ARCHITECTURE, "teacher architecture differs")
    _require(all(checkpoint[key] is False for key in _FLAGS), "teacher checkpoint cannot declare qualification or authority")
    _config(checkpoint)
    _provenance(checkpoint)
    transform, codec = _transform(checkpoint), _codec(checkpoint)
    _hash(checkpoint["weights_sha256"], "teacher weights SHA256")
    _require(checkpoint["weights_sha256"] == _digest(checkpoint["model_state"]), "teacher weights digest differs")
    actual = _INVENTORY._tensors(checkpoint["model_state"], "model_state")
    _INVENTORY._shape_check(actual, _INVENTORY._sequence_shapes(checkpoint, DIMENSION), "model_state")
    # Runtime constructs float32 tensors; reject values that are finite only in
    # Python's wider float representation before any future numerical load.
    for tensor in checkpoint["model_state"].values():
        stack = [tensor]
        while stack:
            value = stack.pop()
            if type(value) is list:
                stack.extend(value)
            else:
                _number(value, "float32 teacher tensor", minimum=-3.4028234663852886e38,
                        maximum=3.4028234663852886e38)
    try:
        root = _ordinary_path(repository_root if repository_root is not None else Path(__file__).parents[4], "repository root")
        _require(root.is_dir(), "repository root must be a directory")
        sources = [_source_receipt(root / relative, pin) for relative, pin in sorted(_source_pins(checkpoint).items())]
    except OSError as error:
        raise ValueError("listed implementation source is missing or inaccessible") from error
    epoch, steps, tuning = _archived_tuning(checkpoint)
    return {
        "schema": SCHEMA, "status": "bound", "teacher_runtime_id": domain_id + ":source_training_v2",
        "domain_id": domain_id, "dimension": DIMENSION, "architecture": ARCHITECTURE,
        "checkpoint": receipt, "checkpoint_sha256": receipt["sha256"], "weights_sha256": checkpoint["weights_sha256"],
        "source_representation_id": SOURCE_REPRESENTATION_ID, "source_representation_declared_only": True,
        "codec": {**deepcopy(codec), "target_vocabulary_count": len(codec["target_vocabulary"]),
                  "special_token_ids": {"pad": 0, "bos": 1, "eos": 2}}, "codec_sha256": _digest(codec),
        "input_transform": deepcopy(transform), "input_transform_sha256": _digest(transform),
        "tensor_shapes": {name.removeprefix("model_state."): list(shape) for name, shape in sorted(actual.items())},
        "decoding_contract": {"max_target_tokens": checkpoint["config"]["max_target_tokens"],
            "neural_input": "source_embedding_384_only", "source_text_is_neural_input": False,
            "gradient_api": "model.forward(data384,explicit_prefix)", "inference_target_access": False,
            "teacher_transform_order": "normalize_before_residual_projection"},
        "sources": sources, "implementation_sha256": _digest(checkpoint["implementation"]),
        "implementation_scope": "listed_files_only", "selected_epoch": epoch, "selected_optimizer_steps": steps,
        "selected_exposed_tuning": tuning, "teacher_qualified": False, "native_model_loaded": False,
        "target_source_fidelity_verified": False, "proof_authority": False, "training_executed": False,
    }


__all__ = ["SCHEMA", "SOURCE_REPRESENTATION_ID", "inspect_teacher"]
