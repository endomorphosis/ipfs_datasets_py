"""
MCP++ Task Queue Tools

This module provides 14 comprehensive tools for managing P2P task queues via MCP++ integration.
All tools integrate with the Phase 1 MCP++ wrapper layer and support graceful degradation
when MCP++ is unavailable.

Tools are organized into three categories:
1. Core Task Operations (6 tools): submit, status, cancel, list, priority, result
2. Queue Management (5 tools): stats, pause, resume, clear, retry
3. Worker Management (3 tools): register, unregister, status

All tools are marked as Trio-native (_mcp_runtime='trio') for Phase 3 runtime routing.

Author: MCP++ Integration Team
Date: 2026-02-17
Phase: 2.2 (Task Queue Tools)
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union
from datetime import datetime

# Import tool metadata decorator
from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata, RUNTIME_TRIO

# Import Phase 1 MCP++ wrappers
try:
    from ipfs_datasets_py.mcp_server.mcplusplus import (
        task_queue,
        MCPLUSPLUS_AVAILABLE,
        TaskQueueConfig,
        create_task_queue_wrapper
    )
except ImportError:
    MCPLUSPLUS_AVAILABLE = False
    task_queue = None
    TaskQueueConfig = None
    create_task_queue_wrapper = None

logger = logging.getLogger(__name__)

# ============================================================================
# CORE TASK OPERATIONS (6 tools)
# ============================================================================

@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_taskqueue",
    priority=8,
    timeout_seconds=60.0,
    retry_policy="exponential",
    io_intensive=True,
    mcp_description="Submit a task to the P2P task queue for distributed execution"
)
async def task_submit(
    task_id: str,
    task_type: str,
    payload: Dict[str, Any],
    priority: float = 1.0,
    tags: Optional[List[str]] = None,
    timeout: Optional[int] = None,
    retry_policy: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Submit a task to the P2P task queue for distributed execution.
    
    Distributes tasks across available worker nodes in the P2P network. Tasks are
    queued with priority ordering and can be retried on failure according to the
    specified retry policy.
    
    Args:
        task_id: Unique identifier for the task
        task_type: Type of task (e.g., "download", "process", "transform")
        payload: Task data and parameters
        priority: Task priority (higher = earlier execution, default: 1.0)
        tags: Optional tags for categorization and filtering
        timeout: Optional timeout in seconds (None = no timeout)
        retry_policy: Optional retry configuration (max_retries, backoff_factor)
        metadata: Optional metadata for tracking
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - task_id: Assigned task ID
        - status: Current task status ("queued")
        - queue_position: Position in queue
        - estimated_start_time: When task will likely start
        - assigned_worker: Worker ID if pre-assigned
        
    Example:
        >>> result = await task_submit(
        ...     task_id="task-001",
        ...     task_type="download",
        ...     payload={"url": "https://example.com/data.json"},
        ...     priority=2.0,
        ...     tags=["data-ingestion"],
        ...     retry_policy={"max_retries": 3, "backoff_factor": 2.0}
        ... )
        >>> print(result)
        {
            "success": True,
            "task_id": "task-001",
            "status": "queued",
            "queue_position": 5,
            "estimated_start_time": "2026-02-17T20:25:00Z"
        }
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            logger.warning("MCP++ task queue not available, returning mock response")
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "message": "Install ipfs_accelerate_py for full P2P task queue support",
                "task_id": task_id,
                "status": "unavailable"
            }
        
        # Create task queue wrapper
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper",
                "task_id": task_id
            }
        
        # Submit task to P2P queue
        result = await queue_wrapper.submit_task(
            task_id=task_id,
            task_type=task_type,
            payload=payload,
            priority=priority,
            tags=tags or [],
            timeout=timeout,
            retry_policy=retry_policy or {},
            metadata=metadata or {}
        )
        
        return {
            "success": True,
            "task_id": result.get("task_id", task_id),
            "status": result.get("status", "queued"),
            "queue_position": result.get("queue_position", 0),
            "estimated_start_time": result.get("estimated_start_time"),
            "assigned_worker": result.get("assigned_worker")
        }
        
    except Exception as e:
        logger.error(f"Error submitting task {task_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "task_id": task_id
        }

# Mark as Trio-native for Phase 3 runtime routing
task_submit._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_taskqueue",
    priority=9,
    timeout_seconds=10.0,
    io_intensive=False,
    mcp_description="Get the current status of a submitted task"
)
async def task_status(
    task_id: str,
    include_logs: bool = False,
    include_metrics: bool = False
) -> Dict[str, Any]:
    """
    Get the current status of a task in the P2P queue.
    
    Returns real-time information about task execution including current state,
    progress, assigned worker, and optionally execution logs and metrics.
    
    Args:
        task_id: ID of the task to check
        include_logs: Include execution logs (default: False)
        include_metrics: Include performance metrics (default: False)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - task_id: Task identifier
        - status: Current status (queued/running/completed/failed/cancelled)
        - progress: Progress percentage (0-100)
        - worker_id: ID of worker executing task (if running)
        - start_time: When execution started
        - end_time: When execution completed (if finished)
        - queue_position: Position in queue (if queued)
        - logs: Execution logs (if include_logs=True)
        - metrics: Performance metrics (if include_metrics=True)
        
    Example:
        >>> result = await task_status("task-001", include_metrics=True)
        >>> print(result)
        {
            "success": True,
            "task_id": "task-001",
            "status": "running",
            "progress": 65,
            "worker_id": "worker-abc123",
            "start_time": "2026-02-17T20:20:00Z",
            "metrics": {"cpu_usage": 45, "memory_mb": 128}
        }
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "task_id": task_id,
                "status": "unavailable"
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper",
                "task_id": task_id
            }
        
        result = await queue_wrapper.get_task_status(
            task_id=task_id,
            include_logs=include_logs,
            include_metrics=include_metrics
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
            "metrics": result.get("metrics") if include_metrics else None
        }
        
    except Exception as e:
        logger.error(f"Error getting task status {task_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "task_id": task_id
        }

