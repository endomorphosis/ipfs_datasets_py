"""
Unit tests for RuntimeRouter.

Tests runtime detection, routing logic, metrics collection,
and lifecycle management.

Author: MCP Server Test Team
Date: 2026-02-18
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from ipfs_datasets_py.mcp_server.runtime_router import (
    RuntimeRouter,
    RuntimeMetrics,
    create_router,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
    RUNTIME_AUTO,
    RUNTIME_UNKNOWN,
)
from ipfs_datasets_py.mcp_server.tool_metadata import (
    ToolMetadata,
    ToolMetadataRegistry,
    tool_metadata,
)


class TestRuntimeMetrics:
    """Test RuntimeMetrics dataclass."""

    def test_metrics_initialization(self):
        """
        GIVEN: No parameters
        WHEN: Creating RuntimeMetrics
        THEN: Default values are set
        """
        metrics = RuntimeMetrics()
        
        assert metrics.request_count == 0
        assert metrics.error_count == 0
        assert metrics.total_latency_ms == 0.0
        assert metrics.min_latency_ms == float('inf')
        assert metrics.max_latency_ms == 0.0
        assert len(metrics.latencies) == 0

    def test_metrics_record_request_success(self):
        """
        GIVEN: RuntimeMetrics instance
        WHEN: Recording successful request
        THEN: Metrics are updated correctly
        """
        metrics = RuntimeMetrics()
        metrics.record_request(100.0, error=False)
        
        assert metrics.request_count == 1
        assert metrics.error_count == 0
        assert metrics.total_latency_ms == 100.0
        assert metrics.min_latency_ms == 100.0
        assert metrics.max_latency_ms == 100.0
        assert len(metrics.latencies) == 1

    def test_metrics_record_request_error(self):
        """
        GIVEN: RuntimeMetrics instance
        WHEN: Recording failed request
        THEN: Error count is incremented
        """
        metrics = RuntimeMetrics()
        metrics.record_request(150.0, error=True)
        
        assert metrics.request_count == 1
        assert metrics.error_count == 1

    def test_metrics_record_multiple_requests(self):
        """
        GIVEN: RuntimeMetrics instance
        WHEN: Recording multiple requests
        THEN: Statistics are calculated correctly
        """
        metrics = RuntimeMetrics()
        metrics.record_request(50.0)
        metrics.record_request(100.0)
        metrics.record_request(150.0)
        
        assert metrics.request_count == 3
        assert metrics.min_latency_ms == 50.0
        assert metrics.max_latency_ms == 150.0
        assert metrics.avg_latency_ms == 100.0

    def test_metrics_avg_latency_empty(self):
        """
        GIVEN: Empty RuntimeMetrics
        WHEN: Getting average latency
        THEN: Returns 0.0
        """
        metrics = RuntimeMetrics()
        assert metrics.avg_latency_ms == 0.0

    def test_metrics_p95_latency(self):
        """
        GIVEN: RuntimeMetrics with latency data
        WHEN: Getting 95th percentile
        THEN: Correct value returned
        """
        metrics = RuntimeMetrics()
        for i in range(1, 101):
            metrics.record_request(float(i))
        
        p95 = metrics.p95_latency_ms
        assert 94 <= p95 <= 96

    def test_metrics_p99_latency(self):
        """
        GIVEN: RuntimeMetrics with latency data
        WHEN: Getting 99th percentile
        THEN: Correct value returned
        """
        metrics = RuntimeMetrics()
        for i in range(1, 101):
            metrics.record_request(float(i))
        
        p99 = metrics.p99_latency_ms
        assert 98 <= p99 <= 100

    def test_metrics_latencies_bounded(self):
        """
        GIVEN: RuntimeMetrics instance
        WHEN: Recording >1000 requests
        THEN: Only last 1000 latencies kept
        """
        metrics = RuntimeMetrics()
        for i in range(1500):
            metrics.record_request(float(i))
        
        assert len(metrics.latencies) == 1000
        assert metrics.latencies[0] >= 500.0

    def test_metrics_to_dict(self):
        """
        GIVEN: RuntimeMetrics with data
        WHEN: Converting to dictionary
        THEN: All statistics included
        """
        metrics = RuntimeMetrics()
        metrics.record_request(100.0)
        metrics.record_request(200.0, error=True)
        
        data = metrics.to_dict()
        
        assert data["request_count"] == 2
        assert data["error_count"] == 1
        assert data["avg_latency_ms"] == 150.0
        assert data["min_latency_ms"] == 100.0
        assert data["max_latency_ms"] == 200.0
        assert "p95_latency_ms" in data
        assert "p99_latency_ms" in data


class TestRuntimeRouterInit:
    """Test RuntimeRouter initialization."""

    def test_router_init_default(self):
        """
        GIVEN: No parameters
        WHEN: Creating RuntimeRouter
        THEN: Default values are set
        """
        router = RuntimeRouter()
        
        assert router.default_runtime == RUNTIME_FASTAPI
        assert router.enable_metrics is True
        assert router.enable_memory_tracking is False
        assert router._is_running is False

    def test_router_init_custom_runtime(self):
        """
        GIVEN: Custom default runtime
        WHEN: Creating RuntimeRouter
        THEN: Custom runtime is set
        """
        router = RuntimeRouter(default_runtime=RUNTIME_TRIO)
        assert router.default_runtime == RUNTIME_TRIO

    def test_router_init_metrics_disabled(self):
        """
        GIVEN: Metrics disabled
        WHEN: Creating RuntimeRouter
        THEN: Metrics collection disabled
        """
        router = RuntimeRouter(enable_metrics=False)
        assert router.enable_metrics is False

    def test_router_init_memory_tracking_enabled(self):
        """
        GIVEN: Memory tracking enabled
        WHEN: Creating RuntimeRouter
        THEN: Memory tracking enabled
        """
        router = RuntimeRouter(enable_memory_tracking=True)
        assert router.enable_memory_tracking is True

    def test_router_init_custom_registry(self):
        """
        GIVEN: Custom metadata registry
        WHEN: Creating RuntimeRouter
        THEN: Custom registry is used
        """
        custom_registry = ToolMetadataRegistry()
        router = RuntimeRouter(metadata_registry=custom_registry)
        assert router._metadata_registry is custom_registry


class TestRuntimeRouterLifecycle:
    """Test RuntimeRouter startup and shutdown."""

    @pytest.mark.asyncio
    async def test_router_startup_success(self):
        """
        GIVEN: Initialized router
        WHEN: Starting up router
        THEN: Router is running
        """
        router = RuntimeRouter()
        await router.startup()
        
        assert router._is_running is True
        
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_router_startup_twice(self, caplog):
        """
        GIVEN: Running router
        WHEN: Starting up again
        THEN: Warning is logged
        """
        router = RuntimeRouter()
        await router.startup()
        await router.startup()
        
        assert "already running" in caplog.text.lower()
        
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_router_shutdown_success(self):
        """
        GIVEN: Running router
        WHEN: Shutting down
        THEN: Router is stopped
        """
        router = RuntimeRouter()
        await router.startup()
        await router.shutdown()
        
        assert router._is_running is False

    @pytest.mark.asyncio
    async def test_router_shutdown_not_running(self):
        """
        GIVEN: Non-running router
        WHEN: Shutting down
        THEN: No error occurs
        """
        router = RuntimeRouter()
        await router.shutdown()
        
        assert router._is_running is False

    @pytest.mark.asyncio
    async def test_router_context_manager(self):
        """
        GIVEN: RuntimeRouter
        WHEN: Using as async context manager
        THEN: Properly starts and stops
        """
        router = RuntimeRouter()
        
        async with router.runtime_context() as r:
            assert r._is_running is True
        
        assert router._is_running is False


class TestRuntimeDetection:
    """Test runtime detection logic."""

    def test_detect_runtime_cached(self):
        """
        GIVEN: Tool already in cache
        WHEN: Detecting runtime
        THEN: Cached value is returned
        """
        router = RuntimeRouter()
        router._tool_runtimes["cached_tool"] = RUNTIME_TRIO
        
        def dummy_func():
            pass
        
        runtime = router.detect_runtime("cached_tool", dummy_func)
        assert runtime == RUNTIME_TRIO

    def test_detect_runtime_from_metadata_registry(self):
        """
        GIVEN: Tool registered in metadata registry
        WHEN: Detecting runtime
        THEN: Registry value is used
        """
        registry = ToolMetadataRegistry()
        metadata = ToolMetadata(name="registry_tool", runtime=RUNTIME_TRIO)
        registry.register(metadata)
        
        router = RuntimeRouter(metadata_registry=registry)
        
        def dummy_func():
            pass
        
        runtime = router.detect_runtime("registry_tool", dummy_func)
        assert runtime == RUNTIME_TRIO

    def test_detect_runtime_from_function_attribute(self):
        """
        GIVEN: Function with _mcp_runtime attribute
        WHEN: Detecting runtime
        THEN: Function attribute is used
        """
        router = RuntimeRouter()
        
        def func_with_runtime():
            pass
        func_with_runtime._mcp_runtime = RUNTIME_TRIO
        
        # Use a name that doesn't match any patterns
        runtime = router.detect_runtime("custom_tool", func_with_runtime)
        assert runtime == RUNTIME_TRIO

    def test_detect_runtime_from_module_name_mcplusplus(self):
        """
        GIVEN: Function from mcplusplus module
        WHEN: Detecting runtime
        THEN: Trio runtime is selected
        """
        router = RuntimeRouter()
        
        def mock_func():
            pass
        mock_func.__module__ = "ipfs_datasets_py.mcp_server.mcplusplus.workflow"
        
        runtime = router.detect_runtime("workflow_tool", mock_func)
        assert runtime == RUNTIME_TRIO

    def test_detect_runtime_from_module_name_trio(self):
        """
        GIVEN: Function from trio module
        WHEN: Detecting runtime
        THEN: Trio runtime is selected
        """
        router = RuntimeRouter()
        
        def mock_func():
            pass
        mock_func.__module__ = "ipfs_datasets_py.mcp_server.trio_adapter"
        
        runtime = router.detect_runtime("trio_tool", mock_func)
        assert runtime == RUNTIME_TRIO

    def test_detect_runtime_from_name_pattern_p2p(self):
        """
        GIVEN: Tool name with 'p2p_' prefix
        WHEN: Detecting runtime
        THEN: Trio runtime is selected
        """
        router = RuntimeRouter()
        
        def mock_func():
            pass
        
        runtime = router.detect_runtime("p2p_workflow_submit", mock_func)
        assert runtime == RUNTIME_TRIO

    def test_detect_runtime_from_name_pattern_workflow(self):
        """
        GIVEN: Tool name with 'workflow' in it
        WHEN: Detecting runtime
        THEN: Trio runtime is selected
        """
        router = RuntimeRouter()
        
        def mock_func():
            pass
        
        runtime = router.detect_runtime("submit_workflow", mock_func)
        assert runtime == RUNTIME_TRIO

    def test_detect_runtime_from_name_pattern_taskqueue(self):
        """
        GIVEN: Tool name with 'taskqueue' in it
        WHEN: Detecting runtime
        THEN: Trio runtime is selected
        """
        router = RuntimeRouter()
        
        def mock_func():
            pass
        
        runtime = router.detect_runtime("taskqueue_submit", mock_func)
        assert runtime == RUNTIME_TRIO

    def test_detect_runtime_default_fallback(self):
        """
        GIVEN: Tool with no runtime hints
        WHEN: Detecting runtime
        THEN: Default runtime is used
        """
        router = RuntimeRouter(default_runtime=RUNTIME_FASTAPI)
        
        def plain_func():
            pass
        
        runtime = router.detect_runtime("plain_tool", plain_func)
        assert runtime == RUNTIME_FASTAPI

    def test_detect_runtime_caches_result(self):
        """
        GIVEN: Tool without cached runtime
        WHEN: Detecting runtime
        THEN: Result is cached for next call
        """
        router = RuntimeRouter()
        
        def mock_func():
            pass
        
        router.detect_runtime("test_tool", mock_func)
        assert "test_tool" in router._tool_runtimes


class TestToolRegistration:
    """Test tool runtime registration."""

    def test_register_tool_runtime_fastapi(self):
        """
        GIVEN: Tool name and FastAPI runtime
        WHEN: Registering tool runtime
        THEN: Tool is registered
        """
        router = RuntimeRouter()
        router.register_tool_runtime("test_tool", RUNTIME_FASTAPI)
        
        assert router._tool_runtimes["test_tool"] == RUNTIME_FASTAPI

    def test_register_tool_runtime_trio(self):
        """
        GIVEN: Tool name and Trio runtime
        WHEN: Registering tool runtime
        THEN: Tool is registered
        """
        router = RuntimeRouter()
        router.register_tool_runtime("test_tool", RUNTIME_TRIO)
        
        assert router._tool_runtimes["test_tool"] == RUNTIME_TRIO

    def test_register_tool_runtime_invalid(self):
        """
        GIVEN: Invalid runtime
        WHEN: Registering tool runtime
        THEN: ValueError is raised
        """
        router = RuntimeRouter()
        
        with pytest.raises(ValueError, match="Invalid runtime"):
            router.register_tool_runtime("test_tool", "invalid")

    def test_get_tool_runtime(self):
        """
        GIVEN: Registered tool
        WHEN: Getting tool runtime
        THEN: Registered runtime is returned
        """
        router = RuntimeRouter()
        router.register_tool_runtime("test_tool", RUNTIME_TRIO)
        
        runtime = router.get_tool_runtime("test_tool")
        assert runtime == RUNTIME_TRIO

    def test_get_tool_runtime_not_registered(self):
        """
        GIVEN: Unregistered tool
        WHEN: Getting tool runtime
        THEN: None is returned
        """
        router = RuntimeRouter()
        runtime = router.get_tool_runtime("nonexistent_tool")
        assert runtime is None

    def test_list_tools_by_runtime(self):
        """
        GIVEN: Multiple registered tools
        WHEN: Listing tools by runtime
        THEN: Only tools for that runtime returned
        """
        router = RuntimeRouter()
        router.register_tool_runtime("tool1", RUNTIME_FASTAPI)
        router.register_tool_runtime("tool2", RUNTIME_TRIO)
        router.register_tool_runtime("tool3", RUNTIME_FASTAPI)
        
        fastapi_tools = router.list_tools_by_runtime(RUNTIME_FASTAPI)
        trio_tools = router.list_tools_by_runtime(RUNTIME_TRIO)
        
        assert len(fastapi_tools) == 2
        assert len(trio_tools) == 1
        assert "tool1" in fastapi_tools
        assert "tool3" in fastapi_tools
        assert "tool2" in trio_tools

    def test_bulk_register_tools_from_metadata(self):
        """
        GIVEN: Tools in metadata registry
        WHEN: Bulk registering from metadata
        THEN: All tools are registered
        """
        registry = ToolMetadataRegistry()
        registry.register(ToolMetadata(name="tool1", runtime=RUNTIME_FASTAPI))
        registry.register(ToolMetadata(name="tool2", runtime=RUNTIME_TRIO))
        registry.register(ToolMetadata(name="tool3", runtime=RUNTIME_AUTO))
        
        router = RuntimeRouter(metadata_registry=registry)
        count = router.bulk_register_tools_from_metadata()
        
        assert count == 2  # AUTO is not registered
        assert router.get_tool_runtime("tool1") == RUNTIME_FASTAPI
        assert router.get_tool_runtime("tool2") == RUNTIME_TRIO


class TestToolRouting:
    """Test tool call routing."""

    @pytest.mark.asyncio
    async def test_route_tool_call_not_started(self):
        """
        GIVEN: Router not started
        WHEN: Routing tool call
        THEN: RuntimeError is raised
        """
        router = RuntimeRouter()
        
        async def dummy_tool():
            return "result"
        
        with pytest.raises(RuntimeError, match="not started"):
            await router.route_tool_call("test_tool", dummy_tool)

    @pytest.mark.asyncio
    async def test_route_tool_call_to_fastapi_async(self):
        """
        GIVEN: Async tool with FastAPI runtime
        WHEN: Routing tool call
        THEN: Tool is executed successfully
        """
        router = RuntimeRouter(default_runtime=RUNTIME_FASTAPI)
        await router.startup()
        
        async def async_tool():
            return "async_result"
        
        result = await router.route_tool_call("test_tool", async_tool)
        
        assert result == "async_result"
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_route_tool_call_to_fastapi_sync(self):
        """
        GIVEN: Sync tool with FastAPI runtime
        WHEN: Routing tool call
        THEN: Tool is executed in thread pool
        """
        router = RuntimeRouter(default_runtime=RUNTIME_FASTAPI)
        await router.startup()
        
        def sync_tool():
            return "sync_result"
        
        result = await router.route_tool_call("test_tool", sync_tool)
        
        assert result == "sync_result"
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_route_tool_call_with_args_kwargs(self):
        """
        GIVEN: Tool with arguments
        WHEN: Routing tool call with args and kwargs
        THEN: Tool receives arguments correctly
        """
        router = RuntimeRouter()
        await router.startup()
        
        async def tool_with_args(a, b, c=None):
            return f"{a}-{b}-{c}"
        
        result = await router.route_tool_call(
            "test_tool", tool_with_args, "arg1", "arg2", c="kwarg1"
        )
        
        assert result == "arg1-arg2-kwarg1"
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_route_tool_call_error_propagates(self):
        """
        GIVEN: Tool that raises error
        WHEN: Routing tool call
        THEN: Error is propagated and metrics updated
        """
        router = RuntimeRouter()
        await router.startup()
        
        async def failing_tool():
            raise ValueError("Tool error")
        
        with pytest.raises(ValueError, match="Tool error"):
            await router.route_tool_call("failing_tool", failing_tool)
        
        metrics = router.get_metrics()
        assert metrics[RUNTIME_FASTAPI]["error_count"] == 1
        
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_route_tool_call_metrics_collected(self):
        """
        GIVEN: Router with metrics enabled
        WHEN: Routing tool call
        THEN: Metrics are collected
        """
        router = RuntimeRouter(enable_metrics=True)
        await router.startup()
        
        async def test_tool():
            await asyncio.sleep(0.01)
            return "result"
        
        await router.route_tool_call("test_tool", test_tool)
        
        metrics = router.get_metrics()
        assert metrics[RUNTIME_FASTAPI]["request_count"] == 1
        assert metrics[RUNTIME_FASTAPI]["avg_latency_ms"] > 0
        
        await router.shutdown()


class TestMetricsCollection:
    """Test metrics collection and reporting."""

    @pytest.mark.asyncio
    async def test_get_metrics_empty(self):
        """
        GIVEN: New router
        WHEN: Getting metrics
        THEN: Empty metrics returned
        """
        router = RuntimeRouter()
        metrics = router.get_metrics()
        
        assert metrics[RUNTIME_FASTAPI]["request_count"] == 0
        assert metrics[RUNTIME_TRIO]["request_count"] == 0

    @pytest.mark.asyncio
    async def test_get_runtime_stats(self):
        """
        GIVEN: Router with executed tools
        WHEN: Getting runtime stats
        THEN: Aggregate stats returned
        """
        router = RuntimeRouter()
        await router.startup()
        
        async def test_tool():
            return "result"
        
        await router.route_tool_call("tool1", test_tool)
        await router.route_tool_call("tool2", test_tool)
        
        stats = router.get_runtime_stats()
        
        assert stats["total_requests"] == 2
        assert stats["total_errors"] == 0
        assert RUNTIME_FASTAPI in stats["by_runtime"]
        
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_reset_metrics(self):
        """
        GIVEN: Router with collected metrics
        WHEN: Resetting metrics
        THEN: All metrics cleared
        """
        router = RuntimeRouter()
        await router.startup()
        
        async def test_tool():
            return "result"
        
        await router.route_tool_call("test_tool", test_tool)
        router.reset_metrics()
        
        metrics = router.get_metrics()
        assert metrics[RUNTIME_FASTAPI]["request_count"] == 0
        
        await router.shutdown()

    def test_get_metadata_registry_stats(self):
        """
        GIVEN: Router with metadata registry
        WHEN: Getting registry stats
        THEN: Statistics returned
        """
        registry = ToolMetadataRegistry()
        registry.register(ToolMetadata(name="tool1", runtime=RUNTIME_FASTAPI))
        
        router = RuntimeRouter(metadata_registry=registry)
        stats = router.get_metadata_registry_stats()
        
        assert stats is not None
        assert stats["total_tools"] == 1


class TestCreateRouter:
    """Test convenience create_router function."""

    @pytest.mark.asyncio
    async def test_create_router_default(self):
        """
        GIVEN: No parameters
        WHEN: Creating router via create_router
        THEN: Router is created and started
        """
        router = await create_router()
        
        assert router._is_running is True
        assert router.default_runtime == RUNTIME_FASTAPI
        
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_create_router_custom(self):
        """
        GIVEN: Custom parameters
        WHEN: Creating router via create_router
        THEN: Custom router is created and started
        """
        router = await create_router(
            default_runtime=RUNTIME_TRIO,
            enable_metrics=False
        )
        
        assert router._is_running is True
        assert router.default_runtime == RUNTIME_TRIO
        assert router.enable_metrics is False
        
        await router.shutdown()


class TestRouterRepr:
    """Test RuntimeRouter string representation."""

    def test_router_repr(self):
        """
        GIVEN: RuntimeRouter instance
        WHEN: Getting string representation
        THEN: Informative string returned
        """
        router = RuntimeRouter(default_runtime=RUNTIME_TRIO)
        router.register_tool_runtime("tool1", RUNTIME_TRIO)
        router.register_tool_runtime("tool2", RUNTIME_FASTAPI)
        
        repr_str = repr(router)
        
        assert "RuntimeRouter" in repr_str
        assert "default=trio" in repr_str
        assert "running=False" in repr_str
        assert "tools=2" in repr_str
