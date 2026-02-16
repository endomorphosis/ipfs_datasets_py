"""Consolidated schema definitions for vector stores.

This module re-exports schemas from ml/embeddings/schema.py and adds
IPLD-specific extensions for content-addressed storage.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Re-export base schemas from ml/embeddings
try:
    from ..ml.embeddings.schema import (
        BaseComponent,
        DocumentChunk,
        Document,
        EmbeddingResult,
        SearchResult,
        ChunkingStrategy,
        VectorStoreType,
        EmbeddingConfig,
        VectorStoreConfig,
        ImageType,
        DEFAULT_TEXT_NODE_TMPL,
        DEFAULT_METADATA_TMPL,
        TRUNCATE_LENGTH,
        WRAP_WIDTH
    )
    
    _SCHEMAS_AVAILABLE = True
except ImportError:
    # Minimal fallback if schemas not available
    _SCHEMAS_AVAILABLE = False
    
    BaseComponent = object
    DocumentChunk = Dict
    Document = Dict
    ImageType = Any
    DEFAULT_TEXT_NODE_TMPL = "{metadata_str}\n\n{content}"
    DEFAULT_METADATA_TMPL = "{key}: {value}"
    TRUNCATE_LENGTH = 350
    WRAP_WIDTH = 70
    
    @dataclass
    class EmbeddingResult:
        """Fallback EmbeddingResult.

        This mirrors the interface of the real EmbeddingResult used throughout
        the codebase, exposing both ``chunk_id`` and ``content`` attributes,
        while remaining backwards compatible with the older fallback that used
        ``text`` instead of ``content`` and did not define ``chunk_id``.
        """
        vector: List[float]
        text: Optional[str] = None
        metadata: Optional[Dict[str, Any]] = None
        id: Optional[str] = None
        chunk_id: Optional[str] = None
        content: Optional[str] = None
    
    @dataclass  
    class SearchResult:
        """Fallback SearchResult."""
        id: str
        score: float
        metadata: Optional[Dict[str, Any]] = None
        content: Optional[str] = None


# IPLD-specific extensions

@dataclass
class IPLDEmbeddingResult(EmbeddingResult if _SCHEMAS_AVAILABLE else object):
    """Extended embedding result with IPLD metadata.
    
    Adds content-addressing information for IPLD storage.
    """
    cid: Optional[str] = None
    """Content Identifier (CID) for the embedding in IPLD"""
    
    vector_cid: Optional[str] = None
    """CID specifically for the vector data"""
    
    metadata_cid: Optional[str] = None
    """CID for the metadata block"""
    
    block_size: Optional[int] = None
    """Size of the IPLD block in bytes"""
    
    stored_at: Optional[str] = None
    """Timestamp of when the embedding was stored"""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with IPLD fields."""
        base_dict = super().to_dict() if hasattr(super(), 'to_dict') else {
            'text': self.text if hasattr(self, 'text') else None,
            'vector': self.vector if hasattr(self, 'vector') else None,
            'metadata': self.metadata if hasattr(self, 'metadata') else None,
            'id': self.id if hasattr(self, 'id') else None,
        }
        
        return {
            **base_dict,
            'cid': self.cid,
            'vector_cid': self.vector_cid,
            'metadata_cid': self.metadata_cid,
            'block_size': self.block_size,
            'stored_at': self.stored_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IPLDEmbeddingResult':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class IPLDSearchResult(SearchResult if _SCHEMAS_AVAILABLE else object):
    """Extended search result with IPLD metadata.
    
    Adds content-addressing information and retrieval metadata.
    """
    cid: Optional[str] = None
    """Content Identifier for the result"""
    
    retrieved_from: Optional[str] = None
    """IPFS gateway or node the result was retrieved from"""
    
    retrieval_time: Optional[float] = None
    """Time taken to retrieve from IPFS (seconds)"""
    
    block_size: Optional[int] = None
    """Size of the retrieved block"""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with IPLD fields."""
        base_dict = super().to_dict() if hasattr(super(), 'to_dict') else {
            'id': self.id if hasattr(self, 'id') else None,
            'score': self.score if hasattr(self, 'score') else 0.0,
            'metadata': self.metadata if hasattr(self, 'metadata') else None,
            'content': self.content if hasattr(self, 'content') else None,
        }
        
        return {
            **base_dict,
            'cid': self.cid,
            'retrieved_from': self.retrieved_from,
            'retrieval_time': self.retrieval_time,
            'block_size': self.block_size,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IPLDSearchResult':
        """Create from dictionary."""
        return cls(**data)


@dataclass
class CollectionMetadata:
    """Metadata for a vector collection.
    
    Used for storing collection information in IPLD.
    """
    name: str
    """Collection name"""
    
    dimension: int
    """Vector dimension"""
    
    metric: str
    """Distance metric used"""
    
    count: int
    """Number of vectors in collection"""
    
    created_at: str
    """ISO timestamp of creation"""
    
    updated_at: Optional[str] = None
    """ISO timestamp of last update"""
    
    root_cid: Optional[str] = None
    """Root CID for the collection in IPLD"""
    
    index_cid: Optional[str] = None
    """CID of the search index"""
    
    vectors_cid: Optional[str] = None
    """CID of the vectors container"""
    
    metadata_cid: Optional[str] = None
    """CID of the metadata mappings"""
    
    schema_version: str = "1.0"
    """Schema version for compatibility"""
    
    index_type: Optional[str] = None
    """Type of index used (e.g., 'FlatIP', 'IVFFlat')"""
    
    compression: bool = False
    """Whether compression is enabled"""
    
    chunked: bool = False
    """Whether vectors are chunked"""
    
    chunk_size: Optional[int] = None
    """Size of chunks if chunked"""
    
    total_blocks: Optional[int] = None
    """Total number of IPLD blocks"""
    
    total_size: Optional[int] = None
    """Total size in bytes"""
    
    custom_metadata: Optional[Dict[str, Any]] = None
    """Additional custom metadata"""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'dimension': self.dimension,
            'metric': self.metric,
            'count': self.count,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'root_cid': self.root_cid,
            'index_cid': self.index_cid,
            'vectors_cid': self.vectors_cid,
            'metadata_cid': self.metadata_cid,
            'schema_version': self.schema_version,
            'index_type': self.index_type,
            'compression': self.compression,
            'chunked': self.chunked,
            'chunk_size': self.chunk_size,
            'total_blocks': self.total_blocks,
            'total_size': self.total_size,
            'custom_metadata': self.custom_metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CollectionMetadata':
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


@dataclass
class VectorBlock:
    """Represents a block of vectors in IPLD storage.
    
    Used for chunking large collections.
    """
    block_id: int
    """Sequential block ID"""
    
    start_index: int
    """Starting vector index in this block"""
    
    end_index: int
    """Ending vector index in this block"""
    
    count: int
    """Number of vectors in this block"""
    
    cid: str
    """CID of this block"""
    
    size: int
    """Block size in bytes"""
    
    compressed: bool = False
    """Whether block is compressed"""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'block_id': self.block_id,
            'start_index': self.start_index,
            'end_index': self.end_index,
            'count': self.count,
            'cid': self.cid,
            'size': self.size,
            'compressed': self.compressed,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VectorBlock':
        """Create from dictionary."""
        return cls(**data)


# Export all symbols
__all__ = [
    # Re-exported from ml/embeddings
    'BaseComponent',
    'DocumentChunk',
    'Document',
    'EmbeddingResult',
    'SearchResult',
    'ChunkingStrategy',
    'VectorStoreType',
    'EmbeddingConfig',
    'VectorStoreConfig',
    'ImageType',
    'DEFAULT_TEXT_NODE_TMPL',
    'DEFAULT_METADATA_TMPL',
    'TRUNCATE_LENGTH',
    'WRAP_WIDTH',
    # IPLD extensions
    'IPLDEmbeddingResult',
    'IPLDSearchResult',
    'CollectionMetadata',
    'VectorBlock',
]
