# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/dataset_serialization.py'

Files last updated: 1751677871.0901043

Stub file last updated: 2025-07-07 02:11:01

## DatasetSerializer

```python
class DatasetSerializer:
    """
    Comprehensive Dataset Serialization and Format Conversion Platform

The DatasetSerializer class provides enterprise-grade functionality for converting,
serializing, and managing datasets across multiple formats with IPFS integration.
This platform enables seamless data transformation between popular data science
formats while maintaining schema integrity, metadata preservation, and content
addressability through IPLD (InterPlanetary Linked Data) storage systems.

The serializer supports bidirectional conversion between major data formats
including Apache Arrow tables, HuggingFace datasets, Pandas DataFrames, JSON
Lines, Parquet files, and IPLD-compatible structures. Advanced features include
streaming processing for large datasets, content-based deduplication, graph
dataset support, and vector embedding optimization for machine learning workflows.

Key Features:
- Multi-format dataset conversion with schema preservation
- IPLD serialization for content-addressable storage on IPFS networks
- Streaming processing for memory-efficient large dataset handling
- Content-based deduplication to minimize storage requirements
- Graph dataset support with relationship preservation
- Vector embedding storage with optimized indexing and retrieval
- JSONL import/export with flexible schema inference
- Metadata preservation across all format conversions

Supported Formats:
- Apache Arrow: Columnar in-memory format optimized for analytics
- HuggingFace Datasets: ML-optimized format with built-in preprocessing
- Pandas DataFrames: Python data analysis format with rich functionality
- Parquet Files: Columnar storage format for efficient archival
- JSON Lines: Streaming JSON format for large-scale data processing
- IPLD Structures: Content-addressable linked data for IPFS storage
- Graph Formats: Node/edge structures for network and knowledge graphs
- Vector Collections: Embedding arrays with metadata and indexing

Conversion Capabilities:
- Lossless conversion between supported formats with type preservation
- Automatic schema inference and validation for unstructured data
- Custom serialization handlers for complex data types and structures
- Incremental processing for append-only dataset operations
- Format-specific optimization for performance and storage efficiency
- Metadata enrichment with provenance and transformation tracking

IPFS Integration:
- Direct serialization to IPLD for content-addressable storage
- Automatic chunking and linking for large dataset distribution
- Content deduplication through cryptographic hashing
- Distributed dataset reconstruction from IPFS content identifiers
- Version tracking and immutable dataset snapshots

Attributes:
    storage (IPLDStorage): IPLD storage backend for content-addressable
        dataset persistence and retrieval operations with IPFS integration.
        Manages content chunking, linking, and distributed storage coordination.

Public Methods:
    to_arrow(data: Any, **kwargs) -> pyarrow.Table:
        Convert various data formats to Apache Arrow tables with schema preservation
    to_huggingface(data: Any, **kwargs) -> datasets.Dataset:
        Transform data to HuggingFace datasets format with ML optimizations
    to_pandas(data: Any, **kwargs) -> pandas.DataFrame:
        Convert data to Pandas DataFrame with type inference and validation
    to_parquet(data: Any, file_path: str, **kwargs) -> str:
        Serialize data to Parquet format with compression and optimization
    to_jsonl(data: Any, file_path: str, **kwargs) -> str:
        Export data to JSON Lines format with streaming support
    to_ipld(data: Any, **kwargs) -> Dict[str, Any]:
        Serialize data to IPLD format for content-addressable storage
    from_ipld(cid: str, **kwargs) -> Any:
        Deserialize data from IPLD using content identifier retrieval
    deduplicate(dataset: Any, **kwargs) -> Any:
        Remove duplicate content using content-based hashing
    stream_convert(source: str, target: str, format_from: str, format_to: str) -> str:
        Stream-based conversion for large datasets with memory optimization

Usage Examples:
    # Initialize serializer with IPFS storage
    serializer = DatasetSerializer()
    
    # Convert HuggingFace dataset to Arrow format
    hf_dataset = load_dataset("imdb", split="train")
    arrow_table = serializer.to_arrow(hf_dataset)
    
    # Serialize dataset to IPLD for IPFS storage
    ipld_data = serializer.to_ipld(arrow_table)
    
    # Convert Pandas DataFrame to Parquet with optimization
    df = pd.read_csv("large_dataset.csv")
    parquet_path = serializer.to_parquet(
        df, 
        "optimized_dataset.parquet",
        compression="snappy"
    )
    
    # Stream conversion for memory-efficient processing
    converted_path = serializer.stream_convert(
        source="huge_dataset.jsonl",
        target="huge_dataset.parquet",
        format_from="jsonl",
        format_to="parquet"
    )
    
    # Deduplicate dataset content
    unique_dataset = serializer.deduplicate(
        dataset=raw_dataset,
        method="content_hash"
    )

Dependencies:
    Required:
    - pyarrow: Apache Arrow format support and columnar operations
    - datasets: HuggingFace datasets library for ML-optimized data handling
    - pandas: Data manipulation and analysis framework
    
    Optional:
    - ipfs_datasets_py.ipld: IPLD storage backend for IPFS integration
    - ipfs_datasets_py.ipfs_knn_index: Vector indexing for embedding storage
    - Various format-specific libraries for specialized conversion operations

Notes:
    - Large dataset conversions benefit from streaming processing to manage memory
    - Schema preservation ensures data integrity across format transformations
    - Content deduplication reduces storage requirements and improves efficiency
    - IPLD serialization enables distributed dataset storage and versioning
    - Vector embedding storage includes optimized indexing for similarity search
    - Graph dataset support maintains relationship structures and connectivity
    - Metadata preservation includes transformation history and provenance tracking
    - Performance optimization varies by format and dataset characteristics
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DatasetSerializer

```python
class DatasetSerializer:
    """
    Serializes and deserializes datasets between various formats and IPLD.

Supported formats:
- Arrow tables
- HuggingFace datasets
- Pandas DataFrames (if pandas is available)
- Python dicts
- Graph datasets
- Vector embeddings
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GraphDataset

```python
class GraphDataset:
    """
    A graph dataset containing nodes and edges with query capabilities.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GraphNode

```python
class GraphNode(Generic[T]):
    """
    A node in a graph dataset.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MockChunk

```python
class MockChunk:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorAugmentedGraphDataset

```python
class VectorAugmentedGraphDataset(GraphDataset):
    """
    A graph dataset with integrated vector similarity search (GraphRAG).

This class extends GraphDataset with vector embedding capabilities,
allowing for hybrid retrieval combining semantic similarity and graph structure.

Features:
- Store and query vector embeddings associated with nodes
- Hybrid search combining vector similarity and graph traversal
- Weighted path scoring based on semantic and structural relevance
- Integration with IPFS for persistent storage
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, storage = None):
    """
    Initialize Dataset Serialization Platform with IPLD Storage Integration

Establishes a new DatasetSerializer instance with comprehensive format
conversion capabilities and content-addressable storage through IPLD
(InterPlanetary Linked Data) systems. This initialization configures
all necessary components for multi-format dataset operations while
maintaining optimal performance and storage efficiency.

The initialization process sets up storage backends, format handlers,
schema validation systems, and optimization parameters required for
enterprise-grade dataset serialization workflows. IPLD integration
enables content-addressable storage and distributed dataset management
across IPFS networks.

Args:
    storage (Optional[IPLDStorage], default=None): IPLD storage backend
        for content-addressable dataset persistence and distributed
        storage operations. If None, a new IPLDStorage instance will
        be created automatically with default configuration parameters.
        
        The storage backend provides:
        - Content-addressable chunking and linking for large datasets
        - Cryptographic hashing for content deduplication and integrity
        - Distributed storage coordination across IPFS network nodes
        - Version tracking and immutable dataset snapshot capabilities
        - Metadata preservation and provenance tracking systems
        
        Custom storage configurations support:
        - Alternative IPFS node endpoints and gateway configurations
        - Custom chunking strategies for different dataset characteristics
        - Compression and optimization settings for storage efficiency
        - Access control and encryption for sensitive dataset operations

Attributes Initialized:
    storage (IPLDStorage): Configured IPLD storage backend ready for
        immediate dataset serialization and retrieval operations with
        comprehensive IPFS integration and distributed storage support.

Raises:
    ImportError: If the required IPLD storage dependencies are not available
        or cannot be imported. This includes ipfs_datasets_py.ipld.storage
        and associated IPFS integration libraries.
    ConfigurationError: If the provided storage backend configuration is
        invalid or incompatible with current system capabilities.
    ConnectionError: If IPFS node connectivity tests fail during storage
        backend initialization or network access validation.

Examples:
    # Basic initialization with default IPLD storage
    serializer = DatasetSerializer()
    
    # Custom IPLD storage configuration
    from ipfs_datasets_py.ipld.storage import IPLDStorage
    
    custom_storage = IPLDStorage(
        ipfs_gateway="http://custom-ipfs:8080",
        chunk_size=1024*1024,  # 1MB chunks
        compression="gzip",
        enable_deduplication=True
    )
    serializer = DatasetSerializer(storage=custom_storage)
    
    # Development configuration with local IPFS node
    dev_storage = IPLDStorage(
        ipfs_gateway="http://localhost:8080",
        debug_mode=True,
        cache_size=100  # Small cache for development
    )
    dev_serializer = DatasetSerializer(storage=dev_storage)

Notes:
    - IPLD storage enables content-addressable dataset operations with IPFS
    - Default storage configuration provides secure and efficient operation
    - Custom storage backends support specialized deployment requirements
    - Storage initialization validates IPFS connectivity and configuration
    - Content deduplication is enabled automatically for storage efficiency
    - Distributed storage coordination requires network connectivity
    - Storage backends support both synchronous and asynchronous operations
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## __init__

```python
def __init__(self, id: str, type: str, data: T):
    """
    Initialize a new graph node.

Args:
    id (str): Node identifier
    type (str): Node type
    data (T): Node data
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphNode

## __init__

```python
def __init__(self, name: str = None):
    """
    Initialize a new graph dataset.

