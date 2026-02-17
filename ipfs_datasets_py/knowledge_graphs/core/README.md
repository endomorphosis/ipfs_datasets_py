# Core Graph Database Engine

**Version:** 2.0.0  
**Package:** `ipfs_datasets_py.knowledge_graphs.core`

---

## Overview

The Core module provides the central graph database engine that coordinates all components of the IPFS-based knowledge graph system. It implements unified query execution, intermediate representation (IR), and expression evaluation.

**Key Features:**
- Unified query execution interface
- Intermediate Representation (IR) for query optimization
- Expression evaluation engine
- Graph engine coordination
- Query planning and optimization

---

## Core Components

### GraphEngine (`graph_engine.py`)

Main engine that coordinates all graph database operations:

```python
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

# Initialize engine with storage backend
storage = IPLDBackend()
engine = GraphEngine(storage_backend=storage)

# Execute queries through unified interface
result = engine.execute_query("MATCH (n:Person) RETURN n")
print(f"Found {len(result)} nodes")
```

**Features:**
- Storage backend abstraction
- Transaction coordination
- Index acceleration
- Performance monitoring
- Query routing

### QueryExecutor (`query_executor.py`)

Executes queries against IPLD-backed graphs:

```python
from ipfs_datasets_py.knowledge_graphs.core import QueryExecutor

# Create executor with engine
executor = QueryExecutor(graph_engine=engine)

# Execute Cypher query
result = executor.execute("MATCH (n)-[r]->(m) WHERE n.name = 'Alice' RETURN m")

# Process results
for record in result:
    print(f"Related node: {record['m']}")
```

**Execution Flow:**
1. Parse query string
2. Generate IR (Intermediate Representation)
3. Optimize IR tree
4. Execute against graph engine
5. Return formatted results

### IRExecutor (`ir_executor.py`)

Executes Intermediate Representation queries:

```python
from ipfs_datasets_py.knowledge_graphs.core import IRExecutor
from ipfs_datasets_py.knowledge_graphs.core.ir import IRNode

# Build IR tree
ir_node = IRNode(
    operation="MATCH",
    pattern={"label": "Person", "properties": {"age": {"$gt": 30}}}
)

# Execute IR
executor = IRExecutor(graph_engine=engine)
result = executor.execute(ir_node)
```

**IR Operations:**
- `MATCH` - Pattern matching
- `FILTER` - Predicate evaluation
- `PROJECT` - Column selection
- `AGGREGATE` - Aggregation functions
- `ORDER` - Sorting
- `LIMIT` - Result limiting

### ExpressionEvaluator (`expression_evaluator.py`)

Evaluates expressions and predicates:

```python
from ipfs_datasets_py.knowledge_graphs.core import ExpressionEvaluator

evaluator = ExpressionEvaluator()

# Evaluate simple expression
result = evaluator.evaluate("age > 30 AND name STARTS WITH 'A'", context={
    "age": 35,
    "name": "Alice"
})
print(f"Expression result: {result}")  # True

# Evaluate aggregation
avg_age = evaluator.evaluate("AVG(age)", records=[
    {"age": 25},
    {"age": 30},
    {"age": 35}
])
print(f"Average age: {avg_age}")  # 30
```

**Supported Expressions:**
- Comparison: `=`, `<>`, `<`, `>`, `<=`, `>=`
- Logical: `AND`, `OR`, `NOT`
- String: `STARTS WITH`, `ENDS WITH`, `CONTAINS`
- Functions: `UPPER()`, `LOWER()`, `LENGTH()`
- Aggregations: `COUNT()`, `SUM()`, `AVG()`, `MIN()`, `MAX()`

---

## Architecture

### Component Layers

```
┌─────────────────────────────────────────────┐
│           Driver API & Session              │  ← User Interface
├─────────────────────────────────────────────┤
│              QueryExecutor                  │  ← Query Execution
├─────────────────────────────────────────────┤
│    GraphEngine    │   IRExecutor            │  ← Engine Layer
├───────────────────┼─────────────────────────┤
│  ExpressionEval   │   Query Optimizer       │  ← Evaluation
├─────────────────────────────────────────────┤
│         Storage Backend (IPLD)              │  ← Storage
└─────────────────────────────────────────────┘
```

