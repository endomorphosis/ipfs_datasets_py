# Neo4j Compatibility Layer

**Version:** 2.0.0  
**Package:** `ipfs_datasets_py.knowledge_graphs.neo4j_compat`

---

## Overview

The Neo4j Compatibility module provides a drop-in replacement for the Neo4j Python driver, allowing existing Neo4j applications to work with IPFS-backed knowledge graphs with minimal code changes.

**Key Features:**
- Neo4j Driver API compatibility
- Session and transaction management
- Cypher query execution
- Result streaming
- Connection pooling
- Bookmark support

---

## Core Components

### Driver (`driver.py`)

Main entry point that mimics Neo4j driver interface:

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

# Create driver (Neo4j-compatible API)
driver = GraphDatabase.driver(
    "ipfs://localhost:5001",
    auth=None  # Auth not required for IPFS
)

# Use with context manager
with driver.session() as session:
    result = session.run("MATCH (n:Person) RETURN n.name AS name")
    for record in result:
        print(f"Name: {record['name']}")

driver.close()
```

**Driver Methods:**
- `session()` - Create new session
- `close()` - Close driver
- `verify_connectivity()` - Check connection
- `get_server_info()` - Get server metadata

### Session (`session.py`)

Session management with transaction support:

```python
# Create session
session = driver.session(database="default")

# Run query
result = session.run(
    "MATCH (n:Person {name: $name}) RETURN n",
    name="Alice"
)

# Iterate results
for record in result:
    node = record["n"]
    print(f"Node: {node['name']}, Age: {node['age']}")

# Close session
session.close()
```

**Session Modes:**
- `READ` - Read-only queries
- `WRITE` - Read-write queries

**Transaction Types:**
- Auto-commit (default)
- Explicit transactions
- Transaction functions

### Connection Pool (`connection_pool.py`)

Connection pooling for performance:

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import ConnectionPool

# Create pool
pool = ConnectionPool(
    uri="ipfs://localhost:5001",
    max_connections=10,
    connection_timeout=30
)

# Get connection
with pool.acquire() as connection:
    result = connection.execute("MATCH (n) RETURN COUNT(n)")
    print(f"Node count: {result[0][0]}")
```

**Pool Configuration:**
- `max_connections` - Maximum pool size
- `min_connections` - Minimum connections
- `connection_timeout` - Timeout in seconds
- `max_lifetime` - Connection max age

### Result (`result.py`)

Result streaming and iteration:

```python
# Execute query
result = session.run("MATCH (n:Person) RETURN n.name, n.age")

# Iterate records
for record in result:
    name = record["n.name"]
    age = record["n.age"]
    print(f"{name}: {age}")

# Or convert to list
records = list(result)

# Access by index
first_record = result.peek()
print(f"First: {first_record['n.name']}")

# Get summary
summary = result.consume()
print(f"Query took {summary.result_available_after}ms")
```

**Result Methods:**
- `records()` - Get all records as list
- `single()` - Get single record (error if multiple)
- `peek()` - Peek at first record without consuming
- `consume()` - Consume and get summary
- `data()` - Convert to list of dicts

### Bookmarks (`bookmarks.py`)

Causal consistency with bookmarks:

```python
# Execute with bookmark
session1 = driver.session()
result1 = session1.run("CREATE (n:Person {name: 'Alice'})")
bookmark1 = session1.last_bookmark()

# Use bookmark in another session
session2 = driver.session(bookmarks=[bookmark1])
result2 = session2.run("MATCH (n:Person {name: 'Alice'}) RETURN n")
# Guaranteed to see Alice created in session1
```

**Bookmark Use Cases:**
- Causal consistency across sessions
- Read-your-writes guarantees
- Distributed transaction coordination

### Types (`types.py`)

Neo4j type mappings:

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import (
    Node, Relationship, Path
)

# Node representation
node = Node(
    id=123,
    labels=["Person", "Employee"],
    properties={"name": "Alice", "age": 30}
)

# Relationship representation
rel = Relationship(
    id=456,
    type="WORKS_AT",
    start_node=123,
    end_node=789,
    properties={"since": "2020"}
)

