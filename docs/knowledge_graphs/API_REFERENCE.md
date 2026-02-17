# Knowledge Graphs - API Reference

**Version:** 2.0.0  
**Last Updated:** 2026-02-17

## Overview

Complete API reference for all knowledge graphs classes and methods, consolidated from EXTRACTION_API and QUERY_API documentation.

## Extraction API

### KnowledgeGraphExtractor

Main class for extracting knowledge graphs from text.

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()
graph = extractor.extract(text)
```

**Methods:**
- `extract(text: str) -> KnowledgeGraph`: Extract entities and relationships
- `extract_entities(text: str) -> List[Entity]`: Extract only entities
- `extract_relationships(text: str) -> List[Relationship]`: Extract only relationships

### Entity

Represents an entity in the knowledge graph.

**Attributes:**
- `entity_type: str` - Category (person, place, organization, etc.)
- `name: str` - Primary identifier
- `properties: Dict[str, Any]` - Additional attributes
- `confidence: float` - Extraction confidence (0.0-1.0)

### Relationship

Represents a relationship between entities.

**Attributes:**
- `source: str` - Source entity name
- `target: str` - Target entity name
- `relationship_type: str` - Type of connection
- `properties: Dict[str, Any]` - Additional attributes
- `confidence: float` - Relationship confidence

### KnowledgeGraph

Container for entities and relationships.

**Methods:**
- `add_entity(entity: Entity)` - Add entity to graph
- `add_relationship(rel: Relationship)` - Add relationship to graph
- `get_entities() -> List[Entity]` - Get all entities
- `get_relationships() -> List[Relationship]` - Get all relationships

## Query API

### UnifiedQueryEngine

Central query execution engine for all GraphRAG operations.

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

engine = UnifiedQueryEngine(backend=graph_backend)
result = engine.execute_cypher(query)
```

**Methods:**
- `execute_cypher(query: str, params: Dict = None) -> QueryResult`
- `execute_ir(query: IRQuery) -> QueryResult`
- `execute_hybrid(query: str, top_k: int) -> QueryResult`
- `execute_graphrag(question: str, depth: int) -> QueryResult`

### HybridSearchEngine

Combines vector similarity with graph traversal.

**Methods:**
- `search(query: str, top_k: int, hybrid_weight: float) -> List[SearchResult]`

### BudgetManager

Manages resource budgets for query execution.

**Methods:**
- `check_budget(counters: ExecutionCounters) -> bool`
- `get_remaining_budget() -> ExecutionBudgets`

## Storage API

### IPLDBackend

IPFS/IPLD storage backend for knowledge graphs.

**Methods:**
- `store(graph: KnowledgeGraph, codec: str = "dag-cbor") -> str`
- `retrieve(cid: str) -> KnowledgeGraph`

## Transaction API

### TransactionManager

ACID-compliant transaction management.

**Methods:**
- `begin_transaction() -> Transaction`
- `commit(tx: Transaction)`
- `rollback(tx: Transaction)`

See subdirectory READMEs for detailed module documentation.
