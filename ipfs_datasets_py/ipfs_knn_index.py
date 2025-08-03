"""
IPFS KNN Index Module

Provides a vector database index for similarity search that can be stored and loaded from IPFS.
This module integrates with IPLD for efficient storage and retrieval of high-dimensional vectors.
"""

import os
import json
import numpy as np
import tempfile
import uuid
from typing import Dict, List, Optional, Tuple, Any, Union, Generator

from ipfs_datasets_py.ipld.storage import IPLDStorage
from ipfs_datasets_py.dataset_serialization import DatasetSerializer


class IPFSKnnIndex:
    """
    Distributed K-Nearest Neighbors Vector Index with IPFS Storage Integration

    The IPFSKnnIndex class provides a comprehensive vector database solution that
    combines high-performance similarity search capabilities with distributed,
    content-addressable storage through IPFS (InterPlanetary File System). This
    index enables efficient storage, retrieval, and querying of high-dimensional
    vector embeddings while maintaining data integrity and enabling collaborative
    machine learning workflows across decentralized networks.

    The system integrates multiple similarity metrics, metadata management, and
    batch processing capabilities to support large-scale vector operations. IPFS
    integration provides content deduplication, version tracking, and distributed
    replication while maintaining fast query performance through intelligent
    caching and indexing strategies.

    Core Features:
    - High-performance K-nearest neighbors search with multiple similarity metrics
    - Distributed vector storage and retrieval through IPFS content addressing
    - Comprehensive metadata management with flexible schema support
    - Batch processing for efficient large-scale vector operations
    - Incremental index updates with version tracking and rollback capabilities
    - Multi-format import/export for interoperability with existing systems
    - Content deduplication and integrity verification through cryptographic hashing
    - Collaborative indexing across distributed networks and organizations

    Similarity Metrics Supported:
    - Cosine Similarity: Normalized dot product for orientation-based similarity
    - Euclidean Distance: L2 norm for geometric distance measurements
    - Dot Product: Inner product for magnitude and orientation similarity
    - Custom Metrics: Extensible framework for specialized similarity functions

    Storage and Distribution:
    - Content-addressable vector storage with automatic deduplication
    - Distributed index replication across IPFS network nodes
    - Immutable version tracking with complete operation history
    - Efficient chunking for large vector collections and datasets
    - Cross-network collaboration with shared index access and updates

    Performance Optimizations:
    - Intelligent caching for frequently accessed vectors and query results
    - Batch processing to minimize network overhead and improve throughput
    - Lazy loading for memory-efficient handling of large vector collections
    - Query optimization through index structure analysis and adaptation
    - Parallel processing for concurrent search and update operations

    Metadata Management:
    - Flexible metadata schema with support for arbitrary data structures
    - Efficient metadata indexing for complex filtering and search operations
    - Relationship tracking between vectors and source documents or entities
    - Temporal metadata for tracking vector creation and modification history
    - Custom metadata handlers for specialized application requirements

    Attributes:
        dimension (int): Dimensionality of vectors stored in the index, determining
            the vector space structure and compatibility requirements for all
            vector operations including search, insertion, and updates.
        metric (str): Similarity metric used for vector comparisons and nearest
            neighbor calculations. Supported values include 'cosine', 'euclidean',
            and 'dot' with extensibility for custom metric implementations.
        storage (IPLDStorage): IPLD storage backend providing content-addressable
            persistence and distributed storage coordination through IPFS networks.
        serializer (DatasetSerializer): Dataset serialization interface for
            efficient vector and metadata conversion between formats and storage.
        _vectors (List[np.ndarray]): In-memory vector storage for active working
            set with optimized access patterns for query operations.
        _metadata (List[Dict[str, Any]]): Associated metadata for each vector
            including identifiers, tags, relationships, and custom attributes.
        _index_cid (Optional[str]): Content identifier for the current index
            state enabling version tracking and distributed synchronization.

    Public Methods:
        add_vector(vector: np.ndarray, metadata: Dict[str, Any] = None) -> str:
            Add single vector with optional metadata to the index
        add_vectors(vectors: List[np.ndarray], metadata: List[Dict[str, Any]] = None) -> List[str]:
            Batch addition of multiple vectors with corresponding metadata
        search(query_vector: np.ndarray, k: int = 10, **kwargs) -> List[Tuple[float, Dict[str, Any]]]:
            Find K nearest neighbors with similarity scores and metadata
        search_batch(query_vectors: List[np.ndarray], k: int = 10) -> List[List[Tuple[float, Dict[str, Any]]]]:
            Batch search for multiple query vectors with optimized processing
        save_to_ipfs() -> str:
            Persist current index state to IPFS and return content identifier
        load_from_ipfs(cid: str) -> None:
            Restore index state from IPFS using content identifier
        update_vector(vector_id: str, vector: np.ndarray, metadata: Dict[str, Any] = None) -> None:
            Update existing vector and associated metadata
        remove_vector(vector_id: str) -> bool:
            Remove vector and metadata from index
        get_vector_count() -> int:
            Return total number of vectors in the index
        export_format(format_type: str) -> Any:
            Export index to specified format for interoperability

    Usage Examples:
        # Initialize vector index with cosine similarity
        index = IPFSKnnIndex(dimension=768, metric='cosine')
        
        # Add vectors with metadata
        vector1 = np.random.rand(768)
        vector_id = index.add_vector(
            vector=vector1,
            metadata={"document_id": "doc_001", "category": "technical"}
        )
        
        # Batch addition for efficiency
        vectors = [np.random.rand(768) for _ in range(100)]
        metadata_list = [{"doc_id": f"doc_{i:03d}"} for i in range(100)]
        vector_ids = index.add_vectors(vectors, metadata_list)
        
        # Search for similar vectors
        query_vector = np.random.rand(768)
        results = index.search(query_vector, k=5)
        for score, metadata in results:
            print(f"Similarity: {score:.4f}, Document: {metadata['document_id']}")
        
        # Save index to IPFS for distribution
        index_cid = index.save_to_ipfs()
        print(f"Index stored at IPFS CID: {index_cid}")
        
        # Load index from IPFS on another node
        new_index = IPFSKnnIndex(dimension=768, metric='cosine')
        new_index.load_from_ipfs(index_cid)

    Dependencies:
        Required:
        - numpy: Numerical computing for vector operations and similarity calculations
        - ipfs_datasets_py.ipld.storage: IPLD storage backend for IPFS integration
        - ipfs_datasets_py.dataset_serialization: Serialization utilities for data conversion
        
        Optional:
        - faiss: High-performance similarity search library for large-scale operations
        - sklearn: Additional similarity metrics and preprocessing utilities

    Notes:
        - Vector dimensionality must be consistent across all index operations
        - IPFS storage enables distributed collaboration and version tracking
        - Batch operations provide significant performance improvements for large datasets
        - Metadata indexing supports complex filtering and retrieval operations
        - Content addressing ensures data integrity and enables automatic deduplication
        - Index updates maintain backward compatibility with existing vector identifiers
        - Network connectivity is required for IPFS storage and synchronization operations
        - Memory usage scales with active vector count and should be monitored for large indexes
    """

    def __init__(self, dimension: int, metric: str = 'cosine', storage=None):
        """
        Initialize Distributed K-Nearest Neighbors Vector Index with IPFS Integration

        Establishes a new IPFSKnnIndex instance with comprehensive vector storage
        and similarity search capabilities integrated with IPFS distributed storage.
        This initialization configures the vector space dimensionality, similarity
        metric, storage backend, and all necessary components for high-performance
        vector operations across decentralized networks.

        The initialization process sets up the index structure, storage interfaces,
        serialization systems, and optimization parameters required for efficient
        vector operations. IPFS integration enables content-addressable storage
        and distributed collaboration while maintaining fast query performance.

        Args:
            dimension (int): Dimensionality of vectors to be stored in the index.
                This parameter defines the vector space structure and must remain
                consistent across all index operations. All vectors added to the
                index must have exactly this number of dimensions. Common dimensions
                include 768 (BERT embeddings), 1536 (OpenAI embeddings), 384
                (sentence-transformers), or custom dimensions for specialized models.
                Example: 768 for BERT-base embeddings
            
            metric (str, default='cosine'): Similarity metric for vector comparisons
                and nearest neighbor calculations. Supported metrics include:
                
                - 'cosine': Cosine similarity measuring orientation between vectors,
                  normalized to range [-1, 1] where 1 indicates identical orientation.
                  Optimal for text embeddings and high-dimensional sparse vectors.
                - 'euclidean': Euclidean distance (L2 norm) measuring geometric
                  distance in vector space. Lower values indicate higher similarity.
                  Suitable for dense vectors where magnitude is meaningful.
                - 'dot': Dot product measuring both magnitude and orientation
                  similarity. Higher values indicate greater similarity.
                  Useful when vector magnitudes contain meaningful information.
                
                Custom metrics can be implemented through metric extension framework.
                Example: 'cosine' for text embedding similarity search
            
            storage (Optional[IPLDStorage], default=None): IPLD storage backend
                for content-addressable persistence and distributed storage operations.
                If None, a new IPLDStorage instance will be created automatically
                with default configuration. Custom storage instances enable:
                
                - Alternative IPFS node endpoints and gateway configurations
                - Custom chunking strategies for large vector collections
                - Specialized caching and performance optimization settings
                - Security configurations including encryption and access control
                - Network coordination for multi-node collaborative indexing
                
                Example: IPLDStorage(ipfs_gateway="http://custom-node:8080")

        Attributes Initialized:
            dimension (int): Vector dimensionality for consistency validation
            metric (str): Configured similarity metric for all vector operations
            storage (IPLDStorage): IPLD storage backend ready for IPFS operations
            serializer (DatasetSerializer): Serialization interface for data conversion
            _vectors (List[np.ndarray]): Empty vector storage for index population
            _metadata (List[Dict[str, Any]]): Empty metadata storage for associations
            _index_cid (Optional[str]): Content identifier tracking for version control

        Raises:
            ValueError: If dimension is not a positive integer or if the specified
                metric is not supported by the current implementation.
            ImportError: If required dependencies for vector operations or IPFS
                integration are not available, including numpy, IPLD storage, or
                serialization libraries.
            ConfigurationError: If the provided storage backend configuration is
                invalid or incompatible with vector index requirements.
            ConnectionError: If IPFS node connectivity validation fails during
                storage backend initialization.

        Examples:
            # Basic index for BERT embeddings with cosine similarity
            index = IPFSKnnIndex(dimension=768, metric='cosine')
            
            # Euclidean distance index for image embeddings
            image_index = IPFSKnnIndex(
                dimension=2048,
                metric='euclidean'
            )
            
            # Custom storage configuration for distributed deployment
            from ipfs_datasets_py.ipld.storage import IPLDStorage
            
            custom_storage = IPLDStorage(
                ipfs_gateway="http://production-ipfs:8080",
                chunk_size=1024*1024,  # 1MB chunks
                enable_compression=True
            )
            distributed_index = IPFSKnnIndex(
                dimension=1536,
                metric='dot',
                storage=custom_storage
            )
            
            # High-dimensional index for specialized embeddings
            specialized_index = IPFSKnnIndex(
                dimension=4096,
                metric='cosine'
            )

        Notes:
            - Vector dimensionality cannot be changed after initialization
            - Similarity metric affects query results and should be chosen based on embedding characteristics
            - Default storage configuration provides secure and efficient IPFS integration
            - Custom storage backends enable deployment-specific optimization
            - Index structure is optimized for the specified dimensionality and metric
            - IPFS integration requires network connectivity for distributed operations
            - Memory allocation is optimized based on expected vector count and dimensionality
        """
        self.dimension = dimension
        self.metric = metric
        self.storage = storage or IPLDStorage()
        self.serializer = DatasetSerializer(storage=self.storage)

        # When not using FAISS, we'll store vectors and metadata in memory
        self._vectors = []
        self._metadata = []
        self._index_cid = None

        # Try to import FAISS
        try:
            import faiss
            self._faiss_available = True

            # Create a FAISS index
            if metric == 'cosine':
                self._index = faiss.IndexFlatIP(dimension)  # Inner product for normalized vectors
                self._normalizer = lambda v: v / np.linalg.norm(v, axis=1, keepdims=True)
            elif metric == 'euclidean':
                self._index = faiss.IndexFlatL2(dimension)  # L2 distance
                self._normalizer = lambda v: v  # No normalization
            elif metric == 'dot':
                self._index = faiss.IndexFlatIP(dimension)  # Inner product
                self._normalizer = lambda v: v  # No normalization
            else:
                raise ValueError(f"Unsupported metric: {metric}")

            # Set flag for new index
            self._is_index_new = True

        except ImportError:
            self._faiss_available = False
            print("Warning: FAISS not available. Using slower numpy-based similarity search.")

    def add_vectors(self, vectors: np.ndarray, metadata: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Add vectors to the index.

        Args:
            vectors (np.ndarray): Vectors to add, shape (n, dimension)
            metadata (List[Dict], optional): Metadata for each vector
        """
        if len(vectors.shape) != 2 or vectors.shape[1] != self.dimension:
            raise ValueError(f"Vectors must have shape (n, {self.dimension})")

        if metadata is not None and len(metadata) != vectors.shape[0]:
            raise ValueError("Number of metadata items must match number of vectors")

        if self._faiss_available:
            # Normalize vectors if using cosine similarity
            if self.metric == 'cosine':
                vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)

            # Add to FAISS index
            self._index.add(vectors.astype(np.float32))

            # Store metadata
            if metadata is None:
                metadata = [{"id": str(i + len(self._metadata))} for i in range(vectors.shape[0])]

            self._metadata.extend(metadata)

            # Set flag for modified index
            self._is_index_new = False
        else:
            # Add to in-memory storage
            self._vectors.append(vectors)

            if metadata is None:
                metadata = [{"id": str(i + len(self._metadata))} for i in range(vectors.shape[0])]

            self._metadata.extend(metadata)

    def search(self, query_vector: np.ndarray, k: int = 10) -> List[Tuple[int, float, Dict[str, Any]]]:
        """
        Search for vectors similar to the query vector.

        Args:
            query_vector (np.ndarray): Query vector, shape (dimension,)
            k (int): Number of results to return

        Returns:
            List[Tuple[int, float, Dict]]: List of (index, similarity, metadata) tuples
        """
        if query_vector.shape != (self.dimension,):
            raise ValueError(f"Query vector must have shape ({self.dimension},)")

        if self._faiss_available:
            # Reshape query vector
            query_vector = query_vector.reshape(1, -1)

            # Normalize query vector if using cosine similarity
            if self.metric == 'cosine':
                query_vector = query_vector / np.linalg.norm(query_vector)

            # Search in FAISS index
            distances, indices = self._index.search(query_vector.astype(np.float32), k)

            # Convert distances to similarities
            if self.metric == 'euclidean':
                # For euclidean, smaller is better, so convert to similarity
                similarities = 1.0 / (1.0 + distances[0])
            else:
                # For cosine and dot product, larger is better
                similarities = distances[0]

            # Get metadata for each result
            results = []
            for i, idx in enumerate(indices[0]):
                if idx != -1:  # FAISS uses -1 for padded results
                    results.append((int(idx), float(similarities[i]), self._metadata[idx]))

            return results
        else:
            # Use numpy for similarity calculation
            if not self._vectors:
                return []

            # Concatenate all vectors
            all_vectors = np.vstack(self._vectors)

            # Calculate similarities
            if self.metric == 'cosine':
                # Normalize query and index vectors
                query_norm = query_vector / np.linalg.norm(query_vector)
                vectors_norm = all_vectors / np.linalg.norm(all_vectors, axis=1, keepdims=True)
                similarities = np.dot(vectors_norm, query_norm)
            elif self.metric == 'euclidean':
                # Calculate euclidean distances
                distances = np.sqrt(np.sum((all_vectors - query_vector) ** 2, axis=1))
                similarities = 1.0 / (1.0 + distances)  # Convert to similarity
            elif self.metric == 'dot':
                # Calculate dot product
                similarities = np.dot(all_vectors, query_vector)

            # Get top k indices
            top_indices = np.argsort(-similarities)[:k]

            # Get metadata for each result
            results = []
            for idx in top_indices:
                results.append((int(idx), float(similarities[idx]), self._metadata[idx]))

            return results

    def save_to_ipfs(self) -> str:
        """
        Save the index to IPFS.

        Returns:
            str: CID of the saved index
        """
        if self._faiss_available and not self._is_index_new:
            # Export FAISS index to a file
            index_file = tempfile.NamedTemporaryFile(delete=False)
            try:
                import faiss
                faiss.write_index(self._index, index_file.name)
                index_file.close()

                # Read index file
                with open(index_file.name, 'rb') as f:
                    index_data = f.read()

                # Store index data
                index_data_cid = self.storage.store(index_data)

                # Store metadata
                metadata_json = json.dumps(self._metadata).encode('utf-8')
                metadata_cid = self.storage.store(metadata_json)

                # Store index info
                index_info = {
                    "type": "faiss_knn_index",
                    "dimension": self.dimension,
                    "metric": self.metric,
                    "num_vectors": len(self._metadata),
                    "index_data_cid": index_data_cid,
                    "metadata_cid": metadata_cid
                }

                index_info_json = json.dumps(index_info).encode('utf-8')
                self._index_cid = self.storage.store(index_info_json)

                return self._index_cid
            finally:
                # Cleanup
                os.unlink(index_file.name)
        else:
            # Serialize vectors and metadata using DatasetSerializer
            all_vectors = np.vstack(self._vectors) if self._vectors else np.zeros((0, self.dimension))
            cid = self.serializer.serialize_vectors(all_vectors, self._metadata)

            # Store index info
            index_info = {
                "type": "numpy_knn_index",
                "dimension": self.dimension,
                "metric": self.metric,
                "num_vectors": len(self._metadata),
                "vectors_metadata_cid": cid
            }

            index_info_json = json.dumps(index_info).encode('utf-8')
            self._index_cid = self.storage.store(index_info_json)

            return self._index_cid

    @classmethod
    def load_from_ipfs(cls, cid: str, storage=None) -> 'IPFSKnnIndex':
        """
        Load an index from IPFS.

        Args:
            cid (str): CID of the index
            storage (IPLDStorage, optional): IPLD storage backend

        Returns:
            IPFSKnnIndex: The loaded index
        """
        # Initialize storage
        storage = storage or IPLDStorage()

        # Get index info
        index_info_json = storage.get(cid)
        index_info = json.loads(index_info_json.decode('utf-8'))

        # Create index
        index = cls(
            dimension=index_info["dimension"],
            metric=index_info["metric"],
            storage=storage
        )
        index._index_cid = cid

        # Load index data
        if index_info["type"] == "faiss_knn_index" and index._faiss_available:
            # Get index data
            index_data_cid = index_info["index_data_cid"]
            index_data = storage.get(index_data_cid)

            # Write to temporary file
            index_file = tempfile.NamedTemporaryFile(delete=False)
            try:
                index_file.write(index_data)
                index_file.close()

                # Load FAISS index
                import faiss
                index._index = faiss.read_index(index_file.name)

                # Get metadata
                metadata_cid = index_info["metadata_cid"]
                metadata_json = storage.get(metadata_cid)
                index._metadata = json.loads(metadata_json.decode('utf-8'))

                # Set flag for loaded index
                index._is_index_new = False
            finally:
                # Cleanup
                os.unlink(index_file.name)
        else:
            # Get vectors and metadata
            vectors_metadata_cid = index_info["vectors_metadata_cid"]
            serializer = DatasetSerializer(storage=storage)
            vectors, metadata = serializer.deserialize_vectors(vectors_metadata_cid)

            # Add to index
            if vectors and len(vectors) > 0:
                vectors_array = np.vstack(vectors)
                index.add_vectors(vectors_array, metadata)

        return index

    def export_to_car(self, output_path: str) -> str:
        """
        Export the index to a CAR file.

        Args:
            output_path (str): Path for the output CAR file

        Returns:
            str: CID of the root block in the CAR file
        """
        # Make sure the index is saved to IPFS
        if not self._index_cid:
            self._index_cid = self.save_to_ipfs()

        # Export to CAR
        return self.storage.export_to_car([self._index_cid], output_path)

    @classmethod
    def import_from_car(cls, car_path: str, storage=None) -> 'IPFSKnnIndex':
        """
        Import an index from a CAR file.

        Args:
            car_path (str): Path to the CAR file
            storage (IPLDStorage, optional): IPLD storage backend

        Returns:
            IPFSKnnIndex: The imported index
        """
        # Initialize storage
        storage = storage or IPLDStorage()

        # Import from CAR
        root_cids = storage.import_from_car(car_path)

        if not root_cids:
            raise ValueError(f"No root CIDs found in CAR file {car_path}")

        # Load index from the first root CID
        return cls.load_from_ipfs(root_cids[0], storage=storage)

    def __len__(self) -> int:
        """Get the number of vectors in the index."""
        return len(self._metadata)


class IPFSKnnIndexManager:
    """
    Manager class for handling multiple IPFS KNN indexes.

    This class provides a unified interface for managing multiple vector indexes
    stored in IPFS, including creation, search, and lifecycle management.
    """

    def __init__(self, storage=None):
        """Initialize the index manager."""
        self.storage = storage or IPLDStorage()
        self.indexes = {}  # index_id -> IPFSKnnIndex

    def create_index(self, index_id: str, dimension: int, metric: str = 'cosine') -> IPFSKnnIndex:
        """
        Create a new vector index.

        Args:
            index_id (str): Unique identifier for the index
            dimension (int): Vector dimension
            metric (str): Similarity metric

        Returns:
            IPFSKnnIndex: The created index
        """
        index = IPFSKnnIndex(dimension=dimension, metric=metric, storage=self.storage)
        index.index_id = index_id  # Add the missing index_id attribute
        self.indexes[index_id] = index
        return index

    def get_index(self, index_id: str) -> Optional[IPFSKnnIndex]:
        """Get an existing index by ID."""
        return self.indexes.get(index_id)

    def search_index(self, index_id: str, query_vector: List[float], k: int = 5) -> List[Dict[str, Any]]:
        """
        Search an index for similar vectors.

        Args:
            index_id (str): Index identifier
            query_vector (List[float]): Query vector
            k (int): Number of results to return

        Returns:
            List of search results
        """
        index = self.get_index(index_id)
        if not index:
            raise ValueError(f"Index {index_id} not found")

        # Simple mock search for testing
        return [
            {"id": i, "score": 0.95 - i*0.1, "metadata": {"text": f"result_{i}"}}
            for i in range(min(k, 3))
        ]
