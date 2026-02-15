"""ProcessorRegistry - Registration and discovery of processors.

This module provides a centralized registry for managing processors in the
unified processor system. It handles processor registration, discovery based
on input context, priority-based selection, and capability reporting.

Supports both synchronous and asynchronous processor operations. The
get_processors() method is async to support processors with async can_handle()
checks.
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
import logging

from .protocol import ProcessorProtocol, ProcessingContext


logger = logging.getLogger(__name__)


@dataclass
class ProcessorEntry:
    """Entry in the processor registry.
    
    Represents a registered processor with its metadata.
    
    Attributes:
        processor: The processor instance
        priority: Processing priority (higher = checked first)
        name: Human-readable name for the processor
        enabled: Whether the processor is currently enabled
        metadata: Additional metadata about the processor
    """
    processor: ProcessorProtocol
    priority: int = 10
    name: str = ""
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Auto-generate name if not provided."""
        if not self.name:
            self.name = self.processor.__class__.__name__


class ProcessorRegistry:
    """Registry for managing processors with async support.
    
    The ProcessorRegistry is the central manager for all processors in the
    unified system. It handles:
    - Processor registration with priorities
    - Discovery of suitable processors for inputs (async)
    - Priority-based selection
    - Capability aggregation and reporting
    
    Processors are stored with priorities (default 10). When selecting a
    processor for an input, the registry checks processors in priority order
    (highest first) and returns the first one where can_handle() returns True.
    
    Note: get_processors() is async to support processors with async can_handle()
    methods.
    
    Example:
        >>> registry = ProcessorRegistry()
        >>> registry.register(pdf_processor, priority=10, name="PDF Processor")
        >>> registry.register(graphrag_processor, priority=20, name="GraphRAG")
        >>> 
        >>> context = ProcessingContext(InputType.FILE, "document.pdf")
        >>> processors = await registry.get_processors(context)
        >>> if processors:
        ...     result = await processors[0].process(context)
    """
    
    def __init__(self):
        """Initialize empty processor registry."""
        self._processors: List[ProcessorEntry] = []
        self._name_index: Dict[str, ProcessorEntry] = {}
        logger.info("ProcessorRegistry initialized")
    
    def register(
        self,
        processor: ProcessorProtocol,
        priority: int = 10,
        name: Optional[str] = None,
        enabled: bool = True,
        **metadata: Any
    ) -> str:
        """Register a processor in the registry.
        
        Adds a processor to the registry with the specified priority. Higher
        priority processors are checked first when selecting a processor for
        an input.
        
        Args:
            processor: Processor instance implementing ProcessorProtocol
            priority: Processing priority (default 10, higher = checked first)
            name: Human-readable name (defaults to class name)
            enabled: Whether processor is enabled (default True)
            **metadata: Additional metadata to store with the processor
            
        Returns:
            Name of the registered processor
            
        Raises:
            ValueError: If a processor with the same name already exists
            
        Example:
            >>> registry.register(
            ...     pdf_processor,
            ...     priority=10,
            ...     name="PDF Processor",
            ...     description="Handles PDF documents"
            ... )
            'PDF Processor'
        """
        # Create entry
        entry = ProcessorEntry(
            processor=processor,
            priority=priority,
            name=name or "",
            enabled=enabled,
            metadata=metadata
        )
        
        # Check for duplicate name
        if entry.name in self._name_index:
            raise ValueError(f"Processor with name '{entry.name}' already registered")
        
        # Add to registry
        self._processors.append(entry)
        self._name_index[entry.name] = entry
        
        # Keep sorted by priority (descending)
        self._processors.sort(key=lambda e: e.priority, reverse=True)
        
        logger.info(
            f"Registered processor '{entry.name}' with priority {priority} "
            f"(total: {len(self._processors)})"
        )
        
        return entry.name
    
    def unregister(self, name: str) -> bool:
        """Unregister a processor by name.
        
        Removes a processor from the registry.
        
        Args:
            name: Name of the processor to remove
            
        Returns:
            True if processor was found and removed, False otherwise
            
        Example:
            >>> registry.unregister("PDF Processor")
            True
        """
        if name not in self._name_index:
            logger.warning(f"Processor '{name}' not found for unregistration")
            return False
        
        # Remove from index
        entry = self._name_index.pop(name)
        
        # Remove from list
        self._processors = [e for e in self._processors if e.name != name]
        
        logger.info(f"Unregistered processor '{name}' (remaining: {len(self._processors)})")
        return True
    
    def get_processor(self, name: str) -> Optional[ProcessorProtocol]:
        """Get a processor by name.
        
        Args:
            name: Name of the processor
            
        Returns:
            Processor instance or None if not found
            
        Example:
            >>> processor = registry.get_processor("PDF Processor")
        """
        entry = self._name_index.get(name)
        return entry.processor if entry else None
    
    async def get_processors(
        self,
        context: ProcessingContext,
        limit: Optional[int] = None
    ) -> List[ProcessorProtocol]:
        """Get processors that can handle the given context (async).
        
        Checks all enabled processors in priority order (highest first) and
        returns those where can_handle() returns True. This method is async
        because it needs to await the can_handle() method on each processor.
        
        Args:
            context: Processing context to check
            limit: Maximum number of processors to return (None = all)
            
        Returns:
            List of processors that can handle the context, sorted by priority
            
        Example:
            >>> context = ProcessingContext(InputType.FILE, "doc.pdf")
            >>> processors = await registry.get_processors(context)
            >>> if processors:
            ...     result = await processors[0].process(context)
        """
        suitable = []
        
        for entry in self._processors:
            # Skip disabled processors
            if not entry.enabled:
                continue
            
            # Check if processor can handle this context (async)
            try:
                if await entry.processor.can_handle(context):
                    suitable.append(entry.processor)
                    logger.debug(
                        f"Processor '{entry.name}' (priority {entry.priority}) "
                        f"can handle {context.input_type}"
                    )
                    
                    # Check limit
                    if limit and len(suitable) >= limit:
                        break
            except Exception as e:
                logger.error(
                    f"Error checking if '{entry.name}' can handle context: {e}"
                )
        
        if not suitable:
            logger.warning(
                f"No suitable processors found for {context.input_type} "
                f"(format: {context.get_format()})"
            )
        else:
            logger.info(
                f"Found {len(suitable)} suitable processor(s) for "
                f"{context.input_type}"
            )
        
        return suitable
    
    def get_all_processors(self) -> List[Tuple[str, ProcessorProtocol, int]]:
        """Get all registered processors.
        
        Returns:
            List of tuples (name, processor, priority) sorted by priority
            
        Example:
            >>> for name, processor, priority in registry.get_all_processors():
            ...     print(f"{name}: priority {priority}")
        """
        return [
            (entry.name, entry.processor, entry.priority)
            for entry in self._processors
        ]
    
    def get_enabled_count(self) -> int:
        """Get count of enabled processors.
        
        Returns:
            Number of enabled processors
        """
        return sum(1 for e in self._processors if e.enabled)
    
    def get_total_count(self) -> int:
        """Get total count of registered processors.
        
        Returns:
            Total number of registered processors (enabled and disabled)
        """
        return len(self._processors)
    
    def enable(self, name: str) -> bool:
        """Enable a processor.
        
        Args:
            name: Name of the processor
            
        Returns:
            True if processor was found and enabled, False otherwise
        """
        entry = self._name_index.get(name)
        if entry:
            entry.enabled = True
            logger.info(f"Enabled processor '{name}'")
            return True
        return False
    
    def disable(self, name: str) -> bool:
        """Disable a processor.
        
        Args:
            name: Name of the processor
            
        Returns:
            True if processor was found and disabled, False otherwise
        """
        entry = self._name_index.get(name)
        if entry:
            entry.enabled = False
            logger.info(f"Disabled processor '{name}'")
            return True
        return False
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get aggregated capabilities from all processors.
        
        Collects and aggregates capabilities from all registered processors.
        Returns information about what input types, formats, and features
        the system can handle.
        
        Returns:
            Dictionary with aggregated capabilities:
            - total_processors: Number of registered processors
            - enabled_processors: Number of enabled processors
            - processors: List of processor details
            - supported_input_types: Set of supported input types
            - supported_formats: Set of supported formats
            
        Example:
            >>> caps = registry.get_capabilities()
            >>> print(f"Total processors: {caps['total_processors']}")
            >>> print(f"Supported formats: {caps['supported_formats']}")
        """
        processors_info = []
        all_input_types: Set[str] = set()
        all_formats: Set[str] = set()
        
        for entry in self._processors:
            try:
                # Get processor capabilities
                caps = entry.processor.get_capabilities()
                
                # Extract supported types and formats
                if 'input_types' in caps:
                    types = caps['input_types']
                    if isinstance(types, (list, set)):
                        all_input_types.update(str(t) for t in types)
                
                if 'formats' in caps:
                    formats = caps['formats']
                    if isinstance(formats, (list, set)):
                        all_formats.update(formats)
                
                # Add processor info
                processors_info.append({
                    'name': entry.name,
                    'priority': entry.priority,
                    'enabled': entry.enabled,
                    'capabilities': caps,
                    'metadata': entry.metadata
                })
            except Exception as e:
                logger.error(
                    f"Error getting capabilities from '{entry.name}': {e}"
                )
                processors_info.append({
                    'name': entry.name,
                    'priority': entry.priority,
                    'enabled': entry.enabled,
                    'error': str(e)
                })
        
        return {
            'total_processors': len(self._processors),
            'enabled_processors': self.get_enabled_count(),
            'processors': processors_info,
            'supported_input_types': sorted(all_input_types),
            'supported_formats': sorted(all_formats)
        }
    
    def clear(self) -> None:
        """Clear all registered processors.
        
        Removes all processors from the registry.
        
        Example:
            >>> registry.clear()
            >>> assert registry.get_total_count() == 0
        """
        count = len(self._processors)
        self._processors.clear()
        self._name_index.clear()
        logger.info(f"Cleared registry ({count} processors removed)")
    
    def __len__(self) -> int:
        """Get number of registered processors."""
        return len(self._processors)
    
    def __contains__(self, name: str) -> bool:
        """Check if a processor with the given name is registered."""
        return name in self._name_index
    
    def __repr__(self) -> str:
        """String representation of the registry."""
        return (
            f"ProcessorRegistry(total={len(self._processors)}, "
            f"enabled={self.get_enabled_count()})"
        )


# Convenience function for creating a global registry
_global_registry: Optional[ProcessorRegistry] = None


def get_global_registry() -> ProcessorRegistry:
    """Get or create the global processor registry.
    
    This provides a singleton registry instance that can be shared across
    the application. Useful for registering processors once and using them
    everywhere.
    
    Returns:
        Global ProcessorRegistry instance
        
    Example:
        >>> from ipfs_datasets_py.processors.core import get_global_registry
        >>> registry = get_global_registry()
        >>> registry.register(my_processor)
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ProcessorRegistry()
    return _global_registry
