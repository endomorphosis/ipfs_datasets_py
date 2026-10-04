"""Separately versioned native768 batching with anchored bitwise currentness.

An immutable byte anchor comes from the independently validated CPU checkpoint
model after resource admission and before private device upload. Every original
public/intermediate/closing guard boundary compares all reference bytes with
that anchor and all model values with the reference. The original numerical
forwards, receipt checks, cancellation ordering and producers remain unchanged.

CUDA comparison uses exact int32 views plus reference finiteness. CPU opt-out
keeps inherited singleton numerical execution. This closed profile requires
contiguous float32 state and refuses unsupported buffers before allocation.
It grants no training, native encoder, production, performance or proof authority.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import threading
import time

from . import legal_span_device_inference as resident
from . import legal_span_device_batch_inference as batched
from . import owned_tensor_bitwise_guard as bitwise_guard
from .checkpoint_content_guard import CheckpointContentGuard


SCHEMA = batched.SCHEMA
PROFILE = "native-768-source-span-batched-device-bitwise-checkpoint-anchor-float32/v1"
CUDA_GRU_PROFILE = resident.CUDA_GRU_PROFILE
DIMENSION = 768
_require = resident._require
_MAX_REFERENCE_BYTES = 256 * 1024**2


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()
_RESIDENT_CLASS_AT_IMPORT = resident.DeviceDimensionalSpanSession
_BATCH_CLASS_AT_IMPORT = batched.DeviceBatchedDimensionalSpanSession
_RESIDENT_IMPLEMENTATION_AT_IMPORT = resident._implementation
_BATCH_IMPLEMENTATION_AT_IMPORT = batched._implementation
_BATCH_AT_IMPORT = _BATCH_IMPLEMENTATION_AT_IMPORT()
_RESIDENT_METHOD_NAMES = ("__init__", "_poll", "_pure_check", "_check", "_operation", "checkpoint",
    "describe", "_description", "decode_formal_logic", "infer", "_synchronize", "close", "__enter__", "__exit__")
_BATCH_METHOD_NAMES = ("_check", "_description", "_decision", "_admit_batch_memory", "decode_formal_logic", "infer")
_RESIDENT_METHODS_AT_IMPORT = {name: getattr(_RESIDENT_CLASS_AT_IMPORT, name) for name in _RESIDENT_METHOD_NAMES}
_BATCH_METHODS_AT_IMPORT = {name: getattr(_BATCH_CLASS_AT_IMPORT, name) for name in _BATCH_METHOD_NAMES}
_BATCH_DESCRIPTION_AT_IMPORT = _BATCH_CLASS_AT_IMPORT._description
_CLOSE_AT_IMPORT = _RESIDENT_CLASS_AT_IMPORT.close
_RESIDENT_HELPER_NAMES = ("_positive", "_strict_json", "_restore", "_device_model", "_cuda_float32_policy", "_DeviceTorch")
_RESIDENT_HELPERS_AT_IMPORT = {name: getattr(resident, name) for name in _RESIDENT_HELPER_NAMES}
_RESTORE_AT_IMPORT = resident._restore
_DEVICE_MODEL_AT_IMPORT = resident._device_model
_BATCH_MEMORY_AT_IMPORT = batched._batch_memory_bound
_CHECKPOINT_GUARD_AT_IMPORT = CheckpointContentGuard
_BITWISE_CHECK_AT_IMPORT = bitwise_guard.check_owned_tensor_bytes
_BITWISE_IMPLEMENTATION_AT_IMPORT = bitwise_guard.inference_implementation
_BITWISE_AT_IMPORT = _BITWISE_IMPLEMENTATION_AT_IMPORT()
_RESIDENT_PROFILE_AT_IMPORT = resident.PROFILE
_BATCH_PROFILE_AT_IMPORT = batched.PROFILE
_RESIDENT_SCHEMA_AT_IMPORT = resident.SCHEMA
_BATCH_SCHEMA_AT_IMPORT = batched.SCHEMA
_GRU_PROFILE_AT_IMPORT = resident.CUDA_GRU_PROFILE


@dataclass(frozen=True, slots=True)
class _ReferenceByteAnchor:
    """Owned immutable checkpoint bytes, without hostile-process isolation."""
    checkpoint_sha256: str
    layout: tuple
    payload: bytes
    sha256: str


def _check_bindings():
    _require(_source_sha256() == _SOURCE_AT_IMPORT,
             "native768 bitwise session source changed since import")
    _require(resident.DeviceDimensionalSpanSession is _RESIDENT_CLASS_AT_IMPORT
             and batched.DeviceBatchedDimensionalSpanSession is _BATCH_CLASS_AT_IMPORT
             and resident._implementation is _RESIDENT_IMPLEMENTATION_AT_IMPORT
             and batched._implementation is _BATCH_IMPLEMENTATION_AT_IMPORT
             and all(getattr(_RESIDENT_CLASS_AT_IMPORT, name) is method
                     for name, method in _RESIDENT_METHODS_AT_IMPORT.items())
             and all(getattr(_BATCH_CLASS_AT_IMPORT, name) is method
                     for name, method in _BATCH_METHODS_AT_IMPORT.items())
             and all(getattr(resident, name) is helper for name, helper in _RESIDENT_HELPERS_AT_IMPORT.items())
             and batched._batch_memory_bound is _BATCH_MEMORY_AT_IMPORT
             and resident.PROFILE == _RESIDENT_PROFILE_AT_IMPORT
             and batched.PROFILE == _BATCH_PROFILE_AT_IMPORT
             and resident.SCHEMA == _RESIDENT_SCHEMA_AT_IMPORT
             and batched.SCHEMA == _BATCH_SCHEMA_AT_IMPORT
             and resident.CUDA_GRU_PROFILE == _GRU_PROFILE_AT_IMPORT,
             "native768 inherited class, methods, primitives or profile binding changed")
    _require(bitwise_guard.check_owned_tensor_bytes is _BITWISE_CHECK_AT_IMPORT
             and bitwise_guard.inference_implementation is _BITWISE_IMPLEMENTATION_AT_IMPORT
             and CheckpointContentGuard is _CHECKPOINT_GUARD_AT_IMPORT,
             "native768 bitwise comparison or checkpoint guard binding changed")


def _implementation_receipt(batch_implementation, comparison_implementation):
    _require(batch_implementation == _BATCH_AT_IMPORT and comparison_implementation == _BITWISE_AT_IMPORT,
             "native768 bitwise verified implementation differs")
    return {"schema": "native-768-bitwise-checkpoint-anchor-session-implementation/v1",
            "source_sha256": _SOURCE_AT_IMPORT,
            "inherited_batched_implementation": batch_implementation,
            "bitwise_guard_implementation": comparison_implementation,
            "source_verification_success_cached": False,
            "boundary_consolidation_performed": False,
            "native_cuda_qualified": False, "performance_qualified": False,
            "production_admission": False, "proof_authority": False}


def _implementation():
    """Independently verify all current producers and emit a fresh receipt."""
    _check_bindings()
    return _implementation_receipt(_BATCH_IMPLEMENTATION_AT_IMPORT(), _BITWISE_IMPLEMENTATION_AT_IMPORT())


class DeviceBitwiseDimensionalSpanSession(_BATCH_CLASS_AT_IMPORT):
    """Original native768 numerical session with independently anchored state."""
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, optimized=True,
                 scheduler=None, parent_lease=None, cancel_event=None,
                 admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=0):
        _check_bindings()
        _require(type(optimized) is bool, "optimized must be boolean")
        _require(type(expected_checkpoint_sha256) is str and resident.span._SHA.fullmatch(expected_checkpoint_sha256),
                 "external checkpoint SHA256 required")
        maximum = resident._positive(max_seconds, 600, "session deadline")
        admission = resident._positive(admission_timeout_seconds, 600, "admission deadline")
        _require(type(memory_mb) is int and memory_mb >= 1024
                 and type(gpu_memory_mb) is int and gpu_memory_mb >= 256
                 and type(unified_memory_mb) is int and unified_memory_mb >= 0,
                 "explicit bounded CPU/GPU memory reservations required")
        self._process, self._thread, self._lock = os.getpid(), threading.get_ident(), threading.RLock()
        self._deadline, self._cancel = time.monotonic() + maximum, cancel_event
        self._closed, self._model, self._lease = False, None, None
        self._active = False
        self._observations, self._optimized = [], optimized
        self._reference_anchor = self._reference_anchor_identity = self._reference_payload_identity = None
        resident._strict_json(checkpoint)
        self._checkpoint = deepcopy(checkpoint)
        self._guard = CheckpointContentGuard(self._checkpoint, expected_sha256=expected_checkpoint_sha256)
        self.checkpoint_sha256 = expected_checkpoint_sha256
        _RESIDENT_IMPLEMENTATION_AT_IMPORT()
        import torch
        _require(torch.get_num_threads() == 1, "caller must reserve CPU and set torch.set_num_threads(1)")
        _require(str(torch.get_default_device()) == "cpu" and torch.get_default_dtype() == torch.float32,
                 "unchanged CPU/float32 Torch defaults required")
        self._torch = torch
        # Retain the original device-choice order and precision contract.
        self._device = ("cuda:" + str(torch.cuda.current_device())
                        if optimized and torch.cuda.is_available() else "cpu")
        self._precision_policy = resident._cuda_float32_policy(torch) if self._device.startswith("cuda:") else None
        if scheduler is None:
            scheduler = resident.get_global_resource_scheduler()
        _require(type(scheduler) is resident.GlobalResourceScheduler, "exact shared resource scheduler required")
        self._scheduler = scheduler
        self._policy_guard = CheckpointContentGuard(self._policy_binding())
        try:
            self._poll()
            self._lease = scheduler.acquire(resident.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1,
                memory_mb=memory_mb, gpu_memory_mb=gpu_memory_mb if self._device.startswith("cuda:") else 0,
                unified_memory_mb=unified_memory_mb if self._device.startswith("cuda:") else 0,
                requires_gpu=self._device.startswith("cuda:"), parent_lease=parent_lease,
                timeout=min(admission, max(0., self._deadline - time.monotonic())), cancel_event=cancel_event,
                request_id="native-768-source-span-device")
            self._lease_identity = self._lease
            self._lease_guard = CheckpointContentGuard(self._lease_binding())
            self._poll()
            _require(len(self._guard._canonical_bytes) * 12 <= memory_mb * 1024**2,
                     "native768 checkpoint exceeds reserved restoration host memory estimate")
            native = _RESTORE_AT_IMPORT(torch, self._checkpoint)
            native_state = dict(native.state_dict())
            layout, reference_bytes = self._reference_byte_plan(native_state, expected_device="cpu")
            payload = self._reference_state_bytes(native_state, layout, reference_bytes)
            self._reference_anchor = _ReferenceByteAnchor(self.checkpoint_sha256, layout, payload,
                                                          hashlib.sha256(payload).hexdigest())
            self._reference_anchor_identity = self._reference_anchor
            self._reference_payload_identity = payload
            self._reference_anchor_sha256 = self._reference_anchor.sha256
            self._model = _DEVICE_MODEL_AT_IMPORT(torch, native, self._checkpoint["config"], self._device,
                                                  self._observations, self._precision_policy)
            self._model_identity, self._model_type = self._model, type(self._model)
            self._forward = self._model.forward.__func__
            self._module_layout = [(name, module, type(module), module.forward.__func__)
                                   for name, module in self._model.named_modules()]
            self._reference = {name: value.detach().clone() for name, value in self._model.state_dict().items()}
            self._pointers = {name: value.data_ptr() for name, value in self._model.state_dict().items()}
            self._tensor_factory = resident._DeviceTorch(torch, self._device)
            self._decoder = resident.span.SpanLegalFormulaDecoder.__new__(resident.span.SpanLegalFormulaDecoder)
            self._decoder.torch, self._decoder.model = self._tensor_factory, self._model
            self._decoder.checkpoint = self._checkpoint
            self._decoder.checkpoint_sha256 = self.checkpoint_sha256
            self._check()
        except BaseException:
            self.close()
            raise

    def _policy_binding(self):
        return {"optimized": self._optimized, "device": self._device,
                "checkpoint_sha256": self.checkpoint_sha256, "precision_policy": self._precision_policy}

    def _lease_binding(self):
        names = ("lease_id", "lease_key", "lane", "cpu_slots", "memory_mb", "gpu_memory_mb",
                 "unified_memory_mb", "child_process_slots", "requires_gpu", "parent_lease_id", "owner_pid")
        return {name: getattr(self._lease, name) for name in names}

    def _reference_byte_plan(self, state, *, expected_device):
        torch = self._torch
        _require(type(state) is dict and 1 <= len(state) <= 4096
                 and all(type(name) is str and 0 < len(name) <= 1024 for name in state),
                 "bounded ordinary native768 reference tensor state required")
        layout, total = [], 0
        for name in sorted(state):
            value = state[name]
            _require(isinstance(value, torch.Tensor) and value.dtype == torch.float32
                     and value.element_size() == 4 and str(value.device) == expected_device
                     and value.layout == torch.strided and value.is_contiguous()
                     and not value.is_conj() and not value.is_neg(),
                     "resolved contiguous native768 float32 reference tensors required; unsupported buffers refused")
            total += value.numel() * 4
            _require(total <= _MAX_REFERENCE_BYTES, "bounded complete native768 reference byte anchor required")
            layout.append((name, tuple(value.shape), value.numel()))
        _require(total > 0, "nonempty native768 reference byte anchor required")
        host_bound = 128 * 1024**2 + len(self._guard._canonical_bytes) * 12 + total * 8
        gpu_bound = 128 * 1024**2 + total * 6
        _require(host_bound <= self._lease.memory_mb * 1024**2,
                 "native768 reference anchor exceeds reserved host memory estimate")
        if self._device.startswith("cuda:"):
            _require(gpu_bound <= self._lease.gpu_memory_mb * 1024**2,
                     "native768 reference anchor exceeds reserved GPU memory estimate")
        return tuple(layout), total

    def _reference_state_bytes(self, state, layout, reference_bytes):
        views = [state[name].detach().reshape(-1).view(self._torch.uint8) for name, _, _ in layout]
        concatenated = self._torch.cat(views)
        _require(concatenated.numel() == reference_bytes, "complete native768 reference byte coverage differs")
        payload = concatenated.cpu().numpy().tobytes()
        _require(type(payload) is bytes and len(payload) == reference_bytes,
                 "complete immutable native768 reference bytes required")
        return payload

    def _check_reference_anchor(self):
        anchor = self._reference_anchor
        _require(type(anchor) is _ReferenceByteAnchor and anchor is self._reference_anchor_identity
                 and type(anchor.payload) is bytes and anchor.payload is self._reference_payload_identity
                 and anchor.checkpoint_sha256 == self.checkpoint_sha256
                 and anchor.sha256 == self._reference_anchor_sha256,
                 "private native768 immutable reference byte anchor changed")
        layout, reference_bytes = self._reference_byte_plan(self._reference, expected_device=self._device)
        _require(layout == anchor.layout and reference_bytes == len(anchor.payload),
                 "private native768 reference byte layout differs from admitted checkpoint")
        _require(self._reference_state_bytes(self._reference, layout, reference_bytes) == anchor.payload,
                 "private native768 reference bytes changed from admitted checkpoint")
        return {"schema": "native-768-owned-reference-byte-currentness/v1",
                "checkpoint_sha256": anchor.checkpoint_sha256, "anchor_sha256": anchor.sha256,
                "reference_bytes": reference_bytes, "reference_device": self._device,
                "origin": "independently_restored_validated_cpu_checkpoint_model_before_upload",
                "comparison": "complete_immutable_float32_bytes_including_signed_zero",
                "device_to_cpu_reference_transfers": int(self._device.startswith("cuda:")),
                "cpu_byte_materializations": 1, "anchor_identity_checked": True,
                "metadata_and_reservation_checked_before_allocation": True,
                "kernel_resource_enforcement": False, "proof_authority": False}

    def _pure_check(self):
        _check_bindings()
        _require(not self._closed and os.getpid() == self._process
                 and threading.get_ident() == self._thread, "768D device session is closed or foreign")
        self._guard.check(self._checkpoint)
        self._policy_guard.check(self._policy_binding())
        _require(self._lease is self._lease_identity and self._lease._scheduler is self._scheduler,
                 "private native768 resource lease binding changed")
        self._lease_guard.check(self._lease_binding())
        torch, model = self._torch, self._model
        if self._device.startswith("cuda:"):
            _require(resident._cuda_float32_policy(torch) == self._precision_policy,
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
        state = dict(model.state_dict())
        _require(set(state) == set(self._reference) and all(
            str(value.device) == self._device and value.dtype == torch.float32
            and value.shape == self._reference[name].shape and value.data_ptr() == self._pointers[name]
            for name, value in state.items()), "private 768D model tensors changed")
        self._reference_anchor_receipt = self._check_reference_anchor()
        self._value_guard_receipt = _BITWISE_CHECK_AT_IMPORT(torch, state, self._reference,
                                                           optimized=self._optimized)
        _require(all(not module.training and not module._forward_hooks and not module._forward_pre_hooks
                     and not module._backward_hooks for module in model.modules())
                 and all(not parameter.requires_grad and parameter.grad is None for parameter in model.parameters()),
                 "private 768D modes/hooks/gradients changed")
        _require(not torch.nn.modules.module._global_forward_hooks
                 and not torch.nn.modules.module._global_forward_pre_hooks
                 and not torch.nn.modules.module._global_backward_hooks,
                 "global Torch hooks are incompatible with private 768D inference")

    def _admit_batch_memory(self, records):
        state_bytes = sum(value.numel() * value.element_size() for value in self._model.state_dict().values())
        bound = _BATCH_MEMORY_AT_IMPORT(records, self._checkpoint["config"], parameter_bytes=state_bytes,
                                       checkpoint_bytes=len(self._guard._canonical_bytes))
        # The inherited estimate already includes resident weights/references.
        # Add the independent anchor/copy/comparison peak before padded inputs.
        bound["host_working_set_bytes"] += state_bytes * 6
        bound["gpu_working_set_bytes"] += state_bytes * 4
        _require(bound["host_working_set_bytes"] <= self._lease.memory_mb * 1024**2,
                 "complete native768 bitwise batch exceeds reserved host memory estimate")
        if self._device.startswith("cuda:"):
            _require(bound["gpu_working_set_bytes"] <= self._lease.gpu_memory_mb * 1024**2,
                     "complete native768 bitwise batch exceeds reserved GPU memory estimate")
        return bound

    def _description(self):
        _check_bindings()
        description = _BATCH_DESCRIPTION_AT_IMPORT(self)
        implementation = _implementation_receipt(description["batched_implementation"],
                                                  _BITWISE_IMPLEMENTATION_AT_IMPORT())
        description["inherited_profile_id"] = description["profile_id"]
        description["session_profile_id"] = PROFILE
        if self._optimized:
            description["profile_id"] = PROFILE
        description["strict_cuda_gru_profile_id"] = CUDA_GRU_PROFILE
        description["owned_tensor_guard_path"] = (
            "cuda_int32_views_with_reference_finiteness" if self._optimized and self._device.startswith("cuda:")
            else "numeric_reference_checks")
        description["owned_tensor_currentness"] = deepcopy(self._value_guard_receipt)
        description["reference_byte_currentness"] = deepcopy(self._reference_anchor_receipt)
        description["unsupported_state_buffers"] = "refuse_before_anchor_or_comparison_allocation"
        description["boundary_consolidation_performed"] = False
        description["native_bitwise_session_cuda_qualified"] = False
        description["bitwise_session_performance_qualified"] = False
        description["bitwise_session_implementation"] = implementation
        return description

    def close(self):
        _CLOSE_AT_IMPORT(self)
        if self._closed:
            self._reference_anchor = self._reference_anchor_identity = self._reference_payload_identity = None


__all__ = ["DeviceBitwiseDimensionalSpanSession", "SCHEMA", "PROFILE", "CUDA_GRU_PROFILE", "DIMENSION"]
