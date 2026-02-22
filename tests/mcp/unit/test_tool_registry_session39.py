"""
Session 39 — Additional tests for tool_registry.py covering previously-uncovered methods.

Covers:
- ClaudeMCPTool.get_schema() and run()
- ToolRegistry.list_tools()
- ToolRegistry.get_tools_by_category()
- ToolRegistry.get_tools_by_tag()
- ToolRegistry.get_categories()
- ToolRegistry.search_tools()
- ToolRegistry.validate_tool_parameters()
- ToolRegistry.get_tool_statistics()
- _register_* helper functions (smoke tests)
"""
import pytest
import asyncio
from unittest.mock import patch
from typing import Dict, Any

from ipfs_datasets_py.mcp_server.tool_registry import (
    ClaudeMCPTool,
    ToolRegistry,
    _register_embedding_tools,
    _register_search_tools,
    _register_analysis_tools,
    _register_storage_tools,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Tool(ClaudeMCPTool):
    """Minimal concrete implementation for testing."""

    def __init__(self, name="test_tool", description="A tool", category="general", tags=None):
        super().__init__()
        self.name = name
        self.description = description
        self.category = category
        self.tags = tags or ["test"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
        }

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "text": parameters.get("text", "")}


# ---------------------------------------------------------------------------
# ClaudeMCPTool.get_schema() and run()
# ---------------------------------------------------------------------------

class TestClaudeMCPToolSchema:
    """Tests for ClaudeMCPTool.get_schema()."""

    def test_get_schema_returns_dict(self):
        """get_schema() returns a dict."""
        tool = _Tool("my_tool")
        schema = tool.get_schema()
        assert isinstance(schema, dict)

    def test_get_schema_has_name(self):
        """get_schema() includes the tool name."""
        tool = _Tool("alpha")
        assert tool.get_schema()["name"] == "alpha"

    def test_get_schema_has_description(self):
        """get_schema() includes description."""
        tool = _Tool(description="Does something")
        assert "Does something" in tool.get_schema()["description"]

    def test_get_schema_has_input_schema(self):
        """get_schema() includes input_schema."""
        tool = _Tool()
        schema = tool.get_schema()
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"

    def test_get_schema_has_category(self):
        """get_schema() includes category."""
        tool = _Tool(category="dataset_tools")
        assert tool.get_schema()["category"] == "dataset_tools"

    def test_get_schema_has_tags(self):
        """get_schema() includes tags list."""
        tool = _Tool(tags=["fast", "production"])
        assert tool.get_schema()["tags"] == ["fast", "production"]

    def test_get_schema_has_version(self):
        """get_schema() includes version."""
        tool = _Tool()
        assert "version" in tool.get_schema()


class TestClaudeMCPToolRun:
    """Tests for ClaudeMCPTool.run() — increments usage_count / sets last_used."""

    def test_run_returns_execute_result(self):
        """run() returns the result of execute()."""
        tool = _Tool()
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(tool.run(text="hello"))
        loop.close()
        assert result["status"] == "success"
        assert result["text"] == "hello"

    def test_run_increments_usage_count(self):
        """run() increments usage_count by 1 each call."""
        tool = _Tool()
        assert tool.usage_count == 0
        loop = asyncio.new_event_loop()
        loop.run_until_complete(tool.run(text="a"))
        loop.run_until_complete(tool.run(text="b"))
        loop.close()
        assert tool.usage_count == 2

    def test_run_sets_last_used(self):
        """run() sets last_used to a non-None datetime."""
        tool = _Tool()
        assert tool.last_used is None
        loop = asyncio.new_event_loop()
        loop.run_until_complete(tool.run(text="x"))
        loop.close()
        assert tool.last_used is not None


# ---------------------------------------------------------------------------
# ToolRegistry.list_tools()
# ---------------------------------------------------------------------------

class TestToolRegistryListTools:
    """Tests for list_tools()."""

    def test_list_tools_empty_registry(self):
        """list_tools() returns [] when no tools are registered."""
        reg = ToolRegistry()
        assert reg.list_tools() == []

    def test_list_tools_returns_list_of_dicts(self):
        """list_tools() returns a list of dicts."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("t1"))
        result = reg.list_tools()
        assert isinstance(result, list)
        assert all(isinstance(s, dict) for s in result)

    def test_list_tools_each_schema_has_name(self):
        """Each dict in list_tools() has a 'name' key."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("alpha"))
        reg.register_tool(_Tool("beta"))
        names = {s["name"] for s in reg.list_tools()}
        assert names == {"alpha", "beta"}

    def test_list_tools_count_matches_registration(self):
        """list_tools() returns one entry per registered tool."""
        reg = ToolRegistry()
        for i in range(5):
            reg.register_tool(_Tool(f"tool_{i}"))
        assert len(reg.list_tools()) == 5


