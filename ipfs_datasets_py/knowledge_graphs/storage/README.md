# Knowledge Graph Storage

Storage backends for persisting knowledge graphs to IPFS using IPLD (InterPlanetary Linked Data).

## Overview

The storage module provides IPFS-native persistence for knowledge graphs, enabling:
- **Decentralized storage** - Store graphs on IPFS for content-addressed access
- **IPLD integration** - Native IPLD data structures for efficient graph representation
- **Multiple codecs** - Support for dag-cbor, dag-json, and other IPLD codecs
- **Version control** - Content-addressing provides automatic versioning
- **Efficient retrieval** - Direct CID-based access to graph components

## Key Features

- **IPLD Backend** - Native IPFS storage using IPLD blocks
- **Multiple Codecs** - dag-cbor (binary), dag-json (human-readable), dag-jose (encrypted)
- **Chunk Management** - Automatic chunking for large graphs
- **CID Tracking** - Track content identifiers for all graph components
- **Error Recovery** - Robust error handling with specific exception types
- **Lazy Loading** - Load graph components on-demand

## Core Classes

### `IPLDBackend`
Main storage backend for IPFS/IPLD persistence.

```python
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

# Initialize backend
backend = IPLDBackend(
    ipfs_client=ipfs_client,
    codec="dag-cbor"  # or "dag-json"
)

# Store knowledge graph
cid = await backend.store(graph)
print(f"Graph stored at: {cid}")

# Retrieve knowledge graph
retrieved_graph = await backend.retrieve(cid)
```

### `StorageTypes`
Type definitions for storage operations.

```python
from ipfs_datasets_py.knowledge_graphs.storage.types import (
    StorageFormat,
    ChunkStrategy,
    CIDTracker
)

# Define storage format
format_spec = StorageFormat(
    codec="dag-cbor",
    compression=True,
    chunking=ChunkStrategy.AUTO
)
```

## Usage Examples

### Example 1: Basic Graph Storage

```python
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
import asyncio

async def store_and_retrieve():
    # Create knowledge graph
    graph = KnowledgeGraph()
    graph.add_entity(Entity(
        entity_id="e1",
        entity_type="Person",
        name="Alice",
        properties={"age": 30}
    ))
    
    # Initialize storage
    backend = IPLDBackend(ipfs_client=ipfs_client)
    
    # Store graph
    cid = await backend.store(graph)
    print(f"Stored at CID: {cid}")
    
    # Retrieve graph
    retrieved = await backend.retrieve(cid)
    print(f"Retrieved {len(retrieved.entities)} entities")

asyncio.run(store_and_retrieve())
```

### Example 2: Codec Selection

```python
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

async def codec_comparison():
    backend_cbor = IPLDBackend(codec="dag-cbor")  # Binary, efficient
    backend_json = IPLDBackend(codec="dag-json")  # Human-readable
    
    # Store with different codecs
    cbor_cid = await backend_cbor.store(graph)
    json_cid = await backend_json.store(graph)
    
    print(f"CBOR CID: {cbor_cid}")
    print(f"JSON CID: {json_cid}")
    
    # Both can be retrieved
    graph_from_cbor = await backend_cbor.retrieve(cbor_cid)
    graph_from_json = await backend_json.retrieve(json_cid)

asyncio.run(codec_comparison())
```

### Example 3: Error Handling

```python
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    IPLDStorageError,
    SerializationError,
    DeserializationError
)

async def robust_storage():
    backend = IPLDBackend(ipfs_client=ipfs_client)
    
    try:
        cid = await backend.store(graph)
        print(f"Stored successfully: {cid}")
    except SerializationError as e:
        print(f"Failed to serialize graph: {e}")
        print(f"Details: {e.details}")
    except IPLDStorageError as e:
        print(f"IPFS connection failed: {e}")
        print(f"Backend: {e.details.get('backend')}")

asyncio.run(robust_storage())
```

### Example 4: Chunked Storage for Large Graphs

```python
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

async def store_large_graph():
    # Large graph with 100K+ entities
    large_graph = create_large_graph()
    
    # Backend automatically chunks large graphs
    backend = IPLDBackend(
        ipfs_client=ipfs_client,
        chunk_size=256 * 1024  # 256 KB chunks
    )
    
    # Store returns root CID
    root_cid = await backend.store(large_graph)
    print(f"Large graph stored, root CID: {root_cid}")
    
    # Retrieval loads chunks on-demand
    retrieved = await backend.retrieve(root_cid)
    print(f"Retrieved {len(retrieved.entities)} entities")

asyncio.run(store_large_graph())
```

