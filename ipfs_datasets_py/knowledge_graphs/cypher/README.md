# Cypher Query Language Module

**Version:** 2.0.0  
**Package:** `ipfs_datasets_py.knowledge_graphs.cypher`

---

## Overview

The Cypher module provides a Neo4j-compatible query language implementation for knowledge graphs. It includes a complete lexer, parser, AST (Abstract Syntax Tree), compiler, and function library for executing graph queries.

**Key Features:**
- Neo4j Cypher query syntax support
- Graph pattern matching
- Aggregation functions
- String manipulation functions
- Path finding operations
- Query compilation and optimization

---

## Core Components

### Lexer (`lexer.py`)

Tokenizes Cypher query strings into tokens:

```python
from ipfs_datasets_py.knowledge_graphs.cypher import CypherLexer

lexer = CypherLexer()
tokens = lexer.tokenize("MATCH (n:Person) RETURN n")

for token in tokens:
    print(f"{token.type}: {token.value}")
```

**Supported Tokens:**
- Keywords: `MATCH`, `WHERE`, `RETURN`, `CREATE`, `ORDER BY`, `LIMIT`
- Operators: `=`, `<`, `>`, `AND`, `OR`
- Identifiers and literals
- Node/relationship patterns

### Parser (`parser.py`)

Parses tokens into an Abstract Syntax Tree:

```python
from ipfs_datasets_py.knowledge_graphs.cypher import CypherParser

parser = CypherParser()
ast = parser.parse("MATCH (n:Person {name: 'Alice'}) RETURN n")

print(ast.to_dict())  # AST representation
```

**Query Types Supported:**
- `MATCH` queries - Pattern matching
- `WHERE` clauses - Filtering
- `RETURN` statements - Result projection
- `ORDER BY` clauses - Sorting
- `LIMIT` clauses - Result limiting

### AST (`ast.py`)

Abstract Syntax Tree node definitions:

```python
from ipfs_datasets_py.knowledge_graphs.cypher.ast import (
    MatchClause,
    WhereClause,
    ReturnClause,
    PropertyMatch
)

# Build AST programmatically
match = MatchClause(
    node_pattern="n:Person",
    properties={"name": "Alice"}
)
```

**Node Types:**
- `MatchClause` - Graph pattern matching
- `WhereClause` - Filter conditions
- `ReturnClause` - Result specification
- `PropertyMatch` - Property constraints
- `AggregateFunction` - COUNT, SUM, AVG, etc.

### Compiler (`compiler.py`)

Compiles AST to executable query plans:

```python
from ipfs_datasets_py.knowledge_graphs.cypher import CypherCompiler

compiler = CypherCompiler(knowledge_graph)
query_plan = compiler.compile(ast)
result = query_plan.execute()

for record in result:
    print(record)
```

**Compilation Steps:**
1. Parse query to AST
2. Optimize query plan
3. Generate execution plan
4. Execute against knowledge graph

### Functions (`functions.py`)

Built-in Cypher functions:

```python
from ipfs_datasets_py.knowledge_graphs.cypher.functions import (
    count,
    sum_values,
    avg,
    min_value,
    max_value,
    contains,
    starts_with,
    ends_with
)

# Use in queries
results = compiler.execute("MATCH (n:Person) RETURN count(n)")
```

**Function Categories:**
- **Aggregations:** `COUNT()`, `SUM()`, `AVG()`, `MIN()`, `MAX()`
- **String:** `CONTAINS()`, `STARTS WITH()`, `ENDS WITH()`
- **Math:** Basic arithmetic operations
- **List:** List manipulation functions

---

## Usage Examples

### Example 1: Basic Pattern Matching

```python
from ipfs_datasets_py.knowledge_graphs.cypher import CypherCompiler
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph

# Create knowledge graph
kg = KnowledgeGraph()
# ... add entities and relationships ...

# Execute Cypher query
compiler = CypherCompiler(kg)
result = compiler.execute("""
    MATCH (p:Person)
    WHERE p.name = 'Marie Curie'
    RETURN p
""")

for record in result:
    print(f"Found: {record['p'].name}")
```

### Example 2: Relationship Queries

```python
# Find who won what prize
result = compiler.execute("""
    MATCH (p:Person)-[r:WON]->(prize:Award)
    RETURN p.name AS person, prize.name AS award
""")

for record in result:
    print(f"{record['person']} won {record['award']}")
```

### Example 3: Aggregation Queries

```python
# Count entities by type
result = compiler.execute("""
    MATCH (n)
    RETURN n.entity_type AS type, count(n) AS count
    ORDER BY count DESC
""")

for record in result:
    print(f"{record['type']}: {record['count']} entities")
```

### Example 4: Property Filtering

