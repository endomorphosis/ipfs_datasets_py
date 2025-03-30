"""
Test the streaming data loader module.

This module tests the performance optimizations for streaming data loading,
including memory-mapped access, prefetching, and caching.
"""

import os
import time
import tempfile
import unittest
import numpy as np
import json
from typing import Dict, List

# Try to import optional dependencies
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyarrow.csv as csv
    import pyarrow.json as json_pa
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False

try:
    from datasets import Dataset
    HAVE_DATASETS = True
except ImportError:
    HAVE_DATASETS = False

# Import the module to test
from ipfs_datasets_py.streaming_data_loader import (
    StreamingStats,
    StreamingCache,
    PrefetchingQueue,
    StreamingDataLoader,
    ParquetStreamingLoader,
    CSVStreamingLoader,
    JSONStreamingLoader,
    HuggingFaceStreamingLoader,
    MemoryMappedVectorLoader,
    StreamingDataset,
    load_parquet,
    load_csv,
    load_json,
    load_huggingface,
    create_memory_mapped_vectors,
    load_memory_mapped_vectors
)


class TestStreamingStats(unittest.TestCase):
    """Test StreamingStats class."""
    
    def test_stats_collection(self):
        """Test statistics collection."""
        stats = StreamingStats()
        
        # Record some batches
        stats.start_batch()
        time.sleep(0.01)
        stats.end_batch(100, 1024)
        
        stats.start_batch()
        time.sleep(0.01)
        stats.end_batch(200, 2048)
        
        # Get throughput
        throughput = stats.get_throughput()
        
        # Check that we have the expected metrics
        self.assertIn("elapsed_seconds", throughput)
        self.assertIn("records_per_second", throughput)
        self.assertIn("batches_per_second", throughput)
        self.assertIn("bytes_per_second", throughput)
        self.assertIn("total_records", throughput)
        self.assertIn("total_batches", throughput)
        self.assertIn("total_bytes", throughput)
        self.assertIn("avg_batch_time", throughput)
        self.assertIn("avg_batch_size", throughput)
        
        # Check values
        self.assertEqual(throughput["total_records"], 300)
        self.assertEqual(throughput["total_batches"], 2)
        self.assertEqual(throughput["total_bytes"], 3072)
        
        # Reset stats
        stats.reset()
        throughput = stats.get_throughput()
        self.assertEqual(throughput["total_records"], 0)
        self.assertEqual(throughput["total_batches"], 0)


class TestStreamingCache(unittest.TestCase):
    """Test StreamingCache class."""
    
    def test_cache_operations(self):
        """Test basic cache operations."""
        cache = StreamingCache(max_size_mb=1, ttl_seconds=60)
        
        # Cache some items
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        # Get items
        self.assertEqual(cache.get("key1"), "value1")
        self.assertEqual(cache.get("key2"), "value2")
        self.assertIsNone(cache.get("key3"))
        
        # Check hits and misses
        stats = cache.get_stats()
        self.assertEqual(stats["hits"], 2)
        self.assertEqual(stats["misses"], 1)
        
        # Test cache eviction (make sure we evict at least one item)
        data = b"0" * (1024 * 1024)  # 1 MB
        cache.put("big_key", data)
        
        # One of the small keys should be evicted
        self.assertTrue(cache.get("key1") is None or cache.get("key2") is None)
        
        # Clear cache
        cache.clear()
        stats = cache.get_stats()
        self.assertEqual(stats["item_count"], 0)


