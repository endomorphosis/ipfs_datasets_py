"""
Session 41 — Tests for tool_metadata.py to push coverage from 0% to 100%.

Covers:
- ToolMetadata dataclass (construction, defaults, invalid runtime, to_dict, validate_complete)
- ToolMetadataRegistry (register, get, list_by_runtime, list_by_category, list_all,
  get_by_runtime, get_by_category, get_statistics, clear, runtime warning on re-register)
- get_registry() global accessor
- tool_metadata() decorator (registers metadata, attaches attributes, uses docstring)
- get_tool_metadata() by function and by name
- Module constants (RUNTIME_FASTAPI, RUNTIME_TRIO, RUNTIME_AUTO)
"""
import pytest
from unittest.mock import MagicMock

from ipfs_datasets_py.mcp_server.tool_metadata import (
    ToolMetadata,
    ToolMetadataRegistry,
    get_registry,
    get_tool_metadata,
    tool_metadata,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
    RUNTIME_AUTO,
)


# ===========================================================================
# Module constants
# ===========================================================================

class TestModuleConstants:
    def test_runtime_constants_defined(self):
        assert RUNTIME_FASTAPI == "fastapi"
        assert RUNTIME_TRIO == "trio"
        assert RUNTIME_AUTO == "auto"


# ===========================================================================
# ToolMetadata
# ===========================================================================

class TestToolMetadata:

    def test_minimal_construction(self):
        meta = ToolMetadata(name="test_tool")
        assert meta.name == "test_tool"
        assert meta.runtime == RUNTIME_AUTO
        assert meta.requires_p2p is False
        assert meta.category == "general"
        assert meta.priority == 5
        assert meta.deprecated is False
        assert meta.deprecation_message == ""
        assert meta.schema_version == "1.0"

    def test_full_construction(self):
        meta = ToolMetadata(
            name="p2p_tool",
            runtime=RUNTIME_TRIO,
            requires_p2p=True,
            category="p2p_workflow",
            priority=9,
            timeout_seconds=60.0,
            retry_policy="exponential",
            memory_intensive=True,
            cpu_intensive=True,
            io_intensive=True,
            mcp_schema={"type": "object"},
            mcp_description="A P2P tool",
            cache_ttl=30.0,
            schema_version="2.0",
            deprecated=True,
            deprecation_message="Use new_tool instead",
        )
        assert meta.runtime == RUNTIME_TRIO
        assert meta.requires_p2p is True
        assert meta.deprecated is True
        assert meta.schema_version == "2.0"
        assert meta.cache_ttl == 30.0

    def test_invalid_runtime_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid runtime"):
            ToolMetadata(name="bad_tool", runtime="invalid_runtime")

    def test_to_dict_excludes_func(self):
        mock_func = MagicMock()
        meta = ToolMetadata(name="tool", _func=mock_func)
        d = meta.to_dict()
        assert "name" in d
        assert "_func" not in d
        assert d["name"] == "tool"

    def test_validate_complete_minimal(self):
        """Minimal ToolMetadata (no description/schema) should produce warnings."""
        meta = ToolMetadata(name="bare_tool")
        warnings = meta.validate_complete()
        assert isinstance(warnings, list)
        # No name warning (name is set), but should warn about missing description/schema
        assert any("description" in w.lower() or "schema" in w.lower() for w in warnings)

    def test_validate_complete_full(self):
        """Fully-populated ToolMetadata should return no warnings."""
        meta = ToolMetadata(
            name="complete_tool",
            mcp_description="A complete tool",
            mcp_schema={"type": "object"},
            runtime=RUNTIME_AUTO,
        )
        warnings = meta.validate_complete()
        assert len(warnings) == 0

    def test_validate_complete_p2p_fastapi_warns(self):
        """P2P tool on FastAPI runtime should produce a warning."""
        meta = ToolMetadata(
            name="p2p_fastapi",
            runtime=RUNTIME_FASTAPI,
            requires_p2p=True,
            mcp_description="desc",
            mcp_schema={"type": "object"},
        )
        warnings = meta.validate_complete()
        assert any("trio" in w.lower() for w in warnings)

    def test_frozen_prevents_mutation(self):
        """ToolMetadata is frozen=True — direct attribute assignment should fail."""
        meta = ToolMetadata(name="frozen_tool")
        with pytest.raises((AttributeError, TypeError)):
            meta.name = "other_name"  # type: ignore[misc]


# ===========================================================================
# ToolMetadataRegistry
# ===========================================================================

