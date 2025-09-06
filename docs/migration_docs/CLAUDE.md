# IPFS Datasets Python - Development Guide

## Project Overview
This repository serves as a facade to multiple data processing and storage libraries:
- DuckDB, Arrow, and HuggingFace Datasets for data manipulation
- IPLD for data structuring
- IPFS (via ipfs_datasets_py.ipfs_kit) for decentralized storage
- libp2p (via ipfs_datasets_py.libp2p_kit) for peer-to-peer data transfer
- InterPlanetary Wayback (IPWB) for web archive integration

The primary goal is to provide a unified interface for data processing and distribution across decentralized networks, with seamless conversion between formats and storage systems.


### Build & Test Commands
- **Install**: `pip install -e .`
- **Build**: `python setup.py build`
- **Run all tests**: `python -m test.test`
- **Run single test**: `python -m test.test_ipfs_kit` or `python -m test.test_storacha_kit`
- **Run API server**: `uvicorn ipfs_kit_py.api:app --reload --port 8000`
- **Generate AST**: `python -m astroid ipfs_kit_py > ast_analysis.json`
- **Check for duplications**: `pylint --disable=all --enable=duplicate-code ipfs_kit_py`

### Development Guidelines
- **Test-First Development**: All new features must first be developed in the test/ folder
- **Feature Isolation**: Do not modify code outside of test/ until fully debugged
- **API Exposure**: All functionality should be exposed via FastAPI endpoints
- **Performance Focus**: Use memory-mapped structures and Arrow C Data Interface for low-latency IPC
- **Code Analysis**: Maintain an abstract syntax tree (AST) of the project to identify and prevent code duplication
- **DRY Principle**: Use the AST to enforce Don't Repeat Yourself by detecting similar code structures

### Testing Strategy

The project follows a comprehensive testing approach to ensure reliability and maintainability:

#### Test Organization
- **Unit Tests**: Located in the `test/` directory with file naming pattern `test_*.py`
- **Integration Tests**: Also in `test/` but focused on component interactions
- **Performance Tests**: Specialized tests for measuring throughput and latency

#### Recent Test Improvements
- **Mock Integration**: Fixed PyArrow mocking for cluster state helpers
- **Role-Based Architecture**: Improved fixtures for master/worker/leecher node testing
- **Gateway Compatibility**: Enhanced testing with proper filesystem interface mocking
- **LibP2P Integration**: Fixed tests to work without external dependencies
- **Parameter Validation**: Corrected constructor argument handling in tests
- **Interface Focus**: Made tests more resilient to implementation changes by focusing on behaviors rather than implementation details

#### Test Patterns
1. **Fixture-Based Testing**: Use pytest fixtures for test setup and teardown
2. **Mocking IPFS Daemon**: Use subprocess mocking to avoid actual daemon dependency
3. **Property-Based Testing**: Use hypothesis for edge case discovery
4. **Snapshot Testing**: For configuration and schema verification
5. **Parallelized Test Execution**: For faster feedback cycles
6. **PyArrow Patching**: Special handling for PyArrow Schema objects and Table methods
7. **Logging Suppression**: Context managers to control test output noise

#### PyArrow Testing Strategy
The tests must handle PyArrow's immutable Schema objects during mocking. Key approaches:

1. **MonkeyPatching**: Using pytest's monkeypatch fixture to safely patch immutable types
2. **Schema Equality Override**: Custom equality checks that handle MagicMock objects
3. **Schema Type Conversion**: Automatic conversion from MagicMock schemas to real PyArrow schemas
4. **Error Handling**: Special handling for PyArrow's strict type checking errors
5. **Cleanup Patching**: Custom cleanup methods to prevent errors during test teardown

#### Continuous Integration Integration
- Tests are run on every PR and commit to main branch
- Test reports and coverage metrics are generated automatically
- Performance regression tests compare against baseline benchmarks

## Code Style Guidelines
- **Imports**: Standard library first, third-party next, project imports last
- **Variables/Functions**: Use snake_case
- **Classes**: Use snake_case (this is project-specific, differs from PEP 8)
- **Indentation**: 4 spaces, no tabs
- **Error Handling**: Use try/except blocks, catch specific exceptions when possible
- **No Type Annotations**: Project doesn't use typing hints
- **Docstrings**: Not consistently used

The project is a wrapper around HuggingFace Transformers that adds IPFS model management capabilities, allowing models to be downloaded from HTTP/S3/IPFS based on availability and speed.

### API Integration Points
- **IPFS HTTP API**: REST interface (localhost:5001/api/v0) for core IPFS operations
- **IPFS Cluster API**: REST interface (localhost:9094/api/v0) for cluster coordination
- **IPFS Cluster Proxy**: Proxied IPFS API (localhost:9095/api/v0)
- **IPFS Gateway**: Content retrieval via HTTP (localhost:8080/ipfs/[cid])
- **IPFS Socket Interface**: Unix socket for high-performance local communication (/ip4/127.0.0.1/tcp/4001)
- **IPFS Unix Socket API**: On Linux, Kubo can be configured to expose its API via a Unix domain socket instead of HTTP, providing lower-latency communication for local processes. This can be configured in the IPFS config file by modifying the `API.Addresses` field to include a Unix socket path (e.g., `/unix/path/to/socket`).

These APIs enable creating "swarms of swarms" by allowing distributed clusters to communicate across networks and coordinate content pinning, replication, and routing across organizational boundaries. Socket interfaces provide lower-latency communication for high-performance local operations, with Unix domain sockets being particularly efficient for inter-process communication on the same machine.

## IPFS Core Concepts

The IPFS (InterPlanetary File System) architecture is built on several key concepts and components that are essential to understand for effective implementation:

### Content Addressing
- **Content Identifiers (CIDs)**: Unique fingerprints of content based on cryptographic hashes
- **Multihash Format**: Extensible hashing format supporting multiple hash algorithms (default: SHA-256)
- **Base32/Base58 Encoding**: Human-readable representations of binary CIDs
- **Version Prefixes**: CIDv0 (base58btc-encoded SHA-256) vs CIDv1 (self-describing, supports multicodec)

### Data Structures
- **Merkle DAG (Directed Acyclic Graph)**: Core data structure for content-addressed storage
- **IPLD (InterPlanetary Linked Data)**: Framework for creating data models with content-addressable linking
- **UnixFS**: File system abstraction built on IPLD for representing traditional files/directories
- **Blocks**: Raw data chunks that form the atomic units of the Merkle DAG

### Network Components
- **DHT (Distributed Hash Table)**: Distributed key-value store for content routing
- **Bitswap**: Protocol for exchanging blocks between peers
- **libp2p**: Modular networking stack powering IPFS peer-to-peer communication
- **MultiFormats**: Self-describing protocols, formats, and addressing schemes
- **IPNS (InterPlanetary Name System)**: Mutable naming system for content addressing

### Node Types
- **Full Nodes**: Store and serve content, participate in DHT
- **Gateway Nodes**: Provide HTTP access to IPFS content
- **Client Nodes**: Lightweight nodes that rely on others for content routing/storage
- **Bootstrap Nodes**: Well-known nodes that help new nodes join the network
- **Relay Nodes**: Assist with NAT traversal and indirect connections

### Key Operations
- **Adding Content**: Hash-based deduplication and chunking strategies
- **Retrieving Content**: Resolution process from CID to data
- **Pinning**: Mechanism to prevent content from being garbage collected
- **Publishing**: Making content discoverable through DHT/IPNS
- **Garbage Collection**: Process for reclaiming storage from unpinned content

## Testing
```bash
python3 test/test.py            # Run all tests
python3 -c "from test.test import test; test()"  # Run single test function
python3 -c "from test.test import ws_test; ws_test()"  # Test OrbitDB integration
python3 -c "from test.test import download_test; download_test()"  # Test downloads
```

## Usage Example
```python
import numpy as np
from typing import List
from ipfs_datasets_py import ipfs_datasets
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex

# Load a dataset (supports local and remote datasets)
dataset = ipfs_datasets.load_dataset("wikipedia", subset="20220301.en")
print(f"Loaded dataset with {len(dataset)} records")

# Create sample vectors for demonstration
vectors: List[np.ndarray] = [np.random.rand(768) for _ in range(100)]
metadata = [{"id": i, "source": "wikipedia", "title": f"Article {i}"} for i in range(100)]

# Create vector index
index = IPFSKnnIndex(dimension=768, metric="cosine")
vector_ids = index.add_vectors(vectors, metadata=metadata)
print(f"Added {len(vector_ids)} vectors to index")

# Create a query vector
query_vector = np.random.rand(768)

# Search for similar vectors
results = index.search(query_vector, top_k=5)
for i, result in enumerate(results):
    print(f"Result {i+1}: ID={result.id}, Score={result.score:.4f}, Title={result.metadata['title']}")
```

## Code Style Guidelines
- **Imports**: Standard library first, then third-party, then local
- **Formatting**: 4-space indentation, 88-char line limit
- **Typing**: Use type hints for function parameters and return values
- **Naming**: snake_case for variables/functions, PascalCase for classes
- **Error Handling**: Use try/except blocks, log errors appropriately
- **Documentation**: Docstrings for all public functions and classes
- **Dependencies**: All dependencies must be in setup.py/pyproject.toml

## Project Organization
- Main package: `ipfs_datasets_py`
- Tests in: `test/` directory
- Configuration in: `config/` directory

## Architecture & Integration Patterns

### Core Components
- **Dataset Loaders**: Adapters for various dataset formats (HuggingFace, Arrow, DuckDB)
- **IPFS Storage Backend**: Persistent storage of datasets on IPFS network
- **Format Converters**: Bidirectional conversion between Parquet, Arrow, and CAR files
- **Vector Indexing**: Fast similarity search for embeddings
- **Knowledge Graph**: Entity and relationship modeling using IPLD
- **P2P Transport**: libp2p-based dataset sharing and distribution
- **Web Archive Integration**: WARC file indexing and replay via IPWB

### Integration Patterns
- Use the `ipfs_datasets_py` module to load and process data from various sources
- Data can be seamlessly transferred to IPFS storage using the integrated `ipfs_datasets_py.ipfs_kit`
- Peer-to-peer sharing is enabled through `ipfs_datasets_py.libp2p_kit` integration
- Data structures are preserved using IPLD formatting
- DuckDB queries can read/write directly from/to Parquet files or convert to/from CAR files
- HuggingFace Datasets can be converted to Arrow Tables, Parquet files, or CAR files
- Vector indexes support both local memory-mapped storage and IPFS-backed persistent storage
- Knowledge graphs can be queried using both semantic similarity and relationship traversal
- All formats (DuckDB, HuggingFace, Arrow, Parquet, CAR) can be converted to each other

## IPLD-Based Knowledge Graph and Vector Storage
- Store embedding vectors in IPLD structures
- Implement knowledge graph components:
  - Entities as IPLD nodes with CIDs as identifiers
  - Relationships as IPLD links between nodes
  - Attributes as node properties
- GraphRAG search capabilities:
  - Hybrid vector + graph traversal retrieval
  - Semantic similarity via embedding vectors
  - Graph relationship traversal
  - Weighted path scoring
- Specialized IPLD schemas for vector data types
- Efficient nearest-neighbor search over IPLD-stored vectors
- Memory-mapped vector indexes for fast similarity search

### Key Classes

#### IPLDVectorStore
```python
class IPLDVectorStore:
    """IPLD-based vector storage for embeddings."""
    
    def __init__(self, dimension=768, metric="cosine"):
        """
        Initialize vector store with dimension and similarity metric.
        
        Args:
            dimension: int - Dimensionality of vectors
            metric: str - Distance metric ('cosine', 'l2', 'ip')
        """
        self.dimension = dimension
        self.metric = metric
        self.vectors = []
        self.metadata = []
        self.root_cid = None
        
    def add_vectors(self, vectors: List[np.ndarray], metadata: List[dict] = None) -> List[str]:
        """
        Store vectors in IPLD format.
        
        Args:
            vectors: List[np.ndarray] - List of vectors to store
            metadata: List[dict] - Optional metadata for each vector
            
        Returns:
            List[str] - List of vector IDs (CIDs)
        """
        # Implementation details
        return [f"bafy...{i}" for i in range(len(vectors))]  # Example CIDs
        
    def search(self, query_vector: np.ndarray, top_k: int = 10) -> List[SearchResult]:
        """
        Perform vector similarity search.
        
        Args:
            query_vector: np.ndarray - Query vector
            top_k: int - Number of results to return
            
        Returns:
            List[SearchResult] - Ranked search results
        """
        # Implementation details
        return [SearchResult(id=f"bafy...{i}", 
                           score=0.9-i*0.1, 
                           metadata_index=i,
                           metadata=self.metadata[i]) for i in range(min(top_k, len(self.vectors)))]
        
    def export_to_ipld(self) -> tuple:
        """
        Export vector index as IPLD structure.
        
        Returns:
            tuple: (root_cid, {cid: block_data}) - Root CID and blocks
        """
        # Implementation details
        return "bafy...root", {"bafy...root": b"root_data", "bafy...meta": b"meta_data"}
        
    def export_to_car(self, output_path: str) -> str:
        """
        Export vector index to CAR file.
        
        Args:
            output_path: str - Path to output CAR file
            
        Returns:
            str - Root CID of the exported index
        """
        # Implementation details
        return "bafy...root"
```

#### IPLDKnowledgeGraph
```python
import uuid
from typing import Dict, List, Optional, Tuple, Union
from slugify import slugify

class IPLDKnowledgeGraph:
    """Knowledge graph using IPLD for storage."""
    
    def __init__(self):
        """Initialize graph store."""
        self.entities = {}  # Map of entity_id to entity data
        self.relationships = {}  # Map of relationship_id to relationship data
        self.root_cid = None
        self.entity_count = 0
        self.relationship_count = 0
        
    def add_entity(self, entity_data: Dict) -> str:
        """
        Add entity node to graph.
        
        Args:
            entity_data: Dict - Entity data including name, type, properties
            
        Returns:
            str - CID of the new entity
        """
        entity_id = str(uuid.uuid4())
        slug = slugify(entity_data.get("name", f"entity-{entity_id}"))
        entity_cid = f"bafy...{slug}"
        self.entities[entity_id] = {
            "cid": entity_cid,
            "data": entity_data
        }
        self.entity_count += 1
        return entity_cid
        
    def add_relationship(self, source_cid: str, target_cid: str, 
                         relationship_type: str, properties: Optional[Dict] = None) -> str:
        """
        Add relationship between entities.
        
        Args:
            source_cid: str - CID of source entity
            target_cid: str - CID of target entity
            relationship_type: str - Type of relationship
            properties: Optional[Dict] - Additional relationship properties
            
        Returns:
            str - CID of the new relationship
        """
        rel_id = str(uuid.uuid4())
        rel_cid = f"bafy...rel-{rel_id[:8]}"
        self.relationships[rel_id] = {
            "cid": rel_cid,
            "source": source_cid,
            "target": target_cid,
            "type": relationship_type,
            "properties": properties or {}
        }
        self.relationship_count += 1
        return rel_cid
        
    def query(self, start_entity: str, relationship_path: List[str]) -> List[Dict]:
        """
        Query graph following relationship paths.
        
        Args:
            start_entity: str - Starting entity CID
            relationship_path: List[str] - Path of relationship types to follow
            
        Returns:
            List[Dict] - Matching entities and relationships
        """
        # Implementation details
        return [{"entity": f"Entity {i}", "path": relationship_path} for i in range(3)]
        
    def vector_augmented_query(self, query_vector: np.ndarray, 
                              relationship_constraints: List[Dict]) -> List[Dict]:
        """
        GraphRAG query combining vector similarity and graph traversal.
        
        Args:
            query_vector: np.ndarray - Query vector for similarity search
            relationship_constraints: List[Dict] - Constraints on traversal
            
        Returns:
            List[Dict] - Ranked results with entity and relationship data
        """
        # Implementation details
        return [{"score": 0.9-i*0.1, "entity": f"Entity {i}"} for i in range(5)]
        
    def get_entities_by_vector_ids(self, vector_ids: List[str]) -> List[Dict]:
        """
        Get entities that reference the given vector IDs.
        
        Args:
            vector_ids: List[str] - List of vector IDs (CIDs)
            
        Returns:
            List[Dict] - Entities referencing these vectors
        """
        # Implementation details
        return [{"id": f"entity-{i}", "name": f"Entity {i}"} for i in range(len(vector_ids))]
        
    def traverse_from_entities(self, entities: List[Dict], 
                              relationship_types: Optional[List[str]] = None,
                              max_depth: int = 2) -> List[Dict]:
        """
        Traverse graph from seed entities.
        
        Args:
            entities: List[Dict] - Starting entities
            relationship_types: Optional[List[str]] - Types to traverse
            max_depth: int - Maximum traversal depth
            
        Returns:
            List[Dict] - Resulting entities from traversal
        """
        # Implementation details
        return [{"id": f"related-{i}", 
                "type": "concept", 
                "properties": {"name": f"Related Concept {i}"}} 
                for i in range(10)]
                
    def export_to_car(self, output_path: str) -> str:
        """
        Export knowledge graph to CAR file.
        
        Args:
            output_path: str - Path to output CAR file
            
        Returns:
            str - Root CID of the exported graph
        """
        # Implementation details
        return "bafy...graph-root"
        
    @classmethod
    def from_cid(cls, cid: str) -> 'IPLDKnowledgeGraph':
        """
        Load knowledge graph from IPFS by CID.
        
        Args:
            cid: str - Root CID of the knowledge graph
            
        Returns:
            IPLDKnowledgeGraph - Loaded knowledge graph
        """
        graph = cls()
        graph.root_cid = cid
        # Implementation details for loading
        return graph
```

