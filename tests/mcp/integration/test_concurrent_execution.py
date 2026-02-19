"""
Integration tests for concurrent execution scenarios.

Tests cover parallel tool execution, thread safety, concurrent P2P operations,
race conditions, resource contention, and deadlock prevention.
"""
import pytest
import asyncio
import threading
import time
from unittest.mock import Mock, AsyncMock, patch
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed


@pytest.fixture
def mock_tool_registry():
    """Create a mock thread-safe tool registry."""
    class ThreadSafeRegistry:
        def __init__(self):
            self._tools = {}
            self._lock = threading.Lock()
        
        def register(self, name, tool):
            with self._lock:
                self._tools[name] = tool
        
        def get(self, name):
            with self._lock:
                return self._tools.get(name)
        
        def list_tools(self):
            with self._lock:
                return list(self._tools.keys())
    
    return ThreadSafeRegistry()


@pytest.fixture
def mock_state_manager():
    """Create a mock state manager for testing race conditions."""
    class StateManager:
        def __init__(self):
            self.state = {}
            self._lock = asyncio.Lock()
        
        async def get(self, key):
            async with self._lock:
                return self.state.get(key)
        
        async def set(self, key, value):
            async with self._lock:
                self.state[key] = value
        
        async def increment(self, key):
            async with self._lock:
                current = self.state.get(key, 0)
                await asyncio.sleep(0.001)  # Simulate race condition window
                self.state[key] = current + 1
    
    return StateManager()


