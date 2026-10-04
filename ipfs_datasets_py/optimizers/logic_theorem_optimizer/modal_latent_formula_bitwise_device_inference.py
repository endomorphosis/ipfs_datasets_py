"""Owned bitwise device inference for exact 8D and 384D formula lineages.

The original checkpoint validator, Adam restoration, numerical model, grammar,
batched/scalar decisions and device observation hooks remain source bound.
One validated CPU restoration runs after admission and produces an immutable
reference byte anchor before mutable reference cloning or any model upload.
Complete reference bytes and tensor values are checked at every inherited
entry/exit boundary. No successful check is cached and no shared producer is
patched. Cancellation and deadlines are cooperative around native operations.

Optimization defaults on and selects CUDA when available. Explicit opt-out
uses the original CPU numerical path. This module declares no CUDA execution,
performance, semantic, training, production or proof qualification. Adam is
constructed/restored for validation, without a step or fit.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import re
import threading
import time
from types import CodeType, FunctionType

from . import modal_latent_formula as native
from . import modal_latent_formula_inference as batched
from . import modal_latent_formula_device_inference as inherited
from . import owned_tensor_bitwise_guard as bitwise_guard
from . import checkpoint_content_guard as checkpoint_guard
from . import resource_scheduler as resources

PROFILE = "modal-latent-formula-bitwise-owned-device-float32/v1"
SCHEMA = "modal-latent-formula-inference/v1"
LINEAGES = {"legacy_hub_v1": 8, "current_legal_v2": 384}
MAX_REFERENCE_BYTES = 128 * 1024**2
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_require = native._require
_BASE_CLASS = inherited.DeviceLatentFormulaDecoder
_NATIVE_CLASS = native.LatentFormulaDecoder
_BATCH_CLASS = batched.BatchedLatentFormulaDecoder
_DEVICE_TORCH = inherited._DeviceTorch
_RESTORE = native._restore
_DEVICE_INFER = _BASE_CLASS._infer
_PROJECT = _NATIVE_CLASS.project
_CHECKPOINT_GUARD = checkpoint_guard.CheckpointContentGuard
_SCHEDULER = resources.GlobalResourceScheduler
_RESOURCE_LEASE = resources.ResourceLease
_BITWISE_CHECK = bitwise_guard.check_owned_tensor_bytes
_NATIVE_IMPLEMENTATION = native._implementation
_BASE_IMPLEMENTATION = inherited.inference_implementation
_BITWISE_IMPLEMENTATION = bitwise_guard.inference_implementation


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _fingerprint(value):
    if isinstance(value, property):
        return (value, value.fget, value.fget.__code__)
    return (value, getattr(value, "__code__", None))


def _same(value, identity):
    actual = _fingerprint(value)
    return len(actual) == len(identity) and all(left is right for left, right in zip(actual, identity))


_SOURCE_AT_IMPORT = _source_sha256()
_SOURCES = {module: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (native, batched, inherited, bitwise_guard, checkpoint_guard, resources)}
_FUNCTIONS = {
    native: ("_require", "_raw", "checkpoint_digest", "_pins", "_implementation", "_torch", "_binding", "_config",
             "_tensor", "_model", "_optimizer", "_restore", "_vector", "_rows", "_display"),
    batched: ("inference_implementation", "_source_sha256", "_validated_rows", "_inference_vector",
              "_effective_dependency", "_rows", "_display", "checkpoint_digest", "_require"),
    inherited: ("inference_implementation", "_source_sha256"),
    bitwise_guard: ("check_owned_tensor_bytes", "inference_implementation", "_source_sha256", "_plan", "_positive_limit"),
    checkpoint_guard: ("inference_implementation", "_source_sha256", "_raw", "_freeze", "_matches"),
    native.codec_module: ("validate_codec", "allowed_token_ids", "decode_target", "_prefix"),
}
_FUNCTIONS_AT_IMPORT = {module: {name: _fingerprint(getattr(module, name)) for name in names}
                        for module, names in _FUNCTIONS.items()}
_CLASS_NAMES = {native: "LatentFormulaDecoder", batched: "BatchedLatentFormulaDecoder",
                inherited: "DeviceLatentFormulaDecoder", checkpoint_guard: "CheckpointContentGuard",
                resources: "GlobalResourceScheduler"}
_CLASSES_AT_IMPORT = {module: getattr(module, name) for module, name in _CLASS_NAMES.items()}
_CLASS_METHODS = {
    _NATIVE_CLASS: ("__init__", "_check", "project", "_decode", "infer", "checkpoint", "codec", "checkpoint_sha256"),
    _BATCH_CLASS: ("_check", "_base", "_decoded", "_decode_scalar", "_decode_batch", "infer", "infer_with_projection", "_infer", "inference_implementation"),
    _BASE_CLASS: ("__init__", "_check", "_infer", "inference_implementation"),
    _DEVICE_TORCH: ("__init__", "tensor", "__getattr__"),
    _CHECKPOINT_GUARD: ("__init__", "check"),
    _SCHEDULER: ("acquire", "renew", "cancel", "release", "is_cancelled"),
    _RESOURCE_LEASE: ("renew", "release", "to_dict", "released", "cancelled"),
}
_METHODS_AT_IMPORT = {owner: {name: _fingerprint(getattr(owner, name)) for name in names}
                      for owner, names in _CLASS_METHODS.items()}
_NATIVE_AT_IMPORT = _NATIVE_IMPLEMENTATION()
_BASE_AT_IMPORT = _BASE_IMPLEMENTATION()
_BITWISE_AT_IMPORT = _BITWISE_IMPLEMENTATION()
_SOURCE_FUNCTION_AT_IMPORT = _source_sha256


def _nested_code(code, name):
    found = [part for part in code.co_consts if type(part) is CodeType and part.co_name == name]
    _require(len(found) == 1, "exact inherited formula observation code required")
    return found[0]


_OBSERVER_CODE = _nested_code(_nested_code(_DEVICE_INFER.__code__, "observed"), "hook")


@dataclass(frozen=True, slots=True)
class _ReferenceByteAnchor:
    checkpoint_sha256: str
    layout: tuple
    payload: bytes
    sha256: str


def inference_implementation():
    _require(all(globals().get(name) is identity[0] and getattr(globals().get(name), "__code__", None) is identity[1]
                 for name, identity in _OWN_FUNCTIONS_AT_IMPORT.items()), "bitwise formula owner helper function changed")
    _require(_source_sha256 is _SOURCE_FUNCTION_AT_IMPORT and _source_sha256() == _SOURCE_AT_IMPORT,
             "bitwise formula adapter source changed since import")
    _require(all(hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == expected
                 for module, expected in _SOURCES.items()), "bitwise formula dependency source changed")
    _require(all(getattr(module, name) is _CLASSES_AT_IMPORT[module] for module, name in _CLASS_NAMES.items())
             and inherited._DeviceTorch is _DEVICE_TORCH
             and resources.ResourceLease is _RESOURCE_LEASE
             and all(_same(getattr(module, name), identity) for module, entries in _FUNCTIONS_AT_IMPORT.items()
                     for name, identity in entries.items())
             and all(_same(getattr(owner, name), identity) for owner, entries in _METHODS_AT_IMPORT.items()
                     for name, identity in entries.items()), "bitwise formula class, method or function binding changed")
    _require(native.FALSE == _FALSE_AT_IMPORT and native.PROJECTION_ID == _PROJECTION_AT_IMPORT
             and native.SCHEMA == _CHECKPOINT_SCHEMA_AT_IMPORT
             and native.codec_module is _CODEC_AT_IMPORT
             and batched.learning is native and inherited.batched is batched,
             "bitwise formula lineage, grammar or inference binding changed")
    _require(_NATIVE_IMPLEMENTATION() == _NATIVE_AT_IMPORT and _BASE_IMPLEMENTATION() == _BASE_AT_IMPORT
             and _BITWISE_IMPLEMENTATION() == _BITWISE_AT_IMPORT,
             "bitwise formula transitive producer implementation changed")
    if _OWN_METHODS_AT_IMPORT:
        _require(BitwiseDeviceLatentFormulaDecoder is _OWN_CLASS_AT_IMPORT
                 and all(_same(getattr(BitwiseDeviceLatentFormulaDecoder, name), identity)
                         for name, identity in _OWN_METHODS_AT_IMPORT.items()), "bitwise formula owner methods changed")
    return {"schema": "modal-latent-formula-bitwise-device-implementation/v1", "profile_id": PROFILE,
        "source_sha256": _SOURCE_AT_IMPORT, "inherited_device_implementation": deepcopy(_BASE_AT_IMPORT),
        "native_checkpoint_implementation": deepcopy(_NATIVE_AT_IMPORT),
        "bitwise_guard_implementation": deepcopy(_BITWISE_AT_IMPORT),
        "checkpoint_guard_source_sha256": _SOURCES[checkpoint_guard],
        "resource_scheduler_source_sha256": _SOURCES[resources],
        "checkpoint_conversion_performed": False, "native_cuda_qualified": False,
        "performance_qualified": False, "semantic_qualification": False,
        "production_admission": False, "proof_authority": False}


_FALSE_AT_IMPORT = deepcopy(native.FALSE)
_PROJECTION_AT_IMPORT = native.PROJECTION_ID
_CHECKPOINT_SCHEMA_AT_IMPORT = native.SCHEMA
_CODEC_AT_IMPORT = native.codec_module
_OWN_METHODS_AT_IMPORT = {}
_OWN_CLASS_AT_IMPORT = None
_OWN_FUNCTIONS_AT_IMPORT = {}


def _positive(value, maximum, label):
    _require(type(value) in (int, float) and math.isfinite(value) and 0 < value <= maximum,
             "bounded positive " + label + " required")
    return float(value)


def _strict_json(value):
    pending, nodes = [(value, 0)], 0
    while pending:
        part, depth = pending.pop()
        nodes += 1
        _require(depth <= 64 and nodes <= 2_000_000, "bounded plain formula checkpoint required")
        if type(part) is dict:
            _require(all(type(name) is str for name in part), "plain checkpoint string keys required")
            pending.extend((child, depth + 1) for child in part.values())
        elif type(part) is list:
            pending.extend((child, depth + 1) for child in part)
        elif type(part) in (int, float):
            try:
                finite = math.isfinite(part)
            except OverflowError:
                finite = False
            _require(finite, "finite plain checkpoint numbers required")
        else:
            _require(type(part) in (str, bool, type(None)), "plain formula checkpoint values required")


def _select_device(torch, optimized):
    if not optimized or not torch.cuda.is_available():
        return "cpu"
    index = torch.cuda.current_device() if torch.cuda.is_initialized() else 0
    _require(type(index) is int and 0 <= index <= 1024, "bounded CUDA device index required")
    return "cuda:" + str(index)


class BitwiseDeviceLatentFormulaDecoder(_BASE_CLASS):
    """One admitted exact-lineage formula head with independent byte custody."""
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, expected_binding=None,
                 optimized=True, scheduler=None, parent_lease=None, cancel_event=None,
                 admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=512, gpu_memory_mb=256, unified_memory_mb=0):
        _require(inference_implementation is _IMPLEMENTATION_FUNCTION_AT_IMPORT, "bitwise formula implementation function changed")
        inference_implementation()
        _require(type(optimized) is bool, "optimized must be boolean")
        _require(type(expected_checkpoint_sha256) is str and _SHA.fullmatch(expected_checkpoint_sha256),
                 "external formula checkpoint SHA256 required")
        _require(type(memory_mb) is int and 256 <= memory_mb <= 65536
                 and type(gpu_memory_mb) is int and 128 <= gpu_memory_mb <= 65536
                 and type(unified_memory_mb) is int and 0 <= unified_memory_mb <= 131072,
                 "bounded explicit formula host/GPU reservations required")
        maximum = _positive(max_seconds, 600, "formula deadline")
        admission = _positive(admission_timeout_seconds, 600, "formula admission wait")
        _require(cancel_event is None or callable(getattr(cancel_event, "is_set", None)), "cancellation must expose is_set")
        self._process, self._thread = os.getpid(), threading.get_ident()
        self._lock, self._active, self._closed = threading.RLock(), False, False
        self._deadline, self._cancel, self._lease = time.monotonic() + maximum, cancel_event, None
        self._cancel_identity = cancel_event
        self._active_observer, self.model, self._device = None, None, "cpu"
        self._device_materialized = False
        self._optimized = optimized
        _strict_json(checkpoint)
        self._checkpoint = deepcopy(checkpoint)
        self._checkpoint_sha256 = expected_checkpoint_sha256
        self._checkpoint_guard = _CHECKPOINT_GUARD(self._checkpoint, expected_sha256=expected_checkpoint_sha256)
        _require(len(self._checkpoint_guard._canonical_bytes) <= native.MAX_BYTES
                 and 128 * 1024**2 + len(self._checkpoint_guard._canonical_bytes) * 12 <= memory_mb * 1024**2,
                 "formula checkpoint exceeds admitted CPU restoration estimate")
        binding = native._binding(self._checkpoint["binding"])
        _require(LINEAGES.get(binding["lineage_id"]) == binding["dimension"], "exact8D/384D formula lineage required")
        self._binding = binding
        import torch
        _require(torch.get_num_threads() == 1 and str(torch.get_default_device()) == "cpu"
                 and torch.get_default_dtype() == torch.float32, "caller must reserve one CPU thread with unchanged float32 defaults")
        self._native_torch = torch
        self._device = _select_device(torch, optimized)
        scheduler = resources.get_global_resource_scheduler() if scheduler is None else scheduler
        _require(type(scheduler) is _SCHEDULER, "exact shared formula resource scheduler required")
        self._scheduler = scheduler
        try:
            self._poll()
            self._lease = scheduler.acquire(resources.ResourceLane.SNAPSHOT_EVALUATION, cpu_slots=1,
                memory_mb=memory_mb, gpu_memory_mb=gpu_memory_mb if self._device.startswith("cuda:") else 0,
                unified_memory_mb=unified_memory_mb if self._device.startswith("cuda:") else 0,
                requires_gpu=self._device.startswith("cuda:"), parent_lease=parent_lease,
                timeout=admission, cancel_event=cancel_event, request_id="modal-formula-bitwise-device-inference")
            self._lease_identity = self._lease
            self._lease_guard = _CHECKPOINT_GUARD(self._lease_binding())
            self._poll()
            inference_implementation()
            # The immutable CPU checkpoint bytes are independent of every
            # mutable model/reference storage and precede cloning or upload.
            reference_torch, independent, independent_adam = _RESTORE(self._checkpoint, expected_binding)
            _require(reference_torch is torch and all(str(value.device) == "cpu" for value in independent.state_dict().values()),
                     "independent formula checkpoint restoration must remain CPU")
            layout, byte_count = self._byte_plan(dict(independent.state_dict()), expected_device="cpu")
            payload = self._state_bytes(dict(independent.state_dict()), layout, byte_count)
            self._reference_anchor = _ReferenceByteAnchor(expected_checkpoint_sha256, layout, payload,
                                                         hashlib.sha256(payload).hexdigest())
            self._reference_anchor_identity = self._reference_anchor
            self._reference_payload_identity, self._reference_anchor_sha256 = payload, self._reference_anchor.sha256
            model, independent_adam = independent, None
            self.model = model
            independent = None
            self._poll()
            inference_implementation()
            self._reference_weights = {name: value.detach().clone() for name, value in model.state_dict().items()}
            before_layout, before_count = self._byte_plan(self._reference_weights, expected_device="cpu")
            _require(before_layout == layout and before_count == byte_count
                     and self._state_bytes(self._reference_weights, before_layout, before_count) == payload,
                     "validated formula checkpoint bytes disagree before GPU upload")
            self._poll()
            self._device_materialized = True
            model.to(self._device)
            self._reference_weights = {name: value.to(self._device) for name, value in self._reference_weights.items()}
            for parameter in model.parameters():
                parameter.requires_grad_(False)
            model.eval()
            self.torch = _DEVICE_TORCH(torch, self._device)
            self._tensor_factory = self.torch
            self._codec = self._checkpoint["codec"]
            self._model_identity, self._model_type = model, type(model)
            self._reference_identity = self._reference_weights
            self._reference_values = dict(self._reference_weights)
            resident_state = dict(model.state_dict())
            resident_layout, resident_count = self._byte_plan(resident_state, expected_device=self._device)
            _require(resident_layout == layout and resident_count == byte_count
                     and self._state_bytes(resident_state, resident_layout, resident_count) == payload,
                     "uploaded formula model bytes disagree with admitted CPU checkpoint")
            # CUDA GRU upload may pack parameters into shared storage. Bind
            # each owner's physical metadata after upload independently of
            # the checkpoint's device-independent logical byte layout.
            self._state_storage_layout = self._storage_layout(resident_state)
            self._reference_storage_layout = self._storage_layout(self._reference_weights)
            self._state_pointers = {name: value.data_ptr() for name, value in resident_state.items()}
            self._reference_pointers = {name: value.data_ptr() for name, value in self._reference_weights.items()}
            self._module_layout = [(name, module, type(module), _fingerprint(module.forward.__func__))
                                   for name, module in model.named_modules()]
            self._model_methods = {name: _fingerprint(getattr(model, name).__func__) for name in
                ("project", "start", "next_logits", "state_dict", "named_modules", "named_parameters", "named_buffers")}
            self._parameter_layout = list(model.named_parameters())
            self._buffer_layout = list(model.named_buffers())
            self._policy_guard = _CHECKPOINT_GUARD(self._policy())
            self._check()
        except BaseException:
            self.close()
            raise

    def _poll(self):
        _require(os.getpid() == self._process and threading.get_ident() == self._thread and not self._closed,
                 "formula session is closed or belongs to another process/thread")
        _require(self._cancel is self._cancel_identity, "formula cancellation signal identity changed")
        if self._cancel is not None and self._cancel.is_set():
            raise TimeoutError("formula inference cancelled")
        if time.monotonic() >= self._deadline:
            raise TimeoutError("formula inference deadline expired")
        if self._lease is not None:
            _require(self._lease is self._lease_identity and not self._lease.released
                     and not self._lease.cancelled and self._lease.renew(),
                     "owned formula resource lease expired, cancelled or changed")

    def _lease_binding(self):
        names = ("lease_id", "lease_key", "lane", "cpu_slots", "memory_mb", "gpu_memory_mb", "unified_memory_mb",
                 "child_process_slots", "requires_gpu", "parent_lease_id", "owner_pid")
        return {name: getattr(self._lease, name) for name in names}

    def _policy(self):
        torch = self._native_torch
        return {"device": self._device, "optimized": self._optimized, "binding": self._binding,
            "checkpoint_sha256": self._checkpoint_sha256, "deadline": self._deadline,
            "cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
            "cudnn_allow_tf32": torch.backends.cudnn.allow_tf32,
            "float32_matmul_precision": torch.get_float32_matmul_precision()}

    def _byte_plan(self, state, *, expected_device):
        torch = self._native_torch
        _require(type(state) is dict and 1 <= len(state) <= 4096 and all(type(name) is str and 0 < len(name) <= 1024 for name in state),
                 "bounded ordinary named formula state required")
        layout, total = [], 0
        for name in sorted(state):
            value = state[name]
            _require(isinstance(value, torch.Tensor) and value.dtype == torch.float32 and value.layout == torch.strided
                     and str(value.device) == expected_device and value.is_contiguous() and not value.is_conj() and not value.is_neg()
                     and value.element_size() == 4, "supported resolved contiguous float32 formula state required; nonfloat buffers refuse")
            total += value.numel() * 4
            _require(total <= MAX_REFERENCE_BYTES, "bounded complete formula reference byte anchor required")
            layout.append((name, tuple(value.shape), value.numel()))
        _require(total > 0, "nonempty formula reference byte anchor required")
        host_bound = 128 * 1024**2 + len(self._checkpoint_guard._canonical_bytes) * 12 + total * 12
        gpu_bound = 64 * 1024**2 + total * 8
        _require(host_bound <= self._lease.memory_mb * 1024**2, "formula byte anchor exceeds reserved host estimate")
        if self._device.startswith("cuda:"):
            _require(gpu_bound <= self._lease.gpu_memory_mb * 1024**2, "formula byte anchor exceeds reserved GPU estimate")
        return tuple(layout), total

    def _storage_layout(self, state):
        return tuple((name, str(value.device), tuple(value.stride()), value.storage_offset(), value.data_ptr())
                     for name, value in sorted(state.items()))

    def _state_bytes(self, state, layout, count):
        views = [state[name].detach().reshape(-1).view(self._native_torch.uint8) for name, *_ in layout]
        value = self._native_torch.cat(views)
        _require(value.numel() == count, "complete formula reference byte coverage differs")
        payload = value.cpu().numpy().tobytes()
        _require(type(payload) is bytes and len(payload) == count, "immutable complete formula reference bytes required")
        return payload

    def _check_reference_anchor(self):
        anchor = self._reference_anchor
        _require(type(anchor) is _ReferenceByteAnchor and anchor is self._reference_anchor_identity
                 and type(anchor.payload) is bytes and anchor.payload is self._reference_payload_identity
                 and anchor.checkpoint_sha256 == self._checkpoint_sha256 and anchor.sha256 == self._reference_anchor_sha256,
                 "immutable formula reference byte anchor changed")
        layout, count = self._byte_plan(self._reference_weights, expected_device=self._device)
        _require(layout == anchor.layout and count == len(anchor.payload)
                 and self._storage_layout(self._reference_weights) == self._reference_storage_layout,
                 "formula reference byte layout or physical storage metadata changed")
        _require(self._state_bytes(self._reference_weights, layout, count) == anchor.payload,
                 "formula reference bytes changed from admitted checkpoint")
        return {"schema": "modal-formula-owned-reference-byte-currentness/v1", "checkpoint_sha256": anchor.checkpoint_sha256,
            "anchor_sha256": anchor.sha256, "reference_bytes": count, "reference_device": self._device,
            "origin": "validated_cpu_checkpoint_model_before_reference_clone_and_upload",
            "independent_of_mutable_reference_storage": True,
            "comparison": "complete_immutable_float32_bytes_including_signed_zero",
            "device_to_cpu_reference_transfers": int(self._device.startswith("cuda:")), "cpu_byte_materializations": 1,
            "anchor_identity_checked": True, "metadata_and_reservation_checked_before_allocation": True,
            "proof_authority": False, "kernel_resource_enforcement": False}

    def _check_hooks(self):
        observed = {}
        for name, module, _, _ in self._module_layout:
            _require(not module._forward_pre_hooks and not module._backward_hooks,
                     "foreign formula pre/backward hooks are unsupported")
            hooks = list(module._forward_hooks.values())
            if not hooks:
                continue
            _require(self._active and name in ("projection_down", "projection_up", "output") and len(hooks) == 1,
                     "foreign formula forward hook changed")
            hook = hooks[0]
            _require(type(hook) is FunctionType and hook.__code__ is _OBSERVER_CODE
                     and hook.__globals__ is _DEVICE_INFER.__globals__ and hook.__closure__ is not None,
                     "inherited formula observer implementation changed")
            closure = {key: cell.cell_contents for key, cell in zip(hook.__code__.co_freevars, hook.__closure__)}
            calls = closure.get("calls")
            _require(closure.get("self") is self and closure.get("name") == name and type(calls) is dict
                     and set(calls) == {"projection_down", "projection_up", "output"}
                     and all(type(value) is int and value >= 0 for value in calls.values()), "inherited formula observer custody changed")
            observed[name] = calls
        if observed:
            _require(set(observed) == {"projection_down", "projection_up", "output"}
                     and all(value is next(iter(observed.values())) for value in observed.values()), "complete inherited formula observer set required")
            calls = next(iter(observed.values()))
            if self._active_observer is None:
                self._active_observer = calls
            _require(calls is self._active_observer, "inherited formula observer identity changed during request")

    def _pure_check(self):
        torch, model = self._native_torch, self.model
        native._torch()
        _require(not self._closed and model is self._model_identity and type(model) is self._model_type
                 and self.torch is self._tensor_factory and type(self.torch) is _DEVICE_TORCH
                 and self.torch._torch is torch and self.torch._device == self._device, "formula model or tensor factory binding changed")
        self._checkpoint_guard.check(self._checkpoint)
        _require(self._checkpoint["implementation"] == _NATIVE_IMPLEMENTATION() and self._codec is self._checkpoint["codec"],
                 "formula checkpoint/codec source binding changed")
        self._policy_guard.check(self._policy())
        _require(self._lease is self._lease_identity and self._lease._scheduler is self._scheduler,
                 "formula resource lease binding changed")
        self._lease_guard.check(self._lease_binding())
        _require(torch.get_num_threads() == 1 and str(torch.get_default_device()) == "cpu" and torch.get_default_dtype() == torch.float32
                 and not torch.is_autocast_enabled("cpu") and not torch.is_autocast_enabled("cuda"), "formula float32 defaults, thread or autocast changed")
        _require(all(_same(getattr(getattr(model, name, None), "__func__", None), identity)
                     for name, identity in self._model_methods.items()),
                 "formula numerical model method changed")
        modules = list(model.named_modules())
        _require(len(modules) == len(self._module_layout) and all(name == old[0] and module is old[1]
                 and type(module) is old[2] and _same(getattr(module.forward, "__func__", None), old[3])
                 for (name, module), old in zip(modules, self._module_layout)), "formula numerical module layout changed")
        parameters, buffers = list(model.named_parameters()), list(model.named_buffers())
        _require(len(parameters) == len(self._parameter_layout) and all(name == old[0] and value is old[1]
                 for (name, value), old in zip(parameters, self._parameter_layout))
                 and len(buffers) == len(self._buffer_layout) and all(name == old[0] and value is old[1]
                 for (name, value), old in zip(buffers, self._buffer_layout)), "formula parameter/buffer identity changed")
        state = dict(model.state_dict())
        layout, count = self._byte_plan(state, expected_device=self._device)
        _require(layout == self._reference_anchor.layout and count == len(self._reference_anchor.payload)
                 and self._storage_layout(state) == self._state_storage_layout
                 and self._reference_weights is self._reference_identity and set(state) == set(self._reference_weights)
                 and all(value.data_ptr() == self._state_pointers[name] for name, value in state.items())
                 and all(value is self._reference_values[name] and value.data_ptr() == self._reference_pointers[name]
                         for name, value in self._reference_weights.items()), "formula tensor/reference metadata or storage changed")
        self._reference_anchor_receipt = self._check_reference_anchor()
        if self._device == "cpu":
            # CPU comparison instructions may flush subnormals. Immutable
            # physical bytes preserve currentness independently of that mode.
            _require(self._state_bytes(state, layout, count) == self._reference_anchor.payload,
                     "formula CPU model bytes changed from admitted checkpoint")
        self._value_guard_receipt = _BITWISE_CHECK(torch, state, self._reference_weights, optimized=self._optimized,
            max_total_bytes=2 * MAX_REFERENCE_BYTES, max_temporary_bytes=64 * 1024**2)
        _require(all(not module.training for _, module in modules) and all(not value.requires_grad and value.grad is None for _, value in parameters),
                 "formula modes or gradients changed")
        _require(not torch.nn.modules.module._global_forward_hooks and not torch.nn.modules.module._global_forward_pre_hooks
                 and not torch.nn.modules.module._global_backward_hooks, "global formula hooks are unsupported")
        self._check_hooks()

    def _check(self):
        self._poll()
        _require(inference_implementation is _IMPLEMENTATION_FUNCTION_AT_IMPORT, "bitwise formula implementation function changed")
        implementation = inference_implementation()
        self._pure_check()
        return {**implementation, "device": self._device, "cuda_selected": self._device.startswith("cuda:"),
            "optimized": self._optimized, "dimension": self._binding["dimension"], "lineage_id": self._binding["lineage_id"],
            "stored_checkpoint_device": "cpu", "dtype": "float32", "owned_admission": True,
            "reference_byte_currentness": deepcopy(self._reference_anchor_receipt),
            "owned_tensor_currentness": deepcopy(self._value_guard_receipt),
            "cpu_model_byte_currentness_checked": self._device == "cpu",
            "resource_lease": self._lease.to_dict(), "adam_restoration_performed": True,
            "adam_restore_count": 1, "optimizer_steps_executed": 0, "training_executed": False,
            "deadline_scope": "cooperative_around_inherited_calls_not_native_preemption"}

    @contextmanager
    def _operation(self):
        with self._lock:
            _require(os.getpid() == self._process and threading.get_ident() == self._thread and not self._closed,
                     "foreign or closed formula session")
            _require(not self._active, "formula session operation is already active")
            self._active, self._active_observer = True, None
            try:
                yield
            finally:
                self._active, self._active_observer = False, None

    def _infer(self, rows, *, projection_id, include_projection):
        with self._operation():
            self._check()
            _require(type(projection_id) is str and 0 < len(projection_id) <= 256, "bounded projection id required")
            _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 128, "one to 128 inference rows required")
            _strict_json(list(rows))
            input_guard = _CHECKPOINT_GUARD({"rows": list(rows), "projection_id": projection_id})
            try:
                result = _DEVICE_INFER(self, rows, projection_id=projection_id, include_projection=include_projection)
                self._synchronize()
                self._check()
                input_guard.check({"rows": list(rows), "projection_id": projection_id})
                return result
            finally:
                self._synchronize()

    def project(self, latents):
        with self._operation():
            self._check()
            _require(type(latents) in (list, tuple) and 1 <= len(latents) <= 128, "one to 128 vectors required")
            _strict_json(list(latents))
            inputs = _CHECKPOINT_GUARD({"latents": list(latents)})
            try:
                result = _PROJECT(self, latents)
                self._synchronize()
                self._check()
                inputs.check({"latents": list(latents)})
                return result
            finally:
                self._synchronize()

    def describe(self):
        with self._operation():
            return self._check()

    @property
    def inference_implementation(self):
        return self.describe()

    def _synchronize(self):
        if self._device_materialized and self._device.startswith("cuda:"):
            self._native_torch.cuda.synchronize(self._device)

    def close(self):
        with self._lock:
            _require(os.getpid() == self._process and threading.get_ident() == self._thread,
                     "foreign process/thread cannot close formula ownership")
            _require(not self._active, "formula session operation is already active")
            if self._closed:
                return
            self._synchronize()
            self.model, self._model_identity = None, None
            self._reference_weights, self._reference_values = {}, {}
            self._reference_identity, self._reference_anchor, self._reference_anchor_identity = None, None, None
            self._reference_payload_identity = None
            self._module_layout, self._parameter_layout, self._buffer_layout = [], [], []
            self._closed = True
            if self._lease is not None:
                self._lease.release()

    def __enter__(self):
        with self._operation():
            self._check()
        return self

    def __exit__(self, *ignored):
        self.close()


_OWN_CLASS_AT_IMPORT = BitwiseDeviceLatentFormulaDecoder
_IMPLEMENTATION_FUNCTION_AT_IMPORT = inference_implementation
_OWN_FUNCTIONS_AT_IMPORT = {name: _fingerprint(globals()[name]) for name in
    ("inference_implementation", "_source_sha256", "_fingerprint", "_same", "_nested_code", "_positive", "_strict_json", "_select_device", "_require")}
_OWN_METHODS_AT_IMPORT = {name: _fingerprint(getattr(_OWN_CLASS_AT_IMPORT, name)) for name in
    ("__init__", "_poll", "_lease_binding", "_policy", "_byte_plan", "_storage_layout", "_state_bytes", "_check_reference_anchor",
     "_check_hooks", "_pure_check", "_check", "_operation", "_infer", "project", "describe", "inference_implementation",
     "_synchronize", "close", "__enter__", "__exit__")}

__all__ = ["BitwiseDeviceLatentFormulaDecoder", "PROFILE", "SCHEMA", "LINEAGES", "inference_implementation"]
