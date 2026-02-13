"""
Batch processing optimizations for logic modules.

Features:
- Async batch FOL conversion
- Parallel proof execution
- Memory-efficient processing
- Progress tracking
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import time

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """Result from batch processing."""
    total_items: int
    successful: int
    failed: int
    total_time: float
    items_per_second: float
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_items == 0:
            return 0.0
        return (self.successful / self.total_items) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_items": self.total_items,
            "successful": self.successful,
            "failed": self.failed,
            "total_time": self.total_time,
            "items_per_second": self.items_per_second,
            "success_rate": self.success_rate(),
            "results_count": len(self.results),
            "errors_count": len(self.errors),
        }


class BatchProcessor:
    """Batch processing with async and parallel execution."""
    
    def __init__(
        self,
        max_concurrency: int = 10,
        use_process_pool: bool = False,
        show_progress: bool = True,
    ):
        """
        Initialize batch processor.
        
        Args:
            max_concurrency: Maximum concurrent operations
            use_process_pool: Whether to use process pool (CPU-bound) vs thread pool
            show_progress: Whether to log progress
        """
        self.max_concurrency = max_concurrency
        self.use_process_pool = use_process_pool
        self.show_progress = show_progress
        self._semaphore = asyncio.Semaphore(max_concurrency)
    
    async def process_batch_async(
        self,
        items: List[Any],
        process_func: Callable,
        **kwargs
    ) -> BatchResult:
        """
        Process batch of items asynchronously.
        
        Args:
            items: List of items to process
            process_func: Async function to process each item
            **kwargs: Additional arguments for process_func
            
        Returns:
            BatchResult with statistics and results
        """
        start_time = time.time()
        results = []
        errors = []
        successful = 0
        failed = 0
        
        async def process_item(item, index):
            async with self._semaphore:
                try:
                    if self.show_progress and index % 10 == 0:
                        logger.info(f"Processing item {index}/{len(items)}")
                    
                    result = await process_func(item, **kwargs)
                    return {"success": True, "result": result, "index": index}
                except Exception as e:
                    logger.error(f"Error processing item {index}: {e}")
                    return {"success": False, "error": str(e), "index": index}
        
        # Process all items concurrently
        tasks = [process_item(item, i) for i, item in enumerate(items)]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect results
        for item_result in completed:
            if isinstance(item_result, Exception):
                failed += 1
                errors.append({"error": str(item_result)})
            elif item_result.get("success"):
                successful += 1
                results.append(item_result["result"])
            else:
                failed += 1
                errors.append(item_result)
        
        total_time = time.time() - start_time
        
        batch_result = BatchResult(
            total_items=len(items),
            successful=successful,
            failed=failed,
            total_time=total_time,
            items_per_second=len(items) / total_time if total_time > 0 else 0,
            results=results,
            errors=errors,
        )
        
        if self.show_progress:
            logger.info(
                f"Batch complete: {successful}/{len(items)} successful, "
                f"{total_time:.2f}s, {batch_result.items_per_second:.1f} items/sec"
            )
        
        return batch_result
    
    def process_batch_parallel(
        self,
        items: List[Any],
        process_func: Callable,
        **kwargs
    ) -> BatchResult:
        """
        Process batch using thread/process pool.
        
        Args:
            items: List of items to process
            process_func: Synchronous function to process each item
            **kwargs: Additional arguments for process_func
            
        Returns:
            BatchResult with statistics and results
        """
        start_time = time.time()
        results = []
        errors = []
        
        PoolExecutor = ProcessPoolExecutor if self.use_process_pool else ThreadPoolExecutor
        
        with PoolExecutor(max_workers=self.max_concurrency) as executor:
            futures = []
            for i, item in enumerate(items):
                future = executor.submit(process_func, item, **kwargs)
                futures.append((i, future))
            
            successful = 0
            failed = 0
            
            for i, future in futures:
                try:
                    if self.show_progress and i % 10 == 0:
                        logger.info(f"Processing item {i}/{len(items)}")
                    
                    result = future.result()
                    results.append(result)
                    successful += 1
                except Exception as e:
                    logger.error(f"Error processing item {i}: {e}")
                    errors.append({"index": i, "error": str(e)})
                    failed += 1
        
        total_time = time.time() - start_time
        
        batch_result = BatchResult(
            total_items=len(items),
            successful=successful,
            failed=failed,
            total_time=total_time,
            items_per_second=len(items) / total_time if total_time > 0 else 0,
            results=results,
            errors=errors,
        )
        
        if self.show_progress:
            logger.info(
                f"Batch complete: {successful}/{len(items)} successful, "
                f"{total_time:.2f}s, {batch_result.items_per_second:.1f} items/sec"
            )
        
        return batch_result


# Specialized batch processors

class FOLBatchProcessor:
    """Optimized batch processor for FOL conversion."""
    
    def __init__(self, max_concurrency: int = 10):
        """
        Initialize FOL batch processor.
        
        Args:
            max_concurrency: Maximum concurrent conversions
        """
        self.processor = BatchProcessor(max_concurrency=max_concurrency)
    
    async def convert_batch(
        self,
        texts: List[str],
        use_nlp: bool = True,
        confidence_threshold: float = 0.7,
    ) -> BatchResult:
        """
        Convert batch of texts to FOL.
        
        Args:
            texts: List of natural language texts
            use_nlp: Whether to use NLP extraction
            confidence_threshold: Minimum confidence threshold
            
        Returns:
            BatchResult with conversion results
        """
        from ipfs_datasets_py.logic.fol.text_to_fol import convert_text_to_fol
        
        async def convert_single(text):
            return await convert_text_to_fol(
                text,
                use_nlp=use_nlp,
                confidence_threshold=confidence_threshold,
            )
        
        return await self.processor.process_batch_async(
            items=texts,
            process_func=convert_single,
        )


class ProofBatchProcessor:
    """Optimized batch processor for proof execution."""
    
    def __init__(self, max_concurrency: int = 5):
        """
        Initialize proof batch processor.
        
        Args:
            max_concurrency: Maximum concurrent proofs
        """
        self.processor = BatchProcessor(max_concurrency=max_concurrency)
    
    async def prove_batch(
        self,
        formulas: List[Any],
        prover: str = "z3",
        use_cache: bool = True,
    ) -> BatchResult:
        """
        Execute batch of proofs.
        
        Args:
            formulas: List of formulas to prove
            prover: Prover to use
            use_cache: Whether to use proof caching
            
        Returns:
            BatchResult with proof results
        """
        from ipfs_datasets_py.logic.integration.proof_execution_engine import (
            ProofExecutionEngine
        )
        
        engine = ProofExecutionEngine(enable_caching=use_cache)
        
        async def prove_single(formula):
            # Wrap sync prove in async
            return await asyncio.to_thread(
                engine.prove_deontic_formula,
                formula,
                prover=prover,
                use_cache=use_cache,
            )
        
        return await self.processor.process_batch_async(
            items=formulas,
            process_func=prove_single,
        )


# Memory-efficient chunked processing

class ChunkedBatchProcessor:
    """Process large batches in memory-efficient chunks."""
    
    def __init__(
        self,
        chunk_size: int = 100,
        max_concurrency: int = 10,
    ):
        """
        Initialize chunked processor.
        
        Args:
            chunk_size: Size of each chunk
            max_concurrency: Max concurrent operations per chunk
        """
        self.chunk_size = chunk_size
        self.processor = BatchProcessor(max_concurrency=max_concurrency)
    
    async def process_large_batch(
        self,
        items: List[Any],
        process_func: Callable,
        **kwargs
    ) -> BatchResult:
        """
        Process large batch in chunks for memory efficiency.
        
        Args:
            items: Large list of items
            process_func: Async processing function
            **kwargs: Additional arguments
            
        Returns:
            Combined BatchResult from all chunks
        """
        total_results = []
        total_errors = []
        total_successful = 0
        total_failed = 0
        start_time = time.time()
        
        # Process in chunks
        for i in range(0, len(items), self.chunk_size):
            chunk = items[i:i+self.chunk_size]
            chunk_num = i // self.chunk_size + 1
            total_chunks = (len(items) + self.chunk_size - 1) // self.chunk_size
            
            logger.info(f"Processing chunk {chunk_num}/{total_chunks}")
            
            chunk_result = await self.processor.process_batch_async(
                items=chunk,
                process_func=process_func,
                **kwargs
            )
            
            total_results.extend(chunk_result.results)
            total_errors.extend(chunk_result.errors)
            total_successful += chunk_result.successful
            total_failed += chunk_result.failed
        
        total_time = time.time() - start_time
        
        return BatchResult(
            total_items=len(items),
            successful=total_successful,
            failed=total_failed,
            total_time=total_time,
            items_per_second=len(items) / total_time if total_time > 0 else 0,
            results=total_results,
            errors=total_errors,
        )


__all__ = [
    "BatchResult",
    "BatchProcessor",
    "FOLBatchProcessor",
    "ProofBatchProcessor",
    "ChunkedBatchProcessor",
]
