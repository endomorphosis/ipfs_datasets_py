"""
Standardized JSON Log Schema (Session 83, P2-obs) with DuckDB-only cutover (DQK-079).

Provides unified, structured logging across all MCP++ components with:
- Consistent field names and types
- Hierarchical context propagation
- Correlation IDs for request tracing
- Performance metrics integration
- Error classification and severity levels

After canary acceptance (DQK-079), implicit JSON/JSONL, ad-hoc file-handler,
metric-snapshot, and alert-state authorities are disabled. Runtime authority
is typed DuckDB observability state (DQK-078). Only explicit deterministic
exports and ephemeral human-readable console logs remain.

Usage:
    from ipfs_datasets_py.logic.observability.structured_logging import (
        get_logger,
        LogContext,
        log_event,
        log_error,
        log_performance,
        configure_duckdb_only_observability,
    )
    
    logger = get_logger("my_component")
    
    with LogContext(request_id="req-123", user_id="user-456"):
        logger.info("Processing request", extra={"item_count": 10})
        log_event("item_processed", item_id="abc", status="success")
"""

from __future__ import annotations

import hashlib
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
from typing import Any, Dict, Iterator, Mapping, Optional, List, Sequence
from pathlib import Path


# ---------------------------------------------------------------------------
# Log Schema Version
# ---------------------------------------------------------------------------

LOG_SCHEMA_VERSION = "1.0.0"


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
    human_readable: bool = False,
) -> logging.Logger:
    """Get a logger configured for structured logging.

    Default handlers are ephemeral console/stream only. Undeclared
    :class:`logging.FileHandler` sinks are rejected when duckdb-only mode is
    active (DQK-079).

    Args:
        name: Logger name (typically __name__ or component identifier).
        level: Logging level (default: INFO).
        use_json: Use JSON formatter (default: True). Set False for development.
        handlers: Custom handlers. If None, uses StreamHandler to stdout.
        human_readable: Prefer plain console format over JSON (ephemeral).

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

    # Add handlers
    if handlers is None:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        prefer_json = use_json and not human_readable
        if prefer_json:
            handler.setFormatter(JSONLogFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            ))
        handlers = [handler]
    else:
        for handler in handlers:
            _assert_handler_allowed(handler)

    for handler in handlers:
        logger.addHandler(handler)

    return logger


def _assert_handler_allowed(handler: logging.Handler) -> None:
    """Reject undeclared mutable file sinks under duckdb-only mode."""

    if legacy_observability_file_sinks_allowed():
        return
    base = handler
    # Unwrap common wrappers.
    while hasattr(base, "handler") and getattr(base, "handler") is not base:
        base = getattr(base, "handler")
    if isinstance(base, logging.FileHandler):
        path = getattr(base, "baseFilename", None) or getattr(base, "stream", None)
        target = Path(str(path)) if path is not None else Path("undeclared.log")
        get_observability_filesystem_guard().assert_write_allowed(
            target,
            kind="file_handler",
            operation="write",
        )


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
    """Project structured log events into DuckDB cutover (DQK-078/DQK-079).

    Console/stderr is an ephemeral, non-authoritative operational projection.
    Typed DuckDB state is the sole progress/audit/completion authority under
    dual or db-primary (and after DQK-079 duckdb-only promotion).
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


# ---------------------------------------------------------------------------
# DQK-079: Remove mutable file authority from audit / observability producers
# ---------------------------------------------------------------------------

OBSERVABILITY_DUCKDB_ONLY_OWNER_TASK: str = "DQK-079"
OBSERVABILITY_DUCKDB_ONLY_SCHEMA: str = (
    "ipfs_datasets_py/duckdb-only-observability@1"
)
OBSERVABILITY_PUBLICATION_TYPE: str = "observability_quack_publication_v1"
OBSERVABILITY_PUBLICATION_SCHEMA: str = (
    "ipfs_datasets_py/observability-quack-publication@1"
)

