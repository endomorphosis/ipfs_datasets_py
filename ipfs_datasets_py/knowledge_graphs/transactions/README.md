# Knowledge Graph Transactions

ACID-compliant transaction system for knowledge graph modifications with write-ahead logging and rollback support.

## Overview

The transactions module provides:
- **ACID Compliance** - Atomicity, Consistency, Isolation, Durability
- **Write-Ahead Logging (WAL)** - Durable transaction log for crash recovery
- **Rollback Support** - Undo changes when transactions fail
- **Isolation Levels** - Control concurrent access to graph data
- **Snapshot Isolation** - Read-consistent views of the graph
- **Conflict Detection** - Detect and resolve concurrent modification conflicts

## Key Features

- **Transaction Manager** - Coordinate multi-operation transactions
- **WAL (Write-Ahead Log)** - Persist operations before execution
- **Snapshot Management** - Create point-in-time graph snapshots
- **Conflict Resolution** - Handle concurrent modifications
- **Recovery** - Automatic recovery from crashes
- **Nested Transactions** - Support for savepoints and sub-transactions

## Core Classes

### `TransactionManager`
Central coordinator for all transactions.

```python
from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager

manager = TransactionManager(graph=knowledge_graph)

# Begin transaction
txn = await manager.begin()

try:
    # Perform operations
    txn.add_entity(entity)
    txn.add_relationship(rel)
    
    # Commit changes
    await manager.commit(txn)
except Exception:
    # Rollback on error
    await manager.rollback(txn)
```

### `WriteAheadLog (WAL)`
Persistent log for transaction operations.

```python
from ipfs_datasets_py.knowledge_graphs.transactions import WriteAheadLog

wal = WriteAheadLog(log_path="/path/to/wal")

# Append transaction entry
await wal.append(TransactionEntry(
    txn_id=txn.id,
    operation="ADD_ENTITY",
    data=entity
))

# Read transaction history
entries = await wal.read(txn_id)

# Compact log (remove completed transactions)
await wal.compact()
```

### `TransactionTypes`
Type definitions for transactions.

```python
from ipfs_datasets_py.knowledge_graphs.transactions.types import (
    TransactionStatus,
    IsolationLevel,
    OperationType
)

# Transaction statuses
status in [
    TransactionStatus.ACTIVE,
    TransactionStatus.COMMITTED,
    TransactionStatus.ABORTED,
    TransactionStatus.PREPARING
]

# Isolation levels
isolation in [
    IsolationLevel.READ_UNCOMMITTED,
    IsolationLevel.READ_COMMITTED,
    IsolationLevel.REPEATABLE_READ,
    IsolationLevel.SERIALIZABLE
]
```

## Usage Examples

### Example 1: Basic Transaction

```python
from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager
import asyncio

async def basic_transaction():
    manager = TransactionManager(graph=kg)
    
    # Begin transaction
    txn = await manager.begin()
    
    try:
        # Add entity
        txn.add_entity(Entity(
            entity_id="e1",
            entity_type="Person",
            name="Alice"
        ))
        
        # Add relationship
        txn.add_relationship(Relationship(
            relationship_id="r1",
            source_id="e1",
            target_id="e2",
            relationship_type="KNOWS"
        ))
        
        # Commit
        await manager.commit(txn)
        print("Transaction committed successfully")
        
    except Exception as e:
        # Rollback on error
        await manager.rollback(txn)
        print(f"Transaction rolled back: {e}")

asyncio.run(basic_transaction())
```

### Example 2: Snapshot Isolation

```python
from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager

async def snapshot_example():
    manager = TransactionManager(graph=kg)
    
    # Transaction 1: Read-only snapshot
    txn1 = await manager.begin(isolation=IsolationLevel.REPEATABLE_READ)
    snapshot1 = await manager.get_snapshot(txn1)
    
    # Transaction 2: Modify graph
    txn2 = await manager.begin()
    txn2.add_entity(new_entity)
    await manager.commit(txn2)
    
    # Transaction 1 still sees original snapshot
    entities_before = snapshot1.get_entities()
    # new_entity NOT in entities_before
    
    await manager.commit(txn1)
    
    # New transaction sees updated graph
    txn3 = await manager.begin()
    snapshot3 = await manager.get_snapshot(txn3)
    entities_after = snapshot3.get_entities()
    # new_entity IS in entities_after

asyncio.run(snapshot_example())
```

### Example 3: Conflict Detection

```python
from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager
from ipfs_datasets_py.knowledge_graphs.exceptions import TransactionConflictError

async def concurrent_modifications():
    manager = TransactionManager(graph=kg)
    
    # Two concurrent transactions
    txn1 = await manager.begin()
    txn2 = await manager.begin()
    
    # Both try to modify the same entity
    txn1.update_entity("e1", {"name": "Alice Updated 1"})
    txn2.update_entity("e1", {"name": "Alice Updated 2"})
    
    # First commit succeeds
    await manager.commit(txn1)
    print("Transaction 1 committed")
    
    # Second commit detects conflict
    try:
        await manager.commit(txn2)
    except TransactionConflictError as e:
        print(f"Conflict detected: {e}")
        await manager.rollback(txn2)

asyncio.run(concurrent_modifications())
```

### Example 4: Write-Ahead Logging

