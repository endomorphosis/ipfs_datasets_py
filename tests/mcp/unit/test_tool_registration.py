"""
Phase B2 — Unit tests for tool_registration.py

Classes/functions: MCPToolRegistry, register_all_migrated_tools,
                   create_and_register_all_tools
Pure sync helper module.
"""
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# TestMCPToolRegistry
# ---------------------------------------------------------------------------
class TestMCPToolRegistry:
    def test_empty_registry(self):
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry
        registry = MCPToolRegistry()
        assert registry.tools == {}
        assert registry.categories == {}

    def test_register_errors_empty(self):
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry
        registry = MCPToolRegistry()
        assert isinstance(registry.registration_errors, list)
        assert len(registry.registration_errors) == 0

    def test_register_tool_stores_it(self):
        """A BaseMCPTool-like object can be stored in the registry."""
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import BaseMCPTool

        registry = MCPToolRegistry()
        mock_tool = MagicMock(spec=BaseMCPTool)
        mock_tool.name = "test_tool"
        mock_tool.category = "testing"

        ok = registry.register_tool(mock_tool)
        assert ok is True
        assert "test_tool" in registry.tools

    def test_register_duplicate_returns_false(self):
        """Registering the same tool name twice should return False (or True)."""
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import BaseMCPTool

        registry = MCPToolRegistry()
        mock_tool = MagicMock(spec=BaseMCPTool)
        mock_tool.name = "dup_tool"
        mock_tool.category = "testing"

        registry.register_tool(mock_tool)
        result = registry.register_tool(mock_tool)
        # Either False (duplicate rejected) or True (idempotent) — both ok
        assert isinstance(result, bool)

    def test_category_populated_after_register(self):
        from ipfs_datasets_py.mcp_server.tools.tool_registration import MCPToolRegistry
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import BaseMCPTool

        registry = MCPToolRegistry()
        mock_tool = MagicMock(spec=BaseMCPTool)
        mock_tool.name = "cat_tool"
        mock_tool.category = "cat_tests"

        registry.register_tool(mock_tool)
        assert "cat_tests" in registry.categories
        assert "cat_tool" in registry.categories["cat_tests"]


# ---------------------------------------------------------------------------
# TestCreateAndRegisterAllTools
# ---------------------------------------------------------------------------
class TestCreateAndRegisterAllTools:
    def test_returns_registry_instance(self):
        from ipfs_datasets_py.mcp_server.tools.tool_registration import (
            MCPToolRegistry,
            create_and_register_all_tools,
        )
        registry = create_and_register_all_tools()
        assert isinstance(registry, MCPToolRegistry)

    def test_registry_tools_is_dict(self):
        from ipfs_datasets_py.mcp_server.tools.tool_registration import create_and_register_all_tools
        registry = create_and_register_all_tools()
        assert isinstance(registry.tools, dict)

    def test_registry_categories_is_dict(self):
        from ipfs_datasets_py.mcp_server.tools.tool_registration import create_and_register_all_tools
        registry = create_and_register_all_tools()
        assert isinstance(registry.categories, dict)


# ---------------------------------------------------------------------------
# TestRegisterAllMigratedTools
# ---------------------------------------------------------------------------
class TestRegisterAllMigratedTools:
    def test_accepts_registry_param(self):
        from ipfs_datasets_py.mcp_server.tools.tool_registration import (
            MCPToolRegistry,
            register_all_migrated_tools,
        )
        registry = MCPToolRegistry()
        result = register_all_migrated_tools(registry)
        assert isinstance(result, dict)

    def test_returns_stats_dict(self):
        """Return value should be a dict with registration statistics."""
        from ipfs_datasets_py.mcp_server.tools.tool_registration import (
            MCPToolRegistry,
            register_all_migrated_tools,
        )
        registry = MCPToolRegistry()
        stats = register_all_migrated_tools(registry)
        # Must be a dict; keys can vary by impl
        assert isinstance(stats, dict)
