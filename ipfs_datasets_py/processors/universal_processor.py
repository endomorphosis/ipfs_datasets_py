"""
UniversalProcessor - Single entrypoint for all processing needs.

This module provides the UniversalProcessor class, which automatically
routes inputs to appropriate specialized processors and returns
standardized knowledge graphs + vectors.
"""

from __future__ import annotations

import logging
import time
import anyio
from typing import Union, Optional, Any
from pathlib import Path
from dataclasses import dataclass, field

from .protocol import (
    ProcessorProtocol,
    ProcessingResult,
    ProcessingMetadata,
    ProcessingStatus,
    InputType,
    KnowledgeGraph,
    VectorStore
)
from .registry import ProcessorRegistry
from .input_detection import InputDetector, classify_input
from .caching import SmartCache
from .error_handling import (
    ProcessorError,
    TransientError,
    RetryConfig,
    RetryWithBackoff,
    CircuitBreaker,
    CircuitBreakerConfig
)
from .monitoring import HealthMonitor

logger = logging.getLogger(__name__)


@dataclass
class ProcessorConfig:
    """
    Configuration for UniversalProcessor.
    
    Attributes:
        enable_caching: Enable result caching
        parallel_workers: Number of workers for batch processing
        timeout_seconds: Timeout for individual processing operations
        fallback_enabled: Enable fallback to alternative processors on failure
        preferred_processors: Manual routing overrides {input_pattern: processor_name}
        max_retries: Maximum retry attempts on failure
        raise_on_error: Raise exception on processing error vs. return error result
        cache_size_mb: Maximum cache size in megabytes (default: 100)
        cache_ttl_seconds: Cache time-to-live in seconds (default: 3600)
        cache_eviction_policy: Cache eviction policy: "lru", "lfu", or "fifo" (default: "lru")
        enable_monitoring: Enable health checks and monitoring (default: True)
        circuit_breaker_enabled: Enable circuit breaker pattern (default: True)
        circuit_breaker_threshold: Number of failures before opening circuit (default: 5)
    """
    enable_caching: bool = True
    parallel_workers: int = 4
    timeout_seconds: int = 300
    fallback_enabled: bool = True
    preferred_processors: dict[str, str] = field(default_factory=dict)
    max_retries: int = 2
    raise_on_error: bool = False
    cache_size_mb: int = 100
    cache_ttl_seconds: int = 3600
    cache_eviction_policy: str = "lru"
    enable_monitoring: bool = True
    circuit_breaker_enabled: bool = True
    circuit_breaker_threshold: int = 5
    
    def __post_init__(self):
        """Validate configuration."""
        if self.parallel_workers < 1:
            raise ValueError("parallel_workers must be >= 1")
        
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be >= 1")
        
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        
        if self.cache_size_mb < 0:
            raise ValueError("cache_size_mb must be >= 0 (0 = no cache size limit)")
        
        if self.cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds must be >= 0 (0 = no expiration)")
        
        if self.cache_ttl_seconds > 86400:
            raise ValueError("cache_ttl_seconds must be between 0 and 86400 seconds (0 to 1 day)")
        
        if self.cache_eviction_policy not in ("lru", "lfu", "fifo"):
            raise ValueError("cache_eviction_policy must be one of: 'lru', 'lfu', 'fifo'")


@dataclass
class BatchProcessingResult:
    """
    Result of batch processing operation.
    
    Attributes:
        results: List of successful ProcessingResult objects
        errors: List of (input, error_message) tuples for failed inputs
        metadata: Batch processing metadata
    """
    results: list[ProcessingResult]
    errors: list[tuple[str, str]]
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        total = len(self.results) + len(self.errors)
        if total == 0:
            return 0.0
        return len(self.results) / total


