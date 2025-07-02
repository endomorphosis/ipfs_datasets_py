"""FAISS vector store implementation.

This module provides a FAISS-based vector store for embedding operations,
migrated and adapted from ipfs_embeddings_py.
"""

import logging
import os
import math
import pickle
import uuid
from typing import List, Dict, Any, Optional, Union
import json
import concurrent.futures
import multiprocessing

from .base import BaseVectorStore, VectorStoreError, VectorStoreConnectionError, VectorStoreOperationError
from ..embeddings.schema import EmbeddingResult, SearchResult, VectorStoreConfig, VectorStoreType


logger = logging.getLogger(__name__)

class MockFaissIndex:
    """Mock FAISS index for testing purposes."""

    def __init__(self, dimension: int):
        self.dimension = dimension
        self.ntotal = 0
        self.is_trained = True

    def Index(self):
        """Mock Index method."""
        return self

    def add(self, vectors):
        """Mock add method."""
        self.ntotal += len(vectors)

    def search(self, query_vector, top_k):
        """Mock search method."""
        return [[1.0] * top_k], [[i for i in range(top_k)]]

    def write_index(self, path):
        """Mock write index method."""
        pass
    
    def read_index(self, path):
        """Mock read index method."""
        return self


from typing import TypeAlias

# Check for FAISS and NumPy availability
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    logger.warning("FAISS not available. Using mock implementation.")
    #faiss: TypeAlias = MockFaissIndex
    FAISS_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    logger.warning("numpy not available. Using mock implementation.")
    np = None
    NUMPY_AVAILABLE = False

try:
    import datasets
    from datasets import Dataset, load_dataset, concatenate_datasets, load_from_disk
    DATASETS_AVAILABLE = True
except ImportError:
    logger.warning("datasets not available. Using mock implementation.")
    datasets = None
    Dataset = None
    load_dataset = None
    concatenate_datasets = None
    load_from_disk = None
    DATASETS_AVAILABLE = False


