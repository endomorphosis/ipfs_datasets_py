"""Hermetic Python execution tracing bound to SAWM-007 execution contracts.

This module is the datasets collection authority for SAWM-008.  It records
admitted call/return/line/exception/handler/yield/await/selected-external
events as ``ProgramEvent@1`` / ``ExecutionTrace@1`` values with exact
tree/source/code/environment identity, bounded state summaries, cancellation,
and redaction.

Normative constraints:

* Importing this module never opens a network or socket, starts an installer,
  subprocess, database, repository scan, watcher, or model load.
* Collection binds exact source bytes and environment identities.
* Cancellation emits no accepted transition.  Tracing never persists
  operational acceptance.
* Private raw trace bodies never enter public records.
* Line and basic-block detail is policy/cost bounded.
* Nondeterministic external effects remain explicit observations or
  unavailable; they are never treated as absence.
* Shell tracing is not provided.  Unsupported languages remain typed
  unavailable at the SAWM-007 contract boundary.
"""

from __future__ import annotations

import inspect
import os
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
from types import CodeType, FrameType, MappingProxyType
from typing import Any, ClassVar, Final

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
    ProgramLanguage,
    RedactionProfile,
    SECRET_FIELD_MARKERS,
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
PYTHON_EXECUTION_TRACE_RECEIPT_INTERFACE: Final[str] = (
    "PythonExecutionTraceReceipt@1"
)
PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE: Final[str] = (
    "PythonExecutionReplayReceipt@1"
)
PYTHON_EXECUTION_TRACER_VERSION: Final[str] = "1"

PYTHON_EXECUTION_TRACE_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-trace-receipt@1"
)
PYTHON_EXECUTION_REPLAY_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-replay-receipt@1"
)
PYTHON_EXECUTION_CAPTURE_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-capture-profile@1"
)
PYTHON_EXECUTION_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-environment@1"
)
PYTHON_EXECUTION_CODE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-code@1"
)
PYTHON_EXECUTION_TREE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-tree@1"
)
PYTHON_EXECUTION_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-subject@1"
)
PYTHON_EXECUTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-policy@1"
)

ADMITTED_LANGUAGE: Final[str] = ProgramLanguage.PYTHON.value
IMPORT_SIDE_EFFECTS_PERFORMED: Final[bool] = False
IMPORT_NETWORK_LOADED: Final[bool] = False
IMPORT_SOCKET_CONNECTED: Final[bool] = False
IMPORT_INSTALLER_STARTED: Final[bool] = False
IMPORT_SUBPROCESS_STARTED: Final[bool] = False
IMPORT_DATABASE_OPENED: Final[bool] = False
IMPORT_REPO_SCAN_PERFORMED: Final[bool] = False
IMPORT_WATCHER_STARTED: Final[bool] = False
IMPORT_MODEL_LOADED: Final[bool] = False

