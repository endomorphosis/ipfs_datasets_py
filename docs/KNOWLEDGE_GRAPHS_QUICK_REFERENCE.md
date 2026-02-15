# IPFS Graph Database - Quick Reference

**Version:** 1.0  
**Last Updated:** 2026-02-15

This is a quick reference guide for the IPFS/IPLD-native graph database with Neo4j compatibility.

---

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [API Compatibility](#api-compatibility)
3. [Cypher Query Examples](#cypher-query-examples)
4. [Transaction Management](#transaction-management)
5. [JSON-LD Translation](#json-ld-translation)
6. [Migration from Neo4j](#migration-from-neo4j)
7. [Performance Tips](#performance-tips)

---

## Quick Start

### Installation

```bash
# Basic installation
pip install ipfs-datasets-py

# With graph database features
pip install ipfs-datasets-py[graph-db]

# Development installation
pip install -e ".[graph-db,test]"
```

### Basic Usage

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

# Connect to IPFS daemon
driver = GraphDatabase.driver("ipfs://localhost:5001", auth=("user", "token"))

# Or use embedded mode (no daemon required)
driver = GraphDatabase.driver("ipfs+embedded://./my_graph")

# Run a query
with driver.session() as session:
    result = session.run("""
        MATCH (n:Person {name: $name})
        RETURN n
    """, name="Alice")
    
    for record in result:
        print(record["n"])

driver.close()
```

---

## API Compatibility

### Connection URIs

| URI Format | Description | Use Case |
|------------|-------------|----------|
| `ipfs://localhost:5001` | Connect to local IPFS daemon | Development |
| `ipfs://ipfs.example.com:443` | Connect to remote IPFS API | Production |
| `ipfs+embedded://./data` | Embedded mode (no daemon) | Portable apps |
| `ipfs+cluster://cluster1,cluster2` | IPFS cluster connection | High availability |

### Driver API (Neo4j Compatible)

```python
# Create driver
driver = GraphDatabase.driver(uri, auth=(username, password))

# Create session
session = driver.session(database="default")

# Run query (auto-commit)
result = session.run(query, **parameters)

# Transactions
with session.begin_transaction() as tx:
    tx.run(query1)
    tx.run(query2)
    tx.commit()  # Or tx.rollback()

# Read/write transactions
def create_person(tx, name):
    return tx.run("CREATE (p:Person {name: $name}) RETURN p", name=name)

with session.write_transaction(create_person, "Alice") as result:
    print(result.single())

# Close resources
session.close()
driver.close()
```

---

## Cypher Query Examples

### Basic Queries

```cypher
-- Create nodes
CREATE (p:Person {name: "Alice", age: 30})

-- Create relationships
MATCH (a:Person {name: "Alice"}), (b:Person {name: "Bob"})
CREATE (a)-[:KNOWS {since: 2020}]->(b)

-- Find nodes
MATCH (p:Person)
WHERE p.age > 25
RETURN p.name, p.age
ORDER BY p.age DESC
LIMIT 10

-- Pattern matching
MATCH (p:Person)-[:KNOWS]->(friend:Person)
WHERE p.name = "Alice"
RETURN friend.name

-- Multi-hop traversal
MATCH (p:Person)-[:KNOWS*1..3]->(friend)
WHERE p.name = "Alice"
RETURN DISTINCT friend.name
```

### Advanced Queries

```cypher
-- Aggregations
MATCH (p:Person)-[:WORKS_AT]->(c:Company)
RETURN c.name, COUNT(p) AS employee_count
ORDER BY employee_count DESC

-- Shortest path
MATCH path = shortestPath(
  (a:Person {name: "Alice"})-[:KNOWS*]-(b:Person {name: "Charlie"})
)
RETURN path

-- Conditional logic
MATCH (p:Person)
RETURN p.name,
  CASE
    WHEN p.age < 18 THEN "Minor"
    WHEN p.age < 65 THEN "Adult"
    ELSE "Senior"
  END AS category

-- Merge (upsert)
MERGE (p:Person {email: "alice@example.com"})
ON CREATE SET p.name = "Alice", p.created = timestamp()
ON MATCH SET p.lastSeen = timestamp()
RETURN p
```

### Graph Algorithms

```cypher
-- PageRank (future feature)
CALL graph.pageRank("Person", "KNOWS")
YIELD nodeId, score
RETURN nodeId, score
ORDER BY score DESC
LIMIT 10

-- Community detection (future feature)
CALL graph.louvain("Person", "KNOWS")
YIELD nodeId, communityId
RETURN communityId, COUNT(nodeId) AS size
ORDER BY size DESC
```

---

## Transaction Management

### Transaction Types

```python
from ipfs_datasets_py.knowledge_graphs.transactions import IsolationLevel

# Auto-commit (default)
session.run("CREATE (p:Person {name: 'Alice'})")

# Explicit transaction
tx = session.begin_transaction()
try:
    tx.run("CREATE (p:Person {name: 'Bob'})")
    tx.run("CREATE (p:Person {name: 'Charlie'})")
    tx.commit()
except Exception as e:
    tx.rollback()
    raise

# Isolation levels
tx = session.begin_transaction(isolation_level=IsolationLevel.REPEATABLE_READ)
```

### Isolation Levels

| Level | Description | Performance | Use Case |
|-------|-------------|-------------|----------|
| `READ_UNCOMMITTED` | No isolation | Fastest | Analytics, non-critical reads |
| `READ_COMMITTED` | See committed changes only | Fast | Web applications |
| `REPEATABLE_READ` | Snapshot isolation (default) | Medium | General purpose |
| `SERIALIZABLE` | Full serializability | Slow | Financial transactions |

### Transaction Best Practices

```python
# 1. Keep transactions short
with session.write_transaction(create_batch) as result:
    pass  # Transaction auto-commits

# 2. Retry on conflicts
from ipfs_datasets_py.knowledge_graphs.transactions import TransactionConflict

MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        with session.write_transaction(update_node):
            break
    except TransactionConflict:
        if attempt == MAX_RETRIES - 1:
            raise

# 3. Use read transactions for queries
with session.read_transaction(find_friends) as result:
    friends = [r["friend"] for r in result]
```

---

## JSON-LD Translation

### Basic Translation

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import JSONLDTranslator

translator = JSONLDTranslator()

# Convert JSON-LD to IPLD graph
jsonld = {
    "@context": "https://schema.org/",
    "@id": "http://example.com/alice",
    "@type": "Person",
    "name": "Alice Smith",
    "knows": {
        "@id": "http://example.com/bob",
        "@type": "Person",
        "name": "Bob Jones"
    }
}

ipld_graph = translator.jsonld_to_ipld(jsonld)
graph_cid = ipld_graph.save()
print(f"Graph stored at: {graph_cid}")

# Convert back to JSON-LD
recovered_jsonld = translator.ipld_to_jsonld(ipld_graph)
```

### Custom Vocabularies

```python
# Define custom context
custom_context = {
    "@vocab": "http://mycompany.com/ontology/",
    "knows": {"@type": "@id"},
    "birthDate": {"@type": "xsd:date"}
}

jsonld = {
    "@context": custom_context,
    "@type": "Employee",
    "name": "Alice",
    "knows": "http://example.com/bob",
    "birthDate": "1990-01-01"
}

ipld_graph = translator.jsonld_to_ipld(jsonld, context=custom_context)
```

### Supported Vocabularies

- ✅ **Schema.org** - `https://schema.org/`
- ✅ **FOAF** - Friend of a Friend
- ✅ **Dublin Core** - Metadata terms
- ✅ **SKOS** - Simple Knowledge Organization System
- ✅ **Wikidata** - Wikidata entities
- ✅ **Custom** - User-defined contexts

---

## Migration from Neo4j

### Step-by-Step Migration

```python
from ipfs_datasets_py.knowledge_graphs.migration import Neo4jMigrator

# 1. Create migrator
migrator = Neo4jMigrator(
    neo4j_uri="bolt://localhost:7687",
    neo4j_auth=("neo4j", "password"),
    ipfs_uri="ipfs://localhost:5001"
)

# 2. Export Neo4j database to CAR file
migrator.export_to_car(
    output_path="my_graph.car",
    database="neo4j"  # or None for default
)

# 3. Verify export
stats = migrator.get_export_stats("my_graph.car")
print(f"Exported {stats['node_count']} nodes, {stats['relationship_count']} relationships")

# 4. Import to IPFS
graph_cid = migrator.import_from_car("my_graph.car")
print(f"Graph migrated to IPFS: {graph_cid}")

# 5. Validate migration
validation = migrator.validate_migration(graph_cid)
if validation['success']:
    print("✅ Migration successful!")
else:
    print(f"❌ Migration issues: {validation['errors']}")
```

### Code Migration

**Before (Neo4j)**:
```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "pass"))
# ... rest of code
```

**After (IPFS Graph DB)**:
```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

driver = GraphDatabase.driver("ipfs://localhost:5001", auth=("user", "token"))
# ... rest of code (NO CHANGES NEEDED!)
```

### Feature Compatibility

| Neo4j Feature | IPFS Graph DB | Notes |
|---------------|---------------|-------|
| Cypher queries | ✅ Supported | 95%+ compatibility |
| ACID transactions | ✅ Supported | Full ACID |
| Indexes | ✅ Supported | B-tree, full-text |
| Constraints | ✅ Supported | Unique, existence, type |
| Bolt protocol | ❌ Not supported | Use native API instead |
| Clustering | ⚠️ Different | Uses IPFS cluster |
| Procedures (CALL) | ⚠️ Partial | Core procedures only |
| User management | ⚠️ Different | Uses IPFS auth |

---

## Performance Tips

### 1. Use Indexes

```cypher
-- Create indexes for frequently queried properties
CREATE INDEX person_name FOR (p:Person) ON (p.name)
CREATE INDEX person_email FOR (p:Person) ON (p.email)

-- Full-text search
CREATE FULLTEXT INDEX person_search FOR (p:Person) ON EACH [p.name, p.bio]
CALL db.index.fulltext.queryNodes("person_search", "alice") YIELD node
RETURN node
```

### 2. Optimize Queries

```cypher
-- ❌ Bad: Scans all nodes
MATCH (p:Person)
WHERE p.email = "alice@example.com"
RETURN p

-- ✅ Good: Uses index
MATCH (p:Person {email: "alice@example.com"})
RETURN p

-- ❌ Bad: Unnecessary traversal
MATCH (p:Person)-[:KNOWS*]->(friend)
RETURN COUNT(friend)

-- ✅ Good: Limit depth
MATCH (p:Person)-[:KNOWS*1..3]->(friend)
RETURN COUNT(friend)
```

### 3. Batch Operations

```python
# ❌ Slow: Individual inserts
for person in people:
    session.run("CREATE (p:Person $props)", props=person)

# ✅ Fast: Batch insert
session.run("""
    UNWIND $people AS person
    CREATE (p:Person)
    SET p = person
""", people=people)
```

### 4. Use Caching

```python
from ipfs_datasets_py.knowledge_graphs import GraphDatabase, CacheConfig

driver = GraphDatabase.driver(
    "ipfs://localhost:5001",
    cache_config=CacheConfig(
        enabled=True,
        ttl=3600,  # 1 hour
        max_size=1000,  # 1000 query results
        strategy="LRU"  # Least Recently Used
    )
)
```

### 5. Monitor Performance

```python
# Enable query logging
driver = GraphDatabase.driver(
    "ipfs://localhost:5001",
    config={
        "query_logging": True,
        "slow_query_threshold": 1000  # Log queries >1s
    }
)

# Get query statistics
with driver.session() as session:
    result = session.run("CALL db.stats.query($query)", query="MATCH (n) RETURN n")
    stats = result.single()
    print(f"Execution time: {stats['execution_time']}ms")
```

---

## Troubleshooting

### Common Issues

#### 1. Connection Failed

```
Error: Failed to connect to IPFS daemon at localhost:5001
```

**Solution**:
```bash
# Check IPFS daemon is running
ipfs swarm peers

# Start IPFS daemon
ipfs daemon

# Or use embedded mode
driver = GraphDatabase.driver("ipfs+embedded://./data")
```

#### 2. Transaction Conflict

```
Error: Transaction conflict detected, CID mismatch
```

**Solution**:
```python
# Add retry logic
MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        with session.write_transaction(my_function):
            break
    except TransactionConflict:
        if attempt == MAX_RETRIES - 1:
            raise
        time.sleep(0.1 * (2 ** attempt))  # Exponential backoff
```

#### 3. Query Timeout

```
Error: Query exceeded maximum execution time (10s)
```

**Solution**:
```python
# Increase timeout
driver = GraphDatabase.driver(
    "ipfs://localhost:5001",
    config={"query_timeout": 30000}  # 30 seconds
)

# Or optimize query with LIMIT
session.run("MATCH (n:Person) RETURN n LIMIT 100")
```

---

## Examples

### Example 1: Social Network

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

driver = GraphDatabase.driver("ipfs://localhost:5001")

with driver.session() as session:
    # Create users
    session.run("""
        CREATE (alice:Person {name: "Alice", age: 30})
        CREATE (bob:Person {name: "Bob", age: 25})
        CREATE (charlie:Person {name: "Charlie", age: 35})
        CREATE (alice)-[:KNOWS {since: 2015}]->(bob)
        CREATE (bob)-[:KNOWS {since: 2018}]->(charlie)
    """)
    
    # Find friends of friends
    result = session.run("""
        MATCH (p:Person {name: "Alice"})-[:KNOWS*2]->(fof)
        RETURN DISTINCT fof.name AS friend_of_friend
    """)
    
    for record in result:
        print(f"Friend of friend: {record['friend_of_friend']}")

driver.close()
```

### Example 2: Movie Recommendations

```python
# Create movie graph
session.run("""
    CREATE (alice:Person {name: "Alice"})
    CREATE (bob:Person {name: "Bob"})
    CREATE (matrix:Movie {title: "The Matrix", year: 1999})
    CREATE (inception:Movie {title: "Inception", year: 2010})
    CREATE (alice)-[:WATCHED {rating: 5}]->(matrix)
    CREATE (bob)-[:WATCHED {rating: 5}]->(matrix)
    CREATE (bob)-[:WATCHED {rating: 4}]->(inception)
""")

# Recommend movies based on similar users
result = session.run("""
    MATCH (alice:Person {name: "Alice"})-[:WATCHED]->(m:Movie)<-[:WATCHED]-(other:Person)
    MATCH (other)-[:WATCHED]->(rec:Movie)
    WHERE NOT (alice)-[:WATCHED]->(rec)
    RETURN rec.title, COUNT(*) AS score
    ORDER BY score DESC
    LIMIT 5
""")

for record in result:
    print(f"Recommended: {record['rec.title']} (score: {record['score']})")
```

---

## Resources

### Documentation
- [Full Refactoring Plan](./KNOWLEDGE_GRAPHS_NEO4J_REFACTORING_PLAN.md)
- [Architecture Overview](./GRAPH_DATABASE_ARCHITECTURE.md)
- [API Reference](./api/graph_database.html)

### External Resources
- [Neo4j Cypher Manual](https://neo4j.com/docs/cypher-manual/)
- [IPFS Documentation](https://docs.ipfs.tech/)
- [JSON-LD Specification](https://www.w3.org/TR/json-ld11/)

### Support
- GitHub Issues: [endomorphosis/ipfs_datasets_py](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- Discussion Forum: TBD
- Email: TBD

---

**Last Updated:** 2026-02-15  
**Version:** 1.0  
**License:** MIT
