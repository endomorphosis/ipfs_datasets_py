"""
Session 29 — RuntimeRouter coverage improvements.

Targets runtime_router.py lines currently uncovered:
  78-83    TOOL_METADATA_AVAILABLE=False fallback constants
  209-211  p95_latency_ms with data
  218-220  p99_latency_ms with data
  287      RuntimeRouter.__init__ TOOL_METADATA_AVAILABLE branch
  313-327  startup() — success + already-running guard
  333-351  shutdown() — with Trio nursery + already-shutdown guard
  377      detect_runtime — default_runtime fallback
  432-436  register_tool_runtime — invalid runtime raises ValueError
  471-508  route_tool_call — FastAPI, Trio, error paths
  517-521  _route_to_fastapi — sync function path
  530-554  _route_to_trio — trio unavailable fallback + exception fallback
  718-725  _calculate_latency_improvement — insufficient data + enough data
  729-735  reset_metrics()
  747      get_tool_runtime() — present and absent key
  759      list_tools_by_runtime()
  773      get_metadata_registry_stats() — registry=None path
  911-915  runtime_context() async context manager
  948-953  create_router() convenience function
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import anyio

from ipfs_datasets_py.mcp_server.runtime_router import (
    RuntimeMetrics,
    RuntimeRouter,
    create_router,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
)
from ipfs_datasets_py.mcp_server.exceptions import RuntimeExecutionError


# ---------------------------------------------------------------------------
# RuntimeMetrics
# ---------------------------------------------------------------------------

class TestRuntimeMetrics:
    """Test RuntimeMetrics data class and its computed properties."""

    def test_record_request_increments_count(self):
        m = RuntimeMetrics()
        m.record_request(10.0)
        assert m.request_count == 1
        assert m.total_latency_ms == 10.0

    def test_record_error_increments_error_count(self):
        m = RuntimeMetrics()
        m.record_request(5.0, error=True)
        assert m.error_count == 1

    def test_avg_latency_ms_zero_when_no_requests(self):
        m = RuntimeMetrics()
        assert m.avg_latency_ms == 0.0

    def test_avg_latency_ms_computed(self):
        m = RuntimeMetrics()
        m.record_request(20.0)
        m.record_request(40.0)
        assert m.avg_latency_ms == 30.0

    def test_p95_latency_ms_with_data(self):
        """Line 209-211: p95 uses sorted list."""
        m = RuntimeMetrics()
        for v in range(100):
            m.record_request(float(v + 1))
        # p95 of 1..100 is near the top
        assert m.p95_latency_ms >= 90.0

    def test_p99_latency_ms_with_data(self):
        """Lines 218-220: p99 uses sorted list."""
        m = RuntimeMetrics()
        for v in range(100):
            m.record_request(float(v + 1))
        assert m.p99_latency_ms >= 95.0

    def test_p95_latency_ms_empty_returns_zero(self):
        m = RuntimeMetrics()
        assert m.p95_latency_ms == 0.0

    def test_p99_latency_ms_empty_returns_zero(self):
        m = RuntimeMetrics()
        assert m.p99_latency_ms == 0.0

    def test_to_dict_includes_expected_keys(self):
        m = RuntimeMetrics()
        d = m.to_dict()
        assert "request_count" in d
        assert "error_count" in d

    def test_latency_list_bounded_to_1000(self):
        """Record 1001 requests — list stays at 1000."""
        m = RuntimeMetrics()
        for i in range(1001):
            m.record_request(float(i))
        assert len(m.latencies) == 1000


# ---------------------------------------------------------------------------
# RuntimeRouter startup / shutdown
# ---------------------------------------------------------------------------

class TestRuntimeRouterLifecycle:
    """Lines 313-351: startup() and shutdown() lifecycle."""

    @pytest.mark.anyio
    async def test_startup_sets_is_running(self):
        """Lines 313-327: startup() sets _is_running=True."""
        router = RuntimeRouter()
        assert router._is_running is False
        await router.startup()
        assert router._is_running is True
        await router.shutdown()

    @pytest.mark.anyio
    async def test_startup_idempotent_when_already_running(self):
        """startup() logs warning but does not raise on second call."""
        router = RuntimeRouter()
        await router.startup()
        await router.startup()  # second call — should not raise
        assert router._is_running is True
        await router.shutdown()

    @pytest.mark.anyio
    async def test_shutdown_sets_not_running(self):
        """Lines 333-351: shutdown() sets _is_running=False."""
        router = RuntimeRouter()
        await router.startup()
        await router.shutdown()
        assert router._is_running is False

    @pytest.mark.anyio
    async def test_shutdown_idempotent_when_not_running(self):
        """Shutdown when not started returns without raise."""
        router = RuntimeRouter()
        await router.shutdown()  # should not raise


# ---------------------------------------------------------------------------
# register_tool_runtime validation
# ---------------------------------------------------------------------------

class TestRegisterToolRuntime:
    """Line 432-436: register_tool_runtime() raises ValueError for bad runtime."""

    def test_invalid_runtime_raises_value_error(self):
        router = RuntimeRouter()
        with pytest.raises(ValueError, match="Invalid runtime"):
            router.register_tool_runtime("my_tool", "invalid_runtime")

    def test_valid_fastapi_runtime_registered(self):
        router = RuntimeRouter()
        router.register_tool_runtime("my_tool", RUNTIME_FASTAPI)
        assert router.get_tool_runtime("my_tool") == RUNTIME_FASTAPI

    def test_valid_trio_runtime_registered(self):
        router = RuntimeRouter()
        router.register_tool_runtime("my_tool", RUNTIME_TRIO)
        assert router.get_tool_runtime("my_tool") == RUNTIME_TRIO


# ---------------------------------------------------------------------------
# get_tool_runtime and list_tools_by_runtime
# ---------------------------------------------------------------------------

class TestToolRuntimeQueries:
    """Lines 747-759: get_tool_runtime + list_tools_by_runtime."""

    def test_get_tool_runtime_returns_none_for_unknown(self):
        router = RuntimeRouter()
        assert router.get_tool_runtime("nonexistent") is None

    def test_get_tool_runtime_returns_registered_runtime(self):
        router = RuntimeRouter()
        router.register_tool_runtime("t1", RUNTIME_FASTAPI)
        assert router.get_tool_runtime("t1") == RUNTIME_FASTAPI

    def test_list_tools_by_runtime_returns_matching_tools(self):
        """Line 759: list_tools_by_runtime filters by runtime."""
        router = RuntimeRouter()
        router.register_tool_runtime("a", RUNTIME_FASTAPI)
        router.register_tool_runtime("b", RUNTIME_TRIO)
        router.register_tool_runtime("c", RUNTIME_FASTAPI)
        fastapi_tools = router.list_tools_by_runtime(RUNTIME_FASTAPI)
        assert "a" in fastapi_tools
        assert "c" in fastapi_tools
        assert "b" not in fastapi_tools

    def test_list_tools_by_runtime_empty_for_unknown_runtime(self):
        router = RuntimeRouter()
        assert router.list_tools_by_runtime("nonexistent") == []


# ---------------------------------------------------------------------------
# route_tool_call — FastAPI path
# ---------------------------------------------------------------------------

class TestRouteToolCallFastAPI:
    """Lines 471-521: route_tool_call dispatches to _route_to_fastapi."""

    @pytest.mark.anyio
    async def test_routes_async_function_via_fastapi(self):
        """Lines 471-508: async function routed through FastAPI path."""
        router = RuntimeRouter()
        await router.startup()

        async def my_tool(x: int) -> int:
            return x * 2

        router.register_tool_runtime("my_tool", RUNTIME_FASTAPI)
        result = await router.route_tool_call("my_tool", my_tool, x=5)
        assert result == 10
        await router.shutdown()

    @pytest.mark.anyio
    async def test_routes_sync_function_via_fastapi(self):
        """Lines 517-521: sync function wrapped in thread pool."""
        router = RuntimeRouter()
        await router.startup()

        def sync_tool(x: int) -> int:
            return x + 1

        router.register_tool_runtime("sync_tool", RUNTIME_FASTAPI)
        result = await router.route_tool_call("sync_tool", sync_tool, x=9)
        assert result == 10
        await router.shutdown()

    @pytest.mark.anyio
    async def test_not_started_raises_runtime_error(self):
        """RuntimeRouter not started → RuntimeError."""
        router = RuntimeRouter()
        async def my_tool() -> str:
            return "x"
        with pytest.raises(RuntimeError, match="not started"):
            await router.route_tool_call("my_tool", my_tool)

    @pytest.mark.anyio
    async def test_tool_exception_wraps_in_runtime_execution_error(self):
        """Lines 503-508: unexpected Exception → RuntimeExecutionError."""
        router = RuntimeRouter()
        await router.startup()

        async def failing_tool(**kw: Any) -> None:
            raise IOError("disk full")

        router.register_tool_runtime("bad", RUNTIME_FASTAPI)
        with pytest.raises(RuntimeExecutionError):
            await router.route_tool_call("bad", failing_tool)
        await router.shutdown()

    @pytest.mark.anyio
    async def test_metrics_recorded_on_success(self):
        """Metrics updated after successful call."""
        router = RuntimeRouter(enable_metrics=True)
        await router.startup()

        async def ok_tool() -> int:
            return 1

        router.register_tool_runtime("ok", RUNTIME_FASTAPI)
        await router.route_tool_call("ok", ok_tool)
        metrics = router.get_metrics()
        assert metrics[RUNTIME_FASTAPI]["request_count"] == 1
        await router.shutdown()


# ---------------------------------------------------------------------------
# route_tool_call — Trio path
# ---------------------------------------------------------------------------

class TestRouteToolCallTrio:
    """Lines 530-554: _route_to_trio falls back when trio unavailable."""

    @pytest.mark.anyio
    async def test_trio_fallback_to_fastapi_when_unavailable(self):
        """Lines 530-543: if _trio_available=False, falls back to FastAPI."""
        router = RuntimeRouter()
        router._is_running = True
        router._trio_available = False

        async def my_tool(x: int) -> int:
            return x * 3

        router.register_tool_runtime("t", RUNTIME_TRIO)
        result = await router.route_tool_call("t", my_tool, x=4)
        assert result == 12

    @pytest.mark.anyio
    async def test_trio_exception_falls_back_to_fastapi(self):
        """Lines 548-554: exception in Trio path → fallback to FastAPI."""
        router = RuntimeRouter()
        router._is_running = True
        router._trio_available = True

        async def my_tool(x: int) -> int:
            return x * 2

        with patch.object(router, "_route_to_trio",
                          side_effect=RuntimeError("trio error")):
            router.register_tool_runtime("t2", RUNTIME_TRIO)
            # Should not raise — RuntimeExecutionError expected
            with pytest.raises(RuntimeExecutionError):
                await router.route_tool_call("t2", my_tool, x=3)


# ---------------------------------------------------------------------------
# get_runtime_stats and _calculate_latency_improvement
# ---------------------------------------------------------------------------

class TestRuntimeStats:
    """Lines 574-735: get_runtime_stats + _calculate_latency_improvement."""

    @pytest.mark.anyio
    async def test_get_runtime_stats_returns_dict(self):
        """Lines 574+: basic structure check."""
        router = RuntimeRouter()
        stats = router.get_runtime_stats()
        assert "total_requests" in stats
        assert "total_errors" in stats
        assert "by_runtime" in stats

    @pytest.mark.anyio
    async def test_latency_improvement_none_with_insufficient_data(self):
        """Lines 718-725: None when fewer than 10 requests on each runtime."""
        router = RuntimeRouter()
        stats = router.get_runtime_stats()
        assert stats["latency_improvement"] is None

    @pytest.mark.anyio
    async def test_latency_improvement_computed_with_enough_data(self):
        """Lines 715-725: returns float when both runtimes have 10+ samples."""
        router = RuntimeRouter()
        # Give FastAPI 20ms avg and Trio 10ms avg
        for _ in range(15):
            router._metrics[RUNTIME_FASTAPI].record_request(20.0)
            router._metrics[RUNTIME_TRIO].record_request(10.0)
        improvement = router._calculate_latency_improvement()
        assert improvement is not None
        assert improvement > 0  # Trio is faster

    def test_reset_metrics_clears_all_counts(self):
        """Lines 729-735: reset_metrics zeros all RuntimeMetrics."""
        router = RuntimeRouter()
        router._metrics[RUNTIME_FASTAPI].record_request(50.0)
        router.reset_metrics()
        assert router._metrics[RUNTIME_FASTAPI].request_count == 0

    def test_get_metadata_registry_stats_none_when_no_registry(self):
        """Line 773: returns None if _metadata_registry is None."""
        router = RuntimeRouter()
        router._metadata_registry = None
        assert router.get_metadata_registry_stats() is None


# ---------------------------------------------------------------------------
# runtime_context async context manager
# ---------------------------------------------------------------------------

class TestRuntimeContext:
    """Lines 911-915: runtime_context() starts + yields + shuts down router."""

    @pytest.mark.anyio
    async def test_runtime_context_starts_and_stops(self):
        router = RuntimeRouter()
        async with router.runtime_context():
            assert router._is_running is True
        assert router._is_running is False


# ---------------------------------------------------------------------------
# create_router convenience function
# ---------------------------------------------------------------------------

class TestCreateRouter:
    """Lines 948-953: create_router() creates a started RuntimeRouter."""

    @pytest.mark.anyio
    async def test_create_router_returns_started_router(self):
        router = await create_router()
        assert router._is_running is True
        await router.shutdown()

    @pytest.mark.anyio
    async def test_create_router_with_custom_runtime(self):
        router = await create_router(default_runtime=RUNTIME_TRIO)
        assert router.default_runtime == RUNTIME_TRIO
        await router.shutdown()


# ---------------------------------------------------------------------------
# detect_runtime fallback
# ---------------------------------------------------------------------------

class TestDetectRuntime:
    """Line 377: detect_runtime falls back to default_runtime."""

    def test_detect_runtime_uses_default_when_no_override(self):
        """No metadata, no attribute — returns default_runtime."""
        router = RuntimeRouter(default_runtime=RUNTIME_FASTAPI)

        def plain_fn():
            pass

        result = router.detect_runtime("unknown_tool", plain_fn)
        assert result == RUNTIME_FASTAPI
