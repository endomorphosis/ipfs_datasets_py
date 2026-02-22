"""Phase H43 — Integration: Full dispatch_parallel workflow with 5 concurrent tools.

Covers lines 875-905 of hierarchical_tool_manager.py:
- Concurrent execution of N calls in a task group
- Results returned in the same order as calls
- Per-call exception capture (return_exceptions=True)
- Exception propagation (return_exceptions=False)
- Empty input fast-path

Test Format: GIVEN-WHEN-THEN
"""

import asyncio
import pytest
import tempfile
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, AsyncMock, patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    HierarchicalToolManager,
    ToolCategory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manager(tmp_path: Path) -> HierarchicalToolManager:
    """Return a HierarchicalToolManager pre-configured for dispatch tests."""
    mgr = HierarchicalToolManager(tmp_path)
    mgr._discovered_categories = True
    return mgr


def _register_sync_tool(mgr: HierarchicalToolManager, cat_name: str, tool_name: str, func):
    """Register a sync tool in a mock category on *mgr*."""
    mock_cat = Mock(spec=ToolCategory)
    mock_cat.get_tool.return_value = func
    mock_cat.list_tools.return_value = [{"name": tool_name}]
    # getattr(mock_cat, "_mcp_metadata", None) already returns None on a Mock
    mgr.categories[cat_name] = mock_cat


def _register_async_tool(mgr: HierarchicalToolManager, cat_name: str, tool_name: str, func):
    """Register an async tool in a mock category on *mgr*."""
    _register_sync_tool(mgr, cat_name, tool_name, func)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDispatchParallelEmptyInput:
    """Verify the empty-input fast-path (line 875-876)."""

    @pytest.mark.asyncio
    async def test_empty_calls_returns_empty_list(self, tmp_path):
        """GIVEN an empty list of calls
        WHEN dispatch_parallel is called
        THEN an empty list is returned immediately.
        """
        mgr = _make_manager(tmp_path)
        result = await mgr.dispatch_parallel([])
        assert result == []


class TestDispatchParallelAllSucceed:
    """Verify that 5 concurrent tool calls all succeed and results are ordered."""

    @pytest.mark.asyncio
    async def test_five_sync_tools_succeed_in_order(self, tmp_path):
        """GIVEN five sync tools returning their own index
        WHEN dispatch_parallel is called with all five
        THEN results come back in input order, each with status=success.
        """
        # GIVEN
        mgr = _make_manager(tmp_path)

        for i in range(5):
            idx = i  # capture loop variable for closure
            def make_tool(n):
                def tool() -> Dict[str, Any]:
                    return {"status": "success", "value": n}
                return tool
            _register_sync_tool(mgr, f"cat{i}", f"tool{i}", make_tool(i))

        calls = [
            {"category": f"cat{i}", "tool": f"tool{i}", "params": {}}
            for i in range(5)
        ]

        # WHEN
        results = await mgr.dispatch_parallel(calls)

        # THEN
        assert len(results) == 5
        for i, res in enumerate(results):
            assert res["status"] == "success"
            assert res["value"] == i

    @pytest.mark.asyncio
    async def test_five_async_tools_succeed_in_order(self, tmp_path):
        """GIVEN five async tools
        WHEN dispatch_parallel is called
        THEN results come back in input order.
        """
        # GIVEN
        mgr = _make_manager(tmp_path)

        for i in range(5):
            def make_async_tool(n):
                async def tool() -> Dict[str, Any]:
                    await asyncio.sleep(0)
                    return {"status": "success", "idx": n}
                return tool
            _register_async_tool(mgr, f"acat{i}", f"atool{i}", make_async_tool(i))

        calls = [
            {"category": f"acat{i}", "tool": f"atool{i}"}
            for i in range(5)
        ]

        # WHEN
        results = await mgr.dispatch_parallel(calls)

        # THEN
        assert len(results) == 5
        for i, res in enumerate(results):
            assert res["status"] == "success"
            assert res["idx"] == i

    @pytest.mark.asyncio
    async def test_params_forwarded_correctly(self, tmp_path):
        """GIVEN tools that accept parameters
        WHEN dispatch_parallel is called with params
        THEN each tool receives its own parameters.
        """
        # GIVEN
        mgr = _make_manager(tmp_path)

        def echo_tool(msg: str) -> Dict[str, Any]:
            return {"status": "success", "echo": msg}

        for i in range(3):
            _register_sync_tool(mgr, f"ecat{i}", "echo_tool", echo_tool)

        calls = [
            {"category": f"ecat{i}", "tool": "echo_tool", "params": {"msg": f"hello-{i}"}}
            for i in range(3)
        ]

        # WHEN
        results = await mgr.dispatch_parallel(calls)

        # THEN
        assert len(results) == 3
        for i, res in enumerate(results):
            assert res["status"] == "success"
            assert res["echo"] == f"hello-{i}"