DEFAULT_EVENT_KINDS: Final[tuple[str, ...]] = (
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
DEFAULT_UNAVAILABLE_DIMENSIONS: Final[tuple[str, ...]] = (
    "heap",
    "raw_memory",
    "native_stack",
)
DEFAULT_MAX_EVENTS: Final[int] = 256
DEFAULT_MAX_LINE_EVENTS: Final[int] = 64
DEFAULT_MAX_STACK_FRAMES: Final[int] = 32
DEFAULT_MAX_LOCAL_ITEMS: Final[int] = 16
DEFAULT_MAX_LOCAL_CHARS: Final[int] = 256
DEFAULT_MAX_PAYLOAD_BYTES: Final[int] = 4_096
DEFAULT_MAX_DEPTH: Final[int] = 4

_TRACER_FILE: Final[str] = __file__
_CO_GENERATOR: Final[int] = inspect.CO_GENERATOR
_CO_COROUTINE: Final[int] = inspect.CO_COROUTINE
_CO_ASYNC_GENERATOR: Final[int] = inspect.CO_ASYNC_GENERATOR
_CO_ITERABLE_COROUTINE: Final[int] = getattr(inspect, "CO_ITERABLE_COROUTINE", 0x100)

_SECRET_MARKERS: Final[frozenset[str]] = frozenset(
    marker.lower().replace("-", "_") for marker in SECRET_FIELD_MARKERS
)
_FORBIDDEN_MARKERS: Final[frozenset[str]] = frozenset(
    marker.lower().replace("-", "_") for marker in FORBIDDEN_FIELD_MARKERS
)
_EXTERNAL_EFFECTS: Final[frozenset[str]] = frozenset(
    {
        "socket.connect",
        "socket.connect_ex",
        "socket.create_connection",
        "socket.getaddrinfo",
        "subprocess.Popen",
        "os.system",
    }
)

_RECEIPT_STATUSES: Final[frozenset[str]] = frozenset(
    {"recorded", "cancelled", "truncated", "target_failed", "unavailable"}
)


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic Python tracing inputs or results are unsound."""


class TraceStatus(StrEnum):
    RECORDED = "recorded"
    CANCELLED = "cancelled"
    TRUNCATED = "truncated"
    TARGET_FAILED = "target_failed"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Text / CID helpers
# ---------------------------------------------------------------------------


def _nfc(value: object, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise PythonExecutionTraceError(f"{name} must be a nonempty string")
    normalized = unicodedata.normalize("NFC", value)
    if normalized != normalized.strip():
        raise PythonExecutionTraceError(f"{name} must be trimmed NFC text")
    if len(normalized) > MAX_TEXT_CHARS or any(
        not char.isprintable() for char in normalized
    ):
        raise PythonExecutionTraceError(f"{name} contains invalid text")
    return normalized


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise PythonExecutionTraceError(f"{name} must be a boolean")
    return value


def _positive_int(value: object, name: str, *, upper: int | None = None) -> int:
    if type(value) is not int or isinstance(value, bool) or value <= 0:
        raise PythonExecutionTraceError(f"{name} must be a positive integer")
    if value > MAX_SAFE_INTEGER:
        raise PythonExecutionTraceError(f"{name} exceeds the safe JSON integer range")
    if upper is not None and value > upper:
        raise PythonExecutionTraceError(f"{name} exceeds its bound {upper}")
    return value


def _cid(value: object, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise PythonExecutionTraceError(f"{name} must be a valid CID") from exc


def _basename(path: str) -> str:
    if not path:
        return "unknown.py"
    return PurePosixPath(path.replace("\\", "/")).name or "unknown.py"


def _logical_name(frame: FrameType) -> str:
    module = frame.f_globals.get("__name__")
    if type(module) is not str or not module:
        module = "unknown"
    qualname = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
    if type(qualname) is not str or not qualname:
        qualname = frame.f_code.co_name or "unknown"
    name = f"{module}.{qualname}"
    normalized = unicodedata.normalize("NFC", name).strip()
    if len(normalized) > MAX_TEXT_CHARS:
        normalized = normalized[:MAX_TEXT_CHARS]
    return "".join(char for char in normalized if char.isprintable()) or "unknown"


def default_environment_binding() -> dict[str, str]:
    """Exact interpreter identity without host, pid, or wall-clock fields."""

    version = sys.version_info
    return {
        "implementation": sys.implementation.name,
        "language": ADMITTED_LANGUAGE,
        "python_major": str(version.major),
        "python_micro": str(version.micro),
        "python_minor": str(version.minor),
    }


def environment_binding_cid(bindings: Mapping[str, str] | None = None) -> str:
    items: list[dict[str, str]] = []
    payload = default_environment_binding() if bindings is None else bindings
    if not isinstance(payload, Mapping):
        raise PythonExecutionTraceError("environment_binding must be a string mapping")
    for key, value in payload.items():
        items.append(
            {
                "key": _nfc(str(key), "environment key"),
                "value": _nfc(str(value), "environment value"),
            }
        )
    items.sort(key=lambda item: (item["key"], item["value"]))
    return cid_for_structured(
        {"bindings": items, "schema": PYTHON_EXECUTION_ENVIRONMENT_SCHEMA}
    )


def _callable_code(target: Callable[..., Any]) -> CodeType:
    code = getattr(target, "__code__", None)
    if isinstance(code, CodeType):
        return code
    func = getattr(target, "__func__", None)
    code = getattr(func, "__code__", None)
    if isinstance(code, CodeType):
        return code
    raise PythonExecutionTraceError("target must be a Python function or method")


def _callable_source(target: Callable[..., Any]) -> tuple[str, str]:
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError):
        code = _callable_code(target)
        source = (
            f"# unavailable-source {code.co_name}:{code.co_firstlineno}\n"
            "pass\n"
        )
    normalized = unicodedata.normalize("NFC", source)
    return normalized, cid_for_bytes(normalized.encode("utf-8"))


def _code_cid(frame: FrameType, *, logical_name: str) -> str:
    code = frame.f_code
    return cid_for_structured(
        {
            "bytecode_cid": cid_for_bytes(code.co_code),
            "firstlineno": code.co_firstlineno,
            "logical_name": logical_name,
            "schema": PYTHON_EXECUTION_CODE_SCHEMA,
        }
    )


def _subject_cid(*, logical_name: str, code_cid: str) -> str:
    return cid_for_structured(
        {
            "code_cid": code_cid,
            "logical_name": logical_name,
            "schema": PYTHON_EXECUTION_SUBJECT_SCHEMA,
        }
    )


def _tree_cid(*, source_cid: str, logical_name: str) -> str:
    return cid_for_structured(
        {
            "language": ADMITTED_LANGUAGE,
            "logical_name": logical_name,
            "schema": PYTHON_EXECUTION_TREE_SCHEMA,
            "source_cid": source_cid,
        }
    )


def _normalize_key(key: str) -> str:
    return unicodedata.normalize("NFC", key).strip().lower().replace("-", "_")


def _is_forbidden_key(key: str) -> bool:
    lowered = _normalize_key(key)
    if lowered in _FORBIDDEN_MARKERS:
        return True
    return any(
        lowered.endswith(f"_{marker}") or lowered.endswith(marker)
        for marker in _FORBIDDEN_MARKERS
    )


def _is_secret_key(key: str) -> bool:
    lowered = _normalize_key(key)
    if lowered in _SECRET_MARKERS:
        return True
    return any(
        lowered.endswith(f"_{marker}") or lowered.endswith(marker)
        for marker in _SECRET_MARKERS
    )


# ---------------------------------------------------------------------------
# Policy, redactor, cancellation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Cost, isolation, and event-kind bounds for one recording."""

    event_kinds: tuple[str, ...] = DEFAULT_EVENT_KINDS
    collect_lines: bool = True
    collect_locals: bool = True
    collect_external: bool = True
    deny_network: bool = True
    deny_subprocess: bool = True
    deny_installer: bool = True
    include_raw_bodies: bool = False
    max_events: int = DEFAULT_MAX_EVENTS
    max_line_events: int = DEFAULT_MAX_LINE_EVENTS
    max_stack_frames: int = DEFAULT_MAX_STACK_FRAMES
    max_local_items: int = DEFAULT_MAX_LOCAL_ITEMS
    max_local_chars: int = DEFAULT_MAX_LOCAL_CHARS
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
    max_depth: int = DEFAULT_MAX_DEPTH

    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE
    SCHEMA: ClassVar[str] = PYTHON_EXECUTION_POLICY_SCHEMA

    def __post_init__(self) -> None:
        kinds = tuple(
            EventKind(item).value if not isinstance(item, EventKind) else item.value
            for item in self.event_kinds
        )
        if not kinds:
            raise PythonExecutionTraceError("event_kinds must not be empty")
        if len(kinds) != len(set(kinds)):
            raise PythonExecutionTraceError("event_kinds must not contain duplicates")
        try:
            ordered = tuple(sorted(kinds))
        except TypeError as exc:
            raise PythonExecutionTraceError("event_kinds must be EventKind values") from exc
        object.__setattr__(self, "event_kinds", ordered)
        object.__setattr__(self, "collect_lines", _bool(self.collect_lines, "collect_lines"))
        object.__setattr__(self, "collect_locals", _bool(self.collect_locals, "collect_locals"))
        object.__setattr__(
            self, "collect_external", _bool(self.collect_external, "collect_external")
        )
        object.__setattr__(self, "deny_network", _bool(self.deny_network, "deny_network"))
        object.__setattr__(
            self, "deny_subprocess", _bool(self.deny_subprocess, "deny_subprocess")
        )
        object.__setattr__(
            self, "deny_installer", _bool(self.deny_installer, "deny_installer")
        )
        object.__setattr__(
            self, "include_raw_bodies", _bool(self.include_raw_bodies, "include_raw_bodies")
        )
        object.__setattr__(
            self, "max_events", _positive_int(self.max_events, "max_events")
        )
        object.__setattr__(
            self,
            "max_line_events",
            _positive_int(self.max_line_events, "max_line_events"),
        )
        object.__setattr__(
            self,
            "max_stack_frames",
            _positive_int(self.max_stack_frames, "max_stack_frames"),
        )
        object.__setattr__(
            self,
            "max_local_items",
            _positive_int(self.max_local_items, "max_local_items"),
        )
        object.__setattr__(
            self,
            "max_local_chars",
            _positive_int(self.max_local_chars, "max_local_chars", upper=MAX_TEXT_CHARS),
        )
        object.__setattr__(
            self,
            "max_payload_bytes",
            _positive_int(
                self.max_payload_bytes,
                "max_payload_bytes",
                upper=MAX_METADATA_BYTES,
            ),
        )
        object.__setattr__(
            self, "max_depth", _positive_int(self.max_depth, "max_depth", upper=16)
        )

    def admits(self, kind: str) -> bool:
        return kind in self.event_kinds

    def identity_payload(self) -> dict[str, Any]:
        return {
            "collect_external": self.collect_external,
            "collect_lines": self.collect_lines,
            "collect_locals": self.collect_locals,
            "deny_installer": self.deny_installer,
            "deny_network": self.deny_network,
            "deny_subprocess": self.deny_subprocess,
            "event_kinds": list(self.event_kinds),
            "include_raw_bodies": self.include_raw_bodies,
            "max_depth": self.max_depth,
            "max_events": self.max_events,
            "max_line_events": self.max_line_events,
            "max_local_chars": self.max_local_chars,
            "max_local_items": self.max_local_items,
            "max_payload_bytes": self.max_payload_bytes,
            "max_stack_frames": self.max_stack_frames,
            "schema": self.SCHEMA,
        }

    @property
    def policy_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def capture_profile_cid(self) -> str:
        return cid_for_structured(
            {
                "policy": self.identity_payload(),
                "schema": PYTHON_EXECUTION_CAPTURE_PROFILE_SCHEMA,
                "tracer": PYTHON_EXECUTION_TRACER_INTERFACE,
                "version": PYTHON_EXECUTION_TRACER_VERSION,
            }
        )


class TraceRedactor:
    """Strip secret and non-semantic fields before they enter execution records."""

    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE

    def __init__(self, extra_markers: Sequence[str] = ()) -> None:
        extras = frozenset(_normalize_key(_nfc(item, "redaction marker")) for item in extra_markers)
        self._extra = extras
        self.redacted_keys: set[str] = set()

    def is_forbidden(self, key: str) -> bool:
        lowered = _normalize_key(key)
        if lowered in self._extra or _is_forbidden_key(key):
            if _is_secret_key(key) or lowered in self._extra:
                self.redacted_keys.add("secrets")
            else:
                self.redacted_keys.add(lowered)
            return True
        return False

    def redact(self, value: Any, *, depth: int = 0, max_depth: int = DEFAULT_MAX_DEPTH) -> Any:
        if depth > max_depth:
            return {"unavailable": "depth"}
        value_type = type(value)
        if value is None or value_type is bool:
            return value
        if value_type is int and not isinstance(value, bool):
            if abs(value) > MAX_SAFE_INTEGER:
                return {"unavailable": "overflow"}
            return value
        if value_type is str:
            text = unicodedata.normalize("NFC", value)
            if len(text) > DEFAULT_MAX_LOCAL_CHARS:
                text = text[:DEFAULT_MAX_LOCAL_CHARS]
            return "".join(char for char in text if char.isprintable())
        if value_type is float:
            return {"unavailable": "float"}
        if value_type in {list, tuple}:
            return [
                self.redact(item, depth=depth + 1, max_depth=max_depth) for item in value[:DEFAULT_MAX_LOCAL_ITEMS]
            ]
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if type(key) is not str or self.is_forbidden(key):
                    continue
                if len(result) >= DEFAULT_MAX_LOCAL_ITEMS:
                    break
                result[key] = self.redact(item, depth=depth + 1, max_depth=max_depth)
            return result
        name = getattr(type(value), "__name__", "object")
        if type(name) is not str or not name.isidentifier():
            name = "object"
        return {"type": name}

    @property
    def redacted_dimensions(self) -> tuple[str, ...]:
        return tuple(sorted(self.redacted_keys))


class TraceCancellation:
    """Cooperative cancellation token; a cancelled recording cannot be accepted."""

    INTERFACE: ClassVar[str] = TRACE_CANCELLATION_INTERFACE

    def __init__(self, reason: str = "") -> None:
        self._cancelled = False
        self.reason = reason

    def cancel(self, reason: str = "cancelled") -> None:
        self.reason = _nfc(reason, "cancellation reason")
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def check(self) -> bool:
        return self._cancelled


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


def _reject_accepted_transition(*, accepted_transition: bool, status: str, cancelled: bool) -> None:
    if accepted_transition:
        raise PythonExecutionTraceError("tracing cannot emit an accepted transition")
    if status == "accepted":
        raise PythonExecutionTraceError("tracing cannot emit an accepted transition")
    if cancelled and accepted_transition:
        raise PythonExecutionTraceError("cancellation emits no accepted transition")


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceReceipt:
    """Private catalog plus a public trace that never carries raw bodies."""

    status: str
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    capture_profile_cid: str
    policy_cid: str
    private_trace: ExecutionTrace
    public_trace: ExecutionTrace
    events: tuple[ProgramEvent, ...]
    states: tuple[ProgramExecutionState, ...]
    event_kinds: tuple[str, ...]
    result_summary: Mapping[str, Any] = field(default_factory=dict)
    accepted_transition: bool = False
    cancelled: bool = False
    cancellation_reason: str = ""
    truncated: bool = False
    network_denied: bool = False
    target_exception_type: str = ""
    language: str = ADMITTED_LANGUAGE

    SCHEMA: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECEIPT_SCHEMA
    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        status = _nfc(self.status, "status")
        if status not in _RECEIPT_STATUSES:
            raise PythonExecutionTraceError(f"unsupported trace status {status!r}")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "language", _nfc(self.language, "language"))
        if self.language != ADMITTED_LANGUAGE:
            raise PythonExecutionTraceError("Python tracing admits only python")
        object.__setattr__(self, "tree_cid", _cid(self.tree_cid, "tree_cid"))
        object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(
            self,
            "environment_binding_cid",
            _cid(self.environment_binding_cid, "environment_binding_cid"),
        )
        object.__setattr__(
            self, "capture_profile_cid", _cid(self.capture_profile_cid, "capture_profile_cid")
        )
        object.__setattr__(self, "policy_cid", _cid(self.policy_cid, "policy_cid"))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "states", tuple(self.states))
        object.__setattr__(self, "event_kinds", tuple(self.event_kinds))
        object.__setattr__(
            self, "accepted_transition", _bool(self.accepted_transition, "accepted_transition")
        )
        object.__setattr__(self, "cancelled", _bool(self.cancelled, "cancelled"))
        object.__setattr__(self, "truncated", _bool(self.truncated, "truncated"))
        object.__setattr__(
            self, "network_denied", _bool(self.network_denied, "network_denied")
        )
        object.__setattr__(
            self,
            "cancellation_reason",
            _nfc(self.cancellation_reason, "cancellation_reason", empty=True),
        )
        object.__setattr__(
            self,
            "target_exception_type",
            _nfc(self.target_exception_type, "target_exception_type", empty=True),
        )
        _reject_accepted_transition(
            accepted_transition=self.accepted_transition,
            status=self.status,
            cancelled=self.cancelled,
        )
        if self.cancelled and self.status != TraceStatus.CANCELLED.value:
            raise PythonExecutionTraceError("cancelled receipts must use cancelled status")
        if not isinstance(self.private_trace, ExecutionTrace):
            raise PythonExecutionTraceError("private_trace must be an ExecutionTrace")
        if not isinstance(self.public_trace, ExecutionTrace):
            raise PythonExecutionTraceError("public_trace must be an ExecutionTrace")
        if self.public_trace.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if self.public_trace.raw_execution_state_cids:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if str(self.public_trace.privacy_class) != PrivacyClass.PUBLIC.value:
            raise PythonExecutionTraceError("public_trace must use public privacy")
        object.__setattr__(
            self, "result_summary", MappingProxyType(dict(self.result_summary))
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "accepted_transition": False,
            "cancelled": self.cancelled,
            "cancellation_reason": self.cancellation_reason,
            "capture_profile_cid": self.capture_profile_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "event_kinds": list(self.event_kinds),
            "language": self.language,
            "network_denied": self.network_denied,
            "policy_cid": self.policy_cid,
            "public_trace_cid": self.public_trace.execution_trace_cid,
            "schema": self.SCHEMA,
            "source_cid": self.source_cid,
            "status": self.status,
            "target_exception_type": self.target_exception_type,
            "tree_cid": self.tree_cid,
            "truncated": self.truncated,
        }

    @property
    def python_execution_trace_receipt_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def public_record(self) -> dict[str, Any]:
        """Publishable record: identities and public trace, never raw bodies."""

        payload = self.identity_payload()
        payload["python_execution_trace_receipt_cid"] = (
            self.python_execution_trace_receipt_cid
        )
        payload["public_trace"] = self.public_trace.to_dict()
        return payload

    def to_dict(self) -> dict[str, Any]:
        payload = self.public_record()
        payload["private_trace"] = self.private_trace.to_dict()
        payload["private_event_cids"] = [event.program_event_cid for event in self.events]
        payload["private_state_cids"] = [
            state.program_execution_state_cid for state in self.states
        ]
        return payload


