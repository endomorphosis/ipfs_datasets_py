# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/background_task_tools/background_task_tools.py'

Files last updated: 1751408933.6864564

Stub file last updated: 2025-07-07 01:10:13

## MockTaskManager

```python
class MockTaskManager:
    """
    Mock task manager for testing purposes.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TaskStatus

```python
class TaskStatus(Enum):
    """
    Task status enumeration.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TaskType

```python
class TaskType(Enum):
    """
    Task type enumeration.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** MockTaskManager

## cancel_task

```python
async def cancel_task(self, task_id: str) -> bool:
    """
    Cancel a task.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockTaskManager

## check_task_status

```python
async def check_task_status(task_id: Optional[str] = None, task_type: str = "all", status_filter: str = "all", limit: int = 20, task_manager = None) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## create_task

```python
async def create_task(self, task_type: str, parameters: Dict[str, Any], priority: str = "normal", timeout_seconds: int = 3600) -> Dict[str, Any]:
    """
    Create a new background task.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockTaskManager

## get_queue_stats

```python
async def get_queue_stats(self) -> Dict[str, Any]:
    """
    Get task queue statistics.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockTaskManager

## get_task_status

```python
async def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
    """
    Get task status by ID.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockTaskManager

## list_tasks

```python
async def list_tasks(self, task_type: Optional[str] = None, status: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """
    List tasks with optional filters.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockTaskManager

## manage_background_tasks

```python
async def manage_background_tasks(action: str, task_id: Optional[str] = None, task_type: Optional[str] = None, parameters: Optional[Dict[str, Any]] = None, priority: str = "normal", task_manager = None) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## manage_task_queue

```python
async def manage_task_queue(action: str, priority: Optional[str] = None, max_concurrent: Optional[int] = None, task_manager = None) -> Dict[str, Any]:
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
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## update_task

```python
async def update_task(self, task_id: str, **kwargs) -> bool:
    """
    Update task data.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MockTaskManager
