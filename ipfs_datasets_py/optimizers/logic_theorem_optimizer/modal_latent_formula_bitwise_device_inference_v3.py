"""Separate per-call input snapshots for the unchanged owned formula heads.

The qualified v2 constructor, checkpoint/policy/lease guards, independent byte
anchor and numerical kernels remain intact. Each public call retains all four
fresh source/currentness/cancellation boundaries. Only the ephemeral rows and
projection-id or latents snapshot uses InputContentGuard; these inputs require
no persistent canonical JSON digest. Existing plain finite input validation
still runs before the snapshot. No source result is cached across boundaries.

Construction retains original Adam restoration/validation and executes no fit
or optimizer step. This distinct candidate profile grants no performance,
semantic, native CUDA, proof or production qualification.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

from . import modal_latent_formula_bitwise_device_inference_v2 as v2
from . import input_content_guard as input_guard

PROFILE = "modal-latent-formula-bitwise-owned-device-input-snapshot-float32/v3"
SCHEMA = "modal-latent-formula-inference/v1"
LINEAGES = {"legacy_hub_v1": 8, "current_legal_v2": 384}
_COORDINATOR_SOURCE_SHA256 = "ebc7f8242ec3a4852be4c025b4ef818bc48e74add7634935ec403e1bd3c6dfb9"

v1 = v2.v1
_require = v2._require
_strict_json = v2._strict_json
_BASE_CLASS = v2.BitwiseDeviceLatentFormulaDecoder
_PARENT_PURE_CHECK = v2._PARENT_PURE_CHECK
_DEVICE_INFER = v2._DEVICE_INFER
_PROJECT = v2._PROJECT
_CHECKPOINT_GUARD = v2._CHECKPOINT_GUARD
_NATIVE_IMPLEMENTATION = v2._NATIVE_IMPLEMENTATION
_BASE_IMPLEMENTATION = v2._BASE_IMPLEMENTATION
_BITWISE_IMPLEMENTATION = v2._BITWISE_IMPLEMENTATION
_GETFRAME = v2._GETFRAME
_COORDINATOR_CHECK_BINDINGS = v2._check_bindings
_COORDINATOR_BASE_IMPLEMENTATION = v2._base_current_implementation
_COORDINATOR_RECEIPT = v2._implementation_receipt
_INPUT_GUARD = input_guard.InputContentGuard
_INPUT_IMPLEMENTATION = input_guard.inference_implementation


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _fingerprint(value):
    if isinstance(value, property):
        return (value, value.fget, value.fget.__code__)
    return (value, getattr(value, "__code__", None))


def _same(value, expected):
    actual = _fingerprint(value)
    return len(actual) == len(expected) and all(left is right for left, right in zip(actual, expected))


_SOURCE_AT_IMPORT = _source_sha256()
_INPUT_SOURCE_AT_IMPORT = hashlib.sha256(Path(input_guard.__file__).read_bytes()).hexdigest()
_INPUT_IMPLEMENTATION_AT_IMPORT = deepcopy(_INPUT_IMPLEMENTATION())
_COORDINATOR_FUNCTIONS_AT_IMPORT = tuple(v2._OWN_FUNCTIONS_AT_IMPORT)
_COORDINATOR_ALIASES_AT_IMPORT = tuple(v2._OWN_ALIASES_AT_IMPORT)
_COORDINATOR_METHODS_AT_IMPORT = tuple(v2._OWN_METHODS_AT_IMPORT) + tuple(v2._RESOLVED_METHODS_AT_IMPORT)
_INPUT_FUNCTIONS_AT_IMPORT = tuple((name, _fingerprint(value)) for name, value in vars(input_guard).items()
    if getattr(value, "__code__", None) is not None and getattr(value, "__module__", None) == input_guard.__name__)
_INPUT_CLASSES_AT_IMPORT = tuple((name, value) for name, value in vars(input_guard).items()
    if isinstance(value, type) and getattr(value, "__module__", None) == input_guard.__name__)
_INPUT_METHODS_AT_IMPORT = tuple((owner, name, _fingerprint(value))
    for _, owner in _INPUT_CLASSES_AT_IMPORT for name, value in vars(owner).items()
    if isinstance(value, property) or getattr(value, "__code__", None) is not None)
_PROFILE_AT_IMPORT, _SCHEMA_AT_IMPORT = PROFILE, SCHEMA
_LINEAGES_AT_IMPORT = tuple(LINEAGES.items())
_OWN_CLASS_AT_IMPORT = None
_OWN_FUNCTIONS_AT_IMPORT = ()
_OWN_ALIASES_AT_IMPORT = ()
_OWN_METHODS_AT_IMPORT = ()
_RESOLVED_METHODS_AT_IMPORT = ()


def _check_bindings():
    """Freshly verify the unchanged coordinator and new input producer."""
    _require(all(_same(globals().get(name), expected) for name, expected in _OWN_FUNCTIONS_AT_IMPORT),
             "formula v3 owner helper function changed")
    _require(all(_same(globals().get(name), expected) for name, expected in _OWN_ALIASES_AT_IMPORT),
             "formula v3 live owner module, kernel or guard alias changed")
    _require(type(PROFILE) is str and PROFILE == _PROFILE_AT_IMPORT
             and type(SCHEMA) is str and SCHEMA == _SCHEMA_AT_IMPORT
             and type(LINEAGES) is dict and tuple(LINEAGES.items()) == _LINEAGES_AT_IMPORT
             and all(type(name) is str and type(dimension) is int for name, dimension in LINEAGES.items()),
             "formula v3 profile, schema or exact lineage declaration changed")
    _require(_source_sha256() == _SOURCE_AT_IMPORT
             and hashlib.sha256(Path(v2.__file__).read_bytes()).hexdigest() == _COORDINATOR_SOURCE_SHA256
             and hashlib.sha256(Path(input_guard.__file__).read_bytes()).hexdigest() == _INPUT_SOURCE_AT_IMPORT,
             "formula v3, qualified v2 or input guard source changed")
    _require(v2.BitwiseDeviceLatentFormulaDecoder is _BASE_CLASS
             and all(_same(getattr(v2, name), expected) for name, expected in _COORDINATOR_FUNCTIONS_AT_IMPORT)
             and all(_same(getattr(v2, name), expected) for name, expected in _COORDINATOR_ALIASES_AT_IMPORT)
             and all(_same(getattr(_BASE_CLASS, name), expected) for name, expected in _COORDINATOR_METHODS_AT_IMPORT),
             "formula v3 qualified coordinator binding changed")
    _COORDINATOR_CHECK_BINDINGS()
    _require(input_guard.InputContentGuard is _INPUT_GUARD
             and all(_same(getattr(input_guard, name), expected) for name, expected in _INPUT_FUNCTIONS_AT_IMPORT)
             and all(getattr(input_guard, name) is expected for name, expected in _INPUT_CLASSES_AT_IMPORT)
             and all(_same(getattr(owner, name), expected) for owner, name, expected in _INPUT_METHODS_AT_IMPORT),
             "formula v3 input guard class, method or function binding changed")
    current_input_implementation = _INPUT_IMPLEMENTATION()
    _require(current_input_implementation == _INPUT_IMPLEMENTATION_AT_IMPORT,
             "formula v3 input guard implementation differs")
    if _OWN_CLASS_AT_IMPORT is not None:
        _require(BitwiseDeviceLatentFormulaDecoder is _OWN_CLASS_AT_IMPORT
                 and all(_same(getattr(_OWN_CLASS_AT_IMPORT, name), expected) for name, expected in _OWN_METHODS_AT_IMPORT)
                 and all(_same(getattr(_OWN_CLASS_AT_IMPORT, name), expected) for name, expected in _RESOLVED_METHODS_AT_IMPORT),
                 "formula v3 own or inherited method resolution changed")
    return current_input_implementation


def _base_current_implementation():
    return _COORDINATOR_BASE_IMPLEMENTATION()


def _check_input_guard_identity(guard, binding):
    _require(type(binding) is tuple and len(binding) == 4 and guard is binding[0]
             and type(guard) is _INPUT_GUARD and guard._reference is binding[1]
             and guard._canonical_bytes is binding[2] and type(binding[2]) in (bytes, type(None))
             and guard._use_fast_comparison is binding[3] and type(binding[3]) is bool,
             "formula v3 per-call input guard object or immutable snapshot changed")


def _implementation_receipt(native_implementation, base_implementation, comparison_implementation,
                            input_implementation):
    _require(input_implementation == _INPUT_IMPLEMENTATION_AT_IMPORT,
             "formula v3 checked input guard implementation differs")
    receipt = _COORDINATOR_RECEIPT(native_implementation, base_implementation, comparison_implementation)
    receipt.update(schema="modal-latent-formula-bitwise-device-implementation/v3", profile_id=PROFILE,
        source_sha256=_SOURCE_AT_IMPORT, inherited_coordinator_source_sha256=_COORDINATOR_SOURCE_SHA256,
        per_call_input_guard_implementation=deepcopy(input_implementation),
        input_content_guard_scope="per_call_rows_projection_id_or_latents_only_checkpoint_policy_lease_guards_unchanged",
        input_content_guard_identity_policy="fixed_per_call_guard_object_and_immutable_root_snapshot",
        input_guard_digest_required=False)
    return receipt


def inference_implementation():
    input_implementation = _check_bindings()
    return _implementation_receipt(_NATIVE_IMPLEMENTATION(), _base_current_implementation(),
                                   _BITWISE_IMPLEMENTATION(), input_implementation)


class BitwiseDeviceLatentFormulaDecoder(_BASE_CLASS):
    """Qualified v2 custody with only ephemeral input snapshot substitution."""
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, expected_binding=None,
                 optimized=True, scheduler=None, parent_lease=None, cancel_event=None,
                 admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=512, gpu_memory_mb=256, unified_memory_mb=0):
        _check_bindings()
        super().__init__(checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256,
            expected_binding=expected_binding, optimized=optimized, scheduler=scheduler,
            parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, max_seconds=max_seconds,
            memory_mb=memory_mb, gpu_memory_mb=gpu_memory_mb, unified_memory_mb=unified_memory_mb)

    def _check(self, *, materialize_receipt=True):
        # Keep the direct parent-constructor -> _check -> guard-identity chain.
        # The inherited immutable ownership checker admits no mutable bootstrap
        # flag and its exact source-bound constructor-frame test remains intact.
        self._poll()
        _require(type(materialize_receipt) is bool, "formula v3 receipt selection must be boolean")
        input_implementation = _check_bindings()
        self._check_guard_identities()
        base_implementation = _base_current_implementation()
        _PARENT_PURE_CHECK(self)
        if not materialize_receipt:
            return None
        implementation = _implementation_receipt(self._checkpoint["implementation"], base_implementation,
                                                   self._value_guard_receipt["implementation"], input_implementation)
        return {**implementation, "device": self._device, "cuda_selected": self._device.startswith("cuda:"),
            "optimized": self._optimized, "dimension": self._binding["dimension"], "lineage_id": self._binding["lineage_id"],
            "stored_checkpoint_device": "cpu", "dtype": "float32", "owned_admission": True,
            "owned_content_guard_object_and_snapshot_identities_checked": self._owned_guard_bindings is not None,
            "reference_byte_currentness": deepcopy(self._reference_anchor_receipt),
            "owned_tensor_currentness": deepcopy(self._value_guard_receipt),
            "cpu_model_byte_currentness_checked": self._device == "cpu",
            "resource_lease": self._lease.to_dict(), "adam_restoration_performed": True,
            "adam_restore_count": 1, "optimizer_steps_executed": 0, "training_executed": False,
            "deadline_scope": "cooperative_around_inherited_calls_not_native_preemption"}

    def _infer(self, rows, *, projection_id, include_projection):
        with self._operation():
            self._check(materialize_receipt=False)
            _require(type(projection_id) is str and 0 < len(projection_id) <= 256, "bounded projection id required")
            _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 128, "one to 128 inference rows required")
            _strict_json(list(rows))
            current_inputs = _INPUT_GUARD({"rows": list(rows), "projection_id": projection_id})
            input_binding = (current_inputs, current_inputs._reference, current_inputs._canonical_bytes,
                             current_inputs._use_fast_comparison)
            _check_input_guard_identity(current_inputs, input_binding)
            try:
                result = _DEVICE_INFER(self, rows, projection_id=projection_id, include_projection=include_projection)
                self._synchronize()
                self._check(materialize_receipt=False)
                _check_input_guard_identity(current_inputs, input_binding)
                current_inputs.check({"rows": list(rows), "projection_id": projection_id}, message="checkpoint content changed")
                report = result[0] if include_projection else result
                report["inference_implementation"]["public_receipt_boundary_scope"] = (
                    "inherited_exit_receipt_with_fresh_outer_exit_guard_and_no_outer_receipt")
                report["inference_implementation"]["per_call_input_content_checked"] = True
                return result
            finally:
                self._synchronize()

    def project(self, latents):
        with self._operation():
            self._check(materialize_receipt=False)
            _require(type(latents) in (list, tuple) and 1 <= len(latents) <= 128, "one to 128 vectors required")
            _strict_json(list(latents))
            current_inputs = _INPUT_GUARD({"latents": list(latents)})
            input_binding = (current_inputs, current_inputs._reference, current_inputs._canonical_bytes,
                             current_inputs._use_fast_comparison)
            _check_input_guard_identity(current_inputs, input_binding)
            try:
                result = _PROJECT(self, latents)
                self._synchronize()
                self._check(materialize_receipt=False)
                _check_input_guard_identity(current_inputs, input_binding)
                current_inputs.check({"latents": list(latents)}, message="checkpoint content changed")
                return result
            finally:
                self._synchronize()


_OWN_CLASS_AT_IMPORT = BitwiseDeviceLatentFormulaDecoder
_OWN_FUNCTIONS_AT_IMPORT = tuple((name, _fingerprint(globals()[name])) for name in
    ("_require", "_strict_json", "_source_sha256", "_fingerprint", "_same", "_check_bindings",
     "_base_current_implementation", "_check_input_guard_identity", "_implementation_receipt", "inference_implementation"))
_OWN_ALIASES_AT_IMPORT = tuple((name, _fingerprint(globals()[name])) for name in
    ("v2", "v1", "input_guard", "_BASE_CLASS", "_PARENT_PURE_CHECK", "_DEVICE_INFER", "_PROJECT",
     "_CHECKPOINT_GUARD", "_NATIVE_IMPLEMENTATION", "_BASE_IMPLEMENTATION", "_BITWISE_IMPLEMENTATION",
     "_GETFRAME", "_COORDINATOR_CHECK_BINDINGS", "_COORDINATOR_BASE_IMPLEMENTATION", "_COORDINATOR_RECEIPT",
     "_INPUT_GUARD", "_INPUT_IMPLEMENTATION", "_COORDINATOR_SOURCE_SHA256", "deepcopy", "hashlib", "Path"))
_OWN_METHODS_AT_IMPORT = tuple((name, _fingerprint(getattr(_OWN_CLASS_AT_IMPORT, name))) for name in
                             ("__init__", "_check", "_infer", "project"))
_RESOLVED_METHODS_AT_IMPORT = tuple((name, _fingerprint(getattr(_OWN_CLASS_AT_IMPORT, name))) for name in
    ("_check_guard_identities", "_poll", "_lease_binding", "_policy", "_byte_plan", "_storage_layout", "_state_bytes",
     "_check_reference_anchor", "_check_hooks", "_pure_check", "_operation", "infer", "infer_with_projection",
     "describe", "inference_implementation", "checkpoint", "codec", "checkpoint_sha256", "_synchronize",
     "close", "__enter__", "__exit__"))

__all__ = ["BitwiseDeviceLatentFormulaDecoder", "SCHEMA", "PROFILE", "LINEAGES", "inference_implementation"]
