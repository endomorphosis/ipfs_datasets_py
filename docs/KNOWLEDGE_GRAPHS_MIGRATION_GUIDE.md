# Knowledge Graphs Migration Guide

**Version:** 1.0  
**Date:** 2026-02-15  
**Status:** Active

---

## Overview

This guide helps you migrate from the legacy `ipld.py` knowledge graph API to the new Neo4j-compatible graph database API. The new API provides better compatibility, more features, and improved performance.

---

## Why Migrate?

### Benefits of the New API

1. **Neo4j Compatibility**: Drop-in replacement for Neo4j driver - change one line of code
2. **Cypher Query Support**: Coming in Phase 2 (Weeks 3-4)
3. **ACID Transactions**: Full transaction support with WAL (Phase 3)
4. **Better Performance**: LRU caching, optimized storage
5. **Active Development**: New features, bug fixes, and improvements
6. **Standard API**: Follow industry-standard graph database patterns

### Deprecation Timeline

- **Current (Phase 1)**: Legacy API deprecated with warnings
- **Phase 2 (Weeks 3-4)**: Legacy API marked for removal
- **Phase 3 (Weeks 5-6)**: Legacy API removed from main codebase
- **Archive**: Legacy code moved to `legacy/` directory

---

## Quick Migration

### Before (Legacy API)

```python
from ipfs_datasets_py.knowledge_graphs.ipld import (
    IPLDKnowledgeGraph, 
    Entity, 
    Relationship
)
from ipfs_datasets_py.data_transformation.ipld.storage import IPLDStorage

# Create storage
storage = IPLDStorage(ipfs_host="localhost", ipfs_port=5001)

# Create knowledge graph
kg = IPLDKnowledgeGraph(storage)

# Add entities
entity1 = Entity(
    entity_type="Person",
    name="Alice",
    properties={"age": 30}
)
entity2 = Entity(
    entity_type="Person",
    name="Bob",
    properties={"age": 25}
)
kg.add_entity(entity1)
kg.add_entity(entity2)

# Add relationship
rel = Relationship(
    relationship_type="KNOWS",
    source_id=entity1.id,
    target_id=entity2.id,
    properties={"since": 2020}
)
kg.add_relationship(rel)

# Save graph
cid = kg.save()
```

### After (New API)

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

# Create driver (Neo4j-compatible)
driver = GraphDatabase.driver("ipfs://localhost:5001")

# Get session
with driver.session() as session:
    # Create storage backend (optional for persistence)
    backend = IPLDBackend(cache_capacity=1000)
    engine = GraphEngine(storage_backend=backend)
    
    # Add nodes (equivalent to entities)
    alice = engine.create_node(
        labels=["Person"],
        properties={"name": "Alice", "age": 30}
    )
    bob = engine.create_node(
        labels=["Person"],
        properties={"name": "Bob", "age": 25}
    )
    
    # Add relationship
    rel = engine.create_relationship(
        rel_type="KNOWS",
        start_node=alice.id,
        end_node=bob.id,
        properties={"since": 2020}
    )
    
    # Save graph
    cid = engine.save_graph()

driver.close()
```

---

## Detailed Migration Steps

### Step 1: Update Imports

#### Old Imports
```python
from ipfs_datasets_py.knowledge_graphs.ipld import (
    IPLDKnowledgeGraph,
    Entity,
    Relationship
)
```

#### New Imports
```python
# Driver API (Neo4j-compatible)
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import (
    GraphDatabase,
    Node,
    Relationship,
    Path
)

# Core graph engine
from ipfs_datasets_py.knowledge_graphs.core import (
    GraphEngine,
    QueryExecutor
)

# Storage layer
from ipfs_datasets_py.knowledge_graphs.storage import (
    IPLDBackend,
    Entity,  # Compatible with legacy Entity
    Relationship as StorageRelationship,
    LRUCache
)
```

### Step 2: Initialize Driver

#### Old Way
```python
from ipfs_datasets_py.data_transformation.ipld.storage import IPLDStorage
storage = IPLDStorage(ipfs_host="localhost", ipfs_port=5001)
kg = IPLDKnowledgeGraph(storage)
```

#### New Way
```python
# Option 1: Use Neo4j-compatible driver (recommended)
driver = GraphDatabase.driver("ipfs://localhost:5001")
session = driver.session()

# Option 2: Use GraphEngine directly
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend
backend = IPLDBackend(cache_capacity=1000)
engine = GraphEngine(storage_backend=backend)
```

### Step 3: Create Nodes (Entities)

#### Old Way
```python
entity = Entity(
    entity_id="person-1",
    entity_type="Person",
    name="Alice",
    properties={"age": 30, "city": "SF"},
    confidence=0.95,
    source_text="Alice is 30 years old"
)
kg.add_entity(entity)
```

#### New Way
```python
# Using GraphEngine
node = engine.create_node(
    labels=["Person"],
    properties={
        "name": "Alice",
        "age": 30,
        "city": "SF"
    }
)

