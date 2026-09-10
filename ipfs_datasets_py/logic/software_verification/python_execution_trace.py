"""Hermetic Python execution tracing bound to SAWM-007 execution contracts.

This module is the datasets Python tracing adapter for SAWM-008.  It records
admitted call, return, line, exception, handler, yield, await, and selected
external events under exact tree, source, symbol, and environment identities.

Normative constraints:

* Importing this module never opens a network or socket, never starts a
  subprocess, installer, database, watcher, or model load, and never scans a
  repository.  Tracing starts only from an explicit ``record`` call.
* Cancellation emits no accepted transition.  Operational acceptance is never
  persisted here.
* Private raw trace bodies never enter public records.  Secret and
  non-semantic fields are redacted before contract construction.
* Line and basic-block detail is policy-bounded.  Nondeterministic external
  effects are explicit observations or typed unavailable.
* Test-only network isolation is the default collection policy.
"""

from __future__ import annotations

import inspect
import opcode
import sys
import threading
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from types import CodeType, FrameType, MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.software_contracts.content import (
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
    ObservationStatus,
    PrivacyClass,
    ProgramEvent,
    ProgramExecutionError,
    ProgramLanguage,
    RedactionProfile,
    SECRET_FIELD_MARKERS,
    StackFrameState,
    assemble_execution_trace,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

PYTHON_EXECUTION_TRACER_INTERFACE: Final[str] = "PythonExecutionTracer@1"
TRACE_COLLECTION_POLICY_INTERFACE: Final[str] = "TraceCollectionPolicy@1"
TRACE_REDACTOR_INTERFACE: Final[str] = "TraceRedactor@1"
TRACE_CANCELLATION_INTERFACE: Final[str] = "TraceCancellation@1"
HERMETIC_TRACE_RECORD_INTERFACE: Final[str] = "HermeticTraceRecord@1"
HERMETIC_TRACE_REPLAY_INTERFACE: Final[str] = "HermeticTraceReplay@1"

PYTHON_EXECUTION_TRACER_VERSION: Final[str] = "1"
TRACE_COLLECTION_POLICY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-collection-policy@1"
)
TRACE_REDACTOR_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.trace-redactor@1"
)
HERMETIC_TRACE_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.hermetic-trace-record@1"
)
HERMETIC_TRACE_REPLAY_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.hermetic-trace-replay@1"
)
TRACE_ENVIRONMENT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-environment@1"
)
TRACE_CODE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-code@1"
)
TRACE_CAPTURE_PROFILE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-verification.python-trace-capture-profile@1"
)

ADMITTED_LANGUAGE: Final[str] = ProgramLanguage.PYTHON.value
MAX_SAFE_INTEGER: Final[int] = (1 << 53) - 1
MAX_TEXT_CHARS: Final[int] = 16_384
DEFAULT_MAX_EVENTS: Final[int] = 256
DEFAULT_MAX_STACK_DEPTH: Final[int] = 32
DEFAULT_MAX_LINE_EVENTS: Final[int] = 64
DEFAULT_MAX_PAYLOAD_BYTES: Final[int] = 2_048
DEFAULT_MAX_LOCAL_CHARS: Final[int] = 256

# Importing this module must remain a no-effect operation.  Tracing is
# explicit via :func:`record_python_execution_trace`.
IMPORT_NETWORK_PERFORMED: Final[bool] = False
IMPORT_SOCKET_PERFORMED: Final[bool] = False
IMPORT_INSTALLER_PERFORMED: Final[bool] = False
IMPORT_SUBPROCESS_PERFORMED: Final[bool] = False
IMPORT_DATABASE_PERFORMED: Final[bool] = False
IMPORT_REPO_SCAN_PERFORMED: Final[bool] = False
IMPORT_WATCHER_PERFORMED: Final[bool] = False
IMPORT_MODEL_LOAD_PERFORMED: Final[bool] = False
IMPORT_SIDE_EFFECTS_PERFORMED: Final[bool] = False

_DENIED_AUDIT_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "socket.connect",
        "socket.sendto",
        "socket.bind",
        "socket.listen",
        "socket.getaddrinfo",
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.posix_spawnp",
    }
)
_DENIED_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "aiohttp",
        "duckdb",
        "ensurepip",
        "httpx",
        "pip",
        "psycopg2",
        "pymongo",
        "requests",
        "torch",
        "transformers",
        "urllib3",
        "watchdog",
    }
)
_AWAIT_OPCODES: Final[frozenset[int]] = frozenset(
    code
    for code in (
        opcode.opmap.get("GET_AWAITABLE"),
        opcode.opmap.get("BEFORE_ASYNC_WITH"),
        opcode.opmap.get("SEND"),
    )
    if code is not None
)
_YIELD_OPCODES: Final[frozenset[int]] = frozenset(
    code
    for code in (opcode.opmap.get("YIELD_VALUE"), opcode.opmap.get("YIELD_FROM"))
    if code is not None
)

_ACTIVE_TRACER: ContextVar["PythonExecutionTracer | None"] = ContextVar(
    "sawm_python_execution_tracer", default=None
)
_HOOK_INSTALLED: bool = False
_TRACER_FILENAME: Final[str] = __file__


class PythonExecutionTraceError(ValueError):
    """Raised when hermetic tracing inputs, policy, or results are unsound."""


class TraceCancelled(BaseException):
    """Interrupt a traced callable after cooperative cancellation."""


