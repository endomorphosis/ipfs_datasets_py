"""Standardized JSON logging schema for ipfs_datasets_py.

This module defines and enforces a consistent JSON logging format across the entire
system, enabling:
- Structured log analysis and alerting
- Machine-readable error tracking
- Performance monitoring and tracing
- Easy integration with log aggregation systems (ELK, Loki, etc.)
- Correlation of related events across services

Standard fields:
- timestamp: ISO 8601 timestamp
- level: DEBUG, INFO, WARNING, ERROR, CRITICAL
- logger: Module name where log originated
- message: Human-readable message
- event_type: Category of event (api_call, database_query, error, etc.)
- correlation_id: Optional ID to trace related logs
- duration_ms: Optional operation duration
- status: Optional success/failure indicator
- extra: Optional additional structured data

Usage:
    from ipfs_datasets_py.optimizers.common.json_logging import get_json_logger
    
    logger = get_json_logger(__name__)
    
    # Structured logging with JSON formatter
    logger.info(
        "API call completed",
        extra={
            "event_type": "api_call",
            "endpoint": "/optimize",
            "duration_ms": 125.5,
            "status": "success",
            "result_count": 42,
        }
    )
    
    # Automatic JSON output:
    # {
    #   "timestamp": "2026-02-25T10:30:45.123Z",
    #   "level": "INFO",
    #   "logger": "my_module",
    #   "message": "API call completed",
    #   "event_type": "api_call",
    #   "endpoint": "/optimize",
    #   "duration_ms": 125.5,
    #   "status": "success",
    #   "result_count": 42
    # }
"""

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict, field
from contextvars import ContextVar

# Context variable for correlation IDs
_correlation_id_context: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)


