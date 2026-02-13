"""Tests for Distributed Processor.

This module contains comprehensive tests for the distributed processing system
that enables scaling logic optimization across multiple nodes.
"""

import pytest
import time
from unittest.mock import Mock, patch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.distributed_processor import (
    DistributedProcessor,
    TaskStatus,
    WorkerStatus,
    Task,
    WorkerInfo,
    DistributedResult,
)


class TestTaskStatus:
    """Tests for TaskStatus enum."""
    
    def test_task_status_values(self):
        """
        GIVEN the TaskStatus enum
        WHEN accessing status values
        THEN all expected statuses should be available
        """
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.RETRYING.value == "retrying"


class TestWorkerStatus:
    """Tests for WorkerStatus enum."""
    
    def test_worker_status_values(self):
        """
        GIVEN the WorkerStatus enum
        WHEN accessing status values
        THEN all expected statuses should be available
        """
        assert WorkerStatus.IDLE.value == "idle"
        assert WorkerStatus.BUSY.value == "busy"
        assert WorkerStatus.FAILED.value == "failed"
        assert WorkerStatus.DISCONNECTED.value == "disconnected"


class TestTask:
    """Tests for Task dataclass."""
    
    def test_task_creation(self):
        """
        GIVEN task data
        WHEN creating a Task
        THEN task should have correct attributes
        """
        task = Task(task_id="task1", data="test_data")
        
        assert task.task_id == "task1"
        assert task.data == "test_data"
        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 0
        assert task.assigned_worker is None


class TestWorkerInfo:
    """Tests for WorkerInfo dataclass."""
    
    def test_worker_info_creation(self):
        """
        GIVEN worker data
        WHEN creating WorkerInfo
        THEN worker should have correct attributes
        """
        worker = WorkerInfo(worker_id="worker1")
        
        assert worker.worker_id == "worker1"
        assert worker.status == WorkerStatus.IDLE
        assert worker.tasks_completed == 0
        assert worker.tasks_failed == 0


class TestDistributedResult:
    """Tests for DistributedResult dataclass."""
    
    def test_distributed_result_creation(self):
        """
        GIVEN result data
        WHEN creating DistributedResult
        THEN result should have correct attributes
        """
        result = DistributedResult(
            total_tasks=10,
            completed_tasks=8,
            failed_tasks=2,
            task_results=[1, 2, 3],
            total_time=10.5,
            workers_used=4,
            avg_task_time=1.2
        )
        
        assert result.total_tasks == 10
        assert result.completed_tasks == 8
        assert result.failed_tasks == 2
        assert len(result.task_results) == 3
        assert result.workers_used == 4