class TestToolMetadataRegistry:

    def _make_registry(self) -> ToolMetadataRegistry:
        r = ToolMetadataRegistry()
        return r

    def test_register_and_get(self):
        r = self._make_registry()
        meta = ToolMetadata(name="my_tool", runtime=RUNTIME_AUTO)
        r.register(meta)
        assert r.get("my_tool") is meta

    def test_get_missing_returns_none(self):
        r = self._make_registry()
        assert r.get("nonexistent") is None

    def test_list_by_runtime_empty(self):
        r = self._make_registry()
        assert r.list_by_runtime(RUNTIME_FASTAPI) == []

    def test_list_by_runtime_returns_matching(self):
        r = self._make_registry()
        r.register(ToolMetadata(name="fastapi_tool", runtime=RUNTIME_FASTAPI))
        r.register(ToolMetadata(name="trio_tool", runtime=RUNTIME_TRIO))
        fastapi_tools = r.list_by_runtime(RUNTIME_FASTAPI)
        assert len(fastapi_tools) == 1
        assert fastapi_tools[0].name == "fastapi_tool"

    def test_list_by_category(self):
        r = self._make_registry()
        r.register(ToolMetadata(name="tool_a", category="search"))
        r.register(ToolMetadata(name="tool_b", category="search"))
        r.register(ToolMetadata(name="tool_c", category="dataset"))
        search_tools = r.list_by_category("search")
        assert len(search_tools) == 2
        assert {t.name for t in search_tools} == {"tool_a", "tool_b"}

    def test_list_by_category_missing_returns_empty(self):
        r = self._make_registry()
        assert r.list_by_category("nonexistent_category") == []

    def test_list_all_returns_all_registered(self):
        r = self._make_registry()
        r.register(ToolMetadata(name="a"))
        r.register(ToolMetadata(name="b"))
        r.register(ToolMetadata(name="c"))
        assert len(r.list_all()) == 3

    def test_get_by_runtime_delegates_to_list_by_runtime(self):
        r = self._make_registry()
        r.register(ToolMetadata(name="trio_tool", runtime=RUNTIME_TRIO))
        result = r.get_by_runtime(RUNTIME_TRIO)
        assert len(result) == 1

    def test_get_by_category_delegates(self):
        r = self._make_registry()
        r.register(ToolMetadata(name="cat_tool", category="graph"))
        result = r.get_by_category("graph")
        assert len(result) == 1

    def test_get_statistics_empty(self):
        r = self._make_registry()
        stats = r.get_statistics()
        assert stats["total"] == 0
        assert stats["total_tools"] == 0
        assert stats["p2p_tools"] == 0

    def test_get_statistics_with_tools(self):
        r = self._make_registry()
        r.register(ToolMetadata(name="p2p_tool", requires_p2p=True, category="p2p"))
        r.register(ToolMetadata(name="regular_tool", requires_p2p=False, category="search"))
        stats = r.get_statistics()
        assert stats["total"] == 2
        assert stats["p2p_tools"] == 1
        assert stats["categories"] == 2

    def test_clear_empties_registry(self):
        r = self._make_registry()
        r.register(ToolMetadata(name="tool_to_clear"))
        r.clear()
        assert r.get("tool_to_clear") is None
        assert len(r.list_all()) == 0

    def test_reregister_different_runtime_logs_warning(self, caplog):
        """Re-registering a tool with a different runtime should log a warning."""
        import logging
        r = self._make_registry()
        r.register(ToolMetadata(name="my_tool", runtime=RUNTIME_FASTAPI))
        with caplog.at_level(logging.WARNING, logger="ipfs_datasets_py.mcp_server.tool_metadata"):
            r.register(ToolMetadata(name="my_tool", runtime=RUNTIME_TRIO))
        assert any("my_tool" in record.message for record in caplog.records)


# ===========================================================================
# get_registry() global accessor
# ===========================================================================

class TestGetRegistry:

    def test_get_registry_returns_instance(self):
        registry = get_registry()
        assert isinstance(registry, ToolMetadataRegistry)

    def test_get_registry_returns_same_global_instance(self):
        """Without a context argument, repeated calls return the same global instance."""
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2


# ===========================================================================
# tool_metadata() decorator
# ===========================================================================

