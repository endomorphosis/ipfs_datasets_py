import unittest
import asyncio
import os
import sys
import tempfile # Added import
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to ensure imports work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class MockDataset:
    def __init__(self, data, format="json"):
        self.data = data
        self.format = format

    async def save_async(self, output_path, format, **kwargs):
        # Simulate saving to a file
        with open(output_path, 'w') as f:
            f.write(f"Mock {format} data: {self.data}")
        return {"size": len(self.data)}

    def convert_format(self, target_format, **kwargs):
        # Simulate in-memory conversion
        return MockDataset(self.data, target_format)

    def __len__(self):
        return len(self.data)

class MockDatasetShardManager:
    def __init__(self):
        self.datasets = {}
        self.next_id = 1

    def get_dataset(self, dataset_id):
        if dataset_id not in self.datasets:
            raise ValueError(f"Dataset {dataset_id} not found")
        return self.datasets[dataset_id]

    def add_dataset(self, dataset):
        new_id = f"dataset-{self.next_id}"
        self.datasets[new_id] = dataset
        self.next_id += 1
        return new_id

class TestMCPConvertDatasetFormat(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Create a mock for DistributedDatasetManager
        self.mock_distributed_dataset_manager = MagicMock()

        # Create an instance of our MockDatasetShardManager
        self.mock_shard_manager_instance = MockDatasetShardManager()

        # Set the shard_manager attribute on the mock DistributedDatasetManager
        self.mock_distributed_dataset_manager.shard_manager = self.mock_shard_manager_instance

        # Configure the mock DistributedDatasetManager to return itself when instantiated
        self.patcher_distributed_manager = patch(
            'ipfs_datasets_py.libp2p_kit.DistributedDatasetManager',
            return_value=self.mock_distributed_dataset_manager
        )
        self.patcher_distributed_manager.start()
        self.addCleanup(self.patcher_distributed_manager.stop)

        # Populate the mock shard_manager with an initial dataset
        self.initial_dataset = MockDataset({"key": "value"}, format="json")
        self.initial_dataset_id = self.mock_shard_manager_instance.add_dataset(self.initial_dataset)

        # Patch the get_dataset method of the mock shard_manager_instance
        # This ensures that when the tool calls manager.shard_manager.get_dataset, it gets our mock dataset
        patcher_get_dataset = patch.object(
            self.mock_shard_manager_instance,
            'get_dataset',
            side_effect=self.mock_shard_manager_instance.get_dataset
        )
        self.mock_get_dataset = patcher_get_dataset.start()
        self.addCleanup(patcher_get_dataset.stop)

        # Patch the add_dataset method of the mock shard_manager_instance
        patcher_add_dataset = patch.object(
            self.mock_shard_manager_instance,
            'add_dataset',
            side_effect=self.mock_shard_manager_instance.add_dataset
        )
        self.mock_add_dataset = patcher_add_dataset.start()
        self.addCleanup(patcher_add_dataset.stop)


    async def test_convert_dataset_format_to_file(self):
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "converted.csv")
            result = await convert_dataset_format(
                dataset_id=self.initial_dataset_id,
                target_format="csv",
                output_path=output_path
            )

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["dataset_id"], self.initial_dataset_id)
            self.assertEqual(result["original_format"], "json")
            self.assertEqual(result["target_format"], "csv")
            self.assertEqual(result["output_path"], output_path)
            self.assertTrue(os.path.exists(output_path))
            with open(output_path, 'r') as f:
                content = f.read()
                self.assertIn("Mock csv data", content)

    async def test_convert_dataset_format_in_memory(self):
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format

        result = await convert_dataset_format(
            dataset_id=self.initial_dataset_id,
            target_format="parquet"
        )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["original_dataset_id"], self.initial_dataset_id)
        self.assertIsNotNone(result["dataset_id"])
        self.assertEqual(result["original_format"], "json")
        self.assertEqual(result["target_format"], "parquet")
        self.assertIn("num_records", result)
        self.assertEqual(result["num_records"], len(self.initial_dataset.data))

    async def test_convert_dataset_format_error_handling(self):
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format

        # Simulate an error during dataset retrieval
        self.mock_get_dataset.side_effect = Exception("Dataset not found error")

        result = await convert_dataset_format(
            dataset_id="non_existent_id",
            target_format="csv"
        )

        self.assertEqual(result["status"], "error")
        self.assertIn("Dataset not found error", result["message"])
        self.assertEqual(result["dataset_id"], "non_existent_id")

if __name__ == '__main__':
    unittest.main()