# ---------------------------------------------------------------------------
# ToolRegistry.get_tools_by_category()
# ---------------------------------------------------------------------------

class TestToolRegistryGetByCategory:
    """Tests for get_tools_by_category()."""

    def test_returns_tools_in_category(self):
        """get_tools_by_category() returns tools whose category matches."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("a", category="cat_a"))
        reg.register_tool(_Tool("b", category="cat_b"))
        result = reg.get_tools_by_category("cat_a")
        assert len(result) == 1
        assert result[0].name == "a"

    def test_returns_empty_for_unknown_category(self):
        """get_tools_by_category() returns [] for an unknown category."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("a", category="cat_a"))
        assert reg.get_tools_by_category("nonexistent") == []

    def test_returns_all_tools_in_shared_category(self):
        """get_tools_by_category() returns all tools sharing the same category."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("x", category="shared"))
        reg.register_tool(_Tool("y", category="shared"))
        reg.register_tool(_Tool("z", category="other"))
        result = reg.get_tools_by_category("shared")
        assert len(result) == 2
        names = {t.name for t in result}
        assert names == {"x", "y"}


# ---------------------------------------------------------------------------
# ToolRegistry.get_tools_by_tag()
# ---------------------------------------------------------------------------

class TestToolRegistryGetByTag:
    """Tests for get_tools_by_tag()."""

    def test_returns_tools_with_tag(self):
        """get_tools_by_tag() returns tools that have the specified tag."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("a", tags=["fast", "stable"]))
        reg.register_tool(_Tool("b", tags=["slow"]))
        result = reg.get_tools_by_tag("fast")
        assert len(result) == 1
        assert result[0].name == "a"

    def test_returns_empty_for_unknown_tag(self):
        """get_tools_by_tag() returns [] for a tag not assigned to any tool."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("a", tags=["stable"]))
        assert reg.get_tools_by_tag("unknown_tag") == []

    def test_cross_category_tag_search(self):
        """get_tools_by_tag() finds tools across different categories."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("p", category="cat_p", tags=["shared_tag"]))
        reg.register_tool(_Tool("q", category="cat_q", tags=["shared_tag"]))
        reg.register_tool(_Tool("r", category="cat_r", tags=["other"]))
        result = reg.get_tools_by_tag("shared_tag")
        assert len(result) == 2
        names = {t.name for t in result}
        assert names == {"p", "q"}


# ---------------------------------------------------------------------------
# ToolRegistry.get_categories()
# ---------------------------------------------------------------------------

class TestToolRegistryGetCategories:
    """Tests for get_categories()."""

    def test_empty_registry_returns_empty(self):
        """get_categories() returns [] when empty."""
        assert ToolRegistry().get_categories() == []

    def test_reflects_registered_categories(self):
        """get_categories() contains all categories of registered tools."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("a", category="cat_a"))
        reg.register_tool(_Tool("b", category="cat_b"))
        cats = set(reg.get_categories())
        assert cats == {"cat_a", "cat_b"}

    def test_no_duplicates_for_shared_category(self):
        """get_categories() returns each category name at most once."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("x", category="shared"))
        reg.register_tool(_Tool("y", category="shared"))
        cats = reg.get_categories()
        assert len(cats) == len(set(cats))  # no duplicates


# ---------------------------------------------------------------------------
# ToolRegistry.search_tools()
# ---------------------------------------------------------------------------

