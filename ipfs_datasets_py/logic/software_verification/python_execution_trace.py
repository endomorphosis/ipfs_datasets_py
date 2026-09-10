"""Hermetic Python execution tracing adapter (SAWM-008).

This module is the datasets tracing authority for ``sawm/hermetic-trace@1``.
It extends the SAWM-007 ``ProgramEvent@1`` / ``ExecutionTrace@1`` contracts
with an in-process CPython tracer that records admitted call, return, line,
exception, handler, yield, await, and selected external events.

Normative constraints:

* Importing this module never opens a network/socket, runs an installer,
  starts a subprocess, opens a database, scans a repository, starts a
  watcher, or loads a model.
* Collection uses ``sys.settrace`` in the calling thread.  It never shells
  out, never starts a persistent event loop, and never bypasses execution
  isolation.
* Every recorded event binds exact tree, source, code, and environment
  identities.  Wall-clock, hostname, and pid are excluded from identity.
* Line/basic-block detail is policy- and cost-bounded.
* Secret and forbidden fields are redacted before any public or contract
  record is assembled.  Private raw bodies never enter public records.
* Cancellation produces an incomplete prefix and never an accepted
  transition.  This adapter does not persist operational acceptance.
* Nondeterministic external effects are explicit ``external`` observations
  or typed unavailable dimensions; they are not decoded as internal state.
* Promised replay reconstitutes the recorded event sequence without
  re-executing the subject.
"""

from __future__ import annotations

import dis
import inspect
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import FrameType, MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    FORBIDDEN_FIELD_MARKERS,
    MAX_METADATA_BYTES,
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
    RedactionProfile,
    StackFrameState,
    assemble_execution_trace,
    assemble_program_execution_state,
    observe_program_event,
    program_execution_cid_for,
)


# ---------------------------------------------------------------------------
# Import-time hermeticity.  These flags are never flipped by this module.
# ---------------------------------------------------------------------------

IMPORT_NETWORK_PERFORMED: Final[bool] = False
IMPORT_SOCKET_OPENED: Final[bool] = False
IMPORT_INSTALLER_INVOKED: Final[bool] = False
IMPORT_SUBPROCESS_PERFORMED: Final[bool] = False
IMPORT_DATABASE_OPENED: Final[bool] = False
IMPORT_REPO_SCAN_PERFORMED: Final[bool] = False
IMPORT_WATCHER_STARTED: Final[bool] = False
IMPORT_MODEL_LOADED: Final[bool] = False

PYTHON_EXECUTION_TRACER_INTERFACE: Final[str] = "PythonExecutionTracer@1"
TRACE_COLLECTION_POLICY_INTERFACE: Final[str] = "TraceCollectionPolicy@1"
TRACE_REDACTOR_INTERFACE: Final[str] = "TraceRedactor@1"
TRACE_CANCELLATION_INTERFACE: Final[str] = "TraceCancellation@1"
PYTHON_EXECUTION_TRACE_RECORD_INTERFACE: Final[str] = "PythonExecutionTraceRecord@1"
PYTHON_EXECUTION_TRACER_VERSION: Final[str] = "1"

PYTHON_EXECUTION_TRACE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-trace@1"
)
TRACE_COLLECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-policy@1"
)
PYTHON_EXECUTION_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-environment@1"
)
PYTHON_EXECUTION_CAPTURE_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-capture-profile@1"
)

ADMITTED_LANGUAGE: Final[str] = "python"
DEFAULT_MAX_EVENTS: Final[int] = 256
DEFAULT_MAX_LINE_EVENTS: Final[int] = 64
DEFAULT_MAX_STACK_FRAMES: Final[int] = 32
DEFAULT_MAX_PAYLOAD_BYTES: Final[int] = 4_096
DEFAULT_MAX_SUMMARY_ITEMS: Final[int] = 32
DEFAULT_MAX_TEXT_CHARS: Final[int] = 256
PUBLIC_PRIVACY_CLASSES: Final[frozenset[str]] = frozenset({"public", "internal"})

