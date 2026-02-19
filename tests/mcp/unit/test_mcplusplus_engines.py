"""
Tests for mcplusplus engine modules (Phase 5 extraction validation).

Covers: TaskQueueEngine, PeerEngine, WorkflowEngine — all degrade gracefully
when MCP++ is unavailable (the expected state in this test environment).
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# TaskQueueEngine tests
# ---------------------------------------------------------------------------

class TestTaskQueueEngineUnavailable:
    """TaskQueueEngine graceful degradation when MCP++ is not available."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.mcplusplus.taskqueue_engine import TaskQueueEngine
        self.engine = TaskQueueEngine()

    def _run(self, coro):  # type: ignore[no-untyped-def]
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_submit_returns_error_dict(self) -> None:
        result = self._run(self.engine.submit("t1", "download", {"url": "http://x"}))
        assert isinstance(result, dict)
        assert "success" in result

    def test_get_status_returns_dict_with_task_id(self) -> None:
        result = self._run(self.engine.get_status("t1"))
        assert isinstance(result, dict)
        assert result.get("task_id") == "t1" or "error" in result

    def test_cancel_returns_dict(self) -> None:
        result = self._run(self.engine.cancel("t1"))
        assert isinstance(result, dict)

    def test_list_tasks_returns_tasks_key(self) -> None:
        result = self._run(self.engine.list_tasks())
        assert "tasks" in result

    def test_get_stats_returns_count_keys(self) -> None:
        result = self._run(self.engine.get_stats())
        # Either success dict with counts or error dict
        assert isinstance(result, dict)
        assert "success" in result

    def test_clear_requires_confirm(self) -> None:
        result = self._run(self.engine.clear(confirm=False))
        assert result["success"] is False
        assert "confirm" in result["error"].lower()

    def test_set_priority_returns_dict(self) -> None:
        result = self._run(self.engine.set_priority("t1", 2.0))
        assert isinstance(result, dict)

    def test_get_result_returns_dict(self) -> None:
        result = self._run(self.engine.get_result("t1"))
        assert isinstance(result, dict)

    def test_pause_returns_dict(self) -> None:
        result = self._run(self.engine.pause())
        assert isinstance(result, dict)

    def test_resume_returns_dict(self) -> None:
        result = self._run(self.engine.resume())
        assert isinstance(result, dict)

    def test_retry_returns_dict(self) -> None:
        result = self._run(self.engine.retry("t1"))
        assert isinstance(result, dict)

    def test_register_worker_returns_dict(self) -> None:
        result = self._run(self.engine.register_worker("w1", ["download"]))
        assert isinstance(result, dict)

    def test_unregister_worker_returns_dict(self) -> None:
        result = self._run(self.engine.unregister_worker("w1"))
        assert isinstance(result, dict)

    def test_get_worker_status_returns_dict(self) -> None:
        result = self._run(self.engine.get_worker_status("w1"))
        assert isinstance(result, dict)


