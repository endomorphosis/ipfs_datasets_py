"""
Async Integration Tests for Processor System
============================================

Tests the async capabilities of the processor system with anyio.
"""

import pytest
import anyio
from ipfs_datasets_py.processors.core import (
    UniversalProcessor,
    ProcessorRegistry,
    ProcessingContext,
    ProcessingResult,
    InputType,
)


class MockAsyncProcessor:
    """Mock async processor for testing."""
    
    def __init__(self, name="MockProcessor", can_handle_result=True, priority=10):
        self._name = name
        self._can_handle_result = can_handle_result
        self._priority = priority
        self.process_called = False
        self.can_handle_called = False
    
    async def can_handle(self, context: ProcessingContext) -> bool:
        """Async can_handle method."""
        self.can_handle_called = True
        await anyio.sleep(0.01)  # Simulate async I/O
        return self._can_handle_result
    
    async def process(self, context: ProcessingContext) -> ProcessingResult:
        """Async process method."""
        self.process_called = True
        await anyio.sleep(0.05)  # Simulate async processing
        return ProcessingResult(
            success=True,
            knowledge_graph={"entities": [{"id": "test", "type": "Test"}]},
            vectors=[],
            metadata={"processor": self._name}
        )
    
    def get_capabilities(self):
        """Get processor capabilities."""
        return {
            "name": self._name,
            "priority": self._priority,
            "formats": ["test"],
        }


@pytest.mark.asyncio
async def test_async_single_file_processing():
    """Test async processing of a single file."""
    # GIVEN: A processor with a mock adapter
    registry = ProcessorRegistry()
    processor_mock = MockAsyncProcessor(name="TestProcessor", priority=10)
    registry.register(processor_mock, priority=10, name="TestProcessor")
    
    processor = UniversalProcessor(registry=registry)
    
    # Create context
    context = ProcessingContext(
        input_type=InputType.FILE,
        source="test.txt",
        metadata={"format": "test"}
    )
    
    # WHEN: Processing asynchronously
    result = await processor.process("test.txt", context=context)
    
    # THEN: Processing succeeds and calls are made
    assert result.success
    assert processor_mock.can_handle_called
    assert processor_mock.process_called


@pytest.mark.asyncio
async def test_async_batch_processing_sequential():
    """Test async batch processing in sequential mode."""
    # GIVEN: A processor with mock adapter
    registry = ProcessorRegistry()
    processor_mock = MockAsyncProcessor(name="BatchTest", priority=10)
    registry.register(processor_mock, priority=10, name="BatchTest")
    
    processor = UniversalProcessor(registry=registry)
    
    # Create contexts
    contexts = [
        ProcessingContext(
            input_type=InputType.FILE,
            source=f"test{i}.txt",
            metadata={"format": "test"}
        )
        for i in range(3)
    ]
    
    # WHEN: Batch processing sequentially
    results = await processor.process_batch(
        [f"test{i}.txt" for i in range(3)],
        contexts=contexts,
        parallel=False
    )
    
    # THEN: All files processed
    assert len(results) == 3
    assert all(r.success for r in results)


@pytest.mark.asyncio
async def test_async_batch_processing_concurrent():
    """Test async batch processing in concurrent mode."""
    # GIVEN: A processor with mock adapter
    registry = ProcessorRegistry()
    processor_mock = MockAsyncProcessor(name="ConcurrentTest", priority=10)
    registry.register(processor_mock, priority=10, name="ConcurrentTest")
    
    processor = UniversalProcessor(registry=registry)
    
    # Create contexts
    contexts = [
        ProcessingContext(
            input_type=InputType.FILE,
            source=f"test{i}.txt",
            metadata={"format": "test"}
        )
        for i in range(5)
    ]
    
    # WHEN: Batch processing concurrently
    results = await processor.process_batch(
        [f"test{i}.txt" for i in range(5)],
        contexts=contexts,
        parallel=True
    )
    
    # THEN: All files processed concurrently
    assert len(results) == 5
    assert all(r.success for r in results)


