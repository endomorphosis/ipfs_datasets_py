"""
OpenTelemetry integration for circuit breaker and structured logging.

This module provides distributed tracing capabilities for the MCP++ observability
infrastructure. It emits spans for circuit breaker state transitions, call latencies,
and error events, enabling trace correlation across distributed systems.

Features:
    - Automatic span creation for circuit breaker calls
    - Trace correlation across parent/child operations
    - Event attributes for state transitions
    - Error event recording with exception context
    - Context propagation for distributed tracing

Example:
    >>> from ipfs_datasets_py.logic.observability.otel_integration import (
    ...     OTelTracer,
    ...     setup_otel_tracer
    ... )
    >>> tracer = setup_otel_tracer("complaint-generator")
    >>> with tracer.start_span("circuit_breaker_call", {"component": "payment_api"}):
    ...     result = await payment_api.call()
    ...     if result.failed:
    ...         tracer.record_error("payment_api", result.error)
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock, local
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


class SpanStatus(str, Enum):
    """OpenTelemetry span status codes."""
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


class EventType(str, Enum):
    """Event types for span events."""
    CIRCUIT_BREAKER_STATE_CHANGE = "circuit_breaker.state_change"
    CIRCUIT_BREAKER_CALL = "circuit_breaker.call"
    CIRCUIT_BREAKER_ERROR = "circuit_breaker.error"
    LOG_ENTRY = "log.entry"
    ERROR = "error"


@dataclass
class SpanEvent:
    """A single event within a span."""
    name: str
    timestamp: float
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    """Represents an OpenTelemetry span."""
    name: str
    span_id: str
    trace_id: str
    parent_span_id: Optional[str]
    start_time: float
    end_time: Optional[float] = None
    status: SpanStatus = SpanStatus.UNSET
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)

    def is_active(self) -> bool:
        """Check if span is still active (not ended)."""
        return self.end_time is None

    def duration_ms(self) -> float:
        """Get span duration in milliseconds."""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000.0


@dataclass
class Trace:
    """Represents a complete trace (collection of related spans)."""
    trace_id: str
    spans: List[Span] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None

    def root_span(self) -> Optional[Span]:
        """Get the root span (no parent)."""
        for span in self.spans:
            if span.parent_span_id is None:
                return span
        return None

    def duration_ms(self) -> float:
        """Get trace duration in milliseconds."""
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000.0


class OTelTracer:
    """OpenTelemetry tracer for circuit breaker and logging instrumentation."""

    def __init__(self, service_name: str):
        """
        Initialize the OpenTelemetry tracer.

        Args:
            service_name: Name of the service being traced.
        """
        self.service_name = service_name
        self._lock = RLock()
        self._local_context = local()
        self._traces: Dict[str, Trace] = {}
        self._completed_traces: List[Trace] = []
        self._max_completed_traces = 100

    def _get_current_trace_id(self) -> str:
        """Get or create the current trace ID."""
        if not hasattr(self._local_context, "trace_id"):
            self._local_context.trace_id = str(uuid4())
        return self._local_context.trace_id

    def _get_current_span_id(self) -> Optional[str]:
        """Get the current active span ID."""
        if not hasattr(self._local_context, "span_stack"):
            self._local_context.span_stack = []
        if self._local_context.span_stack:
            return self._local_context.span_stack[-1]
        return None

    def _push_span(self, span_id: str) -> None:
        """Push a span onto the thread-local stack."""
        if not hasattr(self._local_context, "span_stack"):
            self._local_context.span_stack = []
        self._local_context.span_stack.append(span_id)

    def _pop_span(self) -> Optional[str]:
        """Pop the current span from the thread-local stack."""
        if not hasattr(self._local_context, "span_stack"):
            self._local_context.span_stack = []
        if self._local_context.span_stack:
            return self._local_context.span_stack.pop()
        return None

    def start_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
        parent_span_id: Optional[str] = None
    ) -> Span:
        """
        Start a new span.

        Args:
            name: Name of the span.
            attributes: Optional attributes to attach to the span.
            parent_span_id: Optional parent span ID (defaults to current span).

        Returns:
            The created Span object.
        """
        with self._lock:
            trace_id = self._get_current_trace_id()
            span_id = str(uuid4())
            parent = parent_span_id or self._get_current_span_id()

            span = Span(
                name=name,
                span_id=span_id,
                trace_id=trace_id,
                parent_span_id=parent,
                start_time=time.time(),
                attributes=attributes or {}
            )

            # Get or create trace
            if trace_id not in self._traces:
                self._traces[trace_id] = Trace(trace_id=trace_id)
            self._traces[trace_id].spans.append(span)

            self._push_span(span_id)
            return span

    def end_span(self, span: Span, status: SpanStatus = SpanStatus.OK) -> None:
        """
        End a span.

        Args:
            span: The Span to end.
            status: Final status of the span.
        """
        with self._lock:
            span.end_time = time.time()
            span.status = status
            self._pop_span()

            # If this was the root span, move trace to completed
            if span.parent_span_id is None and span.trace_id in self._traces:
                trace = self._traces.pop(span.trace_id)
                trace.end_time = span.end_time
                self._completed_traces.append(trace)
                if len(self._completed_traces) > self._max_completed_traces:
                    self._completed_traces.pop(0)

    def record_event(
        self,
        span: Span,
        event_type: EventType,
        attributes: Optional[Dict[str, Any]] = None
    ) -> SpanEvent:
        """
        Record an event within a span.

        Args:
            span: The Span to record the event in.
            event_type: Type of event.
            attributes: Optional event attributes.

        Returns:
            The recorded SpanEvent.
        """
        with self._lock:
            event = SpanEvent(
                name=event_type.value,
                timestamp=time.time(),
                attributes=attributes or {}
            )
            span.events.append(event)
            return event

    def record_error(
        self,
        span: Span,
        error_message: str,
        error_type: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record an error event in a span.

        Args:
            span: The Span to record the error in.
            error_message: Error message.
            error_type: Optional error type (exception class name).
            attributes: Optional additional attributes.
        """
        with self._lock:
            error_attrs = attributes or {}
            error_attrs.update({
                "error.type": error_type or "UnknownError",
                "error.message": error_message,
            })
            self.record_event(span, EventType.ERROR, error_attrs)
            span.status = SpanStatus.ERROR

    @contextmanager
    def span_context(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None
    ):
        """
        Context manager for span creation and lifecycle.

        Args:
            name: Name of the span.
            attributes: Optional attributes for the span.

        Yields:
            The created Span object.

        Example:
            >>> with tracer.span_context("api_call", {"endpoint": "/data"}) as span:
            ...     result = await api.call()
            ...     if result.error:
            ...         tracer.record_error(span, str(result.error))
        """
        span = self.start_span(name, attributes)
        try:
            yield span
            self.end_span(span, SpanStatus.OK)
        except Exception as e:
            self.record_error(span, str(e), type(e).__name__)
            self.end_span(span, SpanStatus.ERROR)
            raise

    def set_span_attribute(self, span: Span, key: str, value: Any) -> None:
        """
        Set an attribute on a span.

        Args:
            span: The Span to modify.
            key: Attribute key.
            value: Attribute value.
        """
        with self._lock:
            span.attributes[key] = value

    def get_active_span(self) -> Optional[Span]:
        """
        Get the currently active span.

        Returns:
            The active Span, or None if no span is active.
        """
        span_id = self._get_current_span_id()
        trace_id = self._get_current_trace_id()
        with self._lock:
            if trace_id in self._traces:
                for span in self._traces[trace_id].spans:
                    if span.span_id == span_id:
                        return span
        return None

    def get_trace(self, trace_id: str) -> Optional[Trace]:
        """
        Get a trace by ID (active or completed).

        Args:
            trace_id: The trace ID.

        Returns:
            The Trace, or None if not found.
        """
        with self._lock:
            if trace_id in self._traces:
                return self._traces[trace_id]
            for trace in self._completed_traces:
                if trace.trace_id == trace_id:
                    return trace
        return None

    def get_completed_traces(self) -> List[Trace]:
        """Get all completed traces."""
        with self._lock:
            return list(self._completed_traces)

    def export_jaeger_format(self) -> str:
        """
        Export traces in Jaeger JSON format.

        Returns:
            Traces in Jaeger-compatible JSON format.
        """
        import json

        traces = []
        with self._lock:
            for trace in self._completed_traces:
                trace_dict = {
                    "traceID": trace.trace_id,
                    "spans": [
                        {
                            "traceID": span.trace_id,
                            "spanID": span.span_id,
                            "operationName": span.name,
                            "startTime": int(span.start_time * 1e6),
                            "duration": int(span.duration_ms() * 1000),
                            "references": (
                                [{"refType": "CHILD_OF", "traceID": span.parent_span_id}]
                                if span.parent_span_id else []
                            ),
                            "tags": [
                                {"key": k, "value": v}
                                for k, v in span.attributes.items()
                            ],
                            "logs": [
                                {
                                    "timestamp": int(event.timestamp * 1e6),
                                    "fields": [
                                        {"key": k, "value": v}
                                        for k, v in event.attributes.items()
                                    ]
                                }
                                for event in span.events
                            ],
                        }
                        for span in trace.spans
                    ],
                }
                traces.append(trace_dict)

        return json.dumps({"data": traces}, indent=2)

    def set_trace_context(self, trace_id: str) -> None:
        """
        Set the trace context for the current thread.

        Args:
            trace_id: Trace ID to set.
        """
        self._local_context.trace_id = trace_id

    def clear_context(self) -> None:
        """Clear the thread-local context."""
        if hasattr(self._local_context, "trace_id"):
            delattr(self._local_context, "trace_id")
        if hasattr(self._local_context, "span_stack"):
            delattr(self._local_context, "span_stack")


# Global singleton tracer
_default_tracer: Optional[OTelTracer] = None


def setup_otel_tracer(service_name: str) -> OTelTracer:
    """
    Set up and return the default OpenTelemetry tracer.

    Args:
        service_name: Name of the service being traced.

    Returns:
        Global OTelTracer instance.
    """
    global _default_tracer
    _default_tracer = OTelTracer(service_name)
    return _default_tracer


def get_otel_tracer() -> OTelTracer:
    """
    Get the default OpenTelemetry tracer.

    Returns:
        Global OTelTracer instance, or creates one if not yet initialized.
    """
    global _default_tracer
    if _default_tracer is None:
        return setup_otel_tracer("default")
    return _default_tracer
