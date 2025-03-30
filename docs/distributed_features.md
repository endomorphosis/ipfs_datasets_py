# Distributed Features Guide

This guide covers the distributed features of IPFS Datasets Python, including sharded datasets, peer-to-peer communication, federated search, and resilient operations.

## Table of Contents

1. [Introduction](#introduction)
2. [Sharded Datasets](#sharded-datasets)
3. [Node Architecture](#node-architecture)
4. [Peer-to-Peer Communication](#peer-to-peer-communication)
5. [Dataset Distribution](#dataset-distribution)
6. [Federated Search](#federated-search)
7. [Resilient Operations](#resilient-operations)
8. [Node Health Monitoring](#node-health-monitoring)
9. [Advanced Features](#advanced-features)
10. [Configuration](#configuration)
11. [Best Practices](#best-practices)

## Introduction

IPFS Datasets Python provides powerful distributed capabilities that enable working with datasets across multiple nodes. These features allow you to:

- Distribute large datasets across multiple nodes
- Replicate shards for fault tolerance
- Perform searches across distributed data
- Recover from node failures
- Monitor node health and performance

## Sharded Datasets

A sharded dataset is divided into manageable fragments (shards) distributed across multiple nodes. Each shard contains a subset of the dataset, and metadata is synchronized to enable operations across the entire dataset.

### Creating Sharded Datasets

```python
from ipfs_datasets_py.libp2p_kit import DistributedDatasetManager, NodeRole
import pandas as pd

# Initialize a manager
manager = DistributedDatasetManager(
    node_id="coordinator-node",
    role=NodeRole.COORDINATOR
)

# Create a dataset definition
dataset = manager.create_dataset(
    name="Distributed Dataset",
    description="A dataset distributed across multiple nodes",
    schema={"id": "integer", "text": "string", "vector": "float[]"}
)

# Create sample data
df = pd.DataFrame({
    "id": list(range(1000)),
    "text": [f"Sample text {i}" for i in range(1000)]
})

# Shard and distribute the dataset
shards = await manager.shard_dataset(
    dataset_id=dataset.dataset_id,
    data=df,
    format="parquet",
    shard_size=100,  # Records per shard
    replication_factor=3  # Number of nodes to replicate each shard to
)
```

### Querying Sharded Datasets

```python
# Perform a federated query across all nodes
results = await manager.query(
    dataset_id=dataset.dataset_id,
    query="SELECT id, text FROM dataset WHERE id > 500 LIMIT 10"
)

# For vector datasets, perform a similarity search
vector_results = await manager.vector_search(
    dataset_id=dataset.dataset_id,
    query_vector=query_vector,
    top_k=10
)
```

## Node Architecture

The distributed system consists of nodes with different roles:

### Node Roles

- **Coordinator Node**: Manages dataset creation, sharding, and distribution
- **Worker Node**: Stores and processes dataset fragments
- **Hybrid Node**: Combines coordinator and worker capabilities
- **Client Node**: Queries data without storing it

### Node Setup

```python
# Coordinator node
coordinator = DistributedDatasetManager(
    node_id="coordinator",
    listen_addresses=["/ip4/0.0.0.0/tcp/0"],
    bootstrap_peers=["/ip4/104.131.131.82/tcp/4001/p2p/QmaCp..."],
    role=NodeRole.COORDINATOR
)

# Worker node
worker = DistributedDatasetManager(
    node_id="worker-1",
    listen_addresses=["/ip4/0.0.0.0/tcp/0"],
    bootstrap_peers=["/ip4/127.0.0.1/tcp/4001/p2p/QmCoord..."],
    role=NodeRole.WORKER
)

# Hybrid node
hybrid = DistributedDatasetManager(
    node_id="hybrid-1",
    listen_addresses=["/ip4/0.0.0.0/tcp/0"],
    bootstrap_peers=["/ip4/127.0.0.1/tcp/4001/p2p/QmCoord..."],
    role=NodeRole.HYBRID
)

# Client node
client = DistributedDatasetManager(
    node_id="client-1",
    bootstrap_peers=["/ip4/127.0.0.1/tcp/4001/p2p/QmCoord..."],
    role=NodeRole.CLIENT
)
```

## Peer-to-Peer Communication

Communication between nodes is handled through the libp2p protocol.

### Protocols

The distributed system uses several specialized protocols:

- **Dataset Metadata Protocol**: Synchronizes dataset definitions
- **Shard Transfer Protocol**: Transfers dataset shards between nodes
- **Query Protocol**: Executes queries across nodes
- **Health Protocol**: Monitors node health and status

### Node Discovery

Nodes discover each other through:

- Bootstrap peers
- mDNS (local networks)
- Distributed Hash Table (DHT)

```python
# Get the list of connected peers
peers = await manager.get_connected_peers()
print(f"Connected to {len(peers)} peers: {peers}")

# Discover peers providing a specific dataset
dataset_providers = await manager.find_dataset_providers(dataset_id)
print(f"Found {len(dataset_providers)} providers for dataset {dataset_id}")
```

## Dataset Distribution

Datasets are distributed using consistent hashing and intelligent placement.

### Shard Placement

```python
# Customize shard placement strategy
shards = await manager.shard_dataset(
    dataset_id=dataset.dataset_id,
    data=df,
    format="parquet",
    shard_size=100,
    replication_factor=3,
    placement_strategy="balanced_load",  # Balances shards considering node load
    node_preferences=[
        {"node_id": "worker-1", "preference": 0.8},
        {"node_id": "worker-2", "preference": 0.5}
    ]
)
```

### Rebalancing

```python
# Rebalance shards when nodes join or leave
rebalance_results = await manager.rebalance_shards(
    dataset_id=dataset.dataset_id,
    target_replication=3,
    load_balanced=True
)
print(f"Rebalanced {rebalance_results['total_shards_rebalanced']} shards")
```

## Federated Search

Federated search enables querying across all nodes containing dataset shards.

### Basic Queries

```python
# SQL-like query across all nodes
results = await manager.query(
    dataset_id=dataset.dataset_id,
    query="SELECT * FROM dataset WHERE column = 'value'"
)
```

### Vector Similarity Search

```python
# Vector search across all nodes
results = await manager.vector_search(
    dataset_id=dataset.dataset_id,
    query_vector=query_vector,
    top_k=10,
    similarity_threshold=0.7
)
```

### Knowledge Graph Queries

```python
# GraphRAG query across distributed knowledge graphs
results = await manager.graph_query(
    dataset_id=dataset.dataset_id,
    query_text="How does IPFS work?",
    query_vector=query_vector,
    max_hops=2,
    top_k=5
)
```

## Resilient Operations

The distributed system includes robust resilience features for handling failures.

### Retry Logic

```python
from ipfs_datasets_py.resilient_operations import resilient

# Resilient operation with automatic retry
@resilient(max_retries=3, backoff_factor=1.5)
async def fetch_dataset_shard(shard_id, node_id):
    # Attempt to fetch the shard
    return await manager.get_shard(shard_id, node_id)

# Use the resilient function
shard = await fetch_dataset_shard("shard-123", "worker-1")
```

### Circuit Breaker

```python
from ipfs_datasets_py.resilient_operations import CircuitBreaker

# Create a circuit breaker
breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60,
    fallback_function=get_shard_from_fallback
)

# Use the circuit breaker
with breaker:
    shard = await manager.get_shard("shard-123", "worker-1")
```

### Checkpointing

```python
# Execute a long-running operation with checkpointing
result = await manager.execute_with_checkpoints(
    operation_func=process_large_dataset,
    checkpoint_interval=1000,  # Checkpoint every 1000 records
    checkpoint_path="checkpoints/dataset-processing.json"
)

# Resume an operation from a checkpoint
resumed_result = await manager.resume_from_checkpoint(
    operation_func=process_large_dataset,
    checkpoint_path="checkpoints/dataset-processing.json"
)
```

## Node Health Monitoring

The distributed system includes comprehensive health monitoring.

### Health Checks

```python
# Get health status of a specific node
node_health = await manager.get_node_health("worker-1")
print(f"Node status: {node_health['status']}")
print(f"CPU usage: {node_health['cpu_usage']}%")
print(f"Memory usage: {node_health['memory_usage']}%")
print(f"Disk usage: {node_health['disk_usage']}%")
print(f"Network usage: {node_health['network_usage']} KB/s")

# Get health status of all nodes
all_node_health = await manager.get_all_nodes_health()
for node_id, health in all_node_health.items():
    print(f"Node {node_id}: {health['status']}")
```

### Performance Metrics

```python
# Get performance metrics
metrics = await manager.get_performance_metrics(
    node_id="worker-1",
    start_time=start_time,
    end_time=end_time,
    metrics=["cpu", "memory", "disk", "network", "operations"]
)

# Analyze performance trends
trends = manager.analyze_performance_trends(metrics)
print(f"Performance trend: {trends['trend']}")
```

## Advanced Features

### Specialized Node Roles

Nodes can be configured with specialized capabilities:

```python
# Vector index node
vector_node = DistributedDatasetManager(
    node_id="vector-node-1",
    role=NodeRole.WORKER,
    capabilities=["vector_search", "high_memory"]
)

# Knowledge graph node
kg_node = DistributedDatasetManager(
    node_id="kg-node-1",
    role=NodeRole.WORKER,
    capabilities=["graph_processing", "high_cpu"]
)
```

### Custom Protocols

You can extend the system with custom protocols:

```python
from ipfs_datasets_py.libp2p_kit import Protocol

# Define a custom protocol
class CustomAnalyticsProtocol(Protocol):
    protocol_id = "/ipfs-datasets/analytics/1.0.0"
    
    async def handle_message(self, stream, message):
        # Process the analytics request
        result = process_analytics(message.data)
        await stream.write(encode_response(result))

# Register the protocol
manager.register_protocol(CustomAnalyticsProtocol())
```

### Geographically Distributed Datasets

For globally distributed teams, you can optimize data placement:

```python
# Configure geographical preferences
geo_config = {
    "regions": {
        "us-east": ["node-1", "node-2"],
        "eu-west": ["node-3", "node-4"],
        "asia-east": ["node-5", "node-6"]
    },
    "replication_policy": {
        "min_regions": 2,
        "default_region_replicas": 2
    }
}

# Distribute with geographical awareness
shards = await manager.shard_dataset(
    dataset_id=dataset.dataset_id,
    data=df,
    format="parquet",
    shard_size=100,
    geo_config=geo_config
)
```

## Configuration

Configure the distributed features through the configuration system.

### Configuration Options

```toml
[distributed]
# Node configuration
node_id = "node-1"
role = "hybrid"  # coordinator, worker, hybrid, or client
listen_addresses = ["/ip4/0.0.0.0/tcp/0"]
bootstrap_peers = ["/ip4/104.131.131.82/tcp/4001/p2p/QmaCp..."]

# Capabilities
capabilities = ["vector_search", "high_memory", "graph_processing"]

# Dataset sharding
default_shard_size = 1000
default_replication_factor = 3
use_consistent_hashing = true

# Resilience settings
max_retries = 5
backoff_factor = 2.0
circuit_breaker_threshold = 5
circuit_breaker_timeout = 60

# Health monitoring
health_check_interval = 60  # seconds
collect_metrics = true
metrics_retention_days = 30

# Performance
max_concurrent_transfers = 10
max_concurrent_queries = 5
prefetch_shards = true
```

### Programmatic Configuration

```python
from ipfs_datasets_py.libp2p_kit import DistributedConfig

# Create a configuration
config = DistributedConfig(
    node_id="node-1",
    role="hybrid",
    listen_addresses=["/ip4/0.0.0.0/tcp/0"],
    bootstrap_peers=["/ip4/104.131.131.82/tcp/4001/p2p/QmaCp..."],
    capabilities=["vector_search", "high_memory"]
)

# Initialize with the configuration
manager = DistributedDatasetManager(config=config)
```

## Best Practices

### Dataset Design

1. **Appropriate Shard Size**: Choose shard sizes based on data characteristics and node capabilities
2. **Logical Sharding**: Shard by logical boundaries when possible (e.g., by date for time-series data)
3. **Consider Access Patterns**: Optimize sharding for common query patterns

### Network Planning

1. **Bootstrap Nodes**: Maintain stable bootstrap nodes for network discovery
2. **Geographic Distribution**: Place nodes strategically for global teams
3. **Bandwidth Planning**: Ensure sufficient bandwidth for shard transfers

### Resilience Planning

1. **Appropriate Replication**: Set replication factor based on criticality
2. **Regular Health Checks**: Monitor node health and perform preventive maintenance
3. **Fallback Strategies**: Implement graceful degradation when nodes fail

### Performance Optimization

1. **Resource Allocation**: Allocate specialized nodes for resource-intensive operations
2. **Query Planning**: Optimize query execution across nodes
3. **Caching Strategy**: Implement appropriate caching for frequently accessed data

### Monitoring

1. **Comprehensive Metrics**: Collect detailed metrics on all nodes
2. **Trend Analysis**: Analyze performance trends to identify issues early
3. **Alerting**: Set up alerts for critical health issues

By following these guidelines and leveraging the distributed features of IPFS Datasets Python, you can build robust, scalable data processing systems that operate efficiently across multiple nodes.