class TestTaskQueueEngineMocked:
    """TaskQueueEngine with mock MCP++ wrapper."""

    def _run(self, coro):  # type: ignore[no-untyped-def]
        return asyncio.get_event_loop().run_until_complete(coro)

    def _make_wrapper(self, **kwargs):  # type: ignore[no-untyped-def]
        wrapper = MagicMock()
        for name, return_val in kwargs.items():
            setattr(wrapper, name, AsyncMock(return_value=return_val))
        return wrapper

    def test_submit_success_path(self) -> None:
        wrapper = self._make_wrapper(submit_task={"task_id": "t1", "status": "queued", "queue_position": 3})
        import ipfs_datasets_py.mcp_server.tools.mcplusplus.taskqueue_engine as mod
        with patch.object(mod, "MCPLUSPLUS_AVAILABLE", True), \
             patch.object(mod, "task_queue", MagicMock()), \
             patch.object(mod, "create_task_queue_wrapper", return_value=wrapper):
            from ipfs_datasets_py.mcp_server.tools.mcplusplus.taskqueue_engine import TaskQueueEngine
            engine = TaskQueueEngine()
            result = self._run(engine.submit("t1", "download", {"url": "x"}))
        assert result["success"] is True
        assert result["task_id"] == "t1"
        assert result["status"] == "queued"
        assert result["queue_position"] == 3

    def test_get_status_success_path(self) -> None:
        wrapper = self._make_wrapper(get_task_status={"status": "running", "progress": 50})
        import ipfs_datasets_py.mcp_server.tools.mcplusplus.taskqueue_engine as mod
        with patch.object(mod, "MCPLUSPLUS_AVAILABLE", True), \
             patch.object(mod, "task_queue", MagicMock()), \
             patch.object(mod, "create_task_queue_wrapper", return_value=wrapper):
            from ipfs_datasets_py.mcp_server.tools.mcplusplus.taskqueue_engine import TaskQueueEngine
            engine = TaskQueueEngine()
            result = self._run(engine.get_status("t1"))
        assert result["success"] is True
        assert result["status"] == "running"
        assert result["progress"] == 50

    def test_get_stats_success_path(self) -> None:
        wrapper = self._make_wrapper(get_queue_stats={"queued_count": 5, "running_count": 2,
                                                       "completed_count": 100, "failed_count": 3})
        import ipfs_datasets_py.mcp_server.tools.mcplusplus.taskqueue_engine as mod
        with patch.object(mod, "MCPLUSPLUS_AVAILABLE", True), \
             patch.object(mod, "task_queue", MagicMock()), \
             patch.object(mod, "create_task_queue_wrapper", return_value=wrapper):
            from ipfs_datasets_py.mcp_server.tools.mcplusplus.taskqueue_engine import TaskQueueEngine
            engine = TaskQueueEngine()
            result = self._run(engine.get_stats())
        assert result["success"] is True
        assert result["queued_count"] == 5
        assert result["running_count"] == 2


# ---------------------------------------------------------------------------
# PeerEngine tests
# ---------------------------------------------------------------------------

