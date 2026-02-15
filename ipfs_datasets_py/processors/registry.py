"""
ProcessorRegistry - Discovery and management system for processors.

This module provides a registry for dynamically discovering and managing
processors, enabling automatic routing based on input capabilities.
"""

from __future__ import annotations

import logging
from typing import Union, Optional, Any
from pathlib import Path
from collections import defaultdict

from .protocol import ProcessorProtocol, ProcessorLike, InputType

logger = logging.getLogger(__name__)


class ProcessorRegistry:
    """
    Registry for discovering and managing processors.
    
    The ProcessorRegistry maintains a collection of registered processors
    and provides methods for finding processors that can handle specific
    inputs, listing available processors, and managing processor priorities.
    
    Features:
    - Dynamic processor registration
    - Capability-based routing (find processors by input type)
    - Priority-based selection (prefer higher priority processors)
    - Hot-reloading support
    - Statistics and monitoring
    
    Example:
        >>> registry = ProcessorRegistry()
        >>> registry.register(PDFProcessor())
        >>> registry.register(GraphRAGProcessor(), priority=10)
        >>> 
        >>> # Find processors for a PDF file
        >>> processors = await registry.find_processors("document.pdf")
        >>> processor = registry.select_best_processor(processors, "document.pdf")
        >>> 
        >>> # List all processors
        >>> info = registry.list_processors()
        >>> for name, details in info.items():
        ...     print(f"{name}: {details['types']}")
    """
    
    def __init__(self):
        """Initialize empty registry."""
        self._processors: dict[str, ProcessorLike] = {}
        self._priorities: dict[str, int] = {}
        self._capabilities: dict[str, list[str]] = {}
        self._statistics: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "total_time_seconds": 0.0
        })
    
    def register(
        self, 
        processor: ProcessorLike, 
        priority: Optional[int] = None,
        name: Optional[str] = None
    ) -> None:
        """
        Register a processor with optional priority.
        
        Args:
            processor: Processor instance implementing ProcessorProtocol
            priority: Optional priority (higher = more preferred). If None, uses processor.get_priority()
            name: Optional custom name. If None, uses processor.get_name()
            
        Raises:
            ValueError: If processor doesn't implement ProcessorProtocol
            
        Example:
            >>> registry.register(PDFProcessor())
            >>> registry.register(GraphRAGProcessor(), priority=10)
            >>> registry.register(CustomProcessor(), name="custom_v2")
        """
        # Validate processor implements protocol
        if not isinstance(processor, ProcessorProtocol):
            logger.warning(
                f"Processor {processor.__class__.__name__} does not implement ProcessorProtocol. "
                "It may not work correctly with UniversalProcessor."
            )
        
        # Get or generate name
        if name is None:
            if hasattr(processor, 'get_name'):
                name = processor.get_name()
            else:
                name = processor.__class__.__name__
        
        # Get priority
        if priority is None:
            if hasattr(processor, 'get_priority'):
                priority = processor.get_priority()
            else:
                priority = 0
        
        # Get capabilities
        if hasattr(processor, 'get_supported_types'):
            capabilities = processor.get_supported_types()
        else:
            capabilities = []
            logger.warning(f"Processor {name} does not declare supported types")
        
        # Register
        self._processors[name] = processor
        self._priorities[name] = priority
        self._capabilities[name] = capabilities
        
        logger.info(
            f"Registered processor: {name} "
            f"(priority={priority}, types={capabilities})"
        )
    
    def unregister(self, name: str) -> bool:
        """
        Unregister a processor by name.
        
        Args:
            name: Name of processor to unregister
            
        Returns:
            True if processor was unregistered, False if not found
        """
        if name not in self._processors:
            logger.warning(f"Processor {name} not found in registry")
            return False
        
        del self._processors[name]
        del self._priorities[name]
        del self._capabilities[name]
        if name in self._statistics:
            del self._statistics[name]
        
        logger.info(f"Unregistered processor: {name}")
        return True
    
    def get_processor(self, name: str) -> Optional[ProcessorLike]:
        """
        Get a processor by name.
        
        Args:
            name: Processor name
            
        Returns:
            Processor instance or None if not found
        """
        return self._processors.get(name)
    
    async def find_processors(
        self, 
        input_source: Union[str, Path]
    ) -> list[ProcessorLike]:
        """
        Find all processors that can handle the given input.
        
        This method queries all registered processors to determine which
        ones are capable of processing the given input source.
        
        Args:
            input_source: Input to process (URL, file path, folder path, etc.)
            
        Returns:
            List of processor instances that can handle the input
            
        Example:
            >>> processors = await registry.find_processors("document.pdf")
            >>> print(f"Found {len(processors)} capable processors")
        """
        capable = []
        
        for name, processor in self._processors.items():
            try:
                if hasattr(processor, 'can_process'):
                    can_handle = await processor.can_process(input_source)
                    if can_handle:
                        capable.append(processor)
                        logger.debug(f"Processor {name} can handle: {input_source}")
                else:
                    logger.debug(f"Processor {name} has no can_process method, skipping")
            except Exception as e:
                logger.error(f"Error checking processor {name}: {e}")
        
        if not capable:
            logger.warning(f"No processors found for input: {input_source}")
        else:
            logger.info(f"Found {len(capable)} processors for: {input_source}")
        
        return capable
    
    def select_best_processor(
        self,
        processors: list[ProcessorLike],
        input_source: Union[str, Path]
    ) -> Optional[ProcessorLike]:
        """
        Select the best processor from a list based on priority.
        
        When multiple processors can handle an input, this method selects
        the one with the highest priority.
        
        Args:
            processors: List of capable processors
            input_source: Input being processed (for logging)
            
        Returns:
            Best processor or None if list is empty
            
        Example:
            >>> processors = await registry.find_processors("test.pdf")
            >>> best = registry.select_best_processor(processors, "test.pdf")
        """
        if not processors:
            return None
        
        if len(processors) == 1:
            return processors[0]
        
        # Sort by priority (descending)
        def get_priority(processor: ProcessorLike) -> int:
            name = processor.get_name() if hasattr(processor, 'get_name') else processor.__class__.__name__
            return self._priorities.get(name, 0)
        
        sorted_processors = sorted(processors, key=get_priority, reverse=True)
        best = sorted_processors[0]
        
        best_name = best.get_name() if hasattr(best, 'get_name') else best.__class__.__name__
        best_priority = get_priority(best)
        
        logger.info(
            f"Selected processor {best_name} (priority={best_priority}) "
            f"from {len(processors)} candidates for: {input_source}"
        )
        
        return best
    
    def list_processors(self) -> dict[str, dict[str, Any]]:
        """
        List all registered processors and their capabilities.
        
        Returns:
            Dictionary mapping processor names to their details:
            {
                "ProcessorName": {
                    "types": ["pdf", "file"],
                    "priority": 10,
                    "statistics": {...}
                }
            }
            
        Example:
            >>> info = registry.list_processors()
            >>> for name, details in info.items():
            ...     print(f"{name}:")
            ...     print(f"  Types: {details['types']}")
            ...     print(f"  Priority: {details['priority']}")
            ...     print(f"  Calls: {details['statistics']['calls']}")
        """
        result = {}
        
        for name in self._processors:
            result[name] = {
                "types": self._capabilities.get(name, []),
                "priority": self._priorities.get(name, 0),
                "statistics": dict(self._statistics.get(name, {}))
            }
        
        return result
    
    def get_processors_by_type(self, input_type: str) -> list[str]:
        """
        Get all processors that support a specific input type.
        
        Args:
            input_type: Input type identifier (e.g., "pdf", "url", "video")
            
        Returns:
            List of processor names that support the type
            
        Example:
            >>> pdf_processors = registry.get_processors_by_type("pdf")
            >>> print(f"PDF processors: {pdf_processors}")
        """
        matching = []
        
        for name, types in self._capabilities.items():
            if input_type in types:
                matching.append(name)
        
        return matching
    
    def record_call(self, processor_name: str, success: bool, duration_seconds: float) -> None:
        """
        Record statistics about a processor call.
        
        This method is called by UniversalProcessor to track processor usage
        and performance.
        
        Args:
            processor_name: Name of the processor
            success: Whether the call succeeded
            duration_seconds: Time taken for the call
        """
        stats = self._statistics[processor_name]
        stats["calls"] += 1
        if success:
            stats["successes"] += 1
        else:
            stats["failures"] += 1
        stats["total_time_seconds"] += duration_seconds
    
    def get_statistics(self, processor_name: Optional[str] = None) -> dict[str, Any]:
        """
        Get statistics for a processor or all processors.
        
        Args:
            processor_name: Optional processor name. If None, returns stats for all processors
            
        Returns:
            Statistics dictionary
            
        Example:
            >>> stats = registry.get_statistics("PDFProcessor")
            >>> print(f"Success rate: {stats['successes'] / stats['calls']:.2%}")
        """
        if processor_name is not None:
            return dict(self._statistics.get(processor_name, {}))
        
        # Return all statistics
        return {name: dict(stats) for name, stats in self._statistics.items()}
    
    def reset_statistics(self) -> None:
        """Reset all statistics."""
        self._statistics.clear()
        logger.info("Reset all processor statistics")
    
    def clear(self) -> None:
        """Clear all registered processors."""
        self._processors.clear()
        self._priorities.clear()
        self._capabilities.clear()
        self._statistics.clear()
        logger.info("Cleared all registered processors")
    
    def __len__(self) -> int:
        """Return number of registered processors."""
        return len(self._processors)
    
    def __contains__(self, name: str) -> bool:
        """Check if a processor is registered."""
        return name in self._processors
    
    def __repr__(self) -> str:
        """String representation of registry."""
        return f"ProcessorRegistry({len(self._processors)} processors)"


# Global registry instance (optional convenience)
_global_registry: Optional[ProcessorRegistry] = None


def get_global_registry() -> ProcessorRegistry:
    """
    Get or create the global processor registry.
    
    This is a convenience function for using a shared registry across
    the application. Most applications should create their own registry
    instance for better control.
    
    Returns:
        Global ProcessorRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ProcessorRegistry()
    return _global_registry
