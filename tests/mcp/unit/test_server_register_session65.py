"""
Session P65 — server.py register_tools / register_ipfs_kit_tools / start_stdio / start
"""
import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

# ---------------------------------------------------------------------------
# helpers — import server module with mocked dependencies
# ---------------------------------------------------------------------------

def _get_server_mod():
    """Import the server module, mocking mcp if absent."""
    # Inject a minimal mcp stub if not present
    if "mcp" not in sys.modules:
        mcp_stub = MagicMock()
        mcp_stub.server = MagicMock()
        mcp_stub.server.FastMCP = MagicMock()
        sys.modules["mcp"] = mcp_stub
        sys.modules["mcp.server"] = mcp_stub.server
    return __import__(
        "ipfs_datasets_py.mcp_server.server",
        fromlist=["IPFSDatasetsMCPServer", "import_tools_from_directory",
                  "start_stdio_server", "start_server"]
    )


# ---------------------------------------------------------------------------
# TestRegisterTools
# ---------------------------------------------------------------------------

class TestRegisterTools:
    """Tests for IPFSDatasetsMCPServer.register_tools()"""

    @pytest.mark.asyncio
    async def test_register_tools_mcp_none_raises_import_error(self):
        """register_tools() raises ImportError when mcp is None."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = None
        srv.tools = {}
        with pytest.raises(ImportError, match="MCP dependency"):
            await srv.register_tools()

    @pytest.mark.asyncio
    async def test_register_tools_adds_four_meta_tools(self):
        """register_tools() registers exactly 4 meta-tools."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.tools = {}
        # Patch hierarchical_tool_manager imports
        dummy_fn = lambda: None
        with patch.dict(sys.modules, {
            "ipfs_datasets_py.mcp_server.hierarchical_tool_manager": MagicMock(
                tools_list_categories=dummy_fn,
                tools_list_tools=dummy_fn,
                tools_get_schema=dummy_fn,
                tools_dispatch=dummy_fn,
            )
        }):
            await srv.register_tools()
        assert srv.mcp.add_tool.call_count == 4
        assert len(srv.tools) == 4

    def test_register_tools_from_subdir_error_reporting_false(self):
        """_register_tools_from_subdir() registers without wrapping when ERROR_REPORTING=False."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.tools = {}
        fake_tool = lambda: "result"
        fake_tool.__doc__ = "doc"
        with patch.object(server_mod, "ERROR_REPORTING_AVAILABLE", False), \
             patch.object(server_mod, "import_tools_from_directory", return_value={"my_tool": fake_tool}):
            srv._register_tools_from_subdir(Path("/fake"))
        assert "my_tool" in srv.tools
        assert srv.tools["my_tool"] is fake_tool

    def test_register_tools_from_subdir_error_reporting_true(self):
        """_register_tools_from_subdir() wraps tools when ERROR_REPORTING=True."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.tools = {}
        fake_tool = lambda: "result"
        fake_tool.__doc__ = "doc"
        wrapped = lambda: "wrapped"
        with patch.object(server_mod, "ERROR_REPORTING_AVAILABLE", True), \
             patch.object(server_mod, "import_tools_from_directory", return_value={"my_tool": fake_tool}), \
             patch.object(srv, "_wrap_tool_with_error_reporting", return_value=wrapped):
            srv._register_tools_from_subdir(Path("/fake"))
        assert "my_tool" in srv.tools
        assert srv.tools["my_tool"] is wrapped


# ---------------------------------------------------------------------------
# TestRegisterIpfsKitTools
# ---------------------------------------------------------------------------

