"""Explicit, source-only replay of two retained contextual LegalIR decoders.

Preparation authenticates the original bytes and checks bounded JSON without
importing tensor libraries. Opening is an explicit lazy numerical action. This
experimental capability has no native IR schema/profile/format identity and
grants no quality, training, production runtime, reconstruction or proof authority.
Repeated file and source fences are endpoints, not an atomic multi-file snapshot.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys

SCHEMA = "contextual-legal-ir-runtime-plan/v1"
MAX_REFERENCE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
SOURCE_OWNER_NAMES = (
    "contextual_legal_ir_runtime", "contextual_legal_ir_numeric",
    "dimension_native_decoder_experiment", "decoder_distillation_experiment_v2",
    "projected_source_decoder_experiment", "clause_source_decoder_experiment",
    "action_factorized_clause_decoder_experiment", "ordered_clause_recurrent_decoder_experiment",
    "decoder_distillation_experiment", "decoder_cardinality_experiment",
    "shared_slot_source_decoder_experiment", "source_value_decoder_experiment", "clause_source_context",
)
_REQUEST_FIELDS = {"ir_family_id", "dimension", "dimension_role", "task_id", "checkpoint_sha256"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_STATE_FALSE = ("admitted", "checkpoint_promoted", "convergence_proven", "formalized",
    "fresh_holdout", "lake_executed", "optimizer_resumable", "proof_authority", "qualified",
    "roundtrip_ok", "source_semantics_verified")
_AUTHORITY = dict(runtime_admitted=False, runtime_release_qualified=False,
    native_ir_format_qualified=False, model_task_qualified=False, quality_qualified=False,
    teacher_qualified=False, source_token_budget_qualified=False, source_semantics_verified=False,
    learned_source_text_reconstruction_qualified=False, proof_authority=False,
    training_executed=False, encoder_executed=False, embeddings_generated=False,
    database_write_executed=False, network_executed=False, full_source_dependency_closure_qualified=False)
_SCOPE = "Bounded per-file reads and repeated endpoint fences; no atomic cross-file snapshot or continuous source currentness."


class ContextualLegalRuntimeError(ValueError):
    """Refusal with truthful numerical call-boundary observations."""

    def __init__(self, message):
        super().__init__(message)
        self.model_load_started = False
        self.model_load_performed = False
        self.model_inference_started = False
        self.model_inference_executed = False
        self.raw_candidate_report = None


def _require(value, message):
    if not value:
        raise ContextualLegalRuntimeError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _text(value, maximum, name):
    _require(type(value) is str and 0 < len(value) <= maximum and value.strip(), name + " required")
    try:
        return value.encode("utf-8")
    except UnicodeError as error:
        raise ContextualLegalRuntimeError(name + " must be exact UTF8") from error


def _hash(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _pin(value, maximum):
    _require(type(value) is dict and set(value) == {"path", "bytes", "sha256"}, "closed file pin required")
    path = _text(value["path"], 4096, "absolute pinned path")
    _require(b"\0" not in path and Path(value["path"]).is_absolute(), "explicit absolute pin required")
    _require(value["path"] == str(Path(value["path"])) == str(Path(value["path"]).resolve(strict=True)),
             "canonical nonalias pinned path required")
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= maximum and _hash(value["sha256"]),
             "bounded exact file bytes/SHA256 required")
    return dict(value)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _witness(path):
    _require(str(Path(path).resolve(strict=True)) == path, "pinned path became a filesystem alias")
    info = os.lstat(path)
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "pinned input must be a single-link regular file")
    return _identity(info)


def _read(pin, *, retain=False):
    before = _witness(pin["path"])
    _require(before[3] == pin["bytes"], "pinned byte count differs")
    fd = os.open(pin["path"], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        _require(_identity(os.fstat(fd)) == before, "pinned file changed before open")
        count, digest, chunks = 0, hashlib.sha256(), []
        while True:
            block = os.read(fd, min(1024 * 1024, pin["bytes"] - count + 1))
            if not block:
                break
            count += len(block)
            _require(count <= pin["bytes"], "pinned file grew while read")
            digest.update(block)
            if retain:
                chunks.append(block)
        _require(_identity(os.fstat(fd)) == before == _witness(pin["path"]), "pinned file changed while read")
        _require(count == pin["bytes"] and digest.hexdigest() == pin["sha256"], "pinned bytes/SHA256 differ")
        return b"".join(chunks) if retain else None
    finally:
        os.close(fd)


def _fence(pins, witnesses):
    for pin in pins.values():
        _read(pin)
    # A later read must not conceal replacement of an earlier file.
    _require(all(_witness(pin["path"]) == witnesses[name] for name, pin in pins.items()),
             "input/source generation changed across closing fence")


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def _float(value):
    result = float(value)
    _require(math.isfinite(result), "finite JSON number required")
    return result


def _constant(value):
    raise ContextualLegalRuntimeError("nonfinite JSON constant: " + value)


def _json(raw):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_float=_float, parse_constant=_constant)
    except (UnicodeError, RecursionError, ValueError) as error:
        raise ContextualLegalRuntimeError("invalid bounded contextual JSON") from error
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        _require(depth <= 64 and count <= 1_000_000, "contextual JSON structure exceeds bound")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    return value


def _number(value):
    _require(type(value) in (int, float), "exact numerical scalar required")
    try:
        _require(math.isfinite(value), "finite numerical scalar required")
        packed = struct.pack("=f", value)
        _require(math.isfinite(struct.unpack("=f", packed)[0]), "finite float32 scalar required")
        return packed
    except (OverflowError, struct.error) as error:
        raise ContextualLegalRuntimeError("float32 scalar exceeds range") from error


def _array(value, shape):
    if not shape:
        return _number(value)
    _require(type(value) is list and len(value) == shape[0], "exact tensor/vector shape required")
    return b"".join(_array(child, shape[1:]) for child in value)


def _shapes(dimension):
    raw = {"projection_down.weight": (8, dimension), "projection_down.bias": (8,),
        "projection_up.weight": (dimension, 8), "projection_up.bias": (dimension,),
        "condition.weight": (32, dimension), "condition.bias": (32,),
        "target_embedding.weight": (32, 16), "decoder.weight_ih_l0": (96, 16),
        "decoder.weight_hh_l0": (96, 32), "decoder.bias_ih_l0": (96,),
        "decoder.bias_hh_l0": (96,), "output.weight": (32, 32), "output.bias": (32,)}
    shapes = {"body.body.body." + key: value for key, value in raw.items()}
    shapes.update({"body.body.source_to_embedding.weight": (16, dimension),
        "body.count_head.weight": (32, dimension), "body.count_head.bias": (32,),
        "body.count_prior_logits": (32,), "body.source_mean": (dimension,), "body.source_scale": (),
        "clause_source_mean": (dimension,), "clause_source_scale": (),
        "clause_to_embedding.weight": (16, 128)})
    for head, outputs in (("non_action_head", 96), ("action_head", 32)):
        shapes.update({head + ".source_projection.weight": (64, dimension),
            head + ".source_projection.bias": (64,), head + ".field_readout.weight": (outputs, 64),
            head + ".field_readout.bias": (outputs,)})
    return shapes, raw


def _tensor_digest(state, shapes, *, integer_buffers=False):
    expected = set(shapes) | ({"head_initialization_seed", "ordered_clause_recurrent_version"} if integer_buffers else set())
    _require(type(state) is dict and set(state) == expected, "complete exact saved tensor inventory required")
    digest = hashlib.sha256()
    for name in sorted(state):
        if name in shapes:
            digest.update(_raw([name, "torch.float32", list(shapes[name])]))
            digest.update(_array(state[name], shapes[name]))
        else:
            required = 1729 if name == "head_initialization_seed" else 1
            _require(type(state[name]) is int and state[name] == required, "exact saved integer architecture buffer required")
            digest.update(_raw([name, "torch.int64", []]))
            digest.update(struct.pack("=q", state[name]))
    return digest.hexdigest()


def _receipt(value, schema):
    _require(type(value) is dict and value.get("schema") == schema and _hash(value.get("receipt_sha256")),
             "explicit saved preprocessing receipt required")
    _require(value["receipt_sha256"] == _digest({k: v for k, v in value.items() if k != "receipt_sha256"}),
             "saved preprocessing receipt digest differs")


def _false_flags(value):
    for key in ("admitted", "qualified", "proof_authority", "source_semantics_verified", "production_checkpoint",
                "production_runtime_compatible", "formalized", "roundtrip_ok", "runtime_admitted",
                "runtime_release_qualified", "native_ir_format_qualified", "teacher_qualified", "model_task_qualified",
                "source_token_budget_qualified", "output_semantics_verified", "quality_qualified", "checkpoint_promoted",
                "promotion_admitted", "learned_source_text_reconstruction_qualified"):
        if key in value:
            _require(value[key] is False, "saved state must retain false authority: " + key)
    for key in ("decoder_profile_id", "decoder_format_id", "native_ir_schema_version"):
        if key in value:
            _require(value[key] is None, "private state cannot invent a native decoder identity: " + key)
    for item in value.values():
        if type(item) is dict:
            _false_flags(item)


def _normalization(value, dimension):
    _receipt(value, "training-source-normalization/v1")
    _false_flags(value)
    _require(type(value.get("dimension")) is int and value["dimension"] == dimension
        and value.get("kind") == "center_rms" and value.get("scope") == "training_only_frozen_transform"
        and type(value.get("validation_rows_used_for_fitting")) is int and value["validation_rows_used_for_fitting"] == 0,
        "saved TRAIN-only normalization required")
    _array(value.get("mean"), (dimension,))
    _require(type(value.get("scale")) in (int, float) and value["scale"] > 0, "positive saved normalization scale required")
    _require(struct.unpack("=f", _number(value["scale"]))[0] > 0, "saved normalization scale underflows float32")
    _require(_raw(value["mean"]) == _raw(value.get("fitted_training_mean"))
        and _raw(value["scale"]) == _raw(value.get("fitted_training_scale")), "saved fitted normalization differs")


def _documents(checkpoint, preprocessing, donor, dimension, *, _selected_recipe=None):
    _require(type(checkpoint) is dict and checkpoint.get("schema") == "private-native-dimension-source-state/v1"
        and type(checkpoint.get("dimension")) is int and checkpoint["dimension"] == dimension,
        "exact retained private-state schema and native input width required")
    _require(set(checkpoint) == {"architecture", "codec", "dimension", "initializer_receipt", "input_transform", "lineage",
        "model_state", "recipe", "role", "schema", "selected", "tensor_sha256", "weights_sha256", *_STATE_FALSE},
        "closed complete retained state required")
    selected_recipe = ({"name": "continue-lr0001", "learning_rate": .0001}
                       if _selected_recipe is None else _selected_recipe)
    _require(all(checkpoint[key] is False for key in _STATE_FALSE) and checkpoint["selected"] is True
        and checkpoint["role"] == "selected" and _raw(checkpoint["recipe"]) == _raw(selected_recipe),
        "exact selected recipe and false authority required")
    architecture = checkpoint["architecture"]
    _require(type(architecture) is dict and architecture.get("schema") == "ordered-clause-recurrent-source-decoder-development/v1"
        and type(architecture.get("dimension")) is int and architecture["dimension"] == dimension
        and type(architecture.get("max_rules")) is int and architecture["max_rules"] == 8
        and type(architecture.get("vocabulary_size")) is int and architecture["vocabulary_size"] == 32,
        "exact ordered-clause architecture required")
    _false_flags(architecture)
    codec = checkpoint["codec"]
    _require(type(codec) is dict and set(codec) == {"schema", "target_vocabulary"} and codec["schema"] == "typed-json-lexical/v1"
        and type(codec["target_vocabulary"]) is list and len(codec["target_vocabulary"]) == 32
        and codec["target_vocabulary"][:3] == ["<pad>", "<bos>", "<eos>"]
        and all(type(t) is str and 0 < len(t) <= 64 for t in codec["target_vocabulary"])
        and len(set(codec["target_vocabulary"])) == 32 and architecture.get("codec_sha256") == _digest(codec),
        "exact saved lexical codec required")
    shapes, raw_shapes = _shapes(dimension)
    _require(checkpoint["weights_sha256"] == _digest(checkpoint["model_state"]), "saved model-state canonical digest differs")
    tensor_sha = _tensor_digest(checkpoint["model_state"], shapes, integer_buffers=True)
    _require(_hash(checkpoint["tensor_sha256"]) and tensor_sha == checkpoint["tensor_sha256"],
             "saved typed tensor digest differs")
    _require(type(preprocessing) is dict and type(preprocessing.get("dimension")) is int and preprocessing["dimension"] == dimension,
             "saved preprocessing width differs")
    _false_flags(preprocessing)
    _require(_raw(checkpoint["initializer_receipt"]) == _raw(preprocessing.get("initializer")), "saved initializer join differs")
    initializer = checkpoint["initializer_receipt"]
    _receipt(initializer, "dimension-native-raw-decoder-development/v1")
    _false_flags(initializer)
    for key, expected in (("dimension", dimension), ("projection_width", 8), ("hidden_width", 32),
                          ("token_embedding_width", 16), ("source_seed", 1729)):
        _require(type(initializer.get(key)) is int and initializer[key] == expected, "saved native initializer geometry differs")
    transform = checkpoint["input_transform"]
    _require(type(transform) is dict and set(transform) == {"mode", "origin", "mean", "scale"}
        and transform["mode"] == "center_rms" and transform["origin"] == "training_only"
        and _raw(transform) == _raw(preprocessing.get("input_transform")), "saved TRAIN-only input transform differs")
    _array(transform["mean"], (dimension,))
    _require(type(transform["scale"]) in (int, float) and transform["scale"] > 0, "positive input transform scale required")
    _require(struct.unpack("=f", _number(transform["scale"]))[0] > 0, "saved input transform scale underflows float32")
    paragraph, clause = preprocessing.get("paragraph_normalization"), preprocessing.get("clause_normalization")
    _normalization(paragraph, dimension)
    _normalization(clause, dimension)
    _require(_raw(paragraph) == _raw(architecture.get("normalization"))
        and _raw(clause) == _raw(architecture.get("clause_normalization")), "saved architecture normalization joins differ")
    _require(all(_hash(value.get("training_rows_sha256")) for value in (paragraph, clause)),
             "saved normalization TRAIN cohort digests required")
    prior = preprocessing.get("count_prior")
    _receipt(prior, "training-source-count-prior/v1")
    _false_flags(prior)
    _require(prior.get("scope") == "training_only_frozen_count_prior"
        and prior.get("target_access") == "authenticated_training_count_labels_only"
        and type(prior.get("validation_rows_used_for_fitting")) is int and prior["validation_rows_used_for_fitting"] == 0
        and type(prior.get("count_classes")) is list and all(type(n) is int for n in prior["count_classes"])
        and prior["count_classes"] == list(range(1, 33)), "saved frozen TRAIN-only count prior required")
    _array(prior.get("log_prior"), (32,))
    _require(_hash(prior.get("training_rows_sha256"))
        and prior["training_rows_sha256"] == paragraph["training_rows_sha256"] == clause["training_rows_sha256"],
        "saved paragraph/clause/prior TRAIN cohort joins differ")
    base = architecture.get("base_architecture")
    _require(type(base) is dict and _raw(base.get("count_prior")) == _raw(prior), "saved count prior architecture join differs")
    state = checkpoint["model_state"]
    for key, value in (("body.source_mean", paragraph["mean"]), ("body.source_scale", paragraph["scale"]),
                       ("clause_source_mean", clause["mean"]), ("clause_source_scale", clause["scale"]),
                       ("body.count_prior_logits", prior["log_prior"])):
        _require(_array(state[key], shapes[key]) == _array(value, shapes[key]), "saved frozen normalization/prior tensor differs")
    _require(type(donor) is dict and donor.get("domain_id") == "legal_ir" and type(donor.get("dimension")) is int
        and donor["dimension"] == 384 and _raw(donor.get("codec")) == _raw(codec), "original Legal384 donor/codec differs")
    _false_flags(donor)
    _require(donor.get("weights_sha256") == _digest(donor.get("model_state")), "original donor weights digest differs")
    _, donor_shapes = _shapes(384)
    _require(_tensor_digest(donor["model_state"], donor_shapes) == initializer.get("donor_tensor_sha256"),
             "original raw donor tensor identity differs")
    lineage = checkpoint["lineage"]
    _require(type(lineage) is dict and lineage.get("domain") == "legal_ir"
        and lineage.get("teacher_codec_sha256") == _digest(codec)
        and _hash(lineage.get("teacher_checkpoint_sha256"))
        and _hash(lineage.get("input_provenance_sha256"))
        and lineage["input_provenance_sha256"] == preprocessing.get("source_inputs_sha256")
        and type(lineage.get("teacher_output_limit")) is int and lineage["teacher_output_limit"] == 512,
        "saved donor and source provenance lineage differs")
    initial_state = {}
    copied = ("target_embedding.", "decoder.", "output.")
    for name, shape in raw_shapes.items():
        saved = state["body.body.body." + name]
        if name.startswith(copied):
            initial_state[name] = donor["model_state"][name]
        elif name.startswith("projection_down."):
            initial_state[name] = saved
        else:
            zero = lambda dims: 0. if not dims else [zero(dims[1:]) for _ in range(dims[0])]
            initial_state[name] = zero(shape)
            if name.startswith("projection_up."):
                _require(_array(saved, shape) == _array(initial_state[name], shape), "frozen native projection-up must be zero")
    _require(_tensor_digest(initial_state, raw_shapes) == initializer.get("initial_tensor_sha256"),
             "saved native frozen initialization tensor identity differs")
    config = donor.get("config")
    _require(type(config) is dict and all(type(config.get(k)) is int and config[k] == v for k, v in
        (("hidden_size", 32), ("projection_width", 8), ("token_embedding_dim", 16), ("max_target_tokens", 512), ("seed", 1729))),
        "original donor numerical geometry differs")
    return {"checkpoint": checkpoint, "preprocessing": preprocessing,
            "donor_checkpoint": {key: donor[key] for key in ("codec", "config", "model_state")}}


def _sources(rows, contexts, dimension, row_ids, source_binding):
    _require(type(rows) is list and 1 <= len(rows) <= 4096 and type(contexts) is dict, "closed source-only cached split required")
    by_id, normalized, sources = {}, set(), []
    for index, row in enumerate(rows):
        _require(type(row) is dict and set(row) == {"id", "source_text", "input"}, "source-only row must exclude gold/targets")
        _text(row["id"], 512, "source row id")
        text = _text(row["source_text"], 131072, "source text")
        norm = " ".join(row["source_text"].casefold().split())
        _require(row["id"] not in by_id and norm not in normalized, "unique source IDs and normalized texts required")
        _array(row["input"], (dimension,))
        _require(abs(math.fsum(float(n)**2 for n in row["input"]) - 1.) <= 1e-4, "original normalized paragraph vector required")
        descriptor = contexts.get(row["id"])
        _require(type(descriptor) is dict and set(descriptor) == {"source_sha256", "segments"}
            and descriptor["source_sha256"] == hashlib.sha256(text).hexdigest(), "literal source context binding differs")
        pieces = row["source_text"].split("\n\n")
        _require(type(descriptor["segments"]) is list and 1 <= len(pieces) <= 8
            and len(descriptor["segments"]) == len(pieces) and all(piece.strip() for piece in pieces), "one to eight literal clauses required")
        char = byte = 0
        for piece, segment in zip(pieces, descriptor["segments"]):
            encoded = piece.encode("utf-8")
            _require(type(segment) is dict and set(segment) == {"source_text", "source_sha256", "embedding_sha256", "vector",
                "char_start", "char_end", "byte_start", "byte_end"} and segment["source_text"] == piece,
                "closed literal source-clause descriptor required")
            _array(segment["vector"], (dimension,))
            _require(abs(math.fsum(float(n)**2 for n in segment["vector"]) - 1.) <= 1e-4, "original normalized clause vector required")
            _require(segment["source_sha256"] == hashlib.sha256(encoded).hexdigest()
                and segment["embedding_sha256"] == _digest(segment["vector"]), "clause source/vector digest differs")
            for key, expected in (("char_start", char), ("char_end", char + len(piece)),
                                  ("byte_start", byte), ("byte_end", byte + len(encoded))):
                _require(type(segment[key]) is int and segment[key] == expected, "literal clause offsets differ")
            char += len(piece) + 2
            byte += len(encoded) + 2
        by_id[row["id"]] = (index, row, descriptor)
        normalized.add(norm)
        sources.append(row["id"])
    _require(set(contexts) == set(by_id) and all(identifier in by_id for identifier in row_ids), "exact selected source/context membership required")
    _require(type(source_binding) is dict and source_binding.get("schema") == "training-source-clause-context/v1"
        and source_binding.get("reference_labels_accessed") is False, "saved target-free source binding required")
    validation = source_binding.get("validation")
    _require(type(validation) is dict and validation.get("schema") == "source-clause-context/v1"
        and type(validation.get("dimension")) is int and validation["dimension"] == dimension
        and validation.get("reference_labels_accessed") is False
        and validation.get("contexts_sha256") == _digest(contexts), "saved original source-context split digest differs")
    inventory = [{"id": row["id"], "source_sha256": contexts[row["id"]]["source_sha256"]} for row in rows]
    _require(_raw(validation.get("source_inventory")) == _raw(inventory), "saved original source-only row inventory/order differs")
    selected, selected_contexts, receipts = [], {}, []
    for identifier in row_ids:
        index, row, descriptor = by_id[identifier]
        selected.append(row)
        selected_contexts[identifier] = descriptor
        receipts.append(dict(id=identifier, row_index=index, source_sha256=descriptor["source_sha256"],
            input_sha256=_digest(row["input"]), context_sha256=_digest(descriptor),
            source_clause_count=len(descriptor["segments"]), source_padding_mask=[True]*len(descriptor["segments"])+[False]*(8-len(descriptor["segments"]))))
    return {"rows": selected, "contexts": selected_contexts}, receipts


def _capture(request, checkpoint_pin, preprocessing_pin, donor_checkpoint_pin, source_inputs_pin,
             source_contexts_pin, source_owner_pins, row_ids, deadline_seconds, max_reference_bytes):
    _require(type(request) is dict and set(request) == _REQUEST_FIELDS, "closed five-field contextual request required")
    _require(type(request["ir_family_id"]) is str and request["ir_family_id"] == "legal_ir"
        and type(request["dimension"]) is int and request["dimension"] in (384, 768)
        and type(request["dimension_role"]) is str and request["dimension_role"] == "input_embedding"
        and type(request["task_id"]) is str and request["task_id"] == "semantic_IR_reconstruction"
        and _hash(request["checkpoint_sha256"]), "only separate retained Legal384/768 contextual paths are supported")
    _require(type(max_reference_bytes) is int and 0 < max_reference_bytes <= MAX_REFERENCE_BYTES, "exact bounded reference cap required")
    _require(type(deadline_seconds) in (int, float) and math.isfinite(deadline_seconds) and 0 < deadline_seconds <= 120,
             "finite bounded inference deadline required")
    _require(type(row_ids) in (list, tuple) and 1 <= len(row_ids) <= 64, "one to 64 explicit ordered row IDs required")
    for identifier in row_ids:
        _text(identifier, 512, "selected row id")
    _require(len(set(row_ids)) == len(row_ids), "unique ordered row IDs required")
    _require(type(source_owner_pins) is dict and set(source_owner_pins) == set(SOURCE_OWNER_NAMES), "exact thirteen-owner source closure required")
    pins = {"checkpoint": _pin(checkpoint_pin, max_reference_bytes), "preprocessing": _pin(preprocessing_pin, max_reference_bytes),
        "donor_checkpoint": _pin(donor_checkpoint_pin, max_reference_bytes), "source_inputs": _pin(source_inputs_pin, max_reference_bytes),
        "source_contexts": _pin(source_contexts_pin, max_reference_bytes)}
    for name in SOURCE_OWNER_NAMES:
        pin = _pin(source_owner_pins[name], 512*1024)
        _require(pin["path"] == str(Path(__file__).with_name(name + ".py")), "source owner must be the fixed current library file")
        pins["source:" + name] = pin
    _require(sum(pin["bytes"] for pin in pins.values()) <= MAX_TOTAL_BYTES, "aggregate contextual custody bytes exceed bound")
    _require(request["checkpoint_sha256"] == pins["checkpoint"]["sha256"], "exact selected checkpoint request differs")
    return {"request": dict(request), "pins": pins, "row_ids": list(row_ids),
            "deadline_seconds": deadline_seconds, "max_reference_bytes": max_reference_bytes}


def _prepare(options, *, _selected_recipe=None):
    pins = options["pins"]
    witnesses = {name: _witness(pin["path"]) for name, pin in pins.items()}
    documents = {name: _json(_read(pin, retain=True)) for name, pin in pins.items() if not name.startswith("source:")}
    for name, pin in pins.items():
        if name.startswith("source:"):
            _read(pin)
    dimension = options["request"]["dimension"]
    prepared = _documents(documents["checkpoint"], documents["preprocessing"], documents["donor_checkpoint"], dimension,
                          _selected_recipe=_selected_recipe)
    _require(documents["checkpoint"]["lineage"]["teacher_checkpoint_sha256"] == pins["donor_checkpoint"]["sha256"],
             "exact donor checkpoint lineage pin differs")
    inputs, row_receipts = _sources(documents["source_inputs"], documents["source_contexts"], dimension, options["row_ids"],
                                  documents["preprocessing"].get("source_binding"))
    checkpoint, preprocessing = documents["checkpoint"], documents["preprocessing"]
    plan = dict(schema=SCHEMA, request=options["request"], artifact_receipts={name: pin for name, pin in pins.items() if not name.startswith("source:")},
        source_owner_receipts={name[7:]: pin for name, pin in pins.items() if name.startswith("source:")},
        row_ids=options["row_ids"], source_inputs=inputs, row_receipts=row_receipts,
        state_serialization_schema=checkpoint["schema"], native_ir_schema_version=None,
        decoder_profile_id=None, decoder_format_id=None, complete_runtime_io_contract=False,
        codec=checkpoint["codec"], codec_sha256=_digest(checkpoint["codec"]), model_tensor_sha256=checkpoint["tensor_sha256"],
        input_transform_sha256=_digest(checkpoint["input_transform"]), saved_preprocessing_sha256=_digest(preprocessing),
        input_contract=dict(paragraph_width=dimension, clause_width=dimension, max_source_clauses=8,
            paragraph_vector_binding="caller_pinned_asset_bytes", saved_paragraph_vector_producer_authenticated=False,
            clause_vectors="original_raw_cached_vectors", transform_order="saved_TRAIN_input_transform_then_zero_pad_to_eight",
            decoder_feature_normalizations="saved_separate_paragraph_and_clause_stages_once", source_only=True),
        numerical_setup=dict(device="cpu", dtype="float32", required_cpu_threads=1, caller_configures_threads_explicitly=True),
        budgets=dict(encoder_experiment_tokens=512, decoder_output_tokens=512, batch_size=8, deadline_seconds=options["deadline_seconds"],
                     long_span8192_qualified=False), authority=dict(_AUTHORITY), model_load_performed=False,
        model_inference_executed=False, original_targets_accessed=False, consistency_scope=_SCOPE)
    _fence(pins, witnesses)
    return json.loads(_raw(plan)), prepared, witnesses


def prepare_contextual_legal_ir_runtime(request, *, checkpoint_pin, preprocessing_pin, donor_checkpoint_pin,
        source_inputs_pin, source_contexts_pin, source_owner_pins, row_ids, deadline_seconds=120, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Authenticate exact retained state and source-only cache selection; never load a model."""
    try:
        options = _capture(request, checkpoint_pin, preprocessing_pin, donor_checkpoint_pin, source_inputs_pin,
            source_contexts_pin, source_owner_pins, row_ids, deadline_seconds, max_reference_bytes)
        return _prepare(options)[0]
    except (OSError, RuntimeError, OverflowError, TypeError, UnicodeError) as error:
        raise ContextualLegalRuntimeError("cannot prepare bounded contextual replay: " + str(error)) from error