### Implementation Phases
1. Core IPLD vector storage implementation
2. Basic knowledge graph entity and relationship modeling
3. Integration with existing vector similarity search libraries
4. GraphRAG query capabilities development
5. Performance optimization and scaling enhancements

### IPLD Schemas

#### IPLD Schema for Vectors:
```json
{
  "type": "struct",
  "fields": {
    "dimension": {"type": "int"},
    "metric": {"type": "string"},
    "vectors": {
      "type": "list",
      "valueType": {
        "type": "struct",
        "fields": {
          "id": {"type": "string"},
          "values": {"type": "list", "valueType": "float"},
          "metadata": {"type": "map", "keyType": "string", "valueType": "any"}
        }
      }
    }
  }
}
```

#### IPLD Schema for Knowledge Graph Nodes:
```json
{
  "type": "struct",
  "fields": {
    "id": {"type": "string"},
    "type": {"type": "string"},
    "properties": {"type": "map", "keyType": "string", "valueType": "any"},
    "relationships": {
      "type": "list",
      "valueType": {
        "type": "struct",
        "fields": {
          "type": {"type": "string"},
          "target": {"type": "link"},
          "properties": {"type": "map", "keyType": "string", "valueType": "any"}
        }
      }
    }
  }
}
```


## Advanced Features

### GraphRAG Search with IPLD

The IPLD-based GraphRAG system combines vector similarity search with knowledge graph traversal:

1. **Vector Component**:
   - Store document/chunk embeddings in IPLD structures
   - Implement approximate nearest neighbor search
   - Use FAISS or similar libraries with IPLD persistence

2. **Knowledge Graph Component**:
   - Entities represented as IPLD nodes with CIDs
   - Relationships as typed links between nodes
   - Properties stored as node attributes
   - Graph schema defined via IPLD schemas

3. **Knowledge Graph Extraction from Text**:
   - Extract structured knowledge graphs from raw text using LLM-based extraction
   - Apply "extraction temperature" parameter to control level of detail extracted
   - Use "structure temperature" to tune the structural complexity of the extracted graph
   - Balance between comprehensive extraction and manageable graph complexity
   - Support for testing with mock graphs while ensuring adaptability to real extraction

4. **Hybrid Search Process**:
   - Convert query to embedding vector
   - Find similar vectors via ANN search
   - Expand results through graph relationships
   - Apply path-based relevance scoring
   - Rank by combined vector similarity and graph relevance

5. **IPLD Schema for Vectors**:
```json
{
  "type": "struct",
  "fields": {
    "dimension": {"type": "int"},
    "metric": {"type": "string"},
    "vectors": {
      "type": "list",
      "valueType": {
        "type": "struct",
        "fields": {
          "id": {"type": "string"},
          "values": {"type": "list", "valueType": "float"},
          "metadata": {"type": "map", "keyType": "string", "valueType": "any"}
        }
      }
    }
  }
}
```

6. **IPLD Schema for Knowledge Graph Nodes**:
```json
{
  "type": "struct",
  "fields": {
    "id": {"type": "string"},
    "type": {"type": "string"},
    "properties": {"type": "map", "keyType": "string", "valueType": "any"},
    "relationships": {
      "type": "list",
      "valueType": {
        "type": "struct",
        "fields": {
          "type": {"type": "string"},
          "target": {"type": "link"},
          "properties": {"type": "map", "keyType": "string", "valueType": "any"}
        }
      }
    }
  }
}
```

### Practical GraphRAG Example with LLM Integration

Here's a practical example of using the GraphRAG system with a large language model:

```python
import torch
from transformers import AutoTokenizer, AutoModel
from ipfs_kit_py.ipfs_kit import IPFSKit
from ipfs_kit_py.graph_rag import IPLDGraphRAG

# Initialize components
ipfs = IPFSKit(role="worker")  # Use worker role for processing capabilities
tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
embedding_model = AutoModel.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
graph_rag = IPLDGraphRAG(ipfs_client=ipfs)

# 1. Create a knowledge graph with vector-enabled nodes
def add_document_to_graph(doc_text, doc_metadata):
    """Process a document and add it to the knowledge graph with vector embeddings."""
    # Generate embedding for the document
    inputs = tokenizer(doc_text, padding=True, truncation=True, return_tensors="pt")
    with torch.no_grad():
        outputs = embedding_model(**inputs)
    embeddings = mean_pooling(outputs, inputs['attention_mask'])
    embedding_vector = embeddings[0].numpy()  # Get the vector
    
    # Create document entity in graph with vector
    doc_id = f"doc_{uuid.uuid4()}"
    graph_rag.add_entity(
        entity_id=doc_id,
        properties={
            "type": "document",
            "text": doc_text,
            "title": doc_metadata.get("title", ""),
            "source": doc_metadata.get("source", ""),
            "created_at": doc_metadata.get("created_at", time.time())
        },
        vector=embedding_vector
    )
    
    # Extract concepts and create relationships
    concepts = extract_key_concepts(doc_text)  # Custom extraction function
    for concept in concepts:
        # Create or get concept entity
        concept_id = f"concept_{slugify(concept)}"
        if not graph_rag.get_entity(concept_id):
            graph_rag.add_entity(
                entity_id=concept_id,
                properties={"type": "concept", "name": concept}
            )
        
        # Link document to concept
        graph_rag.add_relationship(
            from_entity=doc_id,
            to_entity=concept_id,
            relationship_type="mentions",
            properties={"confidence": 0.85}
        )
    
    return doc_id

# 2. Perform hybrid search combining vector similarity and graph traversal
def query_knowledge_graph(query_text, top_k=5):
    """Retrieve relevant information using hybrid vector+graph search."""
    # Generate embedding for the query
    inputs = tokenizer(query_text, padding=True, truncation=True, return_tensors="pt")
    with torch.no_grad():
        outputs = embedding_model(**inputs)
    query_embedding = mean_pooling(outputs, inputs['attention_mask'])
    query_vector = query_embedding[0].numpy()
    
    # Perform hybrid search with 2-hop graph exploration
    results = graph_rag.graph_vector_search(
        query_vector=query_vector,
        hop_count=2,
        top_k=top_k
    )
    
    # Extract and format the results
    formatted_results = []
    for result in results:
        entity = graph_rag.get_entity(result["entity_id"])
        formatted_results.append({
            "id": result["entity_id"],
            "score": result["score"],
            "properties": entity["properties"],
            "path": result["path"],  # The graph traversal path
            "distance": result["distance"]  # Graph distance (hops)
        })
    
    return formatted_results

# Helper function for embedding generation
def mean_pooling(model_output, attention_mask):
    token_embeddings = model_output[0]
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)

# 3. Use the retrieved context with an LLM
def answer_with_rag(query, llm_client):
    """Generate an answer using retrieved context from the knowledge graph."""
    # Retrieve relevant context
    context_items = query_knowledge_graph(query)
    
    # Format context for the LLM
    context_text = "\n\n".join([
        f"Document: {item['properties'].get('title', 'Untitled')}\n"
        f"Content: {item['properties'].get('text', '')[:500]}...\n"
        f"Relevance: {item['score']:.2f}"
        for item in context_items
    ])
    
    # Build prompt with context
    prompt = f"""Answer the following question based on the provided context:

Context:
{context_text}

Question: {query}

Answer:"""
    
    # Get response from LLM
    response = llm_client.generate_text(prompt)
    
    return {
        "answer": response,
        "sources": [item["id"] for item in context_items],
        "context_used": context_text
    }
```

This example demonstrates how to:
1. Add documents to a knowledge graph with vector embeddings
2. Create relationships between entities based on content analysis
3. Perform hybrid retrieval combining vector similarity and graph traversal
4. Use the retrieved context with an LLM to answer queries

The GraphRAG approach provides more context-aware and relationship-informed retrieval compared to traditional vector-only approaches, enabling more accurate and explanatory responses from language models.

## Configuration
- Main configuration file: `config/config.toml`
- Key configuration options:
  - IPFS node connection parameters
  - Vector index dimensions and metrics
  - Dataset cache locations
  - Peer discovery settings for P2P sharing
  - DuckDB connection settings
  - Default export formats
  - Embedding model configurations

### Example Configuration
```toml
[ipfs]
api_endpoint = "/ip4/127.0.0.1/tcp/5001"
gateway_url = "http://localhost:8080/ipfs/"
pin = true

[storage]
cache_dir = "~/.ipfs_datasets/cache"
temp_dir = "/tmp/ipfs_datasets"
max_cache_size_gb = 10

[duckdb]
default_db_path = "~/.ipfs_datasets/analytics.duckdb"
memory_limit = "4GB"
threads = 4

[vector_index]
default_dimension = 768
default_metric = "cosine"
index_location = "~/.ipfs_datasets/indexes"
use_memory_mapping = true

[embedding_models]
default = "sentence-transformers/all-MiniLM-L6-v2"
models = [
    { name = "sentence-transformers/all-MiniLM-L6-v2", dimension = 384, type = "sentence" },
    { name = "sentence-transformers/multi-qa-mpnet-base-dot-v1", dimension = 768, type = "qa" }
]

[export]
default_format = "parquet"
compress_car_files = true

[web_archive]
warc_dir = "~/.ipfs_datasets/warcs"
cdxj_dir = "~/.ipfs_datasets/cdxj"
use_squidwarc = false
```

## Performance Considerations
- For large datasets, use streaming data loading to minimize memory usage
- Vector indexes can be memory-mapped for datasets larger than RAM
- Use batch processing when adding vectors to the index
- Consider data sharding for distributed vector search across peers
- Use DuckDB's vectorized processing for efficient data transformations
- Leverage DuckDB's ability to directly query Parquet files without loading into memory
- For extremely large datasets, use incremental processing with checkpointing
- Use appropriate chunking strategies when converting between formats:
  ```python
  # Example of efficient chunking with DuckDB and Parquet
  from ipfs_datasets_py.duckdb_connector import DuckDBConnector
  
  # Initialize connector
  duckdb = DuckDBConnector()
  
  # Process a large Parquet file in chunks with minimal memory usage
  duckdb.execute("""
      COPY (
          SELECT *
          FROM read_parquet('large_dataset.parquet')
          WHERE value > 100
      )
      TO 'filtered_results.parquet'
      (FORMAT PARQUET, ROW_GROUP_SIZE 100000)
  """)
  ```
- When processing large web archives, use selective extraction of only needed content
- Optimize IPLD structures by choosing appropriate hash column strategies
- For CAR file exports, tune block size based on data access patterns

## Version Control
- Commit messages should be clear and descriptive
- Reference issues/PRs in commit messages when applicable
- Follow semantic versioning for releases
- Branch naming convention: feature/[feature-name], bugfix/[bug-name]

## Integrated System Architecture

The following diagram illustrates how all components interact in the complete system architecture:

```
                                  ┌─────────────────┐
                                  │ Data Sources    │
                                  │ (HF, DuckDB,    │
                                  │  Web Archives)  │
                                  └────────┬────────┘
                                           │
                                           ▼
┌──────────────────┐           ┌────────────────────┐           ┌──────────────────┐
│                  │           │                    │           │                  │
│   Processing     │◀─────────▶│     UnifiedData    │◀─────────▶│  Storage Layer   │
│    Pipeline      │           │      Layer         │           │    (IPFS/IPLD)   │
│                  │           │                    │           │                  │
└─────────┬────────┘           └─────────┬──────────┘           └────────┬─────────┘
          │                              │                               │
          ▼                              ▼                               ▼
┌──────────────────┐           ┌────────────────────┐           ┌──────────────────┐
│  Transformations │           │     Conversion     │           │  IPLD Components │
│ - Vector Encoding │           │     Components     │           │ - CAR            │
│ - KG Extraction   │           │ - Parquet ↔ CAR    │           │ - DAG-PB         │
│ - Entity Linking  │           │ - Arrow ↔ IPLD     │           │ - UnixFS         │
└─────────┬────────┘           └─────────┬──────────┘           └────────┬─────────┘
          │                              │                               │
          └──────────────────────────────┼───────────────────────────────┘
                                         │
                                         ▼
                               ┌────────────────────┐
                               │   Query Systems    │
                               │ - Vector Search    │
                               │ - Knowledge Graph  │
                               │ - GraphRAG         │
                               └────────────────────┘
```

## Implementation Plan

### Phase 0: Foundation (Months 1-2)
1. **Core Modules Setup**
   - Set up project structure and package organization
   - Implement basic configuration management
   - Create initial test framework and CI/CD pipeline
   - Set up documentation structure

2. **IPFS Integration**
   - Implement IPFS client integration
   - Create utilities for basic IPFS operations (add, get, pin)
   - Configure IPFS node management

3. **Basic Data Handling**
   - Implement simple dataset loading functions 
   - Create basic converters between formats
   - Build fundamental data structures

### Phase 1: Core Infrastructure Integration (Months 2-4)
1. **IPLD Storage Layer**
   - Implement IPLD-based dataset storage using DAG-PB
   - Create serialization/deserialization helpers for common dataset formats
   - Develop CAR file import/export for efficient dataset exchange
   - Integrate UnixFS for file and directory representation

2. **Web Archive Integration**
   - Integrate ArchiveNow for website archiving and WARC generation
   - Implement IPWB for storing web archives on IPFS
   - Create dataset extraction utilities for web archive content

3. **File Handling**
   - Implement chunking strategies for large dataset files
   - Create efficient memory-mapping mechanisms
   - Develop utilities for incremental data processing

4. **Conversion Layer**
   - Implement Parquet ↔ CAR bidirectional conversion
   - Build Arrow ↔ IPLD conversion utilities
   - Create DuckDB integration for SQL operations on data

### Phase 2: Processing & Analysis (Months 4-6)
1. **Dataset Processing Pipeline**
   - Implement transformation pipeline for web archive processing
   - Create extractors for different content types (text, structured data, etc.)
   - Develop parallel processing capabilities for large archives
   - Implement schema mapping and validation

2. **Vector Processing**
   - Implement multiple embedding model support
   - Create IPLD serialization for vector data
   - Develop efficient nearest-neighbor search
   - Build vector index structures

3. **Basic Query Capabilities**
   - Implement simple query capabilities for datasets
   - Create basic filtering and aggregation operations
   - Develop range queries and sorting functionality

### Phase 3: Advanced Features (Months 6-9)
1. **Knowledge Graph Layer**
   - Implement entity extraction from web archive content
   - Build relationship detection between entities
   - Create IPLD-based knowledge graph with linking between entities
   - Develop graph traversal algorithms

2. **Vector Search Integration**
   - Store embedding vectors in IPLD structures
   - Implement efficient nearest-neighbor search over IPLD-stored vectors
   - Create hybrid search combining vector similarity and IPLD graph traversal
   - Build query processing for vector similarity

3. **Multi-format Query Engine**
   - Implement unified query interface across storage formats
   - Create query planning and optimization
   - Build distributed query execution
   - Implement query results caching

### Phase 4: Optimization and Scaling (Months 9-12)
1. **Performance Optimizations**
   - Implement streaming data loading for large datasets
   - Create memory-mapped vector indexes for datasets larger than RAM
   - Optimize IPLD encoding/decoding for high-throughput processing
   - Improve query performance with statistics and indexes

2. **Distributed Features**
   - Support sharded datasets across multiple IPFS nodes
   - Implement collaborative dataset building with P2P synchronization
   - Create federated search across distributed dataset fragments
   - Build resilient operations with node failures
     - Automatic retry with exponential backoff
     - Circuit breaker pattern for preventing cascading failures
     - Health checking and performance monitoring
     - Node selection based on reliability metrics
     - Resumable operations via checkpointing
     - Fault-tolerant operations with graceful degradation

3. **GraphRAG Implementation**
   - Integrate knowledge graph and vector search for hybrid queries
   - Implement context-aware ranking algorithms
   - Create entity-centric query expansion
   - Develop graph-based relevance scoring
   - LLM reasoning tracer for explainability and transparency
     - Tracking of reasoning steps during query processing
     - Visualization of reasoning graphs
     - Natural language explanation generation
     - Audit capabilities for reasoning processes

### Phase 5: Production Readiness (Months 12-15)
1. **Monitoring and Management**
   - ✅ Implement comprehensive logging
   - ✅ Create performance metrics collection
   - ✅ Build administration dashboards
   - ✅ Develop operational tooling

2. **Security & Governance**
   - Implement encryption for sensitive data
   - Create access control mechanisms
   - Build data provenance tracking
   - Develop audit logging capabilities

3. **Documentation and Packaging**
   - Complete comprehensive documentation
   - Create examples and tutorials
   - Build containerized deployment options
   - Prepare release packaging and distribution

### Current Development Status and Next Steps

#### Completed Components
1. **Knowledge Graph Extraction with Temperature Parameters**
   - Implemented in `knowledge_graph_extraction.py`
   - Extraction temperature controls level of detail (0.0-1.0)
   - Structure temperature controls structural complexity (0.0-1.0)
   - Comprehensive entity and relationship extraction

2. **Wikipedia Integration and SPARQL Validation**
   - Extract knowledge graphs from Wikipedia pages via MediaWiki API
   - Validate extracted knowledge graphs against Wikidata via SPARQL
   - Measure coverage of structured knowledge from Wikidata
   - Entity mapping between extracted entities and Wikidata entities
   - Test suite for validation against different Wikipedia pages
   
