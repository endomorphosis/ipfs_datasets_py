"""
Standardized JSON Log Schema (Session 83, P2-obs) + DQK-079 file-sink guards.

Provides unified, structured logging across all MCP++ components with:
- Consistent field names and types
- Hierarchical context propagation
- Correlation IDs for request tracing
- Performance metrics integration
- Error classification and severity levels

DQK-079: after canary acceptance, implicit JSON/JSONL/file-handler/
metric-snapshot/alert-state authorities are disabled. Only explicit
deterministic exports and ephemeral human-readable console logs remain.
Static and dynamic writer guards reject undeclared mutable file sinks.
Console lines never satisfy progress or completion authority. Publication
views are sanitized (secrets + high-cardinality private payloads removed).

Usage:
    from ipfs_datasets_py.logic.observability.structured_logging import (
        get_logger,
        LogContext,
        log_event,
        log_error,
        log_performance,
        get_observability_filesystem_guard,
        sanitize_publication_view,
    )
    
    logger = get_logger("my_component")
    
    with LogContext(request_id="req-123", user_id="user-456"):
        logger.info("Processing request", extra={"item_count": 10})
        log_event("item_processed", item_id="abc", status="success")
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Union,
)


# ---------------------------------------------------------------------------
# Log Schema Version / DQK-079 pins
# ---------------------------------------------------------------------------

LOG_SCHEMA_VERSION = "1.0.0"
OBSERVABILITY_FILE_SINK_OWNER_TASK = "DQK-079"
OBSERVABILITY_PUBLICATION_SCHEMA = (
    "ipfs_datasets_py/duckdb-observability-publication-view@1"
)
_REDACTION_MARKER = "***REDACTED***"
_MAX_PUBLICATION_ATTR_KEYS = 32
_MAX_PUBLICATION_STRING_BYTES = 512
_MAX_PUBLICATION_LIST_ITEMS = 16

# High-cardinality / private payload keys stripped from publication views.
_HIGH_CARDINALITY_KEYS = frozenset(
    {
        "raw_payload",
        "raw",
        "payload",
        "body",
        "sql",
        "query",
        "query_text",
        "unrestricted_sql",
        "stack",
        "stack_trace",
        "traceback",
        "exception_traceback",
        "embeddings",
        "vectors",
        "tokens",
        "token_ids",
        "chunk_text",
        "full_text",
        "document_text",
        "messages",
        "message_history",
        "event_history",
        "per_row",
        "rows",
        "samples",
        "sample_ids",
        "user_ids",
        "ip_addresses",
        "client_ips",
        "session_ids",
        "request_bodies",
        "response_bodies",
    }
)

_SECRET_KEY_RE = re.compile(
    r"(?i)^(password|passwd|pwd|secret|token|api[_-]?key|authorization|"
    r"private[_-]?key|mnemonic|seed|signing|credential|bearer|"
    r"access[_-]?key|secret[_-]?key|auth[_-]?header)$"
)

# Filenames / suffixes that are treated as mutable observability file sinks.
_GUARDED_EXACT_NAMES = frozenset(
    {
        "mcp_server.log",
        "alert-state.json",
        "alert_state.json",
        "alerts_state.json",
        "metric-snapshot.json",
        "metrics_snapshot.json",
        "metrics-snapshot.json",
        "audit_log.json",
        "audit_log.jsonl",
        "audit.json",
        "audit.jsonl",
    }
)
_GUARDED_NAME_PREFIXES = (
    "audit_",
    "metric-snapshot",
    "metrics_snapshot",
    "metrics-snapshot",
    "alert-state",
    "alert_state",
    "pipeline_",
)
_GUARDED_SUFFIXES = (
    ".audit.json",
    ".audit.jsonl",
    "_audit.json",
    "_audit.jsonl",
    "_metrics.json",
    "_metrics.jsonl",
    "_metric_snapshot.json",
)

_process_guard_lock = threading.RLock()
_process_filesystem_guard: Optional["ObservabilityFilesystemGuard"] = None


# ---------------------------------------------------------------------------
# DQK-079: mutable file-sink writer guards + sanitized publication views
# ---------------------------------------------------------------------------


class ObservabilityMutableFileSinkError(RuntimeError):
    """Raised when an undeclared mutable observability file sink is blocked."""

    def __init__(
        self,
        message: str,
        *,
        path: str = "",
        kind: str = "",
        operation: str = "write",
    ) -> None:
        super().__init__(message)
        self.path = path
        self.kind = kind
        self.operation = operation
        self.owner_task = OBSERVABILITY_FILE_SINK_OWNER_TASK


class ObservabilityFilesystemGuard:
    """Blocks implicit JSON/JSONL/file-handler/metric/alert-state sinks (DQK-079).

    After canary acceptance the default is fail-closed: only ephemeral console
    logs and *explicit* deterministic exports (via :meth:`permit_export`) may
    touch guarded paths. Console projections never grant progress or
    completion authority.
    """

    def __init__(self, *, allow_legacy_file_sinks: bool = False) -> None:
        self._lock = threading.RLock()
        self._export_permits: int = 0
        self._import_permits: int = 0
        self._allow_legacy_file_sinks: bool = bool(allow_legacy_file_sinks)

    @property
    def allow_legacy_file_sinks(self) -> bool:
        with self._lock:
            return self._allow_legacy_file_sinks

    @allow_legacy_file_sinks.setter
    def allow_legacy_file_sinks(self, value: bool) -> None:
        with self._lock:
            self._allow_legacy_file_sinks = bool(value)

    @contextmanager
    def permit_export(self) -> Iterator[None]:
        """Allow one explicit deterministic export of a guarded sink."""

        with self._lock:
            self._export_permits += 1
        try:
            yield
        finally:
            with self._lock:
                self._export_permits = max(0, self._export_permits - 1)

    @contextmanager
    def permit_import(self) -> Iterator[None]:
        """Allow one explicit one-time import of a guarded sink."""

        with self._lock:
            self._import_permits += 1
        try:
            yield
        finally:
            with self._lock:
                self._import_permits = max(0, self._import_permits - 1)

    def _has_permit(self) -> bool:
        with self._lock:
            return self._export_permits > 0 or self._import_permits > 0

    @staticmethod
    def classify_path(path: Union[Path, str]) -> Optional[str]:
        """Return the guarded sink kind for *path*, or ``None`` if unguarded."""

        p = Path(path)
        name = p.name
        lower = name.lower()

        if lower in _GUARDED_EXACT_NAMES:
            if lower == "mcp_server.log":
                return "mcp_log"
            if "alert" in lower and lower.endswith(".json"):
                return "alert_state"
            if "metric" in lower:
                return "metric_snapshot"
            if lower.endswith(".jsonl"):
                return "audit_jsonl"
            return "audit_json"

        if lower.endswith(".jsonl"):
            if lower.startswith("audit") or ".audit." in lower or lower.endswith("_audit.jsonl"):
                return "audit_jsonl"
            if "metric" in lower or "pipeline" in lower:
                return "metric_snapshot" if "metric" in lower else "pipeline_jsonl"
            if lower.startswith(_GUARDED_NAME_PREFIXES) or any(
                lower.endswith(s) for s in _GUARDED_SUFFIXES if s.endswith(".jsonl")
            ):
                return "jsonl_sink"
            # Generic JSONL under known observability directory names.
            parent = p.parent.name.lower()
            if parent in {
                "audit",
                "audit_logs",
                "logs",
                "metrics",
                "observability",
                "alerts",
            }:
                return "jsonl_sink"

        if lower.endswith(".json"):
            if lower.startswith("audit") or ".audit." in lower or lower.endswith("_audit.json"):
                return "audit_json"
            if "metric-snapshot" in lower or "metrics_snapshot" in lower or "metric_snapshot" in lower:
                return "metric_snapshot"
            if "alert-state" in lower or "alert_state" in lower or lower == "alerts_state.json":
                return "alert_state"
            if lower.startswith("metric") and "snapshot" in lower:
                return "metric_snapshot"

        if lower.endswith(".log") and (
            "audit" in lower or "mcp" in lower or "pipeline" in lower
        ):
            return "ad_hoc_file_handler"

        for prefix in _GUARDED_NAME_PREFIXES:
            if lower.startswith(prefix) and (
                lower.endswith(".json") or lower.endswith(".jsonl") or lower.endswith(".log")
            ):
                if "alert" in prefix:
                    return "alert_state"
                if "metric" in prefix:
                    return "metric_snapshot"
                if "pipeline" in prefix:
                    return "pipeline_jsonl" if lower.endswith(".jsonl") else "pipeline_json"
                return "audit_jsonl" if lower.endswith(".jsonl") else "audit_json"

        for suffix in _GUARDED_SUFFIXES:
            if lower.endswith(suffix):
                return "audit_jsonl" if suffix.endswith(".jsonl") else "audit_json"

        return None

    def is_guarded_path(self, path: Union[Path, str]) -> bool:
        return self.classify_path(path) is not None

    def is_mutable_file_handler(self, handler: Any) -> bool:
        """True when *handler* is an ad-hoc logging FileHandler-like sink."""

        if handler is None:
            return False
        cls_name = type(handler).__name__
        if cls_name in {"FileHandler", "RotatingFileHandler", "TimedRotatingFileHandler", "WatchedFileHandler"}:
            return True
        # Project audit handlers that write durable files.
        if cls_name in {"FileAuditHandler", "JSONAuditHandler"}:
            return True
        base_names = {base.__name__ for base in type(handler).__mro__}
        if "FileHandler" in base_names:
            return True
        if hasattr(handler, "file_path") or hasattr(handler, "baseFilename"):
            # StreamHandler and NullHandler do not expose these.
            if cls_name not in {"StreamHandler", "NullHandler", "MemoryHandler"}:
                return True
        return False

    def classify_handler(self, handler: Any) -> Optional[str]:
        if not self.is_mutable_file_handler(handler):
            return None
        path = getattr(handler, "baseFilename", None) or getattr(handler, "file_path", None)
        if path:
            return self.classify_path(path) or "ad_hoc_file_handler"
        return "ad_hoc_file_handler"

    def assert_allowed(
        self,
        path: Union[Path, str, None] = None,
        *,
        kind: Optional[str] = None,
        operation: str = "write",
        handler: Any = None,
    ) -> None:
        """Fail closed when a mutable file sink is blocked without a permit."""

        classified = kind
        if classified is None and path is not None:
            classified = self.classify_path(path)
        if classified is None and handler is not None:
            classified = self.classify_handler(handler)
        if classified is None:
            return
        with self._lock:
            allowed = self._allow_legacy_file_sinks or self._has_permit()
        if allowed:
            return
        target = str(path) if path is not None else (
            str(getattr(handler, "baseFilename", None) or getattr(handler, "file_path", "") or "<handler>")
        )
        raise ObservabilityMutableFileSinkError(
            f"implicit {operation} of undeclared mutable file sink "
            f"{classified!r} blocked after DuckDB observability cutover: "
            f"{target} (use explicit deterministic export; "
            f"owner_task={OBSERVABILITY_FILE_SINK_OWNER_TASK})",
            path=target,
            kind=classified,
            operation=operation,
        )

    def check_path_write(self, path: Union[Path, str], *, kind: str = "") -> None:
        self.assert_allowed(path, kind=kind or None, operation="write")

    def check_handler(self, handler: Any, *, operation: str = "attach") -> None:
        self.assert_allowed(handler=handler, operation=operation)

    def check_path_read(self, path: Union[Path, str], *, kind: str = "") -> None:
        self.assert_allowed(path, kind=kind or None, operation="read")


def get_observability_filesystem_guard() -> ObservabilityFilesystemGuard:
    """Return the process-local observability mutable-file-sink guard."""

    global _process_filesystem_guard
    with _process_guard_lock:
        if _process_filesystem_guard is None:
            # DQK-079 default: deny legacy mutable file sinks.
            _process_filesystem_guard = ObservabilityFilesystemGuard(
                allow_legacy_file_sinks=False
            )
        return _process_filesystem_guard


def reset_observability_filesystem_guard() -> None:
    """Drop the process-local filesystem guard (tests)."""

    global _process_filesystem_guard
    with _process_guard_lock:
        _process_filesystem_guard = None


def set_allow_legacy_observability_file_sinks(allowed: bool) -> None:
    """Enable/disable legacy mutable file sinks (migration / tests only)."""

    get_observability_filesystem_guard().allow_legacy_file_sinks = bool(allowed)


def mutable_observability_file_sinks_allowed() -> bool:
    """True when legacy file sinks or an explicit export/import permit is active."""

    guard = get_observability_filesystem_guard()
    return guard.allow_legacy_file_sinks or guard._has_permit()  # noqa: SLF001


def assert_mutable_file_sink_allowed(
    path: Union[Path, str, None] = None,
    *,
    kind: Optional[str] = None,
    operation: str = "write",
    handler: Any = None,
) -> None:
    """Raise :class:`ObservabilityMutableFileSinkError` if the sink is blocked."""

    get_observability_filesystem_guard().assert_allowed(
        path, kind=kind, operation=operation, handler=handler
    )


def console_grants_progress_authority() -> bool:
    """Console / stderr projections never answer progress queries (DQK-079)."""

    return False


def console_grants_completion_authority() -> bool:
    """Console / stderr projections never answer completion queries (DQK-079)."""

    return False


def console_is_authority() -> bool:
    """Disposable console logs are never an observability authority."""

    return False


def _looks_like_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.fullmatch(str(key).strip()))


def _truncate_public_string(value: str) -> str:
    raw = value.encode("utf-8", errors="replace")
    if len(raw) <= _MAX_PUBLICATION_STRING_BYTES:
        return value
    return raw[:_MAX_PUBLICATION_STRING_BYTES].decode("utf-8", errors="ignore") + "…"


def sanitize_publication_view(
    payload: Mapping[str, Any] | None,
    *,
    max_keys: int = _MAX_PUBLICATION_ATTR_KEYS,
) -> Dict[str, Any]:
    """Return a publication-safe view excluding secrets and high-cardinality data.

    Uses the DQK-077 redaction helpers when available, then strips high-
    cardinality private payload keys and bounds string/list sizes.
    """

    if not payload:
        return {
            "schema": OBSERVABILITY_PUBLICATION_SCHEMA,
            "owner_task": OBSERVABILITY_FILE_SINK_OWNER_TASK,
            "sanitized": True,
            "attributes": {},
        }

    # Prefer shared redaction from the observability adapters when importable.
    redacted: Dict[str, Any]
    try:
        from ipfs_datasets_py.duckdb_control.observability_adapters import (
            redact_event_payload,
        )

        redacted, _klass = redact_event_payload(dict(payload))
    except Exception:
        redacted = {}
        for key, value in dict(payload).items():
            if _looks_like_secret_key(str(key)):
                redacted[str(key)] = _REDACTION_MARKER
            else:
                redacted[str(key)] = value

    cleaned: Dict[str, Any] = {}
    for key, value in redacted.items():
        name = str(key)
        lower = name.lower()
        if lower in _HIGH_CARDINALITY_KEYS or name in _HIGH_CARDINALITY_KEYS:
            continue
        if _looks_like_secret_key(name):
            cleaned[name] = _REDACTION_MARKER
            continue
        if isinstance(value, str):
            cleaned[name] = _truncate_public_string(value)
        elif isinstance(value, Mapping):
            nested = sanitize_publication_view(value, max_keys=max_keys)
            cleaned[name] = nested.get("attributes", nested)
        elif isinstance(value, (list, tuple)):
            items = list(value)[:_MAX_PUBLICATION_LIST_ITEMS]
            bounded: List[Any] = []
            for item in items:
                if isinstance(item, Mapping):
                    nested = sanitize_publication_view(item, max_keys=max_keys)
                    bounded.append(nested.get("attributes", nested))
                elif isinstance(item, str):
                    bounded.append(_truncate_public_string(item))
                elif isinstance(item, (int, float, bool)) or item is None:
                    bounded.append(item)
                else:
                    bounded.append(_truncate_public_string(str(item)))
            cleaned[name] = bounded
        elif isinstance(value, (int, float, bool)) or value is None:
            cleaned[name] = value
        else:
            cleaned[name] = _truncate_public_string(str(value))
        if len(cleaned) >= max_keys:
            break

    return {
        "schema": OBSERVABILITY_PUBLICATION_SCHEMA,
        "owner_task": OBSERVABILITY_FILE_SINK_OWNER_TASK,
        "sanitized": True,
        "console_is_authority": False,
        "console_grants_progress_authority": False,
        "console_grants_completion_authority": False,
        "attributes": cleaned,
    }


def build_observability_publication_view(
    records: Sequence[Mapping[str, Any]] | None = None,
    *,
    extra: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a sanitized multi-record publication view for Quack consumers."""

    safe_records: List[Dict[str, Any]] = []
    for row in list(records or [])[:_MAX_PUBLICATION_LIST_ITEMS]:
        view = sanitize_publication_view(row)
        safe_records.append(view.get("attributes", {}))
    envelope = sanitize_publication_view(extra or {})
    return {
        "schema": OBSERVABILITY_PUBLICATION_SCHEMA,
        "owner_task": OBSERVABILITY_FILE_SINK_OWNER_TASK,
        "sanitized": True,
        "console_is_authority": False,
        "console_grants_progress_authority": console_grants_progress_authority(),
        "console_grants_completion_authority": console_grants_completion_authority(),
        "record_count": len(safe_records),
        "records": safe_records,
        "attributes": envelope.get("attributes", {}),
    }


