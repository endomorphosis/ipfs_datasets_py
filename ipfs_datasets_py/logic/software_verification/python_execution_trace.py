"""Hermetic Python execution tracing for SAWM-008.

This module is the datasets collection adapter for ``ExecutionTrace@1``.  It
records admitted call, return, line, exception, handler, yield, await, and
selected external events under an exact tree, source, and environment binding.

Normative constraints:

* Importing this module never opens a network socket, installer, subprocess,
  database, repository scan, filesystem watcher, model, or trace hook.
* Collection is in-process and isolation-preserving.  Arbitrary shell tracing
  is not provided.  Operational acceptance is never persisted here.
* Event payloads are bounded summaries.  Secret and non-semantic fields are
  stripped before any public or private contract record is assembled.
* Private raw trace bodies never enter public records.
* Cancellation emits no accepted transition.
* Line and basic-block detail is policy-bounded.  Nondeterministic external
  effects are explicit observations or typed unavailable.
* Promised deterministic replay re-collects the same subject under the same
  policy and compares public trace identity; it does not invent hashes.
"""

from __future__ import annotations

import builtins
import dis
import functools
import inspect
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import CodeType, FrameType, MappingProxyType, MethodType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    EventOrigin,
    ExceptionSnapshot,
    ExecutionObservation,
    ExecutionTrace,
    FORBIDDEN_FIELD_MARKERS,
    HandlerKind,
    HandlerState,
    HeapBound,
    MAX_METADATA_BYTES,
    MAX_SAFE_INTEGER,
    MAX_TEXT_CHARS,
    ObservationStatus,
    PrivacyClass,
    ProgramEvent,
    ProgramExecutionError,
    ProgramExecutionState,
    RedactionProfile,
    SECRET_FIELD_MARKERS,
    StackFrameState,
    assemble_execution_trace,
    assemble_program_execution_state,
    observe_program_event,
    public_execution_view,
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PYTHON_EXECUTION_TRACER_INTERFACE: Final[str] = "PythonExecutionTracer@1"
TRACE_COLLECTION_POLICY_INTERFACE: Final[str] = "TraceCollectionPolicy@1"
TRACE_REDACTOR_INTERFACE: Final[str] = "TraceRedactor@1"
TRACE_CANCELLATION_INTERFACE: Final[str] = "TraceCancellation@1"
PYTHON_EXECUTION_TRACE_RECORD_INTERFACE: Final[str] = "PythonExecutionTraceRecord@1"
PYTHON_EXECUTION_TRACE_REPLAY_INTERFACE: Final[str] = "PythonExecutionTraceReplay@1"

TRACE_COLLECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-policy@1"
)
TRACE_CANCELLATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-cancellation@1"
)
TRACE_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-environment@1"
)
TRACE_CODE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-code@1"
)
TRACE_TREE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-tree@1"
)
TRACE_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-subject@1"
)
TRACE_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-trace-record@1"
)
TRACE_REPLAY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-trace-replay@1"
)

ADMITTED_LANGUAGE: Final[str] = "python"
TRACER_VERSION: Final[str] = "1"

# Importing this module must remain a no-op against every denied surface.
IMPORT_SCAN_PERFORMED: Final[bool] = False
IMPORT_NETWORK_PERFORMED: Final[bool] = False
IMPORT_SOCKET_OPENED: Final[bool] = False
IMPORT_SUBPROCESS_SPAWNED: Final[bool] = False
IMPORT_INSTALLER_INVOKED: Final[bool] = False
IMPORT_DATABASE_OPENED: Final[bool] = False
IMPORT_WATCHER_STARTED: Final[bool] = False
IMPORT_MODEL_LOADED: Final[bool] = False
IMPORT_TRACE_HOOKS_INSTALLED: Final[bool] = False

DEFAULT_MAX_EVENTS: Final[int] = 8_192
DEFAULT_MAX_LINE_EVENTS: Final[int] = 2_048
DEFAULT_MAX_STACK_FRAMES: Final[int] = 64
DEFAULT_MAX_PAYLOAD_BYTES: Final[int] = 4_096
DEFAULT_MAX_STRING_CHARS: Final[int] = 256
DEFAULT_MAX_LOCALS: Final[int] = 32
DEFAULT_MAX_COLLECTION_DEPTH: Final[int] = 3

ADMITTED_EVENT_KINDS: Final[frozenset[str]] = frozenset(item.value for item in EventKind)
DEFAULT_EVENT_KINDS: Final[tuple[str, ...]] = (
    EventKind.CALL.value,
    EventKind.RETURN.value,
    EventKind.LINE.value,
    EventKind.RAISE.value,
    EventKind.CATCH.value,
    EventKind.HANDLER.value,
    EventKind.YIELD.value,
    EventKind.AWAIT.value,
    EventKind.ENTER.value,
    EventKind.EXIT.value,
    EventKind.EXTERNAL.value,
)

_YIELD_OPCODES: Final[frozenset[str]] = frozenset({"YIELD_VALUE", "YIELD_FROM"})
_AWAIT_OPCODES: Final[frozenset[str]] = frozenset(
    {"GET_AWAITABLE", "SEND", "YIELD_VALUE", "YIELD_FROM", "BEFORE_ASYNC_WITH"}
)
_EXCEPT_STAR_OPCODES: Final[frozenset[str]] = frozenset(
    {"CHECK_EG_MATCH", "PREP_RERAISE_STAR"}
)

_DENIED_MODULE_ATTRS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "socket": ("socket", "create_connection", "create_server", "socketpair", "fromfd"),
        "_socket": ("socket", "socketpair", "fromfd"),
        "ssl": ("wrap_socket", "SSLContext"),
        "subprocess": ("Popen", "run", "call", "check_call", "check_output", "getoutput"),
        "os": ("system", "popen", "execv", "execve", "execl", "posix_spawn", "spawnv"),
        "sqlite3": ("connect",),
        "duckdb": ("connect",),
        "urllib.request": ("urlopen",),
        "http.client": ("HTTPConnection", "HTTPSConnection"),
        "pip": ("main",),
        "ensurepip": ("_run_pip", "bootstrap"),
        "watchdog.observers": ("Observer",),
        "transformers": ("pipeline",),
        "torch": ("load",),
    }
)
_DENIED_ROOTS: Final[frozenset[str]] = frozenset(
    root.split(".", 1)[0] for root in _DENIED_MODULE_ATTRS
)
_DENIED_FUNCTION_NAMES: Final[frozenset[str]] = frozenset(
    {
        "socket",
        "create_connection",
        "create_server",
        "socketpair",
        "urlopen",
        "Popen",
        "system",
        "popen",
        "pipeline",
    }
)

_TRACER_FILENAME: Final[str] = __file__
_SELF_SKIP_PREFIXES: Final[tuple[str, ...]] = (
    "ipfs_datasets_py.logic.software_verification.python_execution_trace",
    "ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution",
    "ipfs_datasets_py.logic.software_contracts.content",
)


class PythonExecutionTraceError(ValueError):
    """Raised when tracing policy, replay, or bindings are unsound."""


class _CollectionAbort(BaseException):
    """Internal abort that ``except Exception`` in a subject cannot swallow."""


class _CancelledAbort(_CollectionAbort):
    """Collection cancelled; never an accepted transition."""


class _DeniedAbort(_CollectionAbort):
    """Hermetic isolation denied an external effect."""

    def __init__(self, effect: str) -> None:
        super().__init__(effect)
        self.effect = effect


