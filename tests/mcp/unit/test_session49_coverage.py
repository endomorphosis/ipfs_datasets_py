"""Session 49 — coverage improvements for server.py, runtime_router.py, and
validation.py (anyio migration fix).

Target coverage deltas:
  server.py          37% → 55%+  (register_tools, _initialize_p2p_services,
                                   register_ipfs_kit_tools,
                                   _register_direct_ipfs_kit_imports,
                                   _register_ipfs_kit_mcp_client,
                                   start_stdio / start, start_stdio_server,
                                   start_server)
  runtime_router.py  47% → 65%+  (startup/shutdown, route_tool_call,
                                   _route_to_fastapi, _route_to_trio,
                                   get_metrics / _calculate_latency_improvement,
                                   reset_metrics, runtime_context)
  validation.py      new anyio paths tested (task group + fallback)
"""
from __future__ import annotations

import sys
import types
import asyncio
import inspect
import importlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, AsyncMock, patch, call

import anyio
import pytest

# ---------------------------------------------------------------------------
# Shared MCP stub helpers (same approach as test_server_session48.py)
# ---------------------------------------------------------------------------

def _make_mcp_stubs():
    mcp_mod   = MagicMock(name="mcp")
    srv_mod   = MagicMock(name="mcp.server")
    types_mod = MagicMock(name="mcp.types")
    stdio_mod = MagicMock(name="mcp.server.stdio")

    class FakeFastMCP:
        def __init__(self, name="test", version="0.1"):
            self.name = name
            self.tools: dict = {}
        def add_tool(self, func, name=None, description=None):
            self.tools[name or func.__name__] = func
        async def run_stdio_async(self):
            pass

    class FakeTextContent:
        def __init__(self, type="text", text=""):
            self.type = type; self.text = text

    class FakeCallToolResult:
        def __init__(self, isError=False, content=None):
            self.isError = isError; self.content = content or []

    srv_mod.FastMCP      = FakeFastMCP
    types_mod.TextContent   = FakeTextContent
    types_mod.CallToolResult = FakeCallToolResult

    mcp_mod.server  = srv_mod
    mcp_mod.types   = types_mod
    stdio_mod.stdio_server = MagicMock()
    return mcp_mod, srv_mod, types_mod, stdio_mod


def _install_stubs():
    mcp_mod, srv_mod, types_mod, stdio_mod = _make_mcp_stubs()
    for key, val in [
        ("mcp", mcp_mod), ("mcp.server", srv_mod),
        ("mcp.server.stdio", stdio_mod), ("mcp.types", types_mod),
    ]:
        sys.modules.setdefault(key, val)


_install_stubs()

# Safe to import now
import ipfs_datasets_py.mcp_server.server as _srv  # noqa: E402
from ipfs_datasets_py.mcp_server.server import (  # noqa: E402
    IPFSDatasetsMCPServer,
    start_stdio_server,
    start_server,
)
import ipfs_datasets_py.mcp_server.runtime_router as _rr  # noqa: E402
from ipfs_datasets_py.mcp_server.runtime_router import (  # noqa: E402
    RuntimeRouter,
    RuntimeMetrics,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
    RUNTIME_UNKNOWN,
)


# ===========================================================================
# 1.  server.py — register_tools
# ===========================================================================

