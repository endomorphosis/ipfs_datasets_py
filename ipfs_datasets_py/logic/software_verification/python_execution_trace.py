"""Hermetic admitted-Python execution tracing (SAWM-008).

This module is the datasets construction authority for hermetic Python
trace collection.  It binds every admitted event to the SAWM-007
``ProgramEvent@1`` / ``ExecutionTrace@1`` family with exact tree, source,
code, symbol, callsite, and environment identities.

Normative constraints:

* Importing this module never opens a network, socket, installer,
  subprocess, database, repository scan, watcher, or model load, and
  never installs ``sys.settrace`` / ``sys.setprofile``.
* Collection is explicit via :func:`record_python_execution_trace`.
* Cancellation never emits an accepted transition.
* Private raw trace bodies never enter public records.
* Line / basic-block detail is policy-bounded.  Nondeterministic
  external effects are explicit observations or typed unavailable.
* This adapter does not persist operational acceptance, introduce
  shell tracing, or bypass execution isolation.
"""

from __future__ import annotations

import ast
import dis
import inspect
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import FrameType, MappingProxyType, MethodType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes,
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    FORBIDDEN_FIELD_MARKERS,
    MAX_METADATA_BYTES,
    MAX_SAFE_INTEGER,
    MAX_TEXT_CHARS,
    SECRET_FIELD_MARKERS,
    CompletenessClaim,
    EventKind,
    EventOrigin,
    ExceptionSnapshot,
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
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PYTHON_EXECUTION_TRACER_INTERFACE: Final[str] = "PythonExecutionTracer@1"
TRACE_COLLECTION_POLICY_INTERFACE: Final[str] = "TraceCollectionPolicy@1"
TRACE_REDACTOR_INTERFACE: Final[str] = "TraceRedactor@1"
TRACE_CANCELLATION_INTERFACE: Final[str] = "TraceCancellation@1"
PYTHON_EXECUTION_TRACE_RECORD_INTERFACE: Final[str] = "PythonExecutionTraceRecord@1"
PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE: Final[str] = "PythonExecutionReplayReceipt@1"

PYTHON_EXECUTION_TRACER_VERSION: Final[str] = "1"
TRACE_COLLECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-policy@1"
)
TRACE_CAPTURE_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-capture-profile@1"
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
TRACE_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-trace-record@1"
)
TRACE_REPLAY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-replay-receipt@1"
)

# Importing this module must remain inert.
IMPORT_SIDE_EFFECTS_PERFORMED: Final[bool] = False
IMPORT_SCAN_PERFORMED: Final[bool] = False
IMPORT_NETWORK_OPENED: Final[bool] = False
IMPORT_SOCKET_OPENED: Final[bool] = False
IMPORT_INSTALLER_INVOKED: Final[bool] = False
IMPORT_SUBPROCESS_SPAWNED: Final[bool] = False
IMPORT_DATABASE_OPENED: Final[bool] = False
IMPORT_WATCHER_STARTED: Final[bool] = False
IMPORT_MODEL_LOADED: Final[bool] = False
IMPORT_TRACE_HOOK_INSTALLED: Final[bool] = False

ADMITTED_LANGUAGE: Final[str] = ProgramLanguage.PYTHON.value
DEFAULT_MAX_EVENTS: Final[int] = 10_000
DEFAULT_MAX_STACK_FRAMES: Final[int] = 64
DEFAULT_MAX_LINE_EVENTS: Final[int] = 256
DEFAULT_MAX_SUMMARY_CHARS: Final[int] = 256
DEFAULT_MAX_SUMMARY_DEPTH: Final[int] = 2
DEFAULT_MAX_LOCALS: Final[int] = 32
ACCEPTED_TRANSITION_DISPOSITION: Final[str] = "accepted"
SELECTED_EXTERNAL_TARGETS: Final[tuple[str, ...]] = (
    "socket.socket.connect",
    "socket.socket.connect_ex",
    "socket.create_connection",
    "socket.getaddrinfo",
    "subprocess.Popen",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "os.system",
    "sqlite3.connect",
    "duckdb.connect",
    "urllib.request.urlopen",
    "http.client.HTTPConnection.connect",
)
_TRACER_FILENAME: Final[str] = __file__


