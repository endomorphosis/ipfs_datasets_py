"""Optimizer-free CPU restoration of existing 384D and 768D span checkpoints.

The checkpoint format, initial source-copy boundary, stored Adam moments, and
source-span decoding kernel are unchanged. The existing device-inference owner
supplies model-only restoration primitives; this additive profile generalizes
only its dimensional gate to 384 and 768. It creates no optimizer, moves no
model to a GPU, and changes no process-global Torch settings.

This validates stored content and lineage, not a native embedding producer or
the meaning of a decoded rule. Callers own independent checkpoint pins and
source/context admission. No training or legal qualification is conferred.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from . import legal_span_dimensions as dimensional
from . import legal_span_formula as span
from . import legal_span_device_inference as model_owner
from .checkpoint_content_guard import CheckpointContentGuard


PROFILE = "native-dimensional-source-span-cpu-model-only/v1"
DIMENSIONS = (384, 768)
_require = span._require
_SELF_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_OWNER_SHA = hashlib.sha256(Path(model_owner.__file__).read_bytes()).hexdigest()
_DECODE = dimensional.DimensionalSpanDecoder.decode_formal_logic
_ROW_DECODE = span.SpanLegalFormulaDecoder._decode
_HELPERS = {name: getattr(model_owner, name) for name in (
    "_strict_json", "_fresh_model", "_weights", "_optimizer", "_source_parent", "_progress")}
_DIMENSIONAL_IMPLEMENTATION = dimensional._implementation()


def inference_implementation():
    """Bind this adapter and its exact existing model-only helper owners."""
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SELF_SHA,
             "dimensional CPU inference source changed since import")
    _require(hashlib.sha256(Path(model_owner.__file__).read_bytes()).hexdigest() == _OWNER_SHA
             and all(getattr(model_owner, name) is value for name, value in _HELPERS.items()),
             "model-only helper implementation changed since import")
    _require(dimensional._implementation() == _DIMENSIONAL_IMPLEMENTATION
             and dimensional.DimensionalSpanDecoder.decode_formal_logic is _DECODE
             and span.SpanLegalFormulaDecoder._decode is _ROW_DECODE,
             "dimensional inference kernel changed since import")
    model_owner._implementation()
    return {"profile": PROFILE, "source_sha256": _SELF_SHA,
            "model_only_helpers_sha256": _OWNER_SHA,
            "checkpoint_producers": deepcopy(_DIMENSIONAL_IMPLEMENTATION)}


def _restore_snapshot(torch, checkpoint):
    fields = {"schema", "lineage_id", "implementation", "initialization", "config", "context_contract",
        "context_contract_sha256", "source_parent_checkpoint", "source_parent_checkpoint_sha256",
        "source_parent_optimizer_steps", "initial_source_model_sha256", "initial_model_state_sha256",
        "training_manifest_sha256", "training_count", "tuning_manifest_sha256", "tuning_count", "model_state",
        "optimizer_state", "progress", "parent_checkpoint_sha256", *span.FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields
             and checkpoint["schema"] == dimensional.SCHEMA
             and checkpoint["lineage_id"] == dimensional.LINEAGE_ID
             and all(checkpoint[name] is False for name in span.FALSE),
             "closed dimensional checkpoint schema/authority required")
    _require(checkpoint["implementation"] == dimensional._implementation(),
             "dimensional checkpoint implementation differs")
    _require(span._raw(checkpoint["initialization"]) == span._raw(dimensional._INITIALIZATION),
             "dimensional initialization policy differs")
    config = checkpoint["config"]
    _require(type(config) is dict and set(dimensional._CONFIG_KEYS) <= set(config)
             and span._raw(config) == span._raw(dimensional._config(
                 **{name: config[name] for name in dimensional._CONFIG_KEYS})),
             "dimensional configuration differs")
    dimension = config["latent_dimension"]
    _require(type(dimension) is int and dimension in DIMENSIONS,
             "CPU model-only profile requires an actual 384D or 768D head")
    contract = dimensional._context_contract(checkpoint["context_contract"], dimension)
    _require(checkpoint["context_contract_sha256"] == span.checkpoint_digest(contract),
             "native context contract changed")
    parent = checkpoint["source_parent_checkpoint"]
    model_owner._source_parent(torch, parent)
    _require(checkpoint["source_parent_checkpoint_sha256"] == span.checkpoint_digest(parent)
             and type(checkpoint["source_parent_optimizer_steps"]) is int
             and checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"],
             "source-parent content or progress differs")
    for name in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale"):
        _require(span._raw(config[name]) == span._raw(parent["config"][name]),
                 "inherited configuration differs: " + name)
    model = model_owner._fresh_model(torch, config)
    initial = {name: value.detach().tolist() for name, value in model.state_dict().items()}
    source = dimensional._source_state(parent["model_state"])
    _require(set(source) == set(dimensional._source_state(initial)), "source architecture tensor names differ")
    initial.update(deepcopy(source))
    model_owner._weights(torch, model, initial)
    _require(checkpoint["initial_source_model_sha256"] == span.checkpoint_digest(dimensional._source_state(initial))
             and checkpoint["initial_model_state_sha256"] == span.checkpoint_digest(initial),
             "initial copied source/adapter boundary differs")
    model_owner._progress(checkpoint)
    if checkpoint["progress"]["optimizer_steps"] == 0:
        _require(checkpoint["model_state"] == initial and checkpoint["parent_checkpoint_sha256"] is None,
                 "zero-update state differs from declared initialization")
    else:
        _require(checkpoint["parent_checkpoint_sha256"] is not None,
                 "trained checkpoint lacks preceding checkpoint hash")
    model_owner._weights(torch, model, checkpoint["model_state"])
    model_owner._optimizer(torch, model, checkpoint)
    model.eval()
    return model


def _runtime(torch):
    _require(str(torch.get_default_device()) == "cpu" and torch.get_default_dtype() == torch.float32,
             "unchanged CPU/float32 Torch defaults required")
    _require(not torch.is_autocast_enabled("cpu") and not torch.is_autocast_enabled("cuda"),
             "CPU model-only inference forbids autocast")


def _prepared(checkpoint):
    inference_implementation()
    model_owner._strict_json(checkpoint)
    raw = span._raw(checkpoint)
    _require(len(raw) <= dimensional.MAX_BYTES, "dimensional checkpoint exceeds byte bound")
    guard = CheckpointContentGuard(checkpoint)
    detached = json.loads(raw)
    guard.check(detached, message="detached inference checkpoint differs")
    import torch
    _runtime(torch)
    model = _restore_snapshot(torch, detached)
    guard.check(checkpoint, message="original checkpoint changed during CPU restoration")
    guard.check(detached, message="detached checkpoint changed during CPU restoration")
    _runtime(torch)
    inference_implementation()
    return torch, model, detached, guard


def restore_for_inference(checkpoint):
    """Return ``(torch, CPU model)`` after full optimizer-free restoration.

    Stored optimizer tensors are checked for shape, finite values and progress;
    no Adam object is created and no numerical update is performed. The model
    owns its configuration independently of the caller's mutable checkpoint.
    """
    torch, model, _, _ = _prepared(checkpoint)
    return torch, model


class CpuDimensionalSpanDecoder:
    """Existing dimensional output contract, with optimizer-free construction."""

    _decode = _ROW_DECODE

    def __init__(self, checkpoint):
        self.torch, self.model, self.checkpoint, self._checkpoint_guard = _prepared(checkpoint)
        self.checkpoint_sha256 = self._checkpoint_guard.sha256
        self._model_guard = CheckpointContentGuard(self.checkpoint["model_state"])

    def decode_formal_logic(self, texts, latents=None, *, latent_ablation="none"):
        inference_implementation()
        _runtime(self.torch)
        self._checkpoint_guard.check(self.checkpoint, message="owned inference checkpoint changed")
        _require(self.checkpoint_sha256 == self._checkpoint_guard.sha256,
                 "inference checkpoint identity changed")
        tensors = self.model.state_dict()
        _require(all(value.device.type == "cpu" and value.dtype == self.torch.float32
                     for value in tensors.values()), "inference model must remain CPU float32")
        self._model_guard.check({name: value.detach().tolist() for name, value in tensors.items()},
                                message="inference model state changed before forward")
        result = _DECODE(self, texts, latents, latent_ablation=latent_ablation)
        self._checkpoint_guard.check(self.checkpoint, message="owned checkpoint changed during inference")
        _runtime(self.torch)
        inference_implementation()
        return result


__all__ = ["CpuDimensionalSpanDecoder", "restore_for_inference", "inference_implementation", "PROFILE"]
