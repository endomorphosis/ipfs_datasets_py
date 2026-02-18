"""
Tests for MCP++ Structured Concurrency Executor (Phase 4.1)

Tests timeout handling, cancellation, resource limits, and execution metrics.
"""

import pytest
import asyncio
import time
from typing import Dict, Any

# Import executor
from ipfs_datasets_py.mcp_server.mcplusplus.executor import (
    StructuredConcurrencyExecutor,
    ExecutionResult,
    ExecutorMetrics,
    execute_parallel_tools,
    execute_batch_tool,
    HAVE_TRIO
)


# Test tools

async def simple_tool(value: int) -> Dict[str, Any]:
    """Simple test tool that returns a result."""
    await asyncio.sleep(0.01)
    return {'value': value, 'doubled': value * 2}


async def slow_tool(delay: float = 1.0) -> Dict[str, Any]:
    """Tool that takes time to execute."""
    await asyncio.sleep(delay)
    return {'completed': True}


async def failing_tool(error_message: str = "Test error") -> Dict[str, Any]:
    """Tool that always fails."""
    raise ValueError(error_message)


async def conditional_tool(should_fail: bool = False) -> Dict[str, Any]:
    """Tool that fails conditionally."""
    if should_fail:
        raise ValueError("Conditional failure")
    return {'success': True}


# Tests

class TestExecutionResult:
    """Test ExecutionResult dataclass."""
    
    def test_successful_result(self):
        """Test successful result creation."""
        result = ExecutionResult(
            success=True,
            result={'data': 'test'},
            execution_time_ms=50.0,
            tool_name='test_tool'
        )
        
        assert result.success is True
        assert result.result == {'data': 'test'}
        assert result.error is None
        assert result.execution_time_ms == 50.0
        assert result.tool_name == 'test_tool'
        assert result.cancelled is False
        assert result.timed_out is False
    
    def test_failed_result(self):
        """Test failed result creation."""
        result = ExecutionResult(
            success=False,
            error='Test error',
            execution_time_ms=25.0,
            tool_name='failing_tool'
        )
        
        assert result.success is False
        assert result.result is None
        assert result.error == 'Test error'
        assert result.execution_time_ms == 25.0


class TestExecutorMetrics:
    """Test ExecutorMetrics dataclass."""
    
    def test_record_successful_execution(self):
        """Test recording successful execution."""
        metrics = ExecutorMetrics()
        result = ExecutionResult(
            success=True,
            execution_time_ms=50.0,
            tool_name='test_tool'
        )
        
        metrics.record_execution(result)
        
        assert metrics.total_executions == 1
        assert metrics.successful_executions == 1
        assert metrics.failed_executions == 0
        assert metrics.total_execution_time_ms == 50.0
    
    def test_record_failed_execution(self):
        """Test recording failed execution."""
        metrics = ExecutorMetrics()
        result = ExecutionResult(
            success=False,
            error='Test error',
            execution_time_ms=25.0,
            tool_name='failing_tool'
        )
        
        metrics.record_execution(result)
        
        assert metrics.total_executions == 1
        assert metrics.successful_executions == 0
        assert metrics.failed_executions == 1
    
    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        metrics = ExecutorMetrics()
        
        # Add 3 successful, 1 failed
        for _ in range(3):
            metrics.record_execution(ExecutionResult(success=True, execution_time_ms=10.0))
        metrics.record_execution(ExecutionResult(success=False, execution_time_ms=10.0))
        
        assert metrics.success_rate == 0.75  # 3/4
    
    def test_avg_execution_time(self):
        """Test average execution time calculation."""
        metrics = ExecutorMetrics()
        
        metrics.record_execution(ExecutionResult(success=True, execution_time_ms=50.0))
        metrics.record_execution(ExecutionResult(success=True, execution_time_ms=100.0))
        
        assert metrics.avg_execution_time_ms == 75.0


