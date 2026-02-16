# Knowledge Graphs Query API Documentation

**Version:** 1.0.0  
**Last Updated:** 2026-02-16  
**Status:** Production Ready

## Overview

The `query/` package provides a production-ready query system for knowledge graphs with budget management, hybrid search, and a unified query engine. This document provides complete API reference for all query classes and methods.

## Package Structure

```
ipfs_datasets_py.knowledge_graphs.query/
├── __init__.py           # Public API exports
├── unified_engine.py     # UnifiedQueryEngine (535 lines)
├── hybrid_search.py      # HybridSearchEngine (406 lines)
└── budget_manager.py     # BudgetManager (238 lines)
```

## Installation & Import

```python
from ipfs_datasets_py.knowledge_graphs.query import (
    UnifiedQueryEngine,
    HybridSearchEngine,
    BudgetManager
)

# Budget utilities
from ipfs_datasets_py.search.graph_query.budgets import (
    ExecutionBudgets,
    ExecutionCounters,
    budgets_from_preset
)
```

---

## UnifiedQueryEngine

### Description

Central query execution engine for all GraphRAG operations. Consolidates query logic from multiple implementations providing a single entry point for Cypher queries, IR queries, hybrid search, and full GraphRAG pipelines.

### Constructor

```python
UnifiedQueryEngine(
    backend: Any,                        # Graph backend for storage/retrieval
    vector_store: Optional[Any] = None,  # Vector store for similarity search
    llm_processor: Optional[Any] = None, # LLM processor for reasoning
    enable_caching: bool = True,         # Enable query caching
    default_budgets: str = 'safe'        # Default budget preset
)
```

**Parameters:**
- `backend` (Any): Graph backend (IPLD, Neo4j, etc.)
- `vector_store` (Optional[Any]): Vector store for semantic search (FAISS, Qdrant)
- `llm_processor` (Optional[Any]): LLM processor for reasoning tasks
- `enable_caching` (bool): Whether to cache query results (default: True)
- `default_budgets` (str): Default budget preset - 'strict', 'moderate', 'permissive', or 'safe'

**Example:**
```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

engine = UnifiedQueryEngine(
    backend=ipld_backend,
    enable_caching=True,
    default_budgets='moderate'
)
```

### Methods

#### `execute_query(query, params=None, budgets=None, query_type='auto') -> QueryResult`

Execute a query with automatic type detection.

**Parameters:**
- `query` (str): Query string
- `params` (Optional[Dict]): Query parameters (default: {})
- `budgets` (Optional[ExecutionBudgets]): Execution budgets (uses defaults if None)
- `query_type` (str): Query type - 'auto', 'cypher', 'ir', 'hybrid' (default: 'auto')

**Returns:** `QueryResult` with results and statistics

**Example:**
```python
# Simple query
result = engine.execute_query("MATCH (n:Person) RETURN n LIMIT 10")

# With parameters
result = engine.execute_query(
    "MATCH (n:Person {name: $name}) RETURN n",
    params={"name": "Alice"}
)

# With budgets
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset
budgets = budgets_from_preset('strict')
result = engine.execute_query(query, budgets=budgets)

# Explicit query type
result = engine.execute_query(query, query_type='cypher')
```

#### `execute_cypher(query, params=None, budgets=None) -> QueryResult`

Execute a Cypher query.

**Parameters:**
- `query` (str): Cypher query string
- `params` (Optional[Dict]): Query parameters
- `budgets` (Optional[ExecutionBudgets]): Execution budgets

**Returns:** `QueryResult` with nodes, relationships, and statistics

**Example:**
```python
result = engine.execute_cypher(
    "MATCH (p:Person)-[:WORKS_AT]->(c:Company) WHERE p.name = $name RETURN p, c",
    params={"name": "John Doe"}
)

print(f"Found {len(result.items)} results")
for item in result.items:
    print(item)
```

#### `execute_hybrid(query, k=10, budgets=None, vector_weight=0.6, graph_weight=0.4, max_hops=2) -> QueryResult`

Execute hybrid search combining vector similarity and graph traversal.

**Parameters:**
- `query` (str): Search query text
- `k` (int): Number of results to return (default: 10)
- `budgets` (Optional[ExecutionBudgets]): Execution budgets
- `vector_weight` (float): Weight for vector scores 0-1 (default: 0.6)
- `graph_weight` (float): Weight for graph scores 0-1 (default: 0.4)
- `max_hops` (int): Maximum graph traversal hops (default: 2)