# ---------------------------------------------------------------------------
# Standard Field Names
# ---------------------------------------------------------------------------

class LogField(str, Enum):
    """Standard field names for structured logs.
    
    Ensures consistency across all MCP++ components.
    """
    
    # Metadata
    TIMESTAMP = "timestamp"
    SCHEMA_VERSION = "schema_version"
    LEVEL = "level"
    LOGGER_NAME = "logger"
    
    # Context
    REQUEST_ID = "request_id"
    SESSION_ID = "session_id"
    USER_ID = "user_id"
    COMPONENT = "component"
    FUNCTION = "function"
    
    # Event
    EVENT_TYPE = "event_type"
    MESSAGE = "message"
    
    # Error
    ERROR_TYPE = "error_type"
    ERROR_MESSAGE = "error_message"
    ERROR_STACK = "error_stack"
    ERROR_CODE = "error_code"
    
    # Performance
    DURATION_MS = "duration_ms"
    CPU_TIME_MS = "cpu_time_ms"
    MEMORY_MB = "memory_mb"
    
    # MCP++ Specific
    TOOL_NAME = "tool_name"
    INTENT_CID = "intent_cid"
    DECISION_CID = "decision_cid"
    RECEIPT_CID = "receipt_cid"
    POLICY_NAME = "policy_name"
    COMPLIANCE_STATUS = "compliance_status"