def _numeric_owner(plan):
    owner = importlib.import_module(__package__ + ".contextual_legal_ir_numeric")
    _verify_origins(plan)
    return owner


def _verify_origins(plan):
    """Check loaded origins without importing still-lazy numerical owners."""
    for name, pin in plan["source_owner_receipts"].items():
        module = sys.modules.get(__package__ + "." + name)
        if module is not None:
            _require(getattr(module, "__file__", None) == pin["path"], "loaded numerical/source owner origin differs")


class _ContextualLegalAutoencoder:
    def __init__(self, owner, model, options, plan, witnesses, *, _prepare_plan=None):
        self._owner, self._model = owner, model
        self._prepare_plan = _prepare if _prepare_plan is None else _prepare_plan
        self._options_bytes, self._plan_bytes = _raw(options), _raw(plan)
        self._witnesses = witnesses
        self._inference_started = self._inferred = False

    def _recheck(self):
        options = json.loads(self._options_bytes)
        plan, _, _ = self._prepare_plan(options)
        _require(_raw(plan) == self._plan_bytes, "contextual captured plan changed after opening")
        _verify_origins(plan)
        _fence(options["pins"], self._witnesses)
        return plan

    def describe(self):
        plan = json.loads(self._plan_bytes)
        return {"schema": "contextual-legal-ir-runtime-description/v1", "request": plan["request"],
            "artifact_receipts": plan["artifact_receipts"], "source_owner_receipts": plan["source_owner_receipts"],
            "input_contract": plan["input_contract"],
            "row_ids": plan["row_ids"], "state_serialization_schema": plan["state_serialization_schema"],
            "native_ir_schema_version": None, "decoder_profile_id": None, "decoder_format_id": None,
            "complete_runtime_io_contract": False, "model_load_started": True, "model_load_performed": True,
            "model_inference_started": self._inference_started, "cached_inference_executed": self._inferred,
            "authority": dict(_AUTHORITY), "budgets": plan["budgets"], "consistency_scope": _SCOPE}

    def infer_cached(self):
        """Generate ordered candidates using only the selected original source packets."""
        result = None
        started = returned = False
        try:
            plan = self._recheck()
            source_inputs = json.loads(_raw(plan["source_inputs"]))
            before = _raw(source_inputs)
            self._inference_started = started = True
            result = self._owner.infer_contextual_legal_model(self._model, source_inputs,
                output_cap=512, deadline_seconds=plan["budgets"]["deadline_seconds"], batch_size=8)
            self._inferred = returned = True
            _require(_raw(source_inputs) == before, "numerical owner mutated source-only call packet")
            detached = json.loads(_raw(result))
            self._recheck()
            return {"schema": "contextual-legal-ir-cached-inference/v1", "runtime_selection": self.describe(),
                "row_receipts": plan["row_receipts"], "raw_candidate_report": detached,
                "model_inference_executed": True, "original_targets_accessed": False,
                "authority": dict(_AUTHORITY), "budgets": plan["budgets"], "consistency_scope": _SCOPE}
        except Exception as error:
            refused = error if isinstance(error, ContextualLegalRuntimeError) else ContextualLegalRuntimeError(str(error))
            refused.model_load_started = refused.model_load_performed = True
            refused.model_inference_started, refused.model_inference_executed = started, returned
            if returned:
                try:
                    refused.raw_candidate_report = json.loads(_raw(result))
                except Exception:
                    pass
            if refused is error:
                raise
            raise refused from error


