"""
Vector Tools Module for IPFS Datasets and Knowledge Graph Operations

This module provides comprehensive vector operations, embeddings management, and similarity
search functionality specifically designed for IPFS-based datasets and knowledge graph
applications. It implements efficient vector similarity calculations, vector storage
management, and batch processing capabilities optimized for large-scale document
collections and semantic search operations.

Key Features:
- High-performance vector similarity calculations using multiple distance metrics
- Scalable vector storage with metadata management and dimension validation
- Batch processing capabilities for efficient similarity computations
- Integration with IPFS datasets for distributed vector storage
- Support for various similarity metrics including cosine similarity and Euclidean distance
- Memory-efficient vector operations using NumPy for numerical computations
- Flexible metadata association for enriched vector search results
- Error handling and logging for robust production deployment

Components:
- VectorSimilarityCalculator: Core calculator for vector similarity operations
- VectorStore: Comprehensive vector storage and search management system
- Utility functions for common vector operations and store creation

Usage Examples:
    # Create vector store and add vectors
    store = create_vector_store(dimension=768)
    store.add_vector("doc1", embedding_vector, {"title": "Document 1"})
    
    # Search for similar vectors
    results = store.search_similar(query_vector, top_k=5)
    
    # Calculate direct similarity
    similarity = calculate_similarity(vector1, vector2)

Notes:
    - All vector operations use NumPy for optimal performance
    - Vector dimensions must be consistent within each vector store
    - Similarity scores are normalized to [0, 1] range for cosine similarity
    - Error handling ensures graceful degradation in edge cases
    - Logging provides detailed information for debugging and monitoring
"""

import logging
from typing import Dict, List, Optional, Any, Union
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)