class EventType(str, Enum):
    """Standard event types for categorization and filtering."""
    
    # Lifecycle
    SYSTEM_START = "system.start"
    SYSTEM_STOP = "system.stop"
    COMPONENT_INIT = "component.init"
    COMPONENT_SHUTDOWN = "component.shutdown"
    
    # MCP++ Operations
    TOOL_INVOKED = "mcp.tool.invoked"
    TOOL_COMPLETED = "mcp.tool.completed"
    TOOL_FAILED = "mcp.tool.failed"
    POLICY_EVALUATED = "mcp.policy.evaluated"
    COMPLIANCE_CHECKED = "mcp.compliance.checked"
    
    # GraphRAG Operations
    ENTITY_EXTRACTED = "graphrag.entity.extracted"
    ENTITY_DEDUPLICATED = "graphrag.entity.deduplicated"
    GRAPH_TRAVERSED = "graphrag.graph.traversed"
    QUERY_EXECUTED = "graphrag.query.executed"
    
    # Error Events
    ERROR_OCCURRED = "error.occurred"
    ERROR_RECOVERED = "error.recovered"
    CIRCUIT_BREAKER_OPENED = "circuit_breaker.opened"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker.closed"
    
    # Custom
    CUSTOM = "custom"


# ---------------------------------------------------------------------------
# Context Propagation
# ---------------------------------------------------------------------------