@dataclass(frozen=True, slots=True)
class PythonExecutionReplayReceipt:
    """Deterministic replay comparison; never an accepted transition."""

    matched: bool
    promised_public_trace_cid: str
    replayed_public_trace_cid: str
    event_kind_sequence_equal: bool
    accepted_transition: bool = False
    replayed: PythonExecutionTraceReceipt | None = None

    SCHEMA: ClassVar[str] = PYTHON_EXECUTION_REPLAY_RECEIPT_SCHEMA
    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "matched", _bool(self.matched, "matched"))
        object.__setattr__(
            self,
            "event_kind_sequence_equal",
            _bool(self.event_kind_sequence_equal, "event_kind_sequence_equal"),
        )
        object.__setattr__(
            self, "accepted_transition", _bool(self.accepted_transition, "accepted_transition")
        )
        object.__setattr__(
            self,
            "promised_public_trace_cid",
            _cid(self.promised_public_trace_cid, "promised_public_trace_cid"),
        )
        object.__setattr__(
            self,
            "replayed_public_trace_cid",
            _cid(self.replayed_public_trace_cid, "replayed_public_trace_cid"),
        )
        _reject_accepted_transition(
            accepted_transition=self.accepted_transition,
            status="recorded",
            cancelled=False,
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "accepted_transition": False,
            "event_kind_sequence_equal": self.event_kind_sequence_equal,
            "matched": self.matched,
            "promised_public_trace_cid": self.promised_public_trace_cid,
            "replayed_public_trace_cid": self.replayed_public_trace_cid,
            "schema": self.SCHEMA,
        }

    @property
    def python_execution_replay_receipt_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["python_execution_replay_receipt_cid"] = (
            self.python_execution_replay_receipt_cid
        )
        return payload