3. **Federated Search for Distributed Datasets**
   - Implemented in `federated_search.py`
   - Multiple search types (vector, keyword, hybrid, filter)
   - Search result aggregation with various ranking strategies
   - Distributed index management
   - Result caching and optimization
   - Fault-tolerant search across nodes

4. **Resilient Operations for Distributed Systems**
   - Implemented in `resilient_operations.py`
   - Automatic retry mechanism with exponential backoff
   - Circuit breaker pattern for preventing cascading failures
   - Node health monitoring and tracking
   - Health-aware node selection for improved reliability
   - Checkpointing for long-running operations
   - Comprehensive test suite in `test_resilient_operations.py`

#### Completed Components (continued)
5. **LLM Reasoning Tracer for GraphRAG (Mock Implementation)**
   - Implemented as a mock in `llm_reasoning_tracer.py`
   - Provides detailed tracing of reasoning steps in GraphRAG queries
   - Visualization and auditing of knowledge graph traversal
   - Explanation generation for cross-document reasoning
   - Mock implementation that defines interfaces but leaves actual LLM integration for future work with ipfs_accelerate_py
   - Complete example in `llm_reasoning_example.py`
   - Comprehensive test suite in `test_llm_reasoning_tracer.py`

6. **Comprehensive Monitoring and Metrics Collection System**
   - Implemented in `monitoring.py`
   - Configurable structured logging with context
   - Performance metrics collection with multiple metric types (counters, gauges, histograms, timers, events)
   - Operation tracking for distributed transactions
   - System resource monitoring (CPU, memory, disk, network)
   - Prometheus integration for metrics export
   - Context managers and decorators for easy integration
   - Pluggable outputs (file, console, Prometheus)
   - Complete example in `monitoring_example.py`
   - Comprehensive test suite in `test_monitoring.py`

#### Completed Components (continued)

7. **Administration Dashboard and Operational Tooling**
   - Implemented in `admin_dashboard.py`
   - Web-based dashboard for real-time system monitoring
   - Built with Flask and Chart.js for visualization
   - Comprehensive metrics display with historical data
   - Log browsing and filtering capabilities
   - Operation tracking and visualization
   - Node management interface
   - Configuration management and display
   - Complete example in `admin_dashboard_example.py`
   - Comprehensive test suite in `test_admin_dashboard.py`

#### Current Priority Focus Areas

1. **Security & Governance**
   - ✅ Implementing encryption for sensitive data (Completed)
   - ✅ Creating access control mechanisms (Completed)
   - ✅ Building enhanced data provenance tracking with detailed lineage (Completed)
   - ✅ Developing comprehensive audit logging capabilities (Completed)

2. **RAG Query Optimizer for Knowledge Graphs**
   - ✅ Fixed syntax issues in `rag_query_optimizer.py` (Completed)
   - ✅ Implemented statistical learning for adaptive query optimization (Completed)
   - ✅ Created comprehensive test suite with unit, integration, and parameterized tests (Completed)
   - ✅ Optimizing GraphRAG queries over Wikipedia-derived knowledge graphs (Completed)
   - ✅ Query planning, statistics collection, and caching (Completed)
   - ✅ Performance improvements for complex graph traversals (Completed)
   - ✅ Enhanced error handling with fallback plans to ensure optimizer never returns None (Completed)
   - ✅ Fixed JSON serialization for numpy arrays in metrics collection (Completed)
   - ✅ Implemented robust error handling in the statistical learning process (Completed)
   - ✅ Added transaction safety with backup and rollback in learning process (Completed)
   - ✅ Implemented structured logging for learning cycle events (Completed)
   - ✅ Fixed query statistics counting inconsistencies with cache hits (Completed)
   - ✅ Fixed caching functionality issues with improved cache key generation (Completed)
   - ✅ Enhanced cache storage and retrieval with better error handling (Completed)
   - ✅ Visualization and metrics collection for query performance analysis (Completed)

3. **Integration & Documentation**
   - ✅ Alert system for detecting learning anomalies (Completed)
   - ✅ Visualization system for learning metrics (Completed)
   - ✅ Alert and visualization integration for comprehensive monitoring (Completed)
   - ✅ Unified dashboard integrating all monitoring components (Completed)
   - ✅ Comprehensive documentation and example workflows (Completed)

#### Scope Notes
- **LLM-based functionality** including cross-document reasoning will be handled by the separate `ipfs_accelerate_py` package, not in this repository
- The `llm_reasoning_tracer.py` module will remain as a mock implementation with interfaces for integration with `ipfs_accelerate_py`
- This repository focuses on the core data management, storage, and retrieval capabilities, not LLM-specific processing

#### Implementation Notes
- Multi-model embedding generation is handled by the existing `ipfs_embeddings_py` package
- Knowledge graph extraction functionality is complete and tested
- Current focus is on data provenance tracking and RAG query optimization
- All implementation follows the modular design principles of the project

#### RAG Query Optimizer Test Suite

The RAG Query Optimizer has been extensively tested with a comprehensive test suite:

1. **Unit Tests (`test_rag_query_optimizer.py`)**
   - Tests for individual components: QueryRewriter, QueryBudgetManager, GraphRAGQueryStats
   - Tests for query optimization and execution with caching
   - Coverage of basic functionality for each component

2. **Statistical Learning Tests (`test_statistical_learning.py`)**
   - Dedicated test suite for the statistical learning feature
   - Tests for enabling/disabling statistical learning
   - Tests for learning cycle triggering and parameter adaptation
   - Tests for learning from different query patterns
   - Error handling and recovery tests
   - Tests for noisy data handling and persistence

3. **Integration Tests with pytest (`test_rag_query_optimizer_pytest.py`)**
   - Advanced parameterized tests using pytest fixtures
   - Tests with various query types and patterns
   - Performance tests with different query volumes
   - Error handling and edge case coverage
   - Comprehensive test coverage with minimal code duplication

4. **Cross-Component Integration Tests (`test_rag_query_optimizer_integration.py`)**
   - Tests for integration with GraphRAGLLMProcessor
   - Tests for integration with Wikipedia-specific components
   - Tests for integration with visualization components
   - End-to-end query execution flow tests
   - Tests for cross-document reasoning integration

This test suite ensures robust functionality, good performance, and proper integration with other system components. The tests are designed to be maintainable and to clearly identify issues when they arise.

**Note on test status:** We have improved several aspects of the RAG Query Optimizer implementation to address issues identified by the test suite. Recent improvements include:

1. ✅ **Enhanced error handling**: The `optimize_query` method now includes robust error handling with fallback plans to ensure it never returns `None`. This resolves the NoneType errors that were occurring in tests.
   - Added a `_create_fallback_plan` method to generate safe default plans when optimization fails
   - Added safety checks at all return points to ensure no `None` values escape
   - Wrapped the entire method in a try-except block for comprehensive error handling
   - Added specific checks after calls to specialized optimizers

We have successfully addressed the following issues:

1. ✅ **Enhanced error handling**: The `optimize_query` method now includes robust error handling with fallback plans to ensure it never returns `None`.
2. ✅ **JSON serialization**: Enhanced the `_numpy_json_serializable` method to properly handle numpy arrays in metrics collection, preventing serialization errors.
3. ✅ **Error handling in the learning process**: Implemented robust error handling in the statistical learning process with:
   - Transaction safety with backup and rollback capabilities
   - Improved error isolation between different processing stages
   - Structured logging with categorization (info, warning, error)
   - Better data validation and sanitization
   - More comprehensive metrics collection for error visibility
   - Added the `_check_learning_cycle` method with proper error handling

We have successfully addressed all the previously identified issues:

1. ✅ **Enhanced error handling**: The `optimize_query` method now includes robust error handling with fallback plans to ensure it never returns `None`.
2. ✅ **JSON serialization**: Enhanced the `_numpy_json_serializable` method to properly handle numpy arrays in metrics collection, preventing serialization errors.
3. ✅ **Error handling in the learning process**: Implemented robust error handling in the statistical learning process with:
   - Transaction safety with backup and rollback capabilities
   - Improved error isolation between different processing stages
   - Structured logging with categorization (info, warning, error)
   - Better data validation and sanitization
   - More comprehensive metrics collection for error visibility
   - Added the `_check_learning_cycle` method with proper error handling
4. ✅ **Query statistics**: Fixed inconsistencies in counting and reporting analyzed queries, especially with cache hits. The new implementation correctly:
   - Increments query_count only for new queries
   - Tracks cache_hits separately without duplicating the query count
   - Maintains accurate cache hit rates
5. ✅ **Caching functionality**: Fixed issues with the caching mechanism through:
   - Improved cache key generation with better vector representation
   - Enhanced numpy array handling in cache serialization
   - More robust error handling in cache operations
   - Better diagnostics for cache misses and errors

The comprehensive test suite now passes successfully, confirming that all the major issues have been resolved. The RAG Query Optimizer is now robust, reliable, and ready for production use.

### Integration Architecture

The following diagram illustrates how the components integrate:

```
┌─────────────────┐     ┌───────────────┐     ┌───────────────────┐
│  Data Sources   │────▶│ Data Loaders  │────▶│ Processing Pipeline│
└─────────────────┘     └───────────────┘     └───────────────────┘
  - Web Archives          - WARC Loaders        - Extractors
  - Parquet Files         - Parquet Loaders     - Transformers
  - HF Datasets           - HF Dataset Adapters  - Normalizers
                                │
                                ▼
┌─────────────────┐     ┌───────────────┐     ┌───────────────────┐
│  IPLD Storage   │◀───▶│ Dataset API   │────▶│   Query Engine    │
└─────────────────┘     └───────────────┘     └───────────────────┘
  - DAG-PB Nodes          - Dataset Operations   - Vector Search
  - CAR Files             - Metadata Management  - Graph Traversal
  - UnixFS Chunking       - Version Control      - Hybrid RAG Queries
```

### Implementation Approach
- Use modular design with clear interfaces between components
- Implement progressive enhancement with basic functionality first
- Focus on memory efficiency for large dataset handling
- Ensure robust error handling and recovery mechanisms
- Provide comprehensive testing for each component

### Robust Error Handling in GraphRAG Query Optimization

The query optimization system incorporates robust error handling to ensure reliable operation even in edge cases:

#### Fallback Plan Generation
The `UnifiedGraphRAGQueryOptimizer` includes a `_create_fallback_plan` method that generates conservative query plans when optimization fails:

```python
def _create_fallback_plan(self, query: Dict[str, Any], priority: str = "normal", error: Optional[str] = None) -> Dict[str, Any]:
    """Create a fallback query plan when optimization fails."""
    # Create safe defaults for the query parameters
    fallback_query = query.copy()
    if "traversal" not in fallback_query:
        fallback_query["traversal"] = {}
    if "max_depth" not in fallback_query["traversal"]:
        fallback_query["traversal"]["max_depth"] = 2
    # Add conservative vector search parameters
    if "max_vector_results" not in fallback_query:
        fallback_query["max_vector_results"] = 5
    if "min_similarity" not in fallback_query:
        fallback_query["min_similarity"] = 0.6
        
    # Return a complete fallback plan
    return {
        "query": fallback_query,
        "weights": {"vector": 0.7, "graph": 0.3},
        "budget": budget,
        "graph_type": "generic",
        "statistics": {"fallback": True, "error_handled": True},
        "caching": {"enabled": False},
        "traversal_strategy": "default",
        "fallback": True,
        "error": error
    }
```

#### Error Handling Strategy
The error handling strategy incorporates multiple layers of protection:

1. **Safety Checks at Critical Points**:
   - After calling specialized optimizers (e.g., Wikipedia optimizer)
   - After calling base optimizer components
   - Before final return statements

2. **Comprehensive Exception Handling**:
   - Try-except wrapping for the entire optimization method
   - Graceful degradation to fallback plans when errors occur
   - Error logging and metrics collection for debugging

3. **Metadata for Error Tracking**:
   - Fallback plans are marked with `"fallback": True` flag
   - Original error messages are preserved in the plan
   - Error metrics are collected for analysis

This approach ensures that the query optimization process never fails catastrophically, maintaining system reliability even when individual components encounter issues.

## IPLD Components for Dataset Representation

### IPLD-CAR (Content Addressable aRchives)

#### Overview
IPLD-CAR is a library for working with Content Addressable aRchives (CAR), a critical format for IPFS data transfer:
- Provides transport format for datasets to/from IPFS
- Enables packaging multiple related blocks as a single unit
- Facilitates offline data exchange between IPFS nodes
- Supports content-addressed data storage and transfer

#### CAR File Format
The CAR format consists of:
- A header with the root CIDs
- A sequence of content-addressed blocks
- Each block contains its CID and the raw block data

This format allows for efficient transport of IPLD data structures with their complete dependency graphs.

#### Components
- **CAR Encoder/Decoder**: Convert between IPLD blocks and CAR files
- **CID Handling**: Work with Content Identifiers for addressing data
- **Block Management**: Organize data blocks within the CAR container
- **Selective Reading**: Ability to extract specific blocks by CID

#### Core API
The library provides two primary functions:
```python
def encode(roots: List[CID], blocks: List[Tuple[CID, bytes]]) -> bytes:
    """
    Encode roots and blocks into a CAR file.
    
    Args:
        roots: List of root CIDs
        blocks: List of (CID, data) tuples
        
    Returns:
        bytes: The CAR file as bytes
    """

def decode(car_data: bytes) -> Tuple[List[CID], Dict[CID, bytes]]:
    """
    Decode a CAR file into roots and blocks.
    
    Args:
        car_data: The CAR file as bytes
        
    Returns:
        Tuple[List[CID], Dict[CID, bytes]]: (roots, blocks)
    """
```

#### Integration
```python
import ipld_car
from multiformats import multihash, CID

# Encode dataset blocks to CAR format
dataset_car = ipld_car.encode([root_cid], [(cid1, data1), (cid2, data2)])

# Write CAR file to disk
with open("my_dataset.car", "wb") as f:
    f.write(dataset_car)

# Read and decode CAR file
with open("my_dataset.car", "rb") as f:
    car_data = f.read()
roots, blocks = ipld_car.decode(car_data)

# Access dataset blocks by their CIDs
for cid, block_data in blocks.items():
    process_block(cid, block_data)
```

### IPLD-DAG-PB (Directed Acyclic Graph - ProtoBuf)

#### Overview
IPLD-DAG-PB is an implementation of the DAG-PB specification, the primary data structure used in IPFS:
- Provides foundation for structured data representation
- Enables linking between different dataset components
- Supports content-addressed data models
- Can represent relationships between data points

#### DAG-PB Format
The DAG-PB format is a strict schema that defines:
- **PBNode**: A node containing data and links
- **PBLink**: A link to another node with a name, hash (CID), and size (Tsize)

The schema is based on Protocol Buffers and follows this structure:
```protobuf
message PBLink {
  optional string Name = 1;    // UTF-8 string name
  optional bytes Hash = 2;     // CID of the linked node
  optional uint64 Tsize = 3;   // Size of the linked node
}

message PBNode {
  repeated PBLink Links = 1;   // List of links to other nodes
  optional bytes Data = 2;     // Arbitrary data payload
}
```

#### Components
- **PBNode**: Core data structure for representing nodes in the graph
- **PBLink**: Mechanism for creating links between nodes
- **Encoding/Decoding**: Convert between DAG-PB structures and binary format
- **Schema Validation**: Ensure adherence to the strict DAG-PB schema

#### Core API
```python
# Low-level API (raw structures)
def encode_raw(raw_node: Dict) -> bytes:
    """Encode a raw PBNode dictionary to bytes."""
    
def decode_raw(raw_data: bytes) -> Dict:
    """Decode bytes to a raw PBNode dictionary."""

# High-level API (object-oriented)
class PBNode:
    """A node in a DAG-PB graph."""
    
    def __init__(self, data=None, links=None):
        """Initialize a PBNode with optional data and links."""
        
    def add_link(self, name, cid, tsize=None):
        """Add a link to another node."""

def encode(node: PBNode) -> bytes:
    """Encode a PBNode object to bytes."""
    
def decode(data: bytes) -> PBNode:
    """Decode bytes to a PBNode object."""
    
def prepare(obj: Dict) -> PBNode:
    """Prepare a dictionary as a valid PBNode."""
```

#### Integration
```python
from ipld_dag_pb import PBNode, encode, decode, prepare
from multiformats import CID

# Create a node with dataset metadata
metadata_node = PBNode(json.dumps({
    "name": "climate_dataset",
    "dimensions": 3,
    "count": 10000
}).encode("utf-8"))

# Encode to bytes for storage
encoded_metadata = encode(metadata_node)

# Create linked structure for dataset components
root_node = prepare({
    "data": {"Data": json.dumps({"type": "dataset_root"}).encode()},
    "links": [
        {"Name": "metadata", "Hash": metadata_cid, "Tsize": len(encoded_metadata)},
        {"Name": "vectors", "Hash": vectors_cid, "Tsize": vectors_size},
        {"Name": "index", "Hash": index_cid, "Tsize": index_size}
    ]
})

# Decode a node from storage
retrieved_node = decode(stored_bytes)
```

### IPLD-UnixFS

#### Overview
IPLD-UnixFS is an implementation of the UnixFS specification for IPFS:
- Enables file and directory representation in IPFS
- Provides efficient chunking strategies for large datasets
- Supports incremental processing of large files
- Allows fine-grained control over memory usage