# Thread-local context storage using contextvars
_log_context: ContextVar[Dict[str, Any]] = ContextVar("log_context", default={})


@dataclass
class LogContext:
    """Context manager for propagating structured context through log calls.
    
    Usage:
        with LogContext(request_id="req-123", session_id="sess-456"):
            logger.info("Processing")  # Automatically includes request_id, session_id
            
            with LogContext(tool_name="ipfs_add"):
                logger.info("Tool invoked")  # Includes request_id, session_id, tool_name
    """
    
    context: Dict[str, Any] = field(default_factory=dict)
    _previous_context: Optional[Dict[str, Any]] = field(default=None, init=False, repr=False)
    
    def __init__(self, **kwargs: Any):
        self.context = kwargs
    
    def __enter__(self) -> "LogContext":
        # Save previous context
        self._previous_context = _log_context.get().copy()
        
        # Merge new context with existing
        merged = self._previous_context.copy()
        merged.update(self.context)
        _log_context.set(merged)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Restore previous context
        _log_context.set(self._previous_context)


def get_current_context() -> Dict[str, Any]:
    """Get current logging context (thread-safe)."""
    return _log_context.get().copy()


def set_context(**kwargs: Any) -> None:
    """Set context values without using context manager."""
    current = _log_context.get().copy()
    current.update(kwargs)
    _log_context.set(current)


