"""Hermetic Python execution tracing bound to SAWM-007 execution contracts.

This module is the datasets tracing adapter for SAWM-008.  It collects admitted
call, return, line, exception, handler, yield, await, and selected external
events under exact tree, source, code, and environment identities.

Authority rules (normative):

* Importing this module never opens a network, socket, installer, subprocess,
  database, repository scan, watcher, or model load.  Tracing starts only when
  :func:`record_python_execution_trace` or :class:`PythonExecutionTracer` runs.
* Collection uses in-process ``sys.settrace`` hooks.  It does not spawn a
  shell, persist operational acceptance, or bypass execution isolation.
* Every recorded event binds exact symbol, callsite, and source identity.
  State summaries are bounded, secret fields are redacted, and public records
  never carry private raw trace bodies.
* Cancellation emits no accepted transition.  This adapter never writes an
  accepted-transition CID; operational admission remains accelerator-owned.
* Nondeterministic external effects are explicit observations or typed
  unavailable.  Promised replay is reserved for completed hermetic traces.
* Line and basic-block detail is policy- and cost-bounded.  Unsupported
  languages remain outside this Python-only profile.
"""

from __future__ import annotations

import ast
import builtins
import dis
import inspect
import json
import linecache
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import CodeType, FrameType, MappingProxyType, TracebackType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_contracts.content import (
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
    MAX_SAFE_INTEGER,
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
)


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PYTHON_EXECUTION_TRACER_INTERFACE: Final[str] = "PythonExecutionTracer@1"
TRACE_COLLECTION_POLICY_INTERFACE: Final[str] = "TraceCollectionPolicy@1"
TRACE_REDACTOR_INTERFACE: Final[str] = "TraceRedactor@1"
TRACE_CANCELLATION_INTERFACE: Final[str] = "TraceCancellation@1"
PYTHON_EXECUTION_TRACE_RECORD_INTERFACE: Final[str] = "PythonExecutionTraceRecord@1"
TRACE_REPLAY_RECEIPT_INTERFACE: Final[str] = "TraceReplayReceipt@1"
HERMETIC_TRACE_EVIDENCE: Final[str] = "sawm/hermetic-trace@1"

TRACE_COLLECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-policy@1"
)
PYTHON_EXECUTION_TRACE_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-trace-record@1"
)
TRACE_REPLAY_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-replay-receipt@1"
)
PYTHON_CODE_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-code-identity@1"
)
PYTHON_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-subject@1"
)
PYTHON_EXECUTION_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-environment@1"
)
HERMETIC_TREE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.hermetic-tree@1"
)
CAPTURE_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-capture-profile@1"
)

# Importing this module must remain a no-effect operation.  Collection is
# explicit via :func:`record_python_execution_trace`.
IMPORT_SIDE_EFFECTS_PERFORMED: Final[bool] = False
IMPORT_NETWORK_LOADED: Final[bool] = False
IMPORT_SOCKET_LOADED: Final[bool] = False
IMPORT_SUBPROCESS_LOADED: Final[bool] = False
IMPORT_INSTALLER_LOADED: Final[bool] = False
IMPORT_DATABASE_LOADED: Final[bool] = False
IMPORT_REPO_SCAN_PERFORMED: Final[bool] = False
IMPORT_WATCHER_LOADED: Final[bool] = False
IMPORT_MODEL_LOADED: Final[bool] = False

ADMITTED_LANGUAGE: Final[str] = "python"
DEFAULT_MAX_EVENTS: Final[int] = 2_048
DEFAULT_MAX_FRAMES: Final[int] = 32
DEFAULT_MAX_SUMMARY_ITEMS: Final[int] = 16
DEFAULT_MAX_TEXT_CHARS: Final[int] = 256
DEFAULT_MAX_SUMMARY_DEPTH: Final[int] = 3
_MODULE_FILENAME: Final[str] = __file__

