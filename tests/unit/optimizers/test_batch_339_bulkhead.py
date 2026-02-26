"""
Batch 339: Bulkhead Pattern for Resource Isolation
===================================================

Implements the bulkhead pattern to isolate resources into
separate compartments, preventing cascading failures across
different service calls.

Goal: Provide:
- Thread pool isolation per service
- Queue management with boundaries
- Resource usage tracking
- Automatic scaling and load balancing
- Metrics and monitoring
"""

import pytest
import time
import threading
from typing import Callable, Dict, Optional, Any, List
from dataclasses import dataclass
from enum import Enum
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class BulkheadStatus(Enum):
    """Status of bulkhead."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OVERLOADED = "overloaded"


@dataclass
class BulkheadMetrics:
    """Metrics for bulkhead."""
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    rejected_tasks: int = 0
    queued_tasks: int = 0
    active_threads: int = 0
    
    def success_rate(self) -> float:
        """Get success rate."""
        if self.total_tasks == 0:
            return 0.0
        return self.completed_tasks / self.total_tasks
    
    def rejection_rate(self) -> float:
        """Get rejection rate."""
        if self.total_tasks == 0:
            return 0.0
        return self.rejected_tasks / self.total_tasks


# ============================================================================
# BULKHEAD IMPLEMENTATION
# ============================================================================

class Bulkhead:
    """Resource isolation bulkhead."""
    
    def __init__(self, name: str, thread_count: int = 5,
                 queue_size: int = 100,
                 timeout_seconds: float = 30.0):
        """Initialize bulkhead.
        
        Args:
            name: Bulkhead name
            thread_count: Number of worker threads
            queue_size: Max queued tasks
            timeout_seconds: Task timeout
        """
        self.name = name
        self.thread_count = thread_count
        self.queue_size = queue_size
        self.timeout_seconds = timeout_seconds
        
        self.executor = ThreadPoolExecutor(max_workers=thread_count)
        self.pending_tasks: Dict[str, object] = {}
        self.all_tasks: Dict[str, object] = {}  # All tasks, completed or pending
        self.metrics = BulkheadMetrics()
        
        self._lock = threading.Lock()
        self._task_counter = 0
    
    def execute(self, func: Callable, *args, **kwargs) -> str:
        """Execute task in bulkhead.
        
        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Task ID
            
        Raises:
            Exception: If bulkhead overloaded
        """
        with self._lock:
            self.metrics.total_tasks += 1
            
            # Check queue size
            if len(self.pending_tasks) >= self.queue_size:
                self.metrics.rejected_tasks += 1
                raise Exception(f"Bulkhead {self.name} is overloaded")
            
            self._task_counter += 1
            task_id = f"{self.name}_{self._task_counter}"
        
        def task_wrapper():
            try:
                result = func(*args, **kwargs)
                with self._lock:
                    self.metrics.completed_tasks += 1
                return result
            except Exception as e:
                with self._lock:
                    self.metrics.failed_tasks += 1
                raise
            finally:
                with self._lock:
                    if task_id in self.pending_tasks:
                        del self.pending_tasks[task_id]
                    self.metrics.queued_tasks = len(self.pending_tasks)
        
        future = self.executor.submit(task_wrapper)
        
        with self._lock:
            self.pending_tasks[task_id] = future
            self.all_tasks[task_id] = future
            self.metrics.queued_tasks = len(self.pending_tasks)
        
        return task_id
    
    def wait_for_task(self, task_id: str,
                      timeout: Optional[float] = None) -> Any:
        """Wait for task completion.
        
        Args:
            task_id: Task ID
            timeout: Wait timeout
            
        Returns:
            Task result
            
        Raises:
            Exception: If timeout or task failed
        """
        timeout = timeout or self.timeout_seconds
        
        future = self.all_tasks.get(task_id)
        if future is None:
            raise Exception(f"Task {task_id} not found")
        
        return future.result(timeout=timeout)
    
    def get_status(self) -> BulkheadStatus:
        """Get bulkhead status.
        
        Returns:
            Current status
        """
        with self._lock:
            utilization = len(self.pending_tasks) / self.queue_size
            
            if utilization > 0.9:
                return BulkheadStatus.OVERLOADED
            elif utilization > 0.6:
                return BulkheadStatus.DEGRADED
            else:
                return BulkheadStatus.HEALTHY
    
    def shutdown(self) -> None:
        """Shutdown bulkhead."""
        self.executor.shutdown(wait=True)


class BulkheadManager:
    """Manages multiple bulkheads."""
    
    def __init__(self):
        """Initialize manager."""
        self.bulkheads: Dict[str, Bulkhead] = {}
        self._lock = threading.Lock()
    
    def create_bulkhead(self, name: str, thread_count: int = 5,
                        queue_size: int = 100) -> Bulkhead:
        """Create new bulkhead.
        
        Args:
            name: Bulkhead name
            thread_count: Worker threads
            queue_size: Queue size
            
        Returns:
            Bulkhead
        """
        with self._lock:
            if name not in self.bulkheads:
                self.bulkheads[name] = Bulkhead(
                    name, thread_count, queue_size
                )
            
            return self.bulkheads[name]
    
    def get_bulkhead(self, name: str) -> Optional[Bulkhead]:
        """Get bulkhead by name.
        
        Args:
            name: Bulkhead name
            
        Returns:
            Bulkhead or None
        """
        with self._lock:
            return self.bulkheads.get(name)
    
    def get_all_metrics(self) -> Dict[str, Dict]:
        """Get metrics for all bulkheads.
        
        Returns:
            Dict of metrics by name
        """
        with self._lock:
            return {
                name: {
                    "status": bulkhead.get_status().value,
                    "total_tasks": bulkhead.metrics.total_tasks,
                    "completed": bulkhead.metrics.completed_tasks,
                    "failed": bulkhead.metrics.failed_tasks,
                    "rejected": bulkhead.metrics.rejected_tasks,
                    "queued": bulkhead.metrics.queued_tasks,
                    "success_rate": bulkhead.metrics.success_rate(),
                }
                for name, bulkhead in self.bulkheads.items()
            }


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestBulkhead:
    """Test bulkhead pattern."""
    
    def test_execute_task(self):
        """Test basic task execution."""
        bulkhead = Bulkhead("test", thread_count=2)
        
        task_id = bulkhead.execute(lambda: "result")
        result = bulkhead.wait_for_task(task_id, timeout=5.0)
        
        assert result == "result"
        assert bulkhead.metrics.completed_tasks == 1
        
        bulkhead.shutdown()
    
    def test_multiple_tasks(self):
        """Test multiple concurrent tasks."""
        bulkhead = Bulkhead("test", thread_count=3)
        
        task_ids = [
            bulkhead.execute(lambda i=i: i * 2)
            for i in range(5)
        ]
        
        results = [bulkhead.wait_for_task(task_id, timeout=5.0) 
                   for task_id in task_ids]
        
        assert len(results) == 5
        assert bulkhead.metrics.completed_tasks == 5
        
        bulkhead.shutdown()
    
    def test_task_failure(self):
        """Test handling task failure."""
        bulkhead = Bulkhead("test")
        
        task_id = bulkhead.execute(lambda: 1/0)
        
        with pytest.raises(Exception):
            bulkhead.wait_for_task(task_id, timeout=5.0)
        
        assert bulkhead.metrics.failed_tasks == 1
        
        bulkhead.shutdown()
    
    def test_queue_overflow(self):
        """Test queue overflow handling."""
        bulkhead = Bulkhead("test", thread_count=1, queue_size=2)
        
        # Submit first task that blocks
        task1 = bulkhead.execute(lambda: (time.sleep(0.5), "ok")[1])
        task2 = bulkhead.execute(lambda: "ok")
        
        # Should reject third
        with pytest.raises(Exception, match="overloaded"):
            bulkhead.execute(lambda: "ok")
        
        assert bulkhead.metrics.rejected_tasks > 0
        
        bulkhead.shutdown()
    
    def test_bulkhead_status(self):
        """Test status reporting."""
        bulkhead = Bulkhead("test", thread_count=2, queue_size=10)
        
        # Initially healthy
        assert bulkhead.get_status() == BulkheadStatus.HEALTHY
        
        # Submit blocking tasks
        for _ in range(7):
            bulkhead.execute(lambda: time.sleep(0.1))
        
        # Should be degraded
        status = bulkhead.get_status()
        assert status in [BulkheadStatus.DEGRADED, BulkheadStatus.OVERLOADED]
        
        bulkhead.shutdown()
    
    def test_metrics_tracking(self):
        """Test metrics collection."""
        bulkhead = Bulkhead("test")
        
        bulkhead.execute(lambda: "ok")
        bulkhead.execute(lambda: "ok")
        
        try:
            bulkhead.execute(lambda: 1/0)
        except:
            pass
        
        metrics = bulkhead.metrics
        assert metrics.total_tasks == 3
        assert metrics.completed_tasks == 2
        assert metrics.failed_tasks == 1
        
        bulkhead.shutdown()
    
    def test_success_rate(self):
        """Test success rate calculation."""
        bulkhead = Bulkhead("test")
        
        bulkhead.execute(lambda: "ok")
        bulkhead.execute(lambda: "ok")
        
        try:
            bulkhead.execute(lambda: 1/0)
        except:
            pass
        
        rate = bulkhead.metrics.success_rate()
        assert 0.5 < rate < 1.0


class TestBulkheadManager:
    """Test bulkhead manager."""
    
    def test_create_bulkhead(self):
        """Test creating bulkhead."""
        manager = BulkheadManager()
        
        bulkhead = manager.create_bulkhead("api")
        
        assert bulkhead is not None
        assert bulkhead.name == "api"
    
    def test_reuse_bulkhead(self):
        """Test reusing bulkhead by name."""
        manager = BulkheadManager()
        
        bulkhead1 = manager.create_bulkhead("api")
        bulkhead2 = manager.create_bulkhead("api")
        
        assert bulkhead1 is bulkhead2
    
    def test_multiple_bulkheads(self):
        """Test managing multiple bulkheads."""
        manager = BulkheadManager()
        
        api = manager.create_bulkhead("api", thread_count=2)
        db = manager.create_bulkhead("db", thread_count=3)
        
        assert api.thread_count == 2
        assert db.thread_count == 3
    
    def test_get_bulkhead(self):
        """Test retrieving bulkhead."""
        manager = BulkheadManager()
        
        created = manager.create_bulkhead("api")
        retrieved = manager.get_bulkhead("api")
        
        assert created is retrieved
    
    def test_get_all_metrics(self):
        """Test metrics aggregation."""
        manager = BulkheadManager()
        
        api = manager.create_bulkhead("api")
        db = manager.create_bulkhead("db")
        
        api.execute(lambda: "ok")
        db.execute(lambda: "ok")
        
        metrics = manager.get_all_metrics()
        
        assert "api" in metrics
        assert "db" in metrics
        assert metrics["api"]["total_tasks"] >= 1
        assert metrics["db"]["total_tasks"] >= 1
        
        api.shutdown()
        db.shutdown()
    
    def test_isolation(self):
        """Test that bulkheads are isolated."""
        manager = BulkheadManager()
        
        # Create bulkheads with small queues
        api = manager.create_bulkhead("api", thread_count=1, queue_size=2)
        db = manager.create_bulkhead("db", thread_count=2, queue_size=10)
        
        # Overfill API bulkhead with blocking tasks
        api.execute(lambda: time.sleep(0.2))
        api.execute(lambda: time.sleep(0.2))
        
        try:
            api.execute(lambda: "ok")
        except Exception as e:
            assert "overloaded" in str(e)
        
        # DB should still work
        task = db.execute(lambda: "db_ok")
        result = db.wait_for_task(task, timeout=5.0)
        assert result == "db_ok"
        
        api.shutdown()
        db.shutdown()