def clear_context() -> None:
    """Clear all context values."""
    _log_context.set({})


# ---------------------------------------------------------------------------
# Structured Log Formatter
# ---------------------------------------------------------------------------

class JSONLogFormatter(logging.Formatter):
    """Custom formatter that outputs structured JSON logs.
    
    Each log record is formatted as a JSON object with standard fields plus
    any extra fields provided via the `extra` parameter.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # Base log entry
        log_entry: Dict[str, Any] = {
            LogField.TIMESTAMP.value: self.formatTime(record),
            LogField.SCHEMA_VERSION.value: LOG_SCHEMA_VERSION,
            LogField.LEVEL.value: record.levelname,
            LogField.LOGGER_NAME.value: record.name,
            LogField.MESSAGE.value: record.getMessage(),
        }
        
        # Add context
        context = get_current_context()
        if context:
            log_entry.update(context)
        
        # Add function location
        if record.funcName:
            log_entry[LogField.FUNCTION.value] = record.funcName
        if record.module:
            log_entry[LogField.COMPONENT.value] = record.module
        
        # Add exception info if present
        if record.exc_info:
            log_entry[LogField.ERROR_TYPE.value] = record.exc_info[0].__name__ if record.exc_info[0] else None
            log_entry[LogField.ERROR_MESSAGE.value] = str(record.exc_info[1]) if record.exc_info[1] else None
            log_entry[LogField.ERROR_STACK.value] = self.formatException(record.exc_info)
        
        # Add any extra fields from `extra=` parameter
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if (key not in log_entry and 
                    not key.startswith("_") and 
                    key not in ["name", "msg", "args", "created", "filename", "funcName",
                                "levelname", "levelno", "lineno", "module", "msecs",
                                "message", "pathname", "process", "processName",
                                "relativeCreated", "thread", "threadName", "exc_info",
                                "exc_text", "stack_info"]):
                    log_entry[key] = value
        
        return json.dumps(log_entry, default=str)


# ---------------------------------------------------------------------------
# Logger Setup
# ---------------------------------------------------------------------------

def get_logger(
    name: str,
    *,
    level: int = logging.INFO,
    use_json: bool = True,
    handlers: Optional[List[logging.Handler]] = None,
) -> logging.Logger:
    """Get a logger configured for structured logging.
    
    Args:
        name: Logger name (typically __name__ or component identifier).
        level: Logging level (default: INFO).
        use_json: Use JSON formatter (default: True). Set False for development.
        handlers: Custom handlers. If None, uses StreamHandler to stdout.
            FileHandler / other mutable file sinks are rejected unless an
            explicit export permit or legacy-allow flag is active (DQK-079).
    
    Returns:
        Configured logger instance.
    
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing item", extra={"item_id": "abc-123"})
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # Add handlers — default is ephemeral console only (never file authority).
    if handlers is None:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        if use_json:
            handler.setFormatter(JSONLogFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            ))
        handlers = [handler]
    else:
        guard = get_observability_filesystem_guard()
        for handler in handlers:
            guard.check_handler(handler, operation="attach")
    
    for handler in handlers:
        logger.addHandler(handler)
    
    return logger


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

