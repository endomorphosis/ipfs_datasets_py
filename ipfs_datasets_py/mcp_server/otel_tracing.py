# ipfs_datasets_py/mcp_server/otel_tracing.py
"""
L54 — OpenTelemetry Tracing Integration
=========================================
Provides distributed tracing for MCP tool dispatches using the OpenTelemetry
(OTel) SDK.

When ``opentelemetry-api`` and ``opentelemetry-sdk`` are installed, calls are
wrapped in OTel spans and exported via the configured exporter (OTLP/gRPC or
OTLP/HTTP).  Without those packages the module degrades gracefully — all
span operations are no-ops.

Usage::

    from ipfs_datasets_py.mcp_server.otel_tracing import MCPTracer, configure_tracing

    # One-time setup (call at application start):
    configure_tracing(service_name="ipfs-mcp-server", otlp_endpoint="http://localhost:4317")

    # Wrap individual dispatches:
    tracer = MCPTracer()
    with tracer.start_dispatch_span("dataset_tools", "load_dataset", {"source": "squad"}) as span:
        result = await manager.dispatch("dataset_tools", "load_dataset", {"source": "squad"})
        tracer.set_span_ok(span, result)

    # Or use the context-manager decorator:
    @tracer.trace_tool_call
    async def load_my_dataset(...):
        ...
"""

from __future__ import annotations

import functools
import logging
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

try:
    from opentelemetry import trace as otel_trace  # type: ignore[import]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import]
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import]
    OTEL_AVAILABLE = True
except ImportError:
    otel_trace = None  # type: ignore[assignment]
    TracerProvider = None  # type: ignore[assignment]
    BatchSpanProcessor = None  # type: ignore[assignment]
    OTEL_AVAILABLE = False

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore[import]
    OTLP_GRPC_AVAILABLE = True
except ImportError:
    OTLPSpanExporter = None  # type: ignore[assignment]
    OTLP_GRPC_AVAILABLE = False

try:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OTLPHTTPSpanExporter  # type: ignore[import]
    OTLP_HTTP_AVAILABLE = True
except ImportError:
    OTLPHTTPSpanExporter = None  # type: ignore[assignment]
    OTLP_HTTP_AVAILABLE = False


# ---------------------------------------------------------------------------
# No-op span stub
# ---------------------------------------------------------------------------