# ---------------------------------------------------------------------------
# Bounded serialization
# ---------------------------------------------------------------------------


def _bounded_value(
    value: Any,
    *,
    redactor: TraceRedactor,
    policy: TraceCollectionPolicy,
    depth: int = 0,
) -> Any:
    if depth > policy.max_depth:
        return {"unavailable": "depth"}
    value_type = type(value)
    if value is None or value_type is bool:
        return value
    if value_type is int and not isinstance(value, bool):
        if abs(value) > MAX_SAFE_INTEGER:
            return {"unavailable": "overflow"}
        return value
    if value_type is str:
        text = unicodedata.normalize("NFC", value)
        if len(text) > policy.max_local_chars:
            text = text[: policy.max_local_chars]
        return "".join(char for char in text if char.isprintable())
    if value_type is float:
        return {"unavailable": "float"}
    if value_type in {list, tuple}:
        return [
            _bounded_value(item, redactor=redactor, policy=policy, depth=depth + 1)
            for item in list(value)[: policy.max_local_items]
        ]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str or redactor.is_forbidden(key):
                continue
            if len(result) >= policy.max_local_items:
                break
            result[key] = _bounded_value(
                item, redactor=redactor, policy=policy, depth=depth + 1
            )
        return result
    name = getattr(type(value), "__name__", "object")
    if type(name) is not str or not name.isidentifier():
        name = "object"
    return {"type": name}


def _fit_mapping(payload: Mapping[str, Any], *, max_bytes: int) -> dict[str, Any]:
    prepared = dict(payload)
    try:
        encoded = canonical_dag_json_bytes(prepared)
    except Exception:
        return {"bounded": True}
    if len(encoded) <= max_bytes:
        return prepared
    return {"bounded": True}


def _locals_summary(
    frame: FrameType, *, redactor: TraceRedactor, policy: TraceCollectionPolicy
) -> dict[str, Any]:
    if not policy.collect_locals:
        return {}
    locals_map = frame.f_locals
    collected: dict[str, Any] = {}
    for name, value in locals_map.items():
        if type(name) is not str or name.startswith("_"):
            continue
        if redactor.is_forbidden(name):
            continue
        if len(collected) >= policy.max_local_items:
            break
        collected[name] = _bounded_value(value, redactor=redactor, policy=policy)
    return _fit_mapping({"locals": collected}, max_bytes=policy.max_payload_bytes)


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