def log_event(
    event_type: str,
    logger: Optional[logging.Logger] = None,
    level: int = logging.INFO,
    **kwargs: Any
) -> None:
    """Log a structured event with standard fields.
    
    Args:
        event_type: Type of event (use EventType enum members).
        logger: Logger to use. If None, uses root logger.
        level: Log level.
        **kwargs: Additional event-specific fields.
    
    Example:
        >>> log_event(EventType.TOOL_INVOKED, tool_name="ipfs_add", duration_ms=123)
    """
    if logger is None:
        logger = logging.getLogger()
    
    extra = kwargs.copy()
    extra[LogField.EVENT_TYPE.value] = event_type
    
    logger.log(level, f"Event: {event_type}", extra=extra)
    _route_structured_event_to_shadow(
        event_type=str(event_type),
        level=level,
        payload=extra,
        message=f"Event: {event_type}",
    )


def _route_structured_event_to_shadow(
    *,
    event_type: str,
    level: int,
    payload: Dict[str, Any],
    message: str,
    outcome: str = "info",
) -> None:
    """Project structured log events into DuckDB cutover (DQK-078) or shadow (DQK-077).

    Console/stderr remains a disposable operational projection under cutover;
    typed DuckDB state is the progress/audit authority when dual or db-primary.
    """

    try:
        from ipfs_datasets_py.duckdb_control.observability_adapters import (
            ObservabilityProducer,
            derive_stable_event_id,
        )
        from ipfs_datasets_py.duckdb_control.observability_cutover import (
            try_record_observability_event,
        )
    except Exception:
        return

    context = get_current_context()
    merged = {**context, **payload}
    actor = str(
        merged.get("user_id")
        or merged.get("component")
        or merged.get("logger")
        or "system"
    )
    seed = str(
        merged.get("event_id")
        or merged.get("request_id")
        or ""
    ) or None
    event_id = derive_stable_event_id(
        producer=ObservabilityProducer.STRUCTURED_LOGGING.value,
        action=event_type,
        actor=actor,
        detail=message,
        seed=seed,
    )
    if level >= logging.ERROR:
        outcome = "error"
    elif level >= logging.WARNING:
        outcome = "info"

    try_record_observability_event(
        producer=ObservabilityProducer.STRUCTURED_LOGGING,
        action=event_type,
        actor=actor,
        outcome=outcome,
        detail=message,
        attributes=merged,
        event_id=event_id,
        operation_id=f"op-slog-{event_id}",
        raw_payload=merged,
    )