#### UnixFS Format
UnixFS is a data format that represents files and directories in a POSIX-like file system structure:
- Files are represented as chunked data with metadata
- Directories contain entries mapping names to CIDs
- Symlinks, raw files, and other special types are supported
- Data is structured as dag-pb nodes with UnixFS-specific data payload

#### Components
- **Chunkers**: Strategies for splitting large files into manageable pieces
  - Fixed-size chunker: Splits data into fixed-size chunks
  - Rabin chunker: Uses content-defined chunking for better deduplication
  - Size-bounded chunker: Ensures chunks stay within size bounds
- **File Builder**: Tools for constructing UnixFS file representations
- **Directory Builder**: Mechanisms for organizing files in directories
- **CAR Writer**: Tools for writing UnixFS structures directly to CAR files

#### Core API

##### Chunker API
```python
class ChunkerBase:
    """Base class for chunking strategies."""
    
    def cut(self, context, buffer, end=False) -> list[int]:
        """
        Cut buffer into chunks, returning a list of chunk byte lengths.
        
        Args:
            context: Opaque context maintained between calls
            buffer: Bytes buffer to chunk
            end: True if this is the last buffer
            
        Returns:
            list[int]: List of chunk lengths
        """

class FixedSizeChunker(ChunkerBase):
    """Chunks data into fixed-size pieces."""
    
    def __init__(self, chunk_size=262144):  # Default 256KB
        """Initialize with chunk size."""
        
class RabinChunker(ChunkerBase):
    """Content-defined chunking using Rabin fingerprinting."""
    
    def __init__(self, min_size=256*1024, avg_size=1024*1024, max_size=4*1024*1024):
        """Initialize with size parameters."""
```

##### Writer API
```python
class UnixFSWriter:
    """Writes UnixFS files to IPFS."""
    
    def write_file(self, file_path, chunker=None):
        """
        Write a file to IPFS using UnixFS format.
        
        Args:
            file_path: Path to file to write
            chunker: Chunking strategy to use
            
        Returns:
            CID: Content ID of the root node
        """
    
    def write_directory(self, dir_path, recursive=True):
        """
        Write a directory to IPFS using UnixFS format.
        
        Args:
            dir_path: Path to directory to write
            recursive: Whether to include subdirectories
            
        Returns:
            CID: Content ID of the directory node
        """
        
    def write_to_car(self, path, car_path, chunker=None):
        """
        Write a file or directory to a CAR file.
        
        Args:
            path: Path to file or directory
            car_path: Output CAR file path
            chunker: Chunking strategy to use
            
        Returns:
            CID: Content ID of the root node
        """
```

#### Integration
```python
from ipld_unixfs.file.chunker import fixed

# Create a fixed-size chunker for large dataset files
chunker = fixed.FixedSizeChunker(chunk_size=1024*1024)  # 1MB chunks

# Process a large dataset file incrementally
with open("large_dataset.parquet", "rb") as f:
    buffer = f.read(8192)
    while buffer:
        chunks = chunker.cut(None, buffer)
        for chunk in chunks:
            process_chunk(chunk)
        buffer = f.read(8192)
```

## Web Archive Integration

### InterPlanetary Wayback (IPWB) Integration

#### Overview
InterPlanetary Wayback (IPWB) is a web archive integration tool that facilitates:
- Storage of web archive (WARC) files on the IPFS network
- Content-addressable deduplication of web resources
- Distributed replay of archived web content
- Memento Protocol support for time-based content negotiation
- End-to-end encrypted web archives for private archiving

#### Components
- **WARC Indexer**: Extracts HTTP headers and content from WARC files, pushes them to IPFS separately, and creates CDXJ indexes
- **CDXJ Files**: Contains URI-Rs (original URLs), timestamps, and IPFS hashes for archived content with Memento compatibility
- **Replay System**: Serves archived content from IPFS using the CDXJ index for lookup
- **Reconstructive**: Client-side JavaScript library that uses Service Workers to rewrite URLs and handle replay
- **Custom HTML Elements**: Components like `<reconstructive-banner>` for enhancing web archive replay

#### CDXJ Format
CDXJ is a sorted text file format that extends CDX with JSON-formatted metadata:

```
URI-R timestamp [JSON metadata]
```

Example CDXJ entry:
```
com,example)/ 20200101120000 {"uri":"https://example.com/","mime":"text/html","status":"200","digest":"SHA256=abc123...","length":"4526","offset":"0","filename":"example.warc.gz","headers":{"WARC-Type":"response","WARC-Date":"2020-01-01T12:00:00Z"},"ipfs":"QmZ8jJ5kqjfgP9yAJk7NQGcr4Gzdz5..."}
```

The `ipfs` field contains the IPFS hash for the archived content, enabling direct retrieval through the IPFS network.

#### Integration Steps
1. **Installation**:
   ```bash
   pip install ipwb
   
   # Or using Docker
   docker pull oduwsdl/ipwb
   docker run -p 5000:5000 -p 8080:8080 -v /path/to/data:/data oduwsdl/ipwb
   ```

2. **IPFS Setup**:
   - Ensure IPFS daemon is running: `ipfs daemon`
   - Configure with: `ipfs config Addresses.API /ip4/127.0.0.1/tcp/5001`

3. **Indexing Web Archives**:
   ```python
   from ipwb import indexer
   
   # Basic indexing
   cdxj_lines = indexer.index_file_at('path/to/archive.warc', 
                                       outfile='index.cdxj',
                                       quiet=True)
   
   # Encrypted indexing for private archives
   encryption_key = 'mySecretKey'
   cdxj_lines = indexer.index_file_at('path/to/archive.warc',
                                       outfile='encrypted_index.cdxj',
                                       encryption_key=encryption_key)
   
   # Selective indexing (only include specific MIME types)
   cdxj_lines = indexer.index_file_at('path/to/archive.warc',
                                       outfile='filtered_index.cdxj',
                                       include_mimes=['text/html', 'text/css', 'application/javascript'])
   ```

4. **Replaying Web Archives**:
   ```python
   from ipwb import replay
   
   # Start the replay system with your CDXJ index
   replay.start('path/to/index.cdxj')
   
   # Start with encrypted index
   replay.start('path/to/encrypted_index.cdxj', encryption_key='mySecretKey')
   
   # Start with proxy support for HTTPS content
   replay.start('path/to/index.cdxj', proxy=True)
   ```

5. **Advanced API Usage**:
   ```python
   from ipwb import util, indexer, replay
   
   # Direct IPFS interactions
   content_hash = util.push_to_ipfs(content_bytes, headers_dict=None)
   retrieved_content = util.pull_from_ipfs(content_hash)
   
   # Access through Memento TimeMap
   # This provides a list of all captures for a specific URL
   timemap_url = f"http://localhost:5000/timemap/link/http://example.com/"
   
   # Access specific Memento by timestamp
   memento_url = f"http://localhost:5000/memento/20200101120000/http://example.com/"
   ```

### ArchiveNow for Website Archiving

#### Overview
ArchiveNow is a tool for pushing web resources into web archives, including generating local WARC files of entire websites. It provides a unified interface to multiple archive services and local archiving capabilities.

#### Key Features
- Push to multiple web archives simultaneously (Internet Archive, Archive.today, Perma.cc, etc.)
- Generate local WARC files using different agents (wget or squidwarc)
- Extensible architecture with pluggable archive handlers
- CLI, Python API, and web service interfaces
- Docker support for containerized deployment

#### Installation
```bash
pip install archivenow

# Or using Docker
docker pull oduwsdl/archivenow
docker run -p 12345:12345 oduwsdl/archivenow --server --host 0.0.0.0
```

#### Creating WARC Archives of Websites

1. **Command Line Usage**:
   ```bash
   # Create a WARC with default filename (derived from URL)
   archivenow --warc https://example.com/
   
   # Create a WARC with custom filename
   archivenow --warc=myarchive https://example.com/
   
   # Create WARC using a specific agent (wget or squidwarc)
   archivenow --warc --agent=squidwarc https://example.com/
   
   # Push to all supported archives simultaneously
   archivenow --all https://example.com/
   
   # Push to specific archives (ia=Internet Archive, is=Archive.today, cc=Perma.cc)
   archivenow --ia --is https://example.com/
   
   # Archive to Archive.is (archive.today) specifically  
   archivenow --is https://example.com/
   ```

2. **Python API Usage**:
   ```python
   from archivenow import archivenow
   
   # Create a WARC archive of a website
   result = archivenow.push("https://example.com/", "warc", 
                            {"warc": "myarchive", "agent": "wget"})
   
   # Push to Internet Archive
   result_ia = archivenow.push("https://example.com/", "ia")
   print(f"Internet Archive URL: {result_ia}")
   
   # Push to Archive.is (archive.today)
   result_is = archivenow.push("https://example.com/", "is")
   print(f"Archive.is URL: {result_is}")
   
   # Push to multiple archives including Archive.is
   results = archivenow.push("https://example.com/", ["ia", "is", "cc"])
   for archive, url in results.items():
       print(f"{archive}: {url}")
   
   # Direct Archive.is integration with custom headers
   import requests
   
   def archive_to_archive_is(url, wait_for_completion=True):
       """Archive URL directly to Archive.is with completion tracking."""
       response = requests.post(
           'https://archive.is/submit/',
           data={'url': url},
           headers={
               'User-Agent': 'IPFS Datasets Archive Bot 1.0',
               'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
           },
           timeout=60
       )
       
       if response.status_code == 200:
           archive_url = response.url
           if wait_for_completion and 'archive.is' in archive_url:
               # Wait for archive completion
               import time
               time.sleep(5)  # Allow processing time
               
               # Verify archive exists
               verify_response = requests.get(archive_url, timeout=30)
               if verify_response.status_code == 200:
                   return archive_url
           return archive_url
       else:
           raise Exception(f"Archive.is failed with status: {response.status_code}")
   
   # Use direct Archive.is integration
   archive_is_url = archive_to_archive_is("https://example.com")
   print(f"Direct Archive.is URL: {archive_is_url}")
       
   # Custom implementation with handlers
   from archivenow.handlers import warc_handler
   
   custom_handler = warc_handler.WARCHandler()
   archive_url = custom_handler.push("https://example.com/", 
                                    {"warc": "custom_archive", 
                                     "agent": "squidwarc", 
                                     "depth": 1})
   ```

3. **Web Service Usage**:
   ```bash
   # Start ArchiveNow server
   archivenow --server --host 0.0.0.0 --port 12345
   
   # Create WARC via HTTP request
   curl http://localhost:12345/warc/https://example.com/
   
   # Push to Internet Archive
   curl http://localhost:12345/ia/https://example.com/
   
   # Push to all archives 
   curl http://localhost:12345/all/https://example.com/
   
   # Custom options via POST request
   curl -X POST -d '{"agent":"squidwarc","depth":2}' \
        http://localhost:12345/warc/https://example.com/
   ```

4. **Extending ArchiveNow**:
   ```python
   # Creating a custom archive handler
   from archivenow.handlers.archive_handler import ArchiveHandler
   
   class MyCustomArchiveHandler(ArchiveHandler):
       def __init__(self):
           ArchiveHandler.__init__(self)
           self.enabled = True
           self.name = 'my_archive'
           self.service_api = 'https://myarchive.example.org/api/save'
       
       def push(self, uri, params=None):
           # Custom implementation to push to your archive service
           # Returns the URL of the archived version
           return f"https://myarchive.example.org/archived/{uri}"
   
   # Register the handler
   from archivenow import archivenow
   archivenow.handler_api.register_handler(MyCustomArchiveHandler())
   ```

#### Advanced Options

- **Archive Agents**: ArchiveNow supports two WARC generation agents:
  ```bash
  # Using wget (default) - better for static sites
  archivenow --warc --agent=wget https://example.com/
  
  # Using squidwarc - better for dynamic sites with JavaScript
  archivenow --warc --agent=squidwarc https://example.com/
  ```

- **Multiple Archive Formats Simultaneously**:
  ```bash
  # Archive to WARC file and Internet Archive at the same time
  archivenow --ia --warc https://example.com/
  ```

#### Best Practices for Complete Website Archiving

1. **For Static Websites**:
   - Use the default wget agent which captures all necessary resources
   
2. **For Dynamic Websites**:
   - Use the squidwarc agent which uses a headless browser to better capture JavaScript content
   
3. **For Large Websites**:
   - For more comprehensive crawling of large sites, consider using wget directly with recursive options
   - For websites with complex JavaScript, use the squidwarc agent

### Acquiring Web Archives
To obtain WARC or CDXJ files from the Internet Archive:

1. **Internet Archive API**:
   ```python
   import requests
   
   def get_warc_from_ia(identifier, filename):
       """Download a WARC file from Internet Archive."""
       url = f"https://archive.org/download/{identifier}/{filename}"
       response = requests.get(url, stream=True)
       with open(filename, 'wb') as f:
           for chunk in response.iter_content(chunk_size=8192):
               f.write(chunk)
       return filename
   ```

2. **Internet Archive Collection API**:
   ```python
   def get_collection_warcs(collection_id):
       """Get list of WARCs in an IA collection."""
       url = f"https://archive.org/advancedsearch.php?q=collection:{collection_id}+AND+format:WARC&fl[]=identifier&fl[]=filename&output=json"
       response = requests.get(url)
       return response.json()['response']['docs']
   ```

3. **Web Archive Discovery Tools**:
   - CDX API: Use Archive.org's CDX server API to find captures
   - WayBack Machine API: Query archived URLs by timestamp  
   - ARCH Framework: Python library for archive discovery
   - Common Crawl Index API: Query massive web crawl datasets
   - Archive.is API: Direct integration with Archive.today service
   
   ```python
   # CDX API for Wayback Machine
   import requests
   
   def query_cdx_api(url, from_date=None, to_date=None, limit=100):
       """Query Archive.org CDX API for URL captures."""
       params = {
           'url': url,
           'output': 'json',
           'limit': limit
       }
       if from_date:
           params['from'] = from_date
       if to_date:
           params['to'] = to_date
           
       response = requests.get('http://web.archive.org/cdx/search/cdx', params=params)
       return response.json()
   
   # Common Crawl Index API
   def query_common_crawl_index(url_pattern, crawl_id="CC-MAIN-2024-10"):
       """Query Common Crawl index for URL patterns."""
       cc_url = f"https://index.commoncrawl.org/{crawl_id}-index"
       params = {'url': url_pattern, 'output': 'json'}
       
       response = requests.get(cc_url, params=params)
       results = []
       for line in response.text.strip().split('\n'):
           if line:
               results.append(json.loads(line))
       return results
   
   # Archive.is verification and metadata
   def get_archive_is_metadata(archive_url):
       """Get metadata from Archive.is archived page."""
       response = requests.get(archive_url, timeout=30)
       if response.status_code == 200:
           # Extract metadata from Archive.is page
           from bs4 import BeautifulSoup
           soup = BeautifulSoup(response.content, 'html.parser')
           
           # Find archive timestamp and original URL
           meta_info = soup.find('div', class_='TEXT-BLOCK')
           if meta_info:
               return {
                   'archive_url': archive_url,
                   'archived_at': meta_info.get_text().strip(),
                   'original_url': soup.find('a', {'rel': 'canonical'})['href'] if soup.find('a', {'rel': 'canonical'}) else None,
                   'archive_service': 'archive.is'
               }
       return None
   ```

### Usage Examples
```python
# Complete workflow: create, index, and process a web archive
from archivenow import archivenow
from ipfs_datasets_py import web_archive_utils

# Create a WARC archive of a website
warc_file = archivenow.push("https://example.com/", "warc", {"warc": "example_archive"})

# Index the WARC to IPFS using IPWB
cdxj_path = web_archive_utils.index_warc(warc_file)

# Extract structured data from the archive
dataset = web_archive_utils.extract_dataset_from_cdxj(cdxj_path)

# Create vector embeddings from extracted text
embeddings = web_archive_utils.embed_archive_text(dataset)

# Store archive as queryable knowledge graph
kg = web_archive_utils.archive_to_knowledge_graph(dataset)
```

### Considerations
- WARC files can be very large (GBs to TBs), so use streaming processing
- IPFS provides automatic deduplication of web resources across archives
- Implement selective indexing to focus on specific content types or domains
- Use IPFS pinning services to ensure long-term availability of archived content
- For complete website archiving, consider scope limitations (depth of crawl, external links)

### Web Archive to Structured Datasets

#### Querying Common Crawl and Internet Archive

This module aims to provide functionality for querying Common Crawl and Internet Archive to obtain web content that can be processed into structured datasets (Hugging Face Datasets / Parquet files).

