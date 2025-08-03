# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/ipfs_knn_index.py'

Files last updated: 1751678277.7706635

Stub file last updated: 2025-07-07 02:11:01

## IPFSKnnIndex

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## IPFSKnnIndexManager

```python
class IPFSKnnIndexManager:
    """
    Manager class for handling multiple IPFS KNN indexes.

This class provides a unified interface for managing multiple vector indexes
stored in IPFS, including creation, search, and lifecycle management.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, dimension: int, metric: str = "cosine", storage = None):
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
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndex

## __init__

```python
def __init__(self, storage = None):
    """
    Initialize the index manager.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndexManager

## __len__

```python
def __len__(self) -> int:
    """
    Get the number of vectors in the index.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndex

## add_vectors

```python
def add_vectors(self, vectors: np.ndarray, metadata: Optional[List[Dict[str, Any]]] = None) -> None:
    """
    Add vectors to the index.

Args:
    vectors (np.ndarray): Vectors to add, shape (n, dimension)
    metadata (List[Dict], optional): Metadata for each vector
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndex

## create_index

```python
def create_index(self, index_id: str, dimension: int, metric: str = "cosine") -> IPFSKnnIndex:
    """
    Create a new vector index.

Args:
    index_id (str): Unique identifier for the index
    dimension (int): Vector dimension
    metric (str): Similarity metric

Returns:
    IPFSKnnIndex: The created index
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndexManager

## export_to_car

```python
def export_to_car(self, output_path: str) -> str:
    """
    Export the index to a CAR file.

Args:
    output_path (str): Path for the output CAR file

Returns:
    str: CID of the root block in the CAR file
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndex

## get_index

```python
def get_index(self, index_id: str) -> Optional[IPFSKnnIndex]:
    """
    Get an existing index by ID.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndexManager

## import_from_car

```python
@classmethod
def import_from_car(cls, car_path: str, storage = None) -> "IPFSKnnIndex":
    """
    Import an index from a CAR file.

Args:
    car_path (str): Path to the CAR file
    storage (IPLDStorage, optional): IPLD storage backend

Returns:
    IPFSKnnIndex: The imported index
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndex

## load_from_ipfs

```python
@classmethod
def load_from_ipfs(cls, cid: str, storage = None) -> "IPFSKnnIndex":
    """
    Load an index from IPFS.

Args:
    cid (str): CID of the index
    storage (IPLDStorage, optional): IPLD storage backend

Returns:
    IPFSKnnIndex: The loaded index
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndex

## save_to_ipfs

```python
def save_to_ipfs(self) -> str:
    """
    Save the index to IPFS.

Returns:
    str: CID of the saved index
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndex

## search

```python
def search(self, query_vector: np.ndarray, k: int = 10) -> List[Tuple[int, float, Dict[str, Any]]]:
    """
    Search for vectors similar to the query vector.

Args:
    query_vector (np.ndarray): Query vector, shape (dimension,)
    k (int): Number of results to return

Returns:
    List[Tuple[int, float, Dict]]: List of (index, similarity, metadata) tuples
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndex

## search_index

```python
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
```
* **Async:** False
* **Method:** True
* **Class:** IPFSKnnIndexManager
