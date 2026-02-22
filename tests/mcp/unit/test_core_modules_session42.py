"""
Session 42 — tests covering 5 previously-untested mcp_server modules.

Targets:
- logger.py         (12 stmts, 0%  → 100%)
- mcp_interfaces.py (42 stmts, 0%  → 100%)
- exceptions.py     (63 stmts, 78% → 100%)
- configs.py        (75 stmts, 48% → 100%)
- trio_bridge.py    (28 stmts, 0%  → 100%)
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# logger.py — all 12 stmts are module-level; importing executes them all.
# ===========================================================================

class TestLogger:
    def test_import_creates_loggers(self):
        """Importing logger.py executes all module-level stmts."""
        from ipfs_datasets_py.mcp_server import logger as logger_mod
        assert logger_mod.logger is not None
        assert logger_mod.mcp_logger is not None

    def test_loggers_are_logging_logger_instances(self):
        from ipfs_datasets_py.mcp_server import logger as logger_mod
        assert isinstance(logger_mod.logger, logging.Logger)
        assert isinstance(logger_mod.mcp_logger, logging.Logger)

    def test_log_file_path_attribute_exists(self):
        from ipfs_datasets_py.mcp_server import logger as logger_mod
        assert hasattr(logger_mod, "mcp_log_path")

    def test_log_dir_created(self):
        from ipfs_datasets_py.mcp_server import logger as logger_mod
        assert hasattr(logger_mod, "log_dir")


# ===========================================================================
# mcp_interfaces.py
# ===========================================================================

class TestMCPInterfaces:

    # --- Protocol isinstance checks ----------------------------------------

    def test_mcp_server_protocol_isinstance_with_conforming_object(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import MCPServerProtocol

        class FakeServer:
            tools: Dict[str, Callable[..., Any]] = {}
            def validate_p2p_token(self, token: str) -> bool:
                return True

        assert isinstance(FakeServer(), MCPServerProtocol)

    def test_mcp_server_protocol_not_isinstance_without_tools(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import MCPServerProtocol

        class Missing:
            def validate_p2p_token(self, token: str) -> bool:
                return False

        assert not isinstance(Missing(), MCPServerProtocol)

    def test_tool_manager_protocol_isinstance(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import ToolManagerProtocol

        class FakeTM:
            def list_categories(self) -> list:
                return []
            def list_tools(self, category=None) -> list:
                return []
            def get_schema(self, tool_name: str) -> dict:
                return {}
            def dispatch(self, tool_name: str, **kw) -> Any:
                return None

        assert isinstance(FakeTM(), ToolManagerProtocol)

    def test_mcp_client_protocol_isinstance(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import MCPClientProtocol

        class FakeClient:
            def add_tool(self, func, name=None, description=None) -> None:
                pass
            def list_tools(self) -> list:
                return []

        assert isinstance(FakeClient(), MCPClientProtocol)

    def test_p2p_service_protocol_isinstance(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import P2PServiceProtocol

        class FakeP2P:
            def start(self) -> None: pass
            def stop(self) -> None: pass
            def is_running(self) -> bool: return False
            def register_tool(self, name: str, func) -> None: pass

        assert isinstance(FakeP2P(), P2PServiceProtocol)

    # --- check_protocol_implementation -------------------------------------

    def test_check_protocol_true(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import (
            MCPClientProtocol, check_protocol_implementation,
        )

        class FakeClient:
            def add_tool(self, func, name=None, description=None) -> None: pass
            def list_tools(self) -> list: return []

        assert check_protocol_implementation(FakeClient(), MCPClientProtocol) is True

    def test_check_protocol_false_non_strict(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import (
            MCPClientProtocol, check_protocol_implementation,
        )
        assert check_protocol_implementation(object(), MCPClientProtocol) is False

    def test_check_protocol_strict_raises(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import (
            MCPClientProtocol, check_protocol_implementation,
        )
        with pytest.raises(TypeError, match="does not implement"):
            check_protocol_implementation(object(), MCPClientProtocol, strict=True)

    # --- Type aliases are importable ----------------------------------------
    def test_type_aliases(self):
        from ipfs_datasets_py.mcp_server import mcp_interfaces
        assert hasattr(mcp_interfaces, "ToolDict")
        assert hasattr(mcp_interfaces, "ToolDescriptor")
        assert hasattr(mcp_interfaces, "ToolRegistry")


# ===========================================================================
# exceptions.py — fill in the 22% missing (lines 39, 59-64, 77-81, 121-122)
# ===========================================================================

class TestExceptions:

    # --- MCPServerError.__str__ with details --------------------------------
    def test_mcp_server_error_str_with_details(self):
        from ipfs_datasets_py.mcp_server.exceptions import MCPServerError
        err = MCPServerError("something went wrong", {"tool": "my_tool", "code": 42})
        s = str(err)
        assert "something went wrong" in s
        assert "tool=my_tool" in s
        assert "code=42" in s

    def test_mcp_server_error_str_without_details(self):
        from ipfs_datasets_py.mcp_server.exceptions import MCPServerError
        err = MCPServerError("bare error")
        assert str(err) == "bare error"

    # --- ToolNotFoundError with category ------------------------------------
    def test_tool_not_found_with_category(self):
        from ipfs_datasets_py.mcp_server.exceptions import ToolNotFoundError
        err = ToolNotFoundError("my_func", category="search")
        assert err.tool_name == "my_func"
        assert err.category == "search"
        assert "search.my_func" in str(err)

    def test_tool_not_found_without_category(self):
        from ipfs_datasets_py.mcp_server.exceptions import ToolNotFoundError
        err = ToolNotFoundError("my_func")
        assert err.category is None
        assert "my_func" in str(err)

    # --- ToolExecutionError -------------------------------------------------
    def test_tool_execution_error(self):
        from ipfs_datasets_py.mcp_server.exceptions import ToolExecutionError
        cause = ValueError("bad input")
        err = ToolExecutionError("compute_fn", cause)
        assert err.tool_name == "compute_fn"
        assert err.original_error is cause
        assert err.__cause__ is cause
        assert "compute_fn" in str(err)
        assert "ValueError" in str(err)

    # --- RuntimeNotFoundError -----------------------------------------------
    def test_runtime_not_found_error(self):
        from ipfs_datasets_py.mcp_server.exceptions import RuntimeNotFoundError
        err = RuntimeNotFoundError("trio")
        assert err.runtime == "trio"
        assert "trio" in str(err)

    # --- HealthCheckError ---------------------------------------------------
    def test_health_check_error(self):
        from ipfs_datasets_py.mcp_server.exceptions import HealthCheckError
        err = HealthCheckError("db_health", "connection refused")
        assert err.check_name == "db_health"
        assert "db_health" in str(err)
        assert "connection refused" in str(err)

    # --- Remaining exception types are constructable -------------------------
    def test_all_exception_types_instantiable(self):
        from ipfs_datasets_py.mcp_server.exceptions import (
            MCPServerError, ToolError, ToolNotFoundError, ToolExecutionError,
            ToolRegistrationError, ValidationError, RuntimeRoutingError,
            RuntimeNotFoundError, RuntimeExecutionError, P2PServiceError,
            P2PConnectionError, P2PAuthenticationError, ConfigurationError,
            ServerStartupError, ServerShutdownError, HealthCheckError,
            MonitoringError, MetricsCollectionError,
        )
        instances = [
            MCPServerError("m"),
            ToolRegistrationError("r"),
            ValidationError("field", "bad"),
            RuntimeRoutingError("rr"),
            RuntimeExecutionError("re"),
            P2PServiceError("p2p"),
            P2PConnectionError("conn"),
            P2PAuthenticationError("auth"),
            ConfigurationError("cfg"),
            ServerStartupError("start"),
            ServerShutdownError("stop"),
            MonitoringError("mon"),
            MetricsCollectionError("metrics"),
        ]
        for inst in instances:
            assert isinstance(inst, MCPServerError)

    def test_validation_error_field_attribute(self):
        from ipfs_datasets_py.mcp_server.exceptions import ValidationError
        err = ValidationError("query_text", "must not be empty")
        assert err.field == "query_text"
        assert "query_text" in str(err)
        assert "must not be empty" in str(err)


# ===========================================================================
# configs.py — lines 77, 82, 87 (properties) and 100-151 (load_config_from_yaml)
# ===========================================================================

class TestConfigs:

    # --- Dataclass defaults -------------------------------------------------
    def test_defaults(self):
        from ipfs_datasets_py.mcp_server.configs import Configs
        c = Configs()
        assert c.host == "127.0.0.1"
        assert c.port == 5000
        assert c.transport == "stdio"
        assert c.p2p_enabled is False

    # --- Properties (lines 77, 82, 87) --------------------------------------
    def test_root_dir_property(self):
        from ipfs_datasets_py.mcp_server.configs import Configs
        c = Configs()
        assert isinstance(c.ROOT_DIR, Path)
        assert c.ROOT_DIR.is_dir()

    def test_project_name_property(self):
        from ipfs_datasets_py.mcp_server.configs import Configs
        c = Configs()
        assert c.PROJECT_NAME == "ipfs_datasets_mcp"

    def test_config_dir_property(self):
        from ipfs_datasets_py.mcp_server.configs import Configs
        c = Configs()
        assert isinstance(c.CONFIG_DIR, Path)
        assert str(c.CONFIG_DIR).endswith("config")

    # --- load_config_from_yaml: no path → defaults -------------------------
    def test_load_no_path_returns_default(self):
        from ipfs_datasets_py.mcp_server.configs import load_config_from_yaml, Configs
        result = load_config_from_yaml()
        assert isinstance(result, Configs)
        assert result.host == "127.0.0.1"

    def test_load_nonexistent_path_returns_default(self):
        from ipfs_datasets_py.mcp_server.configs import load_config_from_yaml, Configs
        result = load_config_from_yaml("/tmp/definitely_nonexistent_config_42.yaml")
        assert isinstance(result, Configs)

    def test_load_valid_yaml_server_section(self):
        from ipfs_datasets_py.mcp_server.configs import load_config_from_yaml
        yaml_content = """
