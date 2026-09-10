"""Hermetic Python execution tracing (SAWM-008 / PythonExecutionTracer@1).

This module is the datasets construction authority for admitted, bounded
Python traces.  It extends SAWM-007 ``ProgramEvent@1`` / ``ExecutionTrace@1``
records with a runtime collector that binds every event to exact tree,
source, code, symbol, callsite, and environment identities.

Normative constraints:

* Importing this module never opens a network or socket, never starts a
  subprocess or installer, never opens a database, never scans a repository,
  never starts a watcher, and never loads a model.
* Collection is in-process ``sys.settrace`` over a caller-supplied subject.
  Line and basic-block detail is policy-bounded.
* Selected external channels (network, subprocess, database, watcher, model
  load) are denied during collection and recorded as explicit observations
  or typed unavailable; they are never accepted as success.
* Cancellation never emits an accepted transition.
* Private raw trace bodies never enter public records.
* Nondeterministic external effects remain explicit observations or
  unavailable; replay is promised only for traces without those effects.
* This module does not persist operational acceptance, run a scheduler, or
  add arbitrary shell tracing.
"""

from __future__ import annotations

import ast
import builtins
import dis
import functools
import inspect
import marshal
import os
import re
import socket
import subprocess
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
    FORBIDDEN_FIELD_MARKERS,
    MAX_METADATA_BYTES,
    MAX_SAFE_INTEGER,
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

PYTHON_EXECUTION_TRACER_VERSION: Final[str] = "1"
TRACE_COLLECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-policy@1"
)
TRACE_REDACTOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-redactor@1"
)
TRACE_CANCELLATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-cancellation@1"
)
PYTHON_EXECUTION_TRACE_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-trace-record@1"
)
PYTHON_EXECUTION_TRACE_REPLAY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-trace-replay@1"
)
PYTHON_EXECUTION_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-environment@1"
)
PYTHON_EXECUTION_TREE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-tree@1"
)
PYTHON_EXECUTION_CODE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-code@1"
)

# Importing this module must remain a no-I/O, no-scan, no-model operation.
IMPORT_SIDE_EFFECTS_PERFORMED: Final[bool] = False
IMPORT_SCAN_PERFORMED: Final[bool] = False
ADMITTED_LANGUAGE: Final[str] = "python"

ADMITTED_EVENT_KINDS: Final[tuple[str, ...]] = (
    EventKind.CALL.value,
    EventKind.RETURN.value,
    EventKind.LINE.value,
    EventKind.RAISE.value,
    EventKind.CATCH.value,
    EventKind.HANDLER.value,
    EventKind.YIELD.value,
    EventKind.AWAIT.value,
    EventKind.EXTERNAL.value,
    EventKind.ENTER.value,
    EventKind.EXIT.value,
)

DEFAULT_MAX_EVENTS: Final[int] = 4_096
DEFAULT_MAX_LINE_EVENTS: Final[int] = 512
DEFAULT_MAX_FRAMES: Final[int] = 64
DEFAULT_MAX_PAYLOAD_BYTES: Final[int] = 4_096
DEFAULT_MAX_SUMMARY_KEYS: Final[int] = 32
DEFAULT_MAX_SUMMARY_CHARS: Final[int] = 256
DEFAULT_MAX_STATE_SNAPSHOTS: Final[int] = 32
DEFAULT_MAX_DEPTH: Final[int] = 2

