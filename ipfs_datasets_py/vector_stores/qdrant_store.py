"""Qdrant vector store implementation.

This module provides a Qdrant-based vector store for embedding operations,
migrated and adapted from ipfs_embeddings_py.
"""

import logging
import uuid
from typing import List, Dict, Any, Optional, TypeAlias, TypeVar
import asyncio
import json
import hashlib

from .base import BaseVectorStore, VectorStoreError, VectorStoreConnectionError, VectorStoreOperationError
from ..embeddings.schema import EmbeddingResult, SearchResult, VectorStoreConfig, VectorStoreType


class MockQuandrantClient:
    pass

QdrantClientType = TypeVar('QdrantClient')  # Type hint for QdrantClient

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models
    from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
    from qdrant_client.http.exceptions import UnexpectedResponse
    QDRANT_AVAILABLE = True
except ImportError:
    QdrantClient = None
    models = None
    Distance = None
    VectorParams = None
    PointStruct = None
    Filter = None
    FieldCondition = None
    MatchValue = None
    UnexpectedResponse = Exception
    QDRANT_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    pd = None
    PANDAS_AVAILABLE = False

try:
    import datasets
    DATASETS_AVAILABLE = True
except ImportError:
    datasets = None
    DATASETS_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    np = None
    NUMPY_AVAILABLE = False

logger = logging.getLogger(__name__)


