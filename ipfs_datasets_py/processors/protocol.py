"""
ProcessorProtocol - Base interface for all processors.

This module defines the core protocol that all processors must implement
to ensure consistency and enable automatic routing via UniversalProcessor.

All processors should implement ProcessorProtocol to be discoverable and
usable through the unified interface.
"""

from __future__ import annotations

from typing import Protocol, Union, Optional, Any, runtime_checkable
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Optional numpy import (for vector embeddings)
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None


class InputType(Enum):
    """Types of inputs that processors can handle."""
    URL = "url"
    FILE = "file"
    FOLDER = "folder"
    IPFS = "ipfs"
    TEXT = "text"
    BINARY = "binary"
    UNKNOWN = "unknown"


class ProcessingStatus(Enum):
    """Status of processing operation."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Entity:
    """
    Knowledge graph entity (node).
    
    Represents a single entity extracted from content, such as a Person,
    Organization, Location, Concept, etc.
    
    Attributes:
        id: Unique identifier for the entity
        type: Entity type (Person, Organization, Location, etc.)
        label: Human-readable label
        properties: Additional properties (attributes, metadata)
        embedding: Optional vector embedding for semantic search
        confidence: Confidence score (0.0-1.0)
    """
    id: str
    type: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)
    embedding: Optional[Any] = None  # np.ndarray when numpy available
    confidence: float = 1.0
    
    def __post_init__(self):
        """Validate entity fields."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")


@dataclass
class Relationship:
    """
    Knowledge graph relationship (edge).
    
    Represents a connection between two entities in the knowledge graph.
    
    Attributes:
        id: Unique identifier for the relationship
        source: Source entity ID
        target: Target entity ID
        type: Relationship type (e.g., "WORKS_FOR", "LOCATED_IN")
        properties: Additional edge properties
        confidence: Confidence score (0.0-1.0)
        bidirectional: Whether the relationship is bidirectional
    """
    id: str
    source: str
    target: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    bidirectional: bool = False
    
    def __post_init__(self):
        """Validate relationship fields."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Confidence must be between 0.0 and 1.0")


@dataclass
class KnowledgeGraph:
    """
    Standardized knowledge graph format.
    
    All processors must output knowledge graphs in this format to ensure
    consistency and interoperability.
    
    Attributes:
        entities: List of entities (nodes)
        relationships: List of relationships (edges)
        properties: Graph-level properties (metadata, statistics)
        source: Source document/URL that generated this graph
        created_at: When the graph was created
        schema_version: Version of the KG schema
    """
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    schema_version: str = "1.0"
    
    def add_entity(self, entity: Entity) -> None:
        """Add an entity to the graph."""
        self.entities.append(entity)
    
    def add_relationship(self, relationship: Relationship) -> None:
        """Add a relationship to the graph."""
        self.relationships.append(relationship)
    
    def find_entities(self, entity_type: Optional[str] = None) -> list[Entity]:
        """Find entities by type, or return all if type is None."""
        if entity_type is None:
            return self.entities
        return [e for e in self.entities if e.type == entity_type]
    
    def find_relationships(self, rel_type: Optional[str] = None) -> list[Relationship]:
        """Find relationships by type, or return all if type is None."""
        if rel_type is None:
            return self.relationships
        return [r for r in self.relationships if r.type == rel_type]
    
    def get_entity_by_id(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID."""
        for entity in self.entities:
            if entity.id == entity_id:
                return entity
        return None
    
    def get_related_entities(self, entity_id: str) -> list[tuple[Entity, Relationship]]:
        """
        Get all entities related to the given entity.
        
        Returns:
            List of (entity, relationship) tuples
        """
        related = []
        for rel in self.relationships:
            if rel.source == entity_id:
                target = self.get_entity_by_id(rel.target)
                if target:
                    related.append((target, rel))
            elif rel.target == entity_id and rel.bidirectional:
                source = self.get_entity_by_id(rel.source)
                if source:
                    related.append((source, rel))
        return related
    
    def to_dict(self) -> dict[str, Any]:
        """Convert knowledge graph to dictionary."""
        return {
            "entities": [
                {
                    "id": e.id,
                    "type": e.type,
                    "label": e.label,
                    "properties": e.properties,
                    "confidence": e.confidence
                }
                for e in self.entities
            ],
            "relationships": [
                {
                    "id": r.id,
                    "source": r.source,
                    "target": r.target,
                    "type": r.type,
                    "properties": r.properties,
                    "confidence": r.confidence,
                    "bidirectional": r.bidirectional
                }
                for r in self.relationships
            ],
            "properties": self.properties,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "schema_version": self.schema_version
        }