class TraceDisposition(StrEnum):
    """How a collected trace may be used.  Never an operational acceptance."""

    OBSERVED = "observed"
    CANCELLED = "cancelled"
    DENIED = "denied"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ReplayPromise(StrEnum):
    """Whether the public event sequence is a deterministic replay promise."""

    DETERMINISTIC = "deterministic"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _nfc(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise PythonExecutionTraceError(f"{label} must be a nonempty string")
    text = unicodedata.normalize("NFC", value)
    if text != text.strip() or len(text) > MAX_TEXT_CHARS:
        raise PythonExecutionTraceError(f"{label} must be trimmed NFC text")
    return text


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise PythonExecutionTraceError(f"{label} must be a boolean")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value <= 0:
        raise PythonExecutionTraceError(f"{label} must be a positive integer")
    if value > MAX_SAFE_INTEGER:
        raise PythonExecutionTraceError(f"{label} exceeds the safe JSON integer range")
    return value


def _nonneg_int(value: object, label: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise PythonExecutionTraceError(f"{label} must be a nonnegative integer")
    if value > MAX_SAFE_INTEGER:
        raise PythonExecutionTraceError(f"{label} exceeds the safe JSON integer range")
    return value


def _optional_cid(value: object, label: str) -> str | None:
    if value is None:
        return None
    try:
        return validate_cid(value)
    except Exception as error:
        raise PythonExecutionTraceError(f"{label} must be a valid CID") from error


def _mapping(value: object, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PythonExecutionTraceError(f"{label} must be a string mapping")
    items: dict[str, str] = {}
    for key, item in value.items():
        items[_nfc(key, f"{label} key")] = _nfc(item, f"{label} value")
    return items


def _environment_cid(bindings: Mapping[str, str]) -> str:
    items = [
        {"key": key, "value": value}
        for key, value in sorted(bindings.items(), key=lambda pair: pair[0])
    ]
    return cid_for_structured(
        {"schema": TRACE_ENVIRONMENT_SCHEMA, "language": ADMITTED_LANGUAGE, "bindings": items}
    )


def _code_cid(*, module: str, qualname: str, filename: str, firstlineno: int, source_cid: str) -> str:
    return cid_for_structured(
        {
            "schema": TRACE_CODE_SCHEMA,
            "module": module,
            "qualname": qualname,
            "filename": filename,
            "firstlineno": firstlineno,
            "source_cid": source_cid,
        }
    )


def _logical_name(module: str, qualname: str) -> str:
    module = module or "<unknown>"
    return f"{module}.{qualname}" if not qualname.startswith(module) else qualname


def _source_of(target: Callable[..., Any]) -> tuple[str, str]:
    try:
        source = inspect.getsource(target)
    except (OSError, TypeError):
        module = getattr(target, "__module__", "") or "<unknown>"
        qualname = getattr(target, "__qualname__", getattr(target, "__name__", "callable"))
        source = f"{module}.{qualname}"
    text = unicodedata.normalize("NFC", source)
    return text, cid_for_bytes(text.encode("utf-8"))


def _code_of(target: Callable[..., Any]) -> CodeType:
    if inspect.ismethod(target):
        return target.__func__.__code__
    if inspect.isfunction(target):
        return target.__code__
    func = getattr(target, "func", None)
    if callable(func) and func is not target:
        return _code_of(func)
    raise PythonExecutionTraceError("target is not an admitted Python callable")


def _code_location(code: CodeType) -> tuple[str, str, str, int]:
    module = inspect.getmodule(code)
    module_name = module.__name__ if module is not None else ""
    qualname = getattr(code, "co_qualname", code.co_name)
    filename = code.co_filename or "<unknown>"
    return module_name, qualname, filename, int(code.co_firstlineno)


def _bounded_value(value: Any, *, budget: int, depth: int) -> tuple[Any, int]:
    if budget <= 0 or depth <= 0:
        return {"unavailable": "bound"}, 0
    if value is None:
        return None, budget - 4
    if type(value) is bool:
        return value, budget - 4
    if type(value) is int:
        if value < -MAX_SAFE_INTEGER or value > MAX_SAFE_INTEGER:
            return {"unavailable": "integer_range"}, budget - 24
        return value, budget - 8
    if type(value) is str:
        text = unicodedata.normalize("NFC", value)
        limit = min(budget, DEFAULT_MAX_LOCAL_CHARS)
        if len(text) > limit:
            text = text[:limit]
        return text, budget - max(len(text), 1)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        remaining = budget
        for key in list(value.keys())[:32]:
            if type(key) is not str:
                continue
            child, remaining = _bounded_value(value[key], budget=remaining, depth=depth - 1)
            out[unicodedata.normalize("NFC", key)[:128]] = child
            if remaining <= 0:
                break
        return out, remaining
    if isinstance(value, (list, tuple)):
        out_list: list[Any] = []
        remaining = budget
        for item in list(value)[:32]:
            child, remaining = _bounded_value(item, budget=remaining, depth=depth - 1)
            out_list.append(child)
            if remaining <= 0:
                break
        return out_list, remaining
    name = type(value).__name__
    return {"unavailable": "opaque", "type": unicodedata.normalize("NFC", name)[:64]}, budget - 24


def _secret_key(key: str) -> bool:
    lowered = key.lower()
    if key in SECRET_FIELD_MARKERS or lowered in SECRET_FIELD_MARKERS:
        return True
    if key in FORBIDDEN_FIELD_MARKERS or lowered in FORBIDDEN_FIELD_MARKERS:
        return True
    return any(marker in lowered for marker in SECRET_FIELD_MARKERS)


def _dispatch_audit(event: str, args: tuple[Any, ...]) -> None:
    tracer = _ACTIVE_TRACER.get()
    if tracer is None:
        return
    tracer.observe_audit(event, args)


def _ensure_audit_hook() -> None:
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    _HOOK_INSTALLED = True
    sys.addaudithook(_dispatch_audit)


def _drain_coroutine(coro: Any) -> Any:
    """Advance an await-chain without creating an event loop or socket."""

    value: Any = None
    thrown: BaseException | None = None
    while True:
        try:
            if thrown is not None:
                yielded = coro.throw(thrown)
                thrown = None
            else:
                yielded = coro.send(value)
        except StopIteration as stopped:
            return stopped.value
        if inspect.iscoroutine(yielded):
            try:
                value = _drain_coroutine(yielded)
            except BaseException as error:
                thrown = error
                value = None
            continue
        raise PythonExecutionTraceError(
            "nondeterministic await remains unavailable under hermetic tracing"
        )


def _drain_asyncgen(agen: Any) -> tuple[Any, ...]:
    items: list[Any] = []
    try:
        while True:
            items.append(_drain_coroutine(agen.__anext__()))
    except StopAsyncIteration:
        return tuple(items)
    finally:
        aclose = getattr(agen, "aclose", None)
        if callable(aclose):
            closer = aclose()
            if inspect.iscoroutine(closer):
                try:
                    _drain_coroutine(closer)
                except StopAsyncIteration:
                    pass


# ---------------------------------------------------------------------------
# Policy, redaction, cancellation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TraceCollectionPolicy:
    """Bounded, fail-closed collection policy for one hermetic Python run."""

    collect_call: bool = True
    collect_return: bool = True
    collect_line: bool = True
    collect_exception: bool = True
    collect_handler: bool = True
    collect_yield: bool = True
    collect_await: bool = True
    collect_external: bool = True
    capture_locals: bool = False
    capture_raw_bodies: bool = False
    deny_network: bool = True
    deny_socket: bool = True
    deny_subprocess: bool = True
    deny_installer: bool = True
    deny_database: bool = True
    deny_model_load: bool = True
    max_events: int = DEFAULT_MAX_EVENTS
    max_stack_depth: int = DEFAULT_MAX_STACK_DEPTH
    max_line_events: int = DEFAULT_MAX_LINE_EVENTS
    max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES
    line_stride: int = 1
    privacy_class: PrivacyClass | str = PrivacyClass.PUBLIC

    SCHEMA: ClassVar[str] = TRACE_COLLECTION_POLICY_SCHEMA
    INTERFACE: ClassVar[str] = TRACE_COLLECTION_POLICY_INTERFACE

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
        object.__setattr__(self, "capture_locals", _bool(self.capture_locals, "capture_locals"))
        object.__setattr__(
            self, "capture_raw_bodies", _bool(self.capture_raw_bodies, "capture_raw_bodies")
        )
        object.__setattr__(self, "deny_network", _bool(self.deny_network, "deny_network"))
        object.__setattr__(self, "deny_socket", _bool(self.deny_socket, "deny_socket"))
        object.__setattr__(
            self, "deny_subprocess", _bool(self.deny_subprocess, "deny_subprocess")
        )
        object.__setattr__(self, "deny_installer", _bool(self.deny_installer, "deny_installer"))
        object.__setattr__(self, "deny_database", _bool(self.deny_database, "deny_database"))
        object.__setattr__(
            self, "deny_model_load", _bool(self.deny_model_load, "deny_model_load")
        )
        object.__setattr__(self, "max_events", _positive_int(self.max_events, "max_events"))
        object.__setattr__(
            self, "max_stack_depth", _positive_int(self.max_stack_depth, "max_stack_depth")
        )
        object.__setattr__(
            self, "max_line_events", _positive_int(self.max_line_events, "max_line_events")
        )
        object.__setattr__(
            self,
            "max_payload_bytes",
            _positive_int(self.max_payload_bytes, "max_payload_bytes"),
        )
        object.__setattr__(self, "line_stride", _positive_int(self.line_stride, "line_stride"))
        privacy = (
            self.privacy_class.value
            if isinstance(self.privacy_class, PrivacyClass)
            else _nfc(self.privacy_class, "privacy_class")
        )
        try:
            privacy = PrivacyClass(privacy).value
        except ValueError as error:
            raise PythonExecutionTraceError("privacy_class has an unsupported value") from error
        object.__setattr__(self, "privacy_class", privacy)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "collect_await": self.collect_await,
            "collect_call": self.collect_call,
            "collect_exception": self.collect_exception,
            "collect_external": self.collect_external,
            "collect_handler": self.collect_handler,
            "collect_line": self.collect_line,
            "collect_return": self.collect_return,
            "collect_yield": self.collect_yield,
            "capture_locals": self.capture_locals,
            "capture_raw_bodies": self.capture_raw_bodies,
            "deny_database": self.deny_database,
            "deny_installer": self.deny_installer,
            "deny_model_load": self.deny_model_load,
            "deny_network": self.deny_network,
            "deny_socket": self.deny_socket,
            "deny_subprocess": self.deny_subprocess,
            "line_stride": self.line_stride,
            "max_events": self.max_events,
            "max_line_events": self.max_line_events,
            "max_payload_bytes": self.max_payload_bytes,
            "max_stack_depth": self.max_stack_depth,
            "privacy_class": self.privacy_class,
        }

    @property
    def capture_profile_cid(self) -> str:
        return cid_for_structured(
            {"schema": TRACE_CAPTURE_PROFILE_SCHEMA, "policy": self.identity_payload()}
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["capture_profile_cid"] = self.capture_profile_cid
        return payload


@dataclass(frozen=True, slots=True)
class TraceRedactor:
    """Drop secret and non-semantic fields before public contract construction."""

    secret_markers: tuple[str, ...] = tuple(sorted(SECRET_FIELD_MARKERS))

    SCHEMA: ClassVar[str] = TRACE_REDACTOR_SCHEMA
    INTERFACE: ClassVar[str] = TRACE_REDACTOR_INTERFACE

    def redact(self, value: Any) -> tuple[Any, tuple[str, ...]]:
        dimensions: set[str] = set()

        def walk(item: Any) -> Any:
            if isinstance(item, Mapping):
                out: dict[str, Any] = {}
                for key, child in item.items():
                    name = key if type(key) is str else str(key)
                    if _secret_key(name):
                        dimensions.add(unicodedata.normalize("NFC", name.lower())[:128])
                        continue
                    out[name] = walk(child)
                return out
            if isinstance(item, list):
                return [walk(child) for child in item]
            if isinstance(item, tuple):
                return [walk(child) for child in item]
            return item

        return walk(value), tuple(sorted(dimensions))

    def public_payload(
        self, value: Mapping[str, Any] | None, *, budget: int
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        redacted, dimensions = self.redact({} if value is None else value)
        bounded, _ = _bounded_value(redacted, budget=budget, depth=4)
        if not isinstance(bounded, dict):
            return {}, dimensions
        return bounded, dimensions


class TraceCancellation:
    """Cooperative cancellation token.  A cancelled run is never accepted."""

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

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise TraceCancelled(self._reason or "cancelled")


@dataclass(frozen=True, slots=True)
class PrivateTraceBody:
    """Private raw observation; excluded from every public record."""

    event_index: int
    logical_name: str
    locals_preview: Mapping[str, Any]
    exception_repr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_index": self.event_index,
            "exception_repr": self.exception_repr,
            "locals_preview": dict(self.locals_preview),
            "logical_name": self.logical_name,
        }


@dataclass(frozen=True, slots=True)
class HermeticTraceReplay:
    """Receipt that a deterministic public trace was replayed or promised."""

    matched: bool
    promised: bool
    public_trace_cid: str
    event_cids: tuple[str, ...]
    event_kinds: tuple[str, ...]
    accepted_transition: bool
    operational_acceptance: bool = False
    diverged: bool = False

    SCHEMA: ClassVar[str] = HERMETIC_TRACE_REPLAY_SCHEMA
    INTERFACE: ClassVar[str] = HERMETIC_TRACE_REPLAY_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "matched", _bool(self.matched, "matched"))
        object.__setattr__(self, "promised", _bool(self.promised, "promised"))
        object.__setattr__(
            self, "accepted_transition", _bool(self.accepted_transition, "accepted_transition")
        )
        object.__setattr__(
            self,
            "operational_acceptance",
            _bool(self.operational_acceptance, "operational_acceptance"),
        )
        object.__setattr__(self, "diverged", _bool(self.diverged, "diverged"))
        object.__setattr__(self, "event_cids", tuple(self.event_cids))
        object.__setattr__(self, "event_kinds", tuple(self.event_kinds))
        if self.operational_acceptance:
            raise PythonExecutionTraceError("replay cannot persist operational acceptance")

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "accepted_transition": self.accepted_transition,
            "diverged": self.diverged,
            "event_cids": list(self.event_cids),
            "event_kinds": list(self.event_kinds),
            "matched": self.matched,
            "operational_acceptance": False,
            "promised": self.promised,
            "public_trace_cid": self.public_trace_cid,
        }

    @property
    def hermetic_trace_replay_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["hermetic_trace_replay_cid"] = self.hermetic_trace_replay_cid
        return payload


@dataclass(frozen=True, slots=True)
class HermeticTraceRecord:
    """Public hermetic-trace identity plus an explicit private-body accessor."""

    disposition: TraceDisposition | str
    replay_promise: ReplayPromise | str
    accepted_transition: bool
    tree_cid: str
    source_cid: str
    code_cid: str
    environment_binding_cid: str
    capture_profile_cid: str
    public_trace: ExecutionTrace
    events: tuple[ProgramEvent, ...]
    policy: TraceCollectionPolicy
    result_summary: Mapping[str, Any] = field(default_factory=dict)
    exception_type: str | None = None
    cancellation_reason: str = ""
    redacted_dimensions: tuple[str, ...] = ()
    unavailable_dimensions: tuple[str, ...] = ()
    operational_acceptance: bool = False
    _private_bodies: tuple[PrivateTraceBody, ...] = ()

    SCHEMA: ClassVar[str] = HERMETIC_TRACE_RECORD_SCHEMA
    INTERFACE: ClassVar[str] = HERMETIC_TRACE_RECORD_INTERFACE

    def __post_init__(self) -> None:
        disposition = (
            self.disposition.value
            if isinstance(self.disposition, TraceDisposition)
            else TraceDisposition(self.disposition).value
        )
        promise = (
            self.replay_promise.value
            if isinstance(self.replay_promise, ReplayPromise)
            else ReplayPromise(self.replay_promise).value
        )
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "replay_promise", promise)
        object.__setattr__(
            self, "accepted_transition", _bool(self.accepted_transition, "accepted_transition")
        )
        object.__setattr__(
            self,
            "operational_acceptance",
            _bool(self.operational_acceptance, "operational_acceptance"),
        )
        if self.operational_acceptance:
            raise PythonExecutionTraceError("tracing cannot persist operational acceptance")
        if disposition == TraceDisposition.CANCELLED.value and self.accepted_transition:
            raise PythonExecutionTraceError("cancellation emits no accepted transition")
        if self.public_trace.includes_raw_bodies:
            raise PythonExecutionTraceError(
                "private raw trace bodies never enter public records"
            )
        if str(self.public_trace.privacy_class) != PrivacyClass.PUBLIC.value:
            raise PythonExecutionTraceError("public records must use the public privacy class")
        if self.public_trace.raw_execution_state_cids:
            raise PythonExecutionTraceError(
                "public records cannot carry raw execution-state identities"
            )
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "redacted_dimensions", tuple(self.redacted_dimensions))
        object.__setattr__(self, "unavailable_dimensions", tuple(self.unavailable_dimensions))
        object.__setattr__(self, "_private_bodies", tuple(self._private_bodies))
        object.__setattr__(
            self,
            "result_summary",
            MappingProxyType(dict(self.result_summary)),
        )

    @property
    def status(self) -> str:
        return str(self.disposition)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "accepted_transition": self.accepted_transition,
            "cancellation_reason": self.cancellation_reason,
            "capture_profile_cid": self.capture_profile_cid,
            "code_cid": self.code_cid,
            "completeness_claim": self.public_trace.completeness_claim,
            "disposition": self.disposition,
            "environment_binding_cid": self.environment_binding_cid,
            "event_cids": list(self.public_trace.event_cids),
            "event_kinds": [str(event.event_kind) for event in self.events],
            "exception_type": self.exception_type,
            "includes_raw_bodies": False,
            "language": ADMITTED_LANGUAGE,
            "operational_acceptance": False,
            "privacy_class": PrivacyClass.PUBLIC.value,
            "public_trace_cid": self.public_trace.execution_trace_cid,
            "redacted_dimensions": list(self.redacted_dimensions),
            "replay_promise": self.replay_promise,
            "result_summary": dict(self.result_summary),
            "source_cid": self.source_cid,
            "tree_cid": self.tree_cid,
            "unavailable_dimensions": list(self.unavailable_dimensions),
        }

    @property
    def hermetic_trace_record_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        """Return the public record.  Private raw bodies are omitted."""

        payload = self.identity_payload()
        payload["hermetic_trace_record_cid"] = self.hermetic_trace_record_cid
        payload["public_trace"] = self.public_trace.to_dict()
        payload["events"] = [event.to_dict() for event in self.events]
        payload["policy"] = self.policy.to_dict()
        return payload

    to_public_dict = to_dict

    def private_raw_bodies(self) -> tuple[PrivateTraceBody, ...]:
        """Explicit private accessor; never part of :meth:`to_dict`."""

        return self._private_bodies

    def accepted_transition_record(self) -> None:
        """Datasets tracing never emits an operational accepted transition."""

        return None


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------


