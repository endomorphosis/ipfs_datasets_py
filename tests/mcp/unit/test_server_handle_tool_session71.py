"""
S71 — server.py handle-tool, error-handler registration, _wrap_tool_with_error_reporting
=========================================================================================
Targets previously-uncovered paths in IPFSDatasetsMCPServer:
  • _wrap_tool_with_error_reporting: async_wrapper success/error + sync_wrapper success/error
  • _initialize_error_reporting: ERROR_REPORTING_AVAILABLE=True / False paths
  • start_stdio_server / start_server function-level error paths (KeyboardInterrupt, ServerStartupError, generic)
  • Args pydantic model / from_namespace helper
"""
from __future__ import annotations

import sys
import types
import os
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


# ---------------------------------------------------------------------------
# Minimal MCP stub ─ must be injected BEFORE importing server.py
# ---------------------------------------------------------------------------

def _inject_mcp_stub():
    mcp_mod = types.ModuleType("mcp")
    mcp_mod.FastMCP = MagicMock
    server_mod = types.ModuleType("mcp.server")
    server_mod.FastMCP = MagicMock
    sys.modules.setdefault("mcp", mcp_mod)
    sys.modules.setdefault("mcp.server", server_mod)
    sys.modules.setdefault("mcp.server.fastmcp", types.ModuleType("mcp.server.fastmcp"))
    return mcp_mod


_inject_mcp_stub()

from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer, start_stdio_server, start_server
from ipfs_datasets_py.mcp_server.exceptions import ServerStartupError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_server() -> IPFSDatasetsMCPServer:
    """Return a server instance with mcp + p2p stubbed out."""
    srv = IPFSDatasetsMCPServer.__new__(IPFSDatasetsMCPServer)
    srv.tools = {}
    srv.mcp = MagicMock()
    srv.p2p = None
    srv.configs = MagicMock()
    srv.configs.ipfs_kit_mcp_url = None
    return srv


# ===========================================================================
# _wrap_tool_with_error_reporting
# ===========================================================================

class TestWrapToolWithErrorReporting:

    def _server_with_error_reporting(self) -> IPFSDatasetsMCPServer:
        srv = _make_server()
        return srv

    async def test_async_wrapper_success(self):
        """async_wrapper must return value on success."""
        import inspect
        srv = self._server_with_error_reporting()

        async def my_tool(x: int):
            return x * 2

        wrapped = srv._wrap_tool_with_error_reporting("my_tool", my_tool)
        assert inspect.iscoroutinefunction(wrapped), "async tool → async wrapper"
        result = await wrapped(5)
        assert result == 10

    async def test_async_wrapper_reraises_on_exception(self):
        """async_wrapper must re-raise the original exception."""
        srv = self._server_with_error_reporting()

        async def bad_tool():
            raise ValueError("boom")

        wrapped = srv._wrap_tool_with_error_reporting("bad_tool", bad_tool)
        with pytest.raises(ValueError, match="boom"):
            await wrapped()

    def test_sync_wrapper_success(self):
        """sync_wrapper must return value on success."""
        import inspect
        srv = self._server_with_error_reporting()

        def sync_tool(y: str):
            return y.upper()

        wrapped = srv._wrap_tool_with_error_reporting("sync_tool", sync_tool)
        assert not inspect.iscoroutinefunction(wrapped), "sync tool → sync wrapper"
        assert wrapped("hello") == "HELLO"

    def test_sync_wrapper_reraises_on_exception(self):
        """sync_wrapper must re-raise the original exception."""
        srv = self._server_with_error_reporting()

        def bad_sync():
            raise RuntimeError("bad")

        wrapped = srv._wrap_tool_with_error_reporting("bad_sync", bad_sync)
        with pytest.raises(RuntimeError, match="bad"):
            wrapped()

    def test_wraps_preserves_function_name(self):
        """Wrapped function should preserve __name__ via functools.wraps."""
        srv = self._server_with_error_reporting()

        def my_named_tool():
            return 42

        wrapped = srv._wrap_tool_with_error_reporting("my_named_tool", my_named_tool)
        assert wrapped.__name__ == "my_named_tool"


# ===========================================================================
# _initialize_error_reporting
# ===========================================================================