class UniversalProcessor:
    """
    Universal processor that automatically routes inputs to specialized processors.
    
    UniversalProcessor provides a single, unified API for processing any type of
    input (URLs, files, folders) and produces standardized knowledge graphs and
    vector embeddings.
    
    Features:
    - Automatic input type detection (URL, file, folder, IPFS)
    - Processor selection based on capabilities
    - Parallel processing for batch inputs
    - Standardized knowledge graph + vector output
    - Error handling and fallback strategies
    - Caching and performance monitoring
    
    Example:
        >>> processor = UniversalProcessor()
        >>> 
        >>> # Process any input type
        >>> result = await processor.process("https://arxiv.org/pdf/2301.00001.pdf")
        >>> print(result.knowledge_graph.entities)
        >>> 
        >>> # Batch processing
        >>> results = await processor.process_batch([
        ...     "https://example.com",
        ...     "document.pdf",
        ...     "/path/to/folder"
        ... ])
        >>> print(f"Processed {len(results.results)} inputs successfully")
        >>> 
        >>> # Check processor status
        >>> stats = processor.get_statistics()
        >>> print(f"Total calls: {stats['total_calls']}")
    """
    
    def __init__(self, config: Optional[ProcessorConfig] = None):
        """
        Initialize UniversalProcessor.
        
        Args:
            config: Optional configuration. If None, uses default config.
        """
        self.config = config or ProcessorConfig()
        self.registry = ProcessorRegistry()
        self.detector = InputDetector()
        
        # Initialize smart cache
        if self.config.enable_caching:
            self._cache = SmartCache(
                max_size_mb=self.config.cache_size_mb,
                ttl_seconds=self.config.cache_ttl_seconds,
                eviction_policy=self.config.cache_eviction_policy
            )
        else:
            self._cache = None
        
        # Initialize retry handler
        retry_config = RetryConfig(
            max_retries=self.config.max_retries,
            initial_backoff=1.0,
            max_backoff=60.0
        )
        self._retry_handler = RetryWithBackoff(config=retry_config)
        
        # Initialize circuit breakers for each processor
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        
        # Initialize health monitor
        if self.config.enable_monitoring:
            self._health_monitor = HealthMonitor(self.registry)
        else:
            self._health_monitor = None
        
        # Basic statistics (in addition to registry stats)
        self._statistics = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "cache_hits": 0,
            "total_processing_time": 0.0
        }
        
        # Initialize processors
        self._initialize_processors()
        
        logger.info(
            f"UniversalProcessor initialized with {len(self.registry)} processors "
            f"(caching={'ON' if self.config.enable_caching else 'OFF'}, "
            f"monitoring={'ON' if self.config.enable_monitoring else 'OFF'})"
        )
    
    def _initialize_processors(self) -> None:
        """
        Register all available processors.
        
        This method dynamically imports and registers processors that are
        available in the system. It's designed to gracefully handle missing
        dependencies.
        """
        # Import and register IPFS processor (HIGHEST PRIORITY)
        try:
            from .adapters.ipfs_adapter import IPFSProcessorAdapter
            self.registry.register(IPFSProcessorAdapter(self), priority=20)
            logger.info("Registered IPFSProcessorAdapter")
        except ImportError as e:
            logger.debug(f"IPFSProcessorAdapter not available: {e}")
        
        # Import and register Batch processor
        try:
            from .adapters.batch_adapter import BatchProcessorAdapter
            self.registry.register(BatchProcessorAdapter(self), priority=15)
            logger.info("Registered BatchProcessorAdapter")
        except ImportError as e:
            logger.debug(f"BatchProcessorAdapter not available: {e}")
        
        # Import and register Specialized Scraper processor
        try:
            from .adapters.specialized_scraper_adapter import SpecializedScraperAdapter
            self.registry.register(SpecializedScraperAdapter(), priority=12)
            logger.info("Registered SpecializedScraperAdapter")
        except ImportError as e:
            logger.debug(f"SpecializedScraperAdapter not available: {e}")
        
        # Import and register PDF processor
        try:
            from .adapters.pdf_adapter import PDFProcessorAdapter
            self.registry.register(PDFProcessorAdapter(), priority=10)
            logger.info("Registered PDFProcessorAdapter")
        except ImportError as e:
            logger.debug(f"PDFProcessorAdapter not available: {e}")
        
        # Import and register GraphRAG processor
        try:
            from .adapters.graphrag_adapter import GraphRAGProcessorAdapter
            self.registry.register(GraphRAGProcessorAdapter(), priority=10)
            logger.info("Registered GraphRAGProcessorAdapter")
        except ImportError as e:
            logger.debug(f"GraphRAGProcessorAdapter not available: {e}")
        
        # Import and register Multimedia processor
        try:
            from .adapters.multimedia_adapter import MultimediaProcessorAdapter
            self.registry.register(MultimediaProcessorAdapter(), priority=10)
            logger.info("Registered MultimediaProcessorAdapter")
        except ImportError as e:
            logger.debug(f"MultimediaProcessorAdapter not available: {e}")
        
        # Import and register Web Archive processor
        try:
            from .adapters.web_archive_adapter import WebArchiveProcessorAdapter
            self.registry.register(WebArchiveProcessorAdapter(), priority=8)
            logger.info("Registered WebArchiveProcessorAdapter")
        except ImportError as e:
            logger.debug(f"WebArchiveProcessorAdapter not available: {e}")
        
        # Import and register FileConverter processor
        try:
            from .adapters.file_converter_adapter import FileConverterProcessorAdapter
            self.registry.register(FileConverterProcessorAdapter(), priority=5)
            logger.info("Registered FileConverterProcessorAdapter")
        except ImportError as e:
            logger.debug(f"FileConverterProcessorAdapter not available: {e}")
        
        if len(self.registry) == 0:
            logger.warning("No processors registered! UniversalProcessor will not be able to process inputs.")
    
    async def process(
        self,
        input_source: Union[str, Path, list],
        **options
    ) -> Union[ProcessingResult, BatchProcessingResult]:
        """
        Process any input: URL, file, folder, or list of inputs.
        
        This is the main entry point for processing. It automatically detects
        the input type and routes to the appropriate processor.
        
        Args:
            input_source: Input to process (URL, file path, folder path, or list)
            **options: Processor-specific options
            
        Returns:
            ProcessingResult for single input, BatchProcessingResult for list
            
        Raises:
            ValueError: If no processor can handle the input
            Exception: If processing fails and raise_on_error is True
            
        Example:
            >>> # Single file
            >>> result = await processor.process("document.pdf")
            >>> 
            >>> # URL
            >>> result = await processor.process("https://example.com")
            >>> 
            >>> # Batch
            >>> results = await processor.process(["file1.pdf", "file2.pdf"])
        """
        # Handle batch inputs
        if isinstance(input_source, list):
            return await self.process_batch(input_source, **options)
        
        # Update statistics
        self._statistics["total_calls"] += 1
        start_time = time.time()
        
        try:
            # Check cache
            cache_key = str(input_source)
            if self._cache and self._cache.has_key(cache_key):
                logger.info(f"Cache hit for: {input_source}")
                self._statistics["cache_hits"] += 1
                return self._cache.get(cache_key)
            
            # Classify input
            classification = self.detector.classify_for_routing(input_source)
            logger.info(
                f"Processing {input_source} "
                f"(type={classification['input_type']}, "
                f"suggested={classification['suggested_processors']})"
            )
            
            # Check for manual routing
            processor = self._check_manual_routing(input_source)
            
            # Find capable processors if no manual routing
            if processor is None:
                processors = await self.registry.find_processors(input_source)
                
                if not processors:
                    raise ValueError(
                        f"No processor found for: {input_source} "
                        f"(type={classification['input_type']})"
                    )
                
                # Select best processor
                processor = self.registry.select_best_processor(processors, input_source)
            
            if processor is None:
                raise ValueError(f"Could not select processor for: {input_source}")
            
            # Process with retries
            result = await self._process_with_retries(processor, input_source, **options)
            
            # Cache result
            if self._cache:
                self._cache.put(cache_key, result)
            
            # Update statistics
            elapsed = time.time() - start_time
            self._statistics["successful_calls"] += 1
            self._statistics["total_processing_time"] += elapsed
            
            # Record processor statistics
            processor_name = processor.get_name() if hasattr(processor, 'get_name') else processor.__class__.__name__
            self.registry.record_call(processor_name, success=True, duration_seconds=elapsed)
            
            logger.info(f"Successfully processed {input_source} in {elapsed:.2f}s")
            return result
        
        except Exception as e:
            # Update statistics
            elapsed = time.time() - start_time
            self._statistics["failed_calls"] += 1
            self._statistics["total_processing_time"] += elapsed
            
            logger.error(f"Failed to process {input_source}: {e}")
            
            if self.config.raise_on_error:
                raise
            
            # Return error result
            return self._create_error_result(input_source, str(e))
    
    async def _process_with_retries(
        self,
        processor: ProcessorProtocol,
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """
        Process with retry logic.
        
        Args:
            processor: Processor to use
            input_source: Input to process
            **options: Processing options
            
        Returns:
            ProcessingResult
            
        Raises:
            Exception: If all retries fail
        """
        last_error = None
        
        for attempt in range(self.config.max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"Retry attempt {attempt} for: {input_source}")
                
                result = await processor.process(input_source, **options)
                return result
            
            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1} failed for {input_source}: {e}")
                
                if attempt < self.config.max_retries:
                    # Try fallback processor if enabled
                    if self.config.fallback_enabled:
                        fallback = await self._find_fallback_processor(processor, input_source)
                        if fallback:
                            logger.info(f"Trying fallback processor: {fallback.get_name()}")
                            processor = fallback
                            continue
        
        # All retries failed
        raise last_error
    
    async def _find_fallback_processor(
        self,
        failed_processor: ProcessorProtocol,
        input_source: Union[str, Path]
    ) -> Optional[ProcessorProtocol]:
        """
        Find a fallback processor different from the failed one.
        
        Args:
            failed_processor: Processor that failed
            input_source: Input to process
            
        Returns:
            Alternative processor or None
        """
        processors = await self.registry.find_processors(input_source)
        
        # Filter out the failed processor
        failed_name = failed_processor.get_name() if hasattr(failed_processor, 'get_name') else failed_processor.__class__.__name__
        
        alternatives = [
            p for p in processors
            if (p.get_name() if hasattr(p, 'get_name') else p.__class__.__name__) != failed_name
        ]
        
        if alternatives:
            return self.registry.select_best_processor(alternatives, input_source)
        
        return None
    
    def _check_manual_routing(self, input_source: Union[str, Path]) -> Optional[ProcessorProtocol]:
        """
        Check if input matches any manual routing rules.
        
        Args:
            input_source: Input to check
            
        Returns:
            Processor if rule matches, None otherwise
        """
        input_str = str(input_source)
        
        for pattern, processor_name in self.config.preferred_processors.items():
            if pattern in input_str:
                processor = self.registry.get_processor(processor_name)
                if processor:
                    logger.info(f"Using manual routing: {processor_name} for {input_source}")
                    return processor
        
        return None
    
    def _create_error_result(self, input_source: Union[str, Path], error_message: str) -> ProcessingResult:
        """
        Create an error ProcessingResult.
        
        Args:
            input_source: Input that failed
            error_message: Error description
            
        Returns:
            ProcessingResult with error metadata
        """
        metadata = ProcessingMetadata(
            processor_name="UniversalProcessor",
            input_type=self.detector.detect_type(input_source),
            status=ProcessingStatus.FAILED
        )
        metadata.add_error(error_message)
        
        return ProcessingResult(
            knowledge_graph=KnowledgeGraph(source=str(input_source)),
            vectors=VectorStore(),
            content={"error": error_message},
            metadata=metadata
        )
    
    async def process_batch(
        self,
        inputs: list[Union[str, Path]],
        **options
    ) -> BatchProcessingResult:
        """
        Process multiple inputs in parallel.
        
        Args:
            inputs: List of inputs to process
            **options: Processing options applied to all inputs
            
        Returns:
            BatchProcessingResult with results and errors
            
        Example:
            >>> results = await processor.process_batch([
            ...     "file1.pdf",
            ...     "file2.pdf",
            ...     "https://example.com"
            ... ])
            >>> print(f"Success rate: {results.success_rate():.1%}")
        """
        logger.info(f"Batch processing {len(inputs)} inputs")
        start_time = time.time()
        
        results = []
        errors = []
        
        # For now, process sequentially
        # TODO: Implement parallel processing with worker pool
        for input_source in inputs:
            try:
                result = await self.process(input_source, **options)
                
                if result.is_successful():
                    results.append(result)
                else:
                    errors.append((str(input_source), str(result.metadata.errors)))
            
            except Exception as e:
                logger.error(f"Batch item failed {input_source}: {e}")
                errors.append((str(input_source), str(e)))
        
        elapsed = time.time() - start_time
        
        batch_metadata = {
            "total_inputs": len(inputs),
            "successful": len(results),
            "failed": len(errors),
            "processing_time_seconds": elapsed,
            "success_rate": len(results) / len(inputs) if inputs else 0.0
        }
        
        logger.info(
            f"Batch processing complete: {len(results)}/{len(inputs)} successful "
            f"in {elapsed:.2f}s"
        )
        
        return BatchProcessingResult(
            results=results,
            errors=errors,
            metadata=batch_metadata
        )
    
    def get_statistics(self) -> dict[str, Any]:
        """
        Get processing statistics.
        
        Returns:
            Dictionary with statistics:
            {
                "total_calls": int,
                "successful_calls": int,
                "failed_calls": int,
                "cache_hits": int,
                "total_processing_time": float,
                "average_processing_time": float,
                "success_rate": float,
                "processor_stats": dict
            }
        """
        total = self._statistics["total_calls"]
        avg_time = (
            self._statistics["total_processing_time"] / total
            if total > 0 else 0.0
        )
        success_rate = (
            self._statistics["successful_calls"] / total
            if total > 0 else 0.0
        )
        
        return {
            **self._statistics,
            "average_processing_time": avg_time,
            "success_rate": success_rate,
            "processor_stats": self.registry.get_statistics()
        }
    
    def reset_statistics(self) -> None:
        """Reset all statistics."""
        self._statistics = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "cache_hits": 0,
            "total_processing_time": 0.0
        }
        self.registry.reset_statistics()
        logger.info("Reset all statistics")
    
    def clear_cache(self) -> None:
        """Clear result cache."""
        if self._cache:
            self._cache.clear()
            logger.info("Cleared result cache")
    
    def list_processors(self) -> dict[str, dict[str, Any]]:
        """
        List all registered processors and their capabilities.
        
        Returns:
            Dictionary mapping processor names to their details
        """
        return self.registry.list_processors()
    
    def get_health_report(self, format: str = "text") -> str:
        """
        Generate health report for all processors.
        
        Args:
            format: Output format ("text" or "json")
            
        Returns:
            Formatted health report
            
        Example:
            >>> report = processor.get_health_report()
            >>> print(report)
        """
        if not self._health_monitor:
            return "Health monitoring is disabled"
        
        return self._health_monitor.get_health_report(format=format)
    
    def check_health(self):
        """
        Check overall system health.
        
        Returns:
            SystemHealth object with current status
            
        Example:
            >>> health = processor.check_health()
            >>> if health.status == HealthStatus.UNHEALTHY:
            ...     print("System is unhealthy!")
        """
        if not self._health_monitor:
            logger.warning("Health monitoring is disabled")
            return None
        
        return self._health_monitor.check_system_health()
    
    def get_cache_statistics(self) -> dict:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache stats (hits, misses, evictions, hit_rate)
        """
        if not self._cache:
            return {"enabled": False}
        
        stats = self._cache.get_statistics()
        return {
            "enabled": True,
            **stats.to_dict(),
            "size_mb": self._cache.get_size_mb(),
            "usage_percent": self._cache.get_usage_percent()
        }
    
    def _get_or_create_circuit_breaker(self, processor_name: str) -> Optional[CircuitBreaker]:
        """Get or create circuit breaker for processor."""
        if not self.config.circuit_breaker_enabled:
            return None
        
        if processor_name not in self._circuit_breakers:
            config = CircuitBreakerConfig(
                failure_threshold=self.config.circuit_breaker_threshold,
                success_threshold=2,
                timeout_seconds=60.0
            )
            self._circuit_breakers[processor_name] = CircuitBreaker(config=config)
        
        return self._circuit_breakers[processor_name]
    
    def __repr__(self) -> str:
        """String representation."""
        cache_count = len(self._cache._cache) if self._cache else 0
        return f"UniversalProcessor({len(self.registry)} processors, {cache_count} cached)"
