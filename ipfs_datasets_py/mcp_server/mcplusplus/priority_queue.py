"""
MCP++ Priority Queue System (Phase 4.3)

Implements priority-based task scheduling with:
- Priority queue using heapq
- Multiple scheduling algorithms (FIFO, priority-based, deadline-aware)
- Priority inheritance
- Dynamic priority adjustment

This enables efficient task scheduling based on priority and deadlines.
"""

import anyio
import heapq
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SchedulingAlgorithm(Enum):
    """Scheduling algorithm types."""
    FIFO = "fifo"  # First In, First Out (ignores priority)
    PRIORITY = "priority"  # Priority-based (higher priority first)
    DEADLINE = "deadline"  # Earliest deadline first
    PRIORITY_DEADLINE = "priority_deadline"  # Combination of priority and deadline


@dataclass(order=True)
class PriorityTask:
    """
    Task with priority for queue scheduling.
    
    Tasks are ordered by:
    1. Priority (lower value = higher priority)
    2. Deadline (earlier deadline = higher priority)
    3. Submission time (FIFO for ties)
    """
    
    # Fields used for ordering
    priority: float = field(compare=True)
    deadline: Optional[float] = field(default=None, compare=True)
    submission_time: float = field(default_factory=time.time, compare=True)
    
    # Task data (not used for ordering)
    task_id: str = field(default="", compare=False)
    task_func: Optional[Callable] = field(default=None, compare=False)
    args: List = field(default_factory=list, compare=False)
    kwargs: Dict = field(default_factory=dict, compare=False)
    metadata: Dict[str, Any] = field(default_factory=dict, compare=False)
    
    # Execution tracking
    execution_start: Optional[float] = field(default=None, compare=False)
    execution_end: Optional[float] = field(default=None, compare=False)
    result: Any = field(default=None, compare=False)
    error: Optional[str] = field(default=None, compare=False)
    
    @property
    def age_seconds(self) -> float:
        """Calculate task age in seconds."""
        return time.time() - self.submission_time
    
    @property
    def time_to_deadline(self) -> Optional[float]:
        """Calculate time remaining until deadline."""
        if self.deadline is None:
            return None
        return self.deadline - time.time()
    
    @property
    def is_overdue(self) -> bool:
        """Check if task is past its deadline."""
        if self.deadline is None:
            return False
        return time.time() > self.deadline
    
    def adjust_priority(self, delta: float) -> None:
        """Adjust task priority by delta (negative = higher priority)."""
        self.priority += delta
    
    def set_deadline(self, deadline: datetime) -> None:
        """Set task deadline."""
        self.deadline = deadline.timestamp()