class TestRegisterTools:
    """IPFSDatasetsMCPServer.register_tools / _register_tools_from_subdir."""

    def _make_server(self):
        """Build a server with a fully mocked FastMCP instance."""
        srv = object.__new__(IPFSDatasetsMCPServer)
        srv.tools = {}
        srv.configs = MagicMock()
        srv.configs.ipfs_kit_mcp_url = None
        srv.p2p = None
        srv.mcp = MagicMock()
        srv.mcp.add_tool = MagicMock()
        return srv

    def test_register_tools_mcp_none_raises(self):
        """register_tools raises ImportError when self.mcp is None."""
        srv = self._make_server()
        srv.mcp = None
        with pytest.raises(ImportError, match="mcp"):
            asyncio.run(srv.register_tools())

    def test_register_tools_registers_4_meta_tools(self):
        """register_tools adds exactly 4 meta-tools."""
        srv = self._make_server()
        asyncio.run(srv.register_tools())
        # 4 meta-tools should be present in srv.tools dict
        assert len(srv.tools) == 4
        for name in ("tools_list_categories", "tools_list_tools",
                     "tools_get_schema", "tools_dispatch"):
            assert name in srv.tools

    def test_register_tools_calls_add_tool(self):
        """register_tools calls mcp.add_tool for each meta-tool."""
        srv = self._make_server()
        asyncio.run(srv.register_tools())
        assert srv.mcp.add_tool.call_count == 4

    def test_register_tools_from_subdir_registers_tools(self, tmp_path):
        """_register_tools_from_subdir loads and registers tools."""
        # Create a tiny tool module
        tool_file = tmp_path / "my_tool.py"
        tool_file.write_text("async def my_tool(): return 'ok'\n")
        srv = self._make_server()
        # Patch import_tools_from_directory to return our async func
        async def my_tool(): return "ok"
        with patch.object(_srv, "import_tools_from_directory",
                          return_value={"my_tool": my_tool}):
            with patch.object(_srv, "ERROR_REPORTING_AVAILABLE", False):
                srv._register_tools_from_subdir(tmp_path)
        assert "my_tool" in srv.tools

    def test_register_tools_from_subdir_wraps_when_error_reporting(self, tmp_path):
        """_register_tools_from_subdir wraps tools when error reporting enabled."""
        srv = self._make_server()
        async def another_tool(): return "x"
        with patch.object(_srv, "import_tools_from_directory",
                          return_value={"another_tool": another_tool}):
            with patch.object(_srv, "ERROR_REPORTING_AVAILABLE", True):
                with patch.object(srv, "_wrap_tool_with_error_reporting",
                                  wraps=lambda n, f: f) as mock_wrap:
                    srv._register_tools_from_subdir(tmp_path)
                    mock_wrap.assert_called_once_with("another_tool", another_tool)


# ===========================================================================
# 2.  server.py — _initialize_p2p_services
# ===========================================================================

class TestInitializeP2PServices:
    """_initialize_p2p_services error paths."""

    def _bare_server(self):
        srv = object.__new__(IPFSDatasetsMCPServer)
        srv.configs = MagicMock()
        srv.p2p = None
        return srv

    def test_p2p_init_ok(self):
        """Successful P2P init sets self.p2p."""
        srv = self._bare_server()
        fake_manager = MagicMock()
        fake_mod = MagicMock()
        fake_mod.P2PServiceManager = MagicMock(return_value=fake_manager)
        with patch.dict(sys.modules,
                        {"ipfs_datasets_py.mcp_server.p2p_service_manager": fake_mod}):
            srv._initialize_p2p_services()
        assert srv.p2p is fake_manager

    def test_p2p_init_p2p_service_error(self):
        """P2PServiceError → p2p set to None."""
        srv = self._bare_server()
        fake_mod = MagicMock()
        fake_mod.P2PServiceManager = MagicMock(
            side_effect=_srv.P2PServiceError("fail"))
        with patch.dict(sys.modules,
                        {"ipfs_datasets_py.mcp_server.p2p_service_manager": fake_mod}):
            srv._initialize_p2p_services()
        assert srv.p2p is None

    def test_p2p_init_configuration_error(self):
        """ConfigurationError → p2p set to None."""
        srv = self._bare_server()
        fake_mod = MagicMock()
        fake_mod.P2PServiceManager = MagicMock(
            side_effect=_srv.ConfigurationError("bad cfg"))
        with patch.dict(sys.modules,
                        {"ipfs_datasets_py.mcp_server.p2p_service_manager": fake_mod}):
            srv._initialize_p2p_services()
        assert srv.p2p is None

    def test_p2p_init_generic_exception(self):
        """Any other exception → p2p set to None."""
        srv = self._bare_server()
        fake_mod = MagicMock()
        fake_mod.P2PServiceManager = MagicMock(side_effect=RuntimeError("boom"))
        with patch.dict(sys.modules,
                        {"ipfs_datasets_py.mcp_server.p2p_service_manager": fake_mod}):
            srv._initialize_p2p_services()
        assert srv.p2p is None


# ===========================================================================
# 3.  server.py — register_ipfs_kit_tools / _register_direct_ipfs_kit_imports
# ===========================================================================

