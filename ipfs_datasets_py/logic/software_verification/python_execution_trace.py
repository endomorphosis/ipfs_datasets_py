"""Hermetic Python execution tracing (SAWM-008).

Collect admitted call/return/line/exception/handler/yield/await/selected
external events with bounded state summaries, exact symbol/callsite/source
identity, cancellation, and redaction.

Importing this module never opens a network, socket, installer, subprocess,
database, repository scan, watcher, or model load.  Tracing is explicit via
:func:`record_python_execution_trace` / :class:`PythonExecutionTracer`.
Cancellation never admits an accepted transition.  Private raw trace bodies
never enter public records.
"""

from __future__ import annotations

import hashlib
import opcode as opcode_mod
import sys
import threading
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from types import CodeType, FrameType, MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_contracts.content import (
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
    RedactionProfile,
    StackFrameState,
    assemble_execution_trace,
    assemble_program_execution_state,
    observe_program_event,
    public_execution_view,
)


# ---------------------------------------------------------------------------
# Import-time hermeticity.  These flags are never flipped by importing.
# ---------------------------------------------------------------------------

IMPORT_NETWORK_PERFORMED: Final[bool] = False
IMPORT_SOCKET_PERFORMED: Final[bool] = False
IMPORT_INSTALLER_PERFORMED: Final[bool] = False
IMPORT_SUBPROCESS_PERFORMED: Final[bool] = False
IMPORT_DATABASE_PERFORMED: Final[bool] = False
IMPORT_REPO_SCAN_PERFORMED: Final[bool] = False
IMPORT_WATCHER_PERFORMED: Final[bool] = False
IMPORT_MODEL_LOAD_PERFORMED: Final[bool] = False

PYTHON_EXECUTION_TRACER_INTERFACE: Final[str] = "PythonExecutionTracer@1"
TRACE_COLLECTION_POLICY_INTERFACE: Final[str] = "TraceCollectionPolicy@1"
TRACE_REDACTOR_INTERFACE: Final[str] = "TraceRedactor@1"
TRACE_CANCELLATION_INTERFACE: Final[str] = "TraceCancellation@1"
PYTHON_EXECUTION_TRACE_RECORD_INTERFACE: Final[str] = "PythonExecutionTraceRecord@1"
RECORD_PYTHON_EXECUTION_TRACE_INTERFACE: Final[str] = "record_python_execution_trace@1"
REPLAY_DETERMINISTIC_TRACE_INTERFACE: Final[str] = "replay_deterministic_trace@1"

PYTHON_EXECUTION_TRACE_VERSION: Final[str] = "1"
TRACE_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-collection-policy@1"
)
TRACE_CAPTURE_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-capture-profile@1"
)
TRACE_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-environment@1"
)
TRACE_CODE_IDENTITY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-code-identity@1"
)
TRACE_TREE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-tree@1"
)
TRACE_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-execution-trace-record@1"
)
TRACE_TRANSITION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-accepted-transition@1"
)
TRACE_CANCELLATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-cancellation@1"
)
ADMITTED_LANGUAGE: Final[str] = "python"

DEFAULT_MAX_EVENTS: Final[int] = 4_096
DEFAULT_MAX_LINE_EVENTS: Final[int] = 256
DEFAULT_MAX_STACK_DEPTH: Final[int] = 64
DEFAULT_MAX_PAYLOAD_BYTES: Final[int] = 2_048
DEFAULT_MAX_SUMMARY_BYTES: Final[int] = 2_048
DEFAULT_MAX_TEXT: Final[int] = 256
DEFAULT_MAX_CONTAINER_ITEMS: Final[int] = 16
DEFAULT_MAX_DEPTH: Final[int] = 3

CO_GENERATOR: Final[int] = 0x20
CO_COROUTINE: Final[int] = 0x80
CO_ITERABLE_COROUTINE: Final[int] = 0x100
CO_ASYNC_GENERATOR: Final[int] = 0x200

_YIELD_OPCODES: Final[frozenset[str]] = frozenset({"YIELD_VALUE", "YIELD_FROM"})
_RETURN_OPCODES: Final[frozenset[str]] = frozenset(
    {"RETURN_VALUE", "RETURN_CONST"}
)
_AWAIT_OPCODES: Final[frozenset[str]] = frozenset(
    {"GET_AWAITABLE", "SEND", "GET_AITER", "GET_ANEXT", "END_ASYNC_FOR"}
)

_EXTERNAL_MODULES: Final[frozenset[str]] = frozenset(
    {
        "socket",
        "ssl",
        "select",
        "selectors",
        "subprocess",
        "multiprocessing",
        "urllib",
        "urllib.request",
        "urllib.client",
        "http.client",
        "http.server",
        "requests",
        "httpx",
        "aiohttp",
        "sqlite3",
        "duckdb",
        "psycopg",
        "psycopg2",
        "pymongo",
        "watchdog",
        "watchdog.observers",
        "pip",
        "pip._internal",
        "setuptools",
    }
)
_EXTERNAL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "socket",
        "create_connection",
        "getaddrinfo",
        "urlopen",
        "Popen",
        "run",
        "system",
        "popen",
        "connect",
        "urlretrieve",
        "urlopen",
        "CDLL",
    }
)
_DENIED_MODEL_MODULES: Final[frozenset[str]] = frozenset(
    {
        "torch",
        "transformers",
        "tensorflow",
        "jax",
        "keras",
    }
)
_SECRET_KEY_FRAGMENTS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "private_key",
        "cookie",
        "session",
    }
)

_MODULE_FILENAME: Final[str] = __file__
_INTERNAL_MODULE_PREFIXES: Final[tuple[str, ...]] = (
    "ipfs_datasets_py.logic.software_verification.python_execution_trace",
    "ipfs_datasets_py.logic.software_contracts.semantic_state.program_execution",
    "ipfs_datasets_py.logic.software_contracts.content",
    "ipfs_datasets_py.logic.ir_core",
)
_INFRASTRUCTURE_MODULES: Final[frozenset[str]] = frozenset(
    {
        "asyncio",
        "concurrent",
        "concurrent.futures",
        "contextvars",
        "selectors",
        "threading",
        "multiprocessing",
    }
)

