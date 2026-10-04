"""Hermetic in-process Python execution tracing (SAWM-008).

This module binds admitted call/return/line/exception/handler/yield/await and
selected external events to exact tree, source, symbol, callsite, and
environment identities.  It extends the datasets ``ProgramEvent@1`` /
``ExecutionTrace@1`` contracts; it does not introduce shell tracing, persist
operational acceptance, or bypass execution isolation.

Authority rules (normative):

* Import is side-effect free: no network, socket connect, installer,
  subprocess, database, repository scan, watcher, or model load occurs at
  import time.  Tracing hooks and audit dispatchers are installed only while
  a collection is active.
* Cancellation never emits an accepted transition.  This tracer never persists
  operational acceptance; ``accepted_transition`` is always false.
* Private raw trace bodies never enter public records.  Public views are
  redacted, bounded, and fail closed on secret / non-semantic fields.
* Nondeterministic external effects are explicit observations or typed
  unavailable.  Line and basic-block detail is policy/cost bounded.
* Python is the only admitted language.  Unsupported languages remain typed
  unavailable and are rejected at the collection boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import CodeType, FrameType, MappingProxyType, TracebackType
from typing import Any, ClassVar, Final
import dis
import inspect
import sys
import threading
import types
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
    MAX_SAFE_INTEGER,
    ObservationStatus,
    PrivacyClass,
    ProgramEvent,
    ProgramExecutionError,
    ProgramExecutionState,
    ProgramLanguage,
    PUBLIC_PRIVACY_CLASSES,
    RedactionProfile,
    SECRET_FIELD_MARKERS,
    StackFrameState,
    assemble_execution_trace,
    assemble_program_execution_state,
    observe_program_event,
    public_execution_view,
)


# ---------------------------------------------------------------------------
# Schema / interface constants
# ---------------------------------------------------------------------------

HERMETIC_PYTHON_EXECUTION_TRACE_INTERFACE: Final[str] = (
    "HermeticPythonExecutionTrace@1"
)
HERMETIC_PYTHON_EXECUTION_TRACE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.hermetic-python-execution-trace@1"
)
TRACE_COLLECTION_POLICY_INTERFACE: Final[str] = "TraceCollectionPolicy@1"
TRACE_COLLECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-policy@1"
)
PYTHON_RUNTIME_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-runtime-environment@1"
)
PYTHON_CODE_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-code-identity@1"
)
PYTHON_TREE_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-tree-binding@1"
)

ADMITTED_TRACE_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
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
        EventKind.UNAVAILABLE.value,
    }
)
DEFAULT_TRACE_EVENT_KINDS: Final[tuple[str, ...]] = (
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
DENIED_NETWORK_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "socket.connect",
        "socket.getaddrinfo",
        "socket.bind",
        "socket.sendmsg",
        "socket.sendto",
        "socket.send",
    }
)
DENIED_SUBPROCESS_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.posix_spawnp",
    }
)
DENIED_INSTALLER_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "pip.main",
        "ensurepip.bootstrap",
    }
)
YIELD_OPNAMES: Final[frozenset[str]] = frozenset(
    {"YIELD_VALUE", "YIELD_FROM", "YIELD_STAR", "SEND"}
)
AWAIT_OPNAMES: Final[frozenset[str]] = frozenset(
    {
        "GET_AWAITABLE",
        "BEFORE_ASYNC_WITH",
        "GET_AITER",
        "GET_ANEXT",
        "END_ASYNC_FOR",
        "SEND",
    }
)
GENERATOR_FLAGS: Final[int] = (
    inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR
)
COROUTINE_FLAGS: Final[int] = (
    inspect.CO_COROUTINE
    | inspect.CO_ITERABLE_COROUTINE
    | inspect.CO_ASYNC_GENERATOR
)
SCOPE_TARGET_ONLY: Final[str] = "target_only"
SCOPE_SAME_SOURCE: Final[str] = "same_source"
SCOPE_NESTED: Final[str] = "nested"
ADMITTED_SCOPES: Final[frozenset[str]] = frozenset(
    {SCOPE_TARGET_ONLY, SCOPE_SAME_SOURCE, SCOPE_NESTED}
)
MAX_SUMMARY_DEPTH: Final[int] = 3
MAX_SUMMARY_ITEMS: Final[int] = 16
MAX_SUMMARY_CHARS: Final[int] = 256

_HOOK_INSTALLED: bool = False
_THREAD: threading.local = threading.local()


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic tracing configuration or isolation fails closed."""


