"""
Integration tests for runtime routing with tool metadata.

Tests the RuntimeRouter's ability to correctly route tools to
FastAPI or Trio runtime based on metadata and patterns.
"""

import pytest
from unittest.mock import Mock, patch
from ipfs_datasets_py.mcp_server.runtime_router import RuntimeRouter
from ipfs_datasets_py.mcp_server.tool_metadata import (
    ToolMetadata,
    tool_metadata,
    get_registry,
    RUNTIME_AUTO,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
)


class TestRuntimeRouterDetection:
    """Test RuntimeRouter detection logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.router = RuntimeRouter()
        # Clear registry
        get_registry().clear()

    def test_detect_runtime_from_metadata_registry(self):
        """Test detection from metadata registry."""
        # Register tool with Trio runtime
        @tool_metadata(runtime=RUNTIME_TRIO, requires_p2p=True)
        def p2p_submit_task():
            return "task_id"
        
        # Router should detect Trio runtime
        detected = self.router.detect_runtime(p2p_submit_task)
        assert detected == RUNTIME_TRIO

    def test_detect_runtime_from_function_attribute(self):
        """Test detection from function _mcp_runtime attribute."""
        def custom_tool():
            return "result"
        
        custom_tool._mcp_runtime = RUNTIME_TRIO  # type: ignore
        
        detected = self.router.detect_runtime(custom_tool)
        assert detected == RUNTIME_TRIO

    def test_detect_runtime_from_module_name(self):
        """Test detection from module name patterns."""
        # Mock function with trio module
        mock_func = Mock(__name__="test_func")
        mock_func.__module__ = "ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools"
        
        detected = self.router.detect_runtime(mock_func)
        assert detected == RUNTIME_TRIO

    def test_detect_runtime_from_function_name_p2p(self):
        """Test detection from p2p_* function name pattern."""
        def p2p_workflow_submit():
            return "workflow_id"
        
        detected = self.router.detect_runtime(p2p_workflow_submit)
        assert detected == RUNTIME_TRIO

    def test_detect_runtime_from_function_name_workflow(self):
        """Test detection from *workflow* function name pattern."""
        def submit_workflow():
            return "workflow_id"
        
        detected = self.router.detect_runtime(submit_workflow)
        assert detected == RUNTIME_TRIO

    def test_detect_runtime_from_function_name_taskqueue(self):
        """Test detection from *taskqueue* function name pattern."""
        def get_taskqueue_status():
            return {"status": "running"}
        
        detected = self.router.detect_runtime(get_taskqueue_status)
        assert detected == RUNTIME_TRIO

    def test_detect_runtime_default_fastapi(self):
        """Test that unknown tools default to FastAPI."""
        def generic_tool():
            return "result"
        
        detected = self.router.detect_runtime(generic_tool)
        assert detected == RUNTIME_FASTAPI

    def test_detect_runtime_priority_order(self):
        """Test that detection follows correct priority order."""
        # 1. Registry has highest priority
        @tool_metadata(runtime=RUNTIME_TRIO)
        def test_tool():
            return "result"
        
        # Even if function has conflicting attribute
        test_tool._mcp_runtime = RUNTIME_FASTAPI  # type: ignore
        
        # Registry should win
        detected = self.router.detect_runtime(test_tool)
        assert detected == RUNTIME_TRIO


class TestRuntimeRouterRegistration:
    """Test RuntimeRouter registration functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.router = RuntimeRouter()
        get_registry().clear()

    def test_register_from_metadata_single(self):
        """Test registering single tool from metadata."""
        @tool_metadata(runtime=RUNTIME_TRIO, category="test")
        def test_tool():
            return "result"
        
        # Register tools from metadata
        count = self.router.register_from_metadata()
        
        # At least our test tool should be registered
        assert count >= 1
        
        # Check cache
        cached_runtime = self.router._detection_cache.get("test_tool")
        assert cached_runtime == RUNTIME_TRIO

    def test_register_from_metadata_bulk(self):
        """Test bulk registration from metadata."""
        # Register multiple tools
        tools = []
        for i in range(10):
            @tool_metadata(runtime=RUNTIME_TRIO if i % 2 == 0 else RUNTIME_FASTAPI)
            def tool_func():
                return f"result_{i}"
            tool_func.__name__ = f"bulk_tool_{i}"
            tools.append(tool_func)
        
        # Register all
        count = self.router.register_from_metadata()
        
        # Should have registered all tools
        assert count >= 10

    def test_register_from_metadata_statistics(self):
        """Test registration statistics."""
        # Register some tools
        for i in range(5):
            @tool_metadata(runtime=RUNTIME_TRIO, category="p2p")
            def tool():
                return "result"
            tool.__name__ = f"p2p_tool_{i}"
        
        for i in range(3):
            @tool_metadata(runtime=RUNTIME_FASTAPI, category="general")
            def tool():
                return "result"
            tool.__name__ = f"general_tool_{i}"
        
        # Register and get stats
        self.router.register_from_metadata()
        stats = self.router.get_registry_stats()
        
        # Check stats
        assert "total" in stats
        assert "by_runtime" in stats
        assert stats["by_runtime"].get(RUNTIME_TRIO, 0) >= 5
        assert stats["by_runtime"].get(RUNTIME_FASTAPI, 0) >= 3