def log_error(
    error: Exception,
    logger: Optional[logging.Logger] = None,
    **kwargs: Any
) -> None:
    """Log an error with full context and stack trace.
    
    Args:
        error: Exception instance.
        logger: Logger to use. If None, uses root logger.
        **kwargs: Additional error context.
    
    Example:
        >>> try:
        ...     risky_operation()
        ... except Exception as e:
        ...     log_error(e, operation="risky_operation", item_id="abc")
    """
    if logger is None:
        logger = logging.getLogger()
    
    extra = kwargs.copy()
    extra[LogField.EVENT_TYPE.value] = EventType.ERROR_OCCURRED.value
    extra[LogField.ERROR_TYPE.value] = type(error).__name__
    extra[LogField.ERROR_MESSAGE.value] = str(error)
    
    logger.error(
        f"Error: {type(error).__name__}: {error}",
        exc_info=True,
        extra=extra
    )
    _route_structured_event_to_shadow(
        event_type=EventType.ERROR_OCCURRED.value,
        level=logging.ERROR,
        payload=extra,
        message=f"Error: {type(error).__name__}: {error}",
        outcome="error",
    )


def log_performance(
    operation: str,
    duration_ms: float,
    logger: Optional[logging.Logger] = None,
    **kwargs: Any
) -> None:
    """Log performance metrics for an operation.
    
    Args:
        operation: Name of operation measured.
        duration_ms: Duration in milliseconds.
        logger: Logger to use. If None, uses root logger.
        **kwargs: Additional performance metrics (e.g., memory_mb, cpu_time_ms).
    
    Example:
        >>> start = time.perf_counter()
        >>> result = expensive_computation()
        >>> duration = (time.perf_counter() - start) * 1000
        >>> log_performance("expensive_computation", duration, item_count=100)
    """
    if logger is None:
        logger = logging.getLogger()
    
    extra = kwargs.copy()
    extra[LogField.EVENT_TYPE.value] = "performance.measured"
    extra["operation"] = operation
    extra[LogField.DURATION_MS.value] = duration_ms
    
    logger.info(
        f"Performance: {operation} completed in {duration_ms:.2f}ms",
        extra=extra
    )
    _route_structured_event_to_shadow(
        event_type="performance.measured",
        level=logging.INFO,
        payload=extra,
        message=f"Performance: {operation} completed in {duration_ms:.2f}ms",
        outcome="succeeded",
    )