# ---------------------------------------------------------------------------
# Errors / status
# ---------------------------------------------------------------------------


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic trace collection or replay fails closed."""


class PythonExecutionCancelled(BaseException):
    """Injected to halt a cancelled subject; never an accepted transition."""


class PythonExecutionNetworkDenied(PythonExecutionTraceError):
    """Test-only network isolation denied a selected external effect."""


class TraceStatus(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BOUNDED = "bounded"


class TransitionDisposition(StrEnum):
    OBSERVED = "observed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _nfc(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise PythonExecutionTraceError(f"{label} must be a nonempty string")
    normalized = unicodedata.normalize("NFC", value)
    if normalized != value or value.strip() != value or "\x00" in value:
        raise PythonExecutionTraceError(f"{label} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS:
        raise PythonExecutionTraceError(f"{label} exceeds its character bound")
    return value


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise PythonExecutionTraceError(f"{label} must be a boolean")
    return value


def _positive_int(value: object, label: str, *, upper: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value <= 0:
        raise PythonExecutionTraceError(f"{label} must be a positive integer")
    if value > upper:
        raise PythonExecutionTraceError(f"{label} exceeds its bound")
    return value


def _mapping(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise PythonExecutionTraceError(f"{label} must be a string mapping")
    result: dict[str, str] = {}
    for key, item in value.items():
        result[_nfc(str(key), f"{label} key")] = _nfc(str(item), f"{label} value")
    return result


def _secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in SECRET_FIELD_MARKERS or lowered in FORBIDDEN_FIELD_MARKERS:
        return True
    for marker in SECRET_FIELD_MARKERS:
        if (
            lowered == marker
            or lowered.startswith(marker + "_")
            or lowered.endswith("_" + marker)
        ):
            return True
    return False


def _forbidden_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return lowered in FORBIDDEN_FIELD_MARKERS or _secret_key(key)


def _environment_cid(bindings: Mapping[str, str]) -> str:
    items = [
        {"key": key, "value": value}
        for key, value in sorted(bindings.items(), key=lambda pair: pair[0])
    ]
    return cid_for_structured(
        {"schema": TRACE_ENVIRONMENT_SCHEMA, "language": ADMITTED_LANGUAGE, "bindings": items}
    )


def _default_environment() -> dict[str, str]:
    info = sys.version_info
    return {
        "language": ADMITTED_LANGUAGE,
        "python_implementation": sys.implementation.name,
        "python_version": f"{info.major}.{info.minor}.{info.micro}",
    }


def _code_cid(*, logical_name: str, source_cid: str, firstlineno: int, co_name: str) -> str:
    return cid_for_structured(
        {
            "schema": TRACE_CODE_SCHEMA,
            "logical_name": logical_name,
            "source_cid": source_cid,
            "firstlineno": firstlineno,
            "co_name": co_name,
        }
    )


def _tree_cid(source_cid: str, logical_name: str) -> str:
    return cid_for_structured(
        {
            "schema": TRACE_TREE_SCHEMA,
            "source_cid": source_cid,
            "logical_name": logical_name,
            "language": ADMITTED_LANGUAGE,
        }
    )


def _subject_source(subject: Callable[..., Any]) -> tuple[str, str, bool, int]:
    try:
        lines, start = inspect.getsourcelines(subject)
        text = "".join(lines)
        if text.strip():
            payload = unicodedata.normalize("NFC", text).encode("utf-8")
            return text, cid_for_bytes(payload), False, int(start)
    except (OSError, TypeError, SyntaxError):
        pass
    code = getattr(subject, "__code__", None)
    logical = _callable_logical_name(subject)
    stand_in = cid_for_structured(
        {
            "schema": TRACE_CODE_SCHEMA + "#unavailable-source",
            "logical_name": logical,
            "co_name": getattr(code, "co_name", logical),
            "firstlineno": int(getattr(code, "co_firstlineno", 0) or 0),
        }
    )
    return "", stand_in, True, int(getattr(code, "co_firstlineno", 1) or 1)


def _callable_logical_name(subject: Callable[..., Any]) -> str:
    module = getattr(subject, "__module__", "") or ""
    qual = getattr(subject, "__qualname__", None) or getattr(subject, "__name__", "subject")
    name = f"{module}.{qual}" if module else str(qual)
    return _nfc(name[:MAX_TEXT_CHARS], "logical_name")


def _frame_logical_name(frame: FrameType) -> str:
    module = frame.f_globals.get("__name__", "") or ""
    code = frame.f_code
    qual = getattr(code, "co_qualname", None) or code.co_name
    name = f"{module}.{qual}" if module else str(qual)
    return name[:MAX_TEXT_CHARS]


def _summarize_value(
    value: Any,
    *,
    max_chars: int,
    depth: int,
    max_depth: int,
) -> Any:
    if depth > max_depth:
        return {"kind": "truncated", "reason": "depth_bound"}
    if value is None:
        return None
    value_type = type(value)
    if value_type is bool:
        return value
    if value_type is int:
        if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
            return {"kind": "int", "unavailable": "integer_bound"}
        return value
    if value_type is str:
        if len(value) > max_chars:
            return {"kind": "str", "length": len(value), "truncated": True}
        return value
    if value_type is float:
        return {"kind": "float", "unavailable": "float_rejected"}
    if value_type in {list, tuple}:
        preview = [
            _summarize_value(
                item, max_chars=max_chars, depth=depth + 1, max_depth=max_depth
            )
            for item in list(value)[:8]
        ]
        return {"kind": value_type.__name__, "length": len(value), "items": preview}
    if value_type is dict:
        items = []
        for key in sorted(str(item) for item in list(value)[:8]):
            if _forbidden_key(key):
                continue
            items.append(
                {
                    "key": key[:max_chars],
                    "value": _summarize_value(
                        value.get(key) if key in value else None,
                        max_chars=max_chars,
                        depth=depth + 1,
                        max_depth=max_depth,
                    ),
                }
            )
        return {"kind": "dict", "length": len(value), "items": items}
    type_name = getattr(value_type, "__name__", "object")
    return {"kind": "object", "type": str(type_name)[:64]}


def _bounded_payload(payload: Mapping[str, Any], *, max_bytes: int) -> dict[str, Any]:
    prepared = dict(payload)
    try:
        encoded = canonical_dag_json_bytes(prepared)
    except (TypeError, ValueError):
        return {"bounded": True, "reason": "payload_rejected"}
    if len(encoded) > max_bytes:
        return {"bounded": True, "reason": "payload_byte_bound", "byte_length": len(encoded)}
    return prepared


# ---------------------------------------------------------------------------
# Policy / redaction / cancellation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Bounded collection policy; line detail and externals are cost-capped."""

    collect_calls: bool = True
    collect_returns: bool = True
    collect_lines: bool = True
    collect_exceptions: bool = True
    collect_handlers: bool = True
    collect_yields: bool = True
    collect_awaits: bool = True
    collect_external: bool = True
    capture_locals: bool = True
    network_isolation: bool = True
    halt_on_cancel: bool = True
    include_raw_bodies_in_private: bool = True
    max_events: int = DEFAULT_MAX_EVENTS
    max_stack_frames: int = DEFAULT_MAX_STACK_FRAMES
    max_line_events: int = DEFAULT_MAX_LINE_EVENTS
    max_payload_bytes: int = MAX_METADATA_BYTES
    max_summary_chars: int = DEFAULT_MAX_SUMMARY_CHARS
    max_summary_depth: int = DEFAULT_MAX_SUMMARY_DEPTH

    SCHEMA: ClassVar[str] = TRACE_COLLECTION_POLICY_SCHEMA
    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "collect_calls", _bool(self.collect_calls, "collect_calls"))
        object.__setattr__(
            self, "collect_returns", _bool(self.collect_returns, "collect_returns")
        )
        object.__setattr__(self, "collect_lines", _bool(self.collect_lines, "collect_lines"))
        object.__setattr__(
            self,
            "collect_exceptions",
            _bool(self.collect_exceptions, "collect_exceptions"),
        )
        object.__setattr__(
            self, "collect_handlers", _bool(self.collect_handlers, "collect_handlers")
        )
        object.__setattr__(
            self, "collect_yields", _bool(self.collect_yields, "collect_yields")
        )
        object.__setattr__(
            self, "collect_awaits", _bool(self.collect_awaits, "collect_awaits")
        )
        object.__setattr__(
            self, "collect_external", _bool(self.collect_external, "collect_external")
        )
        object.__setattr__(
            self, "capture_locals", _bool(self.capture_locals, "capture_locals")
        )
        object.__setattr__(
            self,
            "network_isolation",
            _bool(self.network_isolation, "network_isolation"),
        )
        object.__setattr__(
            self, "halt_on_cancel", _bool(self.halt_on_cancel, "halt_on_cancel")
        )
        object.__setattr__(
            self,
            "include_raw_bodies_in_private",
            _bool(self.include_raw_bodies_in_private, "include_raw_bodies_in_private"),
        )
        object.__setattr__(
            self,
            "max_events",
            _positive_int(self.max_events, "max_events", upper=DEFAULT_MAX_EVENTS),
        )
        object.__setattr__(
            self,
            "max_stack_frames",
            _positive_int(
                self.max_stack_frames, "max_stack_frames", upper=DEFAULT_MAX_STACK_FRAMES
            ),
        )
        object.__setattr__(
            self,
            "max_line_events",
            _positive_int(
                self.max_line_events, "max_line_events", upper=DEFAULT_MAX_EVENTS
            ),
        )
        object.__setattr__(
            self,
            "max_payload_bytes",
            _positive_int(
                self.max_payload_bytes, "max_payload_bytes", upper=MAX_METADATA_BYTES
            ),
        )
        object.__setattr__(
            self,
            "max_summary_chars",
            _positive_int(
                self.max_summary_chars, "max_summary_chars", upper=MAX_TEXT_CHARS
            ),
        )
        object.__setattr__(
            self,
            "max_summary_depth",
            _positive_int(self.max_summary_depth, "max_summary_depth", upper=8),
        )

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
            "collect_external": self.collect_external,
            "capture_locals": self.capture_locals,
            "network_isolation": self.network_isolation,
            "halt_on_cancel": self.halt_on_cancel,
            "include_raw_bodies_in_private": self.include_raw_bodies_in_private,
            "max_events": self.max_events,
            "max_stack_frames": self.max_stack_frames,
            "max_line_events": self.max_line_events,
            "max_payload_bytes": self.max_payload_bytes,
            "max_summary_chars": self.max_summary_chars,
            "max_summary_depth": self.max_summary_depth,
            "language": ADMITTED_LANGUAGE,
            "tracer_version": PYTHON_EXECUTION_TRACER_VERSION,
        }

    @property
    def trace_collection_policy_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def capture_profile_cid(self) -> str:
        return cid_for_structured(
            {
                "schema": TRACE_CAPTURE_PROFILE_SCHEMA,
                "policy_cid": self.trace_collection_policy_cid,
                "language": ADMITTED_LANGUAGE,
                "tracer_version": PYTHON_EXECUTION_TRACER_VERSION,
            }
        )


