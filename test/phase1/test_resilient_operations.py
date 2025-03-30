"""
Test suite for resilient operations functionality in IPFS Datasets.

Tests the resilience mechanisms for distributed operations including:
- Circuit breaker pattern
- Automatic retries with exponential backoff
- Node health monitoring
- Fault-tolerant distributed operations
"""

import os
import time
import unittest
import asyncio
import random
import tempfile
from unittest.mock import patch, MagicMock, AsyncMock

# Import components to test
from ipfs_datasets_py.resilient_operations import (
    ResilienceManager,
    NodeHealth,
    HealthStatus,
    OperationStatus,
    CircuitBreaker,
    RetryConfig,
    Checkpoint,
    OperationResult,
    CircuitBreakerOpenError,
    resilient
)


class TestCircuitBreaker(unittest.TestCase):
    """Test the circuit breaker pattern implementation."""
    
    def setUp(self):
        """Set up the test environment."""
        self.circuit_breaker = CircuitBreaker(
            name="test_circuit",
            failure_threshold=3,
            reset_timeout_sec=1
        )
    
    def test_initial_state(self):
        """Test the initial state of the circuit breaker."""
        self.assertEqual(self.circuit_breaker.state, "CLOSED")
        self.assertEqual(self.circuit_breaker.failures, 0)
        self.assertIsNone(self.circuit_breaker.trip_time)
    
    def test_successful_execution(self):
        """Test successful execution with the circuit breaker."""
        result = self.circuit_breaker.execute(lambda: "success")
        self.assertEqual(result, "success")
        self.assertEqual(self.circuit_breaker.state, "CLOSED")
    
    def test_circuit_trips_after_failures(self):
        """Test that the circuit breaker trips after reaching the failure threshold."""
        # Cause failures up to threshold
        for i in range(self.circuit_breaker.failure_threshold):
            with self.assertRaises(ValueError):
                self.circuit_breaker.execute(lambda: (_ for _ in ()).throw(ValueError("Test error")))
        
        # Check that the circuit is now open
        self.assertEqual(self.circuit_breaker.state, "OPEN")
        
        # Verify that further calls fail immediately
        with self.assertRaises(CircuitBreakerOpenError):
            self.circuit_breaker.execute(lambda: "This shouldn't execute")
    
    def test_circuit_half_open_after_timeout(self):
        """Test that the circuit transitions to half-open after the reset timeout."""
        # Trip the circuit
        for i in range(self.circuit_breaker.failure_threshold):
            with self.assertRaises(ValueError):
                self.circuit_breaker.execute(lambda: (_ for _ in ()).throw(ValueError("Test error")))
        
        # Check that the circuit is open
        self.assertEqual(self.circuit_breaker.state, "OPEN")
        
        # Wait for the reset timeout
        time.sleep(self.circuit_breaker.reset_timeout_sec + 0.1)
        
        # Trigger state check
        self.circuit_breaker._check_state()
        
        # Check that the circuit is now half-open
        self.assertEqual(self.circuit_breaker.state, "HALF_OPEN")
    
    def test_circuit_closes_after_success_in_half_open(self):
        """Test that the circuit closes after a successful execution in half-open state."""
        # Trip the circuit
        for i in range(self.circuit_breaker.failure_threshold):
            with self.assertRaises(ValueError):
                self.circuit_breaker.execute(lambda: (_ for _ in ()).throw(ValueError("Test error")))
        
        # Manually set to half-open
        self.circuit_breaker.state = "HALF_OPEN"
        
        # Execute successfully
        result = self.circuit_breaker.execute(lambda: "success")
        
        # Check that the circuit is closed
        self.assertEqual(result, "success")
        self.assertEqual(self.circuit_breaker.state, "CLOSED")
        self.assertEqual(self.circuit_breaker.failures, 0)
    
    def test_reset(self):
        """Test manually resetting the circuit breaker."""
        # Trip the circuit
        for i in range(self.circuit_breaker.failure_threshold):
            with self.assertRaises(ValueError):
                self.circuit_breaker.execute(lambda: (_ for _ in ()).throw(ValueError("Test error")))
        
        # Check that the circuit is open
        self.assertEqual(self.circuit_breaker.state, "OPEN")
        
        # Reset the circuit
        self.circuit_breaker.reset()
        
        # Check that the circuit is closed
        self.assertEqual(self.circuit_breaker.state, "CLOSED")
        self.assertEqual(self.circuit_breaker.failures, 0)
        self.assertIsNone(self.circuit_breaker.trip_time)


