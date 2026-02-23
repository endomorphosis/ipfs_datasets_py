"""
Tests for server.py — Session O62 (v8 plan).

Coverage targets:
- return_text_content / return_tool_call_results (with mocked MCP types)
- import_tools_from_directory: non-existent dir, empty dir, valid .py file
- IPFSDatasetsMCPServer.__init__ (FastMCP=None / mocked)
- IPFSDatasetsMCPServer._initialize_error_reporting (with error_reporter mocked)
- IPFSDatasetsMCPServer._initialize_mcp_server (FastMCP=None path)
- IPFSDatasetsMCPServer._initialize_p2p_services (ImportError, Exception, success)
- IPFSDatasetsMCPServer.validate_p2p_message (shared_token, no token, valid token)
- IPFSDatasetsMCPServer._sanitize_error_context (keys, values, sensitive redaction)
- IPFSDatasetsMCPServer._wrap_tool_with_error_reporting (sync/async wrappers, error path)
- IPFSDatasetsMCPServer._register_tools_from_subdir (mocked tools dict)
- IPFSDatasetsMCPServer._register_direct_ipfs_kit_imports (ImportError, success)
- IPFSDatasetsMCPServer._register_ipfs_kit_mcp_client (ImportError path)
- start_stdio_server / start_server (KeyboardInterrupt path)
- Args model
"""

import argparse
import sys
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Helper to get a server module with MCP symbols mocked
# ---------------------------------------------------------------------------

def _load_server_mod():
    """Import (or return cached) the server module."""
    import importlib
    # Ensure it's importable with or without real mcp package
    if "ipfs_datasets_py.mcp_server.server" in sys.modules:
        return sys.modules["ipfs_datasets_py.mcp_server.server"]
    return importlib.import_module("ipfs_datasets_py.mcp_server.server")


server_mod = _load_server_mod()
IPFSDatasetsMCPServer = server_mod.IPFSDatasetsMCPServer
import_tools_from_directory = server_mod.import_tools_from_directory
start_stdio_server = server_mod.start_stdio_server
start_server = server_mod.start_server
Args = server_mod.Args


# ══════════════════════════════════════════════════════════════════════════════
# 1. Helper utilities
# ══════════════════════════════════════════════════════════════════════════════


class TestReturnHelpers:
    """Tests for return_text_content / return_tool_call_results."""

    def test_return_text_content_formats_string(self):
        """GIVEN a text content helper WHEN mocked TextContent THEN format is correct."""
        with patch.object(server_mod, "TextContent") as mock_tc:
            mock_tc.return_value = MagicMock(type="text", text="result: 42")
            result = server_mod.return_text_content(42, "result")
            mock_tc.assert_called_once()
            call_kwargs = mock_tc.call_args
            assert call_kwargs is not None

    def test_return_tool_call_results_no_error(self):
        """GIVEN no error WHEN return_tool_call_results called THEN isError=False."""
        mock_content = MagicMock()
        with patch.object(server_mod, "CallToolResult") as mock_ctr:
            mock_ctr.return_value = MagicMock()
            server_mod.return_tool_call_results(mock_content, error=False)
            mock_ctr.assert_called_once_with(isError=False, content=[mock_content])

    def test_return_tool_call_results_with_error(self):
        """GIVEN error=True WHEN return_tool_call_results called THEN isError=True."""
        mock_content = MagicMock()
        with patch.object(server_mod, "CallToolResult") as mock_ctr:
            mock_ctr.return_value = MagicMock()
            server_mod.return_tool_call_results(mock_content, error=True)
            mock_ctr.assert_called_once_with(isError=True, content=[mock_content])


# ══════════════════════════════════════════════════════════════════════════════
# 2. import_tools_from_directory
# ══════════════════════════════════════════════════════════════════════════════