_THREAD_STATE = threading.local()


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic tracing inputs, isolation, or replay are invalid."""


class TraceStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"


class HermeticIsolationError(PythonExecutionTraceError):
    """Raised when a denied external effect is attempted during tracing."""


def _nfc(value: object, name: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise PythonExecutionTraceError(f"{name} must be a nonempty trimmed string")
    normalized = unicodedata.normalize("NFC", value)
    if normalized != value or "\x00" in value:
        raise PythonExecutionTraceError(f"{name} must be NFC text without NUL")
    if len(value) > MAX_TEXT_CHARS:
        raise PythonExecutionTraceError(f"{name} exceeds the text bound")
    return value


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise PythonExecutionTraceError(f"{name} must be a boolean")
    return value


def _positive_int(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or isinstance(value, bool) or value < minimum:
        raise PythonExecutionTraceError(f"{name} must be an integer >= {minimum}")
    if value > MAX_SAFE_INTEGER:
        raise PythonExecutionTraceError(f"{name} exceeds the safe integer range")
    return value


def _logical_filename(filename: str) -> str:
    if not filename:
        return "<unknown>"
    return PurePosixPath(filename.replace("\\", "/")).name


def _qualname(code: CodeType) -> str:
    return getattr(code, "co_qualname", code.co_name) or code.co_name


def _code_sha256(code: CodeType) -> str:
    return hashlib.sha256(code.co_code).hexdigest()


def _code_identity_payload(code: CodeType) -> dict[str, Any]:
    return {
        "schema": TRACE_CODE_IDENTITY_SCHEMA,
        "argcount": code.co_argcount,
        "code_sha256": _code_sha256(code),
        "filename": _logical_filename(code.co_filename),
        "firstlineno": code.co_firstlineno,
        "flags": code.co_flags,
        "name": code.co_name,
        "names": list(code.co_names),
        "qualname": _qualname(code),
    }


def _code_cid(code: CodeType) -> str:
    return cid_for_structured(_code_identity_payload(code))


def _source_cid_for_code(code: CodeType) -> str:
    return cid_for_bytes(code.co_code)


def _default_environment_binding() -> dict[str, str]:
    info = sys.version_info
    implementation = sys.implementation
    return {
        "implementation": str(implementation.name),
        "language": ADMITTED_LANGUAGE,
        "python_major": str(info.major),
        "python_micro": str(info.micro),
        "python_minor": str(info.minor),
    }


def _environment_cid(bindings: Mapping[str, str]) -> str:
    items = [
        {"key": _nfc(str(key), "environment key"), "value": _nfc(str(value), "environment value")}
        for key, value in bindings.items()
    ]
    items.sort(key=lambda item: (item["key"], item["value"]))
    return cid_for_structured({"bindings": items, "schema": TRACE_ENVIRONMENT_SCHEMA})


def _tree_cid(code: CodeType, source_cid: str) -> str:
    return cid_for_structured(
        {
            "code_cid": _code_cid(code),
            "qualname": _qualname(code),
            "schema": TRACE_TREE_SCHEMA,
            "source_cid": source_cid,
        }
    )


def _secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    if lowered in SECRET_FIELD_MARKERS or lowered in FORBIDDEN_FIELD_MARKERS:
        return True
    return any(fragment in lowered for fragment in _SECRET_KEY_FRAGMENTS)


def _drop_secret_keys(value: Any) -> Any:
    """Omit secret/forbidden keys so program-execution records stay closed."""

    if isinstance(value, Mapping):
        return {
            key: _drop_secret_keys(item)
            for key, item in value.items()
            if type(key) is not str or not _secret_key(key)
        }
    if isinstance(value, list):
        return [_drop_secret_keys(item) for item in value]
    if isinstance(value, tuple):
        return [_drop_secret_keys(item) for item in value]
    return value


def _opname_at(frame: FrameType, cache: dict[CodeType, dict[int, str]]) -> str:
    code = frame.f_code
    mapping = cache.get(code)
    if mapping is None:
        mapping = {}
        bytecode = code.co_code
        index = 0
        names = opcode_mod.opname
        while index < len(bytecode):
            op = bytecode[index]
            if op < len(names):
                mapping[index] = names[op]
            index += 2
        cache[code] = mapping
    lasti = frame.f_lasti
    name = mapping.get(lasti, "")
    while name == "CACHE" and lasti >= 2:
        lasti -= 2
        name = mapping.get(lasti, "")
    return name


def _parse_exception_table(code: CodeType) -> tuple[tuple[int, int, int], ...]:
    table = getattr(code, "co_exceptiontable", b"")
    if not table:
        return ()
    iterator = iter(table)

    def read_varint() -> int:
        byte = next(iterator)
        value = byte & 63
        while byte & 64:
            value <<= 6
            byte = next(iterator)
            value |= byte & 63
        return value

    entries: list[tuple[int, int, int]] = []
    try:
        while True:
            start = read_varint() * 2
            length = read_varint() * 2
            target = read_varint() * 2
            read_varint()
            entries.append((start, start + length, target))
    except StopIteration:
        pass
    return tuple(entries)


def _handler_kind_for_offset(code: CodeType, lasti: int, cache: dict[CodeType, tuple[tuple[int, int, int], ...]]) -> str | None:
    table = cache.get(code)
    if table is None:
        table = _parse_exception_table(code)
        cache[code] = table
    for _start, _end, target in table:
        if lasti == target:
            return HandlerKind.EXCEPT.value
    return None


def _is_internal_frame(frame: FrameType) -> bool:
    filename = frame.f_code.co_filename
    if filename == _MODULE_FILENAME:
        return True
    module_name = str(frame.f_globals.get("__name__", "") or "")
    if any(module_name == prefix or module_name.startswith(prefix + ".") for prefix in _INTERNAL_MODULE_PREFIXES):
        return True
    root = module_name.split(".", 1)[0]
    if module_name in _INFRASTRUCTURE_MODULES or root in _INFRASTRUCTURE_MODULES:
        return True
    normalized = filename.replace("\\", "/")
    return "/asyncio/" in normalized or "/concurrent/" in normalized


def _is_external_callable(func: object) -> tuple[bool, str]:
    module = str(getattr(func, "__module__", "") or "")
    name = str(getattr(func, "__qualname__", getattr(func, "__name__", "")) or "")
    root = module.split(".", 1)[0]
    if module in _EXTERNAL_MODULES or root in _EXTERNAL_MODULES:
        return True, f"{module}.{name}".strip(".")
    simple = name.rsplit(".", 1)[-1]
    if simple in _EXTERNAL_NAMES:
        return True, f"{module}.{name}".strip(".")
    return False, f"{module}.{name}".strip(".")


class TraceCancellation(Exception):
    """Cancel an in-flight trace.  Never an accepted transition."""

    INTERFACE: ClassVar[str] = TRACE_CANCELLATION_INTERFACE
    SCHEMA: ClassVar[str] = TRACE_CANCELLATION_SCHEMA

    def __init__(self, reason: str = "cancelled", *, at_event_index: int | None = None) -> None:
        normalized = _nfc(reason, "cancellation reason")
        super().__init__(normalized)
        self.reason = normalized
        self.at_event_index = at_event_index

    @property
    def accepted_transition(self) -> None:
        return None

    @property
    def accepted(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_transition": False,
            "at_event_index": self.at_event_index,
            "interface": self.INTERFACE,
            "reason": self.reason,
            "schema": self.SCHEMA,
        }


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Cost-bounded collection grammar for hermetic Python traces."""

    collect_call: bool = True
    collect_return: bool = True
    collect_line: bool = True
    collect_exception: bool = True
    collect_handler: bool = True
    collect_yield: bool = True
    collect_await: bool = True
    collect_external: bool = True
    collect_enter_exit: bool = True
    capture_locals: bool = True
    capture_states: bool = True
    include_raw_bodies: bool = False
    redact_secrets: bool = True
    deny_network: bool = True
    deny_socket: bool = True
    deny_subprocess: bool = True
    deny_database: bool = True
    deny_installer: bool = True
    max_events: int = DEFAULT_MAX_EVENTS
    max_line_events: int = DEFAULT_MAX_LINE_EVENTS
    max_stack_depth: int = DEFAULT_MAX_STACK_DEPTH
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
    max_summary_bytes: int = DEFAULT_MAX_SUMMARY_BYTES
    privacy_class: PrivacyClass | str = PrivacyClass.INTERNAL
    environment_binding: Mapping[str, str] = field(default_factory=dict)

    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE
    SCHEMA: ClassVar[str] = TRACE_POLICY_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "collect_call", _bool(self.collect_call, "collect_call"))
        object.__setattr__(self, "collect_return", _bool(self.collect_return, "collect_return"))
        object.__setattr__(self, "collect_line", _bool(self.collect_line, "collect_line"))
        object.__setattr__(
            self, "collect_exception", _bool(self.collect_exception, "collect_exception")
        )
        object.__setattr__(self, "collect_handler", _bool(self.collect_handler, "collect_handler"))
        object.__setattr__(self, "collect_yield", _bool(self.collect_yield, "collect_yield"))
        object.__setattr__(self, "collect_await", _bool(self.collect_await, "collect_await"))
        object.__setattr__(
            self, "collect_external", _bool(self.collect_external, "collect_external")
        )
        object.__setattr__(
            self, "collect_enter_exit", _bool(self.collect_enter_exit, "collect_enter_exit")
        )
        object.__setattr__(self, "capture_locals", _bool(self.capture_locals, "capture_locals"))
        object.__setattr__(self, "capture_states", _bool(self.capture_states, "capture_states"))
        object.__setattr__(
            self, "include_raw_bodies", _bool(self.include_raw_bodies, "include_raw_bodies")
        )
        object.__setattr__(self, "redact_secrets", _bool(self.redact_secrets, "redact_secrets"))
        object.__setattr__(self, "deny_network", _bool(self.deny_network, "deny_network"))
        object.__setattr__(self, "deny_socket", _bool(self.deny_socket, "deny_socket"))
        object.__setattr__(
            self, "deny_subprocess", _bool(self.deny_subprocess, "deny_subprocess")
        )
        object.__setattr__(self, "deny_database", _bool(self.deny_database, "deny_database"))
        object.__setattr__(self, "deny_installer", _bool(self.deny_installer, "deny_installer"))
        object.__setattr__(self, "max_events", _positive_int(self.max_events, "max_events", minimum=1))
        object.__setattr__(
            self, "max_line_events", _positive_int(self.max_line_events, "max_line_events", minimum=0)
        )
        object.__setattr__(
            self,
            "max_stack_depth",
            _positive_int(self.max_stack_depth, "max_stack_depth", minimum=1),
        )
        object.__setattr__(
            self,
            "max_payload_bytes",
            _positive_int(self.max_payload_bytes, "max_payload_bytes", minimum=64),
        )
        object.__setattr__(
            self,
            "max_summary_bytes",
            _positive_int(self.max_summary_bytes, "max_summary_bytes", minimum=64),
        )
        privacy = self.privacy_class
        if isinstance(privacy, PrivacyClass):
            privacy_value = privacy.value
        else:
            try:
                privacy_value = PrivacyClass(privacy).value
            except (TypeError, ValueError) as error:
                raise PythonExecutionTraceError("privacy_class is unsupported") from error
        object.__setattr__(self, "privacy_class", privacy_value)
        binding = self.environment_binding or {}
        if not isinstance(binding, Mapping):
            raise PythonExecutionTraceError("environment_binding must be a string mapping")
        frozen_binding = {
            _nfc(str(key), "environment key"): _nfc(str(value), "environment value")
            for key, value in binding.items()
        }
        object.__setattr__(self, "environment_binding", MappingProxyType(frozen_binding))
        if self.include_raw_bodies and privacy_value in {PrivacyClass.PUBLIC.value, PrivacyClass.INTERNAL.value}:
            raise PythonExecutionTraceError(
                "raw bodies remain private and cannot enter public or internal records"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "capture_locals": self.capture_locals,
            "capture_states": self.capture_states,
            "collect_await": self.collect_await,
            "collect_call": self.collect_call,
            "collect_enter_exit": self.collect_enter_exit,
            "collect_exception": self.collect_exception,
            "collect_external": self.collect_external,
            "collect_handler": self.collect_handler,
            "collect_line": self.collect_line,
            "collect_return": self.collect_return,
            "collect_yield": self.collect_yield,
            "deny_database": self.deny_database,
            "deny_installer": self.deny_installer,
            "deny_network": self.deny_network,
            "deny_socket": self.deny_socket,
            "deny_subprocess": self.deny_subprocess,
            "environment_binding": dict(sorted(self.environment_binding.items())),
            "include_raw_bodies": self.include_raw_bodies,
            "max_events": self.max_events,
            "max_line_events": self.max_line_events,
            "max_payload_bytes": self.max_payload_bytes,
            "max_stack_depth": self.max_stack_depth,
            "max_summary_bytes": self.max_summary_bytes,
            "privacy_class": self.privacy_class,
            "redact_secrets": self.redact_secrets,
            "schema": self.SCHEMA,
        }

    @property
    def policy_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    @property
    def capture_profile_cid(self) -> str:
        return cid_for_structured(
            {
                "policy_cid": self.policy_cid,
                "schema": TRACE_CAPTURE_PROFILE_SCHEMA,
                "version": PYTHON_EXECUTION_TRACE_VERSION,
            }
        )

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
            EventKind.ENTER.value: self.collect_enter_exit,
            EventKind.EXIT.value: self.collect_enter_exit,
        }
        return mapping.get(kind, False)

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["policy_cid"] = self.policy_cid
        return payload

    def with_environment(self, binding: Mapping[str, str]) -> "TraceCollectionPolicy":
        merged = dict(self.environment_binding)
        merged.update(
            {
                _nfc(str(key), "environment key"): _nfc(str(value), "environment value")
                for key, value in binding.items()
            }
        )
        return TraceCollectionPolicy(
            collect_call=self.collect_call,
            collect_return=self.collect_return,
            collect_line=self.collect_line,
            collect_exception=self.collect_exception,
            collect_handler=self.collect_handler,
            collect_yield=self.collect_yield,
            collect_await=self.collect_await,
            collect_external=self.collect_external,
            collect_enter_exit=self.collect_enter_exit,
            capture_locals=self.capture_locals,
            capture_states=self.capture_states,
            include_raw_bodies=self.include_raw_bodies,
            redact_secrets=self.redact_secrets,
            deny_network=self.deny_network,
            deny_socket=self.deny_socket,
            deny_subprocess=self.deny_subprocess,
            deny_database=self.deny_database,
            deny_installer=self.deny_installer,
            max_events=self.max_events,
            max_line_events=self.max_line_events,
            max_stack_depth=self.max_stack_depth,
            max_payload_bytes=self.max_payload_bytes,
            max_summary_bytes=self.max_summary_bytes,
            privacy_class=self.privacy_class,
            environment_binding=merged,
        )