task_status._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_taskqueue",
    priority=10,
    timeout_seconds=15.0,
    io_intensive=False,
    mcp_description="Cancel a pending or running task"
)
async def task_cancel(
    task_id: str,
    reason: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Cancel a queued or running task in the P2P queue.
    
    Attempts to cancel task execution. Queued tasks are removed immediately.
    Running tasks send cancellation signal to worker. Force mode terminates
    task immediately (may leave cleanup incomplete).
    
    Args:
        task_id: ID of task to cancel
        reason: Optional cancellation reason
        force: Force immediate termination (default: False)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - task_id: Task identifier
        - status: New status after cancellation
        - cancelled_at: Timestamp of cancellation
        - cleanup_required: Whether manual cleanup needed
        
    Example:
        >>> result = await task_cancel(
        ...     "task-001",
        ...     reason="User requested cancellation"
        ... )
        >>> print(result)
        {
            "success": True,
            "task_id": "task-001",
            "status": "cancelled",
            "cancelled_at": "2026-02-17T20:25:00Z"
        }
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "task_id": task_id
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper",
                "task_id": task_id
            }
        
        result = await queue_wrapper.cancel_task(
            task_id=task_id,
            reason=reason,
            force=force
        )
        
        return {
            "success": True,
            "task_id": task_id,
            "status": result.get("status", "cancelled"),
            "cancelled_at": result.get("cancelled_at"),
            "cleanup_required": result.get("cleanup_required", False)
        }
        
    except Exception as e:
        logger.error(f"Error cancelling task {task_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "task_id": task_id
        }