1. **Common Crawl Integration**:
   ```python
   from ipfs_datasets_py import web_archive_utils
   
   # Query Common Crawl for specific domain/URL pattern
   results = web_archive_utils.query_common_crawl(
       domain="example.com",
       url_pattern="*/blog/*",
       crawl_id="CC-MAIN-2023-06",  # Optional specific crawl
       limit=1000
   )
   
   # Advanced Common Crawl querying with filters
   filtered_results = web_archive_utils.query_common_crawl(
       domain="stackoverflow.com",
       url_pattern="*/questions/*",
       crawl_id="CC-MAIN-2024-10",
       limit=5000,
       filters={
           'mime_type': 'text/html',
           'status_code': '200',
           'language': 'en',
           'min_content_length': 1000
       }
   )
   
   # Download matching WARC records with parallel processing
   warc_data = web_archive_utils.download_cc_warcs(
       results, 
       max_workers=4,
       chunk_size=1024*1024  # 1MB chunks
   )
   
   # Convert to structured dataset with content analysis
   dataset = web_archive_utils.warc_to_dataset(
       warc_data, 
       extract_text=True, 
       extract_metadata=True,
       content_analysis={
           'language_detection': True,
           'content_classification': True,
           'link_extraction': True,
           'structured_data_extraction': True  # JSON-LD, microdata, etc.
       }
   )
   
   # Advanced Common Crawl processing pipeline
   cc_pipeline = web_archive_utils.CommonCrawlPipeline(
       crawl_ids=["CC-MAIN-2024-10", "CC-MAIN-2024-06"],  # Multiple crawls
       domain_filters=["*.edu", "*.gov", "*.org"],
       content_filters={
           'min_text_length': 500,
           'languages': ['en', 'es', 'fr'],
           'exclude_patterns': ['*/admin/*', '*/login/*']
       },
       output_format='parquet',
       deduplication=True
   )
   
   # Process multiple domains across multiple crawls
   bulk_dataset = cc_pipeline.process_domains([
       "example.com",
       "stackoverflow.com", 
       "github.com"
   ])
   
   # Save as Parquet with partitioning
   bulk_dataset.save_to_parquet(
       "common_crawl_dataset.parquet",
       partition_cols=["domain", "crawl_id", "language"]
   )
   
   # Or push to Hugging Face Datasets Hub
   bulk_dataset.push_to_hub("username/common-crawl-processed")
   ```

2. **Internet Archive Wayback Machine Integration**:
   ```python
   # Query Internet Archive for historical captures of a domain
   captures = web_archive_utils.query_wayback_machine(
       url="example.com",
       from_date="20150101",
       to_date="20220101",
       match_type="domain",
       limit=500
   )
   
   # Download captures as WARC
   warc_data = web_archive_utils.download_wayback_captures(captures)
   
   # Process into dataset with time series information
   timeseries_dataset = web_archive_utils.wayback_to_timeseries_dataset(
       warc_data,
       temporal_field="capture_date",
       content_fields=["html_content", "text_content", "links"]
   )
   ```

3. **Bulk Archive Processing Pipeline**:
   ```python
   # Define processing pipeline for web archives
   pipeline = web_archive_utils.WARCProcessingPipeline(
       extraction_steps=[
           web_archive_utils.extractors.HTMLExtractor(),
           web_archive_utils.extractors.TextExtractor(),
           web_archive_utils.extractors.LinkExtractor(),
           web_archive_utils.extractors.MetadataExtractor()
       ],
       transformation_steps=[
           web_archive_utils.transformers.DedupContent(),
           web_archive_utils.transformers.LanguageDetection(),
           web_archive_utils.transformers.HTMLCleaner(),
           web_archive_utils.transformers.TextNormalizer()
       ],
       output_format="parquet"
   )
   
   # Process multiple archives in parallel
   processed_datasets = pipeline.process_bulk(
       warc_files=["archive1.warc.gz", "archive2.warc.gz"],
       output_dir="processed_datasets/",
       partitions=["domain", "language"],
       parallel_workers=4
   )
   ```

#### Data Extraction and Transformation

The module provides tools for extracting and transforming web content from WARC files into structured datasets:

1. **Content Extraction**:
   - HTML content extraction
   - Plain text extraction with various cleaning options
   - Metadata extraction (headers, timestamps, MIME types)
   - Link extraction and analysis
   - Image and media extraction
   - Structured data extraction (JSON-LD, microdata, etc.)

2. **Transformations**:
   - Content deduplication
   - Language detection and filtering
   - Content classification
   - Named entity recognition
   - Text normalization
   - HTML cleaning and boilerplate removal

3. **Output Formats**:
   - Hugging Face Datasets
   - Apache Parquet files
   - Arrow Tables
   - DuckDB databases
   - IPFS-compatible CAR files

#### Integration with Machine Learning Pipelines

The extracted web content can be directly piped into machine learning pipelines:

```python
# Create a dataset from Common Crawl and fine-tune a model
cc_dataset = web_archive_utils.query_and_process_common_crawl(
    domain="stackoverflow.com",
    url_pattern="*/questions/*",
    extract_qa_pairs=True
)

# Convert to format suitable for model training
training_dataset = cc_dataset.prepare_for_training(
    text_field="answer_text",
    metadata_fields=["tags", "upvotes"]
)

# Use with Hugging Face Transformers
from transformers import Trainer, TrainingArguments
trainer = Trainer(
    model=model,
    args=TrainingArguments(...),
    train_dataset=training_dataset
)
trainer.train()
```

## Multimedia Scraping and Processing Integration

### YT-DLP Video and Audio Scraping

IPFS Datasets Python integrates YT-DLP for downloading content from 1000+ platforms including YouTube, Vimeo, SoundCloud, TikTok, and many others.

#### Core YT-DLP Integration

```python
from ipfs_datasets_py.multimedia import YtDlpWrapper
from ipfs_datasets_py.mcp_server.tools.media_tools import (
    ytdlp_download_video, ytdlp_download_playlist, 
    ytdlp_extract_info, ytdlp_search_videos, ytdlp_batch_download
)

# Initialize YT-DLP wrapper
ytdlp = YtDlpWrapper(
    default_output_dir="downloads",
    default_quality="best[height<=720]"
)

# Download single video with comprehensive metadata
result = await ytdlp_download_video(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    output_dir="multimedia_datasets/videos",
    quality="best[height<=1080]",
    download_info_json=True,
    download_thumbnails=True,
    subtitle_langs=["en", "auto", "es"],
    custom_opts={
        "writesubtitles": True,
        "writeautomaticsub": True,
        "writedescription": True,
        "writeinfojson": True
    }
)

# Download entire playlists for large datasets
playlist_result = await ytdlp_download_playlist(
    url="https://www.youtube.com/playlist?list=PLrAXtmRdnEQy5JBZM-0P3KKiMxz5e3fXr",
    output_dir="multimedia_datasets/playlists",
    quality="best[height<=720]",
    max_downloads=100,
    download_info_json=True,
    archive_file="downloaded_videos.txt"  # Track downloads
)

# Extract metadata without downloading for dataset analysis
info_result = await ytdlp_extract_info(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    extract_flat=False
)

print(f"Video metadata: {info_result['title']}, {info_result['duration']}s")
print(f"Uploader: {info_result['uploader']}, Views: {info_result['view_count']}")
```

### FFmpeg Media Processing Integration

Professional media processing and conversion with FFmpeg integration:

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import (
    ffmpeg_convert, ffmpeg_mux, ffmpeg_demux,
    ffmpeg_cut, ffmpeg_splice, ffmpeg_concat,
    ffmpeg_probe, ffmpeg_analyze, ffmpeg_apply_filters,
    ffmpeg_batch_process, ffmpeg_stream_input, ffmpeg_stream_output
)

# Convert videos to standardized formats for ML datasets
conversion_result = await ffmpeg_convert(
    input_file="raw_video.webm",
    output_file="processed/standardized.mp4",
    video_codec="libx264",
    audio_codec="aac",
    resolution="1280x720",
    quality="medium",
    custom_options={
        "preset": "medium",
        "crf": "23",  # Constant rate factor for quality
        "profile": "high",
        "level": "4.0"
    }
)

# Extract audio for speech/music analysis
audio_extraction = await ffmpeg_convert(
    input_file="video.mp4",
    output_file="audio/extracted.wav",
    video_codec=None,  # Remove video stream
    audio_codec="pcm_s16le",  # Uncompressed for analysis
    audio_sampling_rate="16000",  # Standard for speech processing
    audio_channels=1  # Mono for speech
)

# Extract frames for computer vision datasets
frames_result = await ffmpeg_convert(
    input_file="video.mp4",
    output_file="frames/frame_%04d.jpg",
    custom_options={
        "vf": "fps=1",         # 1 frame per second
        "q:v": "2",            # High quality JPEG
        "start_number": "0"    # Start numbering from 0
    }
)

# Batch processing for large datasets
batch_result = await ffmpeg_batch_process(
    input_files=["video1.mp4", "video2.webm", "video3.avi"],
    output_directory="processed_batch/",
    operation="convert",
    operation_params={
        "video_codec": "libx264",
        "audio_codec": "aac",
        "resolution": "854x480",
        "quality": "medium"
    },
    max_parallel=4,
    progress_callback=lambda status: print(f"Progress: {status['completed']}/{status['total']}")
)
```

### Comprehensive Web Scraping Strategies

```python
async def comprehensive_web_scraping_pipeline(targets):
    """
    Comprehensive web scraping combining all available methods:
    - Traditional web archiving (WARC/IPWB)
    - Internet Archive queries
    - Common Crawl data
    - Archive.is archiving
    - Multimedia content scraping (YT-DLP)
    """
    
    results = {
        'web_archives': [],
        'multimedia_content': [],
        'wayback_captures': [],
        'common_crawl_data': [],
        'archive_is_snapshots': []
    }
    
    for target in targets:
        target_type = target['type']
        url = target['url']
        
        try:
            if target_type == 'web_archive':
                # Traditional web archiving
                warc_path = processor.create_warc(
                    url=url,
                    options=target.get('options', {"agent": "wget", "depth": 1})
                )
                
                # Index to IPFS
                index_result = processor.index_warc(warc_path)
                
                # Archive to multiple services
                ia_url = archivenow.push(url, "ia")
                is_url = archivenow.push(url, "is")
                
                results['web_archives'].append({
                    'url': url,
                    'warc_path': warc_path,
                    'ipfs_hash': index_result['ipfs_hash'],
                    'internet_archive_url': ia_url,
                    'archive_is_url': is_url
                })
                
            elif target_type == 'multimedia':
                # Multimedia content scraping
                if 'playlist' in url:
                    download_result = await ytdlp_download_playlist(
                        url=url,
                        output_dir="multimedia_content",
                        max_downloads=target.get('max_videos', 20)
                    )
                else:
                    download_result = await ytdlp_download_video(
                        url=url,
                        output_dir="multimedia_content",
                        quality=target.get('quality', 'best[height<=720]'),
                        download_info_json=True
                    )
                
                results['multimedia_content'].append(download_result)
                
        except Exception as e:
            print(f"Error processing {url}: {e}")
    
    return results

# Example comprehensive scraping configuration
scraping_targets = [
    {
        "type": "web_archive",
        "url": "https://example.com",
        "options": {"agent": "wget", "depth": 2}
    },
    {
        "type": "multimedia", 
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "quality": "720p"
    }
]

# Run comprehensive scraping
comprehensive_results = asyncio.run(
    comprehensive_web_scraping_pipeline(scraping_targets)
)
```

## Complete Integration Examples

### Example 1: Complete Data Processing and Storage Workflow

The following example demonstrates how DuckDB, HuggingFace, and Arrow components can be integrated to process and store datasets in multiple formats:

```python
from ipfs_datasets_py.data_integration import UnifiedDataLayer
from ipfs_datasets_py.duckdb_connector import DuckDBConnector
import pandas as pd

# Initialize components
data_layer = UnifiedDataLayer()
duckdb = DuckDBConnector("analytics.duckdb")

# 1. Load dataset from Huggingface
print("Loading dataset from Huggingface...")
dataset = data_layer.load_hf_dataset("wikipedia", "20220301.en", split="train")

# 2. Process using DuckDB for analytics
print("Processing with DuckDB...")
# First convert to Arrow
arrow_table = data_layer.hf_dataset_to_arrow(dataset)

# Create DuckDB table from Arrow
duckdb.create_table_from_arrow("wikipedia_raw", arrow_table)

# Run analytics query
processed_data = duckdb.query_to_arrow("""
    SELECT 
        id,
        title,
        url,
        text,
        LENGTH(text) as text_length,
        REGEXP_COUNT(LOWER(text), 'python') as python_mentions
    FROM wikipedia_raw
    WHERE text_length > 1000
    AND python_mentions > 0
    ORDER BY python_mentions DESC
    LIMIT 10000
""")

# 3. Export in multiple formats
print("Exporting data...")
# Export to Parquet
data_layer.arrow_to_parquet(processed_data, "wikipedia_python.parquet")

# Export to CAR file with content-addressing
data_layer.arrow_to_car(processed_data, "wikipedia_python.car", hash_columns=["id"])

# Export back to Huggingface Dataset
hf_processed = data_layer.arrow_to_hf_dataset(processed_data)
hf_processed.push_to_hub("myusername/wikipedia-python-articles")

print("Data processing and export complete!")
print(f"Processed {len(processed_data)} records")
print(f"Outputs: wikipedia_python.parquet, wikipedia_python.car, and dataset on HF Hub")
```

### Example 2: Knowledge Dataset from Web Archives

The following example demonstrates how all the components can be integrated into a complete workflow for building, storing, and querying a knowledge dataset from web archives:

```python
from ipfs_datasets_py import ipfs_datasets, web_archive_utils
from ipfs_datasets_py.ipld_storage import IPLDStorage
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
from ipfs_datasets_py.knowledge_graph import IPLDKnowledgeGraph
from archivenow import archivenow
import json

# Step 1: Archive a website using ArchiveNow
print("Creating web archive...")
warc_file = archivenow.push("https://en.wikipedia.org/wiki/IPFS", "warc", 
                           {"warc": "ipfs_wiki", "agent": "wget"})

# Step 2: Index the WARC file to IPFS using IPWB
print("Indexing to IPFS...")
from ipwb import indexer
cdxj_path = indexer.index_file_at(warc_file, outfile="ipfs_wiki.cdxj")

# Step 3: Extract structured data from the archive
print("Extracting structured data...")
# Create a processing pipeline for the web archive
pipeline = web_archive_utils.WARCProcessingPipeline(
    extraction_steps=[
        web_archive_utils.extractors.HTMLExtractor(),
        web_archive_utils.extractors.TextExtractor(),
        web_archive_utils.extractors.EntityExtractor(),
        web_archive_utils.extractors.LinkExtractor()
    ],
    transformation_steps=[
        web_archive_utils.transformers.HTMLCleaner(),
        web_archive_utils.transformers.TextNormalizer(),
        web_archive_utils.transformers.EntityLinker()
    ],
    output_format="dataset"
)

# Process the archive into a dataset
dataset = pipeline.process(cdxj_path)

# Step 4: Create vector embeddings and store in IPLD
print("Creating embeddings...")
# Initialize IPLD storage
ipld_storage = IPLDStorage()

# Create vector embeddings for the text content
embedding_model = ipfs_datasets.load_embedding_model("sentence-transformers/all-MiniLM-L6-v2")
text_chunks = dataset.get_chunked_texts(chunk_size=512, overlap=50)
embeddings = [embedding_model.encode(chunk) for chunk in text_chunks]

# Create vector index
vector_index = IPFSKnnIndex(dimension=embedding_model.dimension)
vector_ids = vector_index.add_vectors(embeddings, metadata={
    "source": "wikipedia",
    "topic": "ipfs",
    "chunks": text_chunks
})

# Step 5: Build knowledge graph from extracted entities
print("Building knowledge graph...")
kg = IPLDKnowledgeGraph()

# Add entities from the dataset
for entity in dataset.get_entities():
    entity_cid = kg.add_entity({
        "name": entity.name,
        "type": entity.type,
        "mentions": entity.mentions,
        "vector_ids": [vector_ids[i] for i in entity.chunk_indices]
    })

# Add relationships between entities
for relation in dataset.get_relations():
    kg.add_relationship(
        source_cid=relation.source_entity_cid,
        target_cid=relation.target_entity_cid,
        relationship_type=relation.type,
        properties=relation.properties
    )

# Step 6: Export everything to CAR files for distribution
print("Exporting to CAR files...")
# Export vector index to CAR
index_car = vector_index.export_to_car("ipfs_wiki_vectors.car")

# Export knowledge graph to CAR
kg_car = kg.export_to_car("ipfs_wiki_knowledge_graph.car")

# Create a root object linking everything together
dataset_root = {
    "name": "IPFS Wikipedia Dataset",
    "description": "Knowledge dataset created from Wikipedia IPFS article",
    "source_warc": warc_file,
    "cdxj_index": cdxj_path,
    "vector_index_cid": vector_index.root_cid,
    "knowledge_graph_cid": kg.root_cid,
    "created_at": datetime.datetime.now().isoformat()
}

# Store the root object
root_cid = ipld_storage.store(json.dumps(dataset_root).encode())
ipld_storage.export_to_car([root_cid], "ipfs_wiki_dataset_root.car")

print(f"Dataset creation complete. Root CID: {root_cid}")

# Step 7: Query the dataset
print("Performing hybrid vector + graph query...")
query = "How does IPFS handle content addressing?"
query_embedding = embedding_model.encode(query)

# Vector search to find relevant chunks
vector_results = vector_index.search(query_embedding, top_k=5)

# Get entities mentioned in the most relevant chunks
mentioned_entities = kg.get_entities_by_vector_ids(
    [result.id for result in vector_results]
)

# Perform graph traversal to find related concepts
related_concepts = kg.traverse_from_entities(
    mentioned_entities,
    relationship_types=["RELATED_TO", "IS_PART_OF"],
    max_depth=2
)

# Combine results for a comprehensive answer
print("Results:")
for result in vector_results:
    print(f"- {result.metadata['chunks'][result.metadata_index][:100]}...")

print("\nRelated concepts:")
for concept in related_concepts:
    print(f"- {concept.properties['name']} ({concept.properties['type']})")