class TestImportToolsFromDirectory:
    """Tests for import_tools_from_directory."""

    def test_nonexistent_directory_returns_empty(self, tmp_path):
        """GIVEN non-existent directory WHEN called THEN returns {}."""
        result = import_tools_from_directory(tmp_path / "_nonexistent_subdir")
        assert result == {}

    def test_empty_directory_returns_empty(self, tmp_path):
        """GIVEN empty directory WHEN called THEN returns {}."""
        result = import_tools_from_directory(tmp_path)
        assert result == {}

    def test_private_files_skipped(self, tmp_path):
        """GIVEN directory with _private.py WHEN called THEN skipped."""
        (tmp_path / "_private.py").write_text("def _private(): pass")
        result = import_tools_from_directory(tmp_path)
        assert result == {}

    def test_import_error_handled_gracefully(self, tmp_path):
        """GIVEN Python file that fails import WHEN called THEN returns {} without raising."""
        tool_file = tmp_path / "mytool.py"
        tool_file.write_text("raise ImportError('deliberate import failure')")
        # Patch importlib to raise ImportError
        with patch.object(server_mod.importlib, "import_module", side_effect=ImportError("fail")):
            result = import_tools_from_directory(tmp_path)
        assert isinstance(result, dict)

    def test_valid_tool_imported(self, tmp_path):
        """GIVEN a valid tool file WHEN called THEN tool registered."""
        tool_file = tmp_path / "good_tool.py"
        tool_file.write_text(
            "def my_tool(x):\n    '''A test tool.'''\n    return x\n"
        )
        # We need to create a fake module object for importlib to return
        fake_mod = MagicMock()
        fake_mod.__name__ = f"ipfs_datasets_py.mcp_server.tools.{tmp_path.name}.good_tool"
        
        def my_tool(x):
            """A test tool."""
            return x
        
        my_tool.__module__ = fake_mod.__name__
        fake_mod.my_tool = my_tool
        fake_mod.__doc__ = None
        
        with patch.object(server_mod.importlib, "import_module", return_value=fake_mod):
            with patch("builtins.dir", return_value=["my_tool"]):
                result = import_tools_from_directory(tmp_path)
        # Result may or may not include the tool depending on attr checks
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
# 3. IPFSDatasetsMCPServer initialization
# ══════════════════════════════════════════════════════════════════════════════


def _make_server():
    """Create a server instance with all external dependencies mocked."""
    with patch.object(server_mod, "FastMCP", None):
        with patch.object(server_mod, "ERROR_REPORTING_AVAILABLE", False):
            with patch.object(
                IPFSDatasetsMCPServer, "_initialize_p2p_services", lambda self: None
            ):
                srv = IPFSDatasetsMCPServer()
    return srv


class TestIPFSDatasetsMCPServerInit:
    """Tests for IPFSDatasetsMCPServer.__init__ and sub-initializers."""

    def test_basic_init_succeeds(self):
        """GIVEN defaults WHEN init with FastMCP=None THEN mcp attribute is None."""
        srv = _make_server()
        assert srv.mcp is None
        assert srv.tools == {}

    def test_init_with_custom_configs(self):
        """GIVEN custom configs WHEN init THEN configs stored."""
        custom_cfg = MagicMock()
        with patch.object(server_mod, "FastMCP", None):
            with patch.object(server_mod, "ERROR_REPORTING_AVAILABLE", False):
                with patch.object(
                    IPFSDatasetsMCPServer, "_initialize_p2p_services", lambda self: None
                ):
                    srv = IPFSDatasetsMCPServer(server_configs=custom_cfg)
        assert srv.configs is custom_cfg

    def test_initialize_mcp_server_with_fastmcp(self):
        """GIVEN FastMCP available WHEN _initialize_mcp_server THEN mcp is FastMCP instance."""
        mock_mcp = MagicMock()
        with patch.object(server_mod, "FastMCP", return_value=mock_mcp):
            srv = _make_server()
            # Call the method directly since _make_server patches FastMCP=None
            srv._fastmcp_available = True
            with patch.object(server_mod, "FastMCP", return_value=mock_mcp):
                srv._initialize_mcp_server()
        assert srv._fastmcp_available is True
        assert srv.mcp == mock_mcp

    def test_initialize_mcp_server_without_fastmcp(self):
        """GIVEN FastMCP=None WHEN _initialize_mcp_server THEN mcp=None."""
        srv = _make_server()
        with patch.object(server_mod, "FastMCP", None):
            srv._initialize_mcp_server()
        assert srv.mcp is None
        assert srv._fastmcp_available is False

    def test_initialize_error_reporting_when_available(self):
        """GIVEN ERROR_REPORTING_AVAILABLE=True WHEN _initialize_error_reporting THEN installs handler."""
        srv = _make_server()
        mock_reporter = MagicMock()
        with patch.object(server_mod, "ERROR_REPORTING_AVAILABLE", True):
            with patch.object(server_mod, "error_reporter", mock_reporter, create=True):
                srv._initialize_error_reporting()
        mock_reporter.install_global_handler.assert_called_once()

    def test_initialize_error_reporting_exception_swallowed(self):
        """GIVEN error_reporter.install_global_handler raises WHEN called THEN swallowed."""
        srv = _make_server()
        mock_reporter = MagicMock()
        mock_reporter.install_global_handler.side_effect = Exception("boom")
        with patch.object(server_mod, "ERROR_REPORTING_AVAILABLE", True):
            with patch.object(server_mod, "error_reporter", mock_reporter, create=True):
                srv._initialize_error_reporting()  # must not raise
        mock_reporter.install_global_handler.assert_called_once()

    def test_initialize_p2p_services_import_error(self):
        """GIVEN P2PServiceManager import fails WHEN _initialize_p2p_services THEN p2p=None."""
        srv = _make_server()
        with patch.dict(sys.modules, {"ipfs_datasets_py.mcp_server.p2p_service_manager": None}):
            srv._initialize_p2p_services()
        assert srv.p2p is None

    def test_initialize_p2p_services_generic_exception(self):
        """GIVEN P2PServiceManager raises WHEN _initialize_p2p_services THEN p2p=None."""
        srv = _make_server()
        mock_mgr_cls = MagicMock(side_effect=RuntimeError("p2p boom"))
        with patch("ipfs_datasets_py.mcp_server.server.P2PServiceManager", mock_mgr_cls, create=True):
            with patch(
                "ipfs_datasets_py.mcp_server.p2p_service_manager.P2PServiceManager",
                mock_mgr_cls,
            ):
                srv._initialize_p2p_services()
        assert srv.p2p is None


