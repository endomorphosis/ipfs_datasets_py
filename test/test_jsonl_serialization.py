"""
Test JSONL serialization and deserialization.

This module tests the JSONL import, export, and conversion functions.
"""

import os
import json
import tempfile
import unittest
import shutil

from ipfs_datasets_py.dataset_serialization import DatasetSerializer

# Check for dependencies
try:
    import pyarrow as pa
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False

try:
    from datasets import Dataset
    HAVE_HUGGINGFACE = True
except ImportError:
    HAVE_HUGGINGFACE = False


class TestJSONLSerialization(unittest.TestCase):
    """Test JSONL serialization functions."""
    
    def setUp(self):
        """Set up test data."""
        # Create temporary directory
        self.temp_dir = tempfile.mkdtemp()
        
        # Sample data for testing
        self.sample_data = [
            {"id": 1, "name": "Alice", "score": 95.5},
            {"id": 2, "name": "Bob", "score": 82.3},
            {"id": 3, "name": "Charlie", "score": 90.0},
            {"id": 4, "name": "Diana", "score": 88.7},
            {"id": 5, "name": "Eve", "score": 91.2}
        ]
        
        # Create a sample JSONL file
        self.jsonl_path = os.path.join(self.temp_dir, "sample.jsonl")
        with open(self.jsonl_path, "w") as f:
            for record in self.sample_data:
                f.write(json.dumps(record) + "\n")
        
        # Initialize serializer
        self.serializer = DatasetSerializer()
        
    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir)
        
    def test_export_to_jsonl(self):
        """Test exporting data to JSONL."""
        output_path = os.path.join(self.temp_dir, "exported.jsonl")
        
        # Export data
        self.serializer.export_to_jsonl(self.sample_data, output_path)
        
        # Verify the file exists
        self.assertTrue(os.path.exists(output_path))
        
        # Read back and verify
        with open(output_path, "r") as f:
            lines = f.readlines()
            
        self.assertEqual(len(lines), len(self.sample_data))
        
        # Parse each line and compare
        exported_data = []
        for line in lines:
            exported_data.append(json.loads(line))
            
        self.assertEqual(exported_data, self.sample_data)
        
    def test_import_from_jsonl(self):
        """Test importing data from JSONL."""
        if not HAVE_ARROW:
            self.skipTest("PyArrow not available")
            
        # Import data
        table = self.serializer.import_from_jsonl(self.jsonl_path)
        
        # Verify import was successful
        self.assertIsInstance(table, pa.Table)
        self.assertEqual(table.num_rows, len(self.sample_data))
        self.assertIn("id", table.column_names)
        self.assertIn("name", table.column_names)
        self.assertIn("score", table.column_names)
        
        # Convert to Python objects
        records = table.to_pylist()
        
        # Verify data is correct
        self.assertEqual(len(records), len(self.sample_data))
        for i, record in enumerate(records):
            self.assertEqual(record["id"], self.sample_data[i]["id"])
            self.assertEqual(record["name"], self.sample_data[i]["name"])
            self.assertAlmostEqual(record["score"], self.sample_data[i]["score"])
        
    @unittest.skipIf(not HAVE_HUGGINGFACE, "HuggingFace datasets not available")
    def test_convert_jsonl_to_huggingface(self):
        """Test converting JSONL to HuggingFace dataset."""
        # Convert to HuggingFace dataset
        dataset = self.serializer.convert_jsonl_to_huggingface(self.jsonl_path)
        
        # Verify conversion was successful
        self.assertIsInstance(dataset, Dataset)
        self.assertEqual(len(dataset), len(self.sample_data))
        self.assertIn("id", dataset.column_names)
        self.assertIn("name", dataset.column_names)
        self.assertIn("score", dataset.column_names)
        
        # Verify data is correct
        for i, record in enumerate(dataset):
            self.assertEqual(record["id"], self.sample_data[i]["id"])
            self.assertEqual(record["name"], self.sample_data[i]["name"])
            self.assertAlmostEqual(record["score"], self.sample_data[i]["score"])
    
    @unittest.skipIf(not HAVE_ARROW, "PyArrow not available")
    def test_convert_arrow_to_jsonl(self):
        """Test converting Arrow table to JSONL."""
        # Create Arrow table
        table = pa.Table.from_pylist(self.sample_data)
        
        # Convert to JSONL
        output_path = os.path.join(self.temp_dir, "from_arrow.jsonl")
        self.serializer.convert_arrow_to_jsonl(table, output_path)
        
        # Verify the file exists
        self.assertTrue(os.path.exists(output_path))
        
        # Read back and verify
        with open(output_path, "r") as f:
            lines = f.readlines()
            
        self.assertEqual(len(lines), len(self.sample_data))
        
        # Parse each line and compare
        exported_data = []
        for line in lines:
            exported_data.append(json.loads(line))
            
        for i, record in enumerate(exported_data):
            self.assertEqual(record["id"], self.sample_data[i]["id"])
            self.assertEqual(record["name"], self.sample_data[i]["name"])
            self.assertAlmostEqual(record["score"], self.sample_data[i]["score"])
    
    def test_serialize_and_deserialize_jsonl(self):
        """Test serializing and deserializing JSONL to IPLD."""
        # Serialize JSONL to IPLD
        root_cid = self.serializer.serialize_jsonl(self.jsonl_path)
        
        # Verify CID was returned
        self.assertIsNotNone(root_cid)
        
        # Deserialize as records
        records = self.serializer.deserialize_jsonl(root_cid)
        
        # Verify deserialization was successful
        self.assertIsInstance(records, list)
        self.assertEqual(len(records), len(self.sample_data))
        
        # Verify data is correct
        for i, record in enumerate(records):
            self.assertEqual(record["id"], self.sample_data[i]["id"])
            self.assertEqual(record["name"], self.sample_data[i]["name"])
            self.assertAlmostEqual(record["score"], self.sample_data[i]["score"])
        
        # Deserialize to file
        output_path = os.path.join(self.temp_dir, "deserialized.jsonl")
        file_path = self.serializer.deserialize_jsonl(root_cid, output_path=output_path)
        
        # Verify the file exists
        self.assertTrue(os.path.exists(file_path))
        
        # Read back and verify
        with open(file_path, "r") as f:
            lines = f.readlines()
            
        self.assertEqual(len(lines), len(self.sample_data))
        
        # Parse each line and compare
        deserialized_data = []
        for line in lines:
            deserialized_data.append(json.loads(line))
            
        for i, record in enumerate(deserialized_data):
            self.assertEqual(record["id"], self.sample_data[i]["id"])
            self.assertEqual(record["name"], self.sample_data[i]["name"])
            self.assertAlmostEqual(record["score"], self.sample_data[i]["score"])


if __name__ == "__main__":
    unittest.main()