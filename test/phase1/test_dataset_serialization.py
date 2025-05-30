import os
import sys
import unittest
import tempfile
import shutil
import json
import numpy as np
from typing import Dict, List, Any, Optional

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import the module to test
try:
    from ipfs_datasets_py.dataset_serialization import DatasetSerializer
    from ipfs_datasets_py.ipld.storage import IPLDStorage
except ImportError:
    # Mock classes for testing structure before implementation
    class DatasetSerializer:
        def __init__(self, storage=None):
            self.storage = storage or IPLDStorage()

        def serialize_arrow_table(self, table, hash_columns=None):
            """Serialize Arrow table to IPLD"""
            return "bafybeiarrowtablecid"

        def deserialize_arrow_table(self, cid):
            """Deserialize Arrow table from IPLD"""
            # Return a mock table
            class MockTable:
                def __init__(self):
                    self.num_rows = 10
                    self.column_names = ["id", "value"]

                def to_pydict(self):
                    return {
                        "id": list(range(10)),
                        "value": [float(i * 1.5) for i in range(10)]
                    }

            return MockTable()

        def serialize_huggingface_dataset(self, dataset, split="train", hash_columns=None):
            """Serialize HuggingFace dataset to IPLD"""
            return "bafybeihfdatasetcid"

        def deserialize_huggingface_dataset(self, cid):
            """Deserialize HuggingFace dataset from IPLD"""
            # Return a mock dataset
            class MockDataset:
                def __init__(self):
                    self.num_rows = 10
                    self.column_names = ["id", "text"]

                def __len__(self):
                    return self.num_rows

                def __getitem__(self, idx):
                    return {"id": idx, "text": f"Text {idx}"}

            return MockDataset()

    class IPLDStorage:
        def __init__(self, base_dir=None):
            self.base_dir = base_dir or tempfile.mkdtemp()

        def store(self, data: bytes, links=None) -> str:
            """Store data and return CID"""
            return f"bafybeidetatestcid"


# Try to import testing dependencies, skip tests if not available
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    HAVE_ARROW = True
except ImportError:
    HAVE_ARROW = False

try:
    from datasets import Dataset
    HAVE_HF = True
except ImportError:
    HAVE_HF = False


class TestDatasetSerialization(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test"""
        self.temp_dir = tempfile.mkdtemp()
        self.storage = IPLDStorage(base_dir=self.temp_dir)
        self.serializer = DatasetSerializer(storage=self.storage)

    def tearDown(self):
        """Clean up test fixtures after each test"""
        shutil.rmtree(self.temp_dir)

    def test_arrow_serialization(self):
        """Test serializing and deserializing Arrow tables"""
        if not HAVE_ARROW:
            self.skipTest("PyArrow not installed")

        # Create a test Arrow table
        data = {
            "id": pa.array(list(range(5))),
            "name": pa.array(["A", "B", "C", "D", "E"]),
            "value": pa.array([1.1, 2.2, 3.3, 4.4, 5.5]),
        }
        table = pa.Table.from_pydict(data)

        # Serialize table
        cid = self.serializer.serialize_arrow_table(table, hash_columns=["id"])

        # Verify CID
        self.assertIsNotNone(cid)

        # Deserialize table
        restored_table = self.serializer.deserialize_arrow_table(cid)

        # Verify table contents
        self.assertEqual(restored_table.num_rows, table.num_rows)
        self.assertEqual(restored_table.column_names, table.column_names)

        # Convert to Python dictionary for comparison
        original_dict = table.to_pydict()
        restored_dict = restored_table.to_pydict()

        for col in table.column_names:
            self.assertEqual(restored_dict[col], original_dict[col])

    def test_huggingface_serialization(self):
        """Test serializing and deserializing HuggingFace datasets"""
        if not HAVE_HF:
            self.skipTest("HuggingFace datasets not installed")

        # Create a small test dataset
        data = {
            "id": list(range(5)),
            "text": ["Text A", "Text B", "Text C", "Text D", "Text E"],
            "label": [0, 1, 0, 1, 0]
        }
        dataset = Dataset.from_dict(data)

        # Serialize dataset
        cid = self.serializer.serialize_huggingface_dataset(dataset, hash_columns=["id"])

        # Verify CID
        self.assertIsNotNone(cid)

        # Deserialize dataset
        restored_dataset = self.serializer.deserialize_huggingface_dataset(cid)

        # Verify dataset contents
        self.assertEqual(len(restored_dataset), len(dataset))

        # Compare a few items
        for i in range(min(5, len(dataset))):
            original_item = dataset[i]
            restored_item = restored_dataset[i]

            for key in original_item:
                self.assertEqual(restored_item[key], original_item[key])

    def test_large_dataset_streaming(self):
        """Test handling of large datasets with streaming"""
        if not hasattr(self.serializer, 'serialize_dataset_streaming'):
            self.skipTest("Streaming serialization not implemented yet")

        # Mock creation of a large dataset (without actually creating it in memory)
        num_chunks = 5
        rows_per_chunk = 100

        # Function to generate chunks
        def generate_chunks():
            for i in range(num_chunks):
                chunk_data = {
                    "id": list(range(i * rows_per_chunk, (i + 1) * rows_per_chunk)),
                    "value": [float(j * 1.5) for j in range(i * rows_per_chunk, (i + 1) * rows_per_chunk)]
                }

                if HAVE_ARROW:
                    yield pa.Table.from_pydict(chunk_data)
                else:
                    yield chunk_data

        # Serialize in streaming mode
        cid = self.serializer.serialize_dataset_streaming(generate_chunks())

        # Verify CID
        self.assertIsNotNone(cid)

        # Deserialize with streaming
        chunks = list(self.serializer.deserialize_dataset_streaming(cid))

        # Verify number of chunks
        self.assertEqual(len(chunks), num_chunks)

        # Verify total number of rows
        total_rows = sum(len(chunk) for chunk in chunks)
        self.assertEqual(total_rows, num_chunks * rows_per_chunk)


if __name__ == '__main__':
    unittest.main()
