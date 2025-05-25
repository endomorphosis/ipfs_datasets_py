import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset

# Mock Hugging Face Dataset objects
class MockHFDataset:
    def __init__(self, num_rows=10, features=None, info=None):
        self.num_rows = num_rows
        self.features = features if features is not None else {"text": {"dtype": "string"}}
        self.info = info if info is not None else MagicMock(to_dict=lambda: {"description": "Mock Dataset"})

    def __len__(self):
        return self.num_rows

@pytest.mark.asyncio
async def test_load_dataset_success():
    with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.hf_load_dataset', autospec=True) as mock_hf_load_dataset:
        mock_hf_load_dataset.return_value = MockHFDataset()

        source = "mock_source"
        result = await load_dataset(source)

        mock_hf_load_dataset.assert_called_once_with(source, format=None)
        assert result["status"] == "success"
        assert result["dataset_id"] == "N/A" # As per the updated tool, id is N/A for HF datasets
        assert result["summary"]["num_records"] == 10
        assert result["summary"]["format"] == "auto-detected"

@pytest.mark.asyncio
async def test_load_dataset_with_format_and_options():
    with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.hf_load_dataset', autospec=True) as mock_hf_load_dataset:
        mock_hf_load_dataset.return_value = MockHFDataset(num_rows=5, features={"col1": {"dtype": "int"}})

        source = "mock_source.json"
        format = "json"
        options = {"encoding": "utf-8"}
        result = await load_dataset(source, format=format, options=options)

        mock_hf_load_dataset.assert_called_once_with(source, format=format, encoding="utf-8")
        assert result["status"] == "success"
        assert result["summary"]["num_records"] == 5
        assert result["summary"]["format"] == "json"
        assert "col1" in result["summary"]["schema"]

@pytest.mark.asyncio
async def test_load_dataset_with_splits():
    with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.hf_load_dataset', autospec=True) as mock_hf_load_dataset:
        mock_hf_load_dataset.return_value = {
            "train": MockHFDataset(num_rows=100),
            "test": MockHFDataset(num_rows=20)
        }

        source = "mock_dataset_with_splits"
        result = await load_dataset(source)

        mock_hf_load_dataset.assert_called_once_with(source, format=None)
        assert result["status"] == "success"
        assert result["summary"]["num_records"] == 100 # Should default to 'train' split
        assert result["summary"]["source"] == source

@pytest.mark.asyncio
async def test_load_dataset_error():
    with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.hf_load_dataset', autospec=True) as mock_hf_load_dataset:
        mock_hf_load_dataset.side_effect = Exception("Dataset not found on Hugging Face Hub")

        source = "non_existent_source"
        result = await load_dataset(source)

        mock_hf_load_dataset.assert_called_once_with(source, format=None)
        assert result["status"] == "error"
        assert "Dataset not found on Hugging Face Hub" in result["message"]
        assert result["source"] == source
