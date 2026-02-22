"""
Phase B2 — Unit tests for mcplusplus_taskqueue_tools.py

14 tools across 3 categories:
  Core: task_submit, task_status, task_cancel, task_list, task_priority, task_result
  Queue: queue_stats, queue_pause, queue_resume, queue_clear, task_retry
  Workers: worker_register, worker_unregister, worker_status
All async Trio-native.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# TestCoreTaskOperations
# ---------------------------------------------------------------------------
class TestTaskSubmit:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import task_submit
        result = _run(task_submit("task-1", "compute", {"data": 42}))
        assert isinstance(result, dict)

    def test_priority_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import task_submit
        result = _run(task_submit("task-2", "inference", {}, priority=2.0))
        assert isinstance(result, dict)

    def test_tags_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import task_submit
        result = _run(task_submit("task-3", "etl", {}, tags=["prod", "v2"]))
        assert isinstance(result, dict)


class TestTaskStatus:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import task_status
        result = _run(task_status("task-1"))
        assert isinstance(result, dict)

    def test_include_logs_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import task_status
        result = _run(task_status("task-1", include_logs=True))
        assert isinstance(result, dict)


class TestTaskList:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import task_list
        result = _run(task_list())
        assert isinstance(result, dict)

    def test_filter_params(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import task_list
        result = _run(task_list(status_filter="queued", tag_filter=["prod"], limit=5))
        assert isinstance(result, dict)


class TestTaskCancel:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import task_cancel
        result = _run(task_cancel("task-1"))
        assert isinstance(result, dict)

    def test_force_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import task_cancel
        result = _run(task_cancel("task-2", force=True))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestQueueManagement
# ---------------------------------------------------------------------------
class TestQueueStats:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import queue_stats
        result = _run(queue_stats())
        assert isinstance(result, dict)

    def test_include_worker_stats_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import queue_stats
        result = _run(queue_stats(include_worker_stats=True))
        assert isinstance(result, dict)

    def test_include_historical_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import queue_stats
        result = _run(queue_stats(include_historical=True))
        assert isinstance(result, dict)


class TestQueuePauseResume:
    def test_queue_pause_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import queue_pause
        result = _run(queue_pause())
        assert isinstance(result, dict)

    def test_queue_resume_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import queue_resume
        result = _run(queue_resume())
        assert isinstance(result, dict)

    def test_queue_clear_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import queue_clear
        result = _run(queue_clear(confirm=True))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestWorkerManagement
# ---------------------------------------------------------------------------
class TestWorkerManagement:
    def test_worker_register_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import worker_register
        result = _run(worker_register("worker-1", ["compute", "storage"]))
        assert isinstance(result, dict)

    def test_worker_unregister_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import worker_unregister
        result = _run(worker_unregister("worker-1"))
        assert isinstance(result, dict)

    def test_worker_status_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import worker_status
        result = _run(worker_status("worker-1"))
        assert isinstance(result, dict)
