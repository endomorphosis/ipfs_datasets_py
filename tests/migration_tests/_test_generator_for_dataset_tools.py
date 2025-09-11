#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Test generator for Dataset tools in the MCP server.
This script generates tests for the Dataset tools:
- load_dataset
- save_dataset
- process_dataset
- convert_dataset_format
"""

import os
import sys
import inspect
import importlib
from unittest.mock import patch, MagicMock

# Add the parent directory to the path so we can import the tools
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the Dataset tools
try:
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format
except ImportError as e:
    print(f"Error importing Dataset tools: {e}")
    sys.exit(1)

# Function to analyze the function signature
def analyze_function_signature(func):
    sig = inspect.signature(func)
    params = []
    for name, param in sig.parameters.items():
        param_type = param.annotation if param.annotation != inspect.Parameter.empty else "Any"
        if param_type != inspect.Parameter.empty:
            # Convert annotations to strings to handle forward references
            param_type = str(param_type).replace("typing.", "").replace("'", "")
            if "ForwardRef" in param_type:
                param_type = param_type.split("'")[1]
        default = param.default if param.default != inspect.Parameter.empty else None
        params.append({
            'name': name,
            'type': param_type,
            'default': default
        })
    return_type = sig.return_annotation
    if return_type != inspect.Signature.empty:
        return_type = str(return_type).replace("typing.", "").replace("'", "")
        if "ForwardRef" in return_type:
            return_type = return_type.split("'")[1]
    else:
        return_type = "Any"
    return params, return_type

# Create a test class for load_dataset
def generate_load_dataset_test():
    try:
        params, return_type = analyze_function_signature(load_dataset)

        test_content = f"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import os
import tempfile
import json
from datasets import Dataset

# Import the function to test
from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset

class TestLoadDataset:
    @pytest.fixture
    def sample_dataset(self):
        # Create a simple mock dataset
        data = {{'text': ['This is a test', 'Another example'], 'label': [1, 0]}}
        return Dataset.from_dict(data)

    @pytest.fixture
    def mock_datasets_lib(self, sample_dataset):
        mock_datasets = MagicMock()
        mock_datasets.load_from_disk = MagicMock(return_value=sample_dataset)
        mock_datasets.load_dataset = MagicMock(return_value=sample_dataset)
        return mock_datasets

    @pytest.mark.asyncio
    async def test_load_dataset_from_disk(self, sample_dataset, mock_datasets_lib):
        # Create a temporary directory to simulate dataset location
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock the datasets library
            with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.datasets', mock_datasets_lib):
                # Call the function with path parameter
                result = await load_dataset(path=temp_dir)

                # Assertions
                assert result is not None
                assert isinstance(result, dict)
                assert 'dataset' in result
                assert result['dataset'] == sample_dataset

                # Verify the mock was called correctly
                mock_datasets_lib.load_from_disk.assert_called_once_with(temp_dir)
                mock_datasets_lib.load_dataset.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_dataset_from_huggingface(self, sample_dataset, mock_datasets_lib):
        # Mock the datasets library
        with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.datasets', mock_datasets_lib):
            # Call the function with name parameter
            dataset_name = 'example/dataset'
            result = await load_dataset(name=dataset_name)

            # Assertions
            assert result is not None
            assert isinstance(result, dict)
            assert 'dataset' in result
            assert result['dataset'] == sample_dataset

            # Verify the mock was called correctly
            mock_datasets_lib.load_dataset.assert_called_once_with(dataset_name)
            mock_datasets_lib.load_from_disk.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_dataset_with_config(self, sample_dataset, mock_datasets_lib):
        # Mock the datasets library
        with patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.datasets', mock_datasets_lib):
            # Call the function with name and config parameters
            dataset_name = 'example/dataset'
            config = 'en'
            result = await load_dataset(name=dataset_name, config=config)

            # Assertions
            assert result is not None
            assert isinstance(result, dict)
            assert 'dataset' in result
            assert result['dataset'] == sample_dataset

            # Verify the mock was called correctly
            mock_datasets_lib.load_dataset.assert_called_once_with(dataset_name, config)
            mock_datasets_lib.load_from_disk.assert_not_called()

    @pytest.mark.asyncio
    async def test_load_dataset_missing_parameters(self):
        # Test error case when neither path nor name is provided
        with pytest.raises(ValueError):
            await load_dataset()
"""
        return test_content
    except Exception as e:
        print(f"Error generating test for load_dataset: {e}")
        return None

