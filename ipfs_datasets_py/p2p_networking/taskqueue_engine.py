"""
Task Queue Engine — core P2P task queue operations.

Business logic extracted from mcplusplus_taskqueue_tools.py (1454 lines → thin wrapper).
All methods mirror the corresponding tool functions but live outside the MCP layer so
they can be used, tested, and imported independently.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional MCP++ import (graceful degradation)
# ---------------------------------------------------------------------------
try:
    from ipfs_datasets_py.mcp_server.mcplusplus import (
        task_queue,
        MCPLUSPLUS_AVAILABLE,
        TaskQueueConfig,
        create_task_queue_wrapper,
    )
except (ImportError, ModuleNotFoundError):
    MCPLUSPLUS_AVAILABLE = False
    task_queue = None
    TaskQueueConfig = None
    create_task_queue_wrapper = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unavailable(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Standard response when MCP++ task queue is not available."""
    base = {
        "success": False,
        "error": "MCP++ task queue not available",
        "message": "Install ipfs_accelerate_py for full P2P task queue support",
        "status": "unavailable",
    }
    if extra:
        base.update(extra)
    return base


def _no_wrapper(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Standard response when task queue wrapper cannot be created."""
    base = {"success": False, "error": "Failed to create task queue wrapper"}
    if extra:
        base.update(extra)
    return base


def _error(e: Exception, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Standard error response."""
    base = {"success": False, "error": str(e)}
    if extra:
        base.update(extra)
    return base


def _get_wrapper() -> Any:
    """Return a task queue wrapper, or None if MCP++ is unavailable."""
    if not MCPLUSPLUS_AVAILABLE or task_queue is None:
        return None
    if create_task_queue_wrapper is None:
        return None
    return create_task_queue_wrapper()


# ---------------------------------------------------------------------------
# TaskQueueEngine
# ---------------------------------------------------------------------------

class TaskQueueEngine:
    """Core task queue operations, independent of MCP tool layer."""

    # ------------------------------------------------------------------
    # Core task operations
    # ------------------------------------------------------------------

    async def submit(
        self,
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
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable({"task_id": task_id})
        try:
            result = await wrapper.submit_task(
                task_id=task_id,
                task_type=task_type,
                payload=payload,
                priority=priority,
                tags=tags or [],
                timeout=timeout,
                retry_policy=retry_policy or {},
                metadata=metadata or {},
            )
            return {
                "success": True,
                "task_id": result.get("task_id", task_id),
                "status": result.get("status", "queued"),
                "queue_position": result.get("queue_position", 0),
                "estimated_start_time": result.get("estimated_start_time"),
                "assigned_worker": result.get("assigned_worker"),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error submitting task %s: %s", task_id, e)
            return _error(e, {"task_id": task_id})

    async def get_status(
        self,
        task_id: str,
        include_logs: bool = False,
        include_metrics: bool = False,
    ) -> Dict[str, Any]:
        """Get the current status of a task in the P2P queue."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable({"task_id": task_id})
        try:
            result = await wrapper.get_task_status(
                task_id=task_id,
                include_logs=include_logs,
                include_metrics=include_metrics,
            )
            return {
                "success": True,
                "task_id": task_id,
                "status": result.get("status", "unknown"),
                "progress": result.get("progress", 0),
                "worker_id": result.get("worker_id"),
                "start_time": result.get("start_time"),
                "end_time": result.get("end_time"),
                "queue_position": result.get("queue_position"),
                "logs": result.get("logs") if include_logs else None,
                "metrics": result.get("metrics") if include_metrics else None,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error getting task status %s: %s", task_id, e)
            return _error(e, {"task_id": task_id})

    async def cancel(
        self,
        task_id: str,
        reason: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Cancel a queued or running task."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable({"task_id": task_id})
        try:
            result = await wrapper.cancel_task(task_id=task_id, reason=reason, force=force)
            return {
                "success": True,
                "task_id": task_id,
                "status": result.get("status", "cancelled"),
                "cancelled_at": result.get("cancelled_at"),
                "cleanup_required": result.get("cleanup_required", False),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error cancelling task %s: %s", task_id, e)
            return _error(e, {"task_id": task_id})

    async def list_tasks(
        self,
        status_filter: Optional[str] = None,
        worker_filter: Optional[str] = None,
        tag_filter: Optional[List[str]] = None,
        priority_min: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List tasks in the P2P queue with filtering."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return {**_unavailable(), "tasks": [], "total_count": 0, "returned_count": 0, "has_more": False}
        try:
            result = await wrapper.list_tasks(
                status_filter=status_filter,
                worker_filter=worker_filter,
                tag_filter=tag_filter or [],
                priority_min=priority_min,
                limit=limit,
                offset=offset,
            )
            tasks = result.get("tasks", [])
            total = result.get("total_count", 0)
            return {
                "success": True,
                "tasks": tasks,
                "total_count": total,
                "returned_count": len(tasks),
                "has_more": (offset + len(tasks)) < total,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error listing tasks: %s", e)
            return {**_error(e), "tasks": []}

    async def set_priority(
        self,
        task_id: str,
        new_priority: float,
        requeue: bool = True,
    ) -> Dict[str, Any]:
        """Set or update the priority of a queued task."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable({"task_id": task_id})
        try:
            result = await wrapper.update_task_priority(
                task_id=task_id, new_priority=new_priority, requeue=requeue
            )
            return {
                "success": True,
                "task_id": task_id,
                "old_priority": result.get("old_priority", 1.0),
                "new_priority": new_priority,
                "new_queue_position": result.get("new_queue_position"),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error updating task priority %s: %s", task_id, e)
            return _error(e, {"task_id": task_id})

    async def get_result(
        self,
        task_id: str,
        include_output: bool = True,
        include_logs: bool = False,
    ) -> Dict[str, Any]:
        """Get the result of a completed task."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable({"task_id": task_id})
        try:
            result = await wrapper.get_task_result(
                task_id=task_id, include_output=include_output, include_logs=include_logs
            )
            return {
                "success": True,
                "task_id": task_id,
                "status": result.get("status", "completed"),
                "result": result.get("result"),
                "output": result.get("output") if include_output else None,
                "logs": result.get("logs") if include_logs else None,
                "execution_time": result.get("execution_time", 0),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error getting task result %s: %s", task_id, e)
            return _error(e, {"task_id": task_id})

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    async def get_stats(
        self,
        include_worker_stats: bool = False,
        include_historical: bool = False,
    ) -> Dict[str, Any]:
        """Get statistics about the P2P task queue."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return {
                **_unavailable(),
                "queued_count": 0,
                "running_count": 0,
                "completed_count": 0,
                "failed_count": 0,
            }
        try:
            result = await wrapper.get_queue_stats(
                include_worker_stats=include_worker_stats,
                include_historical=include_historical,
            )
            return {
                "success": True,
                "queued_count": result.get("queued_count", 0),
                "running_count": result.get("running_count", 0),
                "completed_count": result.get("completed_count", 0),
                "failed_count": result.get("failed_count", 0),
                "average_wait_time": result.get("average_wait_time", 0),
                "average_execution_time": result.get("average_execution_time", 0),
                "throughput": result.get("throughput", 0),
                "worker_stats": result.get("worker_stats") if include_worker_stats else None,
                "historical": result.get("historical") if include_historical else None,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error getting queue stats: %s", e)
            return _error(e)

    async def pause(self, reason: Optional[str] = None) -> Dict[str, Any]:
        """Pause task queue processing."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable()
        try:
            result = await wrapper.pause_queue(reason=reason)
            return {
                "success": True,
                "status": "paused",
                "paused_at": result.get("paused_at"),
                "queued_tasks": result.get("queued_tasks", 0),
                "running_tasks": result.get("running_tasks", 0),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error pausing queue: %s", e)
            return _error(e)

    async def resume(self, reorder_by_priority: bool = True) -> Dict[str, Any]:
        """Resume task queue processing after pause."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable()
        try:
            result = await wrapper.resume_queue(reorder_by_priority=reorder_by_priority)
            return {
                "success": True,
                "status": "active",
                "resumed_at": result.get("resumed_at"),
                "queued_tasks": result.get("queued_tasks", 0),
                "reordered": result.get("reordered", False),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error resuming queue: %s", e)
            return _error(e)

    async def clear(
        self,
        status_filter: Optional[str] = None,
        confirm: bool = False,
    ) -> Dict[str, Any]:
        """Clear tasks from the queue (requires confirm=True)."""
        if not confirm:
            return {
                "success": False,
                "error": "Confirmation required (set confirm=True)",
                "message": "This operation will remove tasks from the queue",
            }
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable()
        try:
            result = await wrapper.clear_queue(status_filter=status_filter)
            return {
                "success": True,
                "cleared_count": result.get("cleared_count", 0),
                "remaining_count": result.get("remaining_count", 0),
                "cleared_at": result.get("cleared_at"),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error clearing queue: %s", e)
            return _error(e)

    async def retry(
        self,
        task_id: str,
        retry_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Retry a failed task with optional new configuration."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable({"task_id": task_id})
        try:
            result = await wrapper.retry_task(task_id=task_id, retry_config=retry_config or {})
            return {
                "success": True,
                "task_id": task_id,
                "retry_task_id": result.get("retry_task_id"),
                "retry_count": result.get("retry_count", 1),
                "queue_position": result.get("queue_position"),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error retrying task %s: %s", task_id, e)
            return _error(e, {"task_id": task_id})

    # ------------------------------------------------------------------
    # Worker management
    # ------------------------------------------------------------------

    async def register_worker(
        self,
        worker_id: str,
        capabilities: List[str],
        max_concurrent_tasks: int = 5,
        resource_limits: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Register as a worker node in the P2P task queue."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable({"worker_id": worker_id})
        try:
            result = await wrapper.register_worker(
                worker_id=worker_id,
                capabilities=capabilities,
                max_concurrent_tasks=max_concurrent_tasks,
                resource_limits=resource_limits or {},
                metadata=metadata or {},
            )
            return {
                "success": True,
                "worker_id": worker_id,
                "status": "active",
                "registered_at": result.get("registered_at"),
                "assigned_peers": result.get("assigned_peers", []),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error registering worker %s: %s", worker_id, e)
            return _error(e, {"worker_id": worker_id})

    async def unregister_worker(
        self,
        worker_id: str,
        graceful: bool = True,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """Unregister a worker node from the P2P task queue."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable({"worker_id": worker_id})
        try:
            result = await wrapper.unregister_worker(
                worker_id=worker_id, graceful=graceful, timeout=timeout
            )
            return {
                "success": True,
                "worker_id": worker_id,
                "status": "unregistered",
                "unregistered_at": result.get("unregistered_at"),
                "completed_tasks": result.get("completed_tasks", 0),
                "abandoned_tasks": result.get("abandoned_tasks", 0),
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error unregistering worker %s: %s", worker_id, e)
            return _error(e, {"worker_id": worker_id})

    async def get_worker_status(
        self,
        worker_id: str,
        include_tasks: bool = False,
        include_metrics: bool = False,
    ) -> Dict[str, Any]:
        """Get status and statistics for a worker node."""
        wrapper = _get_wrapper()
        if wrapper is None:
            return _unavailable({"worker_id": worker_id})
        try:
            result = await wrapper.get_worker_status(
                worker_id=worker_id,
                include_tasks=include_tasks,
                include_metrics=include_metrics,
            )
            return {
                "success": True,
                "worker_id": worker_id,
                "status": result.get("status", "unknown"),
                "running_tasks": result.get("running_tasks", 0),
                "completed_tasks": result.get("completed_tasks", 0),
                "failed_tasks": result.get("failed_tasks", 0),
                "tasks": result.get("tasks") if include_tasks else None,
                "metrics": result.get("metrics") if include_metrics else None,
            }
        except (OSError, ValueError, RuntimeError) as e:
            logger.error("Error getting worker status %s: %s", worker_id, e)
            return _error(e, {"worker_id": worker_id})