```

This integrated example demonstrates:
1. Creating a web archive with ArchiveNow
2. Indexing it to IPFS with IPWB
3. Processing the archive into structured data
4. Creating and storing vector embeddings using IPLD
5. Building a knowledge graph with entity relationships
6. Exporting everything to CAR files for distribution
7. Performing hybrid vector and graph-based queries

The implementation provides a complete end-to-end workflow for building decentralized, content-addressed datasets with rich semantic knowledge and efficient retrieval capabilities.

## Data Processing and Storage Integration

### DuckDB, Arrow, and Huggingface Datasets Integration

#### Overview
This module provides a unified interface for working with multiple data processing libraries (DuckDB, Arrow, Huggingface Datasets) and enables seamless conversion between these formats and IPLD/IPFS storage formats.

#### Key Features
- Support for multiple data sources and formats (DuckDB, Arrow, Huggingface Datasets)
- Direct query execution on data with DuckDB without format conversion
- Bidirectional conversion between all formats and IPLD
- Export capabilities to both Parquet and CAR files from any source
- Streaming processing for large datasets
- Memory-efficient operations with zero-copy when possible

#### Architecture

```
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
│  Huggingface      │  │     DuckDB        │  │  Apache Arrow     │
│    Datasets       │  │    Database       │  │     Tables        │
└─────────┬─────────┘  └──────┬────────────┘  └─────────┬─────────┘
          │                   │                         │
          └───────────────────┼─────────────────────────┘
                              │
                              ▼
                 ┌───────────────────────────────┐
                 │      Unified Data Layer       │
                 └─────────────────┬─────────────┘
                                   │
                                   ▼
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
│   Parquet Files   │  │    IPLD Blocks    │  │    CAR Files      │
└───────────────────┘  └───────────────────┘  └───────────────────┘
```

#### DuckDB Integration Components

```python
class DuckDBConnector:
    """Interface for working with DuckDB databases and exporting to IPFS."""
    
    def __init__(self, database_path=":memory:"):
        """
        Initialize DuckDB connector.
        
        Args:
            database_path: str - Path to DuckDB database file or ":memory:"
        """
        
    def query_to_arrow(self, query):
        """
        Execute SQL query and return results as Arrow table.
        
        Args:
            query: str - SQL query to execute
            
        Returns:
            pyarrow.Table - Query results as Arrow table
        """
        
    def query_to_ipld(self, query, hash_columns=None):
        """
        Execute SQL query and convert results to IPLD.
        
        Args:
            query: str - SQL query to execute
            hash_columns: list - Column names to use for content-addressing
            
        Returns:
            tuple: (root_cid, {cid: block_data}) - Root CID and blocks
        """
        
    def export_to_car(self, query, output_path, hash_columns=None):
        """
        Execute SQL query and export results directly to CAR file.
        
        Args:
            query: str - SQL query to execute
            output_path: str - Path to output CAR file
            hash_columns: list - Column names to use for content-addressing
        """
        
    def export_to_parquet(self, query, output_path):
        """
        Execute SQL query and export results to Parquet file.
        
        Args:
            query: str - SQL query to execute
            output_path: str - Path to output Parquet file
        """
        
    def import_from_car(self, car_path, table_name):
        """
        Import data from CAR file into DuckDB table.
        
        Args:
            car_path: str - Path to input CAR file
            table_name: str - Name of table to create
            
        Returns:
            int - Number of rows imported
        """
        
    def import_from_parquet(self, parquet_path, table_name):
        """
        Import data from Parquet file into DuckDB table.
        
        Args:
            parquet_path: str - Path to input Parquet file
            table_name: str - Name of table to create
            
        Returns:
            int - Number of rows imported
        """
```

#### HuggingFace Datasets Integration

```python
class HFDatasetsConnector:
    """Interface for working with Huggingface Datasets and exporting to IPFS."""
    
    def __init__(self):
        """Initialize HuggingFace Datasets connector."""
        
    def load_dataset(self, dataset_name, **kwargs):
        """
        Load a dataset from Huggingface Datasets.
        
        Args:
            dataset_name: str - Name of dataset to load
            **kwargs - Additional arguments for datasets.load_dataset
            
        Returns:
            Dataset - Loaded dataset
        """
        
    def dataset_to_arrow(self, dataset, split="train"):
        """
        Convert dataset to Arrow table.
        
        Args:
            dataset: Dataset - Huggingface dataset
            split: str - Dataset split to convert
            
        Returns:
            pyarrow.Table - Dataset as Arrow table
        """
        
    def dataset_to_ipld(self, dataset, split="train", hash_columns=None):
        """
        Convert dataset to IPLD.
        
        Args:
            dataset: Dataset - Huggingface dataset
            split: str - Dataset split to convert
            hash_columns: list - Column names to use for content-addressing
            
        Returns:
            tuple: (root_cid, {cid: block_data}) - Root CID and blocks
        """
        
    def export_to_car(self, dataset, output_path, split="train", hash_columns=None):
        """
        Export dataset directly to CAR file.
        
        Args:
            dataset: Dataset - Huggingface dataset
            output_path: str - Path to output CAR file
            split: str - Dataset split to export
            hash_columns: list - Column names to use for content-addressing
        """
        
    def import_from_car(self, car_path):
        """
        Import dataset from CAR file.
        
        Args:
            car_path: str - Path to input CAR file
            
        Returns:
            Dataset - Imported dataset
        """
```

### Apache Arrow Integration with IPLD and IPFS

#### Overview
This module provides utilities for seamless conversion between Apache Arrow columnar data and IPLD, with support for IPFS CAR export/import and interprocess communication using the C Dataset Interchange Format.

#### Key Features
- Bidirectional conversion between Arrow tables and IPLD
- Content-addressed data using hashed indexes
- Efficient interprocess communication with Arrow C Data Interface
- Import/export between Parquet files and IPFS CAR archives
- Streaming processing for large datasets
- Memory-efficient operations with zero-copy when possible

### Architecture

```
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
│   Arrow Tables    │◀─┤  IPLD Converter   │─▶│    IPLD Blocks    │
└───────────────────┘  └───────────────────┘  └───────────────────┘
         ▲                      │                     │
         │                      │                     ▼
┌───────────────────┐          │             ┌───────────────────┐
│   Parquet Files   │◀─────────┼──────┬─────▶│     CAR Files     │
└───────────────────┘          │      │      └───────────────────┘
         ▲                     ▼      ▼              │
         │            ┌───────────────────┐          │
         └────────────┤ Dataset Utilities │◀─────────┘
                      └───────────────────┘
                              │
                              ▼
                     ┌───────────────────┐
                     │    IPC Channel    │
                     └───────────────────┘
```

### Components

#### 1. Arrow-IPLD Converter

```python
class ArrowIPLDConverter:
    """Convert between Apache Arrow tables and IPLD structures."""
    
    def table_to_ipld(self, table, hash_columns=None):
        """
        Convert Arrow table to IPLD blocks with optional content-addressing.
        
        Args:
            table: pyarrow.Table - The Arrow table to convert
            hash_columns: list - Column names to use for content-addressing
            
        Returns:
            tuple: (root_cid, {cid: block_data}) - Root CID and blocks
        """
        
    def ipld_to_table(self, root_cid, blocks):
        """
        Convert IPLD blocks back to Arrow table.
        
        Args:
            root_cid: CID - The root CID of the table structure
            blocks: dict - Dictionary of {cid: block_data}
            
        Returns:
            pyarrow.Table - The reconstructed Arrow table
        """
        
    def schema_to_ipld(self, schema):
        """
        Convert Arrow schema to IPLD representation.
        
        Args:
            schema: pyarrow.Schema - The Arrow schema
            
        Returns:
            tuple: (schema_cid, schema_block) - CID and serialized schema
        """
```

#### 2. Data Interchange Utilities

```python
class DataInterchangeUtils:
    """Utilities for data interchange between processes and formats."""
    
    def export_table_to_car(self, table, output_path, hash_columns=None):
        """
        Export Arrow table to CAR file with content-addressing.
        
        Args:
            table: pyarrow.Table - The Arrow table to export
            output_path: str - Path to output CAR file
            hash_columns: list - Column names to use for content-addressing
        """
        
    def import_table_from_car(self, car_path):
        """
        Import Arrow table from CAR file.
        
        Args:
            car_path: str - Path to input CAR file
            
        Returns:
            pyarrow.Table - The imported Arrow table
        """
        
    def parquet_to_car(self, parquet_path, car_path, hash_columns=None):
        """
        Convert Parquet file to CAR file with content-addressing.
        
        Args:
            parquet_path: str - Path to input Parquet file
            car_path: str - Path to output CAR file
            hash_columns: list - Column names to use for content-addressing
        """
        
    def car_to_parquet(self, car_path, parquet_path):
        """
        Convert CAR file to Parquet file.
        
        Args:
            car_path: str - Path to input CAR file
            parquet_path: str - Path to output Parquet file
        """
        
    def get_c_data_interface(self, table):
        """
        Get C Data Interface representation for interprocess communication.
        
        Args:
            table: pyarrow.Table - The Arrow table to share
            
        Returns:
            dict - C Data Interface representation
        """
        
    def table_from_c_data_interface(self, c_data):
        """
        Reconstruct Arrow table from C Data Interface representation.
        
        Args:
            c_data: dict - C Data Interface representation
            
        Returns:
            pyarrow.Table - The reconstructed Arrow table
        """
```

#### 3. Streaming Processing for Large Datasets

```python
class StreamingProcessor:
    """Process large datasets with streaming to minimize memory usage."""
    
    def stream_parquet_to_car(self, parquet_path, car_path, batch_size=10000):
        """
        Stream Parquet file to CAR file in batches.
        
        Args:
            parquet_path: str - Path to input Parquet file
            car_path: str - Path to output CAR file
            batch_size: int - Number of rows per batch
        """
        
    def stream_car_to_parquet(self, car_path, parquet_path, batch_size=10000):
        """
        Stream CAR file to Parquet file in batches.
        
        Args:
            car_path: str - Path to input CAR file
            parquet_path: str - Path to output Parquet file
            batch_size: int - Number of rows per batch
        """
```

### Usage Examples

#### 1. Converting Between Formats with Unified Data Layer

```python
from ipfs_datasets_py.data_integration import UnifiedDataLayer

# Initialize the unified data layer
data_layer = UnifiedDataLayer()

# Example 1: DuckDB to CAR file
data_layer.duckdb_to_car(
    query="SELECT * FROM my_table WHERE category = 'science'",
    car_path="science_data.car",
    db_path="my_database.duckdb",
    hash_columns=["id", "timestamp"]
)

# Example 2: DuckDB to Parquet file
data_layer.duckdb_to_parquet(
    query="SELECT * FROM my_table WHERE category = 'science'",
    parquet_path="science_data.parquet",
    db_path="my_database.duckdb"
)

# Example 3: Huggingface Dataset to CAR file
data_layer.hf_dataset_to_car(
    dataset_name="wikipedia",
    split="train",
    car_path="wikipedia_train.car",
    hash_columns=["id"]
)

# Example 4: Huggingface Dataset to Parquet file
data_layer.hf_dataset_to_parquet(
    dataset_name="wikipedia",
    split="train",
    parquet_path="wikipedia_train.parquet"
)

# Example 5: Converting between formats
data_layer.parquet_to_car(
    parquet_path="my_dataset.parquet",
    car_path="my_dataset.car",
    hash_columns=["id", "timestamp"]  # Use these columns for content-addressing
)

# Example 6: Converting CAR to Parquet
data_layer.car_to_parquet(
    car_path="my_dataset.car",
    parquet_path="reconstructed_dataset.parquet"
)
```

#### 2. DuckDB Direct Export Examples

```python
from ipfs_datasets_py.duckdb_connector import DuckDBConnector

# Initialize DuckDB connector
duckdb = DuckDBConnector(database_path="my_analytics.duckdb")

# Execute query and export directly to CAR file
duckdb.export_to_car(
    query="""
    SELECT 
        date, 
        category, 
        SUM(revenue) as total_revenue, 
        COUNT(DISTINCT user_id) as unique_users
    FROM sales
    WHERE date BETWEEN '2023-01-01' AND '2023-12-31'
    GROUP BY date, category
    ORDER BY date, total_revenue DESC
    """,
    output_path="sales_summary_2023.car",
    hash_columns=["date", "category"]
)

# Execute query and export directly to Parquet file
duckdb.export_to_parquet(
    query="""
    SELECT * FROM web_events
    WHERE event_type = 'purchase'
    AND timestamp >= CURRENT_DATE - INTERVAL 30 DAY
    """,
    output_path="recent_purchases.parquet"
)

# Convert data from CAR file and load into DuckDB table
rows_imported = duckdb.import_from_car(
    car_path="external_dataset.car",
    table_name="external_data"
)
print(f"Imported {rows_imported} rows from CAR file")

# Query combining data from different sources
result = duckdb.query_to_arrow("""
    SELECT 
        e.user_id,
        e.event_type,
        u.signup_date,
        u.country
    FROM web_events e
    JOIN external_data.users u ON e.user_id = u.id
    WHERE e.timestamp >= '2023-01-01'
""")
```

#### 3. Working with Arrow Tables and IPLD

```python
import pyarrow as pa
from ipfs_datasets_py.arrow_ipld import ArrowIPLDConverter

# Create an Arrow table
data = {
    "id": pa.array([1, 2, 3, 4]),
    "name": pa.array(["Alice", "Bob", "Charlie", "Dave"]),
    "value": pa.array([10.1, 12.3, 15.7, 9.8])
}
table = pa.Table.from_pydict(data)

# Convert to IPLD
converter = ArrowIPLDConverter()
root_cid, blocks = converter.table_to_ipld(table, hash_columns=["id"])

# Export blocks to CAR file
with open("table_blocks.car", "wb") as f:
    car_data = ipld_car.encode([root_cid], [(cid, block) for cid, block in blocks.items()])
    f.write(car_data)

# Reconstruct table from IPLD
reconstructed_table = converter.ipld_to_table(root_cid, blocks)
```

#### 4. Interprocess Communication with C Data Interface

```python
import pyarrow as pa
from ipfs_datasets_py.arrow_ipld import DataInterchangeUtils
import json
import os

# Process 1: Prepare and share data
data = pa.table({
    "id": range(1000),
    "values": [float(i * 2) for i in range(1000)]
})

interchange = DataInterchangeUtils()
c_data = interchange.get_c_data_interface(data)

# Serialize the interface data (except for the actual memory buffers)
interface_json = json.dumps({
    "schema": c_data["schema"],
    "buffer_addresses": [int(addr) for addr in c_data["buffers"]]
})

# Write to shared location
with open("/tmp/shared_arrow_metadata.json", "w") as f:
    f.write(interface_json)

# Use shared memory for actual data buffers
# (In a real scenario this would use shared memory segments)

# Process 2: Receive and use the data
with open("/tmp/shared_arrow_metadata.json", "r") as f:
    interface_data = json.loads(f.read())

# Reconstruct the interface data with actual memory references
# (In a real scenario this would attach to shared memory segments)

# Reconstruct table
received_table = interchange.table_from_c_data_interface(interface_data)
```

#### 5. Streaming Large Datasets

```python
from ipfs_datasets_py.arrow_ipld import StreamingProcessor

processor = StreamingProcessor()

# Process a large Parquet file in batches, converting to CAR
processor.stream_parquet_to_car(
    parquet_path="large_dataset.parquet",
    car_path="large_dataset.car",
    batch_size=50000  # Process 50k rows at a time
)
```

### IPLD Schema for Arrow Data

The following IPLD schema represents the structure used for storing Arrow tables:

```json
{
  "types": {
    "ArrowTable": {
      "type": "struct",
      "fields": {
        "schema": {"type": "link", "linkedType": "ArrowSchema"},
        "batches": {"type": "list", "valueType": {"type": "link", "linkedType": "RecordBatch"}}
      }
    },
    "ArrowSchema": {
      "type": "struct",
      "fields": {
        "fields": {"type": "list", "valueType": {"type": "link", "linkedType": "Field"}},
        "metadata": {"type": "map", "keyType": "string", "valueType": "string"}
      }
    },
    "Field": {
      "type": "struct",
      "fields": {
        "name": {"type": "string"},
        "type": {"type": "link", "linkedType": "DataType"},
        "nullable": {"type": "bool"},
        "metadata": {"type": "map", "keyType": "string", "valueType": "string"}
      }
    },
    "DataType": {
      "type": "union", 
      "variants": {
        "int": "Int",
        "float": "Float",
        "string": "String",
        "bool": "Bool",
        "list": "List",
        "struct": "Struct",
        "binary": "Binary",
        "date": "Date",
        "time": "Time",
        "timestamp": "Timestamp"
      }
    },
    "RecordBatch": {
      "type": "struct",
      "fields": {
        "rowCount": {"type": "int"},
        "columns": {"type": "list", "valueType": {"type": "link", "linkedType": "Column"}}
      }
    },
    "Column": {
      "type": "struct",
      "fields": {
        "name": {"type": "string"},
        "data": {"type": "link", "linkedType": "ColumnData"}
      }
    },
    "ColumnData": {
      "type": "bytes"
    }
  }
}
```

### Performance Considerations

1. **Memory Efficiency**
   - Use zero-copy approaches when possible
   - Stream large datasets in manageable batches
   - Employ memory mapping for large files

2. **Content Addressing**
   - Choose hash columns strategically based on natural keys
   - Consider partial addressing of only key columns
   - Use hierarchical chunking for large columns

3. **Interprocess Communication**
   - Prefer shared memory over serialization/deserialization
   - Use Arrow's built-in IPC mechanisms for local processes
   - Consider RDMA for high-performance computing contexts

4. **Parallel Processing**
   - Leverage Arrow's support for parallel computation
   - Use worker pools for batch processing
   - Implement partition-aware data handling

## GraphRAG Implementation with IPFS/IPLD

### Overview
This module implements a GraphRAG (Graph Retrieval Augmented Generation) system using IPFS/IPLD as the storage layer. The system processes files stored on IPFS by generating multiple embedding vectors using different models and extracting knowledge graphs for enhanced retrieval capabilities.

#### Key Features
- Multi-model vector embedding generation for each document
- Automated knowledge graph extraction from stored content
- Hybrid search combining graph traversal and vector similarity
- Content-addressed storage of all components using IPFS/IPLD
- Incremental indexing of new content with relationship detection
- Query processing with both semantic and structural awareness

### Architecture

```
                        ┌───────────────────┐
                        │    Input Files    │
                        └────────┬──────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────┐