Args:
    name (str, optional): Dataset name
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## __init__

```python
def __init__(self, name: str = None, vector_dimension: int = 768, vector_metric: str = "cosine", storage = None):
    """
    Initialize a new vector-augmented graph dataset.

Args:
    name (str, optional): Dataset name
    vector_dimension (int): Dimension of vector embeddings
    vector_metric (str): Similarity metric ('cosine', 'euclidean', 'dot')
    storage (IPLDStorage, optional): IPLD storage backend
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## __init__

```python
def __init__(self, storage = None):
    """
    Initialize a new DatasetSerializer.

Args:
    storage (IPLDStorage, optional): IPLD storage backend. If None,
        a new IPLDStorage instance will be created.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## __len__

```python
def __len__(self):
```
* **Async:** False
* **Method:** True
* **Class:** MockChunk

## _analyze_document_evidence_chains

```python
def _analyze_document_evidence_chains(self, documents: List[Tuple[GraphNode, float]], connections: List[Dict[str, Any]], reasoning_depth: str) -> List[Dict[str, Any]]:
    """
    Analyze document evidence chains based on reasoning depth.

Args:
    documents: List of tuples with (document_node, relevance_score).
    connections: List of document connections through entities.
    reasoning_depth: Depth of reasoning ('basic', 'moderate', or 'deep').

Returns:
    List of evidence chains with reasoning analysis.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _analyze_entity_information_relation

```python
def _analyze_entity_information_relation(self, info1: Dict[str, Any], info2: Dict[str, Any]) -> str:
    """
    Analyze the relation between entity information from two documents.

Args:
    info1: Entity information from the first document.
    info2: Entity information from the second document.

Returns:
    Relation type: 'complementary', 'contradictory', 'identical', or 'unrelated'.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _analyze_transitive_relationships

```python
def _analyze_transitive_relationships(self, doc1: GraphNode, doc2: GraphNode, path: List[str]) -> Dict[str, Any]:
    """
    Analyze transitive relationships in a multi-hop path between documents.

Args:
    doc1: The first document node.
    doc2: The second document node.
    path: The path connecting the documents.

Returns:
    Dictionary with transitive relationship analysis.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _calculate_edge_score

```python
def _calculate_edge_score(self, edge_properties, guidance_properties):
    """
    Calculate a score for an edge based on its properties and guidance weights
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _calculate_field_similarity

```python
def _calculate_field_similarity(self, value1, value2):
    """
    Calculate similarity between two field values based on their types
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _calculate_metadata_similarity

```python
def _calculate_metadata_similarity(self, text_node, image_node, field_mappings, field_weights):
    """
    Calculate similarity between text and image nodes based on metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _calculate_property_similarity

```python
def _calculate_property_similarity(self, node1: GraphNode, node2: GraphNode, property_weights: Optional[Dict[str, float]] = None) -> float:
    """
    Calculate similarity between two nodes based on their properties.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _calculate_structural_score

```python
def _calculate_structural_score(self, path_nodes, edge_types, guidance_properties):
    """
    Calculate a structural quality score for a path
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _compute_clustering_coefficient

```python
def _compute_clustering_coefficient(self, subgraph):
    """
    Compute the average clustering coefficient of the subgraph
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _compute_pagerank_for_subgraph

```python
def _compute_pagerank_for_subgraph(self, subgraph, damping = 0.85, max_iterations = 100, tolerance = 1e-06):
    """
    Compute PageRank centrality for nodes in a subgraph
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _count_node_connections

```python
def _count_node_connections(self, subgraph, node_id):
    """
    Count incoming and outgoing connections for a node
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _create_query_vector_from_text

```python
def _create_query_vector_from_text(self, query_text: str) -> np.ndarray:
    """
    Create a query vector from natural language text.

This method would normally use a text embedding model, but for simplicity,
we'll create a mock vector based on word frequencies that match our vector space.
In a real implementation, this would use a language model to generate embeddings.

Args:
    query_text: The natural language query text.

Returns:
    A normalized vector representation of the query.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _create_time_snapshot_subgraph

```python
def _create_time_snapshot_subgraph(self, node_ids):
    """
    Create a subgraph containing only the specified nodes and their interconnections
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _deserialize_column

```python
def _deserialize_column(self, data, type_obj):
    """
    Deserialize bytes to an Arrow array.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _deserialize_features

```python
def _deserialize_features(self, features_dict):
    """
    Deserialize dataset features from a dict.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _determine_cross_modal_edge_type

```python
def _determine_cross_modal_edge_type(self, text_node, image_node):
    """
    Determine the appropriate edge type for a text-image link
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _dict_to_schema

```python
def _dict_to_schema(self, schema_dict):
    """
    Convert a dict to an Arrow schema.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _dict_to_type

```python
def _dict_to_type(self, type_dict):
    """
    Convert a dict to an Arrow type.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _establish_cross_modal_links_by_embedding

```python
def _establish_cross_modal_links_by_embedding(self, text_nodes, image_nodes, min_confidence):
    """
    Helper method to establish links between text and image nodes using embeddings
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _establish_cross_modal_links_by_metadata

```python
def _establish_cross_modal_links_by_metadata(self, text_nodes, image_nodes, min_confidence):
    """
    Helper method to establish links between text and image nodes using metadata matching
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _evaluate_answer_confidence

```python
def _evaluate_answer_confidence(self, synthesis_result: Dict[str, Any], evidence_chains: List[Dict[str, Any]], documents: List[Tuple[GraphNode, float]]) -> float:
    """
    Evaluate the confidence in the synthesized answer.

Args:
    synthesis_result: The synthesized answer result.
    evidence_chains: List of evidence chains.
    documents: List of relevant documents.

Returns:
    A confidence score between 0 and 1.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _execute_graph_rag_search

```python
def _execute_graph_rag_search(self, query_vector: np.ndarray, max_vector_results: int = 5, max_traversal_depth: int = 2, edge_types: Optional[List[str]] = None, min_similarity: float = 0.5) -> List[Tuple[GraphNode, float, List[GraphNode]]]:
    """
    Internal implementation of graph RAG search.

Args:
    query_vector (np.ndarray): Query vector
    max_vector_results (int): Maximum number of initial vector similarity matches
    max_traversal_depth (int): Maximum traversal depth from each similarity match
    edge_types (List[str], optional): Types of edges to follow
    min_similarity (float): Minimum similarity score for initial vector matches

Returns:
    List[Tuple[GraphNode, float, List[GraphNode]]]: Results
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _extract_community_themes

```python
def _extract_community_themes(self, nodes: List[GraphNode]) -> List[str]:
    """
    Extract common themes from a group of nodes based on their properties.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _extract_document_entity_info

```python
def _extract_document_entity_info(self, doc_node: GraphNode, entity_id: str) -> Dict[str, Any]:
    """
    Extract information about an entity from a document.

Args:
    doc_node: The document node.
    entity_id: The entity ID.

Returns:
    Dictionary with information about the entity from the document.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _extract_key_entities_from_documents

```python
def _extract_key_entities_from_documents(self, documents: List[Tuple[GraphNode, float]]) -> Dict[str, Dict[str, Any]]:
    """
    Extract key entities referenced in the documents.

Args:
    documents: List of tuples with (document_node, relevance_score).

Returns:
    Dictionary mapping entity IDs to entity information.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _find_common_neighbor_candidates

```python
def _find_common_neighbor_candidates(self, edge_type, existing_edges):
    """
    Find potential relations based on common neighbors
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _find_entity_mediated_connections

```python
def _find_entity_mediated_connections(self, documents: List[Tuple[GraphNode, float]], entities: Dict[str, Dict[str, Any]], max_hops: int) -> List[Dict[str, Any]]:
    """
    Find connections between documents mediated by shared entities.

Args:
    documents: List of tuples with (document_node, relevance_score).
    entities: Dictionary mapping entity IDs to entity information.
    max_hops: Maximum number of hops between documents.

Returns:
    List of dictionaries describing the entity-mediated connections.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _find_guided_paths

```python
def _find_guided_paths(self, start_node, start_similarity, query_vector, target_node_types, guidance_properties, max_paths, max_depth):
    """
    Helper method to find guided paths from a starting concept node
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _find_relevant_documents

```python
def _find_relevant_documents(self, query_vector: np.ndarray, document_node_types: List[str], min_relevance: float, max_documents: int) -> List[Tuple[GraphNode, float]]:
    """
    Find documents semantically relevant to the query vector.

Args:
    query_vector: The query vector.
    document_node_types: Types of nodes representing documents.
    min_relevance: Minimum relevance score to include a document.
    max_documents: Maximum number of documents to return.

Returns:
    List of tuples containing (document_node, relevance_score).
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _find_symmetric_candidates

```python
def _find_symmetric_candidates(self, edge_type, existing_edges):
    """
    Find potential symmetric relation candidates
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _find_transitive_candidates

```python
def _find_transitive_candidates(self, edge_type, existing_edges):
    """
    Find potential transitive relation candidates (A->B, B->C => A->C)
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _fix_schema_violations

