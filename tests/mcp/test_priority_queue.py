"""
Tests for MCP++ Priority Queue System (Phase 4.3)

Tests priority-based scheduling, deadline awareness, priority inheritance,
and dynamic priority adjustment.
"""

import pytest
import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, Any

from ipfs_datasets_py.mcp_server.mcplusplus.priority_queue import (
    PriorityTask,
    PriorityTaskQueue,
    PriorityScheduler,
    SchedulingAlgorithm
)


# Test fixtures

async def simple_task(value: int) -> Dict[str, Any]:
    """Simple test task."""
    await asyncio.sleep(0.01)
    return {'value': value}


async def slow_task(delay: float = 0.5) -> Dict[str, Any]:
    """Slow test task."""
    await asyncio.sleep(delay)
    return {'completed': True}


async def failing_task() -> Dict[str, Any]:
    """Task that always fails."""
    raise ValueError("Test error")


# Tests

class TestPriorityTask:
    """Test PriorityTask dataclass."""
    
    def test_task_creation(self):
        """Test creating a priority task."""
        task = PriorityTask(
            task_id='test',
            priority=1.0,
            task_func=simple_task
        )
        
        assert task.task_id == 'test'
        assert task.priority == 1.0
        assert task.task_func == simple_task
        assert task.execution_start is None
        assert task.execution_end is None
    
    def test_task_ordering_by_priority(self):
        """Test tasks are ordered by priority."""
        task1 = PriorityTask(task_id='low', priority=3.0)
        task2 = PriorityTask(task_id='high', priority=1.0)
        task3 = PriorityTask(task_id='medium', priority=2.0)
        
        tasks = sorted([task1, task2, task3])
        
        assert tasks[0].task_id == 'high'
        assert tasks[1].task_id == 'medium'
        assert tasks[2].task_id == 'low'
    
    def test_task_ordering_with_deadline(self):
        """Test tasks are ordered by deadline when priorities equal."""
        now = time.time()
        
        task1 = PriorityTask(task_id='late', priority=1.0, deadline=now + 100)
        task2 = PriorityTask(task_id='soon', priority=1.0, deadline=now + 10)
        task3 = PriorityTask(task_id='urgent', priority=1.0, deadline=now + 1)
        
        tasks = sorted([task1, task2, task3])
        
        assert tasks[0].task_id == 'urgent'
        assert tasks[1].task_id == 'soon'
        assert tasks[2].task_id == 'late'
    
    def test_task_age(self):
        """Test task age calculation."""
        task = PriorityTask(task_id='test', priority=1.0)
        time.sleep(0.1)
        
        assert task.age_seconds >= 0.1
    
    def test_time_to_deadline(self):
        """Test time to deadline calculation."""
        now = time.time()
        task = PriorityTask(
            task_id='test',
            priority=1.0,
            deadline=now + 10
        )
        
        ttd = task.time_to_deadline
        assert ttd is not None
        assert 9 < ttd < 11  # Allow for small timing variations
    
    def test_is_overdue(self):
        """Test overdue detection."""
        now = time.time()
        
        task_past = PriorityTask(task_id='past', priority=1.0, deadline=now - 1)
        task_future = PriorityTask(task_id='future', priority=1.0, deadline=now + 100)
        
        assert task_past.is_overdue is True
        assert task_future.is_overdue is False
    
    def test_adjust_priority(self):
        """Test priority adjustment."""
        task = PriorityTask(task_id='test', priority=5.0)
        
        task.adjust_priority(-2.0)  # Increase priority
        assert task.priority == 3.0
        
        task.adjust_priority(1.0)  # Decrease priority
        assert task.priority == 4.0


