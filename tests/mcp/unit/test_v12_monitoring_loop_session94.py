"""
v12 Session AJ94: monitoring._monitoring_loop + _cleanup_loop complete coverage.

Tests every exception branch of both loops:
  _monitoring_loop:
    - cancelled → breaks silently
    - MetricsCollectionError → logs + sleeps(60)
    - OSError → logs + sleeps(60)
    - Generic Exception → logs + sleeps(60)
  _cleanup_loop:
    - cancelled → breaks silently
    - MonitoringError → re-raised
    - IOError → logs + sleeps(3600)
    - Generic Exception → logs + sleeps(3600)

Strategy:
  Patch collector._collect_system_metrics to raise the desired exception on
  the first call.  Patch monitoring.anyio.sleep so that the first call
  (inside the exception handler) completes normally, and the second call
  (at the end of the while-True body, or on the next iteration) raises
  anyio.get_cancelled_exc_class() to exit the loop cleanly.
"""
from __future__ import annotations

import anyio
import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

pytestmark = pytest.mark.asyncio


# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_collector():
    """Return a fresh EnhancedMetricsCollector with enabled=False (no bg tasks)."""
    from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
    return EnhancedMetricsCollector(enabled=False)


async def _run_loop_once(loop_coro, *, max_iterations: int = 5):
    """Drive *loop_coro* inside a task-group that cancels after it exits."""
    with contextlib.suppress(Exception):
        async with anyio.create_task_group() as tg:
            tg.start_soon(loop_coro)
            # Give the loop coroutine a moment to execute one pass
            await anyio.sleep(0)
            tg.cancel_scope.cancel()


# ════════════════════════════════════════════════════════════════════════════
# _monitoring_loop branches
# ════════════════════════════════════════════════════════════════════════════

class TestMonitoringLoopCancelled:

    @pytest.mark.asyncio
    async def test_cancelled_exits_cleanly(self):
        """Cancellation should break the while-loop without raising."""
        col = _make_collector()
        Cancelled = anyio.get_cancelled_exc_class()

        call_count = 0

        async def raise_cancelled_once():
            nonlocal call_count
            call_count += 1
            raise Cancelled()

        with patch.object(col, "_collect_system_metrics", side_effect=raise_cancelled_once):
            with contextlib.suppress(Cancelled):
                await col._monitoring_loop()
        assert call_count == 1


class TestMonitoringLoopMetricsCollectionError:

    @pytest.mark.asyncio
    async def test_sleeps_60_on_metrics_error(self):
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod
        from ipfs_datasets_py.mcp_server.exceptions import MetricsCollectionError

        col = _make_collector()

        call_count = 0

        async def mock_collect():
            nonlocal call_count
            call_count += 1
            raise MetricsCollectionError("test error")

        sleep_calls = []
        Cancelled = anyio.get_cancelled_exc_class()

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) >= 1:
                raise Cancelled()

        with patch.object(col, "_collect_system_metrics", side_effect=mock_collect):
            with patch.object(mon_mod, "anyio") as mock_anyio:
                mock_anyio.get_cancelled_exc_class.return_value = Cancelled
                mock_anyio.sleep = mock_sleep
                with contextlib.suppress(Cancelled):
                    await col._monitoring_loop()

        # The loop should have called sleep(60)
        assert 60 in sleep_calls


class TestMonitoringLoopOSError:

    @pytest.mark.asyncio
    async def test_sleeps_60_on_os_error(self):
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod

        col = _make_collector()

        call_count = 0

        async def mock_collect():
            nonlocal call_count
            call_count += 1
            raise OSError("disk failure")

        sleep_calls = []
        Cancelled = anyio.get_cancelled_exc_class()

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) >= 1:
                raise Cancelled()

        with patch.object(col, "_collect_system_metrics", side_effect=mock_collect):
            with patch.object(mon_mod, "anyio") as mock_anyio:
                mock_anyio.get_cancelled_exc_class.return_value = Cancelled
                mock_anyio.sleep = mock_sleep
                with contextlib.suppress(Cancelled):
                    await col._monitoring_loop()

        assert 60 in sleep_calls


class TestMonitoringLoopGenericException:

    @pytest.mark.asyncio
    async def test_sleeps_60_on_unexpected_error(self):
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod

        col = _make_collector()

        async def mock_collect():
            raise RuntimeError("unexpected!")

        sleep_calls = []
        Cancelled = anyio.get_cancelled_exc_class()

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) >= 1:
                raise Cancelled()

        with patch.object(col, "_collect_system_metrics", side_effect=mock_collect):
            with patch.object(mon_mod, "anyio") as mock_anyio:
                mock_anyio.get_cancelled_exc_class.return_value = Cancelled
                mock_anyio.sleep = mock_sleep
                with contextlib.suppress(Cancelled):
                    await col._monitoring_loop()

        assert 60 in sleep_calls


