"""Private batched inference architecture for the separate native4096 head.

This session restores the new 4096 checkpoint schema and owns its float32 model.
Optimization defaults on, selecting CUDA when available and batching complete
valid sources. ``optimized=False`` uses singleton CPU numerical forwards.

Leanstral's trusted embedding owner is unavailable. Production vectors and all
embedding receipts therefore refuse; explicit synthetic, untrained architecture
controls alone may infer unreceipted vectors. These controls establish no trained
Leanstral head, encoder execution, repository semantics, or proof authority.

CUDA scopes require a worker-private process without unrelated concurrent CuDNN
operations. Cancellation and deadlines are cooperative around native forwards.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import threading
import time

from . import legal_span_4096 as head
from . import legal_span_formula as span
from . import legal_span_device_inference as resident
from . import legal_span_device_batch_inference as batched
from .checkpoint_content_guard import CheckpointContentGuard
from . import owned_tensor_value_guard as tensor_guard
from .resource_scheduler import GlobalResourceScheduler, ResourceLane, get_global_resource_scheduler

SCHEMA = "native-4096-source-span-device-inference/v1"
PROFILE = "native-4096-source-span-batched-device-float32-cpu-decisions/v2"
CUDA_GRU_PROFILE = "native-4096-source-span-strict-cuda-float32/v1"
DIMENSION = 4096
_require = span._require
_OUTPUTS = ("modality", "presence", "start", "end")
_SOURCE_AT_IMPORT = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_HEAD_AT_IMPORT = head._implementation()
_RESTORE_AT_IMPORT = head._restore_for_inference
_DECODE_AT_IMPORT = span.SpanLegalFormulaDecoder._decode
_TOKENIZER_AT_IMPORT = span.tokenize_source
_BATCH_AT_IMPORT = span._batch
_RESIDENT_AT_IMPORT = resident._implementation()
_BATCHED_AT_IMPORT = batched._implementation()
_VALUE_GUARD_AT_IMPORT = tensor_guard.check_owned_tensor_values
_VALUE_GUARD_SOURCE_AT_IMPORT = hashlib.sha256(Path(tensor_guard.__file__).read_bytes()).hexdigest()
_RESIDENT_HELPERS_AT_IMPORT = {name: getattr(resident, name) for name in
    ("_implementation", "_positive", "_strict_json", "_strict_cuda_gru", "_cuda_float32_policy", "_DeviceTorch")}
_BATCHED_HELPERS_AT_IMPORT = {name: getattr(batched, name) for name in
    ("_implementation", "_batch_memory_bound", "_CachedOutput", "_NoForward", "_row_output")}
_SYNTHETIC_PROVENANCE = {
    "schema": "native-4096-source-span-provenance/v1",
    "kind": "synthetic_untrained_architecture_control",
    "synthetic_embeddings": True,
    "trusted_native_owner_verified": False,
}
_MAX_REFERENCE_BYTES = 256 * 1024**2


@dataclass(frozen=True, slots=True)
class _ReferenceByteAnchor:
    """Immutable bytes from the independently validated CPU checkpoint model.

    Object and payload identities are retained separately by the owner. These
    are corruption guards inside the owned process contract, without a claim
    of isolation against arbitrary hostile Python code in that process.
    """
    checkpoint_sha256: str
    layout: tuple
    payload: bytes
    sha256: str


def _implementation():
    _require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_AT_IMPORT,
             "native4096 device inference source changed since import")
    _require(head._implementation() == _HEAD_AT_IMPORT
             and head._restore_for_inference is _RESTORE_AT_IMPORT
             and resident._implementation() == _RESIDENT_AT_IMPORT
             and batched._implementation() == _BATCHED_AT_IMPORT
             and span.SpanLegalFormulaDecoder._decode is _DECODE_AT_IMPORT
             and span.tokenize_source is _TOKENIZER_AT_IMPORT
             and span._batch is _BATCH_AT_IMPORT,
             "native4096 device inference dependency changed")
    _require(all(getattr(resident, name) is value for name, value in _RESIDENT_HELPERS_AT_IMPORT.items())
             and all(getattr(batched, name) is value for name, value in _BATCHED_HELPERS_AT_IMPORT.items())
             and tensor_guard.check_owned_tensor_values is _VALUE_GUARD_AT_IMPORT
             and hashlib.sha256(Path(tensor_guard.__file__).read_bytes()).hexdigest() == _VALUE_GUARD_SOURCE_AT_IMPORT,
             "native4096 inference primitive identity/source changed")
    return {"source_sha256": _SOURCE_AT_IMPORT, "native4096_checkpoint_producer": deepcopy(_HEAD_AT_IMPORT),
            "reused_precision_tensor_primitives": deepcopy(_RESIDENT_AT_IMPORT),
            "reused_cpu_decision_cache_primitives": deepcopy(_BATCHED_AT_IMPORT),
            "owned_tensor_value_guard_sha256": _VALUE_GUARD_SOURCE_AT_IMPORT}


def _device_model(torch, native, config, device, observations, precision_policy):
    """Own a 4096 model subclass; no retained module or global forward changes."""
    config = deepcopy(config)

    class Private4096DeviceSpan(type(native)):
        def forward(self, byte_ids, byte_lengths, lengths, latent, *, enabled=True):
            _require(type(enabled) is bool, "explicit native4096 latent gate required")
            batch, width = byte_ids.shape[:2] if byte_ids.ndim == 3 else (0, 0)
            _require(1 <= batch <= 128 and 1 <= width <= span.MAX_SOURCE_TOKENS
                     and byte_ids.shape[2] <= span.MAX_TOKEN_BYTES,
                     "bounded native4096 source byte tensors required")
            _require(all(isinstance(value, torch.Tensor) and str(value.device) == device
                         and value.dtype == torch.int64 for value in (byte_ids, byte_lengths, lengths)),
                     "actual native4096 byte/length tensors differ from device/dtype")
            _require(tuple(byte_lengths.shape) == (batch, width) and tuple(lengths.shape) == (batch,)
                     and bool(((lengths > 0) & (lengths <= width)).all())
                     and bool(((byte_lengths >= 0) & (byte_lengths <= byte_ids.shape[2])).all())
                     and bool(((byte_ids >= 0) & (byte_ids <= 256)).all()),
                     "native4096 source byte/length values differ")
            _require(isinstance(latent, torch.Tensor) and str(latent.device) == device
                     and latent.dtype == torch.float32 and tuple(latent.shape) == (batch, DIMENSION)
                     and bool(torch.isfinite(latent).all()),
                     "complete finite actual4096 float32 device vectors required")
            embedded = self.byte_embedding(byte_ids)
            mean = embedded.sum(2) / byte_lengths.clamp(min=1)[..., None]
            first = embedded[:, :, 0, :]
            last = embedded.gather(2, (byte_lengths.clamp(min=1) - 1)[:, :, None, None].expand(
                -1, -1, 1, config["embedding_dim"])).squeeze(2)
            size = torch.log1p(byte_lengths.to(torch.float32))[..., None] / math.log1p(span.MAX_TOKEN_BYTES)
            token = torch.tanh(self.token_projection(torch.cat((mean, first, last, size), dim=-1)))
            packed = torch.nn.utils.rnn.pack_padded_sequence(token, lengths.cpu(), batch_first=True,
                                                            enforce_sorted=False)
            with resident._strict_cuda_gru(torch, device, precision_policy) as inherited_precision:
                encoded, _ = self.encoder(packed)
            gru_precision = deepcopy(inherited_precision)
            gru_precision["precision_scope_helper_profile_id"] = gru_precision["profile_id"]
            gru_precision["profile_id"] = CUDA_GRU_PROFILE if device.startswith("cuda:") else PROFILE
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
                     "actual native4096 head output differs from finite float32 device profile")
            observations.append({"rows": batch, "source_tokens": lengths.detach().cpu().tolist(),
                "input_device": device, "native_input_dimension": DIMENSION,
                "output_devices": {name: str(value.device) for name, value in output.items()},
                "output_dtype": "float32", "gru_executed": True, "gru_precision": gru_precision})
            return output

    with torch.random.fork_rng(devices=[]):
        model = Private4096DeviceSpan()
    model.load_state_dict(native.state_dict(), strict=True)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return model.eval().to(device)


def _receipt_status(checkpoint, synthetic_unreceipted, receipts, expected):
    _require(receipts is None and expected is None, "trusted_native_owner_integration_required")
    _require(synthetic_unreceipted and checkpoint.get("provenance") == _SYNTHETIC_PROVENANCE,
             "trusted_native_owner_integration_required")
    return {"status": "synthetic_unreceipted_architecture_control",
            "native_encoder_inputs_authenticated": False, "trusted_native_owner_verified": False,
            "signature_verified": False, "semantic_qualification": False,
            "production_admission": False, "synthetic_embeddings": True}


def _select_device(torch, optimized):
    """Avoid initializing a CUDA context before this session is admitted."""
    if not optimized or not torch.cuda.is_available():
        return "cpu"
    # current_device() initializes CUDA lazily. The uninitialized runtime uses
    # its default visible device 0 only after the owned lease is acquired.
    index = torch.cuda.current_device() if torch.cuda.is_initialized() else 0
    _require(type(index) is int and 0 <= index <= 1024, "bounded actual CUDA device index required")
    return "cuda:" + str(index)


class DeviceLeanstral4096SpanSession:
    """One admitted worker-private numerical head; native producer admission closed."""
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, optimized=True,
                 synthetic_unreceipted=False, scheduler=None, parent_lease=None,
                 cancel_event=None, admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=0):
        _implementation()
        _require(type(optimized) is bool and type(synthetic_unreceipted) is bool,
                 "optimized and synthetic_unreceipted must be boolean")
        _require(type(expected_checkpoint_sha256) is str and span._SHA.fullmatch(expected_checkpoint_sha256),
                 "external native4096 checkpoint SHA256 required")
        maximum = resident._positive(max_seconds, 600, "native4096 session deadline")
        admission = resident._positive(admission_timeout_seconds, 600, "native4096 admission deadline")
        _require(type(memory_mb) is int and memory_mb >= 1024
                 and type(gpu_memory_mb) is int and gpu_memory_mb >= 256
                 and type(unified_memory_mb) is int and unified_memory_mb >= 0,
                 "explicit bounded native4096 host/GPU memory reservations required")
        self._process, self._thread, self._lock = os.getpid(), threading.get_ident(), threading.RLock()
        self._deadline, self._cancel = time.monotonic() + maximum, cancel_event
        self._closed, self._active, self._model, self._lease = False, False, None, None
        self._device, self._observations = "cpu", []
        self._optimized, self._synthetic_unreceipted = optimized, synthetic_unreceipted
        resident._strict_json(checkpoint)
        self._checkpoint = deepcopy(checkpoint)
        self._guard = CheckpointContentGuard(self._checkpoint, expected_sha256=expected_checkpoint_sha256)
        self.checkpoint_sha256 = expected_checkpoint_sha256
        _require(len(self._guard._canonical_bytes) * 12 <= memory_mb * 1024**2,
                 "native4096 checkpoint exceeds reserved restoration host memory estimate")
        _require(not synthetic_unreceipted or self._checkpoint.get("provenance") == _SYNTHETIC_PROVENANCE,
                 "synthetic inference requires synthetic untrained checkpoint provenance")
        _implementation()
        import torch
        _require(torch.get_num_threads() == 1, "caller must reserve CPU and set torch.set_num_threads(1)")
        _require(str(torch.get_default_device()) == "cpu" and torch.get_default_dtype() == torch.float32,
                 "unchanged CPU/float32 Torch defaults required")
        self._torch = torch
        self._device = _select_device(torch, optimized)
        self._precision_policy = resident._cuda_float32_policy(torch) if self._device.startswith("cuda:") else None
        self._policy_guard = CheckpointContentGuard(self._policy())
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
                request_id="native-4096-source-span-device")
            self._lease_identity = self._lease
            self._lease_guard = CheckpointContentGuard(self._lease_binding())
            self._poll()
            native = _RESTORE_AT_IMPORT(torch, self._checkpoint)
            _require(type(self._checkpoint["config"]["latent_dimension"]) is int
                     and self._checkpoint["config"]["latent_dimension"] == DIMENSION
                     and native.latent_down.in_features == DIMENSION,
                     "actual4096 checkpoint adapter required")
            native_state = dict(native.state_dict())
            layout, reference_bytes = self._reference_byte_plan(native_state, expected_device="cpu")
            payload = self._reference_state_bytes(native_state, layout, reference_bytes)
            self._reference_anchor = _ReferenceByteAnchor(self.checkpoint_sha256, layout, payload,
                                                          hashlib.sha256(payload).hexdigest())
            self._reference_anchor_identity = self._reference_anchor
            self._reference_payload_identity = payload
            self._reference_anchor_sha256 = self._reference_anchor.sha256
            self._model = _device_model(torch, native, self._checkpoint["config"], self._device,
                                        self._observations, self._precision_policy)
            self._model_identity, self._model_type = self._model, type(self._model)
            self._forward = self._model.forward.__func__
            self._module_layout = [(name, module, type(module), module.forward.__func__)
                                   for name, module in self._model.named_modules()]
            self._reference = {name: value.detach().clone() for name, value in self._model.state_dict().items()}
            self._pointers = {name: value.data_ptr() for name, value in self._model.state_dict().items()}
            self._tensor_factory = resident._DeviceTorch(torch, self._device)
            self._decoder = span.SpanLegalFormulaDecoder.__new__(span.SpanLegalFormulaDecoder)
            self._decoder.torch, self._decoder.model = self._tensor_factory, self._model
            self._decoder.checkpoint, self._decoder.checkpoint_sha256 = self._checkpoint, self.checkpoint_sha256
            self._check()
        except BaseException:
            self.close()
            raise

    def _poll(self):
        _require(not self._closed, "native4096 device session is closed")
        _require(os.getpid() == self._process and threading.get_ident() == self._thread,
                 "native4096 device session belongs to another process/thread")
        if self._cancel is not None and self._cancel.is_set():
            raise RuntimeError("native4096 device inference cancelled")
        if self._lease is not None and (self._lease.released or self._lease.cancelled):
            raise RuntimeError("native4096 device lease revoked or expired")
        if time.monotonic() >= self._deadline:
            raise TimeoutError("native4096 device inference deadline exceeded")

    def _pure_check(self):
        _require(not self._closed and os.getpid() == self._process and threading.get_ident() == self._thread,
                 "native4096 device session is closed or foreign")
        self._guard.check(self._checkpoint)
        self._policy_guard.check(self._policy())
        _require(self._lease is self._lease_identity and self._lease._scheduler is self._scheduler,
                 "private native4096 resource lease binding changed")
        self._lease_guard.check(self._lease_binding())
        torch, model = self._torch, self._model
        if self._device.startswith("cuda:"):
            _require(resident._cuda_float32_policy(torch) == self._precision_policy,
                     "ambient native4096 CUDA precision policy changed")
        else:
            _require(not torch.is_autocast_enabled("cpu"), "native4096 float32 forbids CPU autocast")
        _require(model is self._model_identity and type(model) is self._model_type
                 and model.forward.__func__ is self._forward, "private native4096 model architecture changed")
        modules = list(model.named_modules())
        _require(len(modules) == len(self._module_layout) and all(
            name == reference[0] and module is reference[1] and type(module) is reference[2]
            and getattr(module.forward, "__func__", None) is reference[3]
            for (name, module), reference in zip(modules, self._module_layout)),
            "private native4096 module implementation changed")
        _require(self._decoder.model is model and self._decoder.torch is self._tensor_factory
                 and self._decoder.checkpoint is self._checkpoint
                 and self._decoder.checkpoint_sha256 == self.checkpoint_sha256
                 and self._tensor_factory._torch is torch and self._tensor_factory._device == self._device,
                 "private native4096 decoder binding changed")
        _require(torch.get_num_threads() == 1 and str(torch.get_default_device()) == "cpu"
                 and torch.get_default_dtype() == torch.float32, "Torch defaults/thread reservation changed")
        # Torch deliberately returns an OrderedDict; own an ordinary mapping
        # for the helper's closed JSON-free metadata contract, preserving every
        # original tensor object, storage pointer, dtype and named block.
        state = dict(model.state_dict())
        _require(set(state) == set(self._reference) and all(
            str(value.device) == self._device and value.dtype == torch.float32
            and value.shape == self._reference[name].shape and value.data_ptr() == self._pointers[name]
            for name, value in state.items()), "private native4096 model tensors changed")
        self._reference_anchor_receipt = self._check_reference_anchor()
        self._value_guard_receipt = _VALUE_GUARD_AT_IMPORT(torch, state, self._reference,
                                                        optimized=self._optimized)
        _require(all(not module.training and not module._forward_hooks and not module._forward_pre_hooks
                     and not module._backward_hooks for module in model.modules())
                 and all(not parameter.requires_grad and parameter.grad is None for parameter in model.parameters()),
                 "private native4096 modes/hooks/gradients changed")
        _require(not torch.nn.modules.module._global_forward_hooks
                 and not torch.nn.modules.module._global_forward_pre_hooks
                 and not torch.nn.modules.module._global_backward_hooks,
                 "global Torch hooks are incompatible with private native4096 inference")

    def _check(self):
        self._poll()
        _implementation()
        self._pure_check()

    def _policy(self):
        return {"optimized": self._optimized, "synthetic_unreceipted": self._synthetic_unreceipted,
                "device": self._device, "checkpoint_sha256": self.checkpoint_sha256,
                "precision_policy": self._precision_policy}

    def _lease_binding(self):
        names = ("lease_id", "lease_key", "lane", "cpu_slots", "memory_mb", "gpu_memory_mb",
                 "unified_memory_mb", "child_process_slots", "requires_gpu", "parent_lease_id", "owner_pid")
        return {name: getattr(self._lease, name) for name in names}

    def _reference_byte_plan(self, state, *, expected_device):
        """Admit all metadata and the complete copy bound before allocation."""
        torch = self._torch
        _require(type(state) is dict and 1 <= len(state) <= 4096
                 and all(type(name) is str and 0 < len(name) <= 1024 for name in state),
                 "bounded ordinary native4096 reference tensor state required")
        layout, total = [], 0
        for name in sorted(state):
            value = state[name]
            _require(isinstance(value, torch.Tensor) and value.dtype == torch.float32
                     and str(value.device) == expected_device and value.layout == torch.strided
                     and value.is_contiguous(), "contiguous native4096 reference float32 device tensors required")
            total += value.numel() * value.element_size()
            _require(total <= _MAX_REFERENCE_BYTES, "bounded complete native4096 reference byte anchor required")
            layout.append((name, tuple(value.shape), value.numel()))
        _require(total > 0, "nonempty native4096 reference byte anchor required")
        # Host: restored CPU model, resident/reference state, immutable anchor,
        # concatenation/transfer/byte-copy temporaries and comparison allowance.
        # Device: resident/reference state, concatenated reference byte tensor,
        # full-value comparisons and an allocator allowance. No padded source
        # tensor exists yet; complete source batch estimates add their buffers.
        host_bound = 128 * 1024**2 + len(self._guard._canonical_bytes) * 12 + total * 8
        gpu_bound = 128 * 1024**2 + total * 6
        _require(host_bound <= self._lease.memory_mb * 1024**2,
                 "native4096 reference anchor exceeds reserved host memory estimate")
        if self._device.startswith("cuda:"):
            _require(gpu_bound <= self._lease.gpu_memory_mb * 1024**2,
                     "native4096 reference anchor exceeds reserved GPU memory estimate")
        return tuple(layout), total

    def _reference_state_bytes(self, state, layout, reference_bytes):
        # Metadata and reservation checks precede even the uint8 views. All
        # admitted tensors are contiguous, so reshape/view cannot copy them.
        views = [state[name].detach().reshape(-1).view(self._torch.uint8) for name, _, _ in layout]
        concatenated = self._torch.cat(views)
        _require(concatenated.numel() == reference_bytes, "complete native4096 reference byte coverage differs")
        payload = concatenated.cpu().numpy().tobytes()
        _require(type(payload) is bytes and len(payload) == reference_bytes,
                 "complete immutable native4096 reference bytes required")
        return payload

    def _check_reference_anchor(self):
        anchor = self._reference_anchor
        _require(type(anchor) is _ReferenceByteAnchor and anchor is self._reference_anchor_identity
                 and type(anchor.payload) is bytes and anchor.payload is self._reference_payload_identity
                 and anchor.checkpoint_sha256 == self.checkpoint_sha256
                 and anchor.sha256 == self._reference_anchor_sha256,
                 "private native4096 immutable reference byte anchor changed")
        layout, reference_bytes = self._reference_byte_plan(self._reference, expected_device=self._device)
        _require(layout == anchor.layout and reference_bytes == len(anchor.payload),
                 "private native4096 reference byte layout differs from admitted checkpoint")
        current = self._reference_state_bytes(self._reference, layout, reference_bytes)
        _require(current == anchor.payload,
                 "private native4096 reference bytes changed from admitted checkpoint")
        return {"schema": "native-4096-owned-reference-byte-currentness/v1",
                "checkpoint_sha256": anchor.checkpoint_sha256, "anchor_sha256": anchor.sha256,
                "reference_bytes": reference_bytes, "reference_device": self._device,
                "origin": "independently_restored_validated_cpu_checkpoint_model",
                "comparison": "complete_immutable_float32_bytes_including_signed_zero",
                "device_to_cpu_reference_transfers": 1 if self._device.startswith("cuda:") else 0,
                "cpu_byte_materializations": 1, "anchor_identity_checked": True,
                "metadata_and_reservation_checked_before_allocation": True,
                "kernel_resource_enforcement": False, "proof_authority": False}

    @contextmanager
    def _operation(self):
        with self._lock:
            _require(os.getpid() == self._process and threading.get_ident() == self._thread,
                     "native4096 device session belongs to another process/thread")
            _require(not self._active, "native4096 session operation is already active")
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
        return {"profile_id": PROFILE, "strict_cuda_gru_profile_id": CUDA_GRU_PROFILE,
            "dimension": DIMENSION, "device": self._device, "optimized": self._optimized,
            "dtype": "float32", "max_rows": 128, "checkpoint_sha256": self.checkpoint_sha256,
            "optimizer_state_sha256": span.checkpoint_digest(self._checkpoint["optimizer_state"]),
            "stored_checkpoint_device": self._checkpoint["config"]["device"],
            "checkpoint_conversion_performed": False, "inference_only": True,
            "numerical_batching": "one_complete_valid_source_batch" if self._optimized else "singleton_cpu_opt_out",
            "canonical_decision_device": "cpu", "native_leanstral_encoder_available": False,
            "trusted_native_owner_verified": False, "native_leanstral_head_qualified": False,
            "production_admission": False, "synthetic_unreceipted_enabled": self._synthetic_unreceipted,
            "precision_policy": {"ambient_at_admission": deepcopy(self._precision_policy),
                "cuda_gru_allow_tf32": False if self._device.startswith("cuda:") else None,
                "persistent_flags_mutated": False,
                "requires_owned_process_without_unrelated_concurrent_cudnn": self._device.startswith("cuda:")},
            "batch_memory_policy": "shape_bound_before_padded_allocation_refuse_without_truncation",
            "kernel_resource_enforcement": False, "singleton_numeric_bitwise_parity_claimed": False,
            "owned_tensor_currentness": deepcopy(self._value_guard_receipt),
            "reference_byte_currentness": deepcopy(self._reference_anchor_receipt),
            "deadline_enforcement": "cooperative_before_and_after_native_forward",
            "resource_lease": self._lease.to_dict(), "implementation": _implementation(), **span.FALSE}

    def _admit_batch_memory(self, records):
        parameter_bytes = sum(value.numel() * value.element_size() for value in self._model.state_dict().values())
        bound = batched._batch_memory_bound(records, self._checkpoint["config"],
            parameter_bytes=parameter_bytes, checkpoint_bytes=len(self._guard._canonical_bytes))
        latent_bytes = len(records) * DIMENSION * 4 * 3
        bound = {name: value + latent_bytes for name, value in bound.items()}
        bound["host_working_set_bytes"] += parameter_bytes * 6
        bound["gpu_working_set_bytes"] += parameter_bytes * 4
        _require(bound["host_working_set_bytes"] <= self._lease.memory_mb * 1024**2,
                 "complete native4096 batch exceeds reserved host memory estimate")
        if self._device.startswith("cuda:"):
            _require(bound["gpu_working_set_bytes"] <= self._lease.gpu_memory_mb * 1024**2,
                     "complete native4096 batch exceeds reserved GPU memory estimate")
        return bound

    def _decision(self, text, vector, tokens, output, enabled):
        surrogate = (batched._NoForward() if tokens is None else batched._CachedOutput(self._torch,
            text=text, vector=vector, tokens=tokens, output=output, enabled=enabled))
        decoder = span.SpanLegalFormulaDecoder.__new__(span.SpanLegalFormulaDecoder)
        decoder.torch, decoder.model = self._torch, surrogate
        decoder.checkpoint, decoder.checkpoint_sha256 = self._checkpoint, self.checkpoint_sha256
        result = _DECODE_AT_IMPORT(decoder, text, vector, enabled=enabled)
        _require(tokens is None or surrogate._used, "valid native4096 source did not consume its bound output")
        return result

    def decode_formal_logic(self, texts, latents, *, latent_ablation="none",
                            embedding_receipts=None, expected_receipt_sha256s=None):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128
                 and all(type(text) is str and len(text.encode("utf-8")) <= 32768 for text in texts)
                 and sum(len(text.encode("utf-8")) for text in texts) <= 2 * 1024**2,
                 "one to 128 bounded complete native4096 source strings required")
        _require(type(latents) in (list, tuple) and len(latents) == len(texts),
                 "one complete native4096 vector per source required")
        vectors = [span._vector(vector, DIMENSION) for vector in latents]
        _require(type(latent_ablation) is str and latent_ablation in ("none", "zero", "rotate", "disabled"),
                 "unsupported native4096 latent ablation")
        _require(latent_ablation != "rotate" or len(texts) > 1, "rotate requires at least two sources")
        authored = deepcopy({"texts": list(texts), "vectors": vectors,
                             "receipts": embedding_receipts, "receipt_pins": expected_receipt_sha256s})
        inputs_guard = CheckpointContentGuard(authored)
        with self._operation():
            self._check()
            receipt_status = _receipt_status(self._checkpoint, self._synthetic_unreceipted,
                                            embedding_receipts, expected_receipt_sha256s)
            if latent_ablation == "zero":
                vectors = [[0.] * DIMENSION for _ in vectors]
            elif latent_ablation == "rotate":
                vectors = vectors[1:] + vectors[:1]
            enabled = latent_ablation != "disabled"
            start, rows, valid, tokens, locations = len(self._observations), [], [], [], {}
            try:
                if self._optimized:
                    for position, (text, vector) in enumerate(zip(authored["texts"], vectors)):
                        self._poll()
                        try:
                            source_tokens = _TOKENIZER_AT_IMPORT(text)
                        except ValueError:
                            source_tokens = None
                        tokens.append(source_tokens)
                        if source_tokens is not None:
                            locations[position] = len(valid)
                            valid.append({"tokens": source_tokens, "latent": vector})
                    self._check()
                    memory_bound = self._admit_batch_memory(valid)
                    output = None
                    if valid:
                        with self._torch.inference_mode():
                            actual = self._model(*_BATCH_AT_IMPORT(self._tensor_factory, valid), enabled=enabled)
                        _require(type(actual) is dict and set(actual) == set(_OUTPUTS)
                                 and tuple(actual["modality"].shape) == (len(valid), 3)
                                 and tuple(actual["presence"].shape) == (len(valid), 4, 2)
                                 and tuple(actual["start"].shape) == tuple(actual["end"].shape)
                                 and actual["start"].shape[:2] == (len(valid), 6),
                                 "batched native4096 output shape/coverage differs")
                        output = {name: actual[name].detach().cpu() for name in _OUTPUTS}
                        self._synchronize()
                        self._check()
                        _require(all(str(value.device) == "cpu" and value.dtype == self._torch.float32
                                     and bool(self._torch.isfinite(value).all()) for value in output.values()),
                                 "batched native4096 CPU decision tensors differ")
                    for position, (text, vector, source_tokens) in enumerate(zip(authored["texts"], vectors, tokens)):
                        self._poll()
                        row_output = (None if source_tokens is None else
                                      batched._row_output(output, locations[position], len(source_tokens)))
                        with self._torch.inference_mode():
                            rows.append(self._decision(text, vector, source_tokens, row_output, enabled))
                else:
                    memory_bound = {"host_working_set_bytes": 0, "gpu_working_set_bytes": 0}
                    for text, vector in zip(authored["texts"], vectors):
                        self._check()
                        try:
                            source_tokens = _TOKENIZER_AT_IMPORT(text)
                        except ValueError:
                            source_tokens = None
                        if source_tokens is not None:
                            row_bound = self._admit_batch_memory([{"tokens": source_tokens, "latent": vector}])
                            memory_bound = {name: max(value, row_bound[name]) for name, value in memory_bound.items()}
                        with self._torch.inference_mode():
                            rows.append(_DECODE_AT_IMPORT(self._decoder, text, vector, enabled=enabled))
                        self._check()
                    valid = [None] * (len(self._observations) - start)
                count = sum(row["status"] == "decoded" for row in rows)
                result = {"schema": SCHEMA, "lineage_id": head.LINEAGE_ID,
                    "checkpoint_sha256": self.checkpoint_sha256,
                    "context_contract_sha256": self._checkpoint["context_contract_sha256"],
                    "input_dimension": DIMENSION, "rows": rows, "decoded_count": count,
                    "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
                    "latent_ablation": latent_ablation, "target_access": False, "teacher_forcing": False,
                    "training_executed": False, "model_state_unchanged": True,
                    "input_receipts": receipt_status, "execution_profile": self._description(),
                    "actual_forward_batches": deepcopy(self._observations[start:]),
                    "cuda_executed": self._device.startswith("cuda:") and bool(valid),
                    "numerical_batching": self._optimized, "valid_source_count": len(valid),
                    "batch_memory_bound": memory_bound,
                    "cpu_head_output_materializations": 4 if self._optimized and valid else 0,
                    "device_to_cpu_head_transfers": 4 if self._optimized and valid and self._device.startswith("cuda:") else 0,
                    "canonical_decision_device": "cpu", "synthetic_embeddings": True,
                    "native_leanstral_head_qualified": False, "production_admission": False, **span.FALSE}
                result_guard = CheckpointContentGuard(result)
                self._check()
                inputs_guard.check({"texts": list(texts), "vectors": [span._vector(vector, DIMENSION) for vector in latents],
                                    "receipts": embedding_receipts, "receipt_pins": expected_receipt_sha256s})
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
                     "foreign process/thread cannot close a native4096 lease")
            _require(not self._active, "native4096 session operation is already active")
            if self._closed:
                return
            self._synchronize()
            self._model = None
            if hasattr(self, "_decoder"):
                self._decoder.model = None
            self._model_identity, self._model_type, self._forward = None, None, None
            self._module_layout = []
            self._reference, self._pointers, self._observations = {}, {}, []
            self._reference_anchor, self._reference_anchor_identity = None, None
            self._reference_payload_identity = None
            self._closed = True
            if self._lease is not None:
                self._lease.release()

    def __enter__(self):
        with self._operation():
            self._check()
        return self

    def __exit__(self, *ignored):
        self.close()


__all__ = ["DeviceLeanstral4096SpanSession", "SCHEMA", "PROFILE", "CUDA_GRU_PROFILE", "DIMENSION"]