class FAISSVectorStore(BaseVectorStore):
    """FAISS vector store implementation."""
    
    def __init__(self, config: VectorStoreConfig):
        """Initialize FAISS vector store.
        
        Args:
            config: Vector store configuration
        """
        if not FAISS_AVAILABLE:
            raise VectorStoreError("FAISS not available. Install with: pip install faiss-cpu or faiss-gpu")

        if not NUMPY_AVAILABLE:
            raise VectorStoreError("NumPy not available. Install with: pip install numpy")

        super().__init__(config)
        self.index_path = config.connection_params.get("index_path", "./faiss_index")
        self.metadata_path = config.connection_params.get("metadata_path", "./faiss_metadata")
        self.index_type = config.connection_params.get("index_type", "Flat")

        # FAISS indices and metadata storage
        self.indices = {}
        self.metadata_store = {}
        self.id_mapping = {}  # Maps string IDs to FAISS internal indices
        self.reverse_id_mapping = {}  # Maps FAISS indices to string IDs

        # Legacy compatibility
        # TODO Find out if these are still needed
        self.search_chunks = self.search_chunks_legacy
        self.autofaiss_chunks = self.autofaiss_chunks_legacy
        self.search_centroids = self.search_centroids_legacy
        self.search_shards = self.search_shards_legacy
        self.autofaiss_shards = self.autofaiss_shards_legacy
        self.kmeans_cluster_split_dataset = self.kmeans_cluster_split_dataset_legacy
        self.chunk_cache = {}

    def _create_client(self):
        """Create FAISS client (actually just return None since FAISS is local)."""
        return None

    def _get_index_file_path(self, collection_name: str) -> str:
        """Get the file path for a FAISS index."""
        return os.path.join(self.index_path, f"{collection_name}.index")
    
    def _get_metadata_file_path(self, collection_name: str) -> str:
        """Get the file path for metadata storage."""
        return os.path.join(self.metadata_path, f"{collection_name}_metadata.pkl")
    
    def _create_index(self, dimension: int, index_type: str = "Flat") -> faiss.Index:
        """Create a FAISS index.

        Args:
            dimension: Vector dimension
            index_type: Type of FAISS index

        Returns:
            FAISS index object
        """
        match index_type:
            case "Flat":
                return faiss.IndexFlatIP(dimension)  # Inner product (cosine similarity)
            case "IVF":
                quantizer = faiss.IndexFlatIP(dimension)
                nlist = min(100, max(1, int(math.sqrt(1000))))  # Heuristic for nlist
                return faiss.IndexIVFFlat(quantizer, dimension, nlist)
            case "HNSW":
                return faiss.IndexHNSWFlat(dimension, 32)
            case _:
                logger.warning(f"Unknown index type {index_type}, using Flat")
                return faiss.IndexFlatIP(dimension)

    def _load_index(self, collection_name: str) -> Optional[faiss.Index]:
        """Load a FAISS index from disk."""
        index_path = self._get_index_file_path(collection_name)
        if os.path.exists(index_path):
            try:
                return faiss.read_index(index_path)
            except Exception as e:
                logger.error(f"Failed to load index {index_path}: {e}")
                return None
        return None
    
    def _save_index(self, collection_name: str, index: faiss.Index):
        """Save a FAISS index to disk."""
        os.makedirs(self.index_path, exist_ok=True)
        index_path = self._get_index_file_path(collection_name)
        try:
            faiss.write_index(index, index_path)
        except Exception as e:
            logger.error(f"Failed to save index {index_path}: {e}")
            raise VectorStoreOperationError(f"Failed to save index: {e}")
    
    def _load_metadata(self, collection_name: str) -> Dict[str, Any]:
        """Load metadata from disk."""
        metadata_path = self._get_metadata_file_path(collection_name)
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.error(f"Failed to load metadata {metadata_path}: {e}")
                return {}
        return {}
    
    def _save_metadata(self, collection_name: str, metadata: Dict[str, Any]):
        """Save metadata to disk."""
        os.makedirs(self.metadata_path, exist_ok=True)
        metadata_path = self._get_metadata_file_path(collection_name)
        try:
            with open(metadata_path, 'wb') as f:
                pickle.dump(metadata, f)
        except Exception as e:
            logger.error(f"Failed to save metadata {metadata_path}: {e}")
            raise VectorStoreOperationError(f"Failed to save metadata: {e}")
    
    async def create_collection(self, collection_name: Optional[str] = None, 
                              dimension: Optional[int] = None, **kwargs) -> bool:
        """Create a new FAISS collection.
        
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
        
        index_type = kwargs.get("index_type", self.index_type)
        
        try:
            index = self._create_index(dimension, index_type)
            self.indices[collection_name] = index
            self.metadata_store[collection_name] = {}
            self.id_mapping[collection_name] = {}
            self.reverse_id_mapping[collection_name] = {}
            
            # Save to disk
            self._save_index(collection_name, index)
            self._save_metadata(collection_name, {
                "dimension": dimension,
                "index_type": index_type,
                "metadata": {},
                "id_mapping": {},
                "reverse_id_mapping": {}
            })
            
            logger.info(f"Created FAISS collection: {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to create collection {collection_name}: {e}")
            raise VectorStoreOperationError(f"Failed to create collection: {e}")
    
    async def delete_collection(self, collection_name: Optional[str] = None) -> bool:
        """Delete a FAISS collection.
        
        Args:
            collection_name: Name of the collection to delete
            
        Returns:
            True if collection was deleted successfully
        """
        collection_name = collection_name or self.collection_name
        
        try:
            # Remove from memory
            if collection_name in self.indices:
                del self.indices[collection_name]
            if collection_name in self.metadata_store:
                del self.metadata_store[collection_name]
            if collection_name in self.id_mapping:
                del self.id_mapping[collection_name]
            if collection_name in self.reverse_id_mapping:
                del self.reverse_id_mapping[collection_name]
            
            # Remove files
            index_path = self._get_index_file_path(collection_name)
            metadata_path = self._get_metadata_file_path(collection_name)
            
            if os.path.exists(index_path):
                os.remove(index_path)
            if os.path.exists(metadata_path):
                os.remove(metadata_path)
            
            logger.info(f"Deleted FAISS collection: {collection_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete collection {collection_name}: {e}")
            raise VectorStoreOperationError(f"Failed to delete collection: {e}")
    
    async def collection_exists(self, collection_name: Optional[str] = None) -> bool:
        """Check if a FAISS collection exists.
        
        Args:
            collection_name: Name of the collection to check
            
        Returns:
            True if collection exists
        """
        collection_name = collection_name or self.collection_name
        
        # Check if in memory or on disk
        if collection_name in self.indices:
            return True
        
        index_path = self._get_index_file_path(collection_name)
        return os.path.exists(index_path)
    
    def _ensure_collection_loaded(self, collection_name: str):
        """Ensure a collection is loaded into memory."""
        if collection_name not in self.indices:
            index = self._load_index(collection_name)
            if index is None:
                raise VectorStoreError(f"Collection {collection_name} not found")
            
            metadata = self._load_metadata(collection_name)
            self.indices[collection_name] = index
            self.metadata_store[collection_name] = metadata.get("metadata", {})
            self.id_mapping[collection_name] = metadata.get("id_mapping", {})
            self.reverse_id_mapping[collection_name] = metadata.get("reverse_id_mapping", {})
    
    async def add_embeddings(self, embeddings: List[EmbeddingResult], 
                           collection_name: Optional[str] = None) -> List[str]:
        """Add embeddings to FAISS collection.
        
        Args:
            embeddings: List of embedding results to add
            collection_name: Target collection name
            
        Returns:
            List of IDs for the added embeddings
        """
        collection_name = collection_name or self.collection_name
        
        if not embeddings:
            return []
        
        # Ensure collection exists
        if not await self.collection_exists(collection_name):
            dimension = len(embeddings[0].embedding)
            await self.create_collection(collection_name, dimension)
        
        self._ensure_collection_loaded(collection_name)
        
        index = self.indices[collection_name]
        vectors = np.array([emb.embedding for emb in embeddings], dtype=np.float32)
        
        # Normalize vectors for cosine similarity
        faiss.normalize_L2(vectors)
        
        # Add to index
        start_id = index.ntotal
        index.add(vectors)
        
        # Store metadata and ID mapping
        point_ids = []
        for i, embedding in enumerate(embeddings):
            point_id = embedding.chunk_id or str(uuid.uuid4())
            point_ids.append(point_id)
            
            faiss_id = start_id + i
            self.id_mapping[collection_name][point_id] = faiss_id
            self.reverse_id_mapping[collection_name][faiss_id] = point_id
            
            self.metadata_store[collection_name][point_id] = {
                "content": embedding.content,
                "chunk_id": embedding.chunk_id,
                "model_name": embedding.model_name,
                "metadata": embedding.metadata or {}
            }
        
        # Save to disk
        self._save_index(collection_name, index)
        self._save_metadata(collection_name, {
            "metadata": self.metadata_store[collection_name],
            "id_mapping": self.id_mapping[collection_name],
            "reverse_id_mapping": self.reverse_id_mapping[collection_name]
        })
        
        logger.info(f"Added {len(embeddings)} embeddings to FAISS collection {collection_name}")
        return point_ids
    
    async def search(self, query_vector: List[float], top_k: int = 10,
                    collection_name: Optional[str] = None,
                    filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """Search for similar vectors in FAISS.
        
        Args:
            query_vector: Query vector to search for
            top_k: Number of results to return
            collection_name: Collection to search in
            filter_dict: Optional metadata filters (applied post-search)
            
        Returns:
            List of search results
        """
        collection_name = collection_name or self.collection_name
        
        if not await self.collection_exists(collection_name):
            return []
        
        self._ensure_collection_loaded(collection_name)
        
        index = self.indices[collection_name]
        query_array = np.array([query_vector], dtype=np.float32)
        faiss.normalize_L2(query_array)
        
        try:
            # Search in FAISS index
            scores, indices = index.search(query_array, min(top_k, index.ntotal))
            
            results = []
            for i, (score, idx) in enumerate(zip(scores[0], indices[0])):
                if idx == -1:  # FAISS returns -1 for invalid results
                    continue
                
                # Get point ID from FAISS index
                point_id = self.reverse_id_mapping[collection_name].get(idx)
                if not point_id:
                    continue
                
                # Get metadata
                metadata = self.metadata_store[collection_name].get(point_id, {})
                
                # Apply filter if specified
                if filter_dict:
                    item_metadata = metadata.get("metadata", {})
                    if not all(item_metadata.get(k) == v for k, v in filter_dict.items()):
                        continue
                
                result = SearchResult(
                    chunk_id=point_id,
                    content=metadata.get("content", ""),
                    score=float(score),
                    metadata=metadata.get("metadata", {}),
                    embedding=None  # Not returned for performance
                )
                results.append(result)
            
            return results[:top_k]  # Ensure we don't exceed requested count after filtering
        except Exception as e:
            logger.error(f"Failed to search in FAISS collection {collection_name}: {e}")
            raise VectorStoreOperationError(f"Failed to search: {e}")
    
    async def get_by_id(self, embedding_id: str, 
                       collection_name: Optional[str] = None) -> Optional[EmbeddingResult]:
        """Retrieve an embedding by ID from FAISS.
        
        Args:
            embedding_id: ID of the embedding to retrieve
            collection_name: Collection to search in
            
        Returns:
            Embedding result if found, None otherwise
        """
        collection_name = collection_name or self.collection_name
        
        if not await self.collection_exists(collection_name):
            return None
        
        self._ensure_collection_loaded(collection_name)
        
        metadata = self.metadata_store[collection_name].get(embedding_id)
        if not metadata:
            return None
        
        # FAISS doesn't store vectors in a way that's easy to retrieve by ID
        # For now, return without the embedding vector
        return EmbeddingResult(
            embedding=[],  # Would need reconstruction from index
            chunk_id=metadata.get("chunk_id", embedding_id),
            content=metadata.get("content", ""),
            metadata=metadata.get("metadata", {}),
            model_name=metadata.get("model_name")
        )
    
    async def delete_by_id(self, embedding_id: str,
                          collection_name: Optional[str] = None) -> bool:
        """Delete an embedding by ID from FAISS.
        
        Note: FAISS doesn't support efficient deletion. This marks the item as deleted
        in metadata but doesn't remove it from the index.
        
        Args:
            embedding_id: ID of the embedding to delete
            collection_name: Collection to delete from
            
        Returns:
            True if embedding was marked as deleted
        """
        collection_name = collection_name or self.collection_name
        
        if not await self.collection_exists(collection_name):
            return False
        
        self._ensure_collection_loaded(collection_name)
        
        try:
            if embedding_id in self.metadata_store[collection_name]:
                del self.metadata_store[collection_name][embedding_id]
                
                # Also remove from ID mappings
                faiss_id = self.id_mapping[collection_name].get(embedding_id)
                if faiss_id is not None:
                    del self.id_mapping[collection_name][embedding_id]
                    if faiss_id in self.reverse_id_mapping[collection_name]:
                        del self.reverse_id_mapping[collection_name][faiss_id]
                
                # Save metadata
                self._save_metadata(collection_name, {
                    "metadata": self.metadata_store[collection_name],
                    "id_mapping": self.id_mapping[collection_name],
                    "reverse_id_mapping": self.reverse_id_mapping[collection_name]
                })
                
                logger.info(f"Marked embedding {embedding_id} as deleted in {collection_name}")
                return True
            
            return False
        except Exception as e:
            logger.error(f"Failed to delete embedding {embedding_id} from {collection_name}: {e}")
            return False
    
    # Note: FAISS doesn't support efficient updates. This adds a new embedding
    # and marks the old one as deleted.

    async def update_embedding(self, embedding_id: str, embedding: EmbeddingResult,
                             collection_name: Optional[str] = None) -> bool:
        """Update an existing embedding in FAISS.

        Args:
            embedding_id: ID of the embedding to update
            embedding: New embedding data
            collection_name: Collection containing the embedding
            
        Returns:
            True if embedding was updated successfully
        """
        collection_name = collection_name or self.collection_name
        
        try:
            # Delete old embedding
            await self.delete_by_id(embedding_id, collection_name)
            
            # Add new embedding with same ID
            embedding.chunk_id = embedding_id
            await self.add_embeddings([embedding], collection_name)
            
            return True
        except Exception as e:
            logger.error(f"Failed to update embedding {embedding_id} in {collection_name}: {e}")
            return False
    
    async def get_collection_info(self, collection_name: Optional[str] = None) -> Dict[str, Any]:
        """Get information about a FAISS collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Dictionary with collection information
        """
        collection_name = collection_name or self.collection_name
        
        if not await self.collection_exists(collection_name):
            raise VectorStoreError(f"Collection {collection_name} not found")
        
        self._ensure_collection_loaded(collection_name)
        
        index = self.indices[collection_name]
        metadata_count = len(self.metadata_store[collection_name])
        
        return {
            "name": collection_name,
            "total_vectors": index.ntotal,
            "active_vectors": metadata_count,  # Excluding deleted items
            "dimension": index.d,
            "index_type": type(index).__name__,
            "is_trained": index.is_trained if hasattr(index, 'is_trained') else True
        }
    
    async def list_collections(self) -> List[str]:
        """List all FAISS collections.
        
        Returns:
            List of collection names
        """
        collections = set()
        
        # From memory
        collections.update(self.indices.keys())
        
        # From disk
        if os.path.exists(self.index_path):
            for filename in os.listdir(self.index_path):
                if filename.endswith('.index'):
                    collection_name = filename[:-6]  # Remove .index extension
                    collections.add(collection_name)
        
        return list(collections)
    
    # Legacy methods for backward compatibility
    async def search_chunks_legacy(self, dataset, split, src_path, model, cids, query, endpoint=None, n=64):
        """Legacy search chunks method."""
        logger.warning("search_chunks is a legacy method and may not work as expected")
        return []
    
    async def autofaiss_chunks_legacy(self, *args, **kwargs):
        """Legacy autofaiss chunks method."""
        logger.warning("autofaiss_chunks is a legacy method and may not work as expected")
        return []
    
    async def search_centroids_legacy(self, *args, **kwargs):
        """Legacy search centroids method."""
        logger.warning("search_centroids is a legacy method and may not work as expected")
        return []
    
    async def search_shards_legacy(self, *args, **kwargs):
        """Legacy search shards method."""
        logger.warning("search_shards is a legacy method and may not work as expected")
        return []
    
    async def autofaiss_shards_legacy(self, *args, **kwargs):
        """Legacy autofaiss shards method."""
        logger.warning("autofaiss_shards is a legacy method and may not work as expected")
        return []
    
    async def kmeans_cluster_split_dataset_legacy(self, *args, **kwargs):
        """Legacy kmeans cluster split dataset method."""
        logger.warning("kmeans_cluster_split_dataset is a legacy method and may not work as expected")
        return []


# Legacy alias for backward compatibility
faiss_kit_py = FAISSVectorStore

# Export public interface
__all__ = [
    'FAISSVectorStore',
    'faiss_kit_py'  # Legacy alias
]