class TraceCancellation:
    """Mutable cancellation token; cancellation is never an accepted transition."""

    INTERFACE: ClassVar[str] = TRACE_CANCELLATION_INTERFACE

    def __init__(self) -> None:
        self._cancelled = False
        self._reason = ""

    def cancel(self, reason: str = "cancelled") -> None:
        self._cancelled = True
        self._reason = _nfc(reason, "cancellation reason")

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason


@dataclass(frozen=True, slots=True)
class TraceRedactor:
    """Omit secret and non-semantic fields; never claim full state after redaction."""

    policy: TraceCollectionPolicy = field(default_factory=TraceCollectionPolicy)

    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE

    def redact_locals(self, locals_map: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
        redacted: list[str] = []
        summary: dict[str, Any] = {}
        if not self.policy.capture_locals:
            return {}, ("locals",)
        count = 0
        for key in sorted(str(item) for item in locals_map):
            if key.startswith("__") and key.endswith("__"):
                continue
            if _forbidden_key(key):
                redacted.append(key if _secret_key(key) else key)
                continue
            if count >= DEFAULT_MAX_LOCALS:
                redacted.append("locals_overflow")
                break
            summary[key] = _summarize_value(
                locals_map[key] if key in locals_map else None,
                max_chars=self.policy.max_summary_chars,
                depth=0,
                max_depth=self.policy.max_summary_depth,
            )
            count += 1
        return summary, tuple(sorted(set(redacted)))

    def profile_for(self, redacted_dimensions: Sequence[str], unavailable: Sequence[str]) -> RedactionProfile:
        dimensions = tuple(sorted(set(redacted_dimensions)))
        missing = tuple(sorted(set(unavailable)))
        if dimensions:
            claim = CompletenessClaim.REDACTED
            privacy = PrivacyClass.RESTRICTED
        elif missing:
            claim = CompletenessClaim.PARTIAL
            privacy = PrivacyClass.INTERNAL
        else:
            claim = CompletenessClaim.FULL_STATE
            privacy = PrivacyClass.INTERNAL
        return RedactionProfile(
            privacy_class=privacy,
            redacted_dimensions=dimensions,
            unavailable_dimensions=missing,
            completeness_claim=claim,
        )


# ---------------------------------------------------------------------------
# Public records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceRecord:
    """In-process collection result with a public identity that omits raw bodies."""

    public_trace: ExecutionTrace
    private_trace: ExecutionTrace
    events: tuple[ProgramEvent, ...]
    states: tuple[ProgramExecutionState, ...]
    frames: tuple[StackFrameState, ...]
    exceptions: tuple[ExceptionSnapshot, ...]
    handlers: tuple[HandlerState, ...]
    policy: TraceCollectionPolicy
    redaction_profile: RedactionProfile
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    subject_cid: str
    logical_name: str
    capture_profile_cid: str
    cancelled: bool
    trace_status: TraceStatus | str
    transition_disposition: TransitionDisposition | str
    result_summary: Mapping[str, Any] = field(default_factory=dict)
    error_summary: Mapping[str, Any] | None = None

    SCHEMA: ClassVar[str] = TRACE_RECORD_SCHEMA
    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECORD_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "states", tuple(self.states))
        object.__setattr__(self, "frames", tuple(self.frames))
        object.__setattr__(self, "exceptions", tuple(self.exceptions))
        object.__setattr__(self, "handlers", tuple(self.handlers))
        object.__setattr__(self, "cancelled", _bool(self.cancelled, "cancelled"))
        object.__setattr__(
            self, "trace_status", TraceStatus(self.trace_status).value
        )
        object.__setattr__(
            self,
            "transition_disposition",
            TransitionDisposition(self.transition_disposition).value,
        )
        if self.cancelled and self.accepted_transition:
            raise PythonExecutionTraceError("cancellation emits no accepted transition")
        if str(self.transition_disposition) == ACCEPTED_TRANSITION_DISPOSITION:
            raise PythonExecutionTraceError("tracer does not persist operational acceptance")
        if self.public_trace.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if str(self.public_trace.privacy_class) not in {"public", "internal"}:
            if self.public_trace.includes_raw_bodies:
                raise PythonExecutionTraceError(
                    "private raw trace bodies never enter public records"
                )
        if self.public_trace.raw_execution_state_cids:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )

    @property
    def accepted_transition(self) -> bool:
        return False

    def event_kinds(self) -> tuple[str, ...]:
        return tuple(str(event.event_kind) for event in self.events)

    def to_public_dict(self) -> dict[str, Any]:
        """Public identity; never includes raw event bodies or private states."""

        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "public_trace": self.public_trace.to_dict(),
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "subject_cid": self.subject_cid,
            "logical_name": self.logical_name,
            "capture_profile_cid": self.capture_profile_cid,
            "policy_cid": self.policy.trace_collection_policy_cid,
            "redaction_profile_cid": self.redaction_profile.redaction_profile_cid,
            "cancelled": self.cancelled,
            "accepted_transition": False,
            "trace_status": self.trace_status,
            "transition_disposition": self.transition_disposition,
            "event_cids": list(self.public_trace.event_cids),
            "event_count": len(self.public_trace.event_cids),
        }

    @property
    def python_execution_trace_record_cid(self) -> str:
        return cid_for_structured(self.to_public_dict())