**Returns:** `QueryResult` with ranked hybrid search results

**Example:**
```python
# Basic hybrid search
result = engine.execute_hybrid(
    query="What is IPFS?",
    k=20
)

# Tune weights for more semantic focus
result = engine.execute_hybrid(
    query="content addressing",
    k=15,
    vector_weight=0.8,  # More emphasis on semantic similarity
    graph_weight=0.2,   # Less emphasis on graph structure
    max_hops=3
)

# Process results
for item in result.items:
    print(f"Score: {item.score:.3f}, ID: {item.node_id}")
```

#### `execute_graphrag(question, context=None, budgets=None) -> GraphRAGResult`

Execute full GraphRAG pipeline: hybrid search + LLM reasoning.

**Parameters:**
- `question` (str): Question to answer
- `context` (Optional[Dict]): Additional context (embeddings, documents)
- `budgets` (Optional[ExecutionBudgets]): Execution budgets

**Returns:** `GraphRAGResult` with answer, reasoning, and evidence

**Example:**
```python
result = engine.execute_graphrag(
    question="Explain how content addressing works in IPFS",
    context={"embeddings": embeddings_dict}
)

print(f"Answer: {result.reasoning['answer']}")
print(f"Confidence: {result.confidence:.2%}")
print(f"Evidence chains: {len(result.evidence_chains)}")
```

#### `batch_execute(queries, budgets=None) -> List[QueryResult]`

Execute multiple queries in batch.

**Parameters:**
- `queries` (List[str]): List of query strings
- `budgets` (Optional[ExecutionBudgets]): Shared execution budgets

**Returns:** List of `QueryResult` objects

**Example:**
```python
queries = [
    "MATCH (n:Person) RETURN n LIMIT 5",
    "MATCH (n:Company) RETURN n LIMIT 5",
    "MATCH (n:Technology) RETURN n LIMIT 5"
]

results = engine.batch_execute(queries)

for i, result in enumerate(results):
    print(f"Query {i+1}: {len(result.items)} results")
```

### Properties

#### `cypher_compiler`

Lazy-loaded Cypher compiler instance.

**Returns:** CypherCompiler instance

#### `ir_executor`

Lazy-loaded IR executor instance.

**Returns:** GraphQueryExecutor instance

#### `graph_engine`

Lazy-loaded graph engine instance.

**Returns:** GraphEngine instance

### QueryResult Class

Result container for query execution.

**Attributes:**
- `items` (List[Any]): List of result items
- `stats` (Dict): Execution statistics
- `counters` (Optional[ExecutionCounters]): Budget counters
- `query_type` (str): Type of query executed
- `success` (bool): Whether query succeeded
- `error` (Optional[str]): Error message if failed

**Methods:**
- `to_dict() -> Dict`: Convert result to dictionary

### GraphRAGResult Class

Extended result for GraphRAG queries.

**Attributes:**
- All QueryResult attributes plus:
- `reasoning` (Optional[Dict]): LLM reasoning output
- `evidence_chains` (Optional[List[Dict]]): Supporting evidence
- `confidence` (float): Confidence score (0-1)

---

## HybridSearchEngine

### Description

Hybrid search engine combining vector similarity search with knowledge graph traversal. Provides unified hybrid search functionality with configurable fusion strategies.

### Constructor

```python
HybridSearchEngine(
    backend: Any,                              # Graph backend
    vector_store: Optional[Any] = None,        # Vector store
    default_vector_weight: float = 0.6,        # Default vector score weight
    default_graph_weight: float = 0.4,         # Default graph score weight
    cache_size: int = 1000                     # Result cache size
)
```

**Parameters:**
- `backend` (Any): Graph backend for traversal operations
- `vector_store` (Optional[Any]): Vector store for similarity search
- `default_vector_weight` (float): Default weight for vector scores (0-1)
- `default_graph_weight` (float): Default weight for graph scores (0-1)
- `cache_size` (int): Maximum number of cached results

**Example:**
```python
from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine

engine = HybridSearchEngine(
    backend=ipld_backend,
    vector_store=faiss_store,
    default_vector_weight=0.7,
    default_graph_weight=0.3
)
```

### Methods

#### `search(query, k=10, vector_weight=None, graph_weight=None, max_hops=2, min_score=0.0) -> List[HybridSearchResult]`

Perform hybrid search.