# Create a test class for save_dataset
def generate_save_dataset_test():
    try:
        params, return_type = analyze_function_signature(save_dataset)

        test_content = """
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import os
import tempfile
from datasets import Dataset

# Import the function to test
from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

class TestSaveDataset:
    @pytest.fixture
    def sample_dataset(self):
        # Create a simple mock dataset
        data = {'text': ['This is a test', 'Another example'], 'label': [1, 0]}
        return Dataset.from_dict(data)

    @pytest.mark.asyncio
    async def test_save_dataset_to_disk(self, sample_dataset):
        # Create a temporary directory for output
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock the save_to_disk method
            sample_dataset.save_to_disk = MagicMock()

            # Call the function
            result = await save_dataset(sample_dataset, output_path=temp_dir)

            # Assertions
            assert result is not None
            assert isinstance(result, dict)
            assert 'path' in result
            assert result['path'] == temp_dir

            # Verify the mock was called correctly
            sample_dataset.save_to_disk.assert_called_once_with(temp_dir)

    @pytest.mark.asyncio
    async def test_save_dataset_with_format(self, sample_dataset):
        # Create a temporary directory for output
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock the save_to_disk method
            sample_dataset.save_to_disk = MagicMock()

            # Call the function with format parameter
            result = await save_dataset(sample_dataset, output_path=temp_dir, file_format='csv')

            # Assertions
            assert result is not None
            assert isinstance(result, dict)
            assert 'path' in result
            assert result['path'] == temp_dir

            # Verify the mock was called correctly with the format option
            sample_dataset.save_to_disk.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_dataset_invalid_dataset(self):
        # Test with an invalid dataset object
        invalid_dataset = {"not_a_dataset": True}

        with pytest.raises(ValueError):
            await save_dataset(invalid_dataset, output_path="/tmp/output")
"""
        return test_content
    except Exception as e:
        print(f"Error generating test for save_dataset: {e}")
        return None

# Create a test class for process_dataset
def generate_process_dataset_test():
    try:
        params, return_type = analyze_function_signature(process_dataset)

        test_content = """
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datasets import Dataset
import numpy as np

# Import the function to test
from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset

class TestProcessDataset:
    @pytest.fixture
    def sample_dataset(self):
        # Create a simple mock dataset
        data = {'text': ['This is a test', 'Another example'], 'label': [1, 0]}
        return Dataset.from_dict(data)

    @pytest.mark.asyncio
    async def test_process_dataset_with_text_function(self, sample_dataset):
        # Define a text processing function
        async def text_processor(example):
            return {'text_length': len(example['text']), 'processed_text': example['text'].upper()}

        # Call the function
        result = await process_dataset(
            dataset=sample_dataset,
            process_function=text_processor,
            input_columns=['text']
        )

        # Assertions
        assert result is not None
        assert isinstance(result, dict)
        assert 'processed_dataset' in result
        assert isinstance(result['processed_dataset'], Dataset)

        # Check that the processed dataset has the new columns
        processed_dataset = result['processed_dataset']
        assert 'text_length' in processed_dataset.column_names
        assert 'processed_text' in processed_dataset.column_names

    @pytest.mark.asyncio
    async def test_process_dataset_batch_processing(self, sample_dataset):
        # Define a batch processing function
        async def batch_processor(examples):
            return {
                'text_lengths': [len(text) for text in examples['text']],
                'processed_texts': [text.upper() for text in examples['text']]
            }

        # Call the function with batch processing
        result = await process_dataset(
            dataset=sample_dataset,
            process_function=batch_processor,
            input_columns=['text'],
            batch_size=2,
            batched=True
        )

        # Assertions
        assert result is not None
        assert isinstance(result, dict)
        assert 'processed_dataset' in result
        assert isinstance(result['processed_dataset'], Dataset)

        # Check that the processed dataset has the new columns
        processed_dataset = result['processed_dataset']
        assert 'text_lengths' in processed_dataset.column_names
        assert 'processed_texts' in processed_dataset.column_names

    @pytest.mark.asyncio
    async def test_process_dataset_invalid_function(self, sample_dataset):
        # Define an invalid processing function that doesn't return a dictionary
        async def invalid_processor(example):
            return "Not a dictionary"

        # Test with an invalid processing function
        with pytest.raises(ValueError):
            await process_dataset(
                dataset=sample_dataset,
                process_function=invalid_processor,
                input_columns=['text']
            )

    @pytest.mark.asyncio
    async def test_process_dataset_invalid_dataset(self):
        # Test with an invalid dataset object
        invalid_dataset = {"not_a_dataset": True}

        async def processor(example):
            return {"processed": True}

        with pytest.raises(ValueError):
            await process_dataset(
                dataset=invalid_dataset,
                process_function=processor,
                input_columns=['text']
            )
"""
        return test_content
    except Exception as e:
        print(f"Error generating test for process_dataset: {e}")
        return None

