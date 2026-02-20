"""
Workflow Engine for P2P Task Orchestration

Provides DAG-based workflow execution with task coordination, dependency
management, and distributed execution support.

Author: MCP Server Team
Date: 2026-02-18
"""

import inspect
import anyio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Any, Callable
from enum import Enum
import json
import logging

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of a workflow task."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class WorkflowStatus(Enum):
    """Status of a workflow."""
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class Task:
    """
    Represents a single task in a workflow.
    
    Attributes:
        task_id: Unique identifier for the task
        name: Human-readable task name
        function: Function to execute (callable or string reference)
        args: Positional arguments for the function
        kwargs: Keyword arguments for the function
        dependencies: List of task IDs that must complete first
        status: Current status of the task
        result: Result of task execution (if completed)
        error: Error message (if failed)
        start_time: When the task started executing
        end_time: When the task finished
        retry_count: Number of times task has been retried
        max_retries: Maximum number of retry attempts
        timeout: Task timeout in seconds
        metadata: Additional task metadata
    """
    task_id: str
    name: str
    function: Any  # Callable or string reference
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 0
    timeout: float = 300.0  # 5 minutes default
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_ready(self, completed_tasks: Set[str]) -> bool:
        """Check if all dependencies are satisfied."""
        if self.status != TaskStatus.PENDING:
            return False
        return all(dep in completed_tasks for dep in self.dependencies)
    
    def can_retry(self) -> bool:
        """Check if task can be retried."""
        return self.status == TaskStatus.FAILED and self.retry_count < self.max_retries
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary."""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "dependencies": self.dependencies,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "metadata": self.metadata
        }


@dataclass
class Workflow:
    """
    Represents a workflow (DAG of tasks).
    
    Attributes:
        workflow_id: Unique identifier for the workflow
        name: Human-readable workflow name
        description: Workflow description
        tasks: Dictionary of task_id -> Task
        status: Current workflow status
        created_time: When the workflow was created
        start_time: When execution started
        end_time: When execution finished
        metadata: Additional workflow metadata
    """
    workflow_id: str
    name: str
    description: str = ""
    tasks: Dict[str, Task] = field(default_factory=dict)
    status: WorkflowStatus = WorkflowStatus.CREATED
    created_time: float = field(default_factory=time.time)
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_task(self, task: Task) -> None:
        """Add a task to the workflow."""
        if task.task_id in self.tasks:
            raise ValueError(f"Task {task.task_id} already exists in workflow")
        self.tasks[task.task_id] = task
    
    def validate_dag(self) -> None:
        """Validate that tasks form a valid DAG (no cycles)."""
        def has_cycle(task_id: str, visited: Set[str], rec_stack: Set[str]) -> bool:
            visited.add(task_id)
            rec_stack.add(task_id)
            
            task = self.tasks.get(task_id)
            if task:
                for dep in task.dependencies:
                    if dep not in visited:
                        if has_cycle(dep, visited, rec_stack):
                            return True
                    elif dep in rec_stack:
                        return True
            
            rec_stack.remove(task_id)
            return False
        
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        
        for task_id in self.tasks:
            if task_id not in visited:
                if has_cycle(task_id, visited, rec_stack):
                    raise ValueError(f"Workflow contains a cycle involving task {task_id}")
    
    def get_ready_tasks(self, completed_tasks: Set[str]) -> List[Task]:
        """Get all tasks that are ready to execute."""
        ready = []
        for task in self.tasks.values():
            if task.is_ready(completed_tasks):
                ready.append(task)
        return ready
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert workflow to dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "tasks": {tid: task.to_dict() for tid, task in self.tasks.items()},
            "status": self.status.value,
            "created_time": self.created_time,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "metadata": self.metadata
        }


class WorkflowEngine:
    """
    Engine for executing workflows with DAG-based task coordination.
    
    Features:
    - DAG validation (cycle detection)
    - Parallel task execution
    - Dependency management
    - Task retry logic
    - Timeout handling
    - Progress tracking
    """
    
    def __init__(self, max_concurrent_tasks: int = 10):
        """
        Initialize workflow engine.
        
        Args:
            max_concurrent_tasks: Maximum number of tasks to run in parallel
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self.workflows: Dict[str, Workflow] = {}
        self.task_functions: Dict[str, Callable] = {}
        self._running_tasks: Set[str] = set()
        self._semaphore = anyio.Semaphore(max_concurrent_tasks)
    
    def register_function(self, name: str, func: Callable) -> None:
        """Register a task function."""
        self.task_functions[name] = func
    
    def create_workflow(
        self,
        workflow_id: str,
        name: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Workflow:
        """
        Create a new workflow.
        
        Args:
            workflow_id: Unique workflow identifier
            name: Human-readable name
            description: Workflow description
            metadata: Additional metadata
            
        Returns:
            Created Workflow object
        """
        if workflow_id in self.workflows:
            raise ValueError(f"Workflow {workflow_id} already exists")
        
        workflow = Workflow(
            workflow_id=workflow_id,
            name=name,
            description=description,
            metadata=metadata or {}
        )
        self.workflows[workflow_id] = workflow
        return workflow
    
    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """Get a workflow by ID."""
        return self.workflows.get(workflow_id)
    
    async def execute_task(self, workflow: Workflow, task: Task) -> None:
        """
        Execute a single task.
        
        Args:
            workflow: The workflow containing the task
            task: The task to execute
        """
        async with self._semaphore:
            task.status = TaskStatus.RUNNING
            task.start_time = time.time()
            self._running_tasks.add(task.task_id)
            
            try:
                # Get the function to execute
                if isinstance(task.function, str):
                    func = self.task_functions.get(task.function)
                    if not func:
                        raise ValueError(f"Function {task.function} not registered")
                else:
                    func = task.function
                
                # Execute with timeout
                try:
                    with anyio.fail_after(task.timeout):
                        if inspect.iscoroutinefunction(func):
                            task.result = await func(*task.args, **task.kwargs)
                        else:
                            # Run sync function in thread pool
                            task.result = await anyio.to_thread.run_sync(
                                lambda: func(*task.args, **task.kwargs)
                            )
                    
                    task.status = TaskStatus.COMPLETED
                    logger.info(f"Task {task.task_id} completed successfully")
                    
                except TimeoutError:
                    task.status = TaskStatus.FAILED
                    task.error = f"Task timed out after {task.timeout}s"
                    logger.error(f"Task {task.task_id} timed out")
                    
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                logger.error(f"Task {task.task_id} failed: {e}")
            
            finally:
                task.end_time = time.time()
                self._running_tasks.discard(task.task_id)
    
    async def execute_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Execute a workflow.
        
        Args:
            workflow_id: ID of workflow to execute
            
        Returns:
            Dictionary with execution results
        """
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")
        
        # Validate DAG
        workflow.validate_dag()
        
        # Update workflow status
        workflow.status = WorkflowStatus.RUNNING
        workflow.start_time = time.time()
        
        completed_tasks: Set[str] = set()
        failed_tasks: Set[str] = set()
        try:
            while True:
                # Get ready tasks
                ready_tasks = workflow.get_ready_tasks(completed_tasks)
                
                # Mark ready tasks
                for task in ready_tasks:
                    task.status = TaskStatus.READY
                
                # Launch ready tasks via anyio task group
                if ready_tasks:
                    async with anyio.create_task_group() as tg:
                        for task in ready_tasks:
                            tg.start_soon(self.execute_task, workflow, task)

                    # After task group exits all tasks are done - check status
                    for task in ready_tasks:
                        task_id = task.task_id
                        if task.status == TaskStatus.COMPLETED:
                            completed_tasks.add(task_id)
                        elif task.status == TaskStatus.FAILED:
                            if task.can_retry():
                                task.retry_count += 1
                                task.status = TaskStatus.PENDING
                                logger.info(f"Retrying task {task_id} (attempt {task.retry_count + 1})")
                            else:
                                failed_tasks.add(task_id)
                else:
                    # No running tasks and no ready tasks
                    break
            
            # Check if all tasks completed
            all_completed = all(
                t.status == TaskStatus.COMPLETED 
                for t in workflow.tasks.values()
            )
            
            if all_completed:
                workflow.status = WorkflowStatus.COMPLETED
            elif failed_tasks:
                workflow.status = WorkflowStatus.FAILED
            else:
                workflow.status = WorkflowStatus.COMPLETED
                
        except Exception as e:
            workflow.status = WorkflowStatus.FAILED
            logger.error(f"Workflow {workflow_id} execution failed: {e}")
        
        finally:
            workflow.end_time = time.time()
        
        return {
            "workflow_id": workflow_id,
            "status": workflow.status.value,
            "completed_tasks": len(completed_tasks),
            "failed_tasks": len(failed_tasks),
            "total_tasks": len(workflow.tasks),
            "execution_time": workflow.end_time - workflow.start_time if workflow.end_time and workflow.start_time else 0
        }
    
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """
        Cancel a running workflow.
        
        Args:
            workflow_id: ID of workflow to cancel
            
        Returns:
            True if cancelled successfully
        """
        workflow = self.workflows.get(workflow_id)
        if not workflow or workflow.status != WorkflowStatus.RUNNING:
            return False
        
        workflow.status = WorkflowStatus.CANCELLED
        workflow.end_time = time.time()
        
        # Mark running tasks as cancelled
        for task in workflow.tasks.values():
            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.CANCELLED
        
        return True
    
    def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a workflow."""
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            return None
        
        return workflow.to_dict()


# Global workflow engine instance
_workflow_engine: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    """Get or create the global workflow engine."""
    global _workflow_engine
    if _workflow_engine is None:
        _workflow_engine = WorkflowEngine()
    return _workflow_engine


def reset_workflow_engine() -> None:
    """Reset the global workflow engine (for testing)."""
    global _workflow_engine
    _workflow_engine = None
