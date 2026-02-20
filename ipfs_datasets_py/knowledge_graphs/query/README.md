# Knowledge Graph Query Engine

Unified query engine for executing queries against knowledge graphs using multiple query languages and execution strategies.

**Version:** 2.1.0 — Updated 2026-02-20

## Overview

The query module provides a flexible, multi-backend query execution engine that supports:
- **Cypher queries** — Neo4j-compatible graph pattern matching (all clauses: MATCH, CREATE, MERGE, REMOVE, SET, UNWIND, WITH, FOREACH, CALL subquery)
- **IR (Intermediate Representation) queries** — Graph traversal operations
- **Hybrid search** — Combines graph queries with vector similarity search
- **GraphRAG** — Retrieval-Augmented Generation with knowledge graphs
- **Distributed query execution** — Fan-out queries across graph partitions
- **SPARQL templates** — Wikidata and general SPARQL query helpers

## Module Contents

| File | Description |
|------|-------------|
| `unified_engine.py` | `UnifiedQueryEngine` — main query coordinator |
| `hybrid_search.py` | Hybrid graph + vector similarity search |
| `budget_manager.py` | Query cost and timeout management |
| `distributed.py` | `GraphPartitioner` + `FederatedQueryExecutor` |
| `knowledge_graph.py` | High-level `KnowledgeGraphQuerier` tool (moved from root) |
| `sparql_templates.py` | Reusable Wikidata / SPARQL query templates (moved from root) |

## Key Features

- **Multi-Language Support** - Execute Cypher, IR, or hybrid queries
- **Unified Interface** - Single entry point for all query types
- **Budget Management** - Control computational costs of queries
- **Timeout Handling** - Prevent long-running queries from blocking
- **Error Recovery** - Graceful degradation and detailed error messages
- **Query Optimization** - Automatic query planning and optimization

## Core Classes

### `UnifiedQueryEngine`
Main query engine that coordinates execution across backends.

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

engine = UnifiedQueryEngine(
    cypher_backend=cypher_engine,
    ir_backend=ir_executor,
    hybrid_backend=hybrid_search_engine
)

# Execute Cypher query
result = await engine.execute_query(
    query="MATCH (n:Person) WHERE n.age > 30 RETURN n",
    query_type="cypher"
)
```

### `HybridSearchEngine`
Combines graph queries with vector similarity search.

```python
from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine

hybrid = HybridSearchEngine(graph_engine, vector_store)

# Search with both graph patterns and semantic similarity
results = await hybrid.search(
    graph_pattern="MATCH (n:Document)-[:MENTIONS]->(e:Entity)",
    vector_query="machine learning applications",
    alpha=0.5  # Balance between graph and vector results
)
```

### `BudgetManager`
Controls computational budgets for queries.

```python
from ipfs_datasets_py.knowledge_graphs.query import BudgetManager

budget = BudgetManager(
    max_nodes=1000,
    max_edges=5000,
    max_time_seconds=30.0
)

# Execute with budget constraints
result = await engine.execute_query(query, budget=budget)
```

## Usage Examples

### Example 1: Basic Cypher Query

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
import asyncio

async def find_people():
    engine = UnifiedQueryEngine(cypher_backend=cypher_engine)
    
    # Find all people older than 30
    result = await engine.execute_query(
        query="MATCH (p:Person) WHERE p.age > 30 RETURN p.name, p.age",
        query_type="cypher"
    )
    
    if result.success:
        for record in result.records:
            print(f"{record['p.name']}: {record['p.age']}")
    else:
        print(f"Query failed: {result.error}")

asyncio.run(find_people())
```

### Example 2: Hybrid Search

```python
from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine

async def hybrid_search_example():
    # Initialize hybrid search engine
    hybrid = HybridSearchEngine(
        graph_engine=graph_engine,
        vector_store=vector_store
    )
    
    # Search for documents related to "AI" with semantic similarity
    results = await hybrid.search(
        graph_pattern="MATCH (d:Document)-[:ABOUT]->(t:Topic {name: 'AI'})",
        vector_query="artificial intelligence applications",
        alpha=0.6,  # 60% graph, 40% vector
        top_k=10
    )
    
    for result in results:
        print(f"Document: {result.document_id}")
        print(f"  Graph score: {result.graph_score}")
        print(f"  Vector score: {result.vector_score}")
        print(f"  Combined score: {result.combined_score}")

asyncio.run(hybrid_search_example())
```

### Example 3: Query with Budget Control

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine, BudgetManager
from ipfs_datasets_py.knowledge_graphs.exceptions import QueryTimeoutError