class TestDispatchParallelReturnExceptionsTrue:
    """Verify that failed calls produce error dicts when return_exceptions=True."""

    @pytest.mark.asyncio
    async def test_all_fail_returns_error_dicts(self, tmp_path):
        """GIVEN five tools that all raise RuntimeError
        WHEN dispatch_parallel is called with return_exceptions=True (default)
        THEN every result is an error dict containing the exception message.
        """
        # GIVEN
        mgr = _make_manager(tmp_path)

        def boom():
            raise RuntimeError("kaboom")

        for i in range(5):
            _register_sync_tool(mgr, f"fcat{i}", f"ftool{i}", boom)

        calls = [
            {"category": f"fcat{i}", "tool": f"ftool{i}"}
            for i in range(5)
        ]

        # WHEN
        results = await mgr.dispatch_parallel(calls, return_exceptions=True)

        # THEN
        assert len(results) == 5
        for res in results:
            assert res["status"] == "error"
            assert "error" in res

    @pytest.mark.asyncio
    async def test_mixed_success_failure(self, tmp_path):
        """GIVEN some tools that succeed and others that fail
        WHEN dispatch_parallel is called with return_exceptions=True
        THEN successes return data and failures return error dicts.
        """
        # GIVEN
        mgr = _make_manager(tmp_path)

        def ok_tool() -> Dict[str, Any]:
            return {"status": "success"}

        def bad_tool():
            raise ValueError("intentional failure")

        _register_sync_tool(mgr, "ok0", "ok_tool", ok_tool)
        _register_sync_tool(mgr, "bad1", "bad_tool", bad_tool)
        _register_sync_tool(mgr, "ok2", "ok_tool", ok_tool)

        calls = [
            {"category": "ok0", "tool": "ok_tool"},
            {"category": "bad1", "tool": "bad_tool"},
            {"category": "ok2", "tool": "ok_tool"},
        ]

        # WHEN
        results = await mgr.dispatch_parallel(calls)

        # THEN
        assert results[0]["status"] == "success"
        assert results[1]["status"] == "error"
        assert results[2]["status"] == "success"

    @pytest.mark.asyncio
    async def test_error_dict_contains_category_and_tool(self, tmp_path):
        """GIVEN a failing tool
        WHEN dispatch_parallel captures the error
        THEN the error dict contains category, tool, and error keys.
        """
        # GIVEN
        mgr = _make_manager(tmp_path)

        def failing():
            raise Exception("oops")

        _register_sync_tool(mgr, "mycat", "mytool", failing)

        calls = [{"category": "mycat", "tool": "mytool", "params": {}}]

        # WHEN
        results = await mgr.dispatch_parallel(calls)

        # THEN
        err = results[0]
        assert err["status"] == "error"
        assert err["category"] == "mycat"
        assert err["tool"] == "mytool"
        assert "error" in err


class TestDispatchParallelReturnExceptionsFalse:
    """Verify exception propagation when return_exceptions=False.

    Note: ``dispatch()`` itself catches generic tool exceptions and returns error
    dicts.  To exercise the ``return_exceptions=False`` raise path in
    ``_run_one`` we must make ``dispatch()`` actually raise — which it does when
    it encounters ``ToolNotFoundError`` or ``ToolExecutionError``.  The simplest
    way is to patch ``dispatch`` directly.
    """

    @pytest.mark.asyncio
    async def test_exception_propagates_when_flag_false(self, tmp_path):
        """GIVEN dispatch() itself raises an exception (e.g. ToolNotFoundError)
        WHEN dispatch_parallel is called with return_exceptions=False
        THEN the exception escapes to the caller.
        """
        # GIVEN
        mgr = _make_manager(tmp_path)

        # Patch the instance's dispatch so it always raises
        from unittest.mock import AsyncMock
        mgr.dispatch = AsyncMock(side_effect=RuntimeError("must propagate"))

        calls = [{"category": "pcat", "tool": "pfail"}]

        # WHEN / THEN
        with pytest.raises(Exception):
            await mgr.dispatch_parallel(calls, return_exceptions=False)


class TestDispatchParallelCategoryNotFound:
    """Verify graceful error when a category is missing from the manager."""

    @pytest.mark.asyncio
    async def test_missing_category_captured_as_error(self, tmp_path):
        """GIVEN a call referencing a non-existent category
        WHEN dispatch_parallel is called (return_exceptions=True)
        THEN the slot contains an error dict (not None, not an exception).
        """
        # GIVEN
        mgr = _make_manager(tmp_path)
        calls = [{"category": "ghost_cat", "tool": "ghost_tool"}]

        # WHEN
        results = await mgr.dispatch_parallel(calls)

        # THEN
        assert len(results) == 1
        assert results[0]["status"] == "error"

    @pytest.mark.asyncio
    async def test_single_call_without_params_key(self, tmp_path):
        """GIVEN a call dict that omits the 'params' key entirely
        WHEN dispatch_parallel processes it
        THEN params defaults to {} and no KeyError occurs.
        """
        # GIVEN
        mgr = _make_manager(tmp_path)

        def noop() -> Dict[str, Any]:
            return {"status": "success"}

        _register_sync_tool(mgr, "ncat", "noop", noop)
        calls = [{"category": "ncat", "tool": "noop"}]  # no "params" key

        # WHEN
        results = await mgr.dispatch_parallel(calls)

        # THEN
        assert results[0]["status"] == "success"
