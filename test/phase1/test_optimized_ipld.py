import os
import sys
import unittest
import tempfile
import shutil
import json
import time
import random
import numpy as np
from typing import Dict, List, Tuple, Any

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the module to test
from ipfs_datasets_py.ipld.optimized_codec import (
    OptimizedEncoder, OptimizedDecoder, BatchProcessor,
    create_batch_processor, optimize_node_structure,
    LRUCache, PerformanceStats
)
from ipfs_datasets_py.ipld.dag_pb import PBNode, PBLink
from ipfs_datasets_py.ipld.storage import IPLDStorage


class TestOptimizedIPLD(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test"""
        self.temp_dir = tempfile.mkdtemp()
        self.storage = IPLDStorage(base_dir=self.temp_dir)
        self.test_data = [b"test data 1", b"test data 2", b"test data 3"]
        
    def tearDown(self):
        """Clean up test fixtures after each test"""
        shutil.rmtree(self.temp_dir)
        
    def test_optimized_encoder(self):
        """Test basic functionality of OptimizedEncoder"""
        encoder = OptimizedEncoder()
        
        # Create a simple node
        node = PBNode(data=b"test data")
        
        # Encode it
        encoded_data, cid = encoder.encode_node(node)
        
        # Verify we got valid results
        self.assertIsNotNone(encoded_data)
        self.assertTrue(isinstance(encoded_data, bytes))
        self.assertIsNotNone(cid)
        self.assertTrue(isinstance(cid, str))
        
    def test_optimized_decoder(self):
        """Test basic functionality of OptimizedDecoder"""
        encoder = OptimizedEncoder()
        decoder = OptimizedDecoder()
        
        # Create and encode a node
        node = PBNode(data=b"test data")
        encoded_data, cid = encoder.encode_node(node)
        
        # Decode it
        decoded_node = decoder.decode_block(encoded_data, cid)
        
        # Verify the result
        self.assertIsNotNone(decoded_node)
        self.assertEqual(decoded_node.data, b"test data")
        self.assertEqual(len(decoded_node.links), 0)
        
    def test_batch_processing(self):
        """Test batch processing of multiple nodes"""
        encoder = OptimizedEncoder()
        
        # Create multiple nodes
        nodes = [PBNode(data=data) for data in self.test_data]
        
        # Encode in batch
        start_time = time.time()
        results = encoder.encode_batch(nodes)
        batch_time = time.time() - start_time
        
        # Verify results
        self.assertEqual(len(results), len(nodes))
        for encoded_data, cid in results:
            self.assertIsNotNone(encoded_data)
            self.assertIsNotNone(cid)
            
        # Now encode one by one
        start_time = time.time()
        individual_results = [encoder.encode_node(node) for node in nodes]
        individual_time = time.time() - start_time
        
        # Compare results
        for (batch_data, batch_cid), (indiv_data, indiv_cid) in zip(results, individual_results):
            self.assertEqual(batch_data, indiv_data)
            self.assertEqual(batch_cid, indiv_cid)
            
        # Batch should be faster, but might not be for very small batches in tests
        # Just check that batch processing works correctly
        
    def test_ipld_storage_batch_methods(self):
        """Test batch methods added to IPLDStorage"""
        # Store multiple blocks in batch
        cids = self.storage.store_batch(self.test_data)
        
        # Verify we got valid CIDs
        self.assertEqual(len(cids), len(self.test_data))
        for cid in cids:
            self.assertIsNotNone(cid)
            
        # Retrieve blocks in batch
        retrieved_data = self.storage.get_batch(cids)
        
        # Verify data integrity
        self.assertEqual(len(retrieved_data), len(self.test_data))
        for original, retrieved in zip(self.test_data, retrieved_data):
            self.assertEqual(original, retrieved)
            
        # Test JSON batch methods
        test_objects = [
            {"id": 1, "name": "Object 1"},
            {"id": 2, "name": "Object 2"},
            {"id": 3, "name": "Object 3"}
        ]
        
        # Store as JSON
        json_cids = self.storage.store_json_batch(test_objects)
        
        # Verify we got valid CIDs
        self.assertEqual(len(json_cids), len(test_objects))
        
        # Retrieve and parse JSON
        retrieved_objects = self.storage.get_json_batch(json_cids)
        
        # Verify data integrity
        self.assertEqual(len(retrieved_objects), len(test_objects))
        for original, retrieved in zip(test_objects, retrieved_objects):
            self.assertEqual(original, retrieved)
            
    def test_car_streaming(self):
        """Test streaming export/import of CAR files"""
        # Skip if ipld_car not available
        if not hasattr(self.storage, 'HAVE_IPLD_CAR') or not self.storage.HAVE_IPLD_CAR:
            self.skipTest("ipld_car module not available")
            
        # Store test data
        cids = self.storage.store_batch(self.test_data)
        
        # Export to CAR using streaming
        car_path = os.path.join(self.temp_dir, "streaming_test.car")
        with open(car_path, 'wb') as f:
            root_cid = self.storage.export_to_car_stream(cids, f)
        
        # Verify file was created
        self.assertTrue(os.path.exists(car_path))
        
        # Create a new storage instance
        new_storage = IPLDStorage(base_dir=os.path.join(self.temp_dir, "new_storage"))
        
        # Import from CAR using streaming
        with open(car_path, 'rb') as f:
            imported_cids = new_storage.import_from_car_stream(f)
        
        # Verify CIDs were imported
        self.assertTrue(len(imported_cids) > 0)
        
        # Retrieve data
        retrieved_data = new_storage.get_batch(cids)
        
        # Verify data integrity
        for original, retrieved in zip(self.test_data, retrieved_data):
            self.assertEqual(original, retrieved)
            
    def test_node_optimization(self):
        """Test optimization of DAG-PB node structures"""
        # Create a node with duplicate links and unordered links
        links = [
            PBLink(name="b", cid="bafyqqqqqb"),
            PBLink(name="a", cid="bafyqqqqqa"),
            PBLink(name="c", cid="bafyqqqqqc"),
            PBLink(name="b", cid="bafyqqqqqb"),  # duplicate
        ]
        node = PBNode(data=json.dumps({"test": "data", "with": "spaces"}).encode(), links=links)
        
        # Optimize the node
        optimized = optimize_node_structure(node)
        
        # Verify optimization results
        self.assertEqual(len(optimized.links), 3)  # Removed duplicate
        self.assertEqual(optimized.links[0].name, "a")  # Sorted by name
        self.assertEqual(optimized.links[1].name, "b")
        self.assertEqual(optimized.links[2].name, "c")
        
        # Verify data was compacted
        self.assertEqual(json.loads(optimized.data), {"test": "data", "with": "spaces"})
        self.assertLess(len(optimized.data), len(node.data))  # Should be more compact
        
    def test_performance_stats(self):
        """Test performance statistics collection"""
        stats = PerformanceStats()
        
        # Record some operations
        stats.record_encode(0.01, 1000, 1)
        stats.record_encode(0.02, 2000, 1)
        stats.record_decode(0.015, 1500, 1)
        stats.record_cache_access(True)
        stats.record_cache_access(False)
        
        # Get summary
        summary = stats.get_summary()
        
        # Verify stats
        self.assertEqual(summary["encode_operations"], 2)
        self.assertEqual(summary["decode_operations"], 1)
        self.assertEqual(summary["total_operations"], 3)
        self.assertEqual(summary["total_bytes_processed"], 4500)
        self.assertEqual(summary["cache_hit_rate"], 0.5)
        
    def test_lru_cache(self):
        """Test LRU cache behavior"""
        cache = LRUCache(max_size=2)
        
        # Add two items
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        # Verify both are in cache
        self.assertEqual(cache.get("key1"), "value1")
        self.assertEqual(cache.get("key2"), "value2")
        
        # Add third item, should evict first item
        cache.put("key3", "value3")
        
        # Verify state
        self.assertIsNone(cache.get("key1"))  # Evicted
        self.assertEqual(cache.get("key2"), "value2")
        self.assertEqual(cache.get("key3"), "value3")
        
        # Access key2, making key3 the least recently used
        _ = cache.get("key2")
        
        # Add fourth item, should evict key3
        cache.put("key4", "value4")
        
        # Verify state
        self.assertIsNone(cache.get("key1"))  # Evicted earlier
        self.assertEqual(cache.get("key2"), "value2")
        self.assertIsNone(cache.get("key3"))  # Evicted
        self.assertEqual(cache.get("key4"), "value4")
        
    def test_cached_encoding(self):
        """Test that caching improves performance for repeated encodings"""
        data = b"test data for caching"
        node = PBNode(data=data)
        
        # Encoder with cache
        cached_encoder = OptimizedEncoder(use_cache=True)
        
        # Encoder without cache
        uncached_encoder = OptimizedEncoder(use_cache=False)
        
        # Warm up cached encoder
        _, _ = cached_encoder.encode_node(node)
        
        # Time multiple encodings with cache
        start_time = time.time()
        for _ in range(100):
            _, _ = cached_encoder.encode_node(node)
        cached_time = time.time() - start_time
        
        # Time multiple encodings without cache
        start_time = time.time()
        for _ in range(100):
            _, _ = uncached_encoder.encode_node(node)
        uncached_time = time.time() - start_time
        
        # Cached should be faster
        self.assertLess(cached_time, uncached_time)
        
        # Check stats
        if cached_encoder.stats:
            self.assertGreater(cached_encoder.stats.cache_hits, 0)
        
    def test_batch_processor_factory(self):
        """Test the batch processor factory function"""
        # Create optimized processor
        processor = create_batch_processor(batch_size=50, optimize_memory=True)
        
        # Verify configuration
        self.assertEqual(processor.batch_size, 50)
        self.assertTrue(hasattr(processor, 'encoder'))
        self.assertTrue(hasattr(processor, 'decoder'))
        
    def test_large_batch_processing(self):
        """Test processing of larger batches"""
        # Create random data blocks
        large_batch_size = 20  # Not too large for unit tests, but enough to test batching
        random_data = []
        for _ in range(large_batch_size):
            size = random.randint(100, 1000)
            data = bytes(random.getrandbits(8) for _ in range(size))
            random_data.append(data)
        
        # Process using batch methods
        cids = self.storage.store_batch(random_data)
        
        # Verify all blocks were stored
        self.assertEqual(len(cids), large_batch_size)
        
        # Retrieve and verify data
        retrieved = self.storage.get_batch(cids)
        
        for original, retrieved_data in zip(random_data, retrieved):
            self.assertEqual(original, retrieved_data)


if __name__ == '__main__':
    unittest.main()