def log_mcp_tool(
    tool_name: str,
    status: str,
    duration_ms: Optional[float] = None,
    logger: Optional[logging.Logger] = None,
    **kwargs: Any
) -> None:
    """Log MCP++ tool invocation with standard fields.
    
    Args:
        tool_name: Name of the MCP++ tool.
        status: Tool status ("invoked", "completed", "failed").
        duration_ms: Optional execution duration.
        logger: Logger to use.
        **kwargs: Additional tool context (intent_cid, decision_cid, etc.).
    
    Example:
        >>> log_mcp_tool("ipfs_add", "completed", duration_ms=456,
        ...              intent_cid="bafyrei...", receipt_cid="bafyrei...")
    """
    if logger is None:
        logger = logging.getLogger()
    
    extra = kwargs.copy()
    extra[LogField.TOOL_NAME.value] = tool_name
    
    if status == "invoked":
        extra[LogField.EVENT_TYPE.value] = EventType.TOOL_INVOKED.value
    elif status == "completed":
        extra[LogField.EVENT_TYPE.value] = EventType.TOOL_COMPLETED.value
    elif status == "failed":
        extra[LogField.EVENT_TYPE.value] = EventType.TOOL_FAILED.value
    
    if duration_ms is not None:
        extra[LogField.DURATION_MS.value] = duration_ms
    
    logger.info(f"Tool {tool_name} {status}", extra=extra)


# ---------------------------------------------------------------------------
# Performance Context Manager
# ---------------------------------------------------------------------------

@dataclass
class LogPerformance:
    """Context manager for automatic performance logging.
    
    Usage:
        with LogPerformance("expensive_operation") as perf:
            do_expensive_work()
        # Automatically logs duration after block completes
    """
    
    operation: str
    logger: Optional[logging.Logger] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _start_time: float = field(default=0.0, init=False)
    
    def __enter__(self) -> "LogPerformance":
        self._start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration_ms = (time.perf_counter() - self._start_time) * 1000
        
        if exc_type is not None:
            # Operation failed
            self.extra["status"] = "failed"
            log_performance(
                self.operation,
                duration_ms,
                logger=self.logger,
                **self.extra
            )
        else:
            # Operation succeeded
            self.extra["status"] = "success"
            log_performance(
                self.operation,
                duration_ms,
                logger=self.logger,
                **self.extra
            )


# ---------------------------------------------------------------------------
# Log Export/Analysis Helpers
# ---------------------------------------------------------------------------

def parse_json_log_file(log_file: Path) -> List[Dict[str, Any]]:
    """Parse a JSON log file into structured records.
    
    Args:
        log_file: Path to JSON log file (one JSON object per line).
    
    Returns:
        List of parsed log records.
    """
    records = []
    with log_file.open("r") as f:
        for line in f:
            try:
                record = json.loads(line.strip())
                records.append(record)
            except json.JSONDecodeError:
                continue  # Skip malformed lines
    return records


def filter_logs(
    records: List[Dict[str, Any]],
    *,
    level: Optional[str] = None,
    event_type: Optional[str] = None,
    component: Optional[str] = None,
    request_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filter log records by criteria.
    
    Args:
        records: List of log records.
        level: Filter by log level (e.g., "ERROR").
        event_type: Filter by event type.
        component: Filter by component name.
        request_id: Filter by request ID.
    
    Returns:
        Filtered list of records.
    """
    filtered = records
    
    if level is not None:
        filtered = [r for r in filtered if r.get(LogField.LEVEL.value) == level]
    
    if event_type is not None:
        filtered = [r for r in filtered if r.get(LogField.EVENT_TYPE.value) == event_type]
    
    if component is not None:
        filtered = [r for r in filtered if r.get(LogField.COMPONENT.value) == component]
    
    if request_id is not None:
        filtered = [r for r in filtered if r.get(LogField.REQUEST_ID.value) == request_id]
    
    return filtered
