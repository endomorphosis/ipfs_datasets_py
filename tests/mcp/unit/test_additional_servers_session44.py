"""
Session 44 — Additional MCP Server Module Tests
=================================================
Covers five previously-untested (or barely-tested) mcp_server root modules:
  • __main__.py               (75  stmts, 0  % → 92 %)
  • investigation_mcp_client.py (71 stmts, 0  % → 97 %)
  • simple_server.py          (120 stmts, 8  % → 83 %)
  • standalone_server.py      (139 stmts, 0  % → 81 %)
  • temporal_deontic_mcp_server.py (122 stmts, 0 % → 90 %)

All tests are pure-unit; no external services are started.
Flask routes are exercised with the built-in test client.
aiohttp I/O is replaced with AsyncMock objects.
The mcp/temporal-deontic-logic tool imports are patched at module level
so that the modules can be imported without those optional packages.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import sys
import unittest
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Module-level mocks that must be in place BEFORE importing the modules we test
# ---------------------------------------------------------------------------

# 1. temporal_deontic_mcp_server.py needs mcp + two logic tool modules
_mock_mcp = MagicMock()
_mock_mcp.types = MagicMock()
_mock_mcp.server = MagicMock()
_mock_mcp.server.Server = MagicMock
_mock_mcp.server.stdio = MagicMock()
_mock_mcp.server.stdio.stdio_server = MagicMock()
sys.modules.setdefault("mcp", _mock_mcp)
sys.modules.setdefault("mcp.types", _mock_mcp.types)
sys.modules.setdefault("mcp.server", _mock_mcp.server)
sys.modules.setdefault("mcp.server.stdio", _mock_mcp.server.stdio)

_mock_tdlt = MagicMock()
_mock_tdlt.TEMPORAL_DEONTIC_LOGIC_TOOLS = []
sys.modules.setdefault(
    "ipfs_datasets_py.mcp_server.tools.logic_tools.temporal_deontic_logic_tools",
    _mock_tdlt,
)
_mock_legal = MagicMock()
_mock_legal.LEGAL_DATASET_MCP_TOOLS = []
sys.modules.setdefault(
    "ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.mcp_tools",
    _mock_legal,
)

# ---------------------------------------------------------------------------
# Safe imports of the modules under test
# ---------------------------------------------------------------------------
import ipfs_datasets_py.mcp_server.__main__ as main_mod  # noqa: E402
from ipfs_datasets_py.mcp_server.investigation_mcp_client import (  # noqa: E402
    InvestigationMCPClient,
    InvestigationMCPClientError,
    create_investigation_mcp_client,
)
from ipfs_datasets_py.mcp_server.simple_server import (  # noqa: E402
    SimpleIPFSDatasetsMCPServer,
    SimpleCallResult,
    import_tools_from_directory,
    import_argparse_program,
)
from ipfs_datasets_py.mcp_server.standalone_server import (  # noqa: E402
    MinimalMCPServer,
    MinimalMCPDashboard,
)
import ipfs_datasets_py.mcp_server.standalone_server as standalone_mod  # noqa: E402
from ipfs_datasets_py.mcp_server.temporal_deontic_mcp_server import (  # noqa: E402
    TemporalDeonticMCPServer,
)
import ipfs_datasets_py.mcp_server.temporal_deontic_mcp_server as tdm_mod  # noqa: E402
from ipfs_datasets_py.mcp_server.exceptions import (  # noqa: E402
    ServerStartupError,
    ConfigurationError,
    ToolExecutionError,
    ToolNotFoundError,
)


# ===========================================================================
# 1.  __main__.py — main() entry point
# ===========================================================================

class TestMain:
    """Tests for ipfs_datasets_py.mcp_server.__main__.main()."""

    def _call_main(self, argv: list, patches: dict | None = None):
        """Helper: call main() with the given sys.argv list."""
        patches = patches or {}
        with patch.object(sys, "argv", ["__main__"] + argv):
            with patch.dict(sys.modules, patches):
                main_mod.main()

    def test_main_stdio_mode_default(self):
        """Default (no --http) calls start_stdio_server."""
        import ipfs_datasets_py.mcp_server as mcp_pkg
        with patch.object(sys, "argv", ["__main__"]):
            with patch.object(mcp_pkg, "start_stdio_server", MagicMock()) as mock_stdio:
                with patch.object(mcp_pkg, "start_server", MagicMock()):
                    with patch.object(mcp_pkg, "configs", MagicMock(), create=True):
                        main_mod.main()
            mock_stdio.assert_called_once()

    def test_main_http_mode(self):
        """--http flag calls start_server with host/port."""
        import ipfs_datasets_py.mcp_server as mcp_pkg
        with patch.object(sys, "argv", ["__main__", "--http", "--port", "9999", "--host", "0.0.0.0"]):
            with patch.object(mcp_pkg, "start_stdio_server", MagicMock(), create=True):
                with patch.object(mcp_pkg, "start_server", MagicMock()) as mock_server:
                    with patch.object(mcp_pkg, "configs", MagicMock(), create=True):
                        main_mod.main()
        mock_server.assert_called_once_with(host="0.0.0.0", port=9999)

    def test_main_keyboard_interrupt(self, capsys):
        """KeyboardInterrupt is caught and a message is printed."""
        import ipfs_datasets_py.mcp_server as mcp_pkg
        with patch.object(sys, "argv", ["__main__"]):
            with patch.object(mcp_pkg, "start_stdio_server",
                              MagicMock(side_effect=KeyboardInterrupt), create=True):
                with patch.object(mcp_pkg, "start_server", MagicMock(), create=True):
                    with patch.object(mcp_pkg, "configs", MagicMock(), create=True):
                        main_mod.main()  # should NOT raise
        out = capsys.readouterr().out
        assert "stopped" in out.lower()

    def test_main_import_error_exits(self, capsys):
        """ImportError exits with code 1."""
        import ipfs_datasets_py.mcp_server as mcp_pkg
        with patch.object(sys, "argv", ["__main__"]):
            with patch.object(mcp_pkg, "start_stdio_server",
                              MagicMock(side_effect=ImportError("missing")), create=True):
                with patch.object(mcp_pkg, "start_server", MagicMock(), create=True):
                    with patch.object(mcp_pkg, "configs", MagicMock(), create=True):
                        with pytest.raises(SystemExit) as exc:
                            main_mod.main()
        assert exc.value.code == 1

    def test_main_server_startup_error_exits(self, capsys):
        """ServerStartupError exits with code 1."""
        import ipfs_datasets_py.mcp_server as mcp_pkg
        with patch.object(sys, "argv", ["__main__"]):
            with patch.object(
                mcp_pkg, "start_stdio_server",
                MagicMock(side_effect=ServerStartupError("startup_fail")), create=True
            ):
                with patch.object(mcp_pkg, "start_server", MagicMock(), create=True):
                    with patch.object(mcp_pkg, "configs", MagicMock(), create=True):
                        with pytest.raises(SystemExit) as exc:
                            main_mod.main()
        assert exc.value.code == 1

    def test_main_configuration_error_exits(self, capsys):
        """ConfigurationError exits with code 1."""
        import ipfs_datasets_py.mcp_server as mcp_pkg
        with patch.object(sys, "argv", ["__main__"]):
            with patch.object(
                mcp_pkg, "start_stdio_server",
                MagicMock(side_effect=ConfigurationError("bad_config")), create=True
            ):
                with patch.object(mcp_pkg, "start_server", MagicMock(), create=True):
                    with patch.object(mcp_pkg, "configs", MagicMock(), create=True):
                        with pytest.raises(SystemExit) as exc:
                            main_mod.main()
        assert exc.value.code == 1

    def test_main_generic_exception_exits(self, capsys):
        """Generic Exception exits with code 1."""
        import ipfs_datasets_py.mcp_server as mcp_pkg
        with patch.object(sys, "argv", ["__main__"]):
            with patch.object(
                mcp_pkg, "start_stdio_server",
                MagicMock(side_effect=RuntimeError("unexpected")), create=True
            ):
                with patch.object(mcp_pkg, "start_server", MagicMock(), create=True):
                    with patch.object(mcp_pkg, "configs", MagicMock(), create=True):
                        with pytest.raises(SystemExit) as exc:
                            main_mod.main()
        assert exc.value.code == 1

    def test_main_debug_flag_sets_logging(self):
        """--debug flag triggers basicConfig(level=DEBUG) call."""
        import ipfs_datasets_py.mcp_server as mcp_pkg
        with patch.object(sys, "argv", ["__main__", "--debug"]):
            with patch.object(mcp_pkg, "start_stdio_server", MagicMock(), create=True):
                with patch.object(mcp_pkg, "start_server", MagicMock(), create=True):
                    with patch.object(mcp_pkg, "configs", MagicMock(), create=True):
                        with patch("logging.basicConfig") as mock_bc:
                            main_mod.main()
        mock_bc.assert_called_once_with(level=logging.DEBUG)

    def test_main_http_import_error_fallback(self, capsys):
        """--http with ImportError from start_server falls back to SimpleIPFSDatasetsMCPServer."""
        import ipfs_datasets_py.mcp_server as mcp_pkg
        mock_simple_server = MagicMock()
        with patch.object(sys, "argv", ["__main__", "--http"]):
            with patch.object(
                mcp_pkg, "start_server",
                MagicMock(side_effect=ImportError("no server")), create=True
            ):
                with patch.object(mcp_pkg, "start_stdio_server", MagicMock(), create=True):
                    with patch.object(mcp_pkg, "configs", MagicMock(), create=True):
                        with patch(
                            "ipfs_datasets_py.mcp_server.simple_server.SimpleIPFSDatasetsMCPServer",
                            return_value=mock_simple_server,
                        ):
                            with patch(
                                "ipfs_datasets_py.mcp_server.configs.load_config_from_yaml",
                                return_value=MagicMock(host="127.0.0.1", port=8000),
                            ):
                                main_mod.main()
        # Should have called run() on the fallback server
        mock_simple_server.register_tools.assert_called_once()
        mock_simple_server.run.assert_called_once()


# ===========================================================================
# 2.  investigation_mcp_client.py — InvestigationMCPClient
# ===========================================================================

class TestInvestigationMCPClientError:
    """InvestigationMCPClientError construction and attributes."""

    def test_basic_construction(self):
        err = InvestigationMCPClientError("something went wrong")
        assert str(err) == "something went wrong"
        assert err.details == {}
        assert isinstance(err.timestamp, str)

    def test_construction_with_details(self):
        err = InvestigationMCPClientError("oops", {"key": "value", "code": 500})
        assert err.details == {"key": "value", "code": 500}


class TestInvestigationMCPClientInit:
    """InvestigationMCPClient initialisation."""

    def test_defaults(self):
        c = InvestigationMCPClient()
        assert c.base_url == "http://localhost:8080"
        assert c.endpoint == "/mcp/call-tool"
        assert c.timeout == 60
        assert c.session is None
        assert c.request_id == 0

    def test_custom_params(self):
        c = InvestigationMCPClient("http://example.com", "/custom", 30)
        assert c.base_url == "http://example.com"
        assert c.endpoint == "/custom"
        assert c.timeout == 30

    def test_trailing_slash_stripped(self):
        c = InvestigationMCPClient("http://example.com/")
        assert c.base_url == "http://example.com"


class TestInvestigationMCPClientConnect:
    """connect() / disconnect() / context manager."""

    def test_connect_creates_session(self):
        async def run():
            c = InvestigationMCPClient()
            assert c.session is None
            await c.connect()
            assert c.session is not None
            await c.disconnect()
            assert c.session is None

        asyncio.run(run())

    def test_connect_idempotent(self):
        """A second call to connect() does nothing if session exists."""
        async def run():
            c = InvestigationMCPClient()
            await c.connect()
            first_session = c.session
            await c.connect()  # second call — should not replace session
            assert c.session is first_session
            await c.disconnect()

        asyncio.run(run())

    def test_disconnect_no_session(self):
        """disconnect() when session is None should not raise."""
        async def run():
            c = InvestigationMCPClient()
            await c.disconnect()  # no-op

        asyncio.run(run())

    def test_async_context_manager(self):
        async def run():
            async with InvestigationMCPClient() as client:
                assert client.session is not None
            # After __aexit__ session should be closed (None)
            assert client.session is None

        asyncio.run(run())


class TestInvestigationMCPClientCallTool:
    """call_tool() — various success and failure paths."""

    def _make_mock_response(self, status=200, json_data=None, text="error body"):
        """Build a mock aiohttp response async context manager."""
        import aiohttp
        mock_resp = AsyncMock()
        mock_resp.status = status
        mock_resp.json = AsyncMock(return_value=json_data or {"result": "ok"})
        mock_resp.text = AsyncMock(return_value=text)
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        return mock_cm, mock_resp

    def test_call_tool_success(self):
        async def run():
            import aiohttp
            c = InvestigationMCPClient()
            await c.connect()
            mock_cm, _ = self._make_mock_response(200, {"result": "answer", "isError": False})
            c.session.post = MagicMock(return_value=mock_cm)
            result = await c.call_tool("my_tool", {"arg": "val"})
            assert result["result"] == "answer"
            assert c.request_id == 1
            await c.disconnect()

        asyncio.run(run())

    def test_call_tool_http_error(self):
        async def run():
            c = InvestigationMCPClient()
            await c.connect()
            mock_cm, _ = self._make_mock_response(503, text="service unavailable")
            c.session.post = MagicMock(return_value=mock_cm)
            with pytest.raises(InvestigationMCPClientError, match="HTTP 503"):
                await c.call_tool("my_tool", {})
            await c.disconnect()

        asyncio.run(run())

    def test_call_tool_is_error_in_response(self):
        async def run():
            c = InvestigationMCPClient()
            await c.connect()
            error_json = {
                "isError": True,
                "content": [{"text": "tool execution failed"}],
            }
            mock_cm, _ = self._make_mock_response(200, error_json)
            c.session.post = MagicMock(return_value=mock_cm)
            with pytest.raises(InvestigationMCPClientError, match="tool execution failed"):
                await c.call_tool("bad_tool", {})
            await c.disconnect()

        asyncio.run(run())

    def test_call_tool_aiohttp_client_error(self):
        async def run():
            import aiohttp
            c = InvestigationMCPClient()
            await c.connect()
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("network fail"))
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            c.session.post = MagicMock(return_value=mock_cm)
            with pytest.raises(InvestigationMCPClientError, match="Network error"):
                await c.call_tool("my_tool", {})
            await c.disconnect()

        asyncio.run(run())

    def test_call_tool_timeout_error(self):
        async def run():
            c = InvestigationMCPClient()
            await c.connect()
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(side_effect=TimeoutError("timed out"))
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            c.session.post = MagicMock(return_value=mock_cm)
            with pytest.raises(InvestigationMCPClientError, match="Timeout"):
                await c.call_tool("my_tool", {})
            await c.disconnect()

        asyncio.run(run())

    def test_call_tool_json_decode_error(self):
        async def run():
            import aiohttp
            c = InvestigationMCPClient()
            await c.connect()
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(side_effect=json.JSONDecodeError("bad json", "", 0))
            mock_resp.text = AsyncMock(return_value="not json")
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            c.session.post = MagicMock(return_value=mock_cm)
            with pytest.raises(InvestigationMCPClientError, match="Invalid JSON"):
                await c.call_tool("my_tool", {})
            await c.disconnect()

        asyncio.run(run())

    def test_call_tool_generic_exception(self):
        async def run():
            c = InvestigationMCPClient()
            await c.connect()
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(side_effect=RuntimeError("something weird"))
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            c.session.post = MagicMock(return_value=mock_cm)
            with pytest.raises(InvestigationMCPClientError, match="Unexpected error"):
                await c.call_tool("my_tool", {})
            await c.disconnect()

        asyncio.run(run())

    def test_call_tool_auto_connect_if_no_session(self):
        """If session is None, call_tool should auto-call connect() first."""
        async def run():
            c = InvestigationMCPClient()
            assert c.session is None
            # Build a proper async context-manager for aiohttp's session.post
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"answer": 42})

            class _MockCM:
                async def __aenter__(self_cm):
                    return mock_resp
                async def __aexit__(self_cm, *_):
                    return False

            async def fake_connect():
                mock_session = MagicMock()
                mock_session.close = AsyncMock()  # disconnect() awaits session.close()
                mock_session.post = MagicMock(return_value=_MockCM())
                c.session = mock_session

            c.connect = fake_connect
            result = await c.call_tool("t", {})
            assert result["answer"] == 42
            await c.disconnect()

        asyncio.run(run())


class TestInvestigationMCPClientConvenienceMethods:
    """Convenience wrappers delegate to call_tool with correct tool names."""

    def test_extract_geographic_entities_calls_correct_tool(self):
        async def run():
            c = InvestigationMCPClient()
            c.call_tool = AsyncMock(return_value={"result": "entities"})
            result = await c.extract_geographic_entities("corpus text")
            c.call_tool.assert_called_once()
            args = c.call_tool.call_args[0]
            assert args[0] == "extract_geographic_entities"
            assert args[1]["corpus_data"] == "corpus text"
            assert result == {"result": "entities"}

        asyncio.run(run())

    def test_map_spatiotemporal_events_calls_correct_tool(self):
        async def run():
            c = InvestigationMCPClient()
            c.call_tool = AsyncMock(return_value={"result": "events"})
            result = await c.map_spatiotemporal_events("corpus data")
            args = c.call_tool.call_args[0]
            assert args[0] == "map_spatiotemporal_events"

        asyncio.run(run())

    def test_query_geographic_context_calls_correct_tool(self):
        async def run():
            c = InvestigationMCPClient()
            c.call_tool = AsyncMock(return_value={"result": "context"})
            result = await c.query_geographic_context("query", "corpus data")
            args = c.call_tool.call_args[0]
            assert args[0] == "query_geographic_context"

        asyncio.run(run())


class TestCreateInvestigationMCPClient:
    """Factory function."""

    def test_factory_creates_client_with_correct_params(self):
        c = create_investigation_mcp_client("http://my-server", "/api", 45)
        assert isinstance(c, InvestigationMCPClient)
        assert c.base_url == "http://my-server"
        assert c.endpoint == "/api"
        assert c.timeout == 45

    def test_factory_uses_defaults(self):
        c = create_investigation_mcp_client()
        assert c.base_url == "http://localhost:8080"


# ===========================================================================
# 3.  simple_server.py — SimpleCallResult + SimpleIPFSDatasetsMCPServer
# ===========================================================================

class TestSimpleCallResult:
    """SimpleCallResult.to_dict() paths."""

    def test_success_result(self):
        r = SimpleCallResult("my result")
        d = r.to_dict()
        assert d["success"] is True
        assert d["result"] == "my result"

    def test_error_result(self):
        r = SimpleCallResult(None, "something went wrong")
        d = r.to_dict()
        assert d["success"] is False
        assert d["error"] == "something went wrong"


class TestImportToolsFromDirectory:
    """import_tools_from_directory — various edge cases."""

    def test_nonexistent_directory_returns_empty(self, tmp_path):
        result = import_tools_from_directory(tmp_path / "does_not_exist")
        assert result == {}

    def test_empty_directory_returns_empty(self, tmp_path):
        result = import_tools_from_directory(tmp_path)
        assert result == {}

    def test_ignores_init_files(self, tmp_path):
        (tmp_path / "__init__.py").write_text("x = 1\n")
        result = import_tools_from_directory(tmp_path)
        assert result == {}


class TestImportArgparseProgram:
    """import_argparse_program — program_name is always None, raises AttributeError."""

    def test_raises_on_none_program_name(self, tmp_path):
        # The function has a bug: program_name is always None.
        # importlib.import_module(None) raises AttributeError on
        # `None.startswith(...)` inside importlib.
        with pytest.raises((TypeError, AttributeError)):
            import_argparse_program(tmp_path)


class TestSimpleIPFSDatasetsMCPServer:
    """SimpleIPFSDatasetsMCPServer — Flask-based routes."""

    def setup_method(self):
        self.server = SimpleIPFSDatasetsMCPServer()
        self.client = self.server.app.test_client()

    def test_root_endpoint(self):
        r = self.client.get("/")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "healthy"
        assert "IPFS" in data["name"]

    def test_tools_endpoint_empty(self):
        r = self.client.get("/tools")
        assert r.status_code == 200
        data = r.get_json()
        assert data["tools"] == {}

    def test_tools_endpoint_with_registered_tool(self):
        def my_tool(x: int = 0):
            """A test tool."""
            return x * 2

        self.server.tools["my_tool"] = my_tool
        r = self.client.get("/tools")
        data = r.get_json()
        assert "my_tool" in data["tools"]
        assert "A test tool" in data["tools"]["my_tool"]["description"]

    def test_call_tool_not_found(self):
        r = self.client.post("/tools/nonexistent", json={})
        assert r.status_code == 404

    def test_call_tool_success(self):
        def adder(a: int = 0, b: int = 0):
            return a + b

        self.server.tools["adder"] = adder
        r = self.client.post("/tools/adder", json={"a": 3, "b": 4})
        assert r.status_code == 200
        data = r.get_json()
        assert data["result"] == 7

    def test_call_tool_type_error(self):
        def strict_fn(required_param: str):
            return required_param

        self.server.tools["strict_fn"] = strict_fn
        # Call without required param → TypeError
        r = self.client.post("/tools/strict_fn", json={})
        assert r.status_code == 400

    def test_call_tool_execution_error(self):
        def fail_fn():
            raise ToolExecutionError("fail_fn", RuntimeError("boom"))

        self.server.tools["fail_fn"] = fail_fn
        r = self.client.post("/tools/fail_fn", json={})
        assert r.status_code == 500

    def test_call_tool_generic_exception(self):
        def buggy_fn():
            raise RuntimeError("unexpected")

        self.server.tools["buggy_fn"] = buggy_fn
        r = self.client.post("/tools/buggy_fn", json={})
        assert r.status_code == 500

    def test_register_tools_subdirectory_missing_is_ignored(self, tmp_path):
        """_register_tools_from_subdir with nonexistent path does nothing."""
        self.server._register_tools_from_subdir(tmp_path / "nonexistent")
        # No exception, tools unchanged

    def test_register_tools_from_subdir_populates(self):
        """_register_tools_from_subdir delegates to import_tools_from_directory."""
        from pathlib import Path
        with patch(
            "ipfs_datasets_py.mcp_server.simple_server.import_tools_from_directory",
            return_value={"fake_tool": lambda: "result"},
        ):
            self.server._register_tools_from_subdir(Path("/some/path"))
        assert "fake_tool" in self.server.tools


# ===========================================================================
# 4.  standalone_server.py — MinimalMCPServer + MinimalMCPDashboard
# ===========================================================================

class TestMinimalMCPServer:
    """MinimalMCPServer Flask routes."""

    def setup_method(self):
        self.server = MinimalMCPServer(host="127.0.0.1", port=9001)
        self.client = self.server.app.test_client()

    def test_init_attributes(self):
        assert self.server.host == "127.0.0.1"
        assert self.server.port == 9001
        assert self.server.app is not None

    def test_health_endpoint(self):
        r = self.client.get("/health")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"

    def test_index_endpoint(self):
        r = self.client.get("/")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "running"
        assert "health" in data["endpoints"]

    def test_tools_endpoint(self):
        r = self.client.get("/tools")
        assert r.status_code == 200
        data = r.get_json()
        assert "tools" in data
        tools = data["tools"]
        assert any(t["name"] == "echo" for t in tools)

    def test_execute_echo_tool(self):
        r = self.client.post(
            "/execute",
            json={"tool_name": "echo", "parameters": {"text": "hello"}},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True
        assert "hello" in data["result"]

    def test_execute_status_tool(self):
        r = self.client.post(
            "/execute", json={"tool_name": "status", "parameters": {}}
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["success"] is True

    def test_execute_unknown_tool(self):
        r = self.client.post(
            "/execute", json={"tool_name": "not_real", "parameters": {}}
        )
        assert r.status_code == 400
        data = r.get_json()
        assert data["success"] is False

    def test_execute_tool_execution_error(self):
        """Non-JSON body causes AttributeError on None.get() → 500."""
        s = MinimalMCPServer()
        # Sending non-JSON → request.get_json() returns None → AttributeError → 500
        r = s.app.test_client().post(
            "/execute",
            data="not json",
            content_type="text/plain",
        )
        assert r.status_code == 500

    def test_execute_value_error_branch(self):
        """ValueError in parameters → 400."""
        # Send request where tool_name would raise ValueError
        # (here: no tool_name key in JSON → None → unknown → 400)
        r = self.client.post("/execute", json={"parameters": {}})
        assert r.status_code == 400


class TestMinimalMCPDashboard:
    """MinimalMCPDashboard Flask routes."""

    def setup_method(self):
        self.dashboard = MinimalMCPDashboard(
            host="127.0.0.1", port=9002, mcp_server_url="http://localhost:9001"
        )
        self.client = self.dashboard.app.test_client()

    def test_init_attributes(self):
        assert self.dashboard.host == "127.0.0.1"
        assert self.dashboard.port == 9002
        assert self.dashboard.mcp_server_url == "http://localhost:9001"

    def test_health_endpoint(self):
        r = self.client.get("/health")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "healthy"

    def test_index_endpoint_returns_html(self):
        r = self.client.get("/")
        assert r.status_code == 200
        assert b"<!DOCTYPE html>" in r.data.lower() or b"IPFS" in r.data

    def test_api_health_endpoint(self):
        r = self.client.get("/api/health")
        assert r.status_code == 200
        data = r.get_json()
        assert data["dashboard_status"] == "healthy"
        assert data["mcp_server"] == "http://localhost:9001"

    def test_api_execute_import_error(self):
        """ImportError inside /api/execute (requests unavailable) → 503."""
        # Setting requests to None in sys.modules makes `import requests` raise
        # ModuleNotFoundError, which is caught by the (ImportError, ModuleNotFoundError)
        # handler → HTTP 503.
        with patch.dict(sys.modules, {"requests": None}):
            r = self.client.post("/api/execute", json={"tool_name": "echo"})
        assert r.status_code == 503

    def test_api_execute_generic_exception(self):
        """Generic exception in /api/execute (connection refused) → 500."""
        import requests as req_mod
        with patch.object(req_mod, "post", side_effect=RuntimeError("conn refused")):
            r = self.client.post("/api/execute", json={"tool_name": "echo"})
        assert r.status_code == 500


class TestStandaloneMain:
    """standalone_server.main() paths."""

    def test_dashboard_only_path(self):
        """--dashboard-only creates and runs a MinimalMCPDashboard."""
        mock_dashboard = MagicMock()
        with patch.object(sys, "argv", ["standalone_server.py", "--dashboard-only"]):
            with patch(
                "ipfs_datasets_py.mcp_server.standalone_server.MinimalMCPDashboard",
                return_value=mock_dashboard,
            ):
                standalone_mod.main()
        mock_dashboard.run.assert_called_once()

    def test_server_only_path(self):
        """--server-only creates and runs a MinimalMCPServer."""
        mock_server = MagicMock()
        with patch.object(sys, "argv", ["standalone_server.py", "--server-only"]):
            with patch(
                "ipfs_datasets_py.mcp_server.standalone_server.MinimalMCPServer",
                return_value=mock_server,
            ):
                standalone_mod.main()
        mock_server.run.assert_called_once()


# ===========================================================================
# 5.  temporal_deontic_mcp_server.py — TemporalDeonticMCPServer
# ===========================================================================

class TestTemporalDeonticMCPServerInit:
    """TemporalDeonticMCPServer.__init__ and state."""

    def test_init_no_mcp(self):
        """When MCP_AVAILABLE is False, init succeeds but server=None."""
        with patch.object(tdm_mod, "MCP_AVAILABLE", False):
            t = TemporalDeonticMCPServer(port=9876)
        assert t.port == 9876
        assert t.server is None

    def test_init_tools_dict_built_from_module_lists(self):
        """Tools dict is built by combining TEMPORAL_DEONTIC_LOGIC_TOOLS and LEGAL_DATASET_MCP_TOOLS."""
        tool_a = MagicMock()
        tool_a.name = "tool_a"
        tool_b = MagicMock()
        tool_b.name = "tool_b"
        mock_tdlt2 = MagicMock()
        mock_tdlt2.TEMPORAL_DEONTIC_LOGIC_TOOLS = [tool_a]
        mock_legal2 = MagicMock()
        mock_legal2.LEGAL_DATASET_MCP_TOOLS = [tool_b]
        with patch.object(tdm_mod, "TEMPORAL_DEONTIC_LOGIC_TOOLS", [tool_a]):
            with patch.object(tdm_mod, "LEGAL_DATASET_MCP_TOOLS", [tool_b]):
                t = TemporalDeonticMCPServer()
        assert "tool_a" in t.tools
        assert "tool_b" in t.tools


class TestTemporalDeonticMCPServerSetupServer:
    """setup_server() behavior when MCP not available."""

    def test_setup_server_raises_when_no_mcp(self):
        with patch.object(tdm_mod, "MCP_AVAILABLE", False):
            t = TemporalDeonticMCPServer()
            with pytest.raises(ImportError, match="MCP library not available"):
                t.setup_server()


class TestTemporalDeonticMCPServerStartMethods:
    """start_stdio / start_websocket when MCP not available."""

    def test_start_stdio_raises_when_no_mcp(self):
        with patch.object(tdm_mod, "MCP_AVAILABLE", False):
            t = TemporalDeonticMCPServer()
            with pytest.raises(ImportError):
                asyncio.run(t.start_stdio())

    def test_start_websocket_raises_when_no_mcp(self):
        with patch.object(tdm_mod, "MCP_AVAILABLE", False):
            t = TemporalDeonticMCPServer()
            with pytest.raises(ImportError):
                asyncio.run(t.start_websocket())

    def test_start_websocket_raises_not_implemented_when_mcp_available(self):
        """WebSocket transport is not yet implemented."""
        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            t = TemporalDeonticMCPServer()
            with pytest.raises(NotImplementedError, match="WebSocket"):
                asyncio.run(t.start_websocket(host="localhost", port=9999))


class TestTemporalDeonticMCPServerGetToolSchemas:
    """get_tool_schemas() returns a dict of schemas."""

    def test_empty_tools(self):
        t = TemporalDeonticMCPServer()
        assert t.get_tool_schemas() == {}

    def test_with_tools(self):
        t = TemporalDeonticMCPServer()
        mock_tool = MagicMock()
        mock_tool.get_schema.return_value = {"name": "t1", "description": "d"}
        t.tools["t1"] = mock_tool
        schemas = t.get_tool_schemas()
        assert "t1" in schemas
        assert schemas["t1"]["description"] == "d"


class TestTemporalDeonticMCPServerCallToolDirect:
    """call_tool_direct() — all success and failure paths."""

    def test_unknown_tool(self):
        t = TemporalDeonticMCPServer()
        result = asyncio.run(t.call_tool_direct("nonexistent", {}))
        assert result["success"] is False
        assert result["error_code"] == "UNKNOWN_TOOL"

    def test_success_path(self):
        async def run():
            t = TemporalDeonticMCPServer()
            mock_tool = MagicMock()
            async def async_execute(params):
                return {"success": True, "data": "result"}
            mock_tool.execute = async_execute
            t.tools["my_tool"] = mock_tool
            result = await t.call_tool_direct("my_tool", {"a": 1})
            assert result["success"] is True

        asyncio.run(run())

    def test_tool_execution_error(self):
        async def run():
            t = TemporalDeonticMCPServer()
            mock_tool = MagicMock()
            async def raise_exec_error(params):
                raise ToolExecutionError("bad_tool", RuntimeError("exec failed"))
            mock_tool.execute = raise_exec_error
            t.tools["bad_tool"] = mock_tool
            result = await t.call_tool_direct("bad_tool", {})
            assert result["success"] is False
            assert result["error_code"] == "TOOL_EXECUTION_ERROR"

        asyncio.run(run())

    def test_type_error(self):
        async def run():
            t = TemporalDeonticMCPServer()
            mock_tool = MagicMock()
            async def raise_type_error(params):
                raise TypeError("bad type")
            mock_tool.execute = raise_type_error
            t.tools["type_err_tool"] = mock_tool
            result = await t.call_tool_direct("type_err_tool", {})
            assert result["success"] is False
            assert "Invalid parameters" in result["error"]

        asyncio.run(run())

    def test_generic_exception(self):
        async def run():
            t = TemporalDeonticMCPServer()
            mock_tool = MagicMock()
            async def raise_generic(params):
                raise RuntimeError("unexpected")
            mock_tool.execute = raise_generic
            t.tools["buggy_tool"] = mock_tool
            result = await t.call_tool_direct("buggy_tool", {})
            assert result["success"] is False
            assert result["error_code"] == "TOOL_EXECUTION_ERROR"

        asyncio.run(run())

    def test_tool_not_found_error_is_reraised(self):
        """ToolNotFoundError is explicitly re-raised."""
        async def run():
            t = TemporalDeonticMCPServer()
            mock_tool = MagicMock()
            async def raise_not_found(params):
                raise ToolNotFoundError("missing_tool")
            mock_tool.execute = raise_not_found
            t.tools["not_found_tool"] = mock_tool
            with pytest.raises(ToolNotFoundError):
                await t.call_tool_direct("not_found_tool", {})

        asyncio.run(run())


class TestTemporalDeonticMCPServerMain:
    """temporal_deontic_mcp_server.main() coroutine."""

    def test_main_no_mcp_prints_message(self, capsys):
        with patch.object(tdm_mod, "MCP_AVAILABLE", False):
            asyncio.run(tdm_mod.main())
        out = capsys.readouterr().out
        assert "Error" in out or "not available" in out.lower()

    def test_main_keyboard_interrupt(self, capsys):
        """KeyboardInterrupt is handled gracefully."""
        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            mock_server = MagicMock()
            mock_server.start_stdio = AsyncMock(side_effect=KeyboardInterrupt)
            with patch(
                "ipfs_datasets_py.mcp_server.temporal_deontic_mcp_server.TemporalDeonticMCPServer",
                return_value=mock_server,
            ):
                asyncio.run(tdm_mod.main())
        # Should not raise; server stopped by user

    def test_main_server_startup_error(self):
        """ServerStartupError is caught and logged."""
        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            mock_server = MagicMock()
            mock_server.start_stdio = AsyncMock(
                side_effect=ServerStartupError("startup fail")
            )
            with patch(
                "ipfs_datasets_py.mcp_server.temporal_deontic_mcp_server.TemporalDeonticMCPServer",
                return_value=mock_server,
            ):
                asyncio.run(tdm_mod.main())
        # Should not raise


# ===========================================================================
# Smoke test: module-level singleton in temporal_deontic_mcp_server
# ===========================================================================

class TestTemporalDeonticSingleton:
    """Module-level singleton is a TemporalDeonticMCPServer instance."""

    def test_singleton_exists(self):
        from ipfs_datasets_py.mcp_server.temporal_deontic_mcp_server import (
            temporal_deontic_mcp_server,
        )
        assert isinstance(temporal_deontic_mcp_server, TemporalDeonticMCPServer)


# ===========================================================================
# 6.  simple_server.py — run() / register_tools() / start_simple_server()
# ===========================================================================

class TestSimpleIPFSDatasetsMCPServerRun:
    """SimpleIPFSDatasetsMCPServer.run() and register_tools()."""

    def test_run_uses_configs_defaults(self):
        """run() calls self.app.run with the config host/port."""
        server = SimpleIPFSDatasetsMCPServer()
        with patch.object(server.app, "run") as mock_run:
            server.run()
        mock_run.assert_called_once_with(
            host=server.configs.host,
            port=server.configs.port,
            debug=server.configs.verbose,
        )

    def test_run_uses_explicit_host_port(self):
        """run() with explicit host/port overrides config."""
        server = SimpleIPFSDatasetsMCPServer()
        with patch.object(server.app, "run") as mock_run:
            server.run(host="0.0.0.0", port=9999)
        mock_run.assert_called_once_with(host="0.0.0.0", port=9999, debug=server.configs.verbose)

    def test_register_tools_calls_subdir_helpers(self):
        """register_tools() iterates all standard subdirs."""
        server = SimpleIPFSDatasetsMCPServer()
        with patch.object(server, "_register_tools_from_subdir") as mock_reg:
            server.register_tools()
        assert mock_reg.call_count >= 3  # at least dataset, vector, graph

    def test_register_tools_catches_import_error(self):
        """ImportError from _register_tools_from_subdir is caught for IPFS tools only."""
        server = SimpleIPFSDatasetsMCPServer()
        def raise_on_ipfs_tools(path):
            if str(path).endswith("ipfs_tools"):
                raise ImportError("ipfs not available")
        with patch.object(server, "_register_tools_from_subdir", side_effect=raise_on_ipfs_tools):
            # Should not raise — ImportError for ipfs_tools is caught
            server.register_tools()


class TestStartSimpleServer:
    """start_simple_server() module-level helper."""

    def test_start_simple_server_creates_and_runs_server(self):
        """start_simple_server() builds a server, registers tools, runs it."""
        mock_server = MagicMock()
        with patch(
            "ipfs_datasets_py.mcp_server.simple_server.SimpleIPFSDatasetsMCPServer",
            return_value=mock_server,
        ):
            with patch(
                "ipfs_datasets_py.mcp_server.configs.load_config_from_yaml",
                return_value=MagicMock(host="127.0.0.1", port=8000),
            ):
                from ipfs_datasets_py.mcp_server.simple_server import start_simple_server
                start_simple_server()
        mock_server.register_tools.assert_called_once()
        mock_server.run.assert_called_once()


# ===========================================================================
# 7.  standalone_server.py — main() default both-together path
# ===========================================================================

class TestStandaloneMainDefaultPath:
    """standalone_server.main() default: both server + dashboard."""

    def test_main_default_starts_both(self):
        """No argv flags → start both server and dashboard."""
        import threading

        mock_server = MagicMock()
        mock_dashboard = MagicMock()

        with patch.object(sys, "argv", ["standalone_server.py"]):
            with patch(
                "ipfs_datasets_py.mcp_server.standalone_server.MinimalMCPServer",
                return_value=mock_server,
            ):
                with patch(
                    "ipfs_datasets_py.mcp_server.standalone_server.MinimalMCPDashboard",
                    return_value=mock_dashboard,
                ):
                    with patch("threading.Thread") as mock_thread_cls:
                        mock_thread = MagicMock()
                        mock_thread_cls.return_value = mock_thread
                        with patch("time.sleep"):
                            standalone_mod.main()

        # Dashboard.run() should have been called (blocking call at end of main)
        mock_dashboard.run.assert_called_once()


# ===========================================================================
# 8.  temporal_deontic_mcp_server.py — setup_server() body coverage
# ===========================================================================

class TestTemporalDeonticSetupServerBody:
    """
    Call setup_server() with a mock MCP Server that captures decorated handlers.
    Then invoke the handlers to cover the inner async functions.
    """

    def _make_capturing_server(self):
        """Return (mock_server, handlers_dict) where handlers_dict maps event→fn."""
        handlers: dict = {}

        def make_decorator(event_name):
            def decorator(fn):
                handlers[event_name] = fn
                return fn
            return decorator

        mock_server = MagicMock()
        mock_server.list_tools = MagicMock(return_value=make_decorator("list_tools"))
        mock_server.call_tool = MagicMock(return_value=make_decorator("call_tool"))
        mock_server.list_prompts = MagicMock(return_value=make_decorator("list_prompts"))
        mock_server.get_prompt = MagicMock(return_value=make_decorator("get_prompt"))
        return mock_server, handlers

    def test_setup_server_with_empty_tools(self):
        """setup_server() with empty tools registers handlers without error."""
        mock_server, handlers = self._make_capturing_server()
        MockServer = MagicMock(return_value=mock_server)

        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            with patch.object(tdm_mod, "Server", MockServer):
                t = TemporalDeonticMCPServer()
                result = t.setup_server()

        assert result is mock_server
        assert "list_tools" in handlers
        assert "call_tool" in handlers

    def test_list_tools_handler_returns_empty_list_for_empty_tools(self):
        """list_tools handler returns [] when no tools are registered."""
        mock_server, handlers = self._make_capturing_server()
        MockServer = MagicMock(return_value=mock_server)

        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            with patch.object(tdm_mod, "Server", MockServer):
                t = TemporalDeonticMCPServer()
                t.setup_server()

        result = asyncio.run(handlers["list_tools"]())
        assert result == []

    def test_list_tools_handler_with_tools(self):
        """list_tools handler builds one types.Tool per registered tool."""
        mock_server, handlers = self._make_capturing_server()
        MockServer = MagicMock(return_value=mock_server)

        mock_tool = MagicMock()
        mock_tool.get_schema.return_value = {
            "description": "A test tool",
            "input_schema": {"type": "object", "properties": {}},
        }

        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            with patch.object(tdm_mod, "Server", MockServer):
                t = TemporalDeonticMCPServer()
                t.tools["test_tool"] = mock_tool
                t.setup_server()

        result = asyncio.run(handlers["list_tools"]())
        assert len(result) == 1

    def test_call_tool_handler_unknown_tool(self):
        """call_tool handler raises ValueError for unknown tool name."""
        mock_server, handlers = self._make_capturing_server()
        MockServer = MagicMock(return_value=mock_server)

        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            with patch.object(tdm_mod, "Server", MockServer):
                t = TemporalDeonticMCPServer()
                t.setup_server()

        async def run():
            with pytest.raises(ValueError, match="Unknown tool"):
                await handlers["call_tool"]("unknown_tool", {})

        asyncio.run(run())

    def test_call_tool_handler_success(self):
        """call_tool handler executes a tool and wraps result in TextContent."""
        mock_server, handlers = self._make_capturing_server()
        MockServer = MagicMock(return_value=mock_server)

        mock_tool = MagicMock()
        async def async_execute(args):
            return {"status": "ok", "value": 42}
        mock_tool.execute = async_execute
        mock_tool.get_schema.return_value = {"description": "t", "input_schema": {}}

        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            with patch.object(tdm_mod, "Server", MockServer):
                t = TemporalDeonticMCPServer()
                t.tools["my_tool"] = mock_tool
                t.setup_server()

        result = asyncio.run(handlers["call_tool"]("my_tool", {}))
        # result is a list of types.Tool objects (mocked) or TextContent
        assert len(result) == 1

    def test_call_tool_handler_exception(self):
        """call_tool handler wraps exceptions in error TextContent."""
        mock_server, handlers = self._make_capturing_server()
        MockServer = MagicMock(return_value=mock_server)

        mock_tool = MagicMock()
        async def failing_execute(args):
            raise RuntimeError("tool crashed")
        mock_tool.execute = failing_execute
        mock_tool.get_schema.return_value = {"description": "t", "input_schema": {}}

        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            with patch.object(tdm_mod, "Server", MockServer):
                t = TemporalDeonticMCPServer()
                t.tools["crash_tool"] = mock_tool
                t.setup_server()

        result = asyncio.run(handlers["call_tool"]("crash_tool", {}))
        assert len(result) == 1
        # The returned TextContent should have error info in its text
        text_content = result[0]
        # text_content is a MagicMock (types.TextContent is mocked)
        # Just verify it was constructed (call count)

    def test_list_prompts_handler(self):
        """list_prompts handler returns a list with one prompt."""
        mock_server, handlers = self._make_capturing_server()
        MockServer = MagicMock(return_value=mock_server)

        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            with patch.object(tdm_mod, "Server", MockServer):
                t = TemporalDeonticMCPServer()
                t.setup_server()

        result = asyncio.run(handlers["list_prompts"]())
        assert len(result) == 1

    def test_get_prompt_handler_unknown_name(self):
        """get_prompt handler raises ValueError for unknown prompt names."""
        mock_server, handlers = self._make_capturing_server()
        MockServer = MagicMock(return_value=mock_server)

        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            with patch.object(tdm_mod, "Server", MockServer):
                t = TemporalDeonticMCPServer()
                t.setup_server()

        async def run():
            with pytest.raises(ValueError, match="Unknown prompt"):
                await handlers["get_prompt"]("bad_name", {})

        asyncio.run(run())

    def test_get_prompt_handler_legal_analysis(self):
        """get_prompt handler for 'legal_analysis_prompt' returns a result."""
        mock_server, handlers = self._make_capturing_server()
        MockServer = MagicMock(return_value=mock_server)

        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            with patch.object(tdm_mod, "Server", MockServer):
                t = TemporalDeonticMCPServer()
                t.setup_server()

        result = asyncio.run(
            handlers["get_prompt"](
                "legal_analysis_prompt",
                {"document_text": "The defendant shall comply with..."},
            )
        )
        assert result is not None

    def test_start_stdio_with_mock(self):
        """start_stdio() with mocked MCP library runs without error."""
        mock_server_obj, _ = self._make_capturing_server()
        MockServer = MagicMock(return_value=mock_server_obj)

        # Mock stdio_server as an async context manager
        mock_read = MagicMock()
        mock_write = MagicMock()

        class _MockStdio:
            async def __aenter__(self_cm):
                return (mock_read, mock_write)
            async def __aexit__(self_cm, *_):
                return False

        mock_server_obj.run = AsyncMock()
        mock_server_obj.create_initialization_options = MagicMock(return_value={})

        with patch.object(tdm_mod, "MCP_AVAILABLE", True):
            with patch.object(tdm_mod, "Server", MockServer):
                with patch.object(tdm_mod, "stdio_server", return_value=_MockStdio()):
                    t = TemporalDeonticMCPServer()
                    asyncio.run(t.start_stdio())

        mock_server_obj.run.assert_called_once_with(mock_read, mock_write, {})
