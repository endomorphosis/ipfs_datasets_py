"""Hermetic Python execution tracing adapter (SAWM-008).

Collect admitted call, return, line, exception, handler, yield, await, and
selected external events with bounded state summaries and exact symbol,
callsite, source, tree, and environment identity.  Python runtime tracing
hooks are the only collection mechanism: this module does not shell-out,
install packages, open sockets, scan a repository, start watchers, or load
models.

Authority rules (normative):

* Datasets owns event/trace meaning through the SAWM-007 contracts.  This
  adapter never persists operational acceptance and cannot admit a program
  transition.
* Cancellation stops collection and emits no accepted transition.
* Private raw trace bodies never enter public records.
* Secret and non-semantic fields fail closed.  Nondeterministic external
  effects are explicit observations or typed unavailable.
* Line and basic-block detail is policy- and cost-bounded.  Unsupported
  languages remain typed unavailable.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import CodeType, FrameType
from typing import Any, ClassVar, Final
import dis
import inspect
import sys
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
    validate_cid,
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
    PUBLIC_PRIVACY_CLASSES,
    REQUIRED_EVENT_KINDS,
    SECRET_FIELD_MARKERS,
    StackFrameState,
    assemble_execution_trace,
    assemble_program_execution_state,
    observe_program_event,
    public_execution_view,
)


PYTHON_EXECUTION_TRACER_INTERFACE: Final[str] = "PythonExecutionTracer@1"
TRACE_COLLECTION_POLICY_INTERFACE: Final[str] = "TraceCollectionPolicy@1"
TRACE_REDACTOR_INTERFACE: Final[str] = "TraceRedactor@1"
TRACE_CANCELLATION_INTERFACE: Final[str] = "TraceCancellation@1"
PYTHON_EXECUTION_TRACE_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-trace-record@1"
)
TRACE_COLLECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-policy@1"
)
PYTHON_SYMBOL_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-symbol@1"
)
PYTHON_ENVIRONMENT_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-environment@1"
)
HERMETIC_TRACE_EVIDENCE: Final[str] = "sawm/hermetic-trace@1"

DEFAULT_ADMITTED_EVENT_KINDS: Final[tuple[str, ...]] = (
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

_NETWORK_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "socket.connect",
        "socket.sendto",
        "socket.sendmsg",
        "socket.bind",
        "socket.listen",
        "socket.accept",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyname_ex",
        "socket.gethostbyaddr",
        "socket.getnameinfo",
        "socket.getservbyname",
        "socket.getservbyport",
        "socket.sethostname",
        "ssl.wrap_socket",
        "urllib.Request",
        "http.client.connect",
    }
)
_SUBPROCESS_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
    }
)
_DATABASE_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "sqlite3.connect",
    }
)
_INSTALLER_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "pip.main",
        "ensurepip.bootstrap",
    }
)

_ALWAYS_UNAVAILABLE: Final[tuple[str, ...]] = ("heap", "native_stack")
_MAX_LOCAL_KEYS: Final[int] = 32
_MAX_SUMMARY_DEPTH: Final[int] = 3

_AUDIT_INSTALLED: bool = False
_ACTIVE_TRACERS: list["PythonExecutionTracer"] = []


class PythonExecutionTraceError(ValueError):
    """Raised when tracing inputs, isolation policy, or promised replay fail closed."""


class TraceDisposition(StrEnum):
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    BOUNDED = "bounded"
    FAILED = "failed"


class TraceCancelledError(PythonExecutionTraceError):
    """Raised when a live cancellation token is checked after cancel()."""


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise PythonExecutionTraceError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise PythonExecutionTraceError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise PythonExecutionTraceError(f"{name} contains invalid text")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise PythonExecutionTraceError(f"{name} must be a boolean")
    return value


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 1:
        raise PythonExecutionTraceError(f"{name} must be a positive integer")
    if value > MAX_SAFE_INTEGER:
        raise PythonExecutionTraceError(f"{name} exceeds the safe JSON integer range")
    return value


def _optional_positive_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, name)


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise PythonExecutionTraceError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _privacy(value: Any, name: str = "privacy_class") -> str:
    if isinstance(value, PrivacyClass):
        return value.value
    try:
        return PrivacyClass(value).value
    except (TypeError, ValueError) as exc:
        raise PythonExecutionTraceError(f"{name} has unsupported value {value!r}") from exc


def _is_secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(marker in lowered for marker in SECRET_FIELD_MARKERS)


def _is_forbidden_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return lowered in FORBIDDEN_FIELD_MARKERS or _is_secret_key(key)


def default_python_environment_binding_cid() -> str:
    """Bind the exact running Python implementation without host observations."""

    return cid_for_structured(
        {
            "schema": PYTHON_ENVIRONMENT_IDENTITY_SCHEMA,
            "implementation": sys.implementation.name,
            "version": [
                int(sys.version_info.major),
                int(sys.version_info.minor),
                int(sys.version_info.micro),
            ],
        }
    )


def _logical_name_for_code(code: CodeType, globals_map: Mapping[str, Any] | None = None) -> str:
    qual = getattr(code, "co_qualname", None) or code.co_name or "unknown"
    module = ""
    if globals_map is not None:
        raw = globals_map.get("__name__")
        if type(raw) is str:
            module = raw
    name = f"{module}.{qual}" if module and not qual.startswith(module + ".") else qual
    normalized = unicodedata.normalize("NFC", name).strip()
    if not normalized:
        normalized = "unknown"
    return normalized[:MAX_TEXT_CHARS]


def _column_for_frame(frame: FrameType) -> int | None:
    lasti = frame.f_lasti
    if lasti < 0:
        return None
    try:
        index = lasti // 2
        for offset, position in enumerate(frame.f_code.co_positions()):
            if offset == index:
                column = position[2]
                if type(column) is int and column >= 0:
                    return column
                return None
    except Exception:
        return None
    return None


def _opcode_name(frame: FrameType) -> str | None:
    lasti = frame.f_lasti
    code = frame.f_code.co_code
    if lasti < 0 or lasti >= len(code):
        return None
    opcode = code[lasti]
    try:
        return dis.opname[opcode]
    except Exception:
        return None


def _code_cid(logical_name: str, code: CodeType) -> str:
    return cid_for_structured(
        {
            "schema": PYTHON_SYMBOL_IDENTITY_SCHEMA,
            "logical_name": logical_name,
            "qualname": getattr(code, "co_qualname", code.co_name),
            "firstlineno": int(code.co_firstlineno),
            "bytecode_cid": cid_for_bytes(code.co_code),
        }
    )


def _source_cid_for_callable(target: Callable[..., Any]) -> str:
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError):
        code = getattr(target, "__code__", None)
        if isinstance(code, CodeType):
            return cid_for_bytes(code.co_code)
        raise PythonExecutionTraceError("target source is unavailable")
    return cid_for_bytes(source.encode("utf-8"))


def _bounded_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit]


def bounded_state_summary(
    value: Any,
    *,
    max_bytes: int,
    max_text_chars: int,
    depth: int = 0,
    redactor: "TraceRedactor" | None = None,
) -> tuple[Any, tuple[str, ...], tuple[str, ...]]:
    """Convert a runtime value into bounded DAG-JSON with explicit redaction."""

    redacted: list[str] = []
    unavailable: list[str] = []
    worker = redactor if redactor is not None else TraceRedactor()

    def convert(item: Any, current_depth: int) -> Any:
        if item is None or type(item) is bool:
            return item
        if type(item) is int and not isinstance(item, bool):
            if item < -MAX_SAFE_INTEGER or item > MAX_SAFE_INTEGER:
                unavailable.append("integer_range")
                return {"unavailable_type": "int"}
            return item
        if type(item) is str:
            return _bounded_text(unicodedata.normalize("NFC", item), max_text_chars)
        if type(item) is float:
            unavailable.append("float")
            return {"unavailable_type": "float"}
        if type(item) is bytes:
            unavailable.append("bytes")
            return {"unavailable_type": "bytes", "length": min(len(item), MAX_SAFE_INTEGER)}
        if current_depth >= _MAX_SUMMARY_DEPTH:
            unavailable.append("depth")
            return {"unavailable_type": type(item).__name__[:64]}
        if isinstance(item, Mapping):
            mapping, hidden, missing = worker.redact_mapping(
                item,
                max_bytes=max_bytes,
                max_text_chars=max_text_chars,
                depth=current_depth + 1,
                convert=convert,
            )
            redacted.extend(hidden)
            unavailable.extend(missing)
            return mapping
        if isinstance(item, (list, tuple)):
            limited = list(item)[:_MAX_LOCAL_KEYS]
            converted = [convert(child, current_depth + 1) for child in limited]
            if len(item) > _MAX_LOCAL_KEYS:
                unavailable.append("collection_bound")
            return converted
        unavailable.append(type(item).__name__[:64] or "object")
        return {"unavailable_type": type(item).__name__[:64]}

    converted = convert(value, depth)
    encoded = canonical_dag_json_bytes(converted)
    if len(encoded) > max_bytes:
        unavailable.append("summary_bytes")
        converted = {"bounded": True, "unavailable_type": type(value).__name__[:64]}
    unique_redacted = tuple(sorted(set(redacted)))
    unique_unavailable = tuple(sorted(set(unavailable)))
    return converted, unique_redacted, unique_unavailable


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Cost and isolation bounds for one hermetic Python trace collection."""

    tree_cid: str
    environment_binding_cid: str | None = None
    source_cid: str | None = None
    subject_cid: str | None = None
    admitted_event_kinds: Sequence[str] = DEFAULT_ADMITTED_EVENT_KINDS
    collect_line_events: bool = True
    collect_locals: bool = True
    follow_callees: bool = True
    isolate_network: bool = True
    isolate_subprocess: bool = True
    isolate_database: bool = True
    max_events: int = 4096
    max_line_events: int = 256
    max_frames: int = 32
    max_summary_bytes: int = 4096
    max_text_chars: int = 256
    include_raw_bodies: bool = True
    privacy_class: PrivacyClass | str = PrivacyClass.PRIVATE

    SCHEMA: ClassVar[str] = TRACE_COLLECTION_POLICY_SCHEMA
    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        env = self.environment_binding_cid
        if env is None:
            env = default_python_environment_binding_cid()
        object.__setattr__(
            self, "environment_binding_cid", _cid(env, "environment_binding_cid")
        )
        object.__setattr__(self, "source_cid", _optional_cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self, "subject_cid", _optional_cid(self.subject_cid, "subject_cid")
        )
        kinds = tuple(
            EventKind(kind).value if not isinstance(kind, EventKind) else kind.value
            for kind in self.admitted_event_kinds
        )
        unknown = [kind for kind in kinds if kind not in REQUIRED_EVENT_KINDS]
        if unknown:
            raise PythonExecutionTraceError(
                f"admitted_event_kinds contains unsupported kinds {unknown}"
            )
        if len(kinds) != len(set(kinds)):
            raise PythonExecutionTraceError("admitted_event_kinds must not contain duplicates")
        object.__setattr__(self, "admitted_event_kinds", kinds)
        object.__setattr__(
            self, "collect_line_events", _bool(self.collect_line_events, "collect_line_events")
        )
        object.__setattr__(
            self, "collect_locals", _bool(self.collect_locals, "collect_locals")
        )
        object.__setattr__(
            self, "follow_callees", _bool(self.follow_callees, "follow_callees")
        )
        object.__setattr__(
            self, "isolate_network", _bool(self.isolate_network, "isolate_network")
        )
        object.__setattr__(
            self,
            "isolate_subprocess",
            _bool(self.isolate_subprocess, "isolate_subprocess"),
        )
        object.__setattr__(
            self, "isolate_database", _bool(self.isolate_database, "isolate_database")
        )
        object.__setattr__(self, "max_events", _positive_int(self.max_events, "max_events"))
        object.__setattr__(
            self, "max_line_events", _positive_int(self.max_line_events, "max_line_events")
        )
        object.__setattr__(self, "max_frames", _positive_int(self.max_frames, "max_frames"))
        object.__setattr__(
            self, "max_summary_bytes", _positive_int(self.max_summary_bytes, "max_summary_bytes")
        )
        if self.max_summary_bytes > MAX_METADATA_BYTES:
            raise PythonExecutionTraceError("max_summary_bytes exceeds the contract byte bound")
        object.__setattr__(
            self, "max_text_chars", _positive_int(self.max_text_chars, "max_text_chars")
        )
        object.__setattr__(
            self, "include_raw_bodies", _bool(self.include_raw_bodies, "include_raw_bodies")
        )
        privacy = _privacy(self.privacy_class)
        object.__setattr__(self, "privacy_class", privacy)
        if self.include_raw_bodies and privacy in PUBLIC_PRIVACY_CLASSES:
            raise PythonExecutionTraceError(
                "raw bodies remain private and cannot enter public records"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "tree_cid": self.tree_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "source_cid": self.source_cid,
            "subject_cid": self.subject_cid,
            "admitted_event_kinds": list(self.admitted_event_kinds),
            "collect_line_events": self.collect_line_events,
            "collect_locals": self.collect_locals,
            "follow_callees": self.follow_callees,
            "isolate_network": self.isolate_network,
            "isolate_subprocess": self.isolate_subprocess,
            "isolate_database": self.isolate_database,
            "max_events": self.max_events,
            "max_line_events": self.max_line_events,
            "max_frames": self.max_frames,
            "max_summary_bytes": self.max_summary_bytes,
            "max_text_chars": self.max_text_chars,
            "include_raw_bodies": self.include_raw_bodies,
            "privacy_class": self.privacy_class,
        }

    @property
    def capture_profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def admits(self, kind: str) -> bool:
        return kind in self.admitted_event_kinds


