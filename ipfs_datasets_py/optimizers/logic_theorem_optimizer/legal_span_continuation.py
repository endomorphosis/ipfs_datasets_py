"""Explicit warm-start lineage around the frozen LegalIR source-span decoder.

The outer checkpoint is authoritative for weight provenance. Its
``base_checkpoint`` uses the unchanged span runtime's constructor configuration
(which says ``from_scratch``), but every model tensor was copied from the
embedded, hash-bound source parent before any continuation update. Adam moments
restart once at that boundary and resume exactly thereafter. Targets and example
texts are never embedded in this wrapper or exposed to its inference API.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import stat

from . import legal_span_formula as span

SCHEMA = "warm-start-span-legal-formula-checkpoint/v1"
LINEAGE_ID = "warm_start_source_span_formula_v1"
MAX_BYTES = 128 * 1024 * 1024
FALSE = span.FALSE
_require = span._require
_raw = span._raw
checkpoint_digest = span.checkpoint_digest
_INITIALIZATION = {
    "mode": "warm_start_all_source_parent_model_tensors",
    "optimizer": "fresh_adam_at_warm_start_then_exact_moment_resumption",
    "base_config_initialization_scope": "standalone_constructor_descriptor; outer_lineage_defines_actual_weight_provenance",
    "all_parent_model_tensors_copied": True,
    "parent_optimizer_moments_transferred": False,
    "trainable_parameters": "all_model_parameters",
}


def _capture_implementation():
    return {"continuation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "base_span": span._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    current = _capture_implementation()
    _require(current == _IMPLEMENTATION_AT_IMPORT, "continuation implementation changed since import")
    return current


def _context_contract(contract):
    _require(type(contract) is dict and set(contract) == {
        "dimension", "representation_id", "producer_sha256", "training_index_sha256"},
        "closed continuation context contract required")
    _require(type(contract["dimension"]) is int and contract["dimension"] == 384,
             "continuation context dimension must be 384")
    _require(type(contract["representation_id"]) is str and
             0 < len(contract["representation_id"].strip()) <= 512, "bounded context representation identity required")
    for field in ("producer_sha256", "training_index_sha256"):
        _require(type(contract[field]) is str and span._SHA.fullmatch(contract[field]), "invalid context " + field)
    return copy.deepcopy(contract)


def _initial_base(base, parent):
    """Reconstruct the zero-update boundary without training examples or targets."""
    initial = copy.deepcopy(base)
    initial["model_state"] = copy.deepcopy(parent["model_state"])
    initial["optimizer_state"] = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
    initial["progress"] = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    initial["parent_checkpoint_sha256"] = None
    return initial


def build_checkpoint(parent, training_examples, tuning_examples=(), *, latent_enabled=True,
                     seed=None, context_contract, learning_rate=.001, batch_size=12):
    """Copy every validated parent's weight and start one new Adam lineage.

    The parent's architecture widths, residual bound, and seed are retained.
    The context interpretation, data manifests, enabled flag, learning rate,
    and batch size are explicit new experimental choices. No old optimizer
    moment is reused, and this function performs no optimizer update.
    """
    span.validate_checkpoint(parent)
    config = parent["config"]
    _require(config["latent_dimension"] == 384, "warm start requires a 384-dimensional span parent")
    _require(parent["progress"]["optimizer_steps"] > 0, "warm start requires a trained source parent")
    selected_seed = config["seed"] if seed is None else seed
    _require(type(selected_seed) is int and selected_seed == config["seed"], "continuation seed must match parent seed")
    contract = _context_contract(context_contract)
    base = span.build_checkpoint(training_examples, tuning_examples, latent_dimension=384,
        latent_enabled=latent_enabled, learning_rate=learning_rate, batch_size=batch_size, seed=selected_seed,
        hidden_size=config["hidden_size"], embedding_dim=config["embedding_dim"],
        projection_width=config["projection_width"], residual_scale=config["residual_scale"])
    base["model_state"] = copy.deepcopy(parent["model_state"])
    span.validate_checkpoint(base)
    parent_hash = checkpoint_digest(parent)
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "initialization": copy.deepcopy(_INITIALIZATION),
        "implementation": _implementation(), "source_parent_checkpoint": copy.deepcopy(parent),
        "source_parent_checkpoint_sha256": parent_hash,
        "source_parent_optimizer_steps": parent["progress"]["optimizer_steps"],
        "initial_model_state_sha256": checkpoint_digest(parent["model_state"]),
        "initial_base_checkpoint_sha256": checkpoint_digest(base),
        "context_contract": contract, "context_contract_sha256": checkpoint_digest(contract),
        "base_checkpoint": base, "parent_checkpoint_sha256": None, **FALSE}
    _require(len(_raw(result)) <= MAX_BYTES, "continuation checkpoint exceeds byte bound")
    return result


def _validated(checkpoint):
    fields = {"schema", "lineage_id", "initialization", "implementation", "source_parent_checkpoint",
        "source_parent_checkpoint_sha256", "source_parent_optimizer_steps", "initial_model_state_sha256",
        "initial_base_checkpoint_sha256", "context_contract", "context_contract_sha256", "base_checkpoint",
        "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed continuation checkpoint schema required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID and
             all(checkpoint[field] is False for field in FALSE), "continuation schema/authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "continuation checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "continuation implementation source drift")
    _require(_raw(checkpoint["initialization"]) == _raw(_INITIALIZATION), "continuation weight provenance differs")
    contract = _context_contract(checkpoint["context_contract"])
    _require(checkpoint["context_contract_sha256"] == checkpoint_digest(contract), "context contract hash differs")
    parent, base = checkpoint["source_parent_checkpoint"], checkpoint["base_checkpoint"]
    span.validate_checkpoint(parent)
    span.validate_checkpoint(base)
    for key in ("source_parent_checkpoint_sha256", "initial_model_state_sha256", "initial_base_checkpoint_sha256"):
        _require(type(checkpoint[key]) is str and span._SHA.fullmatch(checkpoint[key]), "invalid continuation hash")
    _require(checkpoint["source_parent_checkpoint_sha256"] == checkpoint_digest(parent), "source parent hash differs")
    _require(type(checkpoint["source_parent_optimizer_steps"]) is int and
             checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] > 0,
             "source parent optimizer count differs")
    _require(checkpoint["initial_model_state_sha256"] == checkpoint_digest(parent["model_state"]),
             "copied parent model hash differs")
    _require(parent["config"]["latent_dimension"] == base["config"]["latent_dimension"] == contract["dimension"],
             "context/parent/base dimensions differ")
    for key in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale"):
        _require(_raw(base["config"][key]) == _raw(parent["config"][key]), "inherited configuration differs: " + key)
    reconstructed = _initial_base(base, parent)
    _require(checkpoint["initial_base_checkpoint_sha256"] == checkpoint_digest(reconstructed),
             "initial continuation boundary differs")
    previous = checkpoint["parent_checkpoint_sha256"]
    _require(previous is None or type(previous) is str and span._SHA.fullmatch(previous),
             "invalid preceding continuation hash")
    if base["progress"]["optimizer_steps"] == 0:
        _require(base["model_state"] == parent["model_state"], "zero-update model differs from copied source parent")
    else:
        _require(previous is not None, "trained continuation requires previous outer checkpoint hash")
    return base


def validate_checkpoint(checkpoint):
    _validated(checkpoint)


def initial_model_digest(checkpoint):
    """Identity of all copied tensors before any new optimizer update."""
    _validated(checkpoint)
    return checkpoint["initial_model_state_sha256"]


def optimizer_steps(checkpoint):
    """New-lineage update count, excluding the source parent's training."""
    return _validated(checkpoint)["progress"]["optimizer_steps"]