@dataclass(frozen=True, slots=True)
class PythonExecutionReplayReceipt:
    """Deterministic promised replay; never re-executes the subject."""

    execution_trace_cid: str
    event_cids: tuple[str, ...]
    public_record_cid: str
    cancelled: bool
    deterministic: bool = True
    replayed: bool = True

    SCHEMA: ClassVar[str] = TRACE_REPLAY_SCHEMA
    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE

    @property
    def accepted_transition(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "execution_trace_cid": self.execution_trace_cid,
            "event_cids": list(self.event_cids),
            "public_record_cid": self.public_record_cid,
            "cancelled": self.cancelled,
            "accepted_transition": False,
            "deterministic": self.deterministic,
            "replayed": self.replayed,
        }


# ---------------------------------------------------------------------------
# Isolation (runtime only; never at import)
# ---------------------------------------------------------------------------


def _load_module(name: str) -> Any | None:
    return sys.modules.get(name)


def _install_isolation(tracer: "PythonExecutionTracer") -> Callable[[], None]:
    restorers: list[Callable[[], None]] = []

    def patch_attr(module_name: str, attr: str, label: str) -> None:
        module = _load_module(module_name)
        if module is None:
            if module_name not in {"socket", "subprocess", "os"}:
                return
            try:
                module = __import__(module_name, fromlist=["*"])
            except Exception:
                return
        original = getattr(module, attr, None)
        if original is None or not callable(original):
            return

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            tracer._record_selected_external(label)
            if tracer.policy.network_isolation:
                raise PythonExecutionNetworkDenied(
                    f"test-only isolation denied {label}"
                )
            return original(*args, **kwargs)

        setattr(module, attr, wrapped)

        def restore(module: Any = module, attr: str = attr, original: Any = original) -> None:
            setattr(module, attr, original)

        restorers.append(restore)

    def patch_method(module_name: str, class_name: str, method_name: str, label: str) -> None:
        module = _load_module(module_name)
        if module is None:
            if module_name not in {"socket"}:
                return
            try:
                module = __import__(module_name, fromlist=[class_name])
            except Exception:
                return
        cls = getattr(module, class_name, None)
        if cls is None:
            return
        original = getattr(cls, method_name, None)
        if original is None:
            return

        def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
            tracer._record_selected_external(label)
            if tracer.policy.network_isolation:
                raise PythonExecutionNetworkDenied(
                    f"test-only isolation denied {label}"
                )
            return original(self, *args, **kwargs)

        setattr(cls, method_name, wrapped)

        def restore(cls: Any = cls, method_name: str = method_name, original: Any = original) -> None:
            setattr(cls, method_name, original)

        restorers.append(restore)

    if tracer.policy.collect_external or tracer.policy.network_isolation:
        patch_attr("socket", "create_connection", "socket.create_connection")
        patch_attr("socket", "getaddrinfo", "socket.getaddrinfo")
        patch_method("socket", "socket", "connect", "socket.socket.connect")
        patch_method("socket", "socket", "connect_ex", "socket.socket.connect_ex")
        patch_attr("subprocess", "Popen", "subprocess.Popen")
        patch_attr("subprocess", "run", "subprocess.run")
        patch_attr("subprocess", "call", "subprocess.call")
        patch_attr("subprocess", "check_call", "subprocess.check_call")
        patch_attr("subprocess", "check_output", "subprocess.check_output")
        patch_attr("os", "system", "os.system")
        patch_attr("sqlite3", "connect", "sqlite3.connect")
        patch_attr("duckdb", "connect", "duckdb.connect")
        patch_attr("urllib.request", "urlopen", "urllib.request.urlopen")
        patch_method(
            "http.client",
            "HTTPConnection",
            "connect",
            "http.client.HTTPConnection.connect",
        )

    def restore_all() -> None:
        for restore in reversed(restorers):
            restore()

    return restore_all


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class PythonExecutionTracer:
    """Collect admitted Python events with exact bindings and bounded summaries."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE
    VERSION: ClassVar[str] = PYTHON_EXECUTION_TRACER_VERSION

    def __init__(
        self,
        policy: TraceCollectionPolicy | None = None,
        redactor: TraceRedactor | None = None,
    ) -> None:
        self.policy = policy if policy is not None else TraceCollectionPolicy()
        if not isinstance(self.policy, TraceCollectionPolicy):
            raise PythonExecutionTraceError("policy must be a TraceCollectionPolicy")
        self.redactor = redactor if redactor is not None else TraceRedactor(self.policy)
        self._reset_session()

    def _reset_session(self) -> None:
        self._events: list[ProgramEvent] = []
        self._states: list[ProgramExecutionState] = []
        self._frames: list[StackFrameState] = []
        self._exceptions: list[ExceptionSnapshot] = []
        self._handlers: list[HandlerState] = []
        self._predecessor: str | None = None
        self._line_events = 0
        self._bounded = False
        self._cancelled = False
        self._halted = False
        self._pending_exception: ExceptionSnapshot | None = None
        self._handler_emitted = False
        self._instruction_cache: dict[int, tuple[tuple[int, str], ...]] = {}
        self._handler_ranges: tuple[tuple[str, int, int], ...] = ()
        self._subject_filename = ""
        self._subject_code: Any = None
        self._root_frame_id: int | None = None
        self._tree_cid = ""
        self._source_cid = ""
        self._env_cid = ""
        self._source_unavailable = False
        self._logical_name = ""
        self._subject_cid = ""
        self._cancellation: TraceCancellation | None = None
        self._redacted: set[str] = set()
        self._unavailable: set[str] = set()
        self._tracer_error: BaseException | None = None

    def record(
        self,
        subject: Callable[..., Any],
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        *,
        cancellation: TraceCancellation | None = None,
        tree_cid: str | None = None,
        environment_binding: Mapping[str, str] | None = None,
    ) -> PythonExecutionTraceRecord:
        if not callable(subject):
            raise PythonExecutionTraceError("subject must be callable")
        self._reset_session()
        self._cancellation = cancellation
        self._logical_name = _callable_logical_name(subject)
        source_text, source_cid, source_unavailable, source_start = _subject_source(subject)
        self._source_cid = source_cid
        self._source_unavailable = source_unavailable
        if source_unavailable:
            self._unavailable.add("source_text")
        bindings = _mapping(environment_binding or _default_environment(), "environment_binding")
        self._env_cid = _environment_cid(bindings)
        self._tree_cid = tree_cid or _tree_cid(source_cid, self._logical_name)
        self._subject_code = getattr(subject, "__code__", None)
        if isinstance(subject, MethodType):
            self._subject_code = subject.__func__.__code__
        self._subject_filename = str(getattr(self._subject_code, "co_filename", "") or "")
        self._subject_cid = _code_cid(
            logical_name=self._logical_name,
            source_cid=source_cid,
            firstlineno=int(getattr(self._subject_code, "co_firstlineno", 0) or 0),
            co_name=str(getattr(self._subject_code, "co_name", self._logical_name)),
        )
        self._handler_ranges = _handler_ranges(
            source_text, source_unavailable, start_line=source_start
        )
        call_kwargs = dict(kwargs or {})
        previous_trace = sys.gettrace()
        previous_profile = sys.getprofile()
        restore_isolation = _install_isolation(self)
        result: Any = None
        error: BaseException | None = None
        try:
            sys.settrace(self._trace)
            sys.setprofile(self._profile)
            try:
                result = subject(*tuple(args), **call_kwargs)
            except PythonExecutionCancelled:
                self._cancelled = True
                self._halted = True
            except PythonExecutionNetworkDenied as denied:
                error = denied
            except Exception as exc:
                error = exc
        finally:
            sys.settrace(previous_trace)
            sys.setprofile(previous_profile)
            restore_isolation()
            self._instruction_cache.clear()
        if self._cancellation is not None and self._cancellation.cancelled:
            self._cancelled = True
        if self._tracer_error is not None:
            raise PythonExecutionTraceError(
                f"hermetic tracer failed closed: {self._tracer_error}"
            ) from self._tracer_error
        return self._seal(result=result, error=error)

    def replay(
        self,
        record: PythonExecutionTraceRecord,
        *,
        promised_events: Sequence[ProgramEvent] | None = None,
    ) -> PythonExecutionReplayReceipt:
        return replay_deterministic_trace(record, promised_events=promised_events)

    def _trace(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if self._halted:
            return None
        if frame.f_code.co_filename == _TRACER_FILENAME:
            return self._trace
        if self._cancellation is not None and self._cancellation.cancelled:
            self._cancelled = True
            if self.policy.halt_on_cancel:
                self._halted = True
                raise PythonExecutionCancelled(self._cancellation.reason or "cancelled")
            return None
        if not self._inside_subject(frame, event):
            return self._trace
        sys.settrace(None)
        try:
            self._handle_trace_event(frame, event, arg)
        except PythonExecutionCancelled:
            raise
        except PythonExecutionNetworkDenied:
            raise
        except Exception as exc:
            if self._tracer_error is None:
                self._tracer_error = exc
        finally:
            if not self._halted:
                sys.settrace(self._trace)
        if self._halted:
            return None
        return self._trace

    def _profile(self, frame: FrameType, event: str, arg: Any) -> None:
        if self._halted or event != "c_call":
            return
        if frame.f_code.co_filename == _TRACER_FILENAME:
            return
        name = getattr(arg, "__qualname__", None) or getattr(arg, "__name__", "")
        module = getattr(arg, "__module__", "") or ""
        label = f"{module}.{name}" if module else str(name)
        if label in SELECTED_EXTERNAL_TARGETS or str(name) in {
            "connect",
            "create_connection",
            "urlopen",
            "Popen",
            "system",
        }:
            if self._inside_subject(frame, "call"):
                self._record_selected_external(label or str(name))

    def _inside_subject(self, frame: FrameType, event: str) -> bool:
        if self._subject_code is None:
            return False
        if frame.f_code is self._subject_code:
            if event == "call" and self._root_frame_id is None:
                self._root_frame_id = id(frame)
            return True
        if self._subject_filename and frame.f_code.co_filename != self._subject_filename:
            return False
        if frame.f_code.co_filename == _TRACER_FILENAME:
            return False
        current: FrameType | None = frame
        depth = 0
        while current is not None and depth <= self.policy.max_stack_frames + 8:
            if current.f_code.co_filename == _TRACER_FILENAME:
                return False
            if current.f_code is self._subject_code or id(current) == self._root_frame_id:
                return True
            current = current.f_back
            depth += 1
        return False

    def _handle_trace_event(self, frame: FrameType, event: str, arg: Any) -> None:
        if self._event_budget_exhausted():
            return
        if event == "call":
            if self.policy.collect_calls:
                self._emit(EventKind.CALL, frame, payload={"phase": "call"})
            return
        if event == "line":
            self._maybe_emit_handler(frame)
            if self.policy.collect_lines and self._line_events < self.policy.max_line_events:
                self._line_events += 1
                self._emit(EventKind.LINE, frame, payload={"phase": "line"})
            elif self.policy.collect_lines:
                self._unavailable.add("line_overflow")
                self._bounded = True
            return
        if event == "return":
            kind = self._return_kind(frame)
            payload = {"phase": kind.value, "value": self._summarize_arg(arg)}
            if kind is EventKind.YIELD and self.policy.collect_yields:
                self._emit(kind, frame, payload=payload, locals_map=frame.f_locals)
            elif kind is EventKind.AWAIT and self.policy.collect_awaits:
                self._emit(kind, frame, payload=payload, locals_map=frame.f_locals)
            elif kind is EventKind.RETURN and self.policy.collect_returns:
                self._emit(kind, frame, payload=payload, locals_map=frame.f_locals)
            return
        if event == "exception" and self.policy.collect_exceptions:
            snapshot = self._exception_snapshot(frame, arg)
            self._pending_exception = snapshot
            self._handler_emitted = False
            self._emit(
                EventKind.RAISE,
                frame,
                payload={"phase": "raise", "exception_type": snapshot.exception_type},
                exception=snapshot,
                locals_map=frame.f_locals,
            )

    def _return_kind(self, frame: FrameType) -> EventKind:
        flags = frame.f_code.co_flags
        opname = self._opname(frame)
        finished = opname in {"RETURN_VALUE", "RETURN_CONST"}
        if flags & inspect.CO_COROUTINE:
            if finished:
                return EventKind.RETURN
            return EventKind.AWAIT
        if flags & (inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR):
            if finished:
                return EventKind.RETURN
            return EventKind.YIELD
        return EventKind.RETURN

    def _opname(self, frame: FrameType) -> str:
        code = frame.f_code
        cached = self._instruction_cache.get(id(code))
        if cached is None:
            cached = tuple(
                (instruction.offset, instruction.opname)
                for instruction in dis.get_instructions(code)
            )
            self._instruction_cache[id(code)] = cached
        lasti = frame.f_lasti
        name = ""
        for offset, opname in cached:
            if offset <= lasti:
                name = opname
            else:
                break
        return name

    def _maybe_emit_handler(self, frame: FrameType) -> None:
        if not self.policy.collect_handlers or self._pending_exception is None:
            return
        if self._handler_emitted:
            return
        lineno = int(frame.f_lineno or 0)
        match = next(
            (kind for kind, start, end in self._handler_ranges if start <= lineno <= end),
            None,
        )
        if match is None:
            return
        handler = self._handler_state(frame, match, self._pending_exception)
        payload = {"phase": "handler", "handler_kind": match}
        self._emit(
            EventKind.CATCH,
            frame,
            payload=payload,
            exception=self._pending_exception,
            handler=handler,
        )
        if not self._event_budget_exhausted():
            self._emit(
                EventKind.HANDLER,
                frame,
                payload=payload,
                exception=self._pending_exception,
                handler=handler,
            )
        self._handler_emitted = True

    def _event_budget_exhausted(self) -> bool:
        if len(self._events) >= self.policy.max_events:
            self._bounded = True
            self._unavailable.add("remaining_trace")
            return True
        return False

    def _summarize_arg(self, arg: Any) -> Any:
        return _summarize_value(
            arg,
            max_chars=self.policy.max_summary_chars,
            depth=0,
            max_depth=self.policy.max_summary_depth,
        )

    def _stack_frames(
        self,
        frame: FrameType,
        *,
        locals_map: Mapping[str, Any] | None,
        exception: ExceptionSnapshot | None,
        handler: HandlerState | None,
        redacted: Sequence[str],
        unavailable: Sequence[str],
    ) -> tuple[StackFrameState, ...]:
        chain: list[FrameType] = []
        current: FrameType | None = frame
        depth = 0
        while current is not None and depth < self.policy.max_stack_frames:
            if current.f_code.co_filename == _TRACER_FILENAME:
                break
            chain.append(current)
            if current.f_code is self._subject_code:
                break
            current = current.f_back
            depth += 1
        if not chain:
            chain = [frame]
        frames: list[StackFrameState] = []
        for ordinal, item in enumerate(chain):
            logical = _frame_logical_name(item)
            code_cid = _code_cid(
                logical_name=logical,
                source_cid=self._source_cid,
                firstlineno=int(item.f_code.co_firstlineno or 0),
                co_name=item.f_code.co_name,
            )
            summary: dict[str, Any] = {}
            frame_redacted = list(redacted)
            frame_unavailable = list(unavailable)
            if ordinal == 0 and locals_map is not None:
                summary, extra = self.redactor.redact_locals(locals_map)
                frame_redacted.extend(extra)
            elif not self.policy.capture_locals:
                frame_unavailable.append("locals")
            claim = CompletenessClaim.FULL_STATE
            if frame_redacted:
                claim = CompletenessClaim.REDACTED
            elif frame_unavailable:
                claim = CompletenessClaim.PARTIAL
            frames.append(
                StackFrameState(
                    ordinal=ordinal,
                    language=ADMITTED_LANGUAGE,
                    tree_cid=self._tree_cid,
                    source_cid=self._source_cid,
                    code_cid=code_cid,
                    environment_binding_cid=self._env_cid,
                    logical_name=logical,
                    line=int(item.f_lineno or 0),
                    column=_column(item),
                    state_summary=summary,
                    exception_snapshot_cid=(
                        None if exception is None or ordinal != 0 else exception.exception_snapshot_cid
                    ),
                    handler_state_cid=(
                        None if handler is None or ordinal != 0 else handler.handler_state_cid
                    ),
                    exception_active=exception is not None and ordinal == 0,
                    handler_active=handler is not None and ordinal == 0,
                    redacted_dimensions=tuple(sorted(set(frame_redacted))),
                    unavailable_dimensions=tuple(sorted(set(frame_unavailable))),
                    completeness_claim=claim,
                    privacy_class=PrivacyClass.PRIVATE,
                )
            )
        return tuple(frames)

    def _exception_snapshot(self, frame: FrameType, arg: Any) -> ExceptionSnapshot:
        exc_type: type[BaseException] | None = None
        if isinstance(arg, tuple) and arg:
            maybe_type = arg[0]
            if isinstance(maybe_type, type) and issubclass(maybe_type, BaseException):
                exc_type = maybe_type
        type_name = getattr(exc_type, "__name__", "Exception")
        frames = self._stack_frames(
            frame,
            locals_map=None,
            exception=None,
            handler=None,
            redacted=(),
            unavailable=("locals",),
        )
        snapshot = ExceptionSnapshot(
            language=ADMITTED_LANGUAGE,
            exception_type=str(type_name)[:MAX_TEXT_CHARS],
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=frames[0].code_cid if frames else self._subject_cid,
            environment_binding_cid=self._env_cid,
            exception_value_summary={"type": str(type_name), "bounded": True},
            traceback_stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
            raised_at_event_cid=self._predecessor,
            future_execution=False,
            unavailable_dimensions=("exception_args",),
            completeness_claim=CompletenessClaim.PARTIAL,
        )
        self._exceptions.append(snapshot)
        self._frames.extend(frames)
        return snapshot

    def _handler_state(
        self,
        frame: FrameType,
        kind: str,
        exception: ExceptionSnapshot,
    ) -> HandlerState:
        mapping = {
            "except": HandlerKind.EXCEPT,
            "except_star": HandlerKind.EXCEPT_STAR,
            "finally": HandlerKind.FINALLY,
            "else": HandlerKind.ELSE,
        }
        handler = HandlerState(
            language=ADMITTED_LANGUAGE,
            handler_kind=mapping.get(kind, HandlerKind.EXCEPT),
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=_code_cid(
                logical_name=_frame_logical_name(frame),
                source_cid=self._source_cid,
                firstlineno=int(frame.f_code.co_firstlineno or 0),
                co_name=frame.f_code.co_name,
            ),
            environment_binding_cid=self._env_cid,
            logical_name=_frame_logical_name(frame),
            stack_ordinal=0,
            handler_active=True,
            matching_exception_snapshot_cid=exception.exception_snapshot_cid,
            unavailable_dimensions=(),
        )
        self._handlers.append(handler)
        return handler

    def _record_selected_external(self, label: str) -> None:
        if self._halted or self._event_budget_exhausted():
            return
        frame = sys._getframe(2)
        while frame is not None and frame.f_code.co_filename == _TRACER_FILENAME:
            frame = frame.f_back  # type: ignore[assignment]
        if frame is None:
            return
        if not self._inside_subject(frame, "call"):
            return
        payload = {
            "phase": "external",
            "effect": label,
            "isolated": True,
            "denied": self.policy.network_isolation,
        }
        try:
            self._emit(EventKind.EXTERNAL, frame, payload=payload)
        except Exception as exc:
            if self._tracer_error is None:
                self._tracer_error = exc

    def _emit(
        self,
        kind: EventKind,
        frame: FrameType,
        *,
        payload: Mapping[str, Any],
        exception: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
        locals_map: Mapping[str, Any] | None = None,
    ) -> None:
        if self._event_budget_exhausted():
            return
        summary, redacted = (
            self.redactor.redact_locals(locals_map)
            if locals_map is not None
            else ({}, ())
        )
        unavailable = set(self._unavailable)
        if self._source_unavailable:
            unavailable.add("source_text")
        if redacted:
            self._redacted.update(redacted)
        if not self.policy.capture_locals:
            unavailable.add("locals")
        frames = self._stack_frames(
            frame,
            locals_map=locals_map,
            exception=exception,
            handler=handler,
            redacted=redacted,
            unavailable=tuple(unavailable),
        )
        self._frames.extend(frames)
        event_redacted = tuple(sorted(set(redacted)))
        event_unavailable = tuple(sorted(unavailable))
        if event_redacted:
            claim = CompletenessClaim.REDACTED
        elif event_unavailable:
            claim = CompletenessClaim.PARTIAL
        else:
            claim = CompletenessClaim.FULL_STATE
        body = dict(payload)
        if summary:
            body["locals"] = summary
        body = _bounded_payload(body, max_bytes=self.policy.max_payload_bytes)
        event = ProgramEvent(
            event_kind=kind,
            event_origin=EventOrigin.OBSERVED,
            observation_status=ObservationStatus.OBSERVED,
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=frames[0].code_cid if frames else self._subject_cid,
            environment_binding_cid=self._env_cid,
            subject_cid=self._subject_cid,
            logical_name=frames[0].logical_name if frames else self._logical_name,
            payload=body,
            line=int(frame.f_lineno or 0),
            column=_column(frame),
            predecessor_event_cid=self._predecessor,
            stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
            exception_snapshot_cid=None if exception is None else exception.exception_snapshot_cid,
            handler_state_cid=None if handler is None else handler.handler_state_cid,
            redaction_profile_cid=None,
            redacted_dimensions=event_redacted,
            unavailable_dimensions=event_unavailable,
            completeness_claim=claim,
            privacy_class=PrivacyClass.PRIVATE,
        )
        self._events.append(event)
        self._predecessor = event.program_event_cid
        if self.policy.include_raw_bodies_in_private:
            try:
                state = assemble_program_execution_state(
                    language=ADMITTED_LANGUAGE,
                    capture_profile_cid=self.policy.capture_profile_cid,
                    tree_cid=self._tree_cid,
                    source_cid=self._source_cid,
                    environment_binding_cid=self._env_cid,
                    frames=frames,
                    observed_state=summary,
                    heap_summary={},
                    heap_bound=HeapBound.UNAVAILABLE,
                    exception=exception,
                    handler=handler,
                    observation_status=ObservationStatus.OBSERVED,
                    completeness_claim=CompletenessClaim.PARTIAL,
                    privacy_class=PrivacyClass.PRIVATE,
                    includes_raw_bodies=True,
                    unavailable_dimensions=tuple(sorted(set(unavailable) | {"heap"})),
                    code_cid=frames[0].code_cid if frames else self._subject_cid,
                )
                self._states.append(state)
            except ProgramExecutionError:
                self._unavailable.add("execution_state")

    def _ensure_event(self) -> None:
        if self._events:
            return
        unavailable = tuple(sorted(self._unavailable | {"event_body", "remaining_trace"}))
        event = ProgramEvent(
            event_kind=EventKind.UNAVAILABLE,
            event_origin=EventOrigin.OBSERVED,
            observation_status=ObservationStatus.UNAVAILABLE,
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=self._subject_cid,
            environment_binding_cid=self._env_cid,
            subject_cid=self._subject_cid,
            logical_name=self._logical_name,
            payload={"phase": "unavailable"},
            line=0,
            column=0,
            predecessor_event_cid=None,
            stack_frame_cids=(),
            exception_snapshot_cid=None,
            handler_state_cid=None,
            redaction_profile_cid=None,
            redacted_dimensions=(),
            unavailable_dimensions=unavailable,
            completeness_claim=CompletenessClaim.UNAVAILABLE,
            privacy_class=PrivacyClass.INTERNAL,
        )
        self._events.append(event)

    def _seal(
        self,
        *,
        result: Any,
        error: BaseException | None,
    ) -> PythonExecutionTraceRecord:
        self._ensure_event()
        if self._cancelled:
            self._unavailable.add("remaining_trace")
            status = TraceStatus.CANCELLED
            disposition = TransitionDisposition.CANCELLED
        elif self._bounded:
            status = TraceStatus.BOUNDED
            disposition = TransitionDisposition.UNAVAILABLE
        elif error is not None:
            status = TraceStatus.FAILED
            disposition = TransitionDisposition.OBSERVED
        else:
            status = TraceStatus.COMPLETED
            disposition = TransitionDisposition.OBSERVED
        redacted = tuple(sorted(self._redacted | {"raw_body"}))
        unavailable = tuple(sorted(self._unavailable | {"heap"}))
        profile = self.redactor.profile_for(redacted, unavailable)
        private_trace = assemble_execution_trace(
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self._env_cid,
            events=self._events,
            states=self._states if self.policy.include_raw_bodies_in_private else (),
            redaction=profile,
            completeness_claim=CompletenessClaim.REDACTED,
            privacy_class=PrivacyClass.PRIVATE,
            includes_raw_bodies=self.policy.include_raw_bodies_in_private,
            unavailable_dimensions=unavailable,
        )
        public_trace = private_trace.public_view()
        error_summary = None
        if error is not None:
            error_summary = {
                "type": type(error).__name__,
                "bounded": True,
            }
        return PythonExecutionTraceRecord(
            public_trace=public_trace,
            private_trace=private_trace,
            events=tuple(self._events),
            states=tuple(self._states),
            frames=tuple(self._frames),
            exceptions=tuple(self._exceptions),
            handlers=tuple(self._handlers),
            policy=self.policy,
            redaction_profile=profile,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self._env_cid,
            subject_cid=self._subject_cid,
            logical_name=self._logical_name,
            capture_profile_cid=self.policy.capture_profile_cid,
            cancelled=self._cancelled,
            trace_status=status,
            transition_disposition=disposition,
            result_summary=MappingProxyType(
                {"value": self._summarize_arg(result), "error": error_summary}
            ),
            error_summary=error_summary,
        )


def _column(frame: FrameType) -> int:
    # Column is optional on stack frames; keep it a deterministic non-negative int.
    # Instruction-to-column mapping is host-bytecode-layout sensitive, so identity
    # uses line + logical name rather than a guessed column.
    _ = frame
    return 0


def _handler_ranges(
    source_text: str,
    unavailable: bool,
    *,
    start_line: int = 1,
) -> tuple[tuple[str, int, int], ...]:
    if unavailable or not source_text.strip():
        return ()
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return ()
    offset = int(start_line) - 1
    ranges: list[tuple[str, int, int]] = []
    try_types: tuple[type[Any], ...] = (ast.Try,)
    try_star = getattr(ast, "TryStar", None)
    if isinstance(try_star, type):
        try_types = (ast.Try, try_star)

    def span(nodes: list[ast.stmt]) -> tuple[int, int] | None:
        if not nodes:
            return None
        first = nodes[0]
        last = nodes[-1]
        begin = int(getattr(first, "lineno", 0) or 0) + offset
        finish = int(getattr(last, "end_lineno", None) or getattr(last, "lineno", 0) or 0) + offset
        return begin, finish

    for node in ast.walk(tree):
        if not isinstance(node, try_types):
            continue
        kind_default = "except_star" if type(node).__name__ == "TryStar" else "except"
        for handler in getattr(node, "handlers", ()):
            begin = int(handler.lineno) + offset
            finish = int(getattr(handler, "end_lineno", None) or handler.lineno) + offset
            ranges.append((kind_default, begin, finish))
        orelse = span(list(getattr(node, "orelse", ()) or ()))
        if orelse is not None:
            ranges.append(("else", orelse[0], orelse[1]))
        final = span(list(getattr(node, "finalbody", ()) or ()))
        if final is not None:
            ranges.append(("finally", final[0], final[1]))
    return tuple(ranges)


# ---------------------------------------------------------------------------
# Public interfaces
# ---------------------------------------------------------------------------


def record_python_execution_trace(
    subject: Callable[..., Any],
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    *,
    policy: TraceCollectionPolicy | None = None,
    cancellation: TraceCancellation | None = None,
    tree_cid: str | None = None,
    environment_binding: Mapping[str, str] | None = None,
    redactor: TraceRedactor | None = None,
) -> PythonExecutionTraceRecord:
    """Collect a hermetic admitted-Python execution trace for ``subject``."""

    tracer = PythonExecutionTracer(policy=policy, redactor=redactor)
    return tracer.record(
        subject,
        args=args,
        kwargs=kwargs,
        cancellation=cancellation,
        tree_cid=tree_cid,
        environment_binding=environment_binding,
    )


def replay_deterministic_trace(
    record: PythonExecutionTraceRecord,
    *,
    promised_events: Sequence[ProgramEvent] | None = None,
) -> PythonExecutionReplayReceipt:
    """Replay a recorded trace identity without re-executing the subject.

    Promised events, when supplied, must match the recorded event CIDs in
    order.  Cancelled records still cannot decode as accepted transitions.
    """

    if not isinstance(record, PythonExecutionTraceRecord):
        raise PythonExecutionTraceError("replay requires a PythonExecutionTraceRecord")
    events = tuple(record.events)
    if promised_events is not None:
        promised = tuple(promised_events)
        if len(promised) != len(events):
            raise PythonExecutionTraceError("promised event count diverges from the recorded trace")
        for expected, actual in zip(events, promised):
            if not isinstance(actual, ProgramEvent):
                raise PythonExecutionTraceError("promised replay requires ProgramEvent values")
            if expected.program_event_cid != actual.program_event_cid:
                raise PythonExecutionTraceError("promised event identity diverges from the recorded trace")
            if expected.tree_cid != actual.tree_cid or expected.environment_binding_cid != actual.environment_binding_cid:
                raise PythonExecutionTraceError("promised events must bind the recorded tree and environment")
    public = ExecutionTrace.from_dict(record.public_trace.to_dict())
    if public.execution_trace_cid != record.public_trace.execution_trace_cid:
        raise PythonExecutionTraceError("public trace identity is not deterministic")
    if public.includes_raw_bodies or public.raw_execution_state_cids:
        raise PythonExecutionTraceError("private raw trace bodies never enter public records")
    if record.cancelled and record.accepted_transition:
        raise PythonExecutionTraceError("cancellation emits no accepted transition")
    return PythonExecutionReplayReceipt(
        execution_trace_cid=public.execution_trace_cid,
        event_cids=public.event_cids,
        public_record_cid=record.python_execution_trace_record_cid,
        cancelled=record.cancelled,
        deterministic=True,
        replayed=True,
    )


__all__ = [
    "ACCEPTED_TRANSITION_DISPOSITION",
    "ADMITTED_LANGUAGE",
    "IMPORT_DATABASE_OPENED",
    "IMPORT_INSTALLER_INVOKED",
    "IMPORT_MODEL_LOADED",
    "IMPORT_NETWORK_OPENED",
    "IMPORT_SCAN_PERFORMED",
    "IMPORT_SIDE_EFFECTS_PERFORMED",
    "IMPORT_SOCKET_OPENED",
    "IMPORT_SUBPROCESS_SPAWNED",
    "IMPORT_TRACE_HOOK_INSTALLED",
    "IMPORT_WATCHER_STARTED",
    "PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "PYTHON_EXECUTION_TRACE_RECORD_INTERFACE",
    "SELECTED_EXTERNAL_TARGETS",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "PythonExecutionCancelled",
    "PythonExecutionNetworkDenied",
    "PythonExecutionReplayReceipt",
    "PythonExecutionTraceError",
    "PythonExecutionTraceRecord",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCollectionPolicy",
    "TraceRedactor",
    "TraceStatus",
    "TransitionDisposition",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
