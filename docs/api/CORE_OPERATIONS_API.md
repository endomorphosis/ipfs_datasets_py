# Core Operations API Reference

Complete API documentation for `ipfs_datasets_py.core_operations` module.

## Overview

The `core_operations` module provides reusable business logic for:
- **DatasetLoader**: Load datasets from multiple sources
- **IPFSPinner**: Pin content to IPFS
- **KnowledgeGraphManager**: Knowledge graph operations

All MCP tools and CLI commands use these core modules.

## DatasetLoader

```python
from ipfs_datasets_py.core_operations import DatasetLoader

loader = DatasetLoader()
result = await loader.load("squad")
```

### Methods

**`load(source, format=None, options=None)`**
- **source**: Dataset name, file path, or URL
- **format**: "json", "csv", "parquet", "arrow" (auto-detected if None)
- **options**: Dict with split, streaming, etc.
- **Returns**: Dict with status, data, format, error

## IPFSPinner

```python
from ipfs_datasets_py.core_operations import IPFSPinner

pinner = IPFSPinner()
result = await pinner.pin({"key": "value"})
```

### Methods

**`pin(content_source, backend_options=None)`**
- **content_source**: Dict, string, bytes, or file path
- **backend_options**: Dict with daemon_addr, timeout, etc.
- **Returns**: Dict with status, cid, backend, size, error

## KnowledgeGraphManager

```python
from ipfs_datasets_py.core_operations import KnowledgeGraphManager

kg = KnowledgeGraphManager()
await kg.create()
await kg.add_entity("person1", "Person", {"name": "Alice"})
```

### Methods

**`create()`**: Initialize graph database

**`add_entity(entity_id, entity_type, properties=None)`**: Add entity

**`add_relationship(source_id, target_id, relationship_type, properties=None)`**: Add relationship

**`query_cypher(cypher, parameters=None)`**: Execute Cypher query

**`search_hybrid(query, search_type="hybrid", limit=10)`**: Hybrid search

**`transaction_begin()`**: Begin transaction

**`transaction_commit(tx_id)`**: Commit transaction

**`transaction_rollback(tx_id)`**: Rollback transaction

**`create_index(label, property)`**: Create index

**`add_constraint(label, property, constraint_type="unique")`**: Add constraint

## See Also

- [User Guide](../user_guides/GETTING_STARTED.md)
- [CLI Reference](../user_guides/CLI_USAGE.md)
- [Developer Guide](../developer_guides/CREATING_TOOLS.md)