task_cancel._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_taskqueue",
    priority=7,
    timeout_seconds=30.0,
    io_intensive=False,
    mcp_description="List all tasks with optional filtering"
)
async def task_list(
    status_filter: Optional[str] = None,
    worker_filter: Optional[str] = None,
    tag_filter: Optional[List[str]] = None,
    priority_min: Optional[float] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """
    List tasks in the P2P queue with advanced filtering.
    
    Returns paginated list of tasks matching specified filters. Useful for
    monitoring queue status, identifying bottlenecks, and managing workload.
    
    Args:
        status_filter: Filter by status (queued/running/completed/failed/cancelled)
        worker_filter: Filter by assigned worker ID
        tag_filter: Filter by tags (must match all tags)
        priority_min: Minimum priority threshold
        limit: Maximum number of results (default: 100)
        offset: Pagination offset (default: 0)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - tasks: List of task objects
        - total_count: Total matching tasks
        - returned_count: Number of tasks in this response
        - has_more: Whether more results available
        
    Example:
        >>> result = await task_list(
        ...     status_filter="running",
        ...     limit=10
        ... )
        >>> print(f"Found {result['total_count']} running tasks")
        Found 5 running tasks
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "tasks": [],
                "total_count": 0,
                "returned_count": 0,
                "has_more": False
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper",
                "tasks": []
            }
        
        result = await queue_wrapper.list_tasks(
            status_filter=status_filter,
            worker_filter=worker_filter,
            tag_filter=tag_filter or [],
            priority_min=priority_min,
            limit=limit,
            offset=offset
        )
        
        tasks = result.get("tasks", [])
        total = result.get("total_count", 0)
        
        return {
            "success": True,
            "tasks": tasks,
            "total_count": total,
            "returned_count": len(tasks),
            "has_more": (offset + len(tasks)) < total
        }
        
    except Exception as e:
        logger.error(f"Error listing tasks: {e}")
        return {
            "success": False,
            "error": str(e),
            "tasks": []
        }

task_list._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_taskqueue",
    priority=8,
    timeout_seconds=10.0,
    io_intensive=False,
    mcp_description="Get or update the priority of a task"
)
async def task_priority(
    task_id: str,
    new_priority: float,
    requeue: bool = True
) -> Dict[str, Any]:
    """
    Set or update the priority of a queued task.
    
    Changes task priority, affecting its position in the execution queue.
    Higher priority tasks execute before lower priority tasks. Can requeue
    to immediately apply new priority ordering.
    
    Args:
        task_id: ID of task to update
        new_priority: New priority value (higher = earlier execution)
        requeue: Reorder queue immediately (default: True)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - task_id: Task identifier
        - old_priority: Previous priority value
        - new_priority: Updated priority value
        - new_queue_position: Position after reordering
        
    Example:
        >>> result = await task_priority("task-001", 5.0)
        >>> print(f"Priority updated, new position: {result['new_queue_position']}")
        Priority updated, new position: 2
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "task_id": task_id
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper",
                "task_id": task_id
            }
        
        result = await queue_wrapper.update_task_priority(
            task_id=task_id,
            new_priority=new_priority,
            requeue=requeue
        )
        
        return {
            "success": True,
            "task_id": task_id,
            "old_priority": result.get("old_priority", 1.0),
            "new_priority": new_priority,
            "new_queue_position": result.get("new_queue_position")
        }
        
    except Exception as e:
        logger.error(f"Error updating task priority {task_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "task_id": task_id
        }

task_priority._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_taskqueue",
    priority=8,
    timeout_seconds=15.0,
    io_intensive=False,
    mcp_description="Retrieve the result of a completed task"
)
async def task_result(
    task_id: str,
    include_output: bool = True,
    include_logs: bool = False
) -> Dict[str, Any]:
    """
    Get the result of a completed task.
    
    Retrieves execution results for completed tasks including output data,
    execution time, and optionally logs. Only works for completed tasks.
    
    Args:
        task_id: ID of completed task
        include_output: Include task output data (default: True)
        include_logs: Include execution logs (default: False)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - task_id: Task identifier
        - status: Task status (should be "completed")
        - result: Task execution result
        - output: Task output data (if include_output=True)
        - logs: Execution logs (if include_logs=True)
        - execution_time: Total execution time in seconds
        
    Example:
        >>> result = await task_result("task-001", include_logs=True)
        >>> print(f"Task completed in {result['execution_time']}s")
        Task completed in 45.2s
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "task_id": task_id
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper",
                "task_id": task_id
            }
        
        result = await queue_wrapper.get_task_result(
            task_id=task_id,
            include_output=include_output,
            include_logs=include_logs
        )
        
        return {
            "success": True,
            "task_id": task_id,
            "status": result.get("status", "completed"),
            "result": result.get("result"),
            "output": result.get("output") if include_output else None,
            "logs": result.get("logs") if include_logs else None,
            "execution_time": result.get("execution_time", 0)
        }
        
    except Exception as e:
        logger.error(f"Error getting task result {task_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "task_id": task_id
        }

task_result._mcp_runtime = 'trio'


# ============================================================================
# QUEUE MANAGEMENT (5 tools)
# ============================================================================

@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_queue_mgmt",
    priority=7,
    timeout_seconds=10.0,
    io_intensive=False,
    mcp_description="Get comprehensive queue statistics"
)
async def queue_stats(
    include_worker_stats: bool = False,
    include_historical: bool = False
) -> Dict[str, Any]:
    """
    Get statistics about the P2P task queue.
    
    Returns comprehensive metrics about queue health, performance, and workload
    distribution. Useful for monitoring and capacity planning.
    
    Args:
        include_worker_stats: Include per-worker statistics (default: False)
        include_historical: Include historical metrics (default: False)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - queued_count: Number of queued tasks
        - running_count: Number of running tasks
        - completed_count: Total completed tasks
        - failed_count: Total failed tasks
        - average_wait_time: Average queue wait time (seconds)
        - average_execution_time: Average execution time (seconds)
        - throughput: Tasks per minute
        - worker_stats: Per-worker statistics (if include_worker_stats=True)
        - historical: Historical metrics (if include_historical=True)
        
    Example:
        >>> result = await queue_stats(include_worker_stats=True)
        >>> print(f"Queue: {result['queued_count']} queued, {result['running_count']} running")
        Queue: 12 queued, 5 running
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "queued_count": 0,
                "running_count": 0,
                "completed_count": 0,
                "failed_count": 0
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper"
            }
        
        result = await queue_wrapper.get_queue_stats(
            include_worker_stats=include_worker_stats,
            include_historical=include_historical
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
            "historical": result.get("historical") if include_historical else None
        }
        
    except Exception as e:
        logger.error(f"Error getting queue stats: {e}")
        return {
            "success": False,
            "error": str(e)
        }

queue_stats._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_queue_mgmt",
    priority=9,
    timeout_seconds=10.0,
    io_intensive=False,
    mcp_description="Pause task queue processing"
)
async def queue_pause(
    reason: Optional[str] = None
) -> Dict[str, Any]:
    """
    Pause task queue processing.
    
    Stops accepting new task executions. Queued tasks remain in queue.
    Running tasks continue to completion. Useful for maintenance or
    emergency situations.
    
    Args:
        reason: Optional reason for pausing
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - status: New queue status ("paused")
        - paused_at: Timestamp of pause
        - queued_tasks: Number of tasks remaining in queue
        - running_tasks: Number of tasks still running
        
    Example:
        >>> result = await queue_pause("Maintenance window")
        >>> print(f"Queue paused with {result['queued_tasks']} tasks remaining")
        Queue paused with 12 tasks remaining
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available"
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper"
            }
        
        result = await queue_wrapper.pause_queue(reason=reason)
        
        return {
            "success": True,
            "status": "paused",
            "paused_at": result.get("paused_at"),
            "queued_tasks": result.get("queued_tasks", 0),
            "running_tasks": result.get("running_tasks", 0)
        }
        
    except Exception as e:
        logger.error(f"Error pausing queue: {e}")
        return {
            "success": False,
            "error": str(e)
        }

queue_pause._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_queue_mgmt",
    priority=9,
    timeout_seconds=10.0,
    io_intensive=False,
    mcp_description="Resume paused task queue processing"
)
async def queue_resume(
    reorder_by_priority: bool = True
) -> Dict[str, Any]:
    """
    Resume task queue processing after pause.
    
    Re-enables task execution. Queued tasks will begin processing according
    to priority. Can optionally reorder queue before resuming.
    
    Args:
        reorder_by_priority: Reorder queue by priority before resuming (default: True)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - status: New queue status ("active")
        - resumed_at: Timestamp of resume
        - queued_tasks: Number of tasks ready for execution
        - reordered: Whether queue was reordered
        
    Example:
        >>> result = await queue_resume()
        >>> print(f"Queue resumed, processing {result['queued_tasks']} tasks")
        Queue resumed, processing 12 tasks
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available"
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper"
            }
        
        result = await queue_wrapper.resume_queue(
            reorder_by_priority=reorder_by_priority
        )
        
        return {
            "success": True,
            "status": "active",
            "resumed_at": result.get("resumed_at"),
            "queued_tasks": result.get("queued_tasks", 0),
            "reordered": result.get("reordered", False)
        }
        
    except Exception as e:
        logger.error(f"Error resuming queue: {e}")
        return {
            "success": False,
            "error": str(e)
        }

