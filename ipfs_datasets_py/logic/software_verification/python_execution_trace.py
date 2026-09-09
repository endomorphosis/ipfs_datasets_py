"""Hermetic Python execution tracing adapter (SAWM-008).

This module is the datasets collection authority for bounded hermetic Python
traces.  It extends SAWM-007 ``ProgramEvent@1`` / ``ExecutionTrace@1`` records
with a runtime adapter that observes admitted call, return, line, exception,
handler, yield, await, and selected external events.

Normative constraints:

* Importing this module never opens a network, socket, installer, subprocess,
  database, repository scan, watcher, or model load.
* Collection binds exact source, code, tree, and environment identities.
* Line and basic-block detail is policy- and cost-bounded.
* Secret and non-semantic fields are redacted before contract construction.
* Private raw trace bodies never enter public records.
* Cancellation emits no accepted transition.  This adapter never persists
  operational acceptance.
* Nondeterministic external effects are explicit observations or unavailable.
* Arbitrary shell tracing is not provided.
"""

from __future__ import annotations

import inspect
import linecache
import opcode
import sys
import threading
import types
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    SECRET_FIELD_MARKERS,
    CompletenessClaim,
    EventKind,
    EventOrigin,
    ExceptionSnapshot,
    ExecutionObservation,
    ExecutionTrace,
    HandlerKind,
    HandlerState,
    HeapBound,
    ObservationStatus,
    PrivacyClass,
    ProgramEvent,
    ProgramExecutionError,
    ProgramExecutionState,
    ProgramLanguage,
    RedactionProfile,
    StackFrameState,
    assemble_execution_trace,
    assemble_program_execution_state,
    observe_program_event,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PYTHON_EXECUTION_TRACER_INTERFACE: Final[str] = "PythonExecutionTracer@1"
TRACE_COLLECTION_POLICY_INTERFACE: Final[str] = "TraceCollectionPolicy@1"
TRACE_REDACTOR_INTERFACE: Final[str] = "TraceRedactor@1"
TRACE_CANCELLATION_INTERFACE: Final[str] = "TraceCancellation@1"
PYTHON_EXECUTION_TRACE_RECORD_INTERFACE: Final[str] = "PythonExecutionTraceRecord@1"
RECORD_PYTHON_EXECUTION_TRACE_INTERFACE: Final[str] = "record_python_execution_trace"
REPLAY_DETERMINISTIC_TRACE_INTERFACE: Final[str] = "replay_deterministic_trace"

PYTHON_TRACE_CAPTURE_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-capture-profile@1"
)
PYTHON_TRACE_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-environment@1"
)
PYTHON_TRACE_TREE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-tree@1"
)
PYTHON_TRACE_CODE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-code-identity@1"
)
PYTHON_TRACE_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-subject@1"
)
PYTHON_TRACE_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-collection-policy@1"
)

ADMITTED_LANGUAGE: Final[str] = "python"
TRACER_VERSION: Final[str] = "1"

# Importing this module must remain a no-effect operation.  Tracing starts
# only through :func:`record_python_execution_trace` / the tracer class.
IMPORT_SIDE_EFFECTS_PERFORMED: Final[bool] = False
IMPORT_NETWORK_OPENED: Final[bool] = False
IMPORT_SOCKET_OPENED: Final[bool] = False
IMPORT_INSTALLER_INVOKED: Final[bool] = False
IMPORT_SUBPROCESS_STARTED: Final[bool] = False
IMPORT_DATABASE_OPENED: Final[bool] = False
IMPORT_REPO_SCAN_PERFORMED: Final[bool] = False
IMPORT_WATCHER_STARTED: Final[bool] = False
IMPORT_MODEL_LOADED: Final[bool] = False

_MODULE_FILE: Final[str] = __file__
_MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
_MAX_SOURCE_BYTES: Final[int] = 1_048_576
_MAX_STACK_WALK: Final[int] = 128

_YIELD_OPNAMES: Final[frozenset[str]] = frozenset(
    {"YIELD_VALUE", "YIELD_FROM", "RETURN_GENERATOR"}
)
_AWAIT_OPNAMES: Final[frozenset[str]] = frozenset(
    {
        "GET_AWAITABLE",
        "SEND",
        "GET_AITER",
        "GET_ANEXT",
        "END_ASYNC_FOR",
        "BEFORE_ASYNC_WITH",
        "YIELD_VALUE",
    }
)
_DENIED_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "socket.connect",
        "socket.connectex",
        "socket.sendto",
        "socket.sendmsg",
        "socket.getaddrinfo",
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "sqlite3.connect",
    }
)
_SECRET_MARKERS: Final[frozenset[str]] = SECRET_FIELD_MARKERS | frozenset(
    {
        "passwd",
        "token",
        "secret_value",
    }
)
_INTERNAL_NAME_PREFIXES: Final[tuple[str, ...]] = ("__",)
_INTERNAL_PATH_MARKERS: Final[tuple[str, ...]] = (
    "software_contracts/",
    "software_verification/python_execution_trace.py",
)