@dataclass
class VectorStore:
    """
    Vector embeddings for semantic search.
    
    Stores vector embeddings generated from content, enabling semantic
    similarity search and retrieval.
    
    Attributes:
        embeddings: Dictionary mapping content IDs to embeddings
        metadata: Metadata about the embedding model and parameters
        dimension: Dimensionality of embeddings
    """
    embeddings: dict[str, Any] = field(default_factory=dict)  # np.ndarray when numpy available
    metadata: dict[str, Any] = field(default_factory=dict)
    dimension: Optional[int] = None
    
    def add_embedding(self, content_id: str, embedding: Any) -> None:
        """Add an embedding to the store."""
        if self.dimension is None:
            self.dimension = len(embedding)
        elif len(embedding) != self.dimension:
            raise ValueError(f"Embedding dimension mismatch: expected {self.dimension}, got {len(embedding)}")
        self.embeddings[content_id] = embedding
    
    def get_embedding(self, content_id: str) -> Optional[Any]:
        """Get an embedding by content ID."""
        return self.embeddings.get(content_id)
    
    def search(self, query_embedding: Any, top_k: int = 10) -> list[tuple[str, float]]:
        """
        Search for similar embeddings using cosine similarity.
        
        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            
        Returns:
            List of (content_id, similarity_score) tuples
        """
        if not NUMPY_AVAILABLE:
            raise RuntimeError("Numpy is required for vector search. Install with: pip install numpy")
        
        if len(query_embedding) != self.dimension:
            raise ValueError(f"Query embedding dimension mismatch: expected {self.dimension}, got {len(query_embedding)}")
        
        similarities = []
        query_norm = np.linalg.norm(query_embedding)
        
        for content_id, embedding in self.embeddings.items():
            embedding_norm = np.linalg.norm(embedding)
            if query_norm == 0 or embedding_norm == 0:
                similarity = 0.0
            else:
                similarity = np.dot(query_embedding, embedding) / (query_norm * embedding_norm)
            similarities.append((content_id, float(similarity)))
        
        # Sort by similarity (descending) and return top_k
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]


@dataclass
class ProcessingMetadata:
    """
    Metadata about the processing operation.
    
    Tracks information about how content was processed, including timing,
    processor used, errors, and resource usage.
    
    Attributes:
        processor_name: Name of processor that handled the input
        processor_version: Version of the processor
        input_type: Type of input processed
        status: Processing status
        processing_time_seconds: Time taken to process
        errors: List of errors encountered
        warnings: List of warnings generated
        resource_usage: Resource usage statistics
    """
    processor_name: str
    processor_version: str = "1.0"
    input_type: InputType = InputType.UNKNOWN
    status: ProcessingStatus = ProcessingStatus.SUCCESS
    processing_time_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    resource_usage: dict[str, Any] = field(default_factory=dict)
    
    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)
        if self.status == ProcessingStatus.SUCCESS:
            self.status = ProcessingStatus.PARTIAL
    
    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)


