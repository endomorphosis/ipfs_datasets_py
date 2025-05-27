import unittest
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock
import tempfile
import shutil
import ipfs_datasets_py # Added this import

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockDataset:
    def __init__(self, dataset_id, data=None, format="json"):
        self.dataset_id = dataset_id
        self.data = data if data is not None else {"key": "value"}
        self.format = format

    async def save_async(self, destination, format=None, **kwargs):
        # Simulate saving the dataset
        if "simulate_error" in kwargs and kwargs["simulate_error"]:
            raise Exception("Simulated save error")
        
        # For simplicity, just return a success message and a dummy size
        return {"location": destination, "size": 1024}

class MockDatasetManager:
    def __init__(self):
        self.datasets = {}

    def get_dataset(self, dataset_id):
        if dataset_id not in self.datasets:
            raise ValueError(f"Dataset with ID {dataset_id} not found.")
        return self.datasets[dataset_id]

    def add_dataset(self, dataset_id, dataset_instance):
        self.datasets[dataset_id] = dataset_instance

@patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset.DatasetManager', new=MockDatasetManager)
class TestMCPSaveDataset(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.mock_manager = MockDatasetManager()
        # The DatasetManager is now mocked directly, no need to mock get_instance

    async def test_save_dataset_success(self):
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

        dataset_id = "test_dataset_1"
        destination = "/tmp/test_output/dataset1.json"
        mock_dataset = MockDataset(dataset_id)
        self.mock_manager.add_dataset(dataset_id, mock_dataset)

        result = await save_dataset(dataset_id=dataset_id, destination=destination, format="json")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["dataset_id"], dataset_id)
        self.assertEqual(result["destination"], destination)
        self.assertEqual(result["format"], "json")
        self.assertIn("location", result)
        self.assertIn("size", result)
        self.assertEqual(result["size"], 1024)

    async def test_save_dataset_with_options(self):
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

        dataset_id = "test_dataset_2"
        destination = "/tmp/test_output/dataset2.csv"
        options = {"compression": "gzip"}
        mock_dataset = MockDataset(dataset_id, format="csv")
        self.mock_manager.add_dataset(dataset_id, mock_dataset)

        result = await save_dataset(dataset_id=dataset_id, destination=destination, format="csv", options=options)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["dataset_id"], dataset_id)
        self.assertEqual(result["destination"], destination)
        self.assertEqual(result["format"], "csv")
        self.assertIn("location", result)
        self.assertIn("size", result)
        self.assertEqual(result["size"], 1024)

    async def test_save_dataset_not_found(self):
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

        dataset_id = "non_existent_dataset"
        destination = "/tmp/test_output/non_existent.json"

        result = await save_dataset(dataset_id=dataset_id, destination=destination)

        self.assertEqual(result["status"], "error")
        self.assertIn("Dataset with ID non_existent_dataset not found.", result["message"])
        self.assertEqual(result["dataset_id"], dataset_id)
        self.assertEqual(result["destination"], destination)

    async def test_save_dataset_simulated_error(self):
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

        dataset_id = "test_dataset_3"
        destination = "/tmp/test_output/dataset3.json"
        mock_dataset = MockDataset(dataset_id)
        self.mock_manager.add_dataset(dataset_id, mock_dataset)

        # Patch the save_async method to simulate an error
        with patch.object(mock_dataset, 'save_async', side_effect=Exception("Simulated save error")):
            result = await save_dataset(dataset_id=dataset_id, destination=destination, format="json")

            self.assertEqual(result["status"], "error")
            self.assertIn("Simulated save error", result["message"])
            self.assertEqual(result["dataset_id"], dataset_id)
            self.assertEqual(result["destination"], destination)

if __name__ == '__main__':
    unittest.main()