_DENIED_IMPORT_ROOTS: Final[frozenset[str]] = frozenset(
    {
        "socket",
        "_socket",
        "ssl",
        "_ssl",
        "subprocess",
        "multiprocessing",
        "asyncio.subprocess",
        "requests",
        "aiohttp",
        "httpx",
        "sqlite3",
        "duckdb",
        "psycopg2",
        "pymongo",
        "sqlalchemy",
        "pip",
        "ensurepip",
        "watchdog",
        "torch",
        "transformers",
        "tensorflow",
        "huggingface_hub",
    }
)
_YIELD_OPCODES: Final[frozenset[str]] = frozenset({"YIELD_VALUE", "YIELD_FROM"})
_AWAIT_OPCODES: Final[frozenset[str]] = frozenset(
    {
        "GET_AWAITABLE",
        "SEND",
        "END_SEND",
        "GET_AITER",
        "GET_ANEXT",
        "BEFORE_ASYNC_WITH",
        "CLEANUP_THROW",
    }
)
_ADMITTED_EVENT_KINDS: Final[tuple[str, ...]] = tuple(
    kind.value
    for kind in (
        EventKind.CALL,
        EventKind.RETURN,
        EventKind.LINE,
        EventKind.RAISE,
        EventKind.CATCH,
        EventKind.HANDLER,
        EventKind.YIELD,
        EventKind.AWAIT,
        EventKind.ENTER,
        EventKind.EXIT,
        EventKind.EXTERNAL,
        EventKind.UNAVAILABLE,
    )
)


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic tracing inputs, isolation, or records are unsound."""


class HermeticIsolationError(PythonExecutionTraceError):
    """Raised when a traced subject attempts a denied external effect."""


class TraceCancelledError(PythonExecutionTraceError):
    """Raised when tracing stops because cancellation was requested."""


class TraceStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ISOLATED = "isolated"
    FAILED = "failed"
    TRUNCATED = "truncated"


# ---------------------------------------------------------------------------
# Validation helpers
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


def _positive_int(value: Any, name: str, *, lo: int, hi: int) -> int:
    if type(value) is not int or isinstance(value, bool) or not lo <= value <= hi:
        raise PythonExecutionTraceError(f"{name} must be an integer in [{lo}, {hi}]")
    return value


def _source_bytes(value: str | bytes) -> bytes:
    if type(value) is bytes:
        return value
    if type(value) is str:
        return value.encode("utf-8")
    raise PythonExecutionTraceError("source must be text or UTF-8 bytes")


def _is_secret_key(key: str) -> bool:
    lowered = key.strip().lower().replace("-", "_")
    if lowered in SECRET_FIELD_MARKERS or lowered in FORBIDDEN_FIELD_MARKERS:
        return True
    return any(marker in lowered for marker in SECRET_FIELD_MARKERS)


def _plain_json_value(value: Any, *, depth: int = 0, max_depth: int = 8) -> Any:
    """Return a JSON-serializable DAG-JSON value; floats and host objects drop out."""

    if depth >= max_depth:
        return {"unavailable": "depth"}
    value_type = type(value)
    if value is None or value_type is bool:
        return value
    if value_type is int and not isinstance(value, bool):
        if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
            return {"unavailable": "integer_range"}
        return value
    if value_type is str:
        return value
    if value_type is float:
        return {"unavailable": "float"}
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                continue
            converted[key] = _plain_json_value(item, depth=depth + 1, max_depth=max_depth)
        return converted
    if isinstance(value, (list, tuple)):
        return [
            _plain_json_value(item, depth=depth + 1, max_depth=max_depth) for item in value
        ]
    return {"type": value_type.__name__, "unavailable": True}


def _logical_name(code: CodeType, globals_map: Mapping[str, Any] | None = None) -> str:
    module = ""
    if globals_map is not None:
        raw_module = globals_map.get("__name__")
        if type(raw_module) is str and raw_module and raw_module != "__main__":
            module = raw_module
    qualname = getattr(code, "co_qualname", code.co_name)
    if module:
        return f"{module}.{qualname}"
    return str(qualname)


def _filename_name(path: str) -> str:
    normalized = path.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1] or "unknown.py"


def default_environment_binding_cid(*, network_policy: str = "deny") -> str:
    """Bind the current Python runtime without host paths or process identity."""

    return cid_for_structured(
        {
            "schema": PYTHON_EXECUTION_ENVIRONMENT_SCHEMA,
            "language": ADMITTED_LANGUAGE,
            "implementation": sys.implementation.name,
            "major": sys.version_info.major,
            "minor": sys.version_info.minor,
            "micro": sys.version_info.micro,
            "network_policy": network_policy,
        }
    )


def _code_cid_for(code: CodeType, source_cid: str) -> str:
    return cid_for_structured(
        {
            "schema": PYTHON_CODE_IDENTITY_SCHEMA,
            "qualname": getattr(code, "co_qualname", code.co_name),
            "name": code.co_name,
            "firstlineno": code.co_firstlineno,
            "argcount": code.co_argcount,
            "filename": _filename_name(code.co_filename),
            "source_cid": source_cid,
        }
    )


def _subject_cid_for(logical_name: str, code_cid: str) -> str:
    return cid_for_structured(
        {
            "schema": PYTHON_SUBJECT_SCHEMA,
            "logical_name": logical_name,
            "code_cid": code_cid,
        }
    )


# ---------------------------------------------------------------------------
# Policy, cancellation, redaction
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Cost-bounded collection policy; line detail is optional and bounded."""

    max_events: int = DEFAULT_MAX_EVENTS
    max_frames: int = DEFAULT_MAX_FRAMES
    max_summary_items: int = DEFAULT_MAX_SUMMARY_ITEMS
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS
    max_summary_depth: int = DEFAULT_MAX_SUMMARY_DEPTH
    collect_line_events: bool = True
    collect_yield_events: bool = True
    collect_await_events: bool = True
    collect_external_events: bool = True
    capture_locals: bool = True
    deny_network: bool = True
    deny_subprocess: bool = True
    deny_installer: bool = True
    deny_database: bool = True
    deny_model_load: bool = True
    deny_watcher: bool = True
    network_policy: str = "deny"
    privacy_class: PrivacyClass | str = PrivacyClass.PRIVATE
    admitted_event_kinds: Sequence[str] = _ADMITTED_EVENT_KINDS

    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE
    SCHEMA: ClassVar[str] = TRACE_COLLECTION_POLICY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_events", _positive_int(self.max_events, "max_events", lo=1, hi=65_536)
        )
        object.__setattr__(
            self, "max_frames", _positive_int(self.max_frames, "max_frames", lo=1, hi=256)
        )
        object.__setattr__(
            self,
            "max_summary_items",
            _positive_int(self.max_summary_items, "max_summary_items", lo=1, hi=256),
        )
        object.__setattr__(
            self,
            "max_text_chars",
            _positive_int(self.max_text_chars, "max_text_chars", lo=8, hi=4_096),
        )
        object.__setattr__(
            self,
            "max_summary_depth",
            _positive_int(self.max_summary_depth, "max_summary_depth", lo=1, hi=8),
        )
        for flag in (
            "collect_line_events",
            "collect_yield_events",
            "collect_await_events",
            "collect_external_events",
            "capture_locals",
            "deny_network",
            "deny_subprocess",
            "deny_installer",
            "deny_database",
            "deny_model_load",
            "deny_watcher",
        ):
            object.__setattr__(self, flag, _bool(getattr(self, flag), flag))
        object.__setattr__(
            self, "network_policy", _text(self.network_policy, "network_policy")
        )
        if self.network_policy != "deny":
            raise PythonExecutionTraceError("network_policy must be 'deny' in this profile")
        privacy = (
            self.privacy_class.value
            if isinstance(self.privacy_class, PrivacyClass)
            else _text(self.privacy_class, "privacy_class")
        )
        try:
            privacy = PrivacyClass(privacy).value
        except ValueError as exc:
            raise PythonExecutionTraceError("privacy_class has an unsupported value") from exc
        object.__setattr__(self, "privacy_class", privacy)
        kinds = tuple(
            sorted({_text(kind, "admitted_event_kind") for kind in self.admitted_event_kinds})
        )
        unknown = [kind for kind in kinds if kind not in set(_ADMITTED_EVENT_KINDS)]
        if unknown:
            raise PythonExecutionTraceError(
                f"admitted_event_kinds contains unsupported kinds {unknown}"
            )
        object.__setattr__(self, "admitted_event_kinds", kinds)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "max_events": self.max_events,
            "max_frames": self.max_frames,
            "max_summary_items": self.max_summary_items,
            "max_text_chars": self.max_text_chars,
            "max_summary_depth": self.max_summary_depth,
            "collect_line_events": self.collect_line_events,
            "collect_yield_events": self.collect_yield_events,
            "collect_await_events": self.collect_await_events,
            "collect_external_events": self.collect_external_events,
            "capture_locals": self.capture_locals,
            "deny_network": self.deny_network,
            "deny_subprocess": self.deny_subprocess,
            "deny_installer": self.deny_installer,
            "deny_database": self.deny_database,
            "deny_model_load": self.deny_model_load,
            "deny_watcher": self.deny_watcher,
            "network_policy": self.network_policy,
            "privacy_class": self.privacy_class,
            "admitted_event_kinds": list(self.admitted_event_kinds),
        }

    @property
    def capture_profile_cid(self) -> str:
        return cid_for_structured(
            {"schema": CAPTURE_PROFILE_SCHEMA, "policy": self.identity_payload()}
        )

    def admits(self, kind: str) -> bool:
        return kind in self.admitted_event_kinds


class TraceCancellation:
    """Cooperative cancellation token; cancelled traces emit no accepted transition."""

    INTERFACE: ClassVar[str] = TRACE_CANCELLATION_INTERFACE

    def __init__(self) -> None:
        self._requested = False
        self._reason = "cancelled"

    def cancel(self, reason: str = "cancelled") -> None:
        self._requested = True
        self._reason = _text(reason, "cancellation reason")

    @property
    def requested(self) -> bool:
        return self._requested

    @property
    def reason(self) -> str:
        return self._reason


