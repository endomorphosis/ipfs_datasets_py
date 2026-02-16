"""Unified ProcessorRegistry - Central processor management system.

This module provides the consolidated processor registry that combines the best
features from both the legacy registry.py and core/processor_registry.py implementations.

Features:
- Async/await support for modern processors
- Priority-based processor selection
- Capability-based routing
- Statistics tracking and monitoring
- Hot-reloading support
- ProcessorEntry dataclass for better organization

This is the single source of truth for processor registration and discovery.
Legacy imports from processors.registry are redirected here via deprecation shims.
"""

from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple, Union, Set
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path
import logging

from .protocol import ProcessorProtocol, ProcessingContext, InputType

logger = logging.getLogger(__name__)


@dataclass
class ProcessorEntry:
    """Entry in the processor registry.
    
    Represents a registered processor with its metadata and state.
    
    Attributes:
        processor: The processor instance implementing ProcessorProtocol
        priority: Processing priority (higher = checked first, default 10)
        name: Human-readable name for the processor
        enabled: Whether the processor is currently enabled
        metadata: Additional metadata about the processor
        capabilities: List of input types this processor can handle
        statistics: Runtime statistics for this processor
    """
    processor: ProcessorProtocol
    priority: int = 10
    name: str = ""
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=lambda: {
        "calls": 0,
        "successes": 0,
        "failures": 0,
        "total_time_seconds": 0.0
    })
    
    def __post_init__(self):
        """Auto-generate name and capabilities if not provided."""
        if not self.name:
            self.name = self.processor.__class__.__name__
        
        # Auto-discover capabilities if not explicitly set
        if not self.capabilities and hasattr(self.processor, 'get_supported_types'):
            try:
                self.capabilities = self.processor.get_supported_types()
            except Exception as e:
                logger.warning(f"Failed to get capabilities for {self.name}: {e}")


