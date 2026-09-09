"""Hermetic Python execution tracing (SAWM-008).

This module is the datasets tracing adapter for SAWM-G022.  It collects
admitted call, return, line, exception, handler, yield, await, and selected
external events under the SAWM-007 ``ProgramEvent@1`` / ``ExecutionTrace@1``
contracts, with exact symbol, callsite, source, tree, and environment
identity, bounded state summaries, cancellation, and redaction.

Normative constraints:

* Importing this module never opens a network or socket, never starts a
  subprocess, installer, database, watcher, or model load, and never scans a
  repository.  Construction is explicit via
  :func:`record_python_execution_trace`.
* Cancellation emits no accepted transition.  This adapter never persists
  operational acceptance.
* Private raw trace bodies never enter public records.
* Line and basic-block detail is policy- and cost-bounded.  Nondeterministic
  external effects are explicit observations or typed unavailable.
* Python only.  Arbitrary shell tracing is out of scope.
"""

from __future__ import annotations

import ast
import dis
import inspect
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import CodeType, FrameType, MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_structured,
)
from ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution import (
    FORBIDDEN_FIELD_MARKERS,
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
PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE: Final[str] = (
    "PythonExecutionReplayReceipt@1"
)
TRACE_COLLECTION_RECEIPT_INTERFACE: Final[str] = "TraceCollectionReceipt@1"

PYTHON_EXECUTION_TRACER_VERSION: Final[str] = "1"
TRACE_COLLECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-policy@1"
)
TRACE_COLLECTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-receipt@1"
)
PYTHON_EXECUTION_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-environment@1"
)
PYTHON_EXECUTION_CODE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-code@1"
)
PYTHON_EXECUTION_SUBJECT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-subject@1"
)
PYTHON_EXECUTION_TREE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-tree@1"
)
PYTHON_EXECUTION_REPLAY_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-replay-receipt@1"
)
PYTHON_EXECUTION_BINDING_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-binding@1"
)

ADMITTED_LANGUAGE: Final[str] = "python"

# Importing this module must remain a no-scan / no-I/O operation.
IMPORT_SCAN_PERFORMED: Final[bool] = False
IMPORT_NETWORK_PERFORMED: Final[bool] = False
IMPORT_SOCKET_PERFORMED: Final[bool] = False
IMPORT_INSTALLER_PERFORMED: Final[bool] = False
IMPORT_SUBPROCESS_PERFORMED: Final[bool] = False
IMPORT_DATABASE_PERFORMED: Final[bool] = False
IMPORT_WATCHER_PERFORMED: Final[bool] = False
IMPORT_MODEL_LOAD_PERFORMED: Final[bool] = False

MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
MAX_TEXT_CHARS: Final[int] = 16_384
DEFAULT_MAX_EVENTS: Final[int] = 4_096
DEFAULT_MAX_LINE_EVENTS: Final[int] = 256
DEFAULT_MAX_FRAMES: Final[int] = 32
DEFAULT_MAX_SUMMARY_ITEMS: Final[int] = 32
DEFAULT_MAX_SUMMARY_CHARS: Final[int] = 128
DEFAULT_MAX_SUMMARY_DEPTH: Final[int] = 2

_EXTERNAL_MODULE_PREFIXES: Final[tuple[str, ...]] = (
    "socket",
    "ssl",
    "select",
    "selectors",
    "subprocess",
    "multiprocessing",
    "urllib",
    "http",
    "requests",
    "httpx",
    "aiohttp",
    "sqlite3",
    "duckdb",
    "psycopg2",
    "pymongo",
    "redis",
    "watchdog",
    "torch",
    "transformers",
)
_EXTERNAL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "connect",
        "create_connection",
        "getaddrinfo",
        "urlopen",
        "Popen",
        "run",
        "system",
        "posix_spawn",
        "urlretrieve",
        "urlopen",
        "CDLL",
        "PyDLL",
        "WinDLL",
    }
)
_YIELD_OPNAMES: Final[frozenset[str]] = frozenset(
    {"YIELD_VALUE", "YIELD_FROM", "RETURN_GENERATOR"}
)
_AWAIT_OPNAMES: Final[frozenset[str]] = frozenset(
    {"GET_AWAITABLE", "SEND", "BEFORE_ASYNC_WITH", "GET_AITER", "GET_ANEXT"}
)
_RETURN_OPNAMES: Final[frozenset[str]] = frozenset(
    {"RETURN_VALUE", "RETURN_CONST"}
)
_FORBIDDEN_TOP_LEVEL_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "socket",
        "ssl",
        "subprocess",
        "multiprocessing",
        "sqlite3",
        "duckdb",
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "torch",
        "transformers",
        "watchdog",
        "psycopg2",
        "pymongo",
        "redis",
        "celery",
    }
)
_TRACER_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        __file__,
    }
)
_SECRET_KEYS: Final[frozenset[str]] = frozenset(
    key.lower() for key in (SECRET_FIELD_MARKERS | FORBIDDEN_FIELD_MARKERS)
)


