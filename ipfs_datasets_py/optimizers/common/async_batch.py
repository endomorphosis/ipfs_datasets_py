"""Async batch processing support for optimizers.

Provides async/await versions of batch operations for concurrent processing
of multiple items using asyncio instead of ThreadPoolExecutor.
"""

import asyncio
import logging
from typing import List, Any, Optional, Callable, TypeVar, Awaitable, Union
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import time

logger = logging.getLogger(__name__)

T = TypeVar('T')
R = TypeVar('R')


@dataclass
class BatchResult:
    """Result from async batch processing.
    
    Attributes:
        results: List of successful results (may contain None for failures)
        errors: List of error messages (indexed by result position)
        total_time_ms: Total batch processing time in milliseconds
        successful_count: Number of successful operations
        failed_count: Number of failed operations
    """
    results: List[Any]
    errors: List[Optional[str]]
    total_time_ms: float
    successful_count: int
    failed_count: int
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        total = self.successful_count + self.failed_count
        return (self.successful_count / total * 100) if total > 0 else 0.0


class AsyncBatchProcessor:
    """Async batch processor for concurrent operations.
    
    Processes multiple items concurrently using asyncio, with configurable
    concurrency limits, error handling, and progress tracking.
    
    Example:
        >>> processor = AsyncBatchProcessor(max_concurrent=10)
        >>> async def process_item(item):
        ...     # Process item asynchronously
        ...     return result
        >>> result = await processor.process_batch(items, process_item)
    """
    
    def __init__(
        self,
        max_concurrent: int = 10,
        timeout_per_item: Optional[float] = None,
        fail_fast: bool = False,
    ):
        """Initialize async batch processor.
        
        Args:
            max_concurrent: Maximum concurrent tasks (default: 10)
            timeout_per_item: Timeout in seconds per item (default: None)
            fail_fast: Stop processing on first error (default: False)
        """
        self.max_concurrent = max_concurrent
        self.timeout_per_item = timeout_per_item
        self.fail_fast = fail_fast
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_batch(
        self,
        items: List[T],
        process_fn: Union[Callable[[T], Awaitable[R]], Callable[[T], R]],
        fallback_value: Optional[R] = None,
    ) -> BatchResult:
        """Process a batch of items concurrently.
        
        Args:
            items: List of items to process
            process_fn: Async or sync function to process each item
            fallback_value: Value to use for failed items (default: None)
            
        Returns:
            BatchResult with all results and errors
            
        Example:
            >>> async def fetch_data(url):
            ...     # Fetch data from URL
            ...     return data
            >>> result = await processor.process_batch(urls, fetch_data)
        """
        start_time = time.time()
        results: List[Any] = [None] * len(items)
        errors: List[Optional[str]] = [None] * len(items)
        successful = 0
        failed = 0
        
        async def _process_with_semaphore(idx: int, item: T) -> None:
            """Process single item with semaphore."""
            nonlocal successful, failed
            
            async with self._semaphore:
                try:
                    # Check if process_fn is async or sync
                    if asyncio.iscoroutinefunction(process_fn):
                        if self.timeout_per_item:
                            result = await asyncio.wait_for(
                                process_fn(item),
                                timeout=self.timeout_per_item
                            )
                        else:
                            result = await process_fn(item)
                    else:
                        # Sync function - run in thread pool
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(None, process_fn, item)
                    
                    results[idx] = result
                    successful += 1
                    
                except asyncio.TimeoutError:
                    error_msg = f"Timeout after {self.timeout_per_item}s"
                    errors[idx] = error_msg
                    results[idx] = fallback_value
                    failed += 1
                    logger.warning(f"Item {idx} timed out")
                    
                    if self.fail_fast:
                        raise
                        
                except Exception as e:
                    error_msg = f"{type(e).__name__}: {str(e)}"
                    errors[idx] = error_msg
                    results[idx] = fallback_value
                    failed += 1
                    logger.error(f"Error processing item {idx}: {error_msg}")
                    
                    if self.fail_fast:
                        raise
        
        # Create tasks for all items
        tasks = [_process_with_semaphore(i, item) for i, item in enumerate(items)]
        
        # Wait for all tasks to complete
        if self.fail_fast:
            await asyncio.gather(*tasks)
        else:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        total_time_ms = (time.time() - start_time) * 1000
        
        return BatchResult(
            results=results,
            errors=errors,
            total_time_ms=total_time_ms,
            successful_count=successful,
            failed_count=failed,
        )
    
    async def process_batch_with_progress(
        self,
        items: List[T],
        process_fn: Union[Callable[[T], Awaitable[R]], Callable[[T], R]],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        fallback_value: Optional[R] = None,
    ) -> BatchResult:
        """Process batch with progress callback.
        
        Args:
            items: List of items to process
            process_fn: Async or sync function to process each item
            progress_callback: Callback function (completed, total)
            fallback_value: Value to use for failed items
            
        Returns:
            BatchResult with all results and errors
        """
        start_time = time.time()
        results: List[Any] = [None] * len(items)
        errors: List[Optional[str]] = [None] * len(items)
        successful = 0
        failed = 0
        completed = 0
        
        async def _process_with_progress(idx: int, item: T) -> None:
            """Process item and update progress."""
            nonlocal successful, failed, completed
            
            async with self._semaphore:
                try:
                    if asyncio.iscoroutinefunction(process_fn):
                        if self.timeout_per_item:
                            result = await asyncio.wait_for(
                                process_fn(item),
                                timeout=self.timeout_per_item
                            )
                        else:
                            result = await process_fn(item)
                    else:
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(None, process_fn, item)
                    
                    results[idx] = result
                    successful += 1
                    
                except Exception as e:
                    error_msg = f"{type(e).__name__}: {str(e)}"
                    errors[idx] = error_msg
                    results[idx] = fallback_value
                    failed += 1
                    
                finally:
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(items))
        
        tasks = [_process_with_progress(i, item) for i, item in enumerate(items)]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        total_time_ms = (time.time() - start_time) * 1000
        
        return BatchResult(
            results=results,
            errors=errors,
            total_time_ms=total_time_ms,
            successful_count=successful,
            failed_count=failed,
        )
    
    async def process_batch_chunked(
        self,
        items: List[T],
        process_fn: Union[Callable[[T], Awaitable[R]], Callable[[T], R]],
        chunk_size: int = 100,
        fallback_value: Optional[R] = None,
    ) -> BatchResult:
        """Process batch in chunks to manage memory.
        
        Processes items in smaller chunks to avoid overwhelming memory
        with too many concurrent operations.
        
        Args:
            items: List of items to process
            process_fn: Async or sync function to process each item
            chunk_size: Number of items per chunk (default: 100)
            fallback_value: Value to use for failed items
            
        Returns:
            BatchResult with all results and errors
        """
        start_time = time.time()
        all_results: List[Any] = []
        all_errors: List[Optional[str]] = []
        total_successful = 0
        total_failed = 0
        
        # Process in chunks
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            chunk_result = await self.process_batch(
                chunk,
                process_fn,
                fallback_value=fallback_value
            )
            
            all_results.extend(chunk_result.results)
            all_errors.extend(chunk_result.errors)
            total_successful += chunk_result.successful_count
            total_failed += chunk_result.failed_count
            
            logger.info(
                f"Processed chunk {i//chunk_size + 1}/{(len(items)-1)//chunk_size + 1}: "
                f"{chunk_result.successful_count}/{len(chunk)} successful"
            )
        
        total_time_ms = (time.time() - start_time) * 1000
        
        return BatchResult(
            results=all_results,
            errors=all_errors,
            total_time_ms=total_time_ms,
            successful_count=total_successful,
            failed_count=total_failed,
        )


