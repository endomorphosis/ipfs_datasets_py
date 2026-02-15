"""UniversalProcessor - Async single entry point for all processing operations.

This module provides the UniversalProcessor class, which acts as a unified async interface
for processing any input type (URLs, files, folders, text, binary, IPFS content).

The UniversalProcessor automatically:
1. Detects the input type using InputDetector
2. Finds suitable processors using ProcessorRegistry (async)
3. Processes the input with retry logic and fallbacks (async)
4. Returns standardized ProcessingResult

Requires anyio for unified async support across asyncio/trio backends.

Example usage:
    >>> import anyio
    >>> from ipfs_datasets_py.processors.core import UniversalProcessor
    >>> 
    >>> async def main():
    ...     processor = UniversalProcessor()
    ...     result = await processor.process("https://example.com")
    ...     if result.success:
    ...         print(f"Found {result.get_entity_count()} entities")
    >>> 
    >>> anyio.run(main)

Or using the convenience function:
    >>> import anyio
    >>> from ipfs_datasets_py.processors.core import process
    >>> result = anyio.run(process, "document.pdf")
"""

import logging
import time
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field

# anyio for unified async support
try:
    import anyio
    ANYIO_AVAILABLE = True
except ImportError:
    ANYIO_AVAILABLE = False

from .protocol import ProcessingContext, ProcessingResult, ProcessorProtocol, InputType
from .input_detector import InputDetector
from .processor_registry import ProcessorRegistry, get_global_registry

logger = logging.getLogger(__name__)