class TestRuntimeRouterCaching:
    """Test RuntimeRouter caching mechanism."""

    def setup_method(self):
        """Set up test fixtures."""
        self.router = RuntimeRouter()
        get_registry().clear()

    def test_cache_lookup_hit(self):
        """Test cache hit for previously detected tool."""
        def cached_tool():
            return "result"
        
        # First detection (cache miss)
        runtime1 = self.router.detect_runtime(cached_tool)
        
        # Second detection (cache hit)
        runtime2 = self.router.detect_runtime(cached_tool)
        
        assert runtime1 == runtime2
        assert "cached_tool" in self.router._detection_cache

    def test_cache_performance(self):
        """Test that caching improves performance."""
        import time
        
        @tool_metadata(runtime=RUNTIME_TRIO)
        def perf_tool():
            return "result"
        
        # First call (cache miss) - slower
        start1 = time.perf_counter()
        self.router.detect_runtime(perf_tool)
        time1 = time.perf_counter() - start1
        
        # Second call (cache hit) - faster
        start2 = time.perf_counter()
        self.router.detect_runtime(perf_tool)
        time2 = time.perf_counter() - start2
        
        # Cache hit should be faster (or at least not slower)
        assert time2 <= time1 * 1.1  # Allow 10% margin

    def test_cache_clear(self):
        """Test clearing the cache."""
        def tool1():
            return "result"
        
        # Populate cache
        self.router.detect_runtime(tool1)
        assert len(self.router._detection_cache) > 0
        
        # Clear cache
        self.router._detection_cache.clear()
        assert len(self.router._detection_cache) == 0


class TestRuntimeRouterMetrics:
    """Test RuntimeRouter metrics collection."""

    def setup_method(self):
        """Set up test fixtures."""
        self.router = RuntimeRouter()
        get_registry().clear()

    def test_metrics_collection_enabled(self):
        """Test that metrics are collected when enabled."""
        @tool_metadata(runtime=RUNTIME_TRIO)
        def metrics_tool():
            return "result"
        
        # Detect runtime (should record metric)
        self.router.detect_runtime(metrics_tool)
        
        # Check metrics
        metrics = self.router.get_metrics()
        assert "total_detections" in metrics
        assert metrics["total_detections"] >= 1

    def test_metrics_by_runtime(self):
        """Test metrics broken down by runtime."""
        @tool_metadata(runtime=RUNTIME_TRIO)
        def trio_tool():
            return "result"
        
        def fastapi_tool():
            return "result"
        
        # Detect both
        self.router.detect_runtime(trio_tool)
        self.router.detect_runtime(fastapi_tool)
        
        # Check metrics
        metrics = self.router.get_metrics()
        assert "by_runtime" in metrics
        assert metrics["by_runtime"].get(RUNTIME_TRIO, 0) >= 1
        assert metrics["by_runtime"].get(RUNTIME_FASTAPI, 0) >= 1