server:
  host: 0.0.0.0
  port: 8080
  verbose: false
  reload: false
  tool_timeout: 120
  transport: http
  log_level: DEBUG
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            fname = f.name
        try:
            cfg = load_config_from_yaml(fname)
            assert cfg.host == "0.0.0.0"
            assert cfg.port == 8080
            assert cfg.verbose is False
            assert cfg.transport == "http"
            assert cfg.log_level == logging.DEBUG
        finally:
            os.unlink(fname)

    def test_load_yaml_with_tools_section(self):
        from ipfs_datasets_py.mcp_server.configs import load_config_from_yaml
        yaml_content = """
tools:
  enabled_categories:
    - dataset
    - vector
  dataset:
    batch_size: 32
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            fname = f.name
        try:
            cfg = load_config_from_yaml(fname)
            assert "dataset" in cfg.enabled_tool_categories
            assert "vector" in cfg.enabled_tool_categories
            assert cfg.tool_configs.get("dataset", {}).get("batch_size") == 32
        finally:
            os.unlink(fname)

    def test_load_yaml_with_ipfs_kit_section(self):
        from ipfs_datasets_py.mcp_server.configs import load_config_from_yaml
        yaml_content = """
ipfs_kit:
  integration: mcp
  mcp_url: http://localhost:9090
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            fname = f.name
        try:
            cfg = load_config_from_yaml(fname)
            assert cfg.ipfs_kit_integration == "mcp"
            assert cfg.ipfs_kit_mcp_url == "http://localhost:9090"
        finally:
            os.unlink(fname)

    def test_load_invalid_yaml_returns_default(self):
        from ipfs_datasets_py.mcp_server.configs import load_config_from_yaml, Configs
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(": bad: yaml: [[[")
            fname = f.name
        try:
            result = load_config_from_yaml(fname)
            assert isinstance(result, Configs)
        finally:
            os.unlink(fname)

    # --- Global configs instance -------------------------------------------
    def test_global_configs_instance(self):
        from ipfs_datasets_py.mcp_server.configs import configs, Configs
        assert isinstance(configs, Configs)


