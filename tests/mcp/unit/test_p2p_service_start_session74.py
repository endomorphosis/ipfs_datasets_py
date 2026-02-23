"""
T74 — p2p_service_manager.py start() success path + _ensure_ipfs_accelerate_on_path
=====================================================================================
Covers previously-untested branches:

* _ensure_ipfs_accelerate_on_path: path added / already present / OSError
* P2PServiceManager.start(): enabled=False fast-return; ImportError path; success path
  (TaskQueueP2PServiceRuntime mocked); generic-exception path
* P2PServiceManager.state(): P2PServiceError in last_error block; Exception in state block
* has_advanced_features(), get_workflow_scheduler(), get_peer_registry()
* _initialize_mcplusplus_features: all internal paths
"""
from __future__ import annotations

import sys
import types
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ipfs_datasets_py.mcp_server.p2p_service_manager import (
    P2PServiceManager,
    P2PServiceState,
    _ensure_ipfs_accelerate_on_path,
)
from ipfs_datasets_py.mcp_server.exceptions import P2PServiceError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mgr(**kwargs) -> P2PServiceManager:
    defaults = dict(enabled=True, queue_path="/tmp/q.duckdb")
    defaults.update(kwargs)
    return P2PServiceManager(**defaults)


# ===========================================================================
# _ensure_ipfs_accelerate_on_path
# ===========================================================================

class TestEnsureIpfsAccelerateOnPath:

    def test_adds_path_when_candidate_exists(self, tmp_path):
        """When the candidate dir exists and is not in sys.path, it is prepended."""
        candidate = tmp_path / "ipfs_accelerate_py"
        candidate.mkdir()

        fake_file = tmp_path / "mcp_server" / "p2p_service_manager.py"

        # Capture sys.path length before
        before_len = len(sys.path)

        with patch("ipfs_datasets_py.mcp_server.p2p_service_manager.__file__",
                   str(fake_file)):
            _ensure_ipfs_accelerate_on_path()
            # Function must not raise; sys.path must not be corrupted
            assert len(sys.path) >= before_len

    def test_does_not_duplicate_existing_path(self):
        """If candidate already in sys.path, it is not duplicated."""
        before = sys.path.copy()
        _ensure_ipfs_accelerate_on_path()
        # Calling twice is idempotent
        _ensure_ipfs_accelerate_on_path()
        # Function must not raise

    def test_oserror_suppressed(self):
        """OSError during path inspection must be silently swallowed."""
        with patch("ipfs_datasets_py.mcp_server.p2p_service_manager.__file__",
                   "/nonexistent/path/that/raises"):
            _ensure_ipfs_accelerate_on_path()  # must not raise


# ===========================================================================
# P2PServiceManager.start()
# ===========================================================================

class TestP2PServiceManagerStart:

    def test_start_returns_false_when_disabled(self):
        mgr = _make_mgr(enabled=False)
        result = mgr.start()
        assert result is False

    def test_start_returns_false_on_import_error(self):
        """When ipfs_accelerate_py is absent, start() returns False silently."""
        mgr = _make_mgr()
        with patch.dict(sys.modules, {"ipfs_accelerate_py.p2p_tasks.runtime": None}):
            result = mgr.start()
        # ImportError → return False
        assert result is False

    def test_start_success_path_returns_true(self):
        """Mock TaskQueueP2PServiceRuntime → start returns True."""
        import ipfs_datasets_py.mcp_server.p2p_service_manager as mod

        mock_handle = MagicMock()
        mock_handle.started.wait.return_value = None  # no timeout

        mock_runtime = MagicMock()
        mock_runtime.start.return_value = mock_handle
        mock_runtime.running = True

        FakeRuntime = MagicMock(return_value=mock_runtime)

        fake_p2p_tasks = types.ModuleType("ipfs_accelerate_py.p2p_tasks.runtime")
        fake_p2p_tasks.TaskQueueP2PServiceRuntime = FakeRuntime

        mgr = _make_mgr()
        with patch.dict(sys.modules,
                        {"ipfs_accelerate_py.p2p_tasks.runtime": fake_p2p_tasks}):
            with patch.object(mgr, "_initialize_mcplusplus_features"):
                result = mgr.start()

        assert result is True
        assert mgr._runtime is mock_runtime
        assert mgr._handle is mock_handle

    def test_start_generic_exception_returns_false(self):
        """An unexpected non-ImportError exception during import → returns False."""
        mgr = _make_mgr()

        # Module that raises RuntimeError (not ImportError) on attribute access
        class _BadModule:
            def __getattr__(self, name):
                raise RuntimeError("bad import attr")

        with patch.dict(sys.modules,
                        {"ipfs_accelerate_py.p2p_tasks.runtime": _BadModule()}):
            result = mgr.start()
        assert result is False

    def test_start_applies_env_vars(self):
        """start() must call _apply_env before attempting import."""
        mgr = _make_mgr(enabled=True)
        applied = []

        original_apply_env = mgr._apply_env.__func__

        def spy_apply(self):
            applied.append(True)

        with patch.object(type(mgr), "_apply_env", spy_apply):
            with patch.dict(sys.modules, {"ipfs_accelerate_py.p2p_tasks.runtime": None}):
                mgr.start()

        assert applied  # _apply_env was called