@dataclass
class ProcessingResult:
    """
    Standardized output from all processors.
    
    All processors must return results in this format to ensure consistency
    and enable seamless integration with downstream systems.
    
    Attributes:
        knowledge_graph: Extracted knowledge graph (entities, relationships)
        vectors: Vector embeddings for semantic search
        content: Raw extracted content (text, metadata, structured data)
        metadata: Processing metadata (timing, errors, processor info)
        extra: Optional processor-specific additional data
    """
    knowledge_graph: KnowledgeGraph
    vectors: VectorStore
    content: dict[str, Any]
    metadata: ProcessingMetadata
    extra: Optional[dict[str, Any]] = None
    
    def __post_init__(self):
        """Initialize default values if needed."""
        if self.extra is None:
            self.extra = {}
    
    def is_successful(self) -> bool:
        """Check if processing was successful."""
        return self.metadata.status in (ProcessingStatus.SUCCESS, ProcessingStatus.PARTIAL)
    
    def has_errors(self) -> bool:
        """Check if processing had errors."""
        return len(self.metadata.errors) > 0
    
    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "knowledge_graph": self.knowledge_graph.to_dict(),
            "vectors": {
                "count": len(self.vectors.embeddings),
                "dimension": self.vectors.dimension,
                "metadata": self.vectors.metadata
            },
            "content": self.content,
            "metadata": {
                "processor_name": self.metadata.processor_name,
                "processor_version": self.metadata.processor_version,
                "input_type": self.metadata.input_type.value,
                "status": self.metadata.status.value,
                "processing_time_seconds": self.metadata.processing_time_seconds,
                "errors": self.metadata.errors,
                "warnings": self.metadata.warnings,
                "resource_usage": self.metadata.resource_usage
            },
            "extra": self.extra
        }


@runtime_checkable
class ProcessorProtocol(Protocol):
    """
    Protocol that all processors must implement.
    
    This protocol defines the interface for all processors in the system,
    enabling automatic discovery, routing, and consistent behavior.
    
    All processors should implement this protocol to be usable through
    the UniversalProcessor.
    
    Example:
        >>> class MyProcessor:
        ...     async def can_process(self, input_source):
        ...         return str(input_source).endswith('.myformat')
        ...     
        ...     async def process(self, input_source, **options):
        ...         # Process the input
        ...         kg = KnowledgeGraph(...)
        ...         vectors = VectorStore(...)
        ...         content = {...}
        ...         metadata = ProcessingMetadata(processor_name="MyProcessor")
        ...         return ProcessingResult(kg, vectors, content, metadata)
        ...     
        ...     def get_supported_types(self):
        ...         return ["myformat", "file"]
    """
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """
        Check if this processor can handle the given input.
        
        This method is called by the ProcessorRegistry to determine which
        processors are capable of handling a given input source.
        
        Args:
            input_source: Input to check (URL, file path, folder path, etc.)
            
        Returns:
            True if this processor can handle the input, False otherwise
        """
        ...
    
    async def process(
        self, 
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """
        Process the input and return standardized result.
        
        This is the main processing method that all processors must implement.
        It should:
        1. Read/download the input
        2. Extract content and metadata
        3. Build knowledge graph (entities, relationships)
        4. Generate vector embeddings
        5. Return ProcessingResult
        
        Args:
            input_source: Input to process (URL, file path, folder path, etc.)
            **options: Processor-specific options
            
        Returns:
            ProcessingResult with knowledge graph, vectors, content, and metadata
            
        Raises:
            Exception: If processing fails
        """
        ...
    
    def get_supported_types(self) -> list[str]:
        """
        Return list of supported input types.
        
        This method helps the ProcessorRegistry understand what types of
        inputs this processor can handle.
        
        Common types:
        - "url" - HTTP/HTTPS URLs
        - "file" - Local files
        - "folder" - Directories
        - "ipfs" - IPFS content IDs
        - "pdf" - PDF files specifically
        - "video" - Video files
        - "audio" - Audio files
        - "image" - Image files
        - etc.
        
        Returns:
            List of supported input type identifiers
        """
        ...
    
    def get_priority(self) -> int:
        """
        Get processor priority for selection when multiple processors can handle an input.
        
        Higher priority processors are preferred. Default is 0.
        
        Returns:
            Priority value (higher = more preferred)
        """
        return 0
    
    def get_name(self) -> str:
        """
        Get the name of this processor.
        
        Returns:
            Processor name
        """
        return self.__class__.__name__


# Type alias for convenience
ProcessorLike = Union[ProcessorProtocol, Any]