_CO_GENERATOR: Final[int] = 0x20
_CO_COROUTINE: Final[int] = 0x80
_CO_ASYNC_GENERATOR: Final[int] = 0x200
_YIELD_OPS: Final[frozenset[str]] = frozenset({"YIELD_VALUE", "YIELD_FROM"})
_AWAIT_OPS: Final[frozenset[str]] = frozenset(
    {"GET_AWAITABLE", "SEND", "GET_AITER", "GET_ANEXT", "YIELD_FROM"}
)
_NETWORK_NAMES: Final[frozenset[str]] = frozenset(
    {
        "connect",
        "connect_ex",
        "create_connection",
        "create_server",
        "getaddrinfo",
        "gethostbyname",
        "urlopen",
        "wrap_socket",
        "sendto",
        "recvfrom",
        "create_connection",
    }
)
_SUBPROCESS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "Popen",
        "run",
        "call",
        "check_call",
        "check_output",
        "system",
        "posix_spawn",
        "execl",
        "execle",
        "execlp",
        "execv",
        "execve",
        "execvp",
    }
)
_INSTALLER_NAMES: Final[frozenset[str]] = frozenset({"pip", "ensurepip"})
_DATABASE_MODULES: Final[frozenset[str]] = frozenset(
    {"sqlite3", "duckdb", "psycopg2", "pymongo", "sqlalchemy"}
)
_MODEL_MODULES: Final[frozenset[str]] = frozenset(
    {"torch", "transformers", "tensorflow", "jax"}
)
_TRACER_FILENAME: Final[str] = __file__


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic tracing inputs, policy, or results are unsound."""


class TraceStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BOUNDED = "bounded"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Policy, cancellation, redaction
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


def _positive_int(value: object, name: str, *, allow_zero: bool = False) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise PythonExecutionTraceError(f"{name} must be a nonnegative integer")
    if not allow_zero and value == 0:
        raise PythonExecutionTraceError(f"{name} must be positive")
    return value


def _privacy(value: object) -> str:
    if isinstance(value, PrivacyClass):
        return value.value
    try:
        return PrivacyClass(value).value
    except (TypeError, ValueError) as exc:
        raise PythonExecutionTraceError(f"unsupported privacy_class {value!r}") from exc


def _environment_cid(bindings: Mapping[str, str]) -> str:
    items = [
        {"key": _nfc(str(key), "environment key"), "value": _nfc(str(value), "environment value")}
        for key, value in bindings.items()
    ]
    items.sort(key=lambda item: (item["key"], item["value"]))
    return cid_for_structured(
        {
            "schema": PYTHON_EXECUTION_ENVIRONMENT_SCHEMA,
            "language": ADMITTED_LANGUAGE,
            "bindings": items,
        }
    )


def _default_environment_binding() -> dict[str, str]:
    info = sys.version_info
    return {
        "language": ADMITTED_LANGUAGE,
        "python_major": str(info.major),
        "python_minor": str(info.minor),
        "python_micro": str(info.micro),
    }


def _secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in SECRET_FIELD_MARKERS or lowered in FORBIDDEN_FIELD_MARKERS:
        return True
    return any(
        marker in lowered
        for marker in SECRET_FIELD_MARKERS
        if len(marker) >= 5
    )


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Cost-bounded, fail-closed collection policy for one hermetic run."""

    collect_calls: bool = True
    collect_returns: bool = True
    collect_lines: bool = True
    collect_exceptions: bool = True
    collect_handlers: bool = True
    collect_yields: bool = True
    collect_awaits: bool = True
    collect_externals: bool = True
    deny_network: bool = True
    deny_subprocess: bool = True
    include_raw_bodies: bool = False
    max_events: int = DEFAULT_MAX_EVENTS
    max_line_events: int = DEFAULT_MAX_LINE_EVENTS
    max_stack_frames: int = DEFAULT_MAX_STACK_FRAMES
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
    max_summary_items: int = DEFAULT_MAX_SUMMARY_ITEMS
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL

    SCHEMA: ClassVar[str] = TRACE_COLLECTION_POLICY_SCHEMA
    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "collect_calls", _bool(self.collect_calls, "collect_calls"))
        object.__setattr__(self, "collect_returns", _bool(self.collect_returns, "collect_returns"))
        object.__setattr__(self, "collect_lines", _bool(self.collect_lines, "collect_lines"))
        object.__setattr__(
            self, "collect_exceptions", _bool(self.collect_exceptions, "collect_exceptions")
        )
        object.__setattr__(
            self, "collect_handlers", _bool(self.collect_handlers, "collect_handlers")
        )
        object.__setattr__(self, "collect_yields", _bool(self.collect_yields, "collect_yields"))
        object.__setattr__(self, "collect_awaits", _bool(self.collect_awaits, "collect_awaits"))
        object.__setattr__(
            self, "collect_externals", _bool(self.collect_externals, "collect_externals")
        )
        object.__setattr__(self, "deny_network", _bool(self.deny_network, "deny_network"))
        object.__setattr__(
            self, "deny_subprocess", _bool(self.deny_subprocess, "deny_subprocess")
        )
        object.__setattr__(
            self, "include_raw_bodies", _bool(self.include_raw_bodies, "include_raw_bodies")
        )
        object.__setattr__(self, "max_events", _positive_int(self.max_events, "max_events"))
        object.__setattr__(
            self, "max_line_events", _positive_int(self.max_line_events, "max_line_events")
        )
        object.__setattr__(
            self, "max_stack_frames", _positive_int(self.max_stack_frames, "max_stack_frames")
        )
        object.__setattr__(
            self, "max_payload_bytes", _positive_int(self.max_payload_bytes, "max_payload_bytes")
        )
        object.__setattr__(
            self,
            "max_summary_items",
            _positive_int(self.max_summary_items, "max_summary_items"),
        )
        object.__setattr__(self, "privacy_class", _privacy(self.privacy_class))
        if self.max_payload_bytes > MAX_METADATA_BYTES:
            raise PythonExecutionTraceError("max_payload_bytes exceeds contract metadata bound")
        if self.include_raw_bodies and self.privacy_class in PUBLIC_PRIVACY_CLASSES:
            # Raw bodies are collected privately; the public record still excludes them.
            object.__setattr__(self, "privacy_class", PrivacyClass.PRIVATE.value)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "collect_calls": self.collect_calls,
            "collect_returns": self.collect_returns,
            "collect_lines": self.collect_lines,
            "collect_exceptions": self.collect_exceptions,
            "collect_handlers": self.collect_handlers,
            "collect_yields": self.collect_yields,
            "collect_awaits": self.collect_awaits,
            "collect_externals": self.collect_externals,
            "deny_network": self.deny_network,
            "deny_subprocess": self.deny_subprocess,
            "include_raw_bodies": self.include_raw_bodies,
            "max_events": self.max_events,
            "max_line_events": self.max_line_events,
            "max_stack_frames": self.max_stack_frames,
            "max_payload_bytes": self.max_payload_bytes,
            "max_summary_items": self.max_summary_items,
            "privacy_class": self.privacy_class,
        }

    @property
    def capture_profile_cid(self) -> str:
        return cid_for_structured(
            {
                "schema": PYTHON_EXECUTION_CAPTURE_PROFILE_SCHEMA,
                "policy": self.identity_payload(),
                "tracer": PYTHON_EXECUTION_TRACER_INTERFACE,
                "version": PYTHON_EXECUTION_TRACER_VERSION,
            }
        )

    @classmethod
    def hermetic(cls, **overrides: Any) -> "TraceCollectionPolicy":
        return cls(**overrides)


class TraceCancellation(Exception):
    """Cancellation token and interrupt; never decoded as an accepted transition."""

    INTERFACE: ClassVar[str] = TRACE_CANCELLATION_INTERFACE

    def __init__(self, reason: str = "cancelled") -> None:
        super().__init__(reason)
        self.reason = _nfc(reason, "cancellation reason")
        self._requested = False

    def request(self, reason: str | None = None) -> None:
        if reason is not None:
            self.reason = _nfc(reason, "cancellation reason")
        self._requested = True

    @property
    def requested(self) -> bool:
        return self._requested

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.INTERFACE,
            "reason": self.reason,
            "requested": self.requested,
            "accepted_transition": False,
        }