@unittest.skipIf(not HAVE_ARROW, "PyArrow is required for this test")
class TestParquetStreamingLoader(unittest.TestCase):
    """Test ParquetStreamingLoader class."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        # Create a temporary Parquet file
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.parquet_path = os.path.join(cls.temp_dir.name, "test.parquet")
        
        # Create a sample table
        data = {
            "id": pa.array(range(1000)),
            "value": pa.array([float(i) for i in range(1000)])
        }
        table = pa.Table.from_pydict(data)
        
        # Write to Parquet
        pq.write_table(table, cls.parquet_path)
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        cls.temp_dir.cleanup()
    
    def test_parquet_loading(self):
        """Test loading a Parquet file."""
        loader = ParquetStreamingLoader(
            parquet_path=self.parquet_path,
            batch_size=100
        )
        
        # Check metadata
        metadata = loader.get_metadata()
        self.assertEqual(metadata["num_rows"], 1000)
        
        # Iterate over batches
        batch_count = 0
        total_rows = 0
        
        for batch in loader:
            self.assertIsInstance(batch, pa.Table)
            self.assertLessEqual(len(batch), 100)
            batch_count += 1
            total_rows += len(batch)
            
        self.assertEqual(batch_count, 10)
        self.assertEqual(total_rows, 1000)
        
        # Test with prefetching
        loader = ParquetStreamingLoader(
            parquet_path=self.parquet_path,
            batch_size=100,
            prefetch_batches=2
        )
        
        batch_count = 0
        for batch in loader.iter_batches():
            batch_count += 1
            
        self.assertEqual(batch_count, 10)
    
    def test_to_arrow_table(self):
        """Test converting to an Arrow table."""
        loader = ParquetStreamingLoader(
            parquet_path=self.parquet_path,
            batch_size=100
        )
        
        table = loader.to_arrow_table()
        self.assertIsInstance(table, pa.Table)
        self.assertEqual(len(table), 1000)


@unittest.skipIf(not HAVE_ARROW, "PyArrow is required for this test")
class TestCSVStreamingLoader(unittest.TestCase):
    """Test CSVStreamingLoader class."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        # Create a temporary CSV file
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.csv_path = os.path.join(cls.temp_dir.name, "test.csv")
        
        # Write a sample CSV
        with open(cls.csv_path, "w") as f:
            f.write("id,value\n")
            for i in range(1000):
                f.write(f"{i},{float(i)}\n")
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        cls.temp_dir.cleanup()
    
    def test_csv_loading(self):
        """Test loading a CSV file."""
        loader = CSVStreamingLoader(
            csv_path=self.csv_path,
            batch_size=100
        )
        
        # Get schema
        schema = loader.get_schema()
        self.assertEqual(len(schema), 2)
        self.assertEqual(schema.names, ["id", "value"])
        
        # Iterate over batches
        batch_count = 0
        total_rows = 0
        
        for batch in loader:
            self.assertIsInstance(batch, pa.Table)
            batch_count += 1
            total_rows += len(batch)
            
        self.assertGreaterEqual(batch_count, 1)
        self.assertEqual(total_rows, 1000)