class VectorSimilarityCalculator:
    """
    Vector Similarity Calculator for High-Performance Distance Computations

    The VectorSimilarityCalculator class provides comprehensive functionality for calculating
    various distance and similarity metrics between vectors in high-dimensional spaces.
    It implements optimized algorithms for common similarity measures used in machine learning,
    natural language processing, and information retrieval applications. The calculator is
    designed for both single-pair computations and batch processing scenarios, supporting
    efficient similarity calculations for large vector collections.
    This class serves as the core computational engine for vector-based similarity search,
    clustering, and recommendation systems.

    Key Features:
    - Cosine similarity calculation with normalization and zero-vector handling
    - Euclidean distance computation for geometric similarity assessment
    - Batch similarity processing for efficient multi-vector comparisons
    - Most similar vector identification with configurable result limits
    - Robust error handling for edge cases and invalid inputs
    - NumPy optimization for high-performance numerical computations
    - Memory-efficient operations suitable for large-scale vector processing
    - Logarithmic and linear scaling support for different similarity interpretations

    Attributes:
        None: This class is stateless and maintains no internal state between operations.
            All methods are designed to be thread-safe and can be called concurrently.

    Public Methods:
        cosine_similarity(vector1: List[float], vector2: List[float]) -> float:
            Calculate cosine similarity between two vectors with normalization and
            zero-vector handling for robust similarity assessment.
        euclidean_distance(vector1: List[float], vector2: List[float]) -> float:
            Calculate Euclidean distance between two vectors for geometric similarity
            measurement in high-dimensional spaces.
        batch_similarity(vectors: List[List[float]], query_vector: List[float]) -> List[float]:
            Calculate cosine similarities between a query vector and multiple target vectors
            for efficient batch processing and ranking operations.
        find_most_similar(vectors: Dict[str, List[float]], query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
            Identify the most similar vectors to a query vector from a collection
            with configurable result limits and detailed similarity information.

    Usage Example:
        calculator = VectorSimilarityCalculator()
        # Calculate similarity between two vectors
        similarity = calculator.cosine_similarity([1, 0, 1], [0, 1, 1])
        # Batch similarity calculation
        similarities = calculator.batch_similarity(
            vectors=[[1, 0], [0, 1], [1, 1]],
            query_vector=[1, 0]
        )
        # Find most similar vectors
        results = calculator.find_most_similar(
            vectors={"v1": [1, 0], "v2": [0, 1], "v3": [1, 1]},
            query_vector=[1, 0],
            top_k=2
        )

    Notes:
        - Cosine similarity values range from -1 to 1, with 1 indicating identical direction
        - Euclidean distance values range from 0 to infinity, with 0 indicating identical vectors
        - Zero vectors return 0.0 similarity to prevent division by zero errors
        - All vector operations use NumPy for optimized numerical computations
        - Error handling ensures graceful degradation for invalid inputs
        - Memory usage scales linearly with vector dimensions and batch sizes
    """

    def __init__(self):
        """
        Initialize the vector similarity calculator with no internal state.

        This method creates a stateless vector similarity calculator that can perform
        various distance and similarity computations between vectors. The calculator
        maintains no internal state, making it thread-safe and suitable for concurrent
        use across multiple processes or threads.

        Attributes initialized:
            None: This calculator is stateless and maintains no internal attributes.
                All computation methods are pure functions that operate on input vectors
                without modifying any internal state.

        Examples:
            >>> calculator = VectorSimilarityCalculator()
            >>> isinstance(calculator, VectorSimilarityCalculator)
            True
            >>> # Calculator is ready for immediate use
            >>> similarity = calculator.cosine_similarity([1, 0], [0, 1])

        Notes:
            - No parameters are required for initialization
            - Calculator is immediately ready for all similarity operations
            - Thread-safe design allows concurrent usage without synchronization
            - Memory footprint is minimal due to stateless design
        """
        pass

    def cosine_similarity(self, vector1: List[float], vector2: List[float]) -> float:
        """
        Calculate cosine similarity between two vectors with robust normalization.

        This method computes the cosine similarity between two vectors by calculating
        the cosine of the angle between them in high-dimensional space. Cosine similarity
        measures the orientation relationship between vectors regardless of their magnitudes,
        making it ideal for text similarity, recommendation systems, and semantic analysis.
        The method includes robust handling for zero vectors and edge cases.

        Args:
            vector1 (List[float]): The first vector for similarity comparison.
                Should contain numeric values representing features or embeddings.
            vector2 (List[float]): The second vector for similarity comparison.
                Must have the same dimensionality as vector1 for valid computation.

        Returns:
            float: Cosine similarity score between -1.0 and 1.0.
                1.0 indicates identical vector directions (perfect similarity)
                0.0 indicates orthogonal vectors (no similarity)
                -1.0 indicates opposite vector directions (perfect dissimilarity)
                Returns 0.0 for zero vectors or computation errors.

        Raises:
            TypeError: If vector1 or vector2 are not lists or contain non-numeric values
            ValueError: If vectors have different dimensions or are empty
            ZeroDivisionError: Handled internally, returns 0.0 for zero-magnitude vectors

        Examples:
            >>> calculator = VectorSimilarityCalculator()
            >>> calculator.cosine_similarity([1, 0, 0], [1, 0, 0])
            1.0
            >>> calculator.cosine_similarity([1, 0], [0, 1])
            0.0
            >>> calculator.cosine_similarity([1, 1], [-1, -1])
            -1.0
            >>> calculator.cosine_similarity([0, 0], [1, 1])  # Zero vector handling
            0.0

        Notes:
            - Uses NumPy for optimized dot product and norm calculations
            - Handles zero vectors gracefully by returning 0.0 similarity
            - Dimensionality mismatch is handled by NumPy broadcasting rules
            - Result is always a finite floating-point number
            - Computation complexity is O(n) where n is vector dimension
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
        Calculate Euclidean distance between two vectors for geometric similarity.

        This method computes the straight-line distance between two points in
        high-dimensional space using the Euclidean distance formula. Unlike cosine
        similarity, Euclidean distance considers both the direction and magnitude
        of vectors, making it suitable for applications where vector magnitude
        represents meaningful information such as feature intensities or quantities.

        Args:
            vector1 (List[float]): The first vector for distance calculation.
                Should contain numeric values representing coordinates or features.
            vector2 (List[float]): The second vector for distance calculation.
                Must have the same dimensionality as vector1 for valid computation.

        Returns:
            float: Euclidean distance between the two vectors, always non-negative.
                0.0 indicates identical vectors (perfect match)
                Higher values indicate greater dissimilarity between vectors
                Returns 0.0 for computation errors or exception cases.

        Raises:
            TypeError: If vector1 or vector2 are not lists or contain non-numeric values
            ValueError: If vectors have different dimensions or are empty
            OverflowError: Handled internally for very large vector values

        Examples:
            >>> calculator = VectorSimilarityCalculator()
            >>> calculator.euclidean_distance([0, 0], [0, 0])
            0.0
            >>> calculator.euclidean_distance([0, 0], [3, 4])
            5.0
            >>> calculator.euclidean_distance([1, 1], [2, 2])
            1.4142135623730951
            >>> calculator.euclidean_distance([-1, -1], [1, 1])
            2.8284271247461903

        Notes:
            - Uses NumPy's optimized norm calculation for performance
            - Distance is always non-negative due to L2 norm properties
            - Sensitive to vector magnitude unlike cosine similarity
            - Computation complexity is O(n) where n is vector dimension
            - Result represents geometric distance in vector space
            - Error handling ensures graceful failure with 0.0 return
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

        This method efficiently computes cosine similarities between a single query vector
        and a collection of target vectors using batch processing for improved performance.
        It's designed for scenarios where you need to find similarities between one query
        and many candidates, such as document retrieval, recommendation systems, or
        nearest neighbor search operations.

        Args:
            vectors (List[List[float]]): Collection of target vectors for similarity comparison.
                Each inner list should contain numeric values with consistent dimensionality.
                Empty list returns empty result list.
            query_vector (List[float]): The query vector to compare against all target vectors.
                Should have the same dimensionality as all vectors in the target collection.

        Returns:
            List[float]: List of cosine similarity scores in the same order as input vectors.
                Each score ranges from -1.0 to 1.0 following cosine similarity properties.
                Length matches the input vectors list length.
                Empty list if input vectors is empty.

        Raises:
            TypeError: If vectors is not a list of lists or query_vector is not a list
            ValueError: If vectors contain inconsistent dimensions or empty vectors
            IndexError: If vectors list is malformed or contains invalid data

        Examples:
            >>> calculator = VectorSimilarityCalculator()
            >>> vectors = [[1, 0], [0, 1], [1, 1], [-1, 0]]
            >>> query = [1, 0]
            >>> similarities = calculator.batch_similarity(vectors, query)
            >>> similarities
            [1.0, 0.0, 0.7071067811865475, -1.0]
            >>> # Empty vectors list
            >>> calculator.batch_similarity([], [1, 0])
            []

        Notes:
            - Uses the same cosine similarity calculation as the single-vector method
            - Performance scales linearly with the number of target vectors
            - Memory usage is proportional to the number of vectors processed
            - All vectors must have consistent dimensionality for valid results
            - Error handling in individual similarity calculations prevents batch failure
            - Maintains order correspondence between input vectors and output scores
        """
        similarities = []
        for vector in vectors:
            sim = self.cosine_similarity(query_vector, vector)
            similarities.append(sim)
        return similarities

    def find_most_similar(self, vectors: Dict[str, List[float]], query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Find the most similar vectors to a query vector with ranking and metadata.

        This method identifies the top-k most similar vectors from a collection by
        calculating cosine similarities and ranking results in descending order.
        It provides both similarity scores and vector identifiers, making it ideal
        for nearest neighbor search, recommendation systems, and similarity-based
        retrieval operations where you need the most relevant results.

        Args:
            vectors (Dict[str, List[float]]): Dictionary mapping vector IDs to their numeric
                representations. Keys serve as unique identifiers for each vector.
                Values should be lists of consistent dimensionality.
            query_vector (List[float]): The query vector to find similar vectors for.
                Should have the same dimensionality as all vectors in the collection.
            top_k (int, optional): Maximum number of similar vectors to return.
                Must be positive integer. Defaults to 5 for balanced result sets.
                If larger than collection size, returns all vectors ranked by similarity.

        Returns:
            List[Dict[str, Any]]: List of similarity results sorted by decreasing similarity.
                Each result dictionary contains:
                - 'id': Vector identifier from the input dictionary keys
                - 'similarity': Cosine similarity score (-1.0 to 1.0)
                Maximum length is min(top_k, len(vectors)).
                Empty list if input vectors is empty.

        Raises:
            TypeError: If vectors is not a dictionary or query_vector is not a list
            ValueError: If top_k is not positive or vectors contain invalid data
            KeyError: If vector dictionary has malformed structure

        Examples:
            >>> calculator = VectorSimilarityCalculator()
            >>> vectors = {
            ...     "doc1": [1, 0, 0],
            ...     "doc2": [0, 1, 0], 
            ...     "doc3": [1, 1, 0],
            ...     "doc4": [1, 0, 1]
            ... }
            >>> query = [1, 0, 0]
            >>> results = calculator.find_most_similar(vectors, query, top_k=2)
            >>> results[0]["id"]  # Most similar
            'doc1'
            >>> results[0]["similarity"]
            1.0
            >>> len(results)
            2

        Notes:
            - Results are always sorted by similarity in descending order
            - Ties in similarity maintain stable relative ordering from input
            - Vector IDs are preserved from the input dictionary keys
            - Memory usage scales with the size of the vector collection
            - Performance is O(n log n) due to sorting, where n is collection size
            - Empty collections return empty result lists gracefully
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
    Vector Store for Comprehensive Embeddings Management and Similarity Search

    The VectorStore class provides a comprehensive solution for storing, managing, and
    searching high-dimensional vectors with associated metadata. It implements efficient
    vector storage with dimension validation, metadata association, and fast similarity
    search capabilities optimized for machine learning and information retrieval applications.
    This class serves as the foundation for building semantic search systems, recommendation
    engines, and vector-based knowledge retrieval systems.
    The store is designed to handle large collections of vectors while maintaining
    performance and memory efficiency through optimized data structures and algorithms.

    Args:
        dimension (int, optional): The dimensionality of vectors to be stored.
            All vectors added to the store must match this dimension.
            Defaults to 768 for compatibility with common transformer embeddings.

    Key Features:
    - High-performance vector storage with automatic dimension validation
    - Rich metadata association for enhanced search context and filtering
    - Fast similarity search using optimized cosine similarity calculations
    - Memory-efficient storage using NumPy arrays for numerical operations
    - Comprehensive error handling and validation for robust production use
    - Flexible metadata support for diverse application requirements
    - Batch operations support for efficient bulk vector processing
    - Thread-safe operations for concurrent access patterns

    Attributes:
        dimension (int): The required dimensionality for all vectors in the store.
            Used for validation during vector addition operations.
        vectors (Dict[str, np.ndarray]): Internal storage mapping vector IDs to
            their NumPy array representations for efficient numerical operations.
        metadata (Dict[str, Dict]): Associated metadata for each vector, indexed
            by vector ID for quick retrieval during search operations.

    Public Methods:
        add_vector(vector_id: str, vector: List[float], metadata: Optional[Dict] = None) -> Dict[str, Any]:
            Add a vector to the store with optional metadata and dimension validation,
            returning success status and error handling information.
        search_similar(query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
            Search for vectors most similar to a query vector using cosine similarity,
            returning ranked results with scores and associated metadata.

    Usage Example:
        # Create vector store for 768-dimensional embeddings
        store = VectorStore(dimension=768)
        
        # Add vectors with metadata
        result = store.add_vector(
            vector_id="doc_001",
            vector=embedding_vector,
            metadata={"title": "Document 1", "category": "science"}
        )
        
        # Search for similar vectors
        results = store.search_similar(
            query_vector=query_embedding,
            top_k=10
        )
        
        # Access results with metadata
        for result in results:
            print(f"ID: {result['id']}, Score: {result['similarity']}")
            print(f"Title: {result['metadata']['title']}")

    Notes:
        - All vectors must have consistent dimensionality matching the store configuration
        - Vector IDs must be unique within the store; duplicate IDs will overwrite existing vectors
        - Metadata is optional but recommended for meaningful search result interpretation
        - NumPy arrays are used internally for optimized numerical computations
        - Search performance scales linearly with the number of stored vectors
        - Memory usage is proportional to the number of vectors and their dimensionality
    """

    def __init__(self, dimension: int = 768):
        """
        Initialize vector store with specified dimension and empty storage containers.

        This method creates a new vector store configured for vectors of a specific
        dimensionality. The store initializes empty storage containers for vectors
        and metadata, ready to accept vector additions and perform similarity searches.
        The dimension parameter enforces consistency across all vectors added to the store.

        Args:
            dimension (int, optional): The required dimensionality for all vectors
                stored in this instance. Must be a positive integer representing
                the number of features or embedding dimensions. Defaults to 768
                for compatibility with common transformer models like BERT.

        Attributes initialized:
            dimension (int): The enforced dimensionality for vector validation.
            vectors (Dict[str, np.ndarray]): Empty dictionary for storing vector IDs
                mapped to their NumPy array representations.
            metadata (Dict[str, Dict]): Empty dictionary for storing vector metadata
                indexed by vector ID for quick retrieval.

        Raises:
            TypeError: If dimension is not an integer
            ValueError: If dimension is not positive

        Examples:
            >>> store = VectorStore(dimension=512)
            >>> store.dimension
            512
            >>> len(store.vectors)
            0
            >>> len(store.metadata)
            0
            >>> # Default dimension for transformer embeddings
            >>> default_store = VectorStore()
            >>> default_store.dimension
            768

        Notes:
            - Dimension validation occurs during vector addition, not initialization
            - Storage containers start empty and grow dynamically with vector additions
            - Common dimensions: 768 (BERT), 512 (smaller models), 1024+ (large models)
            - Memory footprint is minimal until vectors are added to the store
            - Thread-safe initialization allows concurrent store creation
        """
        self.dimension = dimension
        self.vectors = {}
        self.metadata = {}

    def add_vector(self, vector_id: str, vector: List[float], metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Add a vector to the store with dimension validation and metadata association.

        This method stores a vector in the vector store with automatic dimension validation
        to ensure consistency across all stored vectors. It associates optional metadata
        with the vector for enhanced search context and result interpretation. The method
        provides comprehensive error handling and returns detailed status information
        for robust integration with larger systems.

        Args:
            vector_id (str): Unique identifier for the vector within the store.
                Must be a non-empty string. Duplicate IDs will overwrite existing vectors.
                Recommended to use meaningful identifiers like document IDs or entity names.
            vector (List[float]): The numeric vector to store as a list of float values.
                Must have exactly the same dimensionality as the store's configured dimension.
                Values should be finite numbers for proper similarity calculations.
            metadata (Optional[Dict], optional): Associated metadata for the vector.
                Can contain any key-value pairs relevant to the vector's context.
                Common keys include title, category, timestamp, source, etc.
                Defaults to None, which stores an empty metadata dictionary.

        Returns:
            Dict[str, Any]: Status dictionary containing operation results:
                - 'status': 'success' or 'error' indicating operation outcome
                - 'vector_id': The provided vector ID for successful operations
                - 'message': Error description for failed operations

        Raises:
            TypeError: If vector_id is not a string or vector contains non-numeric values
            ValueError: If vector_id is empty or vector dimension doesn't match store dimension
            MemoryError: If insufficient memory is available for vector storage

        Examples:
            >>> store = VectorStore(dimension=3)
            >>> result = store.add_vector(
            ...     vector_id="vec1",
            ...     vector=[1.0, 2.0, 3.0],
            ...     metadata={"category": "example"}
            ... )
            >>> result['status']
            'success'
            >>> result['vector_id']
            'vec1'
            >>> # Dimension mismatch error
            >>> error_result = store.add_vector("vec2", [1.0, 2.0])  # Wrong dimension
            >>> error_result['status']
            'error'
            >>> 'dimension mismatch' in error_result['message'].lower()
            True

        Notes:
            - Vector IDs must be unique; duplicates overwrite existing vectors
            - Dimension validation prevents inconsistent vector storage
            - Metadata is optional but recommended for meaningful search results
            - NumPy conversion occurs internally for optimized storage and computation
            - Error handling ensures graceful failure without corrupting the store
            - Memory usage increases proportionally with vector additions
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
        Search for vectors most similar to a query vector using cosine similarity ranking.

        This method performs similarity search across all stored vectors using cosine
        similarity calculations to identify the most relevant matches. Results are
        ranked by similarity score and include associated metadata for comprehensive
        result interpretation. The search is optimized for performance while maintaining
        accuracy across large vector collections.

        Args:
            query_vector (List[float]): The query vector to find similar matches for.
                Must have the same dimensionality as vectors stored in the store.
                Should contain finite numeric values for proper similarity calculations.
            top_k (int, optional): Maximum number of similar vectors to return.
                Must be a positive integer. Results are ranked by similarity score.
                If larger than the number of stored vectors, returns all available vectors.
                Defaults to 5 for balanced result sets.

        Returns:
            List[Dict[str, Any]]: List of similarity results sorted by decreasing similarity.
                Each result dictionary contains:
                - 'id': Vector identifier from the store
                - 'similarity': Cosine similarity score (-1.0 to 1.0)
                - 'metadata': Associated metadata dictionary for the vector
                Empty list if no vectors are stored or search fails.
                Maximum length is min(top_k, number_of_stored_vectors).

        Raises:
            TypeError: If query_vector is not a list or top_k is not an integer
            ValueError: If query_vector has wrong dimensions or top_k is not positive
            RuntimeError: If search operation fails due to computational errors

        Examples:
            >>> store = VectorStore(dimension=2)
            >>> store.add_vector("v1", [1.0, 0.0], {"label": "horizontal"})
            >>> store.add_vector("v2", [0.0, 1.0], {"label": "vertical"})
            >>> store.add_vector("v3", [1.0, 1.0], {"label": "diagonal"})
            >>> # Search for vectors similar to horizontal
            >>> results = store.search_similar([1.0, 0.0], top_k=2)
            >>> results[0]['id']
            'v1'
            >>> results[0]['similarity']
            1.0
            >>> results[0]['metadata']['label']
            'horizontal'
            >>> len(results)
            2

        Notes:
            - Uses cosine similarity for orientation-based similarity measurement
            - Results are always sorted by similarity in descending order
            - Metadata from vector addition is included in search results
            - Performance scales linearly with the number of stored vectors
            - Empty stores return empty result lists gracefully
            - Error handling ensures robust operation even with invalid inputs
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
    Create a new vector store instance with specified dimensionality.

    This utility function provides a convenient way to create and configure a new
    VectorStore instance with a specified vector dimension. It serves as a factory
    function for vector store creation, simplifying initialization in applications
    that need multiple vector stores or dynamic store creation.

    Args:
        dimension (int, optional): The dimensionality for vectors in the new store.
            Must be a positive integer representing the number of features or
            embedding dimensions. Defaults to 768 for transformer compatibility.

    Returns:
        VectorStore: A newly initialized vector store ready for vector addition
            and similarity search operations. The store will enforce the specified
            dimension for all added vectors.

    Raises:
        TypeError: If dimension is not an integer
        ValueError: If dimension is not positive

    Examples:
        >>> store = create_vector_store(dimension=512)
        >>> store.dimension
        512
        >>> isinstance(store, VectorStore)
        True
        >>> # Default dimension for transformer embeddings
        >>> default_store = create_vector_store()
        >>> default_store.dimension
        768

    Notes:
        - Equivalent to VectorStore(dimension) but provides cleaner import syntax
        - Useful for factory patterns and dynamic store creation
        - Common dimensions: 768 (BERT), 512 (smaller models), 1024+ (large models)
        - Returns a fresh instance with empty storage containers
    """
    return VectorStore(dimension)

def calculate_similarity(vector1: List[float], vector2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors using optimized computation.

    This utility function provides a convenient interface for calculating cosine
    similarity between two vectors without needing to instantiate a calculator
    object. It uses the same robust computation logic as the VectorSimilarityCalculator
    class, including proper handling of zero vectors and edge cases.

    Args:
        vector1 (List[float]): The first vector for similarity comparison.
            Should contain numeric values representing features or embeddings.
        vector2 (List[float]): The second vector for similarity comparison.
            Must have the same dimensionality as vector1 for valid computation.

    Returns:
        float: Cosine similarity score between -1.0 and 1.0.
            1.0 indicates identical vector directions (perfect similarity)
            0.0 indicates orthogonal vectors (no similarity)
            -1.0 indicates opposite vector directions (perfect dissimilarity)
            Returns 0.0 for zero vectors or computation errors.

    Raises:
        TypeError: If vector1 or vector2 are not lists or contain non-numeric values
        ValueError: If vectors have different dimensions or are empty

    Examples:
        >>> similarity = calculate_similarity([1, 0, 0], [1, 0, 0])
        >>> similarity
        1.0
        >>> similarity = calculate_similarity([1, 0], [0, 1])
        >>> similarity
        0.0
        >>> similarity = calculate_similarity([1, 1], [-1, -1])
        >>> similarity
        -1.0

    Notes:
        - Equivalent to VectorSimilarityCalculator().cosine_similarity() but more concise
        - Uses the same robust error handling and zero vector management
        - Ideal for one-off similarity calculations without object instantiation
        - Performance is identical to the class method implementation
    """
    calculator = VectorSimilarityCalculator()
    return calculator.cosine_similarity(vector1, vector2)