# Path representation
path = Path(
    nodes=[node1, node2, node3],
    relationships=[rel1, rel2]
)
```

---

## Usage Examples

### Example 1: Basic Neo4j Application Migration

**Before (Neo4j):**
```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    "bolt://localhost:7687",
    auth=("neo4j", "password")
)

with driver.session() as session:
    result = session.run("MATCH (n:Person) RETURN n")
    for record in result:
        print(record["n"])

driver.close()
```

**After (IPFS Knowledge Graphs):**
```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

driver = GraphDatabase.driver(
    "ipfs://localhost:5001",
    auth=None  # No auth needed
)

with driver.session() as session:
    result = session.run("MATCH (n:Person) RETURN n")
    for record in result:
        print(record["n"])

driver.close()
```

**Changes Required:** Only the URI and auth (most code unchanged!)

### Example 2: Transactions

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

driver = GraphDatabase.driver("ipfs://localhost:5001")

# Explicit transaction
with driver.session() as session:
    with session.begin_transaction() as tx:
        tx.run("CREATE (n:Person {name: 'Alice'})")
        tx.run("CREATE (n:Person {name: 'Bob'})")
        tx.commit()  # Or tx.rollback()

# Transaction function (auto-retry)
def create_person(tx, name):
    return tx.run("CREATE (n:Person {name: $name}) RETURN n", name=name)

with driver.session() as session:
    result = session.write_transaction(create_person, "Charlie")
```

### Example 3: Parameterized Queries

```python
# Prevent injection, improve performance
result = session.run("""
    MATCH (p:Person {name: $name})
    WHERE p.age > $min_age
    RETURN p
""", name="Alice", min_age=25)

for record in result:
    print(f"Found: {record['p']['name']}")
```

### Example 4: Result Processing

```python
# Method 1: Iterate
result = session.run("MATCH (n:Person) RETURN n.name AS name, n.age AS age")
for record in result:
    print(f"{record['name']}: {record['age']}")

# Method 2: To list
result = session.run("MATCH (n:Person) RETURN n")
records = list(result)
print(f"Found {len(records)} people")

# Method 3: Single result
result = session.run("MATCH (n:Person {name: 'Alice'}) RETURN n")
record = result.single()  # Error if 0 or >1 results
node = record["n"]

# Method 4: To DataFrame
import pandas as pd
result = session.run("MATCH (n:Person) RETURN n.name, n.age")
df = pd.DataFrame([dict(record) for record in result])
```

### Example 5: Connection Pooling

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import GraphDatabase

# Configure pool
driver = GraphDatabase.driver(
    "ipfs://localhost:5001",
    max_connection_pool_size=50,
    max_connection_lifetime=3600,  # 1 hour
    connection_acquisition_timeout=60  # 1 minute
)

# Pool automatically manages connections
with driver.session() as session:
    # Gets connection from pool
    result = session.run("MATCH (n) RETURN COUNT(n)")
    # Returns connection to pool when done
```

---

## Compatibility Matrix

### Supported Features

| Feature | Neo4j Driver | IPFS Compat | Notes |
|---------|--------------|-------------|-------|
| Driver Creation | ✅ | ✅ | Different URI scheme |
| Sessions | ✅ | ✅ | Full support |
| Transactions | ✅ | ✅ | Auto-commit + explicit |
| Bookmarks | ✅ | ✅ | Causal consistency |
| Connection Pool | ✅ | ✅ | Configurable |
| Result Streaming | ✅ | ✅ | Iterator interface |
| Parameterized Queries | ✅ | ✅ | Recommended |
| Transaction Functions | ✅ | ✅ | With auto-retry |
| Read/Write Splitting | ✅ | ⚠️ | Single backend |
| Reactive Sessions | ✅ | ❌ | Not supported |
| Async Driver | ✅ | ❌ | Planned v2.1 |

### URI Schemes

| Scheme | Description | Example |
|--------|-------------|---------|
| `ipfs://` | IPFS HTTP API | `ipfs://localhost:5001` |
| `ipfs+https://` | IPFS over HTTPS | `ipfs+https://ipfs.io` |
| `bolt://` | Neo4j Bolt (not supported) | - |

