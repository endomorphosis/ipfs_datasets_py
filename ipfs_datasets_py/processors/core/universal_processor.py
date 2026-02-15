"""UniversalProcessor - Single entry point for all processing operations.

This module provides the UniversalProcessor class, which acts as a unified interface
for processing any input type (URLs, files, folders, text, binary, IPFS content).

The UniversalProcessor automatically:
1. Detects the input type using InputDetector
2. Finds suitable processors using ProcessorRegistry
3. Processes the input with retry logic and fallbacks
4. Returns standardized ProcessingResult

Example usage:
    >>> from ipfs_datasets_py.processors.core import UniversalProcessor
    >>> processor = UniversalProcessor()
    >>> result = processor.process("https://example.com")
    >>> if result.success:
    ...     print(f"Found {result.get_entity_count()} entities")

Or using the convenience function:
    >>> from ipfs_datasets_py.processors.core import process
    >>> result = process("document.pdf")
"""

import logging
import time
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field

from .protocol import ProcessingContext, ProcessingResult, ProcessorProtocol, InputType
from .input_detector import InputDetector
from .processor_registry import ProcessorRegistry, get_global_registry

logger = logging.getLogger(__name__)


class UniversalProcessor:
    """Universal processor that automatically handles any input type.
    
    This is the main entry point for the processor system. It integrates
    InputDetector and ProcessorRegistry to provide automatic input classification,
    processor selection, and processing with error handling and retries.
    
    Attributes:
        registry: ProcessorRegistry for finding suitable processors
        detector: InputDetector for classifying inputs
        max_retries: Default maximum number of retry attempts
        retry_delay: Default delay between retries in seconds
    
    Example:
        >>> processor = UniversalProcessor()
        >>> # Register your processors
        >>> processor.register_processor(pdf_processor, priority=10)
        >>> # Process any input
        >>> result = processor.process("document.pdf")
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
    
    def process(
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
        """Process input data automatically.
        
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
            timeout: Optional processing timeout in seconds
            **options: Additional options passed to processor
        
        Returns:
            ProcessingResult with success status, knowledge graph, vectors, etc.
        
        Example:
            >>> result = processor.process("https://example.com")
            >>> if result.success:
            ...     print(f"Success! {result.get_entity_count()} entities")
            ... else:
            ...     print(f"Failed: {result.errors}")
        """
        # Use defaults if not specified
        max_retries = max_retries if max_retries is not None else self.max_retries
        retry_delay = retry_delay if retry_delay is not None else self.retry_delay
        
        try:
            # Step 1: Detect input type if context not provided
            if context is None:
                try:
                    context = self.detector.detect(input_data, **options)
                    logger.info(
                        f"Detected input type: {context.input_type.value}, "
                        f"format: {context.get_format()}"
                    )
                except Exception as e:
                    logger.error(f"Error detecting input: {e}", exc_info=True)
                    return ProcessingResult(
                        success=False,
                        errors=[f"Input detection failed: {str(e)}"]
                    )
            
            # Step 2: Find suitable processors
            try:
                processors = self.registry.get_processors(
                    context,
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
                        
                        # Set timeout if specified
                        start_time = time.time()
                        result = processor.process(context)
                        elapsed = time.time() - start_time
                        
                        if timeout and elapsed > timeout:
                            logger.warning(
                                f"{processor_name} exceeded timeout "
                                f"({elapsed:.2f}s > {timeout}s)"
                            )
                            result.success = False
                            result.add_error(f"Processing timeout exceeded")
                        
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
                                time.sleep(delay)
                            
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
                            time.sleep(delay)
                
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
                
        except Exception as e:
            logger.error(f"Unexpected error in process(): {e}", exc_info=True)
            return ProcessingResult(
                success=False,
                errors=[f"Unexpected processing error: {str(e)}"]
            )
    
    def process_batch(
        self,
        inputs: List[Any],
        parallel: bool = False,
        **options
    ) -> List[ProcessingResult]:
        """Process multiple inputs.
        
        Args:
            inputs: List of inputs to process
            parallel: If True, process in parallel (not yet implemented)
            **options: Options passed to process()
        
        Returns:
            List of ProcessingResult objects, one per input
        
        Example:
            >>> results = processor.process_batch(["file1.pdf", "file2.pdf"])
            >>> success_count = sum(1 for r in results if r.success)
            >>> print(f"{success_count}/{len(results)} succeeded")
        """
        logger.info(f"Processing batch of {len(inputs)} inputs")
        
        if parallel:
            logger.warning("Parallel processing not yet implemented, using sequential")
            # TODO: Implement parallel processing with ThreadPoolExecutor
        
        results = []
        for i, input_data in enumerate(inputs):
            logger.info(f"Processing batch item {i + 1}/{len(inputs)}")
            result = self.process(input_data, **options)
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
        >>> processor = get_universal_processor()
        >>> result = processor.process("document.pdf")
    """
    global _global_processor
    if _global_processor is None:
        _global_processor = UniversalProcessor()
        logger.info("Created global UniversalProcessor instance")
    return _global_processor


def process(input_data: Any, **options) -> ProcessingResult:
    """Convenience function to process input with the global processor.
    
    This is the simplest way to process data - just one function call.
    
    Args:
        input_data: The input to process
        **options: Options passed to UniversalProcessor.process()
    
    Returns:
        ProcessingResult
    
    Example:
        >>> from ipfs_datasets_py.processors.core import process
        >>> result = process("https://example.com")
        >>> if result.success:
        ...     print("Success!")
    """
    processor = get_universal_processor()
    return processor.process(input_data, **options)


def process_batch(inputs: List[Any], **options) -> List[ProcessingResult]:
    """Convenience function to process multiple inputs.
    
    Args:
        inputs: List of inputs to process
        **options: Options passed to UniversalProcessor.process_batch()
    
    Returns:
        List of ProcessingResult objects
    
    Example:
        >>> from ipfs_datasets_py.processors.core import process_batch
        >>> results = process_batch(["file1.pdf", "file2.pdf", "https://example.com"])
    """
    processor = get_universal_processor()
    return processor.process_batch(inputs, **options)