# ===========================================================================
# trio_bridge.py
# ===========================================================================

class TestTrioBridge:
    """Tests for run_in_trio() utility."""

    def test_run_in_trio_is_importable(self):
        from ipfs_datasets_py.mcp_server.trio_bridge import run_in_trio
        assert callable(run_in_trio)

    def test_all_exported(self):
        from ipfs_datasets_py.mcp_server import trio_bridge
        assert "run_in_trio" in trio_bridge.__all__

    def test_sniffio_not_found_falls_back_to_thread_runner(self):
        """sniffio.AsyncLibraryNotFoundError -> fall back to anyio thread runner."""
        import sniffio
        from ipfs_datasets_py.mcp_server import trio_bridge

        def simple():
            return "fallback_ok"

        # Mock anyio.to_thread.run_sync to return the result directly
        mock_coro = AsyncMock(return_value="fallback_ok")
        with patch("sniffio.current_async_library",
                   side_effect=sniffio.AsyncLibraryNotFoundError):
            with patch("anyio.to_thread.run_sync", mock_coro):
                result = asyncio.run(trio_bridge.run_in_trio(simple))
        assert result == "fallback_ok"

    def test_import_error_raises_runtime_execution_error(self):
        """ImportError inside the Trio path should raise RuntimeExecutionError."""
        import sniffio
        from ipfs_datasets_py.mcp_server import trio_bridge
        from ipfs_datasets_py.mcp_server.exceptions import RuntimeExecutionError

        def simple():
            return "unreachable"

        async def run_it():
            with patch("sniffio.current_async_library",
                       side_effect=ImportError("trio not installed")):
                with pytest.raises(RuntimeExecutionError, match="Trio runtime unavailable"):
                    await trio_bridge.run_in_trio(simple)

        asyncio.run(run_it())

    def test_generic_exception_falls_back_to_thread_runner(self):
        """A generic exception from sniffio detection falls back to thread runner."""
        from ipfs_datasets_py.mcp_server import trio_bridge

        def simple():
            return "generic_fallback"

        mock_coro = AsyncMock(return_value="generic_fallback")
        with patch("sniffio.current_async_library",
                   side_effect=RuntimeError("unexpected")):
            with patch("anyio.to_thread.run_sync", mock_coro):
                result = asyncio.run(trio_bridge.run_in_trio(simple))
        assert result == "generic_fallback"

    def test_in_trio_context_runs_inline_sync(self):
        """When already in Trio, synchronous callables are returned directly."""
        from ipfs_datasets_py.mcp_server import trio_bridge

        def sync_fn():
            return "inline_sync"

        # Simulate being inside a Trio event loop
        with patch("sniffio.current_async_library", return_value="trio"):
            result = asyncio.run(trio_bridge.run_in_trio(sync_fn))
        assert result == "inline_sync"

    def test_in_trio_context_runs_inline_async(self):
        """When already in Trio, async callables are awaited inline."""
        from ipfs_datasets_py.mcp_server import trio_bridge

        async def async_fn():
            return "inline_async"

        with patch("sniffio.current_async_library", return_value="trio"):
            result = asyncio.run(trio_bridge.run_in_trio(async_fn))
        assert result == "inline_async"


