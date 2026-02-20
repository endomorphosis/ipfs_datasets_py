"""
Background task management tools for MCP server.

Business logic (TaskStatus, TaskType, MockTaskManager) lives in
ipfs_datasets_py.tasks.background_task_engine.  This module is a thin
MCP wrapper that validates inputs, delegates to the engine, and formats
responses.
"""

import logging
from typing import Dict, List, Any, Optional

from ipfs_datasets_py.tasks.background_task_engine import (  # noqa: F401
    TaskStatus,
    TaskType,
    MockBackgroundTask,
    MockTaskManager,
)

logger = logging.getLogger(__name__)

# Module-level singleton — shared across calls within one server process.
_mock_task_manager = MockTaskManager()

async def check_task_status(task_id: Optional[str] = None, task_type: str = "all",
                           status_filter: str = "all", limit: int = 20,
                           task_manager=None) -> Dict[str, Any]:
    """
    Check the status and progress of background tasks.
    
    Args:
        task_id: Specific task ID to check (optional)
        task_type: Type of task to filter by
        status_filter: Filter tasks by status
        limit: Maximum number of tasks to return
        task_manager: Optional task manager service
        
    Returns:
        Dictionary containing task status information
    """
    try:
        # Input validation
        if task_id and not isinstance(task_id, str):
            return {
                "status": "error",
                "message": "Task ID must be a string"
            }
        
        if task_type not in ["create_embeddings", "shard_embeddings", "index_sparse", 
                           "index_cluster", "storacha_clusters", "all"]:
            return {
                "status": "error",
                "message": "Invalid task_type"
            }
        
        if status_filter not in ["pending", "running", "completed", "failed", "timeout", "all"]:
            return {
                "status": "error",
                "message": "Invalid status_filter"
            }
        
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            return {
                "status": "error",
                "message": "Limit must be an integer between 1 and 100"
            }
        
        # Use mock task manager
        manager = task_manager or _mock_task_manager
        
        if task_id:
            # Get specific task — engine returns Optional[Dict] via get_task_status()
            task = await manager.get_task_status(task_id)
            if not task:
                return {
                    "status": "not_found",
                    "message": "Task not found"
                }
            
            return {
                "status": "success",
                "task": {
                    "task_id": task["task_id"],
                    "task_type": task["task_type"],
                    "status": task["status"],
                    "progress": task["progress"],
                    "created_at": task.get("created_at", ""),
                    "started_at": task.get("started_at"),
                    "completed_at": task.get("completed_at"),
                    "resource_usage": task.get("resource_usage", {}),
                    "error": task.get("error")
                },
                "message": "Task status retrieved successfully"
            }
        else:
            # List tasks with filters
            task_objs = await manager.list_tasks(
                task_type=task_type, status=status_filter, limit=limit
            )
            tasks = [t.to_dict() if hasattr(t, "to_dict") else t for t in task_objs]
            
            formatted_tasks = []
            for task in tasks:
                formatted_tasks.append({
                    "task_id": task.get("task_id", ""),
                    "task_type": task.get("task_type", ""),
                    "status": task.get("status", ""),
                    "progress": task.get("progress", 0),
                    "created_at": task.get("created_at", ""),
                    "priority": task.get("metadata", {}).get("priority", "normal"),
                })
            
            return {
                "status": "success",
                "tasks": formatted_tasks,
                "count": len(formatted_tasks),
                "filters": {
                    "task_type": task_type,
                    "status_filter": status_filter,
                    "limit": limit
                },
                "message": f"Retrieved {len(formatted_tasks)} tasks"
            }
        
    except Exception as e:
        logger.error(f"Task status check error: {e}")
        return {
            "status": "error",
            "message": f"Failed to check task status: {str(e)}"
        }

