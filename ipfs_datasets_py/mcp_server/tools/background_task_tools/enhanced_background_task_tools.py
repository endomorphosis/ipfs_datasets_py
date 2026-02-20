"""
Background Task Management MCP tools.
(Mock infrastructure lives in background_task_engine.py)
"""

import logging
import anyio
from typing import Dict, Any, Optional, List

from ..tool_wrapper import EnhancedBaseMCPTool
from ..validators import EnhancedParameterValidator
from ..monitoring import EnhancedMetricsCollector

# Import engine types — re-export for backward compatibility
from .background_task_engine import (  # noqa: F401
    TaskStatus,
    TaskType,
    MockBackgroundTask,
    MockTaskManager,
)

logger = logging.getLogger(__name__)


class EnhancedBackgroundTaskTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for creating and managing background tasks.
    """

    def __init__(self, task_manager=None):
        super().__init__(
            name="create_background_task",
            description="Create and manage background tasks for embedding operations and data processing",
            category="background_tasks"
        )
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["create", "get", "list", "cancel", "cleanup"],
                    "default": "create"
                },
                "task_type": {
                    "type": "string",
                    "description": "Type of background task",
                    "enum": [t.value for t in TaskType],
                    "default": "general"
                },
                "task_id": {
                    "type": "string",
                    "description": "Task ID for get/cancel operations",
                    "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
                },
                "task_config": {
                    "type": "object",
                    "description": "Configuration for the task",
                    "properties": {
                        "dataset": {"type": "string"},
                        "model": {"type": "string"},
                        "batch_size": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1000,
                            "default": 100
                        },
                        "timeout": {
                            "type": "integer",
                            "minimum": 60,
                            "maximum": 86400,
                            "default": 3600
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "normal", "high"],
                            "default": "normal"
                        }
                    }
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for list operation",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["pending", "running", "completed", "failed", "cancelled", "all"],
                            "default": "all"
                        },
                        "task_type": {
                            "type": "string",
                            "enum": [t.value for t in TaskType] + ["all"],
                            "default": "all"
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 20
                        }
                    }
                },
                "cleanup_options": {
                    "type": "object",
                    "description": "Options for cleanup operation",
                    "properties": {
                        "max_age_hours": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 168,
                            "default": 24
                        },
                        "dry_run": {
                            "type": "boolean",
                            "default": false
                        }
                    }
                }
            },
            "required": ["action"]
        }
        
        self.task_manager = task_manager or MockTaskManager()
        self.tags = ["background", "tasks", "async", "management", "jobs"]

    async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute background task operations."""
        try:
            action = parameters.get("action", "create")
            
            # Track task operation
            self.metrics.record_request("background_task_operation", {"action": action})
            
            if action == "create":
                task_type = parameters.get("task_type", "general")
                task_config = parameters.get("task_config", {})
                
                # Validate task type
                valid_types = [t.value for t in TaskType]
                if task_type not in valid_types:
                    return {
                        "status": "error",
                        "error": f"Invalid task type: {task_type}",
                        "code": "INVALID_TASK_TYPE",
                        "valid_types": valid_types
                    }
                
                # Create task
                task_id = await self.task_manager.create_task(
                    task_type=task_type,
                    metadata=task_config,
                    estimated_duration=task_config.get("timeout", 300)
                )
                
                self.logger.info(f"Background task created: {task_id} (type: {task_type})")
                self.metrics.record_request("background_task_created", {"task_type": task_type})
                
                return {
                    "status": "success",
                    "task_id": task_id,
                    "task_type": task_type,
                    "message": f"Background task created successfully"
                }
            
            elif action == "get":
                task_id = parameters.get("task_id")
                if not task_id:
                    return {
                        "status": "error",
                        "error": "task_id is required for get action",
                        "code": "MISSING_TASK_ID"
                    }
                
                task = await self.task_manager.get_task(task_id)
                if not task:
                    return {
                        "status": "error",
                        "error": "Task not found",
                        "code": "TASK_NOT_FOUND"
                    }
                
                return {
                    "status": "success",
                    "task": task.to_dict(),
                    "message": "Task retrieved successfully"
                }
            
            elif action == "list":
                filters = parameters.get("filters", {})
                tasks = await self.task_manager.list_tasks(**filters)
                
                task_dicts = [task.to_dict() for task in tasks]
                
                return {
                    "status": "success",
                    "tasks": task_dicts,
                    "count": len(task_dicts),
                    "filters_applied": filters,
                    "message": f"Retrieved {len(task_dicts)} tasks"
                }
            
            elif action == "cancel":
                task_id = parameters.get("task_id")
                if not task_id:
                    return {
                        "status": "error",
                        "error": "task_id is required for cancel action",
                        "code": "MISSING_TASK_ID"
                    }
                
                cancelled = await self.task_manager.cancel_task(task_id)
                if not cancelled:
                    return {
                        "status": "error",
                        "error": "Task not found or cannot be cancelled",
                        "code": "CANCEL_FAILED"
                    }
                
                self.logger.info(f"Background task cancelled: {task_id}")
                return {
                    "status": "success",
                    "task_id": task_id,
                    "message": "Task cancelled successfully"
                }
            
            elif action == "cleanup":
                cleanup_options = parameters.get("cleanup_options", {})
                max_age_hours = cleanup_options.get("max_age_hours", 24)
                dry_run = cleanup_options.get("dry_run", False)
                
                if dry_run:
                    # Simulate cleanup
                    all_tasks = await self.task_manager.list_tasks()
                    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
                    
                    would_cleanup = []
                    for task in all_tasks:
                        if (task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED] and
                            task.completed_at and task.completed_at < cutoff_time):
                            would_cleanup.append(task.task_id)
                    
                    return {
                        "status": "success",
                        "dry_run": True,
                        "would_cleanup": len(would_cleanup),
                        "task_ids": would_cleanup,
                        "message": f"Would cleanup {len(would_cleanup)} tasks"
                    }
                else:
                    cleaned_tasks = await self.task_manager.cleanup_completed_tasks(max_age_hours)
                    
                    self.logger.info(f"Cleaned up {len(cleaned_tasks)} completed tasks")
                    return {
                        "status": "success",
                        "cleaned_up": len(cleaned_tasks),
                        "task_ids": cleaned_tasks,
                        "message": f"Cleaned up {len(cleaned_tasks)} tasks"
                    }
            
            else:
                return {
                    "status": "error",
                    "error": f"Unknown action: {action}",
                    "code": "UNKNOWN_ACTION"
                }
            
        except Exception as e:
            self.logger.error(f"Background task operation error: {e}")
            self.metrics.record_error("background_task_error", str(e))
            return {
                "status": "error",
                "error": "Background task operation failed",
                "code": "OPERATION_FAILED",
                "message": str(e)
            }


class EnhancedTaskStatusTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for monitoring task status and progress.
    """

    def __init__(self, task_manager=None):
        super().__init__(
            name="get_task_status",
            description="Get comprehensive task status, progress monitoring, and system overview",
            category="background_tasks"
        )
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Specific task ID to monitor",
                    "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
                },
                "include_logs": {
                    "type": "boolean",
                    "description": "Include task execution logs",
                    "default": true
                },
                "include_system_status": {
                    "type": "boolean",
                    "description": "Include overall system status",
                    "default": false
                },
                "include_queue_status": {
                    "type": "boolean",
                    "description": "Include task queue information",
                    "default": false
                },
                "log_limit": {
                    "type": "integer",
                    "description": "Maximum number of log entries to return",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20
                }
            },
            "required": []
        }
        
        self.task_manager = task_manager or MockTaskManager()
        self.tags = ["tasks", "status", "monitoring", "progress", "logs"]

    async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task status monitoring."""
        try:
            task_id = parameters.get("task_id")
            include_logs = parameters.get("include_logs", True)
            include_system_status = parameters.get("include_system_status", False)
            include_queue_status = parameters.get("include_queue_status", False)
            log_limit = parameters.get("log_limit", 20)
            
            # Track status check request
            self.metrics.record_request("task_status_check")
            
            response_data = {}
            
            if task_id:
                # Get specific task status
                task = await self.task_manager.get_task(task_id)
                if not task:
                    return {
                        "status": "error",
                        "error": "Task not found",
                        "code": "TASK_NOT_FOUND"
                    }
                
                task_data = task.to_dict()
                
                if not include_logs:
                    task_data.pop("logs", None)
                elif "logs" in task_data:
                    task_data["logs"] = task_data["logs"][-log_limit:]
                
                response_data["task"] = task_data
            
            if include_system_status:
                # Get system-wide task statistics
                all_tasks = await self.task_manager.list_tasks(limit=1000)
                
                status_counts = {}
                type_counts = {}
                
                for task in all_tasks:
                    status = task.status.value
                    task_type = task.task_type
                    
                    status_counts[status] = status_counts.get(status, 0) + 1
                    type_counts[task_type] = type_counts.get(task_type, 0) + 1
                
                # Calculate average completion time for completed tasks
                completed_tasks = [t for t in all_tasks if t.status == TaskStatus.COMPLETED and t.completed_at]
                avg_completion_time = None
                
                if completed_tasks:
                    total_time = sum((t.completed_at - t.started_at).total_seconds() for t in completed_tasks if t.started_at)
                    avg_completion_time = total_time / len(completed_tasks)
                
                response_data["system_status"] = {
                    "total_tasks": len(all_tasks),
                    "status_breakdown": status_counts,
                    "type_breakdown": type_counts,
                    "running_tasks": len(self.task_manager.running_tasks),
                    "max_concurrent": self.task_manager.max_concurrent_tasks,
                    "average_completion_time": avg_completion_time,
                    "task_history_size": len(self.task_manager.task_history)
                }
            
            if include_queue_status:
                # Get queue information
                queue_info = {}
                total_queued = 0
                
                for task_type, queue in self.task_manager.task_queues.items():
                    queue_size = len(queue)
                    queue_info[task_type] = {
                        "queued_tasks": queue_size,
                        "next_task": queue[0] if queue else None
                    }
                    total_queued += queue_size
                
                response_data["queue_status"] = {
                    "total_queued": total_queued,
                    "queues": queue_info,
                    "processing_capacity": self.task_manager.max_concurrent_tasks - len(self.task_manager.running_tasks)
                }
            
            # Add summary if no specific task requested
            if not task_id:
                running_tasks = list(self.task_manager.running_tasks.values())
                response_data["summary"] = {
                    "currently_running": len(running_tasks),
                    "running_task_ids": [t.task_id for t in running_tasks],
                    "system_health": "operational",
                    "last_updated": datetime.now().isoformat()
                }
            
            return {
                "status": "success",
                "monitoring_data": response_data,
                "message": "Task status retrieved successfully"
            }
            
        except Exception as e:
            self.logger.error(f"Task status monitoring error: {e}")
            self.metrics.record_error("task_status_error", str(e))
            return {
                "status": "error",
                "error": "Task status monitoring failed",
                "code": "MONITORING_FAILED",
                "message": str(e)
            }