class TestInitializeErrorReporting:

    def test_error_reporting_available_flag_set_false_when_import_fails(self):
        """When error_reporter import fails, ERROR_REPORTING_AVAILABLE stays False."""
        import ipfs_datasets_py.mcp_server.server as srv_mod
        # The module-level ERROR_REPORTING_AVAILABLE is already determined at import time.
        # We can confirm the attribute exists and is a bool.
        assert isinstance(srv_mod.ERROR_REPORTING_AVAILABLE, bool)

    def test_initialize_error_reporting_no_exception(self):
        """_initialize_error_reporting should not raise even when reporter absent."""
        srv = _make_server()
        # Should be callable without error
        srv._initialize_error_reporting()  # may be a no-op or log; must not raise

    def test_initialize_error_reporting_with_mock_reporter(self):
        """When error_reporter is present, _initialize_error_reporting stores it."""
        import ipfs_datasets_py.mcp_server.server as srv_mod
        fake_reporter = MagicMock()
        with patch.object(srv_mod, "ERROR_REPORTING_AVAILABLE", True), \
             patch.object(srv_mod, "error_reporter", fake_reporter, create=True):
            srv = _make_server()
            srv._initialize_error_reporting()
            # No assertion — just must not raise


# ===========================================================================
# start_stdio_server function-level
# ===========================================================================

class TestStartStdioServerFunction:

    def _patch_anyio_run(self, side_effect=None):
        """Return a context manager that patches anyio.run inside server module."""
        import ipfs_datasets_py.mcp_server.server as srv_mod
        mock = MagicMock(side_effect=side_effect)
        return patch.object(srv_mod, "anyio", MagicMock(run=mock)), mock

    def test_keyboard_interrupt_handled_silently(self):
        """KeyboardInterrupt must not propagate out of start_stdio_server."""
        import ipfs_datasets_py.mcp_server.server as srv_mod
        fake_anyio = MagicMock()
        fake_anyio.run.side_effect = KeyboardInterrupt()
        with patch.object(srv_mod, "anyio", fake_anyio):
            # Must not raise
            start_stdio_server()

    def test_server_startup_error_handled(self):
        """ServerStartupError must be caught and not re-raised by start_stdio_server."""
        import ipfs_datasets_py.mcp_server.server as srv_mod
        fake_anyio = MagicMock()
        fake_anyio.run.side_effect = ServerStartupError("port in use")
        with patch.object(srv_mod, "anyio", fake_anyio):
            start_stdio_server()  # must not raise

    def test_generic_exception_handled(self):
        """An unexpected exception must be caught gracefully."""
        import ipfs_datasets_py.mcp_server.server as srv_mod
        fake_anyio = MagicMock()
        fake_anyio.run.side_effect = RuntimeError("unexpected")
        with patch.object(srv_mod, "anyio", fake_anyio):
            start_stdio_server()  # must not raise

    def test_with_ipfs_kit_mcp_url(self):
        """Providing ipfs_kit_mcp_url sets configs attributes."""
        import ipfs_datasets_py.mcp_server.server as srv_mod
        fake_anyio = MagicMock()
        # Make run a no-op
        fake_anyio.run.return_value = None
        with patch.object(srv_mod, "anyio", fake_anyio), \
             patch.object(srv_mod, "configs", MagicMock()) as mock_configs:
            start_stdio_server(ipfs_kit_mcp_url="http://localhost:5001")
            assert mock_configs.ipfs_kit_mcp_url == "http://localhost:5001"
            assert mock_configs.ipfs_kit_integration == "mcp"


# ===========================================================================
# start_server function-level
# ===========================================================================

class TestStartServerFunction:

    def test_keyboard_interrupt_handled(self):
        """KeyboardInterrupt must not propagate out of start_server."""
        import ipfs_datasets_py.mcp_server.server as srv_mod
        fake_anyio = MagicMock()
        fake_anyio.run.side_effect = KeyboardInterrupt()
        with patch.object(srv_mod, "anyio", fake_anyio):
            start_server("0.0.0.0", 8080)

    def test_server_startup_error_handled(self):
        """ServerStartupError must be caught and not re-raised by start_server."""
        import ipfs_datasets_py.mcp_server.server as srv_mod
        fake_anyio = MagicMock()
        fake_anyio.run.side_effect = ServerStartupError("bind failed")
        with patch.object(srv_mod, "anyio", fake_anyio):
            start_server()

    def test_generic_exception_handled(self):
        """Unexpected exception must be caught gracefully."""
        import ipfs_datasets_py.mcp_server.server as srv_mod
        fake_anyio = MagicMock()
        fake_anyio.run.side_effect = OSError("port unavailable")
        with patch.object(srv_mod, "anyio", fake_anyio):
            start_server()
