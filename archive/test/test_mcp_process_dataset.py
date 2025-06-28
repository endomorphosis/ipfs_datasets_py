import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
from datasets import Dataset, DatasetDict, Features, Value, DatasetInfo # Import necessary Hugging Face Dataset classes

import pyarrow as pa # Import pyarrow

# Mock Hugging Face Dataset objects by inheriting from actual Dataset/DatasetDict
class MockHFDataset(Dataset):
    def __init__(self, data=None, features=None, info=None, split="train"):
        # Default data if none provided, ensuring consistent types
        if data is None:
            data = [{"col1": 1, "col2": "A"}, {"col1": 2, "col2": "B_str"}, {"col1": 3, "col2": "C"}]

        # Explicitly define features for default data to avoid inference issues
        if features is None:
            features = Features({
                "col1": Value("int32"),
                "col2": Value("string")
            })

        # Create a PyArrow Schema from the Features object
        arrow_schema = features.arrow_schema

        # Create a PyArrow Table from the data with the explicit schema
        arrow_table = pa.Table.from_pylist(data, schema=arrow_schema)

        # Create a real DatasetInfo object
        dataset_info_obj = DatasetInfo(features=features)

        # Initialize the base Dataset class
        super().__init__(
            arrow_table=arrow_table, # Pass the real PyArrow Table
            info=info if info is not None else dataset_info_obj, # Use the real DatasetInfo object
            split=split # Use a simple string for split
        )
        self._data = data # Store the raw Python list for custom method implementations
        # The base Dataset class handles num_rows and features internally.
        # We should not re-assign them directly as they are properties without setters.
        # The custom methods below will operate on the data obtained via self._data.

    # Mimic __getitem__ for direct access and slicing
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[key]
        elif isinstance(key, slice):
            return MockHFDataset(data=self._data[key], features=self.info.features, info=self.info, split=self.split)
        else:
            raise TypeError("Invalid argument type.")

    def __len__(self):
        return len(self._data)

    def to_pylist(self):
        return self._data

    def filter(self, function, with_indices=False, input_columns=None, batched=False, batch_size=1000, drop_last_batch=False, num_proc=None, load_from_cache_file=True, keep_in_memory=None, cache_file_name=None, writer_batch_size=1000, features=None, disable_nullable_feature_validation=False, fn_kwargs=None, **kwargs):
        if with_indices:
            filtered_data = [row for i, row in enumerate(self._data) if function(row, i)]
        else:
            filtered_data = [row for row in self._data if function(row)]
        return MockHFDataset(data=filtered_data, features=self.info.features, info=self.info, split=self.split)

    def select_columns(self, column_names):
        new_data = []
        for row in self._data:
            new_row = {col: row[col] for col in column_names if col in row}
            new_data.append(new_row)

        new_features = Features({col: self.info.features[col] for col in column_names if col in self.info.features})
        return MockHFDataset(data=new_data, features=new_features, info=self.info, split=self.split)

    def rename_columns(self, column_mapping):
        new_data = []
        for row in self._data:
            new_row = row.copy()
            for old_name, new_name in column_mapping.items():
                if old_name in new_row:
                    new_row[new_name] = new_row.pop(old_name)
            new_data.append(new_row)

        new_features = self.info.features.copy()
        for old_name, new_name in column_mapping.items():
            if old_name in new_features:
                new_features[new_name] = new_features.pop(old_name)
        return MockHFDataset(data=new_data, features=new_features, info=self.info, split=self.split)

    def sort(self, column_names, reverse=False, kind=None, indices_cache_file_name=None, writer_batch_size=1000, load_from_cache_file=True, keep_in_memory=None, **kwargs):
        if isinstance(column_names, str):
            column_names = [column_names]

        sorted_data = sorted(self._data, key=lambda x: tuple(x[col] for col in column_names), reverse=reverse)
        return MockHFDataset(data=sorted_data, features=self.info.features, info=self.info, split=self.split)

    def select(self, indices):
        selected_data = [self._data[i] for i in indices]
        return MockHFDataset(data=selected_data, features=self.info.features, info=self.info, split=self.split)

    def map(self, function, with_indices=False, input_columns=None, batched=False, batch_size=1000, drop_last_batch=False, num_proc=None, load_from_cache_file=True, keep_in_memory=None, cache_file_name=None, writer_batch_size=1000, features=None, disable_nullable_feature_validation=False, fn_kwargs=None, **kwargs):
        mapped_data = []
        if batched:
            for i in range(0, len(self._data), batch_size):
                batch = self._data[i:i+batch_size]
                if with_indices:
                    indices_batch = list(range(i, i+len(batch)))
                    mapped_batch = function(batch, indices_batch)
                else:
                    mapped_batch = function(batch)

                # Assuming mapped_batch is a dictionary of lists for columns
                # Convert it back to a list of dictionaries (rows)
                if isinstance(mapped_batch, dict):
                    keys = list(mapped_batch.keys())
                    num_rows_in_batch = len(mapped_batch[keys[0]])
                    for j in range(num_rows_in_batch):
                        row_dict = {key: mapped_batch[key][j] for key in keys}
                        mapped_data.append(row_dict)
                else: # Assuming mapped_batch is a list of dictionaries (rows)
                    mapped_data.extend(mapped_batch)
        else:
            for i, row in enumerate(self._data):
                if with_indices:
                    updated_row = function(row, i)
                else:
                    updated_row = function(row)
                mapped_data.append(updated_row)

        # Re-infer features if not provided, or use existing ones
        new_features = features if features is not None else self.info.features
        return MockHFDataset(data=mapped_data, features=new_features, info=self.info, split=self.split)

    def flatten(self, max_depth=None, new_fingerprint=None):
        # Simplified flatten: just return a copy of the dataset
        return MockHFDataset(data=self._data, features=self.info.features, info=self.info, split=self.split)

    def unique(self, column):
        seen = set()
        unique_data = []
        for row in self._data:
            if row[column] not in seen:
                seen.add(row[column])
                unique_data.append(row)
        return MockHFDataset(data=unique_data, features=self.info.features, info=self.info, split=self.split)