class _HermeticIsolation:
    """Deny network/subprocess/installer during collection and record attempts."""

    def __init__(self, tracer: PythonExecutionTracer) -> None:
        self._tracer = tracer
        self._installed = False
        self._socket = None
        self._subprocess = None
        self._orig: dict[str, Any] = {}

    def install(self) -> None:
        if self._installed:
            return
        policy = self._tracer.policy
        if policy.deny_network:
            import socket

            self._socket = socket
            self._orig["create_connection"] = socket.create_connection
            self._orig["getaddrinfo"] = socket.getaddrinfo
            self._orig["connect"] = socket.socket.connect
            self._orig["connect_ex"] = socket.socket.connect_ex
            socket.create_connection = self._wrap("socket.create_connection", socket.create_connection)
            socket.getaddrinfo = self._wrap("socket.getaddrinfo", socket.getaddrinfo)
            try:
                socket.socket.connect = self._wrap_method("socket.connect", socket.socket.connect)
                socket.socket.connect_ex = self._wrap_method(
                    "socket.connect_ex", socket.socket.connect_ex
                )
            except (AttributeError, TypeError):
                self._orig.pop("connect", None)
                self._orig.pop("connect_ex", None)
        if policy.deny_subprocess or policy.deny_installer:
            import subprocess

            self._subprocess = subprocess
            self._orig["Popen"] = subprocess.Popen
            self._orig["system"] = os.system
            subprocess.Popen = self._wrap("subprocess.Popen", subprocess.Popen)
            os.system = self._wrap("os.system", os.system)
        self._installed = True

    def restore(self) -> None:
        if not self._installed:
            return
        socket = self._socket
        if socket is not None:
            if "create_connection" in self._orig:
                socket.create_connection = self._orig["create_connection"]
            if "getaddrinfo" in self._orig:
                socket.getaddrinfo = self._orig["getaddrinfo"]
            try:
                if "connect" in self._orig:
                    socket.socket.connect = self._orig["connect"]
                if "connect_ex" in self._orig:
                    socket.socket.connect_ex = self._orig["connect_ex"]
            except (AttributeError, TypeError):
                pass
        subprocess = self._subprocess
        if subprocess is not None and "Popen" in self._orig:
            subprocess.Popen = self._orig["Popen"]
        if "system" in self._orig:
            os.system = self._orig["system"]
        self._installed = False

    def _wrap(self, effect: str, original: Callable[..., Any]) -> Callable[..., Any]:
        tracer = self._tracer

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            tracer.note_external(effect)
            raise PythonExecutionTraceError(
                f"{effect} denied by hermetic trace policy"
            )

        wrapped.__name__ = getattr(original, "__name__", effect)
        return wrapped

    def _wrap_method(self, effect: str, original: Callable[..., Any]) -> Callable[..., Any]:
        tracer = self._tracer

        def wrapped(sock: Any, *args: Any, **kwargs: Any) -> Any:
            tracer.note_external(effect)
            raise PythonExecutionTraceError(
                f"{effect} denied by hermetic trace policy"
            )

        wrapped.__name__ = getattr(original, "__name__", effect)
        return wrapped


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class PythonExecutionTracer:
    """sys.settrace collector that emits SAWM-007 execution records."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE
    VERSION: ClassVar[str] = PYTHON_EXECUTION_TRACER_VERSION

    def __init__(
        self,
        *,
        policy: TraceCollectionPolicy | None = None,
        environment_binding: Mapping[str, str] | None = None,
        tree_cid: str | None = None,
        cancellation: TraceCancellation | None = None,
        redactor: TraceRedactor | None = None,
    ) -> None:
        self.policy = policy if policy is not None else TraceCollectionPolicy()
        self.environment_binding = dict(
            environment_binding if environment_binding is not None else default_environment_binding()
        )
        self.env_cid = environment_binding_cid(self.environment_binding)
        self._requested_tree_cid = tree_cid
        self.cancellation = cancellation if cancellation is not None else TraceCancellation()
        self.redactor = redactor if redactor is not None else TraceRedactor()
        self._reset_runtime()

    def _reset_runtime(self) -> None:
        self.events: list[ProgramEvent] = []
        self.states: list[ProgramExecutionState] = []
        self.event_kinds: list[str] = []
        self.truncated = False
        self.network_denied = False
        self.target_exception_type = ""
        self.result_summary: dict[str, Any] = {}
        self._source_cid = ""
        self._tree_cid = ""
        self._capture_cid = self.policy.capture_profile_cid()
        self._target_code: CodeType | None = None
        self._entered = False
        self._previous_event_cid: str | None = None
        self._line_events = 0
        self._pending_exception: BaseException | None = None
        self._handler_emitted = False
        self._code_cids: dict[int, str] = {}
        self._isolation = _HermeticIsolation(self)
        self._stop = False
        self._trace_error = None
        self.redactor.redacted_keys.clear()

    def record(
        self, target: Callable[..., Any], /, *args: Any, **kwargs: Any
    ) -> PythonExecutionTraceReceipt:
        """Collect one hermetic execution of ``target``."""

        if not callable(target):
            raise PythonExecutionTraceError("target must be callable")
        self._reset_runtime()
        source, source_cid = _callable_source(target)
        del source
        self._source_cid = source_cid
        code = _callable_code(target)
        self._target_code = code
        module = getattr(target, "__module__", None) or "unknown"
        qualname = getattr(target, "__qualname__", None) or getattr(target, "__name__", "target")
        logical = _nfc(f"{module}.{qualname}", "target logical name")
        if self._requested_tree_cid:
            self._tree_cid = _cid(self._requested_tree_cid, "tree_cid")
        else:
            self._tree_cid = _tree_cid(source_cid=source_cid, logical_name=logical)

        previous_trace = sys.gettrace()
        try:
            self._isolation.install()
            sys.settrace(self._trace)
            try:
                result = target(*args, **kwargs)
            except PythonExecutionTraceError as error:
                if "denied by hermetic trace policy" in str(error):
                    self.network_denied = True
                    self.target_exception_type = type(error).__name__
                    result = None
                else:
                    raise
            except BaseException as error:
                self.target_exception_type = type(error).__name__
                result = None
            finally:
                sys.settrace(previous_trace)
        finally:
            self._isolation.restore()
            sys.settrace(previous_trace)

        if self._trace_error is not None:
            raise PythonExecutionTraceError(
                f"hermetic trace record failed: {self._trace_error}"
            ) from self._trace_error

        if not self.cancellation.cancelled:
            self.result_summary = _fit_mapping(
                {"value": _bounded_value(result, redactor=self.redactor, policy=self.policy)},
                max_bytes=self.policy.max_payload_bytes,
            )
        return self._build_receipt()

    def note_external(self, effect: str) -> None:
        if effect not in _EXTERNAL_EFFECTS and not effect.startswith("socket."):
            effect = _nfc(effect, "effect")
        self.network_denied = True
        if self._stop or not self.policy.admits(EventKind.EXTERNAL.value):
            return
        if not self.policy.collect_external:
            return
        frame = sys._getframe(2)
        while frame is not None and frame.f_code.co_filename == _TRACER_FILE:
            frame = frame.f_back
        if frame is None:
            return
        self._emit(
            EventKind.EXTERNAL.value,
            frame,
            payload={"denied": True, "effect": effect},
        )

    def _trace(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if self._stop:
            return None
        try:
            return self._trace_inner(frame, event, arg)
        except PythonExecutionTraceError as error:
            self._trace_error = error
            self._stop = True
            return None
        except ProgramExecutionError as error:
            self._trace_error = error
            self._stop = True
            return None
        except Exception:
            return self._trace

    def _trace_inner(
        self, frame: FrameType, event: str, arg: Any
    ) -> Callable[..., Any] | None:
        if frame.f_code.co_filename == _TRACER_FILE:
            return None
        if self.cancellation.check():
            self._stop = True
            return None
        if not self._entered:
            if event == "call" and frame.f_code is self._target_code:
                self._entered = True
            else:
                return self._trace
        if len(self.events) >= self.policy.max_events:
            self.truncated = True
            self._stop = True
            return None

        if event == "call":
            self._emit(EventKind.CALL.value, frame, payload={"callee": _logical_name(frame)})
            return self._trace
        if event == "line":
            self._maybe_emit_handler(frame)
            if not self.policy.collect_lines or not self.policy.admits(EventKind.LINE.value):
                return self._trace
            if self._line_events >= self.policy.max_line_events:
                return self._trace
            self._line_events += 1
            self._emit(EventKind.LINE.value, frame, payload={})
            return self._trace
        if event == "exception":
            exc = arg[1] if isinstance(arg, tuple) and len(arg) > 1 else arg
            self._pending_exception = exc if isinstance(exc, BaseException) else None
            self._handler_emitted = False
            self._emit_raise(frame, exc)
            return self._trace
        if event == "return":
            self._emit_return(frame, arg)
            if frame.f_code is self._target_code:
                self._entered = False
            return self._trace
        return self._trace

    def _maybe_emit_handler(self, frame: FrameType) -> None:
        if self._pending_exception is None or self._handler_emitted:
            return
        current = sys.exc_info()[1]
        if current is None:
            return
        self._handler_emitted = True
        snapshot = self._exception_snapshot(frame, self._pending_exception)
        handler = self._handler_state(frame, snapshot)
        payload = {"handler_kind": HandlerKind.EXCEPT.value}
        if self.policy.admits(EventKind.CATCH.value):
            self._emit(
                EventKind.CATCH.value,
                frame,
                payload=payload,
                handler=handler,
                exception=snapshot,
            )
        if self.policy.admits(EventKind.HANDLER.value):
            self._emit(
                EventKind.HANDLER.value,
                frame,
                payload=payload,
                handler=handler,
                exception=snapshot,
            )

    def _emit_raise(self, frame: FrameType, exc: object) -> None:
        if not self.policy.admits(EventKind.RAISE.value):
            return
        snapshot = self._exception_snapshot(frame, exc)
        exc_type = type(exc).__name__ if isinstance(exc, BaseException) else "Exception"
        self._emit(
            EventKind.RAISE.value,
            frame,
            payload={"exception_type": exc_type},
            exception=snapshot,
            exception_active=True,
        )

    def _emit_return(self, frame: FrameType, arg: Any) -> None:
        flags = frame.f_code.co_flags
        kind = EventKind.RETURN.value
        payload: dict[str, Any]
        if flags & (_CO_GENERATOR | _CO_ASYNC_GENERATOR) and self.policy.admits(
            EventKind.YIELD.value
        ):
            kind = EventKind.YIELD.value
            payload = {"value": _bounded_value(arg, redactor=self.redactor, policy=self.policy)}
        elif flags & (_CO_COROUTINE | _CO_ITERABLE_COROUTINE) and inspect.isawaitable(arg):
            if self.policy.admits(EventKind.AWAIT.value):
                kind = EventKind.AWAIT.value
                payload = {"awaitable_kind": type(arg).__name__}
            else:
                payload = {}
        else:
            payload = {
                "value": _bounded_value(arg, redactor=self.redactor, policy=self.policy)
            }
        if not self.policy.admits(kind):
            return
        self._emit(kind, frame, payload=payload)

    def _stack_frames(
        self,
        frame: FrameType,
        *,
        exception: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
        exception_active: bool = False,
        handler_active: bool = False,
    ) -> tuple[StackFrameState, ...]:
        raw: list[FrameType] = []
        current: FrameType | None = frame
        while current is not None and len(raw) < self.policy.max_stack_frames:
            if current.f_code.co_filename == _TRACER_FILE:
                current = current.f_back
                continue
            raw.append(current)
            if self._target_code is not None and current.f_code is self._target_code:
                break
            current = current.f_back
        frames: list[StackFrameState] = []
        redacted = self.redactor.redacted_dimensions
        claim = (
            CompletenessClaim.REDACTED.value
            if redacted
            else CompletenessClaim.PARTIAL.value
        )
        privacy = (
            PrivacyClass.PRIVATE
            if self.policy.include_raw_bodies
            else PrivacyClass.INTERNAL
        )
        for ordinal, item in enumerate(raw):
            logical = _logical_name(item)
            code_cid = self._code_cids.get(id(item.f_code))
            if code_cid is None:
                code_cid = _code_cid(item, logical_name=logical)
                self._code_cids[id(item.f_code)] = code_cid
            summary = _locals_summary(item, redactor=self.redactor, policy=self.policy)
            frames.append(
                StackFrameState(
                    ordinal=ordinal,
                    language=ADMITTED_LANGUAGE,
                    tree_cid=self._tree_cid,
                    source_cid=self._source_cid,
                    code_cid=code_cid,
                    environment_binding_cid=self.env_cid,
                    logical_name=logical,
                    line=item.f_lineno if item.f_lineno >= 0 else 0,
                    column=None,
                    state_summary=summary,
                    exception_snapshot_cid=(
                        exception.exception_snapshot_cid if exception_active and ordinal == 0 else None
                    ),
                    handler_state_cid=(
                        handler.handler_state_cid if handler_active and ordinal == 0 else None
                    ),
                    exception_active=exception_active and ordinal == 0,
                    handler_active=handler_active and ordinal == 0,
                    redacted_dimensions=redacted,
                    unavailable_dimensions=DEFAULT_UNAVAILABLE_DIMENSIONS,
                    completeness_claim=claim,
                    privacy_class=privacy,
                )
            )
        if not frames:
            logical = "unknown.frame"
            code_cid = cid_for_structured(
                {
                    "bytecode_cid": cid_for_bytes(b"unavailable"),
                    "firstlineno": 0,
                    "logical_name": logical,
                    "schema": PYTHON_EXECUTION_CODE_SCHEMA,
                }
            )
            frames.append(
                StackFrameState(
                    ordinal=0,
                    language=ADMITTED_LANGUAGE,
                    tree_cid=self._tree_cid,
                    source_cid=self._source_cid,
                    code_cid=code_cid,
                    environment_binding_cid=self.env_cid,
                    logical_name=logical,
                    line=0,
                    column=None,
                    state_summary={},
                    unavailable_dimensions=DEFAULT_UNAVAILABLE_DIMENSIONS,
                    completeness_claim=CompletenessClaim.PARTIAL,
                    privacy_class=PrivacyClass.INTERNAL,
                )
            )
        return tuple(frames)

    def _exception_snapshot(self, frame: FrameType, exc: object) -> ExceptionSnapshot:
        frames = self._stack_frames(frame)
        exc_type = type(exc).__name__ if isinstance(exc, BaseException) else "Exception"
        logical = _logical_name(frame)
        code_cid = _code_cid(frame, logical_name=logical)
        return ExceptionSnapshot(
            language=ADMITTED_LANGUAGE,
            exception_type=exc_type,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=code_cid,
            environment_binding_cid=self.env_cid,
            exception_value_summary={"bounded": True, "type": exc_type},
            traceback_stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
            future_execution=False,
            unavailable_dimensions=DEFAULT_UNAVAILABLE_DIMENSIONS,
            completeness_claim=CompletenessClaim.PARTIAL,
        )

    def _handler_state(self, frame: FrameType, snapshot: ExceptionSnapshot) -> HandlerState:
        logical = _logical_name(frame)
        return HandlerState(
            language=ADMITTED_LANGUAGE,
            handler_kind=HandlerKind.EXCEPT,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=_code_cid(frame, logical_name=logical),
            environment_binding_cid=self.env_cid,
            logical_name=logical,
            stack_ordinal=0,
            handler_active=True,
            matching_exception_snapshot_cid=snapshot.exception_snapshot_cid,
        )

    def _emit(
        self,
        kind: str,
        frame: FrameType,
        *,
        payload: Mapping[str, Any],
        exception: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
        exception_active: bool = False,
    ) -> None:
        if self._stop or not self.policy.admits(kind):
            return
        if len(self.events) >= self.policy.max_events:
            self.truncated = True
            self._stop = True
            return
        frames = self._stack_frames(
            frame,
            exception=exception,
            handler=handler,
            exception_active=exception_active,
            handler_active=handler is not None,
        )
        innermost = frames[0]
        redacted = self.redactor.redacted_dimensions
        claim = (
            CompletenessClaim.REDACTED.value
            if redacted
            else CompletenessClaim.PARTIAL.value
        )
        privacy = (
            PrivacyClass.PRIVATE
            if self.policy.include_raw_bodies
            else PrivacyClass.INTERNAL
        )
        fitted = _fit_mapping(payload, max_bytes=self.policy.max_payload_bytes)
        redaction_profile = None
        if redacted:
            redaction_profile = RedactionProfile(
                privacy_class=privacy,
                redacted_dimensions=redacted,
                unavailable_dimensions=DEFAULT_UNAVAILABLE_DIMENSIONS,
                completeness_claim=CompletenessClaim.REDACTED,
            )
        event = ProgramEvent(
            event_kind=kind,
            event_origin=EventOrigin.OBSERVED,
            observation_status=ObservationStatus.OBSERVED,
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=innermost.code_cid,
            environment_binding_cid=self.env_cid,
            subject_cid=_subject_cid(
                logical_name=innermost.logical_name, code_cid=innermost.code_cid
            ),
            logical_name=innermost.logical_name,
            payload=fitted,
            line=innermost.line,
            column=innermost.column,
            predecessor_event_cid=self._previous_event_cid,
            stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
            exception_snapshot_cid=(
                exception.exception_snapshot_cid if exception is not None else None
            ),
            handler_state_cid=handler.handler_state_cid if handler is not None else None,
            redaction_profile_cid=(
                None if redaction_profile is None else redaction_profile.redaction_profile_cid
            ),
            redacted_dimensions=redacted,
            unavailable_dimensions=DEFAULT_UNAVAILABLE_DIMENSIONS,
            completeness_claim=claim,
            privacy_class=privacy,
        )
        self.events.append(event)
        self.event_kinds.append(kind)
        self._previous_event_cid = event.program_event_cid
        state = assemble_program_execution_state(
            language=ADMITTED_LANGUAGE,
            capture_profile_cid=self._capture_cid,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self.env_cid,
            frames=frames,
            observed_state=_thaw(innermost.state_summary),
            heap_summary={},
            heap_bound=HeapBound.UNAVAILABLE,
            exception=exception,
            handler=handler,
            redaction=redaction_profile,
            observation_status=ObservationStatus.OBSERVED,
            completeness_claim=claim,
            privacy_class=privacy,
            includes_raw_bodies=self.policy.include_raw_bodies,
            unavailable_dimensions=DEFAULT_UNAVAILABLE_DIMENSIONS,
            code_cid=innermost.code_cid,
        )
        self.states.append(state)

    def _unavailable_event(self) -> ProgramEvent:
        logical = "unavailable.trace"
        code_cid = cid_for_structured(
            {
                "bytecode_cid": cid_for_bytes(b"unavailable"),
                "firstlineno": 0,
                "logical_name": logical,
                "schema": PYTHON_EXECUTION_CODE_SCHEMA,
            }
        )
        frame = StackFrameState(
            ordinal=0,
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=code_cid,
            environment_binding_cid=self.env_cid,
            logical_name=logical,
            line=0,
            state_summary={},
            unavailable_dimensions=("call_stack", *DEFAULT_UNAVAILABLE_DIMENSIONS),
            completeness_claim=CompletenessClaim.UNAVAILABLE,
            privacy_class=PrivacyClass.INTERNAL,
        )
        return ProgramEvent(
            event_kind=EventKind.UNAVAILABLE,
            event_origin=EventOrigin.OBSERVED,
            observation_status=ObservationStatus.UNAVAILABLE,
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=code_cid,
            environment_binding_cid=self.env_cid,
            subject_cid=_subject_cid(logical_name=logical, code_cid=code_cid),
            logical_name=logical,
            payload={},
            line=0,
            stack_frame_cids=(frame.stack_frame_state_cid,),
            unavailable_dimensions=("event_body", *DEFAULT_UNAVAILABLE_DIMENSIONS),
            completeness_claim=CompletenessClaim.UNAVAILABLE,
            privacy_class=PrivacyClass.INTERNAL,
        )

    def _build_receipt(self) -> PythonExecutionTraceReceipt:
        cancelled = self.cancellation.cancelled
        events = tuple(self.events)
        if not events:
            events = (self._unavailable_event(),)
        redacted = self.redactor.redacted_dimensions
        redaction = None
        if redacted:
            redaction = RedactionProfile(
                privacy_class=(
                    PrivacyClass.PRIVATE
                    if self.policy.include_raw_bodies
                    else PrivacyClass.INTERNAL
                ),
                redacted_dimensions=redacted,
                unavailable_dimensions=DEFAULT_UNAVAILABLE_DIMENSIONS,
                completeness_claim=CompletenessClaim.REDACTED,
            )
        unavailable = list(DEFAULT_UNAVAILABLE_DIMENSIONS)
        if self._line_events >= self.policy.max_line_events:
            unavailable.append("line_suffix")
        if self.truncated:
            unavailable.append("remaining_events")
        if cancelled:
            unavailable.append("suffix")
        claim = (
            CompletenessClaim.REDACTED.value
            if redacted
            else CompletenessClaim.PARTIAL.value
        )
        privacy = (
            PrivacyClass.PRIVATE
            if self.policy.include_raw_bodies
            else PrivacyClass.INTERNAL
        )
        private = assemble_execution_trace(
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self.env_cid,
            events=events,
            states=self.states,
            redaction=redaction,
            completeness_claim=claim,
            privacy_class=privacy,
            includes_raw_bodies=self.policy.include_raw_bodies,
            unavailable_dimensions=tuple(sorted(set(unavailable))),
        )
        public = private.public_view()
        if cancelled:
            status = TraceStatus.CANCELLED.value
        elif self.truncated:
            status = TraceStatus.TRUNCATED.value
        elif self.target_exception_type and not any(
            kind in {EventKind.CATCH.value, EventKind.HANDLER.value} for kind in self.event_kinds
        ):
            status = TraceStatus.TARGET_FAILED.value
        elif not self.events:
            status = TraceStatus.UNAVAILABLE.value
        else:
            status = TraceStatus.RECORDED.value
        return PythonExecutionTraceReceipt(
            status=status,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self.env_cid,
            capture_profile_cid=self._capture_cid,
            policy_cid=self.policy.policy_cid,
            private_trace=private,
            public_trace=public,
            events=events,
            states=tuple(self.states),
            event_kinds=tuple(self.event_kinds) if self.event_kinds else (EventKind.UNAVAILABLE.value,),
            result_summary=self.result_summary,
            accepted_transition=False,
            cancelled=cancelled,
            cancellation_reason=self.cancellation.reason if cancelled else "",
            truncated=self.truncated,
            network_denied=self.network_denied,
            target_exception_type=self.target_exception_type,
        )


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def record_python_execution_trace(
    target: Callable[..., Any],
    /,
    *args: Any,
    policy: TraceCollectionPolicy | None = None,
    environment_binding: Mapping[str, str] | None = None,
    tree_cid: str | None = None,
    cancellation: TraceCancellation | None = None,
    **kwargs: Any,
) -> PythonExecutionTraceReceipt:
    """Record one hermetic Python execution as a SAWM-007 execution trace."""

    tracer = PythonExecutionTracer(
        policy=policy,
        environment_binding=environment_binding,
        tree_cid=tree_cid,
        cancellation=cancellation,
    )
    return tracer.record(target, *args, **kwargs)


def replay_deterministic_trace(
    promised: PythonExecutionTraceReceipt | ExecutionTrace | Sequence[ProgramEvent],
    /,
    *,
    target: Callable[..., Any] | None = None,
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    policy: TraceCollectionPolicy | None = None,
    environment_binding: Mapping[str, str] | None = None,
    tree_cid: str | None = None,
) -> PythonExecutionReplayReceipt:
    """Rehash promised identities and, when a target is supplied, re-record it.

    Replay never emits an accepted transition.  A cancelled promised recording
    cannot become accepted by replay.
    """

    promised_receipt: PythonExecutionTraceReceipt | None
    promised_events: tuple[ProgramEvent, ...]
    promised_public_cid: str
    promised_kinds: tuple[str, ...]
    if isinstance(promised, PythonExecutionTraceReceipt):
        promised_receipt = promised
        promised_events = promised.events
        promised_public_cid = promised.public_trace.execution_trace_cid
        promised_kinds = promised.event_kinds
        if policy is None:
            policy = TraceCollectionPolicy()
        if environment_binding is None:
            environment_binding = default_environment_binding()
        if tree_cid is None:
            tree_cid = promised.tree_cid
    elif isinstance(promised, ExecutionTrace):
        promised_receipt = None
        promised_events = ()
        promised_public_cid = promised.public_view().execution_trace_cid
        promised_kinds = ()
        rebuilt = ExecutionTrace.from_dict(promised.to_dict())
        if rebuilt.execution_trace_cid != promised.execution_trace_cid:
            raise PythonExecutionTraceError("promised trace identity failed to rehash")
    else:
        promised_receipt = None
        promised_events = tuple(promised)
        if not promised_events:
            raise PythonExecutionTraceError("promised events must not be empty")
        for event in promised_events:
            if not isinstance(event, ProgramEvent):
                raise PythonExecutionTraceError("promised events must be ProgramEvent values")
            rebuilt_event = ProgramEvent.from_dict(event.to_dict())
            if rebuilt_event.program_event_cid != event.program_event_cid:
                raise PythonExecutionTraceError("promised event identity failed to rehash")
        promised_kinds = tuple(str(event.event_kind) for event in promised_events)
        public = assemble_execution_trace(
            tree_cid=promised_events[0].tree_cid,
            source_cid=promised_events[0].source_cid,
            environment_binding_cid=promised_events[0].environment_binding_cid,
            events=promised_events,
            privacy_class=PrivacyClass.INTERNAL,
        ).public_view()
        promised_public_cid = public.execution_trace_cid

    for event in promised_events:
        rebuilt_event = ProgramEvent.from_dict(event.to_dict())
        if rebuilt_event.program_event_cid != event.program_event_cid:
            raise PythonExecutionTraceError("promised event identity failed to rehash")
        if event.observation_admissible:
            observation = observe_program_event(event)
            if observation.event_cid != event.program_event_cid:
                raise PythonExecutionTraceError("observation identity drifted under replay")

    if target is None:
        return PythonExecutionReplayReceipt(
            matched=True,
            promised_public_trace_cid=promised_public_cid,
            replayed_public_trace_cid=promised_public_cid,
            event_kind_sequence_equal=True,
            accepted_transition=False,
            replayed=promised_receipt,
        )

    replayed = record_python_execution_trace(
        target,
        *tuple(args),
        policy=policy,
        environment_binding=environment_binding,
        tree_cid=tree_cid,
        **dict(kwargs or {}),
    )
    kinds_equal = replayed.event_kinds == promised_kinds if promised_kinds else True
    matched = (
        replayed.public_trace.execution_trace_cid == promised_public_cid
        and kinds_equal
        and replayed.accepted_transition is False
    )
    if isinstance(promised, PythonExecutionTraceReceipt) and promised.cancelled:
        matched = False
    return PythonExecutionReplayReceipt(
        matched=matched,
        promised_public_trace_cid=promised_public_cid,
        replayed_public_trace_cid=replayed.public_trace.execution_trace_cid,
        event_kind_sequence_equal=kinds_equal,
        accepted_transition=False,
        replayed=replayed,
    )


__all__ = [
    "ADMITTED_LANGUAGE",
    "DEFAULT_EVENT_KINDS",
    "IMPORT_DATABASE_OPENED",
    "IMPORT_INSTALLER_STARTED",
    "IMPORT_MODEL_LOADED",
    "IMPORT_NETWORK_LOADED",
    "IMPORT_REPO_SCAN_PERFORMED",
    "IMPORT_SIDE_EFFECTS_PERFORMED",
    "IMPORT_SOCKET_CONNECTED",
    "IMPORT_SUBPROCESS_STARTED",
    "IMPORT_WATCHER_STARTED",
    "PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE",
    "PYTHON_EXECUTION_TRACE_RECEIPT_INTERFACE",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "PYTHON_EXECUTION_TRACER_VERSION",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "PythonExecutionReplayReceipt",
    "PythonExecutionTraceError",
    "PythonExecutionTraceReceipt",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCollectionPolicy",
    "TraceRedactor",
    "TraceStatus",
    "default_environment_binding",
    "environment_binding_cid",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
