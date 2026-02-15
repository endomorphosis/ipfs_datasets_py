# IPLD - InterPlanetary Linked Data Integration

This module provides comprehensive IPLD (InterPlanetary Linked Data) support for content-addressed data structures and distributed storage in the IPFS Datasets Python library.

## Overview

The IPLD module implements content-addressable data structures, enabling immutable, verifiable data storage and retrieval across distributed networks. It provides optimized encoding/decoding, graph traversal, and integration with IPFS for decentralized data management.

## Components

### IPLD Storage (`storage.py`)
Core IPLD storage engine with content addressing and verification.

**Key Features:**
- Content-addressed data storage with cryptographic verification
- Immutable data structures with version control
- Multi-format support (JSON, CBOR, Protobuf)
- Efficient serialization and deserialization
- Automatic deduplication and compression

### DAG-PB Support (`dag_pb.py`)
Protocol Buffers-based Directed Acyclic Graph implementation.

**Features:**
- DAG-PB format encoding and decoding
- UnixFS compatibility and integration
- File and directory structure representation
- Efficient graph traversal algorithms

### Vector Store IPLD (`vector_store.py`)
IPLD-based vector storage with content addressing for embeddings.

**Vector Storage Features:**
- Content-addressed vector storage
- Immutable embedding collections
- Cryptographic verification of vector data
- Efficient similarity search with IPLD optimization

### Knowledge Graph IPLD (`knowledge_graph.py`)
IPLD-based knowledge graph storage and traversal.

**Graph Features:**
- Content-addressed graph nodes and edges
- Immutable knowledge graph structures
- Efficient graph traversal and querying
- Cross-dataset graph linking
- **Automatic chunking for large graphs** (>800KB blocks are split automatically)
- Handles graphs exceeding IPFS's 1MiB block limit

## Usage Examples

### Basic IPLD Storage
```python
from ipfs_datasets_py.data_transformation.ipld import IPLDStorage

storage = IPLDStorage(ipfs_client=ipfs_client)
data = {"title": "Document", "content": "Text content"}
cid = await storage.store_data(data)
retrieved_data = await storage.retrieve_data(cid)
```

### Vector Storage with IPLD
```python
from ipfs_datasets_py.data_transformation.ipld import IPLDVectorStore

vector_store = IPLDVectorStore(ipfs_client=ipfs_client)
vector_cid = await vector_store.add_vectors(
    vectors=embedding_vectors,
    metadata=document_metadata
)
```

## See Also

- [Vector Stores](../vector_stores/README.md) - Vector database implementations
- [IPFS Features Guide](../../docs/distributed_features.md) - Distributed storage
- [Data Provenance](../../docs/data_provenance.md) - Data lineage and verification