_YIELD_OPCODES: Final[frozenset[int]] = frozenset(
    dis.opmap[name] for name in ("YIELD_VALUE", "YIELD_FROM") if name in dis.opmap
)
_AWAIT_OPCODES: Final[frozenset[int]] = frozenset(
    dis.opmap[name]
    for name in ("GET_AWAITABLE", "BEFORE_ASYNC_WITH", "GET_AITER", "GET_ANEXT", "SEND")
    if name in dis.opmap
)
_RETURN_OPCODES: Final[frozenset[int]] = frozenset(
    dis.opmap[name]
    for name in ("RETURN_VALUE", "RETURN_CONST", "RETURN_GENERATOR")
    if name in dis.opmap
)
_CACHE_OPCODE: Final[int | None] = dis.opmap.get("CACHE")
_SECRET_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[_\-.])(?:password|passwd|secret|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|session[_-]?token|credential|authorization|cookie|"
    r"private[_-]?key|token)(?:$|[_\-.])",
    re.IGNORECASE,
)
_EXTERNAL_MODULE_PREFIXES: Final[tuple[str, ...]] = (
    "socket",
    "ssl",
    "select",
    "selectors",
    "asyncio",
    "subprocess",
    "multiprocessing",
    "concurrent.futures",
    "urllib",
    "http",
    "requests",
    "urllib3",
    "httpx",
    "aiohttp",
    "sqlite3",
    "duckdb",
    "psycopg",
    "pymongo",
    "watchdog",
    "torch",
    "transformers",
    "tensorflow",
)
_DENIED_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "requests",
        "urllib3",
        "httpx",
        "aiohttp",
        "torch",
        "transformers",
        "tensorflow",
        "duckdb",
        "psycopg2",
        "pymongo",
        "watchdog",
    }
)
_ENTER_NAMES: Final[frozenset[str]] = frozenset({"__enter__", "__aenter__"})
_EXIT_NAMES: Final[frozenset[str]] = frozenset({"__exit__", "__aexit__"})
_PUBLIC_PRIVACY: Final[frozenset[str]] = frozenset(
    {PrivacyClass.PUBLIC.value, PrivacyClass.INTERNAL.value}
)


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic tracing inputs, policy, or replay bindings fail."""


class HermeticIsolationError(PythonExecutionTraceError):
    """Raised when a denied external effect is attempted during collection."""


class TraceStatus(StrEnum):
    COLLECTED = "collected"
    CANCELLED = "cancelled"
    ISOLATED = "isolated"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Small validators
# ---------------------------------------------------------------------------


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        raise PythonExecutionTraceError(
            f"{label} must be a non-empty trimmed string without NUL bytes"
        )
    if unicodedata.normalize("NFC", value) != value:
        raise PythonExecutionTraceError(f"{label} must be NFC text")
    return value


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise PythonExecutionTraceError(f"{label} must be a boolean")
    return value


def _positive_int(value: object, label: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PythonExecutionTraceError(f"{label} must be an integer")
    if value < 0 or (value == 0 and not allow_zero):
        raise PythonExecutionTraceError(f"{label} must be a positive integer")
    if value > MAX_SAFE_INTEGER:
        raise PythonExecutionTraceError(f"{label} exceeds the safe JSON integer range")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PythonExecutionTraceError(f"{label} must be a mapping")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PythonExecutionTraceError(f"unknown {label} field(s): {', '.join(unknown)}")


def _environment_cid(bindings: Mapping[str, str]) -> str:
    items = [
        {
            "key": unicodedata.normalize("NFC", str(key)),
            "value": unicodedata.normalize("NFC", str(value)),
        }
        for key, value in bindings.items()
    ]
    items.sort(key=lambda item: (item["key"], item["value"]))
    return cid_for_structured(
        {"schema": PYTHON_EXECUTION_ENVIRONMENT_SCHEMA, "bindings": items}
    )


def _default_environment() -> dict[str, str]:
    version = sys.version_info
    return {
        "language": ADMITTED_LANGUAGE,
        "python_implementation": sys.implementation.name,
        "python_version": f"{version.major}.{version.minor}.{version.micro}",
    }


def _opcode_at(code: CodeType, lasti: int) -> int | None:
    raw = code.co_code
    index = lasti
    if index < 0 or index >= len(raw):
        return None
    opcode = raw[index]
    if _CACHE_OPCODE is not None:
        while index >= 0 and raw[index] == _CACHE_OPCODE:
            index -= 2
            if index < 0:
                return None
            opcode = raw[index]
    return opcode


def _is_yield_return(frame: FrameType, event: str) -> bool:
    if event != "return":
        return False
    flags = frame.f_code.co_flags
    if not (flags & (inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR)):
        return False
    opcode = _opcode_at(frame.f_code, frame.f_lasti)
    if opcode in _YIELD_OPCODES:
        return True
    if opcode in _RETURN_OPCODES:
        return False
    # Generator resumptions report a return event at YIELD_VALUE; if the
    # instruction stream is specialized, treat a non-return opcode as yield.
    return opcode is not None


def _is_await_return(frame: FrameType, event: str) -> bool:
    if event != "return":
        return False
    if not (frame.f_code.co_flags & inspect.CO_COROUTINE):
        return False
    opcode = _opcode_at(frame.f_code, frame.f_lasti)
    if opcode in _YIELD_OPCODES or opcode in _AWAIT_OPCODES:
        return True
    if opcode in _RETURN_OPCODES:
        return False
    return False


def _logical_name_from_code(code: CodeType, globals_map: Mapping[str, Any] | None = None) -> str:
    module = ""
    if globals_map is not None:
        raw = globals_map.get("__name__")
        if type(raw) is str:
            module = raw
    qualname = getattr(code, "co_qualname", code.co_name) or code.co_name
    if module and qualname:
        return f"{module}.{qualname}"
    return qualname or code.co_name or "unknown"


def _logical_name_from_callable(subject: Callable[..., Any]) -> str:
    module = str(getattr(subject, "__module__", "") or "")
    qualname = str(
        getattr(subject, "__qualname__", None) or getattr(subject, "__name__", "") or "unknown"
    )
    if module:
        return f"{module}.{qualname}"
    return qualname


def _unwrap_callable(subject: Callable[..., Any]) -> Callable[..., Any]:
    if isinstance(subject, (staticmethod, classmethod)):
        subject = subject.__func__  # type: ignore[assignment]
    if isinstance(subject, MethodType):
        return subject
    if isinstance(subject, functools.partial):
        return _unwrap_callable(subject.func)  # type: ignore[arg-type]
    try:
        return inspect.unwrap(subject)
    except (ValueError, TypeError):
        return subject


def _callable_code(subject: Callable[..., Any]) -> CodeType:
    target = _unwrap_callable(subject)
    if isinstance(target, MethodType):
        code = getattr(target.__func__, "__code__", None)
    else:
        code = getattr(target, "__code__", None)
    if not isinstance(code, CodeType):
        raise PythonExecutionTraceError("subject must be a Python function or method")
    return code


def _const_fingerprint(value: Any) -> Any:
    if value is None or type(value) is bool or type(value) is int or type(value) is str:
        return value
    if isinstance(value, CodeType):
        return [
            "code",
            value.co_name,
            getattr(value, "co_qualname", value.co_name),
            value.co_firstlineno,
            list(value.co_varnames),
        ]
    if type(value) is bytes:
        return ["bytes", len(value)]
    if type(value) is tuple:
        return ["tuple", [_const_fingerprint(item) for item in value]]
    if type(value) is frozenset:
        return ["frozenset", type(value).__name__]
    return type(value).__name__


def _code_cid(code: CodeType) -> str:
    # Bytecode is excluded: CPython's specializing interpreter mutates
    # ``co_code`` in place, which must not change event identity.
    return cid_for_structured(
        {
            "schema": PYTHON_EXECUTION_CODE_SCHEMA,
            "name": code.co_name,
            "qualname": getattr(code, "co_qualname", code.co_name),
            "firstlineno": code.co_firstlineno,
            "argcount": code.co_argcount,
            "posonlyargcount": code.co_posonlyargcount,
            "kwonlyargcount": code.co_kwonlyargcount,
            "flags": code.co_flags,
            "names": list(code.co_names),
            "varnames": list(code.co_varnames),
            "consts": [_const_fingerprint(item) for item in code.co_consts],
        }
    )


def _source_from_callable(subject: Callable[..., Any], source_text: str | None) -> tuple[str, str]:
    if source_text is not None:
        text = source_text if source_text.endswith("\n") else source_text + "\n"
        return text, cid_for_bytes(text.encode("utf-8"))
    target = _unwrap_callable(subject)
    try:
        text = inspect.getsource(target)
    except (OSError, TypeError):
        text = ""
    if text:
        if not text.endswith("\n"):
            text += "\n"
        return text, cid_for_bytes(text.encode("utf-8"))
    return "", cid_for_bytes(marshal.dumps(_callable_code(subject)))


def _tree_cid(source_cid: str, source_path: str, claimed: str | None) -> str:
    if claimed:
        return claimed
    return cid_for_structured(
        {
            "schema": PYTHON_EXECUTION_TREE_SCHEMA,
            "language": ADMITTED_LANGUAGE,
            "source_cid": source_cid,
            "source_path": os.path.basename(source_path) if source_path else "",
        }
    )


def _secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in SECRET_FIELD_MARKERS or lowered in FORBIDDEN_FIELD_MARKERS:
        return True
    return _SECRET_KEY_RE.search(key) is not None


def _channel_for_symbol(symbol: str) -> str:
    lowered = symbol.lower()
    if any(part in lowered for part in ("socket", "ssl", "urllib", "http", "requests", "httpx")):
        return "network"
    if any(part in lowered for part in ("subprocess", "os.system", "os.popen", "multiprocessing")):
        return "subprocess"
    if any(part in lowered for part in ("sqlite", "duckdb", "psycopg", "pymongo")):
        return "database"
    if any(part in lowered for part in ("watchdog", "inotify", "selector")):
        return "watcher"
    if any(part in lowered for part in ("torch", "transformers", "tensorflow", "model")):
        return "model"
    if lowered.startswith("asyncio"):
        return "watcher"
    return "external"


# ---------------------------------------------------------------------------
# Policy, redactor, cancellation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Closed, bounded collection policy for one hermetic tracing run."""

    collect_event_kinds: tuple[str, ...] = ADMITTED_EVENT_KINDS
    collect_lines: bool = True
    capture_locals: bool = False
    max_events: int = DEFAULT_MAX_EVENTS
    max_line_events: int = DEFAULT_MAX_LINE_EVENTS
    max_frames: int = DEFAULT_MAX_FRAMES
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
    max_summary_keys: int = DEFAULT_MAX_SUMMARY_KEYS
    max_summary_chars: int = DEFAULT_MAX_SUMMARY_CHARS
    max_state_snapshots: int = DEFAULT_MAX_STATE_SNAPSHOTS
    deny_network: bool = True
    deny_subprocess: bool = True
    deny_database: bool = True
    deny_model_loads: bool = True
    deny_watchers: bool = True
    language: str = ADMITTED_LANGUAGE
    schema: str = TRACE_COLLECTION_POLICY_SCHEMA

    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "collect_event_kinds",
            "collect_lines",
            "capture_locals",
            "max_events",
            "max_line_events",
            "max_frames",
            "max_payload_bytes",
            "max_summary_keys",
            "max_summary_chars",
            "max_state_snapshots",
            "deny_network",
            "deny_subprocess",
            "deny_database",
            "deny_model_loads",
            "deny_watchers",
            "language",
            "schema",
            "policy_cid",
        }
    )

    def __post_init__(self) -> None:
        if self.schema != TRACE_COLLECTION_POLICY_SCHEMA:
            raise PythonExecutionTraceError(
                f"unsupported collection-policy schema {self.schema!r}"
            )
        language = _text(self.language, "language")
        if language != ADMITTED_LANGUAGE:
            raise PythonExecutionTraceError(
                f"language {language!r} is typed unavailable in this tracer"
            )
        object.__setattr__(self, "language", language)
        kinds = tuple(_text(item, "collect_event_kind") for item in self.collect_event_kinds)
        if not kinds:
            raise PythonExecutionTraceError("collect_event_kinds must not be empty")
        unknown = [item for item in kinds if item not in ADMITTED_EVENT_KINDS]
        if unknown:
            raise PythonExecutionTraceError(
                f"unsupported collect_event_kinds {unknown}"
            )
        seen: set[str] = set()
        ordered: list[str] = []
        for item in kinds:
            if item not in seen:
                seen.add(item)
                ordered.append(item)
        object.__setattr__(self, "collect_event_kinds", tuple(ordered))
        object.__setattr__(self, "collect_lines", _bool(self.collect_lines, "collect_lines"))
        object.__setattr__(
            self, "capture_locals", _bool(self.capture_locals, "capture_locals")
        )
        object.__setattr__(self, "max_events", _positive_int(self.max_events, "max_events"))
        object.__setattr__(
            self, "max_line_events", _positive_int(self.max_line_events, "max_line_events")
        )
        object.__setattr__(self, "max_frames", _positive_int(self.max_frames, "max_frames"))
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
            "max_summary_chars",
            _positive_int(self.max_summary_chars, "max_summary_chars"),
        )
        object.__setattr__(
            self,
            "max_state_snapshots",
            _positive_int(self.max_state_snapshots, "max_state_snapshots"),
        )
        for name in (
            "deny_network",
            "deny_subprocess",
            "deny_database",
            "deny_model_loads",
            "deny_watchers",
        ):
            object.__setattr__(self, name, _bool(getattr(self, name), name))
        if self.max_payload_bytes > MAX_METADATA_BYTES:
            raise PythonExecutionTraceError("max_payload_bytes exceeds contract metadata bound")

    def admits(self, kind: str) -> bool:
        if kind == EventKind.LINE.value and not self.collect_lines:
            return False
        return kind in self.collect_event_kinds

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "collect_event_kinds": list(self.collect_event_kinds),
            "collect_lines": self.collect_lines,
            "capture_locals": self.capture_locals,
            "max_events": self.max_events,
            "max_line_events": self.max_line_events,
            "max_frames": self.max_frames,
            "max_payload_bytes": self.max_payload_bytes,
            "max_summary_keys": self.max_summary_keys,
            "max_summary_chars": self.max_summary_chars,
            "max_state_snapshots": self.max_state_snapshots,
            "deny_network": self.deny_network,
            "deny_subprocess": self.deny_subprocess,
            "deny_database": self.deny_database,
            "deny_model_loads": self.deny_model_loads,
            "deny_watchers": self.deny_watchers,
            "language": self.language,
        }

    @property
    def policy_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["policy_cid"] = self.policy_cid
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TraceCollectionPolicy:
        value = _mapping(value, "collection policy")
        _reject_unknown(value, cls._FIELDS, "collection policy")
        payload = dict(value)
        payload.pop("policy_cid", None)
        kinds = payload.get("collect_event_kinds", ADMITTED_EVENT_KINDS)
        return cls(
            collect_event_kinds=tuple(kinds),
            collect_lines=payload.get("collect_lines", True),
            capture_locals=payload.get("capture_locals", False),
            max_events=payload.get("max_events", DEFAULT_MAX_EVENTS),
            max_line_events=payload.get("max_line_events", DEFAULT_MAX_LINE_EVENTS),
            max_frames=payload.get("max_frames", DEFAULT_MAX_FRAMES),
            max_payload_bytes=payload.get("max_payload_bytes", DEFAULT_MAX_PAYLOAD_BYTES),
            max_summary_keys=payload.get("max_summary_keys", DEFAULT_MAX_SUMMARY_KEYS),
            max_summary_chars=payload.get("max_summary_chars", DEFAULT_MAX_SUMMARY_CHARS),
            max_state_snapshots=payload.get(
                "max_state_snapshots", DEFAULT_MAX_STATE_SNAPSHOTS
            ),
            deny_network=payload.get("deny_network", True),
            deny_subprocess=payload.get("deny_subprocess", True),
            deny_database=payload.get("deny_database", True),
            deny_model_loads=payload.get("deny_model_loads", True),
            deny_watchers=payload.get("deny_watchers", True),
            language=payload.get("language", ADMITTED_LANGUAGE),
            schema=payload.get("schema", TRACE_COLLECTION_POLICY_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class TraceRedactor:
    """Fail-closed redaction of secrets, forbidden fields, and oversized bodies."""

    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
    max_summary_keys: int = DEFAULT_MAX_SUMMARY_KEYS
    max_summary_chars: int = DEFAULT_MAX_SUMMARY_CHARS
    max_depth: int = DEFAULT_MAX_DEPTH
    schema: str = TRACE_REDACTOR_SCHEMA

    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE

    def __post_init__(self) -> None:
        if self.schema != TRACE_REDACTOR_SCHEMA:
            raise PythonExecutionTraceError(f"unsupported redactor schema {self.schema!r}")
        object.__setattr__(
            self, "max_payload_bytes", _positive_int(self.max_payload_bytes, "max_payload_bytes")
        )
        object.__setattr__(
            self, "max_summary_keys", _positive_int(self.max_summary_keys, "max_summary_keys")
        )
        object.__setattr__(
            self,
            "max_summary_chars",
            _positive_int(self.max_summary_chars, "max_summary_chars"),
        )
        object.__setattr__(self, "max_depth", _positive_int(self.max_depth, "max_depth"))
        if self.max_payload_bytes > MAX_METADATA_BYTES:
            raise PythonExecutionTraceError("max_payload_bytes exceeds contract metadata bound")

    @classmethod
    def from_policy(cls, policy: TraceCollectionPolicy) -> TraceRedactor:
        return cls(
            max_payload_bytes=policy.max_payload_bytes,
            max_summary_keys=policy.max_summary_keys,
            max_summary_chars=policy.max_summary_chars,
        )

    def redact_mapping(self, value: Mapping[str, Any] | None) -> tuple[dict[str, Any], tuple[str, ...]]:
        if not value:
            return {}, ()
        redacted_dimensions: set[str] = set()
        bounded = self._summarize(value, depth=0, redacted=redacted_dimensions, path="")
        if not isinstance(bounded, dict):
            return {}, tuple(sorted(redacted_dimensions | {"payload"}))
        encoded = canonical_dag_json_bytes(bounded)
        if len(encoded) > self.max_payload_bytes:
            redacted_dimensions.add("payload")
            return {"bounded": True}, tuple(sorted(redacted_dimensions))
        return bounded, tuple(sorted(redacted_dimensions))

    def public_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        return trace.public_view()

    def public_state(self, state: ProgramExecutionState) -> ProgramExecutionState:
        return public_execution_view(state)

    def _summarize(
        self,
        value: Any,
        *,
        depth: int,
        redacted: set[str],
        path: str,
    ) -> Any:
        if depth > self.max_depth:
            redacted.add(path or "depth")
            return {"unavailable": "depth"}
        value_type = type(value)
        if value is None or value_type is bool:
            return value
        if value_type is int:
            if abs(value) > MAX_SAFE_INTEGER:
                redacted.add(path or "integer")
                return {"unavailable": "integer_range"}
            return value
        if value_type is str:
            if len(value) > self.max_summary_chars:
                redacted.add(path or "text")
                return value[: self.max_summary_chars]
            return value
        if value_type is float:
            redacted.add(path or "float")
            return {"unavailable": "float"}
        if isinstance(value, Mapping):
            items: dict[str, Any] = {}
            for key, child in value.items():
                if type(key) is not str:
                    redacted.add(path or "key")
                    continue
                if _secret_key(key) or key in FORBIDDEN_FIELD_MARKERS:
                    redacted.add("secrets" if key in SECRET_FIELD_MARKERS or _secret_key(key) else key)
                    continue
                if len(items) >= self.max_summary_keys:
                    redacted.add(path or "keys")
                    break
                child_path = f"{path}.{key}" if path else key
                items[key] = self._summarize(
                    child, depth=depth + 1, redacted=redacted, path=child_path
                )
            return items
        if isinstance(value, (list, tuple)):
            limited = list(value)[: self.max_summary_keys]
            if len(value) > self.max_summary_keys:
                redacted.add(path or "sequence")
            return [
                self._summarize(
                    child,
                    depth=depth + 1,
                    redacted=redacted,
                    path=f"{path}[{index}]" if path else str(index),
                )
                for index, child in enumerate(limited)
            ]
        redacted.add(path or "host_object")
        name = getattr(value_type, "__name__", "object")
        return {"type": name, "unavailable": "host_object"}


class TraceCancellation:
    """Cooperative cancellation token and public cancellation record.

    ``accepted_transition`` is always false.  A cancelled collection never
    promotes its events into an accepted transition.
    """

    INTERFACE: ClassVar[str] = TRACE_CANCELLATION_INTERFACE
    SCHEMA: ClassVar[str] = TRACE_CANCELLATION_SCHEMA

    def __init__(self, reason: str = "requested") -> None:
        self._reason = _text(reason, "reason") if reason else "requested"
        self._cancelled = False
        self._event_count = 0

    def cancel(self, reason: str = "requested", *, event_count: int | None = None) -> None:
        self._cancelled = True
        self._reason = _text(reason, "reason") if reason else self._reason
        if event_count is not None:
            self._event_count = _positive_int(event_count, "event_count", allow_zero=True)

    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def accepted_transition(self) -> bool:
        return False

    def snapshot(self) -> TraceCancellation:
        clone = TraceCancellation(self._reason)
        clone._cancelled = self._cancelled
        clone._event_count = self._event_count
        return clone

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "interface": self.INTERFACE,
            "cancelled": self._cancelled,
            "reason": self._reason,
            "event_count": self._event_count,
            "accepted_transition": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TraceCancellation:
        value = _mapping(value, "cancellation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "schema",
                    "interface",
                    "cancelled",
                    "reason",
                    "event_count",
                    "accepted_transition",
                }
            ),
            "cancellation",
        )
        if value.get("schema", cls.SCHEMA) != cls.SCHEMA:
            raise PythonExecutionTraceError("unsupported cancellation schema")
        if value.get("accepted_transition") is True:
            raise PythonExecutionTraceError("cancellation cannot carry an accepted transition")
        token = cls(str(value.get("reason") or "requested"))
        if value.get("cancelled") is True:
            token.cancel(
                str(value.get("reason") or "requested"),
                event_count=int(value.get("event_count") or 0),
            )
        return token


