"""
Unit tests for ToolMetadata system.

Tests the ToolMetadata dataclass, ToolMetadataRegistry,
and @tool_metadata decorator functionality.

Author: MCP Server Test Team
Date: 2026-02-18
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


class TestToolMetadataDataclass:
    """Test ToolMetadata dataclass creation and validation."""

    def test_metadata_creation_minimal(self):
        """
        GIVEN: Only required parameters
        WHEN: Creating ToolMetadata instance
        THEN: Default values are applied correctly
        """
        metadata = ToolMetadata(name="test_tool")
        
        assert metadata.name == "test_tool"
        assert metadata.runtime == RUNTIME_AUTO
        assert metadata.requires_p2p is False
        assert metadata.category == "general"
        assert metadata.priority == 5
        assert metadata.timeout_seconds == 30.0

    def test_metadata_creation_full(self):
        """
        GIVEN: All parameters specified
        WHEN: Creating ToolMetadata instance
        THEN: All values are set correctly
        """
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
        assert metadata.mcp_schema == schema
        assert metadata.mcp_description == "Advanced P2P workflow tool"

    def test_metadata_invalid_runtime(self):
        """
        GIVEN: Invalid runtime value
        WHEN: Creating ToolMetadata instance
        THEN: ValueError is raised
        """
        with pytest.raises(ValueError, match="Invalid runtime"):
            ToolMetadata(name="test_tool", runtime="invalid_runtime")

    def test_metadata_invalid_priority_range(self):
        """
        GIVEN: Priority outside 0-10 range
        WHEN: Creating ToolMetadata instance
        THEN: ValueError is raised
        """
        with pytest.raises(ValueError, match="Priority must be 0-10"):
            ToolMetadata(name="test_tool", priority=11)
        
        with pytest.raises(ValueError, match="Priority must be 0-10"):
            ToolMetadata(name="test_tool", priority=-1)

    def test_metadata_invalid_retry_policy(self):
        """
        GIVEN: Invalid retry policy
        WHEN: Creating ToolMetadata instance
        THEN: ValueError is raised
        """
        with pytest.raises(ValueError, match="Invalid retry_policy"):
            ToolMetadata(name="test_tool", retry_policy="invalid")

    def test_metadata_to_dict(self):
        """
        GIVEN: ToolMetadata instance
        WHEN: Converting to dictionary
        THEN: All fields are included except internal fields
        """
        metadata = ToolMetadata(
            name="test_tool",
            runtime=RUNTIME_TRIO,
            category="p2p",
            priority=7
        )
        
        data = metadata.to_dict()
        
        assert data["name"] == "test_tool"
        assert data["runtime"] == RUNTIME_TRIO
        assert data["category"] == "p2p"
        assert data["priority"] == 7
        assert "_func" not in data

    def test_metadata_validate_complete_missing_description(self):
        """
        GIVEN: Metadata without description
        WHEN: Validating completeness
        THEN: Warning is returned
        """
        metadata = ToolMetadata(name="test_tool")
        warnings = metadata.validate_complete()
        
        assert any("description" in w.lower() for w in warnings)

    def test_metadata_validate_complete_missing_schema(self):
        """
        GIVEN: Metadata without schema
        WHEN: Validating completeness
        THEN: Warning is returned
        """
        metadata = ToolMetadata(name="test_tool")
        warnings = metadata.validate_complete()
        
        assert any("schema" in w.lower() for w in warnings)

    def test_metadata_validate_p2p_runtime_mismatch(self):
        """
        GIVEN: P2P tool with FastAPI runtime
        WHEN: Validating completeness
        THEN: Warning about runtime mismatch
        """
        metadata = ToolMetadata(
            name="p2p_tool",
            requires_p2p=True,
            runtime=RUNTIME_FASTAPI
        )
        warnings = metadata.validate_complete()
        
        assert any("p2p" in w.lower() and "trio" in w.lower() for w in warnings)

    def test_metadata_validate_complete_all_fields(self):
        """
        GIVEN: Complete metadata with all fields
        WHEN: Validating completeness
        THEN: No warnings returned
        """
        metadata = ToolMetadata(
            name="complete_tool",
            runtime=RUNTIME_TRIO,
            requires_p2p=True,
            mcp_description="Complete tool",
            mcp_schema={"type": "object"}
        )
        warnings = metadata.validate_complete()
        
        assert len(warnings) == 0


class TestToolMetadataRegistry:
    """Test ToolMetadataRegistry registration and lookup."""

    @pytest.fixture
    def registry(self):
        """Provide clean registry for each test."""
        reg = ToolMetadataRegistry()
        yield reg
        reg.clear()

    def test_registry_register_single_tool(self, registry):
        """
        GIVEN: New registry
        WHEN: Registering a single tool
        THEN: Tool is registered successfully
        """
        metadata = ToolMetadata(name="test_tool", runtime=RUNTIME_FASTAPI)
        registry.register(metadata)
        
        result = registry.get("test_tool")
        assert result is not None
        assert result.name == "test_tool"
        assert result.runtime == RUNTIME_FASTAPI

    def test_registry_register_multiple_tools(self, registry):
        """
        GIVEN: New registry
        WHEN: Registering multiple tools
        THEN: All tools are registered
        """
        for i in range(5):
            metadata = ToolMetadata(name=f"tool_{i}", runtime=RUNTIME_FASTAPI)
            registry.register(metadata)
        
        all_tools = registry.list_all()
        assert len(all_tools) == 5

    def test_registry_get_nonexistent_tool(self, registry):
        """
        GIVEN: Registry with no tools
        WHEN: Getting nonexistent tool
        THEN: None is returned
        """
        result = registry.get("nonexistent_tool")
        assert result is None

    def test_registry_list_by_runtime_fastapi(self, registry):
        """
        GIVEN: Tools registered with different runtimes
        WHEN: Listing tools by FastAPI runtime
        THEN: Only FastAPI tools returned
        """
        registry.register(ToolMetadata(name="tool1", runtime=RUNTIME_FASTAPI))
        registry.register(ToolMetadata(name="tool2", runtime=RUNTIME_TRIO))
        registry.register(ToolMetadata(name="tool3", runtime=RUNTIME_FASTAPI))
        
        fastapi_tools = registry.list_by_runtime(RUNTIME_FASTAPI)
        assert len(fastapi_tools) == 2
        assert all(t.runtime == RUNTIME_FASTAPI for t in fastapi_tools)

    def test_registry_list_by_runtime_trio(self, registry):
        """
        GIVEN: Tools registered with different runtimes
        WHEN: Listing tools by Trio runtime
        THEN: Only Trio tools returned
        """
        registry.register(ToolMetadata(name="tool1", runtime=RUNTIME_FASTAPI))
        registry.register(ToolMetadata(name="tool2", runtime=RUNTIME_TRIO))
        registry.register(ToolMetadata(name="tool3", runtime=RUNTIME_TRIO))
        
        trio_tools = registry.list_by_runtime(RUNTIME_TRIO)
        assert len(trio_tools) == 2
        assert all(t.runtime == RUNTIME_TRIO for t in trio_tools)

    def test_registry_list_by_category(self, registry):
        """
        GIVEN: Tools registered with different categories
        WHEN: Listing tools by category
        THEN: Only tools in that category returned
        """
        registry.register(ToolMetadata(name="tool1", category="dataset"))
        registry.register(ToolMetadata(name="tool2", category="p2p"))
        registry.register(ToolMetadata(name="tool3", category="dataset"))
        
        dataset_tools = registry.list_by_category("dataset")
        assert len(dataset_tools) == 2
        assert all(t.category == "dataset" for t in dataset_tools)

    def test_registry_get_statistics(self, registry):
        """
        GIVEN: Registry with multiple tools
        WHEN: Getting statistics
        THEN: Correct statistics returned
        """
        registry.register(ToolMetadata(name="tool1", runtime=RUNTIME_FASTAPI, category="dataset"))
        registry.register(ToolMetadata(name="tool2", runtime=RUNTIME_TRIO, requires_p2p=True))
        registry.register(ToolMetadata(name="tool3", runtime=RUNTIME_FASTAPI, category="dataset"))
        
        stats = registry.get_statistics()
        
        assert stats["total_tools"] == 3
        assert stats["by_runtime"][RUNTIME_FASTAPI] == 2
        assert stats["by_runtime"][RUNTIME_TRIO] == 1
        assert stats["by_category"]["dataset"] == 2
        assert stats["p2p_tools"] == 1
        assert stats["categories"] == 2

    def test_registry_re_register_warning(self, registry, caplog):
        """
        GIVEN: Tool already registered
        WHEN: Re-registering with different runtime
        THEN: Warning is logged
        """
        registry.register(ToolMetadata(name="tool1", runtime=RUNTIME_FASTAPI))
        registry.register(ToolMetadata(name="tool1", runtime=RUNTIME_TRIO))
        
        assert "re-registered" in caplog.text.lower()

    def test_registry_clear(self, registry):
        """
        GIVEN: Registry with registered tools
        WHEN: Clearing registry
        THEN: All tools removed
        """
        for i in range(5):
            registry.register(ToolMetadata(name=f"tool_{i}"))
        
        registry.clear()
        
        assert len(registry.list_all()) == 0
        assert registry.get_statistics()["total_tools"] == 0


class TestToolMetadataDecorator:
    """Test @tool_metadata decorator functionality."""

    def test_decorator_basic_function(self):
        """
        GIVEN: Function with @tool_metadata decorator
        WHEN: Decorator is applied
        THEN: Function has metadata attached
        """
        @tool_metadata(runtime=RUNTIME_TRIO, category="test")
        def test_function():
            """Test function."""
            return "result"
        
        assert hasattr(test_function, "_mcp_metadata")
        assert test_function._mcp_metadata.runtime == RUNTIME_TRIO
        assert test_function._mcp_metadata.category == "test"

    def test_decorator_async_function(self):
        """
        GIVEN: Async function with @tool_metadata decorator
        WHEN: Decorator is applied
        THEN: Function has metadata attached
        """
        @tool_metadata(runtime=RUNTIME_TRIO, requires_p2p=True)
        async def async_test_function():
            """Async test function."""
            return "async_result"
        
        assert hasattr(async_test_function, "_mcp_metadata")
        assert async_test_function._mcp_metadata.runtime == RUNTIME_TRIO
        assert async_test_function._mcp_metadata.requires_p2p is True

    def test_decorator_with_all_parameters(self):
        """
        GIVEN: Decorator with all parameters
        WHEN: Applied to function
        THEN: All metadata fields set correctly
        """
        schema = {"type": "object"}
        
        @tool_metadata(
            runtime=RUNTIME_TRIO,
            requires_p2p=True,
            category="p2p_workflow",
            priority=9,
            timeout_seconds=120.0,
            retry_policy="exponential",
            memory_intensive=True,
            cpu_intensive=False,
            io_intensive=True,
            mcp_schema=schema,
            mcp_description="Full metadata tool"
        )
        def full_metadata_function():
            """Function with full metadata."""
            return "result"
        
        metadata = full_metadata_function._mcp_metadata
        assert metadata.runtime == RUNTIME_TRIO
        assert metadata.requires_p2p is True
        assert metadata.category == "p2p_workflow"
        assert metadata.priority == 9
        assert metadata.timeout_seconds == 120.0
        assert metadata.retry_policy == "exponential"
        assert metadata.memory_intensive is True
        assert metadata.mcp_schema == schema
        assert metadata.mcp_description == "Full metadata tool"

    def test_decorator_auto_registers_with_global_registry(self):
        """
        GIVEN: Function with @tool_metadata decorator
        WHEN: Decorator is applied
        THEN: Function is automatically registered with global registry
        """
        registry = get_registry()
        registry.clear()
        
        @tool_metadata(runtime=RUNTIME_FASTAPI)
        def auto_registered_function():
            """Auto-registered function."""
            return "result"
        
        metadata = registry.get("auto_registered_function")
        assert metadata is not None
        assert metadata.name == "auto_registered_function"

    def test_decorator_uses_docstring_as_description(self):
        """
        GIVEN: Function with docstring but no explicit description
        WHEN: Decorator is applied
        THEN: Docstring is used as description
        """
        @tool_metadata(runtime=RUNTIME_FASTAPI)
        def documented_function():
            """This is the function docstring."""
            return "result"
        
        assert "docstring" in documented_function._mcp_metadata.mcp_description

    def test_decorator_explicit_description_overrides_docstring(self):
        """
        GIVEN: Function with both docstring and explicit description
        WHEN: Decorator is applied
        THEN: Explicit description is used
        """
        @tool_metadata(
            runtime=RUNTIME_FASTAPI,
            mcp_description="Explicit description"
        )
        def function_with_both():
            """This is the docstring."""
            return "result"
        
        assert function_with_both._mcp_metadata.mcp_description == "Explicit description"

    def test_get_tool_metadata_from_function(self):
        """
        GIVEN: Function with metadata
        WHEN: Getting metadata via get_tool_metadata
        THEN: Metadata is returned
        """
        @tool_metadata(runtime=RUNTIME_TRIO)
        def test_function():
            """Test function."""
            return "result"
        
        metadata = get_tool_metadata(test_function)
        assert metadata is not None
        assert metadata.runtime == RUNTIME_TRIO

    def test_get_tool_metadata_no_metadata(self):
        """
        GIVEN: Function without metadata
        WHEN: Getting metadata via get_tool_metadata
        THEN: None is returned
        """
        def plain_function():
            """Plain function."""
            return "result"
        
        metadata = get_tool_metadata(plain_function)
        assert metadata is None

    def test_decorator_sets_legacy_attributes(self):
        """
        GIVEN: Function with @tool_metadata decorator
        WHEN: Decorator is applied
        THEN: Legacy attributes (_mcp_runtime, etc.) are set for backward compatibility
        """
        @tool_metadata(
            runtime=RUNTIME_TRIO,
            requires_p2p=True,
            category="p2p",
            priority=8
        )
        def test_function():
            """Test function."""
            return "result"
        
        assert hasattr(test_function, "_mcp_runtime")
        assert test_function._mcp_runtime == RUNTIME_TRIO
        assert hasattr(test_function, "_mcp_requires_p2p")
        assert test_function._mcp_requires_p2p is True
        assert hasattr(test_function, "_mcp_category")
        assert test_function._mcp_category == "p2p"
        assert hasattr(test_function, "_mcp_priority")
        assert test_function._mcp_priority == 8