# Filenames / suffixes that historically acted as mutable observability authority.
_GUARDED_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "audit.json",
        "audit.jsonl",
        "audit.log",
        "metrics.json",
        "metric_snapshot.json",
        "metrics_snapshot.json",
        "alerts.json",
        "alert_state.json",
        "alert-state.json",
        "mcp_server.log",
        "observability.json",
        "observability.jsonl",
        "pipeline.jsonl",
        "structured.log",
        "structured.jsonl",
    }
)
_GUARDED_PREFIXES: tuple[str, ...] = (
    "audit_",
    "metric_",
    "metrics_",
    "alert_",
    "alerts_",
    "observability_",
    "pipeline_",
)
_GUARDED_SUFFIXES: tuple[str, ...] = (
    ".jsonl",
    ".json.log",
)
_SECRET_KEY_RE = re.compile(
    r"(?i)^(password|passwd|pwd|secret|token|api[_-]?key|authorization|"
    r"private[_-]?key|mnemonic|seed|signing|credential|bearer|raw_payload)$"
)
_HIGH_CARDINALITY_KEYS: frozenset[str] = frozenset(
    {
        "client_ip",
        "session_id",
        "user_agent",
        "request_body",
        "response_body",
        "stack_trace",
        "error_stack",
        "raw_payload",
        "formula",
        "query_text",
        "sql",
        "private_metadata",
        "plaintext",
        "payload",
        "email",
        "phone",
        "ssn",
    }
)
_REDACTION_MARKER = "***REDACTED***"
_MAX_PUBLICATION_ATTR_KEYS = 32
_MAX_PUBLICATION_STRING = 256


class ImplicitMutableFileSinkError(RuntimeError):
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


