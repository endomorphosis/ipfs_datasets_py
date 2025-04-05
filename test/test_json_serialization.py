"""
Unit tests for JSON serialization fixes in the RAG Query Optimizer.

This module tests that the fix for JSON serialization of NumPy arrays in the metrics collection
works correctly.
"""

import os
import sys
import json
import time
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

# Add the parent directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the module
try:
    from ipfs_datasets_py.rag_query_optimizer import QueryMetricsCollector
    MODULE_AVAILABLE = True
except ImportError:
    MODULE_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


@unittest.skipIf(not MODULE_AVAILABLE, "rag_query_optimizer module not available")
class TestJsonSerialization(unittest.TestCase):
    """Test the JSON serialization fixes."""
    
    def setUp(self):
        """Set up the test environment."""
        # Create a temporary directory for metrics
        self.temp_dir = tempfile.mkdtemp()
        
        # Create the metrics collector
        self.metrics_collector = QueryMetricsCollector(
            max_history_size=10,
            metrics_dir=self.temp_dir,
            track_resources=True
        )
    
    def tearDown(self):
        """Clean up after tests."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    @unittest.skipIf(not NUMPY_AVAILABLE, "NumPy not available")
    def test_numpy_serialization(self):
        """Test serialization of NumPy arrays and types."""
        # Create test metrics with various NumPy objects
        metrics = {
            "query_id": "test_numpy",
            "start_time": time.time(),
            "end_time": time.time() + 1.0,
            "duration": 1.0,
            "phases": {
                "test_phase": {
                    "duration": 0.5,
                    "count": 1
                }
            },
            "params": {"test": "value"},
            "results": {
                "count": 10,
                "quality_score": 0.85
            },
            "resources": {
                "peak_memory": 1024 * 1024
            }
        }
        
        # Add NumPy objects
        metrics["numpy_array"] = np.array([1, 2, 3, 4, 5])
        metrics["numpy_float"] = np.float32(3.14159)
        metrics["numpy_int"] = np.int64(42)
        metrics["numpy_bool"] = np.bool_(True)
        metrics["numpy_scalar"] = np.float64(2.71828).item()  # This should already be a Python float
        metrics["statistics"] = {
            "std_dev": np.std([1, 2, 3, 4, 5])
        }
        
        # Persist metrics
        self.metrics_collector._persist_metrics(metrics)
        
        # Check for created files
        files = [f for f in os.listdir(self.temp_dir) if f.endswith('.json')]
        self.assertEqual(len(files), 1, "A metrics file should have been created")
        
        # Load the file and check contents
        with open(os.path.join(self.temp_dir, files[0]), 'r') as f:
            loaded_metrics = json.load(f)
        
        # Check if NumPy types are correctly serialized
        self.assertIsInstance(loaded_metrics["numpy_array"], list)
        self.assertEqual(loaded_metrics["numpy_array"], [1, 2, 3, 4, 5])
        
        self.assertIsInstance(loaded_metrics["numpy_float"], float)
        self.assertAlmostEqual(loaded_metrics["numpy_float"], 3.14159, places=5)
        
        self.assertIsInstance(loaded_metrics["numpy_int"], int)
        self.assertEqual(loaded_metrics["numpy_int"], 42)
        
        self.assertIsInstance(loaded_metrics["numpy_bool"], bool)
        self.assertTrue(loaded_metrics["numpy_bool"])
        
        self.assertIsInstance(loaded_metrics["statistics"]["std_dev"], float)
    
    @unittest.skipIf(not NUMPY_AVAILABLE, "NumPy not available")
    def test_export_metrics_json(self):
        """Test that export_metrics_json correctly handles NumPy arrays."""
        # Create test metrics
        metrics = {
            "query_id": "export_test",
            "start_time": time.time(),
            "end_time": time.time() + 1.0,
            "duration": 1.0,
            "phases": {},
            "params": {},
            "results": {"count": 0, "quality_score": 0.0},
            "resources": {}
        }
        
        # Add NumPy array
        metrics["numpy_array"] = np.array([1, 2, 3])
        
        # Add to collector
        self.metrics_collector.query_metrics.append(metrics)
        
        # Export to file
        export_file = os.path.join(self.temp_dir, "export.json")
        self.metrics_collector.export_metrics_json(export_file)
        
        # Check file exists
        self.assertTrue(os.path.exists(export_file))
        
        # Load and verify
        with open(export_file, 'r') as f:
            exported_data = json.load(f)
        
        self.assertEqual(len(exported_data), 1)
        self.assertIsInstance(exported_data[0]["numpy_array"], list)
        self.assertEqual(exported_data[0]["numpy_array"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()