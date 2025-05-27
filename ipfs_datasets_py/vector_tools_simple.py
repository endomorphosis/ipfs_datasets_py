"""
Vector tools module for IPFS datasets.
Provides vector operations, embeddings, and similarity search functionality.
"""

import logging
from typing import Dict, List, Optional, Any, Union
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)

class VectorSimilarityCalculator:
    """Calculator for vector similarity operations."""
    
    def __init__(self):
        """Initialize the calculator."""
        pass
    
    def cosine_similarity(self, vector1: List[float], vector2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        try:
            v1 = np.array(vector1)
            v2 = np.array(vector2)
            dot_product = np.dot(v1, v2)
            magnitude1 = np.linalg.norm(v1)
            magnitude2 = np.linalg.norm(v2)
            
            if magnitude1 == 0 or magnitude2 == 0:
                return 0.0
            
            return float(dot_product / (magnitude1 * magnitude2))
        except Exception as e:
            logger.error(f"Cosine similarity calculation failed: {e}")
            return 0.0
    
    def euclidean_distance(self, vector1: List[float], vector2: List[float]) -> float:
        """Calculate Euclidean distance between two vectors."""
        try:
            v1 = np.array(vector1)
            v2 = np.array(vector2)
            return float(np.linalg.norm(v1 - v2))
        except Exception as e:
            logger.error(f"Euclidean distance calculation failed: {e}")
            return 0.0
    
    def batch_similarity(self, vectors: List[List[float]], query_vector: List[float]) -> List[float]:
        """Calculate similarities between a query vector and multiple vectors."""
        similarities = []
        for vector in vectors:
            sim = self.cosine_similarity(query_vector, vector)
            similarities.append(sim)
        return similarities
    
    def find_most_similar(self, vectors: Dict[str, List[float]], query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Find the most similar vectors to a query vector."""
        similarities = []
        for vector_id, vector in vectors.items():
            sim = self.cosine_similarity(query_vector, vector)
            similarities.append({"id": vector_id, "similarity": sim})
        
        # Sort by similarity (descending)
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:top_k]

class VectorStore:
    """Vector store for managing embeddings and similarity search."""
    
    def __init__(self, dimension: int = 768):
        """Initialize vector store with specified dimension."""
        self.dimension = dimension
        self.vectors = {}
        self.metadata = {}
        
    def add_vector(self, vector_id: str, vector: List[float], metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Add a vector to the store."""
        try:
            if len(vector) != self.dimension:
                return {"status": "error", "message": f"Vector dimension mismatch. Expected {self.dimension}, got {len(vector)}"}
            
            self.vectors[vector_id] = np.array(vector)
            self.metadata[vector_id] = metadata or {}
            return {"status": "success", "vector_id": vector_id}
        except Exception as e:
            logger.error(f"Failed to add vector {vector_id}: {e}")
            return {"status": "error", "message": str(e)}
    
    def search_similar(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Search for similar vectors."""
        try:
            calculator = VectorSimilarityCalculator()
            similarities = []
            
            for vector_id, vector in self.vectors.items():
                similarity = calculator.cosine_similarity(query_vector, vector.tolist())
                similarities.append({
                    "id": vector_id,
                    "similarity": similarity,
                    "metadata": self.metadata.get(vector_id, {})
                })
            
            # Sort by similarity (descending) and return top_k
            similarities.sort(key=lambda x: x["similarity"], reverse=True)
            return similarities[:top_k]
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []

# Utility functions
def create_vector_store(dimension: int = 768) -> VectorStore:
    """Create a new vector store instance."""
    return VectorStore(dimension)

def calculate_similarity(vector1: List[float], vector2: List[float]) -> float:
    """Calculate similarity between two vectors."""
    calculator = VectorSimilarityCalculator()
    return calculator.cosine_similarity(vector1, vector2)