class UniversalProcessor:
    """Universal processor that automatically handles any input type.
    
    This is the main entry point for the processor system. It integrates
    InputDetector and ProcessorRegistry to provide automatic input classification,
    processor selection, and processing with error handling and retries.
    
    All processing operations are async and use anyio for unified async support
    across asyncio and trio backends.
    
    Attributes:
        registry: ProcessorRegistry for finding suitable processors
        detector: InputDetector for classifying inputs
        max_retries: Default maximum number of retry attempts
        retry_delay: Default delay between retries in seconds
    
    Example:
        >>> import anyio
        >>> from ipfs_datasets_py.processors.core import UniversalProcessor
        >>> 
        >>> async def main():
        ...     processor = UniversalProcessor()
        ...     # Register your processors
        ...     processor.register_processor(pdf_processor, priority=10)
        ...     # Process any input
        ...     result = await processor.process("document.pdf")
        ...     if result.success:
        ...         print(f"Success! {result.get_entity_count()} entities")
        >>> 
        >>> anyio.run(main)
    """
    
    def __init__(
        self,
        registry: Optional[ProcessorRegistry] = None,
        detector: Optional[InputDetector] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        """Initialize the UniversalProcessor.
        
        Args:
            registry: ProcessorRegistry to use. If None, uses global registry.
            detector: InputDetector to use. If None, creates new instance.
            max_retries: Default maximum number of retry attempts per processor.
            retry_delay: Default delay between retries in seconds.
        """
        self.registry = registry if registry is not None else get_global_registry()
        self.detector = detector if detector is not None else InputDetector()
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        logger.info(
            f"UniversalProcessor initialized with {len(self.registry)} processors, "
            f"max_retries={max_retries}, retry_delay={retry_delay}"
        )
    
    async def process(
        self,
        input_data: Any,
        context: Optional[ProcessingContext] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
        use_multiple: bool = False,
        max_processors: Optional[int] = None,
        timeout: Optional[float] = None,
        **options
    ) -> ProcessingResult:
        """Process input data automatically (async).
        
        This is the main method for processing. It:
        1. Detects input type (if context not provided)
        2. Finds suitable processors
        3. Attempts processing with retry logic
        4. Falls back to next processor on failure
        5. Returns standardized result
        
        Args:
            input_data: The input to process (URL, file path, text, etc.)
            context: Optional pre-created ProcessingContext
            max_retries: Maximum retry attempts per processor (overrides default)
            retry_delay: Delay between retries in seconds (overrides default)
            use_multiple: If True, try multiple processors and aggregate results
            max_processors: Maximum number of processors to try
            timeout: Optional processing timeout in seconds (uses anyio.fail_after)
            **options: Additional options passed to processor
        
        Returns:
            ProcessingResult with success status, knowledge graph, vectors, etc.
        
        Example:
            >>> import anyio
            >>> 
            >>> async def main():
            ...     processor = UniversalProcessor()
            ...     result = await processor.process("https://example.com")
            ...     if result.success:
            ...         print(f"Success! {result.get_entity_count()} entities")
            ...     else:
            ...         print(f"Failed: {result.errors}")
            >>> 
            >>> anyio.run(main)
        """
        if not ANYIO_AVAILABLE:
            raise ImportError(
                "anyio is required for async processing. "
                "Install it with: pip install anyio"
            )
        # Use defaults if not specified
        max_retries = max_retries if max_retries is not None else self.max_retries
        retry_delay = retry_delay if retry_delay is not None else self.retry_delay
        
        # Store context at function level
        processing_context = context
        
        async def _process_impl():
            nonlocal processing_context
            # Step 1: Detect input type if context not provided
            if processing_context is None:
                try:
                    processing_context = self.detector.detect(input_data, **options)
                    logger.info(
                        f"Detected input type: {processing_context.input_type.value}, "
                        f"format: {processing_context.get_format()}"
                    )
                except Exception as e:
                    logger.error(f"Error detecting input: {e}", exc_info=True)
                    return ProcessingResult(
                        success=False,
                        errors=[f"Input detection failed: {str(e)}"]
                    )
            
            # Step 2: Find suitable processors
            try:
                processors = await self.registry.get_processors(
                    processing_context,
                    limit=max_processors
                )
                logger.info(f"Found {len(processors)} suitable processors")
                
                if not processors:
                    logger.warning("No suitable processors found for input")
                    return ProcessingResult(
                        success=False,
                        errors=["No suitable processors found for this input type"]
                    )
            except Exception as e:
                logger.error(f"Error finding processors: {e}", exc_info=True)
                return ProcessingResult(
                    success=False,
                    errors=[f"Processor selection failed: {str(e)}"]
                )
            
            # Step 3: Try processors in priority order
            results = []
            all_errors = []
            
            for processor in processors:
                processor_name = processor.__class__.__name__
                
                # Try this processor with retries
                for attempt in range(max_retries):
                    try:
                        logger.info(
                            f"Attempting processing with {processor_name} "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        
                        # Check if processor can handle the context
                        if hasattr(processor, 'can_handle'):
                            can_handle = processor.can_handle(processing_context)
                            if hasattr(can_handle, '__await__'):
                                can_handle = await can_handle
                            if not can_handle:
                                logger.info(f"{processor_name} cannot handle this context")
                                continue
                        
                        # Process with the processor
                        start_time = time.time()
                        result = processor.process(processing_context)
                        # Await if it's a coroutine
                        if hasattr(result, '__await__'):
                            result = await result
                        elapsed = time.time() - start_time
                        
                        if result.success:
                            logger.info(
                                f"{processor_name} succeeded in {elapsed:.2f}s"
                            )
                            results.append(result)
                            
                            # If not using multiple processors, return first success
                            if not use_multiple:
                                return result
                            
                            # Break retry loop on success
                            break
                        else:
                            # Log failure but continue to retry or next processor
                            error_msg = f"{processor_name} failed: {result.errors}"
                            logger.warning(error_msg)
                            all_errors.append(error_msg)
                            
                            # Retry with exponential backoff
                            if attempt < max_retries - 1:
                                delay = retry_delay * (2 ** attempt)
                                logger.info(f"Retrying in {delay:.1f}s...")
                                await anyio.sleep(delay)
                            
                    except Exception as e:
                        error_msg = (
                            f"{processor_name} raised exception (attempt "
                            f"{attempt + 1}/{max_retries}): {str(e)}"
                        )
                        logger.error(error_msg, exc_info=True)
                        all_errors.append(error_msg)
                        
                        # Retry with exponential backoff
                        if attempt < max_retries - 1:
                            delay = retry_delay * (2 ** attempt)
                            logger.info(f"Retrying in {delay:.1f}s...")
                            await anyio.sleep(delay)
                
                # If using multiple processors, continue to next processor
                # If not using multiple, we already returned on success above
                if not use_multiple and results:
                    break
            
            # Step 4: Return aggregated results or error
            if results:
                if len(results) == 1:
                    return results[0]
                else:
                    # Merge multiple results
                    logger.info(f"Aggregating {len(results)} successful results")
                    merged = results[0]
                    for result in results[1:]:
                        merged = merged.merge(result)
                    return merged
            else:
                # All processors failed
                logger.error("All processors failed")
                return ProcessingResult(
                    success=False,
                    errors=all_errors or ["All processors failed"],
                    metadata={'processors_tried': len(processors)}
                )
        
        try:
            # Apply timeout using anyio.fail_after if specified
            if timeout:
                with anyio.fail_after(timeout):
                    return await _process_impl()
            else:
                return await _process_impl()
                
        except Exception as e:
            # Handle both anyio timeout/cancellation and other exceptions
            # anyio uses different exception types depending on the backend
            if ANYIO_AVAILABLE:
                try:
                    cancelled_exc = anyio.get_cancelled_exc_class()
                    if isinstance(e, cancelled_exc):
                        logger.error(f"Processing timeout/cancelled after {timeout}s")
                        return ProcessingResult(
                            success=False,
                            errors=[f"Processing timeout after {timeout}s"]
                        )
                except Exception as exc_err:
                    # Failed to check cancellation exception class, log and continue
                    logger.debug(f"Could not check cancellation exception: {exc_err}")
            
            logger.error(f"Unexpected error in process(): {e}", exc_info=True)
            return ProcessingResult(
                success=False,
                errors=[f"Unexpected processing error: {str(e)}"]
            )
    
    async def process_batch(
        self,
        inputs: List[Any],
        parallel: bool = False,
        **options
    ) -> List[ProcessingResult]:
        """Process multiple inputs (async).
        
        Args:
            inputs: List of inputs to process
            parallel: If True, process in parallel using anyio task groups (default: False)
            **options: Options passed to process()
        
        Returns:
            List of ProcessingResult objects, one per input
        
        Example:
            >>> import anyio
            >>> 
            >>> async def main():
            ...     processor = UniversalProcessor()
            ...     results = await processor.process_batch(["file1.pdf", "file2.pdf"])
            ...     success_count = sum(1 for r in results if r.success)
            ...     print(f"{success_count}/{len(results)} succeeded")
            >>> 
            >>> anyio.run(main)
        """
        if not ANYIO_AVAILABLE:
            raise ImportError(
                "anyio is required for async batch processing. "
                "Install it with: pip install anyio"
            )
        
        logger.info(f"Processing batch of {len(inputs)} inputs (parallel={parallel})")
        
        if parallel:
            # Use anyio task groups for concurrent processing
            results = [None] * len(inputs)
            
            async def process_item(index: int, input_data: Any):
                try:
                    logger.info(f"Processing batch item {index + 1}/{len(inputs)}")
                    result = await self.process(input_data, **options)
                    results[index] = result
                except Exception as e:
                    logger.error(f"Error processing batch item {index + 1}: {e}", exc_info=True)
                    results[index] = ProcessingResult(
                        success=False,
                        errors=[f"Batch processing error: {str(e)}"]
                    )
            
            async with anyio.create_task_group() as tg:
                for i, input_data in enumerate(inputs):
                    tg.start_soon(process_item, i, input_data)
        else:
            # Sequential processing
            results = []
            for i, input_data in enumerate(inputs):
                logger.info(f"Processing batch item {i + 1}/{len(inputs)}")
                result = await self.process(input_data, **options)
                results.append(result)
        
        success_count = sum(1 for r in results if r.success)
        logger.info(
            f"Batch processing complete: {success_count}/{len(inputs)} succeeded"
        )
        
        return results
    
    def register_processor(
        self,
        processor: ProcessorProtocol,
        priority: int = 10,
        name: Optional[str] = None,
        **metadata
    ) -> None:
        """Register a processor with the registry.
        
        This is a convenience method that delegates to the registry.
        
        Args:
            processor: Processor instance to register
            priority: Priority for this processor (higher = checked first)
            name: Optional name for the processor
            **metadata: Additional metadata for the processor
        
        Example:
            >>> processor.register_processor(my_processor, priority=20, name="Custom")
        """
        self.registry.register(processor, priority=priority, name=name, **metadata)
        logger.info(
            f"Registered processor {name or processor.__class__.__name__} "
            f"with priority {priority}"
        )
    
    def unregister_processor(self, name: str) -> None:
        """Unregister a processor from the registry.
        
        Args:
            name: Name of the processor to unregister
        
        Example:
            >>> processor.unregister_processor("Custom")
        """
        self.registry.unregister(name)
        logger.info(f"Unregistered processor {name}")
    
    def get_registered_processors(self) -> List[tuple]:
        """Get all registered processors.
        
        Returns:
            List of (processor, priority) tuples
        
        Example:
            >>> processors = processor.get_registered_processors()
            >>> for proc, priority in processors:
            ...     print(f"{proc.__class__.__name__}: priority {priority}")
        """
        return self.registry.get_all_processors()
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get system capabilities from the registry.
        
        Returns:
            Dictionary with supported formats, input types, etc.
        
        Example:
            >>> caps = processor.get_capabilities()
            >>> print(f"Supports: {caps['supported_formats']}")
        """
        return self.registry.get_capabilities()


# Global instance
_global_processor: Optional[UniversalProcessor] = None


def get_universal_processor() -> UniversalProcessor:
    """Get the global UniversalProcessor instance.
    
    This implements a singleton pattern for convenient access to a shared
    processor instance across your application.
    
    Returns:
        The global UniversalProcessor instance
    
    Example:
        >>> import anyio
        >>> 
        >>> async def main():
        ...     processor = get_universal_processor()
        ...     result = await processor.process("document.pdf")
        ...     if result.success:
        ...         print("Success!")
        >>> 
        >>> anyio.run(main)
    """
    global _global_processor
    if _global_processor is None:
        _global_processor = UniversalProcessor()
        logger.info("Created global UniversalProcessor instance")
    return _global_processor


async def process(input_data: Any, **options) -> ProcessingResult:
    """Convenience function to process input with the global processor (async).
    
    This is the simplest way to process data - just one function call.
    
    Args:
        input_data: The input to process
        **options: Options passed to UniversalProcessor.process()
    
    Returns:
        ProcessingResult
    
    Example:
        >>> import anyio
        >>> from ipfs_datasets_py.processors.core import process
        >>> 
        >>> async def main():
        ...     result = await process("https://example.com")
        ...     if result.success:
        ...         print("Success!")
        >>> 
        >>> anyio.run(main)
        
    Or directly with anyio.run:
        >>> import anyio
        >>> from ipfs_datasets_py.processors.core import process
        >>> result = anyio.run(process, "https://example.com")
    """
    if not ANYIO_AVAILABLE:
        raise ImportError(
            "anyio is required for async processing. "
            "Install it with: pip install anyio"
        )
    processor = get_universal_processor()
    return await processor.process(input_data, **options)


async def process_batch(inputs: List[Any], **options) -> List[ProcessingResult]:
    """Convenience function to process multiple inputs (async).
    
    Args:
        inputs: List of inputs to process
        **options: Options passed to UniversalProcessor.process_batch()
    
    Returns:
        List of ProcessingResult objects
    
    Example:
        >>> import anyio
        >>> from ipfs_datasets_py.processors.core import process_batch
        >>> 
        >>> async def main():
        ...     results = await process_batch(["file1.pdf", "file2.pdf", "https://example.com"])
        ...     success_count = sum(1 for r in results if r.success)
        ...     print(f"{success_count}/{len(results)} succeeded")
        >>> 
        >>> anyio.run(main)
        
    Or directly with anyio.run:
        >>> import anyio
        >>> from ipfs_datasets_py.processors.core import process_batch
        >>> results = anyio.run(process_batch, ["file1.pdf", "file2.pdf"])
    """
    if not ANYIO_AVAILABLE:
        raise ImportError(
            "anyio is required for async batch processing. "
            "Install it with: pip install anyio"
        )
    processor = get_universal_processor()
    return await processor.process_batch(inputs, **options)