# ---------------------------------------------------------------------------
# Errors / enums
# ---------------------------------------------------------------------------


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic tracing inputs, policy, or results are unsound."""


class CollectionOutcome(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    BOUNDED = "bounded"


class TraceCancellation(BaseException):
    """Cancel hermetic collection.  Never an accepted transition."""

    INTERFACE: ClassVar[str] = TRACE_CANCELLATION_INTERFACE
    accepted_transition: ClassVar[bool] = False

    def __init__(self, reason: str = "cancelled") -> None:
        text = _text(reason, "cancellation reason")
        super().__init__(text)
        self.reason = text
        self._cancelled = False

    def cancel(self, reason: str | None = None) -> "TraceCancellation":
        if reason is not None:
            self.reason = _text(reason, "cancellation reason")
        self._cancelled = True
        return self

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def throw_if_cancelled(self) -> None:
        if self._cancelled:
            raise self


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
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


def _pos_int(value: Any, name: str, *, minimum: int = 1) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise PythonExecutionTraceError(f"{name} must be an integer >= {minimum}")
    if value > MAX_SAFE_INTEGER:
        raise PythonExecutionTraceError(f"{name} exceeds the safe JSON integer range")
    return value


def _privacy(value: Any) -> str:
    if isinstance(value, PrivacyClass):
        return value.value
    try:
        return PrivacyClass(value).value
    except (TypeError, ValueError) as exc:
        raise PythonExecutionTraceError(f"unsupported privacy_class {value!r}") from exc


def _unique_sorted(values: Sequence[str] | object, name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise PythonExecutionTraceError(f"{name} must be a sequence of strings")
    items = tuple(sorted({_text(item, name) for item in values}))
    return items


def _normalize_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _is_forbidden_key(key: str) -> bool:
    return _normalize_key(key) in _SECRET_KEYS


def _environment_cid(bindings: Mapping[str, str] | None) -> str:
    if bindings is None:
        bindings = {}
    if not isinstance(bindings, Mapping):
        raise PythonExecutionTraceError("environment_binding must be a string mapping")
    items: list[dict[str, str]] = []
    for key, value in bindings.items():
        items.append(
            {
                "key": _text(str(key), "environment key"),
                "value": _text(str(value), "environment value"),
            }
        )
    items.sort(key=lambda item: (item["key"], item["value"]))
    return cid_for_structured(
        {"schema": PYTHON_EXECUTION_ENVIRONMENT_SCHEMA, "bindings": items}
    )


def _freeze_binding(bindings: Mapping[str, str] | None) -> Mapping[str, str]:
    if bindings is None:
        bindings = {}
    if not isinstance(bindings, Mapping):
        raise PythonExecutionTraceError("environment_binding must be a string mapping")
    frozen = {
        _text(str(key), "environment key"): _text(str(value), "environment value")
        for key, value in bindings.items()
    }
    return MappingProxyType(dict(sorted(frozen.items())))


def _default_environment() -> dict[str, str]:
    info = sys.version_info
    return {
        "implementation": sys.implementation.name,
        "language": ADMITTED_LANGUAGE,
        "python_major": str(info.major),
        "python_micro": str(info.micro),
        "python_minor": str(info.minor),
    }


def _logical_name_of(frame: FrameType) -> str:
    module = frame.f_globals.get("__name__")
    module_text = module if type(module) is str and module else ""
    qual = getattr(frame.f_code, "co_qualname", frame.f_code.co_name)
    if type(qual) is not str or not qual:
        qual = frame.f_code.co_name
    if module_text:
        return f"{module_text}.{qual}"
    return str(qual)


def _callable_logical_name(subject: Callable[..., Any]) -> str:
    module = getattr(subject, "__module__", "") or ""
    qual = getattr(subject, "__qualname__", "") or getattr(subject, "__name__", "") or "subject"
    module_text = module if type(module) is str else ""
    qual_text = qual if type(qual) is str else "subject"
    if module_text:
        return f"{module_text}.{qual_text}"
    return qual_text


def _source_bytes_of(
    subject: Callable[..., Any], explicit: str | bytes | None
) -> tuple[bytes, bool]:
    if explicit is not None:
        if isinstance(explicit, bytes):
            return explicit, True
        if type(explicit) is str:
            return explicit.encode("utf-8"), True
        raise PythonExecutionTraceError("source must be text or UTF-8 bytes")
    try:
        return inspect.getsource(subject).encode("utf-8"), True
    except (OSError, TypeError, SyntaxError):
        code = getattr(subject, "__code__", None)
        if isinstance(code, CodeType):
            return code.co_code, False
        return b"unavailable", False


def _code_cid(logical_name: str, source_cid: str, firstlineno: int) -> str:
    return cid_for_structured(
        {
            "schema": PYTHON_EXECUTION_CODE_SCHEMA,
            "firstlineno": firstlineno,
            "language": ADMITTED_LANGUAGE,
            "logical_name": logical_name,
            "source_cid": source_cid,
        }
    )


def _subject_cid(logical_name: str, source_cid: str, code_cid: str) -> str:
    return cid_for_structured(
        {
            "schema": PYTHON_EXECUTION_SUBJECT_SCHEMA,
            "code_cid": code_cid,
            "language": ADMITTED_LANGUAGE,
            "logical_name": logical_name,
            "source_cid": source_cid,
        }
    )


def _tree_cid_from_source(source_cid: str, logical_name: str) -> str:
    return cid_for_structured(
        {
            "schema": PYTHON_EXECUTION_TREE_SCHEMA,
            "language": ADMITTED_LANGUAGE,
            "sources": [{"logical_name": logical_name, "source_cid": source_cid}],
        }
    )


def _instruction_at(code: CodeType, lasti: int) -> dis.Instruction | None:
    found: dis.Instruction | None = None
    try:
        for instruction in dis.get_instructions(code):
            if instruction.offset <= lasti:
                found = instruction
            else:
                break
    except (TypeError, ValueError, SystemError):
        return None
    return found


def _column_of(code: CodeType, lasti: int) -> int | None:
    instruction = _instruction_at(code, lasti)
    if instruction is None:
        return None
    positions = getattr(instruction, "positions", None)
    if positions is None:
        return None
    column = getattr(positions, "col_offset", None)
    if type(column) is int and not isinstance(column, bool) and column >= 0:
        return column
    return None


def _handler_ranges(source: bytes) -> tuple[tuple[int, int, str], ...]:
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return ()
    ranges: list[tuple[int, int, str]] = []

    def _span(node: ast.AST, kind: str) -> None:
        lineno = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", lineno)
        if type(lineno) is int and type(end) is int:
            ranges.append((lineno, end, kind))

    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            _span(node, HandlerKind.EXCEPT.value)
        elif isinstance(node, ast.Try):
            for item in node.finalbody:
                _span(item, HandlerKind.FINALLY.value)
            for item in node.orelse:
                _span(item, HandlerKind.ELSE.value)
        elif type(node).__name__ == "TryStar":
            for handler in getattr(node, "handlers", ()):
                _span(handler, HandlerKind.EXCEPT_STAR.value)
    return tuple(ranges)


def _in_handler(
    ranges: Sequence[tuple[int, int, str]], lineno: int | None
) -> str | None:
    if type(lineno) is not int:
        return None
    for start, end, kind in ranges:
        if start <= lineno <= end:
            return kind
    return None


def _is_external_frame(frame: FrameType) -> bool:
    module = frame.f_globals.get("__name__")
    module_text = module if type(module) is str else ""
    name = frame.f_code.co_name
    if name in _EXTERNAL_NAMES:
        return True
    for prefix in _EXTERNAL_MODULE_PREFIXES:
        if module_text == prefix or module_text.startswith(prefix + "."):
            return True
    return False


def _is_internal_frame(frame: FrameType) -> bool:
    filename = frame.f_code.co_filename
    if filename in _TRACER_FILENAMES:
        return True
    if filename.endswith("python_execution_trace.py"):
        return True
    return False


# ---------------------------------------------------------------------------
# Policy / redactor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Cost-bounded collection policy for hermetic Python tracing."""

    collect_call: bool = True
    collect_return: bool = True
    collect_line: bool = True
    collect_exception: bool = True
    collect_handler: bool = True
    collect_yield: bool = True
    collect_await: bool = True
    collect_external: bool = True
    max_events: int = DEFAULT_MAX_EVENTS
    max_line_events: int = DEFAULT_MAX_LINE_EVENTS
    max_frames: int = DEFAULT_MAX_FRAMES
    max_summary_items: int = DEFAULT_MAX_SUMMARY_ITEMS
    max_summary_chars: int = DEFAULT_MAX_SUMMARY_CHARS
    include_raw_bodies: bool = False
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL
    redacted_dimensions: Sequence[str] = ()
    deny_network: bool = True
    deny_subprocess: bool = True
    deny_socket: bool = True
    deny_database: bool = True

    SCHEMA: ClassVar[str] = TRACE_COLLECTION_POLICY_SCHEMA
    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "collect_call", _bool(self.collect_call, "collect_call"))
        object.__setattr__(
            self, "collect_return", _bool(self.collect_return, "collect_return")
        )
        object.__setattr__(self, "collect_line", _bool(self.collect_line, "collect_line"))
        object.__setattr__(
            self,
            "collect_exception",
            _bool(self.collect_exception, "collect_exception"),
        )
        object.__setattr__(
            self, "collect_handler", _bool(self.collect_handler, "collect_handler")
        )
        object.__setattr__(
            self, "collect_yield", _bool(self.collect_yield, "collect_yield")
        )
        object.__setattr__(
            self, "collect_await", _bool(self.collect_await, "collect_await")
        )
        object.__setattr__(
            self, "collect_external", _bool(self.collect_external, "collect_external")
        )
        object.__setattr__(self, "max_events", _pos_int(self.max_events, "max_events"))
        object.__setattr__(
            self, "max_line_events", _pos_int(self.max_line_events, "max_line_events")
        )
        object.__setattr__(self, "max_frames", _pos_int(self.max_frames, "max_frames"))
        object.__setattr__(
            self,
            "max_summary_items",
            _pos_int(self.max_summary_items, "max_summary_items"),
        )
        object.__setattr__(
            self,
            "max_summary_chars",
            _pos_int(self.max_summary_chars, "max_summary_chars"),
        )
        object.__setattr__(
            self,
            "include_raw_bodies",
            _bool(self.include_raw_bodies, "include_raw_bodies"),
        )
        privacy = _privacy(self.privacy_class)
        if self.include_raw_bodies and privacy in {"public", "internal"}:
            privacy = PrivacyClass.PRIVATE.value
        object.__setattr__(self, "privacy_class", privacy)
        object.__setattr__(
            self,
            "redacted_dimensions",
            _unique_sorted(self.redacted_dimensions, "redacted_dimension"),
        )
        object.__setattr__(self, "deny_network", _bool(self.deny_network, "deny_network"))
        object.__setattr__(
            self, "deny_subprocess", _bool(self.deny_subprocess, "deny_subprocess")
        )
        object.__setattr__(self, "deny_socket", _bool(self.deny_socket, "deny_socket"))
        object.__setattr__(
            self, "deny_database", _bool(self.deny_database, "deny_database")
        )

    def allows(self, kind: str) -> bool:
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
            EventKind.ENTER.value: True,
            EventKind.EXIT.value: True,
            EventKind.OBSERVE.value: True,
        }
        return mapping.get(kind, True)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "collect_await": self.collect_await,
            "collect_call": self.collect_call,
            "collect_exception": self.collect_exception,
            "collect_external": self.collect_external,
            "collect_handler": self.collect_handler,
            "collect_line": self.collect_line,
            "collect_return": self.collect_return,
            "collect_yield": self.collect_yield,
            "deny_database": self.deny_database,
            "deny_network": self.deny_network,
            "deny_socket": self.deny_socket,
            "deny_subprocess": self.deny_subprocess,
            "include_raw_bodies": self.include_raw_bodies,
            "max_events": self.max_events,
            "max_frames": self.max_frames,
            "max_line_events": self.max_line_events,
            "max_summary_chars": self.max_summary_chars,
            "max_summary_items": self.max_summary_items,
            "privacy_class": self.privacy_class,
            "redacted_dimensions": list(self.redacted_dimensions),
            "schema": self.SCHEMA,
        }

    @property
    def capture_profile_cid(self) -> str:
        return cid_for_structured(self.identity_payload())


