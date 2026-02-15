"""
Embeddings utilities for working with document embeddings.
Provides tools for creating, storing, and searching vector embeddings for documents.
"""
import os
from typing import Any, Callable, Optional, Union
import numpy as np

try:
    from pydantic import BaseModel
except ImportError:
    BaseModel = object

from types_ import Dependency
from logger import logger


class EmbeddingsInterface:
    """
    Manager for document embeddings.
    Handles storage, retrieval, and similarity search for document embeddings.
    """
    
    def __init__(
        self,
        resources: dict[str, Any] = None,
        configs: dict[str, Any] = None,
    ):
        """
        Initialize the embeddings manager with dependency injection.
        
        Args:
            resources: Dictionary of resources including embedding functions.
            configs: A pydantic model of configuration parameters.
        """
        self.resources = resources
        self.configs = configs

        self._numpy = self.resources["numpy"]
        self._duckdb = self.resources["duckdb"]

        # Extract required resources
        self.async_client = self.resources["async_client"]
        self.generate_embeddings_fn = self.resources["generate_embeddings"]
        
        # Initialize configuration
        self.embedding_dimensions = self.configs["embedding_dimensions"]
        self.embedding_model = self.configs["embedding_model"]
        self.cache_size = self.configs["cache_size"]
        
        # Initialize storage
        self._embedding_cache = {}
        
        logger.info(f"Initialized EmbeddingsInterface with dimensions: {self.embedding_dimensions}")

    def cosine_similarity(
        self, 
        vec1: list[float], 
        vec2: list[float]
    ) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            vec1: First vector
            vec2: Second vector
            
        Returns:
            Cosine similarity score (0-1)
        """

        # Convert to numpy arrays for efficient calculation
        vec1_array = np.array(vec1)
        vec2_array = np.array(vec2)
        
        # Calculate dot product and norms
        dot_product = np.dot(vec1_array, vec2_array)
        norm1 = np.linalg.norm(vec1_array)
        norm2 = np.linalg.norm(vec2_array)
        
        # Handle zero vectors
        if norm1 == 0 or norm2 == 0:
            return 0.0
            
        return float(dot_product / (norm1 * norm2))
    
    def store_embedding(
        self, 
        doc_id: str, 
        embedding: list[float], 
        metadata: Optional[dict[str, Any]] = None
    ) -> bool:
        """
        Store an embedding with optional metadata.
        
        Args:
            doc_id: Unique document identifier
            embedding: Embedding vector
            metadata: Optional metadata about the document
            
        Returns:
            True if stored successfully, False otherwise
        """
        try:
            # Check if we need to clear space in the cache
            if len(self._embedding_cache) >= self.cache_size:
                # Remove oldest entry (first key)
                oldest_key = next(iter(self._embedding_cache))
                del self._embedding_cache[oldest_key]
            
            # Store embedding with metadata
            self._embedding_cache[doc_id] = {
                "embedding": embedding,
                "metadata": metadata or {}
            }
            return True
        except Exception as e:
            logger.error(f"Error storing embedding: {e}")
            return False
    
    def get_embedding(self, doc_id: str) -> Optional[dict[str, Any]]:
        """
        Get a stored embedding by document ID.
        
        Args:
            doc_id: Document identifier
            
        Returns:
            Dictionary with embedding and metadata, or None if not found
        """
        return self._embedding_cache.get(doc_id)
    
    def search_similar(
        self, 
        query_embedding: list[float], 
        top_k: int = 5
    ) -> list[dict[str, Any]]:
        """
        Search for similar documents by embedding.
        
        Args:
            query_embedding: Query embedding vector
            top_k: Number of top results to return
            
        Returns:
            List of documents with similarity scores
        """
        results = []
        
        # Calculate similarity for each stored embedding
        for doc_id, entry in self._embedding_cache.items():
            similarity = self.cosine_similarity(query_embedding, entry["embedding"])
            
            results.append({
                "doc_id": doc_id,
                "similarity": similarity,
                "metadata": entry.get("metadata", {})
            })
        
        # Sort by similarity (highest first) and return top_k
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]
    
    def clear_cache(self) -> None:
        """
        Clear the embedding cache.
        """
        self._embedding_cache.clear()