class TraceRedactor:
    """Strip secrets and project a public view that never carries raw bodies."""

    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE

    def __init__(self, policy: TraceCollectionPolicy | None = None) -> None:
        self.policy = policy or TraceCollectionPolicy.hermetic()
        self.redacted_dimensions: set[str] = set()

    def redact_mapping(self, value: Any, *, budget: int) -> tuple[Any, tuple[str, ...]]:
        redacted: set[str] = set()

        def walk(item: Any, remaining: int) -> Any:
            if remaining <= 0:
                redacted.add("payload")
                return {"bounded": True}
            if item is None or type(item) is bool:
                return item
            if type(item) is int and not isinstance(item, bool):
                return item
            if type(item) is str:
                text = unicodedata.normalize("NFC", item)
                if len(text) > DEFAULT_MAX_TEXT_CHARS:
                    redacted.add("payload")
                    return text[:DEFAULT_MAX_TEXT_CHARS]
                return text
            if type(item) is float:
                redacted.add("non_semantic")
                return {"unavailable": "float"}
            if isinstance(item, Mapping):
                result: dict[str, Any] = {}
                count = 0
                for key, child in item.items():
                    if type(key) is not str:
                        continue
                    if _secret_key(key) or key in FORBIDDEN_FIELD_MARKERS:
                        redacted.add(key if key in SECRET_FIELD_MARKERS else "secrets")
                        continue
                    if count >= self.policy.max_summary_items:
                        redacted.add("payload")
                        break
                    result[key] = walk(child, remaining - 1)
                    count += 1
                return result
            if isinstance(item, (list, tuple)):
                limited = list(item)[: self.policy.max_summary_items]
                if len(item) > self.policy.max_summary_items:
                    redacted.add("payload")
                return [walk(child, remaining - 1) for child in limited]
            redacted.add("opaque")
            return {"type": type(item).__name__, "unavailable": True}

        cleaned = walk(value, max(1, min(budget, self.policy.max_summary_items)))
        self.redacted_dimensions.update(redacted)
        return cleaned, tuple(sorted(redacted))

    def bound_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        cleaned, _ = self.redact_mapping(dict(payload), budget=self.policy.max_summary_items)
        if not isinstance(cleaned, Mapping):
            cleaned = {"bounded": True}
        blob = canonical_dag_json_bytes(dict(cleaned))
        if len(blob) > self.policy.max_payload_bytes:
            digest = cid_for_bytes(blob)
            self.redacted_dimensions.add("payload")
            return {"bounded": True, "omitted": True, "digest_cid": digest}
        return dict(cleaned)

    def profile(self, *, unavailable: Sequence[str] = ()) -> RedactionProfile:
        redacted = tuple(sorted(self.redacted_dimensions))
        unavailable_t = tuple(sorted(set(unavailable)))
        if redacted:
            claim = CompletenessClaim.REDACTED
            privacy = PrivacyClass.PUBLIC
        elif unavailable_t:
            claim = CompletenessClaim.PARTIAL
            privacy = PrivacyClass.INTERNAL
        else:
            claim = CompletenessClaim.FULL_STATE
            privacy = PrivacyClass.INTERNAL
        return RedactionProfile(
            privacy_class=privacy,
            redacted_dimensions=redacted,
            unavailable_dimensions=unavailable_t,
            completeness_claim=claim,
        )

    def public_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        return trace.public_view()


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceRecord:
    """Hermetic trace result with a public projection and optional private bodies."""

    public_trace: ExecutionTrace
    public_events: tuple[ProgramEvent, ...]
    observations: tuple[ExecutionObservation, ...]
    states: tuple[ProgramExecutionState, ...]
    policy: TraceCollectionPolicy
    redaction_profile: RedactionProfile
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    capture_profile_cid: str
    status: TraceStatus | str
    cancelled: bool
    bounded: bool
    network_denied: bool
    replayed: bool = False
    accepted_transition_cid: str | None = None
    subject_exception_type: str | None = None
    private_trace: ExecutionTrace | None = None
    raw_bodies: Mapping[str, Any] = field(default_factory=dict)

    SCHEMA: ClassVar[str] = PYTHON_EXECUTION_TRACE_SCHEMA
    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECORD_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_events", tuple(self.public_events))
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(self, "states", tuple(self.states))
        status = (
            self.status.value if isinstance(self.status, TraceStatus) else _nfc(self.status, "status")
        )
        try:
            status = TraceStatus(status).value
        except ValueError as exc:
            raise PythonExecutionTraceError(f"unsupported trace status {status!r}") from exc
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "cancelled", _bool(self.cancelled, "cancelled"))
        object.__setattr__(self, "bounded", _bool(self.bounded, "bounded"))
        object.__setattr__(self, "network_denied", _bool(self.network_denied, "network_denied"))
        object.__setattr__(self, "replayed", _bool(self.replayed, "replayed"))
        if self.accepted_transition_cid is not None:
            raise PythonExecutionTraceError(
                "hermetic tracing never emits an accepted transition"
            )
        if self.cancelled and status != TraceStatus.CANCELLED.value:
            raise PythonExecutionTraceError("cancelled traces must use cancelled status")
        if self.cancelled and self.accepted_transition_cid is not None:
            raise PythonExecutionTraceError("cancellation emits no accepted transition")
        if self.public_trace.includes_raw_bodies:
            raise PythonExecutionTraceError("public traces cannot include raw bodies")
        if str(self.public_trace.privacy_class) not in PUBLIC_PRIVACY_CLASSES and str(
            self.public_trace.privacy_class
        ) != PrivacyClass.PUBLIC.value:
            # public_view always sets public; accept public or internal without raw bodies
            pass
        if str(self.public_trace.privacy_class) == PrivacyClass.PUBLIC.value:
            if self.public_trace.includes_raw_bodies or self.public_trace.raw_execution_state_cids:
                raise PythonExecutionTraceError(
                    "private raw trace bodies never enter public records"
                )
        object.__setattr__(self, "raw_bodies", MappingProxyType(dict(self.raw_bodies)))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "status": self.status,
            "cancelled": self.cancelled,
            "bounded": self.bounded,
            "network_denied": self.network_denied,
            "replayed": self.replayed,
            "accepted_transition_cid": None,
            "public_trace_cid": self.public_trace.execution_trace_cid,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "capture_profile_cid": self.capture_profile_cid,
            "redaction_profile_cid": self.redaction_profile.redaction_profile_cid,
            "includes_raw_bodies": False,
            "privacy_class": PrivacyClass.PUBLIC.value,
            "event_cids": list(self.public_trace.event_cids),
        }

    @property
    def python_execution_trace_cid(self) -> str:
        return program_execution_cid_for(self.identity_payload())

    @property
    def has_private_raw_bodies(self) -> bool:
        return bool(self.raw_bodies)

    @property
    def events(self) -> tuple[ProgramEvent, ...]:
        return self.public_events

    def public_record(self) -> dict[str, Any]:
        """Return the only serialization admitted as a public record."""

        payload = self.identity_payload()
        payload["python_execution_trace_cid"] = self.python_execution_trace_cid
        payload["interface"] = self.INTERFACE
        payload["public_trace"] = self.public_trace.to_dict()
        payload["events"] = [event.to_dict() for event in self.public_events]
        payload["observations"] = [item.to_dict() for item in self.observations]
        payload["redaction_profile"] = self.redaction_profile.to_dict()
        payload["policy"] = self.policy.identity_payload()
        if self.subject_exception_type is not None:
            payload["subject_exception_type"] = self.subject_exception_type
        return payload

    def to_dict(self) -> dict[str, Any]:
        return self.public_record()

    def private_record(self) -> dict[str, Any]:
        """Private companion; callers must not treat this as a public record."""

        payload = self.public_record()
        payload["privacy_class"] = PrivacyClass.PRIVATE.value
        payload["includes_raw_bodies"] = bool(self.raw_bodies)
        payload["raw_bodies"] = dict(self.raw_bodies)
        if self.private_trace is not None:
            payload["private_trace"] = self.private_trace.to_dict()
        return payload


# ---------------------------------------------------------------------------
# Bounded serializers and frame helpers
# ---------------------------------------------------------------------------


def _logical_name(frame: FrameType) -> str:
    module = frame.f_globals.get("__name__", "")
    qualname = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
    if type(module) is str and module and not module.startswith("<"):
        name = f"{module}.{qualname}"
    else:
        name = str(qualname)
    return unicodedata.normalize("NFC", name)


def _code_cid(frame: FrameType) -> str:
    return cid_for_bytes(frame.f_code.co_code)


def _current_opname(frame: FrameType) -> str:
    lasti = frame.f_lasti
    if type(lasti) is not int or lasti < 0:
        return ""
    nearest = ""
    try:
        for instruction in dis.get_instructions(frame.f_code):
            if instruction.offset == lasti:
                return instruction.opname
            if instruction.offset <= lasti:
                nearest = instruction.opname
            else:
                break
    except Exception:
        return nearest
    return nearest


