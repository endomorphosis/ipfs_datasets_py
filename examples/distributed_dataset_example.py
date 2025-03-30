#!/usr/bin/env python3
"""
Example of using the libp2p_kit module for distributed dataset management.

This example demonstrates:
1. Setting up a distributed dataset environment
2. Creating and sharding a dataset
3. Distributing shards across nodes
4. Performing federated search

Requirements:
- py-libp2p (install with: pip install py-libp2p)
- numpy
"""

import os
import sys
import time
import asyncio
import argparse
import numpy as np
from typing import Dict, List, Any, Optional

# Add the parent directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ipfs_datasets_py.libp2p_kit import (
    DistributedDatasetManager,
    NodeRole,
    LibP2PNotAvailableError
)


def setup_argparse():
    """Set up command-line arguments."""
    parser = argparse.ArgumentParser(description='Distributed Dataset Example')
    parser.add_argument(
        '--role',
        choices=['coordinator', 'worker', 'hybrid', 'client'],
        default='hybrid',
        help='Role of this node (default: hybrid)'
    )
    parser.add_argument(
        '--storage',
        default='./data',
        help='Storage directory (default: ./data)'
    )
    parser.add_argument(
        '--listen',
        default='/ip4/0.0.0.0/tcp/0',
        help='Listen address (default: /ip4/0.0.0.0/tcp/0)'
    )
    parser.add_argument(
        '--bootstrap',
        action='append',
        help='Bootstrap peer address(es)'
    )
    parser.add_argument(
        '--create-dataset',
        action='store_true',
        help='Create a new dataset'
    )
    parser.add_argument(
        '--search',
        action='store_true',
        help='Perform a search'
    )
    return parser


async def create_dataset_example(manager):
    """Create and distribute a dataset."""
    print("Creating a new distributed dataset...")
    
    # Create the dataset
    dataset = manager.create_dataset(
        name="Example Vector Dataset",
        description="An example vector dataset created with libp2p_kit",
        schema={
            "id": "string",
            "text": "string",
            "vector": "float32[]"
        },
        vector_dimensions=128,
        tags=["example", "vector", "distributed"]
    )
    
    print(f"Created dataset: {dataset.name}")
    print(f"Dataset ID: {dataset.dataset_id}")
    
    # Create sample data (in a real scenario, this would be loaded from a file)
    print("Creating sample data...")
    sample_size = 100
    sample_data = []
    
    for i in range(sample_size):
        sample_data.append({
            "id": f"sample-{i}",
            "text": f"This is sample document {i}",
            "vector": np.random.rand(128).tolist()  # Random vector
        })
    
    # In a real implementation, we would store this data in a Parquet file
    # and then shard it across the network
    print("Sharding dataset (mock implementation)...")
    
    # Mock implementation of sharding
    shard_size = 20
    num_shards = (sample_size + shard_size - 1) // shard_size
    
    for i in range(num_shards):
        start_idx = i * shard_size
        end_idx = min(start_idx + shard_size, sample_size)
        shard_data = sample_data[start_idx:end_idx]
        
        # In a real implementation, we would store this shard in IPFS
        # and get a CID for it. For this example, we'll use a mock CID.
        mock_cid = f"QmExampleCID{i}"
        
        # Create the shard in the dataset
        shard = manager.shard_manager.create_shard(
            dataset_id=dataset.dataset_id,
            data=None,  # In a real implementation, this would be the actual data
            cid=mock_cid,
            record_count=len(shard_data),
            format="parquet"
        )
        
        print(f"Created shard {i+1}/{num_shards}: {shard.shard_id}")
    
    # Print dataset information
    print("\nDataset Information:")
    print(f"Total records: {dataset.total_records}")
    print(f"Total shards: {dataset.shard_count}")
    
    return dataset


async def search_example(manager, dataset_id=None):
    """Perform a federated search."""
    # Get available datasets
    status = await manager.get_network_status()
    
    if not dataset_id:
        if not status["datasets"]:
            print("No datasets available. Create a dataset first.")
            return
        
        print("\nAvailable Datasets:")
        for i, dataset in enumerate(status["datasets"]):
            print(f"{i+1}. {dataset['name']} (ID: {dataset['dataset_id']})")
        
        dataset_id = status["datasets"][0]["dataset_id"]
        print(f"\nUsing dataset: {dataset_id}")
    
    # Create a random query vector
    vector_dimensions = 128  # This should match the dataset dimensions
    query_vector = np.random.rand(vector_dimensions)
    
    print(f"\nPerforming vector search on dataset {dataset_id}...")
    print(f"Query vector dimensions: {vector_dimensions}")
    
    # In a real implementation, this would perform a federated search
    # across all nodes hosting shards of this dataset
    results = await manager.vector_search(
        dataset_id=dataset_id,
        query_vector=query_vector,
        top_k=5
    )
    
    print("\nSearch Results:")
    if "results" in results and results["results"]:
        for i, result in enumerate(results["results"]):
            print(f"{i+1}. ID: {result.get('id', 'unknown')}")
            print(f"   Distance: {result.get('distance', 'unknown')}")
            
            # Print metadata if available
            if "metadata" in result:
                text = result["metadata"].get("text", "No text available")
                print(f"   Text: {text[:50]}..." if len(text) > 50 else f"   Text: {text}")
            
            print()
    else:
        print("No results found or mock implementation returned empty results.")
    
    print(f"Query executed against {len(results.get('nodes_queried', []))} nodes")


async def main():
    """Main function."""
    parser = setup_argparse()
    args = parser.parse_args()
    
    try:
        print("Initializing distributed dataset manager...")
        
        role_map = {
            "coordinator": NodeRole.COORDINATOR,
            "worker": NodeRole.WORKER,
            "hybrid": NodeRole.HYBRID,
            "client": NodeRole.CLIENT
        }
        
        manager = DistributedDatasetManager(
            storage_dir=args.storage,
            listen_addresses=[args.listen],
            bootstrap_peers=args.bootstrap,
            role=role_map[args.role],
            auto_start=True
        )
        
        print(f"Node initialized with ID: {manager.node.node_id}")
        print(f"Role: {manager.node.role.value}")
        
        # Get initial network status
        status = await manager.get_network_status()
        print(f"Connected to {status['peer_count']} peers")
        print(f"Managing {status['dataset_count']} datasets with {status['shard_count']} shards")
        
        # Create dataset if requested
        dataset_id = None
        if args.create_dataset:
            dataset = await create_dataset_example(manager)
            dataset_id = dataset.dataset_id
        
        # Perform search if requested
        if args.search:
            await search_example(manager, dataset_id)
        
        # If neither operation was requested, show help
        if not (args.create_dataset or args.search):
            print("\nNo operation specified. Use --create-dataset or --search.")
            parser.print_help()
        
        # Keep the node running for a bit to allow for network operations
        print("\nNode is running. Press Ctrl+C to exit...")
        while True:
            await asyncio.sleep(1)
    
    except LibP2PNotAvailableError:
        print("Error: py-libp2p is not installed.")
        print("Install it with: pip install py-libp2p")
        return 1
    
    except KeyboardInterrupt:
        print("\nShutting down...")
    
    finally:
        if 'manager' in locals():
            manager.stop()
    
    return 0


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")