def open_contextual_legal_ir_autoencoder(request, *, checkpoint_pin, preprocessing_pin, donor_checkpoint_pin,
        source_inputs_pin, source_contexts_pin, source_owner_pins, row_ids, deadline_seconds=120, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Lazy-load the fixed contextual numerical owner after source-only admission."""
    started = returned = False
    try:
        options = _capture(request, checkpoint_pin, preprocessing_pin, donor_checkpoint_pin, source_inputs_pin,
            source_contexts_pin, source_owner_pins, row_ids, deadline_seconds, max_reference_bytes)
        plan, prepared, witnesses = _prepare(options)
        owner = _numeric_owner(plan)
        _fence(options["pins"], witnesses)
        started = True
        model = owner.restore_contextual_legal_model(json.loads(_raw(prepared)))
        returned = True
        wrapped = _ContextualLegalAutoencoder(owner, model, options, plan, witnesses)
        wrapped._recheck()
        return wrapped
    except Exception as error:
        refused = error if isinstance(error, ContextualLegalRuntimeError) else ContextualLegalRuntimeError(str(error))
        refused.model_load_started, refused.model_load_performed = started, returned
        if refused is error:
            raise
        raise refused from error


__all__ = ["SCHEMA", "SOURCE_OWNER_NAMES", "MAX_REFERENCE_BYTES", "ContextualLegalRuntimeError",
           "prepare_contextual_legal_ir_runtime", "open_contextual_legal_ir_autoencoder"]
