"""Read-only, dependency-free inventory for the GTE source-IR migration.

This module describes serialized shapes and declared provenance. It does not
load models, verify external embedding producers, qualify teachers, or establish
that an optimizer can resume. Import it directly when package dependencies are
unavailable; every import below belongs to the Python standard library.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat

SCHEMA = "gte-migration-checkpoint-inventory/v1"
MAX_BYTES = 128 * 1024 * 1024
_SOURCE = {"shared-source-384-autoencoder/v2", "domain-384-typed-autoencoder/v1"}
_PAIRED = {"shared-paired-copy-autoencoder/v1", "shared-paired-copy-continuation/v1",
           "shared-paired-copy-aligned-continuation/v2"}
_MODAL = "modal-latent-formula-checkpoint/v1"
_STRUCTURED = "structured-source-384-autoencoder/v1"
_LEGAL = "legal-current-384-inference-package/v1"
_NATIVE = "native-formula-checkpoint/v1"
_NATIVE_COMPLETE = "native-family-complete-autoencoder/v1"
_LEXICAL = "learned-legal-formula-checkpoint/v1"
_ENVELOPES = {"registered-native-formula-candidate/v1"}
_TENSOR_FIELDS = {"model_state", "weights", "projection_state", "head_state", "parameters"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read(path, max_bytes):
    _require(type(max_bytes) is int and max_bytes > 0, "positive integer max_bytes required")
    path = Path(path)
    before = path.stat()
    _require(stat.S_ISREG(before.st_mode), "regular file required")
    _require(before.st_size <= max_bytes, "file exceeds max_bytes")
    # NONBLOCK avoids blocking on a file replaced by a FIFO between stat/open.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require(stat.S_ISREG(opened.st_mode) and _identity(opened) == _identity(before),
                 "file changed before reading")
        raw = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= max_bytes and len(raw) == before.st_size,
             "file exceeds bound or changed while reading")
    _require(_identity(before) == _identity(after) == _identity(path.stat()),
             "file changed while reading")
    return raw


def _parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite JSON number")

    def number(value):
        parsed = float(value)
        _require(math.isfinite(parsed), "nonfinite JSON number")
        return parsed

    try:
        parsed = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid,
                            parse_float=number)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid checkpoint JSON") from error
    _require(type(parsed) is dict, "checkpoint must be a JSON object")
    return parsed


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _tensor_shape(value, name):
    if type(value) is list:
        if not value:
            return (0,)
        shape = _tensor_shape(value[0], name)
        _require(all(_tensor_shape(item, name) == shape for item in value[1:]),
                 name + " tensor must be rectangular")
        return (len(value), *shape)
    _require(type(value) in (int, float), name + " tensor values must be numeric; bool is forbidden")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    _require(finite, name + " tensor values must be finite")
    return ()


def _tensors(value, prefix):
    _require(type(value) is dict, prefix + " must be a tensor object")
    found = {}
    for name, item in sorted(value.items()):
        full_name = prefix + "." + name
        if type(item) is dict:
            found.update(_tensors(item, full_name))
        else:
            found[full_name] = _tensor_shape(item, full_name)
    return found


def _integer(value, label):
    _require(type(value) is int and value > 0, label + " must be a positive integer")
    return value


def _vocabulary(value, label):
    _require(type(value) is list and value and all(type(token) is str for token in value),
             label + " must be a nonempty string list")
    _require(len(value) == len(set(value)), label + " has duplicate tokens")
    return len(value)


def _codec(checkpoint):
    codec = checkpoint.get("codec")
    if type(codec) is dict:
        result = {"schema": codec.get("schema"), "sha256": _digest(codec)}
        for role in ("source", "target"):
            key = role + "_vocabulary"
            if key in codec:
                result[key + "_count"] = _vocabulary(codec[key], key)
                result[key + "_sha256"] = _digest(codec[key])
        return result
    config = checkpoint.get("config", {})
    if type(config) is dict and "vocabulary" in config:
        vocabulary = config["vocabulary"]
        return {"schema": "custom-paired-lexical-vocabulary", "sha256": _digest(vocabulary),
                "target_vocabulary_count": _vocabulary(vocabulary, "vocabulary"),
                "source_vocabulary_count": len(vocabulary)}
    target = checkpoint.get("target_schema")
    if type(target) is dict:
        slots = target.get("slots", [])
        _require(type(slots) is list, "target_schema slots must be a list")
        count = 0
        for slot in slots:
            _require(type(slot) is dict and type(slot.get("classes")) is list,
                     "target_schema slot classes must be a list")
            count += len(slot["classes"])
        return {"schema": target.get("schema"), "sha256": _digest(target),
                "scalar_slot_count": len(slots), "scalar_class_count": count,
                "target_vocabulary_count": None}
    head = checkpoint.get("decoder_head")
    return {"schema": head.get("schema"), "sha256": _digest(head),
            "target_vocabulary_count": None} if type(head) is dict else None


def _family(schema):
    if schema in _SOURCE:
        return "source_sequence"
    return ({_MODAL: "latent_formula_head", _STRUCTURED: "structured_source",
             _LEGAL: "legal_sparse_package", _NATIVE: "native_feature",
             _NATIVE_COMPLETE: "native_feature_complete",
             _LEXICAL: "lexical_formula", "ir-384-hub-package/v1": "external_package_manifest",
             "native-formal-projection-candidate/v1": "native_feature_package"}.get(schema)
            or ("paired_copy" if schema in _PAIRED else "unknown"))


def _pipeline(family):
    descriptions = {
        "source_sequence": ("external source embedding -> input transform -> Torch residual projection -> conditioning -> GRU -> typed IR tokens",
                            True, "embedding_to_decoder_logits", None),
        "latent_formula_head": ("externally bound latent -> Torch residual projection -> conditioning -> GRU -> canonical Legal rule",
                                True, "latent_to_decoder_logits_only", None),
        "structured_source": ("external source embedding -> frozen NumPy residual projection -> NumPy normalization -> ridge scalar classifiers -> fixed typed JSON",
                              False, "NumPy inference has no autograd path", False),
        "legal_sparse_package": ("source text plus declared embedding -> parser features -> sparse Legal core -> optional bound latent formula GRU",
                                 False, "sparse core and parser prevent whole-pipeline autograd", False),
        "native_feature": ("compiler-derived structural features -> native feature normalization -> categorical neural reconstruction -> fixed-shape readout; not GTE source embeddings",
                           True, "numeric_feature_to_logits_only", False),
        "native_feature_complete": ("compiler-derived compositional feature columns -> native normalization -> linear native family reconstruction; no source-text decoder and not GTE source embeddings",
                                    True, "numeric_feature_to_reconstruction_only", False),
        "native_feature_package": ("compiler-derived structural features -> native numeric reconstruction -> symbolic decoder head; not GTE source embeddings",
                                   False, "numeric backend and symbolic readout", False),
        "paired_copy": ("custom lexical token IDs -> learned and inherited lexical vectors -> GRU attention pointer generator; not GTE source embeddings",
                        True, "lexical_embedding_to_sequence_probabilities_only", False),
        "lexical_formula": ("custom source token IDs -> learned lexical embeddings -> source GRU attention -> formula GRU; not GTE source embeddings",
                            True, "lexical_embedding_to_decoder_logits_only", False),
        "external_package_manifest": ("external checkpoint_file selected by explicit runtime; manifest alone contains no learned tensors",
                                      None, "external checkpoint was not loaded", None),
        "unknown": ("unknown schema; vector shape does not establish model or input identity",
                    None, "unknown", None),
    }
    text, differentiable, scope, whole = descriptions[family]
    return text, {"differentiable": differentiable, "scope": scope,
                  "whole_source_pipeline_differentiable": whole,
                  "external_embedding_encoder_loaded": False}


def _gru_shapes(hidden, input_width, prefix):
    return {prefix + ".weight_ih_l0": (3 * hidden, input_width),
            prefix + ".weight_hh_l0": (3 * hidden, hidden),
            prefix + ".bias_ih_l0": (3 * hidden,), prefix + ".bias_hh_l0": (3 * hidden,)}


def _sequence_shapes(checkpoint, dimension):
    config, codec = checkpoint.get("config"), checkpoint.get("codec")
    _require(type(config) is dict and type(codec) is dict, "sequence config and codec required")
    hidden = _integer(config.get("hidden_size"), "hidden_size")
    width = _integer(config.get("projection_width"), "projection_width")
    token_width = _integer(config.get("token_embedding_dim"), "token_embedding_dim")
    count = _vocabulary(codec.get("target_vocabulary"), "target_vocabulary")
    return {"projection_down.weight": (width, dimension), "projection_down.bias": (width,),
            "projection_up.weight": (dimension, width), "projection_up.bias": (dimension,),
            "condition.weight": (hidden, dimension), "condition.bias": (hidden,),
            "target_embedding.weight": (count, token_width),
            "output.weight": (count, hidden), "output.bias": (count,),
            **_gru_shapes(hidden, token_width, "decoder")}


def _shape_check(actual, expected, prefix):
    _require(set(actual) == {prefix + "." + name for name in expected},
             prefix + " tensor names differ from known architecture")
    for name, shape in expected.items():
        _require(actual[prefix + "." + name] == shape,
                 prefix + "." + name + " tensor shape differs from declared architecture")


def _declared_hash(checkpoint, tensor_field, digest_field):
    if digest_field in checkpoint:
        _require(checkpoint[digest_field] == _digest(checkpoint[tensor_field]),
                 digest_field + " differs from serialized tensors")


def _validate_shapes(checkpoint, family, dimension, tensors, prefix=""):
    field = lambda name: prefix + name
    if family in {"source_sequence", "latent_formula_head"}:
        state = _tensors(checkpoint.get("model_state"), field("model_state"))
        _shape_check(state, _sequence_shapes(checkpoint, dimension), field("model_state"))
        _declared_hash(checkpoint, "model_state", "weights_sha256")
    elif family == "structured_source":
        width = _integer(checkpoint.get("projection_width"), "projection_width")
        projection = {"projection_down.weight": (width, dimension), "projection_down.bias": (width,),
                      "projection_up.weight": (dimension, width), "projection_up.bias": (dimension,)}
        _shape_check(_tensors(checkpoint.get("projection_state"), field("projection_state")),
                     projection, field("projection_state"))
        count = _codec(checkpoint)["scalar_class_count"]
        _require(count > 0, "structured source head needs scalar classes")
        _shape_check(_tensors(checkpoint.get("head_state"), field("head_state")),
                     {"weights": (dimension, count), "bias": (count,)}, field("head_state"))
        _declared_hash(checkpoint, "projection_state", "projection_sha256")
        _declared_hash(checkpoint, "head_state", "head_sha256")
    elif family == "paired_copy":
        config = checkpoint.get("config")
        _require(type(config) is dict, "paired config required")
        hidden = _integer(config.get("hidden_size"), "hidden_size")
        embedding = _integer(config.get("embedding_dim"), "embedding_dim")
        lexical = _integer(config.get("lexical_width"), "lexical_width")
        count = _vocabulary(config.get("vocabulary"), "vocabulary")
        expected = {"lexical": (count, lexical), "embedding.weight": (count, embedding),
                    "output.weight": (count, hidden * 2), "output.bias": (count,),
                    "copy_gate.weight": (1, hidden * 2 + embedding + lexical), "copy_gate.bias": (1,),
                    **_gru_shapes(hidden, embedding + lexical, "encoder"),
                    **_gru_shapes(hidden, embedding + lexical, "decoder")}
        _shape_check(_tensors(checkpoint.get("weights"), field("weights")), expected, field("weights"))
        training = checkpoint.get("training", {})
        if type(training) is dict and "final_state_sha256" in training:
            _require(training["final_state_sha256"] == _digest(checkpoint["weights"]),
                     "final_state_sha256 differs from serialized tensors")
    elif family == "native_feature":
        config = checkpoint.get("config")
        _require(type(config) is dict, "native config required")
        width = _integer(config.get("input_width"), "input_width")
        latent = _integer(config.get("latent_width"), "latent_width")
        expected = {"encoder_weight": (width, latent), "encoder_bias": (latent,),
                    "decoder_weight": (latent, width), "decoder_bias": (width,)}
        for name in ("latest", "selected"):
            item = checkpoint.get(name)
            _require(type(item) is dict, name + " state required")
            _shape_check(_tensors(item.get("parameters"), field(name + ".parameters")),
                         expected, field(name + ".parameters"))
    elif family == "native_feature_complete":
        space, report = checkpoint.get("space"), checkpoint.get("report")
        _require(type(space) is dict and type(space.get("columns")) is list and space["columns"],
                 "complete native feature columns required")
        _require(type(report) is dict, "complete native training report required")
        width = len(space["columns"])
        latent = _integer(report.get("latent_width"), "latent_width")
        _require(report.get("feature_count") == width, "native feature count differs from columns")
        expected = [(width, latent), (latent,), (latent, width), (width,)]
        _require(type(checkpoint.get("parameters")) is list and len(checkpoint["parameters"]) == 4,
                 "complete native parameters require four tensors")
        for index, shape in enumerate(expected):
            _require(tensors[field("parameters." + str(index))] == shape,
                     "complete native parameter tensor shape differs from feature contract")
        if "selected_parameters_sha256" in report:
            _require(report["selected_parameters_sha256"] == _digest(checkpoint["parameters"]),
                     "selected_parameters_sha256 differs from serialized tensors")
    elif family == "lexical_formula":
        config, codec = checkpoint.get("config"), checkpoint.get("codec")
        _require(type(config) is dict and type(codec) is dict, "lexical config and codec required")
        hidden = _integer(config.get("hidden_size"), "hidden_size")
        embedding = _integer(config.get("embedding_dim"), "embedding_dim")
        source = _vocabulary(codec.get("source_vocabulary"), "source_vocabulary")
        target = _vocabulary(codec.get("target_vocabulary"), "target_vocabulary")
        expected = {"source_embedding.weight": (source, embedding),
                    "target_embedding.weight": (target, embedding),
                    "output.weight": (target, hidden * 2), "output.bias": (target,),
                    **_gru_shapes(hidden, embedding, "encoder"),
                    **_gru_shapes(hidden, embedding, "decoder")}
        _shape_check(_tensors(checkpoint.get("model_state"), field("model_state")),
                     expected, field("model_state"))


def _collect(checkpoint, prefix=""):
    result = {}
    for key, value in sorted(checkpoint.items()):
        name = prefix + key
        if key in _TENSOR_FIELDS:
            if key == "parameters" and type(value) is list:
                for index, item in enumerate(value):
                    tensor_name = name + "." + str(index)
                    result[tensor_name] = _tensor_shape(item, tensor_name)
            else:
                _require(type(value) is dict, name + " must be a tensor object")
                result.update(_tensors(value, name))
        elif key in {"formula_checkpoint", "latest", "selected", "decoder_head", "checkpoint"} and type(value) is dict:
            result.update(_collect(value, name + "."))
    return result


def _category(name, family):
    if family == "unknown" or family == "external_package_manifest":
        return "unclassified", "Unknown input and architecture contracts prevent transfer classification."
    if family in {"native_feature", "native_feature_complete", "native_feature_package"}:
        return "native_feature_contract_dependent", "Depends on native feature columns and decoder paths; GTE width is unrelated."
    if "core_state." in name:
        return "sparse_state_replay_required", "Sparse features, core binding and replay must remain identical."
    if any(part in name for part in ("target_embedding.weight", "source_embedding.weight",
                                    "embedding.weight", "output.weight", "output.bias", ".lexical")):
        return "token_identity_mapped", "Copy only matching token identities with compatible hidden widths; initialize new rows explicitly."
    if (any(part in name for part in ("projection_down.weight", "projection_up.weight", "projection_up.bias", "condition.weight"))
            or family == "structured_source" and name.endswith("head_state.weights")):
        return "dimension_dependent", "Input/latent coordinates depend on the 384D contract; preserve behind an adapter or replace for native 768D."
    if family == "structured_source" and "head_state." in name:
        return "scalar_identity_mapped", "Scalar slot and class identities must match the fixed target schema."
    if family == "legal_sparse_package" and "formula_checkpoint." not in name:
        return "sparse_state_replay_required", "Sparse core transfer requires its exact input and binding conventions."
    return "architecture_compatible", "Candidate for copying only when tensor shapes, layer semantics and input convention match."


def _optimizer(checkpoint, prefix=""):
    paths = []
    for key, value in checkpoint.items():
        if key in {"optimizer_state", "adam"}:
            paths.append(prefix + key)
        elif key in {"formula_checkpoint", "latest", "checkpoint"} and type(value) is dict:
            paths.extend(_optimizer(value, prefix + key + ".")["declared_fields"])
    return {"present": bool(paths), "declared_fields": sorted(paths),
            "resume_compatibility_verified": False,
            "statement": "Presence records serialized state only; runtime, selected-state alignment and resume equivalence are not verified."}


def inspect_checkpoint(path, *, max_bytes=MAX_BYTES):
    """Hash and inspect bounded strict JSON without executing its producer code.

    Known numerical schemas enforce tensor shapes against declared layer sizes.
    Unsupported schemas remain inspectable but cannot establish transfer support
    from dimensions alone. ValueError denotes corrupt or incompatible data.
    """
    raw = _read(path, max_bytes)
    envelope = _parse(raw)
    checkpoint = envelope
    envelope_schema = None
    if envelope.get("schema") in _ENVELOPES:
        _require(type(envelope.get("checkpoint")) is dict, "candidate envelope needs checkpoint object")
        checkpoint, envelope_schema = envelope["checkpoint"], envelope["schema"]
    schema = checkpoint.get("schema")
    _require(schema is None or type(schema) is str, "checkpoint schema must be a string")
    family = _family(schema)
    binding = checkpoint.get("binding", {})
    _require(type(binding) is dict, "binding must be an object")
    domain = checkpoint.get("domain_id", checkpoint.get("domain", binding.get("domain")))
    if family == "native_feature_complete":
        space = checkpoint.get("space")
        _require(type(space) is dict, "complete native feature space required")
        domain = space.get("domain_id")
    dimension = checkpoint.get("dimension", binding.get("dimension"))
    if dimension is not None:
        _integer(dimension, "dimension")
    if family in {"source_sequence", "structured_source", "legal_sparse_package"}:
        _require(dimension == 384, "known 384D schema dimension differs")
    for binding_name in ("parent_binding", "core_binding", "embedding_contract"):
        declared = checkpoint.get(binding_name)
        if declared is not None:
            _require(type(declared) is dict, binding_name + " must be an object")
            if dimension is not None and "dimension" in declared:
                _require(type(declared["dimension"]) is int and declared["dimension"] == dimension,
                         binding_name + " dimension differs")
    if family == "latent_formula_head":
        _require(dimension in (8, 384), "modal latent binding dimension differs")
        expected = {"legacy_hub_v1": 8, "current_legal_v2": 384}.get(binding.get("lineage_id"))
        _require(expected == dimension, "modal lineage and dimension differ")
    if family in {"native_feature", "native_feature_complete", "native_feature_package", "paired_copy", "lexical_formula"}:
        # These layer widths are not external GTE embedding dimensions.
        dimension = None
    tensors = _collect(checkpoint)
    _validate_shapes(checkpoint, family, dimension, tensors)
    decoder = _codec(checkpoint)
    if family == "legal_sparse_package":
        _require(checkpoint.get("runtime") == "legal_current_v2" and domain == "legal_ir",
                 "legal package runtime/domain differs")
        head = checkpoint.get("formula_checkpoint")
        if head is not None:
            _require(type(head) is dict and head.get("schema") == _MODAL,
                     "legal package requires known formula head schema")
            _require(head.get("binding", {}).get("dimension") == dimension,
                     "legal package formula dimension differs")
            _require(head["binding"].get("domain") == "legal_ir"
                     and head["binding"].get("lineage_id") == "current_legal_v2",
                     "legal package formula lineage/domain differs")
            _validate_shapes(head, "latent_formula_head", dimension, tensors, "formula_checkpoint.")
            decoder = _codec(head)
        core = checkpoint.get("core_state", {})
        _require(type(core) is dict, "legal core_state must be an object")
        for table, values in sorted(core.items()):
            if type(values) is dict and (table.endswith("embedding_weights") or table == "decoded_embeddings"):
                for key, vector in sorted(values.items()):
                    name = "core_state." + table + "." + key
                    shape = _tensor_shape(vector, name)
                    _require(shape == (dimension,), name + " sparse vector dimension differs")
                    tensors[name] = shape
    if "input_transform" in checkpoint:
        transform = checkpoint["input_transform"]
        _require(type(transform) is dict, "input_transform must be an object")
        if "mean" in transform:
            _require(_tensor_shape(transform["mean"], "input_transform.mean") == (dimension,),
                     "input_transform mean dimension differs")
        if "scale" in transform:
            _require(_tensor_shape(transform["scale"], "input_transform.scale") == () and transform["scale"] > 0,
                     "input_transform scale must be a positive finite scalar")
    names = ("architecture", "runtime", "runtime_version", "lineage_id", "implementation", "producer",
             "config", "profile", "runtime_profile", "input_transform", "binding", "parent_binding",
             "core_binding", "core_options", "embedding", "embedding_contract", "projection_id",
             "projection_width", "lineage", "progress", "parent_checkpoint_sha256", "parent_sha256")
    metadata = {key: checkpoint[key] for key in names if key in checkpoint}
    if family == "native_feature_complete":
        space, native_report = checkpoint["space"], checkpoint["report"]
        metadata["feature_contract"] = {"schema": space.get("schema"), "sha256": _digest(space),
            "domain_id": space.get("domain_id"), "column_count": len(space["columns"]),
            "columns_sha256": _digest(space["columns"]), "normalization": space.get("normalization"),
            "latent_width": native_report["latent_width"], "strategy": native_report.get("strategy"),
            "source_text_decoder_trained": native_report.get("source_text_decoder_trained")}
    pipeline, differentiability = _pipeline(family)
    inventory = []
    for name, shape in sorted(tensors.items()):
        category, reason = _category(name, family)
        inventory.append({"name": name, "shape": list(shape), "transfer_category": category, "reason": reason})
    return {"schema": SCHEMA, "checkpoint_schema": schema, "envelope_schema": envelope_schema,
            "path": str(Path(path)), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "family": family, "domain": domain, "dimension": dimension,
            "runtime": checkpoint.get("runtime", checkpoint.get("runtime_version", binding.get("runtime_profile"))),
            "metadata": metadata, "decoder_codec": decoder, "tensor_inventory": inventory,
            "supported_for_transfer": family not in {"unknown", "external_package_manifest"},
            "transfer_support_scope": "serialized shape inventory; native runtime validation and target compatibility are still required",
            "actual_input_pipeline": pipeline, "differentiability": differentiability,
            "optimizer_state": _optimizer(checkpoint), "teacher_qualified": False,
            "external_producer_verified": False, "training_executed": False,
            "model_loaded": False, "network_accessed": False}


def snapshot_files(root, relative_paths):
    """Hash explicitly named bounded files beneath root, without directory scans.

    Relative POSIX paths must have no traversal. In-root symlinks are allowed;
    symlinks resolving outside root, special files and files over MAX_BYTES fail.
    """
    root = Path(root).resolve(strict=True)
    _require(root.is_dir(), "snapshot root must be a directory")
    _require(type(relative_paths) in (list, tuple), "relative_paths must be a list or tuple")
    seen, result = set(), []
    for name in relative_paths:
        _require(type(name) is str and bool(name) and "\\" not in name,
                 "relative POSIX file path required")
        parts = name.split("/")
        _require(not PurePosixPath(name).is_absolute() and all(part not in {"", ".", ".."} for part in parts),
                 "snapshot path must be relative without traversal")
        _require(name not in seen, "duplicate snapshot path")
        seen.add(name)
        original = root / name
        path = original.resolve(strict=True)
        _require(path.is_relative_to(root), "snapshot symlink escapes root")
        raw = _read(path, MAX_BYTES)
        _require(original.resolve(strict=True) == path, "snapshot symlink changed while reading")
        result.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    return sorted(result, key=lambda item: item["path"])


__all__ = ["SCHEMA", "MAX_BYTES", "inspect_checkpoint", "snapshot_files"]