```python
from ipfs_datasets_py.knowledge_graphs.transactions import WriteAheadLog

async def wal_example():
    wal = WriteAheadLog(log_path="/tmp/kg_wal")
    
    # Record transaction operations
    txn_id = "txn123"
    
    await wal.append(TransactionEntry(
        txn_id=txn_id,
        operation="BEGIN",
        timestamp=time.time()
    ))
    
    await wal.append(TransactionEntry(
        txn_id=txn_id,
        operation="ADD_ENTITY",
        data=entity.to_dict()
    ))
    
    await wal.append(TransactionEntry(
        txn_id=txn_id,
        operation="COMMIT",
        timestamp=time.time()
    ))
    
    # Read transaction history
    entries = await wal.read(txn_id)
    print(f"Transaction {txn_id} had {len(entries)} operations")
    
    # Recover from crash
    if crashed:
        await wal.recover()

asyncio.run(wal_example())
```

### Example 5: Savepoints (Nested Transactions)

```python
async def savepoint_example():
    manager = TransactionManager(graph=kg)
    
    txn = await manager.begin()
    
    # Initial operations
    txn.add_entity(entity1)
    
    # Create savepoint
    savepoint = await manager.savepoint(txn, name="before_risky_ops")
    
    try:
        # Risky operations
        txn.add_entity(entity2)
        txn.add_entity(entity3)
        
        # Success - commit entire transaction
        await manager.commit(txn)
        
    except Exception as e:
        # Rollback to savepoint (keep entity1, discard entity2/3)
        await manager.rollback_to_savepoint(txn, savepoint)
        
        # Continue with safe operations
        txn.add_entity(safe_entity)
        await manager.commit(txn)

asyncio.run(savepoint_example())
```

## Transaction Lifecycle

```
BEGIN
  ↓
ACTIVE (operations recorded in WAL)
  ↓
PREPARING (validation, conflict detection)
  ↓
COMMITTED ←→ ABORTED (rollback)
  ↓
COMPLETED
```

## Isolation Levels

### READ_UNCOMMITTED
- Dirty reads allowed
- Lowest isolation, highest performance
- Use for analytics queries

### READ_COMMITTED (Default)
- Only read committed data
- Prevents dirty reads
- Good balance of consistency and performance

### REPEATABLE_READ
- Consistent snapshot throughout transaction
- Prevents non-repeatable reads
- Snapshot isolation

### SERIALIZABLE
- Full isolation, as if transactions run serially
- Highest consistency, lowest performance
- Use for critical operations

```python
txn = await manager.begin(isolation=IsolationLevel.SERIALIZABLE)
```

## Error Handling

Transaction-specific exceptions:

```python
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    TransactionError,         # Base transaction exception
    TransactionConflictError, # Concurrent modification conflict
    TransactionAbortedError,  # Transaction was aborted
    TransactionTimeoutError   # Transaction exceeded timeout
)

try:
    await manager.commit(txn)
except TransactionConflictError as e:
    print(f"Conflict: {e}")
    print(f"Conflicting txn: {e.details.get('conflicting_txn_id')}")
except TransactionTimeoutError as e:
    print(f"Timeout after {e.details.get('timeout_seconds')}s")
except TransactionAbortedError as e:
    print(f"Transaction aborted: {e.details.get('reason')}")
```

## Write-Ahead Log (WAL)

### WAL Operations

```python
wal = WriteAheadLog(log_path="/var/kg/wal")

# Append entry
await wal.append(entry)

# Read entries
entries = await wal.read(txn_id)

# Get history
history = await wal.get_transaction_history(txn_id)

# Compact log (remove old entries)
await wal.compact(before_timestamp=cutoff_time)

# Verify log integrity
is_valid = await wal.verify()

# Recover from crash
recovered_txns = await wal.recover()
```

### WAL Recovery

After a crash, the WAL can recover uncommitted transactions:

```python
async def crash_recovery():
    wal = WriteAheadLog(log_path="/var/kg/wal")
    
    # Recover uncommitted transactions
    recovered = await wal.recover()
    
    for txn_id, entries in recovered.items():
        # Replay or rollback based on transaction state
        last_entry = entries[-1]
        
        if last_entry.operation == "COMMIT":
            # Replay committed transaction
            await replay_transaction(entries)
        else:
            # Rollback incomplete transaction
            await rollback_transaction(entries)

asyncio.run(crash_recovery())
```

## Performance Optimization

### Batched Commits

```python
async def batch_commit():
    manager = TransactionManager(graph=kg)
    
    transactions = []
    for i in range(100):
        txn = await manager.begin()
        txn.add_entity(Entity(entity_id=f"e{i}", ...))
        transactions.append(txn)
    
    # Commit all at once
    await manager.commit_batch(transactions)
```

### Async Operations

```python
# Multiple concurrent transactions
async def concurrent_transactions():
    tasks = [
        process_transaction(data1),
        process_transaction(data2),
        process_transaction(data3)
    ]
    
    results = await asyncio.gather(*tasks)
```

## See Also

- [Storage Module](../storage/README.md) - Persistent storage for transactions
- [Query Module](../query/README.md) - Transactional query execution
- [Core Module](../core/README.md) - Core data structures

## Future Enhancements

- **Distributed Transactions** - Two-phase commit across nodes
- **Optimistic Locking** - Version-based concurrency control
- **Long-Running Transactions** - Support for multi-hour transactions
- **Transaction Logging** - Detailed operation logs for audit
- **Automatic Retry** - Retry failed transactions with exponential backoff
