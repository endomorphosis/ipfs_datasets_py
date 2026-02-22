"""
Phase B2 unit tests for p2p_tools/p2p_tools.py
"""
from __future__ import annotations
import sys
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# Ensure the submodule is importable by its full dotted path
import importlib
try:
    _p2p_mod = importlib.import_module(
        "ipfs_datasets_py.mcp_server.tools.p2p_tools.p2p_tools"
    )
    P2P_IMPORTABLE = True
except Exception:
    P2P_IMPORTABLE = False

pytestmark = pytest.mark.skipif(
    not P2P_IMPORTABLE,
    reason="p2p_tools.p2p_tools not importable in this environment",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_p2p():
    return importlib.import_module("ipfs_datasets_py.mcp_server.tools.p2p_tools.p2p_tools")


# ---------------------------------------------------------------------------
# p2p_service_status
# ---------------------------------------------------------------------------

class TestP2pServiceStatus:
    """Tests for p2p_service_status."""

    def test_returns_dict_when_run_in_trio_raises(self):
        """When run_in_trio raises, p2p_service_status returns a graceful dict."""
        mod = _get_p2p()
        orig = mod.run_in_trio
        try:
            mod.run_in_trio = lambda fn, *a, **kw: (_ for _ in ()).throw(
                RuntimeError("trio unavailable")
            )
            result = mod.p2p_service_status()
            assert isinstance(result, dict)
        finally:
            mod.run_in_trio = orig

    def test_structure_contains_recognisable_key(self):
        """Response always contains at least one of status/error/degraded_mode."""
        mod = _get_p2p()
        orig = mod.run_in_trio
        try:
            mod.run_in_trio = lambda fn, *a, **kw: (_ for _ in ()).throw(
                RuntimeError("trio unavailable")
            )
            result = mod.p2p_service_status()
            assert "degraded_mode" in result or "error" in result or "status" in result
        finally:
            mod.run_in_trio = orig


# ---------------------------------------------------------------------------
# p2p_cache operations
# ---------------------------------------------------------------------------

class TestP2pCache:
    """Tests for P2P cache operations — return dicts even in degraded mode."""

    def _patch_trio(self, mod):
        """Context manager: replace run_in_trio with a raiser."""
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            orig = mod.run_in_trio
            mod.run_in_trio = lambda fn, *a, **kw: (_ for _ in ()).throw(
                RuntimeError("unavailable")
            )
            try:
                yield
            finally:
                mod.run_in_trio = orig

        return _ctx()

    def test_cache_get_returns_dict(self):
        mod = _get_p2p()
        with self._patch_trio(mod):
            result = mod.p2p_cache_get(key="test_key")
        assert isinstance(result, dict)

    def test_cache_set_returns_dict(self):
        mod = _get_p2p()
        with self._patch_trio(mod):
            result = mod.p2p_cache_set(key="k", value={"x": 1})
        assert isinstance(result, dict)

    def test_cache_has_returns_dict(self):
        mod = _get_p2p()
        with self._patch_trio(mod):
            result = mod.p2p_cache_has(key="k")
        assert isinstance(result, dict)

    def test_cache_delete_returns_dict(self):
        mod = _get_p2p()
        with self._patch_trio(mod):
            result = mod.p2p_cache_delete(key="k")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# p2p_task_submit / p2p_task_get
# ---------------------------------------------------------------------------

class TestP2pTasks:
    """Tests for P2P task queue operations."""

    def _patch_trio(self, mod):
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            orig = mod.run_in_trio
            mod.run_in_trio = lambda fn, *a, **kw: (_ for _ in ()).throw(
                RuntimeError("unavailable")
            )
            try:
                yield
            finally:
                mod.run_in_trio = orig

        return _ctx()

    def test_task_submit_returns_dict(self):
        mod = _get_p2p()
        with self._patch_trio(mod):
            result = mod.p2p_task_submit(task_type="inference", payload={"text": "hello"})
        assert isinstance(result, dict)

    def test_task_get_returns_dict(self):
        mod = _get_p2p()
        with self._patch_trio(mod):
            result = mod.p2p_task_get(task_id="tid_123")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# p2p_remote_status (async)
# ---------------------------------------------------------------------------

class TestP2pRemoteStatus:
    """Tests for async remote P2P operations."""

    @pytest.mark.asyncio
    async def test_remote_status_returns_dict(self):
        """p2p_remote_status returns a dict without requiring a live peer."""
        mod = _get_p2p()
        mock_queue = MagicMock()
        mock_queue.remote_status = AsyncMock(return_value={"status": "ok", "peer_id": "p1"})

        orig = mod._remote_queue
        try:
            mod._remote_queue = lambda **kw: mock_queue
            result = await mod.p2p_remote_status(peer_id="p1")
        finally:
            mod._remote_queue = orig

        assert isinstance(result, dict)
