# IPFS Datasets Python - Development Guide

## Project Overview
This repository serves as a facade to multiple data processing and storage libraries:
- DuckDB, Arrow, and Huggingface Datasets for data manipulation
- IPLD for data structuring
- IPFS (via ipfs_kit) for decentralized storage
- libp2p_kit for peer-to-peer data transfer

The primary goal is to provide a unified interface for data processing and distribution across decentralized networks.

## Build & Installation
```bash
pip install -e .                # Install in development mode
pip install -r requirements.txt  # Install dependencies
```

## Testing
```bash
python3 test/test.py            # Run all tests
python3 -c "from test.test import test; test()"  # Run single test function
python3 -c "from test.test import ws_test; ws_test()"  # Test OrbitDB integration
python3 -c "from test.test import download_test; download_test()"  # Test downloads
```

## Usage Example
```python
from ipfs_datasets_py import ipfs_datasets
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex

# Load a dataset
dataset = ipfs_datasets.load_dataset("wikipedia")

# Create vector index
index = IPFSKnnIndex(dimension=768)
index.add_vectors(vectors, metadata={"source": "wikipedia"})

# Search for similar vectors
results = index.search(query_vector, top_k=5)
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
- **Vector Indexing**: Fast similarity search for embeddings
- **Knowledge Graph**: Entity and relationship modeling using IPLD
- **P2P Transport**: libp2p-based dataset sharing and distribution

### Integration Patterns
- Use the `ipfs_datasets_py` module to load and process data from various sources
- Data can be seamlessly transferred to IPFS storage using the integrated ipfs_kit
- Peer-to-peer sharing is enabled through libp2p_kit integration
- Data structures are preserved using IPLD formatting
- Vector indexes support both local memory-mapped storage and IPFS-backed persistent storage
- Knowledge graphs can be queried using both semantic similarity and relationship traversal

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
        # Initialize vector store with dimension and similarity metric
        
    def add_vectors(self, vectors, metadata=None):
        # Store vectors in IPLD format
        
    def search(self, query_vector, top_k=10):
        # Perform vector similarity search
        
    def export_to_ipld(self):
        # Export vector index as IPLD structure
```

#### IPLDKnowledgeGraph
```python
class IPLDKnowledgeGraph:
    """Knowledge graph using IPLD for storage."""
    
    def __init__(self):
        # Initialize graph store
        
    def add_entity(self, entity_data):
        # Add entity node to graph
        
    def add_relationship(self, source_cid, target_cid, relationship_type):
        # Add relationship between entities
        
    def query(self, start_entity, relationship_path):
        # Query graph following relationship paths
        
    def vector_augmented_query(self, query_vector, relationship_constraints):
        # GraphRAG query combining vector similarity and graph traversal
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

## Configuration
- Main configuration file: `config/config.toml`
- Key configuration options:
  - IPFS node connection parameters
  - Vector index dimensions and metrics
  - Dataset cache locations
  - Peer discovery settings for P2P sharing

## Performance Considerations
- For large datasets, use streaming data loading to minimize memory usage
- Vector indexes can be memory-mapped for datasets larger than RAM
- Use batch processing when adding vectors to the index
- Consider data sharding for distributed vector search across peers

## Version Control
- Commit messages should be clear and descriptive
- Reference issues/PRs in commit messages when applicable
- Follow semantic versioning for releases
- Branch naming convention: feature/[feature-name], bugfix/[bug-name]