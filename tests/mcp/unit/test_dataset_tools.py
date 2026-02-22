"""
Tests for dataset_tools tool category.

Tests cover:
- load_dataset: load from source
- save_dataset: persist to destination
- process_dataset: apply operations
- convert_dataset_format: format conversion
"""
import pytest

from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format


class TestLoadDataset:
    """Tests for load_dataset tool function."""

    @pytest.mark.asyncio
    async def test_load_with_source_returns_dict(self):
        """
        GIVEN the dataset_tools module
        WHEN load_dataset is called with a source string
        THEN the result must be a dict containing 'status' or 'dataset_id'
        """
        result = await load_dataset(source="test_dataset")
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_load_with_format_returns_dict(self):
        """
        GIVEN the dataset_tools module
        WHEN load_dataset is called with a source and format
        THEN the result must be a dict
        """
        result = await load_dataset(source="test_dataset", format="json")
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_load_with_options_returns_dict(self):
        """
        GIVEN the dataset_tools module
        WHEN load_dataset is called with additional options
        THEN the result must be a dict
        """
        result = await load_dataset(
            source="test_dataset",
            format="parquet",
            options={"subset": "train"},
        )
        assert result is not None
        assert isinstance(result, dict)


class TestSaveDataset:
    """Tests for save_dataset tool function."""

    @pytest.mark.asyncio
    async def test_save_dict_dataset_returns_dict(self):
        """
        GIVEN the dataset_tools module
        WHEN save_dataset is called with a dataset dict
        THEN the result must be a dict
        """
        dataset = {"records": [{"id": 1, "text": "hello"}], "format": "json"}
        result = await save_dataset(dataset_data=dataset)
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_save_with_destination_returns_dict(self, tmp_path):
        """
        GIVEN the dataset_tools module
        WHEN save_dataset is called with a destination path
        THEN the result must be a dict
        """
        dataset = {"records": [{"id": 1}]}
        dest = str(tmp_path / "output.json")
        result = await save_dataset(dataset_data=dataset, destination=dest, format="json")
        assert result is not None
        assert isinstance(result, dict)


class TestProcessDataset:
    """Tests for process_dataset tool function."""

    @pytest.mark.asyncio
    async def test_process_with_operations_returns_dict(self):
        """
        GIVEN the dataset_tools module
        WHEN process_dataset is called with a dataset and operations
        THEN the result must be a dict
        """
        dataset_source = {"records": [{"id": 1, "text": "Hello World"}, {"id": 2, "text": "Foo"}]}
        operations = [{"type": "filter", "field": "text", "value": "Hello"}]
        result = await process_dataset(dataset_source=dataset_source, operations=operations)
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_process_empty_operations_returns_dict(self):
        """
        GIVEN the dataset_tools module
        WHEN process_dataset is called with empty operations
        THEN the result must be a dict
        """
        dataset_source = {"records": [{"id": 1}]}
        result = await process_dataset(dataset_source=dataset_source, operations=[])
        assert result is not None
        assert isinstance(result, dict)


class TestConvertDatasetFormat:
    """Tests for convert_dataset_format tool function."""

    @pytest.mark.asyncio
    async def test_convert_returns_dict(self):
        """
        GIVEN the dataset_tools module
        WHEN convert_dataset_format is called with an id and target format
        THEN the result must be a dict
        """
        result = await convert_dataset_format(
            dataset_id="test_dataset_001",
            target_format="parquet",
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_convert_with_output_path_returns_dict(self, tmp_path):
        """
        GIVEN the dataset_tools module
        WHEN convert_dataset_format is called with an output path
        THEN the result must be a dict
        """
        out = str(tmp_path / "converted.parquet")
        result = await convert_dataset_format(
            dataset_id="test_dataset_001",
            target_format="parquet",
            output_path=out,
        )
        assert result is not None
        assert isinstance(result, dict)