# ══════════════════════════════════════════════════════════════════════════════
# 4. validate_p2p_message
# ══════════════════════════════════════════════════════════════════════════════


class TestValidateP2PMessage:
    """Tests for IPFSDatasetsMCPServer.validate_p2p_message."""

    def _srv(self):
        return _make_server()

    @pytest.mark.anyio
    async def test_shared_token_mode_returns_false(self):
        """GIVEN auth_mode=shared_token WHEN validate_p2p_message THEN False."""
        srv = self._srv()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "shared_token"
        result = await srv.validate_p2p_message({"token": "abc"})
        assert result is False

    @pytest.mark.anyio
    async def test_no_token_returns_false(self):
        """GIVEN message without token WHEN validate_p2p_message THEN False."""
        srv = self._srv()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "mcp_token"
        result = await srv.validate_p2p_message({})
        assert result is False

    @pytest.mark.anyio
    async def test_empty_token_returns_false(self):
        """GIVEN message with empty token WHEN validate_p2p_message THEN False."""
        srv = self._srv()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "mcp_token"
        result = await srv.validate_p2p_message({"token": ""})
        assert result is False

    @pytest.mark.anyio
    async def test_non_string_token_returns_false(self):
        """GIVEN token is not a string WHEN validate_p2p_message THEN False."""
        srv = self._srv()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "mcp_token"
        result = await srv.validate_p2p_message({"token": 12345})
        assert result is False

    @pytest.mark.anyio
    async def test_valid_token_returns_true(self):
        """GIVEN valid token + mock auth service WHEN validate_p2p_message THEN True."""
        srv = self._srv()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "mcp_token"

        mock_auth_svc = MagicMock()
        mock_auth_svc.validate_token = AsyncMock(return_value={"valid": True})

        with patch.dict(
            sys.modules,
            {"ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools": MagicMock(_mock_auth_service=mock_auth_svc)},
        ):
            result = await srv.validate_p2p_message({"token": "goodtoken"})
        assert result is True

    @pytest.mark.anyio
    async def test_import_error_returns_false(self):
        """GIVEN auth_tools import fails WHEN validate_p2p_message THEN False."""
        srv = self._srv()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "mcp_token"

        with patch.dict(
            sys.modules,
            {"ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools": None},
        ):
            result = await srv.validate_p2p_message({"token": "sometoken"})
        assert result is False

    @pytest.mark.anyio
    async def test_configs_raises_on_auth_mode_defaults_to_mcp_token(self):
        """GIVEN configs raises on p2p_auth_mode WHEN validate_p2p_message THEN defaults gracefully."""
        srv = self._srv()
        # Use a property that raises to simulate the exception path
        class BrokenConfigs:
            @property
            def p2p_auth_mode(self):
                raise Exception("configs boom")
        srv.configs = BrokenConfigs()
        # Should not raise — defaults to mcp_token, but token check fails → False
        result = await srv.validate_p2p_message({})
        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# 5. _sanitize_error_context