@dataclass(frozen=True, slots=True)
class TraceCancellationSnapshot:
    """Immutable cancellation observation; never an accepted transition."""

    reason: str
    cancelled: bool
    after_events: int | None = None
    accepted_transition: None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "cancelled": self.cancelled,
            "after_events": self.after_events,
            "accepted_transition": None,
        }


class TraceCancellation:
    """Live cancellation token.  Cancellation never admits a transition."""

    INTERFACE: ClassVar[str] = TRACE_CANCELLATION_INTERFACE

    __slots__ = ("reason", "after_events", "_cancelled")

    def __init__(
        self,
        *,
        reason: str = "cancelled",
        after_events: int | None = None,
    ) -> None:
        self.reason = _text(reason, "reason")
        self.after_events = _optional_positive_int(after_events, "after_events")
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def accepted_transition(self) -> None:
        return None

    def cancel(self, reason: str | None = None) -> None:
        if reason is not None:
            self.reason = _text(reason, "reason")
        self._cancelled = True

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise TraceCancelledError(self.reason)

    def snapshot(self) -> TraceCancellationSnapshot:
        return TraceCancellationSnapshot(
            reason=self.reason,
            cancelled=self._cancelled,
            after_events=self.after_events,
            accepted_transition=None,
        )


@dataclass(frozen=True, slots=True)
class TraceRedactor:
    """Strip secrets and raw bodies before a record can be published."""

    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE
    secret_markers: tuple[str, ...] = tuple(sorted(SECRET_FIELD_MARKERS))

    def redact_mapping(
        self,
        value: Mapping[Any, Any],
        *,
        max_bytes: int,
        max_text_chars: int,
        depth: int,
        convert: Callable[[Any, int], Any],
    ) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
        redacted: list[str] = []
        unavailable: list[str] = []
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:_MAX_LOCAL_KEYS]:
            if type(raw_key) is not str:
                unavailable.append("non_string_key")
                continue
            key = unicodedata.normalize("NFC", raw_key)
            if _is_forbidden_key(key):
                redacted.append(key)
                continue
            result[key[:max_text_chars]] = convert(item, depth)
        if len(value) > _MAX_LOCAL_KEYS:
            unavailable.append("collection_bound")
        encoded = canonical_dag_json_bytes(result)
        if len(encoded) > max_bytes:
            unavailable.append("summary_bytes")
            result = {"bounded": True}
        return result, tuple(sorted(set(redacted))), tuple(sorted(set(unavailable)))

    def public_event_payload(self, event: ProgramEvent) -> dict[str, Any]:
        payload = {
            "callee": event.logical_name,
            "event_kind": event.event_kind,
        }
        effect = event.payload.get("effect") if isinstance(event.payload, Mapping) else None
        if type(effect) is str and not _is_forbidden_key(effect):
            payload["effect"] = effect
        return payload

    def public_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        return trace.public_view()

    def public_state(self, state: ProgramExecutionState) -> ProgramExecutionState:
        return public_execution_view(state)