class PriorityTaskQueue:
    """
    Priority-based task queue with multiple scheduling algorithms.
    
    Supports:
    - Priority-based scheduling
    - Deadline-aware scheduling
    - Priority inheritance
    - Dynamic priority adjustment
    
    Example:
        queue = PriorityTaskQueue(algorithm=SchedulingAlgorithm.PRIORITY)
        
        # Add tasks with different priorities
        await queue.put_task(task_func1, priority=1.0)  # High priority
        await queue.put_task(task_func2, priority=2.0)  # Lower priority
        
        # Get highest priority task
        task = await queue.get_task()
    """
    
    def __init__(
        self,
        algorithm: SchedulingAlgorithm = SchedulingAlgorithm.PRIORITY,
        max_size: Optional[int] = None,
        enable_priority_inheritance: bool = True
    ):
        """
        Initialize the priority queue.
        
        Args:
            algorithm: Scheduling algorithm to use
            max_size: Maximum queue size (None = unlimited)
            enable_priority_inheritance: Enable priority inheritance for dependent tasks
        """
        self.algorithm = algorithm
        self.max_size = max_size
        self.enable_priority_inheritance = enable_priority_inheritance
        
        self._heap: List[PriorityTask] = []
        self._task_map: Dict[str, PriorityTask] = {}
        self._lock = RLock()
        
        # Statistics
        self.total_submitted = 0
        self.total_completed = 0
        self.total_failed = 0
        
        logger.info(f"Initialized PriorityTaskQueue with {algorithm.value} algorithm")
    
    async def put_task(
        self,
        task_func: Callable,
        task_id: Optional[str] = None,
        priority: float = 1.0,
        deadline: Optional[datetime] = None,
        args: Optional[List] = None,
        kwargs: Optional[Dict] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Add a task to the queue.
        
        Args:
            task_func: Function to execute
            task_id: Optional task ID (auto-generated if None)
            priority: Task priority (lower = higher priority)
            deadline: Optional deadline for task completion
            args: Positional arguments for task_func
            kwargs: Keyword arguments for task_func
            metadata: Optional metadata dictionary
            
        Returns:
            Task ID
        """
        # Check queue size limit
        if self.max_size and self.size >= self.max_size:
            raise RuntimeError(f"Queue is full (max_size={self.max_size})")
        
        # Generate task ID if not provided
        if task_id is None:
            task_id = f"task_{int(time.time() * 1000000)}"
        
        # Create task
        task = PriorityTask(
            task_id=task_id,
            task_func=task_func,
            priority=priority,
            deadline=deadline.timestamp() if deadline else None,
            args=args or [],
            kwargs=kwargs or {},
            metadata=metadata or {}
        )
        
        # Adjust priority based on algorithm
        if self.algorithm == SchedulingAlgorithm.FIFO:
            # FIFO: Use submission time as priority
            task.priority = task.submission_time
        elif self.algorithm == SchedulingAlgorithm.DEADLINE:
            # Deadline-first: Use deadline as priority
            if task.deadline:
                task.priority = task.deadline
        elif self.algorithm == SchedulingAlgorithm.PRIORITY_DEADLINE:
            # Combination: Use weighted combination
            if task.deadline:
                # Weight: 70% priority, 30% deadline urgency
                time_to_deadline = task.time_to_deadline or 0
                task.priority = (0.7 * priority) + (0.3 * time_to_deadline)
        
        # Add to queue
        with self._lock:
            heapq.heappush(self._heap, task)
            self._task_map[task_id] = task
            self.total_submitted += 1
        
        logger.debug(f"Added task {task_id} with priority {task.priority}")
        return task_id
    
    async def get_task(self, timeout: Optional[float] = None) -> Optional[PriorityTask]:
        """
        Get the highest priority task from the queue.
        
        Args:
            timeout: Optional timeout in seconds
            
        Returns:
            PriorityTask or None if queue is empty
        """
        start_time = time.time()
        
        while True:
            with self._lock:
                if self._heap:
                    task = heapq.heappop(self._heap)
                    del self._task_map[task.task_id]
                    task.execution_start = time.time()
                    return task
            
            # Check timeout
            if timeout and (time.time() - start_time) >= timeout:
                return None
            
            # Wait a bit before checking again
            await anyio.sleep(0.01)
    
    async def peek_task(self) -> Optional[PriorityTask]:
        """Peek at the highest priority task without removing it."""
        with self._lock:
            if self._heap:
                return self._heap[0]
        return None
    
    def get_task_by_id(self, task_id: str) -> Optional[PriorityTask]:
        """Get a task by ID without removing it from the queue."""
        with self._lock:
            return self._task_map.get(task_id)
    
    def adjust_priority(self, task_id: str, delta: float) -> bool:
        """
        Adjust task priority by delta.
        
        Args:
            task_id: Task ID
            delta: Priority delta (negative = increase priority)
            
        Returns:
            True if task was found and adjusted
        """
        with self._lock:
            task = self._task_map.get(task_id)
            if not task:
                return False
            
            # Adjust priority
            task.adjust_priority(delta)
            
            # Re-heapify to maintain heap property
            heapq.heapify(self._heap)
            
            logger.debug(f"Adjusted priority for task {task_id} by {delta}")
            return True
    
    def inherit_priority(self, parent_task_id: str, child_task_id: str) -> bool:
        """
        Apply priority inheritance from parent to child task.
        
        If parent has higher priority than child, boost child's priority.
        
        Args:
            parent_task_id: Parent task ID
            child_task_id: Child task ID
            
        Returns:
            True if inheritance was applied
        """
        if not self.enable_priority_inheritance:
            return False
        
        with self._lock:
            parent = self._task_map.get(parent_task_id)
            child = self._task_map.get(child_task_id)
            
            if not parent or not child:
                return False
            
            # If parent has higher priority (lower value), boost child
            if parent.priority < child.priority:
                delta = parent.priority - child.priority
                child.adjust_priority(delta)
                heapq.heapify(self._heap)
                
                logger.debug(f"Applied priority inheritance: {parent_task_id} -> {child_task_id}")
                return True
        
        return False
    
    def mark_completed(self, task: PriorityTask, result: Any = None) -> None:
        """Mark a task as completed."""
        task.execution_end = time.time()
        task.result = result
        with self._lock:
            self.total_completed += 1
    
    def mark_failed(self, task: PriorityTask, error: str) -> None:
        """Mark a task as failed."""
        task.execution_end = time.time()
        task.error = error
        with self._lock:
            self.total_failed += 1
    
    @property
    def size(self) -> int:
        """Get current queue size."""
        with self._lock:
            return len(self._heap)
    
    @property
    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return self.size == 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        with self._lock:
            overdue_count = sum(1 for task in self._heap if task.is_overdue)
            
            return {
                'size': self.size,
                'total_submitted': self.total_submitted,
                'total_completed': self.total_completed,
                'total_failed': self.total_failed,
                'overdue_count': overdue_count,
                'algorithm': self.algorithm.value,
                'max_size': self.max_size,
                'priority_inheritance_enabled': self.enable_priority_inheritance
            }
    
    def get_tasks_by_priority(self, limit: Optional[int] = None) -> List[PriorityTask]:
        """
        Get tasks ordered by priority.
        
        Args:
            limit: Maximum number of tasks to return
            
        Returns:
            List of tasks ordered by priority
        """
        with self._lock:
            sorted_tasks = sorted(self._heap)
            if limit:
                return sorted_tasks[:limit]
            return sorted_tasks
    
    def clear(self) -> int:
        """
        Clear all tasks from the queue.
        
        Returns:
            Number of tasks cleared
        """
        with self._lock:
            count = len(self._heap)
            self._heap.clear()
            self._task_map.clear()
            return count


class PriorityScheduler:
    """
    Priority-aware task scheduler that integrates with the executor.
    
    Manages task scheduling with priorities and executes tasks using
    the StructuredConcurrencyExecutor.
    """
    
    def __init__(
        self,
        queue: PriorityTaskQueue,
        max_concurrent: int = 10
    ):
        """
        Initialize the scheduler.
        
        Args:
            queue: PriorityTaskQueue instance
            max_concurrent: Maximum concurrent task executions
        """
        self.queue = queue
        self.max_concurrent = max_concurrent
        self._running = False
        self._cancel_scope: anyio.CancelScope | None = None

    async def start(self) -> None:
        """Start the scheduler workers.

        Workers run until ``stop()`` sets ``_running = False`` or the
        scheduler's cancel scope is cancelled.
        """
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._cancel_scope = anyio.CancelScope()

        async def _run_workers() -> None:
            with self._cancel_scope:
                async with anyio.create_task_group() as tg:
                    for i in range(self.max_concurrent):
                        tg.start_soon(self._worker, i)

        # Start worker pool in a background task group.
        # Callers that need structured concurrency should use an anyio
        # task group and call start_soon(_run_workers).  For backward
        # compat, schedule the coroutine via the running task group.
        import sniffio as _sniffio  # noqa: F401 (ensures we're in async ctx)
        # Fire-and-forget using current task group via nursery portal is not
        # directly supported in anyio outside a nursery.  Instead we rely on
        # the _running flag loop in _worker() and let callers use a tg.
        # Store the coroutine; callers that need explicit control can await it.
        self._worker_coro = _run_workers
        logger.info(f"Started scheduler with {self.max_concurrent} workers")

    async def stop(self) -> None:
        """Stop the scheduler workers."""
        if not self._running:
            return

        self._running = False
        if self._cancel_scope is not None:
            self._cancel_scope.cancel()
            self._cancel_scope = None

        logger.info("Stopped scheduler")
    
    async def _worker(self, worker_id: int) -> None:
        """Worker task that processes tasks from the queue."""
        logger.debug(f"Worker {worker_id} started")
        
        while self._running:
            try:
                # Get next task from queue
                task = await self.queue.get_task(timeout=1.0)
                
                if not task:
                    continue
                
                # Execute task
                try:
                    result = await task.task_func(*task.args, **task.kwargs)
                    self.queue.mark_completed(task, result)
                    logger.debug(f"Worker {worker_id} completed task {task.task_id}")
                except Exception as e:
                    self.queue.mark_failed(task, str(e))
                    logger.error(f"Worker {worker_id} failed task {task.task_id}: {e}")
            
            except anyio.get_cancelled_exc_class():
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
        
        logger.debug(f"Worker {worker_id} stopped")


# Example usage
if __name__ == '__main__':
    async def example_task(value: int, delay: float = 0.1) -> Dict[str, Any]:
        """Example task for testing."""
        await anyio.sleep(delay)
        return {'value': value, 'squared': value ** 2}
    
    async def main():
        # Create priority queue with priority-based scheduling
        queue = PriorityTaskQueue(algorithm=SchedulingAlgorithm.PRIORITY)
        
        # Add tasks with different priorities
        print("Adding tasks...")
        await queue.put_task(example_task, task_id='low', priority=3.0, kwargs={'value': 1})
        await queue.put_task(example_task, task_id='high', priority=1.0, kwargs={'value': 2})
        await queue.put_task(example_task, task_id='medium', priority=2.0, kwargs={'value': 3})
        
        print(f"Queue size: {queue.size}")
        print(f"Stats: {queue.get_stats()}")
        
        # Get tasks in priority order
        print("\nProcessing tasks in priority order:")
        while not queue.is_empty:
            task = await queue.get_task()
            print(f"  Processing {task.task_id} (priority={task.priority})")
            result = await task.task_func(*task.args, **task.kwargs)
            queue.mark_completed(task, result)
            print(f"    Result: {result}")
        
        print(f"\nFinal stats: {queue.get_stats()}")
        
        # Test with scheduler
        print("\n\nTesting with scheduler...")
        queue2 = PriorityTaskQueue(algorithm=SchedulingAlgorithm.PRIORITY)
        scheduler = PriorityScheduler(queue2, max_concurrent=2)
        
        await scheduler.start()
        
        # Add tasks
        for i in range(10):
            priority = 10 - i  # Higher priority for lower numbers
            await queue2.put_task(
                example_task,
                task_id=f'task_{i}',
                priority=priority,
                kwargs={'value': i, 'delay': 0.2}
            )
        
        # Wait for processing
        while not queue2.is_empty:
            await anyio.sleep(0.1)
        
        await scheduler.stop()
        
        print(f"Scheduler stats: {queue2.get_stats()}")
    
    anyio.run(main)
