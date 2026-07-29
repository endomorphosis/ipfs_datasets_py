"""OpenTelemetry-compatible metrics and traces for KG operations (KGP-032).

Provides an in-process tracer and metrics registry that:

* Works without the optional ``opentelemetry`` SDK installed.
* Optionally bridges to real OTel when available.
* Scrubs sensitive labels via :mod:`redact`.
"""

from __future__ import annotations

import statistics
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from .redact import safe_labels, scrub_for_telemetry

TELEMETRY_SCHEMA_VERSION = "kg-ops-telemetry/v1"
DEFAULT_SERVICE_NAME = "knowledge-graphs"


class SpanStatus(str, Enum):
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


@dataclass
class SpanEvent:
    name: str
    timestamp: float
    attributes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "timestamp": self.timestamp,
            "attributes": dict(self.attributes),
        }


@dataclass
class Span:
    name: str
    span_id: str
    trace_id: str
    parent_span_id: Optional[str]
    start_time: float
    end_time: Optional[float] = None
    status: SpanStatus = SpanStatus.UNSET
    attributes: Dict[str, str] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)

    def duration_ms(self) -> float:
        end = self.end_time if self.end_time is not None else time.time()
        return max(0.0, (end - self.start_time) * 1000.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status.value,
            "duration_ms": self.duration_ms(),
            "attributes": dict(self.attributes),
            "events": [e.to_dict() for e in self.events],
        }


@dataclass
class CounterPoint:
    name: str
    value: float
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class HistogramPoint:
    name: str
    count: int
    sum: float
    samples: List[float] = field(default_factory=list)
    labels: Dict[str, str] = field(default_factory=dict)

    def quantile(self, q: float) -> Optional[float]:
        if not self.samples:
            return None
        ordered = sorted(self.samples)
        if len(ordered) == 1:
            return ordered[0]
        # Inclusive rank for stable small-sample p95.
        idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return ordered[idx]


class OpsMetrics:
    """Thread-safe counter / histogram registry with Prometheus text export."""

    def __init__(self, *, max_histogram_samples: int = 2_048) -> None:
        self._lock = threading.RLock()
        self._counters: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        self._histograms: Dict[
            Tuple[str, Tuple[Tuple[str, str], ...]], HistogramPoint
        ] = {}
        self._gauges: Dict[Tuple[str, Tuple[Tuple[str, str], ...]], float] = {}
        self._max_histogram_samples = max_histogram_samples

    @staticmethod
    def _key(
        name: str, labels: Optional[Mapping[str, Any]]
    ) -> Tuple[str, Tuple[Tuple[str, str], ...]]:
        safe = safe_labels(labels)
        items = tuple(sorted(safe.items()))
        return name, items

    def inc(
        self,
        name: str,
        value: float = 1.0,
        *,
        labels: Optional[Mapping[str, Any]] = None,
    ) -> None:
        with self._lock:
            key = self._key(name, labels)
            self._counters[key] = self._counters.get(key, 0.0) + float(value)

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: Optional[Mapping[str, Any]] = None,
    ) -> None:
        with self._lock:
            key = self._key(name, labels)
            self._gauges[key] = float(value)

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: Optional[Mapping[str, Any]] = None,
    ) -> None:
        with self._lock:
            key = self._key(name, labels)
            point = self._histograms.get(key)
            if point is None:
                point = HistogramPoint(
                    name=name, count=0, sum=0.0, labels=dict(safe_labels(labels))
                )
                self._histograms[key] = point
            point.count += 1
            point.sum += float(value)
            point.samples.append(float(value))
            if len(point.samples) > self._max_histogram_samples:
                point.samples = point.samples[-self._max_histogram_samples :]

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            counters = [
                {
                    "name": name,
                    "value": value,
                    "labels": dict(labels),
                }
                for (name, labels), value in sorted(self._counters.items())
            ]
            gauges = [
                {
                    "name": name,
                    "value": value,
                    "labels": dict(labels),
                }
                for (name, labels), value in sorted(self._gauges.items())
            ]
            histograms = []
            for (name, labels), point in sorted(self._histograms.items()):
                histograms.append(
                    {
                        "name": name,
                        "count": point.count,
                        "sum": point.sum,
                        "p50": point.quantile(0.50),
                        "p95": point.quantile(0.95),
                        "p99": point.quantile(0.99),
                        "labels": dict(labels),
                    }
                )
            return {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "counters": counters,
                "gauges": gauges,
                "histograms": histograms,
            }

    def export_prometheus(self) -> str:
        """Render a Prometheus text exposition (no external dependency)."""
        lines: List[str] = []
        snap = self.snapshot()
        for c in snap["counters"]:
            label_str = _prom_labels(c["labels"])
            lines.append(f'{c["name"]}{label_str} {c["value"]}')
        for g in snap["gauges"]:
            label_str = _prom_labels(g["labels"])
            lines.append(f'{g["name"]}{label_str} {g["value"]}')
        for h in snap["histograms"]:
            label_str = _prom_labels(h["labels"])
            base = h["name"]
            lines.append(f"{base}_count{label_str} {h['count']}")
            lines.append(f"{base}_sum{label_str} {h['sum']}")
            if h["p95"] is not None:
                qlabels = dict(h["labels"])
                qlabels["quantile"] = "0.95"
                lines.append(f"{base}{_prom_labels(qlabels)} {h['p95']}")
        return "\n".join(lines) + ("\n" if lines else "")

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()