# ---------------------------------------------------------------------------
# Public records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceRecord:
    """Sealed collection result with an explicit public/private split."""

    status: str
    policy: TraceCollectionPolicy
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    environment_binding: Mapping[str, str]
    subject_logical_name: str
    subject_code_cid: str
    events: tuple[ProgramEvent, ...]
    states: tuple[ProgramExecutionState, ...]
    trace: ExecutionTrace
    observations: tuple[ExecutionObservation, ...]
    redaction: RedactionProfile
    cancellation: TraceCancellation | None
    replay_promised: bool
    privacy_class: str
    includes_raw_bodies: bool
    result_kind: str
    exception_type: str | None = None
    tracer_version: str = PYTHON_EXECUTION_TRACER_VERSION
    schema: str = PYTHON_EXECUTION_TRACE_RECORD_SCHEMA

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECORD_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _text(self.status, "status"))
        if self.status not in {item.value for item in TraceStatus}:
            raise PythonExecutionTraceError(f"unsupported trace status {self.status!r}")
        if not isinstance(self.policy, TraceCollectionPolicy):
            raise PythonExecutionTraceError("policy must be a TraceCollectionPolicy")
        if not isinstance(self.trace, ExecutionTrace):
            raise PythonExecutionTraceError("trace must be an ExecutionTrace")
        object.__setattr__(
            self,
            "environment_binding",
            MappingProxyType(dict(self.environment_binding)),
        )
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "states", tuple(self.states))
        object.__setattr__(self, "observations", tuple(self.observations))
        object.__setattr__(
            self, "replay_promised", _bool(self.replay_promised, "replay_promised")
        )
        object.__setattr__(
            self,
            "includes_raw_bodies",
            _bool(self.includes_raw_bodies, "includes_raw_bodies"),
        )
        object.__setattr__(
            self, "privacy_class", _text(self.privacy_class, "privacy_class")
        )
        if self.includes_raw_bodies and self.privacy_class in _PUBLIC_PRIVACY:
            raise PythonExecutionTraceError(
                "raw trace bodies remain private and cannot enter public records"
            )
        if self.cancellation is not None:
            if self.cancellation.accepted_transition:
                raise PythonExecutionTraceError(
                    "cancellation cannot carry an accepted transition"
                )
            if self.status == TraceStatus.COLLECTED.value:
                raise PythonExecutionTraceError(
                    "cancelled collections cannot be marked collected"
                )
        if self.replay_promised and not self.accepted_transition:
            raise PythonExecutionTraceError(
                "replay cannot be promised without an accepted transition"
            )

    @property
    def accepted_transition(self) -> bool:
        return (
            self.status == TraceStatus.COLLECTED.value
            and self.cancellation is None
        )

    def public_record(self) -> PythonExecutionTraceRecord:
        public_trace = self.trace.public_view()
        redacted = set(self.redaction.redacted_dimensions)
        redacted.add("raw_body")
        profile = RedactionProfile(
            privacy_class=PrivacyClass.PUBLIC,
            redacted_dimensions=tuple(sorted(redacted)),
            unavailable_dimensions=self.redaction.unavailable_dimensions,
            completeness_claim=CompletenessClaim.REDACTED,
        )
        return PythonExecutionTraceRecord(
            status=self.status,
            policy=self.policy,
            tree_cid=self.tree_cid,
            source_cid=self.source_cid,
            environment_binding_cid=self.environment_binding_cid,
            environment_binding=self.environment_binding,
            subject_logical_name=self.subject_logical_name,
            subject_code_cid=self.subject_code_cid,
            events=self.events,
            states=(),
            trace=public_trace,
            observations=self.observations,
            redaction=profile,
            cancellation=None if self.cancellation is None else self.cancellation.snapshot(),
            replay_promised=self.replay_promised and self.accepted_transition,
            privacy_class=PrivacyClass.PUBLIC.value,
            includes_raw_bodies=False,
            result_kind=self.result_kind,
            exception_type=self.exception_type,
            tracer_version=self.tracer_version,
        )

    def identity_payload(self) -> dict[str, Any]:
        public = self if not self.includes_raw_bodies else self.public_record()
        return {
            "schema": self.schema,
            "interface": self.INTERFACE,
            "status": public.status,
            "accepted_transition": public.accepted_transition,
            "replay_promised": public.replay_promised,
            "policy_cid": public.policy.policy_cid,
            "tree_cid": public.tree_cid,
            "source_cid": public.source_cid,
            "environment_binding_cid": public.environment_binding_cid,
            "subject_logical_name": public.subject_logical_name,
            "subject_code_cid": public.subject_code_cid,
            "trace_cid": public.trace.execution_trace_cid,
            "event_cids": list(public.trace.event_cids),
            "raw_execution_state_cids": [],
            "includes_raw_bodies": False,
            "privacy_class": PrivacyClass.PUBLIC.value,
            "result_kind": public.result_kind,
            "exception_type": public.exception_type,
            "cancellation": (
                None if public.cancellation is None else public.cancellation.to_dict()
            ),
            "redaction": public.redaction.to_dict(),
            "tracer_version": public.tracer_version,
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the public record. Raw bodies are never included."""

        public = self.public_record()
        payload = public.identity_payload()
        payload["trace"] = public.trace.to_dict()
        payload["events"] = [event.to_dict() for event in public.events]
        payload["observations"] = [item.to_dict() for item in public.observations]
        payload["policy"] = public.policy.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceReplay:
    """Deterministic promised-replay receipt."""

    matched: bool
    original_trace_cid: str
    replay_trace_cid: str
    original_event_cids: tuple[str, ...]
    replay_event_cids: tuple[str, ...]
    original_code_cid: str
    replay_code_cid: str
    original_environment_binding_cid: str
    replay_environment_binding_cid: str
    accepted_transition: bool
    schema: str = PYTHON_EXECUTION_TRACE_REPLAY_SCHEMA

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_REPLAY_INTERFACE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "interface": self.INTERFACE,
            "matched": self.matched,
            "original_trace_cid": self.original_trace_cid,
            "replay_trace_cid": self.replay_trace_cid,
            "original_event_cids": list(self.original_event_cids),
            "replay_event_cids": list(self.replay_event_cids),
            "original_code_cid": self.original_code_cid,
            "replay_code_cid": self.replay_code_cid,
            "original_environment_binding_cid": self.original_environment_binding_cid,
            "replay_environment_binding_cid": self.replay_environment_binding_cid,
            "accepted_transition": self.accepted_transition,
        }


# ---------------------------------------------------------------------------
# Isolation, AST handler table, coroutine driver
# ---------------------------------------------------------------------------


class _IsolationGuard:
    """Install test-only denial hooks for the duration of one collection."""

    def __init__(self, policy: TraceCollectionPolicy, emit: Callable[[str, str], None]) -> None:
        self.policy = policy
        self.emit = emit
        self._restores: list[tuple[Any, str, Any]] = []

    def install(self) -> None:
        if self.policy.deny_network:
            self._patch(socket, "create_connection", "network", "socket.create_connection")
            self._patch(socket, "create_server", "network", "socket.create_server")
            self._patch(socket, "getaddrinfo", "network", "socket.getaddrinfo")
            self._patch_method(socket.socket, "connect", "network", "socket.socket.connect")
            self._patch_method(socket.socket, "connect_ex", "network", "socket.socket.connect_ex")
        if self.policy.deny_subprocess:
            self._patch(subprocess, "Popen", "subprocess", "subprocess.Popen")
            self._patch(subprocess, "run", "subprocess", "subprocess.run")
            self._patch(subprocess, "call", "subprocess", "subprocess.call")
            self._patch(subprocess, "check_call", "subprocess", "subprocess.check_call")
            self._patch(subprocess, "check_output", "subprocess", "subprocess.check_output")
            self._patch(os, "system", "subprocess", "os.system")
            self._patch(os, "popen", "subprocess", "os.popen")
        if self.policy.deny_database:
            sqlite3 = sys.modules.get("sqlite3")
            if sqlite3 is not None:
                self._patch(sqlite3, "connect", "database", "sqlite3.connect")
            duckdb = sys.modules.get("duckdb")
            if duckdb is not None:
                self._patch(duckdb, "connect", "database", "duckdb.connect")
        if self.policy.deny_watchers:
            asyncio = sys.modules.get("asyncio")
            if asyncio is not None:
                for name in ("get_event_loop", "get_running_loop", "new_event_loop", "run"):
                    if hasattr(asyncio, name):
                        self._patch(asyncio, name, "watcher", f"asyncio.{name}")
            watchdog = sys.modules.get("watchdog")
            if watchdog is not None:
                observers = sys.modules.get("watchdog.observers")
                if observers is not None and hasattr(observers, "Observer"):
                    self._patch(observers, "Observer", "watcher", "watchdog.observers.Observer")
        if self.policy.deny_model_loads:
            for module_name, attr, symbol in (
                ("torch", "load", "torch.load"),
                ("transformers", "pipeline", "transformers.pipeline"),
            ):
                module = sys.modules.get(module_name)
                if module is not None and hasattr(module, attr):
                    self._patch(module, attr, "model", symbol)
        self._patch(builtins, "__import__", "import", "builtins.__import__", import_hook=True)

    def restore(self) -> None:
        while self._restores:
            obj, name, original = self._restores.pop()
            try:
                setattr(obj, name, original)
            except Exception:
                continue

    def _patch(
        self,
        obj: Any,
        name: str,
        channel: str,
        symbol: str,
        *,
        import_hook: bool = False,
    ) -> None:
        original = getattr(obj, name, None)
        if original is None:
            return
        emit = self.emit

        if import_hook:
            def wrapped(mod_name: Any, *args: Any, **kwargs: Any) -> Any:
                root = str(mod_name).split(".", 1)[0]
                if root in _DENIED_IMPORTS:
                    emit("model" if root in {"torch", "transformers", "tensorflow"} else "network", str(mod_name))
                    raise HermeticIsolationError(f"import of {mod_name!r} denied")
                return original(mod_name, *args, **kwargs)
        else:
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                emit(channel, symbol)
                raise HermeticIsolationError(f"{channel} denied ({symbol})")

        try:
            setattr(obj, name, wrapped)
        except (TypeError, AttributeError):
            return
        self._restores.append((obj, name, original))

    def _patch_method(self, cls: type, name: str, channel: str, symbol: str) -> None:
        original = getattr(cls, name, None)
        if original is None:
            return
        emit = self.emit

        def wrapped(self_obj: Any, *args: Any, **kwargs: Any) -> Any:
            emit(channel, symbol)
            raise HermeticIsolationError(f"{channel} denied ({symbol})")

        try:
            setattr(cls, name, wrapped)
        except (TypeError, AttributeError):
            return
        self._restores.append((cls, name, original))


def _handler_table(source_text: str) -> dict[int, tuple[str, str]]:
    table: dict[int, tuple[str, str]] = {}
    if not source_text:
        return table
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return table

    def mark(node: ast.AST, kind: str, exception_type: str) -> None:
        lineno = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", lineno)
        if type(lineno) is not int:
            return
        last = end if type(end) is int else lineno
        for line in range(lineno, last + 1):
            table.setdefault(line, (kind, exception_type))

    for node in ast.walk(tree):
        handlers: tuple[ast.ExceptHandler, ...] = ()
        star = False
        if isinstance(node, ast.Try):
            handlers = tuple(node.handlers)
        elif hasattr(ast, "TryStar") and isinstance(node, ast.TryStar):  # type: ignore[attr-defined]
            handlers = tuple(node.handlers)
            star = True
        for handler in handlers:
            kind = HandlerKind.EXCEPT_STAR.value if star else HandlerKind.EXCEPT.value
            if getattr(handler, "type", None) is None:
                exception_type = "BaseException"
            elif isinstance(handler.type, ast.Name):
                exception_type = handler.type.id
            else:
                exception_type = ast.dump(handler.type, include_attributes=False)
            mark(handler, kind, exception_type)
            for stmt in handler.body:
                mark(stmt, kind, exception_type)
        if isinstance(node, ast.Try) and node.finalbody:
            for stmt in node.finalbody:
                mark(stmt, HandlerKind.FINALLY.value, "")
    return table


def _drive_coroutine(coro: Any) -> Any:
    stack = [coro]
    inbound: Any = None
    try:
        while stack:
            current = stack[-1]
            try:
                outbound = current.send(inbound)
            except StopIteration as done:
                stack.pop()
                inbound = done.value
                continue
            inbound = None
            if inspect.iscoroutine(outbound):
                stack.append(outbound)
                continue
            raise HermeticIsolationError("non-coroutine awaitable is unavailable")
        return inbound
    finally:
        for item in reversed(stack):
            closer = getattr(item, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    continue


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class PythonExecutionTracer:
    """In-process hermetic tracer bound to SAWM-007 execution contracts."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE
    VERSION: ClassVar[str] = PYTHON_EXECUTION_TRACER_VERSION

    def __init__(
        self,
        policy: TraceCollectionPolicy | None = None,
        redactor: TraceRedactor | None = None,
    ) -> None:
        self.policy = policy if policy is not None else TraceCollectionPolicy()
        self.redactor = redactor if redactor is not None else TraceRedactor.from_policy(self.policy)

    def record(
        self,
        subject: Callable[..., Any],
        *,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        tree_cid: str | None = None,
        source_text: str | None = None,
        source_path: str | None = None,
        environment_binding: Mapping[str, str] | None = None,
        cancellation: TraceCancellation | None = None,
        privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL,
        include_raw_bodies: bool = False,
    ) -> PythonExecutionTraceRecord:
        return record_python_execution_trace(
            subject,
            args=args,
            kwargs=kwargs,
            policy=self.policy,
            tree_cid=tree_cid,
            source_text=source_text,
            source_path=source_path,
            environment_binding=environment_binding,
            cancellation=cancellation,
            privacy_class=privacy_class,
            include_raw_bodies=include_raw_bodies,
            redactor=self.redactor,
        )


class _Collector:
    def __init__(
        self,
        *,
        policy: TraceCollectionPolicy,
        redactor: TraceRedactor,
        subject: Callable[..., Any],
        tree_cid: str,
        source_cid: str,
        source_path: str,
        source_text: str,
        environment_binding_cid: str,
        privacy_class: str,
        include_raw_bodies: bool,
        cancellation: TraceCancellation,
        invoke_code: CodeType,
    ) -> None:
        self.policy = policy
        self.redactor = redactor
        self.subject = subject
        self.tree_cid = tree_cid
        self.source_cid = source_cid
        self.source_path = source_path
        self.source_text = source_text
        self.environment_binding_cid = environment_binding_cid
        self.privacy_class = privacy_class
        self.include_raw_bodies = include_raw_bodies
        self.cancellation = cancellation
        self.invoke_code = invoke_code
        self.subject_filename = _callable_code(subject).co_filename
        self.subject_code = _callable_code(subject)
        self.events: list[ProgramEvent] = []
        self.states: list[ProgramExecutionState] = []
        self.line_events = 0
        self.previous: Any = None
        self.busy = False
        self.stopped = False
        self.external_seen = False
        self.pending_exception: dict[int, tuple[type, BaseException]] = {}
        self.handler_lines = _handler_table(source_text)
        self.code_cids: dict[int, str] = {}
        self.predecessor: str | None = None
        self.redacted: set[str] = set()
        self.unavailable: set[str] = set()

    def code_cid(self, code: CodeType) -> str:
        cached = self.code_cids.get(id(code))
        if cached is not None:
            return cached
        cid = _code_cid(code)
        self.code_cids[id(code)] = cid
        return cid

    def column(self, frame: FrameType) -> int:
        # Column offsets depend on specialized instruction offsets; line
        # identity is the stable callsite coordinate.
        del frame
        return 0

    def admitted(self, frame: FrameType) -> bool:
        if frame.f_code is self.invoke_code:
            return False
        if frame.f_code.co_filename == __file__:
            return False
        return frame.f_code.co_filename == self.subject_filename

    def external_frame(self, frame: FrameType) -> str | None:
        module = frame.f_globals.get("__name__")
        if type(module) is not str:
            return None
        for prefix in _EXTERNAL_MODULE_PREFIXES:
            if module == prefix or module.startswith(prefix + "."):
                return f"{module}.{frame.f_code.co_name}"
        return None

    def stop(self) -> None:
        self.stopped = True
        try:
            sys.settrace(self.previous)
        except Exception:
            sys.settrace(None)

    def bound_reached(self) -> bool:
        if self.cancellation.is_cancelled():
            return True
        if len(self.events) >= self.policy.max_events:
            self.cancellation.cancel("event_bound", event_count=len(self.events))
            return True
        return False

    def emit_external(self, channel: str, symbol: str) -> None:
        self.external_seen = True
        if not self.policy.admits(EventKind.EXTERNAL.value):
            return
        if self.stopped or self.bound_reached():
            return
        payload, redacted = self.redactor.redact_mapping(
            {"channel": channel, "symbol": symbol, "denied": True}
        )
        self.redacted.update(redacted)
        self._append_event(
            kind=EventKind.EXTERNAL.value,
            frame=None,
            payload=payload,
            logical_name=symbol,
            code=self.subject_code,
            line=None,
            column=None,
        )

    def _stack_frames(self, frame: FrameType | None) -> tuple[StackFrameState, ...]:
        if frame is None:
            return ()
        raw: list[FrameType] = []
        current: FrameType | None = frame
        while current is not None:
            if current.f_code is self.invoke_code:
                break
            if current.f_code.co_filename != __file__ and self.admitted(current):
                raw.append(current)
            current = current.f_back
        if len(raw) > self.policy.max_frames:
            self.unavailable.add("outer_frames")
            raw = raw[: self.policy.max_frames]
        frames: list[StackFrameState] = []
        for ordinal, item in enumerate(raw):
            summary: dict[str, Any] = {}
            redacted: tuple[str, ...] = ()
            unavailable: tuple[str, ...] = ()
            claim = CompletenessClaim.FULL_STATE
            if self.policy.capture_locals and self.include_raw_bodies:
                summary, redacted_dims = self.redactor.redact_mapping(item.f_locals)
                redacted = redacted_dims
                if redacted:
                    claim = CompletenessClaim.REDACTED
                    self.redacted.update(redacted)
            frames.append(
                StackFrameState(
                    ordinal=ordinal,
                    language=ProgramLanguage.PYTHON,
                    tree_cid=self.tree_cid,
                    source_cid=self.source_cid,
                    code_cid=self.code_cid(item.f_code),
                    environment_binding_cid=self.environment_binding_cid,
                    logical_name=_logical_name_from_code(item.f_code, item.f_globals),
                    line=item.f_lineno if type(item.f_lineno) is int else 0,
                    column=self.column(item),
                    state_summary=summary,
                    redacted_dimensions=redacted,
                    unavailable_dimensions=unavailable,
                    completeness_claim=claim,
                    privacy_class=(
                        PrivacyClass.PRIVATE if self.include_raw_bodies else self.privacy_class
                    ),
                )
            )
        return tuple(frames)

    def _maybe_state(self, frames: Sequence[StackFrameState], exception: ExceptionSnapshot | None, handler: HandlerState | None) -> None:
        if not self.include_raw_bodies:
            return
        if len(self.states) >= self.policy.max_state_snapshots:
            self.unavailable.add("state_snapshots")
            return
        if not frames:
            return
        observed, redacted = ({}, ())
        if self.policy.capture_locals:
            observed, redacted = self.redactor.redact_mapping(
                {"locals": dict(frames[0].state_summary)}
            )
            self.redacted.update(redacted)
        claim: CompletenessClaim | str
        if redacted:
            claim = CompletenessClaim.REDACTED
        elif self.unavailable:
            claim = CompletenessClaim.PARTIAL
        else:
            claim = CompletenessClaim.FULL_STATE
        try:
            state = assemble_program_execution_state(
                capture_profile_cid=self.policy.policy_cid,
                tree_cid=self.tree_cid,
                source_cid=self.source_cid,
                environment_binding_cid=self.environment_binding_cid,
                frames=frames,
                observed_state=observed,
                heap_summary={"objects": len(frames)},
                heap_bound=HeapBound.BOUNDED_ABSTRACT,
                exception=exception,
                handler=handler,
                completeness_claim=claim,
                privacy_class=PrivacyClass.PRIVATE,
                includes_raw_bodies=True,
                unavailable_dimensions=tuple(sorted(self.unavailable)),
            )
        except ProgramExecutionError:
            self.unavailable.add("execution_state")
            return
        self.states.append(state)

    def _append_event(
        self,
        *,
        kind: str,
        frame: FrameType | None,
        payload: Mapping[str, Any],
        logical_name: str,
        code: CodeType,
        line: int | None,
        column: int | None,
        exception: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
        extra_unavailable: Sequence[str] = (),
    ) -> ProgramEvent | None:
        if not self.policy.admits(kind):
            return None
        if self.bound_reached():
            self.stop()
            return None
        frames = self._stack_frames(frame)
        unavailable = set(extra_unavailable)
        redacted = set()
        payload_dict, payload_redacted = self.redactor.redact_mapping(payload)
        redacted.update(payload_redacted)
        self.redacted.update(payload_redacted)
        if kind == EventKind.LINE.value:
            if self.line_events >= self.policy.max_line_events:
                self.unavailable.add("line")
                return None
            self.line_events += 1
        claim: CompletenessClaim | str = CompletenessClaim.FULL_STATE
        status = ObservationStatus.OBSERVED
        if redacted:
            claim = CompletenessClaim.REDACTED
            status = ObservationStatus.REDACTED
        if unavailable or (kind == EventKind.EXTERNAL.value and payload_dict.get("denied") is True):
            if not redacted:
                claim = CompletenessClaim.PARTIAL if unavailable else CompletenessClaim.FULL_STATE
        if kind == EventKind.UNAVAILABLE.value:
            claim = CompletenessClaim.UNAVAILABLE
            status = ObservationStatus.UNAVAILABLE
        privacy = PrivacyClass.PRIVATE if self.include_raw_bodies else self.privacy_class
        try:
            event = ProgramEvent(
                event_kind=kind,
                event_origin=EventOrigin.OBSERVED,
                observation_status=status,
                language=ProgramLanguage.PYTHON,
                tree_cid=self.tree_cid,
                source_cid=self.source_cid,
                code_cid=self.code_cid(code),
                environment_binding_cid=self.environment_binding_cid,
                subject_cid=self.code_cid(self.subject_code),
                logical_name=logical_name,
                payload=payload_dict,
                line=line if line is not None else (frames[0].line if frames else 0),
                column=column if column is not None else (frames[0].column if frames else 0),
                predecessor_event_cid=self.predecessor,
                stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
                exception_snapshot_cid=(
                    None if exception is None else exception.exception_snapshot_cid
                ),
                handler_state_cid=None if handler is None else handler.handler_state_cid,
                redaction_profile_cid=None,
                redacted_dimensions=tuple(sorted(redacted)),
                unavailable_dimensions=tuple(sorted(unavailable)),
                completeness_claim=claim,
                privacy_class=privacy if privacy != PrivacyClass.PUBLIC.value else PrivacyClass.INTERNAL,
            )
        except ProgramExecutionError as error:
            self.unavailable.add("event")
            raise PythonExecutionTraceError(str(error)) from error
        self.events.append(event)
        self.predecessor = event.program_event_cid
        self._maybe_state(frames, exception, handler)
        if self.bound_reached():
            self.stop()
        return event

    def _exception_snapshot(
        self, frame: FrameType, exc_type: type, exc: BaseException, frames: Sequence[StackFrameState]
    ) -> ExceptionSnapshot:
        summary, redacted = self.redactor.redact_mapping(
            {"type": getattr(exc_type, "__name__", "Exception"), "bounded": True}
        )
        self.redacted.update(redacted)
        claim = CompletenessClaim.REDACTED if redacted else CompletenessClaim.FULL_STATE
        return ExceptionSnapshot(
            language=ProgramLanguage.PYTHON,
            exception_type=getattr(exc_type, "__name__", "Exception"),
            tree_cid=self.tree_cid,
            source_cid=self.source_cid,
            code_cid=self.code_cid(frame.f_code),
            environment_binding_cid=self.environment_binding_cid,
            exception_value_summary=summary,
            traceback_stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
            future_execution=False,
            unavailable_dimensions=(),
            completeness_claim=claim,
        )

    def _handler_state(
        self, frame: FrameType, kind: str, exception: ExceptionSnapshot, frames: Sequence[StackFrameState]
    ) -> HandlerState:
        ordinal = frames[0].ordinal if frames else 0
        try:
            handler_kind = HandlerKind(kind)
        except ValueError:
            handler_kind = HandlerKind.EXCEPT
        return HandlerState(
            language=ProgramLanguage.PYTHON,
            handler_kind=handler_kind,
            tree_cid=self.tree_cid,
            source_cid=self.source_cid,
            code_cid=self.code_cid(frame.f_code),
            environment_binding_cid=self.environment_binding_cid,
            logical_name=_logical_name_from_code(frame.f_code, frame.f_globals),
            stack_ordinal=ordinal,
            handler_active=True,
            matching_exception_snapshot_cid=exception.exception_snapshot_cid,
        )

    def trace(self, frame: FrameType, event: str, arg: Any) -> Any:
        if self.stopped:
            return None
        if self.previous is not None and frame.f_code is not self.invoke_code:
            try:
                self.previous(frame, event, arg)
            except Exception:
                pass
        if self.busy:
            return self.trace
        if frame.f_code is self.invoke_code or frame.f_code.co_filename == __file__:
            return self.trace
        if self.bound_reached():
            self.stop()
            return None
        admitted = self.admitted(frame)
        if event == "call" and not admitted:
            symbol = self.external_frame(frame)
            if symbol is not None:
                self.emit_external(_channel_for_symbol(symbol), symbol)
            return None
        if not admitted:
            return None
        self.busy = True
        try:
            logical = _logical_name_from_code(frame.f_code, frame.f_globals)
            line = frame.f_lineno if type(frame.f_lineno) is int else 0
            column = self.column(frame)
            if event == "call":
                kind = EventKind.CALL.value
                if frame.f_code.co_name in _ENTER_NAMES:
                    kind = EventKind.ENTER.value
                elif frame.f_code.co_name in _EXIT_NAMES:
                    kind = EventKind.EXIT.value
                self._append_event(
                    kind=kind,
                    frame=frame,
                    payload={"callee": logical, "callsite_line": line},
                    logical_name=logical,
                    code=frame.f_code,
                    line=line,
                    column=column,
                )
                return self.trace
            if event == "line":
                pending = self.pending_exception.pop(id(frame), None)
                if pending is not None:
                    frames = self._stack_frames(frame)
                    snapshot = self._exception_snapshot(frame, pending[0], pending[1], frames)
                    handler_kind, exception_type = self.handler_lines.get(
                        line, (HandlerKind.EXCEPT.value, getattr(pending[0], "__name__", "Exception"))
                    )
                    handler = self._handler_state(frame, handler_kind, snapshot, frames)
                    self._append_event(
                        kind=EventKind.CATCH.value,
                        frame=frame,
                        payload={
                            "exception_type": getattr(pending[0], "__name__", "Exception"),
                            "handler_kind": handler_kind,
                        },
                        logical_name=logical,
                        code=frame.f_code,
                        line=line,
                        column=column,
                        exception=snapshot,
                        handler=handler,
                    )
                    self._append_event(
                        kind=EventKind.HANDLER.value,
                        frame=frame,
                        payload={
                            "exception_type": exception_type or getattr(pending[0], "__name__", "Exception"),
                            "handler_kind": handler_kind,
                        },
                        logical_name=logical,
                        code=frame.f_code,
                        line=line,
                        column=column,
                        exception=snapshot,
                        handler=handler,
                    )
                self._append_event(
                    kind=EventKind.LINE.value,
                    frame=frame,
                    payload={},
                    logical_name=logical,
                    code=frame.f_code,
                    line=line,
                    column=column,
                )
                return self.trace
            if event == "return":
                if _is_await_return(frame, event):
                    kind = EventKind.AWAIT.value
                    payload: dict[str, Any] = {"await": True}
                elif _is_yield_return(frame, event):
                    kind = EventKind.YIELD.value
                    payload = {"yield": True}
                elif frame.f_code.co_name in _EXIT_NAMES:
                    kind = EventKind.EXIT.value
                    payload = {"callee": logical}
                else:
                    kind = EventKind.RETURN.value
                    payload = {"callee": logical}
                self._append_event(
                    kind=kind,
                    frame=frame,
                    payload=payload,
                    logical_name=logical,
                    code=frame.f_code,
                    line=line,
                    column=column,
                )
                return self.trace
            if event == "exception":
                exc_type, exc, _tb = arg if isinstance(arg, tuple) and len(arg) >= 2 else (type(None), None, None)
                if not isinstance(exc, BaseException):
                    return self.trace
                self.pending_exception[id(frame)] = (exc_type, exc)
                frames = self._stack_frames(frame)
                snapshot = self._exception_snapshot(frame, exc_type, exc, frames)
                self._append_event(
                    kind=EventKind.RAISE.value,
                    frame=frame,
                    payload={"exception_type": getattr(exc_type, "__name__", "Exception")},
                    logical_name=logical,
                    code=frame.f_code,
                    line=line,
                    column=column,
                    exception=snapshot,
                )
                return self.trace
            return self.trace
        finally:
            self.busy = False


def _cancelled_placeholder(
    *,
    policy: TraceCollectionPolicy,
    tree_cid: str,
    source_cid: str,
    environment_binding_cid: str,
    subject_code: CodeType,
    subject_logical_name: str,
    cancellation: TraceCancellation,
    redactor: TraceRedactor,
    privacy_class: str,
) -> tuple[tuple[ProgramEvent, ...], RedactionProfile]:
    event = ProgramEvent(
        event_kind=EventKind.UNAVAILABLE.value,
        event_origin=EventOrigin.OBSERVED,
        observation_status=ObservationStatus.UNAVAILABLE,
        language=ProgramLanguage.PYTHON,
        tree_cid=tree_cid,
        source_cid=source_cid,
        code_cid=_code_cid(subject_code),
        environment_binding_cid=environment_binding_cid,
        subject_cid=_code_cid(subject_code),
        logical_name=subject_logical_name,
        payload={"cancelled": True, "reason": cancellation.reason},
        line=0,
        column=0,
        predecessor_event_cid=None,
        stack_frame_cids=(),
        redacted_dimensions=(),
        unavailable_dimensions=("execution", "call_stack"),
        completeness_claim=CompletenessClaim.UNAVAILABLE,
        privacy_class=PrivacyClass.INTERNAL,
    )
    profile = RedactionProfile(
        privacy_class=privacy_class,
        redacted_dimensions=(),
        unavailable_dimensions=("execution", "call_stack"),
        completeness_claim=CompletenessClaim.UNAVAILABLE,
    )
    del policy, redactor
    return (event,), profile


def _seal_record(
    *,
    status: str,
    policy: TraceCollectionPolicy,
    tree_cid: str,
    source_cid: str,
    environment_binding: Mapping[str, str],
    environment_binding_cid: str,
    subject_logical_name: str,
    subject_code_cid: str,
    events: Sequence[ProgramEvent],
    states: Sequence[ProgramExecutionState],
    cancellation: TraceCancellation | None,
    redacted: Sequence[str],
    unavailable: Sequence[str],
    include_raw_bodies: bool,
    privacy_class: str,
    result_kind: str,
    exception_type: str | None,
    external_seen: bool,
) -> PythonExecutionTraceRecord:
    event_list = tuple(events)
    if not event_list:
        raise PythonExecutionTraceError("collection produced no events")
    redacted_dims = tuple(sorted(set(redacted)))
    unavailable_dims = tuple(sorted(set(unavailable)))
    if cancellation is not None:
        claim: CompletenessClaim | str = CompletenessClaim.PARTIAL
        if not event_list or str(event_list[0].event_kind) == EventKind.UNAVAILABLE.value:
            claim = CompletenessClaim.UNAVAILABLE
            if not unavailable_dims:
                unavailable_dims = ("execution",)
        elif not unavailable_dims:
            unavailable_dims = ("suffix",)
    elif redacted_dims:
        claim = CompletenessClaim.REDACTED
    elif unavailable_dims:
        claim = CompletenessClaim.PARTIAL
    else:
        claim = CompletenessClaim.FULL_STATE
    profile = RedactionProfile(
        privacy_class=privacy_class if not include_raw_bodies else PrivacyClass.PRIVATE,
        redacted_dimensions=redacted_dims,
        unavailable_dimensions=unavailable_dims,
        completeness_claim=claim,
    )
    raw_states = tuple(states) if include_raw_bodies else ()
    trace_privacy = PrivacyClass.PRIVATE.value if include_raw_bodies else privacy_class
    trace = assemble_execution_trace(
        tree_cid=tree_cid,
        source_cid=source_cid,
        environment_binding_cid=environment_binding_cid,
        events=event_list,
        states=raw_states,
        redaction=profile,
        completeness_claim=claim,
        privacy_class=trace_privacy,
        includes_raw_bodies=include_raw_bodies,
        unavailable_dimensions=unavailable_dims,
    )
    observations: list[ExecutionObservation] = []
    for event in event_list:
        if event.observation_admissible:
            try:
                observations.append(observe_program_event(event))
            except ProgramExecutionError:
                continue
    replay_promised = (
        status == TraceStatus.COLLECTED.value
        and cancellation is None
        and not external_seen
        and not include_raw_bodies
        and EventKind.EXTERNAL.value not in {str(item.event_kind) for item in event_list}
    )
    return PythonExecutionTraceRecord(
        status=status,
        policy=policy,
        tree_cid=tree_cid,
        source_cid=source_cid,
        environment_binding_cid=environment_binding_cid,
        environment_binding=environment_binding,
        subject_logical_name=subject_logical_name,
        subject_code_cid=subject_code_cid,
        events=event_list,
        states=raw_states,
        trace=trace,
        observations=tuple(observations),
        redaction=profile,
        cancellation=None if cancellation is None else cancellation.snapshot(),
        replay_promised=replay_promised,
        privacy_class=trace_privacy,
        includes_raw_bodies=include_raw_bodies,
        result_kind=result_kind,
        exception_type=exception_type,
    )


def record_python_execution_trace(
    subject: Callable[..., Any],
    *,
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    policy: TraceCollectionPolicy | None = None,
    tree_cid: str | None = None,
    source_text: str | None = None,
    source_path: str | None = None,
    environment_binding: Mapping[str, str] | None = None,
    cancellation: TraceCancellation | None = None,
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL,
    include_raw_bodies: bool = False,
    redactor: TraceRedactor | None = None,
) -> PythonExecutionTraceRecord:
    """Collect a hermetic, bounded Python execution trace for ``subject``.

    The subject runs in-process under ``sys.settrace``.  Network, subprocess,
    database, watcher, and model-load channels are denied for the duration of
    collection.  Cancellation never returns an accepted transition.
    """

    if not callable(subject):
        raise PythonExecutionTraceError("subject must be callable")
    policy = policy if policy is not None else TraceCollectionPolicy()
    if not isinstance(policy, TraceCollectionPolicy):
        raise PythonExecutionTraceError("policy must be a TraceCollectionPolicy")
    redactor = redactor if redactor is not None else TraceRedactor.from_policy(policy)
    include_raw = _bool(include_raw_bodies, "include_raw_bodies")
    privacy = (
        privacy_class.value if isinstance(privacy_class, PrivacyClass) else _text(privacy_class, "privacy_class")
    )
    if include_raw and privacy in _PUBLIC_PRIVACY:
        raise PythonExecutionTraceError(
            "raw trace bodies remain private and cannot enter public records"
        )
    env_map = dict(_default_environment())
    if environment_binding is not None:
        binding = _mapping(environment_binding, "environment_binding")
        env_map = {str(key): str(value) for key, value in binding.items()}
        if env_map.get("language", ADMITTED_LANGUAGE) != ADMITTED_LANGUAGE:
            raise PythonExecutionTraceError("environment language is typed unavailable")
    env_cid = _environment_cid(env_map)
    code = _callable_code(subject)
    text, source_cid = _source_from_callable(subject, source_text)
    path = source_path if source_path is not None else (code.co_filename or "")
    bound_tree = _tree_cid(source_cid, path, tree_cid)
    logical = _logical_name_from_callable(_unwrap_callable(subject))
    token = cancellation if cancellation is not None else TraceCancellation("idle")
    invoke_code = record_python_execution_trace.__code__

    if token.is_cancelled():
        events, profile = _cancelled_placeholder(
            policy=policy,
            tree_cid=bound_tree,
            source_cid=source_cid,
            environment_binding_cid=env_cid,
            subject_code=code,
            subject_logical_name=logical,
            cancellation=token,
            redactor=redactor,
            privacy_class=privacy,
        )
        del profile
        token.cancel(token.reason, event_count=0)
        return _seal_record(
            status=TraceStatus.CANCELLED.value,
            policy=policy,
            tree_cid=bound_tree,
            source_cid=source_cid,
            environment_binding=env_map,
            environment_binding_cid=env_cid,
            subject_logical_name=logical,
            subject_code_cid=_code_cid(code),
            events=events,
            states=(),
            cancellation=token,
            redacted=(),
            unavailable=("execution", "call_stack"),
            include_raw_bodies=False,
            privacy_class=privacy,
            result_kind="cancelled",
            exception_type=None,
            external_seen=False,
        )

    collector = _Collector(
        policy=policy,
        redactor=redactor,
        subject=subject,
        tree_cid=bound_tree,
        source_cid=source_cid,
        source_path=path,
        source_text=text,
        environment_binding_cid=env_cid,
        privacy_class=privacy,
        include_raw_bodies=include_raw,
        cancellation=token,
        invoke_code=invoke_code,
    )
    call_kwargs = dict(kwargs or {})
    result_kind = "value"
    exception_type: str | None = None
    guard = _IsolationGuard(policy, collector.emit_external)
    collector.previous = sys.gettrace()
    try:
        guard.install()
        sys.settrace(collector.trace)
        try:
            if inspect.iscoroutinefunction(subject):
                _drive_coroutine(subject(*tuple(args), **call_kwargs))
            else:
                subject(*tuple(args), **call_kwargs)
        except HermeticIsolationError as error:
            result_kind = "isolated"
            exception_type = type(error).__name__
            collector.external_seen = True
        except Exception as error:
            result_kind = "exception"
            exception_type = type(error).__name__
        finally:
            sys.settrace(collector.previous)
    finally:
        guard.restore()
        sys.settrace(collector.previous)

    if token.is_cancelled():
        status = TraceStatus.CANCELLED.value
        result_kind = "cancelled"
        token.cancel(token.reason, event_count=len(collector.events))
    elif result_kind == "isolated":
        status = TraceStatus.ISOLATED.value
    elif not collector.events:
        status = TraceStatus.FAILED.value
        collector.unavailable.add("execution")
        events, _profile = _cancelled_placeholder(
            policy=policy,
            tree_cid=bound_tree,
            source_cid=source_cid,
            environment_binding_cid=env_cid,
            subject_code=code,
            subject_logical_name=logical,
            cancellation=TraceCancellation("empty"),
            redactor=redactor,
            privacy_class=privacy,
        )
        collector.events.extend(events)
    else:
        status = TraceStatus.COLLECTED.value

    cancellation_record: TraceCancellation | None
    if status == TraceStatus.CANCELLED.value:
        cancellation_record = token
    else:
        cancellation_record = None

    return _seal_record(
        status=status,
        policy=policy,
        tree_cid=bound_tree,
        source_cid=source_cid,
        environment_binding=env_map,
        environment_binding_cid=env_cid,
        subject_logical_name=logical,
        subject_code_cid=_code_cid(code),
        events=collector.events,
        states=collector.states,
        cancellation=cancellation_record,
        redacted=tuple(collector.redacted),
        unavailable=tuple(collector.unavailable),
        include_raw_bodies=include_raw,
        privacy_class=privacy,
        result_kind=result_kind,
        exception_type=exception_type,
        external_seen=collector.external_seen,
    )


def replay_deterministic_trace(
    record: PythonExecutionTraceRecord,
    *,
    subject: Callable[..., Any],
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    policy: TraceCollectionPolicy | None = None,
    cancellation: TraceCancellation | None = None,
) -> PythonExecutionTraceReplay:
    """Replay a promised deterministic trace under the original bindings.

    Cancelled collections and traces with external effects are not replayable
    as accepted transitions.  Tree, source, code, and environment identities
    must match exactly.
    """

    if not isinstance(record, PythonExecutionTraceRecord):
        raise PythonExecutionTraceError("replay requires a PythonExecutionTraceRecord")
    if record.cancellation is not None or not record.accepted_transition:
        raise PythonExecutionTraceError("cancellation emits no accepted transition")
    if not record.replay_promised:
        raise PythonExecutionTraceError("replay is not promised for this trace")
    replayed = record_python_execution_trace(
        subject,
        args=args,
        kwargs=kwargs,
        policy=policy if policy is not None else record.policy,
        tree_cid=record.tree_cid,
        environment_binding=record.environment_binding,
        cancellation=cancellation,
        privacy_class=PrivacyClass.INTERNAL,
        include_raw_bodies=False,
    )
    if replayed.tree_cid != record.tree_cid:
        raise PythonExecutionTraceError("replay tree_cid does not match the original binding")
    if replayed.source_cid != record.source_cid:
        raise PythonExecutionTraceError("replay source_cid does not match the original binding")
    if replayed.environment_binding_cid != record.environment_binding_cid:
        raise PythonExecutionTraceError(
            "replay environment_binding_cid does not match the original binding"
        )
    if replayed.subject_code_cid != record.subject_code_cid:
        raise PythonExecutionTraceError("replay subject code_cid does not match the original binding")
    if not replayed.accepted_transition:
        raise PythonExecutionTraceError("cancellation emits no accepted transition")
    matched = (
        replayed.trace.execution_trace_cid == record.trace.execution_trace_cid
        and tuple(replayed.trace.event_cids) == tuple(record.trace.event_cids)
    )
    return PythonExecutionTraceReplay(
        matched=matched,
        original_trace_cid=record.trace.execution_trace_cid,
        replay_trace_cid=replayed.trace.execution_trace_cid,
        original_event_cids=tuple(record.trace.event_cids),
        replay_event_cids=tuple(replayed.trace.event_cids),
        original_code_cid=record.subject_code_cid,
        replay_code_cid=replayed.subject_code_cid,
        original_environment_binding_cid=record.environment_binding_cid,
        replay_environment_binding_cid=replayed.environment_binding_cid,
        accepted_transition=replayed.accepted_transition,
    )


__all__ = [
    "ADMITTED_EVENT_KINDS",
    "ADMITTED_LANGUAGE",
    "IMPORT_SCAN_PERFORMED",
    "IMPORT_SIDE_EFFECTS_PERFORMED",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "HermeticIsolationError",
    "PythonExecutionTraceError",
    "PythonExecutionTraceRecord",
    "PythonExecutionTraceReplay",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCollectionPolicy",
    "TraceRedactor",
    "TraceStatus",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]