## Storage Formats

### dag-cbor (Recommended)
Binary format, efficient storage and fast serialization:

```python
backend = IPLDBackend(codec="dag-cbor")
cid = await backend.store(graph)
# CID: bafyreib... (binary CBOR data)
```

**Pros:**
- Compact binary representation
- Fast serialization/deserialization
- Native IPLD support

**Cons:**
- Not human-readable
- Requires CBOR decoder

### dag-json
JSON format, human-readable:

```python
backend = IPLDBackend(codec="dag-json")
cid = await backend.store(graph)
# CID: baguqeer... (JSON data)
```

**Pros:**
- Human-readable
- Easy debugging
- Wide tool support

**Cons:**
- Larger file size
- Slower serialization

### dag-jose (Encrypted)
Encrypted JSON format:

```python
backend = IPLDBackend(codec="dag-jose", encryption_key=key)
cid = await backend.store(graph)
```

## IPFS Integration

### Direct CID Access

```python
# Store graph
cid = await backend.store(graph)

# Access via IPFS gateway
url = f"https://ipfs.io/ipfs/{cid}"

# Or via local daemon
ipfs_data = ipfs_client.cat(cid)
```

### Content Addressing

```python
# Same graph = same CID (deterministic)
cid1 = await backend.store(graph)
cid2 = await backend.store(graph)
assert cid1 == cid2

# Different graph = different CID
modified_graph = graph.copy()
modified_graph.add_entity(new_entity)
cid3 = await backend.store(modified_graph)
assert cid3 != cid1
```

### Version Control

```python
# Store version 1
v1_cid = await backend.store(graph_v1)

# Modify and store version 2
graph_v2 = graph_v1.copy()
graph_v2.add_relationship(new_rel)
v2_cid = await backend.store(graph_v2)

# Both versions accessible
graph_v1 = await backend.retrieve(v1_cid)
graph_v2 = await backend.retrieve(v2_cid)
```

## Performance Optimization

### Chunking Strategy

For large graphs, use chunking:

```python
backend = IPLDBackend(
    chunk_size=256 * 1024,  # 256 KB chunks
    chunk_links=True  # Use IPLD links between chunks
)
```

### Caching

Enable caching for frequently accessed graphs:

```python
backend = IPLDBackend(
    enable_cache=True,
    cache_size=100  # Cache up to 100 graphs
)

# First retrieval: loads from IPFS
graph1 = await backend.retrieve(cid)

# Second retrieval: loads from cache
graph2 = await backend.retrieve(cid)
```

### Parallel Operations

Store/retrieve multiple graphs in parallel:

```python
# Store multiple graphs
cids = await asyncio.gather(*[
    backend.store(graph) for graph in graphs
])

# Retrieve multiple graphs
graphs = await asyncio.gather(*[
    backend.retrieve(cid) for cid in cids
])
```

## Error Handling

The storage module uses specific exceptions:

```python
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    StorageError,          # Base storage exception
    IPLDStorageError,      # IPFS/IPLD specific errors
    SerializationError,    # Failed to serialize graph
    DeserializationError   # Failed to deserialize graph
)

try:
    cid = await backend.store(graph)
except SerializationError as e:
    print(f"Serialization failed: {e}")
    print(f"Data type: {e.details.get('data_type')}")
    print(f"Codec: {e.details.get('codec')}")
except IPLDStorageError as e:
    print(f"IPFS storage failed: {e}")
    print(f"Backend: {e.details.get('backend')}")
except StorageError as e:
    print(f"Storage operation failed: {e}")
```

## See Also

- [Core Module](../core/README.md) - Core knowledge graph data structures
- [IPLD Types](types.py) - Storage type definitions
- [Query Module](../query/README.md) - Query stored graphs
- [Transactions Module](../transactions/README.md) - Transactional storage

## Future Enhancements

- **Delta Storage** - Store only changes between versions
- **Compression** - Compress graphs before storage
- **Encryption** - Built-in encryption for sensitive graphs
- **Replication** - Automatic replication across IPFS nodes
- **Garbage Collection** - Automatic cleanup of unused graphs
- **Migration Tools** - Migrate between storage formats