```python
# Find entities with specific properties
result = compiler.execute("""
    MATCH (n:Person)
    WHERE n.confidence > 0.8
    RETURN n.name, n.confidence
    ORDER BY n.confidence DESC
    LIMIT 10
""")

for record in result:
    print(f"{record['n.name']}: {record['n.confidence']:.2f}")
```

### Example 5: String Functions

```python
# Search for entities by name pattern
result = compiler.execute("""
    MATCH (n:Person)
    WHERE n.name CONTAINS 'Marie'
    RETURN n.name
""")

for record in result:
    print(record['n.name'])
```

---

## Supported Cypher Features

### ✅ Fully Supported

| Feature | Example | Notes |
|---------|---------|-------|
| `MATCH` | `MATCH (n:Person)` | Pattern matching |
| `WHERE` | `WHERE n.age > 18` | Filtering |
| `RETURN` | `RETURN n, r` | Result projection |
| `ORDER BY` | `ORDER BY n.name DESC` | Sorting |
| `LIMIT` | `LIMIT 10` | Result limiting |
| Aggregations | `COUNT(n)`, `SUM(n.value)` | COUNT, SUM, AVG, MIN, MAX |
| String functions | `CONTAINS()`, `STARTS WITH()` | Pattern matching |
| Property access | `n.name`, `n.properties.age` | Dot notation |

### ⚠️ Partially Supported

| Feature | Status | Workaround |
|---------|--------|------------|
| Complex patterns | Limited | Break into simpler queries |
| Multiple MATCH | Limited | Use joins in application code |
| Subqueries | Not supported | Flatten query structure |

### ❌ Not Supported

| Feature | Status | Alternative |
|---------|--------|-------------|
| `NOT` operator | Not implemented | Use positive conditions |
| `CREATE` relationships | Not implemented | Use Python API |
| `MERGE` | Not implemented | Use CREATE + deduplication |
| `DELETE` | Not implemented | Use Python API |

**See [MIGRATION_GUIDE.md](/docs/knowledge_graphs/MIGRATION_GUIDE.md#cypher-language-support) for workarounds.**

---

## Error Handling

### Common Errors

**Syntax Error:**
```python
try:
    result = compiler.execute("MATCH (n Person) RETURN n")  # Missing colon
except CypherSyntaxError as e:
    print(f"Syntax error: {e}")
    print(f"Position: {e.position}")
```

**Compilation Error:**
```python
try:
    result = compiler.execute("MATCH (n:UnknownType) RETURN n")
except CypherCompilationError as e:
    print(f"Compilation error: {e}")
```

**Runtime Error:**
```python
try:
    result = compiler.execute("RETURN nonexistent_var")
except CypherRuntimeError as e:
    print(f"Runtime error: {e}")
```

---

## Performance Tips

### Query Optimization

1. **Use specific node types:** `MATCH (n:Person)` faster than `MATCH (n)`
2. **Filter early:** Put WHERE clauses immediately after MATCH
3. **Limit results:** Always use LIMIT for large graphs
4. **Index property lookups:** Use indexed properties in WHERE clauses

### Example: Optimized Query

```python
# ❌ Slow
result = compiler.execute("""
    MATCH (n)
    RETURN n
    WHERE n.name = 'Alice'
    LIMIT 10
""")

# ✅ Fast
result = compiler.execute("""
    MATCH (n:Person)
    WHERE n.name = 'Alice'
    RETURN n
    LIMIT 10
""")
```

---

## Integration with Other Modules

### With Extraction Module

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.knowledge_graphs.cypher import CypherCompiler

# Extract knowledge graph
extractor = KnowledgeGraphExtractor()
kg = extractor.extract_knowledge_graph(text)

# Query with Cypher
compiler = CypherCompiler(kg)
result = compiler.execute("MATCH (n:Person) RETURN n")
```

### With Query Module

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

engine = UnifiedQueryEngine(kg)
result = engine.execute_cypher("""
    MATCH (p:Person)-[:WON]->(a:Award)
    RETURN p.name, a.name
""")
```

---

## Testing

Run Cypher module tests:

```bash
pytest tests/unit/knowledge_graphs/test_cypher*.py -v
```

---

## See Also

- [API_REFERENCE.md](/docs/knowledge_graphs/API_REFERENCE.md#cypher-language-reference) - Complete Cypher API
- [USER_GUIDE.md](/docs/knowledge_graphs/USER_GUIDE.md#query-patterns) - Query patterns and examples
- [MIGRATION_GUIDE.md](/docs/knowledge_graphs/MIGRATION_GUIDE.md#cypher-language-support) - Known limitations and workarounds

---

**Last Updated:** 2026-02-17  
**Status:** Production-Ready