async def budgeted_query():
    engine = UnifiedQueryEngine(cypher_backend=cypher_engine)
    
    # Create budget: max 500 nodes, 2000 edges, 10 seconds
    budget = BudgetManager(
        max_nodes=500,
        max_edges=2000,
        max_time_seconds=10.0
    )
    
    try:
        result = await engine.execute_query(
            query="MATCH (n)-[r*1..5]-(m) RETURN n, r, m",
            query_type="cypher",
            budget=budget
        )
        print(f"Query completed: {len(result.records)} results")
    except QueryTimeoutError:
        print("Query exceeded time budget")

asyncio.run(budgeted_query())
```

### Example 4: IR (Intermediate Representation) Query

```python
async def ir_query_example():
    engine = UnifiedQueryEngine(ir_backend=ir_executor)
    
    # Execute IR query (more direct graph traversal)
    ir_query = {
        "operation": "traverse",
        "start_nodes": ["node123"],
        "relationship_type": "KNOWS",
        "max_depth": 3
    }
    
    result = await engine.execute_query(
        query=ir_query,
        query_type="ir"
    )
    
    if result.success:
        print(f"Found {len(result.nodes)} connected nodes")

asyncio.run(ir_query_example())
```

## Query Types

### Cypher Queries
Neo4j-compatible graph pattern matching language:

```cypher
// Find friends of friends
MATCH (person:Person)-[:KNOWS]->(friend)-[:KNOWS]->(fof)
WHERE person.name = 'Alice'
RETURN DISTINCT fof.name
```

### IR Queries
Lower-level graph operations:

```python
{
    "operation": "filter",
    "node_type": "Person",
    "property": "age",
    "operator": ">",
    "value": 30
}
```

### Hybrid Queries
Combined graph + vector search:

```python
{
    "graph_pattern": "MATCH (d:Document)-[:TAGGED]->(t:Tag)",
    "vector_query": "natural language processing",
    "alpha": 0.7,
    "top_k": 20
}
```

## Query Results

All queries return a `QueryResult` object:

```python
@dataclass
class QueryResult:
    success: bool              # True if query executed successfully
    records: List[Dict]        # Query results as list of dicts
    error: Optional[str]       # Error message if success=False
    execution_time: float      # Query execution time in seconds
    nodes_visited: int         # Number of nodes traversed
    edges_visited: int         # Number of edges traversed
    metadata: Dict[str, Any]   # Additional query metadata
```

## Error Handling

The query engine uses specific exceptions for different failure modes:

```python
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    QueryParseError,      # Invalid query syntax
    QueryExecutionError,  # Query execution failed
    QueryTimeoutError     # Query exceeded time budget
)

try:
    result = await engine.execute_query(query)
except QueryParseError as e:
    print(f"Invalid query syntax: {e}")
    print(f"Details: {e.details}")
except QueryTimeoutError as e:
    print(f"Query timed out: {e}")
except QueryExecutionError as e:
    print(f"Execution failed: {e}")
```

## Performance Optimization

### Query Planning

The engine automatically optimizes queries:

```python
# Automatically reorders pattern matching for efficiency
# BEFORE (slow): MATCH (a)-[r]->(b) WHERE a.type = 'Person'
# AFTER (fast): MATCH (a:Person)-[r]->(b)
```

### Caching

Results can be cached for repeated queries:

```python
engine = UnifiedQueryEngine(
    cypher_backend=cypher_engine,
    enable_cache=True,
    cache_ttl=300  # Cache for 5 minutes
)

# First call: executes query
result1 = await engine.execute_query(query)

# Second call: returns cached result
result2 = await engine.execute_query(query)
```

### Parallel Execution

Multiple independent queries can run in parallel:

```python
queries = [
    "MATCH (n:Person) RETURN count(n)",
    "MATCH (n:Document) RETURN count(n)",
    "MATCH (n:Entity) RETURN count(n)"
]

results = await asyncio.gather(*[
    engine.execute_query(q) for q in queries
])
```

## See Also

- [Cypher Module](../cypher/README.md) - Cypher query parsing and compilation
- [Storage Module](../storage/README.md) - Graph storage backends
- [Constraints Module](../constraints/README.md) - Constraint validation during queries
- [Transactions Module](../transactions/README.md) - Transactional query execution

## Future Enhancements

- **Query Optimization** - Cost-based query optimization
- **Distributed Execution** - Query execution across multiple nodes
- **Query Explain** - Detailed execution plans for debugging
- **Result Streaming** - Stream large result sets
- **GraphQL Support** - GraphQL query interface