# ---------------------------------------------------------------------------
# Errors and cancellation
# ---------------------------------------------------------------------------


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic tracing is misconfigured or a policy is violated."""


class TraceCancellation(Exception):
    """Stop collection without admitting an accepted transition.

    Raising this from a traced callable, or hitting a collection bound that
    materializes this record, never produces operational acceptance.
    """

    INTERFACE: ClassVar[str] = TRACE_CANCELLATION_INTERFACE

    def __init__(self, reason: str = "cancelled", *, event_count: int = 0) -> None:
        normalized = _nfc(reason, "cancellation reason")
        super().__init__(normalized)
        self.reason = normalized
        self.event_count = _nonneg_int(event_count, "event_count")
        self.accepted_transition = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.INTERFACE,
            "reason": self.reason,
            "event_count": self.event_count,
            "accepted_transition": None,
        }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _nfc(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise PythonExecutionTraceError(f"{name} must be a nonempty trimmed string")
    normalized = unicodedata.normalize("NFC", value)
    if any(not char.isprintable() for char in normalized) or "\x00" in normalized:
        raise PythonExecutionTraceError(f"{name} must be printable NFC text")
    return normalized


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise PythonExecutionTraceError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: object, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise PythonExecutionTraceError(f"{name} must be a nonnegative integer")
    if value > _MAX_SAFE_INTEGER:
        raise PythonExecutionTraceError(f"{name} exceeds the safe JSON integer range")
    return value


def _positive_int(value: object, name: str) -> int:
    result = _nonneg_int(value, name)
    if result < 1:
        raise PythonExecutionTraceError(f"{name} must be positive")
    return result


def _cid(value: object, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as error:
        raise PythonExecutionTraceError(f"{name} must be a valid CID") from error


def _optional_cid(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _string_mapping(value: object, name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PythonExecutionTraceError(f"{name} must be a string mapping")
    items: dict[str, str] = {}
    for key, item in value.items():
        items[_nfc(key, f"{name} key")] = _nfc(item, f"{name} value")
    return dict(sorted(items.items()))


def _event_kinds(values: object) -> tuple[str, ...]:
    if values is None:
        values = (
            EventKind.CALL.value,
            EventKind.RETURN.value,
            EventKind.LINE.value,
            EventKind.RAISE.value,
            EventKind.CATCH.value,
            EventKind.HANDLER.value,
            EventKind.YIELD.value,
            EventKind.AWAIT.value,
            EventKind.EXTERNAL.value,
        )
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise PythonExecutionTraceError("admitted_event_kinds must be a sequence")
    admitted = tuple(_nfc(item, "event kind") for item in values)
    unknown = [item for item in admitted if item not in {kind.value for kind in EventKind}]
    if unknown:
        raise PythonExecutionTraceError(f"unsupported event kind(s): {unknown}")
    if len(admitted) != len(set(admitted)):
        raise PythonExecutionTraceError("admitted_event_kinds must not contain duplicates")
    return admitted


def _privacy(value: object) -> str:
    if isinstance(value, PrivacyClass):
        return value.value
    try:
        return PrivacyClass(value).value
    except (TypeError, ValueError) as error:
        raise PythonExecutionTraceError("privacy_class has an unsupported value") from error


def _secret_name(name: str) -> bool:
    lowered = name.strip().lower().replace("-", "_")
    if lowered in _SECRET_MARKERS:
        return True
    return any(part in _SECRET_MARKERS for part in lowered.split("_") if part)


# ---------------------------------------------------------------------------
# Policy, redactor, and record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Closed collection bounds, admitted event kinds, and isolation policy."""

    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE

    admitted_event_kinds: Sequence[str] = (
        EventKind.CALL.value,
        EventKind.RETURN.value,
        EventKind.LINE.value,
        EventKind.RAISE.value,
        EventKind.CATCH.value,
        EventKind.HANDLER.value,
        EventKind.YIELD.value,
        EventKind.AWAIT.value,
        EventKind.EXTERNAL.value,
    )
    max_events: int = 2_048
    max_line_events: int = 256
    max_stack_depth: int = 32
    max_summary_items: int = 16
    max_text_chars: int = 128
    max_value_depth: int = 2
    deny_network: bool = True
    deny_subprocess: bool = True
    deny_database: bool = True
    include_raw_bodies: bool = False
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL
    tree_cid: str | None = None
    environment_binding: Mapping[str, str] | None = None
    collect_stdlib: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "admitted_event_kinds", _event_kinds(self.admitted_event_kinds))
        object.__setattr__(self, "max_events", _positive_int(self.max_events, "max_events"))
        object.__setattr__(
            self, "max_line_events", _nonneg_int(self.max_line_events, "max_line_events")
        )
        object.__setattr__(
            self, "max_stack_depth", _positive_int(self.max_stack_depth, "max_stack_depth")
        )
        object.__setattr__(
            self,
            "max_summary_items",
            _positive_int(self.max_summary_items, "max_summary_items"),
        )
        object.__setattr__(
            self, "max_text_chars", _positive_int(self.max_text_chars, "max_text_chars")
        )
        object.__setattr__(
            self, "max_value_depth", _positive_int(self.max_value_depth, "max_value_depth")
        )
        object.__setattr__(self, "deny_network", _bool(self.deny_network, "deny_network"))
        object.__setattr__(
            self, "deny_subprocess", _bool(self.deny_subprocess, "deny_subprocess")
        )
        object.__setattr__(self, "deny_database", _bool(self.deny_database, "deny_database"))
        object.__setattr__(
            self, "include_raw_bodies", _bool(self.include_raw_bodies, "include_raw_bodies")
        )
        object.__setattr__(self, "privacy_class", _privacy(self.privacy_class))
        object.__setattr__(self, "tree_cid", _optional_cid(self.tree_cid, "tree_cid"))
        object.__setattr__(
            self,
            "environment_binding",
            MappingProxyType(_string_mapping(self.environment_binding, "environment_binding")),
        )
        object.__setattr__(
            self, "collect_stdlib", _bool(self.collect_stdlib, "collect_stdlib")
        )
        if self.include_raw_bodies and self.privacy_class in {
            PrivacyClass.PUBLIC.value,
            PrivacyClass.INTERNAL.value,
        }:
            raise PythonExecutionTraceError(
                "raw trace bodies remain private and cannot use a public privacy class"
            )

    def admits(self, kind: str) -> bool:
        return kind in self.admitted_event_kinds

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PYTHON_TRACE_POLICY_SCHEMA,
            "admitted_event_kinds": list(self.admitted_event_kinds),
            "max_events": self.max_events,
            "max_line_events": self.max_line_events,
            "max_stack_depth": self.max_stack_depth,
            "max_summary_items": self.max_summary_items,
            "max_text_chars": self.max_text_chars,
            "max_value_depth": self.max_value_depth,
            "deny_network": self.deny_network,
            "deny_subprocess": self.deny_subprocess,
            "deny_database": self.deny_database,
            "include_raw_bodies": self.include_raw_bodies,
            "privacy_class": self.privacy_class,
            "collect_stdlib": self.collect_stdlib,
            "tracer_version": TRACER_VERSION,
        }

    @property
    def capture_profile_cid(self) -> str:
        return cid_for_structured(
            {
                "schema": PYTHON_TRACE_CAPTURE_PROFILE_SCHEMA,
                "policy": self.identity_payload(),
            }
        )


