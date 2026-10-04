"""Four fresh formula boundaries with authenticated, cadence-based renewal.

The held v2 constructor, numerical kernels, checkpoint/input/policy guards,
independent byte anchor, tensor comparison and resource close remain intact.
Only the owned lease poll changes: every boundary authenticates the current
shared record and complete live ancestry, while durable renewal occurs only
when the unchanged lease's initial TTL cadence requires it. A valid nondue
read returns False from the helper and remains a successful currentness poll.

Construction still performs the original single Adam restoration/validation.
This separate candidate makes no timing, CUDA, semantic or production claim.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

from . import modal_latent_formula_bitwise_device_inference_v2 as v2
from . import authenticated_lease_heartbeat as heartbeat

PROFILE = "modal-latent-formula-bitwise-owned-device-lease-heartbeat-float32/v1"
SCHEMA = "modal-latent-formula-inference/v1"
LINEAGES = {"legacy_hub_v1": 8, "current_legal_v2": 384}
_COORDINATOR_SOURCE_SHA256 = "ebc7f8242ec3a4852be4c025b4ef818bc48e74add7634935ec403e1bd3c6dfb9"

v1 = v2.v1
_require, _strict_json = v2._require, v2._strict_json
_BASE_CLASS = v2.BitwiseDeviceLatentFormulaDecoder
_PARENT_PURE_CHECK = v2._PARENT_PURE_CHECK
_DEVICE_INFER, _PROJECT = v2._DEVICE_INFER, v2._PROJECT
_CHECKPOINT_GUARD = v2._CHECKPOINT_GUARD
_NATIVE_IMPLEMENTATION = v2._NATIVE_IMPLEMENTATION
_BASE_IMPLEMENTATION = v2._BASE_IMPLEMENTATION
_BITWISE_IMPLEMENTATION = v2._BITWISE_IMPLEMENTATION
_GETFRAME = v2._GETFRAME
_GETPID, _GETIDENT, _MONOTONIC = v1.os.getpid, v1.threading.get_ident, v1.time.monotonic
_COORDINATOR_CHECK_BINDINGS = v2._check_bindings
_COORDINATOR_BASE_IMPLEMENTATION = v2._base_current_implementation
_COORDINATOR_RECEIPT = v2._implementation_receipt
_HEARTBEAT = heartbeat.AuthenticatedLeaseHeartbeat
_HEARTBEAT_IMPLEMENTATION = heartbeat.inference_implementation
_LEASE_AUTH_ERRORS = (heartbeat.resources.LeaseCancelledError, heartbeat.resources.LeaseNotFoundError,
                      heartbeat.resources.SchedulerStateError)
_HEARTBEAT_FIELDS = ("_lease", "_scheduler", "_lease_binding", "_scheduler_binding", "_config_binding",
                     "_ancestry", "_renewal_fraction", "_interval", "_process", "_thread")
_CONSTRUCTOR_CODE = v2._PARENT_INIT_AT_IMPORT[1]


def _source_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _fingerprint(value):
    function = value.fget if isinstance(value, property) else getattr(value, "__func__", value)
    keywords = getattr(function, "__kwdefaults__", None)
    return (value, function, getattr(function, "__code__", None), getattr(function, "__defaults__", None),
            keywords, tuple(keywords.items()) if keywords else ())


def _same(value, expected):
    actual = _fingerprint(value)
    return all(left is right for left, right in zip(actual[:5], expected[:5])) and actual[5] == expected[5]


_SOURCE_AT_IMPORT = _source_sha256()
_HEARTBEAT_SOURCE_AT_IMPORT = hashlib.sha256(Path(heartbeat.__file__).read_bytes()).hexdigest()
_HEARTBEAT_IMPLEMENTATION_AT_IMPORT = deepcopy(_HEARTBEAT_IMPLEMENTATION())
_COORDINATOR_FUNCTIONS_AT_IMPORT = tuple((name, _fingerprint(getattr(v2, name)))
                                      for name, _ in v2._OWN_FUNCTIONS_AT_IMPORT)
_COORDINATOR_ALIASES_AT_IMPORT = tuple((name, _fingerprint(getattr(v2, name)))
                                    for name, _ in v2._OWN_ALIASES_AT_IMPORT)
_COORDINATOR_METHODS_AT_IMPORT = tuple((name, _fingerprint(getattr(_BASE_CLASS, name)))
    for name, _ in tuple(v2._OWN_METHODS_AT_IMPORT) + tuple(v2._RESOLVED_METHODS_AT_IMPORT))
_HEARTBEAT_FUNCTIONS_AT_IMPORT = tuple((name, _fingerprint(value)) for name, value in vars(heartbeat).items()
    if getattr(value, "__code__", None) is not None and getattr(value, "__module__", None) == heartbeat.__name__)
_HEARTBEAT_CLASSES_AT_IMPORT = tuple((name, value) for name, value in vars(heartbeat).items()
    if isinstance(value, type) and getattr(value, "__module__", None) == heartbeat.__name__)
_HEARTBEAT_METHODS_AT_IMPORT = tuple((owner, name, _fingerprint(value))
    for _, owner in _HEARTBEAT_CLASSES_AT_IMPORT for name, value in vars(owner).items()
    if isinstance(value, property) or getattr(value, "__code__", None) is not None)
_PROFILE_AT_IMPORT, _SCHEMA_AT_IMPORT = PROFILE, SCHEMA
_LINEAGES_AT_IMPORT = tuple(LINEAGES.items())
_OWN_CLASS_AT_IMPORT = None
_OWN_FUNCTIONS_AT_IMPORT = ()
_OWN_ALIASES_AT_IMPORT = ()
_OWN_METHODS_AT_IMPORT = ()
_RESOLVED_METHODS_AT_IMPORT = ()


def _check_poll_bindings():
    """Check dispatch identities before and after the external callback.

    The helper performs its complete fresh dependency/source verification
    during check(). The full inherited coordinator tree is still verified
    at every _check boundary, at its original checkpoint/model position.
    """
    _require(all(_same(globals().get(name), expected) for name, expected in _OWN_FUNCTIONS_AT_IMPORT),
             "formula heartbeat owner helper function changed")
    _require(all(_same(globals().get(name), expected) for name, expected in _OWN_ALIASES_AT_IMPORT),
             "formula heartbeat live owner module, kernel or guard alias changed")
    _require(type(PROFILE) is str and PROFILE == _PROFILE_AT_IMPORT
             and type(SCHEMA) is str and SCHEMA == _SCHEMA_AT_IMPORT
             and type(LINEAGES) is dict and tuple(LINEAGES.items()) == _LINEAGES_AT_IMPORT
             and all(type(name) is str and type(dimension) is int for name, dimension in LINEAGES.items()),
             "formula heartbeat profile, schema or exact lineage declaration changed")
    _require(_source_sha256() == _SOURCE_AT_IMPORT
             and hashlib.sha256(Path(v2.__file__).read_bytes()).hexdigest() == _COORDINATOR_SOURCE_SHA256
             and hashlib.sha256(Path(heartbeat.__file__).read_bytes()).hexdigest() == _HEARTBEAT_SOURCE_AT_IMPORT,
             "formula heartbeat, qualified v2 or heartbeat helper source changed")
    _require(heartbeat.AuthenticatedLeaseHeartbeat is _HEARTBEAT
             and all(_same(getattr(heartbeat, name), expected) for name, expected in _HEARTBEAT_FUNCTIONS_AT_IMPORT)
             and all(getattr(heartbeat, name) is expected for name, expected in _HEARTBEAT_CLASSES_AT_IMPORT)
             and all(_same(getattr(owner, name), expected) for owner, name, expected in _HEARTBEAT_METHODS_AT_IMPORT),
             "formula heartbeat helper class, method or function binding changed")
    if _OWN_CLASS_AT_IMPORT is not None:
        _require(BitwiseDeviceLatentFormulaDecoder is _OWN_CLASS_AT_IMPORT
                 and all(_same(getattr(_OWN_CLASS_AT_IMPORT, name), expected) for name, expected in _OWN_METHODS_AT_IMPORT)
                 and all(_same(getattr(_OWN_CLASS_AT_IMPORT, name), expected) for name, expected in _RESOLVED_METHODS_AT_IMPORT),
                 "formula heartbeat own or inherited method resolution changed")


def _check_bindings():
    _check_poll_bindings()
    # Use independent captured fingerprints, not a mutable live comparator
    # from the inherited module, before invoking its original full verifier.
    _require(v2.BitwiseDeviceLatentFormulaDecoder is _BASE_CLASS
             and all(_same(getattr(v2, name), expected) for name, expected in _COORDINATOR_FUNCTIONS_AT_IMPORT)
             and all(_same(getattr(v2, name), expected) for name, expected in _COORDINATOR_ALIASES_AT_IMPORT)
             and all(_same(getattr(_BASE_CLASS, name), expected) for name, expected in _COORDINATOR_METHODS_AT_IMPORT),
             "formula heartbeat qualified coordinator binding changed")
    _COORDINATOR_CHECK_BINDINGS()
    current = _HEARTBEAT_IMPLEMENTATION()
    _require(current == _HEARTBEAT_IMPLEMENTATION_AT_IMPORT, "formula heartbeat implementation differs")
    return current


def _base_current_implementation():
    return _COORDINATOR_BASE_IMPLEMENTATION()


def _implementation_receipt(native_implementation, base_implementation, comparison_implementation,
                            heartbeat_implementation):
    _require(heartbeat_implementation == _HEARTBEAT_IMPLEMENTATION_AT_IMPORT,
             "formula heartbeat checked helper implementation differs")
    receipt = _COORDINATOR_RECEIPT(native_implementation, base_implementation, comparison_implementation)
    receipt.update(schema="modal-latent-formula-lease-heartbeat-device-implementation/v1", profile_id=PROFILE,
        source_sha256=_SOURCE_AT_IMPORT, inherited_coordinator_source_sha256=_COORDINATOR_SOURCE_SHA256,
        authenticated_lease_heartbeat_implementation=deepcopy(heartbeat_implementation),
        lease_currentness_policy="fresh_authenticated_read_each_boundary_durable_own_renewal_only_when_due",
        lease_heartbeat_identity_policy="source_bound_constructor_owned_helper_and_immutable_snapshots",
        lease_currentness_success_cached=False, input_guard_substitution_performed=False,
        existing_scheduler_or_auto_heartbeat_modified=False)
    return receipt


def inference_implementation():
    current = _check_bindings()
    return _implementation_receipt(_NATIVE_IMPLEMENTATION(), _base_current_implementation(),
                                   _BITWISE_IMPLEMENTATION(), current)


def _check_heartbeat_snapshot(owner, snapshot):
    _require(type(snapshot) is tuple and len(snapshot) == 1 + len(_HEARTBEAT_FIELDS)
             and owner._heartbeat_owner is snapshot[0] and type(snapshot[0]) is _HEARTBEAT
             and owner._heartbeat_snapshot is snapshot and owner._heartbeat_snapshot_identity is snapshot
             and all(getattr(snapshot[0], name) is value for name, value in zip(_HEARTBEAT_FIELDS, snapshot[1:]))
             and snapshot[0]._lease is owner._lease and owner._lease is owner._lease_identity
             and snapshot[0]._scheduler is owner._scheduler
             and type(snapshot[0]._renewal_fraction) is float and snapshot[0]._renewal_fraction == 1 / 3,
             "formula heartbeat helper object or immutable snapshot changed")


class BitwiseDeviceLatentFormulaDecoder(_BASE_CLASS):
    """Held v2 formula custody with four fresh authenticated lease polls."""
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, expected_binding=None,
                 optimized=True, scheduler=None, parent_lease=None, cancel_event=None,
                 admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=512, gpu_memory_mb=256, unified_memory_mb=0):
        _check_bindings()
        _require(not hasattr(self, "_heartbeat_owner"), "formula heartbeat owner cannot be reinitialized")
        self._heartbeat_owner = self._heartbeat_snapshot = self._heartbeat_snapshot_identity = None
        super().__init__(checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256,
            expected_binding=expected_binding, optimized=optimized, scheduler=scheduler,
            parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, max_seconds=max_seconds,
            memory_mb=memory_mb, gpu_memory_mb=gpu_memory_mb, unified_memory_mb=unified_memory_mb)
        _check_heartbeat_snapshot(self, self._heartbeat_snapshot)

    def _poll(self):
        _check_poll_bindings()
        _require(_GETPID() == self._process and _GETIDENT() == self._thread and not self._closed,
                 "formula owner process/thread changed or closed")
        _require(self._cancel is self._cancel_identity, "formula cancellation owner changed")
        lease, snapshot = self._lease, self._heartbeat_snapshot
        if snapshot is None:
            _require(self._heartbeat_owner is None and self._heartbeat_snapshot_identity is None,
                     "formula heartbeat helper binding snapshot changed")
            frame = _GETFRAME(1)
            try:
                _require(frame.f_code is _CONSTRUCTOR_CODE and frame.f_locals.get("self") is self,
                         "formula heartbeat bootstrap outside inherited constructor")
            finally:
                del frame
            if lease is not None:
                _require(lease is self._lease_identity and lease._scheduler is self._scheduler,
                         "formula heartbeat constructor lease binding changed")
                # Authenticate and capture before invoking any external callback.
                helper = _HEARTBEAT(lease)
                snapshot = (helper, *(getattr(helper, name) for name in _HEARTBEAT_FIELDS))
                self._heartbeat_owner = helper
                self._heartbeat_snapshot = self._heartbeat_snapshot_identity = snapshot
        if snapshot is not None:
            _check_heartbeat_snapshot(self, snapshot)
        try:
            cancelled = bool(self._cancel.is_set()) if self._cancel is not None else False
        finally:
            if self._lease is not lease:
                # The inherited constructor closes on error, including a
                # cancellation callback that returns True or itself raises.
                # Cleanup must retain this poll's original child (or None).
                self._lease = lease
                raise ValueError("formula heartbeat owner or callback lease changed")
        if cancelled:
            raise TimeoutError("formula inference cancelled")
        if _MONOTONIC() >= self._deadline:
            raise TimeoutError("formula inference deadline expired")
        # This independent function-local snapshot survives paired replacement
        # of the helper and both mutable owner markers inside a callback.
        _require(_GETPID() == self._process and _GETIDENT() == self._thread
                 and not self._closed and self._cancel is self._cancel_identity,
                 "formula heartbeat owner or callback lease changed")
        _check_poll_bindings()
        if snapshot is None:
            _require(self._heartbeat_owner is None and self._heartbeat_snapshot is None
                     and self._heartbeat_snapshot_identity is None,
                     "formula heartbeat pre-admission callback changed helper")
            return
        _check_heartbeat_snapshot(self, snapshot)
        try:
            renewed = snapshot[0].check()
        except _LEASE_AUTH_ERRORS as error:
            # Preserve the original public refusal category for a lease that
            # became cancelled, missing or corrupt at a currentness boundary.
            raise ValueError("owned formula resource lease expired, cancelled or changed") from error
        _require(type(renewed) is bool, "formula heartbeat check must return a renewed boolean")
        _check_heartbeat_snapshot(self, snapshot)
        # Observation only: every later poll still reads and authenticates
        # shared state; this value never authorizes or suppresses any check.
        self._heartbeat_renewed_at_boundary = renewed

    def _check(self, *, materialize_receipt=True):
        # Keep the direct source-bound v1 constructor -> _check -> identity
        # checker stack. Calling super()._check() adds an invalid bootstrap frame.
        self._poll()
        renewed_at_boundary = self._heartbeat_renewed_at_boundary
        _require(type(materialize_receipt) is bool, "formula heartbeat receipt selection must be boolean")
        current = _check_bindings()
        self._check_guard_identities()
        base_implementation = _base_current_implementation()
        _PARENT_PURE_CHECK(self)
        if not materialize_receipt:
            return None
        implementation = _implementation_receipt(self._checkpoint["implementation"], base_implementation,
                                                   self._value_guard_receipt["implementation"], current)
        return {**implementation, "device": self._device, "cuda_selected": self._device.startswith("cuda:"),
            "optimized": self._optimized, "dimension": self._binding["dimension"], "lineage_id": self._binding["lineage_id"],
            "stored_checkpoint_device": "cpu", "dtype": "float32", "owned_admission": True,
            "owned_content_guard_object_and_snapshot_identities_checked": self._owned_guard_bindings is not None,
            "authenticated_lease_heartbeat_object_and_snapshot_identities_checked": True,
            "lease_currentness": {"schema": "modal-latent-formula-authenticated-lease-currentness/v1",
                "fresh_authenticated_read_completed": True, "renewed_at_receipt_boundary": renewed_at_boundary,
                "boundary_scope": "this_checked_boundary_only_no_whole_call_or_execution_attestation"},
            "reference_byte_currentness": deepcopy(self._reference_anchor_receipt),
            "owned_tensor_currentness": deepcopy(self._value_guard_receipt),
            "cpu_model_byte_currentness_checked": self._device == "cpu",
            "resource_lease": self._lease.to_dict(), "adam_restoration_performed": True,
            "adam_restore_count": 1, "optimizer_steps_executed": 0, "training_executed": False,
            "deadline_scope": "cooperative_around_inherited_calls_not_native_preemption"}


_OWN_CLASS_AT_IMPORT = BitwiseDeviceLatentFormulaDecoder
_OWN_FUNCTIONS_AT_IMPORT = tuple((name, _fingerprint(globals()[name])) for name in
    ("_require", "_strict_json", "_source_sha256", "_fingerprint", "_same", "_check_poll_bindings", "_check_bindings",
     "_base_current_implementation", "_implementation_receipt", "inference_implementation", "_check_heartbeat_snapshot"))
_OWN_ALIASES_AT_IMPORT = tuple((name, _fingerprint(globals()[name])) for name in
    ("v2", "v1", "heartbeat", "_BASE_CLASS", "_PARENT_PURE_CHECK", "_DEVICE_INFER", "_PROJECT", "_CHECKPOINT_GUARD",
     "_NATIVE_IMPLEMENTATION", "_BASE_IMPLEMENTATION", "_BITWISE_IMPLEMENTATION", "_GETFRAME", "_GETPID", "_GETIDENT",
     "_MONOTONIC", "_COORDINATOR_CHECK_BINDINGS", "_COORDINATOR_BASE_IMPLEMENTATION", "_COORDINATOR_RECEIPT",
     "_HEARTBEAT", "_HEARTBEAT_IMPLEMENTATION", "_LEASE_AUTH_ERRORS", "_HEARTBEAT_FIELDS", "_CONSTRUCTOR_CODE", "deepcopy", "hashlib", "Path"))
_OWN_METHODS_AT_IMPORT = tuple((name, _fingerprint(getattr(_OWN_CLASS_AT_IMPORT, name))) for name in
                             ("__init__", "_poll", "_check"))
_RESOLVED_METHODS_AT_IMPORT = tuple((name, _fingerprint(getattr(_OWN_CLASS_AT_IMPORT, name))) for name in
    ("_check_guard_identities", "_infer", "project", "_lease_binding", "_policy", "_byte_plan", "_storage_layout", "_state_bytes",
     "_check_reference_anchor", "_check_hooks", "_pure_check", "_operation", "infer", "infer_with_projection", "describe",
     "inference_implementation", "checkpoint", "codec", "checkpoint_sha256", "_synchronize", "close", "__enter__", "__exit__"))

__all__ = ["BitwiseDeviceLatentFormulaDecoder", "SCHEMA", "PROFILE", "LINEAGES", "inference_implementation"]
