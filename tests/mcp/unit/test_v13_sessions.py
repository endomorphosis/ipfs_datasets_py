"""
v13 MCP Sessions — AO99 + AQ101 + AR102 + AS103 + AI93
=======================================================
Covers sessions from MASTER_IMPROVEMENT_PLAN_2026_v13.md:

  AO99: interface_descriptor.toolset_slice() budget enforcement (8 tests)
  AQ101: grpc_transport.py conformance — serialisation + params + info (12 tests)
  AR102: prometheus_exporter.py — metric names + cardinality + histogram (12 tests)
  AS103: otel_tracing.py — span attributes + context propagation + errors (10 tests)
  AI93: fastapi_service.py /datasets/* + /ipfs/* + /vectors/* (10 tests)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# ─── import guards ─────────────────────────────────────────────────────────────

try:
    from ipfs_datasets_py.mcp_server.interface_descriptor import (
        InterfaceDescriptor,
        InterfaceRepository,
        get_interface_repository,
        toolset_slice,
    )
    _IDL_OK = True
except Exception as _e:
    _IDL_OK = False
    _IDL_ERR = str(_e)

try:
    from ipfs_datasets_py.mcp_server.grpc_transport import (
        GRPCTransportAdapter,
        GRPCToolRequest,
        GRPCToolResponse,
        GRPC_AVAILABLE,
    )
    _GRPC_OK = True
except Exception as _e:
    _GRPC_OK = False

try:
    from ipfs_datasets_py.mcp_server.prometheus_exporter import (
        PrometheusExporter,
        PROMETHEUS_AVAILABLE,
        _make_counter,
        _make_gauge,
        _make_histogram,
    )
    _PROM_OK = True
except Exception as _e:
    _PROM_OK = False

try:
    from ipfs_datasets_py.mcp_server.otel_tracing import (
        MCPTracer,
        configure_tracing,
        OTEL_AVAILABLE,
        _NoOpSpan,
    )
    _OTEL_OK = True
except Exception as _e:
    _OTEL_OK = False

try:
    from fastapi.testclient import TestClient
    import os
    os.environ.setdefault("SECRET_KEY", "test-secret-key-session55")
    from ipfs_datasets_py.mcp_server.fastapi_service import app
    _FASTAPI_OK = True
except Exception as _e:
    _FASTAPI_OK = False
    _FASTAPI_ERR = str(_e)

# ─── helpers ──────────────────────────────────────────────────────────────────

_skip_no_idl = pytest.mark.skipif(not _IDL_OK, reason="interface_descriptor not importable")
_skip_no_grpc = pytest.mark.skipif(not _GRPC_OK, reason="grpc_transport not importable")
_skip_no_prom = pytest.mark.skipif(not _PROM_OK, reason="prometheus_exporter not importable")
_skip_no_otel = pytest.mark.skipif(not _OTEL_OK, reason="otel_tracing not importable")
_skip_no_fastapi = pytest.mark.skipif(not _FASTAPI_OK, reason=f"fastapi_service not importable")


def _make_descriptor(name: str, tags: list[str] | None = None) -> "InterfaceDescriptor":
    return InterfaceDescriptor(
        name=name,
        version="1.0.0",
        namespace="test",
        semantic_tags=tags or [name],
    )


# ══════════════════════════════════════════════════════════════════════════════
# AO99 — toolset_slice() budget enforcement
# ══════════════════════════════════════════════════════════════════════════════


@_skip_no_idl
class TestToolsetSlice:
    """Session AO99 — 8 tests."""

    def test_no_budget_returns_full_list(self):
        cids = ["sha256:aaa", "sha256:bbb", "sha256:ccc"]
        assert toolset_slice(cids) == cids

    def test_budget_truncates_list(self):
        cids = ["sha256:aaa", "sha256:bbb", "sha256:ccc"]
        assert toolset_slice(cids, budget=2) == ["sha256:aaa", "sha256:bbb"]

    def test_budget_larger_than_list_returns_full(self):
        cids = ["sha256:aaa", "sha256:bbb"]
        assert toolset_slice(cids, budget=10) == cids

    def test_budget_zero_returns_empty(self):
        cids = ["sha256:aaa", "sha256:bbb"]
        assert toolset_slice(cids, budget=0) == []

    def test_sort_fn_reranks_before_truncation(self):
        cids = ["sha256:zzz", "sha256:aaa", "sha256:mmm"]
        # sort alphabetically → aaa, mmm, zzz
        result = toolset_slice(cids, budget=2, sort_fn=lambda c: c)
        assert result == ["sha256:aaa", "sha256:mmm"]

    def test_sort_fn_none_preserves_input_order(self):
        cids = ["sha256:ccc", "sha256:aaa"]
        assert toolset_slice(cids, sort_fn=None) == cids

    def test_sort_fn_numeric_key(self):
        cids = ["sha256:c30", "sha256:a10", "sha256:b20"]
        # extract trailing number for sort
        result = toolset_slice(cids, budget=2, sort_fn=lambda c: int(c[-2:]))
        assert result[0] == "sha256:a10"
        assert result[1] == "sha256:b20"

    def test_integration_with_repo_select(self):
        """toolset_slice round-trip with InterfaceRepository.select()."""
        repo = InterfaceRepository()
        for tag in ("embed", "search", "store"):
            desc = _make_descriptor(tag, tags=[tag])
            repo.register(desc)
        scored = repo.select("embed search", budget=None)
        sliced = toolset_slice(scored, budget=1)
        assert len(sliced) == 1
        assert sliced[0] in scored


# ══════════════════════════════════════════════════════════════════════════════
# AQ101 — gRPC transport conformance
# ══════════════════════════════════════════════════════════════════════════════


@_skip_no_grpc
class TestGRPCToolRequestConformance:
    """Session AQ101 — GRPCToolRequest spec conformance (4 tests)."""

    def test_params_json_default_is_valid_json(self):
        req = GRPCToolRequest(category="cat", tool="tool")
        parsed = json.loads(req.params_json)
        assert isinstance(parsed, dict)

    def test_request_id_default_is_empty_string(self):
        req = GRPCToolRequest(category="cat", tool="tool")
        assert req.request_id == ""

    def test_all_slots_settable(self):
        req = GRPCToolRequest(
            category="dataset_tools",
            tool="load_dataset",
            params_json='{"source":"squad"}',
            request_id="req-123",
        )
        assert req.category == "dataset_tools"
        assert req.tool == "load_dataset"
        assert req.params_json == '{"source":"squad"}'
        assert req.request_id == "req-123"

    def test_serialization_roundtrip(self):
        params = {"source": "squad", "split": "train", "n": 100}
        req = GRPCToolRequest(
            category="cat",
            tool="tool",
            params_json=json.dumps(params),
            request_id="roundtrip",
        )
        recovered = json.loads(req.params_json)
        assert recovered == params


@_skip_no_grpc
class TestGRPCToolResponseConformance:
    """Session AQ101 — GRPCToolResponse spec conformance (4 tests)."""

    def test_success_response_has_non_empty_result_json(self):
        resp = GRPCToolResponse(success=True, result_json='{"status":"ok"}')
        assert resp.result_json
        assert json.loads(resp.result_json)

    def test_error_response_has_non_empty_error(self):
        resp = GRPCToolResponse(success=False, error="Tool not found")
        assert resp.error == "Tool not found"
        assert not resp.success

    def test_error_defaults_to_empty_when_success(self):
        resp = GRPCToolResponse(success=True, result_json="{}")
        assert resp.error == ""

    def test_request_id_echoed(self):
        resp = GRPCToolResponse(success=True, result_json="{}", request_id="abc-42")
        assert resp.request_id == "abc-42"


@_skip_no_grpc
class TestGRPCAdapterConformance:
    """Session AQ101 — GRPCTransportAdapter conformance (4 tests)."""

    def _make_adapter(self, dispatch_result: Any = None) -> "GRPCTransportAdapter":
        mgr = MagicMock()
        mgr.dispatch = AsyncMock(return_value=dispatch_result or {"status": "ok"})
        return GRPCTransportAdapter(mgr)

    @pytest.mark.asyncio
    async def test_handle_request_echoes_request_id(self):
        adapter = self._make_adapter()
        req = GRPCToolRequest(category="cat", tool="tool", request_id="echo-99")
        resp = await adapter.handle_request(req)
        assert resp.request_id == "echo-99"

    @pytest.mark.asyncio
    async def test_handle_request_nested_json_params(self):
        adapter = self._make_adapter({"result": "ok"})
        req = GRPCToolRequest(
            category="cat",
            tool="tool",
            params_json='{"nested":{"key":"value"}}',
        )
        resp = await adapter.handle_request(req)
        assert resp.success is True
        result = json.loads(resp.result_json)
        assert result["result"] == "ok"

    @pytest.mark.asyncio
    async def test_handle_request_empty_params_json_uses_empty_dict(self):
        adapter = self._make_adapter()
        req = GRPCToolRequest(category="cat", tool="tool", params_json="")
        resp = await adapter.handle_request(req)
        assert resp.success is True
        _, kwargs = adapter.manager.dispatch.call_args
        # params passed as positional arg, index 2
        call_args = adapter.manager.dispatch.call_args.args
        assert call_args[2] == {}  # empty params dict

    def test_get_info_has_required_spec_fields(self):
        adapter = self._make_adapter()
        info = adapter.get_info()
        for key in ("transport", "host", "port", "max_workers", "is_running"):
            assert key in info, f"Missing required field: {key}"
        assert info["transport"] == "grpc"


# ══════════════════════════════════════════════════════════════════════════════
# AR102 — Prometheus exporter deeper coverage
# ══════════════════════════════════════════════════════════════════════════════


@_skip_no_prom
class TestPrometheusMetricNames:
    """Session AR102 — metric name conventions (4 tests)."""

    def test_make_counter_returns_metric_object(self):
        counter = _make_counter("mcp_test_requests_total", "Test counter")
        assert counter is not None
        # Must not raise
        counter.inc()

    def test_make_gauge_returns_metric_object(self):
        gauge = _make_gauge("mcp_test_active_connections", "Test gauge")
        assert gauge is not None
        gauge.set(42.0)

    def test_make_histogram_with_default_buckets(self):
        hist = _make_histogram("mcp_test_duration_seconds", "Test histogram")
        assert hist is not None
        hist.observe(0.5)

    def test_make_histogram_with_custom_buckets(self):
        custom = [0.001, 0.01, 0.1, 1.0, 10.0]
        hist = _make_histogram(
            "mcp_test_custom_hist", "Custom histogram", buckets=custom
        )
        assert hist is not None
        hist.observe(0.5)


@_skip_no_prom
class TestPrometheusLabelCardinality:
    """Session AR102 — label cardinality and high-volume recording (4 tests)."""

    def test_record_tool_call_many_tools_no_raise(self):
        exporter = PrometheusExporter(port=29999)
        for i in range(50):
            exporter.record_tool_call(
                category="cat",
                tool=f"tool_{i}",
                status="success",
                latency_seconds=float(i) / 1000.0,
            )

    def test_record_tool_call_updates_success_and_error(self):
        exporter = PrometheusExporter(port=29998)
        exporter.record_tool_call("cat", "mytool", status="success", latency_seconds=0.01)
        exporter.record_tool_call("cat", "mytool", status="error", latency_seconds=0.005)
        # No crash — counters incremented internally

    def test_update_with_high_cardinality_snapshot_no_raise(self):
        collector = MagicMock()
        snapshot = {
            "tool_metrics": {
                "call_counts": {f"tool_{i}": i * 2 for i in range(30)},
                "error_counts": {f"tool_{i}": i for i in range(30)},
                "execution_times": {f"tool_{i}": [float(i)] for i in range(30)},
            },
            "request_metrics": {"total": 100, "errors": 5},
            "system_metrics": {},
        }
        collector.get_metrics_summary = MagicMock(return_value=snapshot)
        exporter = PrometheusExporter(collector=collector, port=29997)
        exporter.update()  # must not raise

    def test_get_info_returns_namespace_field(self):
        exporter = PrometheusExporter(namespace="ipfs_mcp", port=29996)
        info = exporter.get_info()
        assert "namespace" in info
        assert info["namespace"] == "ipfs_mcp"


@_skip_no_prom
class TestPrometheusHistogramBuckets:
    """Session AR102 — histogram bucket depth (4 tests)."""

    def test_update_with_execution_times_no_raise(self):
        collector = MagicMock()
        snapshot = {
            "tool_metrics": {
                "call_counts": {"load_dataset": 5},
                "error_counts": {"load_dataset": 1},
                "execution_times": {"load_dataset": [10.0, 20.0, 30.0]},
            },
            "request_metrics": {"total": 5, "errors": 1},
            "system_metrics": {},
        }
        collector.get_metrics_summary = MagicMock(return_value=snapshot)
        exporter = PrometheusExporter(collector=collector, port=29995)
        exporter.update()

    def test_update_with_missing_tool_metrics_no_raise(self):
        collector = MagicMock()
        snapshot = {
            "request_metrics": {"total": 0, "errors": 0},
            "system_metrics": {},
        }
        collector.get_metrics_summary = MagicMock(return_value=snapshot)
        exporter = PrometheusExporter(collector=collector, port=29994)
        exporter.update()

    def test_exporter_uptime_is_float(self):
        exporter = PrometheusExporter(port=29993)
        info = exporter.get_info()
        assert isinstance(info.get("uptime_seconds", 0.0), float)

    def test_prometheus_available_flag_is_bool(self):
        assert isinstance(PROMETHEUS_AVAILABLE, bool)


# ══════════════════════════════════════════════════════════════════════════════
# AS103 — OpenTelemetry tracing deeper coverage
# ══════════════════════════════════════════════════════════════════════════════


@_skip_no_otel
class TestOTelSpanAttributes:
    """Session AS103 — span attribute methods (4 tests)."""

    def test_start_dispatch_span_returns_span_with_set_attribute(self):
        tracer = MCPTracer()
        with tracer.start_dispatch_span("dataset_tools", "load_dataset", {}) as span:
            assert hasattr(span, "set_attribute")

    def test_noop_span_set_attribute_no_raise(self):
        span = _NoOpSpan()
        span.set_attribute("tool.name", "load_dataset")
        span.set_attribute("params.count", 3)

    def test_noop_span_set_status_no_raise(self):
        span = _NoOpSpan()
        span.set_status("OK", description="success")
        span.set_status("ERROR", description="failed")

    def test_noop_span_record_exception_no_raise(self):
        span = _NoOpSpan()
        span.record_exception(ValueError("test error"))
        span.record_exception(RuntimeError("another error"))


@_skip_no_otel
class TestOTelContextPropagation:
    """Session AS103 — context propagation and configuration (3 tests)."""

    def test_configure_tracing_returns_bool(self):
        result = configure_tracing(service_name="test-service")
        assert isinstance(result, bool)

    def test_mct_tracer_stores_custom_tracer_name(self):
        tracer = MCPTracer(tracer_name="my.custom.tracer")
        info = tracer.get_info()
        assert info.get("tracer_name") == "my.custom.tracer"

    def test_get_info_includes_otel_available(self):
        tracer = MCPTracer()
        info = tracer.get_info()
        assert "otel_available" in info
        assert info["otel_available"] == OTEL_AVAILABLE


@_skip_no_otel
class TestOTelDecoratorErrorPath:
    """Session AS103 — trace_tool_call decorator error paths (3 tests)."""

    @pytest.mark.asyncio
    async def test_decorator_reraises_exceptions(self):
        tracer = MCPTracer()

        @tracer.trace_tool_call
        async def failing_tool(cat: str, tool: str, params: dict) -> dict:
            raise RuntimeError("deliberate failure")

        with pytest.raises(RuntimeError, match="deliberate failure"):
            await failing_tool("cat", "tool", {})

    @pytest.mark.asyncio
    async def test_decorator_returns_result_on_success(self):
        tracer = MCPTracer()

        @tracer.trace_tool_call
        async def ok_tool(cat: str, tool: str, params: dict) -> dict:
            return {"status": "ok"}

        result = await ok_tool("cat", "tool", {})
        assert result == {"status": "ok"}

    def test_set_span_ok_none_result_no_raise(self):
        tracer = MCPTracer()
        span = _NoOpSpan()
        tracer.set_span_ok(span, result=None)


# ══════════════════════════════════════════════════════════════════════════════
# AI93 — fastapi_service.py /datasets/* + /ipfs/* + /vectors/*
# ══════════════════════════════════════════════════════════════════════════════


@_skip_no_fastapi
class TestFastapiDatasetRoutes:
    """Session AI93 — /datasets/* route auth + inner-module failure (5 tests)."""

    def _client(self) -> "TestClient":
        return TestClient(app, raise_server_exceptions=False)

    def _auth_headers(self, client: "TestClient") -> dict:
        resp = client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        if resp.status_code == 200:
            token = resp.json().get("access_token", "dummy-token")
            return {"Authorization": f"Bearer {token}"}
        return {"Authorization": "Bearer dummy-token"}

    def test_datasets_load_without_auth_returns_401(self):
        client = self._client()
        resp = client.post("/datasets/load", json={"source": "squad"})
        assert resp.status_code == 401

    def test_datasets_load_with_auth_returns_500(self):
        client = self._client()
        headers = self._auth_headers(client)
        resp = client.post(
            "/datasets/load",
            json={"source": "squad"},
            headers=headers,
        )
        assert resp.status_code == 500

    def test_datasets_process_with_auth_returns_500(self):
        client = self._client()
        headers = self._auth_headers(client)
        resp = client.post(
            "/datasets/process",
            json={"dataset_source": "squad", "operations": []},
            headers=headers,
        )
        assert resp.status_code == 500

    def test_datasets_save_with_auth_returns_500(self):
        client = self._client()
        headers = self._auth_headers(client)
        resp = client.post(
            "/datasets/save",
            json={"dataset_data": "squad", "destination": "/tmp/out"},
            headers=headers,
        )
        assert resp.status_code == 500

    def test_datasets_convert_with_auth_returns_500(self):
        """convert uses query params: dataset_id + target_format."""
        client = self._client()
        headers = self._auth_headers(client)
        resp = client.post(
            "/datasets/convert?dataset_id=ds-1&target_format=json",
            headers=headers,
        )
        assert resp.status_code == 500


@_skip_no_fastapi
class TestFastapiIPFSRoutes:
    """Session AI93 — /ipfs/* route auth + inner-module failure (3 tests)."""

    def _client(self) -> "TestClient":
        return TestClient(app, raise_server_exceptions=False)

    def _auth_headers(self, client: "TestClient") -> dict:
        resp = client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        if resp.status_code == 200:
            token = resp.json().get("access_token", "dummy-token")
            return {"Authorization": f"Bearer {token}"}
        return {"Authorization": "Bearer dummy-token"}

    def test_ipfs_pin_without_auth_returns_401(self):
        client = self._client()
        resp = client.post("/ipfs/pin", json={"content": "hello"})
        assert resp.status_code == 401

    def test_ipfs_pin_with_auth_returns_500(self):
        client = self._client()
        headers = self._auth_headers(client)
        resp = client.post(
            "/ipfs/pin",
            json={"content_source": "hello"},
            headers=headers,
        )
        assert resp.status_code == 500

    def test_ipfs_get_with_auth_returns_500(self):
        client = self._client()
        headers = self._auth_headers(client)
        resp = client.get("/ipfs/get/Qm123", headers=headers)
        assert resp.status_code == 500


@_skip_no_fastapi
class TestFastapiVectorRoutes:
    """Session AI93 — /vectors/* route auth + inner-module failure (2 tests)."""

    def _client(self) -> "TestClient":
        return TestClient(app, raise_server_exceptions=False)

    def _auth_headers(self, client: "TestClient") -> dict:
        resp = client.post(
            "/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        if resp.status_code == 200:
            token = resp.json().get("access_token", "dummy-token")
            return {"Authorization": f"Bearer {token}"}
        return {"Authorization": "Bearer dummy-token"}

    def test_vectors_create_index_with_auth_returns_500(self):
        """VectorIndexRequest requires: vectors (list of lists of floats)."""
        client = self._client()
        headers = self._auth_headers(client)
        resp = client.post(
            "/vectors/create-index",
            json={"vectors": [[0.1, 0.2], [0.3, 0.4]]},
            headers=headers,
        )
        assert resp.status_code == 500

    def test_vectors_search_with_auth_returns_500(self):
        """search_vector_index: index_id + top_k as query params, query_vector as JSON body."""
        client = self._client()
        headers = self._auth_headers(client)
        resp = client.post(
            "/vectors/search?index_id=idx-1&top_k=5",
            json={"query_vector": [0.1, 0.2]},
            headers=headers,
        )
        assert resp.status_code == 500