def train_decoder(checkpoint, training_examples, tuning_examples=(), *, max_steps=100, max_seconds=60):
    """Resume child Adam/data state; the embedded source parent stays immutable."""
    base = _validated(checkpoint)
    parent_identity = checkpoint["source_parent_checkpoint_sha256"]
    result = span.train_decoder(base, training_examples, tuning_examples, max_steps=max_steps, max_seconds=max_seconds)
    wrapped = {**copy.deepcopy(checkpoint), "base_checkpoint": result["checkpoint"],
               "parent_checkpoint_sha256": checkpoint_digest(checkpoint)}
    _require(_implementation() == checkpoint["implementation"], "continuation source changed during training")
    _require(checkpoint_digest(wrapped["source_parent_checkpoint"]) == parent_identity, "source parent changed during training")
    _require(len(_raw(wrapped)) <= MAX_BYTES, "continuation checkpoint exceeds byte bound")
    report = {**result["report"], "schema": "warm-start-span-legal-formula-training/v1",
        "checkpoint_sha256": checkpoint_digest(wrapped),
        "base_checkpoint_sha256": checkpoint_digest(result["checkpoint"]),
        "source_parent_checkpoint_sha256": parent_identity,
        "source_parent_optimizer_steps": wrapped["source_parent_optimizer_steps"],
        "continuation_optimizer_steps_total": result["checkpoint"]["progress"]["optimizer_steps"],
        "initialization": copy.deepcopy(_INITIALIZATION),
        "context_contract_sha256": wrapped["context_contract_sha256"],
        "previous_continuation_checkpoint_sha256": wrapped["parent_checkpoint_sha256"]}
    return {"checkpoint": wrapped, "report": report}


class SpanContinuationDecoder:
    """Delegate target-free inference while preserving authoritative outer lineage."""
    def __init__(self, checkpoint):
        base = _validated(checkpoint)
        self._checkpoint = copy.deepcopy(checkpoint)
        self.checkpoint_sha256 = checkpoint_digest(checkpoint)
        self._decoder = span.SpanLegalFormulaDecoder(base)
        self.base_checkpoint_sha256 = checkpoint_digest(base)

    @property
    def checkpoint(self):
        return copy.deepcopy(self._checkpoint)

    @property
    def model(self):
        return self._decoder.model

    def decode_formal_logic(self, texts, latents, *, latent_ablation="none"):
        _require(_implementation() == self._checkpoint["implementation"], "continuation implementation source drift")
        result = self._decoder.decode_formal_logic(texts, latents, latent_ablation=latent_ablation)
        return {**result, "schema": "warm-start-span-legal-formula-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "base_checkpoint_sha256": self.base_checkpoint_sha256,
            "source_parent_checkpoint_sha256": self._checkpoint["source_parent_checkpoint_sha256"],
            "source_parent_optimizer_steps": self._checkpoint["source_parent_optimizer_steps"],
            "context_contract_sha256": self._checkpoint["context_contract_sha256"],
            "initialization": copy.deepcopy(_INITIALIZATION)}


def save_checkpoint(checkpoint, path):
    """Exclusively create bounded JSON data; no executable serialization."""
    validate_checkpoint(checkpoint)
    raw = _raw(checkpoint)
    path = Path(path).absolute()
    _require(path.parent.resolve(strict=True) == path.parent, "canonical existing checkpoint parent required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "schema": SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    _require(type(expected_sha256) is str and span._SHA.fullmatch(expected_sha256), "expected checkpoint hash required")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical checkpoint path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, "bounded regular checkpoint required")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= MAX_BYTES and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
             "checkpoint changed while reading")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint hash differs")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("invalid JSON constant: " + value)
    checkpoint = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    validate_checkpoint(checkpoint)
    return checkpoint
