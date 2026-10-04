"""Separate native4096 bitwise session without duplicate source verification.

The inherited public boundaries verify all original implementation sources.
Each full-value boundary additionally verifies this module and callable/class
bindings, then the bitwise helper verifies its own source before comparison.
No verification success, timestamp or tensor revision is cached as authority.

Checkpoint restoration, byte anchors, resource admission, numerical execution,
native-owner refusal and all original guard boundaries remain unchanged. Only
the comparator and its separately declared implementation profile differ.
This implementation declares no native CUDA, performance or proof qualification.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import threading

from . import legal_span_4096_device_inference as inherited
from . import owned_tensor_bitwise_guard as bitwise_guard


SCHEMA = inherited.SCHEMA
PROFILE = "native-4096-source-span-batched-device-bitwise-float32-cpu-decisions/v2"
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
_BITWISE_SOURCE_AT_IMPORT = _BITWISE_AT_IMPORT["source_sha256"]


def _check_bindings():
    """Check current own bytes and callable custody without building receipts.

    The original ``_check`` verifies original transitive sources immediately
    before dispatching ``_pure_check``. Direct private ``_pure_check`` never
    provided that transitive verification in the original contract. The real
    bitwise comparison verifies current helper bytes before any tensor views.
    """
    _require(_source_sha256() == _SOURCE_AT_IMPORT,
             "native4096 bitwise v2 session source changed since import")
    _require(inherited.DeviceLeanstral4096SpanSession is _BASE_CLASS_AT_IMPORT
             and inherited._implementation is _BASE_IMPLEMENTATION_AT_IMPORT
             and all(getattr(_BASE_CLASS_AT_IMPORT, name) is method
                     for name, method in _BASE_METHODS_AT_IMPORT.items())
             and inherited.PROFILE == _BASE_PROFILE_AT_IMPORT
             and inherited.SCHEMA == _BASE_SCHEMA_AT_IMPORT
             and inherited.CUDA_GRU_PROFILE == _BASE_GRU_PROFILE_AT_IMPORT,
             "native4096 inherited session class, methods or implementation binding changed")
    _require(bitwise_guard.check_owned_tensor_bytes is _BITWISE_CHECK_AT_IMPORT
             and bitwise_guard.inference_implementation is _BITWISE_IMPLEMENTATION_AT_IMPORT,
             "native4096 bitwise comparison implementation binding changed")


def _implementation_receipt(original_implementation, comparison_implementation):
    # Both dictionaries are fresh results of their actual current source
    # verifiers. Reuse them without an extra verification or nested deepcopy.
    _require(original_implementation == _BASE_AT_IMPORT
             and comparison_implementation == _BITWISE_AT_IMPORT,
             "native4096 bitwise v2 verified implementation differs")
    return {"schema": "native-4096-bitwise-device-session-implementation/v2",
            "source_sha256": _SOURCE_AT_IMPORT,
            "inherited_session_source_sha256": _BASE_SOURCE_AT_IMPORT,
            "inherited_session_implementation": original_implementation,
            "inherited_methods_identity_checked": list(_BASE_METHOD_NAMES),
            "bitwise_guard_source_sha256": _BITWISE_SOURCE_AT_IMPORT,
            "bitwise_guard_implementation": comparison_implementation,
            "original_public_source_verification": "inherited_check_before_pure_check",
            "duplicate_transitive_verification_in_pure_check": False,
            "source_verification_success_cached": False,
            "boundary_consolidation_performed": False,
            "native_cuda_qualified": False, "performance_qualified": False,
            "production_admission": False, "proof_authority": False}


def _implementation():
    """Independently verify all current sources and produce a fresh receipt."""
    _check_bindings()
    return _implementation_receipt(_BASE_IMPLEMENTATION_AT_IMPORT(),
                                   _BITWISE_IMPLEMENTATION_AT_IMPORT())


class BitwiseDeviceLeanstral4096SpanSession(_BASE_CLASS_AT_IMPORT):
    """Original session custody with a separately verified bitwise comparator."""

    def _pure_check(self):
        _check_bindings()
        # Original custody clauses and order are unchanged below. The actual
        # comparator verifies its helper source before operating on tensors.
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
        _check_bindings()
        # Original description performs its complete source verification once.
        description = _BASE_DESCRIPTION_AT_IMPORT(self)
        implementation = _implementation_receipt(description["implementation"],
                                                  _BITWISE_IMPLEMENTATION_AT_IMPORT())
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