@dataclass(frozen=True, slots=True)
class _RawFrame:
    logical_name: str
    line: int | None
    column: int | None
    code: CodeType
    locals_summary: dict[str, Any]
    redacted_dimensions: tuple[str, ...]
    unavailable_dimensions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RawEvent:
    kind: str
    frame: _RawFrame
    stack: tuple[_RawFrame, ...]
    arg_summary: Any
    exception_type: str | None = None
    handler_kind: str | None = None
    effect: str | None = None
    denied: bool = False
    observation_status: str = ObservationStatus.OBSERVED.value


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceRecord:
    """Private collection plus the public record that never carries raw bodies."""

    events: tuple[ProgramEvent, ...]
    observations: tuple[ExecutionObservation, ...]
    frames: tuple[StackFrameState, ...]
    states: tuple[ProgramExecutionState, ...]
    exceptions: tuple[ExceptionSnapshot, ...]
    handlers: tuple[HandlerState, ...]
    private_trace: ExecutionTrace
    public_record: ExecutionTrace
    policy: TraceCollectionPolicy
    disposition: TraceDisposition | str
    cancellation: TraceCancellationSnapshot | None = None
    accepted_transition: None = None
    result_summary: Mapping[str, Any] = field(default_factory=dict)
    target_exception_type: str | None = None
    replayed: bool = False

    @property
    def capture_profile_cid(self) -> str:
        return self.policy.capture_profile_cid

    @property
    def trace(self) -> ExecutionTrace:
        return self.private_trace

    def to_public_dict(self) -> dict[str, Any]:
        redactor = TraceRedactor()
        public_events = []
        for event in self.events:
            public_events.append(
                {
                    "event_kind": event.event_kind,
                    "logical_name": event.logical_name,
                    "program_event_cid": event.program_event_cid,
                    "code_cid": event.code_cid,
                    "tree_cid": event.tree_cid,
                    "source_cid": event.source_cid,
                    "environment_binding_cid": event.environment_binding_cid,
                    "line": event.line,
                    "column": event.column,
                    "observation_status": event.observation_status,
                    "privacy_class": PrivacyClass.PUBLIC.value,
                    "payload": redactor.public_event_payload(event),
                    "includes_raw_bodies": False,
                }
            )
        cancellation = None if self.cancellation is None else self.cancellation.to_public_dict()
        return {
            "schema": PYTHON_EXECUTION_TRACE_RECORD_SCHEMA,
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, TraceDisposition)
                else str(self.disposition)
            ),
            "accepted_transition": None,
            "trace": self.public_record.to_dict(),
            "events": public_events,
            "cancellation": cancellation,
            "replayed": self.replayed,
            "capture_profile_cid": self.capture_profile_cid,
            "target_exception_type": self.target_exception_type,
            "result_summary": dict(self.result_summary),
            "includes_raw_bodies": False,
            "privacy_class": PrivacyClass.PUBLIC.value,
        }