class TestToolRegistrySearchTools:
    """Tests for search_tools()."""

    def test_search_by_name_substring(self):
        """search_tools() matches by name substring (case-insensitive)."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("embedding_search"))
        reg.register_tool(_Tool("dataset_load"))
        result = reg.search_tools("embed")
        assert len(result) == 1
        assert result[0].name == "embedding_search"

    def test_search_by_description(self):
        """search_tools() matches by description substring."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("t1", description="Finds documents via semantic similarity"))
        reg.register_tool(_Tool("t2", description="Loads a dataset from disk"))
        result = reg.search_tools("semantic")
        assert len(result) == 1
        assert result[0].name == "t1"

    def test_search_by_tag(self):
        """search_tools() matches by tag substring."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("a", tags=["async_capable", "fast"]))
        reg.register_tool(_Tool("b", tags=["sync_only"]))
        result = reg.search_tools("async_capable")
        assert len(result) == 1
        assert result[0].name == "a"

    def test_search_no_match_returns_empty(self):
        """search_tools() returns [] when no tool matches."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("alpha"))
        assert reg.search_tools("zzzzz_nomatch") == []

    def test_search_case_insensitive(self):
        """search_tools() query is case-insensitive."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("EmbeddingTool"))
        result = reg.search_tools("embeddingTOOL")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# ToolRegistry.validate_tool_parameters()
# ---------------------------------------------------------------------------

class TestToolRegistryValidateParameters:
    """Tests for validate_tool_parameters()."""

    def test_valid_params_returns_true(self):
        """validate_tool_parameters() returns True when all required params present."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("t"))
        assert reg.validate_tool_parameters("t", {"text": "hello"}) is True

    def test_missing_required_param_returns_false(self):
        """validate_tool_parameters() returns False when required param is missing."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("t"))
        assert reg.validate_tool_parameters("t", {}) is False

    def test_nonexistent_tool_returns_false(self):
        """validate_tool_parameters() returns False for unknown tool name."""
        reg = ToolRegistry()
        assert reg.validate_tool_parameters("no_such_tool", {"text": "x"}) is False

    def test_extra_params_still_valid(self):
        """validate_tool_parameters() accepts extra parameters beyond required."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("t"))
        assert reg.validate_tool_parameters("t", {"text": "hello", "extra": 42}) is True


# ---------------------------------------------------------------------------
# ToolRegistry.get_tool_statistics()
# ---------------------------------------------------------------------------

class TestToolRegistryStatistics:
    """Tests for get_tool_statistics()."""

    def test_stats_total_tools(self):
        """get_tool_statistics() includes correct total_tools count."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("a"))
        reg.register_tool(_Tool("b"))
        stats = reg.get_tool_statistics()
        assert stats["total_tools"] == 2

    def test_stats_categories_structure(self):
        """get_tool_statistics() includes categories as name→count dict."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("a", category="cat_a"))
        reg.register_tool(_Tool("b", category="cat_a"))
        reg.register_tool(_Tool("c", category="cat_b"))
        stats = reg.get_tool_statistics()
        assert stats["categories"]["cat_a"] == 2
        assert stats["categories"]["cat_b"] == 1

    def test_stats_tool_usage_keys(self):
        """get_tool_statistics() has tool_usage entry for each tool."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("mytool"))
        stats = reg.get_tool_statistics()
        assert "mytool" in stats["tool_usage"]
        usage = stats["tool_usage"]["mytool"]
        assert "usage_count" in usage
        assert "last_used" in usage
        assert "category" in usage

    def test_stats_initial_usage_count_zero(self):
        """get_tool_statistics() shows usage_count=0 for never-executed tools."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("fresh"))
        stats = reg.get_tool_statistics()
        assert stats["tool_usage"]["fresh"]["usage_count"] == 0

    def test_stats_total_executions(self):
        """get_tool_statistics() tracks total_executions counter."""
        reg = ToolRegistry()
        reg.register_tool(_Tool("t"))
        stats = reg.get_tool_statistics()
        assert "total_executions" in stats
        assert isinstance(stats["total_executions"], int)


# ---------------------------------------------------------------------------
# _register_* helper functions (smoke tests — should not raise)
# ---------------------------------------------------------------------------

class TestRegisterHelperFunctions:
    """Smoke tests — _register_* helpers import tools without crashing."""

    def test_register_embedding_tools_no_service(self):
        """_register_embedding_tools() runs without embedding_service."""
        reg = ToolRegistry()
        _register_embedding_tools(reg)  # should not raise

    def test_register_search_tools_no_service(self):
        """_register_search_tools() runs without embedding_service."""
        reg = ToolRegistry()
        _register_search_tools(reg)  # should not raise

    def test_register_analysis_tools_no_service(self):
        """_register_analysis_tools() runs without embedding_service."""
        reg = ToolRegistry()
        _register_analysis_tools(reg)  # should not raise

    def test_register_storage_tools_no_service(self):
        """_register_storage_tools() runs without embedding_service."""
        reg = ToolRegistry()
        _register_storage_tools(reg)  # should not raise
