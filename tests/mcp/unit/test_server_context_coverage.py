"""
Session 29 — Server context coverage improvements.

Targets server_context.py lines currently uncovered:
  156-166  __enter__ error paths (ImportError, generic Exception)
  179-180  __exit__ cleanup error path  
  187-191  _initialize_metadata_registry
  216-218  _initialize_p2p_services ImportError
  226-228  _initialize_workflow_scheduler Exception
  244-247, 254-257, 261-266  _cleanup branches
  373-375  p2p_services property (not entered)
  380-382  workflow_scheduler property (not entered)
  391-395  workflow_scheduler setter (not entered + lock path)
  481-489  list_tools() with real tool_manager
  580      get_tool() category dot-notation hit
  679-688  execute_tool() error paths
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from ipfs_datasets_py.mcp_server.server_context import (
    ServerContext,
    ServerConfig,
    create_server_context,
    set_current_context,
    get_current_context,
)
from ipfs_datasets_py.mcp_server.exceptions import (
    ServerStartupError,
    ToolNotFoundError,
    ToolExecutionError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context() -> ServerContext:
    """Create a fresh ServerContext (without entering)."""
    return ServerContext()


# ---------------------------------------------------------------------------
# Property guards when not entered
# ---------------------------------------------------------------------------

class TestPropertiesWhenNotEntered:
    """Lines 373-395: property guards raise RuntimeError when context not entered."""

    def test_p2p_services_raises_when_not_entered(self):
        ctx = _make_context()
        with pytest.raises(RuntimeError, match="not entered"):
            _ = ctx.p2p_services

    def test_workflow_scheduler_getter_raises_when_not_entered(self):
        ctx = _make_context()
        with pytest.raises(RuntimeError, match="not entered"):
            _ = ctx.workflow_scheduler

    def test_workflow_scheduler_setter_raises_when_not_entered(self):
        ctx = _make_context()
        with pytest.raises(RuntimeError, match="not entered"):
            ctx.workflow_scheduler = MagicMock()

    def test_workflow_scheduler_setter_after_enter(self):
        """Lines 391-395: setter with lock path."""
        with ServerContext() as ctx:
            mock_sched = MagicMock()
            ctx.workflow_scheduler = mock_sched
            assert ctx.workflow_scheduler is mock_sched


# ---------------------------------------------------------------------------
# __enter__ error paths
# ---------------------------------------------------------------------------

class TestEnterErrorPaths:
    """Lines 156-166: ImportError and generic Exception in __enter__."""

    def test_import_error_during_init_raises_server_startup_error(self):
        """Lines 158-162: ImportError → ServerStartupError."""
        ctx = _make_context()
        with patch.object(ctx, "_initialize_metadata_registry",
                          side_effect=ImportError("module not found")):
            with pytest.raises(ServerStartupError, match="Module import failed"):
                ctx.__enter__()

    def test_generic_exception_during_init_raises_server_startup_error(self):
        """Lines 163-166: generic Exception → ServerStartupError."""
        ctx = _make_context()
        with patch.object(ctx, "_initialize_tool_manager",
                          side_effect=RuntimeError("unexpected")):
            with pytest.raises(ServerStartupError, match="Server initialization failed"):
                ctx.__enter__()

    def test_cleanup_called_on_enter_failure(self):
        """_cleanup() is called when __enter__ raises."""
        ctx = _make_context()
        cleanup_called = []
        orig_cleanup = ctx._cleanup

        def tracking_cleanup():
            cleanup_called.append(True)
            orig_cleanup()

        ctx._cleanup = tracking_cleanup

        with patch.object(ctx, "_initialize_tool_manager",
                          side_effect=RuntimeError("boom")):
            with pytest.raises(ServerStartupError):
                ctx.__enter__()

        assert cleanup_called, "_cleanup() was not called on enter failure"


# ---------------------------------------------------------------------------
# __exit__ error paths
# ---------------------------------------------------------------------------

class TestExitErrorPaths:
    """Lines 179-191: __exit__ when cleanup raises."""

    def test_cleanup_error_in_exit_wraps_in_server_shutdown_error(self):
        """Line 189-191: Exception during _cleanup → ServerShutdownError."""
        from ipfs_datasets_py.mcp_server.exceptions import ServerShutdownError

        ctx = _make_context()
        ctx._entered = True  # Simulate entered state

        with patch.object(ctx, "_cleanup", side_effect=RuntimeError("cleanup boom")):
            with pytest.raises(ServerShutdownError, match="Cleanup failed"):
                ctx.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# _cleanup branches
# ---------------------------------------------------------------------------

class TestCleanupBranches:
    """Lines 244-266: _cleanup with metadata registry, tool manager, p2p services."""

    def test_cleanup_calls_metadata_registry_clear(self):
        """Lines 244-247: metadata registry .clear() called."""
        with ServerContext() as ctx:
            mock_registry = MagicMock()
            ctx._metadata_registry = mock_registry
            ctx._cleanup()
            mock_registry.clear.assert_called_once()

    def test_cleanup_handles_metadata_registry_exception(self):
        """Exception from registry.clear() is logged, not raised."""
        with ServerContext() as ctx:
            mock_registry = MagicMock()
            mock_registry.clear.side_effect = RuntimeError("clear failed")
            ctx._metadata_registry = mock_registry
            # Should not raise
            ctx._cleanup()

    def test_cleanup_with_p2p_services_dict(self):
        """Lines 261-266: p2p_services block executed without raise."""
        with ServerContext() as ctx:
            ctx._p2p_services = {"peer": "mock"}
            ctx._cleanup()  # Should not raise


# ---------------------------------------------------------------------------
# list_tools()
# ---------------------------------------------------------------------------

class TestListTools:
    """Lines 481-489: list_tools() delegates to tool_manager."""

    def test_list_tools_no_tool_manager(self):
        """Returns [] when _tool_manager is None."""
        with ServerContext() as ctx:
            ctx._tool_manager = None
            assert ctx.list_tools() == []

    def test_list_tools_with_mocked_tool_manager(self):
        """Lines 483-488: iterates categories and tools."""
        with ServerContext() as ctx:
            mock_mgr = MagicMock()
            mock_mgr.list_categories.return_value = [
                {"name": "cat_a"},
                {"name": "cat_b"},
            ]
            mock_mgr.list_tools.side_effect = lambda cat: [
                {"name": f"{cat}_tool1"},
                {"name": f"{cat}_tool2"},
            ]
            ctx._tool_manager = mock_mgr
            tools = ctx.list_tools()
            assert "cat_a_tool1" in tools
            assert "cat_b_tool2" in tools
            assert len(tools) == 4


# ---------------------------------------------------------------------------
# get_tool() — dot-notation hit
# ---------------------------------------------------------------------------

class TestGetToolDotNotation:
    """Line 580: get_tool("category.tool") hits the dot-notation branch."""

    def test_get_tool_qualified_name_found(self):
        """Lines 578-580: category found, get_tool() returns callable."""
        with ServerContext() as ctx:
            mock_fn = MagicMock(return_value="ok")
            mock_cat = MagicMock()
            mock_cat.get_tool.return_value = mock_fn

            mock_mgr = MagicMock()
            mock_mgr.categories = {"my_cat": mock_cat}
            ctx._tool_manager = mock_mgr

            result = ctx.get_tool("my_cat.my_tool")
            assert result is mock_fn
            mock_cat.get_tool.assert_called_once_with("my_tool")

    def test_get_tool_qualified_name_category_not_found(self):
        """Returns None when category does not exist."""
        with ServerContext() as ctx:
            mock_mgr = MagicMock()
            mock_mgr.categories = {}  # no categories
            ctx._tool_manager = mock_mgr
            result = ctx.get_tool("missing_cat.some_tool")
            assert result is None


# ---------------------------------------------------------------------------
# execute_tool() error paths
# ---------------------------------------------------------------------------

class TestExecuteToolErrorPaths:
    """Lines 679-688: execute_tool() wraps various exceptions."""

    def test_execute_tool_type_error_wraps_in_tool_execution_error(self):
        """Lines 683-685: TypeError → ToolExecutionError."""
        with ServerContext() as ctx:
            mock_fn = MagicMock(side_effect=TypeError("bad args"))
            mock_cat = MagicMock()
            mock_cat.get_tool.return_value = mock_fn
            mock_mgr = MagicMock()
            mock_mgr.categories = {"cat": mock_cat}
            ctx._tool_manager = mock_mgr

            with pytest.raises(ToolExecutionError):
                ctx.execute_tool("cat.tool", x=1)

    def test_execute_tool_generic_exception_wraps_in_tool_execution_error(self):
        """Lines 686-688: generic Exception → ToolExecutionError."""
        with ServerContext() as ctx:
            mock_fn = MagicMock(side_effect=IOError("disk full"))
            mock_cat = MagicMock()
            mock_cat.get_tool.return_value = mock_fn
            mock_mgr = MagicMock()
            mock_mgr.categories = {"cat": mock_cat}
            ctx._tool_manager = mock_mgr

            with pytest.raises(ToolExecutionError):
                ctx.execute_tool("cat.tool")

    def test_execute_tool_not_found_raises_tool_not_found(self):
        """Line 679: missing tool → ToolNotFoundError."""
        with ServerContext() as ctx:
            mock_mgr = MagicMock()
            mock_mgr.categories = {}
            ctx._tool_manager = mock_mgr

            with pytest.raises(ToolNotFoundError):
                ctx.execute_tool("cat.missing")

    def test_execute_tool_success_path(self):
        """execute_tool() returns tool result when callable succeeds."""
        with ServerContext() as ctx:
            mock_fn = MagicMock(return_value={"ok": True})
            mock_cat = MagicMock()
            mock_cat.get_tool.return_value = mock_fn
            mock_mgr = MagicMock()
            mock_mgr.categories = {"cat": mock_cat}
            ctx._tool_manager = mock_mgr

            result = ctx.execute_tool("cat.tool", x=42)
            assert result == {"ok": True}


# ---------------------------------------------------------------------------
# create_server_context() convenience function
# ---------------------------------------------------------------------------

class TestCreateServerContext:
    """Lines 692-720: create_server_context() context manager."""

    def test_create_server_context_yields_server_context(self):
        with create_server_context() as ctx:
            assert isinstance(ctx, ServerContext)
            assert ctx._entered is True

    def test_create_server_context_cleanup_on_exit(self):
        cleanup_called = []
        with create_server_context() as ctx:
            ctx.register_cleanup_handler(lambda: cleanup_called.append(True))
        assert cleanup_called


# ---------------------------------------------------------------------------
# set/get current context (thread-local)
# ---------------------------------------------------------------------------

class TestThreadLocalContext:
    """Lines 719-865: set_current_context / get_current_context."""

    def test_set_and_get_current_context(self):
        with ServerContext() as ctx:
            set_current_context(ctx)
            assert get_current_context() is ctx
            set_current_context(None)

    def test_thread_isolation(self):
        """Different threads get different contexts (created sequentially to avoid races)."""
        results = {}

        def worker(tid: int, ctx_obj):
            set_current_context(ctx_obj)
            results[tid] = get_current_context()

        # Create contexts sequentially (avoids shared-singleton race conditions)
        with ServerContext() as ctx_a:
            t1 = threading.Thread(target=worker, args=(1, ctx_a))
            t1.start()
            t1.join()

        with ServerContext() as ctx_b:
            t2 = threading.Thread(target=worker, args=(2, ctx_b))
            t2.start()
            t2.join()

        assert results[1] is ctx_a
        assert results[2] is ctx_b