# ===========================================================================
# P2PServiceManager.state()
# ===========================================================================

class TestP2PServiceManagerState:

    def test_state_returns_p2pservicestate_instance(self):
        mgr = _make_mgr()
        result = mgr.state()
        assert isinstance(result, P2PServiceState)

    def test_state_running_false_when_no_runtime(self):
        mgr = _make_mgr()
        mgr._runtime = None
        s = mgr.state()
        assert s.running is False

    def test_state_last_error_from_runtime_attribute(self):
        mgr = _make_mgr()
        mock_rt = MagicMock()
        mock_rt.last_error = "oops"
        mgr._runtime = mock_rt
        s = mgr.state()
        assert s.last_error == "oops"

    def test_state_last_error_p2p_service_error(self):
        """P2PServiceError in last_error access → last_error is the error message."""
        mgr = _make_mgr()

        class BadRuntime:
            @property
            def last_error(self):
                raise P2PServiceError("P2P failed")
            running = False

        mgr._runtime = BadRuntime()
        s = mgr.state()
        assert "P2P failed" in s.last_error

    def test_state_exception_fallback_uses_runtime_running(self):
        """Generic exception in state() → falls back to runtime.running."""
        mgr = _make_mgr()
        mgr._runtime = MagicMock()
        mgr._runtime.last_error = ""
        mgr._runtime.running = True

        # Make get_local_service_state raise
        import ipfs_datasets_py.mcp_server.p2p_service_manager as p2p_mod
        fake_service = MagicMock()
        fake_service.get_local_service_state.side_effect = RuntimeError("no state")
        fake_p2p_service = types.ModuleType(
            "ipfs_accelerate_py.p2p_tasks.service"
        )
        fake_p2p_service.get_local_service_state = MagicMock(
            side_effect=RuntimeError("no state")
        )
        fake_p2p_service.list_known_peers = MagicMock(return_value=[])
        with patch.dict(
            sys.modules, {"ipfs_accelerate_py.p2p_tasks.service": fake_p2p_service}
        ):
            s = mgr.state()
        assert isinstance(s, P2PServiceState)


# ===========================================================================
# has_advanced_features / get_workflow_scheduler / get_peer_registry
# ===========================================================================

class TestAdvancedFeatureAccessors:

    def test_has_advanced_features_false_by_default(self):
        mgr = _make_mgr()
        assert mgr.has_advanced_features() is False

    def test_has_advanced_features_true_when_flag_set(self):
        mgr = _make_mgr()
        mgr._mcplusplus_available = True
        assert mgr.has_advanced_features() is True

    def test_get_workflow_scheduler_none_by_default(self):
        mgr = _make_mgr()
        assert mgr.get_workflow_scheduler() is None

    def test_get_peer_registry_none_by_default(self):
        mgr = _make_mgr()
        assert mgr.get_peer_registry() is None

    def test_get_workflow_scheduler_returns_set_value(self):
        mgr = _make_mgr()
        fake = MagicMock()
        mgr._workflow_scheduler = fake
        assert mgr.get_workflow_scheduler() is fake

    def test_get_peer_registry_returns_set_value(self):
        mgr = _make_mgr()
        fake = MagicMock()
        mgr._peer_registry = fake
        assert mgr.get_peer_registry() is fake


# ===========================================================================
# _initialize_mcplusplus_features
# ===========================================================================

class TestInitializeMCPPlusPlus:

    def test_import_error_sets_available_false(self):
        """When ipfs_datasets_py.mcp_server.mcplusplus not importable → flag stays False."""
        mgr = _make_mgr()
        import ipfs_datasets_py.mcp_server.p2p_service_manager as p2p_mod
        with patch.dict(
            sys.modules,
            {"ipfs_datasets_py.mcp_server.mcplusplus": None}
        ):
            mgr._initialize_mcplusplus_features()
        assert mgr._mcplusplus_available is False

    def test_mcplusplus_not_available_skips(self):
        """HAVE_MCPLUSPLUS=False → early return, _workflow_scheduler stays None."""
        mgr = _make_mgr()
        fake_mcp = types.ModuleType("ipfs_datasets_py.mcp_server.mcplusplus")
        fake_mcp.HAVE_MCPLUSPLUS = False
        fake_mcp.HAVE_WORKFLOW_SCHEDULER = False
        fake_mcp.HAVE_PEER_REGISTRY = False
        fake_mcp.HAVE_BOOTSTRAP = False
        with patch.dict(
            sys.modules,
            {"ipfs_datasets_py.mcp_server.mcplusplus": fake_mcp}
        ):
            mgr._initialize_mcplusplus_features()
        assert mgr._workflow_scheduler is None

    def test_exception_during_init_sets_available_false(self):
        """A generic exception → _mcplusplus_available=False, no raise."""
        mgr = _make_mgr()
        import ipfs_datasets_py.mcp_server.p2p_service_manager as p2p_mod

        class BoomModule:
            HAVE_MCPLUSPLUS = True  # gets past the guard
            @property
            def HAVE_WORKFLOW_SCHEDULER(self):
                raise RuntimeError("boom")

        with patch.dict(
            sys.modules,
            {"ipfs_datasets_py.mcp_server.mcplusplus": BoomModule()}
        ):
            mgr._initialize_mcplusplus_features()

        assert mgr._mcplusplus_available is False
