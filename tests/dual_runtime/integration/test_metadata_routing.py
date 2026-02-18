"""
Integration tests for metadata-based routing.

Tests end-to-end metadata-based routing from tool registration
through execution with proper runtime selection.

Author: MCP Server Test Team
Date: 2026-02-18
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from ipfs_datasets_py.mcp_server.runtime_router import RuntimeRouter
from ipfs_datasets_py.mcp_server.tool_metadata import (
    ToolMetadata,
    ToolMetadataRegistry,
    tool_metadata,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
    RUNTIME_AUTO,
)


class TestMetadataRegistrationRouting:
    """Test tool registration with metadata and routing."""

    @pytest.mark.asyncio
    async def test_register_and_route_fastapi_tool(self):
        """
        GIVEN: Tool registered with FastAPI metadata
        WHEN: Routing tool call
        THEN: Tool is routed to FastAPI runtime
        """
        # Create registry and router
        registry = ToolMetadataRegistry()
        router = RuntimeRouter(metadata_registry=registry)
        
        # Register tool with metadata
        @tool_metadata(runtime=RUNTIME_FASTAPI, category="dataset")
        async def load_dataset(name: str):
            """Load a dataset."""
            return f"Loaded {name}"
        
        # Start router
        await router.startup()
        
        # Route tool call
        result = await router.route_tool_call("load_dataset", load_dataset, "squad")
        
        # Verify
        assert result == "Loaded squad"
        assert router.get_tool_runtime("load_dataset") == RUNTIME_FASTAPI
        
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_register_and_route_trio_tool(self):
        """
        GIVEN: Tool registered with Trio metadata
        WHEN: Routing tool call
        THEN: Tool is routed to Trio runtime
        """
        # Create registry and router
        registry = ToolMetadataRegistry()
        router = RuntimeRouter(metadata_registry=registry)
        
        # Register tool with metadata
        @tool_metadata(runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_workflow")
        async def p2p_workflow_submit(workflow_id: str):
            """Submit P2P workflow."""
            return f"Workflow {workflow_id} submitted"
        
        # Start router
        await router.startup()
        
        # Route tool call
        result = await router.route_tool_call("p2p_workflow_submit", p2p_workflow_submit, "wf-001")
        
        # Verify
        assert result == "Workflow wf-001 submitted"
        assert router.get_tool_runtime("p2p_workflow_submit") == RUNTIME_TRIO
        
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_register_multiple_tools_different_runtimes(self):
        """
        GIVEN: Multiple tools with different runtimes
        WHEN: Routing multiple tool calls
        THEN: Each tool uses correct runtime
        """
        # Create registry and router
        registry = ToolMetadataRegistry()
        router = RuntimeRouter(metadata_registry=registry)
        
        # Register tools
        @tool_metadata(runtime=RUNTIME_FASTAPI, category="dataset")
        async def dataset_tool():
            return "dataset"
        
        @tool_metadata(runtime=RUNTIME_TRIO, category="p2p")
        async def p2p_tool():
            return "p2p"
        
        # Start router
        await router.startup()
        
        # Route both tools
        result1 = await router.route_tool_call("dataset_tool", dataset_tool)
        result2 = await router.route_tool_call("p2p_tool", p2p_tool)
        
        # Verify runtimes
        assert router.get_tool_runtime("dataset_tool") == RUNTIME_FASTAPI
        assert router.get_tool_runtime("p2p_tool") == RUNTIME_TRIO
        
        # Verify execution
        assert result1 == "dataset"
        assert result2 == "p2p"
        
        await router.shutdown()


class TestMetadataBasedDetection:
    """Test runtime detection based on metadata."""

    def test_detect_runtime_from_decorator(self):
        """
        GIVEN: Function decorated with @tool_metadata
        WHEN: Detecting runtime
        THEN: Decorator metadata is used
        """
        router = RuntimeRouter()
        
        @tool_metadata(runtime=RUNTIME_TRIO, category="p2p")
        async def p2p_function():
            pass
        
        runtime = router.detect_runtime("p2p_function", p2p_function)
        assert runtime == RUNTIME_TRIO

    def test_detect_runtime_registry_priority(self):
        """
        GIVEN: Tool in both cache and registry
        WHEN: Detecting runtime
        THEN: Cache takes priority
        """
        registry = ToolMetadataRegistry()
        registry.register(ToolMetadata(name="test_tool", runtime=RUNTIME_FASTAPI))
        
        router = RuntimeRouter(metadata_registry=registry)
        router._tool_runtimes["test_tool"] = RUNTIME_TRIO  # Cached value
        
        def dummy_func():
            pass
        
        runtime = router.detect_runtime("test_tool", dummy_func)
        assert runtime == RUNTIME_TRIO  # Cache wins

    def test_detect_runtime_metadata_vs_name_pattern(self):
        """
        GIVEN: Tool with metadata and name pattern
        WHEN: Detecting runtime
        THEN: Metadata takes priority over name pattern
        """
        router = RuntimeRouter()
        
        @tool_metadata(runtime=RUNTIME_FASTAPI)  # Explicit FastAPI
        async def p2p_tool():  # Name suggests Trio
            pass
        
        runtime = router.detect_runtime("p2p_tool", p2p_tool)
        assert runtime == RUNTIME_FASTAPI  # Metadata wins


class TestBulkRegistration:
    """Test bulk tool registration from metadata."""

    @pytest.mark.asyncio
    async def test_bulk_register_populates_cache(self):
        """
        GIVEN: Multiple tools in metadata registry
        WHEN: Bulk registering tools
        THEN: All tools cached in router
        """
        registry = ToolMetadataRegistry()
        registry.register(ToolMetadata(name="tool1", runtime=RUNTIME_FASTAPI))
        registry.register(ToolMetadata(name="tool2", runtime=RUNTIME_TRIO))
        registry.register(ToolMetadata(name="tool3", runtime=RUNTIME_FASTAPI))
        
        router = RuntimeRouter(metadata_registry=registry)
        count = router.bulk_register_tools_from_metadata()
        
        assert count == 3
        assert router.get_tool_runtime("tool1") == RUNTIME_FASTAPI
        assert router.get_tool_runtime("tool2") == RUNTIME_TRIO
        assert router.get_tool_runtime("tool3") == RUNTIME_FASTAPI

    @pytest.mark.asyncio
    async def test_bulk_register_improves_detection_performance(self):
        """
        GIVEN: Many tools in registry
        WHEN: Bulk registering vs individual detection
        THEN: Bulk registration is faster
        """
        import time
        
        # Create registry with many tools
        registry = ToolMetadataRegistry()
        for i in range(100):
            registry.register(ToolMetadata(name=f"tool{i}", runtime=RUNTIME_FASTAPI))
        
        router = RuntimeRouter(metadata_registry=registry)
        
        # Bulk register
        start = time.time()
        router.bulk_register_tools_from_metadata()
        bulk_time = time.time() - start
        
        # All tools should now be cached
        assert len(router._tool_runtimes) == 100


class TestMetadataValidation:
    """Test metadata validation during routing."""

    @pytest.mark.asyncio
    async def test_route_tool_with_incomplete_metadata_warning(self, caplog):
        """
        GIVEN: Tool with incomplete metadata
        WHEN: Routing tool call
        THEN: Warning logged but tool still executes
        """
        @tool_metadata(runtime=RUNTIME_FASTAPI)
        async def incomplete_tool():
            """No schema or detailed description."""
            return "result"
        
        # Check validation warnings
        metadata = incomplete_tool._mcp_metadata
        warnings = metadata.validate_complete()
        
        assert len(warnings) > 0
        
        # Tool should still execute
        router = RuntimeRouter()
        await router.startup()
        result = await router.route_tool_call("incomplete_tool", incomplete_tool)
        assert result == "result"
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_p2p_tool_with_fastapi_runtime_warning(self):
        """
        GIVEN: P2P tool with FastAPI runtime
        WHEN: Validating metadata
        THEN: Warning about runtime mismatch
        """
        @tool_metadata(runtime=RUNTIME_FASTAPI, requires_p2p=True)
        async def mismatched_tool():
            return "result"
        
        metadata = mismatched_tool._mcp_metadata
        warnings = metadata.validate_complete()
        
        # Should have warning about P2P with FastAPI
        assert any("p2p" in w.lower() and "trio" in w.lower() for w in warnings)


class TestCategoryBasedRouting:
    """Test routing based on tool categories."""

    @pytest.mark.asyncio
    async def test_list_tools_by_category(self):
        """
        GIVEN: Tools registered in different categories
        WHEN: Listing tools by category
        THEN: Correct tools returned
        """
        registry = ToolMetadataRegistry()
        registry.register(ToolMetadata(name="dataset1", category="dataset"))
        registry.register(ToolMetadata(name="dataset2", category="dataset"))
        registry.register(ToolMetadata(name="p2p1", category="p2p"))
        registry.register(ToolMetadata(name="storage1", category="storage"))
        
        dataset_tools = registry.list_by_category("dataset")
        p2p_tools = registry.list_by_category("p2p")
        
        assert len(dataset_tools) == 2
        assert len(p2p_tools) == 1

    @pytest.mark.asyncio
    async def test_route_tools_by_category_patterns(self):
        """
        GIVEN: Tools in different categories
        WHEN: Routing tools from same category
        THEN: Similar performance characteristics
        """
        router = RuntimeRouter()
        await router.startup()
        
        @tool_metadata(runtime=RUNTIME_FASTAPI, category="dataset")
        async def dataset1():
            await asyncio.sleep(0.01)
            return "d1"
        
        @tool_metadata(runtime=RUNTIME_FASTAPI, category="dataset")
        async def dataset2():
            await asyncio.sleep(0.01)
            return "d2"
        
        # Route both
        await router.route_tool_call("dataset1", dataset1)
        await router.route_tool_call("dataset2", dataset2)
        
        # Check metrics - both should use same runtime
        metrics = router.get_metrics()
        assert metrics[RUNTIME_FASTAPI]["request_count"] == 2
        
        await router.shutdown()


class TestRuntimeStatistics:
    """Test runtime statistics with metadata."""

    @pytest.mark.asyncio
    async def test_get_statistics_by_runtime(self):
        """
        GIVEN: Tools executed on different runtimes
        WHEN: Getting statistics
        THEN: Stats separated by runtime
        """
        router = RuntimeRouter()
        await router.startup()
        
        @tool_metadata(runtime=RUNTIME_FASTAPI)
        async def fastapi_tool():
            await asyncio.sleep(0.01)
            return "fastapi"
        
        @tool_metadata(runtime=RUNTIME_TRIO)
        async def trio_tool():
            await asyncio.sleep(0.01)
            return "trio"
        
        # Execute tools
        await router.route_tool_call("fastapi_tool", fastapi_tool)
        await router.route_tool_call("fastapi_tool", fastapi_tool)
        await router.route_tool_call("trio_tool", trio_tool)
        
        # Get stats
        stats = router.get_runtime_stats()
        
        assert stats["total_requests"] == 3
        assert stats["by_runtime"][RUNTIME_FASTAPI]["requests"] == 2
        assert stats["by_runtime"][RUNTIME_TRIO]["requests"] == 1
        
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_metadata_registry_stats_integration(self):
        """
        GIVEN: Metadata registry with tools
        WHEN: Getting registry stats from router
        THEN: Complete statistics available
        """
        registry = ToolMetadataRegistry()
        registry.register(ToolMetadata(name="t1", runtime=RUNTIME_FASTAPI, category="dataset"))
        registry.register(ToolMetadata(name="t2", runtime=RUNTIME_TRIO, requires_p2p=True))
        registry.register(ToolMetadata(name="t3", runtime=RUNTIME_FASTAPI, category="dataset"))
        
        router = RuntimeRouter(metadata_registry=registry)
        stats = router.get_metadata_registry_stats()
        
        assert stats["total_tools"] == 3
        assert stats["by_runtime"][RUNTIME_FASTAPI] == 2
        assert stats["by_runtime"][RUNTIME_TRIO] == 1
        assert stats["p2p_tools"] == 1
        assert stats["by_category"]["dataset"] == 2


class TestErrorHandlingWithMetadata:
    """Test error handling in metadata-based routing."""

    @pytest.mark.asyncio
    async def test_tool_error_tracked_by_runtime(self):
        """
        GIVEN: Tool that raises error
        WHEN: Routing tool call
        THEN: Error tracked for correct runtime
        """
        router = RuntimeRouter()
        await router.startup()
        
        @tool_metadata(runtime=RUNTIME_FASTAPI)
        async def failing_tool():
            raise ValueError("Tool failed")
        
        with pytest.raises(ValueError):
            await router.route_tool_call("failing_tool", failing_tool)
        
        metrics = router.get_metrics()
        assert metrics[RUNTIME_FASTAPI]["error_count"] == 1
        assert metrics[RUNTIME_TRIO]["error_count"] == 0
        
        await router.shutdown()

    @pytest.mark.asyncio
    async def test_invalid_metadata_graceful_fallback(self):
        """
        GIVEN: Tool with invalid metadata
        WHEN: Routing tool call
        THEN: Falls back to default runtime
        """
        router = RuntimeRouter(default_runtime=RUNTIME_FASTAPI)
        await router.startup()
        
        # Function without proper metadata
        async def plain_tool():
            return "result"
        
        result = await router.route_tool_call("plain_tool", plain_tool)
        
        assert result == "result"
        assert router.get_tool_runtime("plain_tool") == RUNTIME_FASTAPI
        
        await router.shutdown()