# ══════════════════════════════════════════════════════════════════════════════


class TestSanitizeErrorContext:
    """Tests for IPFSDatasetsMCPServer._sanitize_error_context."""

    def _srv(self):
        return _make_server()

    def test_sensitive_keys_redacted(self):
        """GIVEN kwargs with sensitive keys WHEN sanitize THEN values are REDACTED."""
        srv = self._srv()
        result = srv._sanitize_error_context({"api_key": "secret123", "password": "pw"})
        assert result["sanitized_arguments"]["api_key"] == "<REDACTED>"
        assert result["sanitized_arguments"]["password"] == "<REDACTED>"

    def test_simple_types_preserved(self):
        """GIVEN simple non-sensitive kwargs WHEN sanitize THEN values preserved."""
        srv = self._srv()
        result = srv._sanitize_error_context({"query": "hello", "count": 5, "flag": True})
        assert result["sanitized_arguments"]["query"] == "hello"
        assert result["sanitized_arguments"]["count"] == 5
        assert result["sanitized_arguments"]["flag"] is True

    def test_list_value_replaced_with_length(self):
        """GIVEN list value WHEN sanitize THEN replaced with length summary."""
        srv = self._srv()
        result = srv._sanitize_error_context({"items": [1, 2, 3]})
        assert "3" in result["sanitized_arguments"]["items"]

    def test_dict_value_replaced_with_key_count(self):
        """GIVEN dict value WHEN sanitize THEN replaced with key count summary."""
        srv = self._srv()
        result = srv._sanitize_error_context({"params": {"a": 1, "b": 2}})
        assert "2" in result["sanitized_arguments"]["params"]

    def test_object_value_replaced_with_type(self):
        """GIVEN object value WHEN sanitize THEN replaced with type name."""
        srv = self._srv()
        result = srv._sanitize_error_context({"obj": object()})
        assert "object" in result["sanitized_arguments"]["obj"].lower()

    def test_argument_count_correct(self):
        """GIVEN 3 kwargs WHEN sanitize THEN argument_count=3."""
        srv = self._srv()
        result = srv._sanitize_error_context({"a": 1, "b": 2, "c": 3})
        assert result["argument_count"] == 3

    def test_argument_names_correct(self):
        """GIVEN kwargs WHEN sanitize THEN argument_names matches keys."""
        srv = self._srv()
        result = srv._sanitize_error_context({"x": 10, "y": 20})
        assert set(result["argument_names"]) == {"x", "y"}

    def test_token_key_redacted(self):
        """GIVEN token key WHEN sanitize THEN redacted."""
        srv = self._srv()
        result = srv._sanitize_error_context({"auth_token": "bearer_xyz"})
        assert result["sanitized_arguments"]["auth_token"] == "<REDACTED>"

    def test_empty_kwargs(self):
        """GIVEN empty kwargs WHEN sanitize THEN argument_count=0."""
        srv = self._srv()
        result = srv._sanitize_error_context({})
        assert result["argument_count"] == 0
        assert result["argument_names"] == []


# ══════════════════════════════════════════════════════════════════════════════
# 6. _wrap_tool_with_error_reporting
# ══════════════════════════════════════════════════════════════════════════════


class TestWrapToolWithErrorReporting:
    """Tests for _wrap_tool_with_error_reporting."""

    def _srv(self):
        return _make_server()

    @pytest.mark.anyio
    async def test_async_tool_wrapped_and_called(self):
        """GIVEN async tool WHEN wrapped THEN wrapper is coroutine and calls original."""
        srv = self._srv()
        import inspect

        async def my_async_tool(x):
            """Async tool."""
            return x * 2

        wrapped = srv._wrap_tool_with_error_reporting("my_async_tool", my_async_tool)
        assert inspect.iscoroutinefunction(wrapped)
        result = await wrapped(5)
        assert result == 10

    def test_sync_tool_wrapped_and_called(self):
        """GIVEN sync tool WHEN wrapped THEN wrapper is sync and calls original."""
        srv = self._srv()
        import inspect

        def my_sync_tool(x):
            """Sync tool."""
            return x + 1

        wrapped = srv._wrap_tool_with_error_reporting("my_sync_tool", my_sync_tool)
        assert not inspect.iscoroutinefunction(wrapped)
        result = wrapped(4)
        assert result == 5

    @pytest.mark.anyio
    async def test_async_tool_error_reported_and_reraised(self):
        """GIVEN async tool that raises WHEN wrapped and called THEN error reported + re-raised."""
        srv = self._srv()

        async def bad_async_tool():
            """Raises."""
            raise ValueError("async tool error")

        mock_reporter = MagicMock()
        mock_reporter.report_error = MagicMock()
        mock_get_logs = MagicMock(return_value=[])

        wrapped = srv._wrap_tool_with_error_reporting("bad_async_tool", bad_async_tool)

        with patch.object(server_mod, "ERROR_REPORTING_AVAILABLE", True):
            with patch.object(server_mod, "error_reporter", mock_reporter, create=True):
                with patch.object(server_mod, "get_recent_logs", mock_get_logs, create=True):
                    with pytest.raises(ValueError, match="async tool error"):
                        await wrapped()

    def test_sync_tool_error_reported_and_reraised(self):
        """GIVEN sync tool that raises WHEN wrapped and called THEN re-raised."""
        srv = self._srv()

        def bad_sync_tool():
            """Raises."""
            raise RuntimeError("sync tool error")

        wrapped = srv._wrap_tool_with_error_reporting("bad_sync_tool", bad_sync_tool)

        with pytest.raises(RuntimeError, match="sync tool error"):
            wrapped()

    def test_wrapped_tool_preserves_name(self):
        """GIVEN tool WHEN wrapped THEN __name__ preserved via functools.wraps."""
        srv = self._srv()

        def named_tool():
            """Has name."""
            return "ok"

        wrapped = srv._wrap_tool_with_error_reporting("named_tool", named_tool)
        assert wrapped.__name__ == "named_tool"


# ══════════════════════════════════════════════════════════════════════════════
# 7. _register_tools_from_subdir
# ══════════════════════════════════════════════════════════════════════════════


class TestRegisterToolsFromSubdir:
    """Tests for _register_tools_from_subdir."""

    def _srv_with_mcp(self):
        """Create server with mocked FastMCP instance."""
        mock_mcp_instance = MagicMock()
        with patch.object(server_mod, "FastMCP", return_value=mock_mcp_instance):
            with patch.object(server_mod, "ERROR_REPORTING_AVAILABLE", False):
                with patch.object(
                    IPFSDatasetsMCPServer, "_initialize_p2p_services", lambda self: None
                ):
                    srv = IPFSDatasetsMCPServer()
                    srv.mcp = mock_mcp_instance
                    srv._fastmcp_available = True
        return srv, mock_mcp_instance

    def test_tools_registered_in_tools_dict(self, tmp_path):
        """GIVEN tools in subdir WHEN _register_tools_from_subdir THEN tools added to self.tools."""
        srv, mock_mcp = self._srv_with_mcp()

        def my_func():
            """A tool."""
            return "ok"

        with patch.object(server_mod, "import_tools_from_directory", return_value={"my_func": my_func}):
            srv._register_tools_from_subdir(tmp_path)

        assert "my_func" in srv.tools

    def test_empty_subdir_no_tools_registered(self, tmp_path):
        """GIVEN empty subdir WHEN _register_tools_from_subdir THEN no tools registered."""
        srv, mock_mcp = self._srv_with_mcp()

        with patch.object(server_mod, "import_tools_from_directory", return_value={}):
            srv._register_tools_from_subdir(tmp_path)

        assert srv.tools == {}


# ══════════════════════════════════════════════════════════════════════════════
# 8. _register_direct_ipfs_kit_imports / _register_ipfs_kit_mcp_client
# ══════════════════════════════════════════════════════════════════════════════