### Query Execution Pipeline

1. **Parse** - Convert Cypher to AST
2. **Compile** - Generate IR tree
3. **Optimize** - Apply optimization rules
4. **Execute** - Run against graph engine
5. **Format** - Return results

---

## Usage Examples

### Example 1: Basic Query Execution

```python
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine, QueryExecutor
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

# Setup
storage = IPLDBackend()
engine = GraphEngine(storage_backend=storage)
executor = QueryExecutor(graph_engine=engine)

# Execute query
result = executor.execute("""
    MATCH (person:Person)-[:WORKS_AT]->(company:Company)
    WHERE person.age > 30
    RETURN person.name, company.name
    ORDER BY person.age DESC
    LIMIT 10
""")

# Process results
for record in result:
    print(f"{record['person.name']} works at {record['company.name']}")
```

### Example 2: IR-Based Execution

```python
from ipfs_datasets_py.knowledge_graphs.core import IRExecutor
from ipfs_datasets_py.knowledge_graphs.core.ir import (
    IRMatch, IRFilter, IRProject, IRLimit
)

# Build IR programmatically
ir_query = IRMatch(
    pattern={"label": "Person", "properties": {}},
    filters=[
        IRFilter(expression="age > 30")
    ],
    project=IRProject(columns=["name", "age"]),
    limit=IRLimit(count=10)
)

# Execute
executor = IRExecutor(graph_engine=engine)
result = executor.execute(ir_query)
```

### Example 3: Expression Evaluation

```python
from ipfs_datasets_py.knowledge_graphs.core import ExpressionEvaluator

evaluator = ExpressionEvaluator()

# Complex predicate
predicate = "age BETWEEN 25 AND 35 AND (city = 'NYC' OR city = 'LA')"
context = {"age": 30, "city": "NYC"}

if evaluator.evaluate(predicate, context):
    print("Match found!")

# Aggregation with grouping
records = [
    {"dept": "Engineering", "salary": 100000},
    {"dept": "Engineering", "salary": 120000},
    {"dept": "Sales", "salary": 80000},
]

avg_by_dept = evaluator.group_aggregate(
    records, 
    group_by="dept",
    aggregate="AVG(salary)"
)
print(avg_by_dept)  # {"Engineering": 110000, "Sales": 80000}
```

### Example 4: Transaction Coordination

```python
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine
from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager

engine = GraphEngine(storage_backend=storage)
tx_manager = TransactionManager(storage_backend=storage)

# Start transaction
with tx_manager.begin() as tx:
    # Execute multiple queries in transaction
    engine.execute_query("CREATE (n:Person {name: 'Alice'})", transaction=tx)
    engine.execute_query("CREATE (n:Person {name: 'Bob'})", transaction=tx)
    
    # Transaction commits automatically on exit
```

### Example 5: Performance Monitoring

```python
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine

engine = GraphEngine(storage_backend=storage, enable_metrics=True)

# Execute query
result = engine.execute_query("MATCH (n) RETURN n")

# Get metrics
metrics = engine.get_metrics()
print(f"Query time: {metrics['query_time_ms']}ms")
print(f"Nodes scanned: {metrics['nodes_scanned']}")
print(f"Index hits: {metrics['index_hits']}")
print(f"Cache hit rate: {metrics['cache_hit_rate']:.2%}")
```

---

## Performance Considerations

### Query Optimization

**Index Usage:**
```python
# Inefficient: Full scan
result = engine.execute("MATCH (n:Person) WHERE n.name = 'Alice' RETURN n")

# Efficient: Index lookup (if index exists)
engine.create_index("Person", "name")
result = engine.execute("MATCH (n:Person {name: 'Alice'}) RETURN n")
```

