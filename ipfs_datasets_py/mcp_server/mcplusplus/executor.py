"""
MCP++ Structured Concurrency Executor (Phase 4.1)

Provides Trio nursery-based parallel tool execution with:
- Timeout handling
- Cancellation support
- Resource limits
- Execution metrics

This enables efficient parallel execution of P2P tools without thread hops.
"""

import logging
import time
import inspect
import anyio
from ipfs_datasets_py.utils.anyio_compat import gather as _anyio_gather
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from threading import RLock

logger = logging.getLogger(__name__)

# Try to import Trio
try:
    import trio
    HAVE_TRIO = True
except ImportError:
    HAVE_TRIO = False
    logger.warning("Trio not available - executor will use anyio fallback")


@dataclass
class ExecutionResult:
    """Result of a tool execution."""
    
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    tool_name: str = ""
    cancelled: bool = False
    timed_out: bool = False


@dataclass
class ExecutorMetrics:
    """Metrics for the executor."""
    
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    cancelled_executions: int = 0
    timed_out_executions: int = 0
    total_execution_time_ms: float = 0.0
    
    def record_execution(self, result: ExecutionResult) -> None:
        """Record an execution result."""
        self.total_executions += 1
        self.total_execution_time_ms += result.execution_time_ms
        
        if result.success:
            self.successful_executions += 1
        else:
            self.failed_executions += 1
        
        if result.cancelled:
            self.cancelled_executions += 1
        
        if result.timed_out:
            self.timed_out_executions += 1
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_executions == 0:
            return 0.0
        return self.successful_executions / self.total_executions
    
    @property
    def avg_execution_time_ms(self) -> float:
        """Calculate average execution time."""
        if self.total_executions == 0:
            return 0.0
        return self.total_execution_time_ms / self.total_executions
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'total_executions': self.total_executions,
            'successful_executions': self.successful_executions,
            'failed_executions': self.failed_executions,
            'cancelled_executions': self.cancelled_executions,
            'timed_out_executions': self.timed_out_executions,
            'success_rate': self.success_rate,
            'avg_execution_time_ms': self.avg_execution_time_ms,
            'total_execution_time_ms': self.total_execution_time_ms
        }