class TestRuntimeRouterEdgeCases:
    """Test edge cases and error handling."""

    def setup_method(self):
        """Set up test fixtures."""
        self.router = RuntimeRouter()
        get_registry().clear()

    def test_detect_runtime_none_function(self):
        """Test handling of None function."""
        # Should default to FastAPI or handle gracefully
        detected = self.router.detect_runtime(None)
        assert detected in [RUNTIME_FASTAPI, RUNTIME_AUTO]

    def test_detect_runtime_lambda(self):
        """Test detection for lambda functions."""
        lambda_func = lambda: "result"
        
        detected = self.router.detect_runtime(lambda_func)
        # Should default to FastAPI
        assert detected == RUNTIME_FASTAPI

    def test_detect_runtime_builtin(self):
        """Test detection for builtin functions."""
        # Should handle builtins gracefully
        detected = self.router.detect_runtime(print)
        assert detected in [RUNTIME_FASTAPI, RUNTIME_AUTO]

    def test_detect_runtime_class_method(self):
        """Test detection for class methods."""
        class TestClass:
            @tool_metadata(runtime=RUNTIME_TRIO)
            def method(self):
                return "result"
        
        obj = TestClass()
        detected = self.router.detect_runtime(obj.method)
        assert detected == RUNTIME_TRIO


class TestRuntimeRouterIntegration:
    """Integration tests with real tool patterns."""

    def setup_method(self):
        """Set up test fixtures."""
        self.router = RuntimeRouter()
        get_registry().clear()

    def test_p2p_taskqueue_tools(self):
        """Test routing for P2P taskqueue tools."""
        @tool_metadata(
            runtime=RUNTIME_TRIO,
            requires_p2p=True,
            category="p2p_taskqueue",
            priority=8
        )
        def task_submit(task_data: dict):
            return "task-123"
        
        @tool_metadata(
            runtime=RUNTIME_TRIO,
            requires_p2p=True,
            category="p2p_taskqueue",
            priority=7
        )
        def task_status(task_id: str):
            return {"status": "running"}
        
        # Both should route to Trio
        assert self.router.detect_runtime(task_submit) == RUNTIME_TRIO
        assert self.router.detect_runtime(task_status) == RUNTIME_TRIO

    def test_p2p_workflow_tools(self):
        """Test routing for P2P workflow tools."""
        @tool_metadata(
            runtime=RUNTIME_TRIO,
            requires_p2p=True,
            category="p2p_workflow",
            priority=9
        )
        def workflow_submit(workflow: dict):
            return "workflow-456"
        
        @tool_metadata(
            runtime=RUNTIME_TRIO,
            requires_p2p=True,
            category="p2p_workflow",
            priority=8
        )
        def workflow_dependencies(workflow_id: str):
            return []
        
        # Both should route to Trio
        assert self.router.detect_runtime(workflow_submit) == RUNTIME_TRIO
        assert self.router.detect_runtime(workflow_dependencies) == RUNTIME_TRIO

    def test_general_tools_fastapi(self):
        """Test that general tools route to FastAPI."""
        @tool_metadata(runtime=RUNTIME_FASTAPI, category="general")
        def dataset_load(name: str):
            return {"name": name}
        
        @tool_metadata(runtime=RUNTIME_FASTAPI, category="embedding")
        def embed_text(text: str):
            return [0.1, 0.2, 0.3]
        
        # Both should route to FastAPI
        assert self.router.detect_runtime(dataset_load) == RUNTIME_FASTAPI
        assert self.router.detect_runtime(embed_text) == RUNTIME_FASTAPI

    def test_mixed_runtime_routing(self):
        """Test routing with mixed runtimes."""
        tools = []
        
        # Register mix of tools
        for i in range(5):
            runtime = RUNTIME_TRIO if i % 2 == 0 else RUNTIME_FASTAPI
            
            @tool_metadata(runtime=runtime, category=f"cat_{i}")
            def tool():
                return f"result_{i}"
            tool.__name__ = f"mixed_tool_{i}"
            tools.append(tool)
        
        # Each should route to correct runtime
        for i, tool in enumerate(tools):
            expected = RUNTIME_TRIO if i % 2 == 0 else RUNTIME_FASTAPI
            assert self.router.detect_runtime(tool) == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