**Early Filtering:**
```python
# Inefficient: Filter after match
result = engine.execute("""
    MATCH (n:Person)-[r:KNOWS]->(m:Person)
    WHERE n.age > 30
    RETURN n, m
""")

# Efficient: Filter during match
result = engine.execute("""
    MATCH (n:Person {age: {$gt: 30}})-[r:KNOWS]->(m:Person)
    RETURN n, m
""")
```

### Performance Targets

| Operation | Target Latency | Notes |
|-----------|---------------|--------|
| Simple MATCH | <10ms | Indexed lookup |
| Pattern MATCH | <50ms | Small graph (<1000 nodes) |
| Aggregation | <100ms | With appropriate indexes |
| Complex JOIN | <200ms | Multi-hop traversal |

---

## Error Handling

### Common Errors

**QueryExecutionError:**
```python
from ipfs_datasets_py.knowledge_graphs.core import QueryExecutionError

try:
    result = executor.execute("MATCH (n) WHERE n.invalid_field = 5 RETURN n")
except QueryExecutionError as e:
    print(f"Query failed: {e.message}")
    print(f"Error code: {e.code}")
```

**IRCompilationError:**
```python
from ipfs_datasets_py.knowledge_graphs.core import IRCompilationError

try:
    ir_node = IRMatch(pattern={"invalid": "pattern"})
    executor.execute(ir_node)
except IRCompilationError as e:
    print(f"IR compilation failed: {e}")
```

**ExpressionError:**
```python
from ipfs_datasets_py.knowledge_graphs.core import ExpressionError

try:
    result = evaluator.evaluate("invalid_function()", context={})
except ExpressionError as e:
    print(f"Expression evaluation failed: {e}")
```

---

## Integration

### With Transaction Module

```python
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine
from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager

engine = GraphEngine(storage_backend=storage)
tx_manager = TransactionManager(storage_backend=storage)

# Transactional execution
with tx_manager.begin() as tx:
    engine.execute_query("CREATE (n:Person {name: 'Alice'})", transaction=tx)
```

### With Cypher Module

```python
from ipfs_datasets_py.knowledge_graphs.core import QueryExecutor
from ipfs_datasets_py.knowledge_graphs.cypher import CypherCompiler

executor = QueryExecutor(graph_engine=engine)
compiler = CypherCompiler()

# Compile Cypher to IR, then execute
cypher_query = "MATCH (n:Person) RETURN n"
ir_tree = compiler.compile(cypher_query)
result = executor.execute_ir(ir_tree)
```

### With Storage Module

```python
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

storage = IPLDBackend(ipfs_client=ipfs_client)
engine = GraphEngine(
    storage_backend=storage,
    cache_size=10000,
    enable_metrics=True
)
```

---

## Testing

```bash
# Run core module tests
pytest tests/knowledge_graphs/test_core/ -v

# Test query execution
pytest tests/knowledge_graphs/test_core/test_query_executor.py -v

# Test IR execution
pytest tests/knowledge_graphs/test_core/test_ir_executor.py -v

# Test expression evaluation
pytest tests/knowledge_graphs/test_core/test_expression_evaluator.py -v

# Run with coverage
pytest tests/knowledge_graphs/test_core/ --cov=ipfs_datasets_py.knowledge_graphs.core
```

---

## See Also

- **[Cypher Module](../cypher/README.md)** - Query language implementation
- **[Storage Module](../storage/README.md)** - IPLD storage backend
- **[Transaction Module](../transactions/README.md)** - ACID transactions
- **[Query Module](../query/README.md)** - High-level query interface
- **[USER_GUIDE.md](../../../../docs/knowledge_graphs/USER_GUIDE.md)** - Complete usage guide
- **[API_REFERENCE.md](../../../../docs/knowledge_graphs/API_REFERENCE.md)** - Full API documentation

---

## Status

**Test Coverage:** ~80%  
**Production Ready:** Yes  
**Breaking Changes:** None in 2.x  

**Roadmap:**
- Phase 1: Query routing and execution ✅ Complete
- Phase 2: Cypher integration ✅ Complete  
- Phase 3: Transaction integration ✅ Complete
- Phase 5: Advanced optimization (Planned)
