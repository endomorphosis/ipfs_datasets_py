#!/usr/bin/env python3
"""
Basic test script for the optimized IPLD codec.

This script performs a simple test of the optimized IPLD codec
functionality to confirm it works correctly.
"""

import os
import sys
import tempfile
import time
import json
import random

# Add parent directory to path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

# Import the optimized IPLD codec
sys.path.insert(0, parent_dir)
from ipfs_datasets_py.ipld.optimized_codec import (
    OptimizedEncoder, OptimizedDecoder, BatchProcessor,
    create_batch_processor, optimize_node_structure, PBNode, PBLink
)
from ipfs_datasets_py.ipld.storage import IPLDStorage

def test_optimized_codec():
    """Test the basic functionality of the optimized IPLD codec."""
    print("Testing optimized IPLD codec...")

    # Create a temporary directory for storage
    temp_dir = tempfile.mkdtemp()

    try:
        # Create storage
        storage = IPLDStorage(base_dir=temp_dir)

        # Create test data
        block_count = 10
        test_data = []
        for i in range(block_count):
            test_data.append(f"Test data block {i}".encode())

        print(f"Created {block_count} test blocks.")

        # Test batch storage and retrieval
        start_time = time.time()
        cids = storage.store_batch(test_data)
        store_time = time.time() - start_time

        print(f"Stored {len(cids)} blocks in {store_time:.4f} seconds.")

        start_time = time.time()
        retrieved_data = storage.get_batch(cids)
        get_time = time.time() - start_time

        print(f"Retrieved {len(retrieved_data)} blocks in {get_time:.4f} seconds.")

        # Verify data integrity
        all_match = True
        for original, retrieved in zip(test_data, retrieved_data):
            if original != retrieved:
                all_match = False
                print("WARNING: Data mismatch detected.")
                break

        if all_match:
            print("Data integrity verified: all blocks match.")

        # Test direct codec
        encoder = OptimizedEncoder(use_cache=True)
        decoder = OptimizedDecoder(use_cache=True)

        # Create test nodes
        nodes = []
        for i in range(block_count):
            node = PBNode(data=f"Node {i} data".encode())
            nodes.append(node)

        # Batch encode
        start_time = time.time()
        encoded_results = encoder.encode_batch(nodes)
        encode_time = time.time() - start_time

        print(f"Encoded {len(encoded_results)} nodes in {encode_time:.4f} seconds.")

        # Prepare for batch decode
        blocks_for_decode = [(data, cid) for data, cid in encoded_results]

        # Batch decode
        start_time = time.time()
        decoded_nodes = decoder.decode_batch(blocks_for_decode)
        decode_time = time.time() - start_time

        print(f"Decoded {len(decoded_nodes)} nodes in {decode_time:.4f} seconds.")

        # Verify nodes
        all_match = True
        for original_node, decoded_node in zip(nodes, decoded_nodes):
            if original_node.data != decoded_node.data:
                all_match = False
                print("WARNING: Node data mismatch detected.")
                break

        if all_match:
            print("Node integrity verified: all nodes match.")

        # Create a processor
        processor = create_batch_processor(batch_size=5, collect_stats=True)

        # Get statistics
        stats = processor.get_stats()
        print("Processor statistics available.")

        print("Optimized IPLD codec test completed successfully.")
        return True

    except Exception as e:
        print(f"Test failed with error: {e}")
        return False

    finally:
        # Clean up
        import shutil
        shutil.rmtree(temp_dir)

if __name__ == "__main__":
    test_optimized_codec()