@dataclass(frozen=True, slots=True)
class TraceRedactor:
    """Fail-closed redaction; public records never include raw bodies or secrets."""

    profile: RedactionProfile | None = None
    extra_secret_markers: Sequence[str] = ()

    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE

    def __post_init__(self) -> None:
        markers = tuple(
            sorted({_text(item, "secret marker") for item in self.extra_secret_markers})
        )
        object.__setattr__(self, "extra_secret_markers", markers)
        if self.profile is None:
            object.__setattr__(
                self,
                "profile",
                RedactionProfile(
                    privacy_class=PrivacyClass.PUBLIC,
                    redacted_dimensions=("raw_body", "secrets"),
                    completeness_claim=CompletenessClaim.REDACTED,
                ),
            )
        elif not isinstance(self.profile, RedactionProfile):
            raise PythonExecutionTraceError("profile must be a RedactionProfile")

    def is_secret_key(self, key: str) -> bool:
        if type(key) is not str:
            return True
        if _is_secret_key(key):
            return True
        lowered = key.strip().lower().replace("-", "_")
        return any(marker in lowered for marker in self.extra_secret_markers)

    def redact_mapping(
        self, value: Mapping[str, Any] | None
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        if value is None:
            return {}, ()
        if not isinstance(value, Mapping):
            raise PythonExecutionTraceError("redaction requires a mapping")
        redacted: list[str] = []
        kept: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str or self.is_secret_key(key):
                redacted.append(key if type(key) is str else "non_string_key")
                continue
            if isinstance(item, Mapping):
                child, child_redacted = self.redact_mapping(item)
                kept[key] = child
                redacted.extend(f"{key}.{name}" for name in child_redacted)
            else:
                kept[key] = item
        return kept, tuple(sorted(set(redacted)))

    def public_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        if not isinstance(trace, ExecutionTrace):
            raise PythonExecutionTraceError("public_trace requires an ExecutionTrace")
        return trace.public_view()

    def public_record(self, record: "PythonExecutionTraceRecord") -> dict[str, Any]:
        if not isinstance(record, PythonExecutionTraceRecord):
            raise PythonExecutionTraceError(
                "public_record requires a PythonExecutionTraceRecord"
            )
        payload = record.public_record()
        if payload.get("includes_raw_bodies") is True:
            raise PythonExecutionTraceError(
                "raw bodies remain private and cannot enter public records"
            )
        if payload.get("privacy_class") not in {PrivacyClass.PUBLIC.value, PrivacyClass.INTERNAL.value}:
            raise PythonExecutionTraceError("public records must use a public privacy class")
        encoded = repr(payload)
        for marker in SECRET_FIELD_MARKERS:
            if f"'{marker}'" in encoded and "redacted" not in encoded:
                # Secret *keys* may appear in redacted_dimensions; values must not.
                pass
        return payload


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceRecord:
    """In-process hermetic trace; :meth:`public_record` never carries raw bodies."""

    status: str
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    capture_profile_cid: str
    private_trace: ExecutionTrace
    public_trace: ExecutionTrace
    events: tuple[ProgramEvent, ...]
    states: tuple[ProgramExecutionState, ...]
    observations: tuple[ExecutionObservation, ...]
    replay_promised: bool
    cancellation_requested: bool
    isolation_denied: bool
    truncated: bool
    result_summary: Mapping[str, Any] = field(default_factory=dict)
    unavailable_dimensions: tuple[str, ...] = ()
    accepted_transition_cid: str | None = None

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECORD_INTERFACE
    SCHEMA: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECORD_SCHEMA
    EVIDENCE: ClassVar[str] = HERMETIC_TRACE_EVIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _text(self.status, "status"))
        try:
            TraceStatus(self.status)
        except ValueError as exc:
            raise PythonExecutionTraceError(f"unsupported trace status {self.status!r}") from exc
        object.__setattr__(self, "replay_promised", _bool(self.replay_promised, "replay_promised"))
        object.__setattr__(
            self,
            "cancellation_requested",
            _bool(self.cancellation_requested, "cancellation_requested"),
        )
        object.__setattr__(
            self, "isolation_denied", _bool(self.isolation_denied, "isolation_denied")
        )
        object.__setattr__(self, "truncated", _bool(self.truncated, "truncated"))
        if self.accepted_transition_cid is not None:
            raise PythonExecutionTraceError(
                "hermetic tracing does not persist operational acceptance"
            )
        if self.cancellation_requested and self.accepted_transition_cid is not None:
            raise PythonExecutionTraceError("cancellation emits no accepted transition")
        if self.public_trace.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "raw bodies remain private and cannot enter public records"
            )
        if self.public_trace.privacy_class != PrivacyClass.PUBLIC.value:
            raise PythonExecutionTraceError("public traces must use privacy_class public")
        object.__setattr__(
            self, "result_summary", MappingProxyType(dict(self.result_summary))
        )
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "states", tuple(self.states))
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(self, "unavailable_dimensions", tuple(self.unavailable_dimensions))

    def public_identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "evidence": self.EVIDENCE,
            "status": self.status,
            "language": ADMITTED_LANGUAGE,
            "tree_cid": self.tree_cid,
            "source_cid": self.source_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "capture_profile_cid": self.capture_profile_cid,
            "execution_trace_cid": self.public_trace.execution_trace_cid,
            "event_cids": list(self.public_trace.event_cids),
            "event_kinds": [event.event_kind for event in self.events],
            "logical_names": [event.logical_name for event in self.events],
            "replay_promised": self.replay_promised,
            "accepted_transition_cid": None,
            "includes_raw_bodies": False,
            "privacy_class": PrivacyClass.PUBLIC.value,
            "completeness_claim": self.public_trace.completeness_claim,
            "redacted_dimensions": list(self.public_trace.redacted_dimensions),
            "unavailable_dimensions": list(self.public_trace.unavailable_dimensions),
            "cancellation_requested": self.cancellation_requested,
            "isolation_denied": self.isolation_denied,
            "truncated": self.truncated,
            "result_summary": dict(self.result_summary),
        }

    @property
    def python_execution_trace_record_cid(self) -> str:
        return cid_for_structured(self.public_identity_payload())

    def public_record(self) -> dict[str, Any]:
        payload = self.public_identity_payload()
        payload["python_execution_trace_record_cid"] = self.python_execution_trace_record_cid
        payload["public_trace"] = self.public_trace.to_dict()
        return payload

    def to_dict(self) -> dict[str, Any]:
        """Return the public record.  Private raw bodies are not serialized."""

        return self.public_record()


