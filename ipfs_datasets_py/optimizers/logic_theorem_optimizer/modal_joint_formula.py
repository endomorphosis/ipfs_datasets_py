"""Attach separately owned learned projections/formula heads to modal lineages.

The historical numerical core remains an immutable feature extractor in this
profile. The residual embedding projection and formula decoder train together.
Formula gradients do not update the old Python sparse tables. Inputs still
include parser-derived modal features; this is not independent source-only NLP.
"""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import importlib
import inspect
import json
import math
from pathlib import Path
import time

from .autoencoder_lineages._contract import require_canonical_modules, validate_sample, validate_vector

PROFILE = "modal-latent-joint-formula/v1"
MAX_ROWS = 256
MAX_HEAD_BYTES = 64 * 1024 * 1024
FALSE = {"qualified": False, "admitted": False, "formalized": False,
         "roundtrip_ok": False, "promotion_performed": False}


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _core_binding(model):
    """Bind state/configuration and listed source files, never mutable filenames."""
    require_canonical_modules(model._implementation_class.__module__)
    model._validate_state(model.state, scan_rows=True)
    _require(model.feature_codec is None, "joint formula v1 requires the default raw feature extractor; external codecs need a versioned binding")
    _require(getattr(model, "_legacy_embedding_adapters", None) is None,
             "joint formula v1 does not accept an unbound legacy adapter")
    config = {}
    for name, parameter in inspect.signature(model._implementation_class.__init__).parameters.items():
        if name in {"self", "state", "feature_codec", "legacy_embedding_adapters"}:
            continue
        value = getattr(model, name, parameter.default)
        if name == "compute_device":
            value = str(value)
        if value is inspect.Parameter.empty:
            raise ValueError("unbound core configuration: " + name)
        # A closed serializable constructor configuration is a compatibility
        # boundary; never pickle arbitrary providers into a decoder checkpoint.
        _raw(value)
        config[name] = value
    source = Path(inspect.getfile(model._implementation_class))
    helper = Path(__file__)
    contract = helper.parent / "autoencoder_lineages/_contract.py"
    profile = Path(inspect.getfile(type(model)))
    sources = {str(p.relative_to(helper.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in (source, helper, contract, profile)}
    return {"domain": "legal_ir", "lineage_id": model.LINEAGE_ID,
            "dimension": model.DIMENSION, "runtime_profile": PROFILE,
            "core_sha256": hashlib.sha256(_raw({"state": model.state.to_dict(),
                "config": config, "sources": sources,
                "implementation_module": model._implementation_class.__module__})).hexdigest()}


def raw_projection(model, sample):
    """Exact additive decoder candidate, before target-point safety projection.

    This read-only spelling mirrors the frozen legacy addition order. No
    monkeypatching or copying of the historical implementation is necessary.
    Both widths use this path, and parity tests bind it to their actual cores.
    """
    validate_sample(sample, model.DIMENSION)
    _require(not model._legal_ir_view_target_cache and not model._legal_ir_loss_target_cache,
             "joint formula input cannot use cached teacher bridge targets")
    # Some historical view feature helpers inspect per-sample logit *keys*
    # even with use_sample_memory=False. Read through a worker-private shallow
    # view with both memory tables excluded. Sparse weight dictionaries stay
    # shared read-only; the caller's core, memory and caches are never swapped.
    model = copy.copy(model)
    model.state = replace(model.state, family_logits={}, decoded_embeddings={})
    model._sample_feature_cache = {}
    model._invalidate_legal_ir_view_family_candidates()
    base = model._base_decoded_for(sample)
    dimensions = len(base)
    names = (
        ("compiler_quality", False), ("logic_signature", False),
        ("round_trip_signal", False), ("decompiler_plan", False),
        ("predicate_argument", False), ("family", True),
        ("semantic_slot", False), ("family_semantic_slot", True),
        ("semantic_slot_legal_ir_view", True), ("family_semantic_slot_legal_ir_view", True),
        ("family_legal_ir_view", True), ("legal_ir_view", True), ("feature", False),
    )
    adjustments = []
    for name, memory in names:
        kwargs = {"dimensions": dimensions}
        if memory:
            kwargs["use_sample_memory"] = False
        adjustments.append(getattr(model, "_" + name + "_embedding_adjustment")(sample, **kwargs))
    adjustments.append(model._legacy_embedding_tail_adjustment(sample, dimensions=dimensions, use_sample_memory=False))
    result = []
    for index, value in enumerate(base):
        for adjustment in adjustments:
            value = value + adjustment[index]
        result.append(float(value))
    validate_vector(result, model.DIMENSION, "raw joint formula input")
    return result


def _samples(model, samples):
    from itertools import islice
    rows = list(islice(iter(samples), MAX_ROWS + 1))
    _require(1 <= len(rows) <= MAX_ROWS, "joint formula batches require 1..256 samples")
    seen = set()
    parser_module = importlib.import_module(model._implementation_class.__module__.rsplit(".", 1)[0] + ".legal_modal_parser")
    normalizer = parser_module.LegalModalParser()
    for row in rows:
        validate_sample(row, model.DIMENSION)
        _require(type(row.sample_id) is str and row.sample_id and row.sample_id not in seen,
                 "joint formula sample IDs must be unique nonempty strings")
        _require(type(row.text) is str and 0 < len(row.text) <= 16384,
                 "joint formula samples need bounded exact source text")
        normalized = normalizer.normalize_text(row.text)
        _require(row.normalized_text == normalized and row.modal_ir.normalized_text == normalized
                 and row.modal_ir.document_id == row.sample_id,
                 "modal parser features must bind the exact sample identity and normalized source")
        seen.add(row.sample_id)
    return rows


def _rows(model, samples, targets=None):
    samples = _samples(model, samples)
    if targets is not None:
        _require(type(targets) in (list, tuple) and len(targets) == len(samples),
                 "one explicit formula target per training sample required")
    # Private runtime caches are observations only. Discard stale feature rows;
    # teacher caches above must be empty rather than silently erased.
    _require(not model._legal_ir_view_target_cache and not model._legal_ir_loss_target_cache,
             "joint formula input cannot use cached teacher bridge targets")
    model._sample_feature_cache.clear()
    model._invalidate_legal_ir_view_family_candidates()
    rows = []
    for index, sample in enumerate(samples):
        row = {"id": sample.sample_id, "source_text": sample.text,
               "latent": raw_projection(model, sample)}
        if targets is not None:
            target = targets[index]
            _require(type(target) is dict and set(target) == {"id", "source_text", "canonical_ir"},
                     "closed id/source_text/canonical_ir formula target required")
            _require(target["id"] == sample.sample_id and target["source_text"] == sample.text,
                     "formula target must bind the exact sample ID and text")
            row.update(embedding=list(sample.embedding_vector), canonical_ir=target["canonical_ir"])
        rows.append(row)
    return rows


def attach(model, checkpoint):
    from . import modal_latent_formula as learning
    binding = _core_binding(model)
    _require(type(checkpoint) is dict and checkpoint.get("binding") == binding,
             "formula decoder belongs to another core, lineage or configuration")
    owned = json.loads(_raw(checkpoint))
    decoder = learning.LatentFormulaDecoder(owned, expected_binding=binding)
    model._joint_formula_checkpoint = owned
    model._joint_formula_decoder = decoder
    return describe(model)


def describe(model):
    checkpoint = getattr(model, "_joint_formula_checkpoint", None)
    return {"attached": checkpoint is not None, "profile": PROFILE,
        "dimension": model.DIMENSION, "lineage_id": model.LINEAGE_ID,
        "formula_input": "raw_modal_embedding_before_safety_projection",
        "parser_features_in_input": True, "source_only": False,
        "sample_memory_used": False, "teacher_bridge_cache_used": False,
        "trained_components": ["residual_embedding_projection", "formula_token_decoder"],
        "core_sparse_weights_frozen": True,
        "supported_projections": ["typed_deontic_rule_v1"],
        "full_logic_floor_coverage": False,
        "checkpoint_sha256": None if checkpoint is None else hashlib.sha256(_raw(checkpoint)).hexdigest(),
        **FALSE}


def _attached_checkpoint(model, *, validate_runtime=False):
    """Bind the cached execution model to the exact privately owned sidecar."""
    checkpoint = getattr(model, "_joint_formula_checkpoint", None)
    decoder = getattr(model, "_joint_formula_decoder", None)
    _require(checkpoint is not None and decoder is not None,
             "learned latent formula decoder requires training or an attached checkpoint")
    _require(hashlib.sha256(_raw(checkpoint)).hexdigest() == decoder.checkpoint_sha256,
             "cached formula decoder differs from attached checkpoint; reattach explicitly")
    if validate_runtime:
        decoder._check()
    return checkpoint


def train(model, samples, targets, *, validation_samples, validation_targets,
          epochs=20, max_seconds=60, formula_options=None, max_optimizer_steps=None):
    from . import modal_latent_formula as learning
    started = time.monotonic()
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 3600,
             "joint formula training requires a positive bounded deadline")
    binding = _core_binding(model)
    training = _rows(model, samples, targets)
    tuning = _rows(model, validation_samples, validation_targets)
    checkpoint = getattr(model, "_joint_formula_checkpoint", None)
    if checkpoint is None:
        _require(formula_options is None or type(formula_options) is dict, "formula_options must be a mapping")
        checkpoint = learning.build_checkpoint(binding, training, tuning, **(formula_options or {}))
    else:
        checkpoint = _attached_checkpoint(model, validate_runtime=True)
        _require(not formula_options, "resumed decoder configuration is immutable")
        _require(checkpoint["binding"] == binding, "core changed after decoder attachment; explicit new branch required")
    remaining = max_seconds - (time.monotonic() - started)
    if remaining <= 0:
        raise TimeoutError("joint formula preparation exhausted training deadline; no model update committed")
    result = learning.train(checkpoint, training, tuning, epochs=epochs,
                            max_seconds=remaining, max_optimizer_steps=max_optimizer_steps)
    _require(_core_binding(model) == binding, "core changed during joint formula training")
    attach(model, result["checkpoint"])
    result["report"]["pipeline_elapsed_seconds"] = time.monotonic() - started
    result["report"]["joint_profile"] = describe(model)
    return result


def infer(model, samples):
    checkpoint = _attached_checkpoint(model)
    binding = _core_binding(model)
    _require(checkpoint["binding"] == binding, "core changed after decoder attachment")
    samples = _samples(model, samples)
    _require(len(samples) <= 128, "joint formula inference requires at most 128 samples")
    rows = _rows(model, samples)
    result = model._joint_formula_decoder.infer(rows)
    vectors = model._joint_formula_decoder.project([row["latent"] for row in rows])
    result["decoded_embeddings"] = {row["id"]: vector for row, vector in zip(rows, vectors)}
    result["reconstruction_loss"] = sum(
        sum((float(expected) - actual) ** 2 for expected, actual in zip(sample.embedding_vector, vector))
        / model.DIMENSION for sample, vector in zip(samples, vectors)) / len(samples)
    result["reconstruction_scope"] = "learned_projection_before_target_safety_or_sample_memory"
    _require(_core_binding(model) == binding, "core changed during formula inference")
    result["joint_profile"] = describe(model)
    return result


def projected_embedding(model, sample):
    checkpoint = _attached_checkpoint(model)
    _require(checkpoint is not None and checkpoint["binding"] == _core_binding(model),
             "attached formula projection differs from numerical core")
    rows = _rows(model, [sample])
    return model._joint_formula_decoder.project([rows[0]["latent"]])[0]


def save(model, path):
    checkpoint = _attached_checkpoint(model, validate_runtime=True)
    _require(checkpoint is not None and checkpoint["binding"] == _core_binding(model), "no valid attached formula checkpoint")
    data = _raw(checkpoint)
    _require(len(data) <= MAX_HEAD_BYTES, "formula checkpoint exceeds byte bound")
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(data)
    return {"path": str(path.absolute()), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "core_weights_included": False, **FALSE}


def load(model, path, *, expected_sha256):
    from . import modal_latent_formula as learning
    checkpoint = learning.load_checkpoint(path, expected_sha256=expected_sha256,
                                          expected_binding=_core_binding(model))
    return attach(model, checkpoint)
