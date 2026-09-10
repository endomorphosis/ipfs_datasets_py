"""Hermetic Python execution tracing (``PythonExecutionTrace@1``).

This module records admitted call, return, line, exception, handler, yield,
await, and selected external events from a Python callable using runtime
tracing hooks.  Every event is bound to the exact tree, source, environment,
symbol, and source location supplied at recording time.

Authority and isolation rules (normative):

* Import is inert.  The module does not open sockets, spawn processes, install
  packages, scan repositories, start watchers, connect to databases, or load
  models.
* Cancellation stops admission: a cancelled recording emits no accepted
  transition.
* Secret and forbidden fields are omitted before any public or private
  contract record is assembled.  Private raw trace bodies never enter public
  records.
* Network, socket, and subprocess effects are test-denied during recording
  when the collection policy says so.  Denied attempts are explicit external
  observations, not accepted transitions.
* Replay is promised only for deterministic callables under the same tree,
  source, environment, and collection policy.

This module does not persist operational acceptance, does not invoke a
scheduler, and does not deserialize arbitrary code.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import CodeType, FrameType, MappingProxyType
from typing import Any, ClassVar, Final
import dis
import inspect
import sys
import threading
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    CompletenessClaim,
    EventKind,
    EventOrigin,
    ExceptionSnapshot,
    ExecutionTrace,
    FORBIDDEN_FIELD_MARKERS,
    HandlerKind,
    HandlerState,
    HeapBound,
    MAX_SAFE_INTEGER,
    ObservationStatus,
    PrivacyClass,
    ProgramEvent,
    ProgramExecutionError,
    ProgramExecutionState,
    ProgramLanguage,
    RedactionProfile,
    SECRET_FIELD_MARKERS,
    StackFrameState,
    assemble_execution_trace,
    assemble_program_execution_state,
)


PYTHON_EXECUTION_TRACE_INTERFACE: Final[str] = "PythonExecutionTrace@1"
HERMETIC_TRACE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.hermetic-python-trace@1"
)
TRACE_COLLECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-policy@1"
)
TRACE_REDACTOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-redactor@1"
)
TRACE_CANCELLATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-cancellation@1"
)
TRACE_TRANSITION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-transition@1"
)
HERMETIC_TRACE_REPLAY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.hermetic-trace-replay@1"
)
EVIDENCE_CLASS: Final[str] = "sawm/hermetic-trace@1"
ALGORITHM_VERSION: Final[str] = "hermetic-python-trace/v1"
TASK_ID: Final[str] = "SAWM-008"

_CO_GENERATOR: Final[int] = getattr(inspect, "CO_GENERATOR", 0x20)
_CO_COROUTINE: Final[int] = getattr(inspect, "CO_COROUTINE", 0x80)
_CO_ITERABLE_COROUTINE: Final[int] = getattr(inspect, "CO_ITERABLE_COROUTINE", 0x100)
_CO_ASYNC_GENERATOR: Final[int] = getattr(inspect, "CO_ASYNC_GENERATOR", 0x200)

_EXTERNAL_ROOT_MODULES: Final[frozenset[str]] = frozenset(
    {
        "ftplib",
        "http",
        "httpx",
        "requests",
        "smtplib",
        "socket",
        "ssl",
        "subprocess",
        "urllib",
        "urllib3",
    }
)
_NETWORK_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "socket.connect",
        "socket.getaddrinfo",
        "socket.sendto",
    }
)
_SUBPROCESS_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "os.system",
        "os.posix_spawn",
        "subprocess.Popen",
    }
)
_DEFAULT_EXCLUDE_PREFIXES: Final[tuple[str, ...]] = (
    "<",
    sys.base_prefix.replace("\\", "/") + "/lib",
    sys.exec_prefix.replace("\\", "/") + "/lib",
)
_FORBIDDEN_LOCAL_KEYS: Final[frozenset[str]] = FORBIDDEN_FIELD_MARKERS | SECRET_FIELD_MARKERS
_YIELD_OPNAMES: Final[frozenset[str]] = frozenset({"YIELD_VALUE", "YIELD_FROM", "SEND"})
_RETURN_GENERATOR_OPNAMES: Final[frozenset[str]] = frozenset({"RETURN_GENERATOR"})

_HOOK_INSTALLED: bool = False
_TLS = threading.local()


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic tracing is malformed, cancelled, or isolated."""