# Mock DatasetDict by inheriting from actual DatasetDict
class MockHFDatasetDict(DatasetDict):
    def __init__(self, data=None):
        super().__init__(data if data is not None else {"train": MockHFDataset()})

@pytest.mark.asyncio
async def test_process_dataset_no_operations():
    original_dataset = MockHFDataset()
    operations = []
    result = await process_dataset(original_dataset, operations)

    assert result["status"] == "success"
    assert result["original_dataset_id"] == "N/A"
    assert result["num_operations"] == 0
    assert result["num_records"] == 3
    assert result["processed_dataset_obj"].to_pylist() == original_dataset.to_pylist()

@pytest.mark.asyncio
async def test_process_dataset_filter_operation():
    original_dataset = MockHFDataset(data=[{"col1": 1, "col2": "A"}, {"col1": 2, "col2": "B"}, {"col1": 3, "col2": "A"}])
    operations = [
        {"type": "filter", "column": "col2", "condition": "==", "value": "A"}
    ]
    result = await process_dataset(original_dataset, operations)

    assert result["status"] == "success"
    assert result["num_records"] == 2
    assert result["processed_dataset_obj"].to_pylist() == [{"col1": 1, "col2": "A"}, {"col1": 3, "col2": "A"}]

@pytest.mark.asyncio
async def test_process_dataset_select_operation():
    original_dataset = MockHFDataset()
    operations = [
        {"type": "select", "columns": ["col1"]}
    ]
    result = await process_dataset(original_dataset, operations)

    assert result["status"] == "success"
    assert result["num_records"] == 3
    assert result["processed_dataset_obj"].to_pylist() == [{"col1": 1}, {"col1": 2}, {"col1": 3}]

@pytest.mark.asyncio
async def test_process_dataset_rename_operation():
    original_dataset = MockHFDataset(data=[{"col1": 1, "col2": "A"}, {"col1": 2, "col2": "B"}, {"col1": 3, "col2": "A"}])
    operations = [
        {"type": "rename", "column_mapping": {"col1": "new_col1"}}
    ]
    result = await process_dataset(original_dataset, operations)

    assert result["status"] == "success"
    assert result["num_records"] == 3
    assert result["processed_dataset_obj"].to_pylist() == [{"new_col1": 1, "col2": "A"}, {"new_col1": 2, "col2": "B"}, {"new_col1": 3, "col2": "A"}]

@pytest.mark.asyncio
async def test_process_dataset_sort_operation():
    original_dataset = MockHFDataset(data=[{"val": 3}, {"val": 1}, {"val": 2}])
    operations = [
        {"type": "sort", "column": "val", "ascending": True}
    ]
    result = await process_dataset(original_dataset, operations)

    assert result["status"] == "success"
    assert result["num_records"] == 3
    assert result["processed_dataset_obj"].to_pylist() == [{"val": 1}, {"val": 2}, {"val": 3}]

@pytest.mark.asyncio
async def test_process_dataset_limit_operation():
    original_dataset = MockHFDataset()
    operations = [
        {"type": "limit", "n": 1}
    ]
    result = await process_dataset(original_dataset, operations)

    assert result["status"] == "success"
    assert result["num_records"] == 1
    assert result["processed_dataset_obj"].to_pylist() == [{"col1": 1, "col2": "A"}]

@pytest.mark.asyncio
async def test_process_dataset_map_lower_operation():
    original_dataset = MockHFDataset(data=[{"text_col": "HELLO"}, {"text_col": "World"}])
    operations = [
        {"type": "map", "function": "lower", "column": "text_col"}
    ]
    result = await process_dataset(original_dataset, operations)

    assert result["status"] == "success"
    assert result["num_records"] == 2
    assert result["processed_dataset_obj"].to_pylist() == [{"text_col": "hello"}, {"text_col": "world"}]

@pytest.mark.asyncio
async def test_process_dataset_unique_operation():
    original_dataset = MockHFDataset(data=[{"col1": 1, "col2": "A"}, {"col1": 2, "col2": "B"}, {"col1": 3, "col2": "A"}])
    operations = [
        {"type": "unique", "column": "col2"}
    ]
    result = await process_dataset(original_dataset, operations)

    assert result["status"] == "success"
    assert result["num_records"] == 2
    assert result["processed_dataset_obj"].to_pylist() == [{"col1": 1, "col2": "A"}, {"col1": 2, "col2": "B"}]

@pytest.mark.asyncio
async def test_process_dataset_error_handling():
    original_dataset = MockHFDataset()
    operations = [
        {"type": "invalid_op"}
    ]
    # Mock the logger to check error messages
    with patch('ipfs_datasets_py.mcp_server.logger.logger.error') as mock_logger_error:
        result = await process_dataset(original_dataset, operations)
        assert result["status"] == "error"
        assert "invalid_op" in result["message"]
        mock_logger_error.assert_called_once()

@pytest.mark.asyncio
async def test_process_dataset_with_datasetdict():
    original_dataset_dict = DatasetDict({
        "train": MockHFDataset(data=[{"val": 1}, {"val": 2}]),
        "validation": MockHFDataset(data=[{"val": 3}])
    })
    operations = [
        {"type": "limit", "n": 1}
    ]
    result = await process_dataset(original_dataset_dict, operations)

    assert result["status"] == "success"
    assert result["num_records"] == 1
    assert result["processed_dataset_obj"].to_pylist() == [{"val": 1}]