class TraceRedactor:
    """Strip secrets and project public records without raw bodies."""

    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE

    def __init__(self, extra_redacted: Sequence[str] = ()) -> None:
        extra = _unique_sorted(extra_redacted, "redacted_dimension") if extra_redacted else ()
        self.extra_redacted = extra

    def is_forbidden_key(self, key: str) -> bool:
        return type(key) is str and _is_forbidden_key(key)

    def summarize(
        self,
        value: Any,
        *,
        max_chars: int,
        depth: int = 0,
        redacted: set[str] | None = None,
    ) -> Any:
        marks = redacted if redacted is not None else set()
        if depth > DEFAULT_MAX_SUMMARY_DEPTH:
            return {"type": type(value).__name__, "unavailable": True}
        if value is None or type(value) is bool:
            return value
        if type(value) is int and not isinstance(value, bool):
            if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
                marks.add("integer_range")
                return {"reason": "overflow", "type": "int", "unavailable": True}
            return value
        if type(value) is str:
            if self.is_forbidden_key(value):
                marks.add("secrets")
                return {"redacted": True, "type": "str"}
            if len(value) > max_chars:
                return value[:max_chars]
            return value
        if type(value) is float:
            marks.add("float_values")
            return {"type": "float", "unavailable": True}
        if isinstance(value, Mapping):
            mapping, nested = self.summarize_mapping(
                value, max_items=DEFAULT_MAX_SUMMARY_ITEMS, max_chars=max_chars, depth=depth + 1
            )
            marks.update(nested)
            return mapping
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            items: list[Any] = []
            for item in list(value)[:DEFAULT_MAX_SUMMARY_ITEMS]:
                items.append(
                    self.summarize(
                        item, max_chars=max_chars, depth=depth + 1, redacted=marks
                    )
                )
            return items
        marks.add("native_value")
        return {"type": type(value).__name__, "unavailable": True}

    def summarize_mapping(
        self,
        mapping: Mapping[str, Any] | None,
        *,
        max_items: int,
        max_chars: int,
        depth: int = 0,
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        if not isinstance(mapping, Mapping):
            return {}, ()
        result: dict[str, Any] = {}
        redacted: set[str] = set(self.extra_redacted)
        for key, value in mapping.items():
            if type(key) is not str or not key:
                continue
            if self.is_forbidden_key(key):
                redacted.add("secrets" if _normalize_key(key) in SECRET_FIELD_MARKERS else key)
                continue
            if len(result) >= max_items:
                redacted.add("summary_items")
                break
            result[key] = self.summarize(
                value, max_chars=max_chars, depth=depth, redacted=redacted
            )
        return result, tuple(sorted(redacted))

    def public_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        if not isinstance(trace, ExecutionTrace):
            raise PythonExecutionTraceError("public_trace requires an ExecutionTrace")
        public = trace.public_view()
        if public.includes_raw_bodies or public.raw_execution_state_cids:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if public.privacy_class != PrivacyClass.PUBLIC.value:
            raise PythonExecutionTraceError("public traces must use privacy_class public")
        return public

    def public_state(self, state: ProgramExecutionState) -> ProgramExecutionState:
        if not isinstance(state, ProgramExecutionState):
            raise PythonExecutionTraceError(
                "public_state requires a ProgramExecutionState"
            )
        public = public_execution_view(state)
        if public.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        return public


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PythonExecutionBinding:
    """Exact tree, source, capture, and environment identities for one run."""

    tree_cid: str
    source_cid: str
    code_cid: str
    subject_cid: str
    environment_binding_cid: str
    capture_profile_cid: str
    environment_binding: Mapping[str, str]
    source_available: bool
    logical_name: str
    language: str = ADMITTED_LANGUAGE

    SCHEMA: ClassVar[str] = PYTHON_EXECUTION_BINDING_SCHEMA

    def identity_payload(self) -> dict[str, Any]:
        return {
            "capture_profile_cid": self.capture_profile_cid,
            "code_cid": self.code_cid,
            "environment_binding": dict(self.environment_binding),
            "environment_binding_cid": self.environment_binding_cid,
            "language": self.language,
            "logical_name": self.logical_name,
            "schema": self.SCHEMA,
            "source_available": self.source_available,
            "source_cid": self.source_cid,
            "subject_cid": self.subject_cid,
            "tree_cid": self.tree_cid,
        }

    @property
    def binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())