class AsyncOntologyBatchProcessor(AsyncBatchProcessor):
    """Specialized async batch processor for ontology operations.
    
    Extends AsyncBatchProcessor with ontology-specific features like
    entity extraction batching and result merging.
    """
    
    def __init__(
        self,
        generator: Any,
        max_concurrent: int = 10,
        timeout_per_item: Optional[float] = 60.0,
    ):
        """Initialize ontology batch processor.
        
        Args:
            generator: OntologyGenerator instance
            max_concurrent: Maximum concurrent extractions
            timeout_per_item: Timeout per extraction in seconds
        """
        super().__init__(max_concurrent, timeout_per_item)
        self.generator = generator
    
    async def batch_extract_async(
        self,
        documents: List[str],
        context: Any,
    ) -> List[Any]:
        """Extract entities from documents asynchronously.
        
        Args:
            documents: List of document texts
            context: OntologyGenerationContext
            
        Returns:
            List of EntityExtractionResult
        """
        async def extract_one(doc: str) -> Any:
            """Extract from single document."""
            # Run in thread pool since extract_entities is sync
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                self.generator.extract_entities,
                doc,
                context
            )
        
        result = await self.process_batch(documents, extract_one)
        
        logger.info(
            f"Batch extraction: {result.successful_count}/{len(documents)} successful "
            f"({result.total_time_ms:.2f}ms, {result.success_rate:.1f}% success)"
        )
        
        return result.results
    
    async def batch_extract_with_spans_async(
        self,
        documents: List[str],
        context: Any,
    ) -> List[Any]:
        """Extract entities with spans asynchronously.
        
        Args:
            documents: List of document texts
            context: OntologyGenerationContext
            
        Returns:
            List of EntityExtractionResult with spans
        """
        async def extract_with_spans(doc: str) -> Any:
            """Extract with spans from single document."""
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                self.generator.extract_entities_with_spans,
                doc,
                context
            )
        
        result = await self.process_batch(documents, extract_with_spans)
        
        return result.results


# Convenience function for simple async batch processing
async def process_async_batch(
    items: List[T],
    process_fn: Union[Callable[[T], Awaitable[R]], Callable[[T], R]],
    max_concurrent: int = 10,
    timeout_per_item: Optional[float] = None,
) -> List[R]:
    """Process a batch of items asynchronously (convenience function).
    
    Args:
        items: List of items to process
        process_fn: Async or sync processing function
        max_concurrent: Maximum concurrent operations
        timeout_per_item: Timeout per operation in seconds
        
    Returns:
        List of results (may contain None for failures)
        
    Example:
        >>> results = await process_async_batch(
        ...     urls,
        ...     fetch_url,
        ...     max_concurrent=20
        ... )
    """
    processor = AsyncBatchProcessor(
        max_concurrent=max_concurrent,
        timeout_per_item=timeout_per_item,
    )
    batch_result = await processor.process_batch(items, process_fn)
    return batch_result.results