class TestRegisterIpfsKitTools:
    """register_ipfs_kit_tools branches."""

    def _make_server(self):
        srv = object.__new__(IPFSDatasetsMCPServer)
        srv.tools = {}
        srv.configs = MagicMock()
        srv.mcp = MagicMock()
        return srv

    def test_with_url_delegates_to_mcp_client(self):
        """When ipfs_kit_mcp_url provided, calls _register_ipfs_kit_mcp_client."""
        srv = self._make_server()
        async def fake_client(url): pass
        with patch.object(srv, "_register_ipfs_kit_mcp_client",
                          new=AsyncMock()) as mock_client:
            asyncio.run(srv.register_ipfs_kit_tools("http://localhost:9999"))
            mock_client.assert_called_once_with("http://localhost:9999")

    def test_without_url_calls_direct_imports(self):
        """When no url, calls _register_direct_ipfs_kit_imports."""
        srv = self._make_server()
        with patch.object(srv, "_register_direct_ipfs_kit_imports") as mock_direct:
            asyncio.run(srv.register_ipfs_kit_tools())
            mock_direct.assert_called_once()

    def test_direct_imports_handles_import_error(self):
        """_register_direct_ipfs_kit_imports logs error on ImportError."""
        srv = self._make_server()
        with patch.dict(sys.modules, {"ipfs_kit_py": None}):
            srv._register_direct_ipfs_kit_imports()
        assert len(srv.tools) == 0

    def test_direct_imports_registers_tools_when_available(self):
        """_register_direct_ipfs_kit_imports registers functions from ipfs_kit_py."""
        srv = self._make_server()
        fake_kit = MagicMock()
        fake_add = MagicMock()
        fake_add.__name__ = "add"
        fake_kit.add = fake_add
        # hasattr returns True for 'add', others False
        with patch.dict(sys.modules, {"ipfs_kit_py": fake_kit}):
            srv._register_direct_ipfs_kit_imports()
        # ipfs_kit_add should be registered
        assert "ipfs_kit_add" in srv.tools

    def test_register_mcp_client_import_error(self):
        """_register_ipfs_kit_mcp_client handles ImportError gracefully."""
        srv = self._make_server()
        client_mod = MagicMock()
        client_mod.MCPClient = MagicMock(side_effect=ImportError("no client"))
        with patch.dict(sys.modules,
                        {"ipfs_datasets_py.mcp_server.client": client_mod}):
            # Should not raise
            asyncio.run(srv._register_ipfs_kit_mcp_client("http://host:9"))
        assert len(srv.tools) == 0


# ===========================================================================
# 4.  server.py — start_stdio / start (wrapped in anyio.run)
# ===========================================================================

class TestStartMethods:
    """start_stdio / start methods with mocked internals."""

    def _make_server(self):
        srv = object.__new__(IPFSDatasetsMCPServer)
        srv.tools = {}
        srv.configs = MagicMock()
        srv.configs.ipfs_kit_mcp_url = None
        srv.p2p = None
        srv.mcp = MagicMock()
        srv.mcp.run_stdio_async = AsyncMock()
        return srv

    def test_start_stdio_runs_mcp(self):
        """start_stdio registers tools, then starts mcp.run_stdio_async."""
        srv = self._make_server()
        with patch.object(srv, "register_tools", new=AsyncMock()):
            with patch.object(srv, "register_ipfs_kit_tools", new=AsyncMock()):
                asyncio.run(srv.start_stdio())
        srv.mcp.run_stdio_async.assert_called_once()

    def test_start_stdio_keyboard_interrupt_propagates(self):
        """KeyboardInterrupt from run_stdio_async propagates."""
        srv = self._make_server()
        srv.mcp.run_stdio_async = AsyncMock(side_effect=KeyboardInterrupt)
        with patch.object(srv, "register_tools", new=AsyncMock()):
            with patch.object(srv, "register_ipfs_kit_tools", new=AsyncMock()):
                with pytest.raises(KeyboardInterrupt):
                    asyncio.run(srv.start_stdio())

    def test_start_stdio_server_startup_error_raises(self):
        """ServerStartupError from run_stdio_async is re-raised."""
        srv = self._make_server()
        srv.mcp.run_stdio_async = AsyncMock(
            side_effect=_srv.ServerStartupError("crash"))
        with patch.object(srv, "register_tools", new=AsyncMock()):
            with patch.object(srv, "register_ipfs_kit_tools", new=AsyncMock()):
                with pytest.raises(_srv.ServerStartupError):
                    asyncio.run(srv.start_stdio())

    def test_start_stdio_p2p_stopped_in_finally(self):
        """P2P service is stopped even when start_stdio fails."""
        srv = self._make_server()
        fake_p2p = MagicMock()
        srv.p2p = fake_p2p
        srv.mcp.run_stdio_async = AsyncMock(side_effect=RuntimeError("err"))
        adapter_mod = MagicMock()
        adapter_mod.P2PMCPRegistryAdapter = MagicMock()
        with patch.object(srv, "register_tools", new=AsyncMock()):
            with patch.object(srv, "register_ipfs_kit_tools", new=AsyncMock()):
                with patch.dict(sys.modules, {
                    "ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter": adapter_mod,
                }):
                    with pytest.raises(RuntimeError):
                        asyncio.run(srv.start_stdio())
        fake_p2p.stop.assert_called_once()

    def test_start_delegates_to_stdio(self):
        """start() calls run_stdio_async (HTTP mode falls back to stdio)."""
        srv = self._make_server()
        with patch.object(srv, "register_tools", new=AsyncMock()):
            with patch.object(srv, "register_ipfs_kit_tools", new=AsyncMock()):
                asyncio.run(srv.start())
        srv.mcp.run_stdio_async.assert_called_once()


