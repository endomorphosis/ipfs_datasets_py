#!/usr/bin/env python3
"""
Example demonstrating support for sharded datasets across multiple IPFS nodes.

This example demonstrates:
1. Creating a distributed dataset
2. Sharding and distributing the dataset across nodes
3. Querying the dataset from different nodes
4. Synchronizing dataset metadata between nodes
5. Rebalancing shards to ensure proper distribution
"""

import os
import time
import anyio
import argparse
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional

from ipfs_datasets_py.p2p_networking.libp2p_kit import (
    DistributedDatasetManager,
    NodeRole,
    LIBP2P_AVAILABLE
)


def create_sample_dataset(size=1000):
    """Create a sample dataset for testing."""
    return pd.DataFrame({
        "id": list(range(size)),
        "text": [f"Sample text {i}" for i in range(size)],
        "vector": [np.random.rand(128).tolist() for _ in range(size)]
    })


async def run_coordinator(args):
    """Run a coordinator node that creates and distributes the dataset."""
    print(f"Starting coordinator node with ID {args.node_id}...")

    # Create the distributed dataset manager
    manager = DistributedDatasetManager(
        storage_dir=args.storage_dir,
        node_id=args.node_id,
        listen_addresses=["/ip4/0.0.0.0/tcp/0"],
        bootstrap_peers=args.bootstrap_peers,
        role=NodeRole.COORDINATOR
    )

    # Wait for node to start
    time.sleep(2)

    print("Creating dataset...")
    dataset = manager.create_dataset(
        name="Distributed Test Dataset",
        description="Example dataset distributed across multiple nodes",
        schema={"id": "integer", "text": "string", "vector": "float[]"},
        vector_dimensions=128,
        tags=["example", "test"]
    )

    print(f"Created dataset with ID: {dataset.dataset_id}")

    # Create sample data
    data = create_sample_dataset(size=args.dataset_size)
    print(f"Created sample dataset with {len(data)} records")

    # Shard and distribute the dataset
    print(f"Sharding dataset with shard size {args.shard_size}...")
    shards = await manager.shard_dataset(
        dataset_id=dataset.dataset_id,
        data=data,
        format="parquet",
        shard_size=args.shard_size,
        replication_factor=args.replication
    )

    print(f"Created {len(shards)} shards")

    # Get network status
    network_status = await manager.get_network_status()
    print("\nNetwork Status:")
    print(f"- Node ID: {network_status['node_id']}")
    print(f"- Role: {network_status['role']}")
    print(f"- Peer Count: {network_status['peer_count']}")
    print(f"- Dataset Count: {network_status['dataset_count']}")
    print(f"- Shard Count: {network_status['shard_count']}")

    # Keep the node running
    print("\nCoordinator node is running. Press Ctrl+C to exit.")
    while True:
        await anyio.sleep(10)

        # Rebalance shards every 10 seconds
        if args.rebalance:
            print("Rebalancing shards...")
            rebalance_results = await manager.rebalance_shards(
                dataset_id=dataset.dataset_id,
                target_replication=args.replication
            )
            print(f"Rebalanced {rebalance_results['total_shards_rebalanced']} shards")


async def run_worker(args):
    """Run a worker node that participates in the distributed dataset."""
    print(f"Starting worker node with ID {args.node_id}...")

    # Create the distributed dataset manager
    manager = DistributedDatasetManager(
        storage_dir=args.storage_dir,
        node_id=args.node_id,
        listen_addresses=["/ip4/0.0.0.0/tcp/0"],
        bootstrap_peers=args.bootstrap_peers,
        role=NodeRole.WORKER
    )

    # Wait for node to start
    time.sleep(2)

    # Sync with the network
    print("Synchronizing with network...")
    sync_results = await manager.sync_with_network()
    print(f"Sync results: {sync_results}")

    # Get network status
    network_status = await manager.get_network_status()
    print("\nNetwork Status:")
    print(f"- Node ID: {network_status['node_id']}")
    print(f"- Role: {network_status['role']}")
    print(f"- Peer Count: {network_status['peer_count']}")
    print(f"- Dataset Count: {network_status['dataset_count']}")
    print(f"- Shard Count: {network_status['shard_count']}")

    # Keep the node running
    print("\nWorker node is running. Press Ctrl+C to exit.")
    while True:
        await anyio.sleep(30)

        # Sync with the network periodically
        print("Synchronizing with network...")
        sync_results = await manager.sync_with_network()
        print(f"Sync results: {sync_results}")


