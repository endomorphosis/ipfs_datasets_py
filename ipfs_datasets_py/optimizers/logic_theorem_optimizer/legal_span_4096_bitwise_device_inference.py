"""Separate native4096 device session with the exact CUDA bitwise guard.

The inherited session still controls checkpoint restoration, independent byte
anchors, resource admission, complete-source batching, numerical forwards and
all entry/intermediate/exit boundaries. Only its full-value comparison changes:
CUDA uses integer views plus reference finiteness; CPU/opt-out preserves the
numeric reference path. The original session and its producers remain intact.

Native Leanstral ownership and production admission remain closed. Explicit
synthetic untrained controls alone may run. This implementation declares no
native CUDA, timing, training, production or proof qualification.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import threading

from . import legal_span_4096_device_inference as inherited
from . import owned_tensor_bitwise_guard as bitwise_guard


SCHEMA = inherited.SCHEMA
PROFILE = "native-4096-source-span-batched-device-bitwise-float32-cpu-decisions/v1"
CUDA_GRU_PROFILE = inherited.CUDA_GRU_PROFILE
DIMENSION = inherited.DIMENSION
_require = inherited._require


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256()
_BASE_CLASS_AT_IMPORT = inherited.DeviceLeanstral4096SpanSession
_BASE_IMPLEMENTATION_AT_IMPORT = inherited._implementation
_BASE_AT_IMPORT = _BASE_IMPLEMENTATION_AT_IMPORT()
_BASE_SOURCE_AT_IMPORT = hashlib.sha256(Path(inherited.__file__).read_bytes()).hexdigest()
_BASE_METHOD_NAMES = (
    "__init__", "_poll", "_pure_check", "_check", "_policy", "_lease_binding",
    "_reference_byte_plan", "_reference_state_bytes", "_check_reference_anchor",
    "_operation", "checkpoint", "describe", "_description", "_admit_batch_memory",
    "_decision", "decode_formal_logic", "infer", "_synchronize", "close", "__enter__", "__exit__",
)
_BASE_METHODS_AT_IMPORT = {name: getattr(_BASE_CLASS_AT_IMPORT, name) for name in _BASE_METHOD_NAMES}
_BASE_DESCRIPTION_AT_IMPORT = _BASE_CLASS_AT_IMPORT._description
_BASE_PROFILE_AT_IMPORT = inherited.PROFILE
_BASE_SCHEMA_AT_IMPORT = inherited.SCHEMA
_BASE_GRU_PROFILE_AT_IMPORT = inherited.CUDA_GRU_PROFILE
_BITWISE_CHECK_AT_IMPORT = bitwise_guard.check_owned_tensor_bytes
_BITWISE_IMPLEMENTATION_AT_IMPORT = bitwise_guard.inference_implementation
_BITWISE_AT_IMPORT = _BITWISE_IMPLEMENTATION_AT_IMPORT()
_BITWISE_SOURCE_AT_IMPORT = hashlib.sha256(Path(bitwise_guard.__file__).read_bytes()).hexdigest()


def _implementation():
    _require(_source_sha256() == _SOURCE_AT_IMPORT,
             "native4096 bitwise session source changed since import")
    _require(inherited.DeviceLeanstral4096SpanSession is _BASE_CLASS_AT_IMPORT
             and inherited._implementation is _BASE_IMPLEMENTATION_AT_IMPORT
             and hashlib.sha256(Path(inherited.__file__).read_bytes()).hexdigest() == _BASE_SOURCE_AT_IMPORT
             and all(getattr(_BASE_CLASS_AT_IMPORT, name) is method
                     for name, method in _BASE_METHODS_AT_IMPORT.items())
             and inherited.PROFILE == _BASE_PROFILE_AT_IMPORT
             and inherited.SCHEMA == _BASE_SCHEMA_AT_IMPORT
             and inherited.CUDA_GRU_PROFILE == _BASE_GRU_PROFILE_AT_IMPORT
             and _BASE_IMPLEMENTATION_AT_IMPORT() == _BASE_AT_IMPORT,
             "native4096 inherited session class, methods or source changed")
    _require(bitwise_guard.check_owned_tensor_bytes is _BITWISE_CHECK_AT_IMPORT
             and bitwise_guard.inference_implementation is _BITWISE_IMPLEMENTATION_AT_IMPORT
             and hashlib.sha256(Path(bitwise_guard.__file__).read_bytes()).hexdigest() == _BITWISE_SOURCE_AT_IMPORT
             and _BITWISE_IMPLEMENTATION_AT_IMPORT() == _BITWISE_AT_IMPORT,
             "native4096 bitwise comparison implementation changed")
    return {"schema": "native-4096-bitwise-device-session-implementation/v1",
            "source_sha256": _SOURCE_AT_IMPORT,
            "inherited_session_source_sha256": _BASE_SOURCE_AT_IMPORT,
            "inherited_session_implementation": deepcopy(_BASE_AT_IMPORT),
            "inherited_methods_identity_checked": list(_BASE_METHOD_NAMES),
            "bitwise_guard_source_sha256": _BITWISE_SOURCE_AT_IMPORT,
            "bitwise_guard_implementation": deepcopy(_BITWISE_AT_IMPORT),
            "boundary_consolidation_performed": False,
            "native_cuda_qualified": False, "performance_qualified": False,
            "production_admission": False, "proof_authority": False}


class BitwiseDeviceLeanstral4096SpanSession(_BASE_CLASS_AT_IMPORT):
    """Inherited native4096 session with a separately pinned value comparator."""

    def _pure_check(self):
        _implementation()
        # Retain the inherited complete custody checks in their original order.
        # The only comparison substitution is the separately pinned helper.
        _require(not self._closed and os.getpid() == self._process and threading.get_ident() == self._thread,
                 "native4096 device session is closed or foreign")
        self._guard.check(self._checkpoint)
        self._policy_guard.check(self._policy())
        _require(self._lease is self._lease_identity and self._lease._scheduler is self._scheduler,
                 "private native4096 resource lease binding changed")
        self._lease_guard.check(self._lease_binding())
        torch, model = self._torch, self._model
        if self._device.startswith("cuda:"):
            _require(inherited.resident._cuda_float32_policy(torch) == self._precision_policy,
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
        state = dict(model.state_dict())
        _require(set(state) == set(self._reference) and all(
            str(value.device) == self._device and value.dtype == torch.float32
            and value.shape == self._reference[name].shape and value.data_ptr() == self._pointers[name]
            for name, value in state.items()), "private native4096 model tensors changed")
        self._reference_anchor_receipt = self._check_reference_anchor()
        self._value_guard_receipt = _BITWISE_CHECK_AT_IMPORT(torch, state, self._reference,
                                                           optimized=self._optimized)
        _require(all(not module.training and not module._forward_hooks and not module._forward_pre_hooks
                     and not module._backward_hooks for module in model.modules())
                 and all(not parameter.requires_grad and parameter.grad is None for parameter in model.parameters()),
                 "private native4096 modes/hooks/gradients changed")
        _require(not torch.nn.modules.module._global_forward_hooks
                 and not torch.nn.modules.module._global_forward_pre_hooks
                 and not torch.nn.modules.module._global_backward_hooks,
                 "global Torch hooks are incompatible with private native4096 inference")

    def _description(self):
        implementation = _implementation()
        description = _BASE_DESCRIPTION_AT_IMPORT(self)
        # The CPU opt-out retains its inherited numerical profile; the new
        # session identity and comparator remain explicit in both modes.
        description["inherited_profile_id"] = description["profile_id"]
        description["session_profile_id"] = PROFILE
        if self._optimized:
            description["profile_id"] = PROFILE
        description["strict_cuda_gru_profile_id"] = CUDA_GRU_PROFILE
        description["owned_tensor_guard_path"] = (
            "cuda_int32_views_with_reference_finiteness" if self._optimized and self._device.startswith("cuda:")
            else "inherited_numeric_reference_checks")
        description["boundary_consolidation_performed"] = False
        description["native_bitwise_session_cuda_qualified"] = False
        description["bitwise_session_performance_qualified"] = False
        description["implementation"] = implementation
        return description


__all__ = ["BitwiseDeviceLeanstral4096SpanSession", "SCHEMA", "PROFILE", "CUDA_GRU_PROFILE", "DIMENSION"]
