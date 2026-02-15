"""ProcessorProtocol - Async interface for all processors.

This module defines the core protocol that all processors must implement to be
part of the unified processor system. It provides type-safe async interfaces and
standardized data structures for consistent processing across all input types.

Uses anyio for unified async/await support across different async backends.
"""

from __future__ import annotations

from typing import Protocol, Any, Dict, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

# anyio for unified async support
try:
    import anyio
    ANYIO_AVAILABLE = True
except ImportError:
    ANYIO_AVAILABLE = False
    anyio = None


class InputType(Enum):
    """Types of inputs that can be processed.
    
    This enum defines all possible input types that the system can handle.
    Used by InputDetector to classify inputs and by processors to declare
    what they can handle.
    """
    URL = "url"                    # HTTP/HTTPS URLs
    FILE = "file"                  # Local file paths
    FOLDER = "folder"              # Directory paths
    TEXT = "text"                  # Raw text content
    BINARY = "binary"              # Binary data
    IPFS_CID = "ipfs_cid"         # IPFS content identifiers
    IPNS = "ipns"                  # IPFS naming system
    
    @classmethod
    def from_string(cls, value: str) -> InputType:
        """Convert string to InputType enum.
        
        Args:
            value: String representation of input type
            
        Returns:
            InputType enum value
            
        Raises:
            ValueError: If value doesn't match any InputType
        """
        value_lower = value.lower()
        for input_type in cls:
            if input_type.value == value_lower:
                return input_type
        raise ValueError(f"Unknown input type: {value}")