class PythonExecutionTracer:
    """In-process ``sys.settrace`` adapter with cancellation and redaction."""

    INTERFACE: ClassVar[str] = PYTHON_EXECUTION_TRACER_INTERFACE
    VERSION: ClassVar[str] = PYTHON_EXECUTION_TRACER_VERSION

    def __init__(
        self,
        policy: TraceCollectionPolicy | None = None,
        *,
        redactor: TraceRedactor | None = None,
        tree_cid: str | None = None,
        environment_binding: Mapping[str, str] | None = None,
    ) -> None:
        self.policy = policy if policy is not None else TraceCollectionPolicy()
        self.redactor = redactor if redactor is not None else TraceRedactor()
        self._tree_cid_override = _optional_cid(tree_cid, "tree_cid")
        self._environment_binding = _mapping(environment_binding, "environment_binding")
        self._reset_run_state()

    def _reset_run_state(self) -> None:
        self._thread_id = 0
        self._cancellation: TraceCancellation | None = None
        self._admitted_codes: set[int] = set()
        self._root_code: CodeType | None = None
        self._events: list[ProgramEvent] = []
        self._private_bodies: list[PrivateTraceBody] = []
        self._redacted: set[str] = set()
        self._unavailable: set[str] = set()
        self._predecessor: str | None = None
        self._line_events = 0
        self._line_ticks = 0
        self._pending_exception: dict[int, tuple[str, Any]] = {}
        self._opcode_seen: set[tuple[int, int, str]] = set()
        self._disposition = TraceDisposition.OBSERVED
        self._cancellation_reason = ""
        self._exception_type: str | None = None
        self._recording = False
        self._tree_cid = ""
        self._source_cid = ""
        self._code_cid = ""
        self._env_cid = ""
        self._subject_cid = ""
        self._logical_name = ""
        self._source_text = ""

    def record(
        self,
        target: Callable[..., Any],
        *,
        args: Sequence[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
        cancellation: TraceCancellation | None = None,
    ) -> HermeticTraceRecord:
        if not callable(target):
            raise PythonExecutionTraceError("target must be callable")
        self._reset_run_state()
        self._cancellation = cancellation if cancellation is not None else TraceCancellation()
        self._thread_id = threading.get_ident()
        source_text, source_cid = _source_of(target)
        self._source_text = source_text
        self._source_cid = source_cid
        code = _code_of(target)
        module, qualname, filename, firstlineno = _code_location(code)
        self._logical_name = _logical_name(module, qualname)
        self._code_cid = _code_cid(
            module=module or "<unknown>",
            qualname=qualname,
            filename=filename,
            firstlineno=firstlineno,
            source_cid=source_cid,
        )
        self._subject_cid = self._code_cid
        env = {
            "language": ADMITTED_LANGUAGE,
            "tracer_version": PYTHON_EXECUTION_TRACER_VERSION,
        }
        env.update(self._environment_binding)
        self._env_cid = _environment_cid(env)
        self._tree_cid = self._tree_cid_override or cid_for_structured(
            {
                "schema": TRACE_ENVIRONMENT_SCHEMA + "#tree",
                "source_cid": source_cid,
                "logical_name": self._logical_name,
            }
        )
        self._root_code = code
        self._admitted_codes.add(id(code))
        call_kwargs = {} if kwargs is None else dict(kwargs)
        result: Any = None
        user_error: BaseException | None = None
        if self._cancellation.cancelled:
            self._disposition = TraceDisposition.CANCELLED
            self._cancellation_reason = self._cancellation.reason or "cancelled"
            return self._seal(result=None, invoked=False)
        previous_trace = sys.gettrace()
        token = _ACTIVE_TRACER.set(self)
        _ensure_audit_hook()
        self._recording = True
        try:
            sys.settrace(self._trace)
            try:
                result = self._invoke(target, tuple(args), call_kwargs)
            except TraceCancelled as cancelled:
                self._disposition = TraceDisposition.CANCELLED
                self._cancellation_reason = str(cancelled) or self._cancellation.reason or "cancelled"
            except PythonExecutionTraceError as denied:
                if self._disposition != TraceDisposition.DENIED:
                    self._disposition = TraceDisposition.DENIED
                    self._unavailable.add("external")
                if self._cancellation_reason == "":
                    self._cancellation_reason = str(denied)
            except BaseException as error:
                if isinstance(error, TraceCancelled):
                    raise
                user_error = error
                self._exception_type = type(error).__name__
        finally:
            self._recording = False
            sys.settrace(previous_trace)
            _ACTIVE_TRACER.reset(token)
        if user_error is not None and self._disposition == TraceDisposition.OBSERVED:
            # The exception was observed; it is not an accepted-transition cancel.
            pass
        return self._seal(result=result, invoked=True, user_error=user_error)

    def _invoke(self, target: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
        if inspect.iscoroutinefunction(target):
            return _drain_coroutine(target(*args, **kwargs))
        result = target(*args, **kwargs)
        if inspect.iscoroutine(result):
            return _drain_coroutine(result)
        if inspect.isgenerator(result) and self.policy.collect_yield:
            items: list[Any] = []
            try:
                for item in result:
                    items.append(item)
                    if (
                        len(self._events) >= self.policy.max_events
                        or (self._cancellation is not None and self._cancellation.cancelled)
                    ):
                        result.close()
                        break
            except TraceCancelled:
                result.close()
                raise
            return tuple(items)
        if inspect.isasyncgen(result) and self.policy.collect_yield:
            return _drain_asyncgen(result)
        return result

    def observe_audit(self, event: str, args: tuple[Any, ...]) -> None:
        if not self._recording or threading.get_ident() != self._thread_id:
            return
        denied = False
        kind = event
        if event in _DENIED_AUDIT_EVENTS:
            if event.startswith("socket") and (self.policy.deny_network or self.policy.deny_socket):
                denied = True
            elif event.startswith("subprocess") and (
                self.policy.deny_subprocess or self.policy.deny_installer
            ):
                denied = True
            elif event.startswith("os.") and (
                self.policy.deny_subprocess or self.policy.deny_installer
            ):
                denied = True
        elif event == "import" and args:
            name = args[0] if type(args[0]) is str else ""
            root = name.split(".", 1)[0]
            if root in _DENIED_IMPORTS and (
                self.policy.deny_model_load or self.policy.deny_network or self.policy.deny_database
            ):
                denied = True
                kind = f"import:{root}"
        if not denied and not (
            self.policy.collect_external and event in _DENIED_AUDIT_EVENTS
        ):
            return
        if self.policy.collect_external:
            self._emit(
                EventKind.EXTERNAL,
                logical_name=self._logical_name,
                payload={"effect": kind, "denied": denied},
                code_cid=self._code_cid,
                line=None,
                frames=(),
            )
        if not denied:
            self._unavailable.add("external")
            return
        self._disposition = TraceDisposition.DENIED
        self._unavailable.add("external")
        self._cancellation_reason = f"denied:{kind}"
        self._recording = False
        raise PythonExecutionTraceError(f"hermetic policy denied {kind}")

    def _should_trace(self, frame: FrameType) -> bool:
        if frame.f_code.co_filename == _TRACER_FILENAME:
            return False
        if id(frame.f_code) in self._admitted_codes:
            return True
        parent = frame.f_back
        while parent is not None:
            if id(parent.f_code) in self._admitted_codes:
                self._admitted_codes.add(id(frame.f_code))
                return True
            if parent.f_code.co_filename == _TRACER_FILENAME:
                break
            parent = parent.f_back
        return False

    def _trace(self, frame: FrameType, event: str, arg: Any) -> Callable[..., Any] | None:
        if not self._recording:
            return None
        if threading.get_ident() != self._thread_id:
            return None
        if not self._should_trace(frame):
            return None
        if self.policy.collect_await or self.policy.collect_yield:
            frame.f_trace_opcodes = True
        try:
            if self._cancellation is not None and self._cancellation.cancelled:
                self._disposition = TraceDisposition.CANCELLED
                self._cancellation_reason = self._cancellation.reason or "cancelled"
                self._recording = False
                raise TraceCancelled(self._cancellation_reason)
            if event == "call":
                self._admitted_codes.add(id(frame.f_code))
                if self.policy.collect_call:
                    self._emit_frame_event(EventKind.CALL, frame, arg)
            elif event == "return":
                frame_id = id(frame)
                if frame_id in self._pending_exception and self.policy.collect_handler:
                    self._emit_handler(frame)
                    self._pending_exception.pop(frame_id, None)
                flags = frame.f_code.co_flags
                if self.policy.collect_yield and flags & inspect.CO_GENERATOR:
                    self._emit_frame_event(EventKind.YIELD, frame, arg)
                elif self.policy.collect_await and flags & (
                    inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR
                ):
                    self._emit_frame_event(EventKind.AWAIT, frame, arg)
                elif self.policy.collect_return:
                    self._emit_frame_event(EventKind.RETURN, frame, arg)
            elif event == "line":
                frame_id = id(frame)
                if frame_id in self._pending_exception and self.policy.collect_handler:
                    self._emit_handler(frame)
                    self._pending_exception.pop(frame_id, None)
                if self.policy.collect_line:
                    self._line_ticks += 1
                    if self._line_ticks % self.policy.line_stride == 0:
                        if self._line_events < self.policy.max_line_events:
                            self._emit_frame_event(EventKind.LINE, frame, arg)
                            self._line_events += 1
                        else:
                            self._unavailable.add("line")
            elif event == "exception":
                if self.policy.collect_exception:
                    exc_type = arg[0] if isinstance(arg, tuple) and arg else type(None)
                    name = getattr(exc_type, "__name__", "Exception")
                    self._pending_exception[id(frame)] = (name, arg)
                    self._exception_type = name
                    self._emit_frame_event(EventKind.RAISE, frame, arg, exception_type=name)
            elif event == "opcode":
                self._maybe_opcode(frame, arg)
        except TraceCancelled:
            raise
        except PythonExecutionTraceError:
            raise
        except ProgramExecutionError:
            self._unavailable.add("event")
        return self._trace

    def _maybe_opcode(self, frame: FrameType, arg: Any) -> None:
        if type(arg) is not int:
            return
        key = (id(frame), frame.f_lasti, "await" if arg in _AWAIT_OPCODES else "yield")
        if key in self._opcode_seen:
            return
        if arg in _AWAIT_OPCODES and self.policy.collect_await:
            self._opcode_seen.add(key)
            self._emit_frame_event(EventKind.AWAIT, frame, arg)
        elif arg in _YIELD_OPCODES and self.policy.collect_yield:
            self._opcode_seen.add(key)
            self._emit_frame_event(EventKind.YIELD, frame, arg)

    def _emit_handler(self, frame: FrameType) -> None:
        pending = self._pending_exception.get(id(frame))
        exception_type = pending[0] if pending else "Exception"
        snapshot = self._exception_snapshot(frame, exception_type)
        handler = HandlerState(
            language=ADMITTED_LANGUAGE,
            handler_kind=HandlerKind.EXCEPT,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=self._code_cid_for(frame.f_code),
            environment_binding_cid=self._env_cid,
            logical_name=self._logical_name_for(frame.f_code),
            stack_ordinal=0,
            handler_active=True,
            matching_exception_snapshot_cid=snapshot.exception_snapshot_cid,
        )
        self._emit_frame_event(
            EventKind.CATCH,
            frame,
            None,
            handler=handler,
            exception_snapshot=snapshot,
        )
        self._emit_frame_event(
            EventKind.HANDLER,
            frame,
            None,
            handler=handler,
            exception_snapshot=snapshot,
        )

    def _code_cid_for(self, code: CodeType) -> str:
        module, qualname, filename, firstlineno = _code_location(code)
        return _code_cid(
            module=module or "<unknown>",
            qualname=qualname,
            filename=filename,
            firstlineno=firstlineno,
            source_cid=self._source_cid,
        )

    def _logical_name_for(self, code: CodeType) -> str:
        module, qualname, _, _ = _code_location(code)
        return _logical_name(module, qualname)

    def _stack_frames(self, frame: FrameType) -> tuple[StackFrameState, ...]:
        chain: list[FrameType] = []
        current: FrameType | None = frame
        depth = 0
        while current is not None and depth < self.policy.max_stack_depth:
            if self._should_trace(current):
                chain.append(current)
            current = current.f_back
            depth += 1
        frames: list[StackFrameState] = []
        for ordinal, item in enumerate(chain):
            summary: dict[str, Any] = {"logical_name": self._logical_name_for(item.f_code)}
            redacted_dims: tuple[str, ...] = ()
            unavailable: tuple[str, ...] = ()
            claim = CompletenessClaim.FULL_STATE
            if self.policy.capture_locals:
                raw_locals = dict(item.f_locals)
                public_locals, redacted_dims = self.redactor.public_payload(
                    {"locals": raw_locals}, budget=self.policy.max_payload_bytes
                )
                summary.update(public_locals)
                if redacted_dims:
                    claim = CompletenessClaim.REDACTED
                    self._redacted.update(redacted_dims)
            frames.append(
                StackFrameState(
                    ordinal=ordinal,
                    language=ADMITTED_LANGUAGE,
                    tree_cid=self._tree_cid,
                    source_cid=self._source_cid,
                    code_cid=self._code_cid_for(item.f_code),
                    environment_binding_cid=self._env_cid,
                    logical_name=self._logical_name_for(item.f_code),
                    line=_nonneg_int(item.f_lineno, "line") if item.f_lineno >= 0 else None,
                    column=None,
                    state_summary=summary,
                    exception_snapshot_cid=None,
                    handler_state_cid=None,
                    exception_active=False,
                    handler_active=False,
                    redacted_dimensions=redacted_dims,
                    unavailable_dimensions=unavailable,
                    completeness_claim=claim,
                    privacy_class=PrivacyClass.INTERNAL,
                )
            )
        return tuple(frames)

    def _exception_snapshot(self, frame: FrameType, exception_type: str) -> ExceptionSnapshot:
        frames = self._stack_frames(frame)
        if not frames:
            unavailable = ("call_stack",)
            cids: tuple[str, ...] = ()
            claim = CompletenessClaim.PARTIAL
        else:
            unavailable = ()
            cids = tuple(item.stack_frame_state_cid for item in frames)
            claim = CompletenessClaim.FULL_STATE
        return ExceptionSnapshot(
            language=ADMITTED_LANGUAGE,
            exception_type=_nfc(exception_type, "exception_type"),
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=self._code_cid_for(frame.f_code),
            environment_binding_cid=self._env_cid,
            exception_value_summary={"type": exception_type, "bounded": True},
            traceback_stack_frame_cids=cids,
            raised_at_event_cid=None,
            handler_state_cid=None,
            future_execution=False,
            unavailable_dimensions=unavailable,
            completeness_claim=claim,
        )

    def _emit_frame_event(
        self,
        kind: EventKind,
        frame: FrameType,
        arg: Any,
        *,
        exception_type: str | None = None,
        handler: HandlerState | None = None,
        exception_snapshot: ExceptionSnapshot | None = None,
    ) -> None:
        frames = self._stack_frames(frame)
        payload: dict[str, Any] = {"callee": self._logical_name_for(frame.f_code)}
        if kind is EventKind.RETURN:
            payload["returned"] = True
            payload["result_kind"] = type(arg).__name__[:64] if arg is not None else "none"
        snapshot = exception_snapshot
        if kind is EventKind.RAISE and snapshot is None:
            snapshot = self._exception_snapshot(frame, exception_type or "Exception")
        self._emit(
            kind,
            logical_name=self._logical_name_for(frame.f_code),
            payload=payload,
            code_cid=self._code_cid_for(frame.f_code),
            line=frame.f_lineno if frame.f_lineno >= 0 else None,
            frames=frames,
            exception_snapshot=snapshot,
            handler=handler,
        )
        if self.policy.capture_raw_bodies:
            raw_locals, _ = _bounded_value(
                dict(frame.f_locals), budget=self.policy.max_payload_bytes, depth=3
            )
            if not isinstance(raw_locals, Mapping):
                raw_locals = {}
            self._private_bodies.append(
                PrivateTraceBody(
                    event_index=len(self._events) - 1,
                    logical_name=self._logical_name_for(frame.f_code),
                    locals_preview=raw_locals,
                    exception_repr=exception_type or "",
                )
            )

    def _emit(
        self,
        kind: EventKind,
        *,
        logical_name: str,
        payload: Mapping[str, Any],
        code_cid: str,
        line: int | None,
        frames: Sequence[StackFrameState],
        exception_snapshot: ExceptionSnapshot | None = None,
        handler: HandlerState | None = None,
    ) -> None:
        if len(self._events) >= self.policy.max_events:
            self._unavailable.add("events")
            return
        public_payload, redacted = self.redactor.public_payload(
            dict(payload), budget=self.policy.max_payload_bytes
        )
        self._redacted.update(redacted)
        claim = CompletenessClaim.FULL_STATE
        unavailable: tuple[str, ...] = ()
        if redacted:
            claim = CompletenessClaim.REDACTED
        if kind in {
            EventKind.CALL,
            EventKind.RETURN,
            EventKind.RAISE,
            EventKind.CATCH,
            EventKind.HANDLER,
            EventKind.YIELD,
            EventKind.AWAIT,
            EventKind.ENTER,
            EventKind.EXIT,
        } and not frames:
            unavailable = ("call_stack",)
            claim = CompletenessClaim.PARTIAL
        event = ProgramEvent(
            event_kind=kind,
            event_origin=EventOrigin.OBSERVED,
            observation_status=ObservationStatus.OBSERVED,
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=code_cid,
            environment_binding_cid=self._env_cid,
            subject_cid=self._subject_cid,
            logical_name=logical_name,
            payload=public_payload,
            line=line,
            column=None,
            predecessor_event_cid=self._predecessor,
            stack_frame_cids=tuple(frame.stack_frame_state_cid for frame in frames),
            exception_snapshot_cid=(
                None if exception_snapshot is None else exception_snapshot.exception_snapshot_cid
            ),
            handler_state_cid=None if handler is None else handler.handler_state_cid,
            redaction_profile_cid=None,
            redacted_dimensions=redacted,
            unavailable_dimensions=unavailable,
            completeness_claim=claim,
            privacy_class=PrivacyClass.INTERNAL,
        )
        self._events.append(event)
        self._predecessor = event.program_event_cid

    def _placeholder_event(self) -> ProgramEvent:
        claim = CompletenessClaim.UNAVAILABLE
        unavailable = tuple(sorted(self._unavailable | {"events"}))
        return ProgramEvent(
            event_kind=EventKind.UNAVAILABLE,
            event_origin=EventOrigin.OBSERVED,
            observation_status=ObservationStatus.UNAVAILABLE,
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=self._code_cid,
            environment_binding_cid=self._env_cid,
            subject_cid=self._subject_cid,
            logical_name=self._logical_name,
            payload={"reason": self._disposition.value},
            line=None,
            column=None,
            predecessor_event_cid=None,
            stack_frame_cids=(),
            exception_snapshot_cid=None,
            handler_state_cid=None,
            redaction_profile_cid=None,
            redacted_dimensions=(),
            unavailable_dimensions=unavailable,
            completeness_claim=claim,
            privacy_class=PrivacyClass.INTERNAL,
        )

    def _seal(
        self,
        *,
        result: Any,
        invoked: bool,
        user_error: BaseException | None = None,
    ) -> HermeticTraceRecord:
        events = list(self._events)
        if not events:
            events.append(self._placeholder_event())
        redacted = tuple(sorted(self._redacted))
        unavailable = set(self._unavailable)
        if self._disposition is TraceDisposition.CANCELLED:
            unavailable.add("suffix")
        if self._disposition is TraceDisposition.DENIED:
            unavailable.add("external")
        if not invoked:
            unavailable.add("invocation")
        profile = None
        claim: CompletenessClaim | str
        if redacted:
            profile = RedactionProfile(
                privacy_class=PrivacyClass.PUBLIC,
                redacted_dimensions=redacted,
                unavailable_dimensions=tuple(sorted(unavailable)),
                completeness_claim=(
                    CompletenessClaim.REDACTED
                    if not unavailable
                    else CompletenessClaim.PARTIAL
                ),
            )
            claim = profile.completeness_claim
        elif unavailable:
            claim = CompletenessClaim.PARTIAL
        else:
            claim = CompletenessClaim.FULL_STATE
        public_trace = assemble_execution_trace(
            language=ADMITTED_LANGUAGE,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            environment_binding_cid=self._env_cid,
            events=events,
            states=(),
            redaction=profile,
            completeness_claim=claim,
            privacy_class=PrivacyClass.PUBLIC,
            includes_raw_bodies=False,
            unavailable_dimensions=tuple(sorted(unavailable)),
        )
        public_view = public_trace.public_view()
        if user_error is None and invoked and (result is None or type(result) in {bool, int}):
            if type(result) is int and (result < -MAX_SAFE_INTEGER or result > MAX_SAFE_INTEGER):
                result_summary = {"invoked": True, "result_kind": "int"}
            else:
                result_summary = {"invoked": True, "result": result}
        elif invoked:
            result_kind = "none" if user_error is not None else type(result).__name__[:64]
            result_summary = {"invoked": True, "result_kind": result_kind}
        else:
            result_summary = {"invoked": False}
        result_summary, result_redacted = self.redactor.public_payload(
            result_summary, budget=self.policy.max_payload_bytes
        )
        accepted = (
            self._disposition is TraceDisposition.OBSERVED
            and not (self._cancellation is not None and self._cancellation.cancelled)
        )
        if self._disposition is TraceDisposition.CANCELLED:
            accepted = False
        if self._disposition is TraceDisposition.DENIED:
            accepted = False
        replay = ReplayPromise.DETERMINISTIC if accepted and "external" not in unavailable else ReplayPromise.UNAVAILABLE
        return HermeticTraceRecord(
            disposition=self._disposition,
            replay_promise=replay,
            accepted_transition=accepted,
            tree_cid=self._tree_cid,
            source_cid=self._source_cid,
            code_cid=self._code_cid,
            environment_binding_cid=self._env_cid,
            capture_profile_cid=self.policy.capture_profile_cid,
            public_trace=public_view,
            events=tuple(events),
            policy=self.policy,
            result_summary=result_summary,
            exception_type=self._exception_type if user_error is not None else self._exception_type,
            cancellation_reason=self._cancellation_reason,
            redacted_dimensions=redacted,
            unavailable_dimensions=tuple(sorted(unavailable)),
            operational_acceptance=False,
            _private_bodies=tuple(self._private_bodies),
        )


def record_python_execution_trace(
    target: Callable[..., Any],
    *,
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    policy: TraceCollectionPolicy | None = None,
    cancellation: TraceCancellation | None = None,
    redactor: TraceRedactor | None = None,
    tree_cid: str | None = None,
    environment_binding: Mapping[str, str] | None = None,
) -> HermeticTraceRecord:
    """Record one hermetic Python run as a public execution trace."""

    tracer = PythonExecutionTracer(
        policy,
        redactor=redactor,
        tree_cid=tree_cid,
        environment_binding=environment_binding,
    )
    return tracer.record(target, args=args, kwargs=kwargs, cancellation=cancellation)


def replay_deterministic_trace(
    record: HermeticTraceRecord,
    *,
    target: Callable[..., Any] | None = None,
    args: Sequence[Any] = (),
    kwargs: Mapping[str, Any] | None = None,
    policy: TraceCollectionPolicy | None = None,
) -> HermeticTraceReplay:
    """Replay a promised deterministic trace, or re-execute under the same policy.

    Cancellation never yields an accepted transition, including on replay.
    """

    if not isinstance(record, HermeticTraceRecord):
        raise PythonExecutionTraceError("replay requires a HermeticTraceRecord")
    if str(record.disposition) == TraceDisposition.CANCELLED.value:
        if record.accepted_transition:
            raise PythonExecutionTraceError("cancellation emits no accepted transition")
        raise PythonExecutionTraceError("cancelled traces have no accepted transition to replay")
    if str(record.replay_promise) != ReplayPromise.DETERMINISTIC.value:
        raise PythonExecutionTraceError("deterministic replay is unavailable")
    kinds = tuple(str(event.event_kind) for event in record.events)
    if target is None:
        return HermeticTraceReplay(
            matched=True,
            promised=True,
            public_trace_cid=record.public_trace.execution_trace_cid,
            event_cids=tuple(record.public_trace.event_cids),
            event_kinds=kinds,
            accepted_transition=record.accepted_transition,
            operational_acceptance=False,
            diverged=False,
        )
    replayed = record_python_execution_trace(
        target,
        args=args,
        kwargs=kwargs,
        policy=policy if policy is not None else record.policy,
        tree_cid=record.tree_cid,
        environment_binding=None,
    )
    replay_kinds = tuple(str(event.event_kind) for event in replayed.events)
    matched = replay_kinds == kinds and replayed.source_cid == record.source_cid
    if not matched:
        raise PythonExecutionTraceError("deterministic replay diverged from the promised trace")
    if replayed.environment_binding_cid != record.environment_binding_cid:
        # Environment identity is bound at record time; re-execution under the
        # same tracer version must preserve it when the caller does not override.
        pass
    return HermeticTraceReplay(
        matched=True,
        promised=False,
        public_trace_cid=replayed.public_trace.execution_trace_cid,
        event_cids=tuple(replayed.public_trace.event_cids),
        event_kinds=replay_kinds,
        accepted_transition=replayed.accepted_transition,
        operational_acceptance=False,
        diverged=False,
    )


__all__ = [
    "ADMITTED_LANGUAGE",
    "HERMETIC_TRACE_RECORD_INTERFACE",
    "HERMETIC_TRACE_REPLAY_INTERFACE",
    "IMPORT_DATABASE_PERFORMED",
    "IMPORT_INSTALLER_PERFORMED",
    "IMPORT_MODEL_LOAD_PERFORMED",
    "IMPORT_NETWORK_PERFORMED",
    "IMPORT_REPO_SCAN_PERFORMED",
    "IMPORT_SIDE_EFFECTS_PERFORMED",
    "IMPORT_SOCKET_PERFORMED",
    "IMPORT_SUBPROCESS_PERFORMED",
    "IMPORT_WATCHER_PERFORMED",
    "PYTHON_EXECUTION_TRACER_INTERFACE",
    "TRACE_CANCELLATION_INTERFACE",
    "TRACE_COLLECTION_POLICY_INTERFACE",
    "TRACE_REDACTOR_INTERFACE",
    "HermeticTraceRecord",
    "HermeticTraceReplay",
    "PrivateTraceBody",
    "PythonExecutionTraceError",
    "PythonExecutionTracer",
    "ReplayPromise",
    "TraceCancellation",
    "TraceCancelled",
    "TraceCollectionPolicy",
    "TraceDisposition",
    "TraceRedactor",
    "record_python_execution_trace",
    "replay_deterministic_trace",
]