# Using storage Entity (for compatibility)
from ipfs_datasets_py.knowledge_graphs.storage import Entity
entity = Entity(
    entity_type="Person",
    name="Alice",
    properties={"age": 30, "city": "SF"},
    confidence=0.95,
    source_text="Alice is 30 years old"
)
# Convert to node if needed
```

### Step 4: Create Relationships

#### Old Way
```python
rel = Relationship(
    relationship_id="rel-1",
    relationship_type="KNOWS",
    source_id=entity1.id,
    target_id=entity2.id,
    properties={"since": 2020},
    confidence=0.9
)
kg.add_relationship(rel)
```

#### New Way
```python
# Using GraphEngine
rel = engine.create_relationship(
    rel_type="KNOWS",
    start_node=node1.id,
    end_node=node2.id,
    properties={"since": 2020}
)
```

### Step 5: Query Nodes

#### Old Way
```python
# Get entity by ID
entity = kg.get_entity(entity_id)

# Get all entities of a type
persons = kg.get_entities_by_type("Person")

# Search entities
results = kg.search_entities(query="Alice")
```

#### New Way
```python
# Get node by ID
node = engine.get_node(node_id)

# Find nodes by label
persons = engine.find_nodes(labels=["Person"])

# Find nodes by properties
results = engine.find_nodes(
    labels=["Person"],
    properties={"name": "Alice"}
)

# With limit
limited = engine.find_nodes(labels=["Person"], limit=10)
```

### Step 6: Save and Load Graphs

#### Old Way
```python
# Save graph
cid = kg.save()

# Load graph
kg2 = IPLDKnowledgeGraph(storage)
kg2.load(cid)
```

#### New Way
```python
# Save graph
cid = engine.save_graph()

# Load graph
engine2 = GraphEngine(storage_backend=backend)
engine2.load_graph(cid)
```

### Step 7: Cleanup Resources

#### Old Way
```python
# No explicit cleanup needed
```

#### New Way
```python
# Close driver when done
driver.close()

# Or use context manager (recommended)
with GraphDatabase.driver("ipfs://localhost:5001") as driver:
    with driver.session() as session:
        # Do work here
        pass
# Automatically closes
```

---

## API Mapping Reference

### Classes

| Legacy API | New API | Notes |
|------------|---------|-------|
| `IPLDKnowledgeGraph` | `GraphEngine` | Core graph operations |
| `Entity` | `Node` or `storage.Entity` | Node in graph |
| `Relationship` | `Relationship` | Edge in graph |
| `IPLDStorage` | `IPLDBackend` | Storage layer |
| N/A | `GraphDatabase` | Driver factory |
| N/A | `IPFSSession` | Session management |
| N/A | `Result` | Query results |
| N/A | `Record` | Single result row |

### Methods

| Legacy Method | New Method | Notes |
|---------------|------------|-------|
| `kg.add_entity(entity)` | `engine.create_node(labels, properties)` | Create node |
| `kg.get_entity(id)` | `engine.get_node(id)` | Get node by ID |
| `kg.get_entities_by_type(type)` | `engine.find_nodes(labels=[type])` | Find by label |
| `kg.add_relationship(rel)` | `engine.create_relationship(...)` | Create relationship |
| `kg.get_relationship(id)` | `engine.get_relationship(id)` | Get relationship |
| `kg.save()` | `engine.save_graph()` | Save entire graph |
| `kg.load(cid)` | `engine.load_graph(cid)` | Load graph |
| `kg.export_to_car(path)` | `backend.export_car(cid)` | Export to CAR file |

---

## Common Patterns

### Pattern 1: Batch Node Creation

```python
# Old way
entities = []
for data in batch_data:
    entity = Entity(entity_type="Person", name=data["name"])
    kg.add_entity(entity)
    entities.append(entity)

# New way
nodes = []
for data in batch_data:
    node = engine.create_node(
        labels=["Person"],
        properties={"name": data["name"]}
    )
    nodes.append(node)
```

### Pattern 2: Graph Traversal

```python
# Old way
related = kg.get_related_entities(entity_id, relationship_type="KNOWS")

# New way (Phase 1 - manual)
node = engine.get_node(node_id)
# Traverse relationships manually for now
# Phase 2 will add Cypher: MATCH (n)-[:KNOWS]->(m) RETURN m
```

### Pattern 3: Updating Nodes

```python
# Old way
entity = kg.get_entity(entity_id)
entity.properties["age"] = 31
kg.update_entity(entity)