class TraceRedactor:
    """Bound, fail-closed redaction of locals, payloads, and public records."""

    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE

    def __init__(self, policy: TraceCollectionPolicy | None = None) -> None:
        self.policy = policy if policy is not None else TraceCollectionPolicy()

    def summarize_value(
        self, value: Any, *, depth: int = 0, redacted: set[str] | None = None
    ) -> Any:
        budget = self.policy.max_summary_items
        limit = self.policy.max_text_chars
        marks = set() if redacted is None else redacted
        if depth >= self.policy.max_value_depth:
            return {"unavailable": "depth"}
        if value is None or type(value) is bool:
            return value
        if type(value) is int and not isinstance(value, bool):
            if value < -_MAX_SAFE_INTEGER or value > _MAX_SAFE_INTEGER:
                return {"unavailable": "integer_range"}
            return value
        if type(value) is str:
            if len(value) <= limit:
                return unicodedata.normalize("NFC", value)
            return unicodedata.normalize("NFC", value[:limit])
        if type(value) is float:
            return {"unavailable": "float"}
        if isinstance(value, Mapping) and not isinstance(value, (str, bytes, bytearray)):
            items: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= budget:
                    break
                if type(key) is not str:
                    continue
                name = key[:limit]
                if _secret_name(name):
                    marks.add(name)
                    continue
                items[name] = self.summarize_value(item, depth=depth + 1, redacted=marks)
            return items
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [
                self.summarize_value(item, depth=depth + 1, redacted=marks)
                for item in list(value)[:budget]
            ]
        return {"unavailable": type(value).__name__[:limit]}

    def summarize_locals(
        self, frame: types.FrameType
    ) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
        redacted: set[str] = set()
        unavailable: set[str] = set()
        locals_map: dict[str, Any] = {}
        try:
            raw_locals = frame.f_locals
        except Exception:
            return {"locals": {}}, (), ("locals",)
        if not isinstance(raw_locals, Mapping):
            return {"locals": {}}, (), ("locals",)
        count = 0
        for name, value in raw_locals.items():
            if type(name) is not str or not name:
                continue
            if name.startswith(_INTERNAL_NAME_PREFIXES):
                continue
            if _secret_name(name):
                redacted.add(name)
                continue
            if count >= self.policy.max_summary_items:
                unavailable.add("locals_tail")
                break
            locals_map[name[: self.policy.max_text_chars]] = self.summarize_value(
                value, redacted=redacted
            )
            count += 1
        summary = {"locals": locals_map}
        return summary, tuple(sorted(redacted)), tuple(sorted(unavailable))

    def public_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        if not isinstance(trace, ExecutionTrace):
            raise PythonExecutionTraceError("public projection requires an ExecutionTrace")
        public = trace.public_view()
        if public.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if public.raw_execution_state_cids:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if public.privacy_class != PrivacyClass.PUBLIC.value:
            raise PythonExecutionTraceError("public records must use the public privacy class")
        return public

    def public_record(self, record: "PythonExecutionTraceRecord") -> dict[str, Any]:
        public = self.public_trace(record.trace)
        payload = {
            "accepted_transition": None,
            "cancelled": record.cancelled,
            "event_cids": list(public.event_cids),
            "execution_trace_cid": public.execution_trace_cid,
            "includes_raw_bodies": False,
            "interface": PYTHON_EXECUTION_TRACE_RECORD_INTERFACE,
            "privacy_class": public.privacy_class,
            "raw_execution_state_cids": [],
            "trace": public.to_dict(),
        }
        _assert_no_raw_bodies(payload)
        return payload


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceRecord:
    """Self-contained hermetic trace record with an explicit public projection."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECORD_INTERFACE

    trace: ExecutionTrace
    public_trace: ExecutionTrace
    events: tuple[ProgramEvent, ...]
    observations: tuple[ExecutionObservation, ...]
    states: tuple[ProgramExecutionState, ...]
    frames: tuple[StackFrameState, ...]
    policy: TraceCollectionPolicy
    capture_profile_cid: str
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    subject_cid: str
    cancelled: bool
    cancellation: TraceCancellation | None
    accepted_transition: None
    outcome: str
    return_summary: Mapping[str, Any]
    redaction_profile: RedactionProfile

    def __post_init__(self) -> None:
        if self.accepted_transition is not None:
            raise PythonExecutionTraceError("tracing never emits an accepted transition")
        if self.public_trace.includes_raw_bodies or self.public_trace.raw_execution_state_cids:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if self.cancelled and self.accepted_transition is not None:
            raise PythonExecutionTraceError("cancellation emits no accepted transition")
        object.__setattr__(self, "return_summary", MappingProxyType(dict(self.return_summary)))

    def public_record(self) -> dict[str, Any]:
        return TraceRedactor(self.policy).public_record(self)


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------


def _default_environment() -> dict[str, str]:
    info = sys.version_info
    return {
        "language": ADMITTED_LANGUAGE,
        "python_implementation": sys.implementation.name,
        "python_version": f"{info.major}.{info.minor}.{info.micro}",
    }


def _environment_cid(bindings: Mapping[str, str]) -> str:
    items = [{"key": key, "value": value} for key, value in sorted(bindings.items())]
    return cid_for_structured(
        {"schema": PYTHON_TRACE_ENVIRONMENT_SCHEMA, "bindings": items}
    )


def _target_function(target: Callable[..., Any]) -> Any:
    if not callable(target):
        raise PythonExecutionTraceError("target must be a Python callable")
    func: Any = target
    for attribute in ("__func__", "func", "wrapped"):
        inner = getattr(func, attribute, None)
        if inner is not None and getattr(inner, "__code__", None) is not None:
            func = inner
            break
    if getattr(func, "__code__", None) is None:
        raise PythonExecutionTraceError("target is not an admitted Python function")
    return func


def _source_bytes_for(code: types.CodeType) -> bytes:
    filename = code.co_filename
    if not filename or filename.startswith("<"):
        return code.co_code
    try:
        lines = linecache.getlines(filename)
    except Exception:
        return code.co_code
    if not lines:
        return code.co_code
    payload = "".join(lines).encode("utf-8")
    if len(payload) > _MAX_SOURCE_BYTES:
        return payload[:_MAX_SOURCE_BYTES]
    return payload


def _code_cid(code: types.CodeType) -> str:
    qualname = getattr(code, "co_qualname", code.co_name)
    return cid_for_bytes(
        b"\n".join(
            (
                unicodedata.normalize("NFC", qualname).encode("utf-8"),
                str(code.co_firstlineno).encode("ascii"),
                code.co_code,
            )
        )
    )


def _logical_name(frame: types.FrameType) -> str:
    module = frame.f_globals.get("__name__")
    if type(module) is not str or not module.strip():
        module = "builtins"
    qualname = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
    if type(qualname) is not str or not qualname.strip():
        qualname = frame.f_code.co_name or "unknown"
    return _nfc(f"{module}.{qualname}", "logical_name")


def _opname_at(frame: types.FrameType) -> str:
    raw = frame.f_code.co_code
    lasti = frame.f_lasti
    if lasti < 0 or lasti >= len(raw):
        return ""
    while lasti >= 0:
        try:
            name = opcode.opname[raw[lasti]]
        except (IndexError, KeyError):
            return ""
        if name != "CACHE":
            return name
        lasti -= 2
    return ""


def _is_internal_filename(filename: str) -> bool:
    if not filename or filename.startswith("<frozen"):
        return True
    normalized = filename.replace("\\", "/")
    if normalized == _MODULE_FILE.replace("\\", "/"):
        return True
    return any(marker in normalized for marker in _INTERNAL_PATH_MARKERS)


def _is_stdlib_filename(filename: str) -> bool:
    if not filename:
        return False
    prefixes = [sys.base_prefix, sys.prefix]
    normalized = filename.replace("\\", "/")
    if "site-packages" in normalized:
        return False
    return any(filename.startswith(prefix) for prefix in prefixes if prefix)


def _assert_no_raw_bodies(value: Any) -> None:
    if isinstance(value, Mapping):
        if value.get("includes_raw_bodies") is True:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if value.get("raw_execution_state_cids"):
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        for item in value.values():
            _assert_no_raw_bodies(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _assert_no_raw_bodies(item)


# ---------------------------------------------------------------------------
# Active-tracer audit dispatcher (installed only on first collection)
# ---------------------------------------------------------------------------


_ACTIVE: Final[threading.local] = threading.local()
_AUDIT_INSTALLED = False


def _audit_dispatch(event: str, args: tuple[Any, ...]) -> None:
    tracer = getattr(_ACTIVE, "tracer", None)
    if tracer is None:
        return
    tracer._on_audit(event, args)


def _ensure_audit_hook() -> None:
    global _AUDIT_INSTALLED
    if _AUDIT_INSTALLED:
        return
    sys.addaudithook(_audit_dispatch)
    _AUDIT_INSTALLED = True


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class PythonExecutionTracer:
    """Collect a bounded hermetic Python execution trace for one callable."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE

    def __init__(self, policy: TraceCollectionPolicy | None = None) -> None:
        self.policy = policy if policy is not None else TraceCollectionPolicy()
        self.redactor = TraceRedactor(self.policy)
        self._reset()

    def _reset(self) -> None:
        self._active = False
        self._events: list[ProgramEvent] = []
        self._states: list[ProgramExecutionState] = []
        self._frames: dict[str, StackFrameState] = {}
        self._line_events = 0
        self._cancelled = False
        self._cancellation: TraceCancellation | None = None
        self._denied_external = False
        self._awaiting_handler = False
        self._pending_exception: ExceptionSnapshot | None = None
        self._redacted: set[str] = set()
        self._unavailable: set[str] = {"heap"}
        self._outcome = "unavailable"
        self._return_summary: dict[str, Any] = {}
        self._target_code: types.CodeType | None = None
        self._target_name = "unknown"
        self._tree_cid = ""
        self._source_cid = ""
        self._env_cid = ""
        self._subject_cid = ""
        self._capture_profile_cid = self.policy.capture_profile_cid
        self._previous_trace: Any = None
        self._construction_errors: list[str] = []

    def record(self, target: Callable[..., Any], /, *args: Any, **kwargs: Any) -> PythonExecutionTraceRecord:
        """Execute ``target`` under hermetic tracing and return the bound record."""

        self._reset()
        func = _target_function(target)
        self._bind(func)
        self._previous_trace = sys.gettrace()
        self._active = True
        _ensure_audit_hook()
        _ACTIVE.tracer = self
        try:
            sys.settrace(self._trace)
            try:
                result = target(*args, **kwargs)
            except TraceCancellation as cancellation:
                self._mark_cancelled(cancellation)
                result = None
            except PythonExecutionTraceError as error:
                if self._denied_external:
                    self._outcome = "denied"
                    self._mark_cancelled(
                        TraceCancellation(str(error), event_count=len(self._events))
                    )
                    result = None
                else:
                    raise
            except Exception as error:
                self._outcome = "raised"
                self._return_summary = {
                    "value_kind": type(error).__name__[: self.policy.max_text_chars]
                }
                result = None
            else:
                if not self._cancelled:
                    self._outcome = "returned"
                    self._return_summary = {
                        "value_kind": type(result).__name__[: self.policy.max_text_chars]
                    }
        finally:
            self._active = False
            sys.settrace(self._previous_trace)
            _ACTIVE.tracer = None
        return self._finalize()

    def _bind(self, func: Any) -> None:
        code: types.CodeType = func.__code__
        self._target_code = code
        self._target_name = _nfc(
            f"{getattr(func, '__module__', 'builtins')}.{getattr(func, '__qualname__', code.co_name)}",
            "target name",
        )
        source_cid = cid_for_bytes(_source_bytes_for(code))
        environment = dict(self.policy.environment_binding) or _default_environment()
        env_cid = _environment_cid(environment)
        tree_cid = self.policy.tree_cid or cid_for_structured(
            {
                "schema": PYTHON_TRACE_TREE_SCHEMA,
                "language": ADMITTED_LANGUAGE,
                "source_cid": source_cid,
            }
        )
        subject_cid = cid_for_structured(
            {
                "schema": PYTHON_TRACE_SUBJECT_SCHEMA,
                "code_cid": _code_cid(code),
                "logical_name": self._target_name,
                "source_cid": source_cid,
            }
        )
        self._source_cid = source_cid
        self._env_cid = env_cid
        self._tree_cid = tree_cid
        self._subject_cid = subject_cid

    def _include_frame(self, frame: types.FrameType) -> bool:
        filename = frame.f_code.co_filename
        if _is_internal_filename(filename):
            return False
        if not self.policy.collect_stdlib and _is_stdlib_filename(filename):
            return False
        current: types.FrameType | None = frame
        seen = 0
        while current is not None and seen < _MAX_STACK_WALK:
            if current.f_code is self._target_code:
                return True
            if _is_internal_filename(current.f_code.co_filename):
                return False
            current = current.f_back
            seen += 1
        return False

    def _trace(self, frame: types.FrameType, event: str, arg: Any) -> Any:
        if not self._active or self._cancelled:
            return None
        if not self._include_frame(frame):
            return self._trace
        try:
            if event == "call":
                self._emit_kind(EventKind.CALL.value, frame, {"callee": _logical_name(frame)})
            elif event == "return":
                kind = self._classify_return(frame)
                payload = {"value_kind": type(arg).__name__[: self.policy.max_text_chars]}
                self._emit_kind(kind, frame, payload)
            elif event == "line":
                if self._awaiting_handler:
                    self._emit_handler(frame)
                self._emit_line(frame)
            elif event == "exception":
                self._emit_raise(frame, arg)
            if self._cancelled:
                return None
        except TraceCancellation as cancellation:
            self._mark_cancelled(cancellation)
            return None
        except (PythonExecutionTraceError, ProgramExecutionError) as error:
            # Trace callbacks must not raise: CPython disables tracing and does
            # not propagate the exception to the traced callable.
            self._unavailable.add("trace_event")
            self._construction_errors.append(str(error)[: self.policy.max_text_chars])
        except Exception:
            self._unavailable.add("trace_event")
        return self._trace

    def _classify_return(self, frame: types.FrameType) -> str:
        flags = frame.f_code.co_flags
        opname = _opname_at(frame)
        if flags & (inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR):
            if opname in _YIELD_OPNAMES or (opname and opname != "RETURN_VALUE"):
                return EventKind.YIELD.value
        if flags & (inspect.CO_COROUTINE | inspect.CO_ITERABLE_COROUTINE):
            if opname in _AWAIT_OPNAMES or opname in _YIELD_OPNAMES:
                return EventKind.AWAIT.value
        return EventKind.RETURN.value

    def _emit_line(self, frame: types.FrameType) -> None:
        if not self.policy.admits(EventKind.LINE.value):
            return
        if self._line_events >= self.policy.max_line_events:
            self._unavailable.add("line")
            return
        self._line_events += 1
        self._emit_kind(EventKind.LINE.value, frame, {})

    def _emit_raise(self, frame: types.FrameType, arg: Any) -> None:
        exception_type = "Exception"
        if isinstance(arg, tuple) and arg:
            candidate = arg[0]
            if isinstance(candidate, type):
                exception_type = candidate.__name__
            else:
                exception_type = type(candidate).__name__
        exception_type = exception_type[: self.policy.max_text_chars]
        frames = self._stack_states(frame)
        snapshot = ExceptionSnapshot(
            language=ProgramLanguage.PYTHON,
            exception_type=exception_type,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=_code_cid(frame.f_code),
            environment_binding_cid=self._env_cid,
            exception_value_summary={"type": exception_type, "bounded": True},
            traceback_stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
            future_execution=False,
            unavailable_dimensions=("exception_value",),
            completeness_claim=CompletenessClaim.PARTIAL,
        )
        self._pending_exception = snapshot
        self._awaiting_handler = True
        self._emit_kind(
            EventKind.RAISE.value,
            frame,
            {"exception_type": exception_type},
            exception=snapshot,
            frames=frames,
        )

    def _emit_handler(self, frame: types.FrameType) -> None:
        if not (
            self.policy.admits(EventKind.CATCH.value)
            or self.policy.admits(EventKind.HANDLER.value)
        ):
            self._awaiting_handler = False
            return
        frames = self._stack_states(frame)
        exception = self._pending_exception
        handler = HandlerState(
            language=ProgramLanguage.PYTHON,
            handler_kind=HandlerKind.EXCEPT,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=_code_cid(frame.f_code),
            environment_binding_cid=self._env_cid,
            logical_name=_logical_name(frame),
            stack_ordinal=0,
            handler_active=True,
            matching_exception_snapshot_cid=(
                None if exception is None else exception.exception_snapshot_cid
            ),
            unavailable_dimensions=() if exception is not None else ("exception",),
        )
        payload = {"handler_kind": HandlerKind.EXCEPT.value}
        if self.policy.admits(EventKind.CATCH.value):
            self._emit_kind(
                EventKind.CATCH.value,
                frame,
                payload,
                exception=exception,
                handler=handler,
                frames=frames,
            )
        if self.policy.admits(EventKind.HANDLER.value):
            self._emit_kind(
                EventKind.HANDLER.value,
                frame,
                payload,
                exception=exception,
                handler=handler,
                frames=frames,
            )
        self._awaiting_handler = False

    def _on_audit(self, event: str, args: tuple[Any, ...]) -> None:
        if not self._active or self._cancelled:
            return
        if event not in _DENIED_AUDIT_EVENTS:
            return
        network_event = event.startswith("socket.")
        subprocess_event = event.startswith("subprocess.") or event.startswith("os.")
        database_event = event.startswith("sqlite3.")
        if network_event and not self.policy.deny_network:
            self._emit_external(event, denied=False)
            return
        if subprocess_event and not self.policy.deny_subprocess:
            self._emit_external(event, denied=False)
            return
        if database_event and not self.policy.deny_database:
            self._emit_external(event, denied=False)
            return
        self._denied_external = True
        try:
            self._emit_external(event, denied=True)
        finally:
            raise PythonExecutionTraceError(f"hermetic policy denies {event}")

    def _emit_external(self, event: str, *, denied: bool) -> None:
        if not self.policy.admits(EventKind.EXTERNAL.value):
            return
        frame = inspect.currentframe()
        site = None
        while frame is not None:
            if self._include_frame(frame):
                site = frame
                break
            frame = frame.f_back
        if site is None and self._target_code is not None:
            # Bind the external observation to the target identity when the
            # audit hook is not sitting on an admitted Python frame.
            payload = {
                "denied": denied,
                "external_event": event[: self.policy.max_text_chars],
            }
            self._emit_synthetic_external(payload)
            return
        if site is None:
            self._unavailable.add("external")
            return
        self._emit_kind(
            EventKind.EXTERNAL.value,
            site,
            {
                "denied": denied,
                "external_event": event[: self.policy.max_text_chars],
            },
        )

    def _emit_synthetic_external(self, payload: Mapping[str, Any]) -> None:
        if self._target_code is None:
            return
        logical = self._target_name
        code_cid = _code_cid(self._target_code)
        frame_state = StackFrameState(
            ordinal=0,
            language=ProgramLanguage.PYTHON,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=code_cid,
            environment_binding_cid=self._env_cid,
            logical_name=logical,
            line=self._target_code.co_firstlineno,
            column=None,
            state_summary={"locals": {}},
            completeness_claim=CompletenessClaim.PARTIAL,
            privacy_class=self.policy.privacy_class,
            unavailable_dimensions=("heap", "source_location"),
        )
        self._frames[frame_state.stack_frame_state_cid] = frame_state
        self._emit_kind(
            EventKind.EXTERNAL.value,
            None,
            payload,
            frames=(frame_state,),
            code_cid=code_cid,
            logical_name=logical,
            line=self._target_code.co_firstlineno,
        )

    def _stack_states(self, frame: types.FrameType) -> tuple[StackFrameState, ...]:
        python_frames: list[types.FrameType] = []
        current: types.FrameType | None = frame
        depth = 0
        while current is not None and depth < _MAX_STACK_WALK:
            if self._include_frame(current):
                python_frames.append(current)
            current = current.f_back
            depth += 1
            if len(python_frames) >= self.policy.max_stack_depth:
                self._unavailable.add("call_stack")
                break
        states: list[StackFrameState] = []
        for ordinal, item in enumerate(python_frames):
            states.append(self._frame_state(ordinal, item))
        return tuple(states)

    def _frame_state(self, ordinal: int, frame: types.FrameType) -> StackFrameState:
        summary, redacted, unavailable = self.redactor.summarize_locals(frame)
        self._redacted.update(redacted)
        self._unavailable.update(unavailable)
        claim = CompletenessClaim.REDACTED if redacted else CompletenessClaim.PARTIAL
        line = frame.f_lineno if type(frame.f_lineno) is int and frame.f_lineno >= 0 else None
        unavailable_dims = set(unavailable) | {"heap"}
        if line is None:
            unavailable_dims.add("source_location")
        state = StackFrameState(
            ordinal=ordinal,
            language=ProgramLanguage.PYTHON,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=_code_cid(frame.f_code),
            environment_binding_cid=self._env_cid,
            logical_name=_logical_name(frame),
            line=line,
            column=None,
            state_summary=summary,
            redacted_dimensions=tuple(sorted(redacted)),
            unavailable_dimensions=tuple(sorted(unavailable_dims)),
            completeness_claim=claim,
            privacy_class=self.policy.privacy_class,
        )
        self._frames[state.stack_frame_state_cid] = state
        return state

    def _emit_kind(
        self,
        kind: str,
        frame: types.FrameType | None,
        payload: Mapping[str, Any],
        *,
        exception: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
        frames: Sequence[StackFrameState] | None = None,
        code_cid: str | None = None,
        logical_name: str | None = None,
        line: int | None = None,
    ) -> None:
        if not self.policy.admits(kind) and kind != EventKind.UNAVAILABLE.value:
            return
        if len(self._events) >= self.policy.max_events:
            self._mark_cancelled(
                TraceCancellation("max_events", event_count=len(self._events))
            )
            return
        previous = sys.gettrace()
        sys.settrace(None)
        try:
            stack = tuple(frames) if frames is not None else (
                self._stack_states(frame) if frame is not None else ()
            )
            current_code = code_cid
            current_name = logical_name
            current_line = line
            if frame is not None:
                current_code = current_code or _code_cid(frame.f_code)
                current_name = current_name or _logical_name(frame)
                if current_line is None and type(frame.f_lineno) is int and frame.f_lineno >= 0:
                    current_line = frame.f_lineno
            if current_code is None or current_name is None:
                return
            redacted = tuple(sorted(self._redacted))
            unavailable = tuple(sorted(self._unavailable))
            if redacted:
                claim = CompletenessClaim.REDACTED
                status = ObservationStatus.REDACTED
            else:
                claim = CompletenessClaim.PARTIAL
                status = ObservationStatus.OBSERVED
            if kind in {EventKind.CATCH.value, EventKind.HANDLER.value} and handler is None:
                unavailable = tuple(sorted(set(unavailable) | {"handler"}))
            predecessor = None if not self._events else self._events[-1].program_event_cid
            event = ProgramEvent(
                event_kind=kind,
                event_origin=EventOrigin.OBSERVED,
                observation_status=status if kind != EventKind.UNAVAILABLE.value else ObservationStatus.UNAVAILABLE,
                language=ProgramLanguage.PYTHON,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                code_cid=current_code,
                environment_binding_cid=self._env_cid,
                subject_cid=self._subject_cid,
                logical_name=current_name,
                payload=dict(payload),
                line=current_line,
                column=None,
                predecessor_event_cid=predecessor,
                stack_frame_cids=tuple(item.stack_frame_state_cid for item in stack),
                exception_snapshot_cid=None if exception is None else exception.exception_snapshot_cid,
                handler_state_cid=None if handler is None else handler.handler_state_cid,
                redaction_profile_cid=None,
                redacted_dimensions=redacted,
                unavailable_dimensions=unavailable if claim != CompletenessClaim.FULL_STATE else (),
                completeness_claim=(
                    CompletenessClaim.UNAVAILABLE
                    if kind == EventKind.UNAVAILABLE.value
                    else claim
                ),
                privacy_class=self.policy.privacy_class,
            )
            self._events.append(event)
            if kind in {
                EventKind.CALL.value,
                EventKind.RETURN.value,
                EventKind.RAISE.value,
                EventKind.CATCH.value,
                EventKind.YIELD.value,
                EventKind.AWAIT.value,
            }:
                self._states.append(
                    assemble_program_execution_state(
                        language=ProgramLanguage.PYTHON,
                        capture_profile_cid=self._capture_profile_cid,
                        tree_cid=self._tree_cid,
                        source_cid=self._source_cid,
                        environment_binding_cid=self._env_cid,
                        frames=stack,
                        observed_state={"locals": {}} if not self.policy.include_raw_bodies else (
                            dict(stack[0].state_summary) if stack else {"locals": {}}
                        ),
                        heap_summary={},
                        heap_bound=HeapBound.UNAVAILABLE,
                        exception=exception,
                        handler=handler,
                        observation_status=status,
                        completeness_claim=claim,
                        privacy_class=self.policy.privacy_class,
                        includes_raw_bodies=self.policy.include_raw_bodies,
                        unavailable_dimensions=tuple(sorted(set(unavailable) | {"heap"})),
                        code_cid=current_code,
                    )
                )
        except ProgramExecutionError as error:
            raise PythonExecutionTraceError(str(error)) from error
        finally:
            if self._active and not self._cancelled:
                sys.settrace(self._trace if previous is None else previous)

    def _mark_cancelled(self, cancellation: TraceCancellation) -> None:
        self._cancelled = True
        self._cancellation = cancellation
        self._unavailable.add("continuation")
        if self._outcome not in {"returned", "raised", "denied"}:
            self._outcome = "cancelled"

    def _finalize(self) -> PythonExecutionTraceRecord:
        events = tuple(self._events)
        if not events:
            events = (
                ProgramEvent(
                    event_kind=EventKind.UNAVAILABLE,
                    event_origin=EventOrigin.OBSERVED,
                    observation_status=ObservationStatus.UNAVAILABLE,
                    language=ProgramLanguage.PYTHON,
                    tree_cid=self._tree_cid,
                    source_cid=self._source_cid,
                    code_cid=_code_cid(self._target_code) if self._target_code is not None else cid_for_bytes(b"unavailable"),
                    environment_binding_cid=self._env_cid,
                    subject_cid=self._subject_cid,
                    logical_name=self._target_name,
                    payload={},
                    line=None,
                    column=None,
                    predecessor_event_cid=None,
                    stack_frame_cids=(),
                    redacted_dimensions=(),
                    unavailable_dimensions=("events", "heap", "call_stack"),
                    completeness_claim=CompletenessClaim.UNAVAILABLE,
                    privacy_class=self.policy.privacy_class,
                ),
            )
        redacted = tuple(sorted(self._redacted))
        unavailable = tuple(sorted(self._unavailable))
        if redacted:
            claim = CompletenessClaim.REDACTED
        elif self._cancelled and unavailable:
            claim = CompletenessClaim.PARTIAL
        else:
            claim = CompletenessClaim.PARTIAL
        profile = RedactionProfile(
            privacy_class=self.policy.privacy_class,
            redacted_dimensions=redacted,
            unavailable_dimensions=unavailable,
            completeness_claim=claim,
        )
        states = tuple(self._states) if self.policy.include_raw_bodies else ()
        try:
            trace = assemble_execution_trace(
                language=ProgramLanguage.PYTHON,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                environment_binding_cid=self._env_cid,
                events=events,
                states=states,
                redaction=profile,
                completeness_claim=claim,
                privacy_class=self.policy.privacy_class,
                includes_raw_bodies=self.policy.include_raw_bodies,
                unavailable_dimensions=unavailable,
            )
        except ProgramExecutionError as error:
            raise PythonExecutionTraceError(str(error)) from error
        public = self.redactor.public_trace(trace)
        if self._construction_errors and not any(
            str(event.event_kind) != EventKind.UNAVAILABLE.value for event in events
        ):
            raise PythonExecutionTraceError(
                "trace construction failed: " + "; ".join(self._construction_errors[:4])
            )
        observations: list[ExecutionObservation] = []
        for event in events:
            if event.observation_admissible:
                observations.append(observe_program_event(event))
        return PythonExecutionTraceRecord(
            trace=trace,
            public_trace=public,
            events=events,
            observations=tuple(observations),
            states=tuple(self._states),
            frames=tuple(self._frames.values()),
            policy=self.policy,
            capture_profile_cid=self._capture_profile_cid,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self._env_cid,
            subject_cid=self._subject_cid,
            cancelled=self._cancelled,
            cancellation=self._cancellation,
            accepted_transition=None,
            outcome=self._outcome,
            return_summary=self._return_summary,
            redaction_profile=profile,
        )