def _ensure_audit_hook() -> None:
    global _AUDIT_INSTALLED
    if _AUDIT_INSTALLED:
        return
    sys.addaudithook(_dispatch_audit)
    _AUDIT_INSTALLED = True


def _dispatch_audit(event: str, args: tuple[Any, ...]) -> None:
    if not _ACTIVE_TRACERS:
        return
    _ACTIVE_TRACERS[-1]._audit(event, args)


def _skip_filename(filename: str) -> bool:
    if filename == __file__ or filename.startswith("<"):
        return True
    normalized = filename.replace("\\", "/")
    if "/logic/software_contracts/" in normalized or "/logic/ir_core/" in normalized:
        return True
    if "/_pytest/" in normalized or "/pytest/" in normalized:
        return True
    for prefix in (sys.base_prefix, sys.prefix, getattr(sys, "exec_prefix", "")):
        if prefix and filename.startswith(prefix):
            return True
    return False


class PythonExecutionTracer:
    """Collect one hermetic Python execution using ``sys.settrace``."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE

    def __init__(
        self,
        policy: TraceCollectionPolicy,
        *,
        redactor: TraceRedactor | None = None,
        cancellation: TraceCancellation | None = None,
    ) -> None:
        if not isinstance(policy, TraceCollectionPolicy):
            raise PythonExecutionTraceError("policy must be a TraceCollectionPolicy")
        self.policy = policy
        self.redactor = redactor if redactor is not None else TraceRedactor()
        self.cancellation = cancellation
        self._raw: list[_RawEvent] = []
        self._line_events = 0
        self._stopped = False
        self._disposition = TraceDisposition.COMPLETE
        self._target_filename: str | None = None
        self._pending_handler: dict[int, str] = {}
        self._previous_trace: Any = None
        self._code_cids: dict[int, str] = {}
        self._bound_source_cid: str | None = policy.source_cid
        self._subject_cid: str | None = policy.subject_cid
        self._in_handler = False

    def record(
        self,
        target: Callable[..., Any],
        *,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> PythonExecutionTraceRecord:
        return record_python_execution_trace(
            target,
            args=args,
            kwargs=kwargs,
            policy=self.policy,
            cancellation=self.cancellation,
            redactor=self.redactor,
        )

    def _should_trace(self, frame: FrameType) -> bool:
        filename = frame.f_code.co_filename
        if _skip_filename(filename):
            return False
        if not self.policy.follow_callees and self._target_filename is not None:
            return filename == self._target_filename
        return True

    def _stop(self, disposition: TraceDisposition) -> None:
        self._stopped = True
        self._disposition = disposition
        sys.settrace(self._previous_trace)

    def _audit(self, event: str, _args: tuple[Any, ...]) -> None:
        if self._stopped:
            return
        denied = None
        if self.policy.isolate_network and event in _NETWORK_AUDIT_EVENTS:
            denied = "network"
        elif self.policy.isolate_subprocess and event in _SUBPROCESS_AUDIT_EVENTS:
            denied = "subprocess"
        elif self.policy.isolate_database and event in _DATABASE_AUDIT_EVENTS:
            denied = "database"
        elif event in _INSTALLER_AUDIT_EVENTS:
            denied = "installer"
        if denied is None:
            return
        frame = sys._getframe(1)
        while frame is not None and _skip_filename(frame.f_code.co_filename):
            frame = frame.f_back
        if frame is not None:
            self._collect(
                EventKind.EXTERNAL.value,
                frame,
                arg_summary={"effect": event, "denied": True, "class": denied},
                effect=event,
                denied=True,
                observation_status=ObservationStatus.UNAVAILABLE.value,
            )
        raise PythonExecutionTraceError(f"test isolation denied {denied} event {event}")

    def _snapshot_frame(self, frame: FrameType) -> _RawFrame:
        logical = _logical_name_for_code(frame.f_code, frame.f_globals)
        locals_summary: dict[str, Any] = {}
        redacted: tuple[str, ...] = ()
        unavailable: tuple[str, ...] = _ALWAYS_UNAVAILABLE
        if self.policy.collect_locals and self.policy.include_raw_bodies:
            try:
                raw_locals = frame.f_locals
            except Exception:
                raw_locals = {}
                unavailable = tuple(sorted(set(unavailable) | {"locals"}))
            visible_keys = [
                key
                for key in raw_locals
                if type(key) is str and not key.startswith("__")
            ][:_MAX_LOCAL_KEYS]
            converted, hidden, missing = bounded_state_summary(
                {key: raw_locals[key] for key in visible_keys},
                max_bytes=self.policy.max_summary_bytes,
                max_text_chars=self.policy.max_text_chars,
                redactor=self.redactor,
            )
            if isinstance(converted, dict):
                locals_summary = converted
            redacted = hidden
            unavailable = tuple(sorted(set(unavailable) | set(missing)))
        elif not self.policy.collect_locals:
            unavailable = tuple(sorted(set(unavailable) | {"locals"}))
        return _RawFrame(
            logical_name=logical,
            line=frame.f_lineno if type(frame.f_lineno) is int and frame.f_lineno >= 0 else None,
            column=_column_for_frame(frame),
            code=frame.f_code,
            locals_summary=locals_summary,
            redacted_dimensions=redacted,
            unavailable_dimensions=unavailable,
        )

    def _stack(self, frame: FrameType) -> tuple[_RawFrame, ...]:
        frames: list[_RawFrame] = []
        current: FrameType | None = frame
        depth = 0
        while current is not None and depth < self.policy.max_frames:
            if not self._should_trace(current):
                break
            frames.append(self._snapshot_frame(current))
            current = current.f_back
            depth += 1
        return tuple(frames)

    def _collect(
        self,
        kind: str,
        frame: FrameType,
        *,
        arg_summary: Any = None,
        exception_type: str | None = None,
        handler_kind: str | None = None,
        effect: str | None = None,
        denied: bool = False,
        observation_status: str = ObservationStatus.OBSERVED.value,
    ) -> None:
        if self._stopped or not self.policy.admits(kind):
            return
        if kind == EventKind.LINE.value:
            if not self.policy.collect_line_events:
                return
            if self._line_events >= self.policy.max_line_events:
                return
            self._line_events += 1
        raw_frame = self._snapshot_frame(frame)
        event = _RawEvent(
            kind=kind,
            frame=raw_frame,
            stack=self._stack(frame),
            arg_summary=arg_summary,
            exception_type=exception_type,
            handler_kind=handler_kind,
            effect=effect,
            denied=denied,
            observation_status=observation_status,
        )
        self._raw.append(event)
        token = self.cancellation
        if token is not None and token.after_events is not None:
            if len(self._raw) >= token.after_events:
                token.cancel()
        if token is not None and token.is_cancelled:
            self._stop(TraceDisposition.CANCELLED)
            return
        if len(self._raw) >= self.policy.max_events:
            self._stop(TraceDisposition.BOUNDED)

    def _classify_return(self, frame: FrameType) -> str:
        flags = frame.f_code.co_flags
        opcode = _opcode_name(frame) or ""
        returning = opcode in {"RETURN_VALUE", "RETURN_CONST", "RETURN_GENERATOR"}
        yielded = opcode in {"YIELD_VALUE", "YIELD_FROM", "SEND", "GET_AWAITABLE"}
        if flags & inspect.CO_COROUTINE:
            if yielded or not returning:
                return EventKind.AWAIT.value
            return EventKind.RETURN.value
        if flags & (inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR):
            if yielded or not returning:
                return EventKind.YIELD.value
            return EventKind.RETURN.value
        return EventKind.RETURN.value

    def _handle(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if self._stopped:
            return None
        if self._in_handler:
            return None
        if not self._should_trace(frame):
            return None
        self._in_handler = True
        try:
            return self._handle_event(frame, event, arg)
        finally:
            self._in_handler = False

    def _handle_event(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if event == "call":
            self._collect(EventKind.CALL.value, frame)
            return self._handle
        if event == "return":
            kind = self._classify_return(frame)
            summary, _, _ = bounded_state_summary(
                arg,
                max_bytes=self.policy.max_summary_bytes,
                max_text_chars=self.policy.max_text_chars,
                redactor=self.redactor,
            )
            self._collect(kind, frame, arg_summary=summary)
            self._pending_handler.pop(id(frame), None)
            return self._handle
        if event == "exception":
            exc_type = None
            if isinstance(arg, tuple) and arg:
                maybe_type = arg[0]
                if isinstance(maybe_type, type):
                    exc_type = maybe_type.__name__
                elif maybe_type is not None:
                    exc_type = type(maybe_type).__name__
            self._collect(
                EventKind.RAISE.value,
                frame,
                exception_type=exc_type or "Exception",
            )
            self._pending_handler[id(frame)] = HandlerKind.EXCEPT.value
            return self._handle
        if event == "line":
            handler = self._pending_handler.pop(id(frame), None)
            if handler is not None:
                self._collect(
                    EventKind.CATCH.value,
                    frame,
                    handler_kind=handler,
                )
                if self.policy.admits(EventKind.HANDLER.value):
                    self._collect(
                        EventKind.HANDLER.value,
                        frame,
                        handler_kind=handler,
                    )
            self._collect(EventKind.LINE.value, frame)
            return self._handle
        return self._handle

    def _code_identity(self, raw_frame: _RawFrame) -> str:
        cached = self._code_cids.get(id(raw_frame.code))
        if cached is not None:
            return cached
        cid = _code_cid(raw_frame.logical_name, raw_frame.code)
        self._code_cids[id(raw_frame.code)] = cid
        return cid

    def _materialize(
        self,
        *,
        result_summary: Mapping[str, Any],
        target_exception_type: str | None,
    ) -> PythonExecutionTraceRecord:
        policy = self.policy
        source_cid = self._bound_source_cid
        if source_cid is None:
            raise PythonExecutionTraceError("source_cid must be bound before materialization")
        subject_cid = self._subject_cid or source_cid
        tree_cid = policy.tree_cid
        env_cid = policy.environment_binding_cid
        assert env_cid is not None
        capture_cid = policy.capture_profile_cid
        frame_records: dict[tuple[str, int | None, int | None, int], StackFrameState] = {}
        exception_records: list[ExceptionSnapshot] = []
        handler_records: list[HandlerState] = []
        events: list[ProgramEvent] = []
        states: list[ProgramExecutionState] = []
        predecessor: str | None = None
        all_redacted: set[str] = set()
        all_unavailable: set[str] = set(_ALWAYS_UNAVAILABLE)
        if self._disposition is TraceDisposition.CANCELLED:
            all_unavailable.add("remaining_events")
        elif self._disposition is TraceDisposition.BOUNDED:
            all_unavailable.add("remaining_events")

        def frame_state(raw: _RawFrame, ordinal: int) -> StackFrameState:
            key = (raw.logical_name, raw.line, raw.column, ordinal)
            existing = frame_records.get(key)
            if existing is not None:
                return existing
            redacted = raw.redacted_dimensions
            unavailable = tuple(sorted(set(raw.unavailable_dimensions) | set(_ALWAYS_UNAVAILABLE)))
            if raw.line is None:
                unavailable = tuple(sorted(set(unavailable) | {"source_location"}))
            claim = CompletenessClaim.PARTIAL
            if redacted:
                all_redacted.update(redacted)
            all_unavailable.update(unavailable)
            state = StackFrameState(
                ordinal=ordinal,
                language="python",
                tree_cid=tree_cid,
                source_cid=source_cid,
                code_cid=self._code_identity(raw),
                environment_binding_cid=env_cid,
                logical_name=raw.logical_name,
                line=raw.line,
                column=raw.column,
                state_summary={"locals": raw.locals_summary} if policy.include_raw_bodies else {},
                exception_snapshot_cid=None,
                handler_state_cid=None,
                exception_active=False,
                handler_active=False,
                redacted_dimensions=redacted,
                unavailable_dimensions=unavailable,
                completeness_claim=claim,
                privacy_class=policy.privacy_class,
            )
            frame_records[key] = state
            return state

        if not self._raw:
            unavailable_event = ProgramEvent(
                event_kind=EventKind.UNAVAILABLE.value,
                event_origin=EventOrigin.OBSERVED.value,
                observation_status=ObservationStatus.UNAVAILABLE.value,
                language="python",
                tree_cid=tree_cid,
                source_cid=source_cid,
                code_cid=subject_cid,
                environment_binding_cid=env_cid,
                subject_cid=subject_cid,
                logical_name="unavailable",
                payload={"reason": "no_events"},
                line=None,
                column=None,
                predecessor_event_cid=None,
                stack_frame_cids=(),
                exception_snapshot_cid=None,
                handler_state_cid=None,
                redaction_profile_cid=None,
                redacted_dimensions=(),
                unavailable_dimensions=("event_body", "call_stack"),
                completeness_claim=CompletenessClaim.UNAVAILABLE,
                privacy_class=policy.privacy_class,
            )
            events.append(unavailable_event)
            all_unavailable.update({"event_body", "call_stack"})

        for raw in self._raw:
            stack_states = tuple(
                frame_state(item, ordinal) for ordinal, item in enumerate(raw.stack)
            )
            exception = None
            handler = None
            if raw.kind == EventKind.RAISE.value:
                exception = ExceptionSnapshot(
                    language="python",
                    exception_type=raw.exception_type or "Exception",
                    tree_cid=tree_cid,
                    source_cid=source_cid,
                    code_cid=self._code_identity(raw.frame),
                    environment_binding_cid=env_cid,
                    exception_value_summary={
                        "type": raw.exception_type or "Exception",
                        "bounded": True,
                    },
                    traceback_stack_frame_cids=tuple(
                        item.stack_frame_state_cid for item in stack_states
                    ),
                    raised_at_event_cid=None,
                    handler_state_cid=None,
                    future_execution=False,
                    unavailable_dimensions=_ALWAYS_UNAVAILABLE,
                    completeness_claim=CompletenessClaim.PARTIAL,
                )
                exception_records.append(exception)
            if raw.kind in {EventKind.CATCH.value, EventKind.HANDLER.value}:
                matching = exception_records[-1].exception_snapshot_cid if exception_records else None
                handler = HandlerState(
                    language="python",
                    handler_kind=raw.handler_kind or HandlerKind.EXCEPT.value,
                    tree_cid=tree_cid,
                    source_cid=source_cid,
                    code_cid=self._code_identity(raw.frame),
                    environment_binding_cid=env_cid,
                    logical_name=raw.frame.logical_name,
                    stack_ordinal=0,
                    handler_active=True,
                    matching_exception_snapshot_cid=matching,
                    unavailable_dimensions=() if matching is not None else ("exception",),
                )
                handler_records.append(handler)
            payload: dict[str, Any] = {}
            if policy.include_raw_bodies and raw.frame.locals_summary:
                payload["locals"] = raw.frame.locals_summary
            if raw.arg_summary is not None:
                payload["value"] = raw.arg_summary
            if raw.effect is not None:
                payload["effect"] = raw.effect
            if raw.denied:
                payload["denied"] = True
            if raw.kind == EventKind.CALL.value:
                payload["callee"] = raw.frame.logical_name
            redacted = tuple(sorted(set(raw.frame.redacted_dimensions) | all_redacted))
            unavailable = tuple(sorted(set(raw.frame.unavailable_dimensions) | set(_ALWAYS_UNAVAILABLE)))
            if raw.denied:
                unavailable = tuple(sorted(set(unavailable) | {"external_effect"}))
            observation_status = raw.observation_status
            completeness = CompletenessClaim.PARTIAL
            if redacted:
                completeness = CompletenessClaim.PARTIAL
            if observation_status == ObservationStatus.UNAVAILABLE.value:
                completeness = CompletenessClaim.PARTIAL
            privacy = policy.privacy_class
            event = ProgramEvent(
                event_kind=raw.kind,
                event_origin=EventOrigin.OBSERVED.value,
                observation_status=observation_status,
                language="python",
                tree_cid=tree_cid,
                source_cid=source_cid,
                code_cid=self._code_identity(raw.frame),
                environment_binding_cid=env_cid,
                subject_cid=subject_cid,
                logical_name=raw.frame.logical_name,
                payload=payload,
                line=raw.frame.line,
                column=raw.frame.column,
                predecessor_event_cid=predecessor,
                stack_frame_cids=tuple(item.stack_frame_state_cid for item in stack_states),
                exception_snapshot_cid=None if exception is None else exception.exception_snapshot_cid,
                handler_state_cid=None if handler is None else handler.handler_state_cid,
                redaction_profile_cid=None,
                redacted_dimensions=redacted,
                unavailable_dimensions=unavailable,
                completeness_claim=completeness,
                privacy_class=privacy,
            )
            events.append(event)
            predecessor = event.program_event_cid
            if raw.kind in {
                EventKind.CALL.value,
                EventKind.RETURN.value,
                EventKind.RAISE.value,
                EventKind.CATCH.value,
                EventKind.YIELD.value,
                EventKind.AWAIT.value,
                EventKind.EXTERNAL.value,
            }:
                observed = {"locals": raw.frame.locals_summary} if policy.include_raw_bodies else {}
                state = assemble_program_execution_state(
                    capture_profile_cid=capture_cid,
                    tree_cid=tree_cid,
                    source_cid=source_cid,
                    environment_binding_cid=env_cid,
                    frames=stack_states,
                    observed_state=observed,
                    heap_summary={},
                    heap_bound=HeapBound.UNAVAILABLE,
                    exception=exception,
                    handler=handler,
                    observation_status=observation_status,
                    completeness_claim=CompletenessClaim.PARTIAL,
                    privacy_class=privacy,
                    includes_raw_bodies=policy.include_raw_bodies,
                    unavailable_dimensions=tuple(sorted(set(unavailable) | set(_ALWAYS_UNAVAILABLE))),
                    code_cid=self._code_identity(raw.frame),
                )
                states.append(state)

        observations: list[ExecutionObservation] = []
        for event in events:
            if event.observation_admissible:
                try:
                    observations.append(observe_program_event(event))
                except ProgramExecutionError:
                    continue

        unavailable_dimensions = tuple(sorted(all_unavailable))
        redacted_dimensions = tuple(sorted(all_redacted))
        private_trace = assemble_execution_trace(
            tree_cid=tree_cid,
            source_cid=source_cid,
            environment_binding_cid=env_cid,
            events=events,
            states=states,
            completeness_claim=CompletenessClaim.PARTIAL,
            privacy_class=policy.privacy_class,
            includes_raw_bodies=policy.include_raw_bodies,
            unavailable_dimensions=unavailable_dimensions,
        )
        if redacted_dimensions:
            private_trace = ExecutionTrace(
                language=private_trace.language,
                tree_cid=private_trace.tree_cid,
                source_cid=private_trace.source_cid,
                environment_binding_cid=private_trace.environment_binding_cid,
                event_cids=private_trace.event_cids,
                segment_cids=private_trace.segment_cids,
                raw_execution_state_cids=private_trace.raw_execution_state_cids,
                parent_trace_cid=private_trace.parent_trace_cid,
                redaction_profile_cid=private_trace.redaction_profile_cid,
                redacted_dimensions=redacted_dimensions,
                unavailable_dimensions=private_trace.unavailable_dimensions,
                completeness_claim=CompletenessClaim.PARTIAL,
                privacy_class=private_trace.privacy_class,
                includes_raw_bodies=private_trace.includes_raw_bodies,
            )
        public_record = self.redactor.public_trace(private_trace)
        cancellation_snapshot = None
        if self.cancellation is not None and (
            self.cancellation.is_cancelled or self._disposition is TraceDisposition.CANCELLED
        ):
            cancellation_snapshot = self.cancellation.snapshot()
        return PythonExecutionTraceRecord(
            events=tuple(events),
            observations=tuple(observations),
            frames=tuple(frame_records.values()),
            states=tuple(states),
            exceptions=tuple(exception_records),
            handlers=tuple(handler_records),
            private_trace=private_trace,
            public_record=public_record,
            policy=policy,
            disposition=self._disposition,
            cancellation=cancellation_snapshot,
            accepted_transition=None,
            result_summary=dict(result_summary),
            target_exception_type=target_exception_type,
            replayed=False,
        )


def record_python_execution_trace(
    target: Callable[..., Any],
    *,
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    policy: TraceCollectionPolicy,
    cancellation: TraceCancellation | None = None,
    redactor: TraceRedactor | None = None,
) -> PythonExecutionTraceRecord:
    """Collect one hermetic Python execution.  Never admits a transition."""

    if not callable(target):
        raise PythonExecutionTraceError("target must be callable")
    if inspect.isbuiltin(target):
        raise PythonExecutionTraceError("builtin callables are typed unavailable")
    if not isinstance(policy, TraceCollectionPolicy):
        raise PythonExecutionTraceError("policy must be a TraceCollectionPolicy")
    tracer = PythonExecutionTracer(
        policy,
        redactor=redactor,
        cancellation=cancellation,
    )
    code = getattr(target, "__code__", None)
    if isinstance(code, CodeType):
        tracer._target_filename = code.co_filename
        if tracer._bound_source_cid is None:
            tracer._bound_source_cid = _source_cid_for_callable(target)
        if tracer._subject_cid is None:
            logical = _logical_name_for_code(code, getattr(target, "__globals__", None))
            tracer._subject_cid = _code_cid(logical, code)
    elif tracer._bound_source_cid is None:
        tracer._bound_source_cid = _source_cid_for_callable(target)
    call_kwargs = {} if kwargs is None else dict(kwargs)
    result_summary: dict[str, Any] = {}
    target_exception_type: str | None = None
    _ensure_audit_hook()
    tracer._previous_trace = sys.gettrace()
    _ACTIVE_TRACERS.append(tracer)
    try:
        sys.settrace(tracer._handle)
        try:
            returned = target(*tuple(args), **call_kwargs)
        except TraceCancelledError:
            tracer._disposition = TraceDisposition.CANCELLED
            returned = None
            target_exception_type = "TraceCancelledError"
        except PythonExecutionTraceError as exc:
            if tracer._disposition is TraceDisposition.COMPLETE:
                tracer._disposition = TraceDisposition.COMPLETE
            returned = None
            target_exception_type = type(exc).__name__
            converted, _, _ = bounded_state_summary(
                {"error": type(exc).__name__},
                max_bytes=policy.max_summary_bytes,
                max_text_chars=policy.max_text_chars,
                redactor=tracer.redactor,
            )
            if isinstance(converted, dict):
                result_summary = converted
        except Exception as exc:
            target_exception_type = type(exc).__name__
            returned = None
            converted, _, _ = bounded_state_summary(
                {"error": type(exc).__name__},
                max_bytes=policy.max_summary_bytes,
                max_text_chars=policy.max_text_chars,
                redactor=tracer.redactor,
            )
            if isinstance(converted, dict):
                result_summary = converted
        else:
            converted, _, _ = bounded_state_summary(
                returned,
                max_bytes=policy.max_summary_bytes,
                max_text_chars=policy.max_text_chars,
                redactor=tracer.redactor,
            )
            result_summary = {"value": converted}
    finally:
        sys.settrace(tracer._previous_trace)
        if _ACTIVE_TRACERS and _ACTIVE_TRACERS[-1] is tracer:
            _ACTIVE_TRACERS.pop()
        elif tracer in _ACTIVE_TRACERS:
            _ACTIVE_TRACERS.remove(tracer)
    try:
        return tracer._materialize(
            result_summary=result_summary,
            target_exception_type=target_exception_type,
        )
    except ProgramExecutionError as exc:
        raise PythonExecutionTraceError(str(exc)) from exc


def replay_deterministic_trace(
    record: PythonExecutionTraceRecord,
) -> PythonExecutionTraceRecord:
    """Replay a promised trace by recomputing identities without re-execution.

    External and nondeterministic effects remain the recorded observations or
    typed unavailable dimensions.  Replay never emits an accepted transition.
    """

    if not isinstance(record, PythonExecutionTraceRecord):
        raise PythonExecutionTraceError("replay requires a promised PythonExecutionTraceRecord")
    if not record.events:
        raise PythonExecutionTraceError("promised trace has no events")
    rebuilt = assemble_execution_trace(
        language=record.private_trace.language,
        tree_cid=record.private_trace.tree_cid,
        source_cid=record.private_trace.source_cid,
        environment_binding_cid=record.private_trace.environment_binding_cid,
        events=record.events,
        states=record.states,
        completeness_claim=record.private_trace.completeness_claim,
        privacy_class=record.private_trace.privacy_class,
        includes_raw_bodies=record.private_trace.includes_raw_bodies,
        unavailable_dimensions=record.private_trace.unavailable_dimensions,
    )
    if record.private_trace.redacted_dimensions:
        rebuilt = ExecutionTrace(
            language=rebuilt.language,
            tree_cid=rebuilt.tree_cid,
            source_cid=rebuilt.source_cid,
            environment_binding_cid=rebuilt.environment_binding_cid,
            event_cids=rebuilt.event_cids,
            segment_cids=rebuilt.segment_cids,
            raw_execution_state_cids=rebuilt.raw_execution_state_cids,
            parent_trace_cid=rebuilt.parent_trace_cid,
            redaction_profile_cid=rebuilt.redaction_profile_cid,
            redacted_dimensions=record.private_trace.redacted_dimensions,
            unavailable_dimensions=rebuilt.unavailable_dimensions,
            completeness_claim=rebuilt.completeness_claim,
            privacy_class=rebuilt.privacy_class,
            includes_raw_bodies=rebuilt.includes_raw_bodies,
        )
    if rebuilt.execution_trace_cid != record.private_trace.execution_trace_cid:
        raise PythonExecutionTraceError("promised replay diverged from recorded identity")
    public_record = rebuilt.public_view()
    if public_record.includes_raw_bodies:
        raise PythonExecutionTraceError("raw bodies remain private and cannot enter public records")
    cancellation = record.cancellation
    if cancellation is not None and cancellation.accepted_transition is not None:
        raise PythonExecutionTraceError("cancellation emits no accepted transition")
    return PythonExecutionTraceRecord(
        events=record.events,
        observations=record.observations,
        frames=record.frames,
        states=record.states,
        exceptions=record.exceptions,
        handlers=record.handlers,
        private_trace=rebuilt,
        public_record=public_record,
        policy=record.policy,
        disposition=record.disposition,
        cancellation=cancellation,
        accepted_transition=None,
        result_summary=dict(record.result_summary),
        target_exception_type=record.target_exception_type,
        replayed=True,
    )


__all__ = [
    "DEFAULT_ADMITTED_EVENT_KINDS",
    "HERMETIC_TRACE_EVIDENCE",
    "PYTHON_EXECUTION_TRACE_RECORD_SCHEMA",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "PythonExecutionTraceError",
    "PythonExecutionTraceRecord",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCancellationSnapshot",
    "TraceCancelledError",
    "TraceCollectionPolicy",
    "TraceDisposition",
    "TraceRedactor",
    "bounded_state_summary",
    "default_python_environment_binding_cid",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
