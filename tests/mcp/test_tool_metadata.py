"""
Comprehensive tests for tool metadata system.

Tests the ToolMetadata dataclass, ToolMetadataRegistry,
and @tool_metadata decorator functionality.
"""

import pytest
from dataclasses import FrozenInstanceError
from ipfs_datasets_py.mcp_server.tool_metadata import (
    ToolMetadata,
    ToolMetadataRegistry,
    tool_metadata,
    get_registry,
    get_tool_metadata,
    RUNTIME_AUTO,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
)


class TestToolMetadata:
    """Test ToolMetadata dataclass."""

    def test_metadata_creation_minimal(self):
        """Test creating metadata with minimal required fields."""
        metadata = ToolMetadata(name="test_tool")
        
        assert metadata.name == "test_tool"
        assert metadata.runtime == RUNTIME_AUTO
        assert metadata.requires_p2p is False
        assert metadata.category == "general"
        assert metadata.priority == 5
        assert metadata.timeout_seconds == 30.0
        assert metadata.retry_policy == "none"
        assert metadata.memory_intensive is False
        assert metadata.cpu_intensive is False
        assert metadata.io_intensive is False
        assert metadata.mcp_schema is None
        assert metadata.mcp_description is None

    def test_metadata_creation_full(self):
        """Test creating metadata with all fields."""
        schema = {"type": "object", "properties": {}}
        metadata = ToolMetadata(
            name="advanced_tool",
            runtime=RUNTIME_TRIO,
            requires_p2p=True,
            category="p2p_workflow",
            priority=9,
            timeout_seconds=60.0,
            retry_policy="exponential",
            memory_intensive=True,
            cpu_intensive=False,
            io_intensive=True,
            mcp_schema=schema,
            mcp_description="Advanced P2P workflow tool"
        )
        
        assert metadata.name == "advanced_tool"
        assert metadata.runtime == RUNTIME_TRIO
        assert metadata.requires_p2p is True
        assert metadata.category == "p2p_workflow"
        assert metadata.priority == 9
        assert metadata.timeout_seconds == 60.0
        assert metadata.retry_policy == "exponential"
        assert metadata.memory_intensive is True
        assert metadata.cpu_intensive is False
        assert metadata.io_intensive is True
        assert metadata.mcp_schema == schema
        assert metadata.mcp_description == "Advanced P2P workflow tool"

    def test_metadata_immutable(self):
        """Test that metadata is immutable after creation."""
        metadata = ToolMetadata(name="test_tool")
        
        with pytest.raises((FrozenInstanceError, AttributeError)):
            metadata.name = "modified_name"

    def test_metadata_validation_name(self):
        """Test that name is required."""
        with pytest.raises(TypeError):
            ToolMetadata()  # type: ignore

    def test_metadata_priority_range(self):
        """Test priority values."""
        # Valid priorities
        for priority in [1, 5, 10]:
            metadata = ToolMetadata(name=f"tool_{priority}", priority=priority)
            assert metadata.priority == priority
        
        # Priority outside typical range still allowed (no hard validation)
        metadata = ToolMetadata(name="tool_high", priority=100)
        assert metadata.priority == 100

    def test_metadata_timeout_values(self):
        """Test timeout configurations."""
        # Quick timeout
        metadata = ToolMetadata(name="quick_tool", timeout_seconds=5.0)
        assert metadata.timeout_seconds == 5.0
        
        # Long timeout
        metadata = ToolMetadata(name="long_tool", timeout_seconds=300.0)
        assert metadata.timeout_seconds == 300.0

    def test_metadata_retry_policies(self):
        """Test different retry policies."""
        policies = ["none", "fixed", "exponential", "custom"]
        for policy in policies:
            metadata = ToolMetadata(name=f"tool_{policy}", retry_policy=policy)
            assert metadata.retry_policy == policy