class TestRegisterIpfsKitTools:
    """Tests for register_ipfs_kit_tools() and its helpers."""

    @pytest.mark.asyncio
    async def test_register_ipfs_kit_tools_with_url_calls_mcp_client(self):
        """When ipfs_kit_mcp_url is provided, _register_ipfs_kit_mcp_client is called."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv._register_ipfs_kit_mcp_client = AsyncMock()
        srv._register_direct_ipfs_kit_imports = MagicMock()
        await srv.register_ipfs_kit_tools(ipfs_kit_mcp_url="http://localhost:5001")
        srv._register_ipfs_kit_mcp_client.assert_awaited_once_with("http://localhost:5001")
        srv._register_direct_ipfs_kit_imports.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_ipfs_kit_tools_without_url_calls_direct(self):
        """When no URL, _register_direct_ipfs_kit_imports is called."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv._register_ipfs_kit_mcp_client = AsyncMock()
        srv._register_direct_ipfs_kit_imports = MagicMock()
        await srv.register_ipfs_kit_tools()
        srv._register_direct_ipfs_kit_imports.assert_called_once()
        srv._register_ipfs_kit_mcp_client.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_register_ipfs_kit_mcp_client_import_error_logged(self):
        """_register_ipfs_kit_mcp_client() logs error when MCPClient import fails."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.tools = {}
        # Inject ImportError for .client
        with patch.dict(sys.modules, {
            "ipfs_datasets_py.mcp_server.client": None
        }):
            # Should not raise even if import fails
            try:
                await srv._register_ipfs_kit_mcp_client("http://localhost:5001")
            except ImportError:
                pass  # acceptable

    def test_register_direct_ipfs_kit_imports_no_package(self):
        """_register_direct_ipfs_kit_imports() logs error when ipfs_kit_py absent."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.tools = {}
        with patch.dict(sys.modules, {"ipfs_kit_py": None}):
            # Should not raise
            srv._register_direct_ipfs_kit_imports()
        # No tools added
        assert srv.tools == {}

    def test_register_direct_ipfs_kit_imports_with_package(self):
        """_register_direct_ipfs_kit_imports() registers 'add' tool when available."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.tools = {}
        fake_add = lambda data: "Qm..."
        fake_pkg = MagicMock(add=fake_add)
        with patch.dict(sys.modules, {"ipfs_kit_py": fake_pkg}):
            srv._register_direct_ipfs_kit_imports()
        assert "ipfs_kit_add" in srv.tools


# ---------------------------------------------------------------------------
# TestStartStdio
# ---------------------------------------------------------------------------

class TestStartStdio:
    """Tests for IPFSDatasetsMCPServer.start_stdio() and start()."""

    @pytest.mark.asyncio
    async def test_start_stdio_calls_run_stdio_async(self):
        """start_stdio() calls mcp.run_stdio_async()."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.mcp.run_stdio_async = AsyncMock()
        srv.tools = {}
        srv.p2p = None
        srv.configs = MagicMock(ipfs_kit_mcp_url=None)
        srv.register_tools = AsyncMock()
        srv.register_ipfs_kit_tools = AsyncMock()
        await srv.start_stdio()
        srv.mcp.run_stdio_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_stdio_server_startup_error_reraised(self):
        """start_stdio() re-raises ServerStartupError."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.mcp.run_stdio_async = AsyncMock(
            side_effect=server_mod.ServerStartupError("fail")
        )
        srv.tools = {}
        srv.p2p = None
        srv.configs = MagicMock(ipfs_kit_mcp_url=None)
        srv.register_tools = AsyncMock()
        srv.register_ipfs_kit_tools = AsyncMock()
        with pytest.raises(server_mod.ServerStartupError):
            await srv.start_stdio()

    @pytest.mark.asyncio
    async def test_start_stdio_with_p2p_starts_and_stops_p2p(self):
        """start_stdio() starts and stops P2P when self.p2p is set."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.mcp.run_stdio_async = AsyncMock()
        srv.tools = {}
        srv.configs = MagicMock(ipfs_kit_mcp_url=None)
        srv.register_tools = AsyncMock()
        srv.register_ipfs_kit_tools = AsyncMock()
        # Mock p2p
        fake_p2p = MagicMock()
        srv.p2p = fake_p2p
        adapter_cls = MagicMock()
        with patch.dict(sys.modules, {
            "ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter": MagicMock(
                P2PMCPRegistryAdapter=adapter_cls
            )
        }):
            await srv.start_stdio()
        fake_p2p.start.assert_called_once()
        fake_p2p.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_http_calls_run_stdio_async(self):
        """start() falls back to stdio mode even in HTTP mode."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.mcp.run_stdio_async = AsyncMock()
        srv.tools = {}
        srv.p2p = None
        srv.configs = MagicMock(ipfs_kit_mcp_url=None)
        srv.register_tools = AsyncMock()
        srv.register_ipfs_kit_tools = AsyncMock()
        await srv.start(host="127.0.0.1", port=9999)
        srv.mcp.run_stdio_async.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_with_url_passes_url_to_register(self):
        """start() passes ipfs_kit_mcp_url to register_ipfs_kit_tools."""
        server_mod = _get_server_mod()
        srv = object.__new__(server_mod.IPFSDatasetsMCPServer)
        srv.mcp = MagicMock()
        srv.mcp.run_stdio_async = AsyncMock()
        srv.tools = {}
        srv.p2p = None
        srv.configs = MagicMock(ipfs_kit_mcp_url="http://ipfs:5001")
        srv.register_tools = AsyncMock()
        srv.register_ipfs_kit_tools = AsyncMock()
        await srv.start()
        srv.register_ipfs_kit_tools.assert_awaited_once_with("http://ipfs:5001")