class _TraceIsolationDenied(PythonExecutionTraceError):
    """Raised into the traced callable when test isolation denies an effect."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str) -> str:
    if type(value) is not str or not value:
        raise PythonExecutionTraceError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise PythonExecutionTraceError(f"{name} must be trimmed NFC text")
    if any(not char.isprintable() for char in value):
        raise PythonExecutionTraceError(f"{name} contains invalid text")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise PythonExecutionTraceError(f"{name} must be a boolean")
    return value


def _positive_int(value: Any, name: str, *, minimum: int = 1, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum or value > maximum:
        raise PythonExecutionTraceError(
            f"{name} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    try:
        return validate_cid(value)
    except Exception as exc:
        raise PythonExecutionTraceError(f"{name} must be a valid CID") from exc


def _secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in SECRET_FIELD_MARKERS or lowered in FORBIDDEN_FIELD_MARKERS:
        return True
    return any(marker in lowered for marker in SECRET_FIELD_MARKERS)


def _collect_code_objects(code: CodeType) -> set[CodeType]:
    found = {code}
    for const in code.co_consts:
        if isinstance(const, CodeType):
            found |= _collect_code_objects(const)
    return found


def _opname_at(frame: FrameType) -> str:
    lasti = frame.f_lasti
    if lasti < 0:
        return ""
    current = ""
    try:
        for instruction in dis.get_instructions(frame.f_code):
            if instruction.offset == lasti:
                return instruction.opname
            if instruction.offset < lasti:
                current = instruction.opname
            else:
                return current
    except Exception:
        return current
    return current


def _callable_code(target: Callable[..., Any]) -> CodeType:
    code = getattr(target, "__code__", None)
    if isinstance(code, CodeType):
        return code
    wrapped = getattr(target, "__wrapped__", None)
    if wrapped is not None:
        return _callable_code(wrapped)
    raise PythonExecutionTraceError("target must be a Python function or method")


def _callable_name(target: Callable[..., Any]) -> str:
    name = getattr(target, "__qualname__", None) or getattr(target, "__name__", None)
    if type(name) is not str or not name.strip():
        name = type(target).__name__
    return unicodedata.normalize("NFC", name.strip())


def _callable_source_text(target: Callable[..., Any]) -> str:
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError):
        source = ""
    if not source:
        code = getattr(target, "__code__", None)
        if isinstance(code, CodeType):
            source = f"<bytecode:{_callable_name(target)}:{code.co_firstlineno}>"
        else:
            source = f"<callable:{_callable_name(target)}>"
    normalized = unicodedata.normalize("NFC", source.replace("\r\n", "\n"))
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def _safe_int(value: int) -> int | dict[str, str]:
    if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
        return {"type": "int", "unavailable": "overflow"}
    return value


def bind_python_environment() -> str:
    """Return the CID of the current Python runtime/environment binding."""

    payload = {
        "schema": PYTHON_RUNTIME_ENVIRONMENT_SCHEMA,
        "language": ProgramLanguage.PYTHON.value,
        "implementation": sys.implementation.name,
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "micro": sys.version_info.micro,
    }
    return cid_for_structured(payload)


def bind_python_code(frame: FrameType | CodeType, *, source_cid: str, logical_name: str) -> str:
    """Return the CID of one exact Python code/callsite identity."""

    code = frame.f_code if isinstance(frame, types.FrameType) else frame
    payload = {
        "schema": PYTHON_CODE_IDENTITY_SCHEMA,
        "source_cid": source_cid,
        "logical_name": logical_name,
        "filename": unicodedata.normalize("NFC", code.co_filename.split("/")[-1]),
        "firstlineno": code.co_firstlineno,
        "argcount": code.co_argcount,
        "flags": code.co_flags,
        "bytecode_sha256_cid": cid_for_bytes(code.co_code),
    }
    return cid_for_structured(payload)


def bind_python_tree(*, source_cid: str, logical_name: str) -> str:
    """Return a hermetic fixture tree identity bound to source and symbol."""

    return cid_for_structured(
        {
            "schema": PYTHON_TREE_BINDING_SCHEMA,
            "source_cid": source_cid,
            "logical_name": logical_name,
            "language": ProgramLanguage.PYTHON.value,
        }
    )


def _drive_coroutine(value: Any) -> Any:
    if not inspect.iscoroutine(value):
        return value
    try:
        while True:
            value.send(None)
    except StopIteration as stop:
        return stop.value


def _ensure_audit_hook() -> None:
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    sys.addaudithook(_dispatch_audit)
    _HOOK_INSTALLED = True


def _dispatch_audit(event: str, args: tuple[Any, ...]) -> None:
    tracer = getattr(_THREAD, "tracer", None)
    if tracer is None:
        return
    tracer.handle_audit(event, args)


# ---------------------------------------------------------------------------
# Policy, redaction, cancellation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Bounded collection policy; line/basic-block detail is cost-capped."""

    event_kinds: Sequence[str] = DEFAULT_TRACE_EVENT_KINDS
    max_events: int = 4_096
    max_line_events: int = 256
    max_stack_frames: int = 32
    max_payload_bytes: int = 4_096
    max_state_summary_bytes: int = 2_048
    collect_line_events: bool = True
    collect_locals: bool = True
    deny_network: bool = True
    deny_subprocess: bool = True
    deny_installer: bool = True
    scope: str = SCOPE_SAME_SOURCE
    language: str = ProgramLanguage.PYTHON.value
    privacy_class: str = PrivacyClass.INTERNAL.value
    include_raw_bodies_privately: bool = True
    tree_cid: str | None = None
    source_cid: str | None = None
    environment_binding_cid: str | None = None

    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE
    SCHEMA: ClassVar[str] = TRACE_COLLECTION_POLICY_SCHEMA

    def __post_init__(self) -> None:
        kinds = tuple(_text(kind, "event_kind") for kind in self.event_kinds)
        unknown = sorted(set(kinds) - ADMITTED_TRACE_EVENT_KINDS)
        if unknown:
            raise PythonExecutionTraceError(
                f"event_kinds contains unsupported values {unknown}"
            )
        object.__setattr__(self, "event_kinds", tuple(dict.fromkeys(kinds)))
        object.__setattr__(
            self, "max_events", _positive_int(self.max_events, "max_events", maximum=65_536)
        )
        object.__setattr__(
            self,
            "max_line_events",
            _positive_int(self.max_line_events, "max_line_events", maximum=16_384),
        )
        object.__setattr__(
            self,
            "max_stack_frames",
            _positive_int(self.max_stack_frames, "max_stack_frames", maximum=256),
        )
        object.__setattr__(
            self,
            "max_payload_bytes",
            _positive_int(self.max_payload_bytes, "max_payload_bytes", maximum=16_384),
        )
        object.__setattr__(
            self,
            "max_state_summary_bytes",
            _positive_int(
                self.max_state_summary_bytes, "max_state_summary_bytes", maximum=16_384
            ),
        )
        object.__setattr__(
            self, "collect_line_events", _bool(self.collect_line_events, "collect_line_events")
        )
        object.__setattr__(
            self, "collect_locals", _bool(self.collect_locals, "collect_locals")
        )
        object.__setattr__(self, "deny_network", _bool(self.deny_network, "deny_network"))
        object.__setattr__(
            self, "deny_subprocess", _bool(self.deny_subprocess, "deny_subprocess")
        )
        object.__setattr__(
            self, "deny_installer", _bool(self.deny_installer, "deny_installer")
        )
        scope = _text(self.scope, "scope")
        if scope not in ADMITTED_SCOPES:
            raise PythonExecutionTraceError(f"scope {scope!r} is not admitted")
        object.__setattr__(self, "scope", scope)
        language = _text(self.language, "language")
        if language != ProgramLanguage.PYTHON.value:
            raise PythonExecutionTraceError(
                f"language {language!r} is typed unavailable; Python only"
            )
        object.__setattr__(self, "language", language)
        try:
            privacy = PrivacyClass(self.privacy_class).value
        except (TypeError, ValueError) as exc:
            raise PythonExecutionTraceError("privacy_class is unsupported") from exc
        object.__setattr__(self, "privacy_class", privacy)
        object.__setattr__(
            self,
            "include_raw_bodies_privately",
            _bool(self.include_raw_bodies_privately, "include_raw_bodies_privately"),
        )
        object.__setattr__(self, "tree_cid", _optional_cid(self.tree_cid, "tree_cid"))
        object.__setattr__(self, "source_cid", _optional_cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _optional_cid(self.environment_binding_cid, "environment_binding_cid"),
        )

    def admits(self, kind: str) -> bool:
        return kind in self.event_kinds

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "event_kinds": list(self.event_kinds),
            "max_events": self.max_events,
            "max_line_events": self.max_line_events,
            "max_stack_frames": self.max_stack_frames,
            "max_payload_bytes": self.max_payload_bytes,
            "max_state_summary_bytes": self.max_state_summary_bytes,
            "collect_line_events": self.collect_line_events,
            "collect_locals": self.collect_locals,
            "deny_network": self.deny_network,
            "deny_subprocess": self.deny_subprocess,
            "deny_installer": self.deny_installer,
            "scope": self.scope,
            "language": self.language,
            "privacy_class": self.privacy_class,
            "include_raw_bodies_privately": self.include_raw_bodies_privately,
        }

    @property
    def capture_profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def redaction_profile(self, *, redacted: Sequence[str], unavailable: Sequence[str]) -> RedactionProfile:
        redacted_dims = tuple(sorted(set(redacted)))
        unavailable_dims = tuple(sorted(set(unavailable)))
        if redacted_dims:
            claim = CompletenessClaim.REDACTED
        elif unavailable_dims:
            claim = CompletenessClaim.PARTIAL
        else:
            claim = CompletenessClaim.FULL_STATE
        privacy = (
            PrivacyClass.PUBLIC
            if self.privacy_class in PUBLIC_PRIVACY_CLASSES
            else PrivacyClass.PRIVATE
        )
        return RedactionProfile(
            privacy_class=privacy,
            redacted_dimensions=redacted_dims,
            unavailable_dimensions=unavailable_dims,
            completeness_claim=claim,
        )


