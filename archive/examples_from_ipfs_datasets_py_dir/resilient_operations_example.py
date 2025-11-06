#!/usr/bin/env python3
"""
Example script demonstrating the resilient operations capabilities of IPFS Datasets Python.

This script shows how to:
1. Create a resilience manager for distributed operations
2. Handle node failures gracefully during dataset operations
3. Use circuit breakers to prevent cascading failures
4. Implement automatic retries with exponential backoff
5. Perform health checks and monitor connected nodes
6. Balance dataset shards for improved resilience
7. Create checkpoints for long-running operations
"""

import os
import sys
import time
import asyncio
import random
import logging
import json
from typing import Dict, List, Any, Optional

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(parent_dir)

# Import components from the library
from ipfs_datasets_py.libp2p_kit import (
    LibP2PNode,
    NodeRole,
    NetworkProtocol,
    DatasetShardManager,
    DistributedDatasetManager,
    ShardMetadata,
    DatasetMetadata
)
from ipfs_datasets_py.resilient_operations import (
    ResilienceManager,
    HealthStatus,
    OperationStatus,
    CircuitBreaker,
    RetryConfig,
    resilient
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def resilient_operations_example():
    """Example of resilient operations with IPFS Datasets."""
    print("\n=== Resilient Operations Example ===\n")

    # Create temporary directories for nodes
    base_dir = os.path.join(os.getcwd(), "temp_resilient_example")
    coordinator_dir = os.path.join(base_dir, "coordinator")
    worker1_dir = os.path.join(base_dir, "worker1")
    worker2_dir = os.path.join(base_dir, "worker2")
    worker3_dir = os.path.join(base_dir, "worker3")

    # Create directories
    os.makedirs(coordinator_dir, exist_ok=True)
    os.makedirs(worker1_dir, exist_ok=True)
    os.makedirs(worker2_dir, exist_ok=True)
    os.makedirs(worker3_dir, exist_ok=True)

    # Create nodes
    print("Creating nodes...")
    coordinator_node = await create_node(
        node_type=NodeRole.COORDINATOR,
        storage_dir=coordinator_dir,
        port=9701
    )

    worker1_node = await create_node(
        node_type=NodeRole.WORKER,
        storage_dir=worker1_dir,
        port=9702,
        bootstrap_peers=[f"/ip4/127.0.0.1/tcp/9701/p2p/{coordinator_node.node_id}"]
    )

    worker2_node = await create_node(
        node_type=NodeRole.WORKER,
        storage_dir=worker2_dir,
        port=9703,
        bootstrap_peers=[f"/ip4/127.0.0.1/tcp/9701/p2p/{coordinator_node.node_id}"]
    )

    worker3_node = await create_node(
        node_type=NodeRole.WORKER,
        storage_dir=worker3_dir,
        port=9704,
        bootstrap_peers=[f"/ip4/127.0.0.1/tcp/9701/p2p/{coordinator_node.node_id}"]
    )

    print(f"Coordinator Node ID: {coordinator_node.node_id}")
    print(f"Worker 1 Node ID: {worker1_node.node_id}")
    print(f"Worker 2 Node ID: {worker2_node.node_id}")
    print(f"Worker 3 Node ID: {worker3_node.node_id}")

    # Initialize resilience managers
    print("\nInitializing resilience managers...")
    coordinator_resilience = ResilienceManager(
        node=coordinator_node,
        storage_dir=os.path.join(coordinator_dir, "resilience"),
        health_check_interval_sec=10
    )

    worker1_resilience = ResilienceManager(
        node=worker1_node,
        storage_dir=os.path.join(worker1_dir, "resilience"),
        health_check_interval_sec=10
    )

    worker2_resilience = ResilienceManager(
        node=worker2_node,
        storage_dir=os.path.join(worker2_dir, "resilience"),
        health_check_interval_sec=10
    )

    worker3_resilience = ResilienceManager(
        node=worker3_node,
        storage_dir=os.path.join(worker3_dir, "resilience"),
        health_check_interval_sec=10
    )

    # Connect the nodes
    print("\nConnecting nodes and discovering peers...")
    await connect_nodes(coordinator_node, [worker1_node, worker2_node, worker3_node])

    # Wait for peer discovery to complete
    await asyncio.sleep(2)

    # Create distributed dataset manager
    print("\nCreating distributed dataset manager...")
    dataset_manager = DistributedDatasetManager(
        node=coordinator_node,
        storage_dir=coordinator_dir
    )

    # Create and shard a simple dataset
    print("\nCreating and sharding dataset...")
    dataset_id = await create_example_dataset(dataset_manager)

    # Get initial node health
    print("\nInitial node health status:")
    healthy_nodes = coordinator_resilience.get_healthy_nodes()
    print(f"Healthy nodes: {len(healthy_nodes)}/{3}")

    # Wait for health checks to complete
    print("\nWaiting for health checks to complete...")
    await asyncio.sleep(5)

    # Show updated node health
    print("\nUpdated node health status:")
    for node_id, health in coordinator_resilience.get_all_node_health().items():
        print(f"Node {node_id}: {health.status.value}, " +
              f"Availability: {health.availability_score:.2f}, " +
              f"Avg Response: {health.avg_response_time_ms:.2f}ms")

    # Demonstrate resilient shard transfer
    print("\nDemonstrating resilient shard transfer...")
    all_shards = coordinator_node.shard_manager.get_all_shards()
    if all_shards:
        # Select a shard to transfer
        shard_id = list(all_shards.keys())[0]
        print(f"Selected shard for transfer: {shard_id}")

        # Transfer to all workers with resilience
        result = await coordinator_resilience.resilient_shard_transfer(
            shard_id=shard_id,
            target_node_ids=[worker1_node.node_id, worker2_node.node_id, worker3_node.node_id]
        )

        print(f"Transfer status: {result.status.value}")
        print(f"Successful transfers: {result.success_count}")
        print(f"Failed transfers: {result.failure_count}")
        if result.failed_nodes:
            print("Failed nodes:")
            for node_id, error in result.failed_nodes.items():
                print(f"  - {node_id}: {error}")

    # Simulate a node failure
    print("\nSimulating node failure...")
    print(f"Marking {worker2_node.node_id} as unhealthy")
    worker2_health = coordinator_resilience.get_node_health(worker2_node.node_id)
    if worker2_health:
        worker2_health.status = HealthStatus.UNHEALTHY
        worker2_health.failure_count = 5
        worker2_health.availability_score = 0.0

    # Demonstrate node selection based on health
    print("\nSelecting best nodes for operation:")
    best_nodes = coordinator_resilience.select_best_nodes(count=2)
    print(f"Selected nodes: {best_nodes}")

    # Demonstrate resilient rebalancing
    print("\nRebalancing shards with resilience...")
    rebalance_result = await coordinator_resilience.resilient_rebalance_shards(
        dataset_id=dataset_id,
        target_replication=2,
        use_healthy_nodes_only=True
    )

    print(f"Rebalance status: {rebalance_result.status.value}")
    print(f"Successful operations: {rebalance_result.success_count}")
    print(f"Failed operations: {rebalance_result.failure_count}")

    # Demonstrate the circuit breaker pattern
    print("\nDemonstrating circuit breaker pattern...")
    circuit_breaker = coordinator_resilience.get_circuit_breaker("node_connection")
    if circuit_breaker:
        print(f"Initial state: {circuit_breaker.state}")

        # Simulate multiple failures
        for i in range(circuit_breaker.failure_threshold + 1):
            try:
                circuit_breaker.execute(lambda: simulate_error())
            except Exception as e:
                print(f"Attempt {i+1} failed: {str(e)}")

        print(f"After failures: {circuit_breaker.state}")

        # Try operation with open circuit
        try:
            circuit_breaker.execute(lambda: print("This shouldn't execute"))
        except Exception as e:
            print(f"Circuit breaker prevented execution: {str(e)}")

        # Reset the circuit
        print("Manually resetting circuit...")
        circuit_breaker.reset()
        print(f"After reset: {circuit_breaker.state}")

    # Demonstrate checkpointing for long operations
    print("\nDemonstrating checkpointing for long operations...")
    operation = coordinator_resilience.create_operation("long_process")

    # Create a checkpoint
    checkpoint = coordinator_resilience.create_checkpoint(
        operation_id=operation.operation_id,
        completed_items=["item1", "item2"],
        pending_items=["item3", "item4", "item5"],
        metadata={"progress": 40, "started_at": time.time()}
    )
    print(f"Created checkpoint: {checkpoint.checkpoint_id}")

    # Retrieve the checkpoint
    loaded_checkpoint = coordinator_resilience.get_latest_checkpoint(operation.operation_id)
    if loaded_checkpoint:
        print(f"Retrieved checkpoint with {len(loaded_checkpoint.completed_items)} completed items")
        print(f"Pending items: {loaded_checkpoint.pending_items}")

    # Demonstrate the resilient decorator
    print("\nDemonstrating resilient function decorator...")

    @resilient(max_retries=3, initial_backoff_ms=100)
    def example_resilient_function(fail_count=2):
        nonlocal attempts
        attempts += 1
        if attempts <= fail_count:
            raise ConnectionError(f"Simulated error (attempt {attempts})")
        return "Success!"

    attempts = 0
    result = example_resilient_function()
    print(f"Function result after {attempts} attempts: {result}")

    # Clean up
    print("\nCleaning up...")
    coordinator_resilience.shutdown()
    worker1_resilience.shutdown()
    worker2_resilience.shutdown()
    worker3_resilience.shutdown()

    print("\nResilience features demonstrated successfully!")


async def create_node(
    node_type: NodeRole,
    storage_dir: str,
    port: int = 0,
    bootstrap_peers: List[str] = None
) -> LibP2PNode:
    """Create a node of the specified type."""
    # Create a new node
    node = LibP2PNode(
        role=node_type,
        storage_dir=storage_dir,
        listen_port=port,
        bootstrap_peers=bootstrap_peers or []
    )

    # Initialize the node
    await node.start()

    return node


async def connect_nodes(coordinator: LibP2PNode, workers: List[LibP2PNode]):
    """Connect coordinator to worker nodes."""
    for worker in workers:
        try:
            await coordinator.connect_to_peer(worker.node_id)
            logger.info(f"Connected to worker {worker.node_id}")
        except Exception as e:
            logger.error(f"Failed to connect to worker {worker.node_id}: {str(e)}")


async def create_example_dataset(manager: DistributedDatasetManager):
    """Create a simple example dataset."""
    # Dataset parameters
    dataset_name = "resilient_example"
    num_records = 100
    shard_size = 20  # Records per shard

    # Create sample data
    data = []
    for i in range(num_records):
        data.append({
            "id": i,
            "title": f"Item {i}",
            "value": random.random() * 100,
            "category": random.choice(["A", "B", "C"]),
            "vector": [random.random() for _ in range(10)]
        })

    # Create dataset
    dataset_id = await manager.create_dataset(
        name=dataset_name,
        description="Example dataset for resilient operations",
        metadata={"source": "synthetic", "type": "example"}
    )

    # Shard and distribute
    await manager.shard_dataset(
        dataset_id=dataset_id,
        data=data,
        shard_size=shard_size,
        replication_factor=1  # Start with 1, we'll use resilient_rebalance later
    )

    return dataset_id


def simulate_error():
    """Simulate an error for testing circuit breakers."""
    raise ConnectionError("Simulated connection error")


if __name__ == "__main__":
    # Run the example
    asyncio.run(resilient_operations_example())