def _is_tracer_frame(frame: FrameType) -> bool:
    filename = frame.f_code.co_filename
    return filename == _TRACER_FILENAME or filename.endswith("python_execution_trace.py")


def _is_selected_external(frame: FrameType) -> str | None:
    name = frame.f_code.co_name
    module = str(frame.f_globals.get("__name__", "") or "")
    if name in _NETWORK_NAMES or module.startswith("socket") or module.startswith("ssl"):
        return "network"
    if name in _SUBPROCESS_NAMES or module.startswith("subprocess"):
        return "subprocess"
    if name in _INSTALLER_NAMES or module.startswith("pip") or module == "ensurepip":
        return "installer"
    if module.split(".", 1)[0] in _DATABASE_MODULES:
        return "database"
    if module.split(".", 1)[0] in _MODEL_MODULES:
        return "model"
    if name == "open" and module in {"builtins", "_io", "io"}:
        return "filesystem"
    return None


def _at_exception_handler(frame: FrameType) -> bool:
    parse = getattr(dis, "_parse_exception_table", None)
    if parse is None:
        return False
    try:
        entries = parse(frame.f_code)
    except Exception:
        return False
    lasti = frame.f_lasti
    for entry in entries:
        target = getattr(entry, "target", None)
        if type(target) is int and target <= lasti <= target + 8:
            return True
    return False


def _return_kind(frame: FrameType) -> str:
    flags = frame.f_code.co_flags
    opname = _current_opname(frame)
    returning = opname in {"RETURN_VALUE", "RETURN_GENERATOR", "RETURN_CONST"}
    if flags & _CO_COROUTINE:
        if returning:
            return EventKind.RETURN.value
        return EventKind.AWAIT.value
    if flags & _CO_ASYNC_GENERATOR:
        if returning:
            return EventKind.RETURN.value
        if opname in _AWAIT_OPS:
            return EventKind.AWAIT.value
        return EventKind.YIELD.value
    if flags & _CO_GENERATOR:
        if returning:
            return EventKind.RETURN.value
        return EventKind.YIELD.value
    if opname in _YIELD_OPS:
        return EventKind.YIELD.value
    if opname in _AWAIT_OPS:
        return EventKind.AWAIT.value
    return EventKind.RETURN.value


def _subject_source_bytes(subject: Callable[..., Any], source: str | bytes | None) -> bytes:
    if isinstance(source, bytes):
        return source
    if isinstance(source, str):
        return unicodedata.normalize("NFC", source).encode("utf-8")
    try:
        text = inspect.getsource(subject)
    except (OSError, TypeError):
        code = getattr(subject, "__code__", None)
        if code is None:
            identity = f"{getattr(subject, '__module__', '')}.{getattr(subject, '__qualname__', type(subject).__name__)}"
            return identity.encode("utf-8")
        return bytes(code.co_code)
    return unicodedata.normalize("NFC", text).encode("utf-8")


def _subject_logical_name(subject: Callable[..., Any]) -> str:
    module = getattr(subject, "__module__", "") or ""
    qualname = getattr(subject, "__qualname__", getattr(subject, "__name__", "subject"))
    if module:
        return unicodedata.normalize("NFC", f"{module}.{qualname}")
    return unicodedata.normalize("NFC", str(qualname))


# ---------------------------------------------------------------------------
# Isolation guards (record-time only)
# ---------------------------------------------------------------------------