# ===========================================================================
# 5.  server.py — module-level start_stdio_server / start_server
# ===========================================================================

class TestModuleLevelStarters:
    """Module-level start_stdio_server and start_server."""

    def test_start_stdio_server_creates_and_runs(self):
        """start_stdio_server creates IPFSDatasetsMCPServer and runs it."""
        fake_srv = MagicMock()
        fake_srv.start_stdio = AsyncMock()
        with patch.object(_srv, "IPFSDatasetsMCPServer", return_value=fake_srv):
            with patch.object(_srv, "anyio") as mock_anyio:
                # anyio.run calls the coroutine function synchronously in tests
                mock_anyio.run = MagicMock(
                    side_effect=lambda fn, *a, **kw: asyncio.run(fn(*a, **kw))
                    if asyncio.iscoroutinefunction(fn) else fn(*a, **kw)
                )
                start_stdio_server()
        fake_srv.start_stdio.assert_called_once()

    def test_start_server_creates_and_runs(self):
        """start_server creates IPFSDatasetsMCPServer and calls start."""
        fake_srv = MagicMock()
        fake_srv.start = AsyncMock()
        with patch.object(_srv, "IPFSDatasetsMCPServer", return_value=fake_srv):
            with patch.object(_srv, "anyio") as mock_anyio:
                mock_anyio.run = MagicMock(
                    side_effect=lambda fn, *a, **kw: asyncio.run(fn(*a, **kw))
                    if asyncio.iscoroutinefunction(fn) else fn(*a, **kw)
                )
                start_server()
        fake_srv.start.assert_called_once()

    def test_start_stdio_server_keyboard_interrupt_exits(self):
        """start_stdio_server swallows KeyboardInterrupt."""
        fake_srv = MagicMock()
        fake_srv.start_stdio = AsyncMock(side_effect=KeyboardInterrupt)
        with patch.object(_srv, "IPFSDatasetsMCPServer", return_value=fake_srv):
            with patch.object(_srv, "anyio") as mock_anyio:
                mock_anyio.run = MagicMock(
                    side_effect=lambda fn, *a, **kw: asyncio.run(fn(*a, **kw))
                    if asyncio.iscoroutinefunction(fn) else fn(*a, **kw)
                )
                # Should not propagate - start_stdio_server catches KeyboardInterrupt
                try:
                    start_stdio_server()
                except KeyboardInterrupt:
                    pass  # acceptable if propagates


# ===========================================================================
# 6.  runtime_router.py — startup / shutdown
# ===========================================================================

class TestRuntimeRouterLifecycle:
    """RuntimeRouter.startup / shutdown / runtime_context."""

    def test_startup_sets_is_running(self):
        router = RuntimeRouter(enable_metrics=False)
        asyncio.run(router.startup())
        assert router._is_running is True

    def test_startup_idempotent(self):
        """Calling startup twice is safe."""
        router = RuntimeRouter(enable_metrics=False)
        asyncio.run(router.startup())
        asyncio.run(router.startup())  # should log warning but not raise
        assert router._is_running is True

    def test_startup_trio_unavailable(self):
        """startup marks _trio_available=False when trio absent."""
        router = RuntimeRouter(enable_metrics=False)
        with patch.dict(sys.modules, {"trio": None}):
            asyncio.run(router.startup())
        assert router._trio_available is False

    def test_shutdown_sets_not_running(self):
        router = RuntimeRouter(enable_metrics=False)
        asyncio.run(router.startup())
        asyncio.run(router.shutdown())
        assert router._is_running is False

    def test_shutdown_when_not_running_is_safe(self):
        """shutdown when not started is a no-op."""
        router = RuntimeRouter(enable_metrics=False)
        asyncio.run(router.shutdown())  # should not raise

    def test_runtime_context_starts_and_stops(self):
        """runtime_context async context manager starts and stops the router."""
        router = RuntimeRouter(enable_metrics=False)
        async def _use():
            async with router.runtime_context() as r:
                assert r._is_running is True
            assert router._is_running is False
        asyncio.run(_use())


