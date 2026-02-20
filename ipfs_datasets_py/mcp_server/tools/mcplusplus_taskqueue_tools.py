"""
MCP++ Task Queue Tools — thin MCP wrappers for P2P task queue operations.

14 tools across three categories:
  1. Core Task Operations (6): task_submit, task_status, task_cancel,
     task_list, task_priority, task_result
  2. Queue Management (5): queue_stats, queue_pause, queue_resume,
     queue_clear, task_retry
  3. Worker Management (3): worker_register, worker_unregister, worker_status

Business logic lives in ``tools/mcplusplus/taskqueue_engine.py``.
All tools are Trio-native (_mcp_runtime='trio').
"""

import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata, RUNTIME_TRIO
from ipfs_datasets_py.mcp_server.tools.mcplusplus.taskqueue_engine import TaskQueueEngine

logger = logging.getLogger(__name__)
_engine = TaskQueueEngine()

# ============================================================================
# CORE TASK OPERATIONS (6 tools)
# ============================================================================

@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_taskqueue", priority=8,
    timeout_seconds=60.0, retry_policy="exponential", io_intensive=True,
    mcp_description="Submit a task to the P2P task queue for distributed execution",
)
async def task_submit(
    task_id: str,
    task_type: str,
    payload: Dict[str, Any],
    priority: float = 1.0,
    tags: Optional[List[str]] = None,
    timeout: Optional[int] = None,
    retry_policy: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Submit a task to the P2P task queue for distributed execution."""
    return await _engine.submit(task_id, task_type, payload, priority, tags, timeout, retry_policy, metadata)

task_submit._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_taskqueue", priority=9,
    timeout_seconds=10.0, io_intensive=False,
    mcp_description="Get the current status of a submitted task",
)
async def task_status(
    task_id: str,
    include_logs: bool = False,
    include_metrics: bool = False,
) -> Dict[str, Any]:
    """Get the current status of a task in the P2P queue."""
    return await _engine.get_status(task_id, include_logs, include_metrics)

task_status._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_taskqueue", priority=10,
    timeout_seconds=15.0, io_intensive=False,
    mcp_description="Cancel a pending or running task",
)
async def task_cancel(
    task_id: str,
    reason: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Cancel a queued or running task in the P2P queue."""
    return await _engine.cancel(task_id, reason, force)

task_cancel._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_taskqueue", priority=7,
    timeout_seconds=30.0, io_intensive=False,
    mcp_description="List all tasks with optional filtering",
)
async def task_list(
    status_filter: Optional[str] = None,
    worker_filter: Optional[str] = None,
    tag_filter: Optional[List[str]] = None,
    priority_min: Optional[float] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """List tasks in the P2P queue with advanced filtering."""
    return await _engine.list_tasks(status_filter, worker_filter, tag_filter, priority_min, limit, offset)

task_list._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_taskqueue", priority=8,
    timeout_seconds=10.0, io_intensive=False,
    mcp_description="Get or update the priority of a task",
)
async def task_priority(
    task_id: str,
    new_priority: float,
    requeue: bool = True,
) -> Dict[str, Any]:
    """Set or update the priority of a queued task."""
    return await _engine.set_priority(task_id, new_priority, requeue)

task_priority._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_taskqueue", priority=8,
    timeout_seconds=15.0, io_intensive=False,
    mcp_description="Retrieve the result of a completed task",
)
async def task_result(
    task_id: str,
    include_output: bool = True,
    include_logs: bool = False,
) -> Dict[str, Any]:
    """Get the result of a completed task."""
    return await _engine.get_result(task_id, include_output, include_logs)

task_result._mcp_runtime = "trio"  # type: ignore[attr-defined]


# ============================================================================
# QUEUE MANAGEMENT (5 tools)
# ============================================================================

@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_queue_mgmt", priority=7,
    timeout_seconds=10.0, io_intensive=False,
    mcp_description="Get comprehensive queue statistics",
)
async def queue_stats(
    include_worker_stats: bool = False,
    include_historical: bool = False,
) -> Dict[str, Any]:
    """Get statistics about the P2P task queue."""
    return await _engine.get_stats(include_worker_stats, include_historical)

queue_stats._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_queue_mgmt", priority=9,
    timeout_seconds=10.0, io_intensive=False,
    mcp_description="Pause task queue processing",
)
async def queue_pause(reason: Optional[str] = None) -> Dict[str, Any]:
    """Pause task queue processing."""
    return await _engine.pause(reason)

queue_pause._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_queue_mgmt", priority=9,
    timeout_seconds=10.0, io_intensive=False,
    mcp_description="Resume paused task queue processing",
)
async def queue_resume(reorder_by_priority: bool = True) -> Dict[str, Any]:
    """Resume task queue processing after pause."""
    return await _engine.resume(reorder_by_priority)

queue_resume._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_queue_mgmt", priority=10,
    timeout_seconds=20.0, io_intensive=False,
    mcp_description="Clear all tasks from the queue",
)
async def queue_clear(
    status_filter: Optional[str] = None,
    confirm: bool = False,
) -> Dict[str, Any]:
    """Clear tasks from the queue (requires confirm=True)."""
    return await _engine.clear(status_filter, confirm)