```python
def _fix_schema_violations(self, data, schema, violations):
    """
    Fix schema violations where possible and return count of fixed violations
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _generate_basic_answer

```python
def _generate_basic_answer(self, query: str, documents: List[Tuple[GraphNode, float]], evidence_chains: List[Dict[str, Any]]) -> str:
    """
    Generate a basic answer by combining information from documents.

Args:
    query: The original query.
    documents: List of relevant documents.
    evidence_chains: List of evidence chains.

Returns:
    A synthesized answer string.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _generate_deep_answer

```python
def _generate_deep_answer(self, query: str, documents: List[Tuple[GraphNode, float]], evidence_chains: List[Dict[str, Any]]) -> str:
    """
    Generate a complex answer with deep reasoning across documents.

Args:
    query: The original query.
    documents: List of relevant documents.
    evidence_chains: List of evidence chains.

Returns:
    A synthesized answer string.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _generate_deep_inferences

```python
def _generate_deep_inferences(self, doc1: GraphNode, doc2: GraphNode, entity_id: str, entity_type: str, info_relation: str, knowledge_gaps: List[str]) -> List[str]:
    """
    Generate deep inferences based on entity information and knowledge gaps.

Args:
    doc1: The first document node.
    doc2: The second document node.
    entity_id: The entity ID.
    entity_type: The entity type.
    info_relation: Information relation type.
    knowledge_gaps: List of knowledge gaps.

Returns:
    List of potential inferences.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _generate_inference_for_entity_chain

```python
def _generate_inference_for_entity_chain(self, doc1: GraphNode, doc2: GraphNode, entity_chain_info: List[Dict[str, Any]]) -> str:
    """
    Generate an inference based on an entity chain between documents.

Args:
    doc1: The first document node.
    doc2: The second document node.
    entity_chain_info: Information about the entities in the chain.

Returns:
    A string with the generated inference.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _generate_inference_for_info_relation

```python
def _generate_inference_for_info_relation(self, doc1: GraphNode, doc2: GraphNode, entity_id: str, entity_type: str, info_relation: str) -> str:
    """
    Generate an inference based on the information relation between documents.

Args:
    doc1: The first document node.
    doc2: The second document node.
    entity_id: The entity ID.
    entity_type: The entity type.
    info_relation: The relation type between information.

Returns:
    A string with the generated inference.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _generate_moderate_answer

```python
def _generate_moderate_answer(self, query: str, documents: List[Tuple[GraphNode, float]], evidence_chains: List[Dict[str, Any]]) -> str:
    """
    Generate a moderate complexity answer using document relationships.

Args:
    query: The original query.
    documents: List of relevant documents.
    evidence_chains: List of evidence chains.

Returns:
    A synthesized answer string.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _get_default_edge_schemas

```python
def _get_default_edge_schemas(self):
    """
    Return default schemas for common edge types
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _get_default_node_schemas

```python
def _get_default_node_schemas(self):
    """
    Return default schemas for common node types
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _get_nodes_in_time_interval

```python
def _get_nodes_in_time_interval(self, time_property, start_time, end_time, additional_filters = None):
    """
    Helper method to get nodes within a specific time interval
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _get_subgraph_contextual_embedding

```python
def _get_subgraph_contextual_embedding(self, subgraph, node_id):
    """
    Helper method to get contextual embedding within a subgraph
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _hash_column

```python
def _hash_column(self, column):
    """
    Create a hash of a column for content addressing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _identify_knowledge_gaps

```python
def _identify_knowledge_gaps(self, info1: Dict[str, Any], info2: Dict[str, Any]) -> List[str]:
    """
    Identify knowledge gaps between the information in two documents.

Args:
    info1: Entity information from the first document.
    info2: Entity information from the second document.

Returns:
    List of identified knowledge gaps.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _identify_transitive_relationship_patterns

```python
def _identify_transitive_relationship_patterns(self, relationships: List[Dict[str, Any]]) -> List[str]:
    """
    Identify transitive relationship patterns from a chain of relationships.

Args:
    relationships: List of relationship dictionaries.

Returns:
    List of identified transitive relationship types.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _is_in_time_interval

```python
def _is_in_time_interval(self, value, start, end):
    """
    Check if a value is within a time interval, handling different types
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _list_similarity

```python
def _list_similarity(self, list1, list2):
    """
    Calculate similarity between two lists (e.g., tags)
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _merge_predictions

```python
def _merge_predictions(self, semantic_predictions, structural_predictions):
    """
    Merge and blend predictions from different methods
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _normalize_text

```python
def _normalize_text(self, text):
    """
    Normalize text for comparison: lowercase, remove punctuation
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _predict_edges_semantic

```python
def _predict_edges_semantic(self, nodes_with_embeddings, target_relation_types, existing_edges):
    """
    Predict missing edges using semantic similarity of nodes
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _predict_edges_structural

```python
def _predict_edges_structural(self, target_relation_types, existing_edges):
    """
    Predict missing edges using structural patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _rebuild_vector_index

```python
def _rebuild_vector_index(self):
    """
    Rebuild the vector index after structural changes to the graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _schema_to_dict

```python
def _schema_to_dict(self, schema):
    """
    Convert an Arrow schema to a dict.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _serialize_column

```python
def _serialize_column(self, column):
    """
    Serialize an Arrow array to bytes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _serialize_features

```python
def _serialize_features(self, features):
    """
    Serialize dataset features to a dict.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _store_jsonl_batch

```python
def _store_jsonl_batch(self, records, hash_records = True):
    """
    Store a batch of JSON records in IPLD.

Args:
    records (list): List of JSON records to store
    hash_records (bool): Whether to hash individual records for content addressing

Returns:
    list: List of CIDs for the stored records
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _synthesize_cross_document_information

```python
def _synthesize_cross_document_information(self, query: str, documents: List[Tuple[GraphNode, float]], evidence_chains: List[Dict[str, Any]], reasoning_depth: str) -> Dict[str, Any]:
    """
    Synthesize information across documents to answer the query.

Args:
    query: The original query string.
    documents: List of document nodes with relevance scores.
    evidence_chains: List of evidence chains connecting documents.
    reasoning_depth: Depth of reasoning used.

Returns:
    Dictionary with synthesized answer and reasoning trace.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _text_similarity

```python
def _text_similarity(self, text1, text2):
    """
    Calculate similarity between two text strings
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _type_to_dict

```python
def _type_to_dict(self, type_obj):
    """
    Convert an Arrow type to a dict.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## _validate_against_schema

```python
def _validate_against_schema(self, data, schema, validation_mode):
    """
    Validate data against a schema and return violations
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## _write_arrow_to_jsonl

```python
def _write_arrow_to_jsonl(self, table, file_obj):
    """
    Write an Arrow table to a JSONL file.

Args:
    table (pyarrow.Table): Table to write
    file_obj: File object to write to
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## add_edge

```python
def add_edge(self, edge_type: str, target: "GraphNode", properties: Optional[Dict[str, Any]] = None):
    """
    Add an edge to another node.

Args:
    edge_type (str): Type of the edge
    target (GraphNode): Target node
    properties (Dict, optional): Properties to associate with the edge
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphNode

## add_edge

```python
def add_edge(self, source_id: str, edge_type: str, target_id: str, properties: Optional[Dict[str, Any]] = None):
    """
    Add an edge between nodes.

Args:
    source_id (str): Source node ID
    edge_type (str): Type of the edge
    target_id (str): Target node ID
    properties (Dict, optional): Properties to associate with the edge

Raises:
    ValueError: If source or target node does not exist
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## add_node

```python
def add_node(self, node: GraphNode) -> GraphNode:
    """
    Add a node to the graph.

Args:
    node (GraphNode): Node to add

Returns:
    GraphNode: The added node

Raises:
    ValueError: If a node with the same ID already exists
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## add_node_with_embedding

```python
def add_node_with_embedding(self, node: GraphNode, embedding: np.ndarray, embedding_metadata: Optional[Dict[str, Any]] = None) -> GraphNode:
    """
    Add a node with its vector embedding to the graph.

Args:
    node (GraphNode): Node to add
    embedding (np.ndarray): Vector embedding for the node
    embedding_metadata (Dict, optional): Additional metadata for the embedding

Returns:
    GraphNode: The added node
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## add_nodes_with_text_embedding

```python
def add_nodes_with_text_embedding(self, nodes: List[GraphNode], text_extractor: Callable[[GraphNode], str], embedding_model: Optional[Any] = None, batch_size: int = 32) -> int:
    """
    Add multiple nodes with text embeddings generated from an embedding model.

Args:
    nodes (List[GraphNode]): List of nodes to add
    text_extractor (Callable): Function to extract text from nodes for embedding
    embedding_model (Any, optional): Embedding model to use.
        If None, attempts to use sentence-transformers or other available models.
    batch_size (int): Batch size for processing embeddings

Returns:
    int: Number of nodes successfully added
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## advanced_graph_rag_search

```python
def advanced_graph_rag_search(self, query_vector: np.ndarray, max_vector_results: int = 5, max_traversal_depth: int = 2, edge_types: Optional[List[str]] = None, min_similarity: float = 0.5, semantic_weight: float = 0.7, structural_weight: float = 0.3, path_decay_factor: float = 0.8) -> List[Dict[str, Any]]:
    """
    Perform an advanced hybrid search with weighted scoring for semantic and structural relevance.

Args:
    query_vector (np.ndarray): Query vector
    max_vector_results (int): Maximum number of initial vector similarity matches
    max_traversal_depth (int): Maximum traversal depth from each similarity match
    edge_types (List[str], optional): Types of edges to follow. If None, follow all edge types.
    min_similarity (float): Minimum similarity score for initial vector matches
    semantic_weight (float): Weight for vector similarity score (0-1)
    structural_weight (float): Weight for graph structure score (0-1)
    path_decay_factor (float): Factor to decay relevance score with increasing path length

