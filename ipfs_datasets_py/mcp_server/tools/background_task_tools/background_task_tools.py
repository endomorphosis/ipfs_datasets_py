"""
Background task management tools for MCP server.

This module provides tools for managing background tasks such as
embedding creation, indexing, and other long-running operations.
"""

import anyio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
from enum import Enum

logger = logging.getLogger(__name__)

class TaskStatus(Enum):
    """Task status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"

class TaskType(Enum):
    """Task type enumeration."""
    CREATE_EMBEDDINGS = "create_embeddings"
    SHARD_EMBEDDINGS = "shard_embeddings"
    INDEX_SPARSE = "index_sparse"
    INDEX_CLUSTER = "index_cluster"
    STORACHA_CLUSTERS = "storacha_clusters"
    VECTOR_SEARCH = "vector_search"
    DATA_PROCESSING = "data_processing"

# Mock task manager for testing
class MockTaskManager:
    """Mock task manager for testing purposes."""
    
    def __init__(self):
        self.tasks = {}
        self.task_queues = {
            "high": [],
            "normal": [],
            "low": []
        }
        self.running_tasks = {}
        self.task_counters = {
            "created": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0
        }
    
    async def create_task(self, task_type: str, parameters: Dict[str, Any], 
                         priority: str = "normal", timeout_seconds: int = 3600) -> Dict[str, Any]:
        """Create a new background task."""
        task_id = str(uuid.uuid4())
        
        task_data = {
            "task_id": task_id,
            "task_type": task_type,
            "status": TaskStatus.PENDING.value,
            "parameters": parameters,
            "priority": priority,
            "created_at": datetime.now(),
            "started_at": None,
            "completed_at": None,
            "timeout_at": datetime.now() + timedelta(seconds=timeout_seconds),
            "progress": 0,
            "result": None,
            "error": None,
            "resource_usage": {
                "cpu_percent": 0,
                "memory_mb": 0,
                "gpu_utilization": 0
            }
        }
        
        self.tasks[task_id] = task_data
        self.task_queues[priority].append(task_id)
        self.task_counters["created"] += 1
        
        return task_data
    
    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task status by ID."""
        return self.tasks.get(task_id)
    
    async def update_task(self, task_id: str, **kwargs) -> bool:
        """Update task data."""
        if task_id in self.tasks:
            self.tasks[task_id].update(kwargs)
            return True
        return False
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            if task["status"] in [TaskStatus.PENDING.value, TaskStatus.RUNNING.value]:
                task["status"] = TaskStatus.CANCELLED.value
                task["completed_at"] = datetime.now()
                self.task_counters["cancelled"] += 1
                
                # Remove from queue if pending
                for queue in self.task_queues.values():
                    if task_id in queue:
                        queue.remove(task_id)
                
                # Remove from running tasks
                if task_id in self.running_tasks:
                    del self.running_tasks[task_id]
                
                return True
        return False
    
    async def list_tasks(self, task_type: Optional[str] = None, 
                        status: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """List tasks with optional filters."""
        tasks = list(self.tasks.values())
        
        if task_type and task_type != "all":
            tasks = [t for t in tasks if t.get("task_type") == task_type]
        
        if status and status != "all":
            tasks = [t for t in tasks if t.get("status") == status]
        
        # Sort by created_at descending
        tasks.sort(key=lambda x: x["created_at"], reverse=True)
        
        return tasks[:limit]
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get task queue statistics."""
        return {
            "queues": {
                priority: len(queue) for priority, queue in self.task_queues.items()
            },
            "running_tasks": len(self.running_tasks),
            "total_tasks": len(self.tasks),
            "counters": self.task_counters.copy()
        }

# Global mock task manager instance
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
            # Get specific task
            task = await manager.get_task_status(task_id)
            if not task:
                return {
                    "status": "error",
                    "message": "Task not found"
                }
            
            return {
                "status": "success",
                "task": {
                    "task_id": task["task_id"],
                    "task_type": task["task_type"],
                    "status": task["status"],
                    "progress": task["progress"],
                    "created_at": task["created_at"].isoformat(),
                    "started_at": task["started_at"].isoformat() if task["started_at"] else None,
                    "completed_at": task["completed_at"].isoformat() if task["completed_at"] else None,
                    "resource_usage": task["resource_usage"],
                    "error": task.get("error")
                },
                "message": "Task status retrieved successfully"
            }
        else:
            # List tasks with filters
            tasks = await manager.list_tasks(task_type, status_filter, limit)
            
            formatted_tasks = []
            for task in tasks:
                formatted_tasks.append({
                    "task_id": task["task_id"],
                    "task_type": task["task_type"],
                    "status": task["status"],
                    "progress": task["progress"],
                    "created_at": task["created_at"].isoformat(),
                    "priority": task["priority"]
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
                                 priority: str = "normal", task_manager=None) -> Dict[str, Any]:
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
        if action not in ["create", "cancel", "pause", "resume", "get_stats"]:
            return {
                "status": "error",
                "message": "Invalid action. Must be one of: create, cancel, pause, resume, get_stats"
            }
        
        if action in ["cancel", "pause", "resume"] and not task_id:
            return {
                "status": "error",
                "message": f"task_id is required for {action} action"
            }
        
        if action == "create" and not task_type:
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
            task = await manager.create_task(task_type, task_params, priority)
            
            return {
                "status": "success",
                "task_id": task["task_id"],
                "task_type": task["task_type"],
                "priority": task["priority"],
                "created_at": task["created_at"].isoformat(),
                "timeout_at": task["timeout_at"].isoformat(),
                "message": f"Background task created successfully"
            }
        
        elif action == "cancel":
            # Cancel task
            cancelled = await manager.cancel_task(task_id)
            if not cancelled:
                return {
                    "status": "error",
                    "message": "Task not found or cannot be cancelled"
                }
            
            return {
                "status": "success",
                "task_id": task_id,
                "action": "cancelled",
                "message": "Task cancelled successfully"
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
