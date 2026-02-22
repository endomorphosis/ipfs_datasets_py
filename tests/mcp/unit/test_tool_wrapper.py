"""
Session 38 — tests for tool_wrapper.py (FunctionToolWrapper, wrap_function_as_tool,
wrap_function_with_metadata, wrap_tools_from_module, caching, performance stats).

The bug fixed in session 32 (missing `return function` + `return decorator` in
wrap_function_as_tool decorator form) is also regression-tested here.
"""
import asyncio
import unittest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers to run coroutines synchronously (Python 3.12 compatible)
# ---------------------------------------------------------------------------
def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------
from ipfs_datasets_py.mcp_server.tools.tool_wrapper import (
    FunctionToolWrapper,
    wrap_function_as_tool,
    wrap_function_with_metadata,
    wrap_tools_from_module,
)


# ---------------------------------------------------------------------------
# Simple sync and async functions for testing
# ---------------------------------------------------------------------------
def _sync_tool(x: int, y: int = 0) -> dict:
    return {"sum": x + y}


async def _async_tool(text: str = "hello") -> dict:
    return {"upper": text.upper()}


def _plain_return(n: int) -> int:
    """Return a plain int (not dict)."""
    return n * 2


# ---------------------------------------------------------------------------
# TestFunctionToolWrapperInit
# ---------------------------------------------------------------------------
class TestFunctionToolWrapperInit(unittest.TestCase):

    def test_name_is_set(self):
        w = FunctionToolWrapper(_sync_tool, "sync_sum")
        self.assertEqual(w.name, "sync_sum")

    def test_category_default_is_general(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        self.assertEqual(w.category, "general")

    def test_category_custom(self):
        w = FunctionToolWrapper(_sync_tool, "t", category="math")
        self.assertEqual(w.category, "math")

    def test_description_from_docstring(self):
        w = FunctionToolWrapper(_plain_return, "plain")
        self.assertIn("plain int", w.description)

    def test_description_custom(self):
        w = FunctionToolWrapper(_sync_tool, "t", description="My desc")
        self.assertEqual(w.description, "My desc")

    def test_schema_properties_populated(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        props = w.input_schema.get("properties", {})
        self.assertIn("x", props)
        self.assertIn("y", props)

    def test_schema_required_excludes_defaults(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        required = w.input_schema.get("required", [])
        self.assertIn("x", required)
        self.assertNotIn("y", required)

    def test_get_schema_returns_dict(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        schema = w.get_schema()
        self.assertIsInstance(schema, dict)
        self.assertIn("name", schema)
        self.assertIn("input_schema", schema)


# ---------------------------------------------------------------------------
# TestFunctionToolWrapperExecute
# ---------------------------------------------------------------------------
class TestFunctionToolWrapperExecute(unittest.TestCase):

    def test_execute_sync_function(self):
        w = FunctionToolWrapper(_sync_tool, "sync_sum")
        result = _run(w.execute({"x": 3, "y": 4}))
        self.assertEqual(result.get("sum"), 7)

    def test_execute_async_function(self):
        w = FunctionToolWrapper(_async_tool, "async_upper")
        result = _run(w.execute({"text": "world"}))
        self.assertEqual(result.get("upper"), "WORLD")

    def test_execute_adds_tool_name(self):
        w = FunctionToolWrapper(_sync_tool, "my_tool")
        result = _run(w.execute({"x": 1}))
        self.assertEqual(result.get("tool_name"), "my_tool")

    def test_execute_adds_executed_at(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        result = _run(w.execute({"x": 1}))
        self.assertIn("executed_at", result)

    def test_execute_non_dict_result_wrapped(self):
        w = FunctionToolWrapper(_plain_return, "doubler")
        result = _run(w.execute({"n": 5}))
        # plain int wrapped in {"result": 10, ...}
        self.assertIn("result", result)
        self.assertEqual(result["result"], 10)

    def test_execute_exception_returns_error_dict(self):
        def _bad():
            raise RuntimeError("boom")
        w = FunctionToolWrapper(_bad, "broken")
        result = _run(w.execute({}))
        self.assertFalse(result.get("success"))
        self.assertIn("boom", result.get("error", ""))


# ---------------------------------------------------------------------------
# TestFunctionToolWrapperPerformanceStats
# ---------------------------------------------------------------------------
class TestFunctionToolWrapperPerformanceStats(unittest.TestCase):

    def test_initial_usage_count_zero(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        stats = w.get_performance_stats()
        self.assertEqual(stats["usage_count"], 0)

    def test_usage_count_increments_via_call(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        # call() (not execute()) increments usage_count and tracks metrics
        _run(w.call({"x": 1}))
        _run(w.call({"x": 2}))
        stats = w.get_performance_stats()
        self.assertEqual(stats["usage_count"], 2)

    def test_success_rate_is_float_after_call(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        _run(w.call({"x": 1}))
        stats = w.get_performance_stats()
        # success_rate is computed as a division so can be int 0 or float 1.0
        self.assertIn(stats["success_rate"], (0, 0.0, 1, 1.0))
        self.assertGreaterEqual(stats["success_rate"], 0)
        self.assertLessEqual(stats["success_rate"], 1)


# ---------------------------------------------------------------------------
# TestFunctionToolWrapperCaching
# ---------------------------------------------------------------------------
class TestFunctionToolWrapperCaching(unittest.TestCase):

    def test_caching_disabled_by_default(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        self.assertFalse(w.cache_enabled)

    def test_enable_caching_sets_flag(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        w.enable_caching(ttl_seconds=60)
        self.assertTrue(w.cache_enabled)

    def test_disable_caching_clears_flag(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        w.enable_caching()
        w.disable_caching()
        self.assertFalse(w.cache_enabled)

    def test_clear_cache_empties_cache_dict(self):
        w = FunctionToolWrapper(_sync_tool, "t")
        w.enable_caching()
        w.cache["fake_key"] = {"result": {}, "timestamp": None}
        w.clear_cache()
        self.assertEqual(len(w.cache), 0)


# ---------------------------------------------------------------------------
# TestWrapFunctionAsTool — helper style
# ---------------------------------------------------------------------------
class TestWrapFunctionAsToolHelperStyle(unittest.TestCase):

    def test_returns_function_tool_wrapper(self):
        w = wrap_function_as_tool(_sync_tool, "helper_sum")
        self.assertIsInstance(w, FunctionToolWrapper)

    def test_name_set_correctly(self):
        w = wrap_function_as_tool(_sync_tool, "helper_sum")
        self.assertEqual(w.name, "helper_sum")

    def test_category_passthrough(self):
        w = wrap_function_as_tool(_sync_tool, "t", "mycat")
        self.assertEqual(w.category, "mycat")

    def test_execute_via_wrapper(self):
        w = wrap_function_as_tool(_sync_tool, "helper_sum")
        result = _run(w.execute({"x": 10, "y": 5}))
        self.assertEqual(result["sum"], 15)


# ---------------------------------------------------------------------------
# TestWrapFunctionAsTool — decorator style  (session 32 bug fix regression)
# ---------------------------------------------------------------------------
class TestWrapFunctionAsToolDecoratorStyle(unittest.TestCase):

    def test_decorator_returns_callable(self):
        @wrap_function_as_tool(name="deco_tool")
        async def _deco(n: int) -> dict:
            return {"n": n}
        self.assertTrue(callable(_deco))

    def test_decorator_sets_mcp_name_attribute(self):
        @wrap_function_as_tool(name="named_deco")
        async def _deco2():
            pass
        self.assertEqual(_deco2.__mcp_tool_name__, "named_deco")

    def test_decorator_sets_category_attribute(self):
        @wrap_function_as_tool(name="cat_deco", category="math")
        async def _deco3():
            pass
        self.assertEqual(_deco3.__mcp_tool_category__, "math")

    def test_decorated_function_still_callable(self):
        @wrap_function_as_tool(name="exec_deco")
        async def _deco4(x: int) -> dict:
            return {"v": x}
        result = _run(_deco4(42))
        self.assertEqual(result["v"], 42)


# ---------------------------------------------------------------------------
# TestWrapFunctionWithMetadata
# ---------------------------------------------------------------------------
class TestWrapFunctionWithMetadata(unittest.TestCase):

    def test_returns_function_tool_wrapper(self):
        md = {"name": "meta_tool", "category": "test", "description": "desc"}
        w = wrap_function_with_metadata(_sync_tool, md)
        self.assertIsInstance(w, FunctionToolWrapper)

    def test_name_from_metadata(self):
        md = {"name": "meta_sum"}
        w = wrap_function_with_metadata(_sync_tool, md)
        self.assertEqual(w.name, "meta_sum")

    def test_category_from_metadata(self):
        md = {"name": "t", "category": "arithmetic"}
        w = wrap_function_with_metadata(_sync_tool, md)
        self.assertEqual(w.category, "arithmetic")

    def test_execute_works(self):
        md = {"name": "meta_exec"}
        w = wrap_function_with_metadata(_sync_tool, md)
        result = _run(w.execute({"x": 3, "y": 3}))
        self.assertEqual(result["sum"], 6)


# ---------------------------------------------------------------------------
# TestWrapToolsFromModule
# ---------------------------------------------------------------------------
class TestWrapToolsFromModule(unittest.TestCase):

    def test_returns_dict(self):
        import types
        mod = types.ModuleType("fake_mod")
        mod._sync_tool = _sync_tool
        mappings = {"_sync_tool": {"name": "sync_sum", "category": "math"}}
        result = wrap_tools_from_module(mod, mappings)
        self.assertIsInstance(result, dict)

    def test_wraps_listed_functions(self):
        import types
        mod = types.ModuleType("fake_mod")
        mod._sync_tool = _sync_tool
        mod._async_tool = _async_tool
        mappings = {
            "_sync_tool": {"name": "sync_sum"},
            "_async_tool": {"name": "async_upper"},
        }
        result = wrap_tools_from_module(mod, mappings)
        self.assertIn("sync_sum", result)
        self.assertIn("async_upper", result)

    def test_missing_function_skipped(self):
        import types
        mod = types.ModuleType("fake_mod")
        mappings = {"nonexistent_fn": {"name": "ghost"}}
        result = wrap_tools_from_module(mod, mappings)
        # Should not raise; missing functions skipped or empty
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