Returns:
    List[Dict]: List of result dictionaries containing:
        - 'node': The matched node
        - 'paths': List of paths to context nodes
        - 'score': Combined relevance score
        - 'semantic_score': Vector similarity score
        - 'structural_score': Graph structure relevance score
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## batch_add_nodes_and_edges

```python
def batch_add_nodes_and_edges(self, nodes: List[GraphNode], edges: List[Tuple[str, str, str, Optional[Dict[str, Any]]]], generate_embeddings: bool = False, text_extractor: Optional[Callable[[GraphNode], str]] = None, embedding_model: Optional[Any] = None) -> Tuple[int, int]:
    """
    Batch add nodes and edges to the graph, optionally generating embeddings.

Args:
    nodes (List[GraphNode]): List of nodes to add
    edges (List[Tuple]): List of (source_id, edge_type, target_id, properties) tuples
    generate_embeddings (bool): Whether to generate embeddings for the nodes
    text_extractor (Callable, optional): Function to extract text for embeddings
    embedding_model (Any, optional): Embedding model to use

Returns:
    Tuple[int, int]: (Number of nodes added, Number of edges added)
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## calculate_path_weight

```python
def calculate_path_weight(path, node_scores):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## check_hop

```python
def check_hop(current_node, remaining_hops):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## compare_subgraphs

```python
def compare_subgraphs(self, subgraph1: "GraphDataset", subgraph2: "GraphDataset", comparison_method: str = "hybrid", node_type_weights: Optional[Dict[str, float]] = None, edge_type_weights: Optional[Dict[str, float]] = None, semantic_weight: float = 0.5, structural_weight: float = 0.5) -> Dict[str, Any]:
    """
    Compare two subgraphs and compute a similarity score.

This method quantifies the similarity between two subgraphs using a combination
of structural and semantic features, providing detailed metrics to understand
how the subgraphs relate to each other.

Args:
    subgraph1 (GraphDataset): First subgraph to compare
    subgraph2 (GraphDataset): Second subgraph to compare
    comparison_method (str): Method to use for comparison
        - "structural": Compare only graph structure (node/edge types, connections)
        - "semantic": Compare only node semantics using vector similarity
        - "hybrid": Combine structural and semantic comparison (default)
    node_type_weights (Dict[str, float], optional): Weights for different node types
    edge_type_weights (Dict[str, float], optional): Weights for different edge types
    semantic_weight (float): Weight for semantic similarity (for hybrid method)
    structural_weight (float): Weight for structural similarity (for hybrid method)

Returns:
    Dict[str, Any]: Comparison results including:
        - overall_similarity: Overall similarity score (0-1)
        - structural_similarity: Structural similarity score (0-1)
        - semantic_similarity: Semantic similarity score (0-1) (if applicable)
        - node_type_overlap: Overlap of node types between graphs
        - edge_type_overlap: Overlap of edge types between graphs
        - shared_nodes: List of nodes present in both subgraphs
        - unique_nodes1: Nodes only in subgraph1
        - unique_nodes2: Nodes only in subgraph2

Example:
    # Extract two subgraphs
    query1 = np.array([0.9, 0.1, 0.0])
    query2 = np.array([0.1, 0.9, 0.0])
    subgraph1 = graph.semantic_subgraph(query1, 0.7)
    subgraph2 = graph.semantic_subgraph(query2, 0.7)

    # Compare the subgraphs
    comparison = graph.compare_subgraphs(
        subgraph1,
        subgraph2,
        comparison_method="hybrid",
        semantic_weight=0.6,
        structural_weight=0.4
    )

    print(f"Overall similarity: {comparison['overall_similarity']:.3f}")
    print(f"Shared nodes: {len(comparison['shared_nodes'])}")
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## convert_arrow_to_jsonl

```python
def convert_arrow_to_jsonl(self, table: "pa.Table", output_path: str) -> str:
    """
    Convert an Arrow table to a JSONL file.

Args:
    table (pa.Table): Arrow table to convert
    output_path (str): Path to the output JSONL file

Returns:
    str: Path to the created JSONL file

Raises:
    ImportError: If PyArrow is not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## convert_arrow_to_jsonl

```python
def convert_arrow_to_jsonl(self, table, output_path, compression = None):
    """
    Convert an Arrow table to a JSONL file.

Args:
    table (pyarrow.Table): Arrow table to convert
    output_path (str): Path to output JSONL file
    compression (str, optional): Compression format ("gzip", "bz2", "xz")

Returns:
    str: Path to the exported file
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## convert_jsonl_to_huggingface

```python
def convert_jsonl_to_huggingface(self, jsonl_path: str) -> Optional['Dataset']:
    """
    Convert a JSONL file to a HuggingFace dataset.

Args:
    jsonl_path (str): Path to the JSONL file

Returns:
    Dataset: HuggingFace dataset containing the data

Raises:
    ImportError: If HuggingFace datasets library is not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## convert_jsonl_to_huggingface

```python
def convert_jsonl_to_huggingface(self, input_path, compression = None):
    """
    Convert a JSONL file to a HuggingFace dataset.

Args:
    input_path (str): Path to input JSONL file
    compression (str, optional): Compression format ("gzip", "bz2", "xz")

Returns:
    datasets.Dataset: HuggingFace dataset

Raises:
    ImportError: If HuggingFace datasets is not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## cross_document_reasoning