@pytest.mark.asyncio
class TestPriorityTaskQueue:
    """Test PriorityTaskQueue class."""
    
    async def test_queue_initialization(self):
        """Test queue initialization."""
        queue = PriorityTaskQueue(
            algorithm=SchedulingAlgorithm.PRIORITY,
            max_size=100
        )
        
        assert queue.algorithm == SchedulingAlgorithm.PRIORITY
        assert queue.max_size == 100
        assert queue.size == 0
        assert queue.is_empty is True
    
    async def test_put_and_get_task(self):
        """Test adding and retrieving tasks."""
        queue = PriorityTaskQueue()
        
        task_id = await queue.put_task(
            simple_task,
            priority=1.0,
            kwargs={'value': 42}
        )
        
        assert task_id is not None
        assert queue.size == 1
        
        task = await queue.get_task()
        
        assert task is not None
        assert task.task_func == simple_task
        assert task.kwargs == {'value': 42}
        assert queue.size == 0
    
    async def test_priority_ordering(self):
        """Test tasks are retrieved in priority order."""
        queue = PriorityTaskQueue(algorithm=SchedulingAlgorithm.PRIORITY)
        
        # Add tasks with different priorities
        await queue.put_task(simple_task, task_id='low', priority=3.0)
        await queue.put_task(simple_task, task_id='high', priority=1.0)
        await queue.put_task(simple_task, task_id='medium', priority=2.0)
        
        # Retrieve in priority order
        task1 = await queue.get_task()
        task2 = await queue.get_task()
        task3 = await queue.get_task()
        
        assert task1.task_id == 'high'
        assert task2.task_id == 'medium'
        assert task3.task_id == 'low'
    
    async def test_fifo_algorithm(self):
        """Test FIFO scheduling algorithm."""
        queue = PriorityTaskQueue(algorithm=SchedulingAlgorithm.FIFO)
        
        # Add tasks (priority should be ignored)
        await queue.put_task(simple_task, task_id='first', priority=3.0)
        await asyncio.sleep(0.01)
        await queue.put_task(simple_task, task_id='second', priority=1.0)
        await asyncio.sleep(0.01)
        await queue.put_task(simple_task, task_id='third', priority=2.0)
        
        # Should retrieve in FIFO order
        task1 = await queue.get_task()
        task2 = await queue.get_task()
        task3 = await queue.get_task()
        
        assert task1.task_id == 'first'
        assert task2.task_id == 'second'
        assert task3.task_id == 'third'
    
    async def test_deadline_algorithm(self):
        """Test deadline-based scheduling."""
        queue = PriorityTaskQueue(algorithm=SchedulingAlgorithm.DEADLINE)
        
        now = datetime.now()
        
        # Add tasks with different deadlines
        await queue.put_task(
            simple_task,
            task_id='late',
            priority=1.0,
            deadline=now + timedelta(hours=2)
        )
        await queue.put_task(
            simple_task,
            task_id='urgent',
            priority=3.0,  # Lower priority but earlier deadline
            deadline=now + timedelta(minutes=5)
        )
        await queue.put_task(
            simple_task,
            task_id='soon',
            priority=2.0,
            deadline=now + timedelta(hours=1)
        )
        
        # Should retrieve by deadline, not priority
        task1 = await queue.get_task()
        task2 = await queue.get_task()
        task3 = await queue.get_task()
        
        assert task1.task_id == 'urgent'
        assert task2.task_id == 'soon'
        assert task3.task_id == 'late'
    
    async def test_max_size_limit(self):
        """Test queue size limit."""
        queue = PriorityTaskQueue(max_size=2)
        
        await queue.put_task(simple_task, priority=1.0)
        await queue.put_task(simple_task, priority=2.0)
        
        # Third task should fail
        with pytest.raises(RuntimeError, match="Queue is full"):
            await queue.put_task(simple_task, priority=3.0)
    
    async def test_peek_task(self):
        """Test peeking at tasks without removing them."""
        queue = PriorityTaskQueue()
        
        await queue.put_task(simple_task, task_id='test', priority=1.0)
        
        # Peek should not remove task
        task = await queue.peek_task()
        assert task.task_id == 'test'
        assert queue.size == 1
        
        # Get should remove task
        task = await queue.get_task()
        assert task.task_id == 'test'
        assert queue.size == 0
    
    async def test_get_task_by_id(self):
        """Test retrieving task by ID."""
        queue = PriorityTaskQueue()
        
        task_id = await queue.put_task(simple_task, task_id='test', priority=1.0)
        
        task = queue.get_task_by_id('test')
        assert task is not None
        assert task.task_id == 'test'
        
        # Task should still be in queue
        assert queue.size == 1
    
    async def test_adjust_priority(self):
        """Test dynamic priority adjustment."""
        queue = PriorityTaskQueue()
        
        await queue.put_task(simple_task, task_id='task1', priority=5.0)
        await queue.put_task(simple_task, task_id='task2', priority=3.0)
        
        # Adjust task1 to have higher priority
        success = queue.adjust_priority('task1', -3.0)
        assert success is True
        
        # task1 should now come first
        task = await queue.get_task()
        assert task.task_id == 'task1'
    
    async def test_priority_inheritance(self):
        """Test priority inheritance."""
        queue = PriorityTaskQueue(enable_priority_inheritance=True)
        
        # Add parent with high priority
        await queue.put_task(simple_task, task_id='parent', priority=1.0)
        # Add child with low priority
        await queue.put_task(simple_task, task_id='child', priority=5.0)
        
        # Apply inheritance
        success = queue.inherit_priority('parent', 'child')
        assert success is True
        
        # Child should now have parent's priority
        child = queue.get_task_by_id('child')
        assert child.priority == 1.0
    
    async def test_mark_completed(self):
        """Test marking tasks as completed."""
        queue = PriorityTaskQueue()
        
        await queue.put_task(simple_task, task_id='test', priority=1.0)
        task = await queue.get_task()
        
        result = {'value': 42}
        queue.mark_completed(task, result)
        
        assert task.execution_end is not None
        assert task.result == result
        assert queue.total_completed == 1
    
    async def test_mark_failed(self):
        """Test marking tasks as failed."""
        queue = PriorityTaskQueue()
        
        await queue.put_task(simple_task, task_id='test', priority=1.0)
        task = await queue.get_task()
        
        queue.mark_failed(task, "Test error")
        
        assert task.execution_end is not None
        assert task.error == "Test error"
        assert queue.total_failed == 1
    
    async def test_get_stats(self):
        """Test queue statistics."""
        queue = PriorityTaskQueue()
        
        await queue.put_task(simple_task, priority=1.0)
        await queue.put_task(simple_task, priority=2.0)
        
        stats = queue.get_stats()
        
        assert stats['size'] == 2
        assert stats['total_submitted'] == 2
        assert stats['total_completed'] == 0
        assert stats['algorithm'] == 'priority'
    
    async def test_get_tasks_by_priority(self):
        """Test retrieving tasks in priority order."""
        queue = PriorityTaskQueue()
        
        await queue.put_task(simple_task, task_id='low', priority=3.0)
        await queue.put_task(simple_task, task_id='high', priority=1.0)
        await queue.put_task(simple_task, task_id='medium', priority=2.0)
        
        tasks = queue.get_tasks_by_priority(limit=2)
        
        assert len(tasks) == 2
        assert tasks[0].task_id == 'high'
        assert tasks[1].task_id == 'medium'
    
    async def test_clear_queue(self):
        """Test clearing the queue."""
        queue = PriorityTaskQueue()
        
        await queue.put_task(simple_task, priority=1.0)
        await queue.put_task(simple_task, priority=2.0)
        
        count = queue.clear()
        
        assert count == 2
        assert queue.size == 0
        assert queue.is_empty is True