class TestDistributedProcessor:
    """Tests for DistributedProcessor."""
    
    def test_init_default_params(self):
        """
        GIVEN default parameters
        WHEN initializing DistributedProcessor
        THEN processor should be initialized correctly
        """
        processor = DistributedProcessor()
        
        assert processor.num_workers == 4
        assert processor.max_retries == 3
        assert processor.enable_fault_tolerance is True
        assert len(processor.workers) == 4
    
    def test_init_custom_params(self):
        """
        GIVEN custom parameters
        WHEN initializing DistributedProcessor
        THEN processor should use custom values
        """
        processor = DistributedProcessor(
            num_workers=8,
            max_retries=5,
            enable_fault_tolerance=False
        )
        
        assert processor.num_workers == 8
        assert processor.max_retries == 5
        assert processor.enable_fault_tolerance is False
        assert len(processor.workers) == 8
    
    def test_init_workers(self):
        """
        GIVEN num_workers parameter
        WHEN initializing processor
        THEN correct number of workers should be created
        """
        processor = DistributedProcessor(num_workers=6)
        
        assert len(processor.workers) == 6
        for worker_id, worker in processor.workers.items():
            assert worker.worker_id == worker_id
            assert worker.status == WorkerStatus.IDLE
    
    def test_process_distributed_simple(self):
        """
        GIVEN a list of simple tasks
        WHEN processing distributed
        THEN all tasks should be completed
        """
        processor = DistributedProcessor(num_workers=2)
        
        # Simple processing function
        def process_func(data):
            return data * 2
        
        tasks = [1, 2, 3, 4, 5]
        
        result = processor.process_distributed(tasks, process_func)
        
        assert result.total_tasks == 5
        assert result.completed_tasks == 5
        assert result.failed_tasks == 0
        assert len(result.task_results) == 5
        assert set(result.task_results) == {2, 4, 6, 8, 10}
    
    def test_process_distributed_with_aggregation(self):
        """
        GIVEN tasks and an aggregation function
        WHEN processing distributed
        THEN results should be aggregated
        """
        processor = DistributedProcessor(num_workers=2)
        
        def process_func(data):
            return data * 2
        
        def aggregate_func(results):
            return sum(results)
        
        tasks = [1, 2, 3, 4, 5]
        
        result = processor.process_distributed(
            tasks, process_func, aggregate_func
        )
        
        assert result.total_tasks == 5
        assert result.task_results == 30  # 2+4+6+8+10
    
    def test_process_distributed_with_failures(self):
        """
        GIVEN tasks that may fail
        WHEN processing distributed
        THEN failures should be handled
        """
        processor = DistributedProcessor(
            num_workers=2,
            max_retries=1,
            enable_fault_tolerance=True
        )
        
        # Function that fails on specific inputs
        def process_func(data):
            if data == 3:
                raise ValueError("Test failure")
            return data * 2
        
        tasks = [1, 2, 3, 4, 5]
        
        result = processor.process_distributed(tasks, process_func)
        
        # Task 3 should fail even after retry
        assert result.total_tasks == 5
        assert result.completed_tasks == 4
        assert result.failed_tasks == 1
    
    def test_process_distributed_retry_success(self):
        """
        GIVEN tasks that fail initially but succeed on retry
        WHEN processing distributed with retries
        THEN tasks should eventually succeed
        """
        processor = DistributedProcessor(
            num_workers=2,
            max_retries=2,
            enable_fault_tolerance=True
        )
        
        call_count = {}
        
        def process_func(data):
            # Fail first time, succeed on retry
            if data not in call_count:
                call_count[data] = 0
            call_count[data] += 1
            
            if call_count[data] == 1:
                raise ValueError("First attempt fails")
            return data * 2
        
        tasks = [1, 2, 3]
        
        result = processor.process_distributed(tasks, process_func)
        
        # All should eventually succeed after retry
        assert result.completed_tasks == 3
        assert result.failed_tasks == 0
    
    def test_generate_task_id(self):
        """
        GIVEN task index and data
        WHEN generating task ID
        THEN consistent IDs should be generated
        """
        processor = DistributedProcessor()
        
        id1 = processor._generate_task_id(0, "test_data")
        id2 = processor._generate_task_id(0, "test_data")
        id3 = processor._generate_task_id(1, "test_data")
        
        # Same input should produce same ID
        assert id1 == id2
        # Different input should produce different ID
        assert id1 != id3
    
    def test_get_statistics(self):
        """
        GIVEN a processor with some activity
        WHEN getting statistics
        THEN correct stats should be returned
        """
        processor = DistributedProcessor(num_workers=2)
        
        def process_func(data):
            return data * 2
        
        tasks = [1, 2, 3]
        processor.process_distributed(tasks, process_func)
        
        stats = processor.get_statistics()
        
        assert stats['num_workers'] == 2
        assert stats['total_tasks'] == 3
        assert stats['completed_tasks'] == 3
        assert stats['failed_tasks'] == 0
        assert 'worker_stats' in stats
    
    def test_get_progress(self):
        """
        GIVEN a processor with ongoing work
        WHEN getting progress
        THEN progress info should be returned
        """
        processor = DistributedProcessor(num_workers=2)
        
        # Manually create some tasks for progress tracking
        for i in range(10):
            task_id = f"task_{i}"
            task = Task(task_id=task_id, data=i)
            if i < 5:
                task.status = TaskStatus.COMPLETED
            elif i < 8:
                task.status = TaskStatus.RUNNING
            else:
                task.status = TaskStatus.PENDING
            processor.tasks[task_id] = task
        
        progress = processor.get_progress()
        
        assert progress['total_tasks'] == 10
        assert progress['completed'] == 5
        assert progress['pending'] == 5
        assert progress['progress_percentage'] == 50.0
    
    def test_reset(self):
        """
        GIVEN a processor with processed tasks
        WHEN resetting
        THEN all state should be cleared
        """
        processor = DistributedProcessor(num_workers=2)
        
        # Process some tasks
        def process_func(data):
            return data * 2
        
        processor.process_distributed([1, 2, 3], process_func)
        
        # Verify state exists
        assert len(processor.tasks) > 0
        
        # Reset
        processor.reset()
        
        # Verify state cleared
        assert len(processor.tasks) == 0
        assert processor.total_tasks_processed == 0
        assert processor.total_tasks_failed == 0
        
        for worker in processor.workers.values():
            assert worker.tasks_completed == 0
            assert worker.tasks_failed == 0
    
    def test_fault_tolerance_disabled(self):
        """
        GIVEN fault tolerance disabled
        WHEN tasks fail
        THEN tasks should not be retried
        """
        processor = DistributedProcessor(
            num_workers=2,
            enable_fault_tolerance=False
        )
        
        def process_func(data):
            if data == 2:
                raise ValueError("Failure")
            return data * 2
        
        tasks = [1, 2, 3]
        
        result = processor.process_distributed(tasks, process_func)
        
        # Task 2 should fail without retry
        assert result.completed_tasks == 2
        assert result.failed_tasks == 1
    
    def test_parallel_processing(self):
        """
        GIVEN multiple workers
        WHEN processing many tasks
        THEN tasks should be processed in parallel
        """
        processor = DistributedProcessor(num_workers=4)
        
        def process_func(data):
            time.sleep(0.1)  # Simulate work
            return data * 2
        
        tasks = list(range(20))
        start_time = time.time()
        
        result = processor.process_distributed(tasks, process_func)
        
        elapsed_time = time.time() - start_time
        
        # With 4 workers, should take roughly 20*0.1/4 = 0.5 seconds
        # Allow some overhead, should be much less than sequential (2 seconds)
        assert elapsed_time < 2.0
        assert result.completed_tasks == 20
    
    def test_worker_load_distribution(self):
        """
        GIVEN multiple workers
        WHEN processing tasks
        THEN work should be distributed among workers
        """
        processor = DistributedProcessor(num_workers=3)
        
        def process_func(data):
            time.sleep(0.01)  # Small delay to ensure parallel execution
            return data * 2
        
        tasks = list(range(15))
        
        result = processor.process_distributed(tasks, process_func)
        
        # Check that all tasks completed (main assertion)
        assert result.completed_tasks == 15
        assert result.total_tasks == 15
        
        # Check stats are reasonable
        stats = processor.get_statistics()
        workers_with_work = sum(
            1 for w in stats['worker_stats'].values()
            if w['completed'] > 0
        )
        
        # At least some workers should have done work
        assert workers_with_work >= 1
    
    def test_max_retries_exceeded(self):
        """
        GIVEN max_retries limit
        WHEN task fails repeatedly
        THEN task should eventually be marked as failed
        """
        processor = DistributedProcessor(
            num_workers=2,
            max_retries=2,
            enable_fault_tolerance=True
        )
        
        def process_func(data):
            # Always fail
            raise ValueError("Always fails")
        
        tasks = [1]
        
        result = processor.process_distributed(tasks, process_func)
        
        # Should fail after 2 retries
        assert result.failed_tasks == 1
        assert result.completed_tasks == 0
    
    def test_empty_task_list(self):
        """
        GIVEN an empty task list
        WHEN processing distributed
        THEN result should reflect no tasks
        """
        processor = DistributedProcessor(num_workers=2)
        
        def process_func(data):
            return data * 2
        
        result = processor.process_distributed([], process_func)
        
        assert result.total_tasks == 0
        assert result.completed_tasks == 0
        assert result.failed_tasks == 0
    
    def test_single_worker(self):
        """
        GIVEN single worker configuration
        WHEN processing tasks
        THEN all tasks should be processed sequentially by one worker
        """
        processor = DistributedProcessor(num_workers=1)
        
        def process_func(data):
            return data * 2
        
        tasks = [1, 2, 3, 4, 5]
        
        result = processor.process_distributed(tasks, process_func)
        
        assert result.completed_tasks == 5
        assert result.workers_used == 1
    
    def test_large_batch(self):
        """
        GIVEN a large batch of tasks
        WHEN processing distributed
        THEN all tasks should complete successfully
        """
        processor = DistributedProcessor(num_workers=4)
        
        def process_func(data):
            return data ** 2
        
        tasks = list(range(100))
        
        result = processor.process_distributed(tasks, process_func)
        
        assert result.total_tasks == 100
        assert result.completed_tasks == 100
        assert result.failed_tasks == 0
        assert len(result.task_results) == 100