class TraceCancellation:
    """Cooperative cancellation token; cancelled traces emit no accepted transition."""

    __slots__ = ("_reason", "_cancelled", "_events_recorded")

    def __init__(self, reason: str = "explicit") -> None:
        self._reason = _text(reason, "reason")
        self._cancelled = False
        self._events_recorded = 0

    def cancel(self, reason: str | None = None) -> "TraceCancellation":
        if reason is not None:
            self._reason = _text(reason, "reason")
        self._cancelled = True
        return self

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def events_recorded(self) -> int:
        return self._events_recorded

    @property
    def accepted_transition(self) -> bool:
        return False

    def bind_event_count(self, count: int) -> None:
        if type(count) is not int or isinstance(count, bool) or count < 0:
            raise PythonExecutionTraceError("events_recorded must be a nonnegative integer")
        self._events_recorded = count

    def to_dict(self) -> dict[str, Any]:
        return {
            "cancelled": self._cancelled,
            "reason": self._reason,
            "accepted_transition": False,
            "events_recorded": self._events_recorded,
        }


class TraceRedactor:
    """Bounded serializer that strips secrets and never claims full redacted state."""

    def __init__(self, policy: TraceCollectionPolicy) -> None:
        self._policy = policy

    def summarize(
        self,
        value: Any,
        *,
        depth: int = 0,
        redacted: set[str] | None = None,
        unavailable: set[str] | None = None,
        path: str = "value",
    ) -> Any:
        redacted = set() if redacted is None else redacted
        unavailable = set() if unavailable is None else unavailable
        if depth >= MAX_SUMMARY_DEPTH:
            unavailable.add(path)
            return {"unavailable": "depth_bound"}
        if value is None or type(value) is bool:
            return value
        if type(value) is int and not isinstance(value, bool):
            return _safe_int(value)
        if type(value) is str:
            text = unicodedata.normalize("NFC", value)
            if len(text) > MAX_SUMMARY_CHARS or any(not char.isprintable() for char in text):
                unavailable.add(path)
                return {"type": "str", "n": len(text), "unavailable": "payload_bound"}
            return text
        if isinstance(value, Mapping):
            items: dict[str, Any] = {}
            for index, (key, child) in enumerate(value.items()):
                if index >= MAX_SUMMARY_ITEMS:
                    unavailable.add(path)
                    break
                if type(key) is not str:
                    unavailable.add(path)
                    continue
                if _secret_key(key):
                    redacted.add("secrets")
                    continue
                items[key] = self.summarize(
                    child,
                    depth=depth + 1,
                    redacted=redacted,
                    unavailable=unavailable,
                    path=f"{path}.{key}",
                )
            return items
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            items_list: list[Any] = []
            for index, child in enumerate(value):
                if index >= MAX_SUMMARY_ITEMS:
                    unavailable.add(path)
                    break
                items_list.append(
                    self.summarize(
                        child,
                        depth=depth + 1,
                        redacted=redacted,
                        unavailable=unavailable,
                        path=f"{path}[{index}]",
                    )
                )
            return items_list
        unavailable.add(path)
        return {"type": type(value).__name__, "unavailable": "non_dag_json"}

    def locals_summary(
        self, frame: FrameType
    ) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
        if not self._policy.collect_locals:
            return {}, (), ("locals",)
        redacted: set[str] = set()
        unavailable: set[str] = set()
        raw = dict(frame.f_locals)
        summarized = self.summarize(
            raw, redacted=redacted, unavailable=unavailable, path="locals"
        )
        payload = {"locals": summarized}
        encoded = canonical_dag_json_bytes(payload)
        if len(encoded) > self._policy.max_state_summary_bytes:
            unavailable.add("locals_overflow")
            payload = {"locals": {"unavailable": "payload_bound"}}
        return payload, tuple(sorted(redacted)), tuple(sorted(unavailable))

    def bound_payload(
        self, payload: Mapping[str, Any]
    ) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
        redacted: set[str] = set()
        unavailable: set[str] = set()
        summarized = self.summarize(
            dict(payload), redacted=redacted, unavailable=unavailable, path="payload"
        )
        if not isinstance(summarized, dict):
            summarized = {"unavailable": "payload"}
            unavailable.add("payload")
        encoded = canonical_dag_json_bytes(summarized)
        if len(encoded) > self._policy.max_payload_bytes:
            unavailable.add("payload_bound")
            summarized = {"unavailable": "payload_bound"}
        return summarized, tuple(sorted(redacted)), tuple(sorted(unavailable))

    def public_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        public = trace.public_view()
        if public.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if public.privacy_class not in PUBLIC_PRIVACY_CLASSES:
            raise PythonExecutionTraceError("public traces must use a public privacy class")
        return public

    def public_state(self, state: ProgramExecutionState) -> ProgramExecutionState:
        public = public_execution_view(state)
        if public.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        return public