def record_python_execution_trace(
    target: Callable[..., Any],
    /,
    *args: Any,
    policy: TraceCollectionPolicy | None = None,
    **kwargs: Any,
) -> PythonExecutionTraceRecord:
    """Collect an admitted hermetic Python execution trace for ``target``."""

    return PythonExecutionTracer(policy).record(target, *args, **kwargs)


def replay_deterministic_trace(
    source: PythonExecutionTraceRecord | ExecutionTrace,
    /,
    events: Sequence[ProgramEvent] | None = None,
    states: Sequence[ProgramExecutionState] | None = None,
) -> PythonExecutionTraceRecord:
    """Replay a promised deterministic trace without operational acceptance.

    Replay reconstructs the same trace identity from recorded events.  It does
    not re-execute the original callable and never emits an accepted
    transition.
    """

    if isinstance(source, PythonExecutionTraceRecord):
        record_events = tuple(source.events if events is None else events)
        record_states = tuple(source.states if states is None else states)
        policy = source.policy
        capture_profile_cid = source.capture_profile_cid
        subject_cid = source.subject_cid
        cancelled = source.cancelled
        cancellation = source.cancellation
        outcome = source.outcome
        return_summary = dict(source.return_summary)
        redaction = source.redaction_profile
        frames = source.frames
        original_cid = source.trace.execution_trace_cid
        original_public = source.public_trace.execution_trace_cid
        tree_cid = source.tree_cid
        source_cid = source.source_cid
        env_cid = source.environment_binding_cid
        includes_raw = source.trace.includes_raw_bodies
        privacy = source.trace.privacy_class
        unavailable = source.trace.unavailable_dimensions
        claim = source.trace.completeness_claim
    elif isinstance(source, ExecutionTrace):
        if events is None:
            raise PythonExecutionTraceError(
                "promised replay of a bare ExecutionTrace requires recorded events"
            )
        record_events = tuple(events)
        record_states = tuple(states or ())
        policy = TraceCollectionPolicy(
            include_raw_bodies=source.includes_raw_bodies,
            privacy_class=source.privacy_class,
        )
        capture_profile_cid = policy.capture_profile_cid
        subject_cid = record_events[0].subject_cid
        cancelled = False
        cancellation = None
        outcome = "replayed"
        return_summary = {}
        redaction = RedactionProfile(
            privacy_class=source.privacy_class,
            redacted_dimensions=source.redacted_dimensions,
            unavailable_dimensions=source.unavailable_dimensions,
            completeness_claim=source.completeness_claim,
        )
        frames = ()
        original_cid = source.execution_trace_cid
        original_public = source.public_view().execution_trace_cid
        tree_cid = source.tree_cid
        source_cid = source.source_cid
        env_cid = source.environment_binding_cid
        includes_raw = source.includes_raw_bodies
        privacy = source.privacy_class
        unavailable = source.unavailable_dimensions
        claim = source.completeness_claim
    else:
        raise PythonExecutionTraceError("replay requires a recorded trace")

    if not record_events:
        raise PythonExecutionTraceError("promised replay requires at least one event")
    attached_states = record_states if includes_raw else ()
    try:
        trace = assemble_execution_trace(
            language=ProgramLanguage.PYTHON,
            tree_cid=tree_cid,
            source_cid=source_cid,
            environment_binding_cid=env_cid,
            events=record_events,
            states=attached_states,
            redaction=redaction,
            completeness_claim=claim,
            privacy_class=privacy,
            includes_raw_bodies=includes_raw,
            unavailable_dimensions=unavailable,
        )
    except ProgramExecutionError as error:
        raise PythonExecutionTraceError(str(error)) from error
    if trace.execution_trace_cid != original_cid:
        raise PythonExecutionTraceError("promised replay diverged from the recorded trace identity")
    public = TraceRedactor(policy).public_trace(trace)
    if public.execution_trace_cid != original_public:
        raise PythonExecutionTraceError("promised replay diverged from the public trace identity")
    observations = tuple(
        observe_program_event(event) for event in record_events if event.observation_admissible
    )
    return PythonExecutionTraceRecord(
        trace=trace,
        public_trace=public,
        events=record_events,
        observations=observations,
        states=record_states,
        frames=frames,
        policy=policy,
        capture_profile_cid=capture_profile_cid,
        tree_cid=tree_cid,
        source_cid=source_cid,
        environment_binding_cid=env_cid,
        subject_cid=subject_cid,
        cancelled=cancelled,
        cancellation=cancellation,
        accepted_transition=None,
        outcome=outcome,
        return_summary=return_summary,
        redaction_profile=redaction,
    )


__all__ = [
    "ADMITTED_LANGUAGE",
    "IMPORT_DATABASE_OPENED",
    "IMPORT_INSTALLER_INVOKED",
    "IMPORT_MODEL_LOADED",
    "IMPORT_NETWORK_OPENED",
    "IMPORT_REPO_SCAN_PERFORMED",
    "IMPORT_SIDE_EFFECTS_PERFORMED",
    "IMPORT_SOCKET_OPENED",
    "IMPORT_SUBPROCESS_STARTED",
    "IMPORT_WATCHER_STARTED",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "PYTHON_EXECUTION_TRACE_RECORD_INTERFACE",
    "RECORD_PYTHON_EXECUTION_TRACE_INTERFACE",
    "REPLAY_DETERMINISTIC_TRACE_INTERFACE",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "PythonExecutionTraceError",
    "PythonExecutionTraceRecord",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCollectionPolicy",
    "TraceRedactor",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
