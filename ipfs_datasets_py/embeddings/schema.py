"""Schema definitions for embeddings and vector operations.

This module provides base classes and data structures for embedding operations,
migrated and adapted from ipfs_embeddings_py.
"""

import json
import logging
import pickle
import textwrap
import uuid
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from hashlib import sha256
from io import BytesIO
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

# try:
#     from dataclasses_json import DataClassJsonMixin
# except ImportError:
#     DataClassJsonMixin = object

from pydantic import (
    BaseModel, Field, ConfigDict, model_serializer,
    SerializeAsAny
)

try:
    from llama_index.core.bridge.pydantic_core import CoreSchema
    from llama_index.core.instrumentation import DispatcherSpanMixin
    from llama_index.core.utils import SAMPLE_TEXT, truncate_text
except ImportError:
    # Fallback to pydantic if llama_index is not available
    try:
        from pydantic import BaseModel, Field, ConfigDict, model_serializer
        GetJsonSchemaHandler = Any
        SerializeAsAny = Any
        DispatcherSpanMixin = object
        SAMPLE_TEXT = "This is a sample text."
        def truncate_text(text: str, length: int = 350) -> str:
            return text[:length] + "..." if len(text) > length else text
    except ImportError:
        # Final fallback - minimal implementation
        BaseModel = object
        Field = lambda *args, **kwargs: None
        ConfigDict = dict
        model_serializer = lambda *args, **kwargs: lambda x: x
        GetJsonSchemaHandler = Any
        SerializeAsAny = Any
        DispatcherSpanMixin = object
        SAMPLE_TEXT = "This is a sample text."
        def truncate_text(text: str, length: int = 350) -> str:
            return text[:length] + "..." if len(text) > length else text

from typing_extensions import Self

if TYPE_CHECKING:
    try:
        from haystack.schema import Document as HaystackDocument
        from llama_index.core.bridge.langchain import Document as LCDocument
        from semantic_kernel.memory.memory_record import MemoryRecord
        from llama_cloud.types.cloud_document import CloudDocument
    except ImportError:
        pass

DEFAULT_TEXT_NODE_TMPL = "{metadata_str}\n\n{content}"
DEFAULT_METADATA_TMPL = "{key}: {value}"
# NOTE: for pretty printing
TRUNCATE_LENGTH = 350
WRAP_WIDTH = 70

ImageType = Union[str, BytesIO]

logger = logging.getLogger(__name__)


class BaseComponent(BaseModel if BaseModel != object else object):
    """Base component object to capture class names."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    @classmethod
    def class_name(cls) -> str:
        """
        Get the class name, used as a unique ID in serialization.

        This provides a key that makes serialization robust against actual class
        name changes.
        """
        return cls.__name__.lower()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        if hasattr(self, 'model_dump'):
            return self.model_dump()
        elif hasattr(self, '__dict__'):
            return self.__dict__.copy()
        else:
            return {}

    def to_json(self, **kwargs: Any) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaseComponent':
        """Create instance from dictionary."""
        if hasattr(cls, 'model_validate'):
            return cls.model_validate(data)
        else:
            return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> 'BaseComponent':
        """Create instance from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


@dataclass
class DocumentChunk:
    """Represents a chunk of a document for embedding processing."""
    
    content: str
    chunk_id: str
    document_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    start_index: Optional[int] = None
    end_index: Optional[int] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.chunk_id is None:
            self.chunk_id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'content': self.content,
            'chunk_id': self.chunk_id,
            'document_id': self.document_id,
            'metadata': self.metadata,
            'start_index': self.start_index,
            'end_index': self.end_index
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DocumentChunk':
        """Create instance from dictionary."""
        return cls(**data)


@dataclass
class EmbeddingResult:
    """Represents the result of an embedding operation."""
    
    embedding: List[float]
    chunk_id: str
    content: str
    metadata: Optional[Dict[str, Any]] = None
    model_name: Optional[str] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'embedding': self.embedding,
            'chunk_id': self.chunk_id,
            'content': self.content,
            'metadata': self.metadata,
            'model_name': self.model_name
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EmbeddingResult':
        """Create instance from dictionary."""
        return cls(**data)


@dataclass
class SearchResult:
    """Represents a search result from vector similarity search."""
    
    chunk_id: str
    content: str
    score: float
    metadata: Optional[Dict[str, Any]] = None
    embedding: Optional[List[float]] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'chunk_id': self.chunk_id,
            'content': self.content,
            'score': self.score,
            'metadata': self.metadata,
            'embedding': self.embedding
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SearchResult':
        """Create instance from dictionary."""
        return cls(**data)