async def manage_background_tasks(action: str, task_id: Optional[str] = None,
                                 task_type: Optional[str] = None, parameters: Optional[Dict[str, Any]] = None,
                                 priority: str = "normal", task_manager=None,
                                 task_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Manage background tasks with operations like creation, cancellation, and monitoring.
    
    Args:
        action: Action to perform (create, cancel, pause, resume, get_stats)
        task_id: Task ID for specific operations
        task_type: Type of task to create
        parameters: Parameters for task creation
        priority: Task priority (high, normal, low)
        task_manager: Optional task manager service
        
    Returns:
        Dictionary containing task management result
    """
    try:
        # Input validation
        if action not in ["create", "cancel", "pause", "resume", "get_stats", "list", "schedule"]:
            return {
                "status": "error",
                "message": "Invalid action. Must be one of: create, cancel, pause, resume, get_stats"
            }
        
        if action in ["cancel", "pause", "resume"] and not task_id:
            return {
                "status": "error",
                "message": f"task_id is required for {action} action"
            }
        
        if task_config and action in ["create", "schedule"]:
            task_type = task_type or task_config.get("type") or task_config.get("task_type")
            parameters = parameters or task_config.get("parameters")
            priority = task_config.get("priority", priority)

        if action in ["create", "schedule"] and not task_type:
            return {
                "status": "error",
                "message": "task_type is required for create action"
            }
        
        if priority not in ["high", "normal", "low"]:
            return {
                "status": "error",
                "message": "Invalid priority. Must be one of: high, normal, low"
            }
        
        # Use mock task manager
        manager = task_manager or _mock_task_manager
        
        if action == "create":
            # Create new task
            task_params = parameters or {}
            task_id_new = await manager.create_task(task_type, parameters=task_params, priority=priority)
            task_obj = await manager.get_task(task_id_new)
            task_d = task_obj.to_dict() if task_obj else {"task_id": task_id_new, "task_type": task_type}
            
            return {
                "status": "success",
                "task_id": task_d["task_id"],
                "task_type": task_d["task_type"],
                "priority": priority,
                "created_at": task_d.get("created_at", ""),
                "message": "Background task created successfully"
            }

        elif action == "schedule":
            task_params = parameters or {}
            task_id_new = await manager.create_task(task_type, parameters=task_params, priority=priority)
            task_obj = await manager.get_task(task_id_new)
            task_d = task_obj.to_dict() if task_obj else {"task_id": task_id_new, "task_type": task_type}
            return {
                "status": "scheduled",
                "task_id": task_d["task_id"],
                "task_type": task_d["task_type"],
                "priority": priority,
                "schedule": task_config.get("schedule") if task_config else None,
                "message": "Recurring task scheduled successfully"
            }
        
        elif action == "cancel":
            # Cancel task
            cancelled = await manager.cancel_task(task_id)
            if not cancelled:
                return {
                    "status": "not_found",
                    "message": "Task not found or cannot be cancelled"
                }
            
            return {
                "status": "success",
                "task_id": task_id,
                "action": "cancelled",
                "message": "Task cancelled successfully"
            }

        elif action == "list":
            task_objs = await manager.list_tasks()
            tasks = [t.to_dict() if hasattr(t, "to_dict") else t for t in task_objs]
            return {
                "status": "success",
                "tasks": tasks,
                "count": len(tasks)
            }
        
        elif action == "pause":
            # Pause task (mock implementation)
            updated = await manager.update_task(task_id, status="paused")
            if not updated:
                return {
                    "status": "error",
                    "message": "Task not found"
                }
            
            return {
                "status": "success",
                "task_id": task_id,
                "action": "paused",
                "message": "Task paused successfully"
            }
        
        elif action == "resume":
            # Resume task (mock implementation)
            updated = await manager.update_task(task_id, status="running")
            if not updated:
                return {
                    "status": "error",
                    "message": "Task not found"
                }
            
            return {
                "status": "success",
                "task_id": task_id,
                "action": "resumed",
                "message": "Task resumed successfully"
            }
        
        elif action == "get_stats":
            # Get queue statistics
            stats = await manager.get_queue_stats()
            
            return {
                "status": "success",
                "statistics": stats,
                "message": "Task statistics retrieved successfully"
            }
        
    except Exception as e:
        logger.error(f"Task management error: {e}")
        return {
            "status": "error",
            "message": f"Task management failed: {str(e)}"
        }

async def manage_task_queue(action: str, priority: Optional[str] = None,
                           max_concurrent: Optional[int] = None, task_manager=None) -> Dict[str, Any]:
    """
    Manage task queues, scheduling, and resource allocation.
    
    Args:
        action: Action to perform (get_stats, clear_queue, set_limits, reorder)
        priority: Priority queue to operate on
        max_concurrent: Maximum concurrent tasks limit
        task_manager: Optional task manager service
        
    Returns:
        Dictionary containing queue management result
    """
    try:
        # Input validation
        if action not in ["get_stats", "clear_queue", "set_limits", "reorder"]:
            return {
                "status": "error",
                "message": "Invalid action. Must be one of: get_stats, clear_queue, set_limits, reorder"
            }
        
        if action in ["clear_queue", "reorder"] and not priority:
            return {
                "status": "error",
                "message": f"priority is required for {action} action"
            }
        
        if priority and priority not in ["high", "normal", "low"]:
            return {
                "status": "error",
                "message": "Invalid priority. Must be one of: high, normal, low"
            }
        
        # Use mock task manager
        manager = task_manager or _mock_task_manager
        
        if action == "get_stats":
            # Get detailed queue statistics
            stats = await manager.get_queue_stats()
            
            return {
                "status": "success",
                "queue_statistics": {
                    "total_queued": sum(stats["queues"].values()),
                    "by_priority": stats["queues"],
                    "running_tasks": stats["running_tasks"],
                    "total_tasks_created": stats["counters"]["created"],
                    "total_tasks_completed": stats["counters"]["completed"],
                    "total_tasks_failed": stats["counters"]["failed"],
                    "total_tasks_cancelled": stats["counters"]["cancelled"]
                },
                "message": "Queue statistics retrieved successfully"
            }
        
        elif action == "clear_queue":
            # Clear specific priority queue
            queue_size = len(manager.task_queues[priority])
            manager.task_queues[priority].clear()
            
            return {
                "status": "success",
                "priority": priority,
                "tasks_cleared": queue_size,
                "message": f"Cleared {queue_size} tasks from {priority} priority queue"
            }
        
        elif action == "set_limits":
            # Set concurrency limits (mock implementation)
            if max_concurrent is not None:
                if not isinstance(max_concurrent, int) or max_concurrent < 1:
                    return {
                        "status": "error",
                        "message": "max_concurrent must be a positive integer"
                    }
            
            return {
                "status": "success",
                "max_concurrent_tasks": max_concurrent or 10,
                "message": f"Concurrency limit set to {max_concurrent or 10} tasks"
            }
        
        elif action == "reorder":
            # Reorder queue by priority (mock implementation)
            queue_size = len(manager.task_queues[priority])
            
            return {
                "status": "success",
                "priority": priority,
                "tasks_reordered": queue_size,
                "message": f"Reordered {queue_size} tasks in {priority} priority queue"
            }
        
    except Exception as e:
        logger.error(f"Task queue management error: {e}")
        return {
            "status": "error",
            "message": f"Task queue management failed: {str(e)}"
        }