**Parameters:**
- `query` (str): Search query text
- `k` (int): Number of results (default: 10)
- `vector_weight` (Optional[float]): Vector score weight (uses default if None)
- `graph_weight` (Optional[float]): Graph score weight (uses default if None)
- `max_hops` (int): Maximum traversal hops (default: 2)
- `min_score` (float): Minimum score threshold 0-1 (default: 0.0)

**Returns:** List of `HybridSearchResult` objects, sorted by score descending

**Example:**
```python
# Basic search
results = engine.search(
    query="machine learning algorithms",
    k=20
)

# With score threshold
results = engine.search(
    query="neural networks",
    k=50,
    min_score=0.5  # Only results with score >= 0.5
)

# Customize weights
results = engine.search(
    query="deep learning",
    k=30,
    vector_weight=0.8,  # Emphasize semantic similarity
    graph_weight=0.2,
    max_hops=3          # Explore further in graph
)

# Process results
for result in results:
    print(f"Node: {result.node_id}")
    print(f"  Combined Score: {result.score:.3f}")
    print(f"  Vector Score: {result.vector_score:.3f}")
    print(f"  Graph Score: {result.graph_score:.3f}")
    print(f"  Distance: {result.hop_distance} hops")
```

#### `vector_search(query, k=10) -> List[HybridSearchResult]`

Perform pure vector similarity search.

**Parameters:**
- `query` (str): Search query
- `k` (int): Number of results

**Returns:** List of results with vector scores only

**Example:**
```python
results = engine.vector_search("artificial intelligence", k=15)
```

#### `graph_expand(seed_nodes, max_hops=2, max_results=100) -> List[HybridSearchResult]`

Expand from seed nodes via graph traversal.

**Parameters:**
- `seed_nodes` (List[str]): Starting node IDs
- `max_hops` (int): Maximum traversal distance (default: 2)
- `max_results` (int): Maximum nodes to return (default: 100)

**Returns:** List of nodes found via traversal with graph scores

**Example:**
```python
# Start from specific nodes
seed_ids = ["node1", "node2", "node3"]
results = engine.graph_expand(
    seed_nodes=seed_ids,
    max_hops=3,
    max_results=200
)
```

#### `fuse_results(vector_results, graph_results, vector_weight=0.6, graph_weight=0.4, strategy='weighted') -> List[HybridSearchResult]`

Fuse vector and graph results using specified strategy.

**Parameters:**
- `vector_results` (List[HybridSearchResult]): Vector search results
- `graph_results` (List[HybridSearchResult]): Graph expansion results
- `vector_weight` (float): Weight for vector scores (default: 0.6)
- `graph_weight` (float): Weight for graph scores (default: 0.4)
- `strategy` (str): Fusion strategy - 'weighted', 'rrf', 'max' (default: 'weighted')

**Returns:** Fused and ranked results

**Fusion Strategies:**
- `'weighted'`: Linear combination of scores
- `'rrf'`: Reciprocal Rank Fusion
- `'max'`: Take maximum score from either source

**Example:**
```python
# Get separate results
vector_results = engine.vector_search("query", k=50)
graph_results = engine.graph_expand(seed_nodes, max_hops=2)

# Fuse with weighted strategy
fused = engine.fuse_results(
    vector_results,
    graph_results,
    vector_weight=0.7,
    graph_weight=0.3,
    strategy='weighted'
)

# Fuse with RRF (rank-based)
fused_rrf = engine.fuse_results(
    vector_results,
    graph_results,
    strategy='rrf'
)
```

#### `clear_cache()`

Clear the result cache.

**Example:**
```python
engine.clear_cache()
```

### HybridSearchResult Class

Result from hybrid search.

**Attributes:**
- `node_id` (str): Node identifier
- `score` (float): Combined score (0-1)
- `vector_score` (float): Vector similarity score (0-1)
- `graph_score` (float): Graph relevance score (0-1)
- `hop_distance` (int): Distance from seed nodes
- `metadata` (Optional[Dict]): Additional metadata

---

## BudgetManager

### Description

Manages computational budgets for query execution. Enforces limits on timeout, node visits, edge scans, traversal depth, and backend calls to ensure safe execution on large graphs.

### Constructor

```python
BudgetManager()
```

No constructor parameters. Budget Manager is a lightweight utility class.

**Example:**
```python
from ipfs_datasets_py.knowledge_graphs.query import BudgetManager

manager = BudgetManager()
```

### Methods

#### `track(budgets) -> BudgetTracker`

Context manager for tracking budget usage.

**Parameters:**
- `budgets` (ExecutionBudgets): Budget limits

