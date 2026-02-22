"""
MCP++ Enhanced Workflow Tools — thin MCP wrappers for P2P workflow scheduling.

6 tools:
  1. workflow_submit       — Submit workflow to P2P network
  2. workflow_status       — Check workflow status
  3. workflow_cancel       — Cancel a running/queued workflow
  4. workflow_list         — List workflows with filtering
  5. workflow_dependencies — Get workflow dependency DAG
  6. workflow_result       — Retrieve completed workflow result

Business logic lives in ``tools/mcplusplus/workflow_engine.py``.
All tools are Trio-native (_mcp_runtime='trio').
"""

import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata, RUNTIME_TRIO
from ipfs_datasets_py.mcp_server.tools.mcplusplus.workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)
_engine = WorkflowEngine()


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_workflow", priority=8,
    timeout_seconds=90.0, retry_policy="exponential", io_intensive=True, cpu_intensive=True,
    mcp_description="Submit a workflow to the P2P network for distributed execution",
)
async def workflow_submit(
    workflow_id: str,
    name: str,
    steps: List[Dict[str, Any]],
    priority: float = 1.0,
    tags: Optional[List[str]] = None,
    dependencies: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Submit a workflow to the P2P network for distributed execution."""
    return await _engine.submit(workflow_id, name, steps, priority, tags, dependencies, metadata)

workflow_submit._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_workflow", priority=9,
    timeout_seconds=30.0, io_intensive=False,
    mcp_description="Check the status of a submitted workflow",
)
async def workflow_status(
    workflow_id: str,
    include_steps: bool = True,
    include_metrics: bool = False,
) -> Dict[str, Any]:
    """Check the status of a submitted workflow."""
    return await _engine.get_status(workflow_id, include_steps, include_metrics)

workflow_status._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_workflow", priority=10,
    timeout_seconds=20.0, io_intensive=False,
    mcp_description="Cancel a running or pending workflow",
)
async def workflow_cancel(
    workflow_id: str,
    reason: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Cancel a running or queued workflow."""
    return await _engine.cancel(workflow_id, reason, force)

workflow_cancel._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_workflow", priority=7,
    timeout_seconds=30.0, io_intensive=False,
    mcp_description="List all workflows with optional filtering",
)
async def workflow_list(
    status_filter: Optional[str] = None,
    peer_filter: Optional[str] = None,
    tag_filter: Optional[List[str]] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List workflows with optional filtering."""
    return await _engine.list_workflows(status_filter, peer_filter, tag_filter, limit, offset)

workflow_list._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_workflow", priority=7,
    timeout_seconds=15.0, io_intensive=False,
    mcp_description="Get dependency graph for a workflow",
)
async def workflow_dependencies(
    workflow_id: str,
    fmt: str = "json",
) -> Dict[str, Any]:
    """Get the dependency DAG (Directed Acyclic Graph) for a workflow."""
    return await _engine.get_dependencies(workflow_id, fmt)

workflow_dependencies._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_workflow", priority=8,
    timeout_seconds=20.0, io_intensive=False,
    mcp_description="Retrieve the result of a completed workflow",
)
async def workflow_result(
    workflow_id: str,
    include_outputs: bool = True,
    include_logs: bool = False,
) -> Dict[str, Any]:
    """Retrieve the result of a completed workflow."""
    return await _engine.get_result(workflow_id, include_outputs, include_logs)

workflow_result._mcp_runtime = "trio"  # type: ignore[attr-defined]


# MCP tool registration
TOOLS = [
    {"function": workflow_submit, "description": "Submit workflow to P2P network",
     "input_schema": {"type": "object", "properties": {
         "workflow_id": {"type": "string"}, "name": {"type": "string"},
         "steps": {"type": "array", "items": {"type": "object"}},
         "priority": {"type": "number"},
         "tags": {"type": "array", "items": {"type": "string"}},
         "dependencies": {"type": "array", "items": {"type": "string"}},
         "metadata": {"type": "object"}},
         "required": ["workflow_id", "name", "steps"]}},
    {"function": workflow_status, "description": "Check workflow execution status",
     "input_schema": {"type": "object", "properties": {
         "workflow_id": {"type": "string"}, "include_steps": {"type": "boolean"},
         "include_metrics": {"type": "boolean"}}, "required": ["workflow_id"]}},
    {"function": workflow_cancel, "description": "Cancel workflow execution",
     "input_schema": {"type": "object", "properties": {
         "workflow_id": {"type": "string"}, "reason": {"type": "string"},
         "force": {"type": "boolean"}}, "required": ["workflow_id"]}},
    {"function": workflow_list, "description": "List workflows with filtering",
     "input_schema": {"type": "object", "properties": {
         "status_filter": {"type": "string"}, "peer_filter": {"type": "string"},
         "tag_filter": {"type": "array", "items": {"type": "string"}},
         "limit": {"type": "integer"}, "offset": {"type": "integer"}}}},
    {"function": workflow_dependencies, "description": "Get workflow dependency DAG",
     "input_schema": {"type": "object", "properties": {
         "workflow_id": {"type": "string"}, "fmt": {"type": "string", "description": "Output format: json, dot, or mermaid"}},
         "required": ["workflow_id"]}},
    {"function": workflow_result, "description": "Get completed workflow result",
     "input_schema": {"type": "object", "properties": {
         "workflow_id": {"type": "string"}, "include_outputs": {"type": "boolean"},
         "include_logs": {"type": "boolean"}}, "required": ["workflow_id"]}},
]
