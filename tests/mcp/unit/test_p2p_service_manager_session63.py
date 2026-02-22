"""
Tests for p2p_service_manager.py — Session O63 (v8 plan).

Coverage targets:
- P2PServiceState dataclass construction and field defaults
- P2PServiceManager.__init__ — all init parameters
- _setdefault_env: only sets when not already set
- _apply_env: sets all environment variables
- _restore_env: restores previous values, handles exceptions
- start(): enabled=False, ImportError, generic Exception
- stop(): no runtime, P2PServiceError, generic Exception, success
- state(): various fallback paths (ImportError, generic Exception)
- _initialize_mcplusplus_features: ImportError, unavailable HAVE_MCPLUSPLUS
- _cleanup_mcplusplus_features: with and without scheduler, exception path
- get_workflow_scheduler / get_peer_registry / has_advanced_features
- acquire_connection: hit (pop) and miss (not in pool)
- release_connection: success, full pool, conn=None
- clear_connection_pool: removes all, resets counters
- get_pool_stats: empty, with entries, hit rate calculation
- get_capabilities: all keys present
"""

import os
import sys
import threading
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.mcp_server.p2p_service_manager import (
    P2PServiceManager,
    P2PServiceState,
    _ensure_ipfs_accelerate_on_path,
)
from ipfs_datasets_py.mcp_server.exceptions import (
    P2PServiceError,
    P2PConnectionError,
    ConfigurationError,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _mgr(enabled: bool = False, **kwargs) -> P2PServiceManager:
    """Create a manager instance (enabled=False avoids real network calls)."""
    return P2PServiceManager(enabled=enabled, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# 1. P2PServiceState
# ══════════════════════════════════════════════════════════════════════════════


class TestP2PServiceState:
    """Tests for the P2PServiceState dataclass."""

    def test_basic_construction(self):
        """GIVEN required fields WHEN constructed THEN all fields accessible."""
        state = P2PServiceState(
            running=True,
            peer_id="QmABC",
            listen_port=4001,
            started_at=1000.0,
        )
        assert state.running is True
        assert state.peer_id == "QmABC"
        assert state.listen_port == 4001
        assert state.started_at == 1000.0

    def test_default_optional_fields(self):
        """GIVEN only required fields WHEN constructed THEN optional fields have defaults."""
        state = P2PServiceState(
            running=False, peer_id="", listen_port=None, started_at=0.0
        )
        assert state.last_error == ""
        assert state.workflow_scheduler_available is False
        assert state.peer_registry_available is False
        assert state.bootstrap_available is False
        assert state.connected_peers == 0
        assert state.active_workflows == 0

    def test_optional_fields_set(self):
        """GIVEN all fields WHEN constructed THEN values stored correctly."""
        state = P2PServiceState(
            running=True,
            peer_id="Qm123",
            listen_port=4001,
            started_at=999.9,
            last_error="oops",
            workflow_scheduler_available=True,
            peer_registry_available=True,
            bootstrap_available=True,
            connected_peers=5,
            active_workflows=3,
        )
        assert state.last_error == "oops"
        assert state.workflow_scheduler_available is True
        assert state.connected_peers == 5
        assert state.active_workflows == 3


# ══════════════════════════════════════════════════════════════════════════════
# 2. P2PServiceManager.__init__
# ══════════════════════════════════════════════════════════════════════════════


class TestP2PServiceManagerInit:
    """Tests for __init__ parameter handling."""

    def test_enabled_false_by_default(self):
        """GIVEN no enabled kwarg WHEN created THEN enabled=False."""
        mgr = _mgr()
        assert mgr.enabled is False

    def test_enabled_true(self):
        """GIVEN enabled=True WHEN created THEN enabled=True."""
        mgr = _mgr(enabled=True)
        assert mgr.enabled is True

    def test_queue_path_default(self):
        """GIVEN no queue_path WHEN created THEN a path string is set."""
        mgr = _mgr()
        assert isinstance(mgr.queue_path, str)
        assert len(mgr.queue_path) > 0

    def test_custom_queue_path(self):
        """GIVEN custom queue_path WHEN created THEN stored."""
        mgr = _mgr(queue_path="/tmp/custom.duckdb")
        assert mgr.queue_path == "/tmp/custom.duckdb"

    def test_listen_port_none_by_default(self):
        """GIVEN no listen_port WHEN created THEN None."""
        mgr = _mgr()
        assert mgr.listen_port is None

    def test_listen_port_set(self):
        """GIVEN listen_port=4001 WHEN created THEN stored as int."""
        mgr = _mgr(listen_port=4001)
        assert mgr.listen_port == 4001

    def test_auth_mode_default(self):
        """GIVEN no auth_mode WHEN created THEN 'mcp_token'."""
        mgr = _mgr()
        assert mgr.auth_mode == "mcp_token"

    def test_pool_initialized_empty(self):
        """GIVEN fresh manager WHEN created THEN pool is empty dict."""
        mgr = _mgr()
        assert mgr._connection_pool == {}
        assert mgr._pool_hits == 0
        assert mgr._pool_misses == 0

    def test_pool_max_size_default(self):
        """GIVEN fresh manager WHEN created THEN max_size=10."""
        mgr = _mgr()
        assert mgr._pool_max_size == 10

    def test_mcplusplus_available_false_initially(self):
        """GIVEN fresh manager WHEN created THEN MCP++ not available."""
        mgr = _mgr()
        assert mgr._mcplusplus_available is False

    def test_bootstrap_nodes_default_empty(self):
        """GIVEN no bootstrap_nodes WHEN created THEN empty list."""
        mgr = _mgr()
        assert mgr.bootstrap_nodes == []

    def test_bootstrap_nodes_custom(self):
        """GIVEN bootstrap_nodes list WHEN created THEN stored."""
        nodes = ["/ip4/1.2.3.4/tcp/4001"]
        mgr = _mgr(bootstrap_nodes=nodes)
        assert mgr.bootstrap_nodes == nodes


# ══════════════════════════════════════════════════════════════════════════════
# 3. Environment helpers
# ══════════════════════════════════════════════════════════════════════════════


class TestEnvHelpers:
    """Tests for _setdefault_env, _apply_env, _restore_env."""

    def test_setdefault_env_sets_when_not_set(self):
        """GIVEN key not in env WHEN _setdefault_env THEN sets value."""
        mgr = _mgr()
        key = "_TEST_P2P_KEY_NOT_IN_ENV_XYZ"
        os.environ.pop(key, None)
        try:
            mgr._setdefault_env(key, "testval")
            assert os.environ[key] == "testval"
            assert mgr._env_restore[key] is None
        finally:
            os.environ.pop(key, None)

    def test_setdefault_env_skips_when_already_set(self):
        """GIVEN key already in env WHEN _setdefault_env THEN not overwritten."""
        mgr = _mgr()
        key = "_TEST_P2P_EXISTING_KEY_XYZ"
        os.environ[key] = "original"
        try:
            mgr._setdefault_env(key, "newval")
            assert os.environ[key] == "original"
            assert key not in mgr._env_restore
        finally:
            os.environ.pop(key, None)

    def test_apply_env_sets_task_queue_path(self):
        """GIVEN _apply_env called WHEN queue_path set THEN env var set."""
        mgr = _mgr(queue_path="/tmp/test_queue.db")
        env_key = "IPFS_ACCELERATE_PY_TASK_QUEUE_PATH"
        os.environ.pop(env_key, None)
        try:
            mgr._apply_env()
            assert os.environ.get(env_key) == "/tmp/test_queue.db"
        finally:
            # Cleanup
            for k in list(mgr._env_restore.keys()):
                os.environ.pop(k, None)

    def test_restore_env_removes_set_vars(self):
        """GIVEN _apply_env called WHEN _restore_env called THEN vars removed."""
        mgr = _mgr(queue_path="/tmp/restore_test.db")
        env_key = "IPFS_ACCELERATE_PY_TASK_QUEUE_PATH"
        os.environ.pop(env_key, None)
        try:
            mgr._apply_env()
            assert env_key in os.environ
            mgr._restore_env()
            assert env_key not in os.environ
        finally:
            os.environ.pop(env_key, None)

    def test_restore_env_restores_prior_value(self):
        """GIVEN env var had prior value WHEN _restore_env THEN prior value restored."""
        mgr = _mgr()
        key = "_TEST_P2P_RESTORE_PRIOR_XYZ"
        os.environ[key] = "prior_value"
        try:
            # Manually set the _env_restore entry as if we had overridden it
            mgr._env_restore[key] = "prior_value"
            os.environ[key] = "changed_value"
            mgr._restore_env()
            assert os.environ[key] == "prior_value"
        finally:
            os.environ.pop(key, None)


# ══════════════════════════════════════════════════════════════════════════════
# 4. start()
# ══════════════════════════════════════════════════════════════════════════════


class TestStart:
    """Tests for P2PServiceManager.start()."""

    def test_start_disabled_returns_false(self):
        """GIVEN enabled=False WHEN start() THEN returns False without importing."""
        mgr = _mgr(enabled=False)
        result = mgr.start()
        assert result is False

    def test_start_import_error_returns_false(self):
        """GIVEN ipfs_accelerate_py not installed WHEN start() THEN returns False."""
        mgr = _mgr(enabled=True)
        with patch.dict(
            sys.modules,
            {"ipfs_accelerate_py": None, "ipfs_accelerate_py.p2p_tasks": None,
             "ipfs_accelerate_py.p2p_tasks.runtime": None},
        ):
            result = mgr.start()
        assert result is False

    def test_start_generic_exception_returns_false(self):
        """GIVEN importing TaskQueueP2PServiceRuntime raises non-ImportError WHEN start() THEN False."""
        mgr = _mgr(enabled=True)
        # Create a module stub whose attribute access raises a generic Exception
        class _RaisingMod:
            @property
            def TaskQueueP2PServiceRuntime(self):
                raise RuntimeError("not an ImportError")
        fake_mod_instance = _RaisingMod()
        with patch.dict(
            sys.modules,
            {"ipfs_accelerate_py.p2p_tasks.runtime": fake_mod_instance},
        ):
            result = mgr.start()
        assert result is False

    def test_start_with_mocked_runtime_success(self):
        """GIVEN mocked runtime WHEN start() THEN returns running state."""
        mgr = _mgr(enabled=True)
        mock_handle = MagicMock()
        mock_handle.started = MagicMock()
        mock_handle.started.wait = MagicMock(return_value=True)
        
        mock_runtime = MagicMock()
        mock_runtime.running = True
        mock_runtime.start = MagicMock(return_value=mock_handle)
        
        mock_runtime_cls = MagicMock(return_value=mock_runtime)
        fake_mod = MagicMock()
        fake_mod.TaskQueueP2PServiceRuntime = mock_runtime_cls
        
        with patch.dict(sys.modules, {"ipfs_accelerate_py.p2p_tasks.runtime": fake_mod}):
            with patch.object(mgr, "_initialize_mcplusplus_features"):
                result = mgr.start()
        
        assert result is True


# ══════════════════════════════════════════════════════════════════════════════
# 5. stop()
# ══════════════════════════════════════════════════════════════════════════════


class TestStop:
    """Tests for P2PServiceManager.stop()."""

    def test_stop_no_runtime_returns_true(self):
        """GIVEN no runtime WHEN stop() THEN returns True."""
        mgr = _mgr()
        mgr._runtime = None
        result = mgr.stop()
        assert result is True

    def test_stop_p2p_service_error_returns_false(self):
        """GIVEN runtime.stop raises P2PServiceError WHEN stop() THEN returns False."""
        mgr = _mgr()
        mock_rt = MagicMock()
        mock_rt.stop = MagicMock(side_effect=P2PServiceError("stop failed"))
        mgr._runtime = mock_rt

        with patch.object(mgr, "_cleanup_mcplusplus_features"):
            result = mgr.stop()
        assert result is False

    def test_stop_generic_exception_returns_false(self):
        """GIVEN runtime.stop raises generic Exception WHEN stop() THEN returns False."""
        mgr = _mgr()
        mock_rt = MagicMock()
        mock_rt.stop = MagicMock(side_effect=RuntimeError("stop crash"))
        mgr._runtime = mock_rt

        with patch.object(mgr, "_cleanup_mcplusplus_features"):
            result = mgr.stop()
        assert result is False

    def test_stop_success_returns_true(self):
        """GIVEN runtime.stop() returns True WHEN stop() THEN returns True."""
        mgr = _mgr()
        mock_rt = MagicMock()
        mock_rt.stop = MagicMock(return_value=True)
        mgr._runtime = mock_rt

        with patch.object(mgr, "_cleanup_mcplusplus_features"):
            result = mgr.stop()
        assert result is True


# ══════════════════════════════════════════════════════════════════════════════
# 6. state()
# ══════════════════════════════════════════════════════════════════════════════


class TestState:
    """Tests for P2PServiceManager.state()."""

    def test_state_no_runtime_returns_state_object(self):
        """GIVEN no runtime and ipfs_accelerate_py unavailable WHEN state() THEN returns P2PServiceState."""
        mgr = _mgr()
        mgr._runtime = None
        with patch.dict(
            sys.modules,
            {"ipfs_accelerate_py": None, "ipfs_accelerate_py.p2p_tasks": None,
             "ipfs_accelerate_py.p2p_tasks.service": None},
        ):
            result = mgr.state()
        assert isinstance(result, P2PServiceState)
        assert result.running is False

    def test_state_import_error_falls_back_to_runtime_attr(self):
        """GIVEN service module unavailable WHEN state() THEN uses runtime.running fallback."""
        mgr = _mgr()
        mock_rt = MagicMock()
        mock_rt.running = True
        mgr._runtime = mock_rt

        with patch.dict(
            sys.modules,
            {"ipfs_accelerate_py.p2p_tasks.service": None},
        ):
            result = mgr.state()
        assert isinstance(result, P2PServiceState)

    def test_state_includes_mcplusplus_fields(self):
        """GIVEN MCP++ scheduler set WHEN state() THEN workflow_scheduler_available=True."""
        mgr = _mgr()
        mgr._workflow_scheduler = MagicMock()
        mgr._runtime = None
        with patch.dict(
            sys.modules,
            {"ipfs_accelerate_py.p2p_tasks.service": None},
        ):
            result = mgr.state()
        assert result.workflow_scheduler_available is True


# ══════════════════════════════════════════════════════════════════════════════
# 7. _initialize_mcplusplus_features / _cleanup_mcplusplus_features
# ══════════════════════════════════════════════════════════════════════════════


class TestMCPPlusPlusFeatures:
    """Tests for MCP++ initialization and cleanup."""

    def test_initialize_import_error_sets_not_available(self):
        """GIVEN mcplusplus import fails WHEN _initialize_mcplusplus_features THEN not available."""
        mgr = _mgr()
        with patch.dict(
            sys.modules,
            {"ipfs_datasets_py.mcp_server.mcplusplus": None},
        ):
            mgr._initialize_mcplusplus_features()
        assert mgr._mcplusplus_available is False

    def test_initialize_generic_exception_sets_not_available(self):
        """GIVEN import raises Exception WHEN _initialize_mcplusplus_features THEN not available."""
        mgr = _mgr()
        import importlib
        import ipfs_datasets_py.mcp_server as mcp_server_pkg
        fake_mcplusplus = MagicMock()
        fake_mcplusplus.HAVE_MCPLUSPLUS = False
        with patch.dict(
            sys.modules,
            {"ipfs_datasets_py.mcp_server.mcplusplus": fake_mcplusplus},
        ):
            mgr._initialize_mcplusplus_features()
        assert mgr._mcplusplus_available is False

    def test_cleanup_no_scheduler(self):
        """GIVEN no scheduler WHEN _cleanup_mcplusplus_features THEN no error."""
        mgr = _mgr()
        mgr._workflow_scheduler = None
        mgr._cleanup_mcplusplus_features()  # must not raise
        assert mgr._mcplusplus_available is False

    def test_cleanup_with_scheduler(self):
        """GIVEN scheduler set and reset_scheduler is callable WHEN _cleanup THEN scheduler cleared."""
        mgr = _mgr()
        mgr._workflow_scheduler = MagicMock()

        # Patch reset_scheduler directly so it doesn't raise
        from ipfs_datasets_py.mcp_server import mcplusplus as mcp_mod
        with patch.object(mcp_mod, "reset_scheduler", MagicMock()):
            mgr._cleanup_mcplusplus_features()
        assert mgr._workflow_scheduler is None

    def test_cleanup_exception_swallowed(self):
        """GIVEN cleanup raises Exception WHEN _cleanup_mcplusplus_features THEN no raise."""
        mgr = _mgr()
        mgr._workflow_scheduler = MagicMock()
        with patch.dict(
            sys.modules,
            {"ipfs_datasets_py.mcp_server.mcplusplus": None},
        ):
            mgr._cleanup_mcplusplus_features()  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# 8. getters
# ══════════════════════════════════════════════════════════════════════════════


class TestGetters:
    """Tests for get_workflow_scheduler, get_peer_registry, has_advanced_features."""

    def test_get_workflow_scheduler_none_initially(self):
        """GIVEN no scheduler WHEN get_workflow_scheduler THEN None."""
        mgr = _mgr()
        assert mgr.get_workflow_scheduler() is None

    def test_get_workflow_scheduler_returns_value(self):
        """GIVEN scheduler set WHEN get_workflow_scheduler THEN returns it."""
        mgr = _mgr()
        mock_sched = MagicMock()
        mgr._workflow_scheduler = mock_sched
        assert mgr.get_workflow_scheduler() is mock_sched

    def test_get_peer_registry_none_initially(self):
        """GIVEN no registry WHEN get_peer_registry THEN None."""
        mgr = _mgr()
        assert mgr.get_peer_registry() is None

    def test_get_peer_registry_returns_value(self):
        """GIVEN registry set WHEN get_peer_registry THEN returns it."""
        mgr = _mgr()
        mock_reg = MagicMock()
        mgr._peer_registry = mock_reg
        assert mgr.get_peer_registry() is mock_reg

    def test_has_advanced_features_false_initially(self):
        """GIVEN fresh manager WHEN has_advanced_features THEN False."""
        mgr = _mgr()
        assert mgr.has_advanced_features() is False

    def test_has_advanced_features_true_when_available(self):
        """GIVEN _mcplusplus_available=True WHEN has_advanced_features THEN True."""
        mgr = _mgr()
        mgr._mcplusplus_available = True
        assert mgr.has_advanced_features() is True


# ══════════════════════════════════════════════════════════════════════════════
# 9. Connection pool
# ══════════════════════════════════════════════════════════════════════════════


class TestConnectionPool:
    """Tests for acquire_connection / release_connection / clear_connection_pool / get_pool_stats."""

    def test_acquire_miss_increments_misses(self):
        """GIVEN empty pool WHEN acquire_connection THEN miss++ and returns None."""
        mgr = _mgr()
        result = mgr.acquire_connection("QmPeer1")
        assert result is None
        assert mgr._pool_misses == 1
        assert mgr._pool_hits == 0

    def test_acquire_hit_returns_conn_and_increments_hits(self):
        """GIVEN conn in pool WHEN acquire_connection THEN returns conn and hit++."""
        mgr = _mgr()
        fake_conn = MagicMock()
        mgr._connection_pool["QmPeer1"] = fake_conn
        result = mgr.acquire_connection("QmPeer1")
        assert result is fake_conn
        assert mgr._pool_hits == 1
        assert mgr._pool_misses == 0
        # Connection removed from pool after acquire
        assert "QmPeer1" not in mgr._connection_pool

    def test_release_connection_stores_conn(self):
        """GIVEN empty pool WHEN release_connection THEN conn stored."""
        mgr = _mgr()
        fake_conn = MagicMock()
        result = mgr.release_connection("QmPeer1", fake_conn)
        assert result is True
        assert mgr._connection_pool["QmPeer1"] is fake_conn

    def test_release_connection_none_returns_false(self):
        """GIVEN conn=None WHEN release_connection THEN returns False."""
        mgr = _mgr()
        result = mgr.release_connection("QmPeer1", None)
        assert result is False
        assert "QmPeer1" not in mgr._connection_pool

    def test_release_connection_full_pool_returns_false(self):
        """GIVEN pool at capacity WHEN release_connection THEN returns False."""
        mgr = _mgr()
        mgr._pool_max_size = 2
        mgr._connection_pool = {f"peer{i}": MagicMock() for i in range(2)}
        result = mgr.release_connection("new_peer", MagicMock())
        assert result is False

    def test_clear_connection_pool_removes_all(self):
        """GIVEN pool with entries WHEN clear_connection_pool THEN pool empty."""
        mgr = _mgr()
        mgr._connection_pool = {"p1": MagicMock(), "p2": MagicMock()}
        mgr._pool_hits = 5
        mgr._pool_misses = 3
        count = mgr.clear_connection_pool()
        assert count == 2
        assert mgr._connection_pool == {}
        assert mgr._pool_hits == 0
        assert mgr._pool_misses == 0

    def test_clear_empty_pool_returns_zero(self):
        """GIVEN empty pool WHEN clear_connection_pool THEN 0."""
        mgr = _mgr()
        count = mgr.clear_connection_pool()
        assert count == 0

    def test_get_pool_stats_empty_pool(self):
        """GIVEN empty pool, no attempts WHEN get_pool_stats THEN hit_rate=None."""
        mgr = _mgr()
        stats = mgr.get_pool_stats()
        assert stats["size"] == 0
        assert stats["max_size"] == 10
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] is None

    def test_get_pool_stats_with_hits_and_misses(self):
        """GIVEN 2 hits, 2 misses WHEN get_pool_stats THEN hit_rate=0.5."""
        mgr = _mgr()
        mgr._pool_hits = 2
        mgr._pool_misses = 2
        stats = mgr.get_pool_stats()
        assert stats["hit_rate"] == pytest.approx(0.5)

    def test_get_pool_stats_reflects_current_pool_size(self):
        """GIVEN 3 connections in pool WHEN get_pool_stats THEN size=3."""
        mgr = _mgr()
        mgr._connection_pool = {f"p{i}": MagicMock() for i in range(3)}
        stats = mgr.get_pool_stats()
        assert stats["size"] == 3

    def test_pool_thread_safety(self):
        """GIVEN concurrent acquire/release WHEN pool used THEN no data corruption."""
        mgr = _mgr()
        errors = []

        def worker():
            try:
                conn = MagicMock()
                mgr.release_connection("shared_peer", conn)
                mgr.acquire_connection("shared_peer")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ══════════════════════════════════════════════════════════════════════════════
# 10. get_capabilities
# ══════════════════════════════════════════════════════════════════════════════


class TestGetCapabilities:
    """Tests for get_capabilities."""

    def test_capabilities_keys_present(self):
        """GIVEN fresh manager WHEN get_capabilities THEN all expected keys present."""
        mgr = _mgr()
        caps = mgr.get_capabilities()
        expected_keys = {
            "p2p_enabled",
            "mcplusplus_available",
            "workflow_scheduler",
            "peer_registry",
            "bootstrap",
            "tools_enabled",
            "cache_enabled",
            "connection_pool_max_size",
        }
        assert expected_keys.issubset(set(caps.keys()))

    def test_capabilities_enabled_false(self):
        """GIVEN enabled=False WHEN get_capabilities THEN p2p_enabled=False."""
        mgr = _mgr(enabled=False)
        assert mgr.get_capabilities()["p2p_enabled"] is False

    def test_capabilities_enabled_true(self):
        """GIVEN enabled=True WHEN get_capabilities THEN p2p_enabled=True."""
        mgr = _mgr(enabled=True)
        assert mgr.get_capabilities()["p2p_enabled"] is True

    def test_capabilities_pool_max_size(self):
        """GIVEN default max size WHEN get_capabilities THEN 10."""
        mgr = _mgr()
        assert mgr.get_capabilities()["connection_pool_max_size"] == 10

    def test_capabilities_workflow_scheduler_reflects_state(self):
        """GIVEN no scheduler WHEN get_capabilities THEN workflow_scheduler=False."""
        mgr = _mgr()
        assert mgr.get_capabilities()["workflow_scheduler"] is False

    def test_ensure_ipfs_accelerate_on_path_no_raise(self):
        """GIVEN _ensure_ipfs_accelerate_on_path called WHEN no submodule THEN no raise."""
        _ensure_ipfs_accelerate_on_path()  # must not raise
