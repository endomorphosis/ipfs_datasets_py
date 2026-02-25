"""
Standardized JSON Log Schema (Session 83, P2-obs).

Provides unified, structured logging across all MCP++ components with:
- Consistent field names and types
- Hierarchical context propagation
- Correlation IDs for request tracing
- Performance metrics integration
- Error classification and severity levels

Usage:
    from ipfs_datasets_py.logic.observability.structured_logging import (
        get_logger,
        LogContext,
        log_event,
        log_error,
        log_performance,
    )
    
    logger = get_logger("my_component")
    
    with LogContext(request_id="req-123", user_id="user-456"):
        logger.info("Processing request", extra={"item_count": 10})
        log_event("item_processed", item_id="abc", status="success")
"""

import json
import logging
import time
import traceback
from contextvars import ContextVar
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Optional, List
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
) -> logging.Logger:
    """Get a logger configured for structured logging.
    
    Args:
        name: Logger name (typically __name__ or component identifier).
        level: Logging level (default: INFO).
        use_json: Use JSON formatter (default: True). Set False for development.
        handlers: Custom handlers. If None, uses StreamHandler to stdout.
    
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
        if use_json:
            handler.setFormatter(JSONLogFormatter())
        else:
            handler.setFormatter(logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            ))
        handlers = [handler]
    
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