@dataclass(frozen=True, slots=True)
class TraceReplayReceipt:
    """Deterministic promised-replay comparison; never self-admits a transition."""

    original_trace_cid: str
    replayed_trace_cid: str | None
    matched: bool
    promised: bool
    event_kind_sequence_equal: bool
    binding_equal: bool
    unavailable_dimensions: tuple[str, ...] = ()
    accepted_transition_cid: str | None = None

    INTERFACE: ClassVar[str] = TRACE_REPLAY_RECEIPT_INTERFACE
    SCHEMA: ClassVar[str] = TRACE_REPLAY_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "matched", _bool(self.matched, "matched"))
        object.__setattr__(self, "promised", _bool(self.promised, "promised"))
        object.__setattr__(
            self,
            "event_kind_sequence_equal",
            _bool(self.event_kind_sequence_equal, "event_kind_sequence_equal"),
        )
        object.__setattr__(self, "binding_equal", _bool(self.binding_equal, "binding_equal"))
        object.__setattr__(self, "unavailable_dimensions", tuple(self.unavailable_dimensions))
        if self.accepted_transition_cid is not None:
            raise PythonExecutionTraceError(
                "replay does not persist operational acceptance"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "original_trace_cid": self.original_trace_cid,
            "replayed_trace_cid": self.replayed_trace_cid,
            "matched": self.matched,
            "promised": self.promised,
            "event_kind_sequence_equal": self.event_kind_sequence_equal,
            "binding_equal": self.binding_equal,
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "accepted_transition_cid": None,
        }

    @property
    def trace_replay_receipt_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["trace_replay_receipt_cid"] = self.trace_replay_receipt_cid
        return payload


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class PythonExecutionTracer:
    """In-process ``sys.settrace`` collector with hermetic isolation."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE

    def __init__(
        self,
        *,
        policy: TraceCollectionPolicy | None = None,
        cancellation: TraceCancellation | None = None,
        tree_cid: str | None = None,
        source: str | bytes | None = None,
        environment_binding_cid: str | None = None,
        redactor: TraceRedactor | None = None,
    ) -> None:
        self.policy = policy if policy is not None else TraceCollectionPolicy()
        if not isinstance(self.policy, TraceCollectionPolicy):
            raise PythonExecutionTraceError("policy must be a TraceCollectionPolicy")
        self.cancellation = cancellation
        if cancellation is not None and not isinstance(cancellation, TraceCancellation):
            raise PythonExecutionTraceError("cancellation must be a TraceCancellation")
        self._source_override = source
        self._tree_override = tree_cid
        self._env_override = environment_binding_cid
        self.redactor = redactor if redactor is not None else TraceRedactor()
        if not isinstance(self.redactor, TraceRedactor):
            raise PythonExecutionTraceError("redactor must be a TraceRedactor")
        self._reset_runtime()

    def _reset_runtime(self) -> None:
        self._events: list[ProgramEvent] = []
        self._states: list[ProgramExecutionState] = []
        self._observations: list[ExecutionObservation] = []
        self._opcode_cache: dict[CodeType, dict[int, str]] = {}
        self._code_cids: dict[CodeType, str] = {}
        self._stop = False
        self._cancelled = False
        self._isolated = False
        self._truncated = False
        self._failed: str | None = None
        self._pending_exception: tuple[type[BaseException], BaseException, TracebackType | None] | None = None
        self._pending_exception_frames: list[StackFrameState] = []
        self._last_handler: HandlerState | None = None
        self._last_exception: ExceptionSnapshot | None = None
        self._redacted_dimensions: set[str] = set()
        self._unavailable: set[str] = {"heap", "native_stack"}
        self._result_summary: dict[str, Any] = {}
        self._isolation_patches: list[tuple[str, Any, str, Any]] = []
        self._original_import: Any = None
        self._denied_module: str | None = None
        self._target: Callable[..., Any] | None = None
        self._target_filename = ""
        self._tree_cid = ""
        self._source_cid = ""
        self._env_cid = ""
        self._capture_cid = self.policy.capture_profile_cid
        self._subject_source_unavailable = False
        self._seen_call_frames: set[int] = set()

    def record(
        self,
        target: Callable[..., Any],
        *,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> PythonExecutionTraceRecord:
        if not callable(target):
            raise PythonExecutionTraceError("target must be callable")
        self._reset_runtime()
        self._target = target
        self._target_filename = getattr(getattr(target, "__code__", None), "co_filename", "")
        source_bytes, source_unavailable = self._resolve_source(target)
        self._source_cid = cid_for_bytes(source_bytes)
        self._subject_source_unavailable = source_unavailable
        if source_unavailable:
            self._unavailable.add("source_text")
        self._tree_cid = self._tree_override or cid_for_structured(
            {"schema": HERMETIC_TREE_SCHEMA, "source_cid": self._source_cid}
        )
        self._env_cid = self._env_override or default_environment_binding_cid(
            network_policy=self.policy.network_policy
        )
        call_kwargs = {} if kwargs is None else dict(kwargs)
        if self.cancellation is not None and self.cancellation.requested:
            self._cancelled = True
            self._append_event(
                kind=EventKind.UNAVAILABLE.value,
                frame=None,
                payload={"reason": self.cancellation.reason},
                observation_status=ObservationStatus.UNAVAILABLE,
                completeness_claim=CompletenessClaim.UNAVAILABLE,
                extra_unavailable=("execution", "accepted_transition"),
                code=getattr(target, "__code__", None),
            )
            return self._finish(TraceStatus.CANCELLED.value)

        previous_trace = sys.gettrace()
        try:
            self._install_isolation()
            self._append_event(
                kind=EventKind.ENTER.value,
                frame=None,
                payload={"callee": _logical_name(target.__code__, getattr(target, "__globals__", {}))},
                code=target.__code__,
                globals_map=getattr(target, "__globals__", None),
                line=target.__code__.co_firstlineno,
            )
            if self._stop:
                return self._finish(self._status_after_run())
            sys.settrace(self._trace)
            try:
                result = self._invoke(target, tuple(args), call_kwargs)
            finally:
                sys.settrace(previous_trace)
            self._result_summary = self._summarize_result(result)
            if not self._stop:
                self._append_event(
                    kind=EventKind.EXIT.value,
                    frame=None,
                    payload={"callee": _logical_name(target.__code__, getattr(target, "__globals__", {}))},
                    code=target.__code__,
                    globals_map=getattr(target, "__globals__", None),
                    line=target.__code__.co_firstlineno,
                )
        except HermeticIsolationError as exc:
            self._isolated = True
            self._denied_module = getattr(exc, "module", None) or self._denied_module
            self._append_external_denied(str(exc))
        except TraceCancelledError:
            self._cancelled = True
        except PythonExecutionTraceError as exc:
            self._failed = str(exc)
            self._unavailable.add("tracer")
        except Exception as exc:
            self._result_summary = {
                "exception_type": type(exc).__name__,
                "bounded": True,
            }
            if self._pending_exception is None and not any(
                event.event_kind == EventKind.RAISE.value for event in self._events
            ):
                self._append_event(
                    kind=EventKind.RAISE.value,
                    frame=None,
                    payload={"exception_type": type(exc).__name__},
                    code=getattr(target, "__code__", None),
                    extra_unavailable=("exception", "call_stack"),
                    completeness_claim=CompletenessClaim.PARTIAL,
                )
        finally:
            sys.settrace(previous_trace)
            self._remove_isolation()
        return self._finish(self._status_after_run())

    def _status_after_run(self) -> str:
        if self._cancelled:
            return TraceStatus.CANCELLED.value
        if self._isolated:
            return TraceStatus.ISOLATED.value
        if self._failed is not None:
            return TraceStatus.FAILED.value
        if self._truncated:
            return TraceStatus.TRUNCATED.value
        return TraceStatus.COMPLETED.value

    def _resolve_source(self, target: Callable[..., Any]) -> tuple[bytes, bool]:
        if self._source_override is not None:
            return _source_bytes(self._source_override), False
        try:
            return inspect.getsource(target).encode("utf-8"), False
        except (OSError, TypeError):
            fallback = f"# source unavailable for {getattr(target, '__qualname__', repr(target))}\n"
            return fallback.encode("utf-8"), True

    def _invoke(
        self,
        target: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        if inspect.iscoroutinefunction(target):
            import asyncio

            coroutine = target(*args, **kwargs)
            frame = getattr(coroutine, "cr_frame", None)
            if frame is not None:
                frame.f_trace = self._trace
            sys.settrace(self._trace)
            return asyncio.run(coroutine)
        if inspect.isasyncgenfunction(target):
            import asyncio

            async def _consume_async() -> list[Any]:
                collected: list[Any] = []
                agen = target(*args, **kwargs)
                agen_frame = getattr(agen, "ag_frame", None)
                if agen_frame is not None:
                    agen_frame.f_trace = self._trace
                try:
                    async for item in agen:
                        collected.append(item)
                        if len(collected) >= self.policy.max_events:
                            self._truncated = True
                            break
                finally:
                    await agen.aclose()
                return collected

            sys.settrace(self._trace)
            return asyncio.run(_consume_async())
        if inspect.isgeneratorfunction(target):
            generator = target(*args, **kwargs)
            collected: list[Any] = []
            try:
                for _ in range(self.policy.max_events + 1):
                    collected.append(next(generator))
                self._truncated = True
                generator.close()
            except StopIteration as stop:
                if stop.value is not None:
                    return {"yielded": collected, "returned": stop.value}
            return collected
        return target(*args, **kwargs)

    def _install_isolation(self) -> None:
        self._original_import = builtins.__import__
        tracer = self

        def isolated_import(name: str, *args: Any, **kwargs: Any) -> Any:
            root = name.split(".", 1)[0]
            denied = False
            if tracer.policy.deny_network and (
                root in {"socket", "_socket", "ssl", "_ssl", "requests", "aiohttp", "httpx"}
                or name in {"urllib.request", "http.client", "http.server"}
            ):
                denied = True
            if tracer.policy.deny_subprocess and root in {"subprocess", "multiprocessing"}:
                denied = True
            if tracer.policy.deny_installer and root in {"pip", "ensurepip"}:
                denied = True
            if tracer.policy.deny_database and root in {
                "sqlite3",
                "duckdb",
                "psycopg2",
                "pymongo",
                "sqlalchemy",
            }:
                denied = True
            if tracer.policy.deny_model_load and root in {
                "torch",
                "transformers",
                "tensorflow",
                "huggingface_hub",
            }:
                denied = True
            if tracer.policy.deny_watcher and root in {"watchdog"}:
                denied = True
            if name in _DENIED_IMPORT_ROOTS or denied:
                error = HermeticIsolationError(f"hermetic isolation denied import {name}")
                error.module = name  # type: ignore[attr-defined]
                tracer._denied_module = name
                raise error
            return tracer._original_import(name, *args, **kwargs)

        builtins.__import__ = isolated_import
        # Patch only the subject's globals.  Process-wide stdlib monkeypatching
        # would bypass isolation boundaries and can disturb the test harness.
        target_globals = getattr(self._target, "__globals__", None)
        if isinstance(target_globals, dict):
            for name in ("socket", "subprocess", "ssl", "sqlite3", "duckdb"):
                if name in target_globals:
                    original = target_globals[name]
                    target_globals[name] = _DeniedImport(name, tracer)
                    self._isolation_patches.append(("mapping", target_globals, name, original))

    def _remove_isolation(self) -> None:
        if self._original_import is not None:
            builtins.__import__ = self._original_import
            self._original_import = None
        while self._isolation_patches:
            kind, owner, attribute, original = self._isolation_patches.pop()
            if kind == "mapping":
                owner[attribute] = original
            else:
                setattr(owner, attribute, original)

    def _should_trace(self, frame: FrameType) -> bool:
        if frame.f_code.co_filename == _MODULE_FILENAME:
            return False
        if self._target is None:
            return False
        if frame.f_code is self._target.__code__:
            return True
        if self._target_filename and frame.f_code.co_filename == self._target_filename:
            return True
        current: FrameType | None = frame
        while current is not None:
            if current.f_code is self._target.__code__:
                return True
            current = current.f_back
        return False

    def _opname(self, frame: FrameType) -> str | None:
        code = frame.f_code
        table = self._opcode_cache.get(code)
        if table is None:
            table = {instruction.offset: instruction.opname for instruction in dis.get_instructions(code)}
            self._opcode_cache[code] = table
        lasti = frame.f_lasti
        if lasti in table:
            return table[lasti]
        best: int | None = None
        for offset in table:
            if offset <= lasti and (best is None or offset > best):
                best = offset
        return table.get(best) if best is not None else None

    def _ensure_call_event(self, frame: FrameType) -> None:
        """Admit one CALL per Python frame, including coroutine first-resume."""

        frame_id = id(frame)
        if frame_id in self._seen_call_frames:
            return
        self._seen_call_frames.add(frame_id)
        self._append_event(
            kind=EventKind.CALL.value,
            frame=frame,
            payload={"callee": _logical_name(frame.f_code, frame.f_globals)},
        )

    def _trace(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if self._stop:
            return None
        if not self._should_trace(frame):
            return None
        frame.f_trace = self._trace
        if self.cancellation is not None and self.cancellation.requested:
            self._cancelled = True
            self._stop = True
            return None
        try:
            if event in {"call", "line", "return", "exception"}:
                self._ensure_call_event(frame)
            if event == "return":
                opcode = self._opname(frame)
                flags = frame.f_code.co_flags
                if self.policy.collect_yield_events and flags & (
                    inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR
                ):
                    if opcode in {"RETURN_VALUE", "RETURN_GENERATOR"}:
                        kind = EventKind.RETURN.value
                    else:
                        kind = EventKind.YIELD.value
                    self._append_event(
                        kind=kind,
                        frame=frame,
                        payload={"callee": _logical_name(frame.f_code, frame.f_globals)},
                    )
                elif self.policy.collect_await_events and flags & inspect.CO_COROUTINE:
                    kind = (
                        EventKind.RETURN.value
                        if opcode in {"RETURN_VALUE", "RETURN_GENERATOR"}
                        else EventKind.AWAIT.value
                    )
                    self._append_event(
                        kind=kind,
                        frame=frame,
                        payload={"callee": _logical_name(frame.f_code, frame.f_globals)},
                    )
                else:
                    self._append_event(
                        kind=EventKind.RETURN.value,
                        frame=frame,
                        payload={"callee": _logical_name(frame.f_code, frame.f_globals)},
                    )
            elif event == "exception":
                exc_type = arg[0] if isinstance(arg, tuple) and arg else None
                if exc_type not in {StopIteration, StopAsyncIteration, GeneratorExit}:
                    self._pending_exception = arg
                    self._append_raise(frame, arg)
            elif event == "line":
                if self._pending_exception is not None:
                    self._append_handler(frame)
                    self._pending_exception = None
                opcode = self._opname(frame)
                if self.policy.collect_await_events and opcode in _AWAIT_OPCODES:
                    self._append_event(
                        kind=EventKind.AWAIT.value,
                        frame=frame,
                        payload={"opcode": opcode},
                    )
                if self.policy.collect_line_events:
                    self._append_event(
                        kind=EventKind.LINE.value,
                        frame=frame,
                        payload={"line": frame.f_lineno},
                    )
        except HermeticIsolationError:
            raise
        except Exception as exc:
            self._failed = type(exc).__name__
            self._unavailable.add("tracer")
            self._stop = True
            return None
        if self._stop:
            return None
        return self._trace

    def _code_cid(self, code: CodeType) -> str:
        cached = self._code_cids.get(code)
        if cached is not None:
            return cached
        cid = _code_cid_for(code, self._source_cid)
        self._code_cids[code] = cid
        return cid

    def _stack_frames(self, frame: FrameType | None) -> tuple[StackFrameState, ...]:
        if frame is None:
            if self._target is None:
                return ()
            code = self._target.__code__
            logical = _logical_name(code, getattr(self._target, "__globals__", {}))
            summary, redacted, unavailable, claim = self._frame_summary(None)
            self._redacted_dimensions.update(redacted)
            return (
                StackFrameState(
                    ordinal=0,
                    language=ADMITTED_LANGUAGE,
                    tree_cid=self._tree_cid,
                    source_cid=self._source_cid,
                    code_cid=self._code_cid(code),
                    environment_binding_cid=self._env_cid,
                    logical_name=logical,
                    line=code.co_firstlineno,
                    column=0,
                    state_summary=summary,
                    redacted_dimensions=redacted,
                    unavailable_dimensions=unavailable,
                    completeness_claim=claim,
                    privacy_class=PrivacyClass.INTERNAL,
                ),
            )
        walked: list[FrameType] = []
        current: FrameType | None = frame
        while current is not None and len(walked) < self.policy.max_frames:
            if current.f_code.co_filename == _MODULE_FILENAME:
                break
            if self._should_trace(current):
                walked.append(current)
            current = current.f_back
        frames: list[StackFrameState] = []
        for ordinal, item in enumerate(walked):
            summary, redacted, unavailable, claim = self._frame_summary(item)
            self._redacted_dimensions.update(redacted)
            frames.append(
                StackFrameState(
                    ordinal=ordinal,
                    language=ADMITTED_LANGUAGE,
                    tree_cid=self._tree_cid,
                    source_cid=self._source_cid,
                    code_cid=self._code_cid(item.f_code),
                    environment_binding_cid=self._env_cid,
                    logical_name=_logical_name(item.f_code, item.f_globals),
                    line=item.f_lineno,
                    column=0,
                    state_summary=summary,
                    redacted_dimensions=redacted,
                    unavailable_dimensions=unavailable,
                    completeness_claim=claim,
                    privacy_class=PrivacyClass.INTERNAL,
                )
            )
        return tuple(frames)

    def _frame_summary(
        self, frame: FrameType | None
    ) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...], str]:
        if not self.policy.capture_locals or frame is None:
            return {}, (), ("locals",), CompletenessClaim.PARTIAL.value
        raw_locals = {}
        try:
            raw_locals = dict(frame.f_locals)
        except Exception:
            return {}, (), ("locals",), CompletenessClaim.PARTIAL.value
        summarized, redacted = self._summarize_mapping(raw_locals)
        unavailable: tuple[str, ...]
        if redacted:
            claim = CompletenessClaim.REDACTED.value
            unavailable = ()
        else:
            claim = CompletenessClaim.PARTIAL.value
            unavailable = ("heap",)
        return {"locals": summarized}, redacted, unavailable, claim

    def _summarize_mapping(
        self, value: Mapping[str, Any], *, depth: int = 0
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        redacted: list[str] = []
        kept: dict[str, Any] = {}
        count = 0
        for key, item in value.items():
            if count >= self.policy.max_summary_items:
                break
            if type(key) is not str:
                continue
            if key.startswith("__"):
                continue
            if self.redactor.is_secret_key(key):
                redacted.append(key)
                continue
            summarized = self._summarize_value(item, depth=depth)
            if summarized is _UNREPRESENTABLE:
                continue
            kept[key] = _plain_json_value(summarized)
            count += 1
        return kept, tuple(sorted(set(redacted)))

    def _summarize_value(self, value: Any, *, depth: int) -> Any:
        if depth >= self.policy.max_summary_depth:
            return {"unavailable": "depth"}
        value_type = type(value)
        if value is None or value_type is bool:
            return value
        if value_type is int and not isinstance(value, bool):
            if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
                return {"unavailable": "integer_range"}
            return value
        if value_type is str:
            if len(value) > self.policy.max_text_chars:
                return value[: self.policy.max_text_chars]
            return value
        if value_type is float:
            return {"unavailable": "float"}
        if value_type is list:
            return [
                self._summarize_value(item, depth=depth + 1)
                for item in value[: self.policy.max_summary_items]
            ]
        if value_type is tuple:
            return [
                self._summarize_value(item, depth=depth + 1)
                for item in value[: self.policy.max_summary_items]
            ]
        if value_type is dict:
            nested, _redacted = self._summarize_mapping(value, depth=depth + 1)
            return nested
        if inspect.isfunction(value) or inspect.ismethod(value) or inspect.isclass(value):
            name = getattr(value, "__qualname__", type(value).__name__)
            return {"type": type(value).__name__, "name": str(name)}
        return {"type": value_type.__name__, "unavailable": True}

    def _summarize_result(self, result: Any) -> dict[str, Any]:
        summarized = _plain_json_value(self._summarize_value(result, depth=0))
        if isinstance(summarized, dict):
            return summarized
        return {"value": summarized}

    def _append_raise(
        self,
        frame: FrameType,
        arg: tuple[type[BaseException], BaseException, TracebackType | None],
    ) -> None:
        exc_type, _exc, traceback = arg
        frames = self._stack_frames(frame)
        self._pending_exception_frames = list(frames)
        try:
            snapshot = ExceptionSnapshot(
                language=ADMITTED_LANGUAGE,
                exception_type=exc_type.__name__,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                code_cid=self._code_cid(frame.f_code),
                environment_binding_cid=self._env_cid,
                exception_value_summary={"type": exc_type.__name__, "bounded": True},
                traceback_stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
                unavailable_dimensions=() if frames else ("call_stack",),
                completeness_claim=(
                    CompletenessClaim.FULL_STATE if frames else CompletenessClaim.PARTIAL
                ),
            )
        except ProgramExecutionError:
            self._append_event(
                kind=EventKind.RAISE.value,
                frame=frame,
                payload={"exception_type": exc_type.__name__},
                frames=frames,
                extra_unavailable=("exception",),
                completeness_claim=CompletenessClaim.PARTIAL,
            )
            return
        self._last_exception = snapshot
        self._append_event(
            kind=EventKind.RAISE.value,
            frame=frame,
            payload={"exception_type": exc_type.__name__},
            exception=snapshot,
            frames=frames,
        )

    def _handler_kind_at(self, frame: FrameType) -> str:
        source_line = linecache.getline(frame.f_code.co_filename, frame.f_lineno)
        stripped = source_line.strip()
        if stripped.startswith("except*"):
            return HandlerKind.EXCEPT_STAR.value
        if stripped.startswith("except"):
            return HandlerKind.EXCEPT.value
        if stripped.startswith("finally"):
            return HandlerKind.FINALLY.value
        if stripped.startswith("else"):
            return HandlerKind.ELSE.value
        return HandlerKind.EXCEPT.value

    def _append_handler(self, frame: FrameType) -> None:
        kind = self._handler_kind_at(frame)
        frames = self._stack_frames(frame)
        matching = (
            None if self._last_exception is None else self._last_exception.exception_snapshot_cid
        )
        try:
            handler = HandlerState(
                language=ADMITTED_LANGUAGE,
                handler_kind=kind,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                code_cid=self._code_cid(frame.f_code),
                environment_binding_cid=self._env_cid,
                logical_name=_logical_name(frame.f_code, frame.f_globals),
                stack_ordinal=0,
                handler_active=True,
                matching_exception_snapshot_cid=matching,
                unavailable_dimensions=() if matching is not None else ("exception",),
            )
        except ProgramExecutionError:
            self._append_event(
                kind=EventKind.CATCH.value,
                frame=frame,
                payload={"handler_kind": kind},
                frames=frames,
                extra_unavailable=("handler",),
                completeness_claim=CompletenessClaim.PARTIAL,
            )
            return
        self._last_handler = handler
        event_kind = (
            EventKind.HANDLER.value
            if kind in {HandlerKind.FINALLY.value, HandlerKind.ELSE.value}
            else EventKind.CATCH.value
        )
        self._append_event(
            kind=event_kind,
            frame=frame,
            payload={"handler_kind": kind},
            handler=handler,
            frames=frames,
            exception=self._last_exception,
        )
        if event_kind == EventKind.CATCH.value and self.policy.admits(EventKind.HANDLER.value):
            self._append_event(
                kind=EventKind.HANDLER.value,
                frame=frame,
                payload={"handler_kind": kind},
                handler=handler,
                frames=frames,
                exception=self._last_exception,
            )

    def _append_external_denied(self, message: str) -> None:
        if not self.policy.collect_external_events or not self.policy.admits(
            EventKind.EXTERNAL.value
        ):
            return
        module = self._denied_module or "external"
        self._append_event(
            kind=EventKind.EXTERNAL.value,
            frame=None,
            payload={
                "effect": module,
                "disposition": "denied",
                "reason": message[: self.policy.max_text_chars],
            },
            observation_status=ObservationStatus.UNAVAILABLE,
            completeness_claim=CompletenessClaim.PARTIAL,
            extra_unavailable=("external_effect",),
            code=getattr(self._target, "__code__", None) if self._target is not None else None,
        )

    def _append_event(
        self,
        *,
        kind: str,
        frame: FrameType | None,
        payload: Mapping[str, Any] | None = None,
        observation_status: ObservationStatus | str = ObservationStatus.OBSERVED,
        completeness_claim: CompletenessClaim | str = CompletenessClaim.FULL_STATE,
        extra_unavailable: Sequence[str] = (),
        code: CodeType | None = None,
        globals_map: Mapping[str, Any] | None = None,
        line: int | None = None,
        exception: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
        frames: Sequence[StackFrameState] | None = None,
    ) -> None:
        if self._stop:
            return
        if not self.policy.admits(kind):
            return
        if len(self._events) >= self.policy.max_events:
            self._truncated = True
            self._stop = True
            self._unavailable.add("truncated_events")
            return
        stack = tuple(frames) if frames is not None else self._stack_frames(frame)
        event_code = code
        event_globals = globals_map
        event_line = line
        if frame is not None:
            event_code = frame.f_code
            event_globals = frame.f_globals
            event_line = frame.f_lineno
        if event_code is None and self._target is not None:
            event_code = self._target.__code__
            event_globals = getattr(self._target, "__globals__", {})
            event_line = event_code.co_firstlineno if event_line is None else event_line
        if event_code is None:
            return
        logical = _logical_name(event_code, event_globals)
        code_cid = self._code_cid(event_code)
        predecessor = None if not self._events else self._events[-1].program_event_cid
        unavailable = list(extra_unavailable)
        if not stack and kind in {
            EventKind.CALL.value,
            EventKind.RETURN.value,
            EventKind.RAISE.value,
            EventKind.CATCH.value,
            EventKind.HANDLER.value,
            EventKind.YIELD.value,
            EventKind.AWAIT.value,
            EventKind.ENTER.value,
            EventKind.EXIT.value,
        }:
            unavailable.append("call_stack")
        claim = completeness_claim
        if unavailable and str(claim) == CompletenessClaim.FULL_STATE.value:
            claim = CompletenessClaim.PARTIAL
        redacted = tuple(sorted(self._redacted_dimensions))
        if redacted and str(claim) == CompletenessClaim.FULL_STATE.value:
            claim = CompletenessClaim.REDACTED
        event_payload, payload_redacted = self.redactor.redact_mapping(
            _plain_json_value({} if payload is None else dict(payload))
        )
        event_payload = _plain_json_value(event_payload)
        if payload_redacted:
            redacted = tuple(sorted(set(redacted) | set(payload_redacted)))
            if str(claim) == CompletenessClaim.FULL_STATE.value:
                claim = CompletenessClaim.REDACTED
        try:
            event = ProgramEvent(
                event_kind=kind,
                event_origin=EventOrigin.OBSERVED,
                observation_status=observation_status,
                language=ADMITTED_LANGUAGE,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                code_cid=code_cid,
                environment_binding_cid=self._env_cid,
                subject_cid=_subject_cid_for(logical, code_cid),
                logical_name=logical,
                payload=event_payload,
                line=event_line,
                column=0 if event_line is not None else None,
                predecessor_event_cid=predecessor,
                stack_frame_cids=tuple(item.stack_frame_state_cid for item in stack),
                exception_snapshot_cid=(
                    None if exception is None else exception.exception_snapshot_cid
                ),
                handler_state_cid=None if handler is None else handler.handler_state_cid,
                redaction_profile_cid=self.redactor.profile.redaction_profile_cid,
                redacted_dimensions=redacted,
                unavailable_dimensions=tuple(sorted(set(unavailable))),
                completeness_claim=claim,
                privacy_class=PrivacyClass.INTERNAL,
            )
        except ProgramExecutionError:
            event = ProgramEvent(
                event_kind=EventKind.UNAVAILABLE.value,
                event_origin=EventOrigin.OBSERVED,
                observation_status=ObservationStatus.UNAVAILABLE,
                language=ADMITTED_LANGUAGE,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                code_cid=code_cid,
                environment_binding_cid=self._env_cid,
                subject_cid=_subject_cid_for(logical, code_cid),
                logical_name=logical,
                payload={"reason": "event_validation_failed"},
                line=event_line,
                column=0 if event_line is not None else None,
                predecessor_event_cid=predecessor,
                stack_frame_cids=tuple(item.stack_frame_state_cid for item in stack),
                unavailable_dimensions=("event_body",),
                completeness_claim=CompletenessClaim.UNAVAILABLE,
                privacy_class=PrivacyClass.INTERNAL,
            )
        payload_dict = _plain_json_value(event.payload)
        try:
            json.dumps(payload_dict, allow_nan=False)
        except (TypeError, ValueError):
            payload_dict = {"unavailable": "payload"}
        object.__setattr__(event, "payload", payload_dict)
        self._events.append(event)
        if self.policy.capture_locals and stack:
            self._capture_state(stack, exception=exception, handler=handler)
        if (
            str(event.event_origin) == EventOrigin.OBSERVED.value
            and str(event.observation_status) == ObservationStatus.OBSERVED.value
            and event.event_kind != EventKind.UNAVAILABLE.value
        ):
            try:
                self._observations.append(observe_program_event(event))
            except ProgramExecutionError:
                pass

    def _capture_state(
        self,
        frames: Sequence[StackFrameState],
        *,
        exception: ExceptionSnapshot | None,
        handler: HandlerState | None,
    ) -> None:
        if not frames:
            return
        observed: dict[str, Any] = {}
        redacted: list[str] = []
        innermost = frames[0]
        if "locals" in innermost.state_summary:
            locals_value = innermost.state_summary["locals"]
            if isinstance(locals_value, Mapping):
                observed, extra_redacted = self.redactor.redact_mapping(
                    _plain_json_value(locals_value)
                )
                observed = _plain_json_value(observed)
                redacted.extend(extra_redacted)
        includes_raw = bool(observed)
        privacy = PrivacyClass.PRIVATE if includes_raw else PrivacyClass.INTERNAL
        claim = CompletenessClaim.PARTIAL
        redacted_dims = tuple(sorted(set(redacted) | set(innermost.redacted_dimensions)))
        if redacted_dims:
            claim = CompletenessClaim.REDACTED
        unavailable = tuple(sorted(set(innermost.unavailable_dimensions) | {"heap", "native_stack"}))
        try:
            state = assemble_program_execution_state(
                capture_profile_cid=self._capture_cid,
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                environment_binding_cid=self._env_cid,
                frames=frames,
                observed_state=observed,
                heap_bound=HeapBound.UNAVAILABLE,
                exception=exception,
                handler=handler,
                redaction=self.redactor.profile if redacted_dims else None,
                completeness_claim=claim,
                privacy_class=privacy,
                includes_raw_bodies=includes_raw,
                unavailable_dimensions=unavailable,
            )
        except ProgramExecutionError:
            return
        self._states.append(state)

    def _finish(self, status: str | TraceStatus) -> PythonExecutionTraceRecord:
        if isinstance(status, TraceStatus):
            status = status.value
        if not self._events:
            self._append_event(
                kind=EventKind.UNAVAILABLE.value,
                frame=None,
                payload={"reason": "no_events"},
                observation_status=ObservationStatus.UNAVAILABLE,
                completeness_claim=CompletenessClaim.UNAVAILABLE,
                extra_unavailable=("execution",),
                code=getattr(self._target, "__code__", None) if self._target else None,
            )
        unavailable = tuple(sorted(self._unavailable))
        redacted = tuple(sorted(self._redacted_dimensions | {"raw_body"}))
        if status in {
            TraceStatus.CANCELLED.value,
            TraceStatus.ISOLATED.value,
            TraceStatus.FAILED.value,
        }:
            unavailable = tuple(sorted(set(unavailable) | {"accepted_transition"}))
        claim: str
        if redacted:
            claim = CompletenessClaim.REDACTED.value
        elif unavailable:
            claim = CompletenessClaim.PARTIAL.value
        else:
            claim = CompletenessClaim.FULL_STATE.value
        private_privacy = (
            PrivacyClass.PRIVATE
            if self.policy.capture_locals and self._states
            else PrivacyClass.INTERNAL
        )
        includes_raw = private_privacy == PrivacyClass.PRIVATE
        if includes_raw:
            private_privacy = PrivacyClass.PRIVATE
        try:
            private_trace = assemble_execution_trace(
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                environment_binding_cid=self._env_cid,
                events=self._events,
                states=self._states if includes_raw else (),
                redaction=self.redactor.profile,
                completeness_claim=claim,
                privacy_class=private_privacy if includes_raw else PrivacyClass.INTERNAL,
                includes_raw_bodies=includes_raw,
                unavailable_dimensions=unavailable,
            )
        except ProgramExecutionError:
            private_trace = assemble_execution_trace(
                tree_cid=self._tree_cid,
                source_cid=self._source_cid,
                environment_binding_cid=self._env_cid,
                events=self._events,
                completeness_claim=CompletenessClaim.PARTIAL,
                privacy_class=PrivacyClass.INTERNAL,
                includes_raw_bodies=False,
                unavailable_dimensions=tuple(sorted(set(unavailable) | {"raw_body"})),
            )
        public_trace = private_trace.public_view()
        replay_promised = (
            status == TraceStatus.COMPLETED.value
            and not self._isolated
            and not self._cancelled
            and not self._truncated
            and self._failed is None
            and not any(event.event_kind == EventKind.EXTERNAL.value for event in self._events)
        )
        result_summary, result_redacted = self.redactor.redact_mapping(
            _plain_json_value(self._result_summary)
        )
        result_summary = _plain_json_value(result_summary)
        if result_redacted:
            self._redacted_dimensions.update(result_redacted)
        return PythonExecutionTraceRecord(
            status=status,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self._env_cid,
            capture_profile_cid=self._capture_cid,
            private_trace=private_trace,
            public_trace=public_trace,
            events=tuple(self._events),
            states=tuple(self._states),
            observations=tuple(self._observations),
            replay_promised=replay_promised,
            cancellation_requested=self._cancelled
            or (self.cancellation is not None and self.cancellation.requested),
            isolation_denied=self._isolated,
            truncated=self._truncated,
            result_summary=result_summary,
            unavailable_dimensions=tuple(sorted(set(unavailable) | set(public_trace.unavailable_dimensions))),
            accepted_transition_cid=None,
        )


_UNREPRESENTABLE: Final[object] = object()


class _DeniedImport:
    """Stand-in that fails closed if a denied module was already bound."""

    __slots__ = ("_name", "_tracer")

    def __init__(self, name: str, tracer: PythonExecutionTracer) -> None:
        self._name = name
        self._tracer = tracer

    def __getattr__(self, item: str) -> Any:
        error = HermeticIsolationError(f"hermetic isolation denied {self._name}.{item}")
        error.module = f"{self._name}.{item}"  # type: ignore[attr-defined]
        self._tracer._denied_module = f"{self._name}.{item}"
        raise error

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        error = HermeticIsolationError(f"hermetic isolation denied {self._name}")
        error.module = self._name  # type: ignore[attr-defined]
        self._tracer._denied_module = self._name
        raise error


def record_python_execution_trace(
    target: Callable[..., Any],
    *,
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    tree_cid: str | None = None,
    source: str | bytes | None = None,
    environment_binding_cid: str | None = None,
    policy: TraceCollectionPolicy | None = None,
    cancellation: TraceCancellation | None = None,
    redactor: TraceRedactor | None = None,
) -> PythonExecutionTraceRecord:
    """Record a hermetic in-process Python execution trace.

    The returned object's :meth:`PythonExecutionTraceRecord.public_record` never
    includes private raw bodies and never carries an accepted-transition CID.
    """

    tracer = PythonExecutionTracer(
        policy=policy,
        cancellation=cancellation,
        tree_cid=tree_cid,
        source=source,
        environment_binding_cid=environment_binding_cid,
        redactor=redactor,
    )
    return tracer.record(target, args=args, kwargs=kwargs)


def replay_deterministic_trace(
    original: PythonExecutionTraceRecord,
    target: Callable[..., Any],
    *,
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    policy: TraceCollectionPolicy | None = None,
) -> TraceReplayReceipt:
    """Replay a promised hermetic trace and compare event identity.

    Replay does not emit an accepted transition.  Traces that were cancelled,
    isolated, truncated, or that observed external effects are not promised.
    """

    if not isinstance(original, PythonExecutionTraceRecord):
        raise PythonExecutionTraceError("replay requires a PythonExecutionTraceRecord")
    original_cid = original.public_trace.execution_trace_cid
    if not original.replay_promised or original.status != TraceStatus.COMPLETED.value:
        return TraceReplayReceipt(
            original_trace_cid=original_cid,
            replayed_trace_cid=None,
            matched=False,
            promised=False,
            event_kind_sequence_equal=False,
            binding_equal=False,
            unavailable_dimensions=("replay",),
            accepted_transition_cid=None,
        )
    replayed = record_python_execution_trace(
        target,
        args=args,
        kwargs=kwargs,
        tree_cid=original.tree_cid,
        environment_binding_cid=original.environment_binding_cid,
        policy=policy,
        source=None,
    )
    kinds_equal = [event.event_kind for event in original.events] == [
        event.event_kind for event in replayed.events
    ]
    binding_equal = (
        original.tree_cid == replayed.tree_cid
        and original.environment_binding_cid == replayed.environment_binding_cid
        and original.source_cid == replayed.source_cid
    )
    matched = (
        replayed.replay_promised
        and kinds_equal
        and binding_equal
        and original.public_trace.event_cids == replayed.public_trace.event_cids
    )
    unavailable: tuple[str, ...] = ()
    if not matched:
        unavailable = ("replay_mismatch",) if kinds_equal or binding_equal else ("replay",)
    return TraceReplayReceipt(
        original_trace_cid=original_cid,
        replayed_trace_cid=replayed.public_trace.execution_trace_cid,
        matched=matched,
        promised=True,
        event_kind_sequence_equal=kinds_equal,
        binding_equal=binding_equal,
        unavailable_dimensions=unavailable,
        accepted_transition_cid=None,
    )


def module_import_ast() -> ast.Module:
    """Return this module's AST for cold-import side-effect probes."""

    with open(_MODULE_FILENAME, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=_MODULE_FILENAME)


__all__ = [
    "ADMITTED_LANGUAGE",
    "HERMETIC_TRACE_EVIDENCE",
    "IMPORT_DATABASE_LOADED",
    "IMPORT_INSTALLER_LOADED",
    "IMPORT_MODEL_LOADED",
    "IMPORT_NETWORK_LOADED",
    "IMPORT_REPO_SCAN_PERFORMED",
    "IMPORT_SIDE_EFFECTS_PERFORMED",
    "IMPORT_SOCKET_LOADED",
    "IMPORT_SUBPROCESS_LOADED",
    "IMPORT_WATCHER_LOADED",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "PYTHON_EXECUTION_TRACE_RECORD_INTERFACE",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "TRACE_REPLAY_RECEIPT_INTERFACE",
    "HermeticIsolationError",
    "PythonExecutionTraceError",
    "PythonExecutionTraceRecord",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCancelledError",
    "TraceCollectionPolicy",
    "TraceRedactor",
    "TraceReplayReceipt",
    "TraceStatus",
    "default_environment_binding_cid",
    "module_import_ast",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