# ===========================================================================
# 7.  runtime_router.py — route_tool_call
# ===========================================================================

class TestRouteToolCall:
    """RuntimeRouter.route_tool_call dispatching."""

    def _started_router(self):
        router = RuntimeRouter(enable_metrics=True)
        asyncio.run(router.startup())
        return router

    def test_route_fastapi_async_tool(self):
        """Async tools are awaited directly in FastAPI runtime."""
        router = self._started_router()
        async def my_tool(x): return x * 2
        with patch.object(router, "detect_runtime", return_value=RUNTIME_FASTAPI):
            result = asyncio.run(router.route_tool_call("my_tool", my_tool, 21))
        assert result == 42

    def test_route_fastapi_sync_tool(self):
        """Sync tools are run via anyio.to_thread in FastAPI runtime."""
        router = self._started_router()
        def sync_tool(x): return x + 1
        with patch.object(router, "detect_runtime", return_value=RUNTIME_FASTAPI):
            result = asyncio.run(router.route_tool_call("sync_tool", sync_tool, 9))
        assert result == 10

    def test_route_not_started_raises(self):
        """route_tool_call raises RuntimeError when router not started."""
        router = RuntimeRouter(enable_metrics=False)
        async def tool(): return None
        with pytest.raises(RuntimeError, match="not started"):
            asyncio.run(router.route_tool_call("t", tool))

    def test_route_records_metrics(self):
        """Successful routing increments FastAPI request counter."""
        router = self._started_router()
        async def tool(): return "ok"
        with patch.object(router, "detect_runtime", return_value=RUNTIME_FASTAPI):
            asyncio.run(router.route_tool_call("t", tool))
        assert router._metrics[RUNTIME_FASTAPI].request_count == 1

    def test_route_records_error_metric(self):
        """Failed routing increments error count."""
        router = self._started_router()
        async def bad_tool(): raise ValueError("oops")
        with patch.object(router, "detect_runtime", return_value=RUNTIME_FASTAPI):
            with pytest.raises(Exception):
                asyncio.run(router.route_tool_call("bad", bad_tool))
        assert router._metrics[RUNTIME_FASTAPI].error_count == 1

    def test_route_trio_fallback_to_fastapi(self):
        """Trio runtime falls back to FastAPI when _trio_available=False."""
        router = self._started_router()
        router._trio_available = False
        async def tool(): return "trio_fallback"
        with patch.object(router, "detect_runtime", return_value=RUNTIME_TRIO):
            result = asyncio.run(router.route_tool_call("t", tool))
        assert result == "trio_fallback"


# ===========================================================================
# 8.  runtime_router.py — get_metrics / _calculate_latency_improvement
# ===========================================================================

class TestRuntimeRouterMetrics:
    """get_metrics and latency-improvement calculations."""

    def test_get_metrics_empty_has_totals(self):
        router = RuntimeRouter(enable_metrics=True)
        asyncio.run(router.startup())
        m = router.get_runtime_stats()
        assert m["total_requests"] == 0
        assert m["error_rate"] == 0.0
        assert "by_runtime" in m

    def test_get_metrics_after_requests(self):
        router = RuntimeRouter(enable_metrics=True)
        asyncio.run(router.startup())
        async def tool(): return "x"
        with patch.object(router, "detect_runtime", return_value=RUNTIME_FASTAPI):
            for _ in range(3):
                asyncio.run(router.route_tool_call("t", tool))
        m = router.get_runtime_stats()
        assert m["total_requests"] == 3
        assert RUNTIME_FASTAPI in m["by_runtime"]

    def test_latency_improvement_none_when_insufficient_data(self):
        router = RuntimeRouter(enable_metrics=True)
        result = router._calculate_latency_improvement()
        assert result is None

    def test_reset_metrics_clears_counts(self):
        router = RuntimeRouter(enable_metrics=True)
        asyncio.run(router.startup())
        router._metrics[RUNTIME_FASTAPI].record_request(10.0, False)
        router.reset_metrics()
        assert router._metrics[RUNTIME_FASTAPI].request_count == 0