class ChunkingStrategy(Enum):
    """Supported chunking strategies."""
    SEMANTIC = "semantic"
    FIXED = "fixed"
    SENTENCES = "sentences"
    SLIDING_WINDOW = "sliding_window"


class VectorStoreType(Enum):
    """Supported vector store types."""
    QDRANT = "qdrant"
    FAISS = "faiss"
    ELASTICSEARCH = "elasticsearch"
    CHROMA = "chroma"


@dataclass
class EmbeddingConfig:
    """Configuration for embedding operations."""
    
    model_name: str
    chunk_size: int = 512
    chunk_overlap: int = 50
    chunking_strategy: ChunkingStrategy = ChunkingStrategy.SEMANTIC
    embedding_dim: Optional[int] = None
    batch_size: int = 32
    device: str = "cpu"
    normalize_embeddings: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'model_name': self.model_name,
            'chunk_size': self.chunk_size,
            'chunk_overlap': self.chunk_overlap,
            'chunking_strategy': self.chunking_strategy.value if isinstance(self.chunking_strategy, ChunkingStrategy) else self.chunking_strategy,
            'embedding_dim': self.embedding_dim,
            'batch_size': self.batch_size,
            'device': self.device,
            'normalize_embeddings': self.normalize_embeddings
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EmbeddingConfig':
        """Create instance from dictionary."""
        if 'chunking_strategy' in data and isinstance(data['chunking_strategy'], str):
            data['chunking_strategy'] = ChunkingStrategy(data['chunking_strategy'])
        return cls(**data)


@dataclass
class VectorStoreConfig:
    """Configuration for vector store operations."""
    
    store_type: VectorStoreType
    collection_name: str
    host: Optional[str] = None
    port: Optional[int] = None
    index_name: Optional[str] = None
    dimension: Optional[int] = None
    distance_metric: str = "cosine"
    connection_params: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.connection_params is None:
            self.connection_params = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'store_type': self.store_type.value if isinstance(self.store_type, VectorStoreType) else self.store_type,
            'collection_name': self.collection_name,
            'host': self.host,
            'port': self.port,
            'index_name': self.index_name,
            'dimension': self.dimension,
            'distance_metric': self.distance_metric,
            'connection_params': self.connection_params
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VectorStoreConfig':
        """Create instance from dictionary."""
        if 'store_type' in data and isinstance(data['store_type'], str):
            data['store_type'] = VectorStoreType(data['store_type'])
        return cls(**data)


# FastAPI Request/Response models for embedding API endpoints
class EmbeddingRequest(BaseModel):
    """Request model for embedding generation API."""
    
    texts: Union[str, List[str]] = Field(..., description="Text(s) to generate embeddings for")
    model_name: Optional[str] = Field(default=None, description="Model to use for embeddings")
    chunk_size: Optional[int] = Field(default=512, description="Chunk size for text processing")
    normalize: Optional[bool] = Field(default=True, description="Whether to normalize embeddings")
    batch_size: Optional[int] = Field(default=32, description="Batch size for processing")
    
    class Config:
        json_encoders = {
            # Handle any custom encoding if needed
        }


class EmbeddingResponse(BaseModel):
    """Response model for embedding generation API."""
    
    embeddings: List[List[float]] = Field(..., description="Generated embeddings")
    model_name: str = Field(..., description="Model used for generation")
    dimensions: int = Field(..., description="Embedding dimensions")
    texts_processed: int = Field(..., description="Number of texts processed")
    processing_time: Optional[float] = Field(default=None, description="Processing time in seconds")
    
    class Config:
        json_encoders = {
            # Handle any custom encoding if needed
        }


class EmbeddingModel:
    """Model information for available embedding models."""
    
    def __init__(self, name: str, dimensions: int, description: str = "", 
                 max_tokens: int = 8192, available: bool = True):
        self.name = name
        self.dimensions = dimensions
        self.description = description
        self.max_tokens = max_tokens
        self.available = available
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'dimensions': self.dimensions,
            'description': self.description,
            'max_tokens': self.max_tokens,
            'available': self.available
        }


# Compatibility aliases for integration with existing ipfs_embeddings_py code
Document = DocumentChunk  # Alias for backward compatibility

# Export all public classes and functions
__all__ = [
    'BaseComponent',
    'DocumentChunk', 
    'Document',
    'EmbeddingResult',
    'SearchResult',
    'ChunkingStrategy',
    'VectorStoreType',
    'EmbeddingConfig',
    'VectorStoreConfig',
    'EmbeddingRequest',
    'EmbeddingResponse', 
    'EmbeddingModel',
    'ImageType',
    'DEFAULT_TEXT_NODE_TMPL',
    'DEFAULT_METADATA_TMPL',
    'TRUNCATE_LENGTH',
    'WRAP_WIDTH'
]