queue_clear._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_taskqueue", priority=8,
    timeout_seconds=15.0, retry_policy="exponential", io_intensive=False,
    mcp_description="Retry a failed task",
)
async def task_retry(
    task_id: str,
    retry_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Retry a failed task with optional new configuration."""
    return await _engine.retry(task_id, retry_config)

task_retry._mcp_runtime = "trio"  # type: ignore[attr-defined]


# ============================================================================
# WORKER MANAGEMENT (3 tools)
# ============================================================================

@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_worker_mgmt", priority=9,
    timeout_seconds=20.0, io_intensive=False,
    mcp_description="Register a worker node for task execution",
)
async def worker_register(
    worker_id: str,
    capabilities: List[str],
    max_concurrent_tasks: int = 5,
    resource_limits: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Register as a worker node in the P2P task queue."""
    return await _engine.register_worker(worker_id, capabilities, max_concurrent_tasks, resource_limits, metadata)

worker_register._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_worker_mgmt", priority=9,
    timeout_seconds=15.0, io_intensive=False,
    mcp_description="Unregister a worker node",
)
async def worker_unregister(
    worker_id: str,
    graceful: bool = True,
    timeout: int = 300,
) -> Dict[str, Any]:
    """Unregister a worker node from the P2P task queue."""
    return await _engine.unregister_worker(worker_id, graceful, timeout)

worker_unregister._mcp_runtime = "trio"  # type: ignore[attr-defined]


@tool_metadata(
    runtime=RUNTIME_TRIO, requires_p2p=True, category="p2p_worker_mgmt", priority=7,
    timeout_seconds=10.0, io_intensive=False,
    mcp_description="Get status of worker nodes",
)
async def worker_status(
    worker_id: str,
    include_tasks: bool = False,
    include_metrics: bool = False,
) -> Dict[str, Any]:
    """Get status and statistics for a worker node."""
    return await _engine.get_worker_status(worker_id, include_tasks, include_metrics)

worker_status._mcp_runtime = "trio"  # type: ignore[attr-defined]


# ============================================================================
# MCP TOOL REGISTRATION
# ============================================================================

TOOLS = [
    {"function": task_submit, "description": "Submit task to P2P queue for distributed execution",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "string"}, "task_type": {"type": "string"},
         "payload": {"type": "object"}, "priority": {"type": "number"},
         "tags": {"type": "array", "items": {"type": "string"}},
         "timeout": {"type": "integer"}, "retry_policy": {"type": "object"},
         "metadata": {"type": "object"}}, "required": ["task_id", "task_type", "payload"]}},
    {"function": task_status, "description": "Get task execution status and progress",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "string"}, "include_logs": {"type": "boolean"},
         "include_metrics": {"type": "boolean"}}, "required": ["task_id"]}},
    {"function": task_cancel, "description": "Cancel queued or running task",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "string"}, "reason": {"type": "string"},
         "force": {"type": "boolean"}}, "required": ["task_id"]}},
    {"function": task_list, "description": "List tasks with advanced filtering",
     "input_schema": {"type": "object", "properties": {
         "status_filter": {"type": "string"}, "worker_filter": {"type": "string"},
         "tag_filter": {"type": "array", "items": {"type": "string"}},
         "priority_min": {"type": "number"}, "limit": {"type": "integer"},
         "offset": {"type": "integer"}}}},
    {"function": task_priority, "description": "Set or update task priority",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "string"}, "new_priority": {"type": "number"},
         "requeue": {"type": "boolean"}}, "required": ["task_id", "new_priority"]}},
    {"function": task_result, "description": "Get completed task result and output",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "string"}, "include_output": {"type": "boolean"},
         "include_logs": {"type": "boolean"}}, "required": ["task_id"]}},
    {"function": queue_stats, "description": "Get queue statistics and metrics",
     "input_schema": {"type": "object", "properties": {
         "include_worker_stats": {"type": "boolean"}, "include_historical": {"type": "boolean"}}}},
    {"function": queue_pause, "description": "Pause queue processing",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}}},
    {"function": queue_resume, "description": "Resume queue processing",
     "input_schema": {"type": "object", "properties": {"reorder_by_priority": {"type": "boolean"}}}},
    {"function": queue_clear, "description": "Clear tasks from queue",
     "input_schema": {"type": "object", "properties": {
         "status_filter": {"type": "string"}, "confirm": {"type": "boolean"}},
         "required": ["confirm"]}},
    {"function": task_retry, "description": "Retry failed task with optional new configuration",
     "input_schema": {"type": "object", "properties": {
         "task_id": {"type": "string"}, "retry_config": {"type": "object"}},
         "required": ["task_id"]}},
    {"function": worker_register, "description": "Register as worker node",
     "input_schema": {"type": "object", "properties": {
         "worker_id": {"type": "string"},
         "capabilities": {"type": "array", "items": {"type": "string"}},
         "max_concurrent_tasks": {"type": "integer"}, "resource_limits": {"type": "object"},
         "metadata": {"type": "object"}}, "required": ["worker_id", "capabilities"]}},
    {"function": worker_unregister, "description": "Unregister worker node",
     "input_schema": {"type": "object", "properties": {
         "worker_id": {"type": "string"}, "graceful": {"type": "boolean"},
         "timeout": {"type": "integer"}}, "required": ["worker_id"]}},
    {"function": worker_status, "description": "Get worker status and metrics",
     "input_schema": {"type": "object", "properties": {
         "worker_id": {"type": "string"}, "include_tasks": {"type": "boolean"},
         "include_metrics": {"type": "boolean"}}, "required": ["worker_id"]}},
]