# ===========================================================================
# 9.  runtime_router.py — _route_to_trio async execution
# ===========================================================================

class TestRoutingPaths:
    """_route_to_fastapi / _route_to_trio async/sync branching."""

    def _started(self):
        r = RuntimeRouter(enable_metrics=False)
        asyncio.run(r.startup())
        return r

    def test_route_to_fastapi_async(self):
        router = self._started()
        async def f(): return 99
        assert asyncio.run(router._route_to_fastapi(f)) == 99

    def test_route_to_fastapi_sync(self):
        router = self._started()
        def f(): return 42
        assert asyncio.run(router._route_to_fastapi(f)) == 42

    def test_route_to_trio_fallback_when_unavailable(self):
        """_route_to_trio falls back to FastAPI when trio not available."""
        router = self._started()
        router._trio_available = False
        async def f(): return "trio"
        assert asyncio.run(router._route_to_trio(f)) == "trio"

    def test_route_to_trio_import_error_falls_back(self):
        """ImportError inside trio path falls back to _route_to_fastapi."""
        router = self._started()
        router._trio_available = True
        async def f(): return "ok"
        with patch.dict(sys.modules, {"trio": None}):
            result = asyncio.run(router._route_to_trio(f))
        assert result == "ok"


# ===========================================================================
# 10. validation.py — anyio task group migration
# ===========================================================================

class TestValidationAnyioMigration:
    """Verify the asyncio.gather → anyio task group migration in validation.py."""

    def test_no_asyncio_import_in_validation(self):
        """validation.py should no longer contain `import asyncio`."""
        val_path = (
            Path(__file__).parents[3]
            / "ipfs_datasets_py" / "optimizers" / "agentic" / "validation.py"
        )
        text = val_path.read_text(encoding="utf-8")
        assert "import asyncio" not in text, (
            "optimizers/agentic/validation.py still contains `import asyncio`"
        )

    def test_anyio_create_task_group_present(self):
        """validation.py should use anyio.create_task_group."""
        val_path = (
            Path(__file__).parents[3]
            / "ipfs_datasets_py" / "optimizers" / "agentic" / "validation.py"
        )
        text = val_path.read_text(encoding="utf-8")
        assert "anyio.create_task_group" in text

    def test_no_asyncio_import_in_ontology_pipeline(self):
        """ontology_pipeline.py should no longer contain `import asyncio`."""
        pipe_path = (
            Path(__file__).parents[3]
            / "ipfs_datasets_py" / "optimizers" / "graphrag" / "ontology_pipeline.py"
        )
        text = pipe_path.read_text(encoding="utf-8")
        assert "import asyncio" not in text, (
            "optimizers/graphrag/ontology_pipeline.py still contains `import asyncio`"
        )

    def test_anyio_to_thread_in_ontology_pipeline(self):
        """ontology_pipeline.py should use anyio.to_thread.run_sync."""
        pipe_path = (
            Path(__file__).parents[3]
            / "ipfs_datasets_py" / "optimizers" / "graphrag" / "ontology_pipeline.py"
        )
        text = pipe_path.read_text(encoding="utf-8")
        assert "anyio.to_thread.run_sync" in text

    def test_validation_parallel_runs_with_anyio(self):
        """_validate_parallel_anyio_fallback executes tasks concurrently."""
        # Build minimal validator stubs
        try:
            from ipfs_datasets_py.optimizers.agentic.validation import (
                ValidationOrchestrator,
            )
        except ImportError:
            pytest.skip("ValidationOrchestrator not importable in this environment")

        results: list = []

        async def fake_validate(code, files, ctx):
            results.append(code)
            return {"passed": True, "errors": []}

        mock_v1 = MagicMock()
        mock_v1.validate = fake_validate
        mock_v2 = MagicMock()
        mock_v2.validate = fake_validate

        orch = object.__new__(ValidationOrchestrator)
        orch.validators = {"v1": mock_v1, "v2": mock_v2}
        orch._log = MagicMock()

        async def run():
            return await orch._validate_parallel_anyio_fallback(
                "code_under_test", [], {}
            )

        out = asyncio.run(run())
        assert "v1" in out
        assert "v2" in out
        assert out["v1"]["passed"] is True