class TraceOutcome(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DENIED = "denied"
    RAISED = "raised"
    TRUNCATED = "truncated"


# ---------------------------------------------------------------------------
# Small validators
# ---------------------------------------------------------------------------


def _nfc(value: object, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise PythonExecutionTraceError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise PythonExecutionTraceError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise PythonExecutionTraceError(f"{name} contains invalid text")
    return value


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise PythonExecutionTraceError(f"{name} must be a boolean")
    return value


def _positive_int(value: object, name: str, *, minimum: int = 1) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise PythonExecutionTraceError(f"{name} must be an integer >= {minimum}")
    if value > MAX_SAFE_INTEGER:
        raise PythonExecutionTraceError(f"{name} exceeds the safe JSON integer range")
    return value


def _event_kinds(values: object) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise PythonExecutionTraceError("event_kinds must be a sequence of event kinds")
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        kind = item.value if isinstance(item, EventKind) else _nfc(item, "event_kind")
        if kind not in ADMITTED_EVENT_KINDS:
            raise PythonExecutionTraceError(f"event kind {kind!r} is not admitted")
        if kind in seen:
            continue
        seen.add(kind)
        result.append(kind)
    if not result:
        raise PythonExecutionTraceError("event_kinds must not be empty")
    return tuple(sorted(result))


def _string_mapping(value: object, name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PythonExecutionTraceError(f"{name} must be a string mapping")
    result: dict[str, str] = {}
    for key, item in value.items():
        result[_nfc(key, f"{name} key")] = _nfc(item, f"{name} value", empty=True)
    return result


def _environment_cid(bindings: Mapping[str, str]) -> str:
    items = [{"key": key, "value": bindings[key]} for key in sorted(bindings)]
    return cid_for_structured({"schema": TRACE_ENVIRONMENT_SCHEMA, "bindings": items})


def _default_environment() -> dict[str, str]:
    implementation = getattr(sys.implementation, "name", "unknown")
    return {
        "implementation": _nfc(str(implementation), "implementation"),
        "language": ADMITTED_LANGUAGE,
        "python_major": str(sys.version_info.major),
        "python_minor": str(sys.version_info.minor),
    }


def _unwrap_subject(subject: Callable[..., Any]) -> Callable[..., Any]:
    current: Any = subject
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, functools.partial):
            current = current.func
            continue
        if isinstance(current, MethodType):
            current = current.__func__
            continue
        wrapped = getattr(current, "__wrapped__", None)
        if wrapped is not None and wrapped is not current:
            current = wrapped
            continue
        break
    if not callable(current):
        raise PythonExecutionTraceError("subject must be callable")
    return current


def _code_of(subject: Callable[..., Any]) -> CodeType | None:
    code = getattr(subject, "__code__", None)
    return code if isinstance(code, CodeType) else None


def _subject_source_bytes(
    subject: Callable[..., Any], source_text: str | None
) -> bytes:
    if source_text is not None:
        return _nfc(source_text, "source_text").encode("utf-8")
    try:
        text = inspect.getsource(subject)
    except (OSError, TypeError, SyntaxError):
        text = ""
    if text:
        return text.encode("utf-8")
    code = _code_of(subject)
    if code is not None:
        return bytes(code.co_code)
    raise PythonExecutionTraceError("subject source identity is unavailable")


def _qualname_of(subject: Callable[..., Any]) -> str:
    name = getattr(subject, "__qualname__", None) or getattr(subject, "__name__", None)
    module = getattr(subject, "__module__", None) or ""
    if not name:
        code = _code_of(subject)
        name = getattr(code, "co_qualname", None) or (code.co_name if code else "subject")
    label = str(name)
    if module and module not in {"builtins", "__main__"} and not label.startswith(f"{module}."):
        label = f"{module}.{label}"
    return _nfc(label[:MAX_TEXT_CHARS], "logical_name")


def _frame_qualname(frame: FrameType) -> str:
    code = frame.f_code
    name = getattr(code, "co_qualname", code.co_name)
    module = frame.f_globals.get("__name__", "") if isinstance(frame.f_globals, dict) else ""
    label = str(name)
    if module and not label.startswith(f"{module}."):
        label = f"{module}.{label}"
    return label[:MAX_TEXT_CHARS]


def _opcode_at(code: CodeType, lasti: int) -> str:
    if lasti < 0:
        return ""
    previous = ""
    try:
        for instruction in dis.get_instructions(code):
            offset = instruction.offset
            if offset == lasti:
                return instruction.opname
            if offset > lasti:
                return previous
            previous = instruction.opname
    except (TypeError, ValueError, RuntimeError):
        return previous
    return previous


def _is_yield(frame: FrameType, event: str) -> bool:
    if event != "return":
        return False
    flags = frame.f_code.co_flags
    if not (flags & (inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR)):
        return False
    opcode = _opcode_at(frame.f_code, frame.f_lasti)
    if opcode in _YIELD_OPCODES:
        return True
    return opcode not in {"RETURN_VALUE", "RETURN_CONST", "RETURN_GENERATOR"}


def _is_await(frame: FrameType, event: str) -> bool:
    if event != "return":
        return False
    flags = frame.f_code.co_flags
    if not (flags & inspect.CO_COROUTINE):
        return False
    opcode = _opcode_at(frame.f_code, frame.f_lasti)
    if opcode in _YIELD_OPCODES or opcode in _AWAIT_OPCODES:
        return True
    return opcode not in {"RETURN_VALUE", "RETURN_CONST"}


def _secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in SECRET_FIELD_MARKERS or lowered in FORBIDDEN_FIELD_MARKERS:
        return True
    return any(marker in lowered for marker in SECRET_FIELD_MARKERS)


# ---------------------------------------------------------------------------
# Bounded summarization / redaction
# ---------------------------------------------------------------------------


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit]


def _summarize_value(
    value: Any,
    *,
    string_limit: int,
    depth: int,
    redactor: "TraceRedactor",
) -> Any:
    if depth < 0:
        return {"type": type(value).__name__, "unavailable": "depth"}
    value_type = type(value)
    if value is None or value_type is bool:
        return value
    if value_type is int and not isinstance(value, bool):
        if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
            return {"type": "int", "unavailable": "overflow"}
        return value
    if value_type is str:
        return _truncate_text(value, string_limit)
    if value_type is float:
        return {"type": "float", "unavailable": "non_integer"}
    if isinstance(value, Mapping):
        items: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= DEFAULT_MAX_LOCALS:
                break
            if type(key) is not str:
                continue
            if redactor.is_secret_key(key):
                continue
            items[key] = _summarize_value(
                item, string_limit=string_limit, depth=depth - 1, redactor=redactor
            )
        return items
    if isinstance(value, (list, tuple)):
        limited = list(value)[:DEFAULT_MAX_LOCALS]
        return [
            _summarize_value(item, string_limit=string_limit, depth=depth - 1, redactor=redactor)
            for item in limited
        ]
    return {"type": value_type.__name__, "unavailable": "opaque"}


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


def _bound_payload(payload: Mapping[str, Any], *, max_bytes: int) -> dict[str, Any]:
    prepared = _thaw(payload)
    encoded = canonical_dag_json_bytes(prepared)
    if len(encoded) <= max_bytes and len(encoded) <= MAX_METADATA_BYTES:
        return prepared
    return {"unavailable": "payload_bound", "bounded": True}


def _locals_summary(
    frame: FrameType,
    *,
    redactor: "TraceRedactor",
    string_limit: int,
    capture_locals: bool,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if not capture_locals:
        return {}, ("locals",)
    try:
        raw_locals = frame.f_locals
    except (AttributeError, RuntimeError, SystemError):
        return {}, ("locals",)
    if not isinstance(raw_locals, Mapping):
        return {}, ("locals",)
    redacted: list[str] = []
    summary: dict[str, Any] = {}
    for index, (key, item) in enumerate(raw_locals.items()):
        if index >= DEFAULT_MAX_LOCALS:
            break
        if type(key) is not str or key.startswith("__"):
            continue
        if redactor.is_secret_key(key):
            redacted.append("secrets")
            continue
        summary[key] = _summarize_value(
            item,
            string_limit=string_limit,
            depth=DEFAULT_MAX_COLLECTION_DEPTH,
            redactor=redactor,
        )
    return summary, tuple(sorted(set(redacted)))


# ---------------------------------------------------------------------------
# Policy, cancellation, redactor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Closed collection policy: admitted events, bounds, and isolation."""

    language: str = ADMITTED_LANGUAGE
    event_kinds: Sequence[str] = DEFAULT_EVENT_KINDS
    collect_line_events: bool = True
    capture_locals: bool = True
    include_raw_bodies: bool = False
    deny_network: bool = True
    deny_subprocess: bool = True
    deny_installer: bool = True
    deny_database: bool = True
    deny_watchers: bool = True
    deny_model_loads: bool = True
    max_events: int = DEFAULT_MAX_EVENTS
    max_line_events: int = DEFAULT_MAX_LINE_EVENTS
    max_stack_frames: int = DEFAULT_MAX_STACK_FRAMES
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
    max_string_chars: int = DEFAULT_MAX_STRING_CHARS
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL

    SCHEMA: ClassVar[str] = TRACE_COLLECTION_POLICY_SCHEMA
    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE
    VERSION: ClassVar[str] = TRACER_VERSION

    def __post_init__(self) -> None:
        language = _nfc(self.language, "language")
        if language != ADMITTED_LANGUAGE:
            raise PythonExecutionTraceError(
                f"language {language!r} is typed unavailable; Python only"
            )
        object.__setattr__(self, "language", language)
        kinds = _event_kinds(self.event_kinds)
        collect_line = _bool(self.collect_line_events, "collect_line_events")
        if not collect_line:
            kinds = tuple(kind for kind in kinds if kind != EventKind.LINE.value)
            if not kinds:
                raise PythonExecutionTraceError("event_kinds must not be empty")
        object.__setattr__(self, "event_kinds", kinds)
        object.__setattr__(self, "collect_line_events", collect_line)
        object.__setattr__(self, "capture_locals", _bool(self.capture_locals, "capture_locals"))
        object.__setattr__(
            self, "include_raw_bodies", _bool(self.include_raw_bodies, "include_raw_bodies")
        )
        object.__setattr__(self, "deny_network", _bool(self.deny_network, "deny_network"))
        object.__setattr__(self, "deny_subprocess", _bool(self.deny_subprocess, "deny_subprocess"))
        object.__setattr__(self, "deny_installer", _bool(self.deny_installer, "deny_installer"))
        object.__setattr__(self, "deny_database", _bool(self.deny_database, "deny_database"))
        object.__setattr__(self, "deny_watchers", _bool(self.deny_watchers, "deny_watchers"))
        object.__setattr__(self, "deny_model_loads", _bool(self.deny_model_loads, "deny_model_loads"))
        object.__setattr__(self, "max_events", _positive_int(self.max_events, "max_events"))
        object.__setattr__(
            self, "max_line_events", _positive_int(self.max_line_events, "max_line_events")
        )
        object.__setattr__(
            self, "max_stack_frames", _positive_int(self.max_stack_frames, "max_stack_frames")
        )
        object.__setattr__(
            self,
            "max_payload_bytes",
            _positive_int(self.max_payload_bytes, "max_payload_bytes"),
        )
        if self.max_payload_bytes > MAX_METADATA_BYTES:
            object.__setattr__(self, "max_payload_bytes", MAX_METADATA_BYTES)
        object.__setattr__(
            self,
            "max_string_chars",
            _positive_int(self.max_string_chars, "max_string_chars"),
        )
        privacy = (
            self.privacy_class.value
            if isinstance(self.privacy_class, PrivacyClass)
            else _nfc(self.privacy_class, "privacy_class")
        )
        try:
            privacy = PrivacyClass(privacy).value
        except ValueError as exc:
            raise PythonExecutionTraceError("privacy_class has unsupported value") from exc
        if self.include_raw_bodies and privacy in {PrivacyClass.PUBLIC.value, PrivacyClass.INTERNAL.value}:
            privacy = PrivacyClass.PRIVATE.value
        object.__setattr__(self, "privacy_class", privacy)

    def admits(self, kind: str) -> bool:
        return kind in self.event_kinds

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "language": self.language,
            "event_kinds": list(self.event_kinds),
            "collect_line_events": self.collect_line_events,
            "capture_locals": self.capture_locals,
            "include_raw_bodies": self.include_raw_bodies,
            "deny_network": self.deny_network,
            "deny_subprocess": self.deny_subprocess,
            "deny_installer": self.deny_installer,
            "deny_database": self.deny_database,
            "deny_watchers": self.deny_watchers,
            "deny_model_loads": self.deny_model_loads,
            "max_events": self.max_events,
            "max_line_events": self.max_line_events,
            "max_stack_frames": self.max_stack_frames,
            "max_payload_bytes": self.max_payload_bytes,
            "max_string_chars": self.max_string_chars,
            "privacy_class": self.privacy_class,
            "version": self.VERSION,
        }

    @property
    def trace_collection_policy_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["trace_collection_policy_cid"] = self.trace_collection_policy_cid
        return payload

    def isolation_enabled(self) -> bool:
        return any(
            (
                self.deny_network,
                self.deny_subprocess,
                self.deny_installer,
                self.deny_database,
                self.deny_watchers,
                self.deny_model_loads,
            )
        )


class TraceCancellation:
    """Mutable cancellation token.  A cancelled collection never accepts."""

    INTERFACE: ClassVar[str] = TRACE_CANCELLATION_INTERFACE
    SCHEMA: ClassVar[str] = TRACE_CANCELLATION_SCHEMA
    __slots__ = ("_requested", "_reason")

    def __init__(self, reason: str = "not_requested") -> None:
        self._requested = False
        self._reason = _nfc(reason, "cancellation reason") if reason else "not_requested"

    def cancel(self, reason: str = "cancelled") -> None:
        self._requested = True
        self._reason = _nfc(reason, "cancellation reason") if reason else "cancelled"

    @property
    def requested(self) -> bool:
        return self._requested

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def accepted_transition(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "requested": self._requested,
            "reason": self._reason,
            "accepted_transition": False,
        }


class TraceRedactor:
    """Strip secrets and project public records without raw bodies."""

    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE

    def __init__(
        self,
        *,
        secret_markers: Sequence[str] | None = None,
        profile: RedactionProfile | None = None,
    ) -> None:
        extra = tuple(secret_markers or ())
        markers = set(SECRET_FIELD_MARKERS) | set(FORBIDDEN_FIELD_MARKERS)
        for item in extra:
            markers.add(_nfc(item, "secret marker").lower())
        self.secret_markers = frozenset(markers)
        self.profile = profile

    def is_secret_key(self, key: str) -> bool:
        lowered = key.lower().replace("-", "_")
        if lowered in self.secret_markers:
            return True
        return any(marker in lowered for marker in SECRET_FIELD_MARKERS)

    def redact_mapping(self, value: Mapping[str, Any] | None) -> tuple[dict[str, Any], tuple[str, ...]]:
        if not value:
            return {}, ()
        redacted: set[str] = set()
        result: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                continue
            if self.is_secret_key(key):
                redacted.add("secrets")
                continue
            if isinstance(item, Mapping):
                child, child_redacted = self.redact_mapping(item)
                result[key] = child
                redacted.update(child_redacted)
            else:
                result[key] = item
        return result, tuple(sorted(redacted))

    def public_state(self, state: ProgramExecutionState) -> ProgramExecutionState:
        return public_execution_view(state)

    def public_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        return trace.public_view()

    def public_record(self, record: "PythonExecutionTraceRecord") -> dict[str, Any]:
        return record.public_record()

    def redaction_profile(self, dimensions: Sequence[str]) -> RedactionProfile | None:
        unique = tuple(sorted(set(dimensions)))
        if not unique and self.profile is None:
            return None
        if self.profile is not None:
            merged = tuple(sorted(set(self.profile.redacted_dimensions) | set(unique)))
            unavailable = self.profile.unavailable_dimensions
            privacy = self.profile.privacy_class
        else:
            merged = unique
            unavailable = ()
            privacy = PrivacyClass.INTERNAL
        if not merged and not unavailable:
            return None
        claim = CompletenessClaim.REDACTED if merged else CompletenessClaim.PARTIAL
        return RedactionProfile(
            privacy_class=privacy,
            redacted_dimensions=merged,
            unavailable_dimensions=unavailable,
            completeness_claim=claim,
        )


# ---------------------------------------------------------------------------
# Lightweight facts collected under the trace hook
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _FrameFact:
    ordinal: int
    qualname: str
    filename: str
    line: int | None
    code: CodeType
    locals_summary: Mapping[str, Any]
    redacted_dimensions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _EventFact:
    kind: str
    qualname: str
    filename: str
    line: int | None
    payload: Mapping[str, Any]
    frames: tuple[_FrameFact, ...]
    exception_type: str | None = None
    handler_kind: str | None = None
    redacted_dimensions: tuple[str, ...] = ()
    unavailable_dimensions: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceRecord:
    """Sealed collection result with explicit public/private separation."""

    policy: TraceCollectionPolicy
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    subject_cid: str
    events: tuple[ProgramEvent, ...]
    observations: tuple[ExecutionObservation, ...]
    frames: tuple[StackFrameState, ...]
    states: tuple[ProgramExecutionState, ...]
    public_trace: ExecutionTrace
    private_trace: ExecutionTrace
    cancellation: Mapping[str, Any]
    accepted_transition: bool
    outcome: str
    result_summary: Mapping[str, Any]
    unavailable_dimensions: tuple[str, ...]
    completeness_claim: str
    redaction_profile_cid: str | None = None
    exception_snapshots: tuple[ExceptionSnapshot, ...] = ()
    handler_states: tuple[HandlerState, ...] = ()

    SCHEMA: ClassVar[str] = TRACE_RECORD_SCHEMA
    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECORD_INTERFACE

    def public_record(self) -> dict[str, Any]:
        """Public projection: no private raw bodies and no accepted cancel."""

        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "accepted_transition": self.accepted_transition,
            "cancellation": dict(self.cancellation),
            "completeness_claim": self.completeness_claim,
            "environment_binding_cid": self.environment_binding_cid,
            "includes_raw_bodies": False,
            "observations": [item.to_dict() for item in self.observations],
            "outcome": self.outcome,
            "policy_cid": self.policy.trace_collection_policy_cid,
            "public_events": [item.to_dict() for item in self.events],
            "public_trace": self.public_trace.to_dict(),
            "redaction_profile_cid": self.redaction_profile_cid,
            "result_summary": dict(self.result_summary),
            "source_cid": self.source_cid,
            "subject_cid": self.subject_cid,
            "tree_cid": self.tree_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.public_record()
        payload["private_trace"] = self.private_trace.to_dict()
        payload["private_states"] = [item.to_dict() for item in self.states]
        payload["includes_raw_bodies"] = self.private_trace.includes_raw_bodies
        return payload


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceReplay:
    """Receipt of a promised deterministic re-collection."""

    previous_public_trace_cid: str
    replayed_public_trace_cid: str
    matched: bool
    unavailable_dimensions: tuple[str, ...]
    accepted_transition: bool
    record: PythonExecutionTraceRecord

    SCHEMA: ClassVar[str] = TRACE_REPLAY_SCHEMA
    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_REPLAY_INTERFACE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "accepted_transition": self.accepted_transition,
            "matched": self.matched,
            "previous_public_trace_cid": self.previous_public_trace_cid,
            "public_record": self.record.public_record(),
            "replayed_public_trace_cid": self.replayed_public_trace_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }


# ---------------------------------------------------------------------------
# Isolation guard (collection-time only)
# ---------------------------------------------------------------------------


def _effect_denied(policy: TraceCollectionPolicy, module_name: str, attr: str) -> bool:
    root = module_name.split(".", 1)[0]
    if policy.deny_network and root in {"socket", "_socket", "ssl", "urllib", "http", "requests"}:
        return True
    if policy.deny_subprocess and (root in {"subprocess"} or (root == "os" and attr in {
        "system", "popen", "execv", "execve", "execl", "posix_spawn", "spawnv",
    })):
        return True
    if policy.deny_installer and root in {"pip", "ensurepip"}:
        return True
    if policy.deny_database and root in {"sqlite3", "duckdb", "psycopg2", "pymongo"}:
        return True
    if policy.deny_watchers and root in {"watchdog"}:
        return True
    if policy.deny_model_loads and root in {"transformers", "torch", "tensorflow"}:
        return True
    return False


class _IsolationGuard:
    def __init__(self, policy: TraceCollectionPolicy, on_denied: Callable[[str], None]) -> None:
        self.policy = policy
        self._on_denied = on_denied
        self._restore: list[tuple[Any, str, Any]] = []

    def __enter__(self) -> "_IsolationGuard":
        if not self.policy.isolation_enabled():
            return self
        for name, module in list(sys.modules.items()):
            self._wrap_loaded(name, module)
        original_import = builtins.__import__

        def wrapped_import(
            name: str,
            globals: Any = None,
            locals: Any = None,
            fromlist: Any = (),
            level: int = 0,
        ) -> Any:
            module = original_import(name, globals, locals, fromlist, level)
            self._wrap_loaded(name, module)
            if fromlist:
                root = name.split(".", 1)[0] if level == 0 else getattr(module, "__name__", name)
                self._wrap_loaded(str(root), module)
            return module

        self._restore.append((builtins, "__import__", original_import))
        builtins.__import__ = wrapped_import  # type: ignore[assignment]
        return self

    def __exit__(self, *_exc: object) -> bool:
        for obj, attr, original in reversed(self._restore):
            try:
                setattr(obj, attr, original)
            except Exception:
                continue
        self._restore.clear()
        return False

    def _wrap_loaded(self, name: str, module: Any) -> None:
        if module is None:
            return
        attrs = _DENIED_MODULE_ATTRS.get(name)
        if attrs is None:
            root = name.split(".", 1)[0]
            attrs = _DENIED_MODULE_ATTRS.get(root)
            if attrs is None:
                return
        for attr in attrs:
            if not _effect_denied(self.policy, name, attr):
                continue
            if not hasattr(module, attr):
                continue
            original = getattr(module, attr)
            if getattr(original, "_sawm_hermetic_denied", False):
                continue
            effect = f"{name}.{attr}"
            denied = self._denier(effect)
            try:
                setattr(module, attr, denied)
            except Exception:
                continue
            self._restore.append((module, attr, original))

    def _denier(self, effect: str) -> Callable[..., Any]:
        on_denied = self._on_denied

        def denied(*_args: object, **_kwargs: object) -> Any:
            on_denied(effect)
            raise _DeniedAbort(effect)

        denied._sawm_hermetic_denied = True  # type: ignore[attr-defined]
        denied.__name__ = effect.replace(".", "_")
        denied.__qualname__ = effect
        return denied