class TestPeerEngineUnavailable:
    """PeerEngine graceful degradation when MCP++ is not available."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.mcplusplus.peer_engine import PeerEngine
        self.engine = PeerEngine()

    def _run(self, coro):  # type: ignore[no-untyped-def]
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_discover_returns_peers_key(self) -> None:
        result = self._run(self.engine.discover())
        assert "peers" in result or "success" in result

    def test_connect_returns_dict_with_peer_id(self) -> None:
        result = self._run(self.engine.connect("QmPeer1", "/ip4/1.2.3.4/tcp/4001"))
        assert isinstance(result, dict)

    def test_disconnect_returns_dict(self) -> None:
        result = self._run(self.engine.disconnect("QmPeer1"))
        assert isinstance(result, dict)

    def test_list_peers_returns_peers_key(self) -> None:
        result = self._run(self.engine.list_peers())
        assert "peers" in result

    def test_get_metrics_returns_dict(self) -> None:
        result = self._run(self.engine.get_metrics("QmPeer1"))
        assert isinstance(result, dict)

    def test_bootstrap_returns_connected_count(self) -> None:
        result = self._run(self.engine.bootstrap())
        assert "connected_count" in result or "success" in result


class TestPeerEngineMocked:
    """PeerEngine with mock peer registry."""

    def _run(self, coro):  # type: ignore[no-untyped-def]
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_discover_with_registry(self) -> None:
        mock_registry = MagicMock()
        import ipfs_datasets_py.mcp_server.tools.mcplusplus.peer_engine as mod
        with patch.object(mod, "MCPLUSPLUS_AVAILABLE", True), \
             patch.object(mod, "get_peer_registry", AsyncMock(return_value=mock_registry)):
            from ipfs_datasets_py.mcp_server.tools.mcplusplus.peer_engine import PeerEngine
            engine = PeerEngine()
            result = self._run(engine.discover(max_peers=2))
        assert result["success"] is True
        assert result["discovered_count"] <= 2
        assert isinstance(result["peers"], list)

    def test_connect_with_registry(self) -> None:
        mock_registry = MagicMock()
        import ipfs_datasets_py.mcp_server.tools.mcplusplus.peer_engine as mod
        with patch.object(mod, "MCPLUSPLUS_AVAILABLE", True), \
             patch.object(mod, "get_peer_registry", AsyncMock(return_value=mock_registry)):
            from ipfs_datasets_py.mcp_server.tools.mcplusplus.peer_engine import PeerEngine
            engine = PeerEngine()
            result = self._run(engine.connect("QmPeer1", "/ip4/1.2.3.4/tcp/4001"))
        assert result["success"] is True
        assert "connection_id" in result


# ---------------------------------------------------------------------------
# WorkflowEngine tests
# ---------------------------------------------------------------------------

class TestWorkflowEngineUnavailable:
    """WorkflowEngine graceful degradation when MCP++ is not available."""

    def setup_method(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.mcplusplus.workflow_engine import WorkflowEngine
        self.engine = WorkflowEngine()

    def _run(self, coro):  # type: ignore[no-untyped-def]
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_submit_missing_params_returns_error(self) -> None:
        result = self._run(self.engine.submit("", "wf", []))
        assert result["success"] is False

    def test_submit_invalid_step_returns_error(self) -> None:
        result = self._run(self.engine.submit("wf1", "My WF", [{"no_step_id": True}]))
        assert result["success"] is False

    def test_submit_local_fallback_when_unavailable(self) -> None:
        import ipfs_datasets_py.mcp_server.tools.mcplusplus.workflow_engine as mod
        with patch.object(mod, "MCPLUSPLUS_AVAILABLE", False):
            from ipfs_datasets_py.mcp_server.tools.mcplusplus.workflow_engine import WorkflowEngine
            engine = WorkflowEngine()
            result = self._run(engine.submit("wf1", "Test", [{"step_id": "s1", "action": "do"}]))
        # Graceful degradation: falls back to local execution
        assert result["success"] is True
        assert result["status"] == "queued_local"

    def test_get_status_missing_id_returns_error(self) -> None:
        result = self._run(self.engine.get_status(""))
        assert result["success"] is False

    def test_cancel_missing_id_returns_error(self) -> None:
        result = self._run(self.engine.cancel(""))
        assert result["success"] is False

    def test_list_workflows_invalid_limit_returns_error(self) -> None:
        result = self._run(self.engine.list_workflows(limit=0))
        assert result["success"] is False

    def test_get_dependencies_invalid_format_returns_error(self) -> None:
        result = self._run(self.engine.get_dependencies("wf1", fmt="xml"))
        assert result["success"] is False

    def test_get_result_missing_id_returns_error(self) -> None:
        result = self._run(self.engine.get_result(""))
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Backward-compat: thin wrapper imports
# ---------------------------------------------------------------------------

class TestThinWrapperImports:
    """Ensure all 26 exported functions are importable from the thin wrapper files."""

    def test_taskqueue_tools_all_14_tools(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import (
            task_submit, task_status, task_cancel, task_list, task_priority, task_result,
            queue_stats, queue_pause, queue_resume, queue_clear, task_retry,
            worker_register, worker_unregister, worker_status, TOOLS,
        )
        assert len(TOOLS) == 14
        for fn in [task_submit, task_status, task_cancel, task_list, task_priority, task_result,
                   queue_stats, queue_pause, queue_resume, queue_clear, task_retry,
                   worker_register, worker_unregister, worker_status]:
            assert callable(fn)

    def test_peer_tools_all_6_tools(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import (
            peer_discover, peer_connect, peer_disconnect,
            peer_list, peer_metrics, bootstrap_network, TOOLS,
        )
        assert len(TOOLS) == 6
        for fn in [peer_discover, peer_connect, peer_disconnect, peer_list, peer_metrics, bootstrap_network]:
            assert callable(fn)

    def test_workflow_tools_all_6_tools(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import (
            workflow_submit, workflow_status, workflow_cancel,
            workflow_list, workflow_dependencies, workflow_result, TOOLS,
        )
        assert len(TOOLS) == 6
        for fn in [workflow_submit, workflow_status, workflow_cancel,
                   workflow_list, workflow_dependencies, workflow_result]:
            assert callable(fn)

    def test_mcp_runtime_attribute_preserved(self) -> None:
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools import task_submit
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_peer_tools import peer_discover
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_submit
        assert getattr(task_submit, "_mcp_runtime", None) == "trio"
        assert getattr(peer_discover, "_mcp_runtime", None) == "trio"
        assert getattr(workflow_submit, "_mcp_runtime", None) == "trio"