def _prom_labels(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    parts = [f'{k}="{_escape_prom(v)}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(parts) + "}"


def _escape_prom(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class OpsTracer:
    """In-process OpenTelemetry-style tracer with optional real OTel bridge."""

    def __init__(self, service_name: str = DEFAULT_SERVICE_NAME) -> None:
        self.service_name = service_name
        self._lock = threading.RLock()
        self._local = threading.local()
        self._spans: List[Span] = []
        self._max_spans = 5_000
        self._otel_tracer = _try_load_otel_tracer(service_name)

    def _stack(self) -> List[str]:
        stack = getattr(self._local, "span_stack", None)
        if stack is None:
            stack = []
            self._local.span_stack = stack
        return stack

    def _current_trace_id(self) -> str:
        tid = getattr(self._local, "trace_id", None)
        if not tid:
            tid = uuid.uuid4().hex
            self._local.trace_id = tid
        return tid

    def start_span(
        self,
        name: str,
        attributes: Optional[Mapping[str, Any]] = None,
        *,
        parent_span_id: Optional[str] = None,
    ) -> Span:
        with self._lock:
            stack = self._stack()
            parent = parent_span_id or (stack[-1] if stack else None)
            span = Span(
                name=name,
                span_id=uuid.uuid4().hex[:16],
                trace_id=self._current_trace_id(),
                parent_span_id=parent,
                start_time=time.time(),
                attributes=safe_labels(attributes),
            )
            stack.append(span.span_id)
            self._spans.append(span)
            if len(self._spans) > self._max_spans:
                self._spans = self._spans[-self._max_spans :]
            # Optional real OTel bridge (best-effort).
            if self._otel_tracer is not None:
                try:
                    otel_span = self._otel_tracer.start_span(name)
                    for k, v in span.attributes.items():
                        otel_span.set_attribute(k, v)
                    span.attributes["_otel_bridged"] = "true"
                    setattr(self._local, f"otel_{span.span_id}", otel_span)
                except Exception:
                    pass
            return span

    def end_span(self, span: Span, status: SpanStatus = SpanStatus.OK) -> None:
        with self._lock:
            span.end_time = time.time()
            span.status = status
            stack = self._stack()
            if stack and stack[-1] == span.span_id:
                stack.pop()
            elif span.span_id in stack:
                stack.remove(span.span_id)
            otel_span = getattr(self._local, f"otel_{span.span_id}", None)
            if otel_span is not None:
                try:
                    otel_span.end()
                except Exception:
                    pass
                try:
                    delattr(self._local, f"otel_{span.span_id}")
                except Exception:
                    pass

    def add_event(
        self,
        span: Span,
        name: str,
        attributes: Optional[Mapping[str, Any]] = None,
    ) -> None:
        span.events.append(
            SpanEvent(
                name=name,
                timestamp=time.time(),
                attributes=safe_labels(attributes),
            )
        )

    def record_exception(self, span: Span, exc: BaseException) -> None:
        self.add_event(
            span,
            "exception",
            {
                "exception.type": type(exc).__name__,
                "exception.message": str(exc)[:256],
            },
        )
        span.status = SpanStatus.ERROR

    @contextmanager
    def span(
        self,
        name: str,
        attributes: Optional[Mapping[str, Any]] = None,
    ) -> Iterator[Span]:
        active = self.start_span(name, attributes)
        try:
            yield active
            if active.status == SpanStatus.UNSET:
                self.end_span(active, SpanStatus.OK)
            else:
                self.end_span(active, active.status)
        except Exception as exc:
            self.record_exception(active, exc)
            self.end_span(active, SpanStatus.ERROR)
            raise

    def completed_spans(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [s.to_dict() for s in self._spans if s.end_time is not None]

    def all_spans(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [s.to_dict() for s in self._spans]

    def reset(self) -> None:
        with self._lock:
            self._spans.clear()
            self._local.span_stack = []
            self._local.trace_id = None


def _try_load_otel_tracer(service_name: str) -> Any:
    try:
        from opentelemetry import trace  # type: ignore
        from opentelemetry.sdk.resources import Resource  # type: ignore
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore

        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name})
        )
        trace.set_tracer_provider(provider)
        return trace.get_tracer(service_name)
    except Exception:
        return None


@dataclass
class OpsTelemetry:
    """Bundled metrics + tracer used by health and diagnostics surfaces."""

    service_name: str = DEFAULT_SERVICE_NAME
    metrics: OpsMetrics = field(default_factory=OpsMetrics)
    tracer: OpsTracer = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tracer is None:
            self.tracer = OpsTracer(self.service_name)

    def record_operation(
        self,
        operation: str,
        duration_ms: float,
        *,
        success: bool = True,
        labels: Optional[Mapping[str, Any]] = None,
    ) -> None:
        base = {"operation": operation, "status": "ok" if success else "error"}
        if labels:
            base.update(dict(labels))
        self.metrics.inc("kg_ops_operations_total", labels=base)
        self.metrics.observe(
            "kg_ops_operation_duration_ms", duration_ms, labels={"operation": operation}
        )

    def export(self) -> Dict[str, Any]:
        return {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "service_name": self.service_name,
            "metrics": self.metrics.snapshot(),
            "spans": self.tracer.completed_spans()[-100:],
        }


# Process-wide default used by health/diagnostics when none is injected.
_DEFAULT_TELEMETRY: Optional[OpsTelemetry] = None
_DEFAULT_LOCK = threading.Lock()


def get_default_telemetry() -> OpsTelemetry:
    global _DEFAULT_TELEMETRY
    with _DEFAULT_LOCK:
        if _DEFAULT_TELEMETRY is None:
            _DEFAULT_TELEMETRY = OpsTelemetry()
        return _DEFAULT_TELEMETRY


def reset_default_telemetry() -> None:
    global _DEFAULT_TELEMETRY
    with _DEFAULT_LOCK:
        if _DEFAULT_TELEMETRY is not None:
            _DEFAULT_TELEMETRY.metrics.reset()
            _DEFAULT_TELEMETRY.tracer.reset()
        _DEFAULT_TELEMETRY = OpsTelemetry()


__all__ = [
    "DEFAULT_SERVICE_NAME",
    "OpsMetrics",
    "OpsTelemetry",
    "OpsTracer",
    "Span",
    "SpanEvent",
    "SpanStatus",
    "TELEMETRY_SCHEMA_VERSION",
    "get_default_telemetry",
    "reset_default_telemetry",
    "scrub_for_telemetry",
]