│                 Processing Pipeline                  │
├──────────────┬──────────────────────┬───────────────┤
│ Text         │ Multi-model          │ Knowledge     │
│ Extraction   │ Embedding Generation │ Graph         │
│              │                      │ Extraction    │
└──────┬───────┴──────────┬───────────┴───────┬───────┘
       │                  │                   │
       ▼                  ▼                   ▼
┌────────────┐   ┌────────────────┐   ┌─────────────────┐
│   IPLD     │   │  IPLD Vector   │   │  IPLD Graph     │
│ Document   │   │    Store       │   │    Store        │
│   Store    │   │ (Multi-model)  │   │                 │
└─────┬──────┘   └────────┬───────┘   └────────┬────────┘
      │                   │                    │
      └───────────────────┼────────────────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │    GraphRAG Query       │
              │       Engine            │
              └─────────────────────────┘
                          │
                          ▼
              ┌─────────────────────────┐
              │    Search Results       │
              │  (Combined Ranking)     │
              └─────────────────────────┘
```

### Components

#### 1. Multi-model Embedding Generator

```python
class MultiModelEmbeddingGenerator:
    """Generate embeddings using multiple models for comprehensive representation."""
    
    def __init__(self, model_configs=None):
        """
        Initialize with multiple embedding models.
        
        Args:
            model_configs: list - List of model configurations
                Example: [
                    {"name": "all-MiniLM-L6-v2", "dimension": 384, "type": "sentence"},
                    {"name": "e5-large", "dimension": 1024, "type": "passage"},
                    {"name": "instructor-xl", "dimension": 768, "type": "instruction"}
                ]
        """
        
    def generate_embeddings(self, text, chunk_size=512, overlap=50):
        """
        Generate embeddings using all configured models.
        
        Args:
            text: str - Text to embed
            chunk_size: int - Size of text chunks
            overlap: int - Overlap between chunks
            
        Returns:
            dict - Map of model name to list of embeddings
        """
        
    def store_on_ipfs(self, embeddings, metadata=None):
        """
        Store embeddings on IPFS using IPLD.
        
        Args:
            embeddings: dict - Map of model name to embeddings
            metadata: dict - Additional metadata
            
        Returns:
            dict - Map of model name to CIDs
        """
        
    @classmethod
    def from_config(cls, config_path):
        """
        Create generator from configuration file.
        
        Args:
            config_path: str - Path to configuration file
            
        Returns:
            MultiModelEmbeddingGenerator
        """
```

#### 2. Knowledge Graph Extractor

```python
class KnowledgeGraphExtractor:
    """Extract knowledge graph from text documents."""
    
    def __init__(self, extraction_models=None):
        """
        Initialize with extraction models.
        
        Args:
            extraction_models: dict - Map of extraction model types to model names
                Example: {
                    "entity": "spacy_large",
                    "relation": "rebel-large",
                    "coreference": "neuralcoref",
                    "concept": "dbpedia-spotlight"
                }
        """
        
    def extract_graph(self, text, document_cid=None):
        """
        Extract knowledge graph from text.
        
        Args:
            text: str - Text to extract from
            document_cid: str - CID of source document
            
        Returns:
            tuple - (entities, relationships)
        """
        
    def merge_with_existing(self, new_graph, existing_graph_cid):
        """
        Merge new graph with existing graph.
        
        Args:
            new_graph: tuple - (entities, relationships)
            existing_graph_cid: str - CID of existing graph
            
        Returns:
            tuple - (merged_entities, merged_relationships, updated_cid)
        """
        
    def store_on_ipfs(self, entities, relationships, metadata=None):
        """
        Store knowledge graph on IPFS using IPLD.
        
        Args:
            entities: list - List of entity objects
            relationships: list - List of relationship objects
            metadata: dict - Additional metadata
            
        Returns:
            str - Root CID of knowledge graph
        """
```

#### 3. GraphRAG Query Engine

```python
class GraphRAGQueryEngine:
    """Query engine combining vector search and graph traversal."""
    
    def __init__(self, vector_stores, graph_store, model_weights=None):
        """
        Initialize with vector stores and graph store.
        
        Args:
            vector_stores: dict - Map of model name to vector store
            graph_store: GraphStore - Knowledge graph store
            model_weights: dict - Weights for each model's results
        """
        
    def query(self, query_text, top_k=10, max_graph_hops=2, 
              min_relevance=0.7, combine_method="weighted"):
        """
        Perform GraphRAG query.
        
        Args:
            query_text: str - Query text
            top_k: int - Number of results to return
            max_graph_hops: int - Maximum graph traversal hops
            min_relevance: float - Minimum relevance score
            combine_method: str - Method to combine results
            
        Returns:
            list - Ranked results with metadata
        """
        
    def vector_search(self, query_embedding, models=None):
        """
        Perform vector search across specified models.
        
        Args:
            query_embedding: dict - Map of model name to query embedding
            models: list - Models to search, None for all
            
        Returns:
            dict - Map of model name to search results
        """
        
    def graph_search(self, seed_entities, max_hops=2, relation_types=None):
        """
        Perform graph search from seed entities.
        
        Args:
            seed_entities: list - List of seed entity CIDs
            max_hops: int - Maximum traversal hops
            relation_types: list - Types of relations to traverse
            
        Returns:
            list - Graph search results
        """
        
    def combine_results(self, vector_results, graph_results, method="weighted"):
        """
        Combine vector and graph search results.
        
        Args:
            vector_results: dict - Vector search results by model
            graph_results: list - Graph search results
            method: str - Combination method
            
        Returns:
            list - Combined and ranked results
        """
```

#### 4. IPFS File Processor

```python
class IPFSFileProcessor:
    """Process files stored on IPFS for GraphRAG indexing."""
    
    def __init__(self, embedding_generator, graph_extractor):
        """
        Initialize with embedding generator and graph extractor.
        
        Args:
            embedding_generator: MultiModelEmbeddingGenerator
            graph_extractor: KnowledgeGraphExtractor
        """
        
    def process_file(self, file_path=None, ipfs_cid=None, file_type=None):
        """
        Process a file for GraphRAG indexing.
        
        Args:
            file_path: str - Path to local file
            ipfs_cid: str - CID of file already on IPFS
            file_type: str - Type of file
            
        Returns:
            dict - Processing results with CIDs
        """
        
    def process_directory(self, dir_path, recursive=True, file_types=None):
        """
        Process a directory of files.
        
        Args:
            dir_path: str - Path to directory
            recursive: bool - Process subdirectories
            file_types: list - File types to process
            
        Returns:
            dict - Processing results by file
        """
        
    def update_index(self, new_cids, graph_cid=None):
        """
        Update GraphRAG index with new content.
        
        Args:
            new_cids: list - New content CIDs
            graph_cid: str - Existing graph CID
            
        Returns:
            dict - Updated index CIDs
        """
```

### Integration with IPLD/IPFS Storage

The GraphRAG system uses IPLD structures to store all components with content-addressing:

1. **Document Storage**:
   - Raw content stored as IPLD blocks
   - Metadata linked to content via CIDs
   - Version history maintained through linked IPLD structures

2. **Multi-model Vector Storage**:
   - Each embedding model has its own vector space
   - Vectors linked to source document CIDs
   - Efficient nearest-neighbor search via IPLD structures

3. **Knowledge Graph Storage**:
   - Entities and relationships stored as IPLD nodes and links
   - Entity nodes contain properties and link to document CIDs
   - Relationship links connect entity nodes with typed edges

4. **Index Structure**:
   - Root index links to all vector stores and the knowledge graph
   - Updates are made by creating new IPLD nodes and updating links
   - Historical versions preserved through immutable IPLD structures

### Usage Examples

#### 1. Processing Files for GraphRAG

```python
import datetime
from ipfs_datasets_py.graphrag import IPFSFileProcessor, MultiModelEmbeddingGenerator, KnowledgeGraphExtractor

# Initialize components
embedding_generator = MultiModelEmbeddingGenerator([
    {"name": "sentence-transformers/all-MiniLM-L6-v2", "dimension": 384, "type": "sentence"},
    {"name": "sentence-transformers/multi-qa-mpnet-base-dot-v1", "dimension": 768, "type": "qa"}
])

graph_extractor = KnowledgeGraphExtractor({
    "entity": "spacy_large",
    "relation": "rebel-large"
})

processor = IPFSFileProcessor(embedding_generator, graph_extractor)

# Process a single PDF file
result = processor.process_file(
    file_path="/path/to/research_paper.pdf",
    file_type="pdf"
)

print(f"Document CID: {result['document_cid']}")
print(f"Embedding CIDs: {result['embedding_cids']}")
print(f"Graph CID: {result['graph_cid']}")

# Process a directory of files
directory_results = processor.process_directory(
    dir_path="/path/to/documents",
    recursive=True,
    file_types=["pdf", "docx", "txt"]
)

# Export index structure to CAR file
processor.export_index_to_car("graphrag_index.car")
```

#### 2. Querying with GraphRAG

```python
from ipfs_datasets_py.graphrag import GraphRAGQueryEngine
from ipfs_datasets_py.vector_store import IPLDVectorStore
from ipfs_datasets_py.knowledge_graph import IPLDKnowledgeGraph

# Initialize stores from CIDs
vector_stores = {
    "all-MiniLM-L6-v2": IPLDVectorStore.from_cid("bafybeihsl7tqdebswdmafvytgkofgxnpq5rwzzqpsbd7gtaiujwsn4qeyy"),
    "multi-qa-mpnet": IPLDVectorStore.from_cid("bafybeibtj5t2vxiiipnsbfji5qvlhv5zqbyblxcy7smtho2dup7g4zsqa")
}

graph_store = IPLDKnowledgeGraph.from_cid("bafybeicezu4acwofwzihqnqlipwytxnl5n5j7wr7rgxfjddj3m5jk4ux4q")

# Initialize query engine with store references
query_engine = GraphRAGQueryEngine(
    vector_stores=vector_stores,
    graph_store=graph_store,
    model_weights={
        "all-MiniLM-L6-v2": 0.3,
        "multi-qa-mpnet": 0.7
    }
)

# Perform a query
results = query_engine.query(
    query_text="How does IPFS handle content addressing?",
    top_k=5,
    max_graph_hops=2,
    combine_method="weighted"
)

# Display results
for i, result in enumerate(results):
    print(f"Result {i+1}: {result['text'][:100]}...")
    print(f"  Source: {result['source']}")
    print(f"  Relevance: {result['relevance']:.2f}")
    print(f"  Supporting Entities: {[e['name'] for e in result['entities']]}")
    print()
```

#### 3. Incremental Graph Building

```python
from ipfs_datasets_py.graphrag import KnowledgeGraphExtractor
from ipfs_datasets_py.knowledge_graph import IPLDKnowledgeGraph

# Initialize extractor
extractor = KnowledgeGraphExtractor()

# Get existing graph from IPFS
existing_graph_cid = "bafybeicezu4acwofwzihqnqlipwytxnl5n5j7wr7rgxfjddj3m5jk4ux4q"
existing_graph = IPLDKnowledgeGraph.from_cid(existing_graph_cid)

# Process new document
with open("/path/to/new_document.txt", "r") as f:
    text = f.read()

# Extract entities and relationships
new_entities, new_relationships = extractor.extract_graph(text)

# Merge with existing graph
merged_entities, merged_relationships, updated_cid = extractor.merge_with_existing(
    (new_entities, new_relationships),
    existing_graph_cid
)

print(f"New entities added: {len(merged_entities) - existing_graph.entity_count}")
print(f"New relationships added: {len(merged_relationships) - existing_graph.relationship_count}")
print(f"Updated graph CID: {updated_cid}")
```

### IPLD Schema for GraphRAG Components

#### Document Schema
```json
{
  "type": "struct",
  "fields": {
    "content": {"type": "bytes"},
    "metadata": {
      "type": "struct",
      "fields": {
        "title": {"type": "string"},
        "mimetype": {"type": "string"},
        "source": {"type": "string"},
        "created": {"type": "string"},
        "processed": {"type": "string"}
      }
    },
    "embeddings": {
      "type": "map",
      "keyType": "string",
      "valueType": {"type": "link"}
    },
    "graph": {"type": "link"},
    "chunks": {
      "type": "list",
      "valueType": {
        "type": "struct",
        "fields": {
          "text": {"type": "string"},
          "start": {"type": "int"},
          "end": {"type": "int"},
          "embeddings": {
            "type": "map",
            "keyType": "string",
            "valueType": {"type": "link"}
          }
        }
      }
    }
  }
}
```

#### Entity Schema
```json
{
  "type": "struct",
  "fields": {
    "id": {"type": "string"},
    "name": {"type": "string"},
    "type": {"type": "string"},
    "properties": {"type": "map", "keyType": "string", "valueType": "any"},
    "mentions": {
      "type": "list",
      "valueType": {
        "type": "struct",
        "fields": {
          "document_cid": {"type": "link"},
          "chunk_index": {"type": "int"},
          "start": {"type": "int"},
          "end": {"type": "int"},
          "text": {"type": "string"}
        }
      }
    },
    "vector_ids": {
      "type": "map",
      "keyType": "string",
      "valueType": {"type": "list", "valueType": "string"}
    }
  }
}
```

#### Relationship Schema
```json
{
  "type": "struct",
  "fields": {
    "id": {"type": "string"},
    "type": {"type": "string"},
    "source": {"type": "link"},
    "target": {"type": "link"},
    "properties": {"type": "map", "keyType": "string", "valueType": "any"},
    "provenance": {
      "type": "list",
      "valueType": {
        "type": "struct",
        "fields": {
          "document_cid": {"type": "link"},
          "chunk_index": {"type": "int"},
          "text": {"type": "string"},
          "confidence": {"type": "float"}
        }
      }
    }
  }
}
```

### Design Considerations

1. **Multiple Embedding Models**
   - Different models capture different semantic aspects
   - Specialized models for different query types (passage, QA, etc.)
   - Model fusion improves retrieval robustness

2. **Knowledge Graph Quality**
   - Entity disambiguation and coreference resolution
   - Relationship confidence scoring
   - Source attribution for provenance

3. **Scalability**
   - Chunked processing for large documents
   - Incremental graph updates
   - Distributed vector search across IPFS nodes

4. **Query Processing**
   - Dynamic weighting of vector vs. graph results
   - Query type detection for model selection
   - User feedback incorporation for result refinement

5. **Storage Efficiency**
   - Shared embedding storage for similar chunks
   - IPLD-based deduplicated storage

## IPFS Kit Migration Plan

### Overview
This section outlines the plan for migrating from the current `ipfs_kit` implementation to the new `ipfs_kit_py` package. The new package provides more robust functionality, improved architecture, role-based operation, and enhanced features like tiered caching, cluster management, and AI/ML integration.

### Current Usage Analysis
Based on analysis of the codebase, the `ipfs_kit` is currently used in:
1. `/home/barberb/ipfs_datasets_py/ipfs_datasets_py/ipfs_faiss_py/ipfs_knn_lib/knn.py`

Current usage patterns:
- Import: `from ipfs_kit import ipfs_kit`
- Initialization: `self.ipfs_kit = ipfs_kit(resources, meta)`
- Primary methods used:
  - `ipfs_upload_object()` - Used to upload JSON objects to IPFS

### Key Differences Between Old and New Implementations

#### Architecture
- **Old ipfs_kit**: Simpler implementation with basic IPFS operations
- **New ipfs_kit_py**: Comprehensive architecture with role-based operation (master/worker/leecher), tiered caching, and advanced features

#### API Changes
- **Old ipfs_kit**: Direct method calls with result dictionaries
- **New ipfs_kit_py**: Multiple API options:
  - Core API (similar to old ipfs_kit but more consistent)
  - High-Level API (`IPFSSimpleAPI` with simplified interface)
  - Command-line interface
  - HTTP API server

#### Method Names and Parameters
- **Old ipfs_kit**:
  - `ipfs_upload_object(object_data, **kwargs)`
- **New ipfs_kit_py**:
  - Core API: `ipfs_add(filepath_or_data)`
  - High-Level API: `add(filepath_or_data)`

#### Result Format
- **Old ipfs_kit**: Custom result dictionaries
- **New ipfs_kit_py**: Standardized result format with consistent fields

### Migration Steps

#### 1. Install the New Package
```bash
pip install ipfs_kit_py
```

#### 2. Update Import Statements
```python
# Old
from ipfs_kit import ipfs_kit

