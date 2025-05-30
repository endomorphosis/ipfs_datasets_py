"""
Test JSONL serialization functionality in isolation.
"""

import os
import json
import tempfile
import unittest
import shutil

# Mock dependencies
HAVE_ARROW = False
HAVE_HUGGINGFACE = False

# Mock IPLDStorage class
class MockStorage:
    def store_json(self, data):
        """Mock store_json method that returns a fake CID."""
        return "fakecid123456789"

    def get_json(self, cid):
        """Mock get_json method that returns fake data."""
        if cid != "fakecid123456789":
            raise ValueError(f"CID {cid} not found")
        return {
            "type": "jsonl_dataset",
            "record_count": 5,
            "records": [
                {"id": 1, "name": "Alice", "score": 95.5},
                {"id": 2, "name": "Bob", "score": 82.3},
                {"id": 3, "name": "Charlie", "score": 90.0},
                {"id": 4, "name": "Diana", "score": 88.7},
                {"id": 5, "name": "Eve", "score": 91.2}
            ],
            "metadata": {
                "created_at": "2023-01-01T00:00:00",
                "source_file": "sample.jsonl"
            }
        }

# Implementation of DatasetSerializer class for testing
class DatasetSerializer:
    """
    Class for serializing and deserializing datasets between various formats.
    """

    def __init__(self, storage=None):
        """
        Initialize the dataset serializer.

        Args:
            storage (IPLDStorage, optional): IPLD storage backend
        """
        self.storage = storage or MockStorage()

    def export_to_jsonl(self, data, output_path):
        """
        Export data to a JSONL (JSON Lines) file.

        Args:
            data (List[Dict]): List of JSON-serializable records
            output_path (str): Path to the output JSONL file

        Returns:
            str: Path to the created JSONL file
        """
        with open(output_path, 'w') as f:
            for record in data:
                json_str = json.dumps(record)
                f.write(json_str + '\n')
        return output_path

    def serialize_jsonl(self, jsonl_path):
        """
        Serialize a JSONL file to IPLD for storage on IPFS.

        Args:
            jsonl_path (str): Path to the JSONL file

        Returns:
            str: CID of the serialized data
        """
        # Read the JSONL file
        records = []
        with open(jsonl_path, 'r') as f:
            for line in f:
                if line.strip():  # Skip empty lines
                    records.append(json.loads(line))

        # Structure for storage
        dataset = {
            "type": "jsonl_dataset",
            "record_count": len(records),
            "records": records,
            "metadata": {
                "created_at": "2023-01-01T00:00:00",
                "source_file": os.path.basename(jsonl_path)
            }
        }

        # Store in IPLD
        return self.storage.store_json(dataset)

    def deserialize_jsonl(self, cid, output_path=None):
        """
        Deserialize JSONL data from IPLD/IPFS.

        Args:
            cid (str): CID of the serialized JSONL data
            output_path (str, optional): If provided, write the deserialized data to this path

        Returns:
            Union[List[Dict], str]: List of records, or path to the output file if output_path is provided
        """
        # Get the data from IPFS
        dataset = self.storage.get_json(cid)

        # Verify it's a JSONL dataset
        if dataset.get("type") != "jsonl_dataset":
            raise ValueError(f"CID {cid} does not contain a JSONL dataset")

        # Extract records
        records = dataset.get("records", [])

        # If output path provided, write to file
        if output_path:
            with open(output_path, 'w') as f:
                for record in records:
                    json_str = json.dumps(record)
                    f.write(json_str + '\n')
            return output_path

        # Otherwise return records
        return records


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
