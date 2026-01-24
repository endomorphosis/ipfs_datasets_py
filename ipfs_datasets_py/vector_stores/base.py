"""Base vector store interface for embeddings.

This module provides the abstract base class for vector store implementations,
defining the common interface for vector storage and retrieval operations.
"""
from abc import ABC, abstractmethod
import anyio
from typing import List, Dict, Any, Optional, Tuple, Union
import logging

from ..embeddings.schema import EmbeddingResult, SearchResult, VectorStoreConfig

logger = logging.getLogger(__name__)


class BaseVectorStore(ABC):
    """Abstract base class for vector store implementations."""
    
    def __init__(self, config: VectorStoreConfig):
        """Initialize the vector store with configuration.
        
        Args:
            config: Vector store configuration
        """
        self.config = config
        self.collection_name = config.collection_name
        self.dimension = config.dimension
        self.distance_metric = config.distance_metric
        self._client = None
    
    @property
    def client(self):
        """Get the underlying client connection."""
        if self._client is None:
            self._client = self._create_client()
        return self._client
    
    @abstractmethod
    def _create_client(self):
        """Create the underlying client connection."""
        pass
    
    @abstractmethod
    async def create_collection(self, collection_name: Optional[str] = None, 
                              dimension: Optional[int] = None, **kwargs) -> bool:
        """Create a new collection/index.
        
        Args:
            collection_name: Name of the collection to create
            dimension: Vector dimension
            **kwargs: Additional collection parameters
            
        Returns:
            True if collection was created successfully
        """
        pass
    
    @abstractmethod
    async def delete_collection(self, collection_name: Optional[str] = None) -> bool:
        """Delete a collection/index.
        
        Args:
            collection_name: Name of the collection to delete
            
        Returns:
            True if collection was deleted successfully
        """
        pass
    
    @abstractmethod
    async def collection_exists(self, collection_name: Optional[str] = None) -> bool:
        """Check if a collection exists.
        
        Args:
            collection_name: Name of the collection to check
            
        Returns:
            True if collection exists
        """
        pass
    
    @abstractmethod
    async def add_embeddings(self, embeddings: List[EmbeddingResult], 
                           collection_name: Optional[str] = None) -> List[str]:
        """Add embeddings to the vector store.
        
        Args:
            embeddings: List of embedding results to add
            collection_name: Target collection name
            
        Returns:
            List of IDs for the added embeddings
        """
        pass
    
    @abstractmethod
    async def search(self, query_vector: List[float], top_k: int = 10,
                    collection_name: Optional[str] = None,
                    filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """Search for similar vectors.
        
        Args:
            query_vector: Query vector to search for
            top_k: Number of results to return
            collection_name: Collection to search in
            filter_dict: Optional metadata filters
            
        Returns:
            List of search results
        """
        pass
    
    @abstractmethod
    async def get_by_id(self, embedding_id: str, 
                       collection_name: Optional[str] = None) -> Optional[EmbeddingResult]:
        """Retrieve an embedding by ID.
        
        Args:
            embedding_id: ID of the embedding to retrieve
            collection_name: Collection to search in
            
        Returns:
            Embedding result if found, None otherwise
        """
        pass
    
    @abstractmethod
    async def delete_by_id(self, embedding_id: str,
                          collection_name: Optional[str] = None) -> bool:
        """Delete an embedding by ID.
        
        Args:
            embedding_id: ID of the embedding to delete
            collection_name: Collection to delete from
            
        Returns:
            True if embedding was deleted successfully
        """
        pass
    
    @abstractmethod
    async def update_embedding(self, embedding_id: str, embedding: EmbeddingResult,
                             collection_name: Optional[str] = None) -> bool:
        """Update an existing embedding.
        
        Args:
            embedding_id: ID of the embedding to update
            embedding: New embedding data
            collection_name: Collection containing the embedding
            
        Returns:
            True if embedding was updated successfully
        """
        pass
    
    @abstractmethod
    async def get_collection_info(self, collection_name: Optional[str] = None) -> Dict[str, Any]:
        """Get information about a collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Dictionary with collection information
        """
        pass
    
    @abstractmethod
    async def list_collections(self) -> List[str]:
        """List all collections in the vector store.
        
        Returns:
            List of collection names
        """
        pass
    
    async def batch_add_embeddings(self, embeddings: List[EmbeddingResult],
                                  batch_size: int = 100,
                                  collection_name: Optional[str] = None) -> List[str]:
        """Add embeddings in batches.
        
        Args:
            embeddings: List of embedding results to add
            batch_size: Size of each batch
            collection_name: Target collection name
            
        Returns:
            List of IDs for all added embeddings
        """
        all_ids = []
        for i in range(0, len(embeddings), batch_size):
            batch = embeddings[i:i + batch_size]
            batch_ids = await self.add_embeddings(batch, collection_name)
            all_ids.extend(batch_ids)
        return all_ids
    
    async def similarity_search(self, query_vector: List[float], top_k: int = 10,
                               collection_name: Optional[str] = None,
                               score_threshold: Optional[float] = None,
                               filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """Search for similar vectors with optional score filtering.
        
        Args:
            query_vector: Query vector to search for
            top_k: Number of results to return
            collection_name: Collection to search in
            score_threshold: Minimum similarity score threshold
            filter_dict: Optional metadata filters
            
        Returns:
            List of search results above the score threshold
        """
        results = await self.search(query_vector, top_k, collection_name, filter_dict)
        
        if score_threshold is not None:
            results = [r for r in results if r.score >= score_threshold]
        
        return results
    
    async def close(self):
        """Close the vector store connection."""
        if self._client is not None:
            if hasattr(self._client, 'close'):
                await self._client.close()
            elif hasattr(self._client, 'disconnect'):
                await self._client.disconnect()
            self._client = None
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        # Note: This is sync, but close() is async
        # Subclasses should override if they need proper async cleanup
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.close())

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        return await self.close()


class VectorStoreError(Exception):
    """Base exception for vector store operations."""
    pass


class VectorStoreConnectionError(VectorStoreError):
    """Exception raised when connection to vector store fails."""
    pass


class VectorStoreOperationError(VectorStoreError):
    """Exception raised when a vector store operation fails."""
    pass


# Export public interface
__all__ = [
    'BaseVectorStore',
    'VectorStoreError',
    'VectorStoreConnectionError', 
    'VectorStoreOperationError'
]