class _NoOpSpan:
    """Inert span used when OpenTelemetry is not installed."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any, description: str = "") -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *_args: Any) -> None:
        pass


_NOOP_SPAN = _NoOpSpan()


# ---------------------------------------------------------------------------
# Global configuration
# ---------------------------------------------------------------------------

_tracer_provider: Optional[Any] = None


def configure_tracing(
    service_name: str = "ipfs-mcp-server",
    otlp_endpoint: Optional[str] = None,
    *,
    export_protocol: str = "grpc",
    insecure: bool = True,
) -> bool:
    """Configure the global OpenTelemetry tracer provider.

    Args:
        service_name:    Logical service name reported in traces.
        otlp_endpoint:   OTLP collector endpoint (e.g. ``"http://localhost:4317"``).
                         When ``None``, no exporter is registered (useful for
                         testing with a console exporter or noop).
        export_protocol: ``"grpc"`` (default) or ``"http"`` — selects the OTLP
                         transport.
        insecure:        Pass ``True`` to connect without TLS (typical in
                         development/local environments).

    Returns:
        ``True`` if the tracer provider was configured successfully, ``False``
        if the required packages are missing.
    """
    global _tracer_provider

    if not OTEL_AVAILABLE:
        logger.warning(
            "opentelemetry packages not installed; tracing disabled.  "
            "Run `pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-exporter-otlp-proto-grpc` to enable tracing."
        )
        return False

    from opentelemetry.sdk.resources import Resource  # type: ignore[import]

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint is not None:
        exporter = _build_exporter(otlp_endpoint, export_protocol, insecure)
        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter))

    otel_trace.set_tracer_provider(provider)
    _tracer_provider = provider
    logger.info("OpenTelemetry tracing configured (service=%s, endpoint=%s)", service_name, otlp_endpoint)
    return True


def _build_exporter(endpoint: str, protocol: str, insecure: bool) -> Optional[Any]:
    """Construct an OTLP exporter or return ``None`` on import failure."""
    if protocol == "grpc" and OTLP_GRPC_AVAILABLE:
        return OTLPSpanExporter(endpoint=endpoint, insecure=insecure)
    if protocol == "http" and OTLP_HTTP_AVAILABLE:
        return OTLPHTTPSpanExporter(endpoint=endpoint)
    logger.warning(
        "OTLP exporter for protocol=%r not available; no spans will be exported.", protocol
    )
    return None


# ---------------------------------------------------------------------------
# MCPTracer
# ---------------------------------------------------------------------------


class MCPTracer:
    """High-level tracing helper for MCP tool dispatches.

    Args:
        tracer_name: Name used to create the OTel tracer (default:
                     ``"ipfs_datasets_py.mcp_server"``).
    """

    def __init__(self, tracer_name: str = "ipfs_datasets_py.mcp_server") -> None:
        self.tracer_name = tracer_name
        self._tracer: Optional[Any] = None

    def _get_tracer(self) -> Any:
        """Lazily acquire the tracer from the global provider."""
        if not OTEL_AVAILABLE:
            return None
        if self._tracer is None:
            self._tracer = otel_trace.get_tracer(self.tracer_name)
        return self._tracer

    @contextmanager
    def start_dispatch_span(
        self,
        category: str,
        tool: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Generator[Any, None, None]:
        """Context manager that opens an OTel span for a single dispatch call.

        Span attributes set automatically:
        - ``mcp.category`` — tool category
        - ``mcp.tool`` — tool name
        - ``mcp.params_keys`` — comma-separated list of parameter key names

        Args:
            category: Tool category name.
            tool:     Tool name.
            params:   Call parameters dict (keys logged, values omitted for
                      privacy).

        Yields:
            The active span (OTel ``Span`` or :class:`_NoOpSpan`).
        """
        tracer = self._get_tracer()
        if tracer is None:
            yield _NOOP_SPAN
            return

        span_name = f"mcp.dispatch/{category}/{tool}"
        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("mcp.category", category)
            span.set_attribute("mcp.tool", tool)
            if params:
                span.set_attribute("mcp.params_keys", ",".join(sorted(params.keys())))
            try:
                yield span
            except BaseException as exc:
                # Catch all exceptions (including subclasses) to record them on
                # the span before re-raising.  This is intentional and standard
                # OpenTelemetry instrumentation pattern.
                span.record_exception(exc)
                if OTEL_AVAILABLE:
                    span.set_status(
                        otel_trace.StatusCode.ERROR,  # type: ignore[attr-defined]
                        description=str(exc),
                    )
                raise

    def set_span_ok(self, span: Any, result: Any = None) -> None:
        """Mark *span* as successful.

        Args:
            span:   The span returned by :meth:`start_dispatch_span`.
            result: Optional result dict — ``status`` key is recorded when present.
        """
        if OTEL_AVAILABLE and not isinstance(span, _NoOpSpan):
            span.set_status(otel_trace.StatusCode.OK)  # type: ignore[attr-defined]
            if isinstance(result, dict) and "status" in result:
                span.set_attribute("mcp.result.status", str(result["status"]))

    def trace_tool_call(self, func: Any) -> Any:
        """Decorator that wraps an async tool function with an OTel span.

        The decorated function must have ``category`` and ``tool`` as the
        first two positional parameters (or keyword arguments).

        Example::

            @tracer.trace_tool_call
            async def load_dataset(category: str, tool: str, params: dict):
                ...
        """
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Try to extract category/tool from positional or keyword args.
            category = (
                args[0] if len(args) > 0 else kwargs.get("category", "unknown")
            )
            tool = (
                args[1] if len(args) > 1 else kwargs.get("tool", "unknown")
            )
            params = (
                args[2] if len(args) > 2 else kwargs.get("params", {})
            )
            with self.start_dispatch_span(str(category), str(tool), params) as span:
                result = await func(*args, **kwargs)
                self.set_span_ok(span, result)
                return result

        return wrapper

    def get_info(self) -> Dict[str, Any]:
        """Return metadata about this tracer instance."""
        return {
            "tracer": "opentelemetry",
            "tracer_name": self.tracer_name,
            "otel_available": OTEL_AVAILABLE,
            "otlp_grpc_available": OTLP_GRPC_AVAILABLE,
            "otlp_http_available": OTLP_HTTP_AVAILABLE,
        }