class ObservabilityFilesystemGuard:
    """Static/dynamic guard rejecting undeclared mutable file sinks (DQK-079).

    Implicit writes of audit JSON/JSONL, metric snapshots, alert-state files,
    ad-hoc ``FileHandler`` targets, and related log sinks fail closed unless:

    * legacy file-sink I/O is still allowed (pre-canary / shadow), or
    * an explicit :meth:`permit_export` / :meth:`permit_import` is held.
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
        with self._lock:
            self._export_permits += 1
        try:
            yield
        finally:
            with self._lock:
                self._export_permits = max(0, self._export_permits - 1)

    @contextmanager
    def permit_import(self) -> Iterator[None]:
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

    def classify_path(self, path: Path | str) -> str | None:
        """Return a guarded kind for *path*, or ``None`` if not guarded."""

        p = Path(path)
        name = p.name.lower()
        if name in _GUARDED_EXACT_NAMES:
            if name.endswith(".jsonl"):
                return "audit_jsonl" if "audit" in name or "pipeline" in name else "jsonl"
            if "metric" in name:
                return "metric_snapshot"
            if "alert" in name:
                return "alert_state"
            if name.endswith(".log"):
                return "log_file"
            return "audit_json" if name.endswith(".json") else "ad_hoc_file_sink"
        if name.endswith(".jsonl"):
            return "audit_jsonl"
        if name.endswith(".json") and any(name.startswith(pref) for pref in _GUARDED_PREFIXES):
            if "metric" in name:
                return "metric_snapshot"
            if "alert" in name:
                return "alert_state"
            return "audit_json"
        if any(name.endswith(suf) for suf in _GUARDED_SUFFIXES):
            return "jsonl"
        if name.endswith(".log") and any(
            token in name for token in ("audit", "mcp", "observ", "pipeline", "metric")
        ):
            return "log_file"
        return None

    def assert_write_allowed(
        self,
        path: Path | str,
        *,
        kind: str | None = None,
        operation: str = "write",
    ) -> None:
        """Fail closed if *path* is a guarded mutable sink without a permit."""

        classified = kind or self.classify_path(path)
        if classified is None and kind is None:
            return
        sink_kind = classified or kind or "ad_hoc_file_sink"
        with self._lock:
            allowed = self._allow_legacy_file_sinks or self._has_permit()
        if allowed:
            return
        raise ImplicitMutableFileSinkError(
            f"implicit {sink_kind} {operation} blocked by observability "
            f"filesystem guard: {path} (use explicit deterministic export "
            f"or ephemeral console logs; DQK-079)",
            path=str(path),
            kind=str(sink_kind),
            operation=operation,
        )

    def assert_allowed(
        self,
        path: Path | str,
        *,
        kind: str | None = None,
        operation: str = "write",
    ) -> None:
        """Alias used by static/dynamic guard tests (parity with graph guard)."""

        self.assert_write_allowed(path, kind=kind, operation=operation)

    def check_path_write(self, path: Path | str, *, kind: str = "json") -> None:
        self.assert_write_allowed(path, kind=kind, operation="write")


_guard_lock = threading.RLock()
_process_guard: ObservabilityFilesystemGuard | None = None
_duckdb_only_active: bool = False


def get_observability_filesystem_guard() -> ObservabilityFilesystemGuard:
    """Return the process-wide observability filesystem guard."""

    global _process_guard
    with _guard_lock:
        if _process_guard is None:
            # Default post-canary: fail closed (no implicit mutable sinks).
            _process_guard = ObservabilityFilesystemGuard(
                allow_legacy_file_sinks=False
            )
        return _process_guard


def reset_observability_filesystem_guard() -> None:
    """Reset process guard and duckdb-only flag (tests / process teardown)."""

    global _process_guard, _duckdb_only_active
    with _guard_lock:
        _process_guard = None
        _duckdb_only_active = False


def legacy_observability_file_sinks_allowed() -> bool:
    """True when implicit JSON/JSONL/file-handler sinks may still write."""

    return get_observability_filesystem_guard().allow_legacy_file_sinks


def duckdb_only_observability() -> bool:
    """True after :func:`configure_duckdb_only_observability` (DQK-079)."""

    with _guard_lock:
        return _duckdb_only_active


def set_legacy_observability_file_sinks_allowed(allowed: bool) -> None:
    """Enable or disable legacy mutable file-sink I/O for the process."""

    get_observability_filesystem_guard().allow_legacy_file_sinks = bool(allowed)
    if allowed:
        with _guard_lock:
            global _duckdb_only_active
            # Re-enabling legacy sinks exits pure duckdb-only mode.
            _duckdb_only_active = False


def assert_observability_file_write_allowed(
    path: Path | str,
    *,
    kind: str | None = None,
    operation: str = "write",
) -> None:
    """Raise :class:`ImplicitMutableFileSinkError` if *path* is blocked."""

    get_observability_filesystem_guard().assert_write_allowed(
        path, kind=kind, operation=operation
    )


def configure_duckdb_only_observability(
    *,
    mode: str | Any = "db-primary",
    source_revision: str | None = None,
    allow_legacy_file_sinks: bool = False,
    console_enabled: bool = True,
):
    """Promote observability to DuckDB-only authority and disable file sinks.

    Configures the DQK-078 cutover repository (when available) to *mode*
    (default ``db-primary``) and installs process guards that reject undeclared
    mutable JSON/JSONL/file-handler/metric-snapshot/alert-state sinks.

    Returns the cutover repository instance, or ``None`` if cutover wiring is
    unavailable in the current environment.
    """

    global _duckdb_only_active
    guard = get_observability_filesystem_guard()
    guard.allow_legacy_file_sinks = bool(allow_legacy_file_sinks)
    with _guard_lock:
        _duckdb_only_active = not bool(allow_legacy_file_sinks)

    repo = None
    try:
        from ipfs_datasets_py.duckdb_control.authority_transition import (
            AuthorityMode,
        )
        from ipfs_datasets_py.duckdb_control.observability_cutover import (
            ConsoleProjection,
            configure_observability_cutover,
        )

        mode_enum = (
            mode
            if isinstance(mode, AuthorityMode)
            else AuthorityMode.parse(str(mode))
        )
        repo = configure_observability_cutover(
            mode=mode_enum,
            source_revision=source_revision
            or "dqk-079-duckdb-only-observability",
            console=ConsoleProjection(stream=None, enabled=console_enabled),
        )
        # When starting from dual/shadow, promote to db-primary for canary exit.
        if mode_enum is AuthorityMode.DB_PRIMARY and repo.mode is not AuthorityMode.DB_PRIMARY:
            try:
                # Seed a parity key so promotion can fence if required.
                from ipfs_datasets_py.duckdb_control.observability_adapters import (
                    ObservabilityProducer,
                )

                receipt = repo.record_event(
                    producer=ObservabilityProducer.STRUCTURED_LOGGING,
                    action="lifecycle.duckdb_only.promote",
                    actor="dqk-079",
                    outcome="succeeded",
                    detail="configure_duckdb_only_observability",
                    event_id="dqk-079-promote-seed",
                )
                if receipt is not None:
                    key = f"obs:{receipt.producer}:{receipt.event_id}"
                    repo.promote_to_db_primary(parity_key=key)
            except Exception:  # noqa: BLE001 — best-effort promotion
                pass
    except Exception:  # noqa: BLE001 — hermetic / partial installs
        repo = None
    return repo


def export_observability_json(
    path: Path | str,
    payload: Mapping[str, Any] | Sequence[Any],
    *,
    pretty: bool = True,
) -> Path:
    """Explicit deterministic JSON export under an export permit (DQK-079).

    This is the **only** supported way to materialize observability JSON after
    canary acceptance. Implicit writers must not call this without a deliberate
    export call path.
    """

    target = Path(path)
    guard = get_observability_filesystem_guard()
    with guard.permit_export():
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (
            json.dumps(payload, indent=2, sort_keys=True, default=str)
            if pretty
            else json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
        )
        target.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
    return target


def sanitize_for_publication(
    value: Any,
    *,
    _depth: int = 0,
) -> Any:
    """Redact secrets and high-cardinality private fields from a view payload."""

    if _depth > 8:
        return _REDACTION_MARKER
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for i, (key, item) in enumerate(value.items()):
            if i >= _MAX_PUBLICATION_ATTR_KEYS:
                out["_truncated_keys"] = True
                break
            name = str(key)
            if _SECRET_KEY_RE.fullmatch(name) or name.lower() in _HIGH_CARDINALITY_KEYS:
                out[name] = _REDACTION_MARKER
                continue
            out[name] = sanitize_for_publication(item, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        # Bound cardinality of array payloads.
        limited = list(value)[:16]
        return [sanitize_for_publication(v, _depth=_depth + 1) for v in limited]
    if isinstance(value, str):
        if len(value) > _MAX_PUBLICATION_STRING:
            return value[:_MAX_PUBLICATION_STRING] + "…[truncated]"
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_PUBLICATION_STRING]


def build_sanitized_observability_publication(
    *,
    snapshot: Mapping[str, Any] | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    progress: Mapping[str, Any] | None = None,
    mode: str = "db-primary",
) -> dict[str, Any]:
    """Build a Quack-safe publication view excluding secrets and private payloads.

    Console lines and raw high-cardinality private fields never appear.
    Progress/completion authority is always the DuckDB snapshot sequence, never
    console log content.
    """

    snap = dict(snapshot or {})
    # Prefer cutover snapshot when none supplied.
    if not snap:
        try:
            from ipfs_datasets_py.duckdb_control.observability_cutover import (
                get_observability_cutover,
            )

            repo = get_observability_cutover()
            if repo is not None:
                authority_snap = repo.open_snapshot()
                snap = authority_snap.to_dict()
                if progress is None:
                    progress = authority_snap.progress_cursor()
                if events is None:
                    events = list(authority_snap.audit_events())
                mode = authority_snap.mode
        except Exception:  # noqa: BLE001
            pass

    safe_events: list[dict[str, Any]] = []
    for row in events or snap.get("records", {}).get("audit_events", ()) or ():
        if isinstance(row, Mapping):
            safe_events.append(sanitize_for_publication(dict(row)))

    safe_progress = sanitize_for_publication(
        dict(progress or snap.get("progress") or {"authority": "sequence", "sequence": 0})
    )
    # Explicitly assert console is not authority in the published document.
    if isinstance(safe_progress, dict):
        safe_progress["console_is_authority"] = False
        safe_progress.setdefault("authority", "sequence")

    body = {
        "schema": OBSERVABILITY_PUBLICATION_SCHEMA,
        "publication_type": OBSERVABILITY_PUBLICATION_TYPE,
        "owner_task": OBSERVABILITY_DUCKDB_ONLY_OWNER_TASK,
        "mode": mode,
        "authority": "duckdb",
        "console_is_authority": False,
        "jsonl_scanned": False,
        "legacy_file_sinks_allowed": legacy_observability_file_sinks_allowed(),
        "progress": safe_progress,
        "approved_sanitized_audit_views": safe_events[:128],
        "family_counts": sanitize_for_publication(
            dict(snap.get("family_counts") or {})
        ),
        "secrets_excluded": True,
        "high_cardinality_private_excluded": True,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    body["content_digest"] = f"sha256:{digest}"
    return body


def console_cannot_satisfy_progress_or_completion(
    console_lines: Sequence[str] | None = None,
    *,
    progress: Mapping[str, Any] | None = None,
) -> bool:
    """Return True when progress/completion authority is not console-derived.

    Console logs are ephemeral human-readable projections only. This helper is
    used by e2e and validation gates to prove they never answer progress or
    completion queries.
    """

    if progress is not None:
        auth = str(progress.get("authority") or "").lower()
        if auth in {"console", "stderr", "stdout", "log", "jsonl", "file"}:
            return False
        if progress.get("console_is_authority") is True:
            return False
    # Presence of console lines alone never constitutes completion authority.
    _ = console_lines
    return True