class TestRetryDecorator(unittest.TestCase):
    """Test the retry decorator implementation."""
    
    def test_sync_retry_success_after_failures(self):
        """Test that a sync function retries and eventually succeeds."""
        attempt_count = 0
        
        @resilient(max_retries=3, initial_backoff_ms=10)
        def test_function():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ConnectionError("Test error")
            return "success"
        
        # Should succeed on the third attempt
        result = test_function()
        self.assertEqual(result, "success")
        self.assertEqual(attempt_count, 3)
    
    def test_sync_retry_exhaust_retries(self):
        """Test that a sync function gives up after max retries."""
        attempt_count = 0
        
        @resilient(max_retries=2, initial_backoff_ms=10)
        def test_function():
            nonlocal attempt_count
            attempt_count += 1
            raise ConnectionError("Test error")
        
        # Should fail after 3 attempts (initial + 2 retries)
        with self.assertRaises(ConnectionError):
            test_function()
        
        self.assertEqual(attempt_count, 3)
    
    def test_sync_retry_non_retryable_exception(self):
        """Test that non-retryable exceptions are not retried."""
        attempt_count = 0
        
        @resilient(max_retries=3, initial_backoff_ms=10, retry_on_exceptions=[ConnectionError])
        def test_function():
            nonlocal attempt_count
            attempt_count += 1
            raise ValueError("Test error")
        
        # Should not retry for ValueError
        with self.assertRaises(ValueError):
            test_function()
        
        self.assertEqual(attempt_count, 1)
    
    async def test_async_retry_success_after_failures(self):
        """Test that an async function retries and eventually succeeds."""
        attempt_count = 0
        
        @resilient(max_retries=3, initial_backoff_ms=10)
        async def test_function():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ConnectionError("Test error")
            return "success"
        
        # Should succeed on the third attempt
        result = await test_function()
        self.assertEqual(result, "success")
        self.assertEqual(attempt_count, 3)
    
    async def test_async_retry_exhaust_retries(self):
        """Test that an async function gives up after max retries."""
        attempt_count = 0
        
        @resilient(max_retries=2, initial_backoff_ms=10)
        async def test_function():
            nonlocal attempt_count
            attempt_count += 1
            raise ConnectionError("Test error")
        
        # Should fail after 3 attempts (initial + 2 retries)
        with self.assertRaises(ConnectionError):
            await test_function()
        
        self.assertEqual(attempt_count, 3)


class TestNodeHealth(unittest.TestCase):
    """Test the node health monitoring functionality."""
    
    def setUp(self):
        """Set up the test environment."""
        self.node_health = NodeHealth(node_id="test_node")
    
    def test_initial_state(self):
        """Test the initial state of the node health."""
        self.assertEqual(self.node_health.node_id, "test_node")
        self.assertEqual(self.node_health.status, HealthStatus.UNKNOWN)
        self.assertEqual(self.node_health.failure_count, 0)
        self.assertEqual(self.node_health.availability_score, 0.0)
    
    def test_update_response_time(self):
        """Test updating response time metrics."""
        self.node_health.update_response_time(100)
        self.assertEqual(self.node_health.response_times_ms, [100])
        self.assertEqual(self.node_health.avg_response_time_ms, 100)
        
        self.node_health.update_response_time(200)
        self.assertEqual(self.node_health.response_times_ms, [100, 200])
        self.assertEqual(self.node_health.avg_response_time_ms, 150)
    
    def test_record_success(self):
        """Test recording a successful operation."""
        self.node_health.record_success()
        self.assertEqual(self.node_health.status, HealthStatus.HEALTHY)
        self.assertIsNotNone(self.node_health.last_check_time)
        self.assertGreater(self.node_health.availability_score, 0.0)
    
    def test_record_failure(self):
        """Test recording a failed operation."""
        # Initially healthy
        self.node_health.record_success()
        self.assertEqual(self.node_health.status, HealthStatus.HEALTHY)
        
        # Record failure
        self.node_health.record_failure()
        self.assertEqual(self.node_health.failure_count, 1)
        self.assertEqual(self.node_health.status, HealthStatus.DEGRADED)
        self.assertIsNotNone(self.node_health.last_failure_time)
        
        # Multiple failures should mark as unhealthy
        for i in range(DEFAULT_NODE_FAILURE_THRESHOLD - 1):
            self.node_health.record_failure()
        
        self.assertEqual(self.node_health.status, HealthStatus.UNHEALTHY)
    
    def test_availability_score(self):
        """Test that availability score changes with successes and failures."""
        initial_score = self.node_health.availability_score
        
        # Success increases score
        self.node_health.record_success()
        self.assertGreater(self.node_health.availability_score, initial_score)
        
        current_score = self.node_health.availability_score
        
        # Failure decreases score
        self.node_health.record_failure()
        self.assertLess(self.node_health.availability_score, current_score)