# ---------------------------------------------------------------------------
# Subject invocation (in-process; no subprocess)
# ---------------------------------------------------------------------------


def _run_generator(generator: Any) -> dict[str, Any]:
    yielded: list[Any] = []
    try:
        for _ in range(DEFAULT_MAX_EVENTS):
            yielded.append(next(generator))
        raise PythonExecutionTraceError("generator did not complete within the event bound")
    except StopIteration as stop:
        return {"returned": _opaque(stop.value), "yielded_count": len(yielded)}


def _run_coroutine(coroutine: Any) -> Any:
    value: Any = None
    for _ in range(DEFAULT_MAX_EVENTS):
        try:
            yielded = coroutine.send(value)
        except StopIteration as stop:
            return stop.value
        if inspect.iscoroutine(yielded):
            value = _run_coroutine(yielded)
        else:
            value = None
    raise PythonExecutionTraceError("coroutine did not complete within the event bound")


def _run_async_generator(async_gen: Any) -> dict[str, Any]:
    yielded = 0
    aclose = getattr(async_gen, "aclose", None)
    try:
        for _ in range(DEFAULT_MAX_EVENTS):
            waiter = async_gen.asend(None)
            _run_coroutine(waiter)
            yielded += 1
        raise PythonExecutionTraceError("async generator did not complete within the event bound")
    except StopAsyncIteration:
        return {"yielded_count": yielded}
    finally:
        if callable(aclose):
            try:
                _run_coroutine(aclose())
            except Exception:
                pass


def _opaque(value: Any) -> Any:
    value_type = type(value)
    if value is None or value_type is bool or value_type is str:
        if value_type is str:
            return _truncate_text(value, DEFAULT_MAX_STRING_CHARS)
        return value
    if value_type is int and not isinstance(value, bool):
        if -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            return value
    return {"type": value_type.__name__, "unavailable": "opaque"}


