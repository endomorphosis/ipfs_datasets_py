"""
Background Task Engine — reusable mock task infrastructure.

This engine is independent of MCP and can be imported directly by tests, CLI
tools, or other modules.  MCP tool wrappers in
``enhanced_background_task_tools.py`` import from here.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskType(Enum):
    """Types of background task that the system understands."""

    CREATE_EMBEDDINGS = "create_embeddings"
    SHARD_EMBEDDINGS = "shard_embeddings"
    INDEX_SPARSE = "index_sparse"
    INDEX_CLUSTER = "index_cluster"
    SEARCH_EMBEDDINGS = "search_embeddings"
    DATA_PROCESSING = "data_processing"
    IPFS_OPERATIONS = "ipfs_operations"
    CLEANUP = "cleanup"
    BACKUP = "backup"
    GENERAL = "general"


class MockBackgroundTask:
    """Mock background task for testing and development."""

    def __init__(self, task_id: str, task_type: str, **kwargs: Any) -> None:
        self.task_id = task_id
        self.task_type = task_type
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.progress: float = 0.0
        self.metadata: Dict[str, Any] = kwargs.get("metadata", {})
        self.logs: List[Dict[str, Any]] = []
        self.result: Any = None
        self.error: Optional[str] = None
        self.estimated_duration: int = kwargs.get("estimated_duration", 300)

    def add_log(self, level: str, message: str) -> None:
        """Append a log entry."""
        self.logs.append(
            {"timestamp": datetime.now().isoformat(), "level": level, "message": message}
        )

    def update_progress(self, progress: float) -> None:
        """Update progress (0.0–1.0) and auto-transition to RUNNING."""
        self.progress = max(0.0, min(1.0, progress))
        if self.status == TaskStatus.PENDING and progress > 0:
            self.status = TaskStatus.RUNNING
            self.started_at = datetime.now()

    def complete(self, result: Any = None) -> None:
        """Mark as COMPLETED."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now()
        self.progress = 1.0
        self.result = result
        self.add_log("INFO", "Task completed successfully")

    def fail(self, error: str) -> None:
        """Mark as FAILED."""
        self.status = TaskStatus.FAILED
        self.completed_at = datetime.now()
        self.error = error
        self.add_log("ERROR", f"Task failed: {error}")

    def cancel(self) -> None:
        """Mark as CANCELLED."""
        self.status = TaskStatus.CANCELLED
        self.completed_at = datetime.now()
        self.add_log("INFO", "Task cancelled")

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable representation."""
        elapsed_time: Optional[float] = None
        estimated_completion: Optional[str] = None
        if self.started_at:
            elapsed_time = (datetime.now() - self.started_at).total_seconds()
            if self.progress > 0 and self.status == TaskStatus.RUNNING:
                remaining = (elapsed_time / self.progress) * (1 - self.progress)
                estimated_completion = (datetime.now() + timedelta(seconds=remaining)).isoformat()
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "progress": self.progress,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "elapsed_time": elapsed_time,
            "estimated_completion": estimated_completion,
            "metadata": self.metadata,
            "logs": self.logs[-10:],
            "result": self.result,
            "error": self.error,
        }


class MockTaskManager:
    """Enhanced mock task manager with production-like features."""

    def __init__(self) -> None:
        self.tasks: Dict[str, MockBackgroundTask] = {}
        self.task_queues: Dict[str, List[str]] = {t.value: [] for t in TaskType}
        self.running_tasks: Dict[str, MockBackgroundTask] = {}
        self.task_history: List[Dict[str, Any]] = []
        self.max_concurrent_tasks: int = 5

    async def create_task(self, task_type: str, **kwargs: Any) -> str:
        """Create a new background task and return its ID."""
        task_id = str(uuid.uuid4())
        task = MockBackgroundTask(task_id, task_type, **kwargs)
        task.add_log("INFO", f"Task created: {task_type}")
        self.tasks[task_id] = task
        queue = self.task_queues.get(task_type, self.task_queues[TaskType.GENERAL.value])
        queue.append(task_id)
        await self._process_queue()
        return task_id

    async def get_task(self, task_id: str) -> Optional[MockBackgroundTask]:
        """Return the task for *task_id*, simulating progress if running."""
        task = self.tasks.get(task_id)
        if task and task.status == TaskStatus.RUNNING:
            await self._simulate_task_progress(task)
        return task

    async def list_tasks(self, **filters: Any) -> List[MockBackgroundTask]:
        """Return tasks with optional filtering by status / task_type / limit."""
        tasks = list(self.tasks.values())
        if filters.get("status") and filters["status"] != "all":
            tasks = [t for t in tasks if t.status.value == filters["status"]]
        if filters.get("task_type") and filters["task_type"] != "all":
            tasks = [t for t in tasks if t.task_type == filters["task_type"]]
        limit = int(filters.get("limit", 50))
        tasks = sorted(tasks, key=lambda t: t.created_at, reverse=True)[:limit]
        for task in tasks:
            if task.status == TaskStatus.RUNNING:
                await self._simulate_task_progress(task)
        return tasks

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or running task. Returns True if cancelled."""
        task = self.tasks.get(task_id)
        if not task:
            return False
        if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.cancel()
            for queue in self.task_queues.values():
                if task_id in queue:
                    queue.remove(task_id)
                    break
            self.running_tasks.pop(task_id, None)
            return True
        return False

    async def cleanup_completed_tasks(self, max_age_hours: int = 24) -> List[str]:
        """Remove completed/failed/cancelled tasks older than *max_age_hours*."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        cleaned: List[str] = []
        terminal = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        for task_id, task in list(self.tasks.items()):
            if task.status in terminal and task.completed_at and task.completed_at < cutoff:
                self.task_history.append(task.to_dict())
                del self.tasks[task_id]
                cleaned.append(task_id)
        if len(self.task_history) > 1000:
            self.task_history = self.task_history[-1000:]
        return cleaned

    async def get_stats(self) -> Dict[str, Any]:
        """Return aggregate task statistics."""
        tasks = list(self.tasks.values())
        status_counts: Dict[str, int] = {}
        for task in tasks:
            status_counts[task.status.value] = status_counts.get(task.status.value, 0) + 1
        return {
            "total_tasks": len(tasks),
            "status_breakdown": status_counts,
            "running_tasks": len(self.running_tasks),
            "max_concurrent": self.max_concurrent_tasks,
            "task_history_size": len(self.task_history),
        }

    async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return serialisable status dict for *task_id* (compat alias for get_task)."""
        task = await self.get_task(task_id)
        return task.to_dict() if task else None

    async def update_task(self, task_id: str, **kwargs: Any) -> bool:
        """Update arbitrary attributes on a task by keyword argument. Returns True if found."""
        task = self.tasks.get(task_id)
        if task is None:
            return False
        for key, value in kwargs.items():
            if key == "status":
                # Accept either a string value or a TaskStatus member
                if isinstance(value, str):
                    try:
                        task.status = TaskStatus(value)
                    except ValueError:
                        task.status = TaskStatus.RUNNING  # safe fallback
                else:
                    task.status = value
            elif hasattr(task, key):
                setattr(task, key, value)
        return True

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Return queue-level counters compatible with the legacy API."""
        tasks = list(self.tasks.values())
        counters = {s.value: 0 for s in TaskStatus}
        for task in tasks:
            counters[task.status.value] = counters.get(task.status.value, 0) + 1
        return {
            "queues": {
                ttype: len(queue) for ttype, queue in self.task_queues.items()
            },
            "running_tasks": len(self.running_tasks),
            "total_tasks": len(tasks),
            "counters": {
                "created": len(tasks),
                "completed": counters.get("completed", 0),
                "failed": counters.get("failed", 0),
                "cancelled": counters.get("cancelled", 0),
            },
        }

    async def _process_queue(self) -> None:
        """Promote pending tasks to running when capacity allows."""
        if len(self.running_tasks) >= self.max_concurrent_tasks:
            return
        for task_type in TaskType:
            queue = self.task_queues[task_type.value]
            while queue and len(self.running_tasks) < self.max_concurrent_tasks:
                task_id = queue.pop(0)
                task = self.tasks.get(task_id)
                if task and task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.RUNNING
                    task.started_at = datetime.now()
                    task.add_log("INFO", "Task started")
                    self.running_tasks[task_id] = task

    async def _simulate_task_progress(self, task: MockBackgroundTask) -> None:
        """Simulate progress for a running task (demo / test purposes)."""
        if task.status != TaskStatus.RUNNING or task.started_at is None:
            return
        elapsed = (datetime.now() - task.started_at).total_seconds()
        task.progress = min(0.95, elapsed / task.estimated_duration)
        task.progress += (hash(task.task_id) % 10) / 1000
        if elapsed > task.estimated_duration:
            result: Dict[str, Any]
            if task.task_type == TaskType.CREATE_EMBEDDINGS.value:
                result = {
                    "embeddings_created": 1000,
                    "model": "sentence-transformers/all-MiniLM-L6-v2",
                    "output_path": f"/tmp/embeddings_{task.task_id[:8]}.npz",
                }
            elif task.task_type == TaskType.SHARD_EMBEDDINGS.value:
                result = {
                    "shards_created": 4,
                    "shard_size": 250,
                    "output_dir": f"/tmp/shards_{task.task_id[:8]}/",
                }
            else:
                result = {"status": "completed", "processed_items": 500}
            task.complete(result)
            self.running_tasks.pop(task.task_id, None)


__all__ = [
    "TaskStatus",
    "TaskType",
    "MockBackgroundTask",
    "MockTaskManager",
]