**Returns:** BudgetTracker context manager

**Example:**
```python
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset

manager = BudgetManager()
budgets = budgets_from_preset('moderate')

with manager.track(budgets) as tracker:
    # Execute operations
    result = execute_expensive_query()
    
    # Periodically check budgets
    tracker.check_timeout()
    tracker.check_nodes()

# After context exits
if tracker.exceeded:
    print(f"Budget exceeded: {tracker.exceeded_reason}")
else:
    print(f"Nodes visited: {tracker.counters.nodes_visited}")
    print(f"Edges scanned: {tracker.counters.edges_scanned}")
```

#### `create_preset_budgets(preset) -> ExecutionBudgets`

Create budgets from preset name.

**Parameters:**
- `preset` (str): Preset name - 'strict', 'moderate', 'permissive', 'safe'

**Returns:** ExecutionBudgets with preset values

**Preset Values:**

| Budget | Strict | Moderate | Permissive | Safe |
|--------|--------|----------|------------|------|
| Timeout (ms) | 1000 | 5000 | 30000 | 2000 |
| Max Nodes | 100 | 1000 | 10000 | 500 |
| Max Edges | 500 | 5000 | 50000 | 2500 |
| Max Depth | 3 | 5 | 10 | 4 |
| Max Backend Calls | 10 | 50 | 200 | 25 |

**Example:**
```python
strict = manager.create_preset_budgets('strict')
moderate = manager.create_preset_budgets('moderate')
permissive = manager.create_preset_budgets('permissive')

# Use in query
result = engine.execute_query(query, budgets=strict)
```

#### `check_exceeded(counters, budgets) -> Optional[str]`

Check if any budget limits are exceeded.

**Parameters:**
- `counters` (ExecutionCounters): Current usage counters
- `budgets` (ExecutionBudgets): Budget limits

**Returns:** Error message if exceeded, None otherwise

**Example:**
```python
counters = ExecutionCounters(nodes_visited=150, edges_scanned=600)
budgets = budgets_from_preset('strict')

error = manager.check_exceeded(counters, budgets)
if error:
    print(f"Budget violation: {error}")
```

### ExecutionBudgets Class

Budget limits for query execution.

**Attributes:**
- `timeout_ms` (int): Maximum execution time in milliseconds
- `max_nodes_visited` (int): Maximum number of nodes to visit
- `max_edges_scanned` (int): Maximum number of edges to scan
- `max_traversal_depth` (int): Maximum traversal depth
- `max_backend_calls` (int): Maximum backend API calls

**Example:**
```python
from ipfs_datasets_py.search.graph_query.budgets import ExecutionBudgets

# Custom budgets
budgets = ExecutionBudgets(
    timeout_ms=3000,
    max_nodes_visited=500,
    max_edges_scanned=2000,
    max_traversal_depth=4,
    max_backend_calls=30
)
```

### ExecutionCounters Class

Tracks actual resource usage during query execution.

**Attributes:**
- `nodes_visited` (int): Number of nodes visited
- `edges_scanned` (int): Number of edges scanned
- `traversal_depth` (int): Maximum depth reached
- `backend_calls` (int): Number of backend calls made
- `cache_hits` (int): Number of cache hits
- `cache_misses` (int): Number of cache misses

### BudgetTracker Class

Tracks budget usage within a context.

**Attributes:**
- `budgets` (ExecutionBudgets): Budget limits
- `counters` (ExecutionCounters): Usage counters
- `started` (float): Start time (monotonic)
- `exceeded` (bool): Whether budgets were exceeded
- `exceeded_reason` (Optional[str]): Reason for exceedance

**Methods:**
- `check_timeout()`: Check if timeout exceeded (raises BudgetExceededError)
- `check_nodes()`: Check if node limit exceeded
- `check_edges()`: Check if edge limit exceeded
- `check_depth()`: Check if depth limit exceeded
- `check_backend_calls()`: Check if backend call limit exceeded

---

## Error Handling

### Common Exceptions

```python
from ipfs_datasets_py.search.graph_query.errors import (
    BudgetExceededError,
    QueryError,
    InvalidQueryError
)

try:
    result = engine.execute_query(query, budgets=strict_budgets)
except BudgetExceededError as e:
    print(f"Budget exceeded: {e}")
except InvalidQueryError as e:
    print(f"Invalid query syntax: {e}")
except QueryError as e:
    print(f"Query error: {e}")
```

### Budget Exceeded Handling