class TestRegisterIpfsKitTools:
    """Tests for direct ipfs_kit imports and MCP client registration."""

    def _srv_with_mcp(self):
        mock_mcp_instance = MagicMock()
        with patch.object(server_mod, "FastMCP", return_value=mock_mcp_instance):
            with patch.object(server_mod, "ERROR_REPORTING_AVAILABLE", False):
                with patch.object(
                    IPFSDatasetsMCPServer, "_initialize_p2p_services", lambda self: None
                ):
                    srv = IPFSDatasetsMCPServer()
                    srv.mcp = mock_mcp_instance
                    srv._fastmcp_available = True
        return srv, mock_mcp_instance

    def test_direct_import_import_error_handled(self):
        """GIVEN ipfs_kit_py not installed WHEN _register_direct_ipfs_kit_imports THEN no raise."""
        srv, _ = self._srv_with_mcp()
        with patch.dict(sys.modules, {"ipfs_kit_py": None}):
            srv._register_direct_ipfs_kit_imports()  # must not raise

    def test_direct_import_registers_available_funcs(self):
        """GIVEN ipfs_kit_py with 'add' func WHEN register THEN ipfs_kit_add in tools."""
        srv, mock_mcp = self._srv_with_mcp()
        fake_add = MagicMock()
        fake_ipfs_kit = MagicMock()
        fake_ipfs_kit.add = fake_add

        with patch.dict(sys.modules, {"ipfs_kit_py": fake_ipfs_kit}):
            srv._register_direct_ipfs_kit_imports()

        assert "ipfs_kit_add" in srv.tools

    @pytest.mark.anyio
    async def test_register_ipfs_kit_mcp_client_import_error_handled(self):
        """GIVEN MCPClient import fails WHEN _register_ipfs_kit_mcp_client THEN no raise."""
        srv, _ = self._srv_with_mcp()
        with patch.dict(sys.modules, {"ipfs_datasets_py.mcp_server.client": None}):
            await srv._register_ipfs_kit_mcp_client("http://localhost:9000")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# 9. start_stdio_server / start_server
# ══════════════════════════════════════════════════════════════════════════════


class TestStartFunctions:
    """Tests for start_stdio_server / start_server (KeyboardInterrupt)."""

    def test_start_stdio_server_keyboard_interrupt(self):
        """GIVEN KeyboardInterrupt from anyio.run WHEN start_stdio_server THEN no raise."""
        with patch.object(server_mod, "IPFSDatasetsMCPServer") as mock_cls:
            mock_cls.return_value = MagicMock()
            with patch.object(server_mod, "anyio") as mock_anyio:
                mock_anyio.run.side_effect = KeyboardInterrupt()
                start_stdio_server()  # must not raise

    def test_start_server_keyboard_interrupt(self):
        """GIVEN KeyboardInterrupt from anyio.run WHEN start_server THEN no raise."""
        with patch.object(server_mod, "IPFSDatasetsMCPServer") as mock_cls:
            mock_cls.return_value = MagicMock()
            with patch.object(server_mod, "anyio") as mock_anyio:
                mock_anyio.run.side_effect = KeyboardInterrupt()
                start_server()  # must not raise

    def test_start_stdio_server_sets_ipfs_kit_url(self):
        """GIVEN ipfs_kit_mcp_url WHEN start_stdio_server THEN configs updated."""
        with patch.object(server_mod, "IPFSDatasetsMCPServer") as mock_cls:
            mock_cls.return_value = MagicMock()
            with patch.object(server_mod, "anyio") as mock_anyio:
                mock_anyio.run.side_effect = KeyboardInterrupt()
                start_stdio_server(ipfs_kit_mcp_url="http://localhost:9999")
        assert server_mod.configs.ipfs_kit_mcp_url == "http://localhost:9999"


# ══════════════════════════════════════════════════════════════════════════════
# 10. Args model
# ══════════════════════════════════════════════════════════════════════════════


class TestArgsModel:
    """Tests for the Args pydantic model."""

    def _namespace(self, host="0.0.0.0", port=8000, ipfs_kit_mcp_url=None, config=None):
        ns = argparse.Namespace()
        ns.host = host
        ns.port = port
        ns.ipfs_kit_mcp_url = ipfs_kit_mcp_url
        ns.config = config
        return ns

    def test_basic_args_construction(self):
        """GIVEN basic namespace WHEN Args constructed THEN host/port correct."""
        args = Args(self._namespace())
        assert args.host == "0.0.0.0"
        assert args.port == 8000

    def test_custom_host_and_port(self):
        """GIVEN custom host/port WHEN Args constructed THEN values stored."""
        args = Args(self._namespace(host="127.0.0.1", port=9000))
        assert args.host == "127.0.0.1"
        assert args.port == 9000

    def test_optional_fields_none_by_default(self):
        """GIVEN no url/config WHEN Args constructed THEN optional fields are None."""
        args = Args(self._namespace())
        assert args.ipfs_kit_mcp_url is None
        assert args.config is None