@dataclass(frozen=True, slots=True)
class HermeticTraceRecord:
    """Public hermetic trace plus a private raw channel that is never exported."""

    public_trace: ExecutionTrace
    events: tuple[ProgramEvent, ...]
    observations: tuple[ExecutionObservation, ...]
    public_states: tuple[ProgramExecutionState, ...]
    policy: TraceCollectionPolicy
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    capture_profile_cid: str
    outcome: str
    cancellation: TraceCancellation | None = None
    accepted_transition: bool = False
    exception_snapshot: ExceptionSnapshot | None = None
    _private_raw_trace: ExecutionTrace | None = field(default=None, repr=False, compare=False)
    _private_raw_bodies: Mapping[str, Any] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.accepted_transition:
            raise PythonExecutionTraceError(
                "hermetic tracing does not persist operational acceptance"
            )
        if self.cancellation is not None and self.cancellation.cancelled:
            object.__setattr__(self, "accepted_transition", False)
        if self.public_trace.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if self.public_trace.privacy_class not in PUBLIC_PRIVACY_CLASSES:
            raise PythonExecutionTraceError("public traces must use a public privacy class")
        object.__setattr__(
            self, "_private_raw_bodies", MappingProxyType(dict(self._private_raw_bodies))
        )

    @property
    def private_raw_trace(self) -> ExecutionTrace | None:
        return self._private_raw_trace

    @property
    def private_raw_bodies(self) -> Mapping[str, Any]:
        return self._private_raw_bodies

    def public_record(self) -> dict[str, Any]:
        """Return the public record; raw bodies and private traces are omitted."""

        record = {
            "schema": HERMETIC_PYTHON_EXECUTION_TRACE_SCHEMA,
            "interface": HERMETIC_PYTHON_EXECUTION_TRACE_INTERFACE,
            "accepted_transition": False,
            "transitions": [],
            "outcome": self.outcome,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "capture_profile_cid": self.capture_profile_cid,
            "public_trace": self.public_trace.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "observations": [item.to_dict() for item in self.observations],
            "public_states": [state.to_dict() for state in self.public_states],
            "cancellation": None if self.cancellation is None else self.cancellation.to_dict(),
            "policy": self.policy.identity_payload(),
        }
        if self.exception_snapshot is not None:
            record["exception_snapshot"] = self.exception_snapshot.to_dict()
        _assert_public_record(record)
        return record