class StructuredConcurrencyExecutor:
    """
    Structured concurrency executor for parallel tool execution.
    
    Uses Trio nurseries for structured concurrency, enabling:
    - Parallel execution with automatic cleanup
    - Timeout support
    - Cancellation support
    - Resource limits
    - Execution metrics
    
    Example:
        executor = StructuredConcurrencyExecutor(
            max_concurrent=10,
            default_timeout=30.0
        )
        
        async with executor.runtime_context():
            results = await executor.execute_parallel([
                (tool1, {'arg': 'value'}),
                (tool2, {'arg': 'value'})
            ])
    """
    
    def __init__(
        self,
        max_concurrent: int = 10,
        default_timeout: float = 30.0,
        enable_metrics: bool = True
    ):
        """
        Initialize the executor.
        
        Args:
            max_concurrent: Maximum number of concurrent executions
            default_timeout: Default timeout for tool execution (seconds)
            enable_metrics: Whether to collect execution metrics
        """
        self.max_concurrent = max_concurrent
        self.default_timeout = default_timeout
        self.enable_metrics = enable_metrics
        
        self.metrics = ExecutorMetrics()
        self.metrics_lock = RLock()
        
        self._nursery = None
        self._semaphore = None
        self._active = False
        
        logger.info(f"Initialized StructuredConcurrencyExecutor "
                   f"(max_concurrent={max_concurrent}, timeout={default_timeout}s)")
    
    @asynccontextmanager
    async def runtime_context(self):
        """
        Context manager for executor runtime.
        
        Usage:
            async with executor.runtime_context():
                results = await executor.execute_parallel([...])
        """
        if HAVE_TRIO:
            # Use Trio nursery
            async with trio.open_nursery() as nursery:
                self._nursery = nursery
                self._semaphore = trio.Semaphore(self.max_concurrent)
                self._active = True
                
                try:
                    yield self
                finally:
                    self._active = False
                    self._nursery = None
                    self._semaphore = None
        else:
            # Fallback to asyncio
            self._semaphore = anyio.Semaphore(self.max_concurrent)
            self._active = True
            
            try:
                yield self
            finally:
                self._active = False
                self._semaphore = None
    
    async def execute_single(
        self,
        tool_func: Callable,
        args: Optional[List] = None,
        kwargs: Optional[Dict] = None,
        timeout: Optional[float] = None,
        tool_name: Optional[str] = None
    ) -> ExecutionResult:
        """
        Execute a single tool.
        
        Args:
            tool_func: Tool function to execute
            args: Positional arguments
            kwargs: Keyword arguments
            timeout: Execution timeout (uses default if None)
            tool_name: Optional tool name for metrics
            
        Returns:
            ExecutionResult with execution details
        """
        args = args or []
        kwargs = kwargs or {}
        timeout = timeout or self.default_timeout
        tool_name = tool_name or getattr(tool_func, '__name__', 'unknown')
        
        start_time = time.perf_counter()
        result = ExecutionResult(success=False, tool_name=tool_name)
        
        try:
            if HAVE_TRIO:
                # Use Trio with timeout and cancellation
                with trio.move_on_after(timeout) as cancel_scope:
                    result.result = await tool_func(*args, **kwargs)
                
                if cancel_scope.cancelled_caught:
                    result.timed_out = True
                    result.error = f"Tool execution timed out after {timeout}s"
                else:
                    result.success = True
            else:
                # Use asyncio with timeout
                try:
                    with anyio.fail_after(timeout):
                        result.result = await tool_func(*args, **kwargs)
                    result.success = True
                except TimeoutError:
                    result.timed_out = True
                    result.error = f"Tool execution timed out after {timeout}s"
        
        except anyio.get_cancelled_exc_class():
            result.cancelled = True
            result.error = "Tool execution was cancelled"
            raise  # Re-raise to properly handle cancellation
        
        except Exception as e:
            result.error = str(e)
            logger.error(f"Error executing {tool_name}: {e}")
        
        finally:
            end_time = time.perf_counter()
            result.execution_time_ms = (end_time - start_time) * 1000
            
            # Record metrics
            if self.enable_metrics:
                with self.metrics_lock:
                    self.metrics.record_execution(result)
        
        return result
    
    async def execute_parallel(
        self,
        tasks: List[Tuple[Callable, Dict]],
        timeout: Optional[float] = None
    ) -> List[ExecutionResult]:
        """
        Execute multiple tools in parallel with structured concurrency.
        
        Args:
            tasks: List of (tool_func, kwargs) tuples
            timeout: Optional timeout for each task
            
        Returns:
            List of ExecutionResult objects
        """
        if not self._active:
            raise RuntimeError("Executor not active - use within runtime_context()")
        
        results = []
        
        if HAVE_TRIO:
            # Use Trio nursery for structured concurrency
            async def run_task(tool_func, kwargs, index):
                async with self._semaphore:
                    result = await self.execute_single(
                        tool_func,
                        kwargs=kwargs,
                        timeout=timeout
                    )
                    results.append((index, result))
            
            # Start all tasks in the nursery
            for i, (tool_func, kwargs) in enumerate(tasks):
                self._nursery.start_soon(run_task, tool_func, kwargs, i)
            
            # Wait for all tasks to complete (nursery context manager handles this)
            # Results are collected in the run_task function
            
            # Sort results by original index
            results.sort(key=lambda x: x[0])
            return [r[1] for r in results]
        
        else:
            # Fallback to asyncio with gather
            async def run_task(tool_func, kwargs):
                async with self._semaphore:
                    return await self.execute_single(
                        tool_func,
                        kwargs=kwargs,
                        timeout=timeout
                    )
            
            results = await _anyio_gather([
                run_task(tool_func, kwargs)
                for tool_func, kwargs in tasks
            ])
            
            # Convert exceptions to ExecutionResults
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    tool_func, _ = tasks[i]
                    tool_name = getattr(tool_func, '__name__', 'unknown')
                    processed_results.append(ExecutionResult(
                        success=False,
                        error=str(result),
                        tool_name=tool_name
                    ))
                else:
                    processed_results.append(result)
            
            return processed_results
    
    async def execute_batch(
        self,
        tool_func: Callable,
        batch_kwargs: List[Dict],
        timeout: Optional[float] = None
    ) -> List[ExecutionResult]:
        """
        Execute the same tool with different parameters in parallel.
        
        Args:
            tool_func: Tool function to execute
            batch_kwargs: List of keyword argument dicts
            timeout: Optional timeout for each execution
            
        Returns:
            List of ExecutionResult objects
        """
        tasks = [(tool_func, kwargs) for kwargs in batch_kwargs]
        return await self.execute_parallel(tasks, timeout)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get execution metrics."""
        with self.metrics_lock:
            return self.metrics.to_dict()
    
    def reset_metrics(self) -> None:
        """Reset execution metrics."""
        with self.metrics_lock:
            self.metrics = ExecutorMetrics()


# Convenience functions

async def execute_parallel_tools(
    tasks: List[Tuple[Callable, Dict]],
    max_concurrent: int = 10,
    timeout: float = 30.0
) -> List[ExecutionResult]:
    """
    Convenience function to execute tools in parallel.
    
    Args:
        tasks: List of (tool_func, kwargs) tuples
        max_concurrent: Maximum concurrent executions
        timeout: Timeout for each execution
        
    Returns:
        List of ExecutionResult objects
    """
    executor = StructuredConcurrencyExecutor(
        max_concurrent=max_concurrent,
        default_timeout=timeout
    )
    
    async with executor.runtime_context():
        return await executor.execute_parallel(tasks)


async def execute_batch_tool(
    tool_func: Callable,
    batch_kwargs: List[Dict],
    max_concurrent: int = 10,
    timeout: float = 30.0
) -> List[ExecutionResult]:
    """
    Convenience function to execute the same tool with different parameters.
    
    Args:
        tool_func: Tool function to execute
        batch_kwargs: List of keyword argument dicts
        max_concurrent: Maximum concurrent executions
        timeout: Timeout for each execution
        
    Returns:
        List of ExecutionResult objects
    """
    executor = StructuredConcurrencyExecutor(
        max_concurrent=max_concurrent,
        default_timeout=timeout
    )
    
    async with executor.runtime_context():
        return await executor.execute_batch(tool_func, batch_kwargs)


# Example usage
if __name__ == '__main__':
    async def example_tool(value: int, delay: float = 0.1) -> Dict[str, Any]:
        """Example tool for testing."""
        await anyio.sleep(delay)
        if value < 0:
            raise ValueError(f"Invalid value: {value}")
        return {'value': value, 'squared': value ** 2}
    
    async def main():
        # Example 1: Execute different tools
        print("Example 1: Parallel execution of different tools")
        executor = StructuredConcurrencyExecutor(max_concurrent=5)
        
        async with executor.runtime_context():
            results = await executor.execute_parallel([
                (example_tool, {'value': 1}),
                (example_tool, {'value': 2}),
                (example_tool, {'value': 3}),
                (example_tool, {'value': -1}),  # Will fail
                (example_tool, {'value': 5}),
            ])
        
        for i, result in enumerate(results):
            print(f"Task {i}: success={result.success}, "
                  f"result={result.result}, error={result.error}")
        
        print(f"\nMetrics: {executor.get_metrics()}")
        
        # Example 2: Batch execution
        print("\n\nExample 2: Batch execution")
        results = await execute_batch_tool(
            example_tool,
            [{'value': i} for i in range(10)],
            max_concurrent=3
        )
        
        print(f"Executed {len(results)} tasks")
        success_count = sum(1 for r in results if r.success)
        print(f"Success rate: {success_count}/{len(results)}")
    
    if HAVE_TRIO:
        trio.run(main)
    else:
        anyio.run(main)
