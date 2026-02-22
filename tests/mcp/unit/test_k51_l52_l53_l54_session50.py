"""
K51 / L52-L54 — Adaptive batch sizing + ecosystem integration tests
=====================================================================
Covers:
  K51: dispatch_parallel max_concurrent parameter (adaptive batching)
  L52: GRPCTransportAdapter
  L53: PrometheusExporter
  L54: MCPTracer / configure_tracing / otel_tracing
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest
import anyio

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# ---------------------------------------------------------------------------
# Imports (graceful skip if heavy deps missing)
# ---------------------------------------------------------------------------

try:
    from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
        HierarchicalToolManager,
        ToolCategory,
    )
    HTM_AVAILABLE = True
except Exception:
    HTM_AVAILABLE = False

try:
    from ipfs_datasets_py.mcp_server.grpc_transport import (
        GRPCTransportAdapter,
        GRPCToolRequest,
        GRPCToolResponse,
        GRPC_AVAILABLE,
    )
    GRPC_MODULE_OK = True
except Exception:
    GRPC_MODULE_OK = False

try:
    from ipfs_datasets_py.mcp_server.prometheus_exporter import (
        PrometheusExporter,
        PROMETHEUS_AVAILABLE,
    )
    PROM_MODULE_OK = True
except Exception:
    PROM_MODULE_OK = False

try:
    from ipfs_datasets_py.mcp_server.otel_tracing import (
        MCPTracer,
        configure_tracing,
        OTEL_AVAILABLE,
        _NoOpSpan,
    )
    OTEL_MODULE_OK = True
except Exception:
    OTEL_MODULE_OK = False


# ===========================================================================
# K51 — adaptive batch sizing
# ===========================================================================

@pytest.mark.skipif(not HTM_AVAILABLE, reason="HierarchicalToolManager not importable")
class TestDispatchParallelAdaptiveBatch:
    """Tests for the max_concurrent parameter added in K51."""

    def _make_manager_with_echo(self):
        """Return a manager whose dispatch() immediately returns an echo dict."""
        from unittest.mock import AsyncMock, patch

        mgr = HierarchicalToolManager()

        async def _echo(category, tool, params):
            return {"status": "ok", "category": category, "tool": tool, "params": params}

        # Patch the underlying dispatch method to avoid needing real tool files
        mgr.dispatch = _echo
        return mgr

    def test_max_concurrent_none_is_default(self):
        """max_concurrent=None runs all calls at once (original behaviour)."""
        async def _run():
            mgr = self._make_manager_with_echo()
            calls = [
                {"category": "echo", "tool": "ping", "params": {"n": i}}
                for i in range(5)
            ]
            return await mgr.dispatch_parallel(calls, max_concurrent=None)

        results = asyncio.get_event_loop().run_until_complete(_run())
        assert len(results) == 5
        for i, r in enumerate(results):
            assert r["params"]["n"] == i

    def test_max_concurrent_1_processes_sequentially(self):
        """max_concurrent=1 processes one call at a time."""
        order = []

        async def _run():
            mgr = HierarchicalToolManager()

            async def _track(category, tool, params):
                order.append(params.get("n"))
                return {"status": "ok", "n": params.get("n")}

            mgr.dispatch = _track
            calls = [{"category": "seq", "tool": "fn", "params": {"n": i}} for i in range(4)]
            return await mgr.dispatch_parallel(calls, max_concurrent=1)

        results = asyncio.get_event_loop().run_until_complete(_run())
        assert len(results) == 4

    def test_max_concurrent_2_batches_of_2(self):
        """With max_concurrent=2 and 6 calls, 3 batches of 2 are processed."""
        async def _run():
            mgr = HierarchicalToolManager()

            async def _echo(cat, tool, params):
                return {"status": "ok", "idx": params.get("idx")}

            mgr.dispatch = _echo
            calls = [{"category": "b2", "tool": "fn", "params": {"idx": i}} for i in range(6)]
            return await mgr.dispatch_parallel(calls, max_concurrent=2)

        results = asyncio.get_event_loop().run_until_complete(_run())
        assert len(results) == 6

    def test_max_concurrent_larger_than_calls_runs_all_at_once(self):
        """max_concurrent >= len(calls) is equivalent to max_concurrent=None."""
        async def _run():
            mgr = HierarchicalToolManager()
            mgr.dispatch = AsyncMock(return_value={"status": "ok"})
            calls = [{"category": "big", "tool": "fn"} for _ in range(3)]
            return await mgr.dispatch_parallel(calls, max_concurrent=100)

        from unittest.mock import AsyncMock
        results = asyncio.get_event_loop().run_until_complete(_run())
        assert len(results) == 3

    def test_max_concurrent_preserves_order(self):
        """Results are returned in the same order as input calls regardless of batching."""
        async def _run():
            mgr = HierarchicalToolManager()

            async def _echo(cat, tool, params):
                await asyncio.sleep(0.001)
                return {"status": "ok", "idx": params["idx"]}

            mgr.dispatch = _echo
            calls = [{"category": "ord", "tool": "fn", "params": {"idx": i}} for i in range(8)]
            return await mgr.dispatch_parallel(calls, max_concurrent=3)

        results = asyncio.get_event_loop().run_until_complete(_run())
        for i, r in enumerate(results):
            assert r["idx"] == i

    def test_max_concurrent_with_errors_in_batch(self):
        """Errors within a batch are captured (return_exceptions=True)."""
        async def _run():
            mgr = HierarchicalToolManager()

            async def _fail(cat, tool, params):
                raise RuntimeError("boom")

            mgr.dispatch = _fail
            calls = [{"category": "err", "tool": "fail"} for _ in range(4)]
            return await mgr.dispatch_parallel(calls, max_concurrent=2, return_exceptions=True)

        results = asyncio.get_event_loop().run_until_complete(_run())
        assert len(results) == 4
        for r in results:
            assert r["status"] == "error"
            assert "boom" in r["error"]

    def test_empty_calls_returns_empty_list(self):
        """Empty call list returns [] regardless of max_concurrent."""
        async def _run():
            mgr = HierarchicalToolManager()
            return await mgr.dispatch_parallel([], max_concurrent=5)

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result == []


# ===========================================================================
# L52 — gRPC Transport Adapter
# ===========================================================================

@pytest.mark.skipif(not GRPC_MODULE_OK, reason="grpc_transport not importable")
class TestGRPCTransportAdapter:

    def _make_mock_manager(self):
        """Create a minimal mock manager that responds to dispatch."""
        class MockManager:
            async def dispatch(self, category, tool, params):
                return {"status": "ok", "category": category, "tool": tool, "params": params}
        return MockManager()

    def test_get_info_returns_dict(self):
        mgr = self._make_mock_manager()
        adapter = GRPCTransportAdapter(mgr, port=50051)
        info = adapter.get_info()
        assert info["transport"] == "grpc"
        assert info["port"] == 50051
        assert "grpc_available" in info

    def test_is_running_false_before_start(self):
        adapter = GRPCTransportAdapter(self._make_mock_manager())
        assert adapter.is_running is False

    def test_start_raises_import_error_when_grpc_unavailable(self):
        if GRPC_AVAILABLE:
            pytest.skip("grpcio is installed; cannot test ImportError path")
        adapter = GRPCTransportAdapter(self._make_mock_manager())
        with pytest.raises(ImportError, match="grpcio"):
            asyncio.get_event_loop().run_until_complete(adapter.start())

    def test_stop_when_not_started_is_safe(self):
        adapter = GRPCTransportAdapter(self._make_mock_manager())
        asyncio.get_event_loop().run_until_complete(adapter.stop())  # no error

    def test_handle_request_dispatches_to_manager(self):
        async def _run():
            mgr = self._make_mock_manager()
            adapter = GRPCTransportAdapter(mgr)
            req = GRPCToolRequest(
                category="dataset_tools",
                tool="load_dataset",
                params_json='{"source": "squad"}',
                request_id="req-001",
            )
            resp = await adapter.handle_request(req)
            return resp

        resp = asyncio.get_event_loop().run_until_complete(_run())
        assert resp.success is True
        assert resp.request_id == "req-001"
        data = json.loads(resp.result_json)
        assert data["category"] == "dataset_tools"

    def test_handle_request_bad_json_returns_error(self):
        async def _run():
            adapter = GRPCTransportAdapter(self._make_mock_manager())
            req = GRPCToolRequest(category="x", tool="y", params_json="NOT_JSON")
            return await adapter.handle_request(req)

        resp = asyncio.get_event_loop().run_until_complete(_run())
        assert resp.success is False
        assert "Invalid params JSON" in resp.error

    def test_handle_request_manager_exception_returns_error(self):
        async def _run():
            class FailManager:
                async def dispatch(self, *a, **kw):
                    raise RuntimeError("db offline")
            adapter = GRPCTransportAdapter(FailManager())
            req = GRPCToolRequest(category="x", tool="y", request_id="r2")
            return await adapter.handle_request(req)

        resp = asyncio.get_event_loop().run_until_complete(_run())
        assert resp.success is False
        assert "db offline" in resp.error
        assert resp.request_id == "r2"

    def test_grpc_tool_request_defaults(self):
        req = GRPCToolRequest("cat", "tool")
        assert req.params_json == "{}"
        assert req.request_id == ""

    def test_grpc_tool_response_defaults(self):
        resp = GRPCToolResponse()
        assert resp.success is True
        assert resp.error == ""

    def test_adapter_custom_host(self):
        adapter = GRPCTransportAdapter(self._make_mock_manager(), host="127.0.0.1", port=9999)
        info = adapter.get_info()
        assert info["host"] == "127.0.0.1"
        assert info["port"] == 9999


# ===========================================================================
# L53 — Prometheus Exporter
# ===========================================================================

@pytest.mark.skipif(not PROM_MODULE_OK, reason="prometheus_exporter not importable")
class TestPrometheusExporter:

    def test_get_info_returns_dict(self):
        exp = PrometheusExporter(port=9090)
        info = exp.get_info()
        assert info["exporter"] == "prometheus"
        assert info["port"] == 9090
        assert "prometheus_available" in info

    def test_start_http_server_raises_when_unavailable(self):
        if PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client is installed; cannot test ImportError path")
        exp = PrometheusExporter()
        with pytest.raises(ImportError, match="prometheus-client"):
            exp.start_http_server()

    def test_stop_http_server_when_not_started(self):
        exp = PrometheusExporter()
        exp.stop_http_server()  # no error

    def test_http_server_running_false_before_start(self):
        exp = PrometheusExporter()
        assert exp.get_info()["http_server_running"] is False

    def test_record_tool_call_does_not_raise(self):
        exp = PrometheusExporter()
        exp.record_tool_call("dataset_tools", "load_dataset", "success", 0.042)
        exp.record_tool_call("graph_tools", "query", "error", 1.5)

    def test_update_with_no_collector_does_not_raise(self):
        exp = PrometheusExporter(collector=None)
        exp.update()  # no error

    def test_update_with_mock_collector(self):
        class MockCollector:
            def get_snapshot(self):
                return {
                    "error_rate": 0.05,
                    "active_connections": 3,
                    "system_metrics": {"cpu_percent": 42.0, "memory_percent": 60.0},
                }
        exp = PrometheusExporter(collector=MockCollector())
        exp.update()  # no error

    def test_update_with_collector_error_does_not_raise(self):
        class BadCollector:
            def get_snapshot(self):
                raise RuntimeError("collector crashed")
        exp = PrometheusExporter(collector=BadCollector())
        exp.update()  # swallows the error

    def test_uptime_increases_over_time(self):
        exp = PrometheusExporter()
        t1 = exp.get_info()["uptime_seconds"]
        time.sleep(0.01)
        t2 = exp.get_info()["uptime_seconds"]
        assert t2 > t1

    def test_custom_namespace(self):
        exp = PrometheusExporter(namespace="myns")
        assert exp.namespace == "myns"

    def test_update_collector_with_get_current_metrics_fallback(self):
        """Falls back to get_current_metrics when get_snapshot absent."""
        class AltCollector:
            def get_current_metrics(self):
                return {"error_rate": 0.1}
        exp = PrometheusExporter(collector=AltCollector())
        exp.update()  # no error


# ===========================================================================
# L54 — OpenTelemetry Tracing
# ===========================================================================

@pytest.mark.skipif(not OTEL_MODULE_OK, reason="otel_tracing not importable")
class TestOTelTracing:

    def test_configure_tracing_returns_false_when_unavailable(self):
        if OTEL_AVAILABLE:
            pytest.skip("opentelemetry installed; cannot test False path")
        result = configure_tracing("test-service")
        assert result is False

    def test_mct_tracer_get_info(self):
        tracer = MCPTracer()
        info = tracer.get_info()
        assert info["tracer"] == "opentelemetry"
        assert "otel_available" in info

    def test_start_dispatch_span_returns_noop_when_unavailable(self):
        if OTEL_AVAILABLE:
            pytest.skip("opentelemetry installed")
        tracer = MCPTracer()
        with tracer.start_dispatch_span("cat", "tool", {"k": "v"}) as span:
            assert isinstance(span, _NoOpSpan)

    def test_noop_span_context_manager(self):
        span = _NoOpSpan()
        with span:
            span.set_attribute("foo", "bar")
            span.set_status(None, "ok")
            span.record_exception(ValueError("test"))

    def test_set_span_ok_noop_span_does_not_raise(self):
        tracer = MCPTracer()
        span = _NoOpSpan()
        tracer.set_span_ok(span, {"status": "ok"})

    def test_start_dispatch_span_no_params(self):
        tracer = MCPTracer()
        with tracer.start_dispatch_span("cat", "tool") as span:
            pass  # should not raise

    def test_start_dispatch_span_re_raises_exception(self):
        tracer = MCPTracer()
        with pytest.raises(RuntimeError, match="boom"):
            with tracer.start_dispatch_span("cat", "tool") as span:
                raise RuntimeError("boom")

    def test_trace_tool_call_decorator_async(self):
        tracer = MCPTracer()

        @tracer.trace_tool_call
        async def my_func(category, tool, params):
            return {"status": "ok", "category": category}

        async def _run():
            return await my_func("dataset_tools", "load_dataset", {"source": "x"})

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result["status"] == "ok"
        assert result["category"] == "dataset_tools"

    def test_trace_tool_call_decorator_propagates_exception(self):
        tracer = MCPTracer()

        @tracer.trace_tool_call
        async def bad_func(category, tool, params):
            raise ValueError("intentional")

        async def _run():
            await bad_func("cat", "tool", {})

        with pytest.raises(ValueError, match="intentional"):
            asyncio.get_event_loop().run_until_complete(_run())

    def test_custom_tracer_name(self):
        tracer = MCPTracer(tracer_name="my.custom.tracer")
        assert tracer.tracer_name == "my.custom.tracer"
        info = tracer.get_info()
        assert info["tracer_name"] == "my.custom.tracer"

    def test_noop_span_labels(self):
        span = _NoOpSpan()
        assert span.__enter__() is span
        span.__exit__(None, None, None)
        span.end()