class TraceStatus(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise PythonExecutionTraceError(f"{label} must be a nonempty trimmed string")
    if "\x00" in value or any(not char.isprintable() for char in value):
        raise PythonExecutionTraceError(f"{label} contains invalid text")
    return _nfc(value)


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise PythonExecutionTraceError(f"{label} must be a boolean")
    return value


def _positive_int(value: object, label: str, *, minimum: int = 1) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise PythonExecutionTraceError(f"{label} must be an integer >= {minimum}")
    if value > MAX_SAFE_INTEGER:
        raise PythonExecutionTraceError(f"{label} exceeds the safe JSON integer range")
    return value


def _cid(value: object, label: str) -> str:
    text = _text(value, label)
    if not text.startswith("b") or len(text) < 20:
        raise PythonExecutionTraceError(f"{label} must be a CIDv1 string")
    return text


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PythonExecutionTraceError(f"{label} must be a mapping")
    return value


def _logical_name(code: CodeType, module: str | None) -> str:
    qualname = getattr(code, "co_qualname", code.co_name) or code.co_name
    if module:
        name = f"{module}.{qualname}"
    else:
        name = qualname
    name = _nfc(name.strip())
    if not name:
        name = "python.anonymous"
    return name[:512]


def _module_of(frame: FrameType | None, code: CodeType | None = None) -> str:
    if frame is not None:
        name = frame.f_globals.get("__name__")
        if type(name) is str and name:
            return name
    if code is not None:
        filename = code.co_filename.replace("\\", "/")
        stem = filename.rsplit("/", 1)[-1]
        if stem.endswith(".py"):
            return stem[:-3]
    return ""


def _code_cid(code: CodeType, logical_name: str) -> str:
    identity = "\n".join(
        (
            logical_name,
            str(code.co_firstlineno),
            str(code.co_argcount),
            str(len(code.co_code)),
        )
    )
    return cid_for_bytes(identity.encode("utf-8") + b"\n" + code.co_code)


def _subject_cid(logical_name: str, code_cid: str) -> str:
    return cid_for_structured({"code_cid": code_cid, "logical_name": logical_name})


def _is_secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in _FORBIDDEN_LOCAL_KEYS:
        return True
    for marker in SECRET_FIELD_MARKERS:
        if (
            lowered == marker
            or lowered.startswith(f"{marker}_")
            or lowered.endswith(f"_{marker}")
        ):
            return True
    return False


def _is_tracer_code(code: CodeType) -> bool:
    return code.co_filename == __file__


def _is_excluded_filename(filename: str, prefixes: Sequence[str]) -> bool:
    normalized = filename.replace("\\", "/")
    if "site-packages" in normalized:
        return True
    return any(normalized.startswith(prefix) for prefix in prefixes if prefix)


def bind_source_cid(target: Callable[..., Any]) -> str:
    """Return a source CID for ``target`` without reading the repository tree."""

    unwrapped = inspect.unwrap(target)
    try:
        source = inspect.getsource(unwrapped)
    except (OSError, TypeError):
        code = getattr(unwrapped, "__code__", None)
        if isinstance(code, CodeType):
            return cid_for_bytes(code.co_code)
        raise PythonExecutionTraceError("target source is unavailable") from None
    return cid_for_bytes(source.encode("utf-8"))


def bind_environment_cid() -> str:
    """Bind the exact Python language/runtime without host or clock fields."""

    return cid_for_structured(
        {
            "implementation": sys.implementation.name,
            "language": ProgramLanguage.PYTHON.value,
            "major": sys.version_info.major,
            "micro": sys.version_info.micro,
            "minor": sys.version_info.minor,
        }
    )


def _target_code(target: Callable[..., Any]) -> CodeType:
    unwrapped = inspect.unwrap(target)
    code = getattr(unwrapped, "__code__", None)
    if isinstance(code, CodeType):
        return code
    func = getattr(unwrapped, "__func__", None)
    code = getattr(func, "__code__", None)
    if isinstance(code, CodeType):
        return code
    call = getattr(unwrapped, "__call__", None)
    code = getattr(call, "__code__", None)
    if isinstance(code, CodeType) and not _is_tracer_code(code):
        return code
    raise PythonExecutionTraceError("target is not a Python function")


def _opname_at(frame: FrameType) -> str:
    lasti = frame.f_lasti
    if type(lasti) is not int or lasti < 0:
        return ""
    matched = ""
    try:
        for instruction in dis.get_instructions(frame.f_code):
            if instruction.offset <= lasti:
                if instruction.opname != "CACHE":
                    matched = instruction.opname
            else:
                break
    except (TypeError, ValueError, SystemError):
        return ""
    return matched


def _line_column(code: CodeType, offset: int, frame: FrameType | None) -> tuple[int | None, int | None]:
    if frame is not None and type(frame.f_lineno) is int and frame.f_lineno >= 0:
        line = frame.f_lineno
    else:
        line = None
        for start, end, lineno in code.co_lines():
            if start <= offset < end:
                line = lineno
                break
        if line is None:
            line = code.co_firstlineno
    column: int | None = None
    try:
        positions = list(code.co_positions())
        index = offset // 2
        if 0 <= index < len(positions):
            _start_line, _end_line, start_col, _end_col = positions[index]
            if type(start_col) is int and start_col >= 0:
                column = start_col
    except (AttributeError, TypeError, ValueError):
        column = None
    return line, column


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Closed collection bounds for one hermetic recording."""

    collect_call: bool = True
    collect_return: bool = True
    collect_line: bool = True
    collect_exception: bool = True
    collect_handler: bool = True
    collect_yield: bool = True
    collect_await: bool = True
    collect_external: bool = True
    include_callees: bool = True
    collect_locals: bool = True
    deny_network: bool = True
    deny_subprocess: bool = True
    max_events: int = 4_096
    max_stack_depth: int = 32
    max_payload_bytes: int = 4_096
    max_summary_keys: int = 32
    max_summary_depth: int = 2
    max_text_chars: int = 128
    line_stride: int = 1
    exclude_filename_prefixes: tuple[str, ...] = _DEFAULT_EXCLUDE_PREFIXES
    schema: str = TRACE_COLLECTION_POLICY_SCHEMA

    SCHEMA: ClassVar[str] = TRACE_COLLECTION_POLICY_SCHEMA
    INTERFACE: ClassVar[str] = "TraceCollectionPolicy@1"

    def __post_init__(self) -> None:
        if self.schema != TRACE_COLLECTION_POLICY_SCHEMA:
            raise PythonExecutionTraceError(
                f"unsupported collection-policy schema {self.schema!r}"
            )
        for name in (
            "collect_call",
            "collect_return",
            "collect_line",
            "collect_exception",
            "collect_handler",
            "collect_yield",
            "collect_await",
            "collect_external",
            "include_callees",
            "collect_locals",
            "deny_network",
            "deny_subprocess",
        ):
            object.__setattr__(self, name, _bool(getattr(self, name), name))
        object.__setattr__(self, "max_events", _positive_int(self.max_events, "max_events"))
        object.__setattr__(
            self, "max_stack_depth", _positive_int(self.max_stack_depth, "max_stack_depth")
        )
        object.__setattr__(
            self,
            "max_payload_bytes",
            _positive_int(self.max_payload_bytes, "max_payload_bytes"),
        )
        object.__setattr__(
            self,
            "max_summary_keys",
            _positive_int(self.max_summary_keys, "max_summary_keys"),
        )
        object.__setattr__(
            self,
            "max_summary_depth",
            _positive_int(self.max_summary_depth, "max_summary_depth"),
        )
        object.__setattr__(
            self, "max_text_chars", _positive_int(self.max_text_chars, "max_text_chars")
        )
        object.__setattr__(
            self, "line_stride", _positive_int(self.line_stride, "line_stride")
        )
        prefixes = tuple(
            _text(item, "exclude_filename_prefix")
            for item in self.exclude_filename_prefixes
        )
        object.__setattr__(self, "exclude_filename_prefixes", prefixes)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "collect_await": self.collect_await,
            "collect_call": self.collect_call,
            "collect_exception": self.collect_exception,
            "collect_external": self.collect_external,
            "collect_handler": self.collect_handler,
            "collect_line": self.collect_line,
            "collect_locals": self.collect_locals,
            "collect_return": self.collect_return,
            "collect_yield": self.collect_yield,
            "deny_network": self.deny_network,
            "deny_subprocess": self.deny_subprocess,
            "exclude_filename_prefixes": list(self.exclude_filename_prefixes),
            "include_callees": self.include_callees,
            "line_stride": self.line_stride,
            "max_events": self.max_events,
            "max_payload_bytes": self.max_payload_bytes,
            "max_stack_depth": self.max_stack_depth,
            "max_summary_depth": self.max_summary_depth,
            "max_summary_keys": self.max_summary_keys,
            "max_text_chars": self.max_text_chars,
            "schema": self.schema,
        }

    @property
    def capture_profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["capture_profile_cid"] = self.capture_profile_cid
        return payload

    def admits(self, kind: str) -> bool:
        mapping = {
            EventKind.CALL.value: self.collect_call,
            EventKind.RETURN.value: self.collect_return,
            EventKind.LINE.value: self.collect_line,
            EventKind.RAISE.value: self.collect_exception,
            EventKind.CATCH.value: self.collect_handler,
            EventKind.HANDLER.value: self.collect_handler,
            EventKind.YIELD.value: self.collect_yield,
            EventKind.AWAIT.value: self.collect_await,
            EventKind.EXTERNAL.value: self.collect_external,
        }
        return mapping.get(kind, False)


@dataclass(frozen=True, slots=True)
class TraceRedactor:
    """Omit secrets and forbidden fields from bounded summaries."""

    extra_markers: tuple[str, ...] = ()
    privacy_class: PrivacyClass | str = PrivacyClass.PUBLIC
    schema: str = TRACE_REDACTOR_SCHEMA

    SCHEMA: ClassVar[str] = TRACE_REDACTOR_SCHEMA
    INTERFACE: ClassVar[str] = "TraceRedactor@1"

    def __post_init__(self) -> None:
        if self.schema != TRACE_REDACTOR_SCHEMA:
            raise PythonExecutionTraceError(f"unsupported redactor schema {self.schema!r}")
        markers = tuple(_text(item, "extra_marker") for item in self.extra_markers)
        object.__setattr__(self, "extra_markers", markers)
        privacy = self.privacy_class
        if isinstance(privacy, PrivacyClass):
            privacy = privacy.value
        object.__setattr__(self, "privacy_class", _text(privacy, "privacy_class"))

    @property
    def markers(self) -> frozenset[str]:
        return SECRET_FIELD_MARKERS | frozenset(self.extra_markers)

    def is_forbidden_key(self, key: str) -> bool:
        if type(key) is not str:
            return True
        if _is_secret_key(key):
            return True
        lowered = key.lower().replace("-", "_")
        return any(
            lowered == marker or lowered.endswith(f"_{marker}")
            for marker in self.extra_markers
        )

    def profile(self, *, redacted: bool) -> RedactionProfile | None:
        if not redacted:
            return None
        return RedactionProfile(
            privacy_class=self.privacy_class,
            redacted_dimensions=("secrets",),
            completeness_claim=CompletenessClaim.REDACTED,
        )

    def bound_value(
        self,
        value: Any,
        *,
        policy: TraceCollectionPolicy,
        depth: int = 0,
        budget: list[int],
        redacted: list[bool],
    ) -> Any:
        if budget[0] <= 0 or depth > policy.max_summary_depth:
            return {"unavailable": "bound"}
        if value is None or type(value) is bool:
            budget[0] -= 1
            return value
        if type(value) is int and not isinstance(value, bool):
            budget[0] -= 8
            if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
                return {"unavailable": "integer_range"}
            return value
        if type(value) is str:
            text = value[: policy.max_text_chars]
            budget[0] -= len(text)
            return text
        if type(value) is bytes:
            budget[0] -= 8
            return {"type": "bytes", "length": min(len(value), MAX_SAFE_INTEGER)}
        if isinstance(value, Mapping):
            items: dict[str, Any] = {}
            for index, key in enumerate(sorted(value, key=lambda item: str(item))):
                if index >= policy.max_summary_keys or budget[0] <= 0:
                    break
                if type(key) is not str or self.is_forbidden_key(key):
                    redacted[0] = True
                    continue
                items[key] = self.bound_value(
                    value[key],
                    policy=policy,
                    depth=depth + 1,
                    budget=budget,
                    redacted=redacted,
                )
            return items
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            items = []
            for index, item in enumerate(value):
                if index >= policy.max_summary_keys or budget[0] <= 0:
                    break
                items.append(
                    self.bound_value(
                        item,
                        policy=policy,
                        depth=depth + 1,
                        budget=budget,
                        redacted=redacted,
                    )
                )
            return items
        budget[0] -= 8
        type_name = type(value).__name__
        if type(type_name) is str and type_name.isidentifier():
            return {"type": type_name}
        return {"unavailable": "object"}

    def summarize_locals(
        self,
        frame: FrameType,
        *,
        policy: TraceCollectionPolicy,
    ) -> tuple[dict[str, Any], bool]:
        if not policy.collect_locals:
            return {}, False
        redacted = [False]
        budget = [policy.max_payload_bytes]
        try:
            raw_locals = dict(frame.f_locals)
        except Exception:
            return {}, False
        summary = self.bound_value(
            raw_locals,
            policy=policy,
            budget=budget,
            redacted=redacted,
        )
        if not isinstance(summary, dict):
            return {}, redacted[0]
        return summary, redacted[0]


class TraceCancellation:
    """One-shot cancellation token; cancelled recordings admit no transition."""

    __slots__ = ("_cancelled", "_reason")
    SCHEMA: ClassVar[str] = TRACE_CANCELLATION_SCHEMA
    INTERFACE: ClassVar[str] = "TraceCancellation@1"

    def __init__(self) -> None:
        self._cancelled = False
        self._reason = ""

    def cancel(self, reason: str = "cancelled") -> None:
        text = reason if type(reason) is str and reason.strip() else "cancelled"
        self._reason = _nfc(text.strip())
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "cancelled": self._cancelled,
            "reason": self._reason,
            "schema": TRACE_CANCELLATION_SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class TraceTransition:
    """Observed successor edge.  ``accepted`` is true only for complete runs."""

    predecessor_event_cid: str
    successor_event_cid: str
    action: str
    accepted: bool
    schema: str = TRACE_TRANSITION_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "predecessor_event_cid",
            _cid(self.predecessor_event_cid, "predecessor_event_cid"),
        )
        object.__setattr__(
            self,
            "successor_event_cid",
            _cid(self.successor_event_cid, "successor_event_cid"),
        )
        object.__setattr__(self, "action", _text(self.action, "action"))
        object.__setattr__(self, "accepted", _bool(self.accepted, "accepted"))
        if self.schema != TRACE_TRANSITION_SCHEMA:
            raise PythonExecutionTraceError("unsupported transition schema")
        if self.accepted and self.predecessor_event_cid == self.successor_event_cid:
            raise PythonExecutionTraceError("accepted transitions cannot be self-loops")

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "action": self.action,
            "predecessor_event_cid": self.predecessor_event_cid,
            "schema": self.schema,
            "successor_event_cid": self.successor_event_cid,
        }


def _accepted_transitions(
    events: Sequence[ProgramEvent],
    *,
    accepted: bool,
) -> tuple[TraceTransition, ...]:
    if not accepted:
        return ()
    transitions: list[TraceTransition] = []
    previous: ProgramEvent | None = None
    for event in events:
        if previous is not None:
            transitions.append(
                TraceTransition(
                    predecessor_event_cid=previous.program_event_cid,
                    successor_event_cid=event.program_event_cid,
                    action=str(event.event_kind),
                    accepted=True,
                )
            )
        previous = event
    return tuple(transitions)


@dataclass(frozen=True, slots=True)
class HermeticTraceRecord:
    """Private recording plus a public view that never carries raw bodies."""

    status: TraceStatus | str
    events: tuple[ProgramEvent, ...]
    private_trace: ExecutionTrace
    public_trace: ExecutionTrace
    policy: TraceCollectionPolicy
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    capture_profile_cid: str
    accepted_transitions: tuple[TraceTransition, ...]
    private_raw_bodies: tuple[Mapping[str, Any], ...] = ()
    result_summary: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    cancelled_reason: str = ""
    schema: str = HERMETIC_TRACE_SCHEMA

    def __post_init__(self) -> None:
        status = self.status
        if not isinstance(status, TraceStatus):
            status = TraceStatus(status)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self,
            "capture_profile_cid",
            _cid(self.capture_profile_cid, "capture_profile_cid"),
        )
        if self.schema != HERMETIC_TRACE_SCHEMA:
            raise PythonExecutionTraceError("unsupported hermetic-trace schema")
        if self.public_trace.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if str(self.public_trace.privacy_class) not in {"public", "internal"}:
            if self.public_trace.raw_execution_state_cids:
                raise PythonExecutionTraceError(
                    "private raw trace bodies never enter public records"
                )
        if self.public_trace.raw_execution_state_cids:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        object.__setattr__(
            self, "result_summary", MappingProxyType(dict(self.result_summary))
        )
        object.__setattr__(
            self,
            "private_raw_bodies",
            tuple(MappingProxyType(dict(item)) for item in self.private_raw_bodies),
        )

    @property
    def accepted(self) -> bool:
        return self.status is TraceStatus.COMPLETED and bool(self.accepted_transitions)

    @property
    def cancelled(self) -> bool:
        return self.status is TraceStatus.CANCELLED

    @property
    def execution_trace_cid(self) -> str:
        return self.public_trace.execution_trace_cid

    def to_dict(self) -> dict[str, Any]:
        """Public record.  Private raw bodies are intentionally absent."""

        return {
            "accepted": self.status is TraceStatus.COMPLETED
            and bool(self.accepted_transitions),
            "accepted_transitions": [item.to_dict() for item in self.accepted_transitions],
            "cancelled": self.cancelled,
            "cancelled_reason": self.cancelled_reason,
            "capture_profile_cid": self.capture_profile_cid,
            "completeness_claim": self.public_trace.completeness_claim,
            "environment_binding_cid": self.environment_binding_cid,
            "error": self.error,
            "event_cids": list(self.public_trace.event_cids),
            "event_kinds": [str(event.event_kind) for event in self.events],
            "evidence": EVIDENCE_CLASS,
            "execution_trace_cid": self.public_trace.execution_trace_cid,
            "includes_raw_bodies": False,
            "interface": PYTHON_EXECUTION_TRACE_INTERFACE,
            "logical_names": [event.logical_name for event in self.events],
            "privacy_class": self.public_trace.privacy_class,
            "public_trace": self.public_trace.to_dict(),
            "result_summary": dict(self.result_summary),
            "schema": self.schema,
            "source_cid": self.source_cid,
            "status": str(self.status),
            "tree_cid": self.tree_cid,
            "unavailable_dimensions": list(self.public_trace.unavailable_dimensions),
        }

    to_public_dict = to_dict


@dataclass(frozen=True, slots=True)
class HermeticTraceReplay:
    """Deterministic replay comparison under the original bindings."""

    original: HermeticTraceRecord
    replayed: HermeticTraceRecord
    matched: bool
    promised: bool = True
    schema: str = HERMETIC_TRACE_REPLAY_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "original_execution_trace_cid": self.original.execution_trace_cid,
            "promised": self.promised,
            "replayed_execution_trace_cid": self.replayed.execution_trace_cid,
            "schema": self.schema,
        }


def _ensure_audit_hook() -> None:
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    sys.addaudithook(_audit_dispatcher)
    _HOOK_INSTALLED = True


def _audit_dispatcher(event: str, args: tuple[Any, ...]) -> None:
    isolation = getattr(_TLS, "isolation", None)
    if isolation is None:
        return
    isolation.audit(event, args)


class _Isolation:
    def __init__(self, policy: TraceCollectionPolicy, session: "_TraceSession") -> None:
        self.policy = policy
        self.session = session

    def audit(self, event: str, _args: tuple[Any, ...]) -> None:
        if event in _NETWORK_AUDIT_EVENTS and self.policy.deny_network:
            self.session.note_external("network", event)
            raise PythonExecutionTraceError(
                "network denied during hermetic tracing"
            )
        if event in _SUBPROCESS_AUDIT_EVENTS and self.policy.deny_subprocess:
            self.session.note_external("subprocess", event)
            raise PythonExecutionTraceError(
                "subprocess denied during hermetic tracing"
            )


class _TraceSession:
    def __init__(
        self,
        *,
        policy: TraceCollectionPolicy,
        redactor: TraceRedactor,
        cancellation: TraceCancellation | None,
        tree_cid: str,
        source_cid: str,
        environment_binding_cid: str,
        target_code: CodeType,
        target_filename: str,
    ) -> None:
        self.policy = policy
        self.redactor = redactor
        self.cancellation = cancellation
        self.tree_cid = tree_cid
        self.source_cid = source_cid
        self.environment_binding_cid = environment_binding_cid
        self.target_code = target_code
        self.target_filename = target_filename.replace("\\", "/")
        self.events: list[ProgramEvent] = []
        self.private_raw_bodies: list[dict[str, Any]] = []
        self.cancelled_seen = False
        self.truncated = False
        self.redacted = False
        self.line_count = 0
        self.last_event_cid: str | None = None
        self.last_frames: tuple[StackFrameState, ...] = ()
        self.external_attempts: list[str] = []
        self._emit_depth = 0
        self._pending_handler: CodeType | None = None
        self._coroutine_started: set[int] = set()

    def stop_admission(self) -> bool:
        if self.cancellation is not None and self.cancellation.cancelled:
            self.cancelled_seen = True
            return True
        if self.truncated:
            return True
        return False

    def note_external(self, kind: str, event: str) -> None:
        self.external_attempts.append(f"{kind}:{event}")
        if self.stop_admission() or not self.policy.collect_external:
            return
        self._emit_depth += 1
        try:
            frame = sys._getframe(2)
            code = frame.f_code if frame is not None else self.target_code
            self._emit(
                EventKind.EXTERNAL.value,
                code,
                0,
                frame,
                payload={"effect": event, "kind": kind},
                include_locals=False,
            )
        finally:
            self._emit_depth -= 1

    def admits_code(self, code: CodeType) -> bool:
        if _is_tracer_code(code):
            return False
        filename = code.co_filename.replace("\\", "/")
        if _is_excluded_filename(filename, self.policy.exclude_filename_prefixes):
            return False
        if code is self.target_code or filename == self.target_filename:
            return True
        return self.policy.include_callees

    def _stack(self, frame: FrameType | None) -> tuple[StackFrameState, ...]:
        collected: list[FrameType] = []
        current = frame
        while current is not None and len(collected) < self.policy.max_stack_depth:
            code = current.f_code
            if self.admits_code(code):
                collected.append(current)
            if code is self.target_code:
                break
            current = current.f_back
        frames: list[StackFrameState] = []
        for ordinal, current in enumerate(collected):
            code = current.f_code
            module = _module_of(current, code)
            logical = _logical_name(code, module)
            code_cid = _code_cid(code, logical)
            summary, redacted = self.redactor.summarize_locals(
                current, policy=self.policy
            )
            if redacted:
                self.redacted = True
            claim = (
                CompletenessClaim.REDACTED if redacted else CompletenessClaim.FULL_STATE
            )
            frames.append(
                StackFrameState(
                    ordinal=ordinal,
                    language=ProgramLanguage.PYTHON,
                    tree_cid=self.tree_cid,
                    source_cid=self.source_cid,
                    code_cid=code_cid,
                    environment_binding_cid=self.environment_binding_cid,
                    logical_name=logical,
                    line=current.f_lineno if type(current.f_lineno) is int else 0,
                    column=0,
                    state_summary={"locals": summary} if summary else {},
                    redacted_dimensions=("secrets",) if redacted else (),
                    completeness_claim=claim,
                    privacy_class=PrivacyClass.INTERNAL,
                )
            )
        self.last_frames = tuple(frames)
        return self.last_frames

    def _emit(
        self,
        kind: str,
        code: CodeType,
        offset: int,
        frame: FrameType | None,
        *,
        payload: Mapping[str, Any] | None = None,
        include_locals: bool = False,
        exception: BaseException | None = None,
    ) -> None:
        if self.stop_admission():
            return
        if not self.policy.admits(kind):
            return
        if kind == EventKind.LINE.value:
            self.line_count += 1
            if self.line_count % self.policy.line_stride != 0:
                return
        if len(self.events) >= self.policy.max_events:
            self.truncated = True
            return
        module = _module_of(frame, code)
        logical = _logical_name(code, module)
        code_cid = _code_cid(code, logical)
        line, column = _line_column(code, offset, frame)
        frames = self._stack(frame) if kind != EventKind.LINE.value else ()
        if kind == EventKind.LINE.value and line is None:
            line = code.co_firstlineno
        redacted_dimensions: tuple[str, ...] = ("secrets",) if self.redacted else ()
        claim: CompletenessClaim | str = (
            CompletenessClaim.REDACTED if self.redacted else CompletenessClaim.FULL_STATE
        )
        unavailable: tuple[str, ...] = ()
        if kind != EventKind.LINE.value and not frames:
            unavailable = ("call_stack",)
            claim = CompletenessClaim.PARTIAL
        exception_cid = None
        handler_cid = None
        if kind == EventKind.RAISE.value:
            if exception is not None:
                snapshot = ExceptionSnapshot(
                    language=ProgramLanguage.PYTHON,
                    exception_type=type(exception).__name__,
                    tree_cid=self.tree_cid,
                    source_cid=self.source_cid,
                    code_cid=code_cid,
                    environment_binding_cid=self.environment_binding_cid,
                    exception_value_summary={"type": type(exception).__name__},
                    traceback_stack_frame_cids=tuple(
                        item.stack_frame_state_cid for item in frames
                    ),
                    completeness_claim=(
                        CompletenessClaim.PARTIAL
                        if not frames
                        else CompletenessClaim.FULL_STATE
                    ),
                    unavailable_dimensions=("call_stack",) if not frames else (),
                )
                exception_cid = snapshot.exception_snapshot_cid
            elif "exception" not in unavailable:
                unavailable = tuple(sorted(set(unavailable) | {"exception"}))
                if str(claim) == CompletenessClaim.FULL_STATE.value:
                    claim = CompletenessClaim.PARTIAL
        if kind in {EventKind.CATCH.value, EventKind.HANDLER.value}:
            handler = HandlerState(
                language=ProgramLanguage.PYTHON,
                handler_kind=HandlerKind.EXCEPT,
                tree_cid=self.tree_cid,
                source_cid=self.source_cid,
                code_cid=code_cid,
                environment_binding_cid=self.environment_binding_cid,
                logical_name=logical,
                stack_ordinal=0,
                handler_active=True,
                matching_exception_snapshot_cid=None,
                unavailable_dimensions=("exception",),
            )
            handler_cid = handler.handler_state_cid
        event_payload = dict(payload or {})
        if include_locals and frame is not None:
            summary, redacted = self.redactor.summarize_locals(
                frame, policy=self.policy
            )
            if redacted:
                self.redacted = True
                redacted_dimensions = ("secrets",)
                claim = CompletenessClaim.REDACTED
            if summary:
                self.private_raw_bodies.append({"kind": kind, "locals": summary})
                event_payload["locals_keys"] = sorted(summary)[: self.policy.max_summary_keys]
        try:
            event = ProgramEvent(
                event_kind=kind,
                event_origin=EventOrigin.OBSERVED,
                observation_status=ObservationStatus.OBSERVED,
                language=ProgramLanguage.PYTHON,
                tree_cid=self.tree_cid,
                source_cid=self.source_cid,
                code_cid=code_cid,
                environment_binding_cid=self.environment_binding_cid,
                subject_cid=_subject_cid(logical, code_cid),
                logical_name=logical,
                payload=event_payload,
                line=line,
                column=column,
                predecessor_event_cid=self.last_event_cid,
                stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
                exception_snapshot_cid=exception_cid,
                handler_state_cid=handler_cid,
                redaction_profile_cid=(
                    None
                    if not redacted_dimensions
                    else self.redactor.profile(redacted=True).redaction_profile_cid
                    if self.redactor.profile(redacted=True) is not None
                    else None
                ),
                redacted_dimensions=redacted_dimensions,
                unavailable_dimensions=unavailable,
                completeness_claim=claim,
                privacy_class=PrivacyClass.INTERNAL,
            )
        except ProgramExecutionError:
            return
        self.events.append(event)
        self.last_event_cid = event.program_event_cid

    def _maybe_external(self, frame: FrameType) -> None:
        module = _module_of(frame, frame.f_code)
        root = module.split(".", 1)[0] if module else ""
        caller = frame.f_back
        if (
            root in _EXTERNAL_ROOT_MODULES
            and self.policy.collect_external
            and caller is not None
            and self.admits_code(caller.f_code)
        ):
            self._emit(
                EventKind.EXTERNAL.value,
                caller.f_code,
                caller.f_lasti if caller.f_lasti >= 0 else 0,
                caller,
                payload={"callee": _logical_name(frame.f_code, module), "module": root},
                include_locals=False,
            )

    def handle_trace(self, frame: FrameType, event: str, arg: Any) -> Any:
        if self._emit_depth:
            return self.handle_trace
        if _is_tracer_code(frame.f_code):
            return self.handle_trace
        admitted = self.admits_code(frame.f_code)
        if event == "call" and not admitted:
            self._emit_depth += 1
            try:
                self._maybe_external(frame)
            finally:
                self._emit_depth -= 1
            return self.handle_trace
        if not admitted:
            return self.handle_trace
        self._emit_depth += 1
        try:
            offset = frame.f_lasti if type(frame.f_lasti) is int and frame.f_lasti >= 0 else 0
            flags = frame.f_code.co_flags
            if event == "call":
                self._emit(
                    EventKind.CALL.value,
                    frame.f_code,
                    offset,
                    frame,
                    include_locals=True,
                )
                code_id = id(frame.f_code)
                if flags & (_CO_COROUTINE | _CO_ITERABLE_COROUTINE | _CO_ASYNC_GENERATOR):
                    if code_id in self._coroutine_started:
                        self._emit(
                            EventKind.AWAIT.value,
                            frame.f_code,
                            offset,
                            frame,
                            include_locals=True,
                        )
                    else:
                        self._coroutine_started.add(code_id)
            elif event == "return":
                opname = _opname_at(frame)
                is_coro = bool(
                    flags
                    & (_CO_COROUTINE | _CO_ITERABLE_COROUTINE | _CO_ASYNC_GENERATOR)
                )
                is_gen = bool(flags & _CO_GENERATOR)
                yielded = opname in _YIELD_OPNAMES or (
                    is_gen
                    and opname
                    not in {
                        "RETURN_VALUE",
                        "RETURN_CONST",
                        "RETURN_GENERATOR",
                        "",
                    }
                )
                if yielded:
                    kind = EventKind.AWAIT.value if is_coro else EventKind.YIELD.value
                    self._emit(
                        kind,
                        frame.f_code,
                        offset,
                        frame,
                        include_locals=True,
                    )
                else:
                    self._emit(
                        EventKind.RETURN.value,
                        frame.f_code,
                        offset,
                        frame,
                        include_locals=True,
                    )
            elif event == "exception":
                exception = arg[1] if isinstance(arg, tuple) and len(arg) > 1 else None
                self._emit(
                    EventKind.RAISE.value,
                    frame.f_code,
                    offset,
                    frame,
                    payload={
                        "exception_type": type(exception).__name__
                        if exception is not None
                        else "Exception"
                    },
                    include_locals=True,
                    exception=exception if isinstance(exception, BaseException) else None,
                )
                self._pending_handler = frame.f_code
            elif event == "line":
                if self._pending_handler is frame.f_code:
                    self._emit(
                        EventKind.HANDLER.value,
                        frame.f_code,
                        offset,
                        frame,
                        include_locals=True,
                    )
                    self._pending_handler = None
                self._emit(
                    EventKind.LINE.value,
                    frame.f_code,
                    offset,
                    frame,
                    payload={"line": frame.f_lineno} if type(frame.f_lineno) is int else {},
                )
        except Exception:
            pass
        finally:
            self._emit_depth -= 1
        return self.handle_trace


def _placeholder_event(
    *,
    tree_cid: str,
    source_cid: str,
    environment_binding_cid: str,
    logical_name: str,
    reason: str,
) -> ProgramEvent:
    code_cid = cid_for_bytes(logical_name.encode("utf-8"))
    return ProgramEvent(
        event_kind=EventKind.OBSERVE,
        event_origin=EventOrigin.OBSERVED,
        observation_status=ObservationStatus.UNAVAILABLE,
        language=ProgramLanguage.PYTHON,
        tree_cid=tree_cid,
        source_cid=source_cid,
        code_cid=code_cid,
        environment_binding_cid=environment_binding_cid,
        subject_cid=_subject_cid(logical_name, code_cid),
        logical_name=logical_name,
        payload={"reason": reason},
        line=0,
        column=0,
        unavailable_dimensions=("call_stack", "trace_body"),
        completeness_claim=CompletenessClaim.UNAVAILABLE,
        privacy_class=PrivacyClass.INTERNAL,
    )


def _assemble_record(
    *,
    session: _TraceSession | None,
    status: TraceStatus,
    policy: TraceCollectionPolicy,
    redactor: TraceRedactor,
    tree_cid: str,
    source_cid: str,
    environment_binding_cid: str,
    logical_name: str,
    result_summary: Mapping[str, Any],
    error: str | None,
    cancelled_reason: str,
) -> HermeticTraceRecord:
    events = list(session.events) if session is not None else []
    private_raw_bodies = tuple(session.private_raw_bodies) if session is not None else ()
    redacted = bool(session.redacted) if session is not None else False
    truncated = bool(session.truncated) if session is not None else False
    cancelled = status is TraceStatus.CANCELLED
    if not events:
        events.append(
            _placeholder_event(
                tree_cid=tree_cid,
                source_cid=source_cid,
                environment_binding_cid=environment_binding_cid,
                logical_name=logical_name,
                reason=cancelled_reason or str(status),
            )
        )
    unavailable: list[str] = []
    if cancelled:
        unavailable.append("trace_suffix")
    if truncated:
        unavailable.append("trace_suffix")
    if redacted:
        claim: CompletenessClaim | str = CompletenessClaim.REDACTED
        redacted_dimensions: tuple[str, ...] = ("secrets",)
    elif unavailable:
        claim = CompletenessClaim.PARTIAL
        redacted_dimensions = ()
    else:
        claim = CompletenessClaim.FULL_STATE
        redacted_dimensions = ()
    frames = session.last_frames if session is not None else ()
    states: tuple[ProgramExecutionState, ...] = ()
    includes_raw = False
    if frames and private_raw_bodies:
        includes_raw = True
        observed = {"frames": len(frames)}
        try:
            states = (
                assemble_program_execution_state(
                    capture_profile_cid=policy.capture_profile_cid,
                    tree_cid=tree_cid,
                    source_cid=source_cid,
                    environment_binding_cid=environment_binding_cid,
                    frames=frames,
                    observed_state=observed,
                    heap_bound=HeapBound.BOUNDED_ABSTRACT,
                    redaction=redactor.profile(redacted=redacted),
                    completeness_claim=claim,
                    privacy_class=PrivacyClass.PRIVATE,
                    includes_raw_bodies=True,
                    unavailable_dimensions=unavailable,
                ),
            )
        except ProgramExecutionError:
            includes_raw = False
            states = ()
    private_trace = assemble_execution_trace(
        tree_cid=tree_cid,
        source_cid=source_cid,
        environment_binding_cid=environment_binding_cid,
        events=events,
        states=states,
        redaction=redactor.profile(redacted=redacted),
        completeness_claim=claim,
        privacy_class=PrivacyClass.PRIVATE if includes_raw else PrivacyClass.INTERNAL,
        includes_raw_bodies=includes_raw,
        unavailable_dimensions=unavailable,
    )
    public_trace = private_trace.public_view()
    accepted = status is TraceStatus.COMPLETED and not cancelled and not truncated
    transitions = _accepted_transitions(events, accepted=accepted)
    return HermeticTraceRecord(
        status=status,
        events=tuple(events),
        private_trace=private_trace,
        public_trace=public_trace,
        policy=policy,
        tree_cid=tree_cid,
        source_cid=source_cid,
        environment_binding_cid=environment_binding_cid,
        capture_profile_cid=policy.capture_profile_cid,
        accepted_transitions=transitions,
        private_raw_bodies=private_raw_bodies,
        result_summary=result_summary,
        error=error,
        cancelled_reason=cancelled_reason,
    )


def record_python_execution_trace(
    target: Callable[..., Any],
    /,
    *args: Any,
    tree_cid: str,
    source_cid: str | None = None,
    environment_binding_cid: str | None = None,
    policy: TraceCollectionPolicy | None = None,
    redactor: TraceRedactor | None = None,
    cancellation: TraceCancellation | None = None,
    **kwargs: Any,
) -> HermeticTraceRecord:
    """Record one hermetic execution of ``target``.

    The returned public record never includes private raw trace bodies.
    Cancellation, including pre-start cancellation, emits no accepted
    transition.
    """

    if not callable(target):
        raise PythonExecutionTraceError("target must be callable")
    policy = policy or TraceCollectionPolicy()
    redactor = redactor or TraceRedactor()
    tree = _cid(tree_cid, "tree_cid")
    source = _cid(source_cid, "source_cid") if source_cid is not None else bind_source_cid(target)
    environment = (
        _cid(environment_binding_cid, "environment_binding_cid")
        if environment_binding_cid is not None
        else bind_environment_cid()
    )
    code = _target_code(target)
    logical = _logical_name(code, getattr(target, "__module__", None))
    if cancellation is not None and cancellation.cancelled:
        return _assemble_record(
            session=None,
            status=TraceStatus.CANCELLED,
            policy=policy,
            redactor=redactor,
            tree_cid=tree,
            source_cid=source,
            environment_binding_cid=environment,
            logical_name=logical,
            result_summary={},
            error=None,
            cancelled_reason=cancellation.reason or "cancelled",
        )

    session = _TraceSession(
        policy=policy,
        redactor=redactor,
        cancellation=cancellation,
        tree_cid=tree,
        source_cid=source,
        environment_binding_cid=environment,
        target_code=code,
        target_filename=code.co_filename,
    )
    isolation = _Isolation(policy, session)
    _ensure_audit_hook()
    previous_isolation = getattr(_TLS, "isolation", None)
    previous_trace = sys.gettrace()
    _TLS.isolation = isolation
    error: str | None = None
    result: Any = None
    status = TraceStatus.COMPLETED
    try:
        sys.settrace(session.handle_trace)
        try:
            result = target(*args, **kwargs)
        except PythonExecutionTraceError as exc:
            error = str(exc)
            status = (
                TraceStatus.CANCELLED if session.cancelled_seen else TraceStatus.FAILED
            )
        except BaseException as exc:
            error = type(exc).__name__
            status = TraceStatus.FAILED
        finally:
            sys.settrace(previous_trace)
        if session.cancelled_seen or (cancellation is not None and cancellation.cancelled):
            status = TraceStatus.CANCELLED
        redacted_flag = [False]
        summary = redactor.bound_value(
            {"result_type": type(result).__name__},
            policy=policy,
            budget=[policy.max_payload_bytes],
            redacted=redacted_flag,
        )
        if not isinstance(summary, dict):
            summary = {}
        return _assemble_record(
            session=session,
            status=status,
            policy=policy,
            redactor=redactor,
            tree_cid=tree,
            source_cid=source,
            environment_binding_cid=environment,
            logical_name=logical,
            result_summary=summary,
            error=error,
            cancelled_reason=(
                cancellation.reason
                if cancellation is not None and cancellation.cancelled
                else ""
            ),
        )
    finally:
        sys.settrace(previous_trace)
        _TLS.isolation = previous_isolation


def replay_deterministic_trace(
    record: HermeticTraceRecord,
    target: Callable[..., Any],
    /,
    *args: Any,
    cancellation: TraceCancellation | None = None,
    **kwargs: Any,
) -> HermeticTraceReplay:
    """Replay ``target`` under the original tree, source, environment, and policy."""

    if not isinstance(record, HermeticTraceRecord):
        raise PythonExecutionTraceError("replay requires a HermeticTraceRecord")
    replayed = record_python_execution_trace(
        target,
        *args,
        tree_cid=record.tree_cid,
        source_cid=record.source_cid,
        environment_binding_cid=record.environment_binding_cid,
        policy=record.policy,
        cancellation=cancellation,
        **kwargs,
    )
    matched = (
        not record.cancelled
        and not replayed.cancelled
        and record.status is TraceStatus.COMPLETED
        and replayed.status is TraceStatus.COMPLETED
        and record.public_trace.execution_trace_cid == replayed.public_trace.execution_trace_cid
        and [event.event_kind for event in record.events]
        == [event.event_kind for event in replayed.events]
    )
    return HermeticTraceReplay(
        original=record,
        replayed=replayed,
        matched=matched,
        promised=True,
    )


class PythonExecutionTracer:
    """Stateful facade over :func:`record_python_execution_trace`."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_INTERFACE

    def __init__(
        self,
        policy: TraceCollectionPolicy | None = None,
        redactor: TraceRedactor | None = None,
    ) -> None:
        self.policy = policy or TraceCollectionPolicy()
        self.redactor = redactor or TraceRedactor()

    def record(
        self,
        target: Callable[..., Any],
        /,
        *args: Any,
        tree_cid: str,
        source_cid: str | None = None,
        environment_binding_cid: str | None = None,
        cancellation: TraceCancellation | None = None,
        **kwargs: Any,
    ) -> HermeticTraceRecord:
        return record_python_execution_trace(
            target,
            *args,
            tree_cid=tree_cid,
            source_cid=source_cid,
            environment_binding_cid=environment_binding_cid,
            policy=self.policy,
            redactor=self.redactor,
            cancellation=cancellation,
            **kwargs,
        )

    def replay(
        self,
        record: HermeticTraceRecord,
        target: Callable[..., Any],
        /,
        *args: Any,
        cancellation: TraceCancellation | None = None,
        **kwargs: Any,
    ) -> HermeticTraceReplay:
        return replay_deterministic_trace(
            record,
            target,
            *args,
            cancellation=cancellation,
            **kwargs,
        )


__all__ = [
    "ALGORITHM_VERSION",
    "EVIDENCE_CLASS",
    "HERMETIC_TRACE_SCHEMA",
    "PYTHON_EXECUTION_TRACE_INTERFACE",
    "TASK_ID",
    "HermeticTraceRecord",
    "HermeticTraceReplay",
    "PythonExecutionTraceError",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCollectionPolicy",
    "TraceRedactor",
    "TraceStatus",
    "TraceTransition",
    "bind_environment_cid",
    "bind_source_cid",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