```python
def cross_document_reasoning(self, query: str, document_node_types: List[str] = ['document', 'paper'], max_hops: int = 2, min_relevance: float = 0.6, max_documents: int = 5, reasoning_depth: str = "moderate") -> Dict[str, Any]:
    """
    Perform reasoning across multiple documents in the knowledge graph.

This method goes beyond simple document retrieval by connecting information
across multiple documents using their semantic relationships and shared entities.
It enables answering complex queries that require synthesizing information from
multiple sources.

Args:
    query: The natural language query to reason about.
    document_node_types: Types of nodes that represent documents in the graph.
    max_hops: Maximum number of hops between documents to consider.
    min_relevance: Minimum relevance score for documents to be included.
    max_documents: Maximum number of documents to reason across.
    reasoning_depth: Depth of reasoning ('basic', 'moderate', or 'deep').
        - 'basic': Simple connections between documents
        - 'moderate': Includes entity-mediated relationships
        - 'deep': Complex multi-hop reasoning with evidence chains

Returns:
    Dictionary containing the reasoning results, including:
        - 'answer': The synthesized answer to the query
        - 'documents': List of relevant documents used
        - 'evidence_paths': Paths connecting the information
        - 'confidence': Confidence score for the answer
        - 'reasoning_trace': Step-by-step reasoning process

Raises:
    ValueError: If no document nodes match the specified types.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## cross_modal_linking

```python
def cross_modal_linking(self, text_nodes: List[str], image_nodes: List[str], linking_method: str = "embedding", min_confidence: float = 0.7, max_links_per_node: int = 5, attributes_to_transfer: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Create semantic links between text and image nodes in the knowledge graph.

This method establishes cross-modal connections between text-based entities and
image-based entities, enabling joint querying across modalities.

Args:
    text_nodes (List[str]): List of text node IDs to link
    image_nodes (List[str]): List of image node IDs to link
    linking_method (str): Method for establishing links
        - "embedding": Use vector similarity between embeddings (default)
        - "metadata": Use matching attributes in node metadata
        - "hybrid": Combine embedding similarity and metadata matching
    min_confidence (float): Minimum confidence score for a link to be created
    max_links_per_node (int): Maximum number of links to create per node
    attributes_to_transfer (List[str], optional): Node attributes to copy to the edge properties

Returns:
    List[Dict[str, Any]]: List of created links with details:
        - source_node: Source node object
        - target_node: Target node object
        - edge_type: The relationship type created ("depicts" or "illustrated_by")
        - confidence: Confidence score (0-1)
        - method: Method used to establish the link

Example:
    # Create cross-modal links between article descriptions and images
    links = graph.cross_modal_linking(
        text_nodes=article_nodes,
        image_nodes=image_nodes,
        linking_method="hybrid",
        min_confidence=0.75,
        attributes_to_transfer=["topic", "date"]
    )

    # Print the established links
    for link in links:
        text_title = link["source_node"].data.get("title", "Unknown")
        image_id = link["target_node"].id
        print(f"Connected {text_title} to image {image_id} ({link['confidence']:.2f} confidence)")
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## deserialize_arrow_table

```python
def deserialize_arrow_table(self, cid):
    """
    Deserialize an Arrow table from IPLD.

Args:
    cid (str): CID of the root IPLD block

Returns:
    pyarrow.Table: The deserialized table

Raises:
    ImportError: If PyArrow is not available
    ValueError: If the IPLD block is not a valid Arrow table
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## deserialize_dataset_streaming

```python
def deserialize_dataset_streaming(self, cid):
    """
    Deserialize a dataset in streaming mode.

Args:
    cid (str): CID of the root IPLD block

Yields:
    pyarrow.Table: Chunks of the dataset
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## deserialize_graph_dataset

```python
def deserialize_graph_dataset(self, cid: str) -> GraphDataset:
    """
    Deserialize a graph dataset from IPLD.

Args:
    cid (str): CID of the root IPLD block

Returns:
    GraphDataset: The deserialized graph dataset
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## deserialize_huggingface_dataset

```python
def deserialize_huggingface_dataset(self, cid):
    """
    Deserialize a HuggingFace dataset from IPLD.

Args:
    cid (str): CID of the root IPLD block

Returns:
    datasets.Dataset: The deserialized dataset

Raises:
    ImportError: If HuggingFace datasets is not available
    ValueError: If the IPLD block is not a valid HuggingFace dataset
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## deserialize_jsonl

```python
def deserialize_jsonl(self, cid: str, output_path: Optional[str] = None) -> Union[List[Dict[str, Any]], str]:
    """
    Deserialize JSONL data from IPLD/IPFS.

Args:
    cid (str): CID of the serialized JSONL data
    output_path (str, optional): If provided, write the deserialized data to this path

Returns:
    Union[List[Dict], str]: List of records, or path to the output file if output_path is provided
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## deserialize_jsonl

```python
def deserialize_jsonl(self, cid, output_path = None, compression = None, max_records = None):
    """
    Deserialize a JSONL dataset from IPLD.

Args:
    cid (str): CID of the root IPLD block
    output_path (str, optional): Path to output JSONL file. If None, records are returned as a list.
    compression (str, optional): Compression format for output file ("gzip", "bz2", "xz")
    max_records (int, optional): Maximum number of records to retrieve

Returns:
    Union[str, List[Dict]]: Path to output file if output_path is specified, otherwise list of records

Raises:
    ValueError: If the IPLD block is not a valid JSONL dataset
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## deserialize_vectors

```python
def deserialize_vectors(self, cid: str) -> Tuple[List[np.ndarray], Optional[List[Dict[str, Any]]]]:
    """
    Deserialize vector embeddings from IPLD.

Args:
    cid (str): CID of the root IPLD block

Returns:
    Tuple[List[np.ndarray], Optional[List[Dict]]]: Vectors and metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## dfs

```python
def dfs(current_id, path, depth):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## edge_filter_func

```python
def edge_filter_func(props):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## edge_matches_filters

```python
def edge_matches_filters(edge_properties):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## enable_query_optimization

```python
def enable_query_optimization(self, vector_weight: float = 0.7, graph_weight: float = 0.3, cache_enabled: bool = True, cache_ttl: float = 300.0) -> None:
    """
    Enable query optimization for GraphRAG operations.

Args:
    vector_weight (float): Weight for vector similarity in hybrid queries
    graph_weight (float): Weight for graph structure in hybrid queries
    cache_enabled (bool): Whether to enable query caching
    cache_ttl (float): Time-to-live for cached results in seconds
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## enable_vector_partitioning

```python
def enable_vector_partitioning(self, num_partitions: int = 4) -> None:
    """
    Enable vector index partitioning for more efficient search in large datasets.

Args:
    num_partitions (int): Number of partitions to create
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## expand_query

```python
def expand_query(self, query_vector: np.ndarray, expansion_strategy: str = "neighbor_vectors", expansion_factor: float = 0.3, max_terms: int = 3, min_similarity: float = 0.7) -> np.ndarray:
    """
    Expand a query vector using information from the knowledge graph.

This method improves retrieval by expanding the original query vector with
related concepts from the graph, similar to how query expansion works in
traditional information retrieval but in the embedding space.

Args:
    query_vector (np.ndarray): Original query vector
    expansion_strategy (str): Strategy for expanding the query
        - "neighbor_vectors": Use vectors of neighboring nodes
        - "cluster_centroids": Use centroids of relevant clusters
        - "concept_enrichment": Emphasize conceptual dimensions
    expansion_factor (float): Weight of expansion terms relative to original query
    max_terms (int): Maximum number of expansion terms to include
    min_similarity (float): Minimum similarity threshold for expansion terms

Returns:
    np.ndarray: The expanded query vector
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## explain_path

```python
def explain_path(self, start_node_id: str, end_node_id: str, max_paths: int = 3, max_depth: int = 4) -> List[Dict[str, Any]]:
    """
    Generate explanations for paths between two nodes in the graph.

This method traces paths through the knowledge graph and explains the
relationships, supporting explainable reasoning in GraphRAG applications.

Args:
    start_node_id (str): ID of the starting node
    end_node_id (str): ID of the ending node
    max_paths (int): Maximum number of paths to return
    max_depth (int): Maximum path depth to explore

Returns:
    List[Dict]: List of path explanations containing:
        - nodes: List of nodes in the path
        - edges: List of edges in the path
        - explanation: Textual explanation of the path
        - confidence: Path quality score
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## export_to_car

```python
def export_to_car(self, output_path: str) -> str:
    """
    Export the vector-augmented graph dataset to a CAR file.

Args:
    output_path (str): Path for the output CAR file

Returns:
    str: CID of the root block in the CAR file
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## export_to_jsonl

```python
def export_to_jsonl(self, data: List[Dict[str, Any]], output_path: str) -> str:
    """
    Export data to a JSONL (JSON Lines) file.

Args:
    data (List[Dict]): List of JSON-serializable records
    output_path (str): Path to the output JSONL file

Returns:
    str: Path to the created JSONL file
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## export_to_jsonl

```python
def export_to_jsonl(self, data, output_path, orient = "records", lines = True, compression = None):
    """
    Export data to a JSONL file.

Args:
    data: Data to export (Arrow Table, HuggingFace Dataset, Pandas DataFrame, or dict)
    output_path (str): Path to output JSONL file
    orient (str): JSON orientation format (for pandas conversion)
    lines (bool): Whether to write JSON Lines format (one object per line)
    compression (str, optional): Compression format ("gzip", "bz2", "xz")

Returns:
    str: Path to the exported file

Raises:
    ValueError: If data type is not supported
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## find

```python
def find(x):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## find_entity_clusters

```python
def find_entity_clusters(self, similarity_threshold: float = 0.6, min_community_size: int = 2, max_communities: int = 10, relationship_weight: float = 0.3) -> List[Dict[str, Any]]:
    """
    Find clusters of semantically similar and structurally connected entities.

This method uses a combination of vector similarity and graph structure
to identify communities or clusters of related entities. It's useful for
discovering thematic groups in knowledge graphs.

Args:
    similarity_threshold (float): Minimum similarity for considering nodes related
    min_community_size (int): Minimum number of nodes in a community
    max_communities (int): Maximum number of communities to return
    relationship_weight (float): Weight given to structural relationships vs. semantic similarity

Returns:
    List[Dict]: List of community dictionaries with nodes, themes, and cohesion scores
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## find_neighbors_with_properties

```python
def find_neighbors_with_properties(self, node_id: str, node_property_filters: Optional[Dict[str, Any]] = None, edge_property_filters: Optional[Dict[str, Any]] = None, edge_types: Optional[List[str]] = None, max_distance: int = 1) -> List[GraphNode]:
    """
    Find neighbors of a node that match specific property criteria.

Args:
    node_id (str): Starting node ID
    node_property_filters (Dict, optional): Filters for node properties
    edge_property_filters (Dict, optional): Filters for edge properties
    edge_types (List[str], optional): Types of edges to follow
    max_distance (int): Maximum traversal distance

Returns:
    List[GraphNode]: List of matching neighbor nodes
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## find_paths

```python
def find_paths(self, start_node_id: str, end_node_id: str, edge_types: Optional[List[str]] = None, max_depth: int = 5, direction: str = "outgoing") -> List[List[Tuple[GraphNode, str, Dict[str, Any]]]]:
    """
    Find all paths between two nodes up to a maximum depth.

Args:
    start_node_id (str): Starting node ID
    end_node_id (str): Ending node ID
    edge_types (List[str], optional): Types of edges to follow. If None, follow all edge types.
    max_depth (int): Maximum path depth
    direction (str): "outgoing", "incoming", or "both"

Returns:
    List[List[Tuple[GraphNode, str, Dict]]]: List of paths, where each path is a list of
                                            (node, edge_type, edge_properties) tuples
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## find_similar_connected_nodes

```python
def find_similar_connected_nodes(self, query_vector: np.ndarray, max_hops: int = 2, min_similarity: float = 0.7, edge_filters: Optional[List[Tuple[str, str, Any]]] = None, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Find nodes that are both semantically similar to the query vector
and connected by specific relationship patterns.

This advanced GraphRAG search combines vector similarity with relationship patterns
to find semantically and structurally relevant nodes.

Args:
    query_vector (np.ndarray): Query vector for semantic search
    max_hops (int): Maximum number of hops in the relationship pattern
    min_similarity (float): Minimum semantic similarity threshold
    edge_filters (List[Tuple[str, str, Any]], optional): List of edge filters as
        triplets of (property_name, comparison_operator, value).
        Comparison operators: "=", "!=", ">", "<", ">=", "<=", "contains"
    max_results (int): Maximum number of results to return

Returns:
    List[Dict]: List of matching nodes with their similarity scores,
                connection paths, and combined relevance scores
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## from_knowledge_triples

```python
@classmethod
def from_knowledge_triples(cls, triples: List[Tuple[str, str, str, Dict[str, Any], Dict[str, Any]]], name: str = None, vector_dimension: int = 768, storage = None) -> "VectorAugmentedGraphDataset":
    """
    Create a vector-augmented graph dataset from knowledge triples.

Args:
    triples: List of (subject, predicate, object, subject_props, object_props) tuples
    name: Name for the dataset
    vector_dimension: Dimension for vector embeddings
    storage: Optional IPLD storage backend

Returns:
    VectorAugmentedGraphDataset: A new dataset populated with the triples
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## generate_contextual_embeddings

```python
def generate_contextual_embeddings(self, node_id: str, context_strategy: str = "neighborhood", context_depth: int = 1, edge_weight_property: Optional[str] = None) -> np.ndarray:
    """
    Generate enhanced embeddings for a node that incorporate contextual information from the graph.

This method creates an improved embedding that accounts for the node's structural context,
going beyond the basic embedding to capture relationship information.

Args:
    node_id (str): ID of the node to generate contextual embedding for
    context_strategy (str): Strategy for incorporating context
        - "neighborhood": Average embeddings from neighboring nodes
        - "weighted_edges": Weight neighboring nodes by edge properties
        - "type_specific": Apply different weights based on node types
    context_depth (int): Depth of neighborhood to consider for context
    edge_weight_property (str, optional): Edge property to use for weighting

Returns:
    np.ndarray: The contextual embedding vector
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## get_edge_properties

```python
def get_edge_properties(self, target_id: str, edge_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get properties of an edge to a specific target node.

Args:
    target_id (str): ID of the target node
    edge_type (str, optional): Type of the edge. If None, search all edge types.

Returns:
    Optional[Dict]: Edge properties, or None if no matching edge exists
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphNode

## get_edges

```python
def get_edges(self, edge_type: Optional[str] = None) -> List[Tuple['GraphNode', Dict[str, Any]]]:
    """
    Get all edges of a specified type, or all edges if no type is specified.

Args:
    edge_type (str, optional): Type of edges to retrieve. If None, get all edges.

Returns:
    List[Tuple[GraphNode, Dict]]: List of (target_node, edge_properties) tuples
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphNode

## get_edges_by_property

```python
def get_edges_by_property(self, edge_type: str, property_name: str, property_value: Any) -> List[Tuple[GraphNode, GraphNode, Dict[str, Any]]]:
    """
    Get all edges of a given type with a specific property value.

Args:
    edge_type (str): Edge type
    property_name (str): Property name
    property_value (Any): Property value

Returns:
    List[Tuple[GraphNode, GraphNode, Dict]]: List of (source, target, properties) tuples
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## get_edges_by_type

```python
def get_edges_by_type(self, edge_type: str) -> List[Tuple[GraphNode, GraphNode, Dict[str, Any]]]:
    """
    Get all edges of a given type.

Args:
    edge_type (str): Edge type

Returns:
    List[Tuple[GraphNode, GraphNode, Dict]]: List of (source, target, properties) tuples
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## get_embeddings

```python
def get_embeddings(texts):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_neighbors

```python
def get_neighbors(self, edge_type: Optional[str] = None) -> List['GraphNode']:
    """
    Get all neighbor nodes connected by edges of a specified type,
or all neighbors if no type is specified.

Args:
    edge_type (str, optional): Type of edges to traverse. If None, use all edges.

Returns:
    List[GraphNode]: List of connected nodes
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphNode

## get_node

```python
def get_node(self, node_id: str) -> Optional[GraphNode]:
    """
    Get a node by ID.

Args:
    node_id (str): Node ID

Returns:
    Optional[GraphNode]: The node, or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## get_nodes_by_property

```python
def get_nodes_by_property(self, property_name: str, property_value: Any) -> List[GraphNode]:
    """
    Get all nodes with a specific property value.

Args:
    property_name (str): Property name
    property_value (Any): Property value

Returns:
    List[GraphNode]: List of nodes
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## get_nodes_by_type

```python
def get_nodes_by_type(self, node_type: str) -> List[GraphNode]:
    """
    Get all nodes of a given type.

Args:
    node_type (str): Node type

Returns:
    List[GraphNode]: List of nodes
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## graph_rag_search

```python
def graph_rag_search(self, query_vector: np.ndarray, max_vector_results: int = 5, max_traversal_depth: int = 2, edge_types: Optional[List[str]] = None, min_similarity: float = 0.5, use_optimizer: bool = False) -> List[Tuple[GraphNode, float, List[GraphNode]]]:
    """
    Perform a hybrid search combining vector similarity and graph traversal.

Args:
    query_vector (np.ndarray): Query vector
    max_vector_results (int): Maximum number of initial vector similarity matches
    max_traversal_depth (int): Maximum traversal depth from each similarity match
    edge_types (List[str], optional): Types of edges to follow. If None, follow all edge types.
    min_similarity (float): Minimum similarity score for initial vector matches
    use_optimizer (bool): Whether to use the query optimizer if available

Returns:
    List[Tuple[GraphNode, float, List[GraphNode]]]:
        List of (node, similarity, context_path) tuples
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## hierarchical_path_search

```python
def hierarchical_path_search(self, query_vector: np.ndarray, target_node_types: Optional[List[str]] = None, max_results: int = 10, guidance_properties: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """
    Perform hierarchical path search combining semantic search with graph navigation.

This method searches for relevant paths through the graph by combining vector
similarity with guided path traversal through concept hierarchies.

Args:
    query_vector (np.ndarray): Query vector for semantic similarity
    target_node_types (List[str], optional): Types of target nodes to find (e.g., ["paper"])
    max_results (int): Maximum number of paths to return
    guidance_properties (Dict[str, float], optional): Edge properties to guide traversal with weights
        Example: {"relevance": 1.0, "importance": 0.8}

Returns:
    List[Dict[str, Any]]: Ranked paths through the concept hierarchy, including:
        - path: List of nodes in the path
        - transitions: List of edge types connecting nodes in the path
        - overall_score: Combined semantic and structural score
        - semantic_score: Contribution from semantic similarity
        - structural_score: Contribution from graph structure
        - end_node: Final node in the path

Example:
    # Search for papers relevant to "neural networks" by tracing through concept hierarchy
    query_embedding = embed("neural networks")

    paths = graph.hierarchical_path_search(
        query_vector=query_embedding,
        target_node_types=["paper"],
        guidance_properties={"centrality": 1.0, "relevance": 0.8}
    )

    # Print the best path
    best_path = paths[0]
    print(f"Best path (score: {best_path['overall_score']:.3f}):")
    for i, node in enumerate(best_path['path']):
        node_name = node.data.get('name', node.data.get('title', node.id))
        if i < len(best_path['transitions']):
            print(f"  {node_name} -[{best_path['transitions'][i]}]-> ", end="")
        else:
            print(f"{node_name}")
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## hybrid_structured_semantic_search

```python
def hybrid_structured_semantic_search(self, query_vector: np.ndarray, node_filters: Optional[List[Tuple[str, str, Any]]] = None, relationship_patterns: Optional[List[Dict[str, Any]]] = None, max_results: int = 10, min_similarity: float = 0.6) -> List[Dict[str, Any]]:
    """
    Perform a hybrid search combining semantic similarity with structured filters and graph patterns.

This advanced search method integrates vector similarity with property-based filtering
and relationship pattern matching, enabling highly precise GraphRAG queries that combine
all aspects of knowledge graph and vector search.

Args:
    query_vector (np.ndarray): Query vector for semantic similarity
    node_filters (List[Tuple], optional): List of node property filters as
        triplets of (property_path, comparison_operator, value).
        Property path can include nested attributes using dot notation (e.g., "metadata.date")
        Comparison operators: "=", "!=", ">", "<", ">=", "<=", "contains", "startswith", "endswith"
    relationship_patterns (List[Dict], optional): List of relationship patterns to match, with each
        pattern specified as a dictionary with the following keys:
        - direction: "outgoing", "incoming", or "any"
        - edge_type: The type of edge, or None to match any type
        - target_filters: Optional list of property filters for target nodes
        - edge_filters: Optional list of property filters for edges
        - hops: Optional integer specifying number of hops (default: 1)
    max_results (int): Maximum number of results to return
    min_similarity (float): Minimum semantic similarity threshold

Returns:
    List[Dict]: List of matching nodes with their similarity scores and matched patterns

Example:
    ```python
    # Find research papers related to AI that cite papers from before 2020
    # and have at least 10 citations
    results = dataset.hybrid_structured_semantic_search(
        query_vector=ai_vector,
        node_filters=[
            ("type", "=", "research_paper"),
            ("citation_count", ">=", 10)
        ],
        relationship_patterns=[
            {
                "direction": "outgoing",
                "edge_type": "cites",
                "target_filters": [
                    ("publication_date", "<", "2020-01-01")
                ]
            }
        ]
    )
    ```
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## import_from_car

```python
@classmethod
def import_from_car(cls, car_path: str, storage = None) -> "VectorAugmentedGraphDataset":
    """
    Import a vector-augmented graph dataset from a CAR file.

Args:
    car_path (str): Path to the CAR file
    storage (IPLDStorage, optional): IPLD storage backend

Returns:
    VectorAugmentedGraphDataset: The imported dataset
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## import_from_jsonl

```python
def import_from_jsonl(self, jsonl_path: str) -> Optional['pa.Table']:
    """
    Import data from a JSONL file to an Arrow table.

Args:
    jsonl_path (str): Path to the JSONL file

Returns:
    pa.Table: Arrow table containing the data

Raises:
    ImportError: If PyArrow is not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## import_from_jsonl

```python
def import_from_jsonl(self, input_path, schema = None, compression = None, infer_schema = True, max_rows_for_inference = 1000):
    """
    Import data from a JSONL file.

Args:
    input_path (str): Path to input JSONL file
    schema (pyarrow.Schema, optional): Schema for the data
    compression (str, optional): Compression format ("gzip", "bz2", "xz")
    infer_schema (bool): Whether to infer schema from the data
    max_rows_for_inference (int): Maximum number of rows to read for schema inference

Returns:
    pyarrow.Table: Imported data as an Arrow table

Raises:
    ImportError: If PyArrow is not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## import_knowledge_graph

```python
def import_knowledge_graph(self, knowledge_graph, embedding_model = None) -> List[str]:
    """
    Import a KnowledgeGraph into the vector-augmented graph dataset.

Args:
    knowledge_graph: KnowledgeGraph to import
    embedding_model: Model to use for generating embeddings (if not provided in KG)

Returns:
    List[str]: List of entity IDs that were added
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## incremental_graph_update

```python
def incremental_graph_update(self, nodes_to_add: List[GraphNode] = None, edges_to_add: List[Tuple[str, str, str, Dict[str, Any]]] = None, nodes_to_remove: List[str] = None, edges_to_remove: List[Tuple[str, str, str]] = None, maintain_index: bool = True) -> Tuple[int, int, int, int]:
    """
    Incrementally update the graph while maintaining vector indices.

This method efficiently handles batch updates to the graph structure
without requiring a full rebuilding of vector indices.

Args:
    nodes_to_add (List[GraphNode]): List of nodes to add
    edges_to_add (List[Tuple]): List of (source_id, edge_type, target_id, properties) tuples
    nodes_to_remove (List[str]): List of node IDs to remove
    edges_to_remove (List[Tuple]): List of (source_id, edge_type, target_id) tuples
    maintain_index (bool): Whether to maintain the vector index integrity

Returns:
    Tuple[int, int, int, int]:
        (nodes_added, edges_added, nodes_removed, edges_removed)
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## knowledge_graph_completion

```python
def knowledge_graph_completion(self, completion_method: str = "semantic", target_relation_types: Optional[List[str]] = None, min_confidence: float = 0.7, max_candidates: int = 50, use_existing_edges_as_training: bool = True) -> List[Dict[str, Any]]:
    """
    Predict missing edges in the knowledge graph.

This method analyzes the graph structure and node embeddings to suggest
potentially missing relationships with confidence scores.

Args:
    completion_method (str): Method for edge prediction
        - "semantic": Use vector similarity to predict edges
        - "structural": Use graph structure patterns to predict edges
        - "combined": Use both semantic and structural information
    target_relation_types (List[str], optional): Types of edges to predict
    min_confidence (float): Minimum confidence score for predictions
    max_candidates (int): Maximum number of edge candidates to return
    use_existing_edges_as_training (bool): Use existing edges to validate prediction quality

Returns:
    List[Dict[str, Any]]: List of predicted edges with:
        - source_node: The source node object
        - target_node: The target node object
        - relation_type: Predicted edge type
        - confidence: Confidence score (0-1)
        - explanation: Brief explanation of the prediction

Example:
    # Predict missing citation edges in a paper citation network
    predicted_edges = graph.knowledge_graph_completion(
        completion_method="combined",
        target_relation_types=["cites"],
        min_confidence=0.8
    )

    # Print predicted edges
    for prediction in predicted_edges[:5]:
        source = prediction["source_node"].data["title"]
        target = prediction["target_node"].data["title"]
        print(f"{source} should cite {target} (confidence: {prediction['confidence']:.2f})")
        print(f"Reason: {prediction['explanation']}")
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## load_from_ipfs

```python
@classmethod
def load_from_ipfs(cls, cid: str, storage = None) -> "VectorAugmentedGraphDataset":
    """
    Load a vector-augmented graph dataset from IPFS.

Args:
    cid (str): CID of the dataset
    storage (IPLDStorage, optional): IPLD storage backend

Returns:
    VectorAugmentedGraphDataset: The loaded dataset
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## logical_query

```python
def logical_query(self, query_vectors: List[np.ndarray], operators: List[str], similarity_threshold: float = 0.7, max_results: int = 10) -> List[Tuple[GraphNode, float]]:
    """
    Perform logical operations (AND, OR, NOT) with multiple query vectors.

This method allows combining multiple semantic queries with logical operations,
enabling more precise GraphRAG searches with compound conditions.

Args:
    query_vectors (List[np.ndarray]): List of query vectors
    operators (List[str]): Logical operators between vectors ('AND', 'OR', 'NOT')
        Must be one less than the number of query_vectors
    similarity_threshold (float): Minimum similarity score for inclusion
    max_results (int): Maximum number of results to return

Returns:
    List[Tuple[GraphNode, float]]: List of (node, combined_score) tuples

Example:
    ```python
    # Find nodes similar to vector1 AND vector2 but NOT vector3
    results = dataset.logical_query(
        query_vectors=[vector1, vector2, vector3],
        operators=["AND", "NOT"],
        similarity_threshold=0.7
    )
    ```
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## match_edge_filter

```python
def match_edge_filter(edge_properties, filter_condition):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## match_edge_filter

```python
def match_edge_filter(edge_properties, filter_condition):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## match_property_filter

```python
def match_property_filter(node, filter_condition):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## matches_relationship_pattern

```python
def matches_relationship_pattern(node, pattern):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## merge

```python
def merge(self, other: "GraphDataset", resolve_conflicts: str = "keep_existing") -> "GraphDataset":
    """
    Merge another graph dataset into this one.

Args:
    other (GraphDataset): The graph dataset to merge
    resolve_conflicts (str): How to resolve node ID conflicts
        - "keep_existing": Keep existing nodes (default)
        - "replace": Replace with nodes from other graph
        - "merge_properties": Merge properties of conflicting nodes

Returns:
    GraphDataset: Self, after merging
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## multi_hop_inference

```python
def multi_hop_inference(self, start_node_id: str, relationship_pattern: List[str], confidence_threshold: float = 0.5, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Infer multi-hop relationships that may not be explicitly present in the graph.

This method follows a specified relationship pattern across multiple hops to
infer potential connections between nodes, even if they are not directly connected.
It assigns confidence scores based on the strength of the path.

Args:
    start_node_id (str): ID of the starting node
    relationship_pattern (List[str]): Sequence of relationship types to follow
    confidence_threshold (float): Minimum confidence score for inferred relationships
    max_results (int): Maximum number of results to return

Returns:
    List[Dict]: List of inferred relationships with nodes, paths, and confidence scores

Example:
    ```python
    # Infer "may_collaborate_with" relationships using the pattern ["authored", "cites", "authored_by"]
    potential_collaborators = graph.multi_hop_inference(
        start_node_id="author1",
        relationship_pattern=["authored", "cites", "authored_by"],
        confidence_threshold=0.6
    )
    ```
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## node_filter_func

```python
def node_filter_func(node):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## node_matches_filters

```python
def node_matches_filters(node, filters):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## query

```python
def query(self, query: Dict[str, Any]) -> List[GraphNode]:
    """
    Query nodes by multiple criteria.

Args:
    query (Dict): Query conditions with property names and values

Returns:
    List[GraphNode]: List of matching nodes
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## rank_nodes_by_centrality

```python
def rank_nodes_by_centrality(self, query_vector: Optional[np.ndarray] = None, alpha: float = 0.85, max_iterations: int = 50, tolerance: float = 1e-06, damping_by_similarity: bool = False, weight_by_edge_properties: Optional[Dict[str, str]] = None) -> List[Tuple[GraphNode, float]]:
    """
    Ranks nodes by their centrality in the graph, optionally influenced by semantic similarity.

This method implements a version of the PageRank algorithm, optionally incorporating
semantic similarity to the query vector. It can be used to find the most important
nodes in the context of a specific query.

Args:
    query_vector (np.ndarray, optional): Query vector for semantic similarity component
    alpha (float): Damping factor for PageRank algorithm (default: 0.85)
    max_iterations (int): Maximum number of iterations for convergence (default: 50)
    tolerance (float): Convergence threshold (default: 1e-6)
    damping_by_similarity (bool): If True, damping factor is adjusted by semantic similarity
    weight_by_edge_properties (Dict[str, str], optional): Dictionary mapping edge types to
        property names whose values will be used as edge weights (e.g., {"cites": "importance"})

Returns:
    List[Tuple[GraphNode, float]]: List of (node, centrality_score) tuples, sorted by score
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## resolve_entities

```python
def resolve_entities(self, candidate_nodes: List[GraphNode], resolution_strategy: str = "vector_similarity", similarity_threshold: float = 0.8, property_weights: Optional[Dict[str, float]] = None) -> Dict[str, List[GraphNode]]:
    """
    Perform entity resolution to identify and group duplicate/equivalent entities.

This method identifies entities in the graph that likely refer to the same real-world
entity, enabling deduplication and linking of equivalent nodes.

Args:
    candidate_nodes (List[GraphNode]): List of nodes to perform resolution on
    resolution_strategy (str): Strategy for entity resolution
        - "vector_similarity": Use vector similarity to identify duplicates
        - "property_matching": Match based on property values
        - "hybrid": Combine vector similarity and property matching
    similarity_threshold (float): Minimum similarity threshold for considering entities equivalent
    property_weights (Dict[str, float], optional): Weights for different properties when using
        property-based matching or hybrid approaches

Returns:
    Dict[str, List[GraphNode]]: Dictionary mapping canonical entity IDs to lists of equivalent nodes
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## save_to_ipfs

```python
def save_to_ipfs(self) -> str:
    """
    Save the vector-augmented graph dataset to IPFS.

Returns:
    str: CID of the saved dataset
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## schema_based_validation

```python
def schema_based_validation(self, node_schemas: Optional[Dict[str, Dict[str, Any]]] = None, edge_schemas: Optional[Dict[str, Dict[str, Any]]] = None, fix_violations: bool = False, validation_mode: str = "strict") -> Dict[str, Any]:
    """
    Validate the graph against schemas and optionally fix violations.

This method enforces data quality by validating node and edge properties
against defined schemas, and can automatically fix common issues.

Args:
    node_schemas (Dict[str, Dict], optional): Schema definitions for node types
        Format: {node_type: {property_name: {type, required, default, enum, ...}}}
    edge_schemas (Dict[str, Dict], optional): Schema definitions for edge types
        Format: {edge_type: {property_name: {type, required, default, enum, ...}}}
    fix_violations (bool): Whether to automatically fix schema violations
    validation_mode (str):
        - "strict": Enforce all schema rules
        - "warn": Report violations but don't raise errors
        - "minimal": Only validate required fields

Returns:
    Dict[str, Any]: Validation results including:
        - valid (bool): Whether the graph is valid
        - node_violations: Dict of violations by node
        - edge_violations: Dict of violations by edge
        - fixed_violations: Count of fixed violations (if fix_violations=True)
        - schema_coverage: Percentage of graph covered by schemas

Example:
    # Define schemas for papers and authors
    node_schemas = {
        "paper": {
            "title": {"type": "string", "required": True},
            "year": {"type": "number", "required": True, "min": 1900, "max": 2023},
            "citations": {"type": "number", "default": 0}
        },
        "author": {
            "name": {"type": "string", "required": True},
            "affiliation": {"type": "string"},
            "h_index": {"type": "number", "min": 0}
        }
    }

    # Define schemas for relationships
    edge_schemas = {
        "authored": {
            "contribution": {"type": "string", "enum": ["first", "corresponding", "contributing"]}
        },
        "cites": {
            "context": {"type": "string"},
            "page": {"type": "number", "min": 1}
        }
    }

    # Validate the graph
    validation = graph.schema_based_validation(
        node_schemas=node_schemas,
        edge_schemas=edge_schemas,
        fix_violations=True
    )

    if validation["valid"]:
        print("Graph is valid!")
    else:
        print(f"Found {len(validation['node_violations'])} node violations")
        print(f"Found {len(validation['edge_violations'])} edge violations")
        print(f"Fixed {validation['fixed_violations']} violations")
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## search_with_weighted_paths

```python
def search_with_weighted_paths(self, query_vector: np.ndarray, max_initial_results: int = 10, max_path_length: int = 3, path_weight_strategy: str = "decay", relation_weights: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """
    Search for paths in the graph starting from vector similarity matches,
with weights applied to paths based on semantic relevance and path properties.

Args:
    query_vector (np.ndarray): Query vector
    max_initial_results (int): Maximum number of initial vector similarity matches
    max_path_length (int): Maximum path length to consider
    path_weight_strategy (str): Strategy for weighting paths
        - "decay": Weight decays with path length
        - "avg": Average semantic scores along path
        - "min": Minimum semantic score along path
    relation_weights (Dict[str, float], optional): Weights for different relation types

Returns:
    List[Dict]: List of results with weighted paths
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## semantic_subgraph

```python
def semantic_subgraph(self, query_vector: np.ndarray, similarity_threshold: float = 0.7, include_connections: bool = True, max_distance: int = 2) -> "GraphDataset":
    """
    Extract a subgraph containing nodes semantically similar to the query vector
and their connections.

This creates a focused knowledge graph around semantically relevant entities.

Args:
    query_vector (np.ndarray): Query vector for semantic search
    similarity_threshold (float): Minimum similarity threshold for inclusion
    include_connections (bool): Whether to include connections between similar nodes
    max_distance (int): Maximum distance for connections to include

Returns:
    GraphDataset: Subgraph containing semantically similar nodes and connections
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## serialize_arrow_table

```python
def serialize_arrow_table(self, table, hash_columns = None):
    """
    Serialize an Arrow table to IPLD.

Args:
    table: pyarrow.Table to serialize
    hash_columns (List[str], optional): Columns to use for content addressing

Returns:
    str: CID of the root IPLD block

Raises:
    ImportError: If PyArrow is not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## serialize_dataset_streaming

```python
def serialize_dataset_streaming(self, chunks_iter):
    """
    Serialize a dataset in streaming mode.

This allows processing of large datasets without loading them fully into memory.

Args:
    chunks_iter: Iterator yielding chunks of the dataset (as Arrow tables)

Returns:
    str: CID of the root IPLD block
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## serialize_graph_dataset

```python
def serialize_graph_dataset(self, graph: GraphDataset) -> str:
    """
    Serialize a graph dataset to IPLD.

Args:
    graph (GraphDataset): Graph dataset to serialize

Returns:
    str: CID of the root IPLD block
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## serialize_huggingface_dataset

```python
def serialize_huggingface_dataset(self, dataset, split = "train", hash_columns = None):
    """
    Serialize a HuggingFace dataset to IPLD.

Args:
    dataset: datasets.Dataset to serialize
    split (str, optional): Split to serialize. Only used for DatasetDict.
    hash_columns (List[str], optional): Columns to use for content addressing

Returns:
    str: CID of the root IPLD block

Raises:
    ImportError: If HuggingFace datasets is not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## serialize_jsonl

```python
def serialize_jsonl(self, jsonl_path: str) -> str:
    """
    Serialize a JSONL file to IPLD for storage on IPFS.

Args:
    jsonl_path (str): Path to the JSONL file

Returns:
    str: CID of the serialized data
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## serialize_jsonl

```python
def serialize_jsonl(self, input_path, hash_records = True, compression = None, batch_size = 1000):
    """
    Serialize a JSONL file to IPLD with efficient streaming.

Args:
    input_path (str): Path to input JSONL file
    hash_records (bool): Whether to hash individual records for content addressing
    compression (str, optional): Compression format of the input file ("gzip", "bz2", "xz")
    batch_size (int): Number of records per batch for streaming processing

Returns:
    str: CID of the root IPLD block

Raises:
    ImportError: If PyArrow is not available for optimized processing
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## serialize_vectors

```python
def serialize_vectors(self, vectors: List[np.ndarray], metadata: Optional[List[Dict[str, Any]]] = None) -> str:
    """
    Serialize vector embeddings to IPLD.

Args:
    vectors (List[np.ndarray]): List of vectors
    metadata (List[Dict], optional): Metadata for each vector

Returns:
    str: CID of the root IPLD block
    """
```
* **Async:** False
* **Method:** True
* **Class:** DatasetSerializer

## subgraph

```python
def subgraph(self, node_ids: List[str]) -> "GraphDataset":
    """
    Create a subgraph containing only the specified nodes and their interconnecting edges.

Args:
    node_ids (List[str]): List of node IDs to include in the subgraph

Returns:
    GraphDataset: A new graph dataset containing only the specified nodes
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## temporal_graph_analysis

```python
def temporal_graph_analysis(self, time_property: str, time_intervals: List[Tuple[Any, Any]], node_filters: Optional[List[Tuple[str, str, Any]]] = None, metrics: List[str] = ['node_count', 'edge_count', 'density', 'centrality'], reference_node_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze the evolution of the knowledge graph over time.

This method creates snapshots of the graph at different time intervals and
computes metrics to track how the graph structure evolves.

Args:
    time_property (str): Node property used for temporal information (e.g., "year", "timestamp")
    time_intervals (List[Tuple]): List of (start, end) time intervals to analyze
    node_filters (List[Tuple], optional): Additional filters to apply when selecting nodes
    metrics (List[str]): List of metrics to compute for each time snapshot
    reference_node_id (str, optional): Node to track across time intervals (for centrality/importance)

Returns:
    Dict[str, Any]: Analysis results including:
        - snapshots: List of graph metrics at each time interval
        - trends: Changes in key metrics over time
        - reference_node_metrics: Evolution of the reference node (if provided)

Example:
    # Analyze a research paper graph over different years
    time_analysis = graph.temporal_graph_analysis(
        time_property="year",
        time_intervals=[(2018, 2019), (2019, 2020), (2020, 2021), (2021, 2022)],
        metrics=["node_count", "edge_count", "density", "centrality"],
        reference_node_id="paper1"  # Track specific paper over time
    )

    # Print key metrics over time
    for i, snapshot in enumerate(time_analysis["snapshots"]):
        print(f"Time period {i+1}: {snapshot['interval']}")
        print(f"  Nodes: {snapshot['node_count']}")
        print(f"  Edges: {snapshot['edge_count']}")
        print(f"  Density: {snapshot['density']:.3f}")
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to a dictionary representation.

Returns:
    Dict: Dictionary representation of the node
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphNode

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to a dictionary representation.

Returns:
    Dict: Dictionary representation of the graph
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## traverse

```python
def traverse(self, start_node_id: str, edge_type: Optional[str] = None, direction: str = "outgoing", max_depth: int = 1, filter_func: Optional[Callable[[GraphNode], bool]] = None, edge_filter_func: Optional[Callable[[Dict[str, Any]], bool]] = None) -> List[GraphNode]:
    """
    Traverse the graph starting from a node.

Args:
    start_node_id (str): Starting node ID
    edge_type (str, optional): Type of edges to follow. If None, follow all edge types.
    direction (str): "outgoing", "incoming", or "both"
    max_depth (int): Maximum traversal depth
    filter_func (Callable, optional): Function to filter nodes during traversal
    edge_filter_func (Callable, optional): Function to filter edges during traversal

Returns:
    List[GraphNode]: List of nodes reached by traversal
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphDataset

## union

```python
def union(x, y):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## update_node_embedding

```python
def update_node_embedding(self, node_id: str, embedding: np.ndarray) -> bool:
    """
    Update the embedding for an existing node.

Args:
    node_id (str): ID of the node to update
    embedding (np.ndarray): New vector embedding

Returns:
    bool: True if successful, False otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset

## vector_search

```python
def vector_search(self, query_vector: np.ndarray, k: int = 10) -> List[Tuple[GraphNode, float]]:
    """
    Search for nodes with embeddings similar to the query vector.

Args:
    query_vector (np.ndarray): Query vector
    k (int): Number of results to return

Returns:
    List[Tuple[GraphNode, float]]: List of (node, similarity) tuples
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorAugmentedGraphDataset
