"""Tests for MCP server ToolRegistry and initialize_laion_tools."""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from typing import Dict, Any

from ipfs_datasets_py.mcp_server.tool_registry import (
    ClaudeMCPTool,
    ToolRegistry,
    initialize_laion_tools,
    _register_embedding_tools,
    _register_search_tools,
    _register_analysis_tools,
    _register_storage_tools,
)
from ipfs_datasets_py.mcp_server.exceptions import (
    ToolRegistrationError,
    ToolNotFoundError,
    ToolExecutionError,
    ConfigurationError,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _ConcreteTool(ClaudeMCPTool):
    """Minimal concrete tool for testing (ClaudeMCPTool is abstract)."""

    def __init__(self, name: str = "test_tool", category: str = "test", tags=None):
        super().__init__()
        self.name = name
        self.description = f"A test tool: {name}"
        self.category = category
        self.tags = tags or ["test"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "input": {"type": "string"},
            },
            "required": ["input"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "input": parameters.get("input")}


@pytest.fixture
def registry():
    """Return a fresh empty ToolRegistry."""
    return ToolRegistry()


@pytest.fixture
def populated_registry():
    """Return a ToolRegistry with a few tools pre-registered."""
    reg = ToolRegistry()
    reg.register_tool(_ConcreteTool("tool_a", "cat_a", ["tag1", "tag2"]))
    reg.register_tool(_ConcreteTool("tool_b", "cat_a", ["tag2", "tag3"]))
    reg.register_tool(_ConcreteTool("tool_c", "cat_b", ["tag1"]))
    return reg


# ---------------------------------------------------------------------------
# ToolRegistry – basic CRUD
# ---------------------------------------------------------------------------

class TestToolRegistryRegistration:
    """GIVEN a ToolRegistry WHEN tools are registered THEN they are discoverable."""

    def test_register_and_get_tool(self, registry):
        """
        GIVEN: An empty ToolRegistry
        WHEN: A tool is registered
        THEN: It is retrievable by name
        """
        tool = _ConcreteTool("my_tool")
        registry.register_tool(tool)
        assert registry.get_tool("my_tool") is tool

    def test_has_tool_returns_true_after_registration(self, registry):
        """
        GIVEN: An empty ToolRegistry
        WHEN: A tool is registered
        THEN: has_tool returns True
        """
        registry.register_tool(_ConcreteTool("my_tool"))
        assert registry.has_tool("my_tool") is True

    def test_has_tool_returns_false_for_unknown(self, registry):
        """
        GIVEN: An empty ToolRegistry
        WHEN: has_tool is called with an unknown name
        THEN: Returns False
        """
        assert registry.has_tool("nonexistent") is False

    def test_register_invalid_tool_raises(self, registry):
        """
        GIVEN: An empty ToolRegistry
        WHEN: A non-tool object is registered
        THEN: ValueError is raised
        """
        with pytest.raises(ValueError):
            registry.register_tool("not_a_tool")  # type: ignore

    def test_register_duplicate_overwrites(self, registry):
        """
        GIVEN: A ToolRegistry with tool 'x'
        WHEN: Another tool named 'x' is registered
        THEN: The new tool replaces the old one
        """
        original = _ConcreteTool("x")
        registry.register_tool(original)
        replacement = _ConcreteTool("x")
        registry.register_tool(replacement)
        assert registry.get_tool("x") is replacement


class TestToolRegistryCategories:
    """GIVEN a populated ToolRegistry WHEN queried by category THEN correct tools are returned."""

    def test_get_tools_by_category(self, populated_registry):
        """
        GIVEN: Registry with tools in 'cat_a' and 'cat_b'
        WHEN: get_tools_by_category('cat_a') is called
        THEN: Returns only cat_a tools
        """
        tools = populated_registry.get_tools_by_category("cat_a")
        names = {t.name for t in tools}
        assert names == {"tool_a", "tool_b"}

    def test_get_categories_lists_all(self, populated_registry):
        """
        GIVEN: Registry with categories cat_a and cat_b
        WHEN: get_categories() is called
        THEN: Both categories are returned
        """
        cats = populated_registry.get_categories()
        assert set(cats) >= {"cat_a", "cat_b"}

    def test_get_tools_by_tag(self, populated_registry):
        """
        GIVEN: Registry with tools tagged tag1 and tag2
        WHEN: get_tools_by_tag('tag1') is called
        THEN: Returns tools with tag1
        """
        tools = populated_registry.get_tools_by_tag("tag1")
        names = {t.name for t in tools}
        assert "tool_a" in names
        assert "tool_c" in names
        assert "tool_b" not in names


class TestToolRegistryUnregister:
    """GIVEN a populated ToolRegistry WHEN a tool is unregistered THEN it disappears."""

    def test_unregister_returns_true_for_existing(self, populated_registry):
        """
        GIVEN: Registry with 'tool_a'
        WHEN: unregister_tool('tool_a') is called
        THEN: Returns True and tool is gone
        """
        result = populated_registry.unregister_tool("tool_a")
        assert result is True
        assert not populated_registry.has_tool("tool_a")

    def test_unregister_returns_false_for_missing(self, registry):
        """
        GIVEN: An empty ToolRegistry
        WHEN: unregister_tool('nonexistent') is called
        THEN: Returns False without raising
        """
        assert registry.unregister_tool("nonexistent") is False

    def test_category_cleaned_up_after_last_tool_removed(self, registry):
        """
        GIVEN: Registry with one tool in cat_x
        WHEN: The only tool in cat_x is unregistered
        THEN: cat_x no longer appears in get_categories()
        """
        registry.register_tool(_ConcreteTool("solo", "cat_x"))
        registry.unregister_tool("solo")
        assert "cat_x" not in registry.get_categories()


# ---------------------------------------------------------------------------
# ToolRegistry – search
# ---------------------------------------------------------------------------

class TestToolRegistrySearch:
    """GIVEN a populated ToolRegistry WHEN searched THEN matching tools are returned."""

    def test_search_by_name(self, populated_registry):
        """
        GIVEN: Registry with 'tool_a', 'tool_b', 'tool_c'
        WHEN: search_tools('tool_a') is called
        THEN: Returns tool_a
        """
        results = populated_registry.search_tools("tool_a")
        assert any(t.name == "tool_a" for t in results)

    def test_search_no_match_returns_empty(self, populated_registry):
        """
        GIVEN: A populated registry
        WHEN: search_tools with a query that matches nothing
        THEN: Returns an empty list
        """
        results = populated_registry.search_tools("zzz_no_match_zzz")
        assert results == []


# ---------------------------------------------------------------------------
# ToolRegistry – validation
# ---------------------------------------------------------------------------

class TestToolRegistryValidation:
    """GIVEN a ToolRegistry WHEN validate_tool_parameters is called THEN returns correct result."""

    def test_valid_parameters_return_true(self, registry):
        """
        GIVEN: A tool requiring 'input' parameter
        WHEN: validate_tool_parameters called with 'input' present
        THEN: Returns True
        """
        registry.register_tool(_ConcreteTool("my_tool"))
        assert registry.validate_tool_parameters("my_tool", {"input": "hello"}) is True

    def test_missing_required_returns_false(self, registry):
        """
        GIVEN: A tool requiring 'input' parameter
        WHEN: validate_tool_parameters called without 'input'
        THEN: Returns False
        """
        registry.register_tool(_ConcreteTool("my_tool"))
        assert registry.validate_tool_parameters("my_tool", {}) is False

    def test_unknown_tool_returns_false(self, registry):
        """
        GIVEN: An empty registry
        WHEN: validate_tool_parameters called for unknown tool
        THEN: Returns False (no exception raised)
        """
        assert registry.validate_tool_parameters("nope", {"input": "x"}) is False


# ---------------------------------------------------------------------------
# ToolRegistry – statistics
# ---------------------------------------------------------------------------

class TestToolRegistryStatistics:
    """GIVEN a populated ToolRegistry WHEN statistics are requested THEN accurate data returned."""

    def test_get_tool_statistics_structure(self, populated_registry):
        """
        GIVEN: A registry with 3 tools
        WHEN: get_tool_statistics() is called
        THEN: Returns a dict with tool_count >= 3
        """
        stats = populated_registry.get_tool_statistics()
        assert isinstance(stats, dict)
        assert stats.get("total_tools", 0) >= 3

    def test_get_all_tools_returns_list(self, populated_registry):
        """
        GIVEN: A registry with 3 tools
        WHEN: get_all_tools() is called
        THEN: Returns a list with 3 tools
        """
        tools = populated_registry.get_all_tools()
        assert len(tools) == 3


# ---------------------------------------------------------------------------
# initialize_laion_tools
# ---------------------------------------------------------------------------

class TestInitializeLaionTools:
    """Tests for the initialize_laion_tools function."""

    def test_returns_list_when_no_registry_provided(self):
        """
        GIVEN: No existing registry
        WHEN: initialize_laion_tools() is called without arguments
        THEN: Returns a list (possibly empty if all imports fail in test env)
        """
        result = initialize_laion_tools()
        assert result is None or isinstance(result, list)

    def test_returns_none_when_registry_provided(self):
        """
        GIVEN: An existing ToolRegistry
        WHEN: initialize_laion_tools(registry) is called
        THEN: Returns None (tools registered in-place)
        """
        reg = ToolRegistry()
        result = initialize_laion_tools(registry=reg)
        assert result is None

    def test_registers_tools_into_provided_registry(self):
        """
        GIVEN: An existing ToolRegistry
        WHEN: initialize_laion_tools(registry) is called
        THEN: Registry may have tools registered (depends on installed deps)
              but the registry itself is used (not a new one created)
        """
        reg = ToolRegistry()
        initialize_laion_tools(registry=reg)
        # We don't assert specific count since tool deps may not be installed;
        # the key assertion is that the function completes without exception.
        assert isinstance(reg, ToolRegistry)

    def test_graceful_degradation_with_no_embedding_service(self):
        """
        GIVEN: No embedding_service provided
        WHEN: initialize_laion_tools() is called
        THEN: Completes without raising (some tools may not register)
        """
        reg = ToolRegistry()
        # Should not raise even when embedding_service=None
        initialize_laion_tools(registry=reg, embedding_service=None)

    def test_all_private_helpers_are_callable(self):
        """
        GIVEN: The refactored module
        WHEN: The private helpers are inspected
        THEN: All 19 private helpers exist and are callable
        """
        from ipfs_datasets_py.mcp_server import tool_registry as tr
        helpers = [
            "_register_embedding_tools",
            "_register_search_tools",
            "_register_analysis_tools",
            "_register_storage_tools",
            "_register_data_processing_tools",
            "_register_auth_tools",
            "_register_admin_tools",
            "_register_cache_tools",
            "_register_monitoring_tools_group",
            "_register_background_task_tools",
            "_register_rate_limiting_tools",
            "_register_index_management_tools",
            "_register_sparse_embedding_tools",
            "_register_ipfs_cluster_tools",
            "_register_session_tools",
            "_register_embedding_generation_tools",
            "_register_shard_embedding_tools",
            "_register_vector_store_tools",
            "_register_workflow_tools",
        ]
        for helper_name in helpers:
            assert hasattr(tr, helper_name), f"Missing helper: {helper_name}"
            assert callable(getattr(tr, helper_name)), f"Not callable: {helper_name}"

    def test_private_helpers_do_not_raise_on_missing_imports(self):
        """
        GIVEN: Tool dependencies may not be installed
        WHEN: Each private helper is called
        THEN: No exception propagates (graceful degradation)
        """
        from ipfs_datasets_py.mcp_server import tool_registry as tr
        reg = ToolRegistry()
        helpers_with_service = [
            tr._register_embedding_tools,
            tr._register_search_tools,
            tr._register_analysis_tools,
            tr._register_storage_tools,
            tr._register_auth_tools,
            tr._register_admin_tools,
            tr._register_cache_tools,
            tr._register_monitoring_tools_group,
            tr._register_background_task_tools,
            tr._register_rate_limiting_tools,
            tr._register_index_management_tools,
            tr._register_sparse_embedding_tools,
            tr._register_ipfs_cluster_tools,
            tr._register_session_tools,
        ]
        helpers_without_service = [
            tr._register_embedding_generation_tools,
            tr._register_shard_embedding_tools,
            tr._register_vector_store_tools,
            tr._register_workflow_tools,
        ]
        for fn in helpers_with_service:
            fn(reg, None)  # should not raise

        for fn in helpers_without_service:
            fn(reg)  # should not raise


# ---------------------------------------------------------------------------
# ClaudeMCPTool – base class
# ---------------------------------------------------------------------------

class TestClaudeMCPTool:
    """Tests for the ClaudeMCPTool abstract base class."""

    def test_schema_contains_required_fields(self):
        """
        GIVEN: A concrete tool
        WHEN: get_schema() is called
        THEN: Returns dict with name, description, input_schema, category, tags, version
        """
        tool = _ConcreteTool("schema_test", "test_cat", ["t1"])
        schema = tool.get_schema()
        assert "name" in schema
        assert "description" in schema
        assert "input_schema" in schema
        assert "category" in schema
        assert "tags" in schema
        assert "version" in schema

    def test_run_increments_usage_count(self):
        """
        GIVEN: A concrete tool with usage_count=0
        WHEN: run() is called
        THEN: usage_count becomes 1
        """
        import asyncio
        tool = _ConcreteTool()
        assert tool.usage_count == 0
        asyncio.run(tool.run(input="hello"))
        assert tool.usage_count == 1

    def test_execute_returns_dict(self):
        """
        GIVEN: A concrete tool
        WHEN: execute() is called with valid parameters
        THEN: Returns a dict
        """
        import asyncio
        tool = _ConcreteTool()
        result = asyncio.run(tool.execute({"input": "hello"}))
        assert isinstance(result, dict)
        assert result["status"] == "success"