@dataclass
class LogEvent:
    """Structured log event."""
    timestamp: str
    level: str
    logger: str
    message: str
    event_type: str = ""
    correlation_id: Optional[str] = None
    duration_ms: Optional[float] = None
    status: Optional[str] = None  # "success", "failure", "error"
    extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, filtering None values."""
        data = asdict(self)
        # Remove None values for cleaner JSON
        return {k: v for k, v in data.items() if v is not None}
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)


class JSONFormatter(logging.Formatter):
    """JSON log formatter that outputs structured logs."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.
        
        Args:
            record: LogRecord to format
            
        Returns:
            JSON-formatted log line
        """
        # Extract timestamp
        timestamp = datetime.fromtimestamp(record.created).isoformat() + "Z"
        
        # Get correlation ID from context
        correlation_id = _correlation_id_context.get()
        
        # Build base event
        event = LogEvent(
            timestamp=timestamp,
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
        )
        
        # Extract structured fields from the record's __dict__
        # (fields passed via extra= parameter in logger.info(..., extra={...}))
        extra_dict = {}
        
        # Standard LogRecord fields to skip
        standard_fields = {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "message", "pathname", "process", "processName",
            "relativeCreated", "stack_info", "thread", "threadName",
            "exc_info", "exc_text", "taskName"  # taskName is added by logging module
        }
        
        # Collect all extra fields from the record
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in standard_fields:
                continue
            extra_dict[key] = value
        
        # Extract known fields
        if "event_type" in extra_dict:
            event.event_type = extra_dict.pop("event_type")
        
        if "duration_ms" in extra_dict:
            event.duration_ms = extra_dict.pop("duration_ms")
        
        if "status" in extra_dict:
            event.status = extra_dict.pop("status")
        
        if correlation_id:
            event.correlation_id = correlation_id
        
        # Flatten remaining extra fields into the event dict
        # Then merge into the returned JSON
        result_dict = event.to_dict()
        result_dict.update(extra_dict)
        
        return json.dumps(result_dict, default=str)


class JSONLogger:
    """High-level JSON logger with convenience methods."""
    
    def __init__(self, logger: logging.Logger):
        """Initialize JSON logger wrapping a standard logger.
        
        Args:
            logger: Standard Python logger to wrap
        """
        self.logger = logger
    
    def set_correlation_id(self, correlation_id: Optional[str]) -> None:
        """Set correlation ID for log tracing.
        
        Args:
            correlation_id: ID to include in all subsequent logs
        """
        _correlation_id_context.set(correlation_id)
    
    def get_correlation_id(self) -> Optional[str]:
        """Get current correlation ID."""
        return _correlation_id_context.get()
    
    def generate_correlation_id(self) -> str:
        """Generate and set a new correlation ID.
        
        Returns:
            The generated correlation ID
        """
        correlation_id = str(uuid.uuid4())
        self.set_correlation_id(correlation_id)
        return correlation_id
    
    def debug(
        self,
        message: str,
        *,
        event_type: str = "",
        duration_ms: Optional[float] = None,
        status: Optional[str] = None,
        **extra: Any
    ) -> None:
        """Log debug message with structured fields."""
        self._log(
            logging.DEBUG,
            message,
            event_type=event_type,
            duration_ms=duration_ms,
            status=status,
            **extra
        )
    
    def info(
        self,
        message: str,
        *,
        event_type: str = "",
        duration_ms: Optional[float] = None,
        status: Optional[str] = None,
        **extra: Any
    ) -> None:
        """Log info message with structured fields."""
        self._log(
            logging.INFO,
            message,
            event_type=event_type,
            duration_ms=duration_ms,
            status=status,
            **extra
        )
    
    def warning(
        self,
        message: str,
        *,
        event_type: str = "",
        duration_ms: Optional[float] = None,
        status: Optional[str] = None,
        **extra: Any
    ) -> None:
        """Log warning message with structured fields."""
        self._log(
            logging.WARNING,
            message,
            event_type=event_type,
            duration_ms=duration_ms,
            status=status,
            **extra
        )
    
    def error(
        self,
        message: str,
        *,
        event_type: str = "",
        duration_ms: Optional[float] = None,
        status: Optional[str] = None,
        **extra: Any
    ) -> None:
        """Log error message with structured fields."""
        self._log(
            logging.ERROR,
            message,
            event_type=event_type,
            duration_ms=duration_ms,
            status=status,
            **extra
        )
    
    def critical(
        self,
        message: str,
        *,
        event_type: str = "",
        duration_ms: Optional[float] = None,
        status: Optional[str] = None,
        **extra: Any
    ) -> None:
        """Log critical message with structured fields."""
        self._log(
            logging.CRITICAL,
            message,
            event_type=event_type,
            duration_ms=duration_ms,
            status=status,
            **extra
        )
    
    def _log(
        self,
        level: int,
        message: str,
        event_type: str = "",
        duration_ms: Optional[float] = None,
        status: Optional[str] = None,
        **extra: Any
    ) -> None:
        """Internal logging method."""
        if event_type:
            extra["event_type"] = event_type
        if duration_ms is not None:
            extra["duration_ms"] = duration_ms
        if status:
            extra["status"] = status
        
        self.logger.log(level, message, extra=extra)


# Registry of JSON loggers
_json_loggers: Dict[str, JSONLogger] = {}


def get_json_logger(name: str) -> JSONLogger:
    """Get or create a JSON logger for the given name.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        JSONLogger instance with JSON formatting enabled
    """
    if name not in _json_loggers:
        # Create standard logger
        standard_logger = logging.getLogger(name)
        
        # Add JSON formatter if not already present
        has_json_formatter = any(
            isinstance(h, logging.StreamHandler) and
            isinstance(h.formatter, JSONFormatter)
            for h in standard_logger.handlers
        )
        
        if not has_json_formatter:
            # Add console handler with JSON formatter
            handler = logging.StreamHandler()
            handler.setFormatter(JSONFormatter())
            standard_logger.addHandler(handler)
        
        # Create wrapper
        _json_loggers[name] = JSONLogger(standard_logger)
    
    return _json_loggers[name]


def setup_json_logging(
    name: str = None,
    level: int = logging.INFO,
    output_file: Optional[str] = None,
) -> JSONLogger:
    """Setup JSON logging for an application or module.
    
    Args:
        name: Logger name (None for root logger)
        level: Logging level
        output_file: Optional file to write logs to
        
    Returns:
        Configured JSONLogger instance
    """
    logger_obj = logging.getLogger(name)
    logger_obj.setLevel(level)
    
    # Remove existing handlers
    logger_obj.handlers.clear()
    
    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(JSONFormatter())
    logger_obj.addHandler(console_handler)
    
    # Add file handler if specified
    if output_file:
        file_handler = logging.FileHandler(output_file)
        file_handler.setFormatter(JSONFormatter())
        logger_obj.addHandler(file_handler)
    
    return get_json_logger(name or "root")


class OperationTimer:
    """Context manager for timing operations and logging results."""
    
    def __init__(
        self,
        logger: JSONLogger,
        operation_name: str,
        event_type: str = "",
        **extra_fields: Any
    ):
        """Initialize operation timer.
        
        Args:
            logger: JSONLogger instance
            operation_name: Name of operation being timed
            event_type: Event type to log
            **extra_fields: Additional fields to include in log
        """
        self.logger = logger
        self.operation_name = operation_name
        self.event_type = event_type or operation_name
        self.extra_fields = extra_fields
        self.start_time: Optional[float] = None
        self.duration_ms: Optional[float] = None
    
    def __enter__(self) -> "OperationTimer":
        """Start timing."""
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop timing and log result."""
        if self.start_time is not None:
            self.duration_ms = (time.perf_counter() - self.start_time) * 1000
        
        status = "failure" if exc_type else "success"
        
        message = f"{self.operation_name} {'failed' if exc_type else 'completed'}"
        
        log_fields = {
            "event_type": self.event_type,
            "duration_ms": self.duration_ms,
            "status": status,
            **self.extra_fields
        }
        
        if exc_type:
            log_fields["exception"] = str(exc_val)
            self.logger.error(message, **log_fields)
        else:
            self.logger.info(message, **log_fields)


# Example convenience functions
def log_api_call(
    logger: JSONLogger,
    endpoint: str,
    method: str,
    status_code: int,
    duration_ms: float,
    **kwargs: Any
) -> None:
    """Log an API call with standard fields."""
    status = "success" if 200 <= status_code < 300 else "failure"
    
    logger.info(
        f"API {method} {endpoint} {status_code}",
        event_type="api_call",
        duration_ms=duration_ms,
        status=status,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        **kwargs
    )


def log_database_query(
    logger: JSONLogger,
    query_type: str,
    duration_ms: float,
    rows_affected: int = 0,
    **kwargs: Any
) -> None:
    """Log a database query with standard fields."""
    logger.info(
        f"Database {query_type} completed",
        event_type="database_query",
        duration_ms=duration_ms,
        query_type=query_type,
        rows_affected=rows_affected,
        **kwargs
    )


def log_cache_access(
    logger: JSONLogger,
    cache_key: str,
    hit: bool,
    duration_ms: float = 0.0,
    **kwargs: Any
) -> None:
    """Log cache access with hit/miss status."""
    status = "hit" if hit else "miss"
    
    logger.debug(
        f"Cache {status} for {cache_key}",
        event_type="cache_access",
        duration_ms=duration_ms,
        status=status,
        cache_key=cache_key,
        **kwargs
    )
