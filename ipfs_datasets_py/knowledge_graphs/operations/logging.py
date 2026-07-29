"""Structured JSON logging for knowledge-graph operations (KGP-032).

Emits bounded, redacted JSON records with correlation fields. Graph property
values, raw queries, UCAN tokens, and secrets are scrubbed by default.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Union

from .redact import (
    OPERATIONS_CONTRACT_VERSION,
    bound_string,
    scrub_for_telemetry,
)

LOG_SCHEMA_VERSION = "kg-ops-log/v1"
_COMPONENT = "knowledge_graphs.operations"

_ops_context: ContextVar[Dict[str, Any]] = ContextVar("kg_ops_log_context", default={})


class OpsLogField:
    TIMESTAMP = "timestamp"
    SCHEMA_VERSION = "schema_version"
    CONTRACT_VERSION = "contract_version"
    LEVEL = "level"
    LOGGER = "logger"
    MESSAGE = "message"
    EVENT = "event"
    COMPONENT = "component"
    REQUEST_ID = "request_id"
    TRACE_ID = "trace_id"
    SPAN_ID = "span_id"
    TENANT = "tenant"
    GRAPH_ID = "graph_id"
    REVISION_ID = "revision_id"
    BRANCH = "branch"
    OPERATION = "operation"
    DURATION_MS = "duration_ms"
    STATUS = "status"
    ERROR_CODE = "error_code"
    ERROR_TYPE = "error_type"


@dataclass
class OpsLogContext:
    """Propagate correlation fields through nested operational calls."""

    fields: Dict[str, Any] = field(default_factory=dict)
    _previous: Optional[Dict[str, Any]] = field(default=None, init=False, repr=False)

    def __init__(self, **kwargs: Any) -> None:
        self.fields = dict(kwargs)

    def __enter__(self) -> "OpsLogContext":
        self._previous = _ops_context.get().copy()
        merged = self._previous.copy()
        merged.update(self.fields)
        _ops_context.set(merged)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _ops_context.set(self._previous or {})


def get_ops_context() -> Dict[str, Any]:
    return _ops_context.get().copy()


def set_ops_context(**kwargs: Any) -> None:
    current = _ops_context.get().copy()
    current.update(kwargs)
    _ops_context.set(current)


def clear_ops_context() -> None:
    _ops_context.set({})


def new_request_id() -> str:
    return f"kg-ops-{uuid.uuid4().hex[:16]}"


class OpsJSONFormatter(logging.Formatter):
    """Format log records as single-line JSON with redacted extras."""

    def format(self, record: logging.LogRecord) -> str:
        entry: Dict[str, Any] = {
            OpsLogField.TIMESTAMP: time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)
            ),
            OpsLogField.SCHEMA_VERSION: LOG_SCHEMA_VERSION,
            OpsLogField.CONTRACT_VERSION: OPERATIONS_CONTRACT_VERSION,
            OpsLogField.LEVEL: record.levelname,
            OpsLogField.LOGGER: record.name,
            OpsLogField.MESSAGE: bound_string(record.getMessage(), max_chars=2_048),
            OpsLogField.COMPONENT: _COMPONENT,
        }
        ctx = get_ops_context()
        if ctx:
            entry.update(scrub_for_telemetry(ctx))

        reserved = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "thread",
            "threadName",
            "exc_info",
            "exc_text",
            "stack_info",
            "taskName",
        }
        extras: Dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in reserved or key.startswith("_"):
                continue
            extras[key] = value
        if extras:
            entry.update(scrub_for_telemetry(extras))

        if record.exc_info and record.exc_info[0] is not None:
            entry[OpsLogField.ERROR_TYPE] = record.exc_info[0].__name__
            entry["error_message"] = bound_string(
                str(record.exc_info[1] or ""), max_chars=512
            )
            # Stack traces stay process-local: omit frames by default for ops logs.
            entry["error_present"] = True

        return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


def get_ops_logger(
    name: str = "ipfs_datasets_py.knowledge_graphs.operations",
    *,
    level: int = logging.INFO,
    stream: Optional[Any] = None,
    use_json: bool = True,
) -> logging.Logger:
    """Return a logger configured for structured ops emission."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    # Avoid duplicate handlers when called repeatedly in tests.
    handler_key = "kg_ops_json_handler"
    existing = [
        h for h in logger.handlers if getattr(h, "_kg_ops_handler", None) == handler_key
    ]
    if not existing:
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setLevel(level)
        if use_json:
            handler.setFormatter(OpsJSONFormatter())
        else:
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
        setattr(handler, "_kg_ops_handler", handler_key)
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_ops_event(
    event: str,
    *,
    logger: Optional[logging.Logger] = None,
    level: int = logging.INFO,
    message: Optional[str] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """Emit a structured ops event and return the redacted payload (for tests)."""
    log = logger or get_ops_logger()
    payload = scrub_for_telemetry(
        {
            OpsLogField.EVENT: event,
            **fields,
        }
    )
    log.log(level, message or f"ops.event:{event}", extra=payload)
    return payload


class InMemoryLogCapture(logging.Handler):
    """Test helper: capture structured log records as parsed JSON dicts."""

    def __init__(self) -> None:
        super().__init__()
        self.records: List[Dict[str, Any]] = []
        self.setFormatter(OpsJSONFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = self.format(record)
            self.records.append(json.loads(text))
        except Exception:  # pragma: no cover - never fail the application logger
            pass


def attach_capture(logger: Optional[logging.Logger] = None) -> InMemoryLogCapture:
    log = logger or get_ops_logger()
    capture = InMemoryLogCapture()
    log.addHandler(capture)
    return capture


__all__ = [
    "LOG_SCHEMA_VERSION",
    "InMemoryLogCapture",
    "OpsJSONFormatter",
    "OpsLogContext",
    "OpsLogField",
    "attach_capture",
    "clear_ops_context",
    "get_ops_context",
    "get_ops_logger",
    "log_ops_event",
    "new_request_id",
    "set_ops_context",
]