# New - Core API (closest to old API)
from ipfs_kit_py.ipfs_kit import ipfs_kit

# New - High-Level API (recommended)
from ipfs_kit_py.high_level_api import IPFSSimpleAPI
```

#### 3. Update Initialization
```python
# Old
old_ipfs = ipfs_kit(resources, meta)

# New - Core API (similar initialization)
new_ipfs = ipfs_kit(role="leecher", metadata=meta)

# New - High-Level API (recommended)
api = IPFSSimpleAPI(role="leecher")
```

#### 4. Method Migration Example for knn.py

```python
# Old
vector_store_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(vector_store), **kwargs)

# New - Core API approach
vector_store_cid = self.ipfs_kit.ipfs_add(json.dumps(vector_store))
if vector_store_cid.get("success"):
    cid = vector_store_cid.get("Hash")

# New - High-Level API approach (recommended)
cid = self.api.add(json.dumps(vector_store))
```

#### 5. Specific Changes for knn.py

```python
# Initialize the module
from ipfs_kit_py.high_level_api import IPFSSimpleAPI

class KNN:
    # ...existing code...
    
    def __init__(self, resources, meta):
        # ...existing code...
        
        # Old
        # self.ipfs_kit = ipfs_kit(resources, meta)
        
        # New
        self.api = IPFSSimpleAPI(metadata=meta)
        
        # ...existing code...
    
    # ...
    
    def save_database(self, dest, bucket, dir, documentdb, **kwargs):
        # ...existing code...
        
        # Old
        # vector_store_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(vector_store), **kwargs)
        # vector_index_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(vector_index), **kwargs)
        # doc_index_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(doc_index), **kwargs)
        # doc_store_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(doc_store), **kwargs)
        # metadata_cid = self.ipfs_kit.ipfs_upload_object(json.dumps(metadata_json), **kwargs)
        
        # New
        vector_store_cid = self.api.add(json.dumps(vector_store))
        vector_index_cid = self.api.add(json.dumps(vector_index))
        doc_index_cid = self.api.add(json.dumps(doc_index))
        doc_store_cid = self.api.add(json.dumps(doc_store))
        metadata_cid = self.api.add(json.dumps(metadata_json))
        
        # ...existing code...
```

### Benefits of Migration

1. **Enhanced Functionality**: Access to tiered caching, cluster management, metadata indexing
2. **Improved Performance**: Optimized operations with memory-mapped structures 
3. **Robustness**: Better error handling and recovery mechanisms
4. **Scalability**: Role-based architecture for distributed operations
5. **Future-proofing**: Ongoing development and maintenance of the new package

### Testing Recommendations

1. **Parallel Implementation**: Initially, maintain both old and new implementations in parallel:
   ```python
   try:
       # Try new implementation
       from ipfs_kit_py.high_level_api import IPFSSimpleAPI
       api = IPFSSimpleAPI(metadata=meta)
       cid = api.add(json.dumps(data))
   except Exception as e:
       # Fall back to old implementation
       from ipfs_kit import ipfs_kit
       old_ipfs = ipfs_kit(resources, meta)
       cid = old_ipfs.ipfs_upload_object(json.dumps(data))
   ```

2. **Validate Results**: For each operation, compare the results from old and new implementations
3. **Incremental Migration**: Migrate one component at a time, thoroughly testing each

### Timeline

1. **Preparation (1 day)**
   - Install new package
   - Update import statements
   - Create test harness for validation

2. **Implementation (1 day)**
   - Update initialization code
   - Migrate method calls
   - Add error handling

3. **Testing (1-2 days)**
   - Validate results against old implementation
   - Check for edge cases
   - Stress test with large files

4. **Cleanup (1 day)**
   - Remove old code and fallbacks
   - Update documentation
   - Commit final changes

## ipfs_kit_py Feature Integration Plan

This section outlines a comprehensive plan for integrating the features from the new `ipfs_kit_py` package into the `ipfs_datasets_py` codebase. The goal is to leverage the advanced capabilities of `ipfs_kit_py` to enhance the functionality, performance, and reliability of our decentralized data management system.

### 1. Feature Analysis and Integration Priorities

#### Core Features from ipfs_kit_py to Integrate

| Feature | Priority | Description | Integration Complexity |
|---------|----------|-------------|------------------------|
| **High-Level API** | High | Simplified interface with declarative configuration and error handling | Medium |
| **Role-based Architecture** | High | Master/worker/leecher node configuration for distributed operations | High |
| **Tiered Storage & Caching** | High | Intelligent content management across storage backends with ARC caching | High |
| **FSSpec Interface** | High | Standard filesystem interface for IPFS content | Medium |
| **Metadata Indexing** | High | Arrow-based index for fast content discovery | Medium |
| **Direct P2P Communication** | Medium | LibP2P connections for daemon-less content exchange | High |
| **Cluster Management** | Medium | Cluster coordination with leader election and task distribution | High |
| **AI/ML Integration** | Medium | Tools for model registry and dataset management | Medium |
| **Observability** | Medium | Metrics collection and visualization | Low |
| **Arrow-Based Cluster State** | Low | Efficient state sharing across processes | Medium |
| **IPLD Knowledge Graph** | Low | Modeling relationships between IPFS objects | High |

### 2. Integration Architecture

We will implement a layered architecture that incorporates `ipfs_kit_py` components while maintaining backward compatibility with existing code:

```
┌─────────────────────────────────────────────────────────────────┐
│                    ipfs_datasets_py Core API                    │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Feature-Specific Interfaces                    │
├─────────────┬─────────────┬──────────────┬────────────┬─────────┤
│  KnowledgeGraph  │  Dataset API  │  Vector Index  │  Provenance  │  Archive  │
└─────────────┴─────────────┴──────────────┴────────────┴─────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ipfs_kit_py Integration                     │
├─────────────┬─────────────┬──────────────┬────────────┬─────────┤
│  High-Level API  │  Role System  │  Tiered Cache  │  FSSpec IF  │  Cluster  │
└─────────────┴─────────────┴──────────────┴────────────┴─────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Storage Backends                           │
├─────────────┬─────────────┬──────────────┬────────────┬─────────┤
│     IPFS     │     S3      │   Storacha    │    HF Hub   │  Local  │
└─────────────┴─────────────┴──────────────┴────────────┴─────────┘
```

### 3. Detailed Integration Plan

#### Phase 1: Core API and High-Level Interface (2 weeks)

1. **Create Integration Layer**
   - Implement a facade pattern to bridge ipfs_datasets_py and ipfs_kit_py
   - Define consistent interface that abstracts underlying implementation
   - Set up configuration mapping between systems

2. **Migrate Core IPFS Operations**
   - Replace direct IPFS calls with High-Level API
   - Implement proper error handling and result mapping
   - Add caching integration for repeated operations

3. **Implement Role-Based System**
   - Create node role configuration (master/worker/leecher)
   - Define role-specific behavior and capabilities
   - Add dynamic role switching based on resource availability

4. **Add FSSpec Interface Integration**
   - Enhance current file handling with FSSpec integration
   - Implement filesystem-like IPFS access
   - Ensure compatibility with data science tools

#### Phase 2: Advanced Features and Performance (3 weeks)

1. **Integrate Tiered Caching System**
   - Implement memory, disk, and memory-mapped caching tiers
   - Add cache configuration and monitoring
   - Optimize for different data access patterns

2. **Implement Arrow-Based Metadata Indexing**
   - Create schema for dataset metadata
   - Implement fast index querying
   - Add distributed index synchronization

3. **Set up Cluster Integration**
   - Configure master/worker roles for cluster operations
   - Implement basic task distribution
   - Add cluster health monitoring

4. **Enable Performance Optimizations**
   - Implement chunked operations for large datasets
   - Add memory-mapped file access
   - Enable low-latency socket communication

#### Phase 3: AI/ML and Knowledge Graph Features (3 weeks)

1. **Implement AI/ML Integration**
   - Create model registry for ML models
   - Add dataset management for training data
   - Implement IPFS DataLoader for deep learning frameworks

2. **Add Knowledge Graph Support**
   - Implement IPLD-based knowledge graph
   - Create entity and relationship modeling
   - Add graph query capabilities

3. **Enhance Search Capabilities**
   - Implement GraphRAG for combined vector + graph search
   - Add hybrid retrieval mechanisms
   - Implement efficient ranking algorithms

4. **Set up Observability**
   - Configure metrics collection
   - Add performance monitoring
   - Create basic dashboards

#### Phase 4: Consolidation and Optimization (2 weeks)

1. **Performance Testing and Optimization**
   - Benchmark against current implementation
   - Identify and resolve bottlenecks
   - Optimize for specific use cases

2. **Documentation and Examples**
   - Update API documentation
   - Create integration examples
   - Add migration guides for existing code

3. **Cleanup and Stabilization**
   - Remove deprecated code and workarounds
   - Standardize error handling and logging
   - Ensure consistent API behavior

### 4. Code Examples for Key Integrations

#### High-Level API Integration

```python
from ipfs_datasets_py import ipfs_datasets
from ipfs_kit_py.high_level_api import IPFSSimpleAPI

class EnhancedIPFSDataset:
    def __init__(self, name, role="leecher", config=None):
        """Initialize with enhanced IPFS capabilities."""
        self.name = name
        # Initialize both dataset and advanced IPFS API
        self.dataset = ipfs_datasets.load_dataset(name)
        self.ipfs_api = IPFSSimpleAPI(role=role, config_path=config)
        
    def save_to_ipfs(self, subset=None):
        """Save dataset to IPFS with advanced features."""
        # Convert dataset to serializable format
        data = self.dataset.to_dict() if subset is None else self.dataset[subset].to_dict()
        
        # Save with metadata and pinning
        cid = self.ipfs_api.add(data, pin=True)
        
        # Register in metadata index
        self.ipfs_api.register_dataset(cid, {
            "name": self.name,
            "type": "dataset",
            "rows": len(self.dataset),
            "created_at": self.ipfs_api.get_timestamp()
        })
        
        return cid
        
    def load_from_ipfs(self, cid):
        """Load dataset from IPFS with caching and verification."""
        # Using tiered cache system automatically
        data = self.ipfs_api.get(cid)
        
        # Convert back to dataset format
        return ipfs_datasets.Dataset.from_dict(data)
```

#### Role-Based Processing Example

```python
def setup_processing_node(role, resources=None):
    """Configure a node for distributed dataset processing."""
    from ipfs_datasets_py import ipfs_datasets
    from ipfs_kit_py.high_level_api import IPFSSimpleAPI
    
    # Configure based on role
    if role == "master":
        # Master node manages task distribution and result aggregation
        api = IPFSSimpleAPI(
            role="master",
            resources=resources or {"max_memory": "4GB", "max_storage": "100GB"}
        )
        
        # Set up cluster coordination 
        api.setup_cluster(replication_factor=3)
        
        # Create metadata index
        api.initialize_metadata_index(sync_interval=60)  # seconds
        
        return api
        
    elif role == "worker":
        # Worker node handles computational tasks
        api = IPFSSimpleAPI(
            role="worker", 
            resources=resources or {"max_memory": "8GB", "max_cpu": 8}
        )
        
        # Connect to cluster
        master_addresses = discover_masters()
        api.join_cluster(master_addresses)
        
        # Configure processing capabilities
        api.register_capabilities(["embedding_generation", "data_transformation"])
        
        return api
        
    else:  # leecher
        # Leecher node primarily consumes data
        api = IPFSSimpleAPI(
            role="leecher",
            resources=resources or {"max_memory": "2GB"}
        )
        
        # Configure minimal local cache
        api.setup_cache(memory_size="500MB", disk_size="2GB")
        
        return api
```

#### Tiered Cache Integration

```python
from ipfs_datasets_py import ipfs_datasets
from ipfs_kit_py.high_level_api import IPFSSimpleAPI
from ipfs_kit_py.tiered_cache import TieredCache

class CachedDatasetOperations:
    """Dataset operations with enhanced caching."""
    
    def __init__(self):
        self.api = IPFSSimpleAPI()
        
        # Configure tiered cache with optimal settings
        self.cache = TieredCache(
            memory_size="1GB",
            disk_size="10GB",
            mmap_size="4GB",
            path="~/.ipfs_datasets/cache",
            eviction_policy="ARC"  # Adaptive Replacement Cache
        )
        
    def process_dataset_batch(self, dataset_cid, batch_size=1000):
        """Process dataset in batches with caching."""
        dataset = self.load_dataset_with_cache(dataset_cid)
        
        results = []
        for i in range(0, len(dataset), batch_size):
            batch = dataset[i:i+batch_size]
            
            # Process batch
            processed_batch = self.process_batch(batch)
            results.extend(processed_batch)
            
        return results
        
    def load_dataset_with_cache(self, cid):
        """Load dataset with tiered caching."""
        # Check memory cache
        if self.cache.has(cid, tier="memory"):
            return self.cache.get(cid, tier="memory")
            
        # Check disk cache
        if self.cache.has(cid, tier="disk"):
            dataset = self.cache.get(cid, tier="disk")
            # Promote to memory cache
            self.cache.put(cid, dataset, tier="memory")
            return dataset
            
        # Fetch from IPFS
        data = self.api.get(cid)
        dataset = ipfs_datasets.Dataset.from_dict(data)
        
        # Store in cache
        self.cache.put(cid, dataset, tier="memory")
        self.cache.put(cid, dataset, tier="disk")
        
        return dataset
```

#### Knowledge Graph Integration

```python
from ipfs_datasets_py import ipfs_datasets, knowledge_graph_extraction
from ipfs_kit_py.high_level_api import IPFSSimpleAPI
from ipfs_kit_py.ipld_knowledge_graph import IPLDKnowledgeGraph

class EnhancedKnowledgeGraph:
    """Enhanced knowledge graph with IPLD storage."""
    
    def __init__(self):
        self.api = IPFSSimpleAPI()
        self.kg = IPLDKnowledgeGraph()
        
    def extract_and_store(self, dataset_name, text_column):
        """Extract knowledge graph from dataset and store in IPLD."""
        # Load dataset
        dataset = ipfs_datasets.load_dataset(dataset_name)
        
        # Extract entities and relationships
        entities = []
        relationships = []
        
        for item in dataset:
            text = item[text_column]
            item_entities, item_relationships = knowledge_graph_extraction.extract(
                text, 
                extraction_temperature=0.7,
                structure_temperature=0.5
            )
            
            entities.extend(item_entities)
            relationships.extend(item_relationships)
        
        # Add to knowledge graph
        for entity in entities:
            self.kg.add_entity(entity)
            
        for rel in relationships:
            self.kg.add_relationship(
                rel["source"], 
                rel["target"], 
                rel["type"], 
                rel["properties"]
            )
        
        # Export to IPLD/IPFS
        root_cid = self.kg.export_to_car("/tmp/knowledge_graph.car")
        
        # Register in metadata index
        self.api.register_knowledge_graph(root_cid, {
            "dataset": dataset_name,
            "entity_count": len(entities),
            "relationship_count": len(relationships)
        })
        
        return root_cid
```

### 5. Data Migration Strategy

1. **Content Identification and Inventory**
   - Create inventory of existing IPFS content
   - Map dataset structures and relationships
   - Identify critical vs. non-critical data

2. **Migration Workflow**
   - Develop background migration process
   - Implement verification and validation
   - Create rollback capabilities

3. **Testing Strategy**
   - Set up staging environment
   - Perform parallel validations
   - Implement progressive migration

4. **Monitoring and Metrics**
   - Track migration progress
   - Monitor system performance
   - Validate data integrity

### 6. Risk Assessment and Mitigation

| Risk | Impact | Likelihood | Mitigation Strategy |
|------|--------|------------|---------------------|
| API Incompatibility | High | Medium | Create adapter patterns, thorough testing, fallback mechanisms |
| Performance Degradation | High | Low | Performance benchmarking, incremental migration, optimization |
| Data Loss | Very High | Very Low | Comprehensive backups, dual-write during transition, integrity checks |
| Increased Complexity | Medium | Medium | Clear documentation, simplified facade API, training |
| Dependency Management | Medium | Medium | Strict versioning, compatibility testing, dependency injection |

### 7. Timeline and Milestones

| Milestone | Timeline | Deliverables |
|-----------|----------|--------------|
| Initial Setup | Week 1-2 | Integration layer, configuration mapping, basic High-Level API integration |
| Core Integration | Week 3-4 | Role system, FSSpec interface, error handling standardization |
| Advanced Features | Week 5-7 | Tiered caching, metadata indexing, cluster integration |
| AI/ML Integration | Week 8-10 | Model registry, dataset tools, knowledge graph |
| Optimization | Week 11-12 | Performance tuning, documentation, cleanup |

### 8. Conclusion

The integration of `ipfs_kit_py` features into `ipfs_datasets_py` will significantly enhance our decentralized data management capabilities. By leveraging the advanced architecture, performance optimizations, and additional features of `ipfs_kit_py`, we can create a more robust, efficient, and feature-rich system for working with datasets across decentralized networks.

Key benefits of this integration include:
- Improved performance through tiered caching and optimized operations
- Enhanced distributed capabilities via role-based architecture
- Better developer experience with the High-Level API
- Advanced data organization with metadata indexing and knowledge graphs
- Streamlined AI/ML workflows with specialized integration components

This comprehensive integration plan provides a roadmap for incorporating these advanced features while maintaining compatibility with existing code and ensuring a smooth transition for users of the library.