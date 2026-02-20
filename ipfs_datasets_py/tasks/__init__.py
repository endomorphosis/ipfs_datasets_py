"""
Background task management package for ipfs_datasets_py.

Provides task lifecycle management, status tracking, and the MockTaskManager
used in development/testing.

Reusable by:
- MCP server tools (mcp_server/tools/background_task_tools/)
- CLI commands
- Direct Python imports
"""
from .background_task_engine import (
    TaskStatus,
    TaskType,
    MockBackgroundTask,
    MockTaskManager,
)

__all__ = [
    "TaskStatus",
    "TaskType",
    "MockBackgroundTask",
    "MockTaskManager",
]