# Create a test class for convert_dataset_format
def generate_convert_dataset_format_test():
    try:
        params, return_type = analyze_function_signature(convert_dataset_format)

        test_content = """
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import os
import tempfile
from datasets import Dataset
import pandas as pd
import json

# Import the function to test
from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import convert_dataset_format

class TestConvertDatasetFormat:
    @pytest.fixture
    def sample_dataset(self):
        # Create a simple mock dataset
        data = {'text': ['This is a test', 'Another example'], 'label': [1, 0]}
        return Dataset.from_dict(data)

    @pytest.mark.asyncio
    async def test_convert_dataset_to_csv(self, sample_dataset):
        # Create a temporary directory for output
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, 'output.csv')

            # Call the function
            result = await convert_dataset_format(
                dataset=sample_dataset,
                output_format='csv',
                output_path=output_path
            )

            # Assertions
            assert result is not None
            assert isinstance(result, dict)
            assert 'output_path' in result
            assert result['output_path'] == output_path

            # Verify the file was created
            assert os.path.exists(output_path)

            # Verify the content is a valid CSV
            df = pd.read_csv(output_path)
            assert 'text' in df.columns
            assert 'label' in df.columns
            assert len(df) == 2

    @pytest.mark.asyncio
    async def test_convert_dataset_to_json(self, sample_dataset):
        # Create a temporary directory for output
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, 'output.json')

            # Call the function
            result = await convert_dataset_format(
                dataset=sample_dataset,
                output_format='json',
                output_path=output_path
            )

            # Assertions
            assert result is not None
            assert isinstance(result, dict)
            assert 'output_path' in result
            assert result['output_path'] == output_path

            # Verify the file was created
            assert os.path.exists(output_path)

            # Verify the content is valid JSON
            with open(output_path, 'r') as f:
                data = json.load(f)
            assert 'text' in data
            assert 'label' in data
            assert len(data['text']) == 2

    @pytest.mark.asyncio
    async def test_convert_dataset_to_parquet(self, sample_dataset):
        # Create a temporary directory for output
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, 'output.parquet')

            # Call the function
            result = await convert_dataset_format(
                dataset=sample_dataset,
                output_format='parquet',
                output_path=output_path
            )

            # Assertions
            assert result is not None
            assert isinstance(result, dict)
            assert 'output_path' in result
            assert result['output_path'] == output_path

            # Verify the file was created
            assert os.path.exists(output_path)

            # Verify the content is a valid parquet file
            df = pd.read_parquet(output_path)
            assert 'text' in df.columns
            assert 'label' in df.columns
            assert len(df) == 2

    @pytest.mark.asyncio
    async def test_convert_dataset_invalid_format(self, sample_dataset):
        # Test with an invalid output format
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, 'output.unknown')

            with pytest.raises(ValueError):
                await convert_dataset_format(
                    dataset=sample_dataset,
                    output_format='unknown',
                    output_path=output_path
                )

    @pytest.mark.asyncio
    async def test_convert_dataset_invalid_dataset(self):
        # Test with an invalid dataset object
        invalid_dataset = {"not_a_dataset": True}

        with pytest.raises(ValueError):
            await convert_dataset_format(
                dataset=invalid_dataset,
                output_format='csv',
                output_path='/tmp/output.csv'
            )
"""
        return test_content
    except Exception as e:
        print(f"Error generating test for convert_dataset_format: {e}")
        return None

# Generate the test file
def generate_test_file():
    load_dataset_test = generate_load_dataset_test()
    save_dataset_test = generate_save_dataset_test()
    process_dataset_test = generate_process_dataset_test()
    convert_dataset_format_test = generate_convert_dataset_format_test()

    test_file_content = """#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
    test_file_content += '"""'
    test_file_content += """
Test suite for Dataset tools in the MCP server.
This file was automatically generated by test_generator_for_dataset_tools.py.
"""
    test_file_content += '"""'
    test_file_content += """

import os
import sys
import pytest
"""

    if load_dataset_test:
        test_file_content += "\n" + load_dataset_test

    if save_dataset_test:
        test_file_content += "\n" + save_dataset_test

    if process_dataset_test:
        test_file_content += "\n" + process_dataset_test

    if convert_dataset_format_test:
        test_file_content += "\n" + convert_dataset_format_test

    # Create the test file
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
    os.makedirs(test_dir, exist_ok=True)
    test_file_path = os.path.join(test_dir, "test_dataset_tools.py")

    with open(test_file_path, "w") as f:
        f.write(test_file_content)

    print(f"Generated test file: {test_file_path}")

# Main function
def main():
    print("Generating tests for Dataset tools...")
    generate_test_file()
    print("Done!")

if __name__ == "__main__":
    main()