queue_resume._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_queue_mgmt",
    priority=10,
    timeout_seconds=20.0,
    io_intensive=False,
    mcp_description="Clear all tasks from the queue"
)
async def queue_clear(
    status_filter: Optional[str] = None,
    confirm: bool = False
) -> Dict[str, Any]:
    """
    Clear tasks from the queue.
    
    Removes tasks from queue based on status filter. Running tasks are not
    affected. Requires explicit confirmation to prevent accidental data loss.
    
    Args:
        status_filter: Only clear tasks with this status (queued/failed/cancelled)
                      If None, clears all non-running tasks
        confirm: Must be True to execute (safety check)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - cleared_count: Number of tasks removed
        - remaining_count: Number of tasks still in queue
        - cleared_at: Timestamp of clear operation
        
    Example:
        >>> result = await queue_clear(
        ...     status_filter="failed",
        ...     confirm=True
        ... )
        >>> print(f"Cleared {result['cleared_count']} failed tasks")
        Cleared 3 failed tasks
    """
    try:
        if not confirm:
            return {
                "success": False,
                "error": "Confirmation required (set confirm=True)",
                "message": "This operation will remove tasks from the queue"
            }
        
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available"
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper"
            }
        
        result = await queue_wrapper.clear_queue(
            status_filter=status_filter
        )
        
        return {
            "success": True,
            "cleared_count": result.get("cleared_count", 0),
            "remaining_count": result.get("remaining_count", 0),
            "cleared_at": result.get("cleared_at")
        }
        
    except Exception as e:
        logger.error(f"Error clearing queue: {e}")
        return {
            "success": False,
            "error": str(e)
        }

queue_clear._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_taskqueue",
    priority=8,
    timeout_seconds=15.0,
    retry_policy="exponential",
    io_intensive=False,
    mcp_description="Retry a failed task"
)
async def task_retry(
    task_id: str,
    retry_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Retry a failed task with optional new configuration.
    
    Resubmits a failed task for execution. Can override original retry policy
    or timeout. Preserves task history and links retries to original task.
    
    Args:
        task_id: ID of failed task to retry
        retry_config: Optional new retry configuration (max_retries, timeout)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - task_id: Original task ID
        - retry_task_id: New task ID for retry
        - retry_count: Total retry attempts for this task
        - queue_position: Position in queue
        
    Example:
        >>> result = await task_retry(
        ...     "task-001",
        ...     retry_config={"max_retries": 2, "timeout": 300}
        ... )
        >>> print(f"Task retry queued as {result['retry_task_id']}")
        Task retry queued as task-001-retry-1
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "task_id": task_id
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper",
                "task_id": task_id
            }
        
        result = await queue_wrapper.retry_task(
            task_id=task_id,
            retry_config=retry_config or {}
        )
        
        return {
            "success": True,
            "task_id": task_id,
            "retry_task_id": result.get("retry_task_id"),
            "retry_count": result.get("retry_count", 1),
            "queue_position": result.get("queue_position")
        }
        
    except Exception as e:
        logger.error(f"Error retrying task {task_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "task_id": task_id
        }