class TestToolMetadataRegistry:
    """Test ToolMetadataRegistry functionality."""

    def setup_method(self):
        """Reset registry before each test."""
        # Create a fresh registry for testing
        self.registry = ToolMetadataRegistry()

    def test_registry_register_and_get(self):
        """Test registering and retrieving metadata."""
        metadata = ToolMetadata(name="test_tool", category="test")
        self.registry.register(metadata)
        
        retrieved = self.registry.get("test_tool")
        assert retrieved is not None
        assert retrieved.name == "test_tool"
        assert retrieved.category == "test"

    def test_registry_get_nonexistent(self):
        """Test getting nonexistent tool returns None."""
        result = self.registry.get("nonexistent_tool")
        assert result is None

    def test_registry_duplicate_registration(self):
        """Test that duplicate registration updates metadata."""
        metadata1 = ToolMetadata(name="tool", category="cat1")
        metadata2 = ToolMetadata(name="tool", category="cat2")
        
        self.registry.register(metadata1)
        self.registry.register(metadata2)
        
        retrieved = self.registry.get("tool")
        assert retrieved.category == "cat2"  # Updated

    def test_registry_list_all(self):
        """Test listing all registered tools."""
        tools = [
            ToolMetadata(name="tool1"),
            ToolMetadata(name="tool2"),
            ToolMetadata(name="tool3"),
        ]
        
        for tool in tools:
            self.registry.register(tool)
        
        all_tools = self.registry.list_all()
        assert len(all_tools) == 3
        names = {t.name for t in all_tools}
        assert names == {"tool1", "tool2", "tool3"}

    def test_registry_get_by_runtime(self):
        """Test filtering tools by runtime."""
        tools = [
            ToolMetadata(name="fastapi_tool1", runtime=RUNTIME_FASTAPI),
            ToolMetadata(name="fastapi_tool2", runtime=RUNTIME_FASTAPI),
            ToolMetadata(name="trio_tool1", runtime=RUNTIME_TRIO),
            ToolMetadata(name="auto_tool", runtime=RUNTIME_AUTO),
        ]
        
        for tool in tools:
            self.registry.register(tool)
        
        fastapi_tools = self.registry.get_by_runtime(RUNTIME_FASTAPI)
        assert len(fastapi_tools) == 2
        assert all(t.runtime == RUNTIME_FASTAPI for t in fastapi_tools)
        
        trio_tools = self.registry.get_by_runtime(RUNTIME_TRIO)
        assert len(trio_tools) == 1
        assert trio_tools[0].name == "trio_tool1"

    def test_registry_get_by_category(self):
        """Test filtering tools by category."""
        tools = [
            ToolMetadata(name="workflow1", category="p2p_workflow"),
            ToolMetadata(name="workflow2", category="p2p_workflow"),
            ToolMetadata(name="queue1", category="p2p_taskqueue"),
            ToolMetadata(name="general1", category="general"),
        ]
        
        for tool in tools:
            self.registry.register(tool)
        
        workflow_tools = self.registry.get_by_category("p2p_workflow")
        assert len(workflow_tools) == 2
        assert all(t.category == "p2p_workflow" for t in workflow_tools)

    def test_registry_clear(self):
        """Test clearing the registry."""
        tools = [ToolMetadata(name=f"tool{i}") for i in range(5)]
        for tool in tools:
            self.registry.register(tool)
        
        assert len(self.registry.list_all()) == 5
        
        self.registry.clear()
        assert len(self.registry.list_all()) == 0

    def test_registry_get_statistics(self):
        """Test getting registry statistics."""
        tools = [
            ToolMetadata(name="f1", runtime=RUNTIME_FASTAPI, category="cat1"),
            ToolMetadata(name="f2", runtime=RUNTIME_FASTAPI, category="cat1"),
            ToolMetadata(name="t1", runtime=RUNTIME_TRIO, category="cat2"),
            ToolMetadata(name="t2", runtime=RUNTIME_TRIO, category="cat2"),
            ToolMetadata(name="t3", runtime=RUNTIME_TRIO, category="cat3"),
        ]
        
        for tool in tools:
            self.registry.register(tool)
        
        stats = self.registry.get_statistics()
        
        assert stats["total"] == 5
        assert stats["by_runtime"][RUNTIME_FASTAPI] == 2
        assert stats["by_runtime"][RUNTIME_TRIO] == 3
        assert stats["by_category"]["cat1"] == 2
        assert stats["by_category"]["cat2"] == 2
        assert stats["by_category"]["cat3"] == 1

    def test_registry_thread_safety(self):
        """Test concurrent access to registry (basic check)."""
        import threading
        
        def register_tools(start, count):
            for i in range(start, start + count):
                metadata = ToolMetadata(name=f"tool_{i}")
                self.registry.register(metadata)
        
        threads = [
            threading.Thread(target=register_tools, args=(0, 10)),
            threading.Thread(target=register_tools, args=(10, 10)),
            threading.Thread(target=register_tools, args=(20, 10)),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Should have all 30 tools registered
        assert len(self.registry.list_all()) == 30


class TestToolMetadataDecorator:
    """Test @tool_metadata decorator."""

    def setup_method(self):
        """Reset registry before each test."""
        # Clear global registry
        registry = get_registry()
        registry.clear()

    def test_decorator_basic(self):
        """Test basic decorator usage."""
        @tool_metadata(runtime=RUNTIME_TRIO, category="test")
        def test_function():
            return "result"
        
        # Function should still work
        assert test_function() == "result"
        
        # Metadata should be registered
        registry = get_registry()
        metadata = registry.get("test_function")
        assert metadata is not None
        assert metadata.name == "test_function"
        assert metadata.runtime == RUNTIME_TRIO
        assert metadata.category == "test"

    def test_decorator_with_all_params(self):
        """Test decorator with all parameters."""
        @tool_metadata(
            runtime=RUNTIME_TRIO,
            requires_p2p=True,
            category="p2p_workflow",
            priority=9,
            timeout_seconds=60.0,
            retry_policy="exponential",
            memory_intensive=True,
            cpu_intensive=False,
            io_intensive=True,
            mcp_description="Test workflow tool"
        )
        def workflow_tool():
            return "workflow_result"
        
        metadata = get_registry().get("workflow_tool")
        assert metadata.runtime == RUNTIME_TRIO
        assert metadata.requires_p2p is True
        assert metadata.category == "p2p_workflow"
        assert metadata.priority == 9
        assert metadata.timeout_seconds == 60.0
        assert metadata.retry_policy == "exponential"
        assert metadata.memory_intensive is True
        assert metadata.cpu_intensive is False
        assert metadata.io_intensive is True
        assert metadata.mcp_description == "Test workflow tool"

    def test_decorator_async_function(self):
        """Test decorator on async function."""
        @tool_metadata(runtime=RUNTIME_TRIO)
        async def async_tool():
            return "async_result"
        
        # Metadata should be registered
        metadata = get_registry().get("async_tool")
        assert metadata is not None
        assert metadata.name == "async_tool"

    def test_decorator_preserves_docstring(self):
        """Test that decorator preserves function docstring."""
        @tool_metadata(runtime=RUNTIME_TRIO)
        def documented_function():
            """This is the docstring."""
            return "result"
        
        assert documented_function.__doc__ == "This is the docstring."

    def test_decorator_preserves_name(self):
        """Test that decorator preserves function name."""
        @tool_metadata(runtime=RUNTIME_TRIO)
        def named_function():
            return "result"
        
        assert named_function.__name__ == "named_function"

    def test_get_tool_metadata_helper(self):
        """Test get_tool_metadata helper function."""
        @tool_metadata(runtime=RUNTIME_TRIO, category="helper_test")
        def test_tool():
            return "result"
        
        # Should be able to get metadata by name
        metadata = get_tool_metadata("test_tool")
        assert metadata is not None
        assert metadata.category == "helper_test"
        
        # Nonexistent tool should return None
        assert get_tool_metadata("nonexistent") is None


class TestGlobalRegistry:
    """Test global registry singleton."""

    def test_get_registry_singleton(self):
        """Test that get_registry returns singleton."""
        registry1 = get_registry()
        registry2 = get_registry()
        
        assert registry1 is registry2

    def test_global_registry_persistence(self):
        """Test that registry persists across calls."""
        registry = get_registry()
        registry.clear()
        
        metadata = ToolMetadata(name="persistent_tool")
        registry.register(metadata)
        
        # Get registry again and tool should still be there
        registry2 = get_registry()
        retrieved = registry2.get("persistent_tool")
        assert retrieved is not None
        assert retrieved.name == "persistent_tool"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