@unittest.skipIf(not HAVE_ARROW, "PyArrow is required for this test")
class TestJSONStreamingLoader(unittest.TestCase):
    """Test JSONStreamingLoader class."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        # Create a temporary JSON file
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.json_path = os.path.join(cls.temp_dir.name, "test.json")
        
        # Write a sample JSONL
        with open(cls.json_path, "w") as f:
            for i in range(1000):
                f.write(json.dumps({"id": i, "value": float(i)}) + "\n")
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        cls.temp_dir.cleanup()
    
    def test_json_loading(self):
        """Test loading a JSON file."""
        loader = JSONStreamingLoader(
            json_path=self.json_path,
            batch_size=100
        )
        
        # Get schema
        schema = loader.get_schema()
        self.assertEqual(len(schema), 2)
        self.assertEqual(set(schema.names), set(["id", "value"]))
        
        # Iterate over batches
        batch_count = 0
        total_rows = 0
        
        for batch in loader:
            self.assertIsInstance(batch, pa.Table)
            batch_count += 1
            total_rows += len(batch)
            
        self.assertGreaterEqual(batch_count, 1)
        self.assertEqual(total_rows, 1000)


@unittest.skipIf(not HAVE_DATASETS, "HuggingFace datasets is required for this test")
class TestHuggingFaceStreamingLoader(unittest.TestCase):
    """Test HuggingFaceStreamingLoader class."""
    
    def setUp(self):
        """Set up test data."""
        # Create a sample dataset
        data = {
            "id": list(range(1000)),
            "value": [float(i) for i in range(1000)]
        }
        self.dataset = Dataset.from_dict(data)
    
    def test_huggingface_loading(self):
        """Test loading a HuggingFace dataset."""
        loader = HuggingFaceStreamingLoader(
            dataset_object=self.dataset,
            batch_size=100
        )
        
        # Get features
        features = loader.get_features()
        self.assertIn("id", features)
        self.assertIn("value", features)
        
        # Iterate over batches
        batch_count = 0
        total_rows = 0
        
        for batch in loader:
            self.assertIsInstance(batch, pa.Table)
            self.assertLessEqual(len(batch), 100)
            batch_count += 1
            total_rows += len(batch)
            
        self.assertEqual(batch_count, 10)
        self.assertEqual(total_rows, 1000)


class TestMemoryMappedVectorLoader(unittest.TestCase):
    """Test MemoryMappedVectorLoader class."""
    
    def test_memory_mapped_vectors(self):
        """Test memory-mapped vector access."""
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            # Create and populate memory-mapped vectors
            dimension = 10
            
            # Initial vectors
            initial_vectors = np.random.rand(100, dimension).astype(np.float32)
            
            # Create memory map
            with create_memory_mapped_vectors(
                file_path=temp_path,
                dimension=dimension,
                initial_vectors=initial_vectors
            ) as mmap_vectors:
                # Check length
                self.assertEqual(len(mmap_vectors), 100)
                
                # Get a vector
                vector = mmap_vectors[0]
                self.assertEqual(vector.shape, (dimension,))
                
                # Get a slice
                vectors = mmap_vectors[10:20]
                self.assertEqual(vectors.shape, (10, dimension))
                
                # Append more vectors
                new_vectors = np.random.rand(50, dimension).astype(np.float32)
                mmap_vectors.append(new_vectors)
                
                # Check new length
                self.assertEqual(len(mmap_vectors), 150)
            
            # Re-open the memory map read-only
            with load_memory_mapped_vectors(
                file_path=temp_path,
                dimension=dimension,
                mode='r'
            ) as mmap_vectors:
                # Check length
                self.assertEqual(len(mmap_vectors), 150)
                
                # Verify the appended vectors
                vectors = mmap_vectors[100:150]
                self.assertEqual(vectors.shape, (50, dimension))
                
                # Verify data
                np.testing.assert_allclose(
                    vectors,
                    new_vectors,
                    rtol=1e-5,
                    atol=1e-5
                )
                
                # Try to append (should fail with read-only)
                with self.assertRaises(Exception):
                    mmap_vectors.append(np.random.rand(10, dimension).astype(np.float32))
        
        finally:
            # Clean up
            os.unlink(temp_path)


@unittest.skipIf(not HAVE_ARROW, "PyArrow is required for this test")
class TestStreamingDataset(unittest.TestCase):
    """Test StreamingDataset class."""
    
    @classmethod
    def setUpClass(cls):
        """Set up test data."""
        # Create a temporary Parquet file
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.parquet_path = os.path.join(cls.temp_dir.name, "test.parquet")
        
        # Create a sample table
        data = {
            "id": pa.array(range(1000)),
            "value": pa.array([float(i) for i in range(1000)])
        }
        table = pa.Table.from_pydict(data)
        
        # Write to Parquet
        pq.write_table(table, cls.parquet_path)
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test data."""
        cls.temp_dir.cleanup()
    
    def test_streaming_dataset(self):
        """Test the high-level StreamingDataset API."""
        # Load dataset
        dataset = load_parquet(
            parquet_path=self.parquet_path,
            batch_size=100
        )
        
        # Iterate over batches
        batch_count = 0
        for batch in dataset.iter_batches():
            self.assertIsInstance(batch, pa.Table)
            batch_count += 1
            
        self.assertEqual(batch_count, 10)
        
        # Apply transformation
        def double_values(batch):
            values = batch.column("value")
            doubled = [v * 2 for v in values]
            return batch.set_column(1, "value", pa.array(doubled))
            
        transformed = dataset.map(double_values)
        
        for batch in transformed.iter_batches():
            # Check that values are doubled
            values = batch.column("value").to_pylist()
            ids = batch.column("id").to_pylist()
            for i, v in zip(ids, values):
                self.assertAlmostEqual(v, i * 2)
        
        # Convert to Arrow table
        table = dataset.to_arrow_table()
        self.assertEqual(len(table), 1000)
        
        # Get stats
        stats = dataset.get_stats()
        self.assertIsInstance(stats, dict)


if __name__ == "__main__":
    unittest.main()