---

## Migration Guide

### Step 1: Update Dependencies

```bash
# Before
pip install neo4j

# After
pip install ipfs-datasets-py
```

### Step 2: Update Imports

```python
# Before
from neo4j import GraphDatabase, Session, Transaction

# After
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import (
    GraphDatabase, Session, Transaction
)
```

### Step 3: Update Connection URI

```python
# Before
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))

# After
driver = GraphDatabase.driver("ipfs://localhost:5001", auth=None)
```

### Step 4: Test Application

```python
# Run existing tests to verify compatibility
pytest tests/ -v
```

### Common Migration Issues

**Issue 1: Auth Required**
```python
# Neo4j requires auth
driver = GraphDatabase.driver("bolt://...", auth=("user", "pass"))

# IPFS doesn't (set to None)
driver = GraphDatabase.driver("ipfs://...", auth=None)
```

**Issue 2: Reactive Sessions**
```python
# Not supported yet
# session = driver.session(database="neo4j", fetch_size=100)  # ❌

# Use regular sessions
session = driver.session()  # ✅
```

**Issue 3: Multi-Database**
```python
# Neo4j supports multiple databases
session = driver.session(database="mydb")

# IPFS uses single database (parameter ignored)
session = driver.session()  # database ignored
```

---

## Performance Considerations

### Connection Reuse

```python
# Inefficient: Create driver per query
def query_data():
    driver = GraphDatabase.driver("ipfs://localhost:5001")
    with driver.session() as session:
        return session.run("MATCH (n) RETURN n").data()
    driver.close()

# Efficient: Reuse driver
driver = GraphDatabase.driver("ipfs://localhost:5001")

def query_data():
    with driver.session() as session:
        return session.run("MATCH (n) RETURN n").data()

# Close when done
driver.close()
```

### Session Reuse

```python
# Use context manager to auto-close
with driver.session() as session:
    result1 = session.run("MATCH (n:Person) RETURN n")
    result2 = session.run("MATCH (n:Company) RETURN n")
    # Session closed automatically
```

---

## Error Handling

### Common Exceptions

```python
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import (
    ServiceUnavailable,
    TransientError,
    DatabaseError
)

try:
    driver = GraphDatabase.driver("ipfs://invalid:5001")
    driver.verify_connectivity()
except ServiceUnavailable as e:
    print(f"Cannot connect: {e}")

try:
    result = session.run("INVALID CYPHER")
except DatabaseError as e:
    print(f"Query error: {e}")
```

---

## Testing

```bash
# Run Neo4j compatibility tests
pytest tests/knowledge_graphs/test_neo4j_compat/ -v

# Test driver
pytest tests/knowledge_graphs/test_neo4j_compat/test_driver.py -v

# Test sessions
pytest tests/knowledge_graphs/test_neo4j_compat/test_session.py -v

# Test transactions
pytest tests/knowledge_graphs/test_neo4j_compat/test_transactions.py -v
```

---

## See Also

- **[Driver Module](../core/README.md)** - Core graph engine
- **[Cypher Module](../cypher/README.md)** - Query language
- **[Transaction Module](../transactions/README.md)** - ACID transactions
- **[MIGRATION_GUIDE.md](../../../../docs/knowledge_graphs/MIGRATION_GUIDE.md)** - Neo4j migration guide
- **[API_REFERENCE.md](../../../../docs/knowledge_graphs/API_REFERENCE.md)** - Full API docs

---

## Status

**Test Coverage:** ~70%  
**Production Ready:** Yes  
**Neo4j Compatibility:** ~80% (driver API)

**Known Limitations:**
- No reactive/async sessions (planned v2.1)
- Single database only (no multi-db)
- No Bolt protocol (uses IPFS HTTP API)
- Some admin operations not supported

**Roadmap:**
- v2.0: Core driver compatibility ✅
- v2.1: Async driver support (Q2 2026)
- v2.2: Advanced pooling (Q3 2026)