class QdrantVectorStore(BaseVectorStore):
    """Qdrant vector store implementation."""
    
    def __init__(self, config: VectorStoreConfig):
        """Initialize Qdrant vector store.
        
        Args:
            config: Vector store configuration
        """
        if not QDRANT_AVAILABLE:
            raise VectorStoreError("Qdrant client not available. Install with: pip install qdrant-client")
        
        super().__init__(config)
        self.host = config.host or "localhost"
        self.port = config.port or 6333
        self.connection_params = config.connection_params or {}
        
        # Map distance metrics
        self.distance_map = {
            "cosine": Distance.COSINE,
            "euclidean": Distance.EUCLID,
            "dot": Distance.DOT,
            "manhattan": Distance.MANHATTAN,
        }

        # Legacy compatibility
        self.datasets = datasets if DATASETS_AVAILABLE else None
        self.chunk_cache = {}
        self.knn_index_hash = []
        self.datasets_hash = []

    def _create_client(self) -> QdrantClientType:
        """Create Qdrant client connection."""
        try:
            return QdrantClient(
                host=self.host,
                port=self.port,
                **self.connection_params
            )
        except Exception as e:
            raise VectorStoreConnectionError(f"Failed to connect to Qdrant: {e}")
    
    async def create_collection(self, collection_name: Optional[str] = None, 
                              dimension: Optional[int] = None, **kwargs) -> bool:
        """Create a new Qdrant collection.
        
        Args:
            collection_name: Name of the collection to create
            dimension: Vector dimension
            **kwargs: Additional collection parameters
            
        Returns:
            True if collection was created successfully
        """
        collection_name = collection_name or self.collection_name
        dimension = dimension or self.dimension
        
        if not dimension:
            raise VectorStoreError("Vector dimension must be specified")
        
        distance = self.distance_map.get(self.distance_metric.lower(), Distance.COSINE)
        
        try:
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=dimension, distance=distance),
                **kwargs
            )
            logger.info(f"Created Qdrant collection: {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to create collection {collection_name}: {e}")
            raise VectorStoreOperationError(f"Failed to create collection: {e}")
    
    async def delete_collection(self, collection_name: Optional[str] = None) -> bool:
        """Delete a Qdrant collection.
        
        Args:
            collection_name: Name of the collection to delete
            
        Returns:
            True if collection was deleted successfully
        """
        collection_name = collection_name or self.collection_name
        
        try:
            self.client.delete_collection(collection_name=collection_name)
            logger.info(f"Deleted Qdrant collection: {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete collection {collection_name}: {e}")
            raise VectorStoreOperationError(f"Failed to delete collection: {e}")
    
    async def collection_exists(self, collection_name: Optional[str] = None) -> bool:
        """Check if a Qdrant collection exists.
        
        Args:
            collection_name: Name of the collection to check
            
        Returns:
            True if collection exists
        """
        collection_name = collection_name or self.collection_name
        
        try:
            collections = self.client.get_collections()
            collection_names = [c.name for c in collections.collections]
            return collection_name in collection_names
        except Exception as e:
            logger.error(f"Failed to check collection existence {collection_name}: {e}")
            return False
    
    async def add_embeddings(self, embeddings: List[EmbeddingResult], 
                           collection_name: Optional[str] = None) -> List[str]:
        """Add embeddings to Qdrant collection.
        
        Args:
            embeddings: List of embedding results to add
            collection_name: Target collection name
            
        Returns:
            List of point IDs for the added embeddings
        """
        collection_name = collection_name or self.collection_name
        
        if not embeddings:
            return []
        
        # Ensure collection exists
        if not await self.collection_exists(collection_name):
            # Auto-create collection if it doesn't exist
            dimension = len(embeddings[0].embedding)
            await self.create_collection(collection_name, dimension)
        
        points = []
        point_ids = []
        
        for embedding in embeddings:
            point_id = embedding.chunk_id or str(uuid.uuid4())
            point_ids.append(point_id)
            
            # Prepare payload with metadata
            payload = {
                "content": embedding.content,
                "chunk_id": embedding.chunk_id,
                "model_name": embedding.model_name,
                **(embedding.metadata or {})
            }
            
            point = PointStruct(
                id=point_id,
                vector=embedding.embedding,
                payload=payload
            )
            points.append(point)
        
        try:
            self.client.upsert(
                collection_name=collection_name,
                points=points
            )
            logger.info(f"Added {len(points)} embeddings to collection {collection_name}")
            return point_ids
        except Exception as e:
            logger.error(f"Failed to add embeddings to {collection_name}: {e}")
            raise VectorStoreOperationError(f"Failed to add embeddings: {e}")
    
    async def search(self, query_vector: List[float], top_k: int = 10,
                    collection_name: Optional[str] = None,
                    filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """Search for similar vectors in Qdrant.
        
        Args:
            query_vector: Query vector to search for
            top_k: Number of results to return
            collection_name: Collection to search in
            filter_dict: Optional metadata filters
            
        Returns:
            List of search results
        """
        collection_name = collection_name or self.collection_name
        
        # Prepare filter if provided
        query_filter = None
        if filter_dict:
            conditions = []
            for key, value in filter_dict.items():
                condition = FieldCondition(
                    key=key,
                    match=MatchValue(value=value)
                )
                conditions.append(condition)
            
            if conditions:
                query_filter = Filter(must=conditions)
        
        try:
            search_result = self.client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False
            )
            
            results = []
            for point in search_result:
                payload = point.payload or {}
                result = SearchResult(
                    chunk_id=payload.get("chunk_id", str(point.id)),
                    content=payload.get("content", ""),
                    score=point.score,
                    metadata={k: v for k, v in payload.items() 
                             if k not in ["content", "chunk_id"]},
                    embedding=None  # Not returned by default for performance
                )
                results.append(result)
            
            return results
        except Exception as e:
            logger.error(f"Failed to search in collection {collection_name}: {e}")
            raise VectorStoreOperationError(f"Failed to search: {e}")
    
    async def get_by_id(self, embedding_id: str, 
                       collection_name: Optional[str] = None) -> Optional[EmbeddingResult]:
        """Retrieve an embedding by ID from Qdrant.
        
        Args:
            embedding_id: ID of the embedding to retrieve
            collection_name: Collection to search in
            
        Returns:
            Embedding result if found, None otherwise
        """
        collection_name = collection_name or self.collection_name
        
        try:
            result = self.client.retrieve(
                collection_name=collection_name,
                ids=[embedding_id],
                with_payload=True,
                with_vectors=True
            )
            
            if result:
                point = result[0]
                payload = point.payload or {}
                
                return EmbeddingResult(
                    embedding=point.vector,
                    chunk_id=payload.get("chunk_id", str(point.id)),
                    content=payload.get("content", ""),
                    metadata={k: v for k, v in payload.items() 
                             if k not in ["content", "chunk_id", "model_name"]},
                    model_name=payload.get("model_name")
                )
            
            return None
        except Exception as e:
            logger.error(f"Failed to get embedding {embedding_id} from {collection_name}: {e}")
            return None
    
    async def delete_by_id(self, embedding_id: str,
                          collection_name: Optional[str] = None) -> bool:
        """Delete an embedding by ID from Qdrant.
        
        Args:
            embedding_id: ID of the embedding to delete
            collection_name: Collection to delete from
            
        Returns:
            True if embedding was deleted successfully
        """
        collection_name = collection_name or self.collection_name
        
        try:
            self.client.delete(
                collection_name=collection_name,
                points_selector=[embedding_id]
            )
            logger.info(f"Deleted embedding {embedding_id} from {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete embedding {embedding_id} from {collection_name}: {e}")
            return False
    
    async def update_embedding(self, embedding_id: str, embedding: EmbeddingResult,
                             collection_name: Optional[str] = None) -> bool:
        """Update an existing embedding in Qdrant.
        
        Args:
            embedding_id: ID of the embedding to update
            embedding: New embedding data
            collection_name: Collection containing the embedding
            
        Returns:
            True if embedding was updated successfully
        """
        collection_name = collection_name or self.collection_name
        
        # Qdrant upsert handles both insert and update
        try:
            await self.add_embeddings([embedding], collection_name)
            return True
        except Exception as e:
            logger.error(f"Failed to update embedding {embedding_id} in {collection_name}: {e}")
            return False
    
    async def get_collection_info(self, collection_name: Optional[str] = None) -> Dict[str, Any]:
        """Get information about a Qdrant collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Dictionary with collection information
        """
        collection_name = collection_name or self.collection_name
        
        try:
            info = self.client.get_collection(collection_name=collection_name)
            return {
                "name": collection_name,
                "points_count": info.points_count,
                "segments_count": info.segments_count,
                "vector_size": info.config.params.vectors.size,
                "distance": info.config.params.vectors.distance.value,
                "status": info.status.value
            }
        except Exception as e:
            logger.error(f"Failed to get collection info for {collection_name}: {e}")
            raise VectorStoreOperationError(f"Failed to get collection info: {e}")
    
    async def list_collections(self) -> List[str]:
        """List all collections in Qdrant.
        
        Returns:
            List of collection names
        """
        try:
            collections = self.client.get_collections()
            return [c.name for c in collections.collections]
        except Exception as e:
            logger.error(f"Failed to list collections: {e}")
            raise VectorStoreOperationError(f"Failed to list collections: {e}")
    
    # Legacy methods for backward compatibility
    def hash_chunk(self, chunk: Dict[str, Any]) -> str:
        """Legacy method to hash a chunk."""
        hash_key = {column: chunk[column] for column in chunk}
        return hashlib.sha256(json.dumps(hash_key, sort_keys=True).encode()).hexdigest()
    
    async def join_datasets(self, dataset, knn_index, join_column):
        """Legacy method for joining datasets."""
        # This is a complex legacy method that would need significant refactoring
        # For now, provide a basic implementation
        logger.warning("join_datasets is a legacy method and may not work as expected")
        
        try:
            dataset_iter = iter(dataset)
            knn_index_iter = iter(knn_index)
            
            while True:
                try:
                    dataset_item = next(dataset_iter)
                    knn_index_item = next(knn_index_iter)
                    
                    results = {}
                    for key in dataset_item.keys():
                        results[key] = dataset_item[key]
                    
                    # Check if join columns match
                    same = True
                    for column in join_column:
                        if dataset_item.get(column) != knn_index_item.get(column):
                            same = False
                            break
                    
                    if same:
                        for key in knn_index_item.keys():
                            results[key] = knn_index_item[key]
                    
                    yield results
                    
                except StopIteration:
                    break
                except StopAsyncIteration:
                    break
        except Exception as e:
            logger.error(f"Error in join_datasets: {e}")
            return
    
    async def load_qdrant_iter(self, dataset, knn_index, dataset_split=None, knn_index_split=None):
        """Legacy method for loading Qdrant data."""
        logger.warning("load_qdrant_iter is a legacy method and may not work as expected")
        
        self.dataset_name = dataset
        self.knn_index_name = knn_index
        
        # This would need the datasets library and proper implementation
        # For now, provide a placeholder
        if not DATASETS_AVAILABLE:
            logger.error("datasets library not available for load_qdrant_iter")
            return
        
        # Basic implementation placeholder
        logger.info(f"Loading dataset: {dataset}, knn_index: {knn_index}")


# Legacy alias for backward compatibility
qdrant_kit_py = QdrantVectorStore

# Export public interface
__all__ = [
    'QdrantVectorStore',
    'qdrant_kit_py'  # Legacy alias
]