@dataclass
class ProcessingContext:
    """Context information for processing operations.
    
    This dataclass encapsulates all the information needed to process an input,
    including the type, source, metadata, and options. It's passed to processors
    to help them decide if they can handle the input and how to process it.
    
    Attributes:
        input_type: Classification of the input (URL, file, folder, etc.)
        source: Original source (URL, file path, or content)
        metadata: Additional metadata about the input (format, size, mime type, etc.)
        options: Processing options and parameters
        session_id: Unique identifier for this processing session
        created_at: Timestamp when context was created
    """
    input_type: InputType
    source: Union[str, bytes, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    options: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    def get_format(self) -> Optional[str]:
        """Get the format/extension from metadata.
        
        Returns:
            Format string (e.g., 'pdf', 'mp4', 'html') or None
        """
        return self.metadata.get('format') or self.metadata.get('extension')
    
    def get_mime_type(self) -> Optional[str]:
        """Get MIME type from metadata.
        
        Returns:
            MIME type string or None
        """
        return self.metadata.get('mime_type')
    
    def is_url(self) -> bool:
        """Check if input is a URL."""
        return self.input_type in (InputType.URL, InputType.IPFS_CID, InputType.IPNS)
    
    def is_file(self) -> bool:
        """Check if input is a file."""
        return self.input_type == InputType.FILE
    
    def is_folder(self) -> bool:
        """Check if input is a folder."""
        return self.input_type == InputType.FOLDER


@dataclass
class ProcessingResult:
    """Standardized result from any processor.
    
    All processors must return this standardized format to ensure consistency
    across the system. The result includes a knowledge graph, vector embeddings,
    metadata, and any errors or warnings that occurred during processing.
    
    Attributes:
        success: Whether processing completed successfully
        knowledge_graph: Extracted entities, relationships, and properties
        vectors: Vector embeddings for semantic search
        metadata: Processing metadata (time, processor used, etc.)
        errors: List of error messages (if any)
        warnings: List of warning messages
        raw_output: Optional raw output from the processor
    """
    success: bool
    knowledge_graph: Dict[str, Any] = field(default_factory=dict)
    vectors: List[List[float]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    raw_output: Optional[Any] = None
    
    def has_knowledge_graph(self) -> bool:
        """Check if result contains a knowledge graph."""
        return bool(self.knowledge_graph.get('entities') or 
                   self.knowledge_graph.get('relationships'))
    
    def has_vectors(self) -> bool:
        """Check if result contains vector embeddings."""
        return len(self.vectors) > 0
    
    def get_entity_count(self) -> int:
        """Get number of entities in knowledge graph."""
        entities = self.knowledge_graph.get('entities', [])
        return len(entities) if isinstance(entities, list) else 0
    
    def get_relationship_count(self) -> int:
        """Get number of relationships in knowledge graph."""
        relationships = self.knowledge_graph.get('relationships', [])
        return len(relationships) if isinstance(relationships, list) else 0
    
    def add_error(self, error: str) -> None:
        """Add an error message to the result."""
        self.errors.append(error)
        if self.success and error:
            self.success = False
    
    def add_warning(self, warning: str) -> None:
        """Add a warning message to the result."""
        self.warnings.append(warning)
    
    def merge(self, other: ProcessingResult) -> None:
        """Merge another result into this one.
        
        Useful for combining results from multiple processors or sub-processors.
        
        Args:
            other: Another ProcessingResult to merge
        """
        # Merge knowledge graphs
        if other.knowledge_graph:
            kg = self.knowledge_graph
            other_kg = other.knowledge_graph
            
            # Merge entities
            if 'entities' in other_kg:
                if 'entities' not in kg:
                    kg['entities'] = []
                kg['entities'].extend(other_kg['entities'])
            
            # Merge relationships
            if 'relationships' in other_kg:
                if 'relationships' not in kg:
                    kg['relationships'] = []
                kg['relationships'].extend(other_kg['relationships'])
            
            # Merge properties
            if 'properties' in other_kg:
                if 'properties' not in kg:
                    kg['properties'] = {}
                kg['properties'].update(other_kg['properties'])
        
        # Merge vectors
        self.vectors.extend(other.vectors)
        
        # Merge metadata
        self.metadata.update(other.metadata)
        
        # Merge errors and warnings
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        
        # Update success status
        if not other.success:
            self.success = False


class ProcessorProtocol(Protocol):
    """Async protocol that all processors must implement.
    
    This is the core interface for the unified processor system. Any processor
    that wants to be part of the system must implement these three async methods.
    
    The protocol uses anyio for unified async support, allowing processors to work
    with asyncio, trio, or any other async backend.
    
    Example:
        >>> class MyProcessor:
        ...     async def can_handle(self, context: ProcessingContext) -> bool:
        ...         return context.get_format() == 'my_format'
        ...     
        ...     async def process(self, context: ProcessingContext) -> ProcessingResult:
        ...         # Processing logic here with anyio support
        ...         async with anyio.create_task_group() as tg:
        ...             result = await async_operation()
        ...         return ProcessingResult(success=True, ...)
        ...     
        ...     def get_capabilities(self) -> Dict[str, Any]:
        ...         return {
        ...             'name': 'MyProcessor',
        ...             'handles': ['my_format'],
        ...             'outputs': ['knowledge_graph', 'vectors']
        ...         }
    """
    
    async def can_handle(self, context: ProcessingContext) -> bool:
        """Async check if this processor can handle the given input.
        
        This method is called by the ProcessorRegistry to determine if this
        processor is suitable for the given input. Processors should examine
        the context (especially input_type, format, and metadata) to decide.
        
        Args:
            context: Processing context with input information
            
        Returns:
            True if this processor can handle the input, False otherwise
            
        Example:
            >>> async def can_handle(self, context: ProcessingContext) -> bool:
            ...     # Can do async checks if needed
            ...     return context.get_format() == 'pdf'
        """
        ...
    
    async def process(self, context: ProcessingContext) -> ProcessingResult:
        """Async process the input and return standardized result.
        
        This is the main processing method. It should:
        1. Extract/fetch the content from context.source (may be async I/O)
        2. Process the content (extract text, entities, etc.)
        3. Build a knowledge graph
        4. Generate vector embeddings
        5. Return a ProcessingResult with all outputs
        
        Uses anyio for unified async support:
        - Can use anyio.to_thread.run_sync() for CPU-bound work
        - Can use anyio.create_task_group() for concurrent tasks
        - Can use anyio.sleep() for delays
        
        Args:
            context: Processing context with input and options
            
        Returns:
            ProcessingResult with knowledge graph, vectors, and metadata
            
        Raises:
            ProcessorError: If processing fails
            
        Example:
            >>> def process(self, context: ProcessingContext) -> ProcessingResult:
            ...     try:
            ...         content = self._extract_content(context.source)
            ...         kg = self._build_knowledge_graph(content)
            ...         vectors = self._generate_vectors(content)
            ...         return ProcessingResult(
            ...             success=True,
            ...             knowledge_graph=kg,
            ...             vectors=vectors
            ...         )
            ...     except Exception as e:
            ...         return ProcessingResult(
            ...             success=False,
            ...             errors=[str(e)]
            ...         )
        """
        ...
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Return processor capabilities and metadata.
        
        This method returns information about what the processor can do,
        what formats it handles, what outputs it produces, and any other
        relevant metadata. This information is used by the registry for
        discovery and by users for understanding available processors.
        
        Returns:
            Dictionary with processor capabilities
            
        Expected keys:
            - name: Processor name
            - version: Processor version (optional)
            - handles: List of input types/formats handled
            - outputs: List of output types produced
            - priority: Priority for processor selection (optional, default: 50)
            - description: Human-readable description
            - features: List of special features (optional)
            
        Example:
            >>> def get_capabilities(self) -> Dict[str, Any]:
            ...     return {
            ...         'name': 'PDFProcessor',
            ...         'version': '1.0.0',
            ...         'handles': ['pdf', 'ps'],
            ...         'outputs': ['knowledge_graph', 'vectors', 'text'],
            ...         'priority': 40,
            ...         'description': 'Processes PDF documents with OCR support',
            ...         'features': ['ocr', 'table_extraction', 'image_extraction']
            ...     }
        """
        ...


# Type alias for convenience
Processor = ProcessorProtocol


def is_processor(obj: Any) -> bool:
    """Check if an object implements the async ProcessorProtocol.
    
    This utility function checks if an object has all the required methods
    to be considered a valid processor, including verifying that can_handle
    and process are async methods.
    
    Args:
        obj: Object to check
        
    Returns:
        True if object implements ProcessorProtocol (with async methods), False otherwise
        
    Example:
        >>> processor = MyProcessor()
        >>> if is_processor(processor):
        ...     result = await processor.process(context)
    """
    import inspect
    return (
        hasattr(obj, 'can_handle') and callable(obj.can_handle) and
        inspect.iscoroutinefunction(obj.can_handle) and
        hasattr(obj, 'process') and callable(obj.process) and
        inspect.iscoroutinefunction(obj.process) and
        hasattr(obj, 'get_capabilities') and callable(obj.get_capabilities)
    )