# ===========================================================================
# Additional coverage for ... Protocol bodies and trio_bridge _runner path
# ===========================================================================

class TestMCPInterfaceProtocolBodies:
    """Call Protocol method bodies directly via concrete subclasses."""

    def test_mcp_server_protocol_validate_method_body(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import MCPServerProtocol

        class Stub(MCPServerProtocol): pass

        obj = Stub()
        # Calling the Protocol's own unimplemented method returns None (body is ...)
        result = MCPServerProtocol.validate_p2p_token(obj, "tok")
        assert result is None

    def test_tool_manager_protocol_bodies(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import ToolManagerProtocol

        class Stub(ToolManagerProtocol): pass

        obj = Stub()
        assert ToolManagerProtocol.list_categories(obj) is None
        assert ToolManagerProtocol.list_tools(obj) is None
        assert ToolManagerProtocol.get_schema(obj, "tool") is None
        assert ToolManagerProtocol.dispatch(obj, "tool") is None

    def test_mcp_client_protocol_bodies(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import MCPClientProtocol

        class Stub(MCPClientProtocol): pass

        obj = Stub()
        assert MCPClientProtocol.add_tool(obj, lambda: None) is None
        assert MCPClientProtocol.list_tools(obj) is None

    def test_p2p_service_protocol_bodies(self):
        from ipfs_datasets_py.mcp_server.mcp_interfaces import P2PServiceProtocol

        class Stub(P2PServiceProtocol): pass

        obj = Stub()
        assert P2PServiceProtocol.start(obj) is None
        assert P2PServiceProtocol.stop(obj) is None
        assert P2PServiceProtocol.is_running(obj) is None
        assert P2PServiceProtocol.register_tool(obj, "t", lambda: None) is None


class TestTrioBridgeRunnerPath:
    """Cover the _runner / _inner / anyio.run branch."""

    def test_runner_path_with_mocked_anyio_run(self):
        """
        Patch ONLY trio_bridge's local sniffio reference (not the global one)
        so anyio.to_thread.run_sync still sees the real asyncio backend.
        Also patch anyio.run to avoid needing the Trio install.
        """
        import anyio
        import sniffio as real_sniffio
        import ipfs_datasets_py.mcp_server.trio_bridge as bridge_mod

        def simple():
            return "runner_result"

        def fake_anyio_run(coro_fn, *, backend):
            # Use asyncio instead of trio to run the inner coroutine
            return asyncio.new_event_loop().run_until_complete(coro_fn())

        # Create a mock sniffio that raises AsyncLibraryNotFoundError
        mock_sniffio = MagicMock()
        mock_sniffio.current_async_library.side_effect = (
            real_sniffio.AsyncLibraryNotFoundError
        )
        mock_sniffio.AsyncLibraryNotFoundError = real_sniffio.AsyncLibraryNotFoundError

        async def driver():
            # Patch sniffio and anyio.run ONLY in the trio_bridge namespace
            with patch.object(bridge_mod, "sniffio", mock_sniffio):
                with patch.object(bridge_mod.anyio, "run", fake_anyio_run):
                    return await bridge_mod.run_in_trio(simple)

        result = anyio.run(driver, backend="asyncio")
        assert result == "runner_result"
