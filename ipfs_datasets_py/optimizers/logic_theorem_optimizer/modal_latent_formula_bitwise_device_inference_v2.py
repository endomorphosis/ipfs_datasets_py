"""Four-boundary formula custody with separate verification and receipts.

The qualified v1 constructor and numerical/custody checker remain unchanged.
Each public inference retains its outer and inherited entry/exit checks. Each
boundary freshly verifies sources, checkpoint, lease, cancellation, deadline,
model, reference bytes and tensor values. Only the two outer discarded receipt
assemblies are suppressed; no successful source or value check is cached.

The unchanged v1 pure checker verifies native checkpoint provenance once per
boundary. Receipt metadata is assembled only after that check and the actual
bitwise comparator return. CUDA GRU storage metadata and immutable CPU-origin
anchors retain their v1 separation. Construction still restores Adam once for
original validation, without a training fit or optimizer step.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from sys import _getframe as _GETFRAME

from . import modal_latent_formula_bitwise_device_inference as v1

PROFILE = "modal-latent-formula-bitwise-owned-device-float32/v2"
SCHEMA = "modal-latent-formula-inference/v1"
LINEAGES = {"legacy_hub_v1": 8, "current_legal_v2": 384}

_require = v1._require
_strict_json = v1._strict_json
_BASE_CLASS = v1.BitwiseDeviceLatentFormulaDecoder
_PARENT_PURE_CHECK = _BASE_CLASS._pure_check
_DEVICE_INFER = v1._DEVICE_INFER
_PROJECT = v1._PROJECT
_CHECKPOINT_GUARD = v1._CHECKPOINT_GUARD
_NATIVE_IMPLEMENTATION = v1._NATIVE_IMPLEMENTATION
_BASE_IMPLEMENTATION = v1._BASE_IMPLEMENTATION
_BITWISE_IMPLEMENTATION = v1._BITWISE_IMPLEMENTATION


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
_PARENT_SOURCE_AT_IMPORT = hashlib.sha256(Path(v1.__file__).read_bytes()).hexdigest()
_SOURCE_MODULES = tuple(v1._SOURCES.items())
_PARENT_ALIASES = tuple((name, getattr(v1, name)) for name in (
    "native", "batched", "inherited", "bitwise_guard", "checkpoint_guard", "resources",
    "_require", "_BASE_CLASS", "_NATIVE_CLASS", "_BATCH_CLASS", "_DEVICE_TORCH", "_RESTORE",
    "_DEVICE_INFER", "_PROJECT", "_CHECKPOINT_GUARD", "_SCHEDULER", "_RESOURCE_LEASE",
    "_BITWISE_CHECK", "_NATIVE_IMPLEMENTATION", "_BASE_IMPLEMENTATION", "_BITWISE_IMPLEMENTATION"))
_PARENT_HELPERS = tuple((name, expected) for name, expected in v1._OWN_FUNCTIONS_AT_IMPORT.items())
_PARENT_CLASSES = tuple((module, name, v1._CLASSES_AT_IMPORT[module])
                        for module, name in v1._CLASS_NAMES.items())
_PARENT_FUNCTIONS = tuple((module, name, expected)
                         for module, entries in v1._FUNCTIONS_AT_IMPORT.items()
                         for name, expected in entries.items())
_PARENT_METHODS = tuple((owner, name, expected)
                       for owner, entries in v1._METHODS_AT_IMPORT.items()
                       for name, expected in entries.items()) + tuple(
                           (_BASE_CLASS, name, expected) for name, expected in v1._OWN_METHODS_AT_IMPORT.items())
_MATCHES_AT_IMPORT = _fingerprint(_CHECKPOINT_GUARD.matches)
_GUARD_SHA256_AT_IMPORT = _fingerprint(_CHECKPOINT_GUARD.sha256)
_PARENT_PURE_AT_IMPORT = _fingerprint(_PARENT_PURE_CHECK)
_PARENT_INIT_AT_IMPORT = _fingerprint(_BASE_CLASS.__init__)
_NATIVE_AT_IMPORT = deepcopy(v1._NATIVE_AT_IMPORT)
_BASE_AT_IMPORT = deepcopy(v1._BASE_AT_IMPORT)
_BITWISE_AT_IMPORT = deepcopy(v1._BITWISE_AT_IMPORT)
_FALSE_AT_IMPORT = deepcopy(v1._FALSE_AT_IMPORT)
_PROJECTION_AT_IMPORT = v1._PROJECTION_AT_IMPORT
_CHECKPOINT_SCHEMA_AT_IMPORT = v1._CHECKPOINT_SCHEMA_AT_IMPORT
_CODEC_AT_IMPORT = v1._CODEC_AT_IMPORT
_PROFILE_AT_IMPORT = PROFILE
_SCHEMA_AT_IMPORT = SCHEMA
_LINEAGES_AT_IMPORT = tuple((name, dimension) for name, dimension in LINEAGES.items())
_OWN_CLASS_AT_IMPORT = None
_OWN_FUNCTIONS_AT_IMPORT = ()
_OWN_METHODS_AT_IMPORT = ()
_RESOLVED_METHODS_AT_IMPORT = ()
_OWN_ALIASES_AT_IMPORT = ()


def _check_bindings():
    """Verify every current binding without constructing a v1 receipt."""
    _require(all(_same(globals().get(name), expected) for name, expected in _OWN_FUNCTIONS_AT_IMPORT),
             "formula v2 owner helper function changed")
    _require(all(_same(globals().get(name), expected) for name, expected in _OWN_ALIASES_AT_IMPORT),
             "formula v2 live owner module, kernel or guard alias changed")
    _require(type(PROFILE) is str and PROFILE == _PROFILE_AT_IMPORT
             and type(SCHEMA) is str and SCHEMA == _SCHEMA_AT_IMPORT
             and type(LINEAGES) is dict and tuple(LINEAGES.items()) == _LINEAGES_AT_IMPORT
             and all(type(name) is str and type(dimension) is int for name, dimension in LINEAGES.items()),
             "formula v2 profile, schema or exact lineage declaration changed")
    _require(_source_sha256() == _SOURCE_AT_IMPORT
             and hashlib.sha256(Path(v1.__file__).read_bytes()).hexdigest() == _PARENT_SOURCE_AT_IMPORT,
             "formula v2 or qualified v1 owner source changed")
    _require(all(hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == expected
                 for module, expected in _SOURCE_MODULES), "formula v2 inherited dependency source changed")
    _require(v1.BitwiseDeviceLatentFormulaDecoder is _BASE_CLASS
             and all(getattr(v1, name) is expected for name, expected in _PARENT_ALIASES)
             and all(_same(getattr(v1, name), expected) for name, expected in _PARENT_HELPERS),
             "formula v2 qualified owner class or helper binding changed")
    _require(all(getattr(module, name) is expected for module, name, expected in _PARENT_CLASSES)
             and v1.inherited._DeviceTorch is v1._DEVICE_TORCH
             and v1.resources.ResourceLease is v1._RESOURCE_LEASE
             and all(_same(getattr(module, name), expected) for module, name, expected in _PARENT_FUNCTIONS)
             and all(_same(getattr(owner, name), expected) for owner, name, expected in _PARENT_METHODS),
             "formula v2 inherited class, method or function binding changed")
    _require(_same(_CHECKPOINT_GUARD.matches, _MATCHES_AT_IMPORT),
             "formula v2 checkpoint comparator matches method changed")
    _require(_same(_CHECKPOINT_GUARD.sha256, _GUARD_SHA256_AT_IMPORT),
             "formula v2 checkpoint guard SHA256 property changed")
    _require(_same(_BASE_CLASS._pure_check, _PARENT_PURE_AT_IMPORT)
             and _PARENT_PURE_CHECK is _PARENT_PURE_AT_IMPORT[0],
             "formula v2 original pure checker binding changed")
    _require(v1.native.FALSE == _FALSE_AT_IMPORT and v1.native.PROJECTION_ID == _PROJECTION_AT_IMPORT
             and v1.native.SCHEMA == _CHECKPOINT_SCHEMA_AT_IMPORT and v1.native.codec_module is _CODEC_AT_IMPORT
             and v1.batched.learning is v1.native and v1.inherited.batched is v1.batched,
             "formula v2 original lineage, grammar or inference binding changed")
    if _OWN_CLASS_AT_IMPORT is not None:
        _require(BitwiseDeviceLatentFormulaDecoder is _OWN_CLASS_AT_IMPORT
                 and all(_same(getattr(_OWN_CLASS_AT_IMPORT, name), expected)
                         for name, expected in _OWN_METHODS_AT_IMPORT)
                 and all(_same(getattr(_OWN_CLASS_AT_IMPORT, name), expected)
                         for name, expected in _RESOLVED_METHODS_AT_IMPORT),
                 "formula v2 own or inherited method resolution changed")


def _base_current_implementation():
    current = _BASE_IMPLEMENTATION()
    _require(current == _BASE_AT_IMPORT, "formula v2 inherited device implementation changed")
    return current


def _implementation_receipt(native_implementation, base_implementation, comparison_implementation):
    _require(native_implementation == _NATIVE_AT_IMPORT and base_implementation == _BASE_AT_IMPORT
             and comparison_implementation == _BITWISE_AT_IMPORT,
             "formula v2 fresh transitive implementation differs")
    # Native metadata can originate in the guarded private checkpoint. Keep
    # that mutable state private. The two other observations are fresh local
    # dictionaries; a shallow copy isolates the helper receipt's flat fields.
    return {"schema": "modal-latent-formula-bitwise-device-implementation/v2", "profile_id": PROFILE,
        "source_sha256": _SOURCE_AT_IMPORT, "inherited_owner_source_sha256": _PARENT_SOURCE_AT_IMPORT,
        "inherited_device_implementation": base_implementation,
        "native_checkpoint_implementation": deepcopy(native_implementation),
        "bitwise_guard_implementation": dict(comparison_implementation),
        "checkpoint_guard_source_sha256": next(expected for module, expected in _SOURCE_MODULES if module is v1.checkpoint_guard),
        "resource_scheduler_source_sha256": next(expected for module, expected in _SOURCE_MODULES if module is v1.resources),
        "checkpoint_conversion_performed": False, "native_cuda_qualified": False,
        "performance_qualified": False, "semantic_qualification": False,
        "production_admission": False, "proof_authority": False,
        "source_verification_success_cached": False, "boundary_consolidation_performed": False,
        "duplicate_native_source_verification_in_boundary": False,
        "native_source_verifications_per_boundary": 1,
        "outer_discarded_receipt_construction_avoided": True,
        "checkpoint_matches_method_identity_checked": True,
        "owned_content_guard_identity_policy": "fixed_after_source_bound_constructor_guard_creation"}


def inference_implementation():
    """Independently perform fresh source checks for a standalone receipt."""
    _check_bindings()
    return _implementation_receipt(_NATIVE_IMPLEMENTATION(), _base_current_implementation(),
                                   _BITWISE_IMPLEMENTATION())


class BitwiseDeviceLatentFormulaDecoder(_BASE_CLASS):
    """Qualified v1 custody with same-boundary receipt assembly only."""
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, expected_binding=None,
                 optimized=True, scheduler=None, parent_lease=None, cancel_event=None,
                 admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=512, gpu_memory_mb=256, unified_memory_mb=0):
        _check_bindings()
        _require(not hasattr(self, "_owned_guard_bindings"), "formula v2 owner cannot be reinitialized")
        # The inherited constructor creates the guards from source-bound code
        # and the external checkpoint SHA before its first self._check call.
        self._owned_guard_bindings = self._owned_guard_bindings_identity = None
        super().__init__(checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256,
            expected_binding=expected_binding, optimized=optimized, scheduler=scheduler,
            parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, max_seconds=max_seconds,
            memory_mb=memory_mb, gpu_memory_mb=gpu_memory_mb, unified_memory_mb=unified_memory_mb)
        bindings = tuple((name, guard, guard._canonical_bytes, guard._reference, guard.sha256, guard._use_fast_comparison)
                         for name in ("_checkpoint_guard", "_policy_guard", "_lease_guard")
                         for guard in (getattr(self, name),))
        self._owned_guard_bindings = self._owned_guard_bindings_identity = bindings

    def _check_guard_identities(self):
        bindings = self._owned_guard_bindings
        if bindings is None:
            _require(self._owned_guard_bindings_identity is None,
                     "formula v2 owner guard binding snapshot changed")
            # Only the exact source-bound inherited constructor may bootstrap
            # this first check. Resetting both markers after construction must
            # never reopen ownership. The call chain is this method -> _check
            # -> qualified parent __init__; inspect only that bounded frame.
            constructor_frame = _GETFRAME(2)
            try:
                _require(constructor_frame.f_code is _PARENT_INIT_AT_IMPORT[1]
                         and constructor_frame.f_locals.get("self") is self,
                         "formula v2 owner guard bootstrap outside inherited constructor")
            finally:
                del constructor_frame
        else:
            _require(type(bindings) is tuple and bindings is self._owned_guard_bindings_identity
                     and len(bindings) == 3, "formula v2 owner guard binding snapshot changed")
            for name, guard, canonical, reference, digest, fast in bindings:
                _require(getattr(self, name) is guard and type(guard) is _CHECKPOINT_GUARD
                         and guard._canonical_bytes is canonical and type(canonical) is bytes
                         and guard._reference is reference and guard.sha256 == digest
                         and guard._use_fast_comparison is fast,
                         "formula v2 owner guard object or immutable snapshot changed")
        _require(type(self._checkpoint_guard) is _CHECKPOINT_GUARD
                 and self._checkpoint_guard.sha256 == self._checkpoint_sha256,
                 "formula v2 owner checkpoint guard SHA256 differs from admitted checkpoint")

    def _check(self, *, materialize_receipt=True):
        self._poll()
        _require(type(materialize_receipt) is bool, "formula v2 receipt selection must be boolean")
        _check_bindings()
        self._check_guard_identities()
        base_implementation = _base_current_implementation()
        # This exact qualified body performs the one fresh native source
        # verification at its original checkpoint-provenance position, and
        # the actual helper verifies its own source before comparing tensors.
        _PARENT_PURE_CHECK(self)
        if not materialize_receipt:
            return None
        implementation = _implementation_receipt(self._checkpoint["implementation"], base_implementation,
                                                   self._value_guard_receipt["implementation"])
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
            input_guard = _CHECKPOINT_GUARD({"rows": list(rows), "projection_id": projection_id})
            try:
                result = _DEVICE_INFER(self, rows, projection_id=projection_id, include_projection=include_projection)
                self._synchronize()
                self._check(materialize_receipt=False)
                input_guard.check({"rows": list(rows), "projection_id": projection_id})
                report = result[0] if include_projection else result
                report["inference_implementation"]["public_receipt_boundary_scope"] = (
                    "inherited_exit_receipt_with_fresh_outer_exit_guard_and_no_outer_receipt")
                return result
            finally:
                self._synchronize()

    def project(self, latents):
        with self._operation():
            self._check(materialize_receipt=False)
            _require(type(latents) in (list, tuple) and 1 <= len(latents) <= 128, "one to 128 vectors required")
            _strict_json(list(latents))
            input_guard = _CHECKPOINT_GUARD({"latents": list(latents)})
            try:
                result = _PROJECT(self, latents)
                self._synchronize()
                self._check(materialize_receipt=False)
                input_guard.check({"latents": list(latents)})
                return result
            finally:
                self._synchronize()


_OWN_CLASS_AT_IMPORT = BitwiseDeviceLatentFormulaDecoder
_OWN_FUNCTIONS_AT_IMPORT = tuple((name, _fingerprint(globals()[name])) for name in
    ("_require", "_strict_json", "_source_sha256", "_fingerprint", "_same", "_check_bindings",
     "_base_current_implementation", "_implementation_receipt", "inference_implementation"))
_OWN_ALIASES_AT_IMPORT = tuple((name, _fingerprint(globals()[name])) for name in
    ("v1", "_BASE_CLASS", "_PARENT_PURE_CHECK", "_DEVICE_INFER", "_PROJECT", "_CHECKPOINT_GUARD",
     "_NATIVE_IMPLEMENTATION", "_BASE_IMPLEMENTATION", "_BITWISE_IMPLEMENTATION", "_SOURCE_MODULES", "deepcopy", "_GETFRAME"))
_OWN_METHODS_AT_IMPORT = tuple((name, _fingerprint(getattr(_OWN_CLASS_AT_IMPORT, name))) for name in
                             ("__init__", "_check_guard_identities", "_check", "_infer", "project"))
_RESOLVED_METHODS_AT_IMPORT = tuple((name, _fingerprint(getattr(_OWN_CLASS_AT_IMPORT, name))) for name in
    ("_poll", "_lease_binding", "_policy", "_byte_plan", "_storage_layout", "_state_bytes", "_check_reference_anchor",
     "_check_hooks", "_pure_check", "_operation", "infer", "infer_with_projection", "describe", "inference_implementation",
     "checkpoint", "codec", "checkpoint_sha256", "_synchronize", "close", "__enter__", "__exit__"))

__all__ = ["BitwiseDeviceLatentFormulaDecoder", "SCHEMA", "PROFILE", "LINEAGES", "inference_implementation"]