@pytest.mark.asyncio
class TestStructuredConcurrencyExecutor:
    """Test StructuredConcurrencyExecutor."""
    
    async def test_executor_initialization(self):
        """Test executor initialization."""
        executor = StructuredConcurrencyExecutor(
            max_concurrent=5,
            default_timeout=10.0,
            enable_metrics=True
        )
        
        assert executor.max_concurrent == 5
        assert executor.default_timeout == 10.0
        assert executor.enable_metrics is True
        assert isinstance(executor.metrics, ExecutorMetrics)
    
    async def test_runtime_context(self):
        """Test runtime context manager."""
        executor = StructuredConcurrencyExecutor()
        
        assert executor._active is False
        
        async with executor.runtime_context():
            assert executor._active is True
            assert executor._semaphore is not None
        
        assert executor._active is False
    
    async def test_execute_single_success(self):
        """Test successful single execution."""
        executor = StructuredConcurrencyExecutor()
        
        async with executor.runtime_context():
            result = await executor.execute_single(
                simple_tool,
                kwargs={'value': 5}
            )
        
        assert result.success is True
        assert result.result == {'value': 5, 'doubled': 10}
        assert result.error is None
        assert result.execution_time_ms > 0
    
    async def test_execute_single_failure(self):
        """Test failed single execution."""
        executor = StructuredConcurrencyExecutor()
        
        async with executor.runtime_context():
            result = await executor.execute_single(
                failing_tool,
                kwargs={'error_message': 'Test failure'}
            )
        
        assert result.success is False
        assert result.error == 'Test failure'
        assert result.result is None
    
    async def test_execute_single_timeout(self):
        """Test execution timeout."""
        executor = StructuredConcurrencyExecutor(default_timeout=0.1)
        
        async with executor.runtime_context():
            result = await executor.execute_single(
                slow_tool,
                kwargs={'delay': 1.0}
            )
        
        assert result.success is False
        assert result.timed_out is True
        assert 'timed out' in result.error.lower()
    
    async def test_execute_parallel(self):
        """Test parallel execution of multiple tools."""
        executor = StructuredConcurrencyExecutor(max_concurrent=3)
        
        tasks = [
            (simple_tool, {'value': i})
            for i in range(5)
        ]
        
        start_time = time.perf_counter()
        
        async with executor.runtime_context():
            results = await executor.execute_parallel(tasks)
        
        end_time = time.perf_counter()
        
        # All tasks should succeed
        assert len(results) == 5
        assert all(r.success for r in results)
        
        # Verify results are correct
        for i, result in enumerate(results):
            assert result.result == {'value': i, 'doubled': i * 2}
        
        # Should be faster than sequential (rough check)
        # Sequential would be at least 5 * 0.01 = 0.05s
        # Parallel with concurrency=3 should be faster
        assert end_time - start_time < 0.04  # Allow some overhead
    
    async def test_execute_parallel_with_failures(self):
        """Test parallel execution with some failures."""
        executor = StructuredConcurrencyExecutor()
        
        tasks = [
            (simple_tool, {'value': 1}),
            (failing_tool, {'error_message': 'Fail 1'}),
            (simple_tool, {'value': 2}),
            (failing_tool, {'error_message': 'Fail 2'}),
            (simple_tool, {'value': 3}),
        ]
        
        async with executor.runtime_context():
            results = await executor.execute_parallel(tasks)
        
        assert len(results) == 5
        
        # Check successes
        assert results[0].success is True
        assert results[2].success is True
        assert results[4].success is True
        
        # Check failures
        assert results[1].success is False
        assert 'Fail 1' in results[1].error
        assert results[3].success is False
        assert 'Fail 2' in results[3].error
    
    async def test_execute_batch(self):
        """Test batch execution of same tool."""
        executor = StructuredConcurrencyExecutor()
        
        batch_kwargs = [
            {'value': i}
            for i in range(10)
        ]
        
        async with executor.runtime_context():
            results = await executor.execute_batch(
                simple_tool,
                batch_kwargs
            )
        
        assert len(results) == 10
        assert all(r.success for r in results)
        
        for i, result in enumerate(results):
            assert result.result == {'value': i, 'doubled': i * 2}
    
    async def test_max_concurrent_limit(self):
        """Test that max_concurrent limit is respected."""
        executor = StructuredConcurrencyExecutor(max_concurrent=2)
        
        # Track concurrent executions
        concurrent_count = 0
        max_concurrent_seen = 0
        lock = asyncio.Lock()
        
        async def tracked_tool(value: int):
            nonlocal concurrent_count, max_concurrent_seen
            
            async with lock:
                concurrent_count += 1
                max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
            
            await asyncio.sleep(0.05)
            
            async with lock:
                concurrent_count -= 1
            
            return {'value': value}
        
        tasks = [(tracked_tool, {'value': i}) for i in range(6)]
        
        async with executor.runtime_context():
            results = await executor.execute_parallel(tasks)
        
        assert len(results) == 6
        assert all(r.success for r in results)
        assert max_concurrent_seen <= 2
    
    async def test_metrics_collection(self):
        """Test that metrics are collected correctly."""
        executor = StructuredConcurrencyExecutor(enable_metrics=True)
        
        tasks = [
            (simple_tool, {'value': 1}),
            (failing_tool, {'error_message': 'Test'}),
            (simple_tool, {'value': 2}),
        ]
        
        async with executor.runtime_context():
            await executor.execute_parallel(tasks)
        
        metrics = executor.get_metrics()
        
        assert metrics['total_executions'] == 3
        assert metrics['successful_executions'] == 2
        assert metrics['failed_executions'] == 1
        assert metrics['success_rate'] == 2/3
        assert metrics['avg_execution_time_ms'] > 0
    
    async def test_reset_metrics(self):
        """Test metrics reset."""
        executor = StructuredConcurrencyExecutor()
        
        async with executor.runtime_context():
            await executor.execute_single(simple_tool, kwargs={'value': 1})
        
        # Verify metrics exist
        metrics = executor.get_metrics()
        assert metrics['total_executions'] == 1
        
        # Reset metrics
        executor.reset_metrics()
        
        metrics = executor.get_metrics()
        assert metrics['total_executions'] == 0