```python
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset
from ipfs_datasets_py.search.graph_query.errors import BudgetExceededError

budgets = budgets_from_preset('strict')

try:
    result = engine.execute_query(large_query, budgets=budgets)
except BudgetExceededError as e:
    # Retry with more permissive budgets
    print(f"Strict budgets exceeded: {e}")
    print("Retrying with moderate budgets...")
    
    moderate_budgets = budgets_from_preset('moderate')
    result = engine.execute_query(large_query, budgets=moderate_budgets)
```

---

## Configuration Examples

### Engine Configuration

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset

# Production configuration
engine = UnifiedQueryEngine(
    backend=production_backend,
    vector_store=faiss_production,
    llm_processor=gpt4_processor,
    enable_caching=True,
    default_budgets='moderate'
)

# Development configuration (more permissive)
dev_engine = UnifiedQueryEngine(
    backend=dev_backend,
    enable_caching=False,  # Disable for fresh results
    default_budgets='permissive'
)
```

### Hybrid Search Tuning

```python
from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine

# Semantic-focused (good for concept search)
semantic_engine = HybridSearchEngine(
    backend=backend,
    vector_store=vector_store,
    default_vector_weight=0.8,
    default_graph_weight=0.2,
    cache_size=5000
)

# Structure-focused (good for relationship queries)
structure_engine = HybridSearchEngine(
    backend=backend,
    vector_store=vector_store,
    default_vector_weight=0.3,
    default_graph_weight=0.7
)

# Balanced (general purpose)
balanced_engine = HybridSearchEngine(
    backend=backend,
    vector_store=vector_store,
    default_vector_weight=0.5,
    default_graph_weight=0.5
)
```

---

## Best Practices

### 1. Always Use Budget Management

```python
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset

budgets = budgets_from_preset('moderate')
result = engine.execute_query(query, budgets=budgets)
```

### 2. Enable Caching for Repeated Queries

```python
engine = UnifiedQueryEngine(backend, enable_caching=True)
```

### 3. Tune Hybrid Search Weights

```python
# More semantic for abstract concepts
result = engine.execute_hybrid(
    "machine learning paradigms",
    vector_weight=0.8,
    graph_weight=0.2
)

# More structural for relationships
result = engine.execute_hybrid(
    "who works with whom",
    vector_weight=0.3,
    graph_weight=0.7
)
```

### 4. Use Appropriate Budgets

```python
# Quick queries
quick_budgets = budgets_from_preset('strict')

# Standard queries
standard_budgets = budgets_from_preset('moderate')

# Complex analytics
complex_budgets = budgets_from_preset('permissive')
```

### 5. Handle Errors Gracefully

```python
try:
    result = engine.execute_query(query, budgets=budgets)
    process_results(result)
except BudgetExceededError:
    # Retry with larger budgets or break query into smaller parts
    pass
except QueryError as e:
    logging.error(f"Query failed: {e}")
```

---

## Performance Tips

1. **Use caching** for frequently repeated queries
2. **Set appropriate budgets** to prevent runaway queries
3. **Tune hybrid weights** based on your use case
4. **Batch similar queries** when possible
5. **Monitor counters** to understand resource usage
6. **Clear cache periodically** to free memory
7. **Use lazy loading** for heavy components

---

## Migration from Legacy APIs

### From Direct Cypher Execution

**Before:**
```python
from ipfs_datasets_py.knowledge_graphs.cypher import CypherCompiler

compiler = CypherCompiler()
result = compiler.execute(query)
```

**After:**
```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

engine = UnifiedQueryEngine(backend)
result = engine.execute_cypher(query)
```

### From Legacy Hybrid Search

**Before:**
```python
from processors.graphrag.integration import HybridVectorGraphSearch

search = HybridVectorGraphSearch(backend, vector_store)
results = search.search(query)
```

**After:**
```python
from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine

engine = HybridSearchEngine(backend, vector_store)
results = engine.search(query)
```

---

## Additional Resources

- **Architecture Documentation:** `KNOWLEDGE_GRAPHS_QUERY_ARCHITECTURE.md`
- **Usage Examples:** `KNOWLEDGE_GRAPHS_USAGE_EXAMPLES.md`
- **Extraction API:** `KNOWLEDGE_GRAPHS_EXTRACTION_API.md`
- **Budget System:** `ipfs_datasets_py/search/graph_query/budgets.py`

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-16  
**Author:** Knowledge Graphs Team  
**Status:** Production Ready