@dataclass(frozen=True, slots=True)
class TraceCollectionReceipt:
    """Sealed collection outcome; cancellation never accepts a transition."""

    outcome: str
    accepted_transition: bool
    operational_acceptance: bool
    cancelled: bool
    bounded: bool
    event_count: int
    public_trace_cid: str
    private_trace_cid: str
    capture_profile_cid: str
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    binding_cid: str
    redacted_dimensions: tuple[str, ...]
    unavailable_dimensions: tuple[str, ...]
    cancellation_reason: str | None = None

    SCHEMA: ClassVar[str] = TRACE_COLLECTION_RECEIPT_SCHEMA
    INTERFACE: ClassVar[str] = TRACE_COLLECTION_RECEIPT_INTERFACE

    def identity_payload(self) -> dict[str, Any]:
        return {
            "accepted_transition": self.accepted_transition,
            "binding_cid": self.binding_cid,
            "bounded": self.bounded,
            "cancellation_reason": self.cancellation_reason,
            "cancelled": self.cancelled,
            "capture_profile_cid": self.capture_profile_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "event_count": self.event_count,
            "operational_acceptance": False,
            "outcome": self.outcome,
            "private_trace_cid": self.private_trace_cid,
            "public_trace_cid": self.public_trace_cid,
            "redacted_dimensions": list(self.redacted_dimensions),
            "schema": self.SCHEMA,
            "source_cid": self.source_cid,
            "tree_cid": self.tree_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def trace_collection_receipt_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["trace_collection_receipt_cid"] = self.trace_collection_receipt_cid
        return payload


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceRecord:
    """Private collection result plus a public view that never carries raw bodies."""

    outcome: str
    accepted_transition: bool
    operational_acceptance: bool
    binding: PythonExecutionBinding
    policy: TraceCollectionPolicy
    events: tuple[ProgramEvent, ...]
    states: tuple[ProgramExecutionState, ...]
    observations: tuple[ExecutionObservation, ...]
    private_trace: ExecutionTrace
    public_trace: ExecutionTrace
    public_states: tuple[ProgramExecutionState, ...]
    receipt: TraceCollectionReceipt
    cancellation_reason: str | None = None
    bounded: bool = False
    result_summary: Mapping[str, Any] = field(default_factory=dict)
    redacted_dimensions: tuple[str, ...] = ()
    unavailable_dimensions: tuple[str, ...] = ()

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECORD_INTERFACE

    def __post_init__(self) -> None:
        if self.public_trace.includes_raw_bodies or self.public_trace.raw_execution_state_cids:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if self.public_trace.privacy_class != PrivacyClass.PUBLIC.value:
            raise PythonExecutionTraceError("public traces must use privacy_class public")
        for state in self.public_states:
            if state.includes_raw_bodies:
                raise PythonExecutionTraceError(
                    "private raw trace bodies never enter public records"
                )
        object.__setattr__(self, "operational_acceptance", False)
        if self.outcome == CollectionOutcome.CANCELLED.value and self.accepted_transition:
            raise PythonExecutionTraceError("cancellation emits no accepted transition")


@dataclass(frozen=True, slots=True)
class PythonExecutionReplayReceipt:
    """Deterministic promised-replay comparison under exact bindings."""

    matched: bool
    binding_matched: bool
    accepted_transition: bool
    operational_acceptance: bool
    original_outcome: str
    replayed_outcome: str
    original_trace_cid: str
    replayed_trace_cid: str
    original_public_trace_cid: str
    replayed_public_trace_cid: str
    diverged_event_cids: tuple[str, ...]
    original_event_cids: tuple[str, ...]
    replayed_event_cids: tuple[str, ...]

    SCHEMA: ClassVar[str] = PYTHON_EXECUTION_REPLAY_RECEIPT_SCHEMA
    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE

    def identity_payload(self) -> dict[str, Any]:
        return {
            "accepted_transition": self.accepted_transition,
            "binding_matched": self.binding_matched,
            "diverged_event_cids": list(self.diverged_event_cids),
            "matched": self.matched,
            "operational_acceptance": False,
            "original_event_cids": list(self.original_event_cids),
            "original_outcome": self.original_outcome,
            "original_public_trace_cid": self.original_public_trace_cid,
            "original_trace_cid": self.original_trace_cid,
            "replayed_event_cids": list(self.replayed_event_cids),
            "replayed_outcome": self.replayed_outcome,
            "replayed_public_trace_cid": self.replayed_public_trace_cid,
            "replayed_trace_cid": self.replayed_trace_cid,
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


@dataclass(frozen=True, slots=True)
class _RawFrame:
    logical_name: str
    filename: str
    line: int | None
    column: int | None
    firstlineno: int
    locals_snapshot: Mapping[str, Any]
    code: CodeType


@dataclass(frozen=True, slots=True)
class _RawEvent:
    hint: str
    logical_name: str
    filename: str
    line: int | None
    column: int | None
    lasti: int
    flags: int
    code: CodeType | None
    arg_type: str
    arg_summary: Any
    stack: tuple[_RawFrame, ...]
    exception_type: str | None = None
    handler_kind: str | None = None
    effect: str | None = None
    denied: bool = False


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class PythonExecutionTracer:
    """In-process ``sys.settrace`` collector bound to exact identities."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE
    VERSION: ClassVar[str] = PYTHON_EXECUTION_TRACER_VERSION

    def __init__(
        self,
        policy: TraceCollectionPolicy | None = None,
        *,
        tree_cid: str | None = None,
        environment_binding: Mapping[str, str] | None = None,
        source: str | bytes | None = None,
        cancellation: TraceCancellation | None = None,
        redactor: TraceRedactor | None = None,
    ) -> None:
        self.policy = policy if policy is not None else TraceCollectionPolicy()
        if not isinstance(self.policy, TraceCollectionPolicy):
            raise PythonExecutionTraceError("policy must be a TraceCollectionPolicy")
        self._tree_cid_override = tree_cid
        self._environment_binding = _freeze_binding(
            environment_binding if environment_binding is not None else _default_environment()
        )
        self._source_override = source
        self.cancellation = cancellation
        self.redactor = redactor if redactor is not None else TraceRedactor(
            self.policy.redacted_dimensions
        )
        self._inside = False
        self._previous: Callable[..., Any] | None = None
        self._raw: list[_RawEvent] = []
        self._line_count = 0
        self._bounded = False
        self._stop = False
        self._pending_exception = False
        self._handler_ranges: tuple[tuple[int, int, str], ...] = ()
        self._subject_code: CodeType | None = None
        self._root_filename = ""
        self._binding: PythonExecutionBinding | None = None
        self._unavailable: set[str] = set()
        self._redacted: set[str] = set(self.policy.redacted_dimensions)
        self._denied_effects: list[str] = []

    def record(
        self, subject: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> PythonExecutionTraceRecord:
        if not callable(subject):
            raise PythonExecutionTraceError("subject must be a Python callable")
        binding = self._bind(subject)
        self._binding = binding
        if self.cancellation is not None and self.cancellation.cancelled:
            return self._cancelled_without_run(binding, self.cancellation.reason)
        source_bytes, source_available = _source_bytes_of(subject, self._source_override)
        if source_available:
            self._handler_ranges = _handler_ranges(source_bytes)
        else:
            self._unavailable.add("source_text")
            self._handler_ranges = ()
        self._subject_code = getattr(subject, "__code__", None)
        self._root_filename = (
            self._subject_code.co_filename if self._subject_code is not None else ""
        )
        self._raw = []
        self._line_count = 0
        self._bounded = False
        self._stop = False
        self._pending_exception = False
        self._denied_effects = []
        outcome = CollectionOutcome.COMPLETED
        cancellation_reason: str | None = None
        result_summary: dict[str, Any] = {"type": "NoneType", "unavailable": True}
        restore = self._install_denials()
        previous = sys.gettrace()
        self._previous = previous
        try:
            sys.settrace(self._trace)
            try:
                value = subject(*args, **kwargs)
            except TraceCancellation as cancelled:
                outcome = CollectionOutcome.CANCELLED
                cancellation_reason = cancelled.reason
                result_summary = {"type": "TraceCancellation", "unavailable": True}
            except PythonExecutionTraceError as denied:
                if str(denied).startswith("hermetic policy denied"):
                    outcome = CollectionOutcome.FAILED
                    result_summary = {"denied": True, "type": "PythonExecutionTraceError"}
                    self._unavailable.add("external_effect")
                else:
                    raise
            except Exception as exc:
                outcome = CollectionOutcome.FAILED
                result_summary = {"type": type(exc).__name__, "unavailable": True}
            else:
                marks: set[str] = set()
                summarized = self.redactor.summarize(
                    value, max_chars=self.policy.max_summary_chars, redacted=marks
                )
                self._redacted.update(marks)
                if isinstance(summarized, dict):
                    result_summary = summarized
                else:
                    result_summary = {"value": summarized}
        finally:
            sys.settrace(previous)
            self._restore_denials(restore)
        if self._bounded and outcome == CollectionOutcome.COMPLETED:
            outcome = CollectionOutcome.BOUNDED
        return self._assemble(
            binding=binding,
            outcome=outcome,
            cancellation_reason=cancellation_reason,
            result_summary=result_summary,
        )

    def _bind(self, subject: Callable[..., Any]) -> PythonExecutionBinding:
        logical_name = _text(_callable_logical_name(subject), "logical_name")
        source_bytes, source_available = _source_bytes_of(subject, self._source_override)
        source_cid = cid_for_bytes(source_bytes)
        firstlineno = 0
        code = getattr(subject, "__code__", None)
        if isinstance(code, CodeType):
            firstlineno = code.co_firstlineno
        code_cid = _code_cid(logical_name, source_cid, firstlineno)
        subject_cid = _subject_cid(logical_name, source_cid, code_cid)
        tree_cid = self._tree_cid_override or _tree_cid_from_source(source_cid, logical_name)
        environment_binding_cid = _environment_cid(self._environment_binding)
        return PythonExecutionBinding(
            tree_cid=tree_cid,
            source_cid=source_cid,
            code_cid=code_cid,
            subject_cid=subject_cid,
            environment_binding_cid=environment_binding_cid,
            capture_profile_cid=self.policy.capture_profile_cid,
            environment_binding=self._environment_binding,
            source_available=source_available,
            logical_name=logical_name,
        )

    def _trace(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if self._stop:
            return None
        if self.cancellation is not None and self.cancellation.cancelled:
            self._stop = True
            sys.settrace(self._previous)
            return None
        if self._inside or _is_internal_frame(frame):
            return self._trace
        if event not in {"call", "return", "line", "exception"}:
            return self._trace
        self._inside = True
        try:
            if len(self._raw) >= self.policy.max_events:
                self._bounded = True
                self._stop = True
                sys.settrace(self._previous)
                return None
            if event == "line":
                if not self.policy.collect_line and not (
                    self._pending_exception and self.policy.collect_handler
                ):
                    return self._trace
                if self._line_count >= self.policy.max_line_events and not (
                    self._pending_exception and self.policy.collect_handler
                ):
                    return self._trace
            self._capture(frame, event, arg)
        except TraceCancellation:
            self._stop = True
            sys.settrace(self._previous)
            raise
        except Exception:
            self._unavailable.add("trace_callback")
        finally:
            self._inside = False
        return self._trace

    def _capture(self, frame: FrameType, event: str, arg: Any) -> None:
        stack = self._snapshot_stack(frame)
        if not stack:
            return
        current = stack[0]
        handler_kind = None
        exception_type = None
        effect = None
        denied = False
        if event == "exception":
            self._pending_exception = True
            if isinstance(arg, tuple) and arg:
                exception_type = getattr(arg[0], "__name__", None) or type(arg[0]).__name__
        elif event == "line" and self._pending_exception:
            handler_kind = _in_handler(self._handler_ranges, current.line)
            if handler_kind is not None:
                self._pending_exception = False
        elif event == "call" and _is_external_frame(frame):
            effect = current.logical_name
        if event == "line":
            self._line_count += 1
        arg_type = "NoneType" if arg is None else type(arg).__name__
        arg_summary: Any = {"type": arg_type, "unavailable": True}
        if event == "return" and self.policy.include_raw_bodies:
            marks: set[str] = set()
            arg_summary = self.redactor.summarize(
                arg, max_chars=self.policy.max_summary_chars, redacted=marks
            )
            self._redacted.update(marks)
        self._raw.append(
            _RawEvent(
                hint=event,
                logical_name=current.logical_name,
                filename=current.filename,
                line=current.line,
                column=current.column,
                lasti=frame.f_lasti,
                flags=frame.f_code.co_flags,
                code=frame.f_code,
                arg_type=arg_type,
                arg_summary=arg_summary,
                stack=stack,
                exception_type=exception_type,
                handler_kind=handler_kind,
                effect=effect,
                denied=denied,
            )
        )

    def _snapshot_stack(self, frame: FrameType) -> tuple[_RawFrame, ...]:
        frames: list[_RawFrame] = []
        current: FrameType | None = frame
        while current is not None and len(frames) < self.policy.max_frames:
            if _is_internal_frame(current):
                break
            locals_map: dict[str, Any] = {}
            if self.policy.include_raw_bodies:
                try:
                    locals_map = dict(current.f_locals)
                except Exception:
                    locals_map = {}
                    self._unavailable.add("locals")
            frames.append(
                _RawFrame(
                    logical_name=_logical_name_of(current),
                    filename=current.f_code.co_filename,
                    line=current.f_lineno if current.f_lineno >= 0 else None,
                    column=_column_of(current.f_code, current.f_lasti),
                    firstlineno=current.f_code.co_firstlineno,
                    locals_snapshot=locals_map,
                    code=current.f_code,
                )
            )
            current = current.f_back
        if current is not None and not _is_internal_frame(current):
            self._unavailable.add("call_stack_tail")
        return tuple(frames)

    def _classify(self, raw: _RawEvent) -> str:
        if raw.effect or raw.denied:
            return EventKind.EXTERNAL.value
        if raw.hint == "exception":
            return EventKind.RAISE.value
        if raw.hint == "line" and raw.handler_kind:
            return EventKind.CATCH.value
        if raw.hint == "line":
            return EventKind.LINE.value
        if raw.hint == "call":
            return EventKind.CALL.value
        if raw.hint == "return":
            opname = ""
            if raw.code is not None:
                instruction = _instruction_at(raw.code, raw.lasti)
                if instruction is not None:
                    opname = instruction.opname
            flags = raw.flags
            if opname in _YIELD_OPNAMES or (
                flags & inspect.CO_GENERATOR and opname not in _RETURN_OPNAMES
            ):
                return EventKind.YIELD.value
            if opname in _AWAIT_OPNAMES or (
                flags & inspect.CO_COROUTINE and opname not in _RETURN_OPNAMES
            ):
                return EventKind.AWAIT.value
            if flags & inspect.CO_ASYNC_GENERATOR and opname not in _RETURN_OPNAMES:
                return EventKind.YIELD.value
            return EventKind.RETURN.value
        return EventKind.OBSERVE.value

    def _should_collect(self, kind: str) -> bool:
        return self.policy.allows(kind)

    def _completeness(self, extra_unavailable: Sequence[str] = ()) -> str:
        unavailable = set(self._unavailable) | set(extra_unavailable)
        redacted = set(self._redacted)
        if redacted:
            return CompletenessClaim.REDACTED.value
        if unavailable:
            return CompletenessClaim.PARTIAL.value
        return CompletenessClaim.FULL_STATE.value

    def _build_frames(self, stack: Sequence[_RawFrame]) -> tuple[StackFrameState, ...]:
        if self._binding is None:
            raise PythonExecutionTraceError("binding required before frame assembly")
        binding = self._binding
        frames: list[StackFrameState] = []
        unavailable = tuple(sorted(self._unavailable))
        redacted = tuple(sorted(self._redacted))
        completeness = self._completeness()
        for ordinal, raw in enumerate(stack):
            frame_unavailable = unavailable
            claim = completeness
            if redacted:
                claim = CompletenessClaim.REDACTED.value
            elif frame_unavailable:
                claim = CompletenessClaim.PARTIAL.value
            if raw.line is None and "source_location" not in frame_unavailable:
                frame_unavailable = tuple(sorted(set(frame_unavailable) | {"source_location"}))
                if claim == CompletenessClaim.FULL_STATE.value:
                    claim = CompletenessClaim.PARTIAL.value
            frames.append(
                StackFrameState(
                    ordinal=ordinal,
                    language=ProgramLanguage.PYTHON,
                    tree_cid=binding.tree_cid,
                    source_cid=binding.source_cid,
                    code_cid=_code_cid(raw.logical_name, binding.source_cid, raw.firstlineno),
                    environment_binding_cid=binding.environment_binding_cid,
                    logical_name=raw.logical_name,
                    line=raw.line,
                    column=raw.column,
                    state_summary={},
                    redacted_dimensions=redacted,
                    unavailable_dimensions=frame_unavailable,
                    completeness_claim=claim,
                    privacy_class=PrivacyClass.INTERNAL,
                )
            )
        return tuple(frames)

    def _payload(self, kind: str, raw: _RawEvent) -> dict[str, Any]:
        if kind == EventKind.CALL.value:
            return {"callee": raw.logical_name}
        if kind == EventKind.RETURN.value:
            return {"value_type": raw.arg_type}
        if kind == EventKind.LINE.value:
            return {"line": raw.line if raw.line is not None else 0}
        if kind == EventKind.RAISE.value:
            return {"exception_type": raw.exception_type or raw.arg_type}
        if kind in {EventKind.CATCH.value, EventKind.HANDLER.value}:
            return {"handler_kind": raw.handler_kind or HandlerKind.EXCEPT.value}
        if kind == EventKind.YIELD.value:
            return {"value_type": raw.arg_type}
        if kind == EventKind.AWAIT.value:
            return {"awaitable_type": raw.arg_type}
        if kind == EventKind.EXTERNAL.value:
            payload = {"effect": raw.effect or raw.logical_name}
            if raw.denied:
                payload["denied"] = True
            return payload
        if kind == EventKind.ENTER.value:
            return {"subject": raw.logical_name}
        if kind == EventKind.EXIT.value:
            return {"subject": raw.logical_name}
        return {"kind": kind}

    def _event(
        self,
        *,
        kind: str,
        raw: _RawEvent,
        frames: Sequence[StackFrameState],
        predecessor: str | None,
        exception: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
        observation_status: str = ObservationStatus.OBSERVED.value,
        extra_unavailable: Sequence[str] = (),
    ) -> ProgramEvent:
        if self._binding is None:
            raise PythonExecutionTraceError("binding required before event assembly")
        binding = self._binding
        unavailable = tuple(sorted(set(self._unavailable) | set(extra_unavailable)))
        redacted = tuple(sorted(self._redacted))
        claim = self._completeness(extra_unavailable)
        if observation_status != ObservationStatus.OBSERVED.value:
            if claim == CompletenessClaim.FULL_STATE.value:
                claim = CompletenessClaim.PARTIAL.value
            if not unavailable:
                unavailable = ("event_body",)
                claim = CompletenessClaim.PARTIAL.value
        privacy = PrivacyClass.INTERNAL.value
        code_cid = frames[0].code_cid if frames else binding.code_cid
        line = raw.line if raw.line is not None else (frames[0].line if frames else None)
        return ProgramEvent(
            event_kind=kind,
            event_origin=EventOrigin.OBSERVED,
            observation_status=observation_status,
            language=ProgramLanguage.PYTHON,
            tree_cid=binding.tree_cid,
            source_cid=binding.source_cid,
            code_cid=code_cid,
            environment_binding_cid=binding.environment_binding_cid,
            subject_cid=binding.subject_cid,
            logical_name=raw.logical_name,
            payload=self._payload(kind, raw),
            line=line,
            column=raw.column,
            predecessor_event_cid=predecessor,
            stack_frame_cids=tuple(frame.stack_frame_state_cid for frame in frames),
            exception_snapshot_cid=(
                None if exception is None else exception.exception_snapshot_cid
            ),
            handler_state_cid=None if handler is None else handler.handler_state_cid,
            redacted_dimensions=redacted,
            unavailable_dimensions=unavailable,
            completeness_claim=claim,
            privacy_class=privacy,
        )

    def _exception_snapshot(
        self, raw: _RawEvent, frames: Sequence[StackFrameState]
    ) -> ExceptionSnapshot:
        if self._binding is None:
            raise PythonExecutionTraceError("binding required before exception assembly")
        binding = self._binding
        unavailable = set(self._unavailable)
        if not frames:
            unavailable.add("call_stack")
        unavailable_t = tuple(sorted(unavailable))
        claim = (
            CompletenessClaim.PARTIAL.value
            if unavailable_t
            else CompletenessClaim.FULL_STATE.value
        )
        return ExceptionSnapshot(
            language=ProgramLanguage.PYTHON,
            exception_type=raw.exception_type or raw.arg_type or "Exception",
            tree_cid=binding.tree_cid,
            source_cid=binding.source_cid,
            code_cid=frames[0].code_cid if frames else binding.code_cid,
            environment_binding_cid=binding.environment_binding_cid,
            exception_value_summary={"type": raw.exception_type or raw.arg_type, "bounded": True},
            traceback_stack_frame_cids=tuple(
                frame.stack_frame_state_cid for frame in frames
            ),
            unavailable_dimensions=unavailable_t,
            completeness_claim=claim,
        )

    def _handler_state(
        self,
        raw: _RawEvent,
        frames: Sequence[StackFrameState],
        exception: ExceptionSnapshot,
    ) -> HandlerState:
        if self._binding is None:
            raise PythonExecutionTraceError("binding required before handler assembly")
        binding = self._binding
        kind = raw.handler_kind or HandlerKind.EXCEPT.value
        return HandlerState(
            language=ProgramLanguage.PYTHON,
            handler_kind=kind,
            tree_cid=binding.tree_cid,
            source_cid=binding.source_cid,
            code_cid=frames[0].code_cid if frames else binding.code_cid,
            environment_binding_cid=binding.environment_binding_cid,
            logical_name=raw.logical_name,
            stack_ordinal=0 if not frames else frames[0].ordinal,
            handler_active=True,
            matching_exception_snapshot_cid=exception.exception_snapshot_cid,
            unavailable_dimensions=tuple(sorted(self._unavailable)),
        )

    def _state_for(
        self,
        frames: Sequence[StackFrameState],
        *,
        exception: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
        observed: Mapping[str, Any] | None = None,
    ) -> ProgramExecutionState:
        if self._binding is None:
            raise PythonExecutionTraceError("binding required before state assembly")
        binding = self._binding
        unavailable = tuple(sorted(self._unavailable))
        redacted = tuple(sorted(self._redacted))
        privacy = self.policy.privacy_class
        includes_raw = self.policy.include_raw_bodies
        if includes_raw:
            privacy = PrivacyClass.PRIVATE.value
        claim = self._completeness()
        unavailable_set = set(unavailable)
        if not frames:
            unavailable_set.add("call_stack")
        heap_bound: HeapBound | str = HeapBound.BOUNDED_ABSTRACT
        if "heap" in unavailable_set:
            heap_bound = HeapBound.UNAVAILABLE
        if redacted:
            claim = CompletenessClaim.REDACTED.value
        elif unavailable_set:
            claim = CompletenessClaim.PARTIAL.value
        redaction = None
        if redacted:
            redaction = RedactionProfile(
                privacy_class=privacy,
                redacted_dimensions=redacted,
                unavailable_dimensions=tuple(sorted(unavailable_set)),
                completeness_claim=CompletenessClaim.REDACTED,
            )
        observed_state: dict[str, Any] = {}
        if includes_raw and observed:
            observed_state, extra = self.redactor.summarize_mapping(
                dict(observed),
                max_items=self.policy.max_summary_items,
                max_chars=self.policy.max_summary_chars,
            )
            if extra:
                self._redacted.update(extra)
                redacted = tuple(sorted(self._redacted))
                claim = CompletenessClaim.REDACTED.value
                redaction = RedactionProfile(
                    privacy_class=privacy,
                    redacted_dimensions=redacted,
                    unavailable_dimensions=tuple(sorted(unavailable_set)),
                    completeness_claim=CompletenessClaim.REDACTED,
                )
        return assemble_program_execution_state(
            language=ProgramLanguage.PYTHON,
            capture_profile_cid=binding.capture_profile_cid,
            tree_cid=binding.tree_cid,
            source_cid=binding.source_cid,
            environment_binding_cid=binding.environment_binding_cid,
            frames=frames,
            observed_state=observed_state,
            heap_summary={},
            heap_bound=heap_bound,
            exception=exception,
            handler=handler,
            redaction=redaction,
            completeness_claim=claim,
            privacy_class=privacy,
            includes_raw_bodies=includes_raw,
            unavailable_dimensions=tuple(sorted(unavailable_set)),
            code_cid=binding.code_cid if not frames else None,
        )

    def _assemble(
        self,
        *,
        binding: PythonExecutionBinding,
        outcome: str,
        cancellation_reason: str | None,
        result_summary: Mapping[str, Any],
    ) -> PythonExecutionTraceRecord:
        events: list[ProgramEvent] = []
        states: list[ProgramExecutionState] = []
        predecessor: str | None = None
        pending_exception: ExceptionSnapshot | None = None
        line_emitted = 0
        for raw in self._raw:
            kind = self._classify(raw)
            if kind == EventKind.LINE.value:
                if line_emitted >= self.policy.max_line_events:
                    continue
                line_emitted += 1
            if not self._should_collect(kind):
                if kind == EventKind.CATCH.value and self.policy.collect_exception:
                    pass
                else:
                    continue
            frames = self._build_frames(raw.stack)
            exception = None
            handler = None
            extra_unavailable: tuple[str, ...] = ()
            status = ObservationStatus.OBSERVED.value
            if kind == EventKind.RAISE.value:
                exception = self._exception_snapshot(raw, frames)
                pending_exception = exception
            elif kind == EventKind.CATCH.value:
                if pending_exception is None:
                    pending_exception = self._exception_snapshot(raw, frames)
                exception = pending_exception
                handler = self._handler_state(raw, frames, exception)
            elif kind == EventKind.EXTERNAL.value and raw.denied:
                extra_unavailable = ("external_effect",)
                status = ObservationStatus.UNAVAILABLE.value
            if not frames and kind in {
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
                extra_unavailable = tuple(sorted(set(extra_unavailable) | {"call_stack"}))
            try:
                event = self._event(
                    kind=kind,
                    raw=raw,
                    frames=frames,
                    predecessor=predecessor,
                    exception=exception,
                    handler=handler,
                    observation_status=status,
                    extra_unavailable=extra_unavailable,
                )
            except ProgramExecutionError as exc:
                raise PythonExecutionTraceError(str(exc)) from exc
            events.append(event)
            predecessor = event.program_event_cid
            if kind in {
                EventKind.CALL.value,
                EventKind.RETURN.value,
                EventKind.RAISE.value,
                EventKind.CATCH.value,
                EventKind.YIELD.value,
                EventKind.AWAIT.value,
                EventKind.EXTERNAL.value,
            }:
                observed = None
                if self.policy.include_raw_bodies and raw.stack:
                    observed = {"locals": dict(raw.stack[0].locals_snapshot)}
                try:
                    states.append(
                        self._state_for(
                            frames,
                            exception=exception,
                            handler=handler,
                            observed=observed,
                        )
                    )
                except ProgramExecutionError:
                    self._unavailable.add("execution_state")
            if kind == EventKind.CATCH.value and self.policy.collect_handler:
                handler_event = self._event(
                    kind=EventKind.HANDLER.value,
                    raw=raw,
                    frames=frames,
                    predecessor=predecessor,
                    exception=exception,
                    handler=handler,
                    extra_unavailable=extra_unavailable,
                )
                events.append(handler_event)
                predecessor = handler_event.program_event_cid
            if len(events) >= self.policy.max_events:
                self._bounded = True
                break
        if not events:
            placeholder = _RawEvent(
                hint="call",
                logical_name=binding.logical_name,
                filename=self._root_filename,
                line=1,
                column=0,
                lasti=0,
                flags=0,
                code=self._subject_code,
                arg_type="NoneType",
                arg_summary={"type": "NoneType", "unavailable": True},
                stack=(),
            )
            extra = ("execution",)
            self._unavailable.add("execution")
            synthetic = self._event(
                kind=EventKind.OBSERVE.value,
                raw=placeholder,
                frames=(),
                predecessor=None,
                observation_status=ObservationStatus.UNAVAILABLE.value,
                extra_unavailable=extra,
            )
            events.append(synthetic)
        cancelled = outcome == CollectionOutcome.CANCELLED.value
        bounded = outcome == CollectionOutcome.BOUNDED.value or self._bounded
        if bounded and outcome == CollectionOutcome.COMPLETED:
            outcome = CollectionOutcome.BOUNDED.value
        accepted = outcome == CollectionOutcome.COMPLETED.value and not cancelled
        unavailable = tuple(sorted(self._unavailable))
        redacted = tuple(sorted(self._redacted))
        privacy = (
            PrivacyClass.PRIVATE.value
            if self.policy.include_raw_bodies
            else PrivacyClass.INTERNAL.value
        )
        claim = self._completeness()
        redaction = None
        if redacted:
            redaction = RedactionProfile(
                privacy_class=privacy,
                redacted_dimensions=redacted,
                unavailable_dimensions=unavailable,
                completeness_claim=CompletenessClaim.REDACTED,
            )
            claim = CompletenessClaim.REDACTED.value
        elif unavailable:
            claim = CompletenessClaim.PARTIAL.value
        try:
            private_trace = assemble_execution_trace(
                language=ProgramLanguage.PYTHON,
                tree_cid=binding.tree_cid,
                source_cid=binding.source_cid,
                environment_binding_cid=binding.environment_binding_cid,
                events=events,
                states=states,
                redaction=redaction,
                completeness_claim=claim,
                privacy_class=privacy,
                includes_raw_bodies=self.policy.include_raw_bodies,
                unavailable_dimensions=unavailable,
            )
        except ProgramExecutionError as exc:
            raise PythonExecutionTraceError(str(exc)) from exc
        public_trace = self.redactor.public_trace(private_trace)
        public_states = tuple(self.redactor.public_state(state) for state in states)
        observations: list[ExecutionObservation] = []
        for event in events:
            if event.observation_admissible:
                try:
                    observations.append(observe_program_event(event))
                except ProgramExecutionError:
                    continue
        receipt = TraceCollectionReceipt(
            outcome=outcome,
            accepted_transition=accepted,
            operational_acceptance=False,
            cancelled=cancelled,
            bounded=bounded,
            event_count=len(events),
            public_trace_cid=public_trace.execution_trace_cid,
            private_trace_cid=private_trace.execution_trace_cid,
            capture_profile_cid=binding.capture_profile_cid,
            tree_cid=binding.tree_cid,
            source_cid=binding.source_cid,
            environment_binding_cid=binding.environment_binding_cid,
            binding_cid=binding.binding_cid,
            redacted_dimensions=redacted,
            unavailable_dimensions=unavailable,
            cancellation_reason=cancellation_reason,
        )
        return PythonExecutionTraceRecord(
            outcome=outcome,
            accepted_transition=accepted,
            operational_acceptance=False,
            binding=binding,
            policy=self.policy,
            events=tuple(events),
            states=tuple(states),
            observations=tuple(observations),
            private_trace=private_trace,
            public_trace=public_trace,
            public_states=public_states,
            receipt=receipt,
            cancellation_reason=cancellation_reason,
            bounded=bounded,
            result_summary=MappingProxyType(dict(result_summary)),
            redacted_dimensions=redacted,
            unavailable_dimensions=unavailable,
        )

    def _cancelled_without_run(
        self, binding: PythonExecutionBinding, reason: str
    ) -> PythonExecutionTraceRecord:
        self._unavailable.add("execution")
        placeholder = _RawEvent(
            hint="call",
            logical_name=binding.logical_name,
            filename="",
            line=0,
            column=0,
            lasti=0,
            flags=0,
            code=None,
            arg_type="NoneType",
            arg_summary={"type": "NoneType", "unavailable": True},
            stack=(),
        )
        event = self._event(
            kind=EventKind.OBSERVE.value,
            raw=placeholder,
            frames=(),
            predecessor=None,
            observation_status=ObservationStatus.UNAVAILABLE.value,
            extra_unavailable=("execution",),
        )
        self._raw = []
        return self._assemble(
            binding=binding,
            outcome=CollectionOutcome.CANCELLED.value,
            cancellation_reason=reason,
            result_summary={"reason": reason, "type": "TraceCancellation"},
        )

    def _note_denied(self, effect: str) -> None:
        self._denied_effects.append(effect)
        self._unavailable.add("external_effect")
        stack: tuple[_RawFrame, ...] = ()
        frame = sys._getframe(1) if hasattr(sys, "_getframe") else None
        while isinstance(frame, FrameType) and _is_internal_frame(frame):
            frame = frame.f_back
        if isinstance(frame, FrameType):
            stack = self._snapshot_stack(frame)
        logical = stack[0].logical_name if stack else effect
        self._raw.append(
            _RawEvent(
                hint="call",
                logical_name=logical,
                filename=stack[0].filename if stack else "",
                line=stack[0].line if stack else None,
                column=stack[0].column if stack else None,
                lasti=0,
                flags=0,
                code=stack[0].code if stack else None,
                arg_type="NoneType",
                arg_summary={"denied": True, "type": "NoneType"},
                stack=stack,
                effect=effect,
                denied=True,
            )
        )

    def _install_denials(self) -> list[tuple[Any, str, Any]]:
        restored: list[tuple[Any, str, Any]] = []

        def deny(owner: Any, name: str, effect: str) -> None:
            original = getattr(owner, name, None)
            if original is None:
                return

            def blocked(*_args: Any, **_kwargs: Any) -> Any:
                self._note_denied(effect)
                raise PythonExecutionTraceError(f"hermetic policy denied {effect}")

            try:
                setattr(owner, name, blocked)
            except (TypeError, AttributeError):
                return
            restored.append((owner, name, original))

        if self.policy.deny_socket or self.policy.deny_network:
            import socket

            deny(socket, "create_connection", "socket.create_connection")
            deny(socket, "getaddrinfo", "socket.getaddrinfo")

        if self.policy.deny_subprocess:
            import os
            import subprocess

            deny(subprocess, "Popen", "subprocess.Popen")
            deny(subprocess, "run", "subprocess.run")
            deny(subprocess, "call", "subprocess.call")
            deny(subprocess, "check_call", "subprocess.check_call")
            deny(subprocess, "check_output", "subprocess.check_output")
            deny(os, "system", "os.system")

        if self.policy.deny_database:
            sqlite3 = sys.modules.get("sqlite3")
            if sqlite3 is not None:
                deny(sqlite3, "connect", "sqlite3.connect")
            duckdb = sys.modules.get("duckdb")
            if duckdb is not None:
                deny(duckdb, "connect", "duckdb.connect")
        return restored

    def _restore_denials(self, restored: Sequence[tuple[Any, str, Any]]) -> None:
        for owner, name, original in restored:
            try:
                setattr(owner, name, original)
            except Exception:
                continue


# ---------------------------------------------------------------------------
# Public interfaces
# ---------------------------------------------------------------------------


def record_python_execution_trace(
    subject: Callable[..., Any],
    *args: Any,
    policy: TraceCollectionPolicy | None = None,
    tree_cid: str | None = None,
    environment_binding: Mapping[str, str] | None = None,
    source: str | bytes | None = None,
    cancellation: TraceCancellation | None = None,
    **kwargs: Any,
) -> PythonExecutionTraceRecord:
    """Collect a bounded hermetic Python execution trace.

    Cancellation emits no accepted transition.  Public records never include
    private raw trace bodies.  Operational acceptance is never persisted.
    """

    tracer = PythonExecutionTracer(
        policy,
        tree_cid=tree_cid,
        environment_binding=environment_binding,
        source=source,
        cancellation=cancellation,
    )
    return tracer.record(subject, *args, **kwargs)


def replay_deterministic_trace(
    record: PythonExecutionTraceRecord,
    *,
    subject: Callable[..., Any],
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    cancellation: TraceCancellation | None = None,
) -> PythonExecutionReplayReceipt:
    """Re-execute ``subject`` under the original bindings and compare identities.

    Binding drift fails closed.  A cancelled original or replay never reports
    an accepted transition.
    """

    if not isinstance(record, PythonExecutionTraceRecord):
        raise PythonExecutionTraceError("replay requires a PythonExecutionTraceRecord")
    if not callable(subject):
        raise PythonExecutionTraceError("replay subject must be a Python callable")
    replayed = record_python_execution_trace(
        subject,
        *tuple(args),
        policy=record.policy,
        tree_cid=record.binding.tree_cid,
        environment_binding=record.binding.environment_binding,
        cancellation=cancellation,
        **(dict(kwargs) if kwargs is not None else {}),
    )
    if replayed.binding.source_cid != record.binding.source_cid:
        raise PythonExecutionTraceError("replay source_cid does not match the original binding")
    if replayed.binding.environment_binding_cid != record.binding.environment_binding_cid:
        raise PythonExecutionTraceError(
            "replay environment_binding_cid does not match the original binding"
        )
    if replayed.binding.tree_cid != record.binding.tree_cid:
        raise PythonExecutionTraceError("replay tree_cid does not match the original binding")
    original_events = record.private_trace.event_cids
    replayed_events = replayed.private_trace.event_cids
    original_set = set(original_events)
    replayed_set = set(replayed_events)
    diverged = tuple(
        cid for cid in original_events if cid not in replayed_set
    ) + tuple(cid for cid in replayed_events if cid not in original_set)
    binding_matched = (
        replayed.binding.binding_cid == record.binding.binding_cid
        and replayed.binding.capture_profile_cid == record.binding.capture_profile_cid
    )
    matched = (
        binding_matched
        and original_events == replayed_events
        and record.public_trace.execution_trace_cid == replayed.public_trace.execution_trace_cid
        and record.outcome == replayed.outcome
    )
    accepted = (
        record.accepted_transition
        and replayed.accepted_transition
        and record.outcome != CollectionOutcome.CANCELLED.value
        and replayed.outcome != CollectionOutcome.CANCELLED.value
    )
    return PythonExecutionReplayReceipt(
        matched=matched,
        binding_matched=binding_matched,
        accepted_transition=accepted,
        operational_acceptance=False,
        original_outcome=record.outcome,
        replayed_outcome=replayed.outcome,
        original_trace_cid=record.private_trace.execution_trace_cid,
        replayed_trace_cid=replayed.private_trace.execution_trace_cid,
        original_public_trace_cid=record.public_trace.execution_trace_cid,
        replayed_public_trace_cid=replayed.public_trace.execution_trace_cid,
        diverged_event_cids=diverged,
        original_event_cids=original_events,
        replayed_event_cids=replayed_events,
    )


def module_forbids_import_time_effects() -> dict[str, bool]:
    """Return the sealed import-time side-effect flags for tests and receipts."""

    return {
        "database": IMPORT_DATABASE_PERFORMED,
        "installer": IMPORT_INSTALLER_PERFORMED,
        "model_load": IMPORT_MODEL_LOAD_PERFORMED,
        "network": IMPORT_NETWORK_PERFORMED,
        "repo_scan": IMPORT_SCAN_PERFORMED,
        "socket": IMPORT_SOCKET_PERFORMED,
        "subprocess": IMPORT_SUBPROCESS_PERFORMED,
        "watcher": IMPORT_WATCHER_PERFORMED,
    }


__all__ = [
    "ADMITTED_LANGUAGE",
    "IMPORT_DATABASE_PERFORMED",
    "IMPORT_INSTALLER_PERFORMED",
    "IMPORT_MODEL_LOAD_PERFORMED",
    "IMPORT_NETWORK_PERFORMED",
    "IMPORT_SCAN_PERFORMED",
    "IMPORT_SOCKET_PERFORMED",
    "IMPORT_SUBPROCESS_PERFORMED",
    "IMPORT_WATCHER_PERFORMED",
    "PYTHON_EXECUTION_REPLAY_RECEIPT_INTERFACE",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "PYTHON_EXECUTION_TRACE_RECORD_INTERFACE",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_COLLECTION_RECEIPT_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "CollectionOutcome",
    "PythonExecutionBinding",
    "PythonExecutionReplayReceipt",
    "PythonExecutionTraceError",
    "PythonExecutionTraceRecord",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCollectionPolicy",
    "TraceCollectionReceipt",
    "TraceRedactor",
    "module_forbids_import_time_effects",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