@pytest.mark.asyncio
class TestConvenienceFunctions:
    """Test convenience functions."""
    
    async def test_execute_parallel_tools(self):
        """Test execute_parallel_tools convenience function."""
        tasks = [
            (simple_tool, {'value': i})
            for i in range(3)
        ]
        
        results = await execute_parallel_tools(
            tasks,
            max_concurrent=2,
            timeout=5.0
        )
        
        assert len(results) == 3
        assert all(r.success for r in results)
    
    async def test_execute_batch_tool(self):
        """Test execute_batch_tool convenience function."""
        batch_kwargs = [
            {'value': i}
            for i in range(5)
        ]
        
        results = await execute_batch_tool(
            simple_tool,
            batch_kwargs,
            max_concurrent=3,
            timeout=5.0
        )
        
        assert len(results) == 5
        assert all(r.success for r in results)


@pytest.mark.skipif(not HAVE_TRIO, reason="Trio not available")
@pytest.mark.asyncio
class TestTrioIntegration:
    """Test Trio-specific integration."""
    
    async def test_trio_cancellation(self):
        """Test that Trio cancellation works correctly."""
        # This test requires Trio to be available
        import trio
        
        executor = StructuredConcurrencyExecutor()
        
        async def long_running_task():
            async with executor.runtime_context():
                return await executor.execute_single(
                    slow_tool,
                    kwargs={'delay': 10.0}
                )
        
        # Cancel after 0.1 seconds
        with pytest.raises(trio.Cancelled):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(long_running_task)
                await trio.sleep(0.1)
                nursery.cancel_scope.cancel()


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