task_retry._mcp_runtime = 'trio'


# ============================================================================
# WORKER MANAGEMENT (3 tools)
# ============================================================================

@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_worker_mgmt",
    priority=9,
    timeout_seconds=20.0,
    io_intensive=False,
    mcp_description="Register a worker node for task execution"
)
async def worker_register(
    worker_id: str,
    capabilities: List[str],
    max_concurrent_tasks: int = 5,
    resource_limits: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Register as a worker node in the P2P task queue.
    
    Registers current node as worker capable of executing tasks. Specifies
    capabilities, concurrency limits, and resource constraints. Workers
    receive task assignments based on capabilities and availability.
    
    Args:
        worker_id: Unique identifier for this worker
        capabilities: List of task types this worker can execute
        max_concurrent_tasks: Maximum parallel tasks (default: 5)
        resource_limits: Optional resource constraints (cpu_cores, memory_gb)
        metadata: Optional worker metadata
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - worker_id: Assigned worker ID
        - status: Worker status ("active")
        - registered_at: Registration timestamp
        - assigned_peers: List of peer coordinators
        
    Example:
        >>> result = await worker_register(
        ...     worker_id="worker-001",
        ...     capabilities=["download", "process", "transform"],
        ...     max_concurrent_tasks=10,
        ...     resource_limits={"cpu_cores": 4, "memory_gb": 16}
        ... )
        >>> print(f"Worker registered: {result['worker_id']}")
        Worker registered: worker-001
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "worker_id": worker_id
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper",
                "worker_id": worker_id
            }
        
        result = await queue_wrapper.register_worker(
            worker_id=worker_id,
            capabilities=capabilities,
            max_concurrent_tasks=max_concurrent_tasks,
            resource_limits=resource_limits or {},
            metadata=metadata or {}
        )
        
        return {
            "success": True,
            "worker_id": worker_id,
            "status": "active",
            "registered_at": result.get("registered_at"),
            "assigned_peers": result.get("assigned_peers", [])
        }
        
    except Exception as e:
        logger.error(f"Error registering worker {worker_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "worker_id": worker_id
        }

