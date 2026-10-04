"""Private, admitted device inference for the native 768D source-span head.

The stored CPU checkpoint, its source parent, and every Adam moment remain
unchanged. This separate numerical profile owns its model, chooses CUDA when
available by default, and releases its own resource lease only after device
work has stopped. It neither creates embeddings nor trains or admits logic.
Cancellation and deadlines are cooperative boundaries around native forwards;
they cannot interrupt a running CUDA kernel.

CUDA requires a worker-private process with no unrelated concurrent Torch CuDNN
operation. CuDNN flags are process-global: this session's thread ownership cannot
isolate another thread. The GRU context preserves ambient enabled/benchmark/
benchmark_limit/deterministic settings, disables only CuDNN TF32, synchronizes
before restoring flags, and refuses changed ambient or CUDA matmul policies.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time

from . import legal_span_dimensions as dimensional
from . import legal_span_formula as span
from .checkpoint_content_guard import CheckpointContentGuard
from .resource_scheduler import (GlobalResourceScheduler, ResourceLane,
                                 get_global_resource_scheduler)

SCHEMA = "native-768-source-span-device-inference/v1"
PROFILE = "native-768-source-span-device-float32/v1"
CUDA_GRU_PROFILE = "native-768-source-span-device-strict-cuda-float32/v2"
_require = span._require
_SOURCE_AT_IMPORT = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_DECODE_AT_IMPORT = span.SpanLegalFormulaDecoder._decode
_FACTORY_AT_IMPORT = span._model
_TOKENIZER_AT_IMPORT = span.tokenize_source
_BATCH_AT_IMPORT = span._batch
_RULE_AT_IMPORT = span.codec_module._rule
_IMPLEMENTATION_AT_IMPORT = dimensional._implementation()


def _positive(value, maximum, label):
    _require(type(value) in (int, float) and math.isfinite(value)
             and 0 < value <= maximum, "bounded positive " + label + " required")
    return float(value)


def _strict_json(value):
    pending, items = [(value, 0)], 0
    while pending:
        part, depth = pending.pop()
        items += 1
        _require(depth <= 64 and items <= 8_000_000, "bounded plain checkpoint JSON required")
        if type(part) is dict:
            _require(all(type(name) is str for name in part), "plain checkpoint JSON keys required")
            pending.extend((child, depth + 1) for child in part.values())
        elif type(part) is list:
            pending.extend((child, depth + 1) for child in part)
        else:
            _require(type(part) in (str, int, float, bool, type(None))
                     and (type(part) is not float or math.isfinite(part)), "plain finite checkpoint JSON required")


def _implementation():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_AT_IMPORT,
             "768D device inference source changed since import")
    _require(dimensional._implementation() == _IMPLEMENTATION_AT_IMPORT
             and span.SpanLegalFormulaDecoder._decode is _DECODE_AT_IMPORT
             and span._model is _FACTORY_AT_IMPORT
             and span.tokenize_source is _TOKENIZER_AT_IMPORT
             and span._batch is _BATCH_AT_IMPORT
             and span.codec_module._rule is _RULE_AT_IMPORT,
             "768D source-span inference producer changed")
    return {"source_sha256": _SOURCE_AT_IMPORT,
            "native_checkpoint_producers": deepcopy(_IMPLEMENTATION_AT_IMPORT)}


class _CpuFactoryTorch:
    """Keep the inherited seeded constructor local to the CPU RNG.

    torch.manual_seed also seeds CUDA. The original factory needs only a CPU
    generator; its fork_rng(devices=[]) restores that generator after creation.
    No process-wide function, default device, dtype, or thread setting changes.
    """
    def __init__(self, torch):
        self._torch = torch

    def manual_seed(self, seed):
        return self._torch.random.default_generator.manual_seed(seed)

    def __getattr__(self, name):
        return getattr(self._torch, name)


def _fresh_model(torch, config):
    return _FACTORY_AT_IMPORT(_CpuFactoryTorch(torch), deepcopy(config))


def _weights(torch, model, saved):
    templates = model.state_dict()
    _require(type(saved) is dict and set(saved) == set(templates),
             "model state keys differ")
    tensors = {name: span._tensor(torch, saved[name], tensor.shape, name)
               for name, tensor in templates.items()}
    _require(span.checkpoint_digest({name: value.tolist() for name, value in tensors.items()})
             == span.checkpoint_digest(saved), "checkpoint weights are not exact float32 serialization")
    model.load_state_dict(tensors, strict=True)


def _progress(checkpoint):
    count, tune = checkpoint["training_count"], checkpoint["tuning_count"]
    _require(type(count) is int and 1 <= count <= span.MAX_EXAMPLES
             and type(tune) is int and 0 <= tune <= span.MAX_EXAMPLES,
             "invalid checkpoint split counts")
    for name in ("training_manifest_sha256", "tuning_manifest_sha256"):
        _require(type(checkpoint[name]) is str and span._SHA.fullmatch(checkpoint[name]),
                 "invalid checkpoint manifest hash")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and set(progress) == {"epochs_completed", "row_cursor", "optimizer_steps"}
             and all(type(value) is int and 0 <= value <= 10**9 for value in progress.values()),
             "invalid checkpoint progress")
    cursor, batch = progress["row_cursor"], checkpoint["config"]["batch_size"]
    _require(cursor < count and cursor % batch == 0 and progress["optimizer_steps"] ==
             progress["epochs_completed"] * math.ceil(count / batch) + cursor // batch,
             "checkpoint step/cursor identity differs")
    previous = checkpoint["parent_checkpoint_sha256"]
    _require(previous is None or type(previous) is str and span._SHA.fullmatch(previous),
             "invalid preceding checkpoint hash")


def _optimizer(torch, model, checkpoint):
    state, steps = checkpoint["optimizer_state"], checkpoint["progress"]["optimizer_steps"]
    _require(type(state) is dict and set(state) == {"schema", "parameters"}
             and state["schema"] == "adam-default-betas-eps/v1" and type(state["parameters"]) is dict,
             "unsupported stored optimizer state")
    parameters = dict(model.named_parameters())
    _require(set(state["parameters"]) == (set(parameters) if steps else set()),
             "stored optimizer parameter keys differ")
    # Validate every retained moment without constructing an optimizer or moving
    # its tensors. Inference has no mutable optimizer object to call accidentally.
    for name, moment in state["parameters"].items():
        _require(type(moment) is dict and set(moment) == {"step", "exp_avg", "exp_avg_sq"}
                 and type(moment["step"]) is int and moment["step"] == steps,
                 "stored optimizer step differs")
        span._tensor(torch, moment["exp_avg"], parameters[name].shape, name)
        span._tensor(torch, moment["exp_avg_sq"], parameters[name].shape, name, nonnegative=True)


def _source_parent(torch, parent):
    fields = {"schema", "lineage_id", "config", "implementation", "training_manifest_sha256",
              "training_count", "tuning_manifest_sha256", "tuning_count", "model_state", "optimizer_state",
              "progress", "parent_checkpoint_sha256", *span.FALSE}
    _require(type(parent) is dict and set(parent) == fields
             and parent["schema"] == span.SCHEMA and parent["lineage_id"] == span.LINEAGE_ID
             and all(parent[key] is False for key in span.FALSE), "closed source-parent checkpoint required")
    _require(len(span._raw(parent)) <= span.MAX_BYTES and parent["implementation"] == span._implementation(),
             "source-parent size or implementation differs")
    config = parent["config"]
    keys = ("latent_dimension", "latent_enabled", "learning_rate", "batch_size", "seed", "hidden_size",
            "embedding_dim", "projection_width", "residual_scale")
    _require(type(config) is dict and all(name in config for name in keys)
             and span._raw(config) == span._raw(span._config(**{name: config[name] for name in keys})),
             "source-parent configuration differs")
    _progress(parent)
    _require(parent["progress"]["optimizer_steps"] > 0
             and (not config["latent_enabled"] or config["latent_dimension"] == 0),
             "trained source-only parent required")
    model = _fresh_model(torch, config)
    _weights(torch, model, parent["model_state"])
    _optimizer(torch, model, parent)
    return model


def _restore(torch, checkpoint):
    """The native closed state/lineage checks, with CPU-only construction.

    This intentionally has its own numerical profile instead of mutating the
    native CPU factory or passing a CUDA checkpoint to that factory. The native
    schemas, configuration validators, tensor validator and source identities
    remain exact; all inherited and dimension-specific tensor blocks survive.
    """
    fields = {"schema", "lineage_id", "implementation", "initialization", "config", "context_contract",
              "context_contract_sha256", "source_parent_checkpoint", "source_parent_checkpoint_sha256",
              "source_parent_optimizer_steps", "initial_source_model_sha256", "initial_model_state_sha256",
              "training_manifest_sha256", "training_count", "tuning_manifest_sha256", "tuning_count",
              "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *span.FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields
             and checkpoint["schema"] == dimensional.SCHEMA and checkpoint["lineage_id"] == dimensional.LINEAGE_ID
             and all(checkpoint[name] is False for name in span.FALSE), "closed dimensional checkpoint required")
    _require(len(span._raw(checkpoint)) <= dimensional.MAX_BYTES
             and checkpoint["implementation"] == dimensional._implementation(),
             "dimensional checkpoint size or implementation differs")
    _require(span._raw(checkpoint["initialization"]) == span._raw(dimensional._INITIALIZATION),
             "dimensional initialization policy differs")
    config = checkpoint["config"]
    _require(type(config) is dict and set(dimensional._CONFIG_KEYS) <= set(config)
             and span._raw(config) == span._raw(dimensional._config(
                 **{name: config[name] for name in dimensional._CONFIG_KEYS})), "dimensional configuration differs")
    _require(type(config["latent_dimension"]) is int and config["latent_dimension"] == 768,
             "this device profile requires an actual native 768D head")
    context = dimensional._context_contract(checkpoint["context_contract"], 768)
    _require(checkpoint["context_contract_sha256"] == span.checkpoint_digest(context),
             "native context contract changed")
    parent = checkpoint["source_parent_checkpoint"]
    _source_parent(torch, parent)
    _require(checkpoint["source_parent_checkpoint_sha256"] == span.checkpoint_digest(parent)
             and type(checkpoint["source_parent_optimizer_steps"]) is int
             and checkpoint["source_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"],
             "source-parent content or progress differs")
    for name in ("seed", "hidden_size", "embedding_dim", "projection_width", "residual_scale"):
        _require(span._raw(config[name]) == span._raw(parent["config"][name]),
                 "inherited configuration differs: " + name)
    initial_model = _fresh_model(torch, config)
    initial = {name: value.detach().tolist() for name, value in initial_model.state_dict().items()}
    source = dimensional._source_state(parent["model_state"])
    _require(set(source) == set(dimensional._source_state(initial)), "source architecture tensor names differ")
    initial.update(deepcopy(source))
    _weights(torch, initial_model, initial)
    _require(checkpoint["initial_source_model_sha256"] == span.checkpoint_digest(dimensional._source_state(initial))
             and checkpoint["initial_model_state_sha256"] == span.checkpoint_digest(initial),
             "initial copied source/adapter boundary differs")
    _progress(checkpoint)
    if checkpoint["progress"]["optimizer_steps"] == 0:
        _require(checkpoint["model_state"] == initial and checkpoint["parent_checkpoint_sha256"] is None,
                 "zero-update state differs from declared initialization")
    else:
        _require(checkpoint["parent_checkpoint_sha256"] is not None,
                 "trained checkpoint lacks preceding checkpoint hash")
    _weights(torch, initial_model, checkpoint["model_state"])
    _optimizer(torch, initial_model, checkpoint)
    return initial_model


class _DeviceTorch:
    def __init__(self, torch, device):
        self._torch, self._device = torch, device

    def tensor(self, values, *args, **kwargs):
        _require("device" not in kwargs or str(kwargs["device"]) == self._device,
                 "foreign tensor device requested")
        return self._torch.tensor(values, *args, **{**kwargs, "device": self._device})

    def zeros(self, *args, **kwargs):
        _require("device" not in kwargs or str(kwargs["device"]) == self._device,
                 "foreign tensor device requested")
        return self._torch.zeros(*args, **{**kwargs, "device": self._device})

    def __getattr__(self, name):
        return getattr(self._torch, name)


def _precision_policy(torch):
    """Read actual ambient backend flags without changing them or probing CUDA."""
    cudnn = torch.backends.cudnn
    settings = {"enabled": cudnn.enabled, "benchmark": cudnn.benchmark,
                "benchmark_limit": cudnn.benchmark_limit, "deterministic": cudnn.deterministic,
                "allow_tf32": cudnn.allow_tf32}
    # New Torch flags() versions also have process-global defaults for these.
    # Bind them, and avoid resetting either to its context-manager default.
    for name in ("fp32_precision", "depthwise_kernel"):
        if hasattr(cudnn, name):
            settings[name] = getattr(cudnn, name)
    return {"cudnn": settings,
            "cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
            "float32_matmul_precision": torch.get_float32_matmul_precision()}


def _cuda_float32_policy(torch):
    policy = _precision_policy(torch)
    _require(policy["cuda_matmul_allow_tf32"] is False
             and policy["float32_matmul_precision"] == "highest",
             "strict CUDA float32 requires matmul TF32 disabled and highest precision")
    _require(not torch.is_autocast_enabled("cuda") and not torch.is_autocast_enabled("cpu"),
             "strict CUDA float32 forbids autocast")
    return policy


@contextmanager
def _strict_cuda_gru(torch, device, ambient):
    """One owned process-local GRU scope, never a CUDA execution attestation."""
    if not device.startswith("cuda:"):
        yield {"profile_id": PROFILE, "scoped_cudnn": False,
               "persistent_flags_mutated": False, "device": device}
        return
    _require(_cuda_float32_policy(torch) == ambient,
             "ambient CUDA precision policy changed before GRU")
    effective = {**ambient, "cudnn": {**ambient["cudnn"], "allow_tf32": False}}
    receipt = {"profile_id": CUDA_GRU_PROFILE, "device": device, "scoped_cudnn": True,
               "ambient_policy": deepcopy(ambient), "effective_policy": deepcopy(effective),
               "synchronized_before_restore": False, "ambient_flags_restored": False,
               "persistent_flags_mutated": False,
               "requires_owned_process_without_unrelated_concurrent_cudnn": True}
    context_flags = dict(effective["cudnn"])
    for name in ("fp32_precision", "depthwise_kernel"):
        if name in context_flags:
            context_flags[name] = None  # set_flags skips None; leave ambient value intact.
    try:
        with torch.backends.cudnn.flags(**context_flags):
            try:
                _require(_cuda_float32_policy(torch) == effective,
                         "effective strict CUDA GRU policy differs")
                yield receipt
            finally:
                # Even an exceptional forward must stop its owned device work
                # while TF32 is still disabled, before flags.__exit__ restores.
                torch.cuda.synchronize(device)
                receipt["synchronized_before_restore"] = True
                _require(_cuda_float32_policy(torch) == effective,
                         "strict CUDA GRU precision policy changed during forward")
    finally:
        _require(_precision_policy(torch) == ambient,
                 "ambient CUDA precision policy was not restored")
        receipt["ambient_flags_restored"] = True


def _device_model(torch, native, config, device, observations, precision_policy=None):
    config = deepcopy(config)
    ambient_precision = (deepcopy(_precision_policy(torch) if precision_policy is None else precision_policy)
                         if device.startswith("cuda:") else None)

    class PrivateDeviceSpan(type(native)):
        def forward(self, byte_ids, byte_lengths, lengths, latent, *, enabled=True):
            _require(type(enabled) is bool, "explicit latent gate required")
            batch, width = byte_ids.shape[:2] if byte_ids.ndim == 3 else (0, 0)
            _require(1 <= batch <= 128 and 1 <= width <= span.MAX_SOURCE_TOKENS
                     and byte_ids.shape[2] <= span.MAX_TOKEN_BYTES,
                     "bounded source byte tensors required")
            for value in (byte_ids, byte_lengths, lengths):
                _require(isinstance(value, torch.Tensor) and str(value.device) == device and value.dtype == torch.int64,
                         "actual source byte/length tensors differ from bound device/dtype")
            _require(tuple(byte_lengths.shape) == (batch, width) and tuple(lengths.shape) == (batch,)
                     and bool(((lengths > 0) & (lengths <= width)).all())
                     and bool(((byte_lengths >= 0) & (byte_lengths <= byte_ids.shape[2])).all())
                     and bool(((byte_ids >= 0) & (byte_ids <= 256)).all()), "source byte/length values differ")
            _require(isinstance(latent, torch.Tensor) and str(latent.device) == device
                     and latent.dtype == torch.float32 and tuple(latent.shape) == (batch, 768)
                     and bool(torch.isfinite(latent).all()), "bounded finite native 768D device inputs required")
            embedded = self.byte_embedding(byte_ids)
            mean = embedded.sum(2) / byte_lengths.clamp(min=1)[..., None]
            first = embedded[:, :, 0, :]
            last = embedded.gather(2, (byte_lengths.clamp(min=1) - 1)[:, :, None, None].expand(
                -1, -1, 1, config["embedding_dim"])).squeeze(2)
            size = torch.log1p(byte_lengths.to(torch.float32))[..., None] / math.log1p(span.MAX_TOKEN_BYTES)
            token = torch.tanh(self.token_projection(torch.cat((mean, first, last, size), dim=-1)))
            # pack_padded_sequence requires CPU lengths even when its actual
            # data and packed GRU tensors execute on CUDA.
            packed = torch.nn.utils.rnn.pack_padded_sequence(token, lengths.cpu(), batch_first=True, enforce_sorted=False)
            with _strict_cuda_gru(torch, device, ambient_precision) as gru_precision:
                encoded, _ = self.encoder(packed)
            encoded, _ = torch.nn.utils.rnn.pad_packed_sequence(encoded, batch_first=True)
            mask = torch.arange(encoded.shape[1], device=device)[None, :] < lengths[:, None]
            residual = torch.tanh(self.latent_up(torch.tanh(self.latent_down(latent))))
            gated = residual * config["residual_scale"] * float(enabled and config["latent_enabled"])
            encoded = encoded * (1 + gated[:, None, :]) + gated[:, None, :]
            pooled = (encoded * mask[..., None]).sum(1) / lengths[:, None]
            output = {"modality": self.modality(pooled), "presence": self.presence(pooled).reshape(-1, 4, 2),
                      "start": self.start(encoded).transpose(1, 2).masked_fill(~mask[:, None, :], -1e9),
                      "end": self.end(encoded).transpose(1, 2).masked_fill(~mask[:, None, :], -1e9)}
            _require(all(str(value.device) == device and value.dtype == torch.float32
                         and bool(torch.isfinite(value).all()) for value in output.values()),
                     "actual source-span forward output differs from device/dtype/finite profile")
            observations.append({"rows": batch, "source_tokens": lengths.detach().cpu().tolist(),
                                 "input_device": device, "native_input_dimension": 768,
                                 "output_devices": {name: str(value.device) for name, value in output.items()},
                                 "output_dtype": "float32", "gru_executed": True,
                                 "gru_precision": deepcopy(gru_precision)})
            return output

    # Own a fresh subclass instead of modifying the retained native model.
    with torch.random.fork_rng(devices=[]):
        model = PrivateDeviceSpan()
    model.load_state_dict(native.state_dict(), strict=True)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model.eval().to(device)


class DeviceDimensionalSpanSession:
    """One worker-private, immutable native768 head with a live resource lease."""
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, optimized=True,
                 scheduler=None, parent_lease=None, cancel_event=None,
                 admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=0):
        _require(type(optimized) is bool, "optimized must be boolean")
        _require(type(expected_checkpoint_sha256) is str and span._SHA.fullmatch(expected_checkpoint_sha256),
                 "external checkpoint SHA256 required")
        maximum = _positive(max_seconds, 600, "session deadline")
        admission = _positive(admission_timeout_seconds, 600, "admission deadline")
        _require(type(memory_mb) is int and memory_mb >= 1024
                 and type(gpu_memory_mb) is int and gpu_memory_mb >= 256
                 and type(unified_memory_mb) is int and unified_memory_mb >= 0,
                 "explicit bounded CPU/GPU memory reservations required")
        self._process, self._thread, self._lock = os.getpid(), threading.get_ident(), threading.RLock()
        self._deadline, self._cancel = time.monotonic() + maximum, cancel_event
        self._closed, self._model, self._lease = False, None, None
        self._active = False
        self._observations, self._optimized = [], optimized
        _strict_json(checkpoint)
        self._checkpoint = deepcopy(checkpoint)
        self._guard = CheckpointContentGuard(self._checkpoint, expected_sha256=expected_checkpoint_sha256)
        self.checkpoint_sha256 = expected_checkpoint_sha256
        _implementation()
        import torch
        _require(torch.get_num_threads() == 1, "caller must reserve CPU and set torch.set_num_threads(1)")
        _require(str(torch.get_default_device()) == "cpu" and torch.get_default_dtype() == torch.float32,
                 "unchanged CPU/float32 Torch defaults required")
        self._torch = torch
        self._device = ("cuda:" + str(torch.cuda.current_device())
                        if optimized and torch.cuda.is_available() else "cpu")
        # CPU reference inference does not consult or alter unrelated CUDA
        # precision settings (including native mixed-API error states).
        self._precision_policy = _cuda_float32_policy(torch) if self._device.startswith("cuda:") else None
        if scheduler is None:
            scheduler = get_global_resource_scheduler()
        _require(type(scheduler) is GlobalResourceScheduler, "exact shared resource scheduler required")
        self._scheduler = scheduler
        try:
            self._poll()
            self._lease = scheduler.acquire(ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1,
                memory_mb=memory_mb, gpu_memory_mb=gpu_memory_mb if self._device.startswith("cuda:") else 0,
                unified_memory_mb=unified_memory_mb if self._device.startswith("cuda:") else 0,
                requires_gpu=self._device.startswith("cuda:"), parent_lease=parent_lease,
                timeout=min(admission, max(0., self._deadline - time.monotonic())), cancel_event=cancel_event,
                request_id="native-768-source-span-device")
            self._poll()
            native = _restore(torch, self._checkpoint)
            self._model = _device_model(torch, native, self._checkpoint["config"], self._device,
                                        self._observations, self._precision_policy)
            self._model_identity, self._model_type = self._model, type(self._model)
            self._forward = self._model.forward.__func__
            self._module_layout = [(name, module, type(module), module.forward.__func__)
                                   for name, module in self._model.named_modules()]
            self._reference = {name: value.detach().clone() for name, value in self._model.state_dict().items()}
            self._pointers = {name: value.data_ptr() for name, value in self._model.state_dict().items()}
            self._tensor_factory = _DeviceTorch(torch, self._device)
            self._decoder = span.SpanLegalFormulaDecoder.__new__(span.SpanLegalFormulaDecoder)
            self._decoder.torch, self._decoder.model = self._tensor_factory, self._model
            self._decoder.checkpoint = self._checkpoint
            self._decoder.checkpoint_sha256 = self.checkpoint_sha256
            self._check()
        except BaseException:
            self.close()
            raise

    def _poll(self):
        _require(not self._closed, "768D device session is closed")
        _require(os.getpid() == self._process, "768D device session cannot be inherited across a fork")
        _require(threading.get_ident() == self._thread, "768D device session belongs to another thread")
        if self._cancel is not None and self._cancel.is_set():
            raise RuntimeError("768D device inference cancelled")
        if self._lease is not None and (self._lease.released or self._lease.cancelled):
            raise RuntimeError("768D device lease revoked or expired")
        if time.monotonic() >= self._deadline:
            raise TimeoutError("768D device inference deadline exceeded")

    def _pure_check(self):
        _require(not self._closed and os.getpid() == self._process
                 and threading.get_ident() == self._thread, "768D device session is closed or foreign")
        self._guard.check(self._checkpoint)
        torch, model = self._torch, self._model
        if self._device.startswith("cuda:"):
            _require(_cuda_float32_policy(torch) == self._precision_policy,
                     "ambient CUDA precision policy changed after admission")
        _require(model is self._model_identity and type(model) is self._model_type
                 and model.forward.__func__ is self._forward, "private 768D model architecture changed")
        modules = list(model.named_modules())
        _require(len(modules) == len(self._module_layout) and all(
            name == reference[0] and module is reference[1] and type(module) is reference[2]
            and getattr(module.forward, "__func__", None) is reference[3]
            for (name, module), reference in zip(modules, self._module_layout)),
            "private 768D model module implementation changed")
        _require(self._decoder.model is model and self._decoder.torch is self._tensor_factory
                 and self._decoder.checkpoint is self._checkpoint
                 and self._tensor_factory._torch is torch and self._tensor_factory._device == self._device,
                 "private 768D decoder binding changed")
        _require(torch.get_num_threads() == 1 and str(torch.get_default_device()) == "cpu"
                 and torch.get_default_dtype() == torch.float32, "Torch defaults/thread reservation changed")
        state = model.state_dict()
        _require(set(state) == set(self._reference) and all(
            str(value.device) == self._device and value.dtype == torch.float32
            and value.shape == self._reference[name].shape and value.data_ptr() == self._pointers[name]
            and torch.equal(value, self._reference[name])
            and torch.equal(torch.signbit(value), torch.signbit(self._reference[name]))
            for name, value in state.items()), "private 768D model tensors changed")
        _require(all(not module.training and not module._forward_hooks and not module._forward_pre_hooks
                     and not module._backward_hooks for module in model.modules())
                 and all(not parameter.requires_grad and parameter.grad is None for parameter in model.parameters()),
                 "private 768D modes/hooks/gradients changed")
        _require(not torch.nn.modules.module._global_forward_hooks
                 and not torch.nn.modules.module._global_forward_pre_hooks
                 and not torch.nn.modules.module._global_backward_hooks,
                 "global Torch hooks are incompatible with private 768D inference")

    def _check(self):
        self._poll()
        _implementation()
        self._pure_check()

    @contextmanager
    def _operation(self):
        with self._lock:
            _require(os.getpid() == self._process and threading.get_ident() == self._thread,
                     "768D device session belongs to another process/thread")
            _require(not self._active, "768D device session operation is already active")
            self._active = True
            try:
                yield
            finally:
                self._active = False

    @property
    def checkpoint(self):
        with self._operation():
            self._check()
            return deepcopy(self._checkpoint)

    def describe(self):
        with self._operation():
            self._check()
            return self._description()

    def _description(self):
        return {"profile_id": CUDA_GRU_PROFILE if self._device.startswith("cuda:") else PROFILE,
                    "dimension": 768, "device": self._device,
                    "optimized": self._optimized, "dtype": "float32", "max_rows": 128,
                    "checkpoint_sha256": self.checkpoint_sha256,
                    "optimizer_state_sha256": span.checkpoint_digest(self._checkpoint["optimizer_state"]),
                    "stored_checkpoint_device": self._checkpoint["config"]["device"],
                    "checkpoint_conversion_performed": False, "inference_only": True,
                    "parity_scope": "finite_numeric_and_canonical_decisions_not_bitwise",
                    "precision_policy": {"ambient_at_admission": deepcopy(self._precision_policy),
                        "cuda_gru_allow_tf32": False if self._device.startswith("cuda:") else None,
                        "cuda_matmul_allow_tf32": False if self._device.startswith("cuda:") else None,
                        "float32_matmul_precision": "highest" if self._device.startswith("cuda:") else None,
                        "persistent_flags_mutated": False,
                        "requires_owned_process_without_unrelated_concurrent_cudnn": self._device.startswith("cuda:")},
                    "deadline_enforcement": "cooperative_before_and_after_native_forward",
                    "resource_lease": self._lease.to_dict(), "implementation": _implementation(), **span.FALSE}

    def decode_formal_logic(self, texts, latents, *, latent_ablation="none",
                            embedding_receipts=None, expected_receipt_sha256s=None):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128 and all(type(text) is str for text in texts),
                 "one to 128 source strings required")
        _require(type(latents) in (list, tuple) and len(latents) == len(texts), "one native768 vector per source required")
        vectors = [span._vector(vector, 768) for vector in latents]
        _require(type(latent_ablation) is str and latent_ablation in ("none", "zero", "rotate", "disabled"),
                 "unsupported latent ablation")
        _require(latent_ablation != "rotate" or len(texts) > 1, "rotate requires at least two sources")
        authored = deepcopy({"texts": list(texts), "vectors": vectors, "receipts": embedding_receipts,
                             "receipt_pins": expected_receipt_sha256s})
        with self._operation():
            self._check()
            receipt_status = _verify_receipts(self._checkpoint["context_contract"], list(texts), vectors,
                                             embedding_receipts, expected_receipt_sha256s)
            inputs_guard = CheckpointContentGuard(authored)
            if latent_ablation == "zero":
                vectors = [[0.] * 768 for _ in vectors]
            elif latent_ablation == "rotate":
                vectors = vectors[1:] + vectors[:1]
            start = len(self._observations)
            rows = []
            try:
                for text, vector in zip(texts, vectors):
                    self._check()
                    with self._torch.inference_mode():
                        rows.append(_DECODE_AT_IMPORT(self._decoder, text, vector, enabled=latent_ablation != "disabled"))
                    self._synchronize()
                    self._check()
                count = sum(row["status"] == "decoded" for row in rows)
                result = {"schema": SCHEMA, "lineage_id": dimensional.LINEAGE_ID,
                    "checkpoint_sha256": self.checkpoint_sha256,
                    "source_parent_checkpoint_sha256": self._checkpoint["source_parent_checkpoint_sha256"],
                    "context_contract_sha256": self._checkpoint["context_contract_sha256"], "input_dimension": 768,
                    "rows": rows, "decoded_count": count,
                    "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
                    "latent_ablation": latent_ablation, "target_access": False, "teacher_forcing": False,
                    "training_executed": False, "model_state_unchanged": True,
                    "input_receipts": receipt_status, "execution_profile": self._description(),
                    "actual_forward_batches": deepcopy(self._observations[start:]),
                    "cuda_executed": self._device.startswith("cuda:") and len(self._observations) > start, **span.FALSE}
                result_guard = CheckpointContentGuard(result)
                self._check()
                inputs_guard.check({"texts": list(texts), "vectors": [span._vector(vector, 768) for vector in latents],
                                    "receipts": embedding_receipts, "receipt_pins": expected_receipt_sha256s})
                # The final check invokes no caller cancellation/lease callbacks.
                # It follows all late receiving callbacks and guards the plain
                # input/result content and retained checkpoint/model again.
                self._pure_check()
                result_guard.check(result)
                return result
            finally:
                self._synchronize()
                del self._observations[start:]

    infer = decode_formal_logic

    def _synchronize(self):
        if self._device.startswith("cuda:"):
            self._torch.cuda.synchronize(self._device)

    def close(self):
        with self._lock:
            _require(os.getpid() == self._process and threading.get_ident() == self._thread,
                     "foreign process/thread cannot close a 768D device lease")
            _require(not self._active, "768D device session operation is already active")
            if self._closed:
                return
            # Do not release GPU authority if synchronization itself fails: a
            # failed synchronization cannot attest that admitted work stopped.
            self._synchronize()
            self._model = None
            if hasattr(self, "_decoder"):
                self._decoder.model = None
            self._model_identity, self._model_type, self._forward = None, None, None
            self._module_layout = []
            self._reference, self._pointers, self._observations = {}, {}, []
            self._closed = True
            if self._lease is not None:
                self._lease.release()

    def __enter__(self):
        with self._operation():
            self._check()
        return self

    def __exit__(self, *ignored):
        self.close()


def _verify_receipts(context, texts, vectors, receipts, expected):
    """Bind externally authenticated producer receipts; never infer authenticity.

    Unreceipted vectors remain useful for explicitly synthetic protocol tests.
    Matching an externally supplied digest establishes a caller's content pin,
    not a signature, encoder execution attestation, or semantic qualification.
    """
    if receipts is None and expected is None:
        return {"status": "unreceipted", "native_encoder_inputs_authenticated": False,
                "signature_verified": False, "semantic_qualification": False}
    _require(type(receipts) in (list, tuple) and type(expected) in (list, tuple)
             and len(receipts) == len(expected) == len(texts), "complete external embedding receipt pins required")
    pins = []
    for text, vector, receipt, pin in zip(texts, vectors, receipts, expected):
        _require(type(pin) is str and span._SHA.fullmatch(pin)
                 and span.checkpoint_digest(receipt) == pin, "external embedding receipt content pin differs")
        _require(type(receipt) is dict and receipt.get("profile_id") == context["representation_id"]
                 and type(receipt.get("dimension")) is int and receipt["dimension"] == 768
                 and receipt.get("source_sha256") == hashlib.sha256(text.encode("utf-8")).hexdigest()
                 and span._raw(receipt.get("embedding")) == span._raw(vector)
                 and receipt.get("truncated") is False and receipt.get("normalized") is True,
                 "embedding receipt source/profile/native vector differs")
        _require(abs(math.sqrt(sum(number * number for number in vector)) - 1.) <= 2e-5,
                 "receipted native768 vector must be L2 normalized")
        _require(type(receipt.get("token_count_including_special_tokens")) is int
                 and 1 <= receipt["token_count_including_special_tokens"] <= 8192
                 and type(receipt.get("token_input_sha256")) is str
                 and span._SHA.fullmatch(receipt["token_input_sha256"]), "bounded native token receipt required")
        _require(type(receipt.get("id")) is str and 0 < len(receipt["id"]) <= 256,
                 "bounded native source receipt identifier required")
        old = {"schema", "id", "source_sha256", "profile_id", "dimension", "embedding",
               "token_count_including_special_tokens", "token_input_sha256", "truncated", "normalized",
               "asset_manifest_sha256"}
        new = {*old, "embedding_sha256", "profile_sha256", "device", "dtype", "proof_authority", "source_semantics_verified"}
        _require(set(receipt) in (old, new), "closed native768 embedding receipt required")
        if receipt["schema"] == "gte-multilingual-embedding-receipt/v1":
            _require(set(receipt) == old, "closed CPU768 embedding receipt required")
        else:
            _require(receipt["schema"] == "gte-native-device-embedding-receipt/v1" and set(receipt) == new
                     and receipt["dtype"] == "float32" and type(receipt["device"]) is str
                     and (receipt["device"] == "cpu" or re.fullmatch(r"cuda:[0-9]+", receipt["device"]) is not None)
                     and receipt["embedding_sha256"] == hashlib.sha256(
                         json.dumps(vector, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()
                     and type(receipt["profile_sha256"]) is str and span._SHA.fullmatch(receipt["profile_sha256"])
                     and receipt["profile_sha256"] == context["producer_sha256"]
                     and receipt["proof_authority"] is False and receipt["source_semantics_verified"] is False,
                     "closed device768 embedding receipt required")
        _require(type(receipt["asset_manifest_sha256"]) is str and span._SHA.fullmatch(receipt["asset_manifest_sha256"]),
                 "native embedding asset pin required")
        pins.append(pin)
    _require(len({receipt["id"] for receipt in receipts}) == len(receipts), "duplicate embedding receipt identifiers")
    return {"status": "externally_content_pinned", "native_encoder_inputs_authenticated": True,
            "receipt_sha256s": pins, "context_producer_sha256": context["producer_sha256"],
            "profile_sha256s": [receipt.get("profile_sha256") for receipt in receipts],
            "signature_verified": False, "semantic_qualification": False}


__all__ = ["DeviceDimensionalSpanSession", "SCHEMA", "PROFILE"]