class ProcessorRegistry:
    """Unified registry for managing processors with async support.
    
    The ProcessorRegistry is the central manager for all processors in the
    unified system. This consolidated version combines the best features of
    both legacy implementations:
    
    - From legacy registry.py: Statistics tracking, capability management
    - From core/processor_registry.py: Async support, ProcessorEntry dataclass
    
    Features:
    - Processor registration with priorities
    - Discovery of suitable processors for inputs (async)
    - Priority-based selection
    - Capability aggregation and reporting
    - Runtime statistics and monitoring
    - Enable/disable processors without unregistering
    
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
        logger.info("Unified ProcessorRegistry initialized")
    
    def register(
        self,
        processor: ProcessorProtocol,
        priority: Optional[int] = None,
        name: Optional[str] = None,
        enabled: bool = True,
        capabilities: Optional[List[str]] = None,
        **metadata: Any
    ) -> str:
        """Register a processor in the registry.
        
        Adds a processor to the registry with the specified priority. Higher
        priority processors are checked first when selecting a processor for
        an input.
        
        Args:
            processor: Processor instance implementing ProcessorProtocol
            priority: Processing priority (default 10, higher = checked first)
                     If None, tries processor.get_priority() then defaults to 10
            name: Human-readable name (defaults to class name)
            enabled: Whether processor is enabled (default True)
            capabilities: List of supported input types (auto-detected if None)
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
            ...     capabilities=["file", "pdf"],
            ...     description="Handles PDF documents"
            ... )
            'PDF Processor'
        """
        # Validate processor implements protocol
        if not isinstance(processor, ProcessorProtocol):
            logger.warning(
                f"Processor {processor.__class__.__name__} does not implement ProcessorProtocol. "
                "It may not work correctly."
            )
        
        # Get priority
        if priority is None:
            if hasattr(processor, 'get_priority'):
                try:
                    priority = processor.get_priority()
                except Exception as e:
                    logger.warning(f"Failed to get priority: {e}, using default")
                    priority = 10
            else:
                priority = 10
        
        # Get capabilities if not provided
        if capabilities is None:
            if hasattr(processor, 'get_supported_types'):
                try:
                    capabilities = processor.get_supported_types()
                except Exception as e:
                    logger.warning(f"Failed to get capabilities: {e}")
                    capabilities = []
            else:
                capabilities = []
        
        # Create entry
        entry = ProcessorEntry(
            processor=processor,
            priority=priority,
            name=name or "",
            enabled=enabled,
            capabilities=capabilities,
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
            f"and capabilities {entry.capabilities} (total: {len(self._processors)})"
        )
        
        return entry.name
    
    def unregister(self, name: str) -> bool:
        """Unregister a processor by name.
        
        Removes a processor from the registry permanently.
        
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
            Processor instance if found, None otherwise
            
        Example:
            >>> processor = registry.get_processor("PDF Processor")
        """
        entry = self._name_index.get(name)
        return entry.processor if entry else None
    
    async def get_processors(
        self,
        context: ProcessingContext,
        enabled_only: bool = True
    ) -> List[ProcessorProtocol]:
        """Get processors that can handle the given context (async).
        
        Checks each registered processor (in priority order) to see if it can
        handle the given input context. Returns list of matching processors
        sorted by priority (highest first).
        
        This method is async to support processors with async can_handle() methods.
        
        Args:
            context: ProcessingContext with input information
            enabled_only: If True, only return enabled processors (default)
            
        Returns:
            List of processors that can handle the context, sorted by priority
            
        Example:
            >>> context = ProcessingContext(InputType.FILE, "document.pdf")
            >>> processors = await registry.get_processors(context)
            >>> for processor in processors:
            ...     result = await processor.process(context)
        """
        matching = []
        
        for entry in self._processors:
            # Skip if disabled and enabled_only is True
            if enabled_only and not entry.enabled:
                continue
            
            # Check if processor can handle this context
            try:
                processor = entry.processor
                
                # Try async can_handle if available
                if hasattr(processor, 'can_handle'):
                    can_handle_method = getattr(processor, 'can_handle')
                    
                    # Check if it's async
                    import inspect
                    if inspect.iscoroutinefunction(can_handle_method):
                        can_handle = await can_handle_method(context)
                    else:
                        can_handle = can_handle_method(context)
                    
                    if can_handle:
                        matching.append(processor)
                        logger.debug(f"Processor '{entry.name}' can handle context")
                else:
                    # Fallback: check capabilities
                    if str(context.input_type.value) in entry.capabilities:
                        matching.append(processor)
                        logger.debug(f"Processor '{entry.name}' matches by capability")
                        
            except Exception as e:
                logger.error(f"Error checking processor '{entry.name}': {e}", exc_info=True)
                continue
        
        return matching
    
    async def find_processors(
        self,
        input_source: Union[str, Path, bytes],
        input_type: Optional[Union[InputType, str]] = None
    ) -> List[ProcessorProtocol]:
        """Find processors for an input (legacy API, async).
        
        This is a convenience method that creates a ProcessingContext and calls
        get_processors(). Provided for backward compatibility with legacy code.
        
        Args:
            input_source: Input source (path, URL, or content)
            input_type: Type of input (auto-detected if None)
            
        Returns:
            List of matching processors sorted by priority
        """
        # Auto-detect input type if not provided
        if input_type is None:
            # Simple heuristic detection
            if isinstance(input_source, bytes):
                input_type = InputType.BINARY
            elif isinstance(input_source, (str, Path)):
                source_str = str(input_source)
                if source_str.startswith(('http://', 'https://')):
                    input_type = InputType.URL
                elif Path(source_str).exists():
                    if Path(source_str).is_dir():
                        input_type = InputType.FOLDER
                    else:
                        input_type = InputType.FILE
                else:
                    input_type = InputType.TEXT
            else:
                input_type = InputType.BINARY
        elif isinstance(input_type, str):
            input_type = InputType.from_string(input_type)
        
        # Create context
        context = ProcessingContext(
            input_type=input_type,
            source=input_source
        )
        
        return await self.get_processors(context)
    
    def select_best_processor(
        self,
        processors: List[ProcessorProtocol],
        input_source: Any
    ) -> Optional[ProcessorProtocol]:
        """Select the best processor from a list (legacy API, sync).
        
        Selects the highest priority processor from the list. Since processors
        are already sorted by priority in get_processors(), this simply returns
        the first one.
        
        Args:
            processors: List of candidate processors
            input_source: Input source (for logging)
            
        Returns:
            Best processor or None if list is empty
        """
        if not processors:
            return None
        
        best = processors[0]
        best_name = best.__class__.__name__
        if hasattr(best, 'get_name'):
            try:
                best_name = best.get_name()
            except Exception:
                pass
        
        logger.info(f"Selected processor '{best_name}' for input: {input_source}")
        return best
    
    def get_all_processors(self) -> List[Tuple[str, ProcessorProtocol, int]]:
        """Get all registered processors with their names and priorities.
        
        Returns:
            List of (name, processor, priority) tuples sorted by priority
        """
        return [(e.name, e.processor, e.priority) for e in self._processors]
    
    def list_processors(self) -> Dict[str, Dict[str, Any]]:
        """List all registered processors with their metadata.
        
        Returns:
            Dictionary mapping processor names to their information:
            - processor: The processor instance
            - priority: Priority value
            - enabled: Whether enabled
            - capabilities: List of supported types
            - statistics: Runtime statistics
            - metadata: Additional metadata
        """
        result = {}
        for entry in self._processors:
            result[entry.name] = {
                "processor": entry.processor,
                "priority": entry.priority,
                "enabled": entry.enabled,
                "capabilities": entry.capabilities,
                "statistics": entry.statistics.copy(),
                "metadata": entry.metadata.copy()
            }
        return result
    
    def get_processors_by_type(self, input_type: Union[str, InputType]) -> List[str]:
        """Get processor names that support a specific input type.
        
        Args:
            input_type: Input type to search for (string or InputType enum)
            
        Returns:
            List of processor names that support this type
        """
        if isinstance(input_type, InputType):
            input_type = input_type.value
        
        matching = []
        for entry in self._processors:
            if input_type in entry.capabilities:
                matching.append(entry.name)
        
        return matching
    
    def get_enabled_count(self) -> int:
        """Get count of enabled processors.
        
        Returns:
            Number of enabled processors
        """
        return sum(1 for e in self._processors if e.enabled)
    
    def get_total_count(self) -> int:
        """Get total count of registered processors.
        
        Returns:
            Total number of registered processors
        """
        return len(self._processors)
    
    def enable(self, name: str) -> bool:
        """Enable a processor.
        
        Args:
            name: Name of processor to enable
            
        Returns:
            True if processor was found and enabled, False otherwise
        """
        entry = self._name_index.get(name)
        if entry:
            entry.enabled = True
            logger.info(f"Enabled processor '{name}'")
            return True
        logger.warning(f"Processor '{name}' not found for enable")
        return False
    
    def disable(self, name: str) -> bool:
        """Disable a processor.
        
        Args:
            name: Name of processor to disable
            
        Returns:
            True if processor was found and disabled, False otherwise
        """
        entry = self._name_index.get(name)
        if entry:
            entry.enabled = False
            logger.info(f"Disabled processor '{name}'")
            return True
        logger.warning(f"Processor '{name}' not found for disable")
        return False
    
    def record_call(
        self,
        processor_name: str,
        success: bool,
        duration_seconds: float
    ) -> None:
        """Record a processor call for statistics tracking.
        
        Args:
            processor_name: Name of the processor
            success: Whether the call succeeded
            duration_seconds: Duration of the call in seconds
        """
        entry = self._name_index.get(processor_name)
        if entry:
            stats = entry.statistics
            stats["calls"] += 1
            if success:
                stats["successes"] += 1
            else:
                stats["failures"] += 1
            stats["total_time_seconds"] += duration_seconds
    
    def get_statistics(
        self,
        processor_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get statistics for processors.
        
        Args:
            processor_name: Specific processor name, or None for all processors
            
        Returns:
            Statistics dictionary for the processor(s)
        """
        if processor_name:
            entry = self._name_index.get(processor_name)
            if entry:
                return entry.statistics.copy()
            return {}
        
        # Return all statistics
        return {
            entry.name: entry.statistics.copy()
            for entry in self._processors
        }
    
    def reset_statistics(self, processor_name: Optional[str] = None) -> None:
        """Reset statistics for processors.
        
        Args:
            processor_name: Specific processor name, or None for all processors
        """
        if processor_name:
            entry = self._name_index.get(processor_name)
            if entry:
                entry.statistics = {
                    "calls": 0,
                    "successes": 0,
                    "failures": 0,
                    "total_time_seconds": 0.0
                }
        else:
            for entry in self._processors:
                entry.statistics = {
                    "calls": 0,
                    "successes": 0,
                    "failures": 0,
                    "total_time_seconds": 0.0
                }
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get aggregated capabilities of all registered processors.
        
        Returns:
            Dictionary with:
            - total_processors: Total count
            - enabled_processors: Enabled count
            - supported_types: Set of all supported input types
            - by_type: Mapping of input types to processor names
        """
        all_types: Set[str] = set()
        by_type: Dict[str, List[str]] = defaultdict(list)
        
        for entry in self._processors:
            for capability in entry.capabilities:
                all_types.add(capability)
                by_type[capability].append(entry.name)
        
        return {
            "total_processors": len(self._processors),
            "enabled_processors": self.get_enabled_count(),
            "supported_types": sorted(all_types),
            "by_type": dict(by_type)
        }
    
    def clear(self) -> None:
        """Clear all registered processors.
        
        Removes all processors from the registry. Use with caution.
        """
        count = len(self._processors)
        self._processors.clear()
        self._name_index.clear()
        logger.info(f"Cleared registry ({count} processors removed)")
    
    def __len__(self) -> int:
        """Get number of registered processors."""
        return len(self._processors)
    
    def __contains__(self, name: str) -> bool:
        """Check if a processor name is registered."""
        return name in self._name_index
    
    def __repr__(self) -> str:
        """String representation of registry."""
        enabled = self.get_enabled_count()
        total = len(self._processors)
        return (
            f"ProcessorRegistry(total={total}, enabled={enabled}, "
            f"priorities={[e.priority for e in self._processors[:3]]}...)"
        )


# Global registry instance
_global_registry: Optional[ProcessorRegistry] = None


def get_global_registry() -> ProcessorRegistry:
    """Get or create the global processor registry singleton.
    
    Returns the global registry instance, creating it if it doesn't exist yet.
    Most applications should use this global registry rather than creating
    their own instances.
    
    Returns:
        Global ProcessorRegistry instance
        
    Example:
        >>> from processors.core.registry import get_global_registry
        >>> registry = get_global_registry()
        >>> registry.register(my_processor)
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = ProcessorRegistry()
        logger.info("Created global processor registry")
    return _global_registry


__all__ = [
    'ProcessorEntry',
    'ProcessorRegistry',
    'get_global_registry',
]