worker_register._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_worker_mgmt",
    priority=9,
    timeout_seconds=15.0,
    io_intensive=False,
    mcp_description="Unregister a worker node"
)
async def worker_unregister(
    worker_id: str,
    graceful: bool = True,
    timeout: int = 300
) -> Dict[str, Any]:
    """
    Unregister a worker node from the P2P task queue.
    
    Removes worker from task assignment pool. Graceful unregistration waits
    for running tasks to complete. Non-graceful terminates immediately
    (running tasks may fail).
    
    Args:
        worker_id: ID of worker to unregister
        graceful: Wait for running tasks to complete (default: True)
        timeout: Maximum wait time for graceful shutdown (seconds, default: 300)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - worker_id: Worker identifier
        - status: New status ("unregistered")
        - unregistered_at: Unregistration timestamp
        - completed_tasks: Tasks completed during shutdown
        - abandoned_tasks: Tasks abandoned (if not graceful)
        
    Example:
        >>> result = await worker_unregister("worker-001", graceful=True)
        >>> print(f"Worker unregistered after completing {result['completed_tasks']} tasks")
        Worker unregistered after completing 3 tasks
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "worker_id": worker_id
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper",
                "worker_id": worker_id
            }
        
        result = await queue_wrapper.unregister_worker(
            worker_id=worker_id,
            graceful=graceful,
            timeout=timeout
        )
        
        return {
            "success": True,
            "worker_id": worker_id,
            "status": "unregistered",
            "unregistered_at": result.get("unregistered_at"),
            "completed_tasks": result.get("completed_tasks", 0),
            "abandoned_tasks": result.get("abandoned_tasks", 0)
        }
        
    except Exception as e:
        logger.error(f"Error unregistering worker {worker_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "worker_id": worker_id
        }

worker_unregister._mcp_runtime = 'trio'


@tool_metadata(
    runtime=RUNTIME_TRIO,
    requires_p2p=True,
    category="p2p_worker_mgmt",
    priority=7,
    timeout_seconds=10.0,
    io_intensive=False,
    mcp_description="Get status of worker nodes"
)
async def worker_status(
    worker_id: str,
    include_tasks: bool = False,
    include_metrics: bool = False
) -> Dict[str, Any]:
    """
    Get status and statistics for a worker node.
    
    Returns current worker state, assigned tasks, resource usage, and
    performance metrics. Useful for monitoring worker health and capacity.
    
    Args:
        worker_id: ID of worker to query
        include_tasks: Include list of assigned tasks (default: False)
        include_metrics: Include resource metrics (default: False)
        
    Returns:
        Dictionary containing:
        - success: Boolean indicating success
        - worker_id: Worker identifier
        - status: Current status (active/idle/busy/offline)
        - running_tasks: Number of currently running tasks
        - completed_tasks: Total completed tasks
        - failed_tasks: Total failed tasks
        - tasks: List of assigned tasks (if include_tasks=True)
        - metrics: Resource usage metrics (if include_metrics=True)
        
    Example:
        >>> result = await worker_status("worker-001", include_metrics=True)
        >>> print(f"Worker {result['worker_id']}: {result['running_tasks']} running")
        Worker worker-001: 3 running
    """
    try:
        if not MCPLUSPLUS_AVAILABLE or task_queue is None:
            return {
                "success": False,
                "error": "MCP++ task queue not available",
                "worker_id": worker_id
            }
        
        queue_wrapper = create_task_queue_wrapper()
        if queue_wrapper is None:
            return {
                "success": False,
                "error": "Failed to create task queue wrapper",
                "worker_id": worker_id
            }
        
        result = await queue_wrapper.get_worker_status(
            worker_id=worker_id,
            include_tasks=include_tasks,
            include_metrics=include_metrics
        )
        
        return {
            "success": True,
            "worker_id": worker_id,
            "status": result.get("status", "unknown"),
            "running_tasks": result.get("running_tasks", 0),
            "completed_tasks": result.get("completed_tasks", 0),
            "failed_tasks": result.get("failed_tasks", 0),
            "tasks": result.get("tasks") if include_tasks else None,
            "metrics": result.get("metrics") if include_metrics else None
        }
        
    except Exception as e:
        logger.error(f"Error getting worker status {worker_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "worker_id": worker_id
        }

worker_status._mcp_runtime = 'trio'


# ============================================================================
# MCP TOOL REGISTRATION
# ============================================================================

# Export tools for MCP registration
TOOLS = [
    # Core Task Operations
    {
        "function": task_submit,
        "description": "Submit task to P2P queue for distributed execution",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Unique task identifier"},
                "task_type": {"type": "string", "description": "Task type"},
                "payload": {"type": "object", "description": "Task data"},
                "priority": {"type": "number", "description": "Task priority (default: 1.0)"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "timeout": {"type": "integer", "description": "Timeout in seconds"},
                "retry_policy": {"type": "object"},
                "metadata": {"type": "object"}
            },
            "required": ["task_id", "task_type", "payload"]
        }
    },
    {
        "function": task_status,
        "description": "Get task execution status and progress",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task identifier"},
                "include_logs": {"type": "boolean", "description": "Include execution logs"},
                "include_metrics": {"type": "boolean", "description": "Include performance metrics"}
            },
            "required": ["task_id"]
        }
    },
    {
        "function": task_cancel,
        "description": "Cancel queued or running task",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task identifier"},
                "reason": {"type": "string", "description": "Cancellation reason"},
                "force": {"type": "boolean", "description": "Force immediate termination"}
            },
            "required": ["task_id"]
        }
    },
    {
        "function": task_list,
        "description": "List tasks with advanced filtering",
        "input_schema": {
            "type": "object",
            "properties": {
                "status_filter": {"type": "string", "description": "Filter by status"},
                "worker_filter": {"type": "string", "description": "Filter by worker ID"},
                "tag_filter": {"type": "array", "items": {"type": "string"}},
                "priority_min": {"type": "number", "description": "Minimum priority"},
                "limit": {"type": "integer", "description": "Max results (default: 100)"},
                "offset": {"type": "integer", "description": "Pagination offset"}
            }
        }
    },
    {
        "function": task_priority,
        "description": "Set or update task priority",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task identifier"},
                "new_priority": {"type": "number", "description": "New priority value"},
                "requeue": {"type": "boolean", "description": "Reorder queue immediately"}
            },
            "required": ["task_id", "new_priority"]
        }
    },
    {
        "function": task_result,
        "description": "Get completed task result and output",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task identifier"},
                "include_output": {"type": "boolean", "description": "Include output data"},
                "include_logs": {"type": "boolean", "description": "Include execution logs"}
            },
            "required": ["task_id"]
        }
    },
    # Queue Management
    {
        "function": queue_stats,
        "description": "Get queue statistics and metrics",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_worker_stats": {"type": "boolean", "description": "Include per-worker stats"},
                "include_historical": {"type": "boolean", "description": "Include historical metrics"}
            }
        }
    },
    {
        "function": queue_pause,
        "description": "Pause queue processing",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Reason for pausing"}
            }
        }
    },
    {
        "function": queue_resume,
        "description": "Resume queue processing",
        "input_schema": {
            "type": "object",
            "properties": {
                "reorder_by_priority": {"type": "boolean", "description": "Reorder before resuming"}
            }
        }
    },
    {
        "function": queue_clear,
        "description": "Clear tasks from queue",
        "input_schema": {
            "type": "object",
            "properties": {
                "status_filter": {"type": "string", "description": "Only clear tasks with this status"},
                "confirm": {"type": "boolean", "description": "Must be true to execute"}
            },
            "required": ["confirm"]
        }
    },
    {
        "function": task_retry,
        "description": "Retry failed task with optional new configuration",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Failed task identifier"},
                "retry_config": {"type": "object", "description": "New retry configuration"}
            },
            "required": ["task_id"]
        }
    },
    # Worker Management
    {
        "function": worker_register,
        "description": "Register as worker node",
        "input_schema": {
            "type": "object",
            "properties": {
                "worker_id": {"type": "string", "description": "Unique worker identifier"},
                "capabilities": {"type": "array", "items": {"type": "string"}, "description": "Task types this worker can execute"},
                "max_concurrent_tasks": {"type": "integer", "description": "Maximum parallel tasks"},
                "resource_limits": {"type": "object", "description": "Resource constraints"},
                "metadata": {"type": "object", "description": "Worker metadata"}
            },
            "required": ["worker_id", "capabilities"]
        }
    },
    {
        "function": worker_unregister,
        "description": "Unregister worker node",
        "input_schema": {
            "type": "object",
            "properties": {
                "worker_id": {"type": "string", "description": "Worker identifier"},
                "graceful": {"type": "boolean", "description": "Wait for tasks to complete"},
                "timeout": {"type": "integer", "description": "Maximum wait time"}
            },
            "required": ["worker_id"]
        }
    },
    {
        "function": worker_status,
        "description": "Get worker status and metrics",
        "input_schema": {
            "type": "object",
            "properties": {
                "worker_id": {"type": "string", "description": "Worker identifier"},
                "include_tasks": {"type": "boolean", "description": "Include assigned tasks"},
                "include_metrics": {"type": "boolean", "description": "Include resource metrics"}
            },
            "required": ["worker_id"]
        }
    }
]