@pytest.mark.asyncio
async def test_async_processor_registry_get_processors():
    """Test async get_processors with async can_handle checks."""
    # GIVEN: Multiple processors registered
    registry = ProcessorRegistry()
    
    # Register processors with different can_handle results
    proc1 = MockAsyncProcessor(name="Proc1", can_handle_result=True, priority=20)
    proc2 = MockAsyncProcessor(name="Proc2", can_handle_result=False, priority=15)
    proc3 = MockAsyncProcessor(name="Proc3", can_handle_result=True, priority=10)
    
    registry.register(proc1, priority=20, name="Proc1")
    registry.register(proc2, priority=15, name="Proc2")
    registry.register(proc3, priority=10, name="Proc3")
    
    # Create context
    context = ProcessingContext(
        input_type=InputType.FILE,
        source="test.txt",
        metadata={"format": "test"}
    )
    
    # WHEN: Getting processors asynchronously
    processors = await registry.get_processors(context)
    
    # THEN: Only processors that can handle are returned, in priority order
    assert len(processors) == 2  # proc1 and proc3
    assert processors[0] == proc1  # Higher priority first
    assert processors[1] == proc3
    
    # Verify all can_handle methods were called
    assert proc1.can_handle_called
    assert proc2.can_handle_called
    assert proc3.can_handle_called


@pytest.mark.asyncio
async def test_async_with_timeout():
    """Test async processing with timeout."""
    # GIVEN: A processor that takes time
    class SlowProcessor(MockAsyncProcessor):
        async def process(self, context: ProcessingContext) -> ProcessingResult:
            await anyio.sleep(2.0)  # Simulate slow processing
            return await super().process(context)
    
    registry = ProcessorRegistry()
    slow_proc = SlowProcessor(name="SlowProc", priority=10)
    registry.register(slow_proc, priority=10, name="SlowProc")
    
    processor = UniversalProcessor(registry=registry)
    
    context = ProcessingContext(
        input_type=InputType.FILE,
        source="test.txt",
        metadata={"format": "test"}
    )
    
    # WHEN: Processing with short timeout (should timeout)
    # Note: The timeout test is expected to raise TimeoutError
    try:
        with anyio.fail_after(0.5):  # 0.5 second timeout
            await processor.process("test.txt", context=context)
        # If we get here, timeout didn't work
        pytest.fail("Expected timeout but processing completed")
    except TimeoutError:
        # Expected - test passes
        pass


@pytest.mark.asyncio
async def test_async_retry_logic():
    """Test async retry logic on failure."""
    # GIVEN: A processor that fails initially
    class FailingProcessor(MockAsyncProcessor):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.attempts = 0
        
        async def process(self, context: ProcessingContext) -> ProcessingResult:
            self.attempts += 1
            await anyio.sleep(0.01)
            
            if self.attempts < 2:
                # Fail first attempt
                return ProcessingResult(
                    success=False,
                    knowledge_graph={},
                    vectors=[],
                    metadata={},
                    errors=["Simulated failure"]
                )
            else:
                # Succeed on retry
                return ProcessingResult(
                    success=True,
                    knowledge_graph={"entities": []},
                    vectors=[],
                    metadata={"processor": self._name}
                )
    
    registry = ProcessorRegistry()
    failing_proc = FailingProcessor(name="FailingProc", priority=10)
    registry.register(failing_proc, priority=10, name="FailingProc")
    
    processor = UniversalProcessor(registry=registry, max_retries=3)
    
    context = ProcessingContext(
        input_type=InputType.FILE,
        source="test.txt",
        metadata={"format": "test"}
    )
    
    # WHEN: Processing with retries
    result = await processor.process("test.txt", context=context)
    
    # THEN: Eventually succeeds after retry
    assert result.success
    assert failing_proc.attempts == 2  # First attempt + 1 retry


@pytest.mark.asyncio
async def test_anyio_backend_compatibility():
    """Test that the code works with anyio (backend-agnostic)."""
    # GIVEN: A simple processor
    registry = ProcessorRegistry()
    proc = MockAsyncProcessor(name="BackendTest", priority=10)
    registry.register(proc, priority=10, name="BackendTest")
    
    processor = UniversalProcessor(registry=registry)
    
    context = ProcessingContext(
        input_type=InputType.FILE,
        source="test.txt",
        metadata={"format": "test"}
    )
    
    # WHEN: Processing (anyio handles backend automatically)
    result = await processor.process("test.txt", context=context)
    
    # THEN: Works regardless of backend (asyncio/trio)
    assert result.success
    assert proc.process_called


if __name__ == "__main__":
    # Run tests with anyio
    pytest.main([__file__, "-v", "-s"])