class TestMonitoringLoopHappyPath:

    @pytest.mark.asyncio
    async def test_happy_path_calls_sleep_30(self):
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod

        col = _make_collector()
        Cancelled = anyio.get_cancelled_exc_class()

        async def mock_collect():
            pass  # success

        async def mock_check_health():
            pass

        async def mock_check_alerts():
            pass

        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)
            raise Cancelled()

        with patch.object(col, "_collect_system_metrics", side_effect=mock_collect):
            with patch.object(col, "_check_health", side_effect=mock_check_health):
                with patch.object(col, "_check_alerts", side_effect=mock_check_alerts):
                    with patch.object(mon_mod, "anyio") as mock_anyio:
                        mock_anyio.get_cancelled_exc_class.return_value = Cancelled
                        mock_anyio.sleep = mock_sleep
                        with contextlib.suppress(Cancelled):
                            await col._monitoring_loop()

        assert 30 in sleep_calls


# ════════════════════════════════════════════════════════════════════════════
# _cleanup_loop branches
# ════════════════════════════════════════════════════════════════════════════

class TestCleanupLoopCancelled:

    @pytest.mark.asyncio
    async def test_cancelled_exits_cleanly(self):
        col = _make_collector()
        Cancelled = anyio.get_cancelled_exc_class()

        call_count = 0

        async def raise_cancelled_once():
            nonlocal call_count
            call_count += 1
            raise Cancelled()

        with patch.object(col, "_cleanup_old_data", side_effect=raise_cancelled_once):
            with contextlib.suppress(Cancelled):
                await col._cleanup_loop()
        assert call_count == 1


class TestCleanupLoopMonitoringError:

    @pytest.mark.asyncio
    async def test_monitoring_error_reraises(self):
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod
        from ipfs_datasets_py.mcp_server.exceptions import MonitoringError

        col = _make_collector()

        async def mock_cleanup():
            raise MonitoringError("fatal cleanup error")

        with patch.object(col, "_cleanup_old_data", side_effect=mock_cleanup):
            with pytest.raises(MonitoringError):
                await col._cleanup_loop()


class TestCleanupLoopIOError:

    @pytest.mark.asyncio
    async def test_sleeps_3600_on_io_error(self):
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod

        col = _make_collector()

        async def mock_cleanup():
            raise IOError("fs read error")

        sleep_calls = []
        Cancelled = anyio.get_cancelled_exc_class()

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) >= 1:
                raise Cancelled()

        with patch.object(col, "_cleanup_old_data", side_effect=mock_cleanup):
            with patch.object(mon_mod, "anyio") as mock_anyio:
                mock_anyio.get_cancelled_exc_class.return_value = Cancelled
                mock_anyio.sleep = mock_sleep
                with contextlib.suppress(Cancelled):
                    await col._cleanup_loop()

        assert 3600 in sleep_calls


class TestCleanupLoopGenericException:

    @pytest.mark.asyncio
    async def test_sleeps_3600_on_generic_error(self):
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod

        col = _make_collector()

        async def mock_cleanup():
            raise ValueError("unexpected cleanup error")

        sleep_calls = []
        Cancelled = anyio.get_cancelled_exc_class()

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) >= 1:
                raise Cancelled()

        with patch.object(col, "_cleanup_old_data", side_effect=mock_cleanup):
            with patch.object(mon_mod, "anyio") as mock_anyio:
                mock_anyio.get_cancelled_exc_class.return_value = Cancelled
                mock_anyio.sleep = mock_sleep
                with contextlib.suppress(Cancelled):
                    await col._cleanup_loop()

        assert 3600 in sleep_calls


class TestCleanupLoopHappyPath:

    @pytest.mark.asyncio
    async def test_happy_path_calls_sleep_3600(self):
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod

        col = _make_collector()
        Cancelled = anyio.get_cancelled_exc_class()

        async def mock_cleanup():
            pass

        sleep_calls = []

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)
            raise Cancelled()

        with patch.object(col, "_cleanup_old_data", side_effect=mock_cleanup):
            with patch.object(mon_mod, "anyio") as mock_anyio:
                mock_anyio.get_cancelled_exc_class.return_value = Cancelled
                mock_anyio.sleep = mock_sleep
                with contextlib.suppress(Cancelled):
                    await col._cleanup_loop()

        assert 3600 in sleep_calls
