# Background Task Tools

MCP tools for managing long-running background jobs: creation, status tracking, queuing, and
cancellation. Mock infrastructure lives in `background_task_engine.py`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `background_task_engine.py` | `BackgroundTaskEngine` class | Reusable mock task infrastructure (engine, not MCP-facing) |
| `background_task_tools.py` | `create_background_task()`, `check_task_status()`, `manage_background_tasks()`, `manage_task_queue()` | Create tasks, poll status, manage queue |
| `enhanced_background_task_tools.py` | `submit_task()`, `cancel_task()`, `list_tasks()`, `get_task_result()`, … | Enhanced task management with priority, retry, and result retrieval |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.background_task_tools import (
    create_background_task, check_task_status
)

# Submit a background task
task = await create_background_task(
    task_type="embedding_generation",
    params={"dataset": "my_corpus", "model": "all-MiniLM-L6-v2"},
    priority=2
)
task_id = task["task_id"]

# Poll status
status = await check_task_status(task_id=task_id)
# Returns: {"task_id": "...", "status": "running", "progress": 0.45, "eta_seconds": 120}
```

### Enhanced task management

```python
from ipfs_datasets_py.mcp_server.tools.background_task_tools import (
    submit_task, get_task_result, cancel_task, list_tasks
)

# Submit with retry
task = await submit_task(
    task_type="index_rebuild",
    params={"index": "legal_corpus"},
    max_retries=3
)

# Get result when complete
result = await get_task_result(task_id=task["task_id"], wait=True, timeout=300)

# List all running tasks
tasks = await list_tasks(status="running")

# Cancel a task
await cancel_task(task_id="task_xyz")
```

## Core Module

- `background_task_engine.BackgroundTaskEngine` — mock task infrastructure for testing

## Status

| Tool | Status |
|------|--------|
| `background_task_tools` | ✅ Production ready |
| `enhanced_background_task_tools` | ✅ Production ready |