async def run_client(args):
    """Run a client node that queries the distributed dataset."""
    print(f"Starting client node with ID {args.node_id}...")

    # Create the distributed dataset manager
    manager = DistributedDatasetManager(
        storage_dir=args.storage_dir,
        node_id=args.node_id,
        listen_addresses=["/ip4/0.0.0.0/tcp/0"],
        bootstrap_peers=args.bootstrap_peers,
        role=NodeRole.CLIENT
    )

    # Wait for node to start
    time.sleep(2)

    # Sync with the network
    print("Synchronizing with network...")
    sync_results = await manager.sync_with_network()
    print(f"Sync results: {sync_results}")

    # Get network status
    network_status = await manager.get_network_status()
    print("\nNetwork Status:")
    print(f"- Node ID: {network_status['node_id']}")
    print(f"- Role: {network_status['role']}")
    print(f"- Peer Count: {network_status['peer_count']}")
    print(f"- Dataset Count: {network_status['dataset_count']}")

    if network_status['dataset_count'] == 0:
        print("No datasets found. Waiting for datasets to be available...")
        while network_status['dataset_count'] == 0:
            await anyio.sleep(5)
            await manager.sync_with_network()
            network_status = await manager.get_network_status()

    # Get the first dataset for querying
    dataset_id = list(manager.shard_manager.datasets.keys())[0]
    dataset = manager.shard_manager.datasets[dataset_id]
    print(f"\nFound dataset: {dataset.name} ({dataset_id})")

    # Perform a query every 10 seconds
    while True:
        # Create a random query vector
        query_vector = np.random.rand(dataset.vector_dimensions)

        print(f"\nPerforming vector search on dataset {dataset.name}...")
        try:
            results = await manager.vector_search(
                dataset_id=dataset_id,
                query_vector=query_vector,
                top_k=5
            )

            print(f"Search results: Found {results['total_results']} matches")
            for i, result in enumerate(results['results'][:3]):
                print(f"Result {i+1}: {result}")

            print(f"Query executed across {len(results.get('nodes_queried', []))} nodes")
        except Exception as e:
            print(f"Error performing search: {str(e)}")

        await anyio.sleep(10)


def main():
    """Main entry point."""
    if not LIBP2P_AVAILABLE:
        print("Error: libp2p is not installed. Install it with: pip install py-libp2p")
        return

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Distributed Dataset Example")
    parser.add_argument("--role", choices=["coordinator", "worker", "client"],
                        required=True, help="Node role")
    parser.add_argument("--node-id", default=None, help="Node ID (generated if not provided)")
    parser.add_argument("--storage-dir", default="./data", help="Storage directory")
    parser.add_argument("--bootstrap-peers", nargs="+", default=[],
                        help="Bootstrap peer multiaddresses")
    parser.add_argument("--dataset-size", type=int, default=1000,
                        help="Size of the sample dataset (coordinator only)")
    parser.add_argument("--shard-size", type=int, default=100,
                        help="Records per shard (coordinator only)")
    parser.add_argument("--replication", type=int, default=3,
                        help="Replication factor (coordinator only)")
    parser.add_argument("--rebalance", action="store_true",
                        help="Enable periodic shard rebalancing (coordinator only)")

    args = parser.parse_args()

    # Create storage directory if it doesn't exist
    os.makedirs(args.storage_dir, exist_ok=True)

    # Run the appropriate node type
    if args.role == "coordinator":
        anyio.run(run_coordinator(args))
    elif args.role == "worker":
        anyio.run(run_worker(args))
    elif args.role == "client":
        anyio.run(run_client(args))


if __name__ == "__main__":
    main()
