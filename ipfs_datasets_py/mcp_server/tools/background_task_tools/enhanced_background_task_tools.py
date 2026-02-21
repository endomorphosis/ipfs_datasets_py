"""
Enhanced Background Task Tools — thin standalone-function wrappers.

Business logic is in ipfs_datasets_py.tasks.background_task_engine (via the
local background_task_engine.py shim).  Each function below replaces a class
that previously extended EnhancedBaseMCPTool.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.tasks.background_task_engine import (  # noqa: F401
    MockTaskManager,
    MockBackgroundTask,
    TaskStatus,
    TaskType,
)

logger = logging.getLogger(__name__)

_task_manager = MockTaskManager()


# ---------------------------------------------------------------------------
# 1.  manage_background_task  (was EnhancedBackgroundTaskTool)
# ---------------------------------------------------------------------------

async def manage_background_task(
    action: str = "create",
    task_type: str = "general",
    task_config: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create, retrieve, list, cancel, or cleanup background tasks."""
    try:
        valid_types = [t.value for t in TaskType]

        if action == "create":
            if task_type not in valid_types:
                return {
                    "status": "error",
                    "error": f"Invalid task type: {task_type}",
                    "code": "INVALID_TASK_TYPE",
                    "valid_types": valid_types,
                }
            cfg = task_config or {}
            new_id = await _task_manager.create_task(
                task_type=task_type,
                metadata=cfg,
                estimated_duration=cfg.get("timeout", 300),
            )
            logger.info("Background task created: %s (type: %s)", new_id, task_type)
            return {"status": "success", "task_id": new_id, "task_type": task_type,
                    "message": "Background task created successfully"}

        elif action == "get":
            if not task_id:
                return {"status": "error", "error": "task_id is required for get action", "code": "MISSING_TASK_ID"}
            task = await _task_manager.get_task(task_id)
            if not task:
                return {"status": "error", "error": "Task not found", "code": "TASK_NOT_FOUND"}
            return {"status": "success", "task": task.to_dict(), "message": "Task retrieved successfully"}

        elif action == "list":
            tasks = await _task_manager.list_tasks(**(filters or {}))
            return {"status": "success", "tasks": [t.to_dict() for t in tasks],
                    "count": len(tasks), "message": f"Found {len(tasks)} tasks"}

        elif action == "cancel":
            if not task_id:
                return {"status": "error", "error": "task_id is required for cancel action", "code": "MISSING_TASK_ID"}
            cancelled = await _task_manager.cancel_task(task_id)
            if not cancelled:
                return {"status": "error", "error": "Task not found or cannot be cancelled", "code": "CANCEL_FAILED"}
            return {"status": "success", "task_id": task_id, "message": "Task cancelled successfully"}

        elif action == "cleanup":
            opts = task_config or {}
            max_age = opts.get("max_age_hours", 24)
            cleaned = await _task_manager.cleanup_completed_tasks(max_age_hours=max_age)
            return {"status": "success", "cleaned_up": len(cleaned), "task_ids": cleaned,
                    "message": f"Cleaned up {len(cleaned)} completed tasks"}

        else:
            return {"status": "error", "error": f"Unknown action: {action}", "code": "UNKNOWN_ACTION",
                    "valid_actions": ["create", "get", "list", "cancel", "cleanup"]}

    except Exception as exc:
        logger.error("Background task operation error: %s", exc)
        return {"status": "error", "error": "Background task operation failed",
                "code": "OPERATION_FAILED", "message": str(exc)}


# ---------------------------------------------------------------------------
# 2.  get_task_status  (was EnhancedTaskStatusTool)
# ---------------------------------------------------------------------------

async def get_task_status(
    task_id: Optional[str] = None,
    include_logs: bool = True,
    include_system_status: bool = False,
    include_queue_status: bool = False,
    log_limit: int = 20,
) -> Dict[str, Any]:
    """Get comprehensive task status, progress monitoring, and system overview."""
    try:
        response_data: Dict[str, Any] = {}

        if task_id:
            task = await _task_manager.get_task(task_id)
            if not task:
                return {"status": "error", "error": "Task not found", "code": "TASK_NOT_FOUND"}
            task_data = task.to_dict()
            if not include_logs:
                task_data.pop("logs", None)
            elif "logs" in task_data:
                task_data["logs"] = task_data["logs"][-log_limit:]
            response_data["task"] = task_data

        if include_system_status:
            stats = await _task_manager.get_stats()
            response_data["system_status"] = {
                "total_tasks": stats.get("total_tasks", 0),
                "running_tasks": stats.get("running_tasks", 0),
                "pending_tasks": stats.get("pending_tasks", 0),
                "completed_tasks": stats.get("completed_tasks", 0),
                "failed_tasks": stats.get("failed_tasks", 0),
            }

        if include_queue_status:
            queue_stats = await _task_manager.get_queue_stats()
            response_data["queue_status"] = queue_stats

        if not response_data:
            # No specific task and no system/queue requested — return summary
            tasks = await _task_manager.list_tasks()
            response_data["summary"] = {
                "total_tasks": len(tasks),
                "task_ids": [t.to_dict().get("task_id") for t in tasks],
            }

        return {"status": "success", **response_data, "message": "Task status retrieved successfully"}

    except Exception as exc:
        logger.error("Task status retrieval error: %s", exc)
        return {"status": "error", "error": "Task status retrieval failed",
                "code": "STATUS_FAILED", "message": str(exc)}
