"""
Standardized JSON Log Schema (Session 83, P2-obs).

Provides unified, structured logging across all MCP++ components with:
- Consistent field names and types
- Hierarchical context propagation
- Correlation IDs for request tracing
- Performance metrics integration
- Error classification and severity levels

Also hosts the DQK-079 mutable file-sink authority policy shared by
observability producers: after canary acceptance (``db-primary`` /
``export-only``), implicit JSON/JSONL/file-handler/metric-snapshot/alert-state
sinks are rejected; only explicit deterministic exports and ephemeral
console/stderr logs remain.

Usage:
    from ipfs_datasets_py.logic.observability.structured_logging import (
        get_logger,
        LogContext,
        log_event,
        log_error,
        log_performance,
        assert_mutable_file_sink_allowed,
        legacy_mutable_file_sinks_allowed,
        permit_explicit_observability_export,
        sanitized_publication_view,
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
from typing import Any, Dict, Generator, Iterable, List, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Log Schema Version
# ---------------------------------------------------------------------------

LOG_SCHEMA_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# DQK-079: mutable file-sink authority policy
# ---------------------------------------------------------------------------

OBSERVABILITY_FILE_SINK_OWNER_TASK = "DQK-079"
OBSERVABILITY_FILE_SINK_POLICY_SCHEMA = (
    "ipfs_datasets_py/duckdb-control-observability-file-sink-policy@1"
)

# Closed set of legacy mutable filenames that must not be required or written
# as authority after canary (db-primary / export-only).
LEGACY_MUTABLE_OBSERVABILITY_FILENAMES: tuple[str, ...] = (
    "audit.json",
    "audit.jsonl",
    "audit_log.json",
    "audit_log.jsonl",
    "audit_trail.json",
    "metrics.json",
    "metrics.jsonl",
    "metric_snapshot.json",
    "metric_snapshots.json",
    "alert_state.json",
    "alerts.json",
    "alert_state.jsonl",
    "mcp_server.log",
    "pipeline.jsonl",
    "pipeline.json",
    "structured.jsonl",
    "structured.json",
    "observability.jsonl",
    "observability.json",
    "logging_audit.json",
)

# Producer modules governed by DQK-079 static / dynamic guards.
OBSERVABILITY_PRODUCER_MODULE_PATHS: tuple[str, ...] = (
    "ipfs_datasets_py/audit/audit_logger.py",
    "ipfs_datasets_py/logic/security/audit_log.py",
    "ipfs_datasets_py/logic/observability/structured_logging.py",
    "ipfs_datasets_py/optimizers/graphrag/audit_logger.py",
    "ipfs_datasets_py/optimizers/graphrag/pipeline_json_logger.py",
    "ipfs_datasets_py/optimizers/common/logging_audit.py",
    "ipfs_datasets_py/alerts/alert_manager.py",
    "ipfs_datasets_py/mcp_server/logger.py",
)

# High-cardinality / private keys stripped from sanitized publication views.
HIGH_CARDINALITY_PRIVATE_KEYS: frozenset[str] = frozenset(
    {
        "user_id",
        "session_id",
        "client_ip",
        "source_ip",
        "ip_address",
        "request_id",
        "trace_id",
        "raw_payload",
        "stack_trace",
        "error_stack",
        "email",
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "authorization",
        "private_key",
        "mnemonic",
        "credential",
        "bearer",
        "hostname",
        "process_id",
        "formula",
        "query_text",
        "sql",
        "body",
        "headers",
        "cookies",
        "payload",
        "details",
        "event_data",
        "metadata",
        "attributes",
    }
)

_REDACTION_MARKER = "[REDACTED]"
_SECRET_KEY_RE = re.compile(
    r"(?i)^(password|passwd|pwd|secret|token|api[_-]?key|authorization|"
    r"private[_-]?key|mnemonic|seed|signing|credential|bearer)$"
)

# Modes where mutable file sinks are rejected (post-canary DuckDB authority).
_FILE_SINK_REJECT_MODES: frozenset[str] = frozenset(
    {"db-primary", "db_primary", "export-only", "export_only"}
)

_export_permit = threading.local()


class ObservabilityMutableFileSinkError(RuntimeError):
    """Raised when an undeclared mutable file sink is requested after cutover."""


class ObservabilityConsoleAuthorityError(RuntimeError):
    """Raised when console/stderr is offered as progress or completion authority."""


def _cutover_mode_value() -> Optional[str]:
    """Return current observability cutover mode string, or None if unset."""

    try:
        from ipfs_datasets_py.duckdb_control.observability_cutover import (
            get_observability_cutover,
        )
    except Exception:
        return None
    try:
        repo = get_observability_cutover()
    except Exception:
        return None
    if repo is None:
        return None
    mode = getattr(repo, "mode", None)
    if mode is None:
        return None
    return str(getattr(mode, "value", mode)).strip().lower().replace("_", "-")


def duckdb_is_observability_authority() -> bool:
    """True when typed DuckDB state is the selected observability authority."""

    mode = _cutover_mode_value()
    if mode is None:
        return False
    return mode in {"dual", "db-primary", "export-only"}


def legacy_mutable_file_sinks_allowed() -> bool:
    """Whether implicit JSON/JSONL/file-handler sinks may still be written.

    After canary acceptance (``db-primary`` / ``export-only``) this is False.
    Shadow/dual dual-writes and pre-cutover (no repository) remain allowed so
    legacy tests and shadow projections continue to function.
    """

    if getattr(_export_permit, "depth", 0) > 0:
        return True
    mode = _cutover_mode_value()
    if mode is None:
        return True
    return mode not in _FILE_SINK_REJECT_MODES


def assert_mutable_file_sink_allowed(
    path: Any = None,
    *,
    kind: str = "mutable_file",
    explicit_export: bool = False,
) -> None:
    """Dynamic writer guard: reject undeclared mutable file sinks post-canary.

    Explicit deterministic exports must pass ``explicit_export=True`` or run
    under :func:`permit_explicit_observability_export`.
    """

    if explicit_export or getattr(_export_permit, "depth", 0) > 0:
        return
    if legacy_mutable_file_sinks_allowed():
        return
    where = f" path={path!s}" if path else ""
    raise ObservabilityMutableFileSinkError(
        f"undeclared mutable observability file sink rejected after DQK-079 "
        f"canary cutover (kind={kind}{where}); use explicit deterministic "
        f"exports or ephemeral console logs only"
    )


@contextmanager
def permit_explicit_observability_export() -> Generator[None, None, None]:
    """Permit a single explicit deterministic export write (not authority)."""

    depth = getattr(_export_permit, "depth", 0)
    _export_permit.depth = depth + 1
    try:
        yield
    finally:
        _export_permit.depth = max(0, getattr(_export_permit, "depth", 1) - 1)


def is_logging_file_handler(handler: Any) -> bool:
    """Return True when *handler* is a logging FileHandler (or subclass)."""

    if handler is None:
        return False
    try:
        return isinstance(handler, logging.FileHandler)
    except Exception:
        return False


def handler_has_file_path(handler: Any) -> bool:
    """True when a handler advertises a mutable file_path / baseFilename."""

    if handler is None:
        return False
    for attr in ("file_path", "baseFilename", "filename", "_file_path"):
        value = getattr(handler, attr, None)
        if value:
            return True
    return is_logging_file_handler(handler)


def assert_handler_not_undeclared_file_sink(handler: Any) -> None:
    """Reject attaching undeclared file/JSONL handlers after canary cutover."""

    if not handler_has_file_path(handler) and not is_logging_file_handler(handler):
        return
    path = (
        getattr(handler, "file_path", None)
        or getattr(handler, "baseFilename", None)
        or getattr(handler, "filename", None)
        or "<file-handler>"
    )
    assert_mutable_file_sink_allowed(path, kind="file_handler")


def assert_console_not_progress_or_completion_authority(
    *,
    claim_progress: bool = False,
    claim_completion: bool = False,
    console_is_authority: bool = False,
) -> None:
    """Console/stderr must never answer progress or completion queries."""

    if claim_progress or claim_completion or console_is_authority:
        raise ObservabilityConsoleAuthorityError(
            "console/stderr logs cannot satisfy progress or completion "
            "authority under DQK-079; query DuckDB sequence progress only"
        )
    # Soft check against live cutover console projection.
    try:
        from ipfs_datasets_py.duckdb_control.observability_cutover import (
            get_observability_cutover,
        )

        repo = get_observability_cutover()
        if repo is not None and getattr(repo.console, "is_authority", False):
            raise ObservabilityConsoleAuthorityError(
                "configured console projection claims authority; forbidden"
            )
    except ObservabilityConsoleAuthorityError:
        raise
    except Exception:
        return


def _looks_like_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.fullmatch(str(key).strip()))


def sanitized_publication_view(
    payload: Mapping[str, Any] | None,
    *,
    strip_high_cardinality: bool = True,
) -> Dict[str, Any]:
    """Build a sanitized publication view excluding secrets and private HC keys.

    Uses the typed observability redactor when available, then drops
    high-cardinality private keys so Quack publication surfaces never re-expose
    them.
    """

    if payload is None:
        return {}
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping")

    try:
        from ipfs_datasets_py.duckdb_control.observability_adapters import (
            redact_event_payload,
        )

        redacted, _klass = redact_event_payload(dict(payload))
    except Exception:
        # Fail closed: redact secret-looking keys locally.
        redacted = {}
        for key, value in payload.items():
            name = str(key)
            if _looks_like_secret_key(name):
                redacted[name] = _REDACTION_MARKER
            elif isinstance(value, Mapping):
                redacted[name] = sanitized_publication_view(
                    value, strip_high_cardinality=strip_high_cardinality
                )
            else:
                redacted[name] = value

    if not strip_high_cardinality:
        return dict(redacted)

    cleaned: Dict[str, Any] = {}
    for key, value in redacted.items():
        name = str(key)
        if name.lower() in HIGH_CARDINALITY_PRIVATE_KEYS or _looks_like_secret_key(
            name
        ):
            continue
        if isinstance(value, Mapping):
            cleaned[name] = sanitized_publication_view(
                value, strip_high_cardinality=True
            )
        else:
            cleaned[name] = value
    return cleaned


def static_guard_reject_undeclared_file_sinks(
    source: str,
    *,
    path: str = "<source>",
) -> List[str]:
    """Scan *source* for unguarded mutable file-sink writes (DQK-079 static guard).

    Allowed write sites must mention a guard/export marker in the enclosing
    function body, or be named as an explicit export helper.
    """

    import ast

    violations: List[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"{path}: syntax error during static guard: {exc}"]

    allow_markers = (
        "assert_mutable_file_sink_allowed",
        "legacy_mutable_file_sinks_allowed",
        "permit_explicit_observability_export",
        "explicit_export",
        "assert_handler_not_undeclared_file_sink",
        "ObservabilityMutableFileSinkError",
        "is_export_only",
        "duckdb_is_observability_authority",
    )
    allow_func_names = frozenset(
        {
            "export_json",
            "export_alert_state",
            "export_deterministic",
            "export_metric_snapshot",
            "permit_explicit_observability_export",
            "assert_mutable_file_sink_allowed",
            "static_guard_reject_undeclared_file_sinks",
            "static_guard_observability_producers",
            "sanitized_publication_view",
            "parse_json_log_file",  # read-only import helper
            "load_audit_trail",  # read-only
            "load_rules_from_file",  # config read
            "to_json",
            "to_dict",
            "format",
            "format_event",
            "JSONLogFormatter",
            "formatMessage",
            "_emit_log",  # console-only JSON line
            "log_event",
            "log",
            "dumps",  # in-memory
            "main",
            "generate_report",
            "build_sanitized_publication_view",
        }
    )

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._func_stack: list[str] = []
            self._func_source_stack: list[str] = []
            self._class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._class_stack.append(node.name)
            self.generic_visit(node)
            self._class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._func_stack.append(node.name)
            try:
                segment = ast.get_source_segment(source, node) or ""
            except Exception:
                segment = ""
            self._func_source_stack.append(segment)
            self.generic_visit(node)
            self._func_stack.pop()
            self._func_source_stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[misc]

        def visit_Call(self, node: ast.Call) -> None:
            name = ""
            owner = ""
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
                if isinstance(node.func.value, ast.Name):
                    owner = node.func.value.id
            elif isinstance(node.func, ast.Name):
                name = node.func.id

            func_name = self._func_stack[-1] if self._func_stack else ""
            body = self._func_source_stack[-1] if self._func_source_stack else ""
            lineno = getattr(node, "lineno", 0)

            # Flag FileHandler construction
            if name in {"FileHandler", "RotatingFileHandler", "TimedRotatingFileHandler"}:
                if func_name in allow_func_names or any(
                    marker in body for marker in allow_markers
                ):
                    self.generic_visit(node)
                    return
                violations.append(
                    f"{path}:{lineno}: {name} construction in "
                    f"{func_name or '<module>'} without file-sink guard"
                )

            # Flag json.dump to files (not dumps for in-memory)
            if name == "dump" and owner in {"json", "_json", ""}:
                if func_name in allow_func_names or any(
                    marker in body for marker in allow_markers
                ):
                    self.generic_visit(node)
                    return
                # Module-level or persistence-like functions without guards
                if re.search(
                    r"persist|save|write|export|snapshot|state|file",
                    func_name,
                    re.I,
                ) or func_name in {"", "<module>"}:
                    violations.append(
                        f"{path}:{lineno}: json.dump in {func_name or '<module>'} "
                        f"without file-sink / explicit-export guard"
                    )

            # Flag open(..., 'w'/'a') for authority-looking sinks
            if name == "open":
                mode_arg = None
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode_arg = str(node.args[1].value)
                for kw in node.keywords or []:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode_arg = str(kw.value.value)
                if mode_arg and any(c in mode_arg for c in ("w", "a", "x")):
                    if func_name in allow_func_names or any(
                        marker in body for marker in allow_markers
                    ):
                        self.generic_visit(node)
                        return
                    if re.search(
                        r"persist|save|write|export|_write|snapshot|state|file|log",
                        func_name,
                        re.I,
                    ):
                        violations.append(
                            f"{path}:{lineno}: open(..., {mode_arg!r}) in "
                            f"{func_name} without file-sink / explicit-export guard"
                        )

            self.generic_visit(node)

    _Visitor().visit(tree)
    return violations


def static_guard_observability_producers(
    repo_root: Any = None,
) -> Dict[str, List[str]]:
    """Run static file-sink guards over every DQK-079 producer module."""

    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    report: Dict[str, List[str]] = {}
    for rel in OBSERVABILITY_PRODUCER_MODULE_PATHS:
        path = root / rel
        if not path.is_file():
            report[rel] = [f"missing module for static guard: {rel}"]
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            report[rel] = [f"unreadable: {exc}"]
            continue
        report[rel] = static_guard_reject_undeclared_file_sinks(text, path=rel)
    return report


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
    
    # Add handlers — file handlers are rejected after DQK-079 canary cutover.
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
        assert_handler_not_undeclared_file_sink(handler)
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
    """Parse a JSON log file into structured records (read-only import helper).

    This is a **compatibility reader** for explicit exports — it does not
    establish progress or completion authority. Prefer DuckDB snapshots for
    authoritative audit/progress queries after DQK-079.

    Args:
        log_file: Path to JSON log file (one JSON object per line).

    Returns:
        List of parsed log records.
    """
    # Console/file lines cannot satisfy progress or completion authority.
    assert_console_not_progress_or_completion_authority()
    records = []
    with Path(log_file).open("r") as f:
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
