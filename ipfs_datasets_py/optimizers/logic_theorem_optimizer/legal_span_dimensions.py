"""Warm-start open-vocabulary span decoding with explicit native input dimensions.

The unchanged byte encoder, span heads, loss and single-rule grammar come from
legal_span_formula. Source tensors are copied from a trained source-only parent;
dimension-specific adapters start afresh, with an exactly zero output layer.
No embedding is padded, truncated, relabelled, or inferred from a target here.
Context contracts describe inputs; callers must verify their producer receipts.
This module does not implement multi-rule segmentation or legal qualification.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat
import time

from . import legal_span_formula as span

SCHEMA = "native-dimensional-source-span-checkpoint/v1"
LINEAGE_ID = "native_dimensional_source_span_v1"
ARCHITECTURE = "utf8-byte-bidirectional-gru-native-dimensional-film-spans/v1"
MAX_BYTES = 128 * 1024 * 1024
DIMENSIONS = (0, 8, 384, 768)
FALSE = span.FALSE
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
_CONFIG_KEYS = ("latent_dimension", "latent_enabled", "learning_rate", "batch_size", "seed",
                "hidden_size", "embedding_dim", "projection_width", "residual_scale")
_INITIALIZATION = {
    "mode": "copy_all_nonlatent_parent_tensors_reset_dimension_specific_adapter",
    "source_parameters_copied": True,
    "adapter_down": "seeded_constructor_for_declared_input_dimension",
    "adapter_up": "exact_zero_weight_and_bias",
    "optimizer": "fresh_adam_then_exact_moment_resumption",
    "parent_optimizer_moments_transferred": False,
    "trainable_parameters": "all_model_parameters",
}


def _capture_implementation():
    return {"dimensions_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "base_span": span._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    current = _capture_implementation()
    _require(current == _IMPLEMENTATION_AT_IMPORT, "dimensional span source changed since import")
    return current


def _source_state(state):
    return {key: value for key, value in state.items()
            if not key.startswith(("latent_down.", "latent_up."))}


def _config(**kwargs):
    dimension = kwargs["latent_dimension"]
    _require(type(dimension) is int and dimension in DIMENSIONS, "unsupported native input dimension")
    # The frozen constructor validates every other numeric/runtime setting.
    result = span._config(**{**kwargs, "latent_dimension": 384 if dimension else 0})
    result.update(latent_dimension=dimension, architecture=ARCHITECTURE,
                  initialization="copied_source_parent_and_zero_output_native_adapter/v1")
    return result


def _context_contract(contract, dimension):
    if dimension == 0:
        _require(contract is None, "source-only model must not declare native context")
        return None
    _require(type(contract) is dict and set(contract) == {
        "dimension", "representation_id", "producer_sha256", "training_index_sha256"},
        "closed native context contract required")
    _require(type(contract["dimension"]) is int and contract["dimension"] == dimension,
             "native context dimension differs")
    _require(type(contract["representation_id"]) is str and
             0 < len(contract["representation_id"].strip()) <= 512, "bounded representation identity required")
    for key in ("producer_sha256", "training_index_sha256"):
        _require(type(contract[key]) is str and span._SHA.fullmatch(contract[key]), "invalid context hash")
    return copy.deepcopy(contract)


def _initial_state(parent, config):
    import torch
    model = span._model(torch, config)
    state = {name: tensor.detach().tolist() for name, tensor in model.state_dict().items()}
    source = _source_state(parent["model_state"])
    _require(set(source) == set(_source_state(state)), "source architecture tensor names differ")
    state.update(copy.deepcopy(source))
    # Strict shape checks also apply to inherited tensors, before any inference.
    model.load_state_dict({name: span._tensor(torch, state[name], tensor.shape, name)
                           for name, tensor in model.state_dict().items()}, strict=True)
    return state


def build_checkpoint(parent, training_examples, tuning_examples=(), *, latent_dimension=0,
                     latent_enabled=True, seed=None, context_contract=None,
                     learning_rate=.001, batch_size=12):
    """Copy the source model and initialize an explicit new optimizer lineage."""
    span.validate_checkpoint(parent)
    parent_config = parent["config"]
    _require(parent["progress"]["optimizer_steps"] > 0, "trained source parent required")
    _require(not parent_config["latent_enabled"] or parent_config["latent_dimension"] == 0,
             "source-only parent required for matched initialization")
    selected_seed = parent_config["seed"] if seed is None else seed
    _require(type(selected_seed) is int and selected_seed == parent_config["seed"], "seed must match source parent")
    config = _config(latent_dimension=latent_dimension, latent_enabled=latent_enabled,
        seed=selected_seed, learning_rate=learning_rate, batch_size=batch_size,
        **{key: parent_config[key] for key in ("hidden_size", "embedding_dim", "projection_width", "residual_scale")})
    contract = _context_contract(context_contract, latent_dimension)
    span._splits(training_examples, tuning_examples, latent_dimension)
    state = _initial_state(parent, config)
    result = {
        "schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "initialization": copy.deepcopy(_INITIALIZATION), "config": config,
        "context_contract": contract, "context_contract_sha256": checkpoint_digest(contract),
        "source_parent_checkpoint": copy.deepcopy(parent),
        "source_parent_checkpoint_sha256": checkpoint_digest(parent),
        "source_parent_optimizer_steps": parent["progress"]["optimizer_steps"],
        "initial_source_model_sha256": checkpoint_digest(_source_state(state)),
        "initial_model_state_sha256": checkpoint_digest(state),
        "training_manifest_sha256": checkpoint_digest(training_examples), "training_count": len(training_examples),
        "tuning_manifest_sha256": checkpoint_digest(tuning_examples), "tuning_count": len(tuning_examples),
        "model_state": state, "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **FALSE,
    }
    _require(len(_raw(result)) <= MAX_BYTES, "dimensional checkpoint exceeds byte bound")
    return result


def _restore(checkpoint):
    import torch
    fields = {"schema", "lineage_id", "implementation", "initialization", "config", "context_contract",
        "context_contract_sha256", "source_parent_checkpoint", "source_parent_checkpoint_sha256",
        "source_parent_optimizer_steps", "initial_source_model_sha256", "initial_model_state_sha256",
        "training_manifest_sha256", "training_count", "tuning_manifest_sha256", "tuning_count", "model_state",
        "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed dimensional checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID and
             all(checkpoint[key] is False for key in FALSE), "dimensional schema/authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "dimensional checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "dimensional implementation source drift")
    _require(_raw(checkpoint["initialization"]) == _raw(_INITIALIZATION), "initialization policy differs")
    # The frozen numerical factory closes over this dictionary. Own it so a
    # caller cannot change inference gates by mutating its checkpoint afterward.
    config = copy.deepcopy(checkpoint["config"])
    _require(type(config) is dict and set(_CONFIG_KEYS) <= set(config), "incomplete dimensional configuration")
    _require(_raw(config) == _raw(_config(**{key: config[key] for key in _CONFIG_KEYS})), "configuration/runtime differs")
    contract = _context_contract(checkpoint["context_contract"], config["latent_dimension"])
    _require(checkpoint["context_contract_sha256"] == checkpoint_digest(contract), "native context contract changed")
    parent = checkpoint["source_parent_checkpoint"]
    span.validate_checkpoint(parent)
    _require(checkpoint["source_parent_checkpoint_sha256"] == checkpoint_digest(parent), "source parent hash differs")
    _require(type(checkpoint["source_parent_optimizer_steps"]) is int and
             checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] > 0,
             "source parent update count differs")
    _require(not parent["config"]["latent_enabled"] or parent["config"]["latent_dimension"] == 0,
             "source-only parent required")
    for key in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale"):
        _require(_raw(config[key]) == _raw(parent["config"][key]), "inherited configuration differs: " + key)
    initial = _initial_state(parent, config)
    _require(checkpoint["initial_source_model_sha256"] == checkpoint_digest(_source_state(initial)) and
             checkpoint["initial_model_state_sha256"] == checkpoint_digest(initial), "initial weight boundary differs")
    for key in ("training_manifest_sha256", "tuning_manifest_sha256"):
        _require(type(checkpoint[key]) is str and span._SHA.fullmatch(checkpoint[key]), "invalid data manifest hash")
    count, tune_count = checkpoint["training_count"], checkpoint["tuning_count"]
    _require(type(count) is int and 1 <= count <= span.MAX_EXAMPLES and type(tune_count) is int and
             0 <= tune_count <= span.MAX_EXAMPLES, "invalid split counts")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"} and
             all(type(value) is int and 0 <= value <= 10**9 for value in progress.values()), "invalid progress")
    cursor, batch = progress["row_cursor"], config["batch_size"]
    _require(cursor < count and cursor % batch == 0 and progress["optimizer_steps"] ==
             progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch, "step/cursor identity differs")
    previous = checkpoint["parent_checkpoint_sha256"]
    _require(previous is None or type(previous) is str and span._SHA.fullmatch(previous), "invalid preceding checkpoint hash")
    if progress["optimizer_steps"] == 0:
        _require(checkpoint["model_state"] == initial and previous is None, "zero-update state differs from declared initialization")
    else:
        _require(previous is not None, "trained checkpoint lacks previous checkpoint hash")
    model = span._model(torch, config)
    template = model.state_dict()
    weights = checkpoint["model_state"]
    _require(type(weights) is dict and set(weights) == set(template), "model state keys differ")
    model.load_state_dict({key: span._tensor(torch, weights[key], value.shape, key) for key, value in template.items()}, strict=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
    state = checkpoint["optimizer_state"]
    _require(type(state) is dict and set(state) == {"schema", "parameters"} and
             state["schema"] == "adam-default-betas-eps/v1" and type(state["parameters"]) is dict,
             "unsupported optimizer state")
    parameters = dict(model.named_parameters())
    _require(set(state["parameters"]) == (set(parameters) if progress["optimizer_steps"] else set()),
             "optimizer parameter keys differ")
    for name, moment in state["parameters"].items():
        _require(type(moment) is dict and set(moment) == {"step", "exp_avg", "exp_avg_sq"} and
                 type(moment["step"]) is int and moment["step"] == progress["optimizer_steps"], "optimizer step differs")
        parameter = parameters[name]
        optimizer.state[parameter] = {"step": torch.tensor(float(moment["step"])),
            "exp_avg": span._tensor(torch, moment["exp_avg"], parameter.shape, name),
            "exp_avg_sq": span._tensor(torch, moment["exp_avg_sq"], parameter.shape, name, nonnegative=True)}
    model.eval()
    return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


def initial_model_digest(checkpoint):
    validate_checkpoint(checkpoint)
    return checkpoint["initial_model_state_sha256"]


def initial_source_model_digest(checkpoint):
    validate_checkpoint(checkpoint)
    return checkpoint["initial_source_model_sha256"]


def optimizer_steps(checkpoint):
    validate_checkpoint(checkpoint)
    return checkpoint["progress"]["optimizer_steps"]


def train_decoder(checkpoint, training_examples, tuning_examples=(), *, max_steps=100, max_seconds=60):
    """Train equal-weight semantic facets, retaining exact resumable Adam state."""
    _require(type(max_steps) is int and 0 <= max_steps <= 10000, "max_steps must be in 0..10000")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be in 0..3600")
    started = time.monotonic()
    deadline = started + max_seconds
    torch, model, optimizer = _restore(checkpoint)
    _require(checkpoint["training_manifest_sha256"] == checkpoint_digest(training_examples) and
             checkpoint["tuning_manifest_sha256"] == checkpoint_digest(tuning_examples), "resume manifests differ")
    records, tuning = span._splits(training_examples, tuning_examples, checkpoint["config"]["latent_dimension"])
    config, progress = checkpoint["config"], dict(checkpoint["progress"])
    losses, maximum_gradient, reason = [], 0., "step_limit"
    for _ in range(max_steps):
        if time.monotonic() >= deadline:
            reason = "deadline_before_batch"
            break
        order = list(range(len(records)))
        random.Random(config["seed"] + progress["epochs_completed"]).shuffle(order)
        indices = order[progress["row_cursor"]:progress["row_cursor"] + config["batch_size"]]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss = span._loss(torch, model, [records[index] for index in indices])
        _require(bool(torch.isfinite(loss)), "nonfinite training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all()) for parameter in parameters),
                 "missing or nonfinite gradients")
        norm = torch.nn.utils.clip_grad_norm_(parameters, 5, error_if_nonfinite=True)
        maximum_gradient = max(maximum_gradient, float(norm))
        optimizer.step()
        _require(all(bool(torch.isfinite(parameter).all()) for parameter in parameters), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(value).all()) for moment in optimizer.state.values()
                     for value in moment.values() if torch.is_tensor(value)), "nonfinite optimizer moments")
        progress["optimizer_steps"] += 1
        progress["row_cursor"] += len(indices)
        if progress["row_cursor"] == len(records):
            progress["epochs_completed"] += 1
            progress["row_cursor"] = 0
        losses.append(float(loss.detach()))
    model.eval()
    total, measured = 0., 0
    with torch.no_grad():
        for start in range(0, len(tuning), config["batch_size"]):
            if time.monotonic() >= deadline:
                break
            chunk = tuning[start:start + config["batch_size"]]
            loss = span._loss(torch, model, chunk)
            _require(bool(torch.isfinite(loss)), "nonfinite tuning loss")
            total += float(loss) * len(chunk)
            measured += len(chunk)
    weights, moments = span._pack(model, optimizer)
    result = ({**copy.deepcopy(checkpoint), "model_state": weights, "optimizer_state": moments, "progress": progress,
               "parent_checkpoint_sha256": checkpoint_digest(checkpoint)} if losses else copy.deepcopy(checkpoint))
    _require(_implementation() == checkpoint["implementation"], "dimensional source changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    return {"checkpoint": result, "report": {"schema": "native-dimensional-source-span-training/v1",
        "checkpoint_sha256": checkpoint_digest(result), "optimizer_steps": len(losses), "training_executed": bool(losses),
        "source_parent_checkpoint_sha256": checkpoint["source_parent_checkpoint_sha256"],
        "source_parent_optimizer_steps": checkpoint["source_parent_optimizer_steps"],
        "new_optimizer_steps_total": progress["optimizer_steps"], "batch_losses": losses, "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [key for key in weights if weights[key] != checkpoint["model_state"][key]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "tuning": {"objective_loss": total / measured if measured else None, "rows_evaluated": measured,
                   "complete": measured == len(tuning), "teacher_forcing": False, "used_for_fit_or_selection": False}, **FALSE}}


class DimensionalSpanDecoder(span.SpanLegalFormulaDecoder):
    """Use the frozen source-copy/grammar inference kernel with new native inputs."""
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self.checkpoint = copy.deepcopy(checkpoint)
        self.checkpoint_sha256 = checkpoint_digest(checkpoint)

    def decode_formal_logic(self, texts, latents=None, *, latent_ablation="none"):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128 and all(type(t) is str for t in texts),
                 "one to128 source strings required")
        dimension = self.checkpoint["config"]["latent_dimension"]
        if dimension:
            _require(type(latents) in (list, tuple) and len(latents) == len(texts), "one native vector per source required")
            vectors = [span._vector(vector, dimension) for vector in latents]
        else:
            _require(latents is None, "source-only decoder does not accept native vectors")
            vectors = [[] for _ in texts]
        _require(latent_ablation in ("none", "zero", "rotate", "disabled"), "unsupported latent ablation")
        _require(latent_ablation != "rotate" or len(texts) > 1, "rotate requires at least two sources")
        _require(_implementation() == self.checkpoint["implementation"], "dimensional implementation source drift")
        if latent_ablation == "zero":
            vectors = [[0.] * dimension for _ in vectors]
        elif latent_ablation == "rotate":
            vectors = vectors[1:] + vectors[:1]
        before = checkpoint_digest({name: value.detach().tolist() for name, value in self.model.state_dict().items()})
        rows = [self._decode(text, vector, enabled=latent_ablation != "disabled") for text, vector in zip(texts, vectors)]
        after = checkpoint_digest({name: value.detach().tolist() for name, value in self.model.state_dict().items()})
        _require(before == after == checkpoint_digest(self.checkpoint["model_state"]), "inference model state changed")
        count = sum(row["status"] == "decoded" for row in rows)
        return {"schema": "native-dimensional-source-span-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "source_parent_checkpoint_sha256": self.checkpoint["source_parent_checkpoint_sha256"],
            "context_contract_sha256": self.checkpoint["context_contract_sha256"], "input_dimension": dimension,
            "rows": rows, "decoded_count": count, "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "latent_ablation": latent_ablation, "target_access": False, "teacher_forcing": False,
            "training_executed": False, "model_state_unchanged": True, **FALSE}


def save_checkpoint(checkpoint, path):
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