@pytest.mark.asyncio
class TestPriorityScheduler:
    """Test PriorityScheduler class."""
    
    async def test_scheduler_initialization(self):
        """Test scheduler initialization."""
        queue = PriorityTaskQueue()
        scheduler = PriorityScheduler(queue, max_concurrent=5)
        
        assert scheduler.queue == queue
        assert scheduler.max_concurrent == 5
        assert scheduler._running is False
    
    async def test_start_and_stop(self):
        """Test starting and stopping the scheduler."""
        queue = PriorityTaskQueue()
        scheduler = PriorityScheduler(queue, max_concurrent=2)
        
        await scheduler.start()
        assert scheduler._running is True
        assert len(scheduler._worker_tasks) == 2
        
        await scheduler.stop()
        assert scheduler._running is False
        assert len(scheduler._worker_tasks) == 0
    
    async def test_task_execution(self):
        """Test scheduler executes tasks."""
        queue = PriorityTaskQueue()
        scheduler = PriorityScheduler(queue, max_concurrent=2)
        
        await scheduler.start()
        
        # Add tasks
        completed_values = []
        
        async def collect_task(value: int):
            await asyncio.sleep(0.05)
            completed_values.append(value)
            return value
        
        for i in range(5):
            await queue.put_task(
                collect_task,
                task_id=f'task_{i}',
                priority=i,
                kwargs={'value': i}
            )
        
        # Wait for all tasks to complete
        while not queue.is_empty or queue.total_completed < 5:
            await asyncio.sleep(0.1)
        
        await scheduler.stop()
        
        # All tasks should be completed
        assert len(completed_values) == 5
        assert queue.total_completed == 5
    
    async def test_priority_execution_order(self):
        """Test scheduler respects priority order."""
        queue = PriorityTaskQueue()
        scheduler = PriorityScheduler(queue, max_concurrent=1)  # Sequential
        
        execution_order = []
        
        async def track_task(task_id: str):
            execution_order.append(task_id)
            await asyncio.sleep(0.05)
        
        await scheduler.start()
        
        # Add tasks with different priorities
        await queue.put_task(track_task, task_id='low', priority=3.0, kwargs={'task_id': 'low'})
        await queue.put_task(track_task, task_id='high', priority=1.0, kwargs={'task_id': 'high'})
        await queue.put_task(track_task, task_id='medium', priority=2.0, kwargs={'task_id': 'medium'})
        
        # Wait for completion
        while not queue.is_empty or queue.total_completed < 3:
            await asyncio.sleep(0.1)
        
        await scheduler.stop()
        
        # Should execute in priority order
        assert execution_order == ['high', 'medium', 'low']
    
    async def test_error_handling(self):
        """Test scheduler handles task failures."""
        queue = PriorityTaskQueue()
        scheduler = PriorityScheduler(queue, max_concurrent=2)
        
        await scheduler.start()
        
        # Add failing task
        await queue.put_task(failing_task, task_id='fail', priority=1.0)
        
        # Wait for task to be processed
        while not queue.is_empty or queue.total_failed < 1:
            await asyncio.sleep(0.1)
        
        await scheduler.stop()
        
        assert queue.total_failed == 1


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