def _contains_raw_body_marker(value: Any) -> bool:
    if isinstance(value, Mapping):
        if value.get("includes_raw_bodies") is True:
            return True
        if "raw_bodies" in value or "private_raw_trace" in value or "raw_body" in value:
            return True
        return any(_contains_raw_body_marker(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_raw_body_marker(item) for item in value)
    return False


def _assert_public_record(record: Mapping[str, Any]) -> None:
    if record.get("accepted_transition") is True:
        raise PythonExecutionTraceError("public records cannot carry accepted transitions")
    if record.get("transitions"):
        raise PythonExecutionTraceError("public records cannot carry accepted transitions")
    if _contains_raw_body_marker(record):
        raise PythonExecutionTraceError(
            "private raw trace bodies never enter public records"
        )
    encoded = canonical_dag_json_bytes(record)
    text = encoded.decode("utf-8")
    for marker in ("password", "api_key", "private_key", "secret="):
        if marker in text:
            raise PythonExecutionTraceError("public records reject secret material")


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class PythonExecutionTracer:
    """In-process ``sys.settrace`` collector with isolation and redaction."""

    def __init__(
        self,
        policy: TraceCollectionPolicy | None = None,
        cancellation: TraceCancellation | None = None,
    ) -> None:
        self._policy = policy if policy is not None else TraceCollectionPolicy()
        self._cancellation = cancellation if cancellation is not None else TraceCancellation(
            "idle"
        )
        self._redactor = TraceRedactor(self._policy)
        self._events: list[ProgramEvent] = []
        self._states: list[ProgramExecutionState] = []
        self._private_states: list[ProgramExecutionState] = []
        self._private_bodies: dict[str, Any] = {}
        self._line_events = 0
        self._recording = False
        self._entered = False
        self._target_code: CodeType | None = None
        self._target_codes: set[CodeType] = set()
        self._target_filename = ""
        self._target_name = ""
        self._source_cid = ""
        self._tree_cid = ""
        self._environment_binding_cid = ""
        self._previous_trace: Any = None
        self._pending_exception: dict[int, tuple[Any, Any, Any]] = {}
        self._last_exception: ExceptionSnapshot | None = None
        self._predecessor: str | None = None
        self._internal_codes = _collect_code_objects(self.__class__.handle_audit.__code__)
        for name in (
            "_global_trace",
            "_local_trace",
            "_handle",
            "_emit",
            "_stack_frames",
            "_build_event",
            "record",
        ):
            method = getattr(self, name, None)
            code = getattr(method, "__code__", None)
            if isinstance(code, CodeType):
                self._internal_codes |= _collect_code_objects(code)

    @property
    def policy(self) -> TraceCollectionPolicy:
        return self._policy

    @property
    def cancellation(self) -> TraceCancellation:
        return self._cancellation

    def record(
        self,
        target: Callable[..., Any],
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> HermeticTraceRecord:
        if not callable(target):
            raise PythonExecutionTraceError("target must be callable")
        code = _callable_code(target)
        self._target_code = code
        self._target_codes = _collect_code_objects(code)
        self._target_filename = code.co_filename
        self._target_name = _callable_name(target)
        source_text = _callable_source_text(target)
        self._source_cid = self._policy.source_cid or cid_for_bytes(
            source_text.encode("utf-8")
        )
        self._environment_binding_cid = (
            self._policy.environment_binding_cid or bind_python_environment()
        )
        self._tree_cid = self._policy.tree_cid or bind_python_tree(
            source_cid=self._source_cid, logical_name=self._target_name
        )
        call_kwargs = {} if kwargs is None else dict(kwargs)
        outcome = "returned"
        raised: BaseException | None = None
        _ensure_audit_hook()
        self._previous_trace = sys.gettrace()
        _THREAD.tracer = self
        try:
            sys.settrace(self._global_trace)
            try:
                result = target(*tuple(args), **call_kwargs)
                result = _drive_coroutine(result)
                del result
            except _TraceIsolationDenied as exc:
                outcome = "denied"
                raised = exc
                if not self._cancellation.cancelled:
                    self._cancellation.cancel(str(exc) or "isolation_denied")
            except BaseException as exc:
                if isinstance(exc, (SystemExit, KeyboardInterrupt, GeneratorExit)):
                    raise
                outcome = "raised"
                raised = exc
        finally:
            sys.settrace(self._previous_trace)
            _THREAD.tracer = None
            self._cancellation.bind_event_count(len(self._events))
        if not self._events:
            self._emit(
                EventKind.UNAVAILABLE.value,
                logical_name=self._target_name,
                payload={"reason": "no_events_recorded"},
                frame=None,
                observation_status=ObservationStatus.UNAVAILABLE.value,
                unavailable=("event_body",),
            )
        if self._cancellation.cancelled:
            outcome = "cancelled" if outcome == "returned" else outcome
        return self._seal(outcome=outcome, raised=raised)

    def handle_audit(self, event: str, args: tuple[Any, ...]) -> None:
        if self._recording or self._cancellation.cancelled:
            return
        denied_reason: str | None = None
        if self._policy.deny_network and event in DENIED_NETWORK_AUDIT_EVENTS:
            denied_reason = "network_denied"
        elif self._policy.deny_subprocess and event in DENIED_SUBPROCESS_AUDIT_EVENTS:
            denied_reason = "subprocess_denied"
        elif self._policy.deny_installer and event in DENIED_INSTALLER_AUDIT_EVENTS:
            denied_reason = "installer_denied"
        if denied_reason is None and event not in (
            DENIED_NETWORK_AUDIT_EVENTS
            | DENIED_SUBPROCESS_AUDIT_EVENTS
            | DENIED_INSTALLER_AUDIT_EVENTS
        ):
            return
        if not self._policy.admits(EventKind.EXTERNAL.value):
            if denied_reason is not None:
                self._cancellation.cancel(denied_reason)
                raise _TraceIsolationDenied(denied_reason)
            return
        self._emit(
            EventKind.EXTERNAL.value,
            logical_name=self._target_name,
            payload={
                "audit_event": event,
                "denied": denied_reason is not None,
            },
            frame=None,
            observation_status=(
                ObservationStatus.UNAVAILABLE.value
                if denied_reason is not None
                else ObservationStatus.OBSERVED.value
            ),
            unavailable=("external_effect",) if denied_reason is not None else (),
        )
        if denied_reason is not None:
            self._cancellation.cancel(denied_reason)
            raise _TraceIsolationDenied(denied_reason)

    def _in_scope(self, frame: FrameType) -> bool:
        code = frame.f_code
        if code in self._internal_codes:
            return False
        if self._policy.scope == SCOPE_TARGET_ONLY:
            return code in self._target_codes
        if self._policy.scope == SCOPE_NESTED:
            current: FrameType | None = frame
            while current is not None:
                if current.f_code in self._target_codes:
                    return True
                current = current.f_back
            return False
        return code.co_filename == self._target_filename or code in self._target_codes

    def _global_trace(self, frame: FrameType, event: str, arg: Any) -> Any:
        if self._recording or self._cancellation.cancelled:
            return self._previous_trace
        if event == "call" and self._in_scope(frame):
            self._handle(frame, event, arg)
            return self._local_trace
        if self._previous_trace is not None:
            return self._previous_trace(frame, event, arg)
        return None

    def _local_trace(self, frame: FrameType, event: str, arg: Any) -> Any:
        if self._cancellation.cancelled:
            return None
        if not self._in_scope(frame):
            return None
        self._handle(frame, event, arg)
        if self._cancellation.cancelled:
            return None
        return self._local_trace

    def _handle(self, frame: FrameType, event: str, arg: Any) -> None:
        if self._recording or self._cancellation.cancelled:
            return
        kind: str | None = None
        payload: dict[str, Any] = {}
        observation_status = ObservationStatus.OBSERVED.value
        unavailable: tuple[str, ...] = ()
        exception_arg = None
        if event == "call":
            flags = frame.f_code.co_flags
            opname = _opname_at(frame)
            if flags & GENERATOR_FLAGS and self._entered and opname in YIELD_OPNAMES:
                kind = EventKind.YIELD.value
                payload = {"phase": "resume"}
            elif flags & COROUTINE_FLAGS and opname in AWAIT_OPNAMES:
                kind = EventKind.AWAIT.value
                payload = {"phase": "resume"}
            elif not self._entered and frame.f_code is self._target_code:
                self._entered = True
                if self._policy.admits(EventKind.ENTER.value):
                    self._emit(
                        EventKind.ENTER.value,
                        logical_name=self._logical_name(frame),
                        payload={"phase": "enter"},
                        frame=frame,
                    )
                kind = EventKind.CALL.value
            else:
                kind = EventKind.CALL.value
            payload.setdefault("callee", self._logical_name(frame))
        elif event == "line":
            frame_id = id(frame)
            if frame_id in self._pending_exception:
                exception_arg = self._pending_exception.pop(frame_id)
                if self._policy.admits(EventKind.HANDLER.value):
                    self._emit(
                        EventKind.HANDLER.value,
                        logical_name=self._logical_name(frame),
                        payload={"handler_kind": HandlerKind.EXCEPT.value},
                        frame=frame,
                        exception_arg=exception_arg,
                    )
                if self._policy.admits(EventKind.CATCH.value):
                    self._emit(
                        EventKind.CATCH.value,
                        logical_name=self._logical_name(frame),
                        payload={"handler_kind": HandlerKind.EXCEPT.value},
                        frame=frame,
                        exception_arg=exception_arg,
                    )
            if not self._policy.collect_line_events or not self._policy.admits(
                EventKind.LINE.value
            ):
                return
            if self._line_events >= self._policy.max_line_events:
                return
            kind = EventKind.LINE.value
            payload = {"line": frame.f_lineno}
        elif event == "return":
            flags = frame.f_code.co_flags
            opname = _opname_at(frame)
            if flags & GENERATOR_FLAGS and opname in YIELD_OPNAMES:
                kind = EventKind.YIELD.value
                payload = {"phase": "yield"}
            elif flags & COROUTINE_FLAGS and opname in AWAIT_OPNAMES:
                kind = EventKind.AWAIT.value
                payload = {"phase": "await"}
            elif frame.f_code is self._target_code:
                kind = EventKind.RETURN.value
                payload = {"has_value": arg is not None}
                if self._policy.admits(EventKind.RETURN.value):
                    self._emit(
                        kind,
                        logical_name=self._logical_name(frame),
                        payload=payload,
                        frame=frame,
                    )
                if self._policy.admits(EventKind.EXIT.value):
                    self._emit(
                        EventKind.EXIT.value,
                        logical_name=self._logical_name(frame),
                        payload={"phase": "exit"},
                        frame=frame,
                    )
                return
            else:
                kind = EventKind.RETURN.value
                payload = {"has_value": arg is not None}
        elif event == "exception":
            kind = EventKind.RAISE.value
            exception_arg = arg
            self._pending_exception[id(frame)] = arg
            exc_type = arg[0] if isinstance(arg, tuple) and arg else type(None)
            payload = {
                "exception_type": getattr(exc_type, "__name__", "Exception"),
            }
        else:
            return
        if kind is None or not self._policy.admits(kind):
            return
        if kind == EventKind.LINE.value:
            self._line_events += 1
        self._emit(
            kind,
            logical_name=self._logical_name(frame),
            payload=payload,
            frame=frame,
            observation_status=observation_status,
            unavailable=unavailable,
            exception_arg=exception_arg,
        )

    def _logical_name(self, frame: FrameType) -> str:
        qualname = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
        return unicodedata.normalize("NFC", qualname)

    def _emit(
        self,
        kind: str,
        *,
        logical_name: str,
        payload: Mapping[str, Any],
        frame: FrameType | None,
        observation_status: str = ObservationStatus.OBSERVED.value,
        unavailable: Sequence[str] = (),
        exception_arg: Any = None,
    ) -> None:
        if self._cancellation.cancelled:
            return
        if len(self._events) >= self._policy.max_events:
            self._cancellation.cancel("event_bound")
            return
        self._recording = True
        try:
            event = self._build_event(
                kind,
                logical_name=logical_name,
                payload=payload,
                frame=frame,
                observation_status=observation_status,
                unavailable=unavailable,
                exception_arg=exception_arg,
            )
            self._events.append(event)
            self._predecessor = event.program_event_cid
            self._cancellation.bind_event_count(len(self._events))
        finally:
            self._recording = False

    def _stack_frames(
        self, frame: FrameType | None
    ) -> tuple[tuple[StackFrameState, ...], dict[str, Any], tuple[str, ...], tuple[str, ...]]:
        if frame is None:
            return (), {}, (), ("call_stack",)
        frames: list[StackFrameState] = []
        raw_locals: dict[str, Any] = {}
        redacted: set[str] = set()
        unavailable: set[str] = set()
        current: FrameType | None = frame
        ordinal = 0
        while current is not None and ordinal < self._policy.max_stack_frames:
            if not self._in_scope(current) and current is not frame:
                current = current.f_back
                continue
            summary, frame_redacted, frame_unavailable = self._redactor.locals_summary(
                current
            )
            redacted.update(frame_redacted)
            unavailable.update(frame_unavailable)
            if ordinal == 0:
                raw_locals = dict(current.f_locals)
            logical_name = self._logical_name(current)
            code_cid = bind_python_code(
                current, source_cid=self._source_cid, logical_name=logical_name
            )
            claim = CompletenessClaim.FULL_STATE
            if frame_redacted:
                claim = CompletenessClaim.REDACTED
            elif frame_unavailable:
                claim = CompletenessClaim.PARTIAL
            frames.append(
                StackFrameState(
                    ordinal=ordinal,
                    language=ProgramLanguage.PYTHON,
                    tree_cid=self._tree_cid,
                    source_cid=self._source_cid,
                    code_cid=code_cid,
                    environment_binding_cid=self._environment_binding_cid,
                    logical_name=logical_name,
                    line=current.f_lineno,
                    column=None,
                    state_summary=summary,
                    exception_snapshot_cid=None,
                    handler_state_cid=None,
                    exception_active=False,
                    handler_active=False,
                    redacted_dimensions=frame_redacted,
                    unavailable_dimensions=frame_unavailable,
                    completeness_claim=claim,
                    privacy_class=PrivacyClass.INTERNAL,
                )
            )
            ordinal += 1
            current = current.f_back
        if not frames:
            unavailable.add("call_stack")
        return tuple(frames), raw_locals, tuple(sorted(redacted)), tuple(sorted(unavailable))

    def _exception_snapshot(
        self,
        exception_arg: Any,
        frames: Sequence[StackFrameState],
    ) -> ExceptionSnapshot | None:
        if not isinstance(exception_arg, tuple) or not exception_arg:
            return self._last_exception
        exc_type = exception_arg[0]
        name = getattr(exc_type, "__name__", "Exception")
        summary, redacted, unavailable = self._redactor.bound_payload(
            {"exception_type": name, "bounded": True}
        )
        if redacted:
            summary = {"exception_type": name, "bounded": True}
        snapshot = ExceptionSnapshot(
            language=ProgramLanguage.PYTHON,
            exception_type=name,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=frames[0].code_cid if frames else cid_for_bytes(name.encode("utf-8")),
            environment_binding_cid=self._environment_binding_cid,
            exception_value_summary=summary,
            traceback_stack_frame_cids=tuple(frame.stack_frame_state_cid for frame in frames),
            raised_at_event_cid=None,
            handler_state_cid=None,
            future_execution=False,
            unavailable_dimensions=unavailable,
            completeness_claim=(
                CompletenessClaim.PARTIAL if unavailable else CompletenessClaim.FULL_STATE
            ),
        )
        self._last_exception = snapshot
        return snapshot

    def _handler_state(
        self,
        frames: Sequence[StackFrameState],
        exception: ExceptionSnapshot | None,
        logical_name: str,
    ) -> HandlerState | None:
        if not frames:
            return None
        matching = None if exception is None else exception.exception_snapshot_cid
        unavailable: tuple[str, ...] = ()
        if matching is None:
            unavailable = ("exception",)
        return HandlerState(
            language=ProgramLanguage.PYTHON,
            handler_kind=HandlerKind.EXCEPT,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=frames[0].code_cid,
            environment_binding_cid=self._environment_binding_cid,
            logical_name=logical_name,
            stack_ordinal=frames[0].ordinal,
            handler_active=True,
            matching_exception_snapshot_cid=matching,
            unavailable_dimensions=unavailable,
        )

    def _build_event(
        self,
        kind: str,
        *,
        logical_name: str,
        payload: Mapping[str, Any],
        frame: FrameType | None,
        observation_status: str,
        unavailable: Sequence[str],
        exception_arg: Any,
    ) -> ProgramEvent:
        frames, raw_locals, redacted, frame_unavailable = self._stack_frames(frame)
        unavailable_dims = set(unavailable) | set(frame_unavailable)
        payload_body, payload_redacted, payload_unavailable = self._redactor.bound_payload(
            payload
        )
        redacted_dims = set(redacted) | set(payload_redacted)
        unavailable_dims.update(payload_unavailable)
        if self._line_events >= self._policy.max_line_events and kind != EventKind.LINE.value:
            unavailable_dims.add("line_events")
        exception = None
        handler = None
        if kind == EventKind.RAISE.value:
            exception = self._exception_snapshot(exception_arg, frames)
        elif kind in {EventKind.CATCH.value, EventKind.HANDLER.value}:
            exception = self._exception_snapshot(exception_arg, frames) or self._last_exception
            handler = self._handler_state(frames, exception, logical_name)
        if kind in {EventKind.CALL.value, EventKind.RETURN.value, EventKind.LINE.value}:
            if frames:
                self._remember_state(frames, raw_locals, redacted_dims, unavailable_dims)
        claim = CompletenessClaim.FULL_STATE
        if redacted_dims:
            claim = CompletenessClaim.REDACTED
        elif unavailable_dims:
            claim = CompletenessClaim.PARTIAL
        if observation_status == ObservationStatus.UNAVAILABLE.value:
            claim = CompletenessClaim.UNAVAILABLE
            if not unavailable_dims:
                unavailable_dims.add("event_body")
        code_cid = (
            frames[0].code_cid
            if frames
            else bind_python_code(
                self._target_code or _callable_code(self.record),
                source_cid=self._source_cid,
                logical_name=logical_name,
            )
            if self._target_code is not None
            else cid_for_bytes(logical_name.encode("utf-8"))
        )
        line = frames[0].line if frames else None
        if line is None and kind not in {EventKind.EXTERNAL.value, EventKind.UNAVAILABLE.value}:
            unavailable_dims.add("source_location")
        return ProgramEvent(
            event_kind=kind,
            event_origin=EventOrigin.OBSERVED,
            observation_status=observation_status,
            language=ProgramLanguage.PYTHON,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=code_cid,
            environment_binding_cid=self._environment_binding_cid,
            subject_cid=code_cid,
            logical_name=logical_name,
            payload=payload_body,
            line=line,
            column=None,
            predecessor_event_cid=self._predecessor,
            stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
            exception_snapshot_cid=None if exception is None else exception.exception_snapshot_cid,
            handler_state_cid=None if handler is None else handler.handler_state_cid,
            redaction_profile_cid=None,
            redacted_dimensions=tuple(sorted(redacted_dims)),
            unavailable_dimensions=tuple(sorted(unavailable_dims)),
            completeness_claim=claim,
            privacy_class=PrivacyClass.INTERNAL,
        )

    def _remember_state(
        self,
        frames: Sequence[StackFrameState],
        raw_locals: Mapping[str, Any],
        redacted: set[str],
        unavailable: set[str],
    ) -> None:
        unavailable_dims = set(unavailable)
        unavailable_dims.add("heap")
        redacted_dims = set(redacted)
        public_summary = frames[0].state_summary if frames else {}
        claim = CompletenessClaim.PARTIAL
        if redacted_dims:
            claim = CompletenessClaim.REDACTED
        public_state = assemble_program_execution_state(
            language=ProgramLanguage.PYTHON,
            capture_profile_cid=self._policy.capture_profile_cid,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self._environment_binding_cid,
            frames=frames,
            observed_state=public_summary,
            heap_summary={},
            heap_bound=HeapBound.UNAVAILABLE,
            observation_status=ObservationStatus.OBSERVED,
            completeness_claim=claim,
            privacy_class=PrivacyClass.INTERNAL,
            includes_raw_bodies=False,
            unavailable_dimensions=tuple(sorted(unavailable_dims)),
        )
        self._states.append(public_state)
        if self._policy.include_raw_bodies_privately:
            private_observed, _, _ = self._redactor.bound_payload({"locals": dict(raw_locals)})
            private_state = assemble_program_execution_state(
                language=ProgramLanguage.PYTHON,
                capture_profile_cid=self._policy.capture_profile_cid,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                environment_binding_cid=self._environment_binding_cid,
                frames=frames,
                observed_state=private_observed,
                heap_summary={},
                heap_bound=HeapBound.UNAVAILABLE,
                observation_status=ObservationStatus.OBSERVED,
                completeness_claim=CompletenessClaim.PARTIAL,
                privacy_class=PrivacyClass.PRIVATE,
                includes_raw_bodies=True,
                unavailable_dimensions=tuple(sorted(unavailable_dims)),
            )
            self._private_states.append(private_state)
            self._private_bodies[private_state.program_execution_state_cid] = private_observed

    def _seal(
        self, *, outcome: str, raised: BaseException | None
    ) -> HermeticTraceRecord:
        redacted: set[str] = set()
        unavailable: set[str] = {"heap"}
        for event in self._events:
            redacted.update(event.redacted_dimensions)
            unavailable.update(event.unavailable_dimensions)
        if self._line_events >= self._policy.max_line_events:
            unavailable.add("line_events")
        if self._cancellation.cancelled:
            unavailable.add("remaining_events")
        claim = CompletenessClaim.PARTIAL
        if redacted:
            claim = CompletenessClaim.REDACTED
        redaction = self._policy.redaction_profile(
            redacted=tuple(redacted), unavailable=tuple(unavailable)
        )
        public_states = tuple(
            self._redactor.public_state(state) for state in self._states[:8]
        )
        public_events = tuple(self._events)
        public_trace = assemble_execution_trace(
            language=ProgramLanguage.PYTHON,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self._environment_binding_cid,
            events=public_events,
            states=public_states,
            redaction=redaction,
            completeness_claim=claim,
            privacy_class=PrivacyClass.PUBLIC,
            includes_raw_bodies=False,
            unavailable_dimensions=tuple(sorted(unavailable)),
        )
        public_trace = self._redactor.public_trace(public_trace)
        private_trace = None
        if self._policy.include_raw_bodies_privately and self._private_states:
            private_trace = assemble_execution_trace(
                language=ProgramLanguage.PYTHON,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                environment_binding_cid=self._environment_binding_cid,
                events=public_events,
                states=self._private_states[:8],
                redaction=redaction,
                completeness_claim=CompletenessClaim.REDACTED
                if redacted
                else CompletenessClaim.PARTIAL,
                privacy_class=PrivacyClass.PRIVATE,
                includes_raw_bodies=True,
                unavailable_dimensions=tuple(sorted(unavailable | {"raw_body"})),
            )
        observations: list[ExecutionObservation] = []
        for event in public_events:
            if event.observation_admissible:
                observations.append(observe_program_event(event))
        cancellation = self._cancellation if self._cancellation.cancelled else None
        if cancellation is not None:
            cancellation.bind_event_count(len(public_events))
        exception_snapshot = self._last_exception
        if raised is not None and exception_snapshot is None:
            exception_snapshot = ExceptionSnapshot(
                language=ProgramLanguage.PYTHON,
                exception_type=type(raised).__name__,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                code_cid=cid_for_bytes(self._target_name.encode("utf-8")),
                environment_binding_cid=self._environment_binding_cid,
                exception_value_summary={"exception_type": type(raised).__name__, "bounded": True},
                traceback_stack_frame_cids=(),
                future_execution=False,
                unavailable_dimensions=("call_stack",),
                completeness_claim=CompletenessClaim.PARTIAL,
            )
        return HermeticTraceRecord(
            public_trace=public_trace,
            events=public_events,
            observations=tuple(observations),
            public_states=public_states,
            policy=self._policy,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self._environment_binding_cid,
            capture_profile_cid=self._policy.capture_profile_cid,
            outcome=outcome,
            cancellation=cancellation,
            accepted_transition=False,
            exception_snapshot=exception_snapshot,
            _private_raw_trace=private_trace,
            _private_raw_bodies=self._private_bodies,
        )


def record_python_execution_trace(
    target: Callable[..., Any],
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    *,
    policy: TraceCollectionPolicy | None = None,
    cancellation: TraceCancellation | None = None,
) -> HermeticTraceRecord:
    """Collect a hermetic in-process Python execution trace for ``target``."""

    tracer = PythonExecutionTracer(policy=policy, cancellation=cancellation)
    return tracer.record(target, args=args, kwargs=kwargs)


def replay_deterministic_trace(
    record: HermeticTraceRecord | Mapping[str, Any],
    *,
    target: Callable[..., Any] | None = None,
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    policy: TraceCollectionPolicy | None = None,
) -> HermeticTraceRecord:
    """Replay a promised deterministic trace by identity or hermetic re-execution.

    Re-execution is in-process only.  Nondeterministic external effects remain
    explicit observations or unavailable and never upgrade into acceptance.
    """

    original = _coerce_record(record)
    if original.accepted_transition:
        raise PythonExecutionTraceError("replay refuses traces that claim acceptance")
    if target is not None:
        replayed = record_python_execution_trace(
            target,
            args=args,
            kwargs=kwargs,
            policy=policy or original.policy,
        )
        if replayed.accepted_transition:
            raise PythonExecutionTraceError("replay cannot emit accepted transitions")
        if replayed.cancellation is not None and replayed.cancellation.cancelled:
            if replayed.cancellation.accepted_transition:
                raise PythonExecutionTraceError("cancelled replay emitted acceptance")
        if replayed.public_trace.execution_trace_cid != original.public_trace.execution_trace_cid:
            raise PythonExecutionTraceError("deterministic promised replay diverged")
        if replayed.tree_cid != original.tree_cid:
            raise PythonExecutionTraceError("replay tree binding diverged")
        if replayed.environment_binding_cid != original.environment_binding_cid:
            raise PythonExecutionTraceError("replay environment binding diverged")
        return replayed
    rebuilt = assemble_execution_trace(
        language=ProgramLanguage.PYTHON,
        tree_cid=original.tree_cid,
        source_cid=original.source_cid,
        environment_binding_cid=original.environment_binding_cid,
        events=original.events,
        states=original.public_states,
        completeness_claim=original.public_trace.completeness_claim,
        privacy_class=PrivacyClass.PUBLIC,
        includes_raw_bodies=False,
        unavailable_dimensions=original.public_trace.unavailable_dimensions,
        redaction=RedactionProfile(
            privacy_class=PrivacyClass.PUBLIC,
            redacted_dimensions=original.public_trace.redacted_dimensions,
            unavailable_dimensions=original.public_trace.unavailable_dimensions,
            completeness_claim=original.public_trace.completeness_claim,
        )
        if original.public_trace.redacted_dimensions
        or original.public_trace.unavailable_dimensions
        else None,
    )
    public = rebuilt.public_view()
    if public.execution_trace_cid != original.public_trace.execution_trace_cid:
        raise PythonExecutionTraceError("promised identity replay diverged")
    if public.includes_raw_bodies:
        raise PythonExecutionTraceError(
            "private raw trace bodies never enter public records"
        )
    return original


def _coerce_record(record: HermeticTraceRecord | Mapping[str, Any]) -> HermeticTraceRecord:
    if isinstance(record, HermeticTraceRecord):
        return record
    if not isinstance(record, Mapping):
        raise PythonExecutionTraceError("replay requires a HermeticTraceRecord or public mapping")
    if record.get("accepted_transition") is True:
        raise PythonExecutionTraceError("replay refuses traces that claim acceptance")
    if record.get("includes_raw_bodies") is True or "private_raw_trace" in record:
        raise PythonExecutionTraceError(
            "private raw trace bodies never enter public records"
        )
    raise PythonExecutionTraceError(
        "promised replay from a mapping requires the original HermeticTraceRecord "
        "or a re-executable target"
    )


__all__ = [
    "ADMITTED_TRACE_EVENT_KINDS",
    "DEFAULT_TRACE_EVENT_KINDS",
    "HERMETIC_PYTHON_EXECUTION_TRACE_INTERFACE",
    "HERMETIC_PYTHON_EXECUTION_TRACE_SCHEMA",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_COLLECTION_POLICY_SCHEMA",
    "HermeticTraceRecord",
    "PythonExecutionTraceError",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCollectionPolicy",
    "TraceRedactor",
    "bind_python_code",
    "bind_python_environment",
    "bind_python_tree",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
