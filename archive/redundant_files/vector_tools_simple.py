"""
Vector Tools Module for IPFS Datasets

This module provides comprehensive vector operations, embeddings, and similarity search
functionality for IPFS-based datasets. It implements efficient vector storage, similarity
calculations, and search capabilities optimized for content-addressable data structures.

The module includes:
- Vector similarity calculations using cosine similarity and Euclidean distance
- In-memory vector storage with metadata support
- Batch processing capabilities for multiple vector operations
- Similarity search with configurable top-k results
- Utility functions for common vector operations

Key Components:
- VectorSimilarityCalculator: Core similarity computation engine
- VectorStore: In-memory vector database with search capabilities
- Utility functions: Convenience methods for vector operations

This module is designed to work seamlessly with IPFS datasets, providing the foundation
for semantic search, content similarity analysis, and vector-based data retrieval.
"""

import logging
from typing import Dict, List, Optional, Any
import numpy as np


logger = logging.getLogger(__name__)


class VectorSimilarityCalculator:
    """
    Vector Similarity Calculator for Distance and Similarity Metrics

    The VectorSimilarityCalculator provides a comprehensive suite of mathematical functions
    for computing distances and similarities between high-dimensional vectors. It supports
    multiple similarity metrics and is optimized for performance with NumPy operations.
    This class serves as the core computational engine for vector-based operations in
    IPFS datasets, enabling semantic search and content similarity analysis.

    Key Features:
    - Cosine similarity computation for normalized vector comparisons
    - Euclidean distance calculation for geometric vector relationships
    - Batch processing capabilities for multiple vector comparisons
    - Most similar vector identification with ranking
    - Robust error handling and logging for production use
    - NumPy-optimized computations for performance

    Supported Metrics:
    - Cosine Similarity: Measures angular similarity between vectors (0-1 range)
    - Euclidean Distance: Measures geometric distance between vectors
    - Batch Similarity: Efficient computation for multiple vector pairs

    Attributes:
        None: This class is stateless and thread-safe

    Public Methods:
        cosine_similarity(vector1, vector2) -> float:
            Calculate cosine similarity between two vectors with values from -1 to 1,
            where 1 indicates identical direction, 0 indicates orthogonal vectors,
            and -1 indicates opposite direction.
        euclidean_distance(vector1, vector2) -> float:
            Calculate Euclidean distance between two vectors, returning the
            straight-line distance in n-dimensional space.
        batch_similarity(vectors, query_vector) -> List[float]:
            Calculate cosine similarities between a query vector and multiple
            target vectors efficiently using vectorized operations.
        find_most_similar(vectors, query_vector, top_k) -> List[Dict[str, Any]]:
            Find and rank the most similar vectors to a query vector,
            returning top-k results with similarity scores.

    Usage Example:
        calculator = VectorSimilarityCalculator()
        similarity = calculator.cosine_similarity([1, 2, 3], [4, 5, 6])
        distances = calculator.batch_similarity(vector_collection, query_vector)
        top_matches = calculator.find_most_similar(vector_dict, query, top_k=5)

    Notes:
        - All vector inputs should be List[float] or compatible numeric sequences
        - Zero-magnitude vectors return 0.0 similarity to prevent division by zero
        - Error handling ensures graceful degradation with logging for debugging
        - NumPy is used internally for optimized mathematical operations
    """

    def __init__(self):
        """
        Initialize the Vector Similarity Calculator.

        Creates a stateless calculator instance for performing vector similarity
        and distance computations. This class requires no configuration parameters
        and maintains no internal state, making it thread-safe and suitable for
        concurrent operations.

        Args:
            None

        Attributes initialized:
            None: This class is stateless and requires no attribute initialization

        Notes:
            - The calculator is immediately ready for use after instantiation
            - No memory allocation or resource initialization is required
            - Multiple instances can be created without performance overhead
            - Thread-safe design allows concurrent usage across multiple threads
        """
        pass

    def cosine_similarity(self, vector1: List[float], vector2: List[float]) -> float:
        """
        Calculate cosine similarity between two vectors using dot product normalization.

        Computes the cosine of the angle between two vectors in n-dimensional space,
        providing a measure of orientation similarity independent of magnitude.
        The result ranges from -1 (opposite direction) to 1 (identical direction),
        with 0 indicating orthogonal vectors. Returns 0.0 if an error occurs.

        Args:
            vector1 (List[float]): First vector for comparison. Must contain numeric values.
            vector2 (List[float]): Second vector for comparison. Must be same length as vector1.

        Returns:
            float: Cosine similarity score between -1.0 and 1.0.
                  - 1.0: Vectors point in identical direction
                  - 0.0: Vectors are orthogonal (perpendicular)
                  - -1.0: Vectors point in opposite directions
                  - 0.0: Returned if either vector has zero magnitude

        Examples:
            >>> calc = VectorSimilarityCalculator()
            >>> calc.cosine_similarity([1, 0], [1, 0])
            1.0
            >>> calc.cosine_similarity([1, 0], [0, 1])
            0.0
            >>> calc.cosine_similarity([1, 0], [-1, 0])
            -1.0
        """
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
        """
        Calculate Euclidean distance between two vectors in n-dimensional space.

        Computes the straight-line distance between two points represented as vectors. 
        This metric provides an absolute measure of separation between vectors, 
        with larger values indicating greater dissimilarity.

        Args:
            vector1 (List[float]): First vector point. Must contain numeric values.
            vector2 (List[float]): Second vector point. Must be same length as vector1.

        Returns:
            float: Euclidean distance as a non-negative value.
                  - 0.0: Vectors are identical
                  - Positive values: Degree of separation, with larger values indicating
                    greater distance between vectors

        Raises:
            Exception: Logs error and returns 0.0 for any computation failures including:
                      - Mismatched vector dimensions
                      - Invalid numeric values (NaN, infinity)
                      - Memory allocation errors
                      - NumPy computation errors

        Examples:
            >>> calc = VectorSimilarityCalculator()
            >>> calc.euclidean_distance([0, 0], [3, 4])
            5.0
            >>> calc.euclidean_distance([1, 2, 3], [1, 2, 3])
            0.0
            >>> calc.euclidean_distance([0, 0], [1, 1])
            1.4142135623730951
        """
        try:
            v1 = np.array(vector1)
            v2 = np.array(vector2)
            return float(np.linalg.norm(v1 - v2))
        except Exception as e:
            logger.error(f"Euclidean distance calculation failed: {e}")
            return 0.0

    def batch_similarity(self, vectors: List[List[float]], query_vector: List[float]) -> List[float]:
        """
        Calculate cosine similarities between a query vector and multiple target vectors.

        Efficiently computes similarities between one query vector and a collection of
        target vectors.

        Args:
            vectors (List[List[float]]): Collection of target vectors for comparison.
                                        Each vector must have the same dimensionality.
            query_vector (List[float]): Reference vector for similarity computation.
                                       Must have same dimensionality as target vectors.

        Returns:
            List[float]: List of cosine similarity scores in the same order as input vectors.
                        Each score ranges from -1.0 to 1.0, where:
                        - 1.0: Maximum similarity (identical direction)
                        - 0.0: No similarity (orthogonal vectors)
                        - -1.0: Maximum dissimilarity (opposite direction)

        Examples:
            >>> calc = VectorSimilarityCalculator()
            >>> vectors = [[1, 0], [0, 1], [1, 1]]
            >>> query = [1, 0]
            >>> calc.batch_similarity(vectors, query)
            [1.0, 0.0, 0.7071067811865475]
        """
        similarities = []
        for vector in vectors:
            sim = self.cosine_similarity(query_vector, vector)
            similarities.append(sim)
        return similarities

    def find_most_similar(self, vectors: Dict[str, List[float]], query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Find and rank the most similar vectors to a query vector with top-k results.

        Performs similarity search across a collection of named vectors, computing
        cosine similarities and returning the top-k most similar results ranked
        by similarity score. This method is essential for nearest neighbor search,
        recommendation systems, and content retrieval applications.

        Args:
            vectors (Dict[str, List[float]]): Named collection of vectors for search.
                                             Keys are vector identifiers, values are vector data.
            query_vector (List[float]): Reference vector for similarity computation.
                                       Must have compatible dimensionality with stored vectors.
            top_k (int, optional): Maximum number of results to return, ranked by similarity.
                                  Defaults to 5. Must be positive integer.

        Returns:
            List[Dict[str, Any]]: Ranked list of most similar vectors, each containing:
                                 - 'id' (str): Vector identifier from input dictionary
                                 - 'similarity' (float): Cosine similarity score (-1.0 to 1.0)
                                 Results are sorted by similarity in descending order.

        Examples:
            >>> calc = VectorSimilarityCalculator()
            >>> vectors = {'v1': [1, 0], 'v2': [0, 1], 'v3': [1, 1]}
            >>> query = [1, 0]
            >>> calc.find_most_similar(vectors, query, top_k=2)
            [{'id': 'v1', 'similarity': 1.0}, {'id': 'v3', 'similarity': 0.707}]
        """
        similarities = []
        for vector_id, vector in vectors.items():
            sim = self.cosine_similarity(query_vector, vector)
            similarities.append({"id": vector_id, "similarity": sim})

        # Sort by similarity (descending)
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:top_k]

class VectorStore:
    """
    In-Memory Vector Database for Embeddings and Similarity Search

    The VectorStore class provides a high-performance, in-memory vector database
    optimized for storing, managing, and searching high-dimensional embeddings.
    It supports metadata association, similarity search, and efficient vector
    operations for content-addressable data structures in IPFS environments.
    This class serves as the foundation for semantic search, content similarity
    analysis, and vector-based data retrieval operations.

    Args:
        dimension (int, optional): Fixed dimensionality for all stored vectors.
                                  All vectors must match this dimension for consistency.
                                  Defaults to 768 (common for transformer embeddings).

    Key Features:
    - Fixed-dimension vector storage with validation
    - Metadata association for rich vector annotations
    - Efficient similarity search using cosine similarity
    - In-memory storage optimized for fast retrieval
    - NumPy-based vector operations for performance
    - Comprehensive error handling and validation
    - Thread-safe operations for concurrent access

    Attributes:
        dimension (int): Fixed dimension requirement for all stored vectors
        vectors (Dict[str, np.ndarray]): Storage mapping vector IDs to NumPy arrays
        metadata (Dict[str, Dict]): Associated metadata for each stored vector

    Public Methods:
        add_vector(vector_id, vector, metadata) -> Dict[str, Any]:
            Store a vector with optional metadata, validating dimension compatibility
            and returning success/error status with detailed messages.
        search_similar(query_vector, top_k) -> List[Dict[str, Any]]:
            Perform similarity search against all stored vectors, returning
            top-k results ranked by cosine similarity with metadata.

    Storage Structure:
    - Vectors are stored as NumPy arrays for computational efficiency
    - Metadata is stored separately to allow flexible annotations
    - Vector IDs serve as unique identifiers across both storage dictionaries

    Usage Example:
        store = VectorStore(dimension=512)
        result = store.add_vector('doc1', embedding_vector, {'title': 'Document 1'})
        similar = store.search_similar(query_vector, top_k=5)
        for match in similar:
            print(f"ID: {match['id']}, Similarity: {match['similarity']:.3f}")

    Notes:
        - All vectors must have exactly the specified dimension
        - Dimension validation prevents inconsistent vector storage
        - In-memory storage provides fast access but is not persistent
        - Suitable for applications requiring real-time similarity search
        - Consider external persistence for large-scale deployments
        - NumPy arrays provide optimized mathematical operations
    """

    def __init__(self, dimension: int = 768):
        """
        Initialize the Vector Store with specified dimensional constraints.

        Creates an in-memory vector database configured for a fixed vector dimension.
        All subsequently stored vectors must match this dimension for consistency
        and compatibility with similarity search operations.

        Args:
            dimension (int, optional): Fixed dimensionality for all stored vectors.
                                     Must be a positive integer representing the number
                                     of components in each vector. Common values include:
                                     - 384: Sentence transformers (small models)
                                     - 512: Medium-sized embeddings
                                     - 768: BERT-base and similar models (default)
                                     - 1024: Large transformer models
                                     - 1536: OpenAI text embeddings
                                     Defaults to 768.

        Attributes initialized:
            dimension (int): Fixed dimension requirement enforced for all vectors
            vectors (Dict[str, np.ndarray]): Empty storage for vector data,
                                           mapping vector IDs to NumPy arrays
            metadata (Dict[str, Dict]): Empty storage for vector metadata,
                                      mapping vector IDs to metadata dictionaries
        """
        self.dimension = dimension
        self.vectors = {}
        self.metadata = {}

    def add_vector(self, vector_id: str, vector: List[float], metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Add a vector to the store with optional metadata and dimension validation.

        Stores a vector in the in-memory database after validating its dimensionality
        against the store's fixed dimension requirement. Existing vectors with the same
        ID will be overwritten.

        Args:
            vector_id (str): Unique identifier for the vector. Used for retrieval,
                           search results, and metadata association. Must be non-empty string.
            vector (List[float]): Numerical vector data to store. Must contain exactly
                                self.dimension elements. All elements should be finite numbers.
            metadata (Optional[Dict], optional): Additional information to associate with
                                               the vector (e.g., document title, source, tags).
                                               Can be any JSON-serializable dictionary.
                                               Defaults to empty dictionary if not provided.

        Returns:
            Dict[str, Any]: Operation result containing:
                          - 'status' (str): 'success' for successful storage, 'error' for failures
                          - 'vector_id' (str): Echo of the provided vector ID (success only)
                          - 'message' (str): Detailed error description (error only)

        Raises:
            Exception: Catches and handles all exceptions gracefully, returning error
                      status with descriptive messages. Common issues include:
                      - Dimension mismatches
                      - Invalid vector data types
                      - Memory allocation failures

        Examples:
            >>> store = VectorStore(dimension=3)
            >>> result = store.add_vector('vec1', [1.0, 2.0, 3.0], {'type': 'document'})
            >>> print(result)
            {'status': 'success', 'vector_id': 'vec1'}
            >>> bad_result = store.add_vector('vec2', [1.0, 2.0])  # Wrong dimension
            >>> print(bad_result['status'])
            'error'
        """
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
        """
        Search for vectors most similar to a query vector using cosine similarity.

        Performs similarity search across all stored vectors, computing cosine
        similarities and returning the top-k most similar results ranked by
        similarity score.

        Args:
            query_vector (List[float]): Reference vector for similarity computation.
                                       Must have the same dimensionality as stored vectors.
                                       Should contain finite numerical values.
            top_k (int, optional): Maximum number of similar vectors to return.
                                  Results are ranked by similarity in descending order.
                                  Must be positive integer. Defaults to 5.

        Returns:
            List[Dict[str, Any]]: Ranked list of most similar vectors, each containing:
                                - 'id' (str): Vector identifier from storage
                                - 'similarity' (float): Cosine similarity score (-1.0 to 1.0)
                                - 'metadata' (Dict): Associated metadata for the vector
                                Results are sorted by similarity in descending order.
                                Empty list returned if no vectors are stored or on error.

        Raises:
            Exception: Handles all computation errors gracefully, logging failures
                      and returning empty list. Common issues include:
                      - Dimension mismatches with stored vectors
                      - Invalid query vector data
                      - Similarity computation failures

        Examples:
            >>> store = VectorStore(dimension=2)
            >>> store.add_vector('v1', [1.0, 0.0], {'name': 'horizontal'})
            >>> store.add_vector('v2', [0.0, 1.0], {'name': 'vertical'})
            >>> results = store.search_similar([1.0, 0.1], top_k=1)
            >>> print(results[0]['id'], results[0]['similarity'])
            'v1' 0.995
        """
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
    """
    Create a new vector store instance with specified dimensional constraints.

    Convenience factory function for creating VectorStore instances with
    standardized configuration.

    Args:
        dimension (int, optional): Fixed dimensionality for all vectors in the store.
                                 Must be a positive integer. Common values:
                                 - 384: Small sentence transformer models
                                 - 512: Medium-sized embeddings
                                 - 768: BERT-base, default for many models
                                 - 1024: Large transformer models
                                 - 1536: OpenAI text embedding models
                                 Defaults to 768.

    Returns:
        VectorStore: Initialized vector store instance

    Examples:
        >>> store = create_vector_store(512)
        >>> result = store.add_vector('test', [0.1] * 512)
        >>> print(result['status'])
        'success'
        >>> store_default = create_vector_store()  # Uses 768 dimensions
        >>> print(store_default.dimension)
        768
    """
    return VectorStore(dimension)

def calculate_similarity(vector1: List[float], vector2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors using optimized computation.

    Convenience function that provides a simple interface for computing cosine
    similarity between two vectors without requiring explicit instantiation of
    the VectorSimilarityCalculator class.

    Args:
        vector1 (List[float]): First vector for similarity comparison.
                              Must contain numerical values and have same length as vector2.
        vector2 (List[float]): Second vector for similarity comparison.
                              Must contain numerical values and have same length as vector1.

    Returns:
        float: Cosine similarity score between -1.0 and 1.0, where:
              - 1.0: Vectors point in identical direction (maximum similarity)
              - 0.0: Vectors are orthogonal (no similarity)
              - -1.0: Vectors point in opposite directions (maximum dissimilarity)
              - 0.0: Returned for zero-magnitude vectors or computation errors

    Examples:
        >>> similarity = calculate_similarity([1, 0, 0], [1, 0, 0])
        >>> print(similarity)
        1.0
        >>> similarity = calculate_similarity([1, 1], [-1, -1])
        >>> print(similarity)
        -1.0
        >>> similarity = calculate_similarity([1, 0], [0, 1])
        >>> print(similarity)
        0.0
    """
    calculator = VectorSimilarityCalculator()
    return calculator.cosine_similarity(vector1, vector2)