class TraceRedactor:
    """Fail-closed redaction of secrets, forbidden fields, and raw bodies."""

    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE

    def __init__(self, policy: TraceCollectionPolicy | None = None) -> None:
        self.policy = policy or TraceCollectionPolicy()

    def redact_value(
        self, value: Any, *, budget: int, depth: int = 0
    ) -> tuple[Any, tuple[str, ...], int]:
        redacted: set[str] = set()
        remaining = budget
        if remaining <= 0:
            return {"bounded": True}, ("payload_bound",), remaining

        if value is None or type(value) is bool:
            return value, (), remaining - 4
        if type(value) is int:
            if abs(value) > MAX_SAFE_INTEGER:
                return {"bounded": True, "type": "int"}, ("integer_bound",), remaining - 16
            return value, (), remaining - 8
        if type(value) is str:
            text = unicodedata.normalize("NFC", value)
            if len(text) > DEFAULT_MAX_TEXT:
                text = text[:DEFAULT_MAX_TEXT]
                redacted.add("text_bound")
            return text, tuple(sorted(redacted)), remaining - len(text) - 2
        if type(value) is float:
            return {"type": "float", "unavailable": True}, ("float",), remaining - 24
        if depth >= DEFAULT_MAX_DEPTH:
            return {"bounded": True, "type": type(value).__name__}, ("depth_bound",), remaining - 16
        if isinstance(value, Mapping):
            items: dict[str, Any] = {}
            count = 0
            for raw_key, raw_item in value.items():
                if count >= DEFAULT_MAX_CONTAINER_ITEMS or remaining <= 0:
                    redacted.add("container_bound")
                    break
                if type(raw_key) is not str:
                    redacted.add("non_string_key")
                    continue
                key = unicodedata.normalize("NFC", raw_key)
                if _secret_key(key):
                    redacted.add(key)
                    remaining -= len(key) + 16
                    count += 1
                    continue
                child, child_redacted, remaining = self.redact_value(
                    raw_item, budget=remaining, depth=depth + 1
                )
                items[key] = child
                redacted.update(child_redacted)
                count += 1
            return items, tuple(sorted(redacted)), remaining
        if isinstance(value, (list, tuple)):
            items_list: list[Any] = []
            for index, raw_item in enumerate(value):
                if index >= DEFAULT_MAX_CONTAINER_ITEMS or remaining <= 0:
                    redacted.add("container_bound")
                    break
                child, child_redacted, remaining = self.redact_value(
                    raw_item, budget=remaining, depth=depth + 1
                )
                items_list.append(child)
                redacted.update(child_redacted)
            return items_list, tuple(sorted(redacted)), remaining
        return (
            {"bounded": True, "type": type(value).__name__},
            ("opaque_value",),
            remaining - 16,
        )

    def bounded_mapping(
        self, value: Mapping[str, Any] | None, *, budget: int
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        if not value:
            return {}, ()
        redacted_value, dimensions, _remaining = self.redact_value(dict(value), budget=budget)
        if not isinstance(redacted_value, dict):
            return {"bounded": True}, ("payload_bound",)
        return redacted_value, dimensions

    def public_trace(self, trace: ExecutionTrace) -> ExecutionTrace:
        return trace.public_view()

    def public_state(self, state: ProgramExecutionState) -> ProgramExecutionState:
        return public_execution_view(state)

    def public_record(self, record: "PythonExecutionTraceRecord") -> dict[str, Any]:
        return record.to_public_dict()


@dataclass(frozen=True, slots=True)
class PythonExecutionTraceRecord:
    """Sealed hermetic-trace result.  Public projections never carry raw bodies."""

    status: TraceStatus | str
    policy: TraceCollectionPolicy
    tree_cid: str
    source_cid: str
    environment_binding_cid: str
    capture_profile_cid: str
    events: tuple[ProgramEvent, ...]
    states: tuple[ProgramExecutionState, ...]
    frames: tuple[StackFrameState, ...]
    exceptions: tuple[ExceptionSnapshot, ...]
    handlers: tuple[HandlerState, ...]
    event_cids: tuple[str, ...]
    unavailable_dimensions: tuple[str, ...]
    redacted_dimensions: tuple[str, ...]
    completeness_claim: CompletenessClaim | str
    privacy_class: PrivacyClass | str
    includes_raw_bodies: bool
    accepted_transition: Mapping[str, Any] | None
    cancellation: Mapping[str, Any] | None
    result_summary: Mapping[str, Any]
    raised_type: str | None
    replayed: bool = False
    promise_matched: bool | None = None
    result: Any = None
    trace: ExecutionTrace | None = None

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACE_RECORD_INTERFACE
    SCHEMA: ClassVar[str] = TRACE_RECORD_SCHEMA

    def __post_init__(self) -> None:
        status = self.status
        if isinstance(status, TraceStatus):
            status_value = status.value
        else:
            try:
                status_value = TraceStatus(status).value
            except (TypeError, ValueError) as error:
                raise PythonExecutionTraceError("status is unsupported") from error
        object.__setattr__(self, "status", status_value)
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "states", tuple(self.states))
        object.__setattr__(self, "frames", tuple(self.frames))
        object.__setattr__(self, "exceptions", tuple(self.exceptions))
        object.__setattr__(self, "handlers", tuple(self.handlers))
        object.__setattr__(self, "event_cids", tuple(self.event_cids))
        object.__setattr__(self, "unavailable_dimensions", tuple(sorted(set(self.unavailable_dimensions))))
        object.__setattr__(self, "redacted_dimensions", tuple(sorted(set(self.redacted_dimensions))))
        if self.accepted_transition is not None:
            if status_value == TraceStatus.CANCELLED.value:
                raise PythonExecutionTraceError("cancellation emits no accepted transition")
            if not isinstance(self.accepted_transition, Mapping):
                raise PythonExecutionTraceError("accepted_transition must be a mapping")
            if self.accepted_transition.get("admitted") is not True:
                raise PythonExecutionTraceError("accepted_transition must be admitted")
            object.__setattr__(
                self, "accepted_transition", MappingProxyType(dict(self.accepted_transition))
            )
        if self.cancellation is not None:
            if not isinstance(self.cancellation, Mapping):
                raise PythonExecutionTraceError("cancellation must be a mapping")
            if self.cancellation.get("accepted_transition") not in {False, None}:
                raise PythonExecutionTraceError("cancellation emits no accepted transition")
            object.__setattr__(self, "cancellation", MappingProxyType(dict(self.cancellation)))
        if status_value == TraceStatus.CANCELLED.value:
            if self.accepted_transition is not None:
                raise PythonExecutionTraceError("cancellation emits no accepted transition")
            if any(str(event.event_kind) == EventKind.EXIT.value for event in self.events):
                raise PythonExecutionTraceError("cancellation emits no accepted transition")
        object.__setattr__(self, "result_summary", MappingProxyType(dict(self.result_summary)))
        if self.includes_raw_bodies and str(self.privacy_class) in {
            PrivacyClass.PUBLIC.value,
            PrivacyClass.INTERNAL.value,
        }:
            raise PythonExecutionTraceError(
                "raw bodies remain private and cannot enter public records"
            )

    @property
    def accepted(self) -> bool:
        return self.accepted_transition is not None and self.status == TraceStatus.COMPLETED.value

    @property
    def cancelled(self) -> bool:
        return self.status == TraceStatus.CANCELLED.value

    @property
    def public_trace(self) -> ExecutionTrace | None:
        if self.trace is None:
            return None
        return self.trace.public_view()

    @property
    def deterministic_promise_cid(self) -> str:
        return cid_for_structured(
            {
                "capture_profile_cid": self.capture_profile_cid,
                "environment_binding_cid": self.environment_binding_cid,
                "event_cids": list(self.event_cids),
                "event_kinds": [str(event.event_kind) for event in self.events],
                "logical_names": [event.logical_name for event in self.events],
                "schema": TRACE_RECORD_SCHEMA + "#promise",
                "source_cid": self.source_cid,
                "status": self.status,
                "tree_cid": self.tree_cid,
            }
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "accepted_transition": (
                None if self.accepted_transition is None else dict(self.accepted_transition)
            ),
            "cancellation": None if self.cancellation is None else dict(self.cancellation),
            "capture_profile_cid": self.capture_profile_cid,
            "completeness_claim": str(self.completeness_claim),
            "deterministic_promise_cid": self.deterministic_promise_cid,
            "environment_binding_cid": self.environment_binding_cid,
            "event_cids": list(self.event_cids),
            "includes_raw_bodies": self.includes_raw_bodies,
            "policy_cid": self.policy.policy_cid,
            "privacy_class": str(self.privacy_class),
            "promise_matched": self.promise_matched,
            "raised_type": self.raised_type,
            "redacted_dimensions": list(self.redacted_dimensions),
            "replayed": self.replayed,
            "result_summary": dict(self.result_summary),
            "schema": self.SCHEMA,
            "source_cid": self.source_cid,
            "status": self.status,
            "trace_cid": None if self.trace is None else self.trace.execution_trace_cid,
            "tree_cid": self.tree_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["record_cid"] = self.record_cid
        payload["events"] = [event.to_dict() for event in self.events]
        if self.trace is not None:
            payload["trace"] = self.trace.to_dict()
        return payload

    def to_public_dict(self) -> dict[str, Any]:
        public_trace = self.public_trace
        payload = self.identity_payload()
        payload["includes_raw_bodies"] = False
        payload["privacy_class"] = PrivacyClass.PUBLIC.value
        payload["raw_execution_state_cids"] = []
        payload["states"] = []
        if self.includes_raw_bodies or self.redacted_dimensions:
            payload["completeness_claim"] = CompletenessClaim.REDACTED.value
            payload["redacted_dimensions"] = sorted(
                set(self.redacted_dimensions) | {"raw_body"}
            )
        payload["accepted_transition"] = (
            None if self.cancelled else payload["accepted_transition"]
        )
        payload["result_summary"] = {"bounded": True}
        payload["trace"] = None if public_trace is None else public_trace.to_dict()
        if public_trace is not None and (
            public_trace.includes_raw_bodies or public_trace.raw_execution_state_cids
        ):
            raise PythonExecutionTraceError("raw bodies remain private")
        payload["events"] = [
            {
                "event_kind": str(event.event_kind),
                "logical_name": event.logical_name,
                "program_event_cid": event.program_event_cid,
                "source_cid": event.source_cid,
                "tree_cid": event.tree_cid,
                "environment_binding_cid": event.environment_binding_cid,
            }
            for event in self.events
        ]
        payload["record_cid"] = cid_for_structured(
            {key: value for key, value in payload.items() if key != "record_cid"}
        )
        return payload


class _HermeticIsolation:
    """Install fail-closed denial hooks for the duration of one recording."""

    def __init__(self, policy: TraceCollectionPolicy, on_denied: Callable[[str], None]) -> None:
        self.policy = policy
        self.on_denied = on_denied
        self._restores: list[tuple[Any, str, Any]] = []

    def _deny(self, name: str) -> Callable[..., Any]:
        def denied(*_args: object, **_kwargs: object) -> Any:
            self.on_denied(name)
            raise HermeticIsolationError(f"{name} denied by hermetic trace policy")

        return denied

    def _patch(self, module: Any, attribute: str, name: str) -> None:
        if module is None or not hasattr(module, attribute):
            return
        original = getattr(module, attribute)
        self._restores.append((module, attribute, original))
        setattr(module, attribute, self._deny(name))

    def _patch_method(self, cls: type, attribute: str, name: str) -> None:
        if not hasattr(cls, attribute):
            return
        original = getattr(cls, attribute)
        self._restores.append((cls, attribute, original))
        setattr(cls, attribute, self._deny(name))

    def __enter__(self) -> "_HermeticIsolation":
        if self.policy.deny_socket or self.policy.deny_network:
            import socket

            self._patch(socket, "create_connection", "socket.create_connection")
            self._patch(socket, "getaddrinfo", "socket.getaddrinfo")
            self._patch(socket, "create_server", "socket.create_server")
            self._patch_method(socket.socket, "connect", "socket.socket.connect")
            self._patch_method(socket.socket, "connect_ex", "socket.socket.connect_ex")
        if self.policy.deny_network:
            urllib_request = sys.modules.get("urllib.request")
            if urllib_request is not None:
                self._patch(urllib_request, "urlopen", "urllib.request.urlopen")
                self._patch(urllib_request, "urlretrieve", "urllib.request.urlretrieve")
            http_client = sys.modules.get("http.client")
            if http_client is not None:
                self._patch(http_client, "HTTPConnection", "http.client.HTTPConnection")
                self._patch(http_client, "HTTPSConnection", "http.client.HTTPSConnection")
        if self.policy.deny_subprocess or self.policy.deny_installer:
            import os
            import subprocess

            self._patch(subprocess, "Popen", "subprocess.Popen")
            self._patch(subprocess, "run", "subprocess.run")
            self._patch(subprocess, "call", "subprocess.call")
            self._patch(subprocess, "check_call", "subprocess.check_call")
            self._patch(subprocess, "check_output", "subprocess.check_output")
            self._patch(os, "system", "os.system")
            self._patch(os, "popen", "os.popen")
        if self.policy.deny_database:
            import sqlite3

            self._patch(sqlite3, "connect", "sqlite3.connect")
            duckdb = sys.modules.get("duckdb")
            if duckdb is not None:
                self._patch(duckdb, "connect", "duckdb.connect")
        return self

    def __exit__(self, *_exc: object) -> None:
        for owner, attribute, original in reversed(self._restores):
            setattr(owner, attribute, original)
        self._restores.clear()


class PythonExecutionTracer:
    """In-process sys.settrace/sys.setprofile collector for admitted Python."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE
    VERSION: ClassVar[str] = PYTHON_EXECUTION_TRACE_VERSION

    def __init__(
        self,
        policy: TraceCollectionPolicy | None = None,
        *,
        redactor: TraceRedactor | None = None,
        tree_cid: str | None = None,
        source_cid: str | None = None,
        environment_binding: Mapping[str, str] | None = None,
    ) -> None:
        if policy is None:
            self.policy = TraceCollectionPolicy(environment_binding=environment_binding or {})
        elif not isinstance(policy, TraceCollectionPolicy):
            raise PythonExecutionTraceError("policy must be a TraceCollectionPolicy")
        elif environment_binding:
            self.policy = policy.with_environment(environment_binding)
        else:
            self.policy = policy
        self.redactor = redactor or TraceRedactor(self.policy)
        self._explicit_tree_cid = tree_cid
        self._explicit_source_cid = source_cid
        self._cancel_requested: TraceCancellation | None = None
        self._reset_session()

    def _reset_session(self) -> None:
        self._target_code: CodeType | None = None
        self._target_qualname = ""
        self._target_filename = ""
        self._events: list[ProgramEvent] = []
        self._states: list[ProgramExecutionState] = []
        self._frames_by_cid: dict[str, StackFrameState] = {}
        self._exceptions: list[ExceptionSnapshot] = []
        self._handlers: list[HandlerState] = []
        self._unavailable: set[str] = set()
        self._redacted: set[str] = set()
        self._line_events = 0
        self._entered = False
        self._root_returned = False
        self._admission_open = True
        self._cancelled: TraceCancellation | None = None
        self._pending_exception: tuple[type, BaseException] | None = None
        self._pending_exception_cid: str | None = None
        self._pending_exception_frame_id: int | None = None
        self._handler_emitted_for: set[int] = set()
        self._opcode_cache: dict[CodeType, dict[int, str]] = {}
        self._exception_table_cache: dict[CodeType, tuple[tuple[int, int, int], ...]] = {}
        self._predecessor: str | None = None
        self._denied_effects: list[str] = []
        self._tree_cid = self._explicit_tree_cid
        self._source_cid = self._explicit_source_cid
        self._environment_binding = dict(self.policy.environment_binding) or _default_environment_binding()
        self._environment_cid = _environment_cid(self._environment_binding)
        self._subject_cid = ""
        self._cancel_check: Callable[[], bool] | None = None
        self._cancel_requested = None

    def cancel(self, reason: str = "cancelled") -> None:
        """Request cancellation.  Subsequent events are not accepted."""

        self._cancel_requested = TraceCancellation(reason, at_event_index=len(self._events))
        self._admission_open = False

    request_cancellation = cancel

    def record(
        self,
        target: Callable[..., Any],
        /,
        *args: Any,
        cancel_check: Callable[[], bool] | None = None,
        **kwargs: Any,
    ) -> PythonExecutionTraceRecord:
        if not callable(target):
            raise PythonExecutionTraceError("record_python_execution_trace requires a callable")
        if getattr(_THREAD_STATE, "active", False):
            raise PythonExecutionTraceError("nested hermetic tracing is not admitted")
        self._reset_session()
        self._cancel_check = cancel_check
        if self._cancel_requested is not None:
            self._cancelled = self._cancel_requested
            self._admission_open = False
        code = getattr(target, "__code__", None)
        if not isinstance(code, CodeType):
            raise PythonExecutionTraceError("target must be a Python function with a code object")
        self._target_code = code
        self._target_qualname = _qualname(code)
        self._target_filename = code.co_filename
        self._source_cid = self._source_cid or _source_cid_for_code(code)
        self._tree_cid = self._tree_cid or _tree_cid(code, self._source_cid)
        self._subject_cid = _code_cid(code)
        return self._run(target, args, kwargs)

    def _run(
        self, target: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> PythonExecutionTraceRecord:
        previous_trace = sys.gettrace()
        previous_profile = sys.getprofile()
        _THREAD_STATE.active = True
        result: Any = None
        raised: BaseException | None = None
        try:
            with _HermeticIsolation(self.policy, self._note_denied):
                sys.settrace(self._trace)
                if self.policy.collect_external:
                    sys.setprofile(self._profile)
                try:
                    result = self._invoke(target, args, kwargs)
                except TraceCancellation as cancelled:
                    self._cancelled = cancelled
                    self._admission_open = False
                except (PythonExecutionTraceError, ProgramExecutionError):
                    raise
                except Exception as error:
                    raised = error
        finally:
            sys.settrace(previous_trace)
            sys.setprofile(previous_profile)
            _THREAD_STATE.active = False
        if self._cancel_requested is not None and self._cancelled is None:
            self._cancelled = self._cancel_requested
            self._admission_open = False
        return self._seal(result, raised)

    def _invoke(
        self, target: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> Any:
        import inspect

        if inspect.iscoroutinefunction(target):
            import asyncio

            return asyncio.run(target(*args, **kwargs))
        return target(*args, **kwargs)

    def _note_denied(self, name: str) -> None:
        self._denied_effects.append(name)
        self._unavailable.add("external")
        if self._admission_open and self.policy.admits(EventKind.EXTERNAL.value):
            # Unlike ordinary trace callbacks, denial hooks run inside the
            # target call. Do not recursively trace the evidence builder.
            previous_trace, previous_profile = sys.gettrace(), sys.getprofile()
            sys.settrace(None)
            sys.setprofile(None)
            try:
                frame = sys._getframe(1)
                while frame is not None and _is_internal_frame(frame):
                    frame = frame.f_back
                if frame is not None:
                    self._emit(
                        frame,
                        EventKind.EXTERNAL.value,
                        payload={"denied": True, "effect": name},
                        observation_status=ObservationStatus.UNAVAILABLE.value,
                        completeness=CompletenessClaim.PARTIAL.value,
                        extra_unavailable=("external",),
                    )
            finally:
                sys.settrace(previous_trace)
                sys.setprofile(previous_profile)

    def _subject_frame(self, frame: FrameType) -> bool:
        if self._target_code is None or _is_internal_frame(frame):
            return False
        current: FrameType | None = frame
        depth = 0
        while current is not None and depth <= self.policy.max_stack_depth * 4:
            if current.f_code is self._target_code:
                return True
            if _is_internal_frame(current):
                current = current.f_back
                depth += 1
                continue
            current = current.f_back
            depth += 1
        return False

    def _maybe_cancel(self) -> bool:
        if not self._admission_open:
            return True
        if self._cancel_requested is not None:
            self._cancelled = self._cancel_requested
            self._admission_open = False
            return True
        if self._cancel_check is not None:
            try:
                requested = bool(self._cancel_check())
            except Exception as error:
                raise PythonExecutionTraceError("cancel_check failed") from error
            if requested:
                self.cancel("cancel_check")
                self._cancelled = self._cancel_requested
                return True
        return False

    def _trace(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if not self._subject_frame(frame):
            return self._trace if not _is_internal_frame(frame) else None
        if self._maybe_cancel():
            return None
        try:
            if event == "call":
                self._on_call(frame)
            elif event == "return":
                self._on_return(frame, arg)
            elif event == "line":
                self._on_line(frame)
            elif event == "exception":
                self._on_exception(frame, arg)
        except TraceCancellation as cancelled:
            self._cancelled = cancelled
            self._admission_open = False
            return None
        except HermeticIsolationError:
            raise
        except PythonExecutionTraceError:
            raise
        except ProgramExecutionError:
            raise
        except Exception:
            self._unavailable.add("tracer")
        if self._maybe_cancel():
            return None
        return self._trace

    def _profile(self, frame: FrameType, event: str, arg: Any) -> None:
        if event != "c_call" or not self._admission_open:
            return
        if not self._subject_frame(frame):
            return
        external, name = _is_external_callable(arg)
        if not external:
            module = str(getattr(arg, "__module__", "") or "")
            if module.split(".", 1)[0] in _DENIED_MODEL_MODULES:
                external, name = True, module
        if not external:
            return
        payload = {"effect": name, "kind": "c_call"}
        self._emit(
            frame,
            EventKind.EXTERNAL.value,
            payload=payload,
            completeness=CompletenessClaim.PARTIAL.value,
            extra_unavailable=("external_result",),
        )

    def _on_call(self, frame: FrameType) -> None:
        is_root = frame.f_code is self._target_code and not self._entered
        if is_root and self.policy.admits(EventKind.ENTER.value):
            self._entered = True
            self._emit(frame, EventKind.ENTER.value, payload={"phase": "enter"})
        elif is_root:
            self._entered = True
        if self.policy.admits(EventKind.CALL.value):
            self._emit(
                frame,
                EventKind.CALL.value,
                payload={"callee": _qualname(frame.f_code)},
            )

    def _on_return(self, frame: FrameType, arg: Any) -> None:
        flags = frame.f_code.co_flags
        opname = _opname_at(frame, self._opcode_cache)
        kind = EventKind.RETURN.value
        payload: dict[str, Any] = {"bounded": True}
        if flags & (CO_GENERATOR | CO_ASYNC_GENERATOR) and opname in _YIELD_OPCODES:
            kind = EventKind.YIELD.value
        elif flags & (CO_COROUTINE | CO_ITERABLE_COROUTINE) and (
            opname in _AWAIT_OPCODES or opname in _YIELD_OPCODES
        ):
            kind = EventKind.AWAIT.value
        if kind == EventKind.RETURN.value and self.policy.capture_locals:
            if type(arg) is str:
                payload = {"bounded": True, "type": "str"}
            else:
                summary, redacted, _remaining_budget = self.redactor.redact_value(
                    arg, budget=min(256, self.policy.max_payload_bytes)
                )
                payload = {"bounded": True, "value": _drop_secret_keys(summary)}
                self._redacted.update(redacted)
        if self.policy.admits(kind):
            self._emit(frame, kind, payload=payload)
        if frame.f_code is self._target_code and kind == EventKind.RETURN.value:
            self._root_returned = True
            if self.policy.admits(EventKind.EXIT.value) and self._admission_open:
                self._emit(frame, EventKind.EXIT.value, payload={"phase": "exit"})

    def _on_line(self, frame: FrameType) -> None:
        handler_kind = _handler_kind_for_offset(
            frame.f_code, frame.f_lasti, self._exception_table_cache
        )
        same_frame_handler = (
            self._pending_exception is not None
            and self._pending_exception_frame_id == id(frame)
        )
        if (
            (handler_kind or same_frame_handler)
            and self._pending_exception is not None
            and id(frame) not in self._handler_emitted_for
            and self.policy.admits(EventKind.HANDLER.value)
        ):
            self._handler_emitted_for.add(id(frame))
            self._emit_handler(frame, handler_kind or HandlerKind.EXCEPT.value)
        if not self.policy.admits(EventKind.LINE.value):
            return
        if self._line_events >= self.policy.max_line_events:
            self._unavailable.add("line")
            return
        self._line_events += 1
        self._emit(frame, EventKind.LINE.value, payload={"lineno": frame.f_lineno})

    def _on_exception(self, frame: FrameType, arg: Any) -> None:
        if not isinstance(arg, tuple) or len(arg) < 2:
            return
        exc_type, exc_value = arg[0], arg[1]
        if isinstance(exc_value, TraceCancellation):
            self._cancelled = exc_value
            self._admission_open = False
            return
        if not self.policy.admits(EventKind.RAISE.value):
            self._unavailable.add("exception")
            return
        snapshot = self._exception_snapshot(frame, exc_type, exc_value)
        self._pending_exception = (exc_type, exc_value)
        self._pending_exception_cid = snapshot.exception_snapshot_cid
        self._pending_exception_frame_id = id(frame)
        self._emit(
            frame,
            EventKind.RAISE.value,
            payload={"exception_type": snapshot.exception_type},
            exception_snapshot_cid=snapshot.exception_snapshot_cid,
        )

    def _emit_handler(self, frame: FrameType, handler_kind: str) -> None:
        matching = self._pending_exception_cid
        handler = HandlerState(
            language=ADMITTED_LANGUAGE,
            handler_kind=handler_kind,
            tree_cid=self._tree_cid or _tree_cid(frame.f_code, self._source_cid or _source_cid_for_code(frame.f_code)),
            source_cid=self._source_cid or _source_cid_for_code(frame.f_code),
            code_cid=_code_cid(frame.f_code),
            environment_binding_cid=self._environment_cid,
            logical_name=_qualname(frame.f_code),
            stack_ordinal=0,
            handler_active=True,
            matching_exception_snapshot_cid=matching,
            unavailable_dimensions=() if matching is not None else ("exception",),
        )
        self._handlers.append(handler)
        self._emit(
            frame,
            EventKind.CATCH.value,
            payload={"handler_kind": handler_kind},
            handler_state_cid=handler.handler_state_cid,
        )
        if self.policy.admits(EventKind.HANDLER.value):
            self._emit(
                frame,
                EventKind.HANDLER.value,
                payload={"handler_kind": handler_kind},
                handler_state_cid=handler.handler_state_cid,
            )
        self._pending_exception = None

    def _locals_summary(self, frame: FrameType) -> tuple[dict[str, Any], tuple[str, ...]]:
        if not self.policy.capture_locals:
            return {}, ("locals",)
        try:
            raw_locals = dict(frame.f_locals)
        except Exception:
            return {}, ("locals",)
        summary, redacted = self.redactor.bounded_mapping(
            raw_locals, budget=self.policy.max_summary_bytes
        )
        dropped = {
            key for key in raw_locals if type(key) is str and _secret_key(key)
        }
        summary = _drop_secret_keys(summary)
        if not isinstance(summary, dict):
            summary = {"bounded": True}
        return {"locals": summary}, tuple(sorted(set(redacted) | dropped))

    def _stack_frames(
        self, frame: FrameType, *, exception_cid: str | None = None, handler_cid: str | None = None
    ) -> tuple[StackFrameState, ...]:
        collected: list[FrameType] = []
        current: FrameType | None = frame
        while current is not None and len(collected) < self.policy.max_stack_depth:
            if self._subject_frame(current):
                collected.append(current)
            current = current.f_back
        if not collected:
            collected = [frame]
        frames: list[StackFrameState] = []
        tree_cid = self._tree_cid or _tree_cid(frame.f_code, self._source_cid or _source_cid_for_code(frame.f_code))
        source_cid = self._source_cid or _source_cid_for_code(frame.f_code)
        for ordinal, item in enumerate(collected):
            summary, redacted = self._locals_summary(item)
            self._redacted.update(redacted)
            claim = CompletenessClaim.FULL_STATE.value
            unavailable: tuple[str, ...] = ()
            if redacted:
                claim = CompletenessClaim.REDACTED.value
            if not self.policy.capture_locals:
                unavailable = ("locals",)
                claim = CompletenessClaim.PARTIAL.value
            if isinstance(summary, dict):
                overlap = set(redacted) & set(summary)
                for key in overlap:
                    summary.pop(key, None)
                summary = _drop_secret_keys(summary)
            try:
                frame_state = StackFrameState(
                    ordinal=ordinal,
                    language=ADMITTED_LANGUAGE,
                    tree_cid=tree_cid,
                    source_cid=source_cid,
                    code_cid=_code_cid(item.f_code),
                    environment_binding_cid=self._environment_cid,
                    logical_name=_qualname(item.f_code),
                    line=item.f_lineno,
                    column=None,
                    state_summary=summary if isinstance(summary, Mapping) else {"bounded": True},
                    exception_snapshot_cid=exception_cid if ordinal == 0 else None,
                    handler_state_cid=handler_cid if ordinal == 0 else None,
                    exception_active=exception_cid is not None and ordinal == 0,
                    handler_active=handler_cid is not None and ordinal == 0,
                    redacted_dimensions=redacted,
                    unavailable_dimensions=unavailable,
                    completeness_claim=claim,
                    privacy_class=self.policy.privacy_class,
                )
            except ProgramExecutionError:
                self._unavailable.add("locals")
                frame_state = StackFrameState(
                    ordinal=ordinal,
                    language=ADMITTED_LANGUAGE,
                    tree_cid=tree_cid,
                    source_cid=source_cid,
                    code_cid=_code_cid(item.f_code),
                    environment_binding_cid=self._environment_cid,
                    logical_name=_qualname(item.f_code),
                    line=item.f_lineno,
                    column=None,
                    state_summary={},
                    exception_snapshot_cid=exception_cid if ordinal == 0 else None,
                    handler_state_cid=handler_cid if ordinal == 0 else None,
                    exception_active=exception_cid is not None and ordinal == 0,
                    handler_active=handler_cid is not None and ordinal == 0,
                    redacted_dimensions=redacted,
                    unavailable_dimensions=tuple(sorted(set(unavailable) | {"locals"})),
                    completeness_claim=CompletenessClaim.PARTIAL.value,
                    privacy_class=self.policy.privacy_class,
                )
            frames.append(frame_state)
            self._frames_by_cid[frame_state.stack_frame_state_cid] = frame_state
        return tuple(frames)

    def _exception_snapshot(
        self, frame: FrameType, exc_type: type, exc_value: BaseException
    ) -> ExceptionSnapshot:
        frames = self._stack_frames(frame)
        snapshot = ExceptionSnapshot(
            language=ADMITTED_LANGUAGE,
            exception_type=getattr(exc_type, "__name__", type(exc_value).__name__),
            tree_cid=self._tree_cid or frames[0].tree_cid,
            source_cid=self._source_cid or frames[0].source_cid,
            code_cid=frames[0].code_cid,
            environment_binding_cid=self._environment_cid,
            exception_value_summary={"bounded": True, "type": getattr(exc_type, "__name__", "Exception")},
            traceback_stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
            raised_at_event_cid=self._predecessor,
            future_execution=False,
            unavailable_dimensions=(),
            completeness_claim=CompletenessClaim.FULL_STATE.value,
        )
        self._exceptions.append(snapshot)
        return snapshot

    def _clamp_payload(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
        summary, redacted = self.redactor.bounded_mapping(
            dict(payload), budget=self.policy.max_payload_bytes
        )
        encoded_size = len(repr(summary))
        if encoded_size > self.policy.max_payload_bytes or encoded_size > MAX_METADATA_BYTES:
            return {"bounded": True}, tuple(sorted(set(redacted) | {"payload_bound"}))
        return summary, redacted

    def _emit(
        self,
        frame: FrameType,
        kind: str,
        *,
        payload: Mapping[str, Any] | None = None,
        exception_snapshot_cid: str | None = None,
        handler_state_cid: str | None = None,
        observation_status: str = ObservationStatus.OBSERVED.value,
        completeness: str | None = None,
        extra_unavailable: Sequence[str] = (),
    ) -> None:
        if not self._admission_open:
            return
        if len(self._events) >= self.policy.max_events:
            self._unavailable.add("event_bound")
            self._admission_open = False
            return
        if not self.policy.admits(kind):
            return
        frames = self._stack_frames(
            frame,
            exception_cid=exception_snapshot_cid,
            handler_cid=handler_state_cid,
        )
        clamped, redacted = self._clamp_payload(payload or {})
        clamped = _drop_secret_keys(clamped)
        if not isinstance(clamped, dict):
            clamped = {"bounded": True}
        self._redacted.update(redacted)
        unavailable = set(extra_unavailable)
        claim = completeness
        if claim is None:
            if redacted:
                claim = CompletenessClaim.REDACTED.value
            elif unavailable:
                claim = CompletenessClaim.PARTIAL.value
            else:
                claim = CompletenessClaim.FULL_STATE.value
        if observation_status != ObservationStatus.OBSERVED.value and claim == CompletenessClaim.FULL_STATE.value:
            claim = CompletenessClaim.PARTIAL.value
            if not unavailable:
                unavailable.add("observation")
        event = ProgramEvent(
            event_kind=kind,
            event_origin=EventOrigin.OBSERVED.value,
            observation_status=observation_status,
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid or frames[0].tree_cid,
            source_cid=self._source_cid or frames[0].source_cid,
            code_cid=frames[0].code_cid,
            environment_binding_cid=self._environment_cid,
            subject_cid=self._subject_cid or frames[0].code_cid,
            logical_name=_qualname(frame.f_code),
            payload=clamped,
            line=frame.f_lineno,
            column=None,
            predecessor_event_cid=self._predecessor,
            stack_frame_cids=tuple(item.stack_frame_state_cid for item in frames),
            exception_snapshot_cid=exception_snapshot_cid,
            handler_state_cid=handler_state_cid,
            redaction_profile_cid=None,
            redacted_dimensions=redacted,
            unavailable_dimensions=tuple(sorted(unavailable)),
            completeness_claim=claim,
            privacy_class=self.policy.privacy_class,
        )
        self._events.append(event)
        self._predecessor = event.program_event_cid
        if self.policy.capture_states and kind in {
            EventKind.CALL.value,
            EventKind.RETURN.value,
            EventKind.RAISE.value,
            EventKind.ENTER.value,
            EventKind.EXIT.value,
        }:
            self._capture_state(frames, exception_snapshot_cid, handler_state_cid)

    def _capture_state(
        self,
        frames: Sequence[StackFrameState],
        exception_cid: str | None,
        handler_cid: str | None,
    ) -> None:
        exception = next(
            (item for item in self._exceptions if item.exception_snapshot_cid == exception_cid),
            None,
        )
        handler = next(
            (item for item in self._handlers if item.handler_state_cid == handler_cid),
            None,
        )
        redaction = None
        if self._redacted:
            redaction = RedactionProfile(
                privacy_class=self.policy.privacy_class,
                redacted_dimensions=tuple(sorted(self._redacted)),
                unavailable_dimensions=(),
                completeness_claim=CompletenessClaim.REDACTED.value,
            )
        observed = frames[0].state_summary if frames else {}
        try:
            state = assemble_program_execution_state(
                capture_profile_cid=self.policy.capture_profile_cid,
                tree_cid=self._tree_cid or frames[0].tree_cid,
                source_cid=self._source_cid or frames[0].source_cid,
                environment_binding_cid=self._environment_cid,
                frames=frames,
                observed_state=observed,
                heap_summary={"objects": len(frames)},
                heap_bound=HeapBound.BOUNDED_ABSTRACT,
                exception=exception,
                handler=handler,
                redaction=redaction,
                privacy_class=(
                    PrivacyClass.PRIVATE.value
                    if self.policy.include_raw_bodies
                    else self.policy.privacy_class
                ),
                includes_raw_bodies=self.policy.include_raw_bodies,
                unavailable_dimensions=tuple(sorted(self._unavailable)),
            )
        except ProgramExecutionError:
            self._unavailable.add("execution_state")
            return
        self._states.append(state)

    def _seal(
        self, result: Any, raised: BaseException | None
    ) -> PythonExecutionTraceRecord:
        cancelled = self._cancelled
        if cancelled is not None:
            status = TraceStatus.CANCELLED
        elif not self._events:
            status = TraceStatus.INCOMPLETE
            self._unavailable.add("events")
        elif raised is not None or self._root_returned:
            status = TraceStatus.COMPLETED
        elif not self._admission_open:
            status = TraceStatus.INCOMPLETE
            self._unavailable.add("trace_prefix")
        else:
            status = TraceStatus.INCOMPLETE
            self._unavailable.add("trace_prefix")
        if cancelled is not None:
            self._unavailable.add("cancelled")
        result_summary, result_redacted, _remaining_budget = self.redactor.redact_value(
            result, budget=min(512, self.policy.max_payload_bytes)
        )
        self._redacted.update(result_redacted)
        if type(result) is str or any(_secret_key(item) for item in self._redacted):
            result_summary = {"bounded": True}
        elif not isinstance(result_summary, Mapping):
            result_summary = {"value": _drop_secret_keys(result_summary), "bounded": True}
        else:
            result_summary = _drop_secret_keys(result_summary)
            if not isinstance(result_summary, Mapping):
                result_summary = {"bounded": True}
        claim: str
        if cancelled is not None or self._unavailable:
            claim = CompletenessClaim.PARTIAL.value
        elif self._redacted:
            claim = CompletenessClaim.REDACTED.value
        else:
            claim = CompletenessClaim.FULL_STATE.value
        privacy = (
            PrivacyClass.PRIVATE.value
            if self.policy.include_raw_bodies
            else self.policy.privacy_class
        )
        trace: ExecutionTrace | None = None
        if self._events:
            redaction = None
            if self._redacted:
                redaction = RedactionProfile(
                    privacy_class=privacy,
                    redacted_dimensions=tuple(sorted(self._redacted)),
                    unavailable_dimensions=tuple(sorted(self._unavailable)),
                    completeness_claim=(
                        CompletenessClaim.REDACTED.value
                        if self._redacted and not self._unavailable
                        else CompletenessClaim.PARTIAL.value
                    ),
                )
            try:
                trace = assemble_execution_trace(
                    tree_cid=self._tree_cid or self._events[0].tree_cid,
                    source_cid=self._source_cid or self._events[0].source_cid,
                    environment_binding_cid=self._environment_cid,
                    events=self._events,
                    states=self._states if self.policy.include_raw_bodies else (),
                    redaction=redaction,
                    completeness_claim=claim,
                    privacy_class=privacy,
                    includes_raw_bodies=self.policy.include_raw_bodies,
                    unavailable_dimensions=tuple(sorted(self._unavailable)),
                )
            except ProgramExecutionError as error:
                raise PythonExecutionTraceError(str(error)) from error
        accepted_transition: dict[str, Any] | None = None
        if status is TraceStatus.COMPLETED and trace is not None:
            terminal = self._events[-1]
            accepted_transition = {
                "admitted": True,
                "from_event_cid": self._events[0].program_event_cid,
                "kind": "accepted_completion",
                "schema": TRACE_TRANSITION_SCHEMA,
                "to_event_cid": terminal.program_event_cid,
                "trace_cid": trace.execution_trace_cid,
            }
        cancellation_payload = None if cancelled is None else cancelled.to_dict()
        record = PythonExecutionTraceRecord(
            status=status,
            policy=self.policy,
            tree_cid=self._tree_cid or (self._events[0].tree_cid if self._events else cid_for_bytes(b"empty-tree")),
            source_cid=self._source_cid or (self._events[0].source_cid if self._events else cid_for_bytes(b"empty-source")),
            environment_binding_cid=self._environment_cid,
            capture_profile_cid=self.policy.capture_profile_cid,
            events=tuple(self._events),
            states=tuple(self._states),
            frames=tuple(self._frames_by_cid.values()),
            exceptions=tuple(self._exceptions),
            handlers=tuple(self._handlers),
            event_cids=tuple(event.program_event_cid for event in self._events),
            unavailable_dimensions=tuple(sorted(self._unavailable)),
            redacted_dimensions=tuple(sorted(self._redacted)),
            completeness_claim=claim,
            privacy_class=privacy,
            includes_raw_bodies=self.policy.include_raw_bodies,
            accepted_transition=accepted_transition,
            cancellation=cancellation_payload,
            result_summary=dict(result_summary),
            raised_type=None if raised is None else type(raised).__name__,
            result=result,
            trace=trace,
        )
        if raised is not None and cancelled is None:
            object.__setattr__(record, "result", None)
        return record


def record_python_execution_trace(
    target: Callable[..., Any],
    /,
    *args: Any,
    policy: TraceCollectionPolicy | None = None,
    tracer: PythonExecutionTracer | None = None,
    cancel_check: Callable[[], bool] | None = None,
    tree_cid: str | None = None,
    source_cid: str | None = None,
    environment_binding: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> PythonExecutionTraceRecord:
    """Record a hermetic, bounded execution trace of ``target``."""

    collector = tracer or PythonExecutionTracer(
        policy,
        tree_cid=tree_cid,
        source_cid=source_cid,
        environment_binding=environment_binding,
    )
    return collector.record(target, *args, cancel_check=cancel_check, **kwargs)


def replay_deterministic_trace(
    record: PythonExecutionTraceRecord,
    target: Callable[..., Any] | None = None,
    /,
    *args: Any,
    policy: TraceCollectionPolicy | None = None,
    **kwargs: Any,
) -> PythonExecutionTraceRecord:
    """Replay a promised deterministic trace without admitting cancelled transitions.

    When ``target`` is omitted the stored event identities are reconstructed and
    the original deterministic promise is re-bound.  When ``target`` is supplied
    the callable is recorded again under the same policy; event identities must
    match or replay fails closed.
    """

    if not isinstance(record, PythonExecutionTraceRecord):
        raise PythonExecutionTraceError("replay requires a PythonExecutionTraceRecord")
    if record.cancelled:
        replayed = PythonExecutionTraceRecord(
            status=TraceStatus.CANCELLED,
            policy=record.policy,
            tree_cid=record.tree_cid,
            source_cid=record.source_cid,
            environment_binding_cid=record.environment_binding_cid,
            capture_profile_cid=record.capture_profile_cid,
            events=record.events,
            states=(),
            frames=record.frames,
            exceptions=record.exceptions,
            handlers=record.handlers,
            event_cids=record.event_cids,
            unavailable_dimensions=tuple(sorted(set(record.unavailable_dimensions) | {"cancelled"})),
            redacted_dimensions=record.redacted_dimensions,
            completeness_claim=CompletenessClaim.PARTIAL,
            privacy_class=record.privacy_class,
            includes_raw_bodies=False,
            accepted_transition=None,
            cancellation=record.cancellation,
            result_summary=dict(record.result_summary),
            raised_type=record.raised_type,
            replayed=True,
            promise_matched=True,
            result=None,
            trace=None if record.trace is None else record.trace.public_view(),
        )
        if replayed.accepted_transition is not None:
            raise PythonExecutionTraceError("cancellation emits no accepted transition")
        return replayed
    if target is None:
        if record.trace is None:
            raise PythonExecutionTraceError("promised replay requires a recorded trace")
        reconstructed = assemble_execution_trace(
            tree_cid=record.tree_cid,
            source_cid=record.source_cid,
            environment_binding_cid=record.environment_binding_cid,
            events=record.events,
            states=(),
            completeness_claim=record.completeness_claim,
            privacy_class=record.privacy_class if not record.includes_raw_bodies else PrivacyClass.INTERNAL,
            includes_raw_bodies=False,
            unavailable_dimensions=record.unavailable_dimensions,
        )
        if reconstructed.event_cids != record.event_cids:
            raise PythonExecutionTraceError("deterministic replay diverged from the promised event order")
        return PythonExecutionTraceRecord(
            status=record.status,
            policy=record.policy,
            tree_cid=record.tree_cid,
            source_cid=record.source_cid,
            environment_binding_cid=record.environment_binding_cid,
            capture_profile_cid=record.capture_profile_cid,
            events=record.events,
            states=(),
            frames=record.frames,
            exceptions=record.exceptions,
            handlers=record.handlers,
            event_cids=record.event_cids,
            unavailable_dimensions=record.unavailable_dimensions,
            redacted_dimensions=tuple(sorted(set(record.redacted_dimensions) | {"raw_body"})),
            completeness_claim=(
                CompletenessClaim.REDACTED
                if record.includes_raw_bodies
                else record.completeness_claim
            ),
            privacy_class=PrivacyClass.PUBLIC if record.includes_raw_bodies else record.privacy_class,
            includes_raw_bodies=False,
            accepted_transition=(
                None if record.accepted_transition is None else dict(record.accepted_transition)
            ),
            cancellation=record.cancellation,
            result_summary=dict(record.result_summary),
            raised_type=record.raised_type,
            replayed=True,
            promise_matched=True,
            result=record.result,
            trace=reconstructed.public_view() if record.includes_raw_bodies else reconstructed,
        )
    replay_policy = policy or record.policy
    recorded = record_python_execution_trace(target, *args, policy=replay_policy, **kwargs)
    matched = recorded.deterministic_promise_cid == record.deterministic_promise_cid
    if not matched:
        raise PythonExecutionTraceError("deterministic replay diverged from the promised trace identity")
    object.__setattr__(recorded, "replayed", True)
    object.__setattr__(recorded, "promise_matched", True)
    return recorded


def observe_recorded_event(event: ProgramEvent) -> Any:
    """Admit an observed event; predicted/simulated events fail closed."""

    return observe_program_event(event)


__all__ = [
    "ADMITTED_LANGUAGE",
    "IMPORT_DATABASE_PERFORMED",
    "IMPORT_INSTALLER_PERFORMED",
    "IMPORT_MODEL_LOAD_PERFORMED",
    "IMPORT_NETWORK_PERFORMED",
    "IMPORT_REPO_SCAN_PERFORMED",
    "IMPORT_SOCKET_PERFORMED",
    "IMPORT_SUBPROCESS_PERFORMED",
    "IMPORT_WATCHER_PERFORMED",
    "PYTHON_EXECUTION_TRACE_RECORD_INTERFACE",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "RECORD_PYTHON_EXECUTION_TRACE_INTERFACE",
    "REPLAY_DETERMINISTIC_TRACE_INTERFACE",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "HermeticIsolationError",
    "PythonExecutionTraceError",
    "PythonExecutionTraceRecord",
    "PythonExecutionTracer",
    "TraceCancellation",
    "TraceCollectionPolicy",
    "TraceRedactor",
    "TraceStatus",
    "observe_recorded_event",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