class TestToolMetadataDecorator:

    def test_decorator_registers_tool(self):
        """@tool_metadata() should register the function in the global registry."""
        # Use a unique name to avoid collisions with other tests
        @tool_metadata(runtime=RUNTIME_AUTO, category="test_cat_41")
        def my_decorated_tool_41():
            """A test tool."""
            pass

        meta = get_registry().get("my_decorated_tool_41")
        assert meta is not None
        assert meta.runtime == RUNTIME_AUTO
        assert meta.category == "test_cat_41"

    def test_decorator_attaches_attributes(self):
        @tool_metadata(runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p")
        def my_p2p_tool_41():
            pass

        assert my_p2p_tool_41._mcp_runtime == RUNTIME_TRIO
        assert my_p2p_tool_41._mcp_requires_p2p is True
        assert my_p2p_tool_41._mcp_category == "p2p"

    def test_decorator_uses_docstring_as_description(self):
        @tool_metadata()
        def tool_with_docstring_41():
            """This is the docstring description."""
            pass

        meta = get_registry().get("tool_with_docstring_41")
        assert "docstring" in (meta.mcp_description or "")

    def test_decorator_with_explicit_description(self):
        @tool_metadata(mcp_description="Explicit description")
        def tool_explicit_desc_41():
            pass

        meta = get_registry().get("tool_explicit_desc_41")
        assert meta.mcp_description == "Explicit description"

    def test_decorator_with_deprecation(self):
        @tool_metadata(deprecated=True, deprecation_message="Use new_tool instead")
        def deprecated_tool_41():
            pass

        meta = get_registry().get("deprecated_tool_41")
        assert meta.deprecated is True
        assert "new_tool" in meta.deprecation_message

    def test_decorator_preserves_function(self):
        """The decorated function should remain callable."""
        @tool_metadata()
        def callable_tool_41():
            return "result"

        assert callable_tool_41() == "result"

    def test_decorator_with_schema_version(self):
        @tool_metadata(schema_version="3.1", cache_ttl=120.0)
        def versioned_tool_41():
            pass

        meta = get_registry().get("versioned_tool_41")
        assert meta.schema_version == "3.1"
        assert meta.cache_ttl == 120.0


# ===========================================================================
# get_tool_metadata()
# ===========================================================================

class TestGetToolMetadata:

    def test_get_by_name_string(self):
        @tool_metadata(category="test_lookup")
        def lookup_tool_by_name_41():
            pass

        meta = get_tool_metadata("lookup_tool_by_name_41")
        assert meta is not None
        assert meta.name == "lookup_tool_by_name_41"

    def test_get_by_function(self):
        @tool_metadata(category="test_lookup_fn")
        def lookup_tool_by_fn_41():
            pass

        meta = get_tool_metadata(lookup_tool_by_fn_41)
        assert meta is not None
        assert meta.category == "test_lookup_fn"

    def test_get_missing_name_returns_none(self):
        result = get_tool_metadata("completely_nonexistent_tool_xyz_41")
        assert result is None

    def test_get_by_function_via_attribute(self):
        """get_tool_metadata returns _mcp_metadata attribute if set."""
        @tool_metadata()
        def tool_with_attr_41():
            pass

        # The decorated function should have _mcp_metadata
        assert hasattr(tool_with_attr_41, "_mcp_metadata")
        meta = get_tool_metadata(tool_with_attr_41)
        assert meta is tool_with_attr_41._mcp_metadata


# ===========================================================================
# Edge cases for 100% coverage
# ===========================================================================

class TestEdgeCases:

    def test_validate_complete_empty_name(self):
        """An empty name string should produce a 'name is required' warning."""
        # Bypass frozen dataclass restriction with object.__new__
        meta = object.__new__(ToolMetadata)
        object.__setattr__(meta, "name", "")
        object.__setattr__(meta, "mcp_description", None)
        object.__setattr__(meta, "mcp_schema", None)
        object.__setattr__(meta, "requires_p2p", False)
        object.__setattr__(meta, "runtime", RUNTIME_AUTO)
        warnings = meta.validate_complete()
        assert any("name" in w.lower() for w in warnings)

    def test_get_registry_with_context(self):
        """get_registry(context) should return context.metadata_registry."""
        mock_context = MagicMock()
        mock_registry = ToolMetadataRegistry()
        mock_context.metadata_registry = mock_registry
        result = get_registry(context=mock_context)
        assert result is mock_registry

    def test_get_tool_metadata_fallback_registry_lookup(self):
        """get_tool_metadata(func_without_attr) should fall back to registry lookup."""
        # A plain function without _mcp_metadata attribute
        def plain_function_for_test_41():
            pass
        # Register it manually in the global registry
        get_registry().register(ToolMetadata(name="plain_function_for_test_41"))
        result = get_tool_metadata(plain_function_for_test_41)
        assert result is not None
        assert result.name == "plain_function_for_test_41"