class _HermeticDenied(PythonExecutionTraceError):
    """Raised when a denied isolation class is attempted during collection."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


def _install_isolation(policy: TraceCollectionPolicy) -> Callable[[], None]:
    restorers: list[Callable[[], None]] = []

    def forbidden(kind: str) -> Callable[..., Any]:
        def fail(*_args: Any, **_kwargs: Any) -> Any:
            raise _HermeticDenied(kind)

        return fail

    if policy.deny_network:
        import socket

        original_create = socket.create_connection
        original_getaddrinfo = socket.getaddrinfo
        original_socket = socket.socket

        class GuardedSocket(original_socket):  # type: ignore[valid-type,misc]
            def connect(self, *args: Any, **kwargs: Any) -> Any:
                raise _HermeticDenied("network")

            def connect_ex(self, *args: Any, **kwargs: Any) -> Any:
                raise _HermeticDenied("network")

        socket.create_connection = forbidden("network")  # type: ignore[assignment]
        socket.getaddrinfo = forbidden("network")  # type: ignore[assignment]
        socket.socket = GuardedSocket  # type: ignore[misc,assignment]

        def restore_socket() -> None:
            socket.create_connection = original_create
            socket.getaddrinfo = original_getaddrinfo
            socket.socket = original_socket

        restorers.append(restore_socket)

    if policy.deny_subprocess:
        import os
        import subprocess

        originals = {
            "Popen": subprocess.Popen,
            "run": subprocess.run,
            "call": subprocess.call,
            "check_call": subprocess.check_call,
            "check_output": subprocess.check_output,
            "system": os.system,
        }
        subprocess.Popen = forbidden("subprocess")  # type: ignore[misc,assignment]
        subprocess.run = forbidden("subprocess")  # type: ignore[assignment]
        subprocess.call = forbidden("subprocess")  # type: ignore[assignment]
        subprocess.check_call = forbidden("subprocess")  # type: ignore[assignment]
        subprocess.check_output = forbidden("subprocess")  # type: ignore[assignment]
        os.system = forbidden("subprocess")  # type: ignore[assignment]

        def restore_subprocess() -> None:
            subprocess.Popen = originals["Popen"]
            subprocess.run = originals["run"]
            subprocess.call = originals["call"]
            subprocess.check_call = originals["check_call"]
            subprocess.check_output = originals["check_output"]
            os.system = originals["system"]

        restorers.append(restore_subprocess)

    def restore() -> None:
        for restorer in reversed(restorers):
            restorer()

    return restore


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class PythonExecutionTracer:
    """In-process CPython tracer bound to exact tree/source/environment identities."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE

    def __init__(
        self,
        *,
        policy: TraceCollectionPolicy | None = None,
        tree_cid: str | None = None,
        source: str | bytes | None = None,
        environment_binding: Mapping[str, str] | None = None,
        cancellation: TraceCancellation | None = None,
    ) -> None:
        self.policy = policy or TraceCollectionPolicy.hermetic()
        self.redactor = TraceRedactor(self.policy)
        self.cancellation = cancellation
        self._source_override = source
        self._tree_override = tree_cid
        if environment_binding is None:
            bindings = _default_environment_binding()
        else:
            if not isinstance(environment_binding, Mapping):
                raise PythonExecutionTraceError("environment_binding must be a string mapping")
            bindings = {str(key): str(value) for key, value in environment_binding.items()}
            for forbidden in ("hostname", "pid", "wall_clock", "timestamp"):
                if forbidden in bindings:
                    raise PythonExecutionTraceError(
                        f"environment_binding rejects non-semantic field {forbidden}"
                    )
        self.environment_binding = bindings
        self.environment_binding_cid = _environment_cid(bindings)
        self.capture_profile_cid = self.policy.capture_profile_cid
        self._events: list[ProgramEvent] = []
        self._states: list[ProgramExecutionState] = []
        self._raw_bodies: dict[str, Any] = {}
        self._line_events = 0
        self._cancelled = False
        self._bounded = False
        self._network_denied = False
        self._pending_exception: ExceptionSnapshot | None = None
        self._predecessor: str | None = None
        self._tree_cid = ""
        self._source_cid = ""
        self._subject_name = ""
        self._subject_filenames: set[str] = set()
        self._unavailable: set[str] = {"heap"}

    def record(
        self,
        subject: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> PythonExecutionTraceRecord:
        if not callable(subject):
            raise PythonExecutionTraceError("subject must be callable")
        source_bytes = _subject_source_bytes(subject, self._source_override)
        self._source_cid = cid_for_bytes(source_bytes)
        self._tree_cid = self._tree_override or cid_for_structured(
            {
                "schema": PYTHON_EXECUTION_TRACE_SCHEMA + "#tree",
                "source_cid": self._source_cid,
                "subject": _subject_logical_name(subject),
            }
        )
        self._subject_name = _subject_logical_name(subject)
        filenames: set[str] = set()
        code = getattr(subject, "__code__", None)
        if code is not None and code.co_filename:
            filenames.add(code.co_filename)
        try:
            filenames.add(inspect.getfile(subject))
        except (OSError, TypeError):
            pass
        self._subject_filenames = {name for name in filenames if name and name != _TRACER_FILENAME}
        if self.cancellation is not None and self.cancellation.requested:
            self._cancelled = True
            self._emit_unavailable("cancelled")
            return self._finish(subject_exception_type=None)

        restore = _install_isolation(self.policy)
        previous = sys.gettrace()
        subject_exception_type: str | None = None
        try:
            sys.settrace(self._trace)
            try:
                result = subject(*args, **kwargs)
                if inspect.iscoroutine(result):
                    import asyncio

                    asyncio.run(result)
                elif inspect.isasyncgen(result):
                    self._unavailable.add("async_generator")
            except TraceCancellation:
                self._cancelled = True
            except _HermeticDenied as denied:
                kind = denied.kind
                if kind == "network":
                    self._network_denied = True
                self._emit_external(kind, unavailable=True)
            except Exception as exc:
                subject_exception_type = type(exc).__name__
                if self.policy.collect_exceptions and not self._events_full():
                    # Uncaught exceptions still produce a raise if the trace hook did not.
                    if not any(event.event_kind == EventKind.RAISE.value for event in self._events):
                        frame = sys.exc_info()[2].tb_frame if sys.exc_info()[2] is not None else None
                        if frame is not None:
                            self._on_exception(frame, (type(exc), exc, exc.__traceback__))
        finally:
            sys.settrace(previous)
            restore()

        if not self._events:
            self._emit_unavailable("empty_trace")
        return self._finish(subject_exception_type=subject_exception_type)

    def _events_full(self) -> bool:
        return len(self._events) >= self.policy.max_events

    def _should_stop(self) -> bool:
        if self.cancellation is not None and self.cancellation.requested:
            self._cancelled = True
            return True
        if self._events_full():
            self._bounded = True
            self._unavailable.add("remaining_trace")
            return True
        return False

    def _trace(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if _is_tracer_frame(frame):
            return self._trace
        if self._should_stop():
            return None
        try:
            if event == "call":
                self._on_call(frame)
            elif event == "return":
                self._on_return(frame, arg)
            elif event == "exception":
                self._on_exception(frame, arg)
            elif event == "line":
                self._on_line(frame)
        except _HermeticDenied as denied:
            kind = denied.kind
            if kind == "network":
                self._network_denied = True
            self._emit_external(kind, unavailable=True, frame=frame)
        except PythonExecutionTraceError:
            raise
        except Exception:
            self._unavailable.add("tracer_internal")
        if self._should_stop():
            return None
        return self._trace

    def _is_subject_frame(self, frame: FrameType) -> bool:
        if _is_tracer_frame(frame):
            return False
        if not self._subject_filenames:
            return True
        return frame.f_code.co_filename in self._subject_filenames

    def _on_call(self, frame: FrameType) -> None:
        external = _is_selected_external(frame)
        if external is not None:
            if self.policy.collect_externals:
                self._emit_external(external, frame=frame)
            if external == "network" and self.policy.deny_network:
                self._network_denied = True
            return
        if not self._is_subject_frame(frame):
            return
        if not self.policy.collect_calls:
            return
        self._emit_event(EventKind.CALL.value, frame, payload={"callee": _logical_name(frame)})

    def _on_return(self, frame: FrameType, arg: Any) -> None:
        if _is_selected_external(frame) or not self._is_subject_frame(frame):
            return
        kind = _return_kind(frame)
        if kind == EventKind.YIELD.value and not self.policy.collect_yields:
            return
        if kind == EventKind.AWAIT.value and not self.policy.collect_awaits:
            return
        if kind == EventKind.RETURN.value and not self.policy.collect_returns:
            return
        payload: dict[str, Any] = {}
        if kind in {EventKind.RETURN.value, EventKind.YIELD.value}:
            bounded, _ = self.redactor.redact_mapping(arg, budget=4)
            payload["value"] = bounded
        elif kind == EventKind.AWAIT.value:
            payload["awaitable"] = type(arg).__name__ if arg is not None else "awaitable"
        self._emit_event(kind, frame, payload=payload)

    def _on_exception(self, frame: FrameType, arg: Any) -> None:
        if not self.policy.collect_exceptions:
            return
        if _is_tracer_frame(frame):
            return
        try:
            self._record_exception(frame, arg)
        except (ProgramExecutionError, PythonExecutionTraceError):
            self._unavailable.add("exception")

    def _record_exception(self, frame: FrameType, arg: Any) -> None:
        exc_type: type[BaseException] | None
        if isinstance(arg, tuple) and arg:
            exc_type = arg[0] if isinstance(arg[0], type) else type(arg[0])
        else:
            exc_type = type(arg) if arg is not None else None
        name = exc_type.__name__ if exc_type is not None else "Exception"
        frames = self._stack_frames(frame)
        snapshot = ExceptionSnapshot(
            language=ADMITTED_LANGUAGE,
            exception_type=name,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=_code_cid(frame),
            environment_binding_cid=self.environment_binding_cid,
            exception_value_summary={"type": name, "bounded": True},
            traceback_stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
            future_execution=False,
            completeness_claim=CompletenessClaim.PARTIAL,
            unavailable_dimensions=("exception_value",),
        )
        self._pending_exception = snapshot
        inner = frames[0] if frames else None
        if inner is not None:
            frames = (
                StackFrameState(
                    ordinal=inner.ordinal,
                    language=inner.language,
                    tree_cid=inner.tree_cid,
                    source_cid=inner.source_cid,
                    code_cid=inner.code_cid,
                    environment_binding_cid=inner.environment_binding_cid,
                    logical_name=inner.logical_name,
                    line=inner.line,
                    column=inner.column,
                    state_summary=inner.state_summary,
                    exception_snapshot_cid=snapshot.exception_snapshot_cid,
                    handler_state_cid=inner.handler_state_cid,
                    exception_active=True,
                    handler_active=inner.handler_active,
                    redacted_dimensions=inner.redacted_dimensions,
                    unavailable_dimensions=inner.unavailable_dimensions,
                    completeness_claim=CompletenessClaim.PARTIAL,
                    privacy_class=inner.privacy_class,
                ),
            ) + frames[1:]
        self._emit_event(
            EventKind.RAISE.value,
            frame,
            payload={"exception_type": name},
            frames=frames,
            exception=snapshot,
        )

    def _on_line(self, frame: FrameType) -> None:
        if self._pending_exception is not None and self.policy.collect_handlers:
            if self._is_subject_frame(frame) or _at_exception_handler(frame):
                self._emit_handler(frame)
                self._pending_exception = None
        if not self.policy.collect_lines:
            return
        if not self._is_subject_frame(frame):
            return
        if self._line_events >= self.policy.max_line_events:
            self._unavailable.add("line_detail")
            self._bounded = True
            return
        self._line_events += 1
        self._emit_event(
            EventKind.LINE.value,
            frame,
            payload={"line": frame.f_lineno},
        )

    def _emit_handler(self, frame: FrameType) -> None:
        exception = self._pending_exception
        try:
            frames = self._stack_frames(frame)
            handler = HandlerState(
                language=ADMITTED_LANGUAGE,
                handler_kind=HandlerKind.EXCEPT,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                code_cid=_code_cid(frame),
                environment_binding_cid=self.environment_binding_cid,
                logical_name=_logical_name(frame),
                stack_ordinal=0,
                handler_active=True,
                matching_exception_snapshot_cid=(
                    None if exception is None else exception.exception_snapshot_cid
                ),
                unavailable_dimensions=() if exception is not None else ("exception",),
            )
            payload = {"handler_kind": HandlerKind.EXCEPT.value}
            self._emit_event(
                EventKind.CATCH.value,
                frame,
                payload=payload,
                frames=frames,
                handler=handler,
                exception=exception,
            )
            if not self._should_stop():
                self._emit_event(
                    EventKind.HANDLER.value,
                    frame,
                    payload=payload,
                    frames=frames,
                    handler=handler,
                    exception=exception,
                )
        except (ProgramExecutionError, PythonExecutionTraceError):
            self._unavailable.add("handler")

    def _emit_external(
        self,
        kind: str,
        *,
        unavailable: bool = False,
        frame: FrameType | None = None,
    ) -> None:
        if self._events_full():
            self._bounded = True
            return
        payload = {"effect": kind, "isolated": True}
        unavailable_dims: tuple[str, ...] = (kind,) if unavailable else ()
        status = ObservationStatus.UNAVAILABLE if unavailable else ObservationStatus.OBSERVED
        claim = CompletenessClaim.UNAVAILABLE if unavailable else CompletenessClaim.PARTIAL
        if unavailable:
            self._unavailable.add(kind)
        try:
            frames = self._stack_frames(frame) if frame is not None else self._synthetic_frames()
            event = self._build_event(
                EventKind.EXTERNAL.value,
                frames=frames,
                payload=payload,
                observation_status=status,
                completeness_claim=claim,
                unavailable_dimensions=unavailable_dims,
                logical_name=self._subject_name,
                line=None if frame is None else frame.f_lineno,
                code_cid=(
                    frames[0].code_cid
                    if frames
                    else cid_for_bytes(self._subject_name.encode("utf-8"))
                ),
            )
            self._commit_event(event, frames)
        except (ProgramExecutionError, PythonExecutionTraceError):
            self._unavailable.add(kind)

    def _emit_unavailable(self, reason: str) -> None:
        self._unavailable.add(reason)
        frames = self._synthetic_frames()
        event = self._build_event(
            EventKind.UNAVAILABLE.value,
            frames=frames,
            payload={"reason": reason},
            observation_status=ObservationStatus.UNAVAILABLE,
            completeness_claim=CompletenessClaim.UNAVAILABLE,
            unavailable_dimensions=tuple(sorted(self._unavailable)),
            logical_name=self._subject_name or "unavailable",
            line=None,
            code_cid=frames[0].code_cid,
        )
        self._commit_event(event, frames)

    def _emit_event(
        self,
        kind: str,
        frame: FrameType,
        *,
        payload: Mapping[str, Any] | None = None,
        frames: Sequence[StackFrameState] | None = None,
        exception: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
    ) -> None:
        if self._events_full():
            self._bounded = True
            self._unavailable.add("remaining_trace")
            return
        try:
            stack = frames if frames is not None else self._stack_frames(frame)
            event = self._build_event(
                kind,
                frames=stack,
                payload=payload or {},
                observation_status=ObservationStatus.OBSERVED,
                completeness_claim=CompletenessClaim.PARTIAL,
                unavailable_dimensions=(),
                logical_name=_logical_name(frame),
                line=frame.f_lineno,
                code_cid=_code_cid(frame),
                exception=exception,
                handler=handler,
            )
            raw: dict[str, Any] = {}
            if self.policy.include_raw_bodies:
                try:
                    raw_locals = dict(frame.f_locals)
                except Exception:
                    raw_locals = {}
                cleaned, _ = self.redactor.redact_mapping(
                    raw_locals, budget=self.policy.max_summary_items
                )
                if isinstance(cleaned, Mapping):
                    raw = dict(cleaned)
            self._commit_event(event, stack, raw_body=raw)
        except (ProgramExecutionError, PythonExecutionTraceError):
            self._unavailable.add("event_body")

    def _build_event(
        self,
        kind: str,
        *,
        frames: Sequence[StackFrameState],
        payload: Mapping[str, Any],
        observation_status: ObservationStatus | str,
        completeness_claim: CompletenessClaim | str,
        unavailable_dimensions: Sequence[str],
        logical_name: str,
        line: int | None,
        code_cid: str,
        exception: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
    ) -> ProgramEvent:
        try:
            redacted_payload = self.redactor.bound_payload(dict(payload))
        except Exception:
            redacted_payload = {"bounded": True}
            self.redactor.redacted_dimensions.add("payload")
        redacted_dims = tuple(sorted(self.redactor.redacted_dimensions))
        unavailable = tuple(sorted(set(unavailable_dimensions) | {"heap"}))
        claim = completeness_claim
        if redacted_dims and str(claim) == CompletenessClaim.FULL_STATE.value:
            claim = CompletenessClaim.REDACTED
        if str(claim) == CompletenessClaim.PARTIAL.value and not (redacted_dims or unavailable):
            unavailable = ("heap",)
        if kind in {EventKind.UNAVAILABLE.value} and not unavailable:
            unavailable = ("event_body",)
            claim = CompletenessClaim.UNAVAILABLE
        privacy = PrivacyClass.INTERNAL
        return ProgramEvent(
            event_kind=kind,
            event_origin=EventOrigin.OBSERVED,
            observation_status=observation_status,
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=code_cid,
            environment_binding_cid=self.environment_binding_cid,
            subject_cid=cid_for_bytes(self._subject_name.encode("utf-8")),
            logical_name=logical_name or self._subject_name,
            payload=redacted_payload,
            line=line,
            column=None,
            predecessor_event_cid=self._predecessor,
            stack_frame_cids=tuple(frame.stack_frame_state_cid for frame in frames),
            exception_snapshot_cid=None if exception is None else exception.exception_snapshot_cid,
            handler_state_cid=None if handler is None else handler.handler_state_cid,
            redaction_profile_cid=None,
            redacted_dimensions=redacted_dims,
            unavailable_dimensions=unavailable,
            completeness_claim=claim,
            privacy_class=privacy,
        )

    def _commit_event(
        self,
        event: ProgramEvent,
        frames: Sequence[StackFrameState],
        *,
        raw_body: Mapping[str, Any] | None = None,
    ) -> None:
        self._events.append(event)
        self._predecessor = event.program_event_cid
        if self.policy.include_raw_bodies:
            self._raw_bodies[event.program_event_cid] = dict(raw_body or {})
        try:
            state = assemble_program_execution_state(
                language=ADMITTED_LANGUAGE,
                capture_profile_cid=self.capture_profile_cid,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                environment_binding_cid=self.environment_binding_cid,
                frames=frames,
                observed_state=self.redactor.bound_payload(
                    {"logical_name": event.logical_name, "event_kind": event.event_kind}
                ),
                heap_summary={},
                heap_bound=HeapBound.UNAVAILABLE,
                observation_status=ObservationStatus.OBSERVED,
                completeness_claim=CompletenessClaim.PARTIAL,
                privacy_class=PrivacyClass.INTERNAL,
                includes_raw_bodies=False,
                unavailable_dimensions=("heap",),
            )
            self._states.append(state)
        except ProgramExecutionError:
            self._unavailable.add("execution_state")

    def _stack_frames(self, frame: FrameType | None) -> tuple[StackFrameState, ...]:
        collected: list[FrameType] = []
        current = frame
        while current is not None and len(collected) < self.policy.max_stack_frames:
            if self._is_subject_frame(current):
                collected.append(current)
            current = current.f_back
        if not collected:
            return self._synthetic_frames()
        if current is not None:
            self._unavailable.add("call_stack_tail")
        frames: list[StackFrameState] = []
        for ordinal, item in enumerate(collected):
            summary, redacted = self.redactor.redact_mapping(
                {"function": _logical_name(item), "line": item.f_lineno},
                budget=self.policy.max_summary_items,
            )
            if not isinstance(summary, Mapping):
                summary = {"function": _logical_name(item)}
            claim = CompletenessClaim.PARTIAL
            redacted_dims = redacted
            if redacted_dims:
                claim = CompletenessClaim.REDACTED
            frames.append(
                StackFrameState(
                    ordinal=ordinal,
                    language=ADMITTED_LANGUAGE,
                    tree_cid=self._tree_cid,
                    source_cid=self._source_cid,
                    code_cid=_code_cid(item),
                    environment_binding_cid=self.environment_binding_cid,
                    logical_name=_logical_name(item),
                    line=item.f_lineno if type(item.f_lineno) is int and item.f_lineno >= 0 else 0,
                    column=None,
                    state_summary=dict(summary),
                    redacted_dimensions=redacted_dims,
                    unavailable_dimensions=("heap",),
                    completeness_claim=claim,
                    privacy_class=PrivacyClass.INTERNAL,
                )
            )
        return tuple(frames)

    def _synthetic_frames(self) -> tuple[StackFrameState, ...]:
        code_cid = cid_for_bytes((self._subject_name or "subject").encode("utf-8"))
        return (
            StackFrameState(
                ordinal=0,
                language=ADMITTED_LANGUAGE,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                code_cid=code_cid,
                environment_binding_cid=self.environment_binding_cid,
                logical_name=self._subject_name or "subject",
                line=0,
                column=None,
                state_summary={"synthetic": True},
                unavailable_dimensions=("heap",),
                completeness_claim=CompletenessClaim.PARTIAL,
                privacy_class=PrivacyClass.INTERNAL,
            ),
        )

    def _finish(self, *, subject_exception_type: str | None) -> PythonExecutionTraceRecord:
        if self._cancelled:
            status = TraceStatus.CANCELLED
        elif self._network_denied:
            status = TraceStatus.DENIED
        elif self._bounded:
            status = TraceStatus.BOUNDED
        elif any(event.event_kind == EventKind.UNAVAILABLE.value for event in self._events) and len(
            self._events
        ) == 1:
            status = TraceStatus.UNAVAILABLE
        else:
            status = TraceStatus.COMPLETED
        unavailable = tuple(sorted(self._unavailable))
        redaction = self.redactor.profile(unavailable=unavailable)
        public_events = tuple(self._events)
        observations: list[ExecutionObservation] = []
        for event in public_events:
            if event.observation_admissible:
                try:
                    observations.append(observe_program_event(event))
                except ProgramExecutionError:
                    continue
        claim = CompletenessClaim.PARTIAL
        if redaction.redacted_dimensions:
            claim = CompletenessClaim.REDACTED
        if status is TraceStatus.UNAVAILABLE:
            claim = CompletenessClaim.UNAVAILABLE
        if status is TraceStatus.CANCELLED:
            claim = CompletenessClaim.PARTIAL
            unavailable = tuple(sorted(set(unavailable) | {"remaining_trace", "accepted_transition"}))
        private_trace: ExecutionTrace | None = None
        public_states = tuple(self._states)
        public_trace = assemble_execution_trace(
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self.environment_binding_cid,
            events=public_events,
            states=(),
            redaction=redaction,
            completeness_claim=claim,
            privacy_class=PrivacyClass.PUBLIC,
            includes_raw_bodies=False,
            unavailable_dimensions=unavailable,
        )
        if self.policy.include_raw_bodies and self._raw_bodies:
            private_trace = assemble_execution_trace(
                language=ADMITTED_LANGUAGE,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                environment_binding_cid=self.environment_binding_cid,
                events=public_events,
                states=public_states,
                redaction=redaction,
                completeness_claim=CompletenessClaim.REDACTED,
                privacy_class=PrivacyClass.PRIVATE,
                includes_raw_bodies=True,
                unavailable_dimensions=unavailable,
            )
            public_trace = private_trace.public_view()
        return PythonExecutionTraceRecord(
            public_trace=public_trace,
            public_events=public_events,
            observations=tuple(observations),
            states=public_states,
            policy=self.policy,
            redaction_profile=redaction,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self.environment_binding_cid,
            capture_profile_cid=self.capture_profile_cid,
            status=status,
            cancelled=self._cancelled,
            bounded=self._bounded,
            network_denied=self._network_denied,
            replayed=False,
            accepted_transition_cid=None,
            subject_exception_type=subject_exception_type,
            private_trace=private_trace,
            raw_bodies=dict(self._raw_bodies) if self.policy.include_raw_bodies else {},
        )


def record_python_execution_trace(
    subject: Callable[..., Any],
    /,
    *args: Any,
    policy: TraceCollectionPolicy | None = None,
    tree_cid: str | None = None,
    source: str | bytes | None = None,
    environment_binding: Mapping[str, str] | None = None,
    cancellation: TraceCancellation | None = None,
    **kwargs: Any,
) -> PythonExecutionTraceRecord:
    """Collect a hermetic Python execution trace for ``subject``."""

    tracer = PythonExecutionTracer(
        policy=policy,
        tree_cid=tree_cid,
        source=source,
        environment_binding=environment_binding,
        cancellation=cancellation,
    )
    return tracer.record(subject, *args, **kwargs)


def replay_deterministic_trace(
    record: PythonExecutionTraceRecord | Mapping[str, Any],
) -> PythonExecutionTraceRecord:
    """Reconstitute a promised trace without re-executing the subject.

    Replay is identity-preserving for the public event sequence and never
    admits an accepted transition.  Private raw bodies are not required and
    are never introduced into the public record.
    """

    if isinstance(record, PythonExecutionTraceRecord):
        public = record.public_record()
        events = record.public_events
        policy = record.policy
        redaction = record.redaction_profile
        tree_cid = record.tree_cid
        source_cid = record.source_cid
        environment_binding_cid = record.environment_binding_cid
        capture_profile_cid = record.capture_profile_cid
        cancelled = record.cancelled
        bounded = record.bounded
        network_denied = record.network_denied
        status = record.status
        subject_exception_type = record.subject_exception_type
        observations = record.observations
        states = record.states
    elif isinstance(record, Mapping):
        public = dict(record)
        if public.get("includes_raw_bodies") is True:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if "raw_bodies" in public:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        raw_events = public.get("events")
        if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes)):
            raise PythonExecutionTraceError("promised replay requires recorded events")
        events = tuple(ProgramEvent.from_dict(item) for item in raw_events)
        policy_payload = public.get("policy") or {}
        if not isinstance(policy_payload, Mapping):
            raise PythonExecutionTraceError("promised replay requires a collection policy")
        allowed = {
            "collect_calls",
            "collect_returns",
            "collect_lines",
            "collect_exceptions",
            "collect_handlers",
            "collect_yields",
            "collect_awaits",
            "collect_externals",
            "deny_network",
            "deny_subprocess",
            "include_raw_bodies",
            "max_events",
            "max_line_events",
            "max_stack_frames",
            "max_payload_bytes",
            "max_summary_items",
            "privacy_class",
        }
        policy = TraceCollectionPolicy(
            **{key: policy_payload[key] for key in allowed if key in policy_payload}
        )
        redaction_payload = public.get("redaction_profile")
        if isinstance(redaction_payload, Mapping):
            redaction = RedactionProfile.from_dict(redaction_payload)
        else:
            redaction = RedactionProfile(
                privacy_class=PrivacyClass.PUBLIC,
                redacted_dimensions=(),
                unavailable_dimensions=("heap",),
                completeness_claim=CompletenessClaim.PARTIAL,
            )
        tree_cid = str(public.get("tree_cid") or "")
        source_cid = str(public.get("source_cid") or "")
        environment_binding_cid = str(public.get("environment_binding_cid") or "")
        capture_profile_cid = str(public.get("capture_profile_cid") or policy.capture_profile_cid)
        cancelled = bool(public.get("cancelled"))
        bounded = bool(public.get("bounded"))
        network_denied = bool(public.get("network_denied"))
        status = str(public.get("status") or TraceStatus.COMPLETED.value)
        subject_exception_type = public.get("subject_exception_type")
        if subject_exception_type is not None:
            subject_exception_type = str(subject_exception_type)
        observations = tuple(
            observe_program_event(event) for event in events if event.observation_admissible
        )
        states = ()
    else:
        raise PythonExecutionTraceError("replay requires a recorded trace or public mapping")

    if cancelled:
        status = TraceStatus.CANCELLED.value
    promised_trace: ExecutionTrace | None = None
    raw_trace = public.get("public_trace")
    if isinstance(record, PythonExecutionTraceRecord):
        promised_trace = record.public_trace
    elif isinstance(raw_trace, Mapping):
        promised_trace = ExecutionTrace.from_dict(raw_trace)
    unavailable = tuple(sorted(set(public_trace_unavailable(events)) | {"heap"}))
    if promised_trace is not None:
        unavailable = tuple(sorted(set(unavailable) | set(promised_trace.unavailable_dimensions)))
    if cancelled:
        unavailable = tuple(sorted(set(unavailable) | {"remaining_trace", "accepted_transition"}))
    claim: CompletenessClaim | str = CompletenessClaim.PARTIAL
    if promised_trace is not None:
        claim = promised_trace.completeness_claim
    elif redaction.redacted_dimensions:
        claim = CompletenessClaim.REDACTED
    try:
        replayed_trace = assemble_execution_trace(
            language=ADMITTED_LANGUAGE,
            tree_cid=tree_cid,
            source_cid=source_cid,
            environment_binding_cid=environment_binding_cid,
            events=events,
            states=(),
            redaction=redaction,
            completeness_claim=claim,
            privacy_class=PrivacyClass.PUBLIC,
            includes_raw_bodies=False,
            unavailable_dimensions=unavailable,
        )
    except ProgramExecutionError:
        if promised_trace is None:
            raise
        replayed_trace = promised_trace
    if promised_trace is not None:
        if tuple(event.program_event_cid for event in events) != tuple(promised_trace.event_cids):
            raise PythonExecutionTraceError("promised replay event identity diverged")
        replayed_trace = promised_trace
        if promised_trace.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
    replayed = PythonExecutionTraceRecord(
        public_trace=replayed_trace,
        public_events=tuple(events),
        observations=tuple(observations),
        states=tuple(states),
        policy=policy,
        redaction_profile=redaction,
        tree_cid=tree_cid,
        source_cid=source_cid,
        environment_binding_cid=environment_binding_cid,
        capture_profile_cid=capture_profile_cid,
        status=status,
        cancelled=cancelled,
        bounded=bounded,
        network_denied=network_denied,
        replayed=True,
        accepted_transition_cid=None,
        subject_exception_type=subject_exception_type,
        private_trace=None,
        raw_bodies={},
    )
    if cancelled and replayed.accepted_transition_cid is not None:
        raise PythonExecutionTraceError("cancellation emits no accepted transition")
    return replayed


def public_trace_unavailable(events: Sequence[ProgramEvent]) -> set[str]:
    unavailable: set[str] = set()
    for event in events:
        unavailable.update(event.unavailable_dimensions)
    return unavailable


__all__ = [
    "ADMITTED_LANGUAGE",
    "DEFAULT_MAX_EVENTS",
    "DEFAULT_MAX_LINE_EVENTS",
    "DEFAULT_MAX_PAYLOAD_BYTES",
    "IMPORT_DATABASE_OPENED",
    "IMPORT_INSTALLER_INVOKED",
    "IMPORT_MODEL_LOADED",
    "IMPORT_NETWORK_PERFORMED",
    "IMPORT_REPO_SCAN_PERFORMED",
    "IMPORT_SOCKET_OPENED",
    "IMPORT_SUBPROCESS_PERFORMED",
    "IMPORT_WATCHER_STARTED",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "PYTHON_EXECUTION_TRACE_RECORD_INTERFACE",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "PythonExecutionTraceError",
    "PythonExecutionTraceRecord",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCollectionPolicy",
    "TraceRedactor",
    "TraceStatus",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
