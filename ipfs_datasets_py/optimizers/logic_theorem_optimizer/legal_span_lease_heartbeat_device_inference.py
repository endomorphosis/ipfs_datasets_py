"""Separate authenticated lease polling for held 768D and 4096D span heads.

All inherited constructors, numerical kernels, checkpoint/input/receipt guards,
byte anchors, tensor comparisons and cleanup remain intact. Every inherited
boundary and per-row poll freshly authenticates its own shared lease and live
ancestry. Durable renewal occurs only when the fixed helper cadence is due.

The held span polls already use readonly cancellation checks, with no inline
renewal. This candidate adds authenticated currentness; it makes no claim to
eliminate their durable writes or improve speed. Cached input is unchanged.
The 4096D synthetic and trusted native-owner gates remain inherited unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from sys import _getframe as _GETFRAME
import os
import threading
import time

from . import legal_span_device_bitwise_inference as bitwise768
from . import legal_span_4096_bitwise_device_inference_v2 as bitwise4096
from . import authenticated_lease_heartbeat as heartbeat

PROFILE_768 = "native-768-owned-bitwise-lease-heartbeat/v1"
PROFILE_4096 = "native-4096-owned-bitwise-lease-heartbeat/v1"
SCHEMA = "span-authenticated-lease-heartbeat-device-implementation/v1"
_BASE_768 = bitwise768.DeviceBitwiseDimensionalSpanSession
_BASE_4096 = bitwise4096.BitwiseDeviceLeanstral4096SpanSession
_DESCRIPTION_768, _DESCRIPTION_4096 = _BASE_768._description, _BASE_4096._description
_HEARTBEAT = heartbeat.AuthenticatedLeaseHeartbeat
_HEARTBEAT_IMPLEMENTATION = heartbeat.inference_implementation
_GETPID, _GETIDENT, _MONOTONIC = os.getpid, threading.get_ident, time.monotonic
_require = bitwise768._require
_HEARTBEAT_FIELDS = ("_lease", "_scheduler", "_lease_binding", "_scheduler_binding", "_config_binding",
                     "_ancestry", "_renewal_fraction", "_interval", "_process", "_thread")
_LEASE_AUTH_ERRORS = (heartbeat.resources.LeaseCancelledError, heartbeat.resources.LeaseNotFoundError,
                      heartbeat.resources.SchedulerStateError)
_SOURCE_PINS = ((bitwise768, "d1c12eb54ca8c17c9815ed20db9237c86876361ac3d72fa30ce2d470b0fccf91"),
    (bitwise4096, "14678654b927d0b6910fda6a8c82961978a9e7ebc29334aaae6cb2320abc5dc3"),
    (heartbeat, "584ddf7f8274481940ff48648da5947d08ba42534cf46157da3591a4ac634b30"))
_BASE_MODULES = (bitwise768, bitwise768.resident, bitwise768.batched, bitwise4096, bitwise4096.inherited)


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
_HEARTBEAT_AT_IMPORT = deepcopy(_HEARTBEAT_IMPLEMENTATION())
_BASE_FUNCTIONS = tuple((module, name, _fingerprint(value)) for module in _BASE_MODULES
    for name, value in vars(module).items() if getattr(value, "__code__", None) is not None)
_BASE_CLASSES = tuple((module, name, value) for module in _BASE_MODULES for name, value in vars(module).items()
    if isinstance(value, type) and value.__module__ == module.__name__)
_BASE_METHODS = tuple((owner, name, _fingerprint(value)) for _, _, owner in _BASE_CLASSES
    for name, value in vars(owner).items() if isinstance(value, property) or getattr(value, "__code__", None) is not None) + tuple(
    (owner, name, _fingerprint(getattr(owner, name))) for owner in (_BASE_768, _BASE_4096)
    for name in ("__init__", "_poll", "_check", "_pure_check", "_description", "_decision", "_operation",
                 "decode_formal_logic", "infer", "close", "_reference_byte_plan", "_reference_state_bytes", "_check_reference_anchor"))
_BASE_METADATA = tuple((module, name, getattr(module, name)) for module in _BASE_MODULES
    for name in ("SCHEMA", "PROFILE", "CUDA_GRU_PROFILE", "DIMENSION") if hasattr(module, name))
_HEARTBEAT_FUNCTIONS = tuple((name, _fingerprint(value)) for name, value in vars(heartbeat).items()
    if getattr(value, "__code__", None) is not None and getattr(value, "__module__", None) == heartbeat.__name__)
_HEARTBEAT_CLASSES = tuple((name, value) for name, value in vars(heartbeat).items()
    if isinstance(value, type) and value.__module__ == heartbeat.__name__)
_HEARTBEAT_METHODS = tuple((owner, name, _fingerprint(value)) for _, owner in _HEARTBEAT_CLASSES
    for name, value in vars(owner).items() if isinstance(value, property) or getattr(value, "__code__", None) is not None)
_OWN_FUNCTIONS = _OWN_ALIASES = _OWN_METHODS = _OWN_TYPES = ()


def _check_bindings():
    """Check own dispatch; inherited full source schedules remain untouched."""
    _require(all(_same(globals().get(name), expected) for name, expected in _OWN_FUNCTIONS),
             "span heartbeat owner helper function changed")
    _require(all(_same(globals().get(name), expected) for name, expected in _OWN_ALIASES),
             "span heartbeat owner alias or profile changed")
    _require(_source_sha256() == _SOURCE_AT_IMPORT
             and all(hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == digest
                     for module, digest in _SOURCE_PINS), "span heartbeat or pinned owner/helper source changed")
    _require(bitwise768.DeviceBitwiseDimensionalSpanSession is _BASE_768
             and bitwise4096.BitwiseDeviceLeanstral4096SpanSession is _BASE_4096
             and all(_same(getattr(module, name), expected) for module, name, expected in _BASE_FUNCTIONS)
             and all(getattr(module, name) is expected for module, name, expected in _BASE_CLASSES)
             and all(_same(getattr(owner, name), expected) for owner, name, expected in _BASE_METHODS)
             and all(type(getattr(module, name)) is type(value) and getattr(module, name) == value
                     for module, name, value in _BASE_METADATA),
             "span heartbeat inherited class, function or method binding changed")
    _require(heartbeat.AuthenticatedLeaseHeartbeat is _HEARTBEAT
             and all(_same(getattr(heartbeat, name), expected) for name, expected in _HEARTBEAT_FUNCTIONS)
             and all(getattr(heartbeat, name) is expected for name, expected in _HEARTBEAT_CLASSES)
             and all(_same(getattr(owner, name), expected) for owner, name, expected in _HEARTBEAT_METHODS),
             "span heartbeat helper class, function or method binding changed")
    _require(all(_same(getattr(owner, name), expected) for owner, name, expected in _OWN_METHODS)
             and all(globals().get(name) is owner for _, name, owner, _, _ in _OWN_TYPES),
             "span heartbeat own class or method binding changed")


def _owner_binding(owner):
    for dimension, _, cls, constructor, methods in _OWN_TYPES:
        if type(owner) is cls:
            for name, expected in methods:
                if isinstance(expected[0], property):
                    # Resolve the class descriptor without evaluating a model
                    # property before the inherited constructor initializes it.
                    actual = getattr(cls, name)
                else:
                    bound = getattr(owner, name, None)
                    actual = getattr(bound, "__func__", bound)
                _require(_same(actual, expected), "span heartbeat private method resolution changed")
            return dimension, constructor
    raise ValueError("exact 768D or 4096D span heartbeat owner required")


def _check_snapshot(owner, snapshot):
    _require(type(snapshot) is tuple and len(snapshot) == 1 + len(_HEARTBEAT_FIELDS)
             and owner._heartbeat_owner is snapshot[0] and type(snapshot[0]) is _HEARTBEAT
             and owner._heartbeat_snapshot is snapshot and owner._heartbeat_snapshot_identity is snapshot
             and all(getattr(snapshot[0], name) is value for name, value in zip(_HEARTBEAT_FIELDS, snapshot[1:]))
             and snapshot[0]._lease is owner._lease and owner._lease is owner._lease_identity
             and snapshot[0]._scheduler is owner._scheduler
             and type(snapshot[0]._renewal_fraction) is float and snapshot[0]._renewal_fraction == 1 / 3,
             "span heartbeat helper object or immutable snapshot changed")


def _initialize(owner, cancel_event):
    _check_bindings()
    _owner_binding(owner)
    _require(not hasattr(owner, "_heartbeat_owner"), "span heartbeat owner cannot be reinitialized")
    owner._heartbeat_owner = owner._heartbeat_snapshot = owner._heartbeat_snapshot_identity = None
    owner._heartbeat_cancel_identity = cancel_event


def inference_implementation():
    """Describe a capability, without claiming an owned live currentness poll."""
    _check_bindings()
    current = _HEARTBEAT_IMPLEMENTATION()
    _require(current == _HEARTBEAT_AT_IMPORT, "span heartbeat checked helper implementation differs")
    return {"schema": SCHEMA, "source_sha256": _SOURCE_AT_IMPORT,
        "profiles": {"768": PROFILE_768, "4096": PROFILE_4096},
        "inherited_owner_source_sha256": {str(module.DIMENSION): digest for module, digest in _SOURCE_PINS[:2]},
        "authenticated_lease_heartbeat_implementation": current,
        "change_scope": "all_existing_boundary_and_per_row_polls_only_inherited_kernels_and_input_guards_unchanged",
        "baseline_poll_scope": "readonly_cancelled_checks_no_inline_renewal",
        "currentness_policy": "fresh_authenticated_read_each_inherited_poll_durable_own_renewal_only_when_due",
        "identity_policy": "source_bound_parent_constructor_helper_and_immutable_snapshot_with_local_callback_anchor",
        "source_verification_success_cached": False, "boundary_consolidation_performed": False,
        "cached_input_substitution_performed": False, "existing_scheduler_or_auto_heartbeat_modified": False,
        "existing_selected_route_changed": False, "performance_qualified": False,
        "native_leanstral_outputs_qualified": False, "trained4096_qualification_established": False,
        "production_qualified": False, "proof_authority": False, "execution_attestation": False}


class _LeaseHeartbeatMixin:
    def _poll(self):
        _check_bindings()
        dimension, constructor = _owner_binding(self)
        _require(not self._closed and _GETPID() == self._process and _GETIDENT() == self._thread,
                 "span heartbeat session is closed or foreign process/thread")
        _require(self._cancel is self._heartbeat_cancel_identity, "span heartbeat cancellation owner changed")
        lease, snapshot = self._lease, self._heartbeat_snapshot
        if snapshot is None:
            _require(self._heartbeat_owner is None and self._heartbeat_snapshot_identity is None,
                     "span heartbeat helper binding snapshot changed")
            frame = _GETFRAME(1)
            try:
                _require(frame.f_code is constructor and frame.f_locals.get("self") is self,
                         "span heartbeat bootstrap outside inherited constructor")
            finally:
                del frame
            if lease is not None:
                _require(lease is self._lease_identity and lease._scheduler is self._scheduler,
                         "span heartbeat constructor lease binding changed")
                helper = _HEARTBEAT(lease)
                snapshot = (helper, *(getattr(helper, name) for name in _HEARTBEAT_FIELDS))
                self._heartbeat_owner = helper
                self._heartbeat_snapshot = self._heartbeat_snapshot_identity = snapshot
        if snapshot is not None:
            _check_snapshot(self, snapshot)
        try:
            cancelled = bool(self._cancel.is_set()) if self._cancel is not None else False
        finally:
            if self._lease is not lease:
                self._lease = lease
                raise ValueError("span heartbeat owner or callback lease changed")
        if cancelled:
            raise RuntimeError(str(dimension) + "D device inference cancelled")
        if _MONOTONIC() >= self._deadline:
            raise TimeoutError(str(dimension) + "D device inference deadline exceeded")
        _require(not self._closed and _GETPID() == self._process and _GETIDENT() == self._thread
                 and self._cancel is self._heartbeat_cancel_identity,
                 "span heartbeat owner or callback cancellation changed")
        _check_bindings()
        _owner_binding(self)
        if snapshot is None:
            _require(self._heartbeat_owner is None and self._heartbeat_snapshot is None
                     and self._heartbeat_snapshot_identity is None,
                     "span heartbeat pre-admission callback changed helper")
            return
        _check_snapshot(self, snapshot)
        try:
            renewed = snapshot[0].check()
        except _LEASE_AUTH_ERRORS as error:
            raise RuntimeError(str(dimension) + "D device lease revoked or expired") from error
        _require(type(renewed) is bool, "span heartbeat check must return a renewed boolean")
        _check_snapshot(self, snapshot)
        self._heartbeat_renewed_at_last_poll = renewed

    def _heartbeat_description(self, description):
        _check_bindings()
        dimension, _ = _owner_binding(self)
        _check_snapshot(self, self._heartbeat_snapshot)
        _require(type(self._heartbeat_renewed_at_last_poll) is bool, "completed owned span heartbeat poll required")
        profile = PROFILE_768 if dimension == 768 else PROFILE_4096
        description["lease_heartbeat_inherited_profile_id"] = description["profile_id"]
        description["lease_heartbeat_profile_id"] = description["session_profile_id"] = profile
        if self._optimized:
            description["profile_id"] = profile
        description["lease_heartbeat_implementation"] = inference_implementation()
        description["authenticated_lease_heartbeat_object_and_snapshot_identities_checked"] = True
        description["lease_currentness"] = {
            "schema": "span-authenticated-lease-currentness/v1",
            "authenticated_read_completed_at_last_poll": True,
            "renewed_at_last_completed_poll": self._heartbeat_renewed_at_last_poll,
            "observation_scope": "most_recent_completed_owned_poll_only_no_whole_call_or_execution_attestation"}
        return description


class DeviceBitwiseDimensionalSpanSession(_LeaseHeartbeatMixin, _BASE_768):
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, optimized=True,
                 scheduler=None, parent_lease=None, cancel_event=None,
                 admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=0):
        _initialize(self, cancel_event)
        super().__init__(checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256, optimized=optimized,
            scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
            admission_timeout_seconds=admission_timeout_seconds, max_seconds=max_seconds,
            memory_mb=memory_mb, gpu_memory_mb=gpu_memory_mb, unified_memory_mb=unified_memory_mb)
        _check_snapshot(self, self._heartbeat_snapshot)

    def _description(self):
        _check_bindings()
        _owner_binding(self)
        return self._heartbeat_description(_DESCRIPTION_768(self))


class BitwiseDeviceLeanstral4096SpanSession(_LeaseHeartbeatMixin, _BASE_4096):
    def __init__(self, checkpoint, *, expected_checkpoint_sha256, optimized=True,
                 synthetic_unreceipted=False, scheduler=None, parent_lease=None,
                 cancel_event=None, admission_timeout_seconds=30, max_seconds=120,
                 memory_mb=1024, gpu_memory_mb=256, unified_memory_mb=0):
        _initialize(self, cancel_event)
        super().__init__(checkpoint, expected_checkpoint_sha256=expected_checkpoint_sha256, optimized=optimized,
            synthetic_unreceipted=synthetic_unreceipted, scheduler=scheduler, parent_lease=parent_lease,
            cancel_event=cancel_event, admission_timeout_seconds=admission_timeout_seconds, max_seconds=max_seconds,
            memory_mb=memory_mb, gpu_memory_mb=gpu_memory_mb, unified_memory_mb=unified_memory_mb)
        _check_snapshot(self, self._heartbeat_snapshot)

    def _description(self):
        _check_bindings()
        _owner_binding(self)
        return self._heartbeat_description(_DESCRIPTION_4096(self))


_METHOD_NAMES = ("__init__", "_poll", "_check", "_pure_check", "_description", "_heartbeat_description", "_decision",
    "_operation", "_lease_binding", "_reference_byte_plan", "_reference_state_bytes", "_check_reference_anchor",
    "_admit_batch_memory", "decode_formal_logic", "infer", "describe", "checkpoint", "_synchronize", "close",
    "__enter__", "__exit__")
_OWN_TYPES = tuple((dimension, name, cls, base.__init__.__code__,
    tuple((method, _fingerprint(getattr(cls, method))) for method in _METHOD_NAMES))
    for dimension, name, cls, base in ((768, "DeviceBitwiseDimensionalSpanSession", DeviceBitwiseDimensionalSpanSession, _BASE_768),
        (4096, "BitwiseDeviceLeanstral4096SpanSession", BitwiseDeviceLeanstral4096SpanSession, _BASE_4096)))
_OWN_METHODS = tuple((owner, name, _fingerprint(value))
    for owner in (_LeaseHeartbeatMixin, DeviceBitwiseDimensionalSpanSession, BitwiseDeviceLeanstral4096SpanSession)
    for name, value in vars(owner).items() if isinstance(value, property) or getattr(value, "__code__", None) is not None)
_OWN_FUNCTIONS = tuple((name, _fingerprint(globals()[name])) for name in ("_require", "_source_sha256", "_fingerprint",
    "_same", "_check_bindings", "_owner_binding", "_check_snapshot", "_initialize", "inference_implementation"))
_OWN_ALIASES = tuple((name, _fingerprint(globals()[name])) for name in ("bitwise768", "bitwise4096", "heartbeat",
    "_BASE_768", "_BASE_4096", "_DESCRIPTION_768", "_DESCRIPTION_4096", "_HEARTBEAT", "_HEARTBEAT_IMPLEMENTATION",
    "_HEARTBEAT_FIELDS", "_SOURCE_PINS", "_BASE_MODULES", "_GETFRAME", "_GETPID", "_GETIDENT", "_MONOTONIC",
    "_LEASE_AUTH_ERRORS", "_LeaseHeartbeatMixin", "_OWN_TYPES", "_METHOD_NAMES", "PROFILE_768", "PROFILE_4096", "SCHEMA",
    "deepcopy", "Path", "hashlib"))

__all__ = ["DeviceBitwiseDimensionalSpanSession", "BitwiseDeviceLeanstral4096SpanSession",
           "PROFILE_768", "PROFILE_4096", "SCHEMA", "inference_implementation"]
