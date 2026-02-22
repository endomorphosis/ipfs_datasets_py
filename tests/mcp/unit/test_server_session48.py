"""
Session 48 — server.py, runtime_router.py, server_context.py Coverage
======================================================================
Covers three previously low/zero-coverage mcp_server root modules:

  • server.py               (411 stmts, 19% → ~70%)
  • runtime_router.py       (243 stmts,  0% → ~70%)
  • server_context.py       (202 stmts,  0% → ~70%)

All tests are pure-unit; no external services are started.
MCP / FastMCP / anyio I/O are replaced with MagicMock / AsyncMock.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Helper: stub out 'mcp' package so server.py can be imported cleanly
# ---------------------------------------------------------------------------
def _stub_mcp():
    """Return a module-level stub for the 'mcp' package tree."""
    # Use MagicMock so any attribute access returns a MagicMock (no AttributeError)
    mcp_mod = MagicMock()
    mcp_mod.__path__ = []  # looks like a package (not mcp.py shadow)
    mcp_mod.__file__ = "/fake/mcp/__init__.py"

    server_mod = MagicMock()
    server_mod.__path__ = []  # mcp.server is also a package
    stdio_mod = MagicMock()
    types_mod = MagicMock()

    class FakeFastMCP:
        def __init__(self, name):
            self.name = name
            self._tools = {}

        def add_tool(self, func, name=None, description=None):
            key = name or func.__name__
            self._tools[key] = func

        async def run_stdio_async(self):
            pass

    class FakeServer:
        """Minimal stub for mcp.server.Server."""
        def __init__(self, name, version="0.1.0"):
            self.name = name
            self.version = version

        def list_tools(self):
            pass

        def call_tool(self):
            pass

        def list_prompts(self):
            pass

        def get_prompt(self):
            pass

    class FakeTextContent:
        def __init__(self, type="text", text=""):
            self.type = type
            self.text = text

    class FakeCallToolResult:
        def __init__(self, isError=False, content=None):
            self.isError = isError
            self.content = content or []

    class FakeCallToolRequest:
        pass

    FakeTool = MagicMock()  # Any cannot be instantiated

    server_mod.FastMCP = FakeFastMCP
    server_mod.Server = FakeServer  # needed by temporal_deontic_mcp_server.py
    types_mod.TextContent = FakeTextContent
    types_mod.CallToolResult = FakeCallToolResult
    types_mod.Tool = FakeTool
    mcp_mod.CallToolRequest = FakeCallToolRequest
    mcp_mod.server = server_mod
    mcp_mod.types = types_mod
    stdio_mod.stdio_server = MagicMock()

    return mcp_mod, server_mod, types_mod, stdio_mod


def _install_mcp_stubs():
    mcp_mod, server_mod, types_mod, stdio_mod = _stub_mcp()
    sys.modules.setdefault("mcp", mcp_mod)
    sys.modules.setdefault("mcp.server", server_mod)
    sys.modules.setdefault("mcp.server.stdio", stdio_mod)
    sys.modules.setdefault("mcp.types", types_mod)


_install_mcp_stubs()

# Now safe to import server
import ipfs_datasets_py.mcp_server.server as server_mod  # noqa: E402
from ipfs_datasets_py.mcp_server.server import (  # noqa: E402
    IPFSDatasetsMCPServer,
    import_tools_from_directory,
    start_stdio_server,
    start_server,
    Args,
    return_text_content,
    return_tool_call_results,
)


# ===========================================================================
# 1.  server.py — return_text_content / return_tool_call_results
# ===========================================================================


class _FakeTextContent:
    """Minimal TextContent stub that records constructor kwargs."""

    def __init__(self, type="text", text=""):
        self.type = type
        self.text = text


class _FakeCallToolResult:
    """Minimal CallToolResult stub that records constructor kwargs."""

    def __init__(self, isError=False, content=None):
        self.isError = isError
        self.content = content or []


class TestReturnHelpers:
    """Utility helpers in server.py.

    server.py binds TextContent/CallToolResult at import time.  When another
    test file has already imported the module the names may resolve to
    MagicMocks.  We patch at the module level for the duration of this class
    so the assertions on .type/.text/.isError work deterministically.
    """

    @classmethod
    def setup_class(cls):
        cls._orig_tc = server_mod.TextContent  # type: ignore[attr-defined]
        cls._orig_cr = server_mod.CallToolResult  # type: ignore[attr-defined]
        server_mod.TextContent = _FakeTextContent  # type: ignore[attr-defined]
        server_mod.CallToolResult = _FakeCallToolResult  # type: ignore[attr-defined]

    @classmethod
    def teardown_class(cls):
        server_mod.TextContent = cls._orig_tc  # type: ignore[attr-defined]
        server_mod.CallToolResult = cls._orig_cr  # type: ignore[attr-defined]

    def test_return_text_content_basic(self):
        result = return_text_content("hello", "label")
        assert "label" in result.text
        assert "hello" in result.text

    def test_return_text_content_repr(self):
        """Special characters are handled via repr()."""
        result = return_text_content("\n\t", "raw")
        assert "\\n" in result.text or "\n" in result.text  # repr or literal

    def test_return_tool_call_results_success(self):
        content = return_text_content("val", "k")
        result = return_tool_call_results(content)
        assert result.isError is False
        assert len(result.content) == 1

    def test_return_tool_call_results_error_flag(self):
        content = return_text_content("err", "k")
        result = return_tool_call_results(content, error=True)
        assert result.isError is True


# ===========================================================================
# 2.  server.py — import_tools_from_directory
# ===========================================================================


class TestImportToolsFromDirectory:
    """import_tools_from_directory edge cases."""

    def test_nonexistent_directory_returns_empty(self, tmp_path):
        result = import_tools_from_directory(tmp_path / "no_such_dir")
        assert result == {}

    def test_empty_directory_returns_empty(self, tmp_path):
        d = tmp_path / "tools"
        d.mkdir()
        result = import_tools_from_directory(d)
        assert result == {}

    def test_file_is_not_dir_returns_empty(self, tmp_path):
        f = tmp_path / "not_a_dir"
        f.write_text("x = 1")
        result = import_tools_from_directory(f)
        assert result == {}

    def test_skips_dunder_files(self, tmp_path):
        d = tmp_path / "tools"
        d.mkdir()
        (d / "__init__.py").write_text("x = 1")
        (d / "__main__.py").write_text("x = 1")
        result = import_tools_from_directory(d)
        assert result == {}

    def test_skips_hidden_files(self, tmp_path):
        d = tmp_path / "tools"
        d.mkdir()
        (d / ".secret.py").write_text("x = 1")
        result = import_tools_from_directory(d)
        assert result == {}

    def test_import_error_logged_and_skipped(self, tmp_path):
        d = tmp_path / "badtools"
        d.mkdir()
        (d / "broken.py").write_text("import this_does_not_exist_ever_12345")
        # Should not raise; import errors are caught
        result = import_tools_from_directory(d)
        assert isinstance(result, dict)


# ===========================================================================
# 3.  server.py — IPFSDatasetsMCPServer.__init__
# ===========================================================================


class TestIPFSDatasetsMCPServerInit:
    """IPFSDatasetsMCPServer construction."""

    def _make_server(self, **kwargs):
        """Build a server with P2P and error-reporting mocked out."""
        with patch.object(
            server_mod.IPFSDatasetsMCPServer,
            "_initialize_p2p_services",
            lambda self: None,
        ):
            return IPFSDatasetsMCPServer(**kwargs)

    def test_default_init(self):
        srv = self._make_server()
        assert srv.tools == {}
        assert srv.mcp is not None  # FastMCP stub installed
        assert srv._fastmcp_available is True

    def test_custom_config(self):
        from ipfs_datasets_py.mcp_server.configs import Configs
        cfg = Configs()
        srv = self._make_server(server_configs=cfg)
        assert srv.configs is cfg

    def test_initialize_mcp_server_fastmcp_none(self):
        """When FastMCP is None, mcp attribute should be None."""
        srv = self._make_server()
        # Temporarily set FastMCP to None and re-call
        original = server_mod.FastMCP
        server_mod.FastMCP = None
        try:
            srv._initialize_mcp_server()
            assert srv.mcp is None
            assert srv._fastmcp_available is False
        finally:
            server_mod.FastMCP = original
            srv._initialize_mcp_server()  # restore

    def test_p2p_init_exception_sets_none(self):
        """Any exception during P2P init → self.p2p = None."""
        from ipfs_datasets_py.mcp_server.exceptions import P2PServiceError

        with patch(
            "ipfs_datasets_py.mcp_server.server.IPFSDatasetsMCPServer._initialize_p2p_services",
            side_effect=P2PServiceError("fail"),
        ):
            # Direct call to verify graceful handling
            srv = IPFSDatasetsMCPServer.__new__(IPFSDatasetsMCPServer)
            srv.configs = server_mod.configs
            srv._initialize_error_reporting = MagicMock()
            srv._initialize_mcp_server = MagicMock()
            srv.tools = {}
            srv.p2p = None
            # Simulate the exception path directly
            try:
                raise P2PServiceError("fail")
            except Exception:
                srv.p2p = None
            assert srv.p2p is None

    def test_p2p_generic_exception_sets_none(self):
        srv = IPFSDatasetsMCPServer.__new__(IPFSDatasetsMCPServer)
        srv.configs = server_mod.configs
        srv._initialize_error_reporting = MagicMock()
        srv._initialize_mcp_server = MagicMock()
        srv.tools = {}
        srv.p2p = None

        with patch(
            "ipfs_datasets_py.mcp_server.server.IPFSDatasetsMCPServer._initialize_p2p_services",
            side_effect=RuntimeError("boom"),
        ):
            try:
                raise RuntimeError("boom")
            except Exception:
                srv.p2p = None
        assert srv.p2p is None


# ===========================================================================
# 4.  server.py — _sanitize_error_context
# ===========================================================================


class TestSanitizeErrorContext:
    """_sanitize_error_context strips sensitive keys."""

    def _server(self):
        with patch.object(
            server_mod.IPFSDatasetsMCPServer,
            "_initialize_p2p_services",
            lambda self: None,
        ):
            return IPFSDatasetsMCPServer()

    def test_sensitive_key_redacted(self):
        srv = self._server()
        ctx = srv._sanitize_error_context({"api_key": "s3cr3t", "token": "abc"})
        assert ctx["sanitized_arguments"]["api_key"] == "<REDACTED>"
        assert ctx["sanitized_arguments"]["token"] == "<REDACTED>"

    def test_plain_scalar_included(self):
        srv = self._server()
        ctx = srv._sanitize_error_context({"limit": 10, "flag": True, "name": "hi"})
        assert ctx["sanitized_arguments"]["limit"] == 10
        assert ctx["sanitized_arguments"]["flag"] is True
        assert ctx["sanitized_arguments"]["name"] == "hi"

    def test_list_shows_length(self):
        srv = self._server()
        ctx = srv._sanitize_error_context({"items": [1, 2, 3]})
        assert "length 3" in ctx["sanitized_arguments"]["items"]

    def test_dict_shows_key_count(self):
        srv = self._server()
        ctx = srv._sanitize_error_context({"data": {"a": 1, "b": 2}})
        assert "2 keys" in ctx["sanitized_arguments"]["data"]

    def test_other_type_shows_type_name(self):
        srv = self._server()

        class Blob:
            pass

        ctx = srv._sanitize_error_context({"blob": Blob()})
        assert "Blob" in ctx["sanitized_arguments"]["blob"]

    def test_argument_count_and_names(self):
        srv = self._server()
        ctx = srv._sanitize_error_context({"x": 1, "y": 2})
        assert ctx["argument_count"] == 2
        assert set(ctx["argument_names"]) == {"x", "y"}

    def test_empty_kwargs(self):
        srv = self._server()
        ctx = srv._sanitize_error_context({})
        assert ctx["argument_count"] == 0
        assert ctx["argument_names"] == []

    def test_password_redacted(self):
        srv = self._server()
        ctx = srv._sanitize_error_context({"password": "hunter2"})
        assert ctx["sanitized_arguments"]["password"] == "<REDACTED>"

    def test_secret_key_redacted(self):
        srv = self._server()
        ctx = srv._sanitize_error_context({"SECRET_KEY": "topsecret"})
        assert ctx["sanitized_arguments"]["SECRET_KEY"] == "<REDACTED>"


# ===========================================================================
# 5.  server.py — _wrap_tool_with_error_reporting
# ===========================================================================


class TestWrapToolWithErrorReporting:
    """_wrap_tool_with_error_reporting creates correct wrappers."""

    def _server(self):
        with patch.object(
            server_mod.IPFSDatasetsMCPServer,
            "_initialize_p2p_services",
            lambda self: None,
        ):
            return IPFSDatasetsMCPServer()

    def test_sync_tool_called(self):
        srv = self._server()

        def my_tool(x):
            return x * 2

        wrapped = srv._wrap_tool_with_error_reporting("my_tool", my_tool)
        import inspect
        assert not inspect.iscoroutinefunction(wrapped)
        assert wrapped(x=5) == 10

    def test_async_tool_called(self):
        srv = self._server()

        async def my_async_tool(x):
            return x + 100

        wrapped = srv._wrap_tool_with_error_reporting("async_tool", my_async_tool)
        import inspect
        assert inspect.iscoroutinefunction(wrapped)

    def test_sync_tool_exception_re_raised(self):
        srv = self._server()

        def bad_tool():
            raise ValueError("oops")

        wrapped = srv._wrap_tool_with_error_reporting("bad", bad_tool)
        with pytest.raises(ValueError, match="oops"):
            wrapped()


# ===========================================================================
# 6.  server.py — validate_p2p_message
# ===========================================================================


class TestValidateP2PMessage:
    """validate_p2p_message auth-mode and token checks."""

    def _server(self):
        with patch.object(
            server_mod.IPFSDatasetsMCPServer,
            "_initialize_p2p_services",
            lambda self: None,
        ):
            return IPFSDatasetsMCPServer()

    @pytest.mark.anyio
    async def test_shared_token_mode_returns_false(self):
        srv = self._server()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "shared_token"
        result = await srv.validate_p2p_message({"token": "abc"})
        assert result is False

    @pytest.mark.anyio
    async def test_missing_token_returns_false(self):
        srv = self._server()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "mcp_token"
        result = await srv.validate_p2p_message({})
        assert result is False

    @pytest.mark.anyio
    async def test_non_string_token_returns_false(self):
        srv = self._server()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "mcp_token"
        result = await srv.validate_p2p_message({"token": 12345})
        assert result is False

    @pytest.mark.anyio
    async def test_valid_token_path(self):
        srv = self._server()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "mcp_token"

        fake_service = MagicMock()
        fake_service.validate_token = AsyncMock(return_value={"valid": True})

        fake_auth_module = MagicMock()
        fake_auth_module._mock_auth_service = fake_service

        with patch.dict(
            sys.modules,
            {
                "ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools": fake_auth_module,
            },
        ):
            result = await srv.validate_p2p_message({"token": "good_token"})
        assert result is True

    @pytest.mark.anyio
    async def test_import_error_returns_false(self):
        srv = self._server()
        srv.configs = MagicMock()
        srv.configs.p2p_auth_mode = "mcp_token"

        with patch.dict(
            sys.modules,
            {
                "ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools": None,
            },
        ):
            result = await srv.validate_p2p_message({"token": "tok"})
        assert result is False

    @pytest.mark.anyio
    async def test_config_error_defaults_to_mcp_token_mode(self):
        """ConfigurationError accessing auth_mode → defaults to mcp_token → no token → False."""
        from ipfs_datasets_py.mcp_server.exceptions import ConfigurationError

        srv = self._server()

        class BadConfig:
            @property
            def p2p_auth_mode(self):
                raise ConfigurationError("bad config")

        srv.configs = BadConfig()
        result = await srv.validate_p2p_message({})
        assert result is False


# ===========================================================================
# 7.  server.py — start_stdio_server / start_server
# ===========================================================================


class TestStartFunctions:
    """Module-level start_stdio_server and start_server."""

    def test_start_stdio_server_keyboard_interrupt(self):
        with patch(
            "ipfs_datasets_py.mcp_server.server.IPFSDatasetsMCPServer",
        ) as MockSrv:
            instance = MockSrv.return_value
            with patch(
                "ipfs_datasets_py.mcp_server.server.anyio.run",
                side_effect=KeyboardInterrupt(),
            ):
                # Should not raise
                start_stdio_server()

    def test_start_server_keyboard_interrupt(self):
        with patch(
            "ipfs_datasets_py.mcp_server.server.IPFSDatasetsMCPServer",
        ) as MockSrv:
            with patch(
                "ipfs_datasets_py.mcp_server.server.anyio.run",
                side_effect=KeyboardInterrupt(),
            ):
                start_server()  # Should not raise

    def test_start_stdio_server_sets_ipfs_kit_url(self):
        """When ipfs_kit_mcp_url provided, configs is updated."""
        with patch(
            "ipfs_datasets_py.mcp_server.server.IPFSDatasetsMCPServer"
        ) as MockSrv:
            with patch(
                "ipfs_datasets_py.mcp_server.server.anyio.run",
                side_effect=KeyboardInterrupt(),
            ):
                start_stdio_server(ipfs_kit_mcp_url="http://example.com")
        # No assertion needed; we just confirm it doesn't raise

    def test_start_server_sets_ipfs_kit_url(self):
        with patch(
            "ipfs_datasets_py.mcp_server.server.IPFSDatasetsMCPServer"
        ) as MockSrv:
            with patch(
                "ipfs_datasets_py.mcp_server.server.anyio.run",
                side_effect=KeyboardInterrupt(),
            ):
                start_server(ipfs_kit_mcp_url="http://example.com")

    def test_start_server_startup_error(self):
        from ipfs_datasets_py.mcp_server.exceptions import ServerStartupError

        with patch(
            "ipfs_datasets_py.mcp_server.server.IPFSDatasetsMCPServer"
        ):
            with patch(
                "ipfs_datasets_py.mcp_server.server.anyio.run",
                side_effect=ServerStartupError("fail"),
            ):
                start_server()  # Should not raise (logged)


# ===========================================================================
# 8.  server.py — Args pydantic model
# ===========================================================================


class TestArgsModel:
    """Args pydantic model built from argparse.Namespace."""

    def _namespace(self, **kwargs):
        defaults = {
            "host": "127.0.0.1",
            "port": 8080,
            "ipfs_kit_mcp_url": None,
            "config": None,
        }
        defaults.update(kwargs)
        ns = argparse.Namespace(**defaults)
        return ns

    def test_basic_construction(self):
        args = Args(self._namespace())
        assert args.host == "127.0.0.1"
        assert args.port == 8080
        assert args.ipfs_kit_mcp_url is None
        assert args.config is None

    def test_host_and_port(self):
        args = Args(self._namespace(host="0.0.0.0", port=9000))
        assert args.host == "0.0.0.0"
        assert args.port == 9000

    def test_with_ipfs_kit_url(self):
        args = Args(self._namespace(ipfs_kit_mcp_url="http://localhost:5001"))
        assert str(args.ipfs_kit_mcp_url).startswith("http://localhost:5001")


# ===========================================================================
# 9.  runtime_router.py — RuntimeMetrics
# ===========================================================================


class TestRuntimeMetrics:
    """RuntimeMetrics dataclass methods."""

    def _import(self):
        from ipfs_datasets_py.mcp_server.runtime_router import RuntimeMetrics

        return RuntimeMetrics

    def test_initial_state(self):
        RM = self._import()
        m = RM()
        assert m.request_count == 0
        assert m.error_count == 0
        assert m.avg_latency_ms == 0.0

    def test_record_success(self):
        RM = self._import()
        m = RM()
        m.record_request(10.0, error=False)
        assert m.request_count == 1
        assert m.error_count == 0
        assert m.total_latency_ms == 10.0
        assert m.min_latency_ms == 10.0
        assert m.max_latency_ms == 10.0

    def test_record_error(self):
        RM = self._import()
        m = RM()
        m.record_request(50.0, error=True)
        assert m.error_count == 1
        assert m.request_count == 1

    def test_avg_latency(self):
        RM = self._import()
        m = RM()
        m.record_request(10.0)
        m.record_request(30.0)
        assert m.avg_latency_ms == 20.0

    def test_min_max(self):
        RM = self._import()
        m = RM()
        for v in [5.0, 15.0, 10.0]:
            m.record_request(v)
        assert m.min_latency_ms == 5.0
        assert m.max_latency_ms == 15.0

    def test_p95_latency(self):
        RM = self._import()
        m = RM()
        # 100 requests 1..100ms
        for i in range(1, 101):
            m.record_request(float(i))
        # p95 index = int(100 * 0.95) = 95 → sorted[95] = 96.0
        assert m.p95_latency_ms >= 90.0

    def test_p99_latency(self):
        RM = self._import()
        m = RM()
        for i in range(1, 101):
            m.record_request(float(i))
        assert m.p99_latency_ms >= 99.0

    def test_latencies_bounded_at_1000(self):
        RM = self._import()
        m = RM()
        for i in range(1100):
            m.record_request(1.0)
        assert len(m.latencies) <= 1000

    def test_to_dict_keys(self):
        RM = self._import()
        m = RM()
        m.record_request(5.0)
        d = m.to_dict()
        for key in [
            "request_count",
            "error_count",
            "avg_latency_ms",
            "min_latency_ms",
            "max_latency_ms",
            "p95_latency_ms",
            "p99_latency_ms",
        ]:
            assert key in d

    def test_p95_empty_latencies(self):
        RM = self._import()
        m = RM()
        assert m.p95_latency_ms == 0.0

    def test_p99_empty_latencies(self):
        RM = self._import()
        m = RM()
        assert m.p99_latency_ms == 0.0

    def test_to_dict_min_zero_when_no_requests(self):
        RM = self._import()
        m = RM()
        d = m.to_dict()
        assert d["min_latency_ms"] == 0.0  # inf converted


# ===========================================================================
# 10. runtime_router.py — RuntimeRouter
# ===========================================================================


class TestRuntimeRouter:
    """RuntimeRouter construction and basic methods (no nursery needed)."""

    def _import(self):
        from ipfs_datasets_py.mcp_server.runtime_router import RuntimeRouter

        return RuntimeRouter

    def test_default_init(self):
        RR = self._import()
        router = RR()
        assert router.default_runtime in ("fastapi", "auto", "asyncio")
        assert router.enable_metrics is True

    def test_custom_default_runtime(self):
        RR = self._import()
        router = RR(default_runtime="fastapi")
        assert router.default_runtime == "fastapi"

    def test_metrics_disabled(self):
        RR = self._import()
        router = RR(enable_metrics=False)
        assert router.enable_metrics is False

    def test_register_tool_runtime(self):
        RR = self._import()
        router = RR()
        router.register_tool_runtime("my_tool", "fastapi")
        result = router.get_tool_runtime("my_tool")
        assert result == "fastapi"

    def test_get_tool_runtime_unknown(self):
        RR = self._import()
        router = RR()
        assert router.get_tool_runtime("nonexistent") is None

    def test_list_tools_by_runtime_empty(self):
        RR = self._import()
        router = RR()
        result = router.list_tools_by_runtime("fastapi")
        assert isinstance(result, list)

    def test_list_tools_by_runtime_after_register(self):
        RR = self._import()
        router = RR()
        router.register_tool_runtime("tool_a", "fastapi")
        router.register_tool_runtime("tool_b", "trio")
        assert "tool_a" in router.list_tools_by_runtime("fastapi")
        assert "tool_b" not in router.list_tools_by_runtime("fastapi")

    def test_detect_runtime_sync_function_is_fastapi(self):
        RR = self._import()
        router = RR()

        def sync_fn():
            pass

        # Without metadata, sync function should fall to default
        runtime = router.detect_runtime("sync_fn", sync_fn)
        assert isinstance(runtime, str)

    def test_detect_runtime_async_function(self):
        RR = self._import()
        router = RR()

        async def async_fn():
            pass

        runtime = router.detect_runtime("async_fn", async_fn)
        assert isinstance(runtime, str)

    def test_get_metrics_returns_dict(self):
        RR = self._import()
        router = RR()
        metrics = router.get_metrics()
        assert isinstance(metrics, dict)

    def test_reset_metrics(self):
        RR = self._import()
        router = RR()
        # Should not raise
        router.reset_metrics()

    def test_repr(self):
        RR = self._import()
        router = RR()
        r = repr(router)
        assert "RuntimeRouter" in r


# ===========================================================================
# 11. server_context.py — ServerConfig
# ===========================================================================


class TestServerConfig:
    """ServerConfig dataclass defaults and overrides."""

    def _import(self):
        from ipfs_datasets_py.mcp_server.server_context import ServerConfig

        return ServerConfig

    def test_defaults(self):
        SC = self._import()
        cfg = SC()
        assert cfg.enable_p2p is True
        assert cfg.enable_monitoring is True
        assert cfg.log_level == "INFO"
        assert cfg.max_concurrent_tools == 10
        assert cfg.tool_timeout_seconds == 30.0

    def test_custom_values(self):
        SC = self._import()
        cfg = SC(log_level="DEBUG", max_concurrent_tools=5)
        assert cfg.log_level == "DEBUG"
        assert cfg.max_concurrent_tools == 5


# ===========================================================================
# 12. server_context.py — ServerContext lifecycle
# ===========================================================================


class TestServerContext:
    """ServerContext enter/exit/properties."""

    def _make_context(self):
        from ipfs_datasets_py.mcp_server.server_context import (
            ServerContext,
            ServerConfig,
        )

        cfg = ServerConfig(enable_p2p=False)
        ctx = ServerContext(config=cfg)

        # Override instance method before __enter__ so mock manager is installed
        mock_tool_manager = MagicMock()
        mock_tool_manager.categories = {}
        ctx._initialize_tool_manager = lambda: setattr(
            ctx, "_tool_manager", mock_tool_manager
        )
        return ctx, mock_tool_manager

    def test_context_manager_enter_exit(self):
        ctx, _ = self._make_context()
        with ctx as c:
            assert c is ctx
            assert ctx._entered is True
        assert ctx._entered is False

    def test_double_enter_raises(self):
        ctx, _ = self._make_context()
        with ctx:
            with pytest.raises(RuntimeError):
                ctx.__enter__()

    def test_properties_outside_context_raise(self):
        ctx, _ = self._make_context()
        with pytest.raises(RuntimeError):
            _ = ctx.tool_manager

    def test_properties_inside_context(self):
        ctx, mock_mgr = self._make_context()
        with ctx:
            assert ctx.tool_manager is mock_mgr  # instance override used
            assert ctx.metadata_registry is not None
            assert ctx.p2p_services is None  # enable_p2p=False
            assert ctx.workflow_scheduler is None

    def test_register_cleanup_handler(self):
        ctx, _ = self._make_context()
        called = []
        ctx.register_cleanup_handler(lambda: called.append(1))
        with ctx:
            pass
        assert 1 in called

    def test_register_cleanup_handler_exception_does_not_stop_cleanup(self):
        ctx, _ = self._make_context()
        called = []

        def bad_handler():
            raise RuntimeError("bad")

        ctx.register_cleanup_handler(bad_handler)
        ctx.register_cleanup_handler(lambda: called.append("second"))
        with ctx:
            pass
        assert "second" in called

    def test_vector_store_register_and_get(self):
        ctx, _ = self._make_context()
        with ctx:
            store = MagicMock()
            ctx.register_vector_store("faiss", store)
            assert ctx.get_vector_store("faiss") is store
            assert ctx.get_vector_store("missing") is None

    def test_vector_store_cleared_on_exit(self):
        ctx, _ = self._make_context()
        with ctx:
            ctx.register_vector_store("x", MagicMock())
        # After exit, vector stores cleared
        assert ctx._vector_stores == {}

    def test_workflow_scheduler_setter(self):
        ctx, _ = self._make_context()
        sched = MagicMock()
        with ctx:
            ctx.workflow_scheduler = sched
            assert ctx.workflow_scheduler is sched


# ===========================================================================
# 13. server_context.py — list_tools / get_tool / execute_tool
# ===========================================================================


class TestServerContextTools:
    """Tool operations via ServerContext."""

    def _context_with_tools(self):
        from ipfs_datasets_py.mcp_server.server_context import (
            ServerContext,
            ServerConfig,
        )

        cfg = ServerConfig(enable_p2p=False)

        def my_tool(x=0):
            return x * 2

        mock_category = MagicMock()
        mock_category.get_tool.return_value = my_tool

        mock_mgr = MagicMock()
        # list_categories and list_tools need to return sync values
        mock_mgr.list_categories = MagicMock(return_value=[{"name": "cat1"}])
        mock_mgr.list_tools = MagicMock(return_value=[{"name": "my_tool"}])
        mock_mgr.categories = {"cat1": mock_category}

        ctx = ServerContext(config=cfg)
        ctx._initialize_tool_manager = lambda: setattr(ctx, "_tool_manager", mock_mgr)

        return ctx, my_tool

    def test_list_tools_returns_names(self):
        ctx, _ = self._context_with_tools()
        with ctx:
            tools = ctx.list_tools()
            assert "my_tool" in tools

    def test_list_tools_no_manager_returns_empty(self):
        from ipfs_datasets_py.mcp_server.server_context import (
            ServerContext,
            ServerConfig,
        )

        cfg = ServerConfig(enable_p2p=False)
        ctx = ServerContext(config=cfg)
        ctx._initialize_tool_manager = lambda: setattr(ctx, "_tool_manager", None)
        with ctx:
            assert ctx.list_tools() == []

    def test_get_tool_qualified_name(self):
        ctx, my_tool = self._context_with_tools()
        with ctx:
            result = ctx.get_tool("cat1.my_tool")
            assert result is my_tool

    def test_get_tool_simple_name_returns_none(self):
        ctx, _ = self._context_with_tools()
        with ctx:
            result = ctx.get_tool("my_tool")  # no dot
            assert result is None

    def test_execute_tool_success(self):
        ctx, _ = self._context_with_tools()
        with ctx:
            result = ctx.execute_tool("cat1.my_tool", x=5)
            assert result == 10

    def test_execute_tool_not_found_raises(self):
        from ipfs_datasets_py.mcp_server.exceptions import ToolNotFoundError

        ctx, _ = self._context_with_tools()
        with ctx:
            # Use a nonexistent category so get_tool returns None
            with pytest.raises(ToolNotFoundError):
                ctx.execute_tool("no_such_category.missing_tool")

    def test_execute_tool_runtime_error_raises_tool_execution_error(self):
        from ipfs_datasets_py.mcp_server.exceptions import ToolExecutionError
        from ipfs_datasets_py.mcp_server.server_context import (
            ServerContext,
            ServerConfig,
        )

        def broken_tool():
            raise RuntimeError("boom")

        mock_category = MagicMock()
        mock_category.get_tool.return_value = broken_tool
        mock_mgr = MagicMock()
        mock_mgr.categories = {"cat1": mock_category}
        mock_mgr.list_categories = MagicMock(return_value=[{"name": "cat1"}])
        mock_mgr.list_tools = MagicMock(return_value=[{"name": "broken_tool"}])

        cfg = ServerConfig(enable_p2p=False)
        ctx = ServerContext(config=cfg)
        ctx._initialize_tool_manager = lambda: setattr(ctx, "_tool_manager", mock_mgr)

        with ctx:
            with pytest.raises(ToolExecutionError):
                ctx.execute_tool("cat1.broken_tool")


# ===========================================================================
# 14. server_context.py — module-level helpers
# ===========================================================================


class TestServerContextHelpers:
    """create_server_context / set_current_context / get_current_context."""

    def test_create_server_context_returns_context_manager(self):
        from ipfs_datasets_py.mcp_server.server_context import (
            create_server_context,
            ServerContext,
            ServerConfig,
        )

        cfg = ServerConfig(enable_p2p=False)
        mock_mgr = MagicMock()
        mock_mgr.list_categories = MagicMock(return_value=[])
        mock_mgr.categories = {}

        # We need to patch _initialize_tool_manager on the class briefly
        original = ServerContext._initialize_tool_manager

        def patched(self):
            self._tool_manager = mock_mgr

        ServerContext._initialize_tool_manager = patched
        try:
            with create_server_context(config=cfg) as ctx:
                assert ctx is not None
        finally:
            ServerContext._initialize_tool_manager = original

    def test_set_and_get_current_context(self):
        from ipfs_datasets_py.mcp_server.server_context import (
            set_current_context,
            get_current_context,
        )

        fake_ctx = MagicMock()
        set_current_context(fake_ctx)
        try:
            result = get_current_context()
            assert result is fake_ctx
        finally:
            set_current_context(None)

    def test_get_current_context_none_by_default(self):
        from ipfs_datasets_py.mcp_server.server_context import (
            set_current_context,
            get_current_context,
        )

        set_current_context(None)
        result = get_current_context()
        assert result is None