def _invoke_subject(subject: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if inspect.iscoroutinefunction(subject):
        return _run_coroutine(subject(*args, **kwargs))
    if inspect.isasyncgenfunction(subject):
        return _run_async_generator(subject(*args, **kwargs))
    if inspect.isgeneratorfunction(subject):
        return _run_generator(subject(*args, **kwargs))
    result = subject(*args, **kwargs)
    if inspect.iscoroutine(result):
        return _run_coroutine(result)
    if inspect.isasyncgen(result):
        return _run_async_generator(result)
    return result


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class PythonExecutionTracer:
    """In-process hermetic tracer bound to exact source and environment."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE
    VERSION: ClassVar[str] = TRACER_VERSION

    def __init__(
        self,
        *,
        policy: TraceCollectionPolicy | None = None,
        environment_binding: Mapping[str, str] | None = None,
        tree_cid: str | None = None,
        redactor: TraceRedactor | None = None,
    ) -> None:
        self.policy = policy if policy is not None else TraceCollectionPolicy()
        bindings = _string_mapping(
            environment_binding if environment_binding is not None else _default_environment(),
            "environment_binding",
        )
        self.environment_binding = bindings
        self.environment_binding_cid = _environment_cid(bindings)
        self.tree_cid_override = tree_cid
        self.redactor = redactor if redactor is not None else TraceRedactor()
        self._facts: list[_EventFact] = []
        self._line_events = 0
        self._truncated = False
        self._denied_effect: str | None = None
        self._pending_exception: str | None = None
        self._subject_code: CodeType | None = None
        self._subject_filename = ""
        self._collecting = False
        self._token: TraceCancellation | None = None

    def record(
        self,
        subject: Callable[..., Any],
        /,
        *args: Any,
        cancellation: TraceCancellation | None = None,
        source_text: str | None = None,
        tree_cid: str | None = None,
        **kwargs: Any,
    ) -> PythonExecutionTraceRecord:
        return self._collect(
            subject,
            args,
            kwargs,
            cancellation=cancellation,
            source_text=source_text,
            tree_cid=tree_cid,
        )

    def _collect(
        self,
        subject: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        cancellation: TraceCancellation | None,
        source_text: str | None,
        tree_cid: str | None,
    ) -> PythonExecutionTraceRecord:
        if not callable(subject):
            raise PythonExecutionTraceError("subject must be callable")
        unwrapped = _unwrap_subject(subject)
        source_bytes = _subject_source_bytes(unwrapped, source_text)
        source_cid = cid_for_bytes(source_bytes)
        tree = tree_cid or self.tree_cid_override
        if tree is None:
            tree = cid_for_structured({"schema": TRACE_TREE_SCHEMA, "source_cid": source_cid})
        logical_name = _qualname_of(unwrapped)
        subject_cid = cid_for_structured(
            {
                "schema": TRACE_SUBJECT_SCHEMA,
                "logical_name": logical_name,
                "source_cid": source_cid,
            }
        )
        token = cancellation if cancellation is not None else TraceCancellation()
        self._token = token
        self._facts = []
        self._line_events = 0
        self._truncated = False
        self._denied_effect = None
        self._pending_exception = None
        self._subject_code = _code_of(unwrapped)
        self._subject_filename = (
            self._subject_code.co_filename if self._subject_code is not None else ""
        )
        outcome = TraceOutcome.COMPLETED
        result_summary: dict[str, Any] = {"status": "completed"}
        unavailable: list[str] = []

        if token.requested:
            outcome = TraceOutcome.CANCELLED
            result_summary = {"status": "cancelled", "reason": token.reason}
            unavailable.append("remaining_trace")
            return self._assemble(
                source_cid=source_cid,
                tree_cid=tree,
                subject_cid=subject_cid,
                logical_name=logical_name,
                token=token,
                outcome=outcome,
                result_summary=result_summary,
                extra_unavailable=unavailable,
                accepted=False,
            )

        self._append_synthetic(
            EventKind.ENTER.value,
            logical_name,
            self._subject_filename,
            getattr(self._subject_code, "co_firstlineno", None),
            {"subject": logical_name},
            (),
        )

        previous_trace = sys.gettrace()
        previous_profile = sys.getprofile()
        self._collecting = True
        try:
            with _IsolationGuard(self.policy, self._note_denied):
                sys.settrace(self._trace)
                sys.setprofile(self._profile)
                try:
                    value = _invoke_subject(unwrapped, args, kwargs)
                    result_summary = {"status": "completed", "result": _opaque(value)}
                except _CancelledAbort:
                    outcome = TraceOutcome.CANCELLED
                    result_summary = {"status": "cancelled", "reason": token.reason}
                    unavailable.append("remaining_trace")
                except _DeniedAbort as denied:
                    outcome = TraceOutcome.DENIED
                    result_summary = {
                        "status": "denied",
                        "effect": denied.effect,
                    }
                    unavailable.append("external_effect")
                except Exception as error:
                    outcome = TraceOutcome.RAISED
                    result_summary = {
                        "status": "raised",
                        "exception_type": type(error).__name__,
                    }
                    if not any(fact.kind == EventKind.RAISE.value for fact in self._facts):
                        self._append_synthetic(
                            EventKind.RAISE.value,
                            logical_name,
                            self._subject_filename,
                            None,
                            {"exception_type": type(error).__name__},
                            ("exception",) if False else (),
                            exception_type=type(error).__name__,
                        )
        finally:
            self._collecting = False
            sys.settrace(previous_trace)
            sys.setprofile(previous_profile)

        if self._truncated:
            unavailable.append("remaining_trace")
            if outcome is TraceOutcome.COMPLETED:
                outcome = TraceOutcome.TRUNCATED
                result_summary = {**result_summary, "status": "truncated"}

        if outcome is TraceOutcome.COMPLETED and self.policy.admits(EventKind.EXIT.value):
            self._append_synthetic(
                EventKind.EXIT.value,
                logical_name,
                self._subject_filename,
                None,
                {"subject": logical_name},
                (),
            )

        accepted = outcome is TraceOutcome.COMPLETED
        if token.requested or outcome is TraceOutcome.CANCELLED:
            accepted = False
            outcome = TraceOutcome.CANCELLED
        if outcome is TraceOutcome.DENIED:
            accepted = False
        return self._assemble(
            source_cid=source_cid,
            tree_cid=tree,
            subject_cid=subject_cid,
            logical_name=logical_name,
            token=token,
            outcome=outcome,
            result_summary=result_summary,
            extra_unavailable=unavailable,
            accepted=accepted,
        )

    def _note_denied(self, effect: str) -> None:
        self._denied_effect = effect
        self._append_synthetic(
            EventKind.EXTERNAL.value,
            effect,
            "",
            None,
            {"disposition": "denied", "effect": effect},
            (),
        )

    def _skip_frame(self, frame: FrameType) -> bool:
        filename = frame.f_code.co_filename or ""
        if filename == _TRACER_FILENAME:
            return True
        module = frame.f_globals.get("__name__", "") if isinstance(frame.f_globals, dict) else ""
        if any(module.startswith(prefix) for prefix in _SELF_SKIP_PREFIXES):
            return True
        return False

    def _in_scope(self, frame: FrameType) -> bool:
        if self._skip_frame(frame):
            return False
        if self._subject_code is not None and frame.f_code is self._subject_code:
            return True
        if self._subject_filename and frame.f_code.co_filename == self._subject_filename:
            return True
        filename = frame.f_code.co_filename or ""
        if filename.startswith("<") or not filename:
            return False
        stdlib = getattr(sys, "stdlib_dir", None) or getattr(sys, "base_prefix", "")
        if stdlib and filename.startswith(str(stdlib)):
            return False
        prefix = sys.prefix
        if prefix and "/lib/python" in filename.replace("\\", "/") and filename.startswith(prefix):
            return False
        return filename == self._subject_filename

    def _trace(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if not self._collecting:
            return None
        if self._truncated:
            return None
        if self._skip_frame(frame):
            return self._trace
        if not self._in_scope(frame):
            return None
        self._handle_python_event(frame, event, arg)
        return self._trace

    def _profile(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if not self._collecting or self._truncated:
            return self._profile
        if event == "c_call" and not self._skip_frame(frame):
            name = getattr(arg, "__name__", "") or ""
            module = getattr(arg, "__module__", "") or ""
            if name in _DENIED_FUNCTION_NAMES or _effect_denied(
                self.policy, module or name, name
            ):
                effect = f"{module}.{name}" if module else str(name)
                if self._denied_effect != effect:
                    self._note_denied(effect)
                raise _DeniedAbort(effect)
        return self._profile

    def _handle_python_event(self, frame: FrameType, event: str, arg: Any) -> None:
        if self._cancel_requested():
            raise _CancelledAbort()
        kind: str | None = None
        payload: dict[str, Any] = {}
        exception_type: str | None = None
        handler_kind: str | None = None
        unavailable: tuple[str, ...] = ()
        if event == "call":
            kind = EventKind.CALL.value
            payload = {"callee": _frame_qualname(frame)}
        elif event == "return":
            if _is_await(frame, event) and self.policy.admits(EventKind.AWAIT.value):
                kind = EventKind.AWAIT.value
                payload = {"awaitable": type(arg).__name__ if arg is not None else "NoneType"}
            elif _is_yield(frame, event) and self.policy.admits(EventKind.YIELD.value):
                kind = EventKind.YIELD.value
                payload = {"value": _opaque(arg)}
            else:
                kind = EventKind.RETURN.value
                payload = {"value": _opaque(arg)}
        elif event == "line":
            if self._pending_exception:
                opcode = _opcode_at(frame.f_code, frame.f_lasti)
                handler_kind = (
                    HandlerKind.EXCEPT_STAR.value
                    if opcode in _EXCEPT_STAR_OPCODES
                    else HandlerKind.EXCEPT.value
                )
                if self.policy.admits(EventKind.CATCH.value):
                    self._emit(
                        EventKind.CATCH.value,
                        frame,
                        {"exception_type": self._pending_exception},
                        exception_type=self._pending_exception,
                        handler_kind=handler_kind,
                    )
                if self.policy.admits(EventKind.HANDLER.value):
                    self._emit(
                        EventKind.HANDLER.value,
                        frame,
                        {"handler_kind": handler_kind},
                        exception_type=self._pending_exception,
                        handler_kind=handler_kind,
                    )
                self._pending_exception = None
            if not self.policy.collect_line_events or not self.policy.admits(EventKind.LINE.value):
                return
            if self._line_events >= self.policy.max_line_events:
                self._truncated = True
                return
            kind = EventKind.LINE.value
            payload = {"line": frame.f_lineno}
            self._line_events += 1
        elif event == "exception":
            exc_type = arg[0] if isinstance(arg, tuple) and arg else type(arg)
            exception_type = getattr(exc_type, "__name__", str(exc_type))
            self._pending_exception = exception_type
            kind = EventKind.RAISE.value
            payload = {"exception_type": exception_type}
        else:
            return
        if kind is None or not self.policy.admits(kind):
            return
        self._emit(
            kind,
            frame,
            payload,
            exception_type=exception_type,
            handler_kind=handler_kind,
            unavailable=unavailable,
        )

    def _cancel_requested(self) -> bool:
        token = getattr(self, "_token", None)
        return bool(token is not None and token.requested)

    def _emit(
        self,
        kind: str,
        frame: FrameType,
        payload: Mapping[str, Any],
        *,
        exception_type: str | None = None,
        handler_kind: str | None = None,
        unavailable: tuple[str, ...] = (),
    ) -> None:
        if len(self._facts) >= self.policy.max_events:
            self._truncated = True
            return
        frames = self._capture_stack(frame)
        redacted: list[str] = []
        for item in frames:
            redacted.extend(item.redacted_dimensions)
        self._facts.append(
            _EventFact(
                kind=kind,
                qualname=_frame_qualname(frame),
                filename=frame.f_code.co_filename,
                line=frame.f_lineno if frame.f_lineno >= 0 else None,
                payload=dict(payload),
                frames=frames,
                exception_type=exception_type,
                handler_kind=handler_kind,
                redacted_dimensions=tuple(sorted(set(redacted))),
                unavailable_dimensions=unavailable,
            )
        )

    def _append_synthetic(
        self,
        kind: str,
        qualname: str,
        filename: str,
        line: int | None,
        payload: Mapping[str, Any],
        unavailable: tuple[str, ...],
        *,
        exception_type: str | None = None,
    ) -> None:
        if not self.policy.admits(kind):
            return
        if len(self._facts) >= self.policy.max_events:
            self._truncated = True
            return
        frames: tuple[_FrameFact, ...] = ()
        if self._subject_code is not None:
            frames = (
                _FrameFact(
                    ordinal=0,
                    qualname=qualname,
                    filename=filename or self._subject_filename,
                    line=line if line is not None else getattr(self._subject_code, "co_firstlineno", None),
                    code=self._subject_code,
                    locals_summary={},
                    redacted_dimensions=(),
                ),
            )
        self._facts.append(
            _EventFact(
                kind=kind,
                qualname=qualname,
                filename=filename,
                line=line,
                payload=dict(payload),
                frames=frames,
                exception_type=exception_type,
                redacted_dimensions=(),
                unavailable_dimensions=unavailable,
            )
        )

    def _capture_stack(self, frame: FrameType) -> tuple[_FrameFact, ...]:
        chain: list[FrameType] = []
        current: FrameType | None = frame
        while current is not None and len(chain) < self.policy.max_stack_frames:
            if not self._skip_frame(current) and self._in_scope(current):
                chain.append(current)
            current = current.f_back
        facts: list[_FrameFact] = []
        for ordinal, item in enumerate(chain):
            locals_summary, redacted = _locals_summary(
                item,
                redactor=self.redactor,
                string_limit=self.policy.max_string_chars,
                capture_locals=self.policy.capture_locals,
            )
            line = item.f_lineno if item.f_lineno and item.f_lineno >= 0 else None
            facts.append(
                _FrameFact(
                    ordinal=ordinal,
                    qualname=_frame_qualname(item),
                    filename=item.f_code.co_filename,
                    line=line,
                    code=item.f_code,
                    locals_summary=locals_summary,
                    redacted_dimensions=redacted,
                )
            )
        return tuple(facts)

    def _code_cid(self, code: CodeType, source_cid: str) -> str:
        qualname = getattr(code, "co_qualname", code.co_name)
        bound_source = source_cid if code is self._subject_code or code.co_filename == self._subject_filename else cid_for_bytes(bytes(code.co_code))
        return cid_for_structured(
            {
                "schema": TRACE_CODE_SCHEMA,
                "firstlineno": code.co_firstlineno,
                "logical_name": str(qualname)[:MAX_TEXT_CHARS],
                "source_cid": bound_source,
            }
        )

    def _assemble(
        self,
        *,
        source_cid: str,
        tree_cid: str,
        subject_cid: str,
        logical_name: str,
        token: TraceCancellation,
        outcome: TraceOutcome,
        result_summary: Mapping[str, Any],
        extra_unavailable: Sequence[str],
        accepted: bool,
    ) -> PythonExecutionTraceRecord:
        policy = self.policy
        redactor = self.redactor
        env_cid = self.environment_binding_cid
        facts = tuple(self._facts)
        if not facts:
            facts = (
                _EventFact(
                    kind=EventKind.UNAVAILABLE.value,
                    qualname=logical_name,
                    filename=self._subject_filename,
                    line=None,
                    payload={"reason": outcome.value},
                    frames=(),
                    unavailable_dimensions=("event_body", "remaining_trace"),
                ),
            )
        all_redacted: set[str] = set()
        all_unavailable: set[str] = set(extra_unavailable)
        all_unavailable.add("native_stack")
        events: list[ProgramEvent] = []
        frames_out: list[StackFrameState] = []
        exceptions: list[ExceptionSnapshot] = []
        handlers: list[HandlerState] = []
        predecessor: str | None = None
        capture_cid = policy.trace_collection_policy_cid
        stack_records_by_event: list[tuple[StackFrameState, ...]] = []

        for fact in facts:
            if fact.kind not in ADMITTED_EVENT_KINDS:
                continue
            all_redacted.update(fact.redacted_dimensions)
            all_unavailable.update(fact.unavailable_dimensions)
            stack_states: list[StackFrameState] = []
            for frame_fact in fact.frames:
                code_cid = self._code_cid(frame_fact.code, source_cid)
                frame_source = (
                    source_cid
                    if frame_fact.code is self._subject_code
                    or frame_fact.filename == self._subject_filename
                    else cid_for_bytes(bytes(frame_fact.code.co_code))
                )
                locals_payload, extra = redactor.redact_mapping(dict(frame_fact.locals_summary))
                redacted = tuple(sorted(set(frame_fact.redacted_dimensions) | set(extra)))
                all_redacted.update(redacted)
                unavailable = ()
                claim = CompletenessClaim.FULL_STATE
                if redacted:
                    claim = CompletenessClaim.REDACTED
                if frame_fact.line is None:
                    unavailable = ("source_location",)
                    claim = CompletenessClaim.PARTIAL if not redacted else CompletenessClaim.REDACTED
                    all_unavailable.add("source_location")
                summary: dict[str, Any] = {}
                if locals_payload:
                    summary["locals"] = locals_payload
                try:
                    bounded = _bound_payload(summary, max_bytes=policy.max_payload_bytes)
                except (TypeError, ValueError, ProgramExecutionError):
                    bounded = {"unavailable": "payload_bound"}
                    unavailable = tuple(sorted(set(unavailable) | {"locals"}))
                    claim = CompletenessClaim.PARTIAL
                frame_state = StackFrameState(
                    ordinal=frame_fact.ordinal,
                    language=ADMITTED_LANGUAGE,
                    tree_cid=tree_cid,
                    source_cid=frame_source,
                    code_cid=code_cid,
                    environment_binding_cid=env_cid,
                    logical_name=_nfc(frame_fact.qualname, "logical_name")[:MAX_TEXT_CHARS],
                    line=frame_fact.line,
                    column=None,
                    state_summary=bounded,
                    redacted_dimensions=redacted,
                    unavailable_dimensions=unavailable,
                    completeness_claim=claim,
                    privacy_class=PrivacyClass.INTERNAL,
                )
                stack_states.append(frame_state)
                frames_out.append(frame_state)
            if (
                fact.kind in {
                    EventKind.CALL.value,
                    EventKind.RETURN.value,
                    EventKind.RAISE.value,
                    EventKind.CATCH.value,
                    EventKind.HANDLER.value,
                    EventKind.YIELD.value,
                    EventKind.AWAIT.value,
                    EventKind.ENTER.value,
                    EventKind.EXIT.value,
                }
                and not stack_states
            ):
                all_unavailable.add("call_stack")
            exception_cid = None
            handler_cid = None
            if fact.kind == EventKind.RAISE.value:
                traceback_cids = tuple(item.stack_frame_state_cid for item in stack_states)
                snapshot_unavailable = () if traceback_cids else ("call_stack",)
                snapshot = ExceptionSnapshot(
                    language=ADMITTED_LANGUAGE,
                    exception_type=fact.exception_type or "Exception",
                    tree_cid=tree_cid,
                    source_cid=source_cid,
                    code_cid=(
                        stack_states[0].code_cid
                        if stack_states
                        else cid_for_structured(
                            {
                                "schema": TRACE_CODE_SCHEMA,
                                "firstlineno": 0,
                                "logical_name": fact.qualname,
                                "source_cid": source_cid,
                            }
                        )
                    ),
                    environment_binding_cid=env_cid,
                    exception_value_summary={
                        "bounded": True,
                        "type": fact.exception_type or "Exception",
                    },
                    traceback_stack_frame_cids=traceback_cids,
                    future_execution=False,
                    unavailable_dimensions=snapshot_unavailable,
                    completeness_claim=(
                        CompletenessClaim.PARTIAL if snapshot_unavailable else CompletenessClaim.FULL_STATE
                    ),
                )
                exceptions.append(snapshot)
                exception_cid = snapshot.exception_snapshot_cid
            if fact.kind in {EventKind.CATCH.value, EventKind.HANDLER.value}:
                matching = exceptions[-1].exception_snapshot_cid if exceptions else cid_for_bytes(b"exc:unbound")
                handler = HandlerState(
                    language=ADMITTED_LANGUAGE,
                    handler_kind=fact.handler_kind or HandlerKind.EXCEPT.value,
                    tree_cid=tree_cid,
                    source_cid=source_cid,
                    code_cid=(
                        stack_states[0].code_cid
                        if stack_states
                        else cid_for_structured(
                            {
                                "schema": TRACE_CODE_SCHEMA,
                                "firstlineno": 0,
                                "logical_name": fact.qualname,
                                "source_cid": source_cid,
                            }
                        )
                    ),
                    environment_binding_cid=env_cid,
                    logical_name=_nfc(fact.qualname, "logical_name")[:MAX_TEXT_CHARS],
                    stack_ordinal=0,
                    handler_active=True,
                    matching_exception_snapshot_cid=matching,
                    unavailable_dimensions=(),
                )
                handlers.append(handler)
                handler_cid = handler.handler_state_cid
            payload, payload_redacted = redactor.redact_mapping(dict(fact.payload))
            all_redacted.update(payload_redacted)
            try:
                payload = _bound_payload(payload, max_bytes=policy.max_payload_bytes)
            except (TypeError, ValueError, ProgramExecutionError):
                payload = {"unavailable": "payload_bound"}
                all_unavailable.add("payload")
            redacted = tuple(sorted(set(fact.redacted_dimensions) | set(payload_redacted)))
            unavailable = tuple(sorted(set(fact.unavailable_dimensions)))
            if fact.kind == EventKind.UNAVAILABLE.value and not unavailable:
                unavailable = ("event_body",)
            claim = CompletenessClaim.FULL_STATE
            status = ObservationStatus.OBSERVED
            origin = EventOrigin.OBSERVED
            if fact.kind == EventKind.UNAVAILABLE.value:
                claim = CompletenessClaim.UNAVAILABLE
                status = ObservationStatus.UNAVAILABLE
            elif redacted:
                claim = CompletenessClaim.REDACTED
                status = ObservationStatus.REDACTED
            elif unavailable:
                claim = CompletenessClaim.PARTIAL
            stack_cids = tuple(item.stack_frame_state_cid for item in stack_states)
            if (
                fact.kind
                in {
                    EventKind.CALL.value,
                    EventKind.RETURN.value,
                    EventKind.RAISE.value,
                    EventKind.CATCH.value,
                    EventKind.HANDLER.value,
                    EventKind.YIELD.value,
                    EventKind.AWAIT.value,
                    EventKind.ENTER.value,
                    EventKind.EXIT.value,
                }
                and not stack_cids
                and "call_stack" not in unavailable
            ):
                unavailable = tuple(sorted(set(unavailable) | {"call_stack"}))
                if claim == CompletenessClaim.FULL_STATE:
                    claim = CompletenessClaim.PARTIAL
            event = ProgramEvent(
                event_kind=fact.kind,
                event_origin=origin,
                observation_status=status,
                language=ADMITTED_LANGUAGE,
                tree_cid=tree_cid,
                source_cid=source_cid,
                code_cid=(
                    stack_states[0].code_cid
                    if stack_states
                    else cid_for_structured(
                        {
                            "schema": TRACE_CODE_SCHEMA,
                            "firstlineno": 0,
                            "logical_name": fact.qualname or logical_name,
                            "source_cid": source_cid,
                        }
                    )
                ),
                environment_binding_cid=env_cid,
                subject_cid=subject_cid,
                logical_name=_nfc(fact.qualname or logical_name, "logical_name")[:MAX_TEXT_CHARS],
                payload=payload,
                line=fact.line,
                column=None,
                predecessor_event_cid=predecessor,
                stack_frame_cids=stack_cids,
                exception_snapshot_cid=exception_cid,
                handler_state_cid=handler_cid,
                redacted_dimensions=redacted,
                unavailable_dimensions=unavailable,
                completeness_claim=claim,
                privacy_class=PrivacyClass.INTERNAL,
            )
            events.append(event)
            predecessor = event.program_event_cid
            stack_records_by_event.append(tuple(stack_states))

        if not events:
            raise PythonExecutionTraceError("trace assembly produced no events")

        observations: list[ExecutionObservation] = []
        for event in events:
            if event.observation_admissible:
                observations.append(observe_program_event(event))

        redaction = redactor.redaction_profile(tuple(all_redacted))
        unavailable_tuple = tuple(sorted(all_unavailable))
        claim = CompletenessClaim.FULL_STATE.value
        if redaction is not None:
            claim = str(redaction.completeness_claim)
        elif unavailable_tuple:
            claim = CompletenessClaim.PARTIAL.value
        if outcome is TraceOutcome.CANCELLED:
            claim = CompletenessClaim.UNAVAILABLE.value if "remaining_trace" in unavailable_tuple else CompletenessClaim.PARTIAL.value
            if "remaining_trace" not in unavailable_tuple:
                unavailable_tuple = tuple(sorted(set(unavailable_tuple) | {"remaining_trace"}))
            if claim == CompletenessClaim.UNAVAILABLE.value and not unavailable_tuple:
                unavailable_tuple = ("remaining_trace",)

        innermost: tuple[StackFrameState, ...] = stack_records_by_event[-1] if stack_records_by_event else ()
        for stack in reversed(stack_records_by_event):
            if stack and stack[0].state_summary:
                innermost = stack
                break
        observed_state: dict[str, Any] = {"outcome": dict(result_summary)}
        if policy.include_raw_bodies and innermost:
            locals_summary = innermost[0].state_summary.get("locals", {}) if innermost[0].state_summary else {}
            observed_state["locals"] = _thaw(locals_summary)
        observed_state, extra_redacted = redactor.redact_mapping(observed_state)
        if extra_redacted:
            all_redacted.update(extra_redacted)
            redaction = redactor.redaction_profile(tuple(all_redacted))
        try:
            observed_state = _bound_payload(observed_state, max_bytes=policy.max_payload_bytes)
        except (TypeError, ValueError, ProgramExecutionError):
            observed_state = {"unavailable": "payload_bound"}

        state_unavailable = list(unavailable_tuple)
        heap_bound = HeapBound.BOUNDED_ABSTRACT
        heap_summary: dict[str, Any] = {"bounded": True, "frames": len(innermost)}
        if policy.include_raw_bodies:
            privacy = PrivacyClass.PRIVATE
            includes_raw = True
            state_claim = CompletenessClaim.PARTIAL
            if "raw_body" not in (redaction.redacted_dimensions if redaction else ()):
                # raw bodies are private; completeness cannot be full_state
                pass
        else:
            privacy = PrivacyClass.INTERNAL
            includes_raw = False
            state_claim = CompletenessClaim(claim) if claim in {item.value for item in CompletenessClaim} else CompletenessClaim.PARTIAL
        if includes_raw and state_claim == CompletenessClaim.FULL_STATE:
            state_claim = CompletenessClaim.PARTIAL
            if "raw_body" not in state_unavailable:
                # keep raw out of unavailable so it can live as includes_raw_bodies
                pass
        if state_claim == CompletenessClaim.FULL_STATE and (all_redacted or state_unavailable):
            state_claim = CompletenessClaim.REDACTED if all_redacted else CompletenessClaim.PARTIAL
        if state_claim == CompletenessClaim.UNAVAILABLE and not state_unavailable:
            state_unavailable.append("remaining_trace")
        if state_claim == CompletenessClaim.PARTIAL and not (state_unavailable or all_redacted):
            state_unavailable.append("heap")
            heap_bound = HeapBound.UNAVAILABLE
            heap_summary = {}

        try:
            raw_state = assemble_program_execution_state(
                language=ADMITTED_LANGUAGE,
                capture_profile_cid=capture_cid,
                tree_cid=tree_cid,
                source_cid=source_cid,
                environment_binding_cid=env_cid,
                frames=innermost,
                observed_state=observed_state if includes_raw else {"outcome": dict(result_summary)},
                heap_summary=heap_summary,
                heap_bound=heap_bound,
                exception=exceptions[-1] if exceptions else None,
                handler=handlers[-1] if handlers else None,
                redaction=redaction,
                completeness_claim=state_claim,
                privacy_class=privacy,
                includes_raw_bodies=includes_raw,
                unavailable_dimensions=state_unavailable,
                code_cid=innermost[0].code_cid if innermost else events[-1].code_cid,
            )
        except ProgramExecutionError:
            raw_state = assemble_program_execution_state(
                language=ADMITTED_LANGUAGE,
                capture_profile_cid=capture_cid,
                tree_cid=tree_cid,
                source_cid=source_cid,
                environment_binding_cid=env_cid,
                frames=innermost,
                observed_state={},
                heap_summary={},
                heap_bound=HeapBound.UNAVAILABLE,
                redaction=redaction,
                completeness_claim=CompletenessClaim.PARTIAL,
                privacy_class=PrivacyClass.INTERNAL,
                includes_raw_bodies=False,
                unavailable_dimensions=tuple(sorted(set(state_unavailable) | {"heap", "observed_state"})),
                code_cid=innermost[0].code_cid if innermost else events[-1].code_cid,
            )
            includes_raw = False

        private_states = (raw_state,) if includes_raw else ()
        public_claim = claim
        if redaction is not None:
            public_claim = str(redaction.completeness_claim)
        elif unavailable_tuple:
            public_claim = CompletenessClaim.PARTIAL.value
        if outcome is TraceOutcome.CANCELLED:
            public_claim = CompletenessClaim.PARTIAL.value
            if "remaining_trace" not in unavailable_tuple:
                unavailable_tuple = tuple(sorted(set(unavailable_tuple) | {"remaining_trace"}))

        public_trace = assemble_execution_trace(
            language=ADMITTED_LANGUAGE,
            tree_cid=tree_cid,
            source_cid=source_cid,
            environment_binding_cid=env_cid,
            events=events,
            states=(),
            redaction=redaction,
            completeness_claim=public_claim,
            privacy_class=PrivacyClass.PUBLIC,
            includes_raw_bodies=False,
            unavailable_dimensions=unavailable_tuple,
        )
        private_trace = assemble_execution_trace(
            language=ADMITTED_LANGUAGE,
            tree_cid=tree_cid,
            source_cid=source_cid,
            environment_binding_cid=env_cid,
            events=events,
            states=private_states,
            redaction=redaction,
            completeness_claim=public_claim if not includes_raw else CompletenessClaim.PARTIAL,
            privacy_class=PrivacyClass.PRIVATE if includes_raw else PrivacyClass.INTERNAL,
            includes_raw_bodies=includes_raw,
            unavailable_dimensions=unavailable_tuple,
        )
        if accepted and token.requested:
            accepted = False
        if outcome is TraceOutcome.CANCELLED:
            accepted = False

        result_bound, _ = redactor.redact_mapping(dict(result_summary))
        try:
            result_bound = _bound_payload(result_bound, max_bytes=policy.max_payload_bytes)
        except (TypeError, ValueError, ProgramExecutionError):
            result_bound = {"status": outcome.value}

        return PythonExecutionTraceRecord(
            policy=policy,
            tree_cid=tree_cid,
            source_cid=source_cid,
            environment_binding_cid=env_cid,
            subject_cid=subject_cid,
            events=tuple(events),
            observations=tuple(observations),
            frames=tuple(frames_out),
            states=private_states,
            public_trace=public_trace,
            private_trace=private_trace,
            cancellation=MappingProxyType(token.to_dict()),
            accepted_transition=accepted,
            outcome=outcome.value,
            result_summary=MappingProxyType(result_bound),
            unavailable_dimensions=unavailable_tuple,
            completeness_claim=public_claim,
            redaction_profile_cid=None if redaction is None else redaction.redaction_profile_cid,
            exception_snapshots=tuple(exceptions),
            handler_states=tuple(handlers),
        )


def record_python_execution_trace(
    subject: Callable[..., Any],
    /,
    *args: Any,
    policy: TraceCollectionPolicy | None = None,
    cancellation: TraceCancellation | None = None,
    environment_binding: Mapping[str, str] | None = None,
    tree_cid: str | None = None,
    source_text: str | None = None,
    redactor: TraceRedactor | None = None,
    **kwargs: Any,
) -> PythonExecutionTraceRecord:
    """Collect an admitted hermetic Python execution trace.

    Cancellation never returns ``accepted_transition=True``.  Public records
    never include private raw trace bodies.  Network, subprocess, installer,
    database, watcher, and model-load effects are denied when the policy says
    so and recorded as external observations.
    """

    tracer = PythonExecutionTracer(
        policy=policy,
        environment_binding=environment_binding,
        tree_cid=tree_cid,
        redactor=redactor,
    )
    tracer._token = cancellation  # checked by the trace hook
    return tracer.record(
        subject,
        *args,
        cancellation=cancellation,
        source_text=source_text,
        tree_cid=tree_cid,
        **kwargs,
    )


def replay_deterministic_trace(
    subject: Callable[..., Any],
    /,
    *args: Any,
    previous: PythonExecutionTraceRecord,
    policy: TraceCollectionPolicy | None = None,
    environment_binding: Mapping[str, str] | None = None,
    tree_cid: str | None = None,
    source_text: str | None = None,
    **kwargs: Any,
) -> PythonExecutionTraceReplay:
    """Re-collect a promised deterministic trace and compare public identity.

    Cancelled traces, denied external effects, and traces that already recorded
    nondeterministic external observations are typed unavailable for replay.
    """

    if not isinstance(previous, PythonExecutionTraceRecord):
        raise PythonExecutionTraceError("previous must be a PythonExecutionTraceRecord")
    unavailable: list[str] = []
    if previous.outcome == TraceOutcome.CANCELLED.value or previous.cancellation.get("requested"):
        raise PythonExecutionTraceError(
            "promised replay is unavailable for cancelled traces"
        )
    if previous.outcome == TraceOutcome.DENIED.value:
        raise PythonExecutionTraceError(
            "promised replay is unavailable for denied external effects"
        )
    if any(event.event_kind == EventKind.EXTERNAL.value for event in previous.events):
        raise PythonExecutionTraceError(
            "promised replay is unavailable for nondeterministic external effects"
        )
    bound_policy = policy if policy is not None else previous.policy
    replayed = record_python_execution_trace(
        subject,
        *args,
        policy=bound_policy,
        environment_binding=environment_binding,
        tree_cid=tree_cid or previous.tree_cid,
        source_text=source_text,
        **kwargs,
    )
    if replayed.outcome == TraceOutcome.CANCELLED.value:
        raise PythonExecutionTraceError("promised replay was cancelled")
    matched = (
        replayed.public_trace.execution_trace_cid == previous.public_trace.execution_trace_cid
        and replayed.source_cid == previous.source_cid
        and replayed.environment_binding_cid == previous.environment_binding_cid
    )
    if not matched:
        unavailable.append("replay_identity")
    return PythonExecutionTraceReplay(
        previous_public_trace_cid=previous.public_trace.execution_trace_cid,
        replayed_public_trace_cid=replayed.public_trace.execution_trace_cid,
        matched=matched,
        unavailable_dimensions=tuple(sorted(unavailable)),
        accepted_transition=bool(matched and replayed.accepted_transition),
        record=replayed,
    )


__all__ = [
    "ADMITTED_EVENT_KINDS",
    "ADMITTED_LANGUAGE",
    "DEFAULT_EVENT_KINDS",
    "IMPORT_DATABASE_OPENED",
    "IMPORT_INSTALLER_INVOKED",
    "IMPORT_MODEL_LOADED",
    "IMPORT_NETWORK_PERFORMED",
    "IMPORT_SCAN_PERFORMED",
    "IMPORT_SOCKET_OPENED",
    "IMPORT_SUBPROCESS_SPAWNED",
    "IMPORT_TRACE_HOOKS_INSTALLED",
    "IMPORT_WATCHER_STARTED",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "PYTHON_EXECUTION_TRACE_RECORD_INTERFACE",
    "PYTHON_EXECUTION_TRACE_REPLAY_INTERFACE",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "PythonExecutionTraceError",
    "PythonExecutionTraceRecord",
    "PythonExecutionTraceReplay",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCollectionPolicy",
    "TraceOutcome",
    "TraceRedactor",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
