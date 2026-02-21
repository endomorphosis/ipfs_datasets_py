"""
Phase B2 — Unit tests for mcplusplus_workflow_tools.py

6 tools: workflow_submit, workflow_status, workflow_cancel,
         workflow_list, workflow_dependencies, workflow_result
All async Trio-native wrappers around WorkflowEngine.
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
# TestWorkflowSubmit
# ---------------------------------------------------------------------------
class TestWorkflowSubmit:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_submit
        result = _run(workflow_submit(
            "wf-1",
            "test workflow",
            [{"step_id": "s1", "task_type": "compute", "payload": {}}],
        ))
        assert isinstance(result, dict)

    def test_priority_tags_params(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_submit
        result = _run(workflow_submit(
            "wf-2", "my flow",
            [{"step_id": "s1", "task_type": "etl", "payload": {}}],
            priority=2.0,
            tags=["prod"],
        ))
        assert isinstance(result, dict)

    def test_dependencies_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_submit
        result = _run(workflow_submit(
            "wf-3", "dep flow",
            [{"step_id": "s1", "task_type": "compute", "payload": {}}],
            dependencies=["wf-1"],
        ))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestWorkflowStatus
# ---------------------------------------------------------------------------
class TestWorkflowStatus:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_status
        result = _run(workflow_status("wf-1"))
        assert isinstance(result, dict)

    def test_include_steps_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_status
        result = _run(workflow_status("wf-1", include_steps=False))
        assert isinstance(result, dict)

    def test_include_metrics_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_status
        result = _run(workflow_status("wf-1", include_metrics=True))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestWorkflowCancel
# ---------------------------------------------------------------------------
class TestWorkflowCancel:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_cancel
        result = _run(workflow_cancel("wf-1"))
        assert isinstance(result, dict)

    def test_force_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_cancel
        result = _run(workflow_cancel("wf-1", reason="timeout", force=True))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestWorkflowList
# ---------------------------------------------------------------------------
class TestWorkflowList:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_list
        result = _run(workflow_list())
        assert isinstance(result, dict)

    def test_filter_params(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_list
        result = _run(workflow_list(status_filter="running", tag_filter=["prod"], limit=5))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestWorkflowDependencies
# ---------------------------------------------------------------------------
class TestWorkflowDependencies:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_dependencies
        result = _run(workflow_dependencies("wf-1"))
        assert isinstance(result, dict)

    def test_fmt_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_dependencies
        result = _run(workflow_dependencies("wf-1", fmt="dot"))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestWorkflowResult
# ---------------------------------------------------------------------------
class TestWorkflowResult:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_result
        result = _run(workflow_result("wf-1"))
        assert isinstance(result, dict)

    def test_include_logs_param(self):
        from ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools import workflow_result
        result = _run(workflow_result("wf-1", include_logs=True, include_outputs=False))
        assert isinstance(result, dict)
