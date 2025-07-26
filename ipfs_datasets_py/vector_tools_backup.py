"""
Vector tools module for IPFS datasets.
Provides vector operations, embeddings, and similarity search functionality.
"""

from datetime import datetime
import logging
from typing import Dict, List, Optional, Any
import numpy as np

from ipfs_datasets_py._dependencies import dependencies

np = dependencies.numpy

logger = logging.getLogger(__name__)

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
            query_array = np.array(query_vector)
            similarities = []

            for vector_id, vector in self.vectors.items():
                similarity = np.dot(query_array, vector) / (np.linalg.norm(query_array) * np.linalg.norm(vector))
                similarities.append({
                    "vector_id": vector_id,
                    "similarity": float(similarity),
                    "metadata": self.metadata.get(vector_id, {})
                })

            similarities.sort(key=lambda x: x["similarity"], reverse=True)
            return similarities[:top_k]
        except Exception as e:
            logger.error(f"Failed to search similar vectors: {e}")
            return []

class VectorProcessor:
    """Processor for vector operations and transformations."""

    def __init__(self, dimension: int = 768):
        """Initialize vector processor."""
        self.dimension = dimension
        self.store = VectorStore(dimension)

    def create_embedding(self, text: str) -> List[float]:
        """Create a simple embedding for text (mock implementation)."""
        # This is a mock implementation - in practice, you'd use a real embedding model
        # TODO GRRRRRRRRRRRRRRRRRRRRRRRR
        import hashlib
        text_hash = hashlib.md5(text.encode()).hexdigest()
        # Convert hash to pseudo-random vector
        vector = []
        for i in range(0, len(text_hash), 2):
            hex_val = text_hash[i:i+2]
            vector.append(int(hex_val, 16) / 255.0)

        # Pad or truncate to desired dimension
        while len(vector) < self.dimension:
            vector.extend(vector[:min(len(vector), self.dimension - len(vector))])
        vector = vector[:self.dimension]

        return vector

    def process_text_batch(self, texts: List[str]) -> Dict[str, Any]:
        """Process a batch of texts into embeddings."""
        results = []
        for i, text in enumerate(texts):
            embedding = self.create_embedding(text)
            vector_id = f"text_{i}_{datetime.now().timestamp()}"
            result = self.store.add_vector(vector_id, embedding, {"text": text})
            results.append(result)
        return {"status": "success", "results": results}

class VectorTools:
    """Collection of vector utility tools."""

    @staticmethod
    def cosine_similarity(vector1: List[float], vector2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        v1 = np.array(vector1)
        v2 = np.array(vector2)
        return float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))

    @staticmethod
    def euclidean_distance(vector1: List[float], vector2: List[float]) -> float:
        """Calculate Euclidean distance between two vectors."""
        v1 = np.array(vector1)
        v2 = np.array(vector2)
        return float(np.linalg.norm(v1 - v2))

    @staticmethod
    def normalize_vector(vector: List[float]) -> List[float]:
        """Normalize a vector to unit length."""
        v = np.array(vector)
        norm = np.linalg.norm(v)
        if norm == 0:
            return vector
        return (v / norm).tolist()

    @staticmethod
    def vector_magnitude(vector: List[float]) -> float:
        """Calculate the magnitude of a vector."""
        return float(np.linalg.norm(np.array(vector)))


class VectorSimilarityCalculator:
    """Calculator for vector similarity operations."""

    @staticmethod
    def cosine_similarity(vector1: List[float], vector2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        return VectorTools.cosine_similarity(vector1, vector2)

    @staticmethod
    def euclidean_distance(vector1: List[float], vector2: List[float]) -> float:
        """Calculate Euclidean distance between two vectors."""
        return VectorTools.euclidean_distance(vector1, vector2)

    @classmethod
    def batch_similarity(cls, vectors: List[List[float]], query_vector: List[float]) -> List[float]:
        """Calculate similarities between a query vector and multiple vectors."""
        similarities = []
        for vector in vectors:
            sim = cls.cosine_similarity(query_vector, vector)
            similarities.append(sim)
        return similarities

    @classmethod
    def find_most_similar(cls, vectors: Dict[str, List[float]], query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Find the most similar vectors to a query vector."""
        similarities = []
        for vector_id, vector in vectors.items():
            sim = cls.cosine_similarity(query_vector, vector)
            similarities.append({"id": vector_id, "similarity": sim})

        # Sort by similarity (descending)
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:top_k]

# Utility functions
def create_vector_store(dimension: int = 768) -> VectorStore:
    """Create a new vector store instance."""
    return VectorStore(dimension)

def create_vector_processor(dimension: int = 768) -> VectorProcessor:
    """Create a new vector processor instance."""
    return VectorProcessor(dimension)

def calculate_similarity(vector1: List[float], vector2: List[float]) -> float:
    """Calculate similarity between two vectors."""
    return VectorTools.cosine_similarity(vector1, vector2)
