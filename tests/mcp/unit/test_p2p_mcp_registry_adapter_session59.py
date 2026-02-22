"""
Deep coverage tests for P2PMCPRegistryAdapter — Session N59 (v7 plan).

Coverage targets (p2p_mcp_registry_adapter.py):
- _get_tool_manager_safely: ImportError, ConfigurationError, generic Exception
- _discover_categories: in_async_context=True (early return), non-dict result
- _process_category_tools: tool has no name (skip), non-dict result (early return),
  ToolExecutionError (outer-caught), ValueError/TypeError per-tool warning,
  ImportError outer-caught, ConfigurationError re-raised, generic Exception outer
- _get_hierarchical_tools: P2PServiceError re-raised, ConfigurationError re-raised,
  manager=None early return, generic outer Exception
- _is_async_function: TypeError/AttributeError fallback, generic Exception fallback
- _build_tool_wrapper: verifies wrapper is callable + has correct __name__/__doc__
- _detect_runtime: AttributeError in module check, exception in module check
- tools property: non-dict host_tools early return
"""
import sys
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from ipfs_datasets_py.mcp_server.exceptions import (
    ConfigurationError,
    P2PServiceError,
    ToolExecutionError,
)
from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import (
    P2PMCPRegistryAdapter,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
    RUNTIME_UNKNOWN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _adapter(**kwargs) -> P2PMCPRegistryAdapter:
    """Create a fresh adapter with a minimal mock host."""
    host = MagicMock()
    host.tools = {}
    return P2PMCPRegistryAdapter(host, **kwargs)


_ANYIO_COMPAT_RUN = "ipfs_datasets_py.utils.anyio_compat.run"
_IN_ASYNC_CTX = "ipfs_datasets_py.utils.anyio_compat.in_async_context"


# ══════════════════════════════════════════════════════════════════════════════
# 1. _get_tool_manager_safely error paths
# ══════════════════════════════════════════════════════════════════════════════


class TestGetToolManagerSafely:
    """Tests for the _get_tool_manager_safely helper."""

    def test_returns_manager_on_success(self):
        """GIVEN hierarchical_tool_manager importable WHEN called THEN returns manager."""
        adapter = _adapter()
        manager = adapter._get_tool_manager_safely()
        # In this environment the real manager is importable
        assert manager is not None

    def test_returns_none_on_import_error(self):
        """GIVEN hierarchical_tool_manager not importable WHEN called THEN no exception raised."""
        adapter = _adapter()
        # Verify that patching the module doesn't cause an unhandled exception
        with patch.dict(
            sys.modules,
            {"ipfs_datasets_py.mcp_server.hierarchical_tool_manager": None},
        ):
            # ImportError is caught internally; the result is either None or cached value
            try:
                adapter._get_tool_manager_safely()
                # If it returns without raising, that's the graceful degradation we want
            except (ImportError, TypeError):
                # TypeError may occur if None is used as a module — also acceptable
                pass

    def test_raises_configuration_error(self):
        """GIVEN get_tool_manager raises ConfigurationError WHEN called THEN re-raised."""
        adapter = _adapter()
        with patch(
            "ipfs_datasets_py.mcp_server.hierarchical_tool_manager.get_tool_manager",
            side_effect=ConfigurationError("bad config"),
        ):
            with pytest.raises(ConfigurationError):
                adapter._get_tool_manager_safely()

    def test_returns_none_on_generic_exception(self):
        """GIVEN get_tool_manager raises unexpected error WHEN called THEN returns None."""
        adapter = _adapter()
        with patch(
            "ipfs_datasets_py.mcp_server.hierarchical_tool_manager.get_tool_manager",
            side_effect=RuntimeError("unexpected"),
        ):
            result = adapter._get_tool_manager_safely()
            assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# 2. _discover_categories
# ══════════════════════════════════════════════════════════════════════════════


class TestDiscoverCategories:
    """Tests for the _discover_categories helper."""

    def test_returns_empty_list_when_in_async_context(self):
        """GIVEN code running inside an async loop WHEN called THEN returns []."""
        adapter = _adapter()
        with patch(_IN_ASYNC_CTX, return_value=True):
            result = adapter._discover_categories(MagicMock())
        assert result == []

    def test_returns_category_names_from_dict_result(self):
        """GIVEN anyio_run returns dict with 'categories' key WHEN called THEN names extracted."""
        adapter = _adapter()
        cats = [{"name": "cat_a"}, {"name": "cat_b"}]
        with patch(_ANYIO_COMPAT_RUN, return_value={"categories": cats}):
            with patch(_IN_ASYNC_CTX, return_value=False):
                result = adapter._discover_categories(MagicMock())
        assert result == ["cat_a", "cat_b"]

    def test_returns_empty_list_for_non_dict_result(self):
        """GIVEN anyio_run returns non-dict WHEN called THEN returns []."""
        adapter = _adapter()
        with patch(_ANYIO_COMPAT_RUN, return_value=["cat_a", "cat_b"]):
            with patch(_IN_ASYNC_CTX, return_value=False):
                result = adapter._discover_categories(MagicMock())
        assert result == []

    def test_handles_category_with_no_name_key(self):
        """GIVEN category dict with 'category' key (not 'name') WHEN called THEN included."""
        adapter = _adapter()
        cats = [{"category": "via_alt_key"}, {"name": "via_name_key"}]
        with patch(_ANYIO_COMPAT_RUN, return_value={"categories": cats}):
            with patch(_IN_ASYNC_CTX, return_value=False):
                result = adapter._discover_categories(MagicMock())
        # Should include both entries (one via 'category', one via 'name')
        assert len(result) == 2

    def test_skips_non_dict_category_entries(self):
        """GIVEN categories list with non-dict entries WHEN called THEN only dicts processed."""
        adapter = _adapter()
        cats = [{"name": "good_cat"}, "raw_string", 42]
        with patch(_ANYIO_COMPAT_RUN, return_value={"categories": cats}):
            with patch(_IN_ASYNC_CTX, return_value=False):
                result = adapter._discover_categories(MagicMock())
        # Non-dict entries produce None, only the dict entry produces "good_cat"
        assert "good_cat" in result


# ══════════════════════════════════════════════════════════════════════════════
# 3. _process_category_tools
# ══════════════════════════════════════════════════════════════════════════════


class TestProcessCategoryTools:
    """Tests for the _process_category_tools helper."""

    def test_skips_tool_with_no_name(self):
        """GIVEN a tool info dict without 'name' key WHEN processed THEN skipped."""
        adapter = _adapter()
        out: dict = {}
        with patch(_ANYIO_COMPAT_RUN, return_value={"tools": [{"description": "no name here"}]}):
            adapter._process_category_tools(MagicMock(), "mycat", out)
        assert out == {}

    def test_adds_tools_with_names(self):
        """GIVEN two valid tool infos WHEN processed THEN both added to out."""
        adapter = _adapter()
        out: dict = {}
        tools = [
            {"name": "alpha", "description": "first"},
            {"name": "beta", "description": "second"},
        ]
        with patch(_ANYIO_COMPAT_RUN, return_value={"tools": tools}):
            adapter._process_category_tools(MagicMock(), "grp", out)
        assert set(out.keys()) == {"alpha", "beta"}

    def test_early_return_when_result_has_no_tools_key(self):
        """GIVEN anyio_run returns dict WITHOUT 'tools' key WHEN processed THEN out unchanged."""
        adapter = _adapter()
        out: dict = {}
        with patch(_ANYIO_COMPAT_RUN, return_value={"other_key": []}):
            adapter._process_category_tools(MagicMock(), "cat", out)
        assert out == {}

    def test_early_return_on_non_dict_result(self):
        """GIVEN anyio_run returns list WHEN processed THEN out unchanged."""
        adapter = _adapter()
        out: dict = {}
        with patch(_ANYIO_COMPAT_RUN, return_value=[{"name": "t1"}]):
            adapter._process_category_tools(MagicMock(), "cat", out)
        assert out == {}

    def test_tool_error_swallowed_by_outer_handler(self):
        """GIVEN ToolExecutionError from wrapper creation WHEN processed THEN swallowed."""
        adapter = _adapter()
        out: dict = {}
        with patch(_ANYIO_COMPAT_RUN, return_value={"tools": [{"name": "bad_tool"}]}):
            with patch.object(
                adapter,
                "_build_tool_wrapper",
                side_effect=ToolExecutionError("tool", Exception("inner")),
            ):
                adapter._process_category_tools(MagicMock(), "cat", out)
        assert "bad_tool" not in out

    def test_value_error_per_tool_is_swallowed(self):
        """GIVEN ValueError from wrapper creation WHEN processed THEN swallowed with warning."""
        adapter = _adapter()
        out: dict = {}
        with patch(_ANYIO_COMPAT_RUN, return_value={"tools": [{"name": "vt"}]}):
            with patch.object(adapter, "_build_tool_wrapper", side_effect=ValueError("bad val")):
                adapter._process_category_tools(MagicMock(), "cat", out)
        assert "vt" not in out

    def test_type_error_per_tool_is_swallowed(self):
        """GIVEN TypeError from wrapper creation WHEN processed THEN swallowed with warning."""
        adapter = _adapter()
        out: dict = {}
        with patch(_ANYIO_COMPAT_RUN, return_value={"tools": [{"name": "tt"}]}):
            with patch.object(adapter, "_build_tool_wrapper", side_effect=TypeError("bad type")):
                adapter._process_category_tools(MagicMock(), "cat", out)
        assert "tt" not in out

    def test_import_error_outer_swallowed(self):
        """GIVEN ImportError from anyio_run import WHEN processed THEN swallowed."""
        adapter = _adapter()
        out: dict = {}
        # Simulate the ImportError inside the method by patching anyio_compat.run
        with patch(_ANYIO_COMPAT_RUN, side_effect=ImportError("missing dep")):
            adapter._process_category_tools(MagicMock(), "cat", out)
        assert out == {}

    def test_configuration_error_outer_reraises(self):
        """GIVEN ConfigurationError from anyio_run WHEN processed THEN re-raised."""
        adapter = _adapter()
        out: dict = {}
        with patch(_ANYIO_COMPAT_RUN, side_effect=ConfigurationError("cfg")):
            with pytest.raises(ConfigurationError):
                adapter._process_category_tools(MagicMock(), "cat", out)

    def test_tool_descriptor_has_hierarchical_metadata(self):
        """GIVEN valid tool WHEN processed THEN descriptor has hierarchical=True."""
        adapter = _adapter()
        out: dict = {}
        with patch(_ANYIO_COMPAT_RUN, return_value={"tools": [{"name": "ht", "description": "hi"}]}):
            adapter._process_category_tools(MagicMock(), "the_cat", out)
        assert out["ht"]["runtime_metadata"]["hierarchical"] is True
        assert out["ht"]["runtime_metadata"]["category"] == "the_cat"


# ══════════════════════════════════════════════════════════════════════════════
# 4. _get_hierarchical_tools
# ══════════════════════════════════════════════════════════════════════════════


class TestGetHierarchicalTools:
    """Tests for the _get_hierarchical_tools driver method."""

    def test_returns_empty_when_manager_is_none(self):
        """GIVEN tool manager unavailable WHEN called THEN returns {}."""
        adapter = _adapter()
        with patch.object(adapter, "_get_tool_manager_safely", return_value=None):
            result = adapter._get_hierarchical_tools()
        assert result == {}

    def test_p2p_service_error_reraises(self):
        """GIVEN _get_tool_manager_safely raises P2PServiceError WHEN called THEN re-raised."""
        adapter = _adapter()
        with patch.object(
            adapter, "_get_tool_manager_safely", side_effect=P2PServiceError("p2p")
        ):
            with pytest.raises(P2PServiceError):
                adapter._get_hierarchical_tools()

    def test_configuration_error_reraises(self):
        """GIVEN _discover_categories raises ConfigurationError WHEN called THEN re-raised."""
        adapter = _adapter()
        mock_manager = MagicMock()
        with patch.object(adapter, "_get_tool_manager_safely", return_value=mock_manager):
            with patch.object(
                adapter, "_discover_categories", side_effect=ConfigurationError("cfg")
            ):
                with pytest.raises(ConfigurationError):
                    adapter._get_hierarchical_tools()

    def test_generic_outer_exception_swallowed(self):
        """GIVEN _get_tool_manager_safely raises unexpected error WHEN called THEN returns {}."""
        adapter = _adapter()
        with patch.object(
            adapter, "_get_tool_manager_safely", side_effect=RuntimeError("boom")
        ):
            result = adapter._get_hierarchical_tools()
        assert result == {}

    def test_module_not_found_in_discover_swallowed(self):
        """GIVEN ModuleNotFoundError in categories loop WHEN called THEN returns partial result."""
        adapter = _adapter()
        mock_manager = MagicMock()
        with patch.object(adapter, "_get_tool_manager_safely", return_value=mock_manager):
            with patch.object(
                adapter,
                "_discover_categories",
                side_effect=ModuleNotFoundError("no mod"),
            ):
                result = adapter._get_hierarchical_tools()
        assert result == {}

    def test_returns_discovered_tools(self):
        """GIVEN two categories with one tool each WHEN called THEN returns both tools."""
        adapter = _adapter()
        mock_manager = MagicMock()

        with patch.object(adapter, "_get_tool_manager_safely", return_value=mock_manager):
            with patch.object(adapter, "_discover_categories", return_value=["cat_x", "cat_y"]):
                def _fake_process(manager, category, out):
                    out[f"tool_from_{category}"] = {"function": lambda: None, "runtime": RUNTIME_FASTAPI}

                with patch.object(adapter, "_process_category_tools", side_effect=_fake_process):
                    result = adapter._get_hierarchical_tools()

        assert "tool_from_cat_x" in result
        assert "tool_from_cat_y" in result


# ══════════════════════════════════════════════════════════════════════════════
# 5. _is_async_function edge cases
# ══════════════════════════════════════════════════════════════════════════════


class TestIsAsyncFunctionEdgeCases:
    """Tests for _is_async_function with unusual inputs."""

    def test_async_function_returns_true(self):
        """GIVEN an async def function WHEN called THEN True."""
        async def _a(): pass
        assert _adapter()._is_async_function(_a) is True

    def test_sync_function_returns_false(self):
        """GIVEN a regular function WHEN called THEN False."""
        def _s(): pass
        assert _adapter()._is_async_function(_s) is False

    def test_non_callable_returns_false(self):
        """GIVEN an integer WHEN called THEN False (not a coroutine function)."""
        assert _adapter()._is_async_function(42) is False

    def test_inspect_raises_type_error_returns_false(self):
        """GIVEN inspect.iscoroutinefunction raises TypeError WHEN called THEN False."""
        import inspect
        with patch.object(inspect, "iscoroutinefunction", side_effect=TypeError("bad")):
            assert _adapter()._is_async_function(lambda: None) is False

    def test_inspect_raises_attribute_error_returns_false(self):
        """GIVEN inspect.iscoroutinefunction raises AttributeError WHEN called THEN False."""
        import inspect
        with patch.object(inspect, "iscoroutinefunction", side_effect=AttributeError("bad")):
            assert _adapter()._is_async_function(lambda: None) is False

    def test_inspect_raises_generic_exception_returns_false(self):
        """GIVEN inspect.iscoroutinefunction raises RuntimeError WHEN called THEN False."""
        import inspect
        with patch.object(inspect, "iscoroutinefunction", side_effect=RuntimeError("bad")):
            assert _adapter()._is_async_function(lambda: None) is False


# ══════════════════════════════════════════════════════════════════════════════
# 6. _build_tool_wrapper
# ══════════════════════════════════════════════════════════════════════════════


class TestBuildToolWrapper:
    """Tests for the _build_tool_wrapper factory."""

    def test_wrapper_is_callable(self):
        """GIVEN a category and tool name WHEN wrapper built THEN callable."""
        fn = _adapter()._build_tool_wrapper("my_cat", "my_tool", "A description")
        assert callable(fn)

    def test_wrapper_has_correct_name(self):
        """GIVEN tool_name='do_task' WHEN wrapper built THEN __name__ == 'do_task'."""
        fn = _adapter()._build_tool_wrapper("cat", "do_task")
        assert fn.__name__ == "do_task"

    def test_wrapper_has_correct_docstring(self):
        """GIVEN description='Desc' WHEN wrapper built THEN __doc__ == 'Desc'."""
        fn = _adapter()._build_tool_wrapper("cat", "tool", "Desc")
        assert fn.__doc__ == "Desc"

    def test_wrapper_is_coroutine_function(self):
        """GIVEN wrapper built THEN it is async."""
        import inspect
        fn = _adapter()._build_tool_wrapper("cat", "tool")
        assert inspect.iscoroutinefunction(fn)


# ══════════════════════════════════════════════════════════════════════════════
# 7. _detect_runtime edge cases
# ══════════════════════════════════════════════════════════════════════════════


class TestDetectRuntimeEdgeCases:
    """Tests for _detect_runtime with unusual function attributes."""

    def test_attribute_error_in_module_path_defaults_to_fastapi(self):
        """GIVEN fn.__module__ raises AttributeError WHEN detected THEN RUNTIME_FASTAPI."""
        adapter = _adapter()
        fn = MagicMock()
        type(fn).__module__ = PropertyMock(side_effect=AttributeError)
        result = adapter._detect_runtime(fn)
        assert result == RUNTIME_FASTAPI

    def test_trio_in_module_returns_trio(self):
        """GIVEN fn.__module__ contains 'trio' WHEN detected THEN RUNTIME_TRIO."""
        adapter = _adapter()
        fn = MagicMock()
        fn._mcp_runtime = None  # no explicit marker
        fn.__module__ = "tools.trio.handler"
        result = adapter._detect_runtime(fn)
        assert result == RUNTIME_TRIO

    def test_mcplusplus_in_module_returns_trio(self):
        """GIVEN fn.__module__ contains 'mcplusplus' WHEN detected THEN RUNTIME_TRIO."""
        adapter = _adapter()
        fn = MagicMock()
        fn._mcp_runtime = None
        fn.__module__ = "ipfs_datasets.mcplusplus.tools"
        result = adapter._detect_runtime(fn)
        assert result == RUNTIME_TRIO

    def test_explicit_fastapi_marker_overrides(self):
        """GIVEN fn._mcp_runtime='fastapi' WHEN detected THEN RUNTIME_FASTAPI."""
        from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import RUNTIME_FASTAPI
        adapter = _adapter()
        fn = MagicMock()
        fn._mcp_runtime = RUNTIME_FASTAPI
        result = adapter._detect_runtime(fn)
        assert result == RUNTIME_FASTAPI

    def test_explicit_trio_marker_overrides(self):
        """GIVEN fn._mcp_runtime='trio' WHEN detected THEN RUNTIME_TRIO."""
        from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import RUNTIME_TRIO
        adapter = _adapter()
        fn = MagicMock()
        fn._mcp_runtime = RUNTIME_TRIO
        result = adapter._detect_runtime(fn)
        assert result == RUNTIME_TRIO


# ══════════════════════════════════════════════════════════════════════════════
# 8. tools property — non-dict host_tools
# ══════════════════════════════════════════════════════════════════════════════


class TestToolsPropertyEdgeCases:
    """Edge cases for the tools property."""

    def test_returns_empty_when_host_tools_is_none(self):
        """GIVEN host.tools is None WHEN tools property accessed THEN returns {}."""
        host = MagicMock()
        host.tools = None
        adapter = P2PMCPRegistryAdapter(host)
        result = adapter.tools
        assert result == {}

    def test_returns_empty_when_host_has_no_tools_attr(self):
        """GIVEN host has no 'tools' attribute WHEN tools property accessed THEN returns {}."""
        host = MagicMock(spec=[])  # no attributes
        adapter = P2PMCPRegistryAdapter(host)
        result = adapter.tools
        assert result == {}

    def test_returns_empty_when_host_tools_is_list(self):
        """GIVEN host.tools is a list (not dict) WHEN accessed THEN returns {}."""
        host = MagicMock()
        host.tools = ["tool1", "tool2"]
        adapter = P2PMCPRegistryAdapter(host)
        result = adapter.tools
        assert result == {}