# New way
engine.update_node(node_id, {"age": 31})
```

### Pattern 4: Deleting Nodes

```python
# Old way
kg.remove_entity(entity_id)

# New way
engine.delete_node(node_id)
```

---

## Feature Comparison

| Feature | Legacy API | New API (Phase 1) | New API (Phase 2+) |
|---------|------------|-------------------|-------------------|
| Entity/Node creation | ✅ | ✅ | ✅ |
| Relationship creation | ✅ | ✅ | ✅ |
| IPLD storage | ✅ | ✅ | ✅ |
| LRU caching | ❌ | ✅ | ✅ |
| Neo4j compatibility | ❌ | ✅ | ✅ |
| Cypher queries | ❌ | ❌ | ✅ (Phase 2) |
| ACID transactions | ❌ | Partial | ✅ (Phase 3) |
| Graph traversal | ✅ | Manual | ✅ (Phase 2) |
| Vector integration | ✅ | Planned | ✅ (Phase 4) |
| JSON-LD support | ❌ | Planned | ✅ (Phase 4) |
| CAR import/export | ✅ | ✅ | ✅ |

---

## Breaking Changes

### 1. Entity vs Node

**Change**: `Entity` objects are now `Node` objects with different structure.

**Impact**: Code that directly accesses `entity.id`, `entity.type`, etc. needs updates.

**Migration**:
```python
# Old
entity.id  # string ID
entity.type  # string type
entity.properties  # dict

# New
node.id  # string ID
node.labels  # list of strings (not single type)
node._properties  # dict (use node.get(key) instead)
```

### 2. Relationship Source/Target

**Change**: Relationships use `start_node` and `end_node` instead of `source_id` and `target_id`.

**Migration**:
```python
# Old
rel.source_id
rel.target_id

# New
rel.start_node
rel.end_node
```

### 3. Storage Initialization

**Change**: Storage initialization is different.

**Migration**:
```python
# Old
from ipfs_datasets_py.data_transformation.ipld.storage import IPLDStorage
storage = IPLDStorage(ipfs_host="localhost", ipfs_port=5001)

# New
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend
backend = IPLDBackend(cache_capacity=1000)
```

---

## Troubleshooting

### Issue: "Module 'ipld' is deprecated" Warning

**Solution**: This is expected. Migrate to the new API to remove the warning.

### Issue: "AttributeError: 'Node' object has no attribute 'type'"

**Solution**: Use `node.labels` instead of `node.type`. Labels is a list.

```python
# Old
if entity.type == "Person":
    ...

# New
if "Person" in node.labels:
    ...
```

### Issue: "Cannot import GraphDatabase"

**Solution**: Ensure you're using the correct import path:

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase
```

### Issue: "Graph not persisting to IPFS"

**Solution**: Ensure you provide a storage backend to GraphEngine:

```python
backend = IPLDBackend(cache_capacity=1000)
engine = GraphEngine(storage_backend=backend)
```

---

## Getting Help

### Documentation

- **Refactoring Plan**: `docs/KNOWLEDGE_GRAPHS_NEO4J_REFACTORING_PLAN.md`
- **Implementation Roadmap**: `docs/KNOWLEDGE_GRAPHS_IMPLEMENTATION_ROADMAP.md`
- **Quick Reference**: `docs/KNOWLEDGE_GRAPHS_QUICK_REFERENCE.md`
- **Feature Matrix**: `docs/KNOWLEDGE_GRAPHS_FEATURE_MATRIX.md`

### Examples

Check the `examples/` directory for working examples:
- Simple graph creation
- Neo4j driver usage
- IPLD persistence
- Batch operations

### Community

- **GitHub Issues**: Report bugs or request features
- **Pull Requests**: Contribute improvements
- **Discussions**: Ask questions and share use cases

---

## Migration Checklist

Use this checklist to track your migration progress:

- [ ] Review migration guide
- [ ] Update imports to new API
- [ ] Replace `IPLDKnowledgeGraph` with `GraphEngine`
- [ ] Replace `Entity` with `Node` creation
- [ ] Update `Relationship` creation
- [ ] Update node queries
- [ ] Update relationship queries
- [ ] Add driver/session management
- [ ] Test with sample data
- [ ] Run full test suite
- [ ] Update documentation
- [ ] Deploy to production

---

## Version History

- **v1.0 (2026-02-15)**: Initial migration guide
  - Phase 1 complete (driver API, storage integration)
  - Legacy API deprecated with warnings
  - Migration patterns documented

---

**Questions?** Open an issue on GitHub or check the documentation!