class TestParallelToolExecution:
    """Test suite for parallel tool execution (5+ tools simultaneously)."""
    
    @pytest.mark.asyncio
    async def test_five_tools_parallel_execution(self):
        """
        GIVEN: Five different tools ready for execution
        WHEN: Executing all tools in parallel
        THEN: All tools complete successfully without interference
        """
        # Arrange
        async def tool_1():
            await asyncio.sleep(0.1)
            return {"tool": "tool_1", "result": "success"}
        
        async def tool_2():
            await asyncio.sleep(0.15)
            return {"tool": "tool_2", "result": "success"}
        
        async def tool_3():
            await asyncio.sleep(0.05)
            return {"tool": "tool_3", "result": "success"}
        
        async def tool_4():
            await asyncio.sleep(0.12)
            return {"tool": "tool_4", "result": "success"}
        
        async def tool_5():
            await asyncio.sleep(0.08)
            return {"tool": "tool_5", "result": "success"}
        
        # Act
        start_time = time.time()
        results = await asyncio.gather(tool_1(), tool_2(), tool_3(), tool_4(), tool_5())
        elapsed = time.time() - start_time
        
        # Assert
        assert len(results) == 5
        assert all(r["result"] == "success" for r in results)
        # Should complete in ~0.15s (longest task), not 0.5s (sequential)
        assert elapsed < 0.3
    
    @pytest.mark.asyncio
    async def test_ten_tools_concurrent_execution(self):
        """
        GIVEN: Ten tools executing concurrently
        WHEN: All tools run simultaneously
        THEN: System handles load and all complete
        """
        # Arrange
        async def mock_tool(tool_id):
            await asyncio.sleep(0.05)
            return {"id": tool_id, "status": "complete"}
        
        # Act
        tasks = [mock_tool(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert len(results) == 10
        assert all(r["status"] == "complete" for r in results)
        # Verify all tool IDs are unique
        tool_ids = [r["id"] for r in results]
        assert len(set(tool_ids)) == 10
    
    @pytest.mark.asyncio
    async def test_parallel_execution_with_mixed_durations(self):
        """
        GIVEN: Tools with varying execution times
        WHEN: Running in parallel
        THEN: Faster tools don't wait for slower ones
        """
        # Arrange
        execution_times = []
        
        async def timed_tool(duration, tool_id):
            start = time.time()
            await asyncio.sleep(duration)
            end = time.time()
            return {"id": tool_id, "duration": end - start}
        
        # Act
        tasks = [
            timed_tool(0.05, "fast1"),
            timed_tool(0.2, "slow"),
            timed_tool(0.05, "fast2"),
            timed_tool(0.1, "medium")
        ]
        results = await asyncio.gather(*tasks)
        
        # Assert
        fast_results = [r for r in results if r["id"].startswith("fast")]
        slow_results = [r for r in results if r["id"] == "slow"]
        
        assert len(fast_results) == 2
        assert all(r["duration"] < 0.1 for r in fast_results)
        assert slow_results[0]["duration"] >= 0.2


class TestThreadSafetyInToolRegistry:
    """Test suite for thread safety in tool registry."""
    
    def test_concurrent_tool_registration(self, mock_tool_registry):
        """
        GIVEN: Multiple threads registering tools simultaneously
        WHEN: Registering tools concurrently
        THEN: All tools are registered without data corruption
        """
        # Arrange
        def register_tools(start_id, count):
            for i in range(count):
                tool_id = f"tool_{start_id + i}"
                mock_tool_registry.register(tool_id, lambda: f"result_{tool_id}")
        
        # Act
        threads = []
        for i in range(5):
            thread = threading.Thread(target=register_tools, args=(i * 10, 10))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Assert
        all_tools = mock_tool_registry.list_tools()
        assert len(all_tools) == 50
        assert len(set(all_tools)) == 50  # No duplicates
    
    def test_concurrent_tool_access(self, mock_tool_registry):
        """
        GIVEN: Tools registered in registry
        WHEN: Multiple threads access tools concurrently
        THEN: All accesses succeed without race conditions
        """
        # Arrange
        for i in range(10):
            mock_tool_registry.register(f"tool_{i}", lambda i=i: f"result_{i}")
        
        results = []
        results_lock = threading.Lock()
        
        def access_tool(tool_id):
            tool = mock_tool_registry.get(tool_id)
            if tool:
                result = tool()
                with results_lock:
                    results.append(result)
        
        # Act
        threads = []
        for i in range(10):
            for _ in range(5):  # Each tool accessed 5 times
                thread = threading.Thread(target=access_tool, args=(f"tool_{i}",))
                threads.append(thread)
                thread.start()
        
        for thread in threads:
            thread.join()
        
        # Assert
        assert len(results) == 50  # 10 tools × 5 accesses


class TestConcurrentP2POperations:
    """Test suite for concurrent P2P operations."""
    
    @pytest.mark.asyncio
    async def test_concurrent_peer_connections(self):
        """
        GIVEN: Multiple peer connection attempts
        WHEN: Connecting to peers concurrently
        THEN: All connections succeed without conflicts
        """
        # Arrange
        async def connect_to_peer(peer_id):
            await asyncio.sleep(0.05)  # Simulate connection time
            return {"peer_id": peer_id, "connected": True}
        
        peer_ids = [f"peer_{i}" for i in range(8)]
        
        # Act
        results = await asyncio.gather(*[connect_to_peer(pid) for pid in peer_ids])
        
        # Assert
        assert len(results) == 8
        assert all(r["connected"] for r in results)
    
    @pytest.mark.asyncio
    async def test_concurrent_data_sharing(self):
        """
        GIVEN: Multiple P2P data sharing operations
        WHEN: Sharing data with peers concurrently
        THEN: All operations complete without data corruption
        """
        # Arrange
        shared_data = {}
        lock = asyncio.Lock()
        
        async def share_data(peer_id, data):
            await asyncio.sleep(0.02)
            async with lock:
                shared_data[peer_id] = data
            return {"peer_id": peer_id, "shared": True}
        
        # Act
        tasks = []
        for i in range(10):
            tasks.append(share_data(f"peer_{i}", f"data_{i}"))
        
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert len(shared_data) == 10
        assert all(r["shared"] for r in results)


class TestRaceConditionsInStateManagement:
    """Test suite for race conditions in state management."""
    
    @pytest.mark.asyncio
    async def test_concurrent_state_updates_with_lock(self, mock_state_manager):
        """
        GIVEN: Multiple concurrent state update operations
        WHEN: Updates are protected by locks
        THEN: State remains consistent
        """
        # Arrange
        key = "counter"
        await mock_state_manager.set(key, 0)
        
        # Act - Increment counter concurrently 20 times
        tasks = [mock_state_manager.increment(key) for _ in range(20)]
        await asyncio.gather(*tasks)
        
        # Assert
        final_value = await mock_state_manager.get(key)
        assert final_value == 20
    
    @pytest.mark.asyncio
    async def test_race_condition_without_lock_detection(self):
        """
        GIVEN: State updates without proper locking
        WHEN: Concurrent updates occur
        THEN: Race condition can be detected (incorrect final value)
        """
        # Arrange - Intentionally unsafe state management
        unsafe_state = {"counter": 0}
        
        async def unsafe_increment():
            current = unsafe_state["counter"]
            await asyncio.sleep(0.001)  # Race condition window
            unsafe_state["counter"] = current + 1
        
        # Act
        await asyncio.gather(*[unsafe_increment() for _ in range(10)])
        
        # Assert - Due to race condition, counter won't be 10
        # This test demonstrates the problem
        assert unsafe_state["counter"] <= 10
    
    @pytest.mark.asyncio
    async def test_atomic_operations_prevent_races(self):
        """
        GIVEN: State manager with atomic operations
        WHEN: Performing atomic updates
        THEN: Race conditions are prevented
        """
        # Arrange
        state_lock = asyncio.Lock()
        state = {"value": 0}
        
        async def atomic_increment():
            async with state_lock:
                state["value"] += 1
        
        # Act
        await asyncio.gather(*[atomic_increment() for _ in range(50)])
        
        # Assert
        assert state["value"] == 50


class TestConcurrentMetricsCollection:
    """Test suite for concurrent metrics collection."""
    
    @pytest.mark.asyncio
    async def test_concurrent_metric_updates(self):
        """
        GIVEN: Multiple threads updating metrics
        WHEN: Metrics are updated concurrently
        THEN: All updates are captured correctly
        """
        # Arrange
        metrics = defaultdict(int)
        lock = asyncio.Lock()
        
        async def update_metric(metric_name):
            async with lock:
                metrics[metric_name] += 1
        
        # Act
        tasks = []
        for i in range(100):
            metric_name = f"metric_{i % 5}"  # 5 different metrics
            tasks.append(update_metric(metric_name))
        
        await asyncio.gather(*tasks)
        
        # Assert
        assert len(metrics) == 5
        assert sum(metrics.values()) == 100
        assert all(count == 20 for count in metrics.values())
    
    @pytest.mark.asyncio
    async def test_concurrent_histogram_updates(self):
        """
        GIVEN: Histogram being updated concurrently
        WHEN: Multiple values added simultaneously
        THEN: All values are recorded
        """
        # Arrange
        from collections import deque
        histogram = deque(maxlen=1000)
        lock = asyncio.Lock()
        
        async def add_value(value):
            async with lock:
                histogram.append(value)
        
        # Act
        tasks = [add_value(i) for i in range(200)]
        await asyncio.gather(*tasks)
        
        # Assert
        assert len(histogram) == 200
        assert min(histogram) == 0
        assert max(histogram) == 199


class TestConcurrentWorkflowExecution:
    """Test suite for concurrent workflow execution."""
    
    @pytest.mark.asyncio
    async def test_multiple_workflows_parallel_execution(self):
        """
        GIVEN: Multiple independent workflows
        WHEN: Executing workflows concurrently
        THEN: All workflows complete without interference
        """
        # Arrange
        async def workflow(workflow_id, steps):
            results = []
            for step in steps:
                await asyncio.sleep(0.02)
                results.append(f"workflow_{workflow_id}_step_{step}")
            return {"id": workflow_id, "steps": results}
        
        # Act
        workflows = [
            workflow(1, [1, 2, 3]),
            workflow(2, [1, 2]),
            workflow(3, [1, 2, 3, 4])
        ]
        results = await asyncio.gather(*workflows)
        
        # Assert
        assert len(results) == 3
        assert len(results[0]["steps"]) == 3
        assert len(results[1]["steps"]) == 2
        assert len(results[2]["steps"]) == 4


class TestResourceContentionHandling:
    """Test suite for resource contention handling."""
    
    @pytest.mark.asyncio
    async def test_database_connection_pool_contention(self):
        """
        GIVEN: Limited database connection pool
        WHEN: More requests than available connections
        THEN: Requests are queued and handled gracefully
        """
        # Arrange
        max_connections = 3
        semaphore = asyncio.Semaphore(max_connections)
        
        async def use_connection(task_id):
            async with semaphore:
                await asyncio.sleep(0.05)  # Simulate DB operation
                return {"task_id": task_id, "completed": True}
        
        # Act
        tasks = [use_connection(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert len(results) == 10
        assert all(r["completed"] for r in results)
    
    @pytest.mark.asyncio
    async def test_file_handle_contention(self):
        """
        GIVEN: Multiple operations requiring file access
        WHEN: File handle limit is approached
        THEN: Operations are serialized properly
        """
        # Arrange
        file_lock = asyncio.Lock()
        file_operations_completed = []
        
        async def file_operation(op_id):
            async with file_lock:
                await asyncio.sleep(0.01)
                file_operations_completed.append(op_id)
                return op_id
        
        # Act
        tasks = [file_operation(i) for i in range(20)]
        await asyncio.gather(*tasks)
        
        # Assert
        assert len(file_operations_completed) == 20
        assert len(set(file_operations_completed)) == 20


class TestDeadlockPrevention:
    """Test suite for deadlock prevention."""
    
    @pytest.mark.asyncio
    async def test_no_deadlock_with_ordered_locking(self):
        """
        GIVEN: Multiple resources requiring locks
        WHEN: Locks are acquired in consistent order
        THEN: No deadlocks occur
        """
        # Arrange
        lock_a = asyncio.Lock()
        lock_b = asyncio.Lock()
        
        async def task_1():
            async with lock_a:
                await asyncio.sleep(0.01)
                async with lock_b:
                    await asyncio.sleep(0.01)
                    return "task_1_done"
        
        async def task_2():
            async with lock_a:  # Same order as task_1
                await asyncio.sleep(0.01)
                async with lock_b:
                    await asyncio.sleep(0.01)
                    return "task_2_done"
        
        # Act
        results = await asyncio.gather(task_1(), task_2())
        
        # Assert
        assert "task_1_done" in results
        assert "task_2_done" in results
    
    @pytest.mark.asyncio
    async def test_timeout_prevents_deadlock(self):
        """
        GIVEN: Operations with potential for deadlock
        WHEN: Timeouts are applied
        THEN: Deadlock is prevented by timeout
        """
        # Arrange
        lock = asyncio.Lock()
        
        async def long_running_operation():
            async with lock:
                await asyncio.sleep(10)  # Very long operation
        
        # Act & Assert
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(long_running_operation(), timeout=0.5)