class TestOperationResult(unittest.TestCase):
    """Test the operation result tracking functionality."""
    
    def setUp(self):
        """Set up the test environment."""
        self.operation = OperationResult(
            operation_id="test_op",
            status=OperationStatus.PENDING,
            start_time=time.time()
        )
    
    def test_initial_state(self):
        """Test the initial state of the operation result."""
        self.assertEqual(self.operation.operation_id, "test_op")
        self.assertEqual(self.operation.status, OperationStatus.PENDING)
        self.assertEqual(self.operation.success_count, 0)
        self.assertEqual(self.operation.failure_count, 0)
    
    def test_add_success(self):
        """Test adding a successful node operation."""
        self.operation.add_success("node1", "result1")
        self.assertEqual(self.operation.success_count, 1)
        self.assertEqual(self.operation.successful_nodes, ["node1"])
        self.assertEqual(self.operation.affected_nodes, ["node1"])
        self.assertEqual(self.operation.results["node1"], "result1")
    
    def test_add_failure(self):
        """Test adding a failed node operation."""
        self.operation.add_failure("node1", "error1")
        self.assertEqual(self.operation.failure_count, 1)
        self.assertEqual(self.operation.failed_nodes, {"node1": "error1"})
        self.assertEqual(self.operation.affected_nodes, ["node1"])
    
    def test_complete_success(self):
        """Test completing an operation with success."""
        self.operation.add_success("node1")
        self.operation.add_success("node2")
        
        self.operation.complete()
        
        self.assertEqual(self.operation.status, OperationStatus.COMPLETED)
        self.assertIsNotNone(self.operation.end_time)
        self.assertGreater(self.operation.execution_time_ms, 0)
        self.assertTrue(self.operation.is_successful())
    
    def test_complete_partial(self):
        """Test completing an operation with partial success."""
        self.operation.add_success("node1")
        self.operation.add_failure("node2", "error2")
        
        self.operation.complete()
        
        self.assertEqual(self.operation.status, OperationStatus.PARTIALLY_COMPLETED)
        self.assertTrue(self.operation.is_partially_successful())
    
    def test_complete_failure(self):
        """Test completing an operation with failure."""
        self.operation.add_failure("node1", "error1")
        self.operation.add_failure("node2", "error2")
        
        self.operation.complete()
        
        self.assertEqual(self.operation.status, OperationStatus.FAILED)
        self.assertFalse(self.operation.is_successful())
        self.assertFalse(self.operation.is_partially_successful())
    
    def test_complete_with_status(self):
        """Test completing an operation with a specified status."""
        self.operation.complete(OperationStatus.INTERRUPTED)
        self.assertEqual(self.operation.status, OperationStatus.INTERRUPTED)


class TestCheckpoint(unittest.TestCase):
    """Test the checkpoint functionality for resumable operations."""
    
    def setUp(self):
        """Set up the test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.checkpoint = Checkpoint(
            operation_id="test_op",
            completed_items=["item1", "item2"],
            pending_items=["item3", "item4", "item5"],
            metadata={"progress": 40}
        )
    
    def tearDown(self):
        """Clean up the test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_save_and_load(self):
        """Test saving and loading a checkpoint."""
        # Save the checkpoint
        filename = self.checkpoint.save(self.temp_dir)
        
        # Load the checkpoint
        loaded = Checkpoint.load(filename)
        
        # Verify the loaded checkpoint
        self.assertEqual(loaded.operation_id, self.checkpoint.operation_id)
        self.assertEqual(loaded.checkpoint_id, self.checkpoint.checkpoint_id)
        self.assertEqual(loaded.completed_items, self.checkpoint.completed_items)
        self.assertEqual(loaded.pending_items, self.checkpoint.pending_items)
        self.assertEqual(loaded.metadata, self.checkpoint.metadata)
    
    def test_find_latest(self):
        """Test finding the latest checkpoint for an operation."""
        # Create multiple checkpoints
        checkpoint1 = Checkpoint(
            operation_id="multi_op",
            checkpoint_id="cp_1000",
            completed_items=["item1"]
        )
        
        time.sleep(0.1)
        
        checkpoint2 = Checkpoint(
            operation_id="multi_op",
            checkpoint_id="cp_2000",
            completed_items=["item1", "item2"]
        )
        
        # Save both checkpoints
        checkpoint1.save(self.temp_dir)
        filename2 = checkpoint2.save(self.temp_dir)
        
        # Find the latest checkpoint
        latest = Checkpoint.find_latest(self.temp_dir, "multi_op")
        
        # Verify it's the second checkpoint
        self.assertIsNotNone(latest)
        self.assertEqual(latest.checkpoint_id, checkpoint2.checkpoint_id)
        self.assertEqual(latest.completed_items, checkpoint2.completed_items)


class TestResilienceManager(unittest.IsolatedAsyncioTestCase):
    """Test the resilience manager functionality."""
    
    async def asyncSetUp(self):
        """Set up the test environment."""
        # Create mock node
        self.node = MagicMock()
        self.node.node_id = "test_node"
        self.node.get_connected_peers = MagicMock(return_value=["peer1", "peer2", "peer3"])
        self.node.send_message = AsyncMock()
        self.node.shard_manager = MagicMock()
        
        # Create temporary directory
        self.temp_dir = tempfile.mkdtemp()
        
        # Create resilience manager
        self.manager = ResilienceManager(
            node=self.node,
            storage_dir=self.temp_dir,
            health_check_interval_sec=100  # Long interval to avoid automatic checks
        )
    
    async def asyncTearDown(self):
        """Clean up the test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)
        self.manager.shutdown()
    
    async def test_node_health_management(self):
        """Test node health management functionality."""
        # Add some node health records
        self.manager.node_health["peer1"] = NodeHealth(node_id="peer1")
        self.manager.node_health["peer2"] = NodeHealth(node_id="peer2")
        
        # Update health records
        self.manager.node_health["peer1"].record_success()
        self.manager.node_health["peer2"].record_failure()
        
        # Test health retrieval
        self.assertEqual(self.manager.get_node_health("peer1").status, HealthStatus.HEALTHY)
        self.assertEqual(self.manager.get_node_health("peer2").status, HealthStatus.DEGRADED)
        
        # Test getting healthy nodes
        healthy_nodes = self.manager.get_healthy_nodes()
        self.assertEqual(len(healthy_nodes), 1)
        self.assertEqual(healthy_nodes[0], "peer1")
        
        # Test selecting best nodes
        best_nodes = self.manager.select_best_nodes(count=1)
        self.assertEqual(len(best_nodes), 1)
        self.assertEqual(best_nodes[0], "peer1")
    
    async def test_circuit_breaker_management(self):
        """Test circuit breaker management functionality."""
        # Test getting a circuit breaker
        circuit = self.manager.get_circuit_breaker("node_connection")
        self.assertIsNotNone(circuit)
        self.assertEqual(circuit.name, "node_connection")
        
        # Test creating a new circuit breaker
        new_circuit = self.manager.create_circuit_breaker(
            name="custom_circuit",
            failure_threshold=5
        )
        self.assertEqual(new_circuit.name, "custom_circuit")
        self.assertEqual(new_circuit.failure_threshold, 5)
        
        # Test getting the new circuit breaker
        retrieved_circuit = self.manager.get_circuit_breaker("custom_circuit")
        self.assertEqual(retrieved_circuit.name, "custom_circuit")
    
    async def test_retry_async(self):
        """Test the retry_async functionality."""
        attempt_count = 0
        
        async def test_func():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ConnectionError("Test error")
            return "success"
        
        # Should succeed on the third attempt
        result = await self.manager.retry_async(test_func)
        self.assertEqual(result, "success")
        self.assertEqual(attempt_count, 3)
    
    async def test_operation_management(self):
        """Test operation tracking functionality."""
        # Create an operation
        operation = self.manager.create_operation("test_operation")
        self.assertEqual(operation.status, OperationStatus.PENDING)
        
        # Add successes and failures
        operation.add_success("peer1", "result1")
        operation.add_failure("peer2", "error2")
        
        # Complete the operation
        operation.complete()
        
        # Test retrieving the operation
        retrieved_op = self.manager.get_operation(operation.operation_id)
        self.assertEqual(retrieved_op.status, OperationStatus.PARTIALLY_COMPLETED)
        self.assertEqual(retrieved_op.success_count, 1)
        self.assertEqual(retrieved_op.failure_count, 1)
    
    async def test_checkpoint_management(self):
        """Test checkpoint management functionality."""
        # Create a checkpoint
        checkpoint = self.manager.create_checkpoint(
            operation_id="test_operation",
            completed_items=["item1", "item2"],
            pending_items=["item3", "item4"],
            metadata={"progress": 50}
        )
        
        # Retrieve the checkpoint
        retrieved_cp = self.manager.get_latest_checkpoint("test_operation")
        
        # Verify the checkpoint
        self.assertIsNotNone(retrieved_cp)
        self.assertEqual(retrieved_cp.operation_id, "test_operation")
        self.assertEqual(retrieved_cp.completed_items, ["item1", "item2"])
        self.assertEqual(retrieved_cp.pending_items, ["item3", "item4"])
        self.assertEqual(retrieved_cp.metadata["progress"], 50)


# Run the tests
if __name__ == "__main__":
    # Run synchronous tests
    unittest.main()