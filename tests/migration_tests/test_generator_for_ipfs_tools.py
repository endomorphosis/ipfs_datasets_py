import asyncio
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Test generator for IPFS tools in the MCP server.
This script generates tests for the IPFS tools:
- pin_to_ipfs
- get_from_ipfs
"""

import os
import sys
import inspect
import importlib
from unittest.mock import patch, MagicMock

# Add the parent directory to the path so we can import the tools
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the IPFS tools
try:
    from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs
    from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs
except ImportError as e:
    print(f"Error importing IPFS tools: {e}")
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

# Create a test class for pin_to_ipfs
def generate_pin_to_ipfs_test():
    try:
        params, return_type = analyze_function_signature(pin_to_ipfs)

        test_content = f"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import os
import tempfile
import json

# Import the function to test
from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs

class TestPinToIPFS:
    @pytest.fixture
    def mock_ipfs_client(self):
        mock_client = MagicMock()
        mock_client.add = MagicMock(return_value=[{{'Hash': 'QmTest', 'Name': 'test_file'}}])
        return mock_client

    @pytest.mark.asyncio
    async def test_pin_to_ipfs_file(self, mock_ipfs_client):
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            temp.write(b"Test data")
            temp_path = temp.name

        try:
            # Mock the IPFS client
            with patch('ipfs_datasets_py.ipfs_kit.IPFSClient', return_value=mock_ipfs_client):
                # Call the function
                result = await pin_to_ipfs(temp_path)

                # Assertions
                assert result is not None
                assert 'cid' in result
                assert result['cid'] == 'QmTest'

                # Verify the mock was called correctly
                mock_ipfs_client.add.assert_called_once()
        finally:
            # Clean up the temporary file
            os.unlink(temp_path)

    @pytest.mark.asyncio
    async def test_pin_to_ipfs_directory(self, mock_ipfs_client):
        # Create a temporary directory
        temp_dir = tempfile.mkdtemp()

        try:
            # Create a file in the temporary directory
            with open(os.path.join(temp_dir, 'test.txt'), 'w') as f:
                f.write("Test data")

            # Mock the IPFS client
            with patch('ipfs_datasets_py.ipfs_kit.IPFSClient', return_value=mock_ipfs_client):
                # Call the function
                result = await pin_to_ipfs(temp_dir)

                # Assertions
                assert result is not None
                assert 'cid' in result
                assert result['cid'] == 'QmTest'

                # Verify the mock was called correctly
                mock_ipfs_client.add.assert_called_once()
        finally:
            # Clean up the temporary directory
            import shutil
            shutil.rmtree(temp_dir)

    @pytest.mark.asyncio
    async def test_pin_to_ipfs_invalid_path(self):
        # Test with an invalid path
        with pytest.raises(Exception):
            await pin_to_ipfs('/invalid/path/that/does/not/exist')
"""
        return test_content
    except Exception as e:
        print(f"Error generating test for pin_to_ipfs: {e}")
        return None

# Create a test class for get_from_ipfs
def generate_get_from_ipfs_test():
    try:
        params, return_type = analyze_function_signature(get_from_ipfs)

        test_content = f"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import os
import tempfile

# Import the function to test
from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs

class TestGetFromIPFS:
    @pytest.fixture
    def mock_ipfs_client(self):
        mock_client = MagicMock()

        # Mock the get method to create a temporary file with test data
        def mock_get(cid, filepath):
            with open(filepath, 'w') as f:
                f.write("Test data from IPFS")
            return filepath

        mock_client.get = MagicMock(side_effect=mock_get)
        return mock_client

    @pytest.mark.asyncio
    async def test_get_from_ipfs(self, mock_ipfs_client):
        # Create a temporary directory for output
        temp_dir = tempfile.mkdtemp()

        try:
            # Mock the IPFS client
            with patch('ipfs_datasets_py.ipfs_kit.IPFSClient', return_value=mock_ipfs_client):
                # Call the function
                result = await get_from_ipfs('QmTest', temp_dir)

                # Assertions
                assert result is not None
                assert os.path.exists(result)
                with open(result, 'r') as f:
                    content = f.read()
                assert content == "Test data from IPFS"

                # Verify the mock was called correctly
                mock_ipfs_client.get.assert_called_once()
        finally:
            # Clean up the temporary directory
            import shutil
            shutil.rmtree(temp_dir)

    @pytest.mark.asyncio
    async def test_get_from_ipfs_invalid_cid(self, mock_ipfs_client):
        # Mock the get method to raise an exception for invalid CID
        mock_ipfs_client.get.side_effect = Exception("Invalid CID")

        # Mock the IPFS client
        with patch('ipfs_datasets_py.ipfs_kit.IPFSClient', return_value=mock_ipfs_client):
            # Test with an invalid CID
            with pytest.raises(Exception):
                await get_from_ipfs('InvalidCID', '/tmp')
"""
        return test_content
    except Exception as e:
        print(f"Error generating test for get_from_ipfs: {e}")
        return None

# Generate the test file
def generate_test_file():
    pin_to_ipfs_test = generate_pin_to_ipfs_test()
    get_from_ipfs_test = generate_get_from_ipfs_test()

    test_file_content = """#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
    test_file_content += '"""'
    test_file_content += """
Test suite for IPFS tools in the MCP server.
This file was automatically generated by test_generator_for_ipfs_tools.py.
"""
    test_file_content += '"""'
    test_file_content += """

import os
import sys
import pytest
"""

    if pin_to_ipfs_test:
        test_file_content += "\n" + pin_to_ipfs_test

    if get_from_ipfs_test:
        test_file_content += "\n" + get_from_ipfs_test

    # Create the test file
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
    os.makedirs(test_dir, exist_ok=True)
    test_file_path = os.path.join(test_dir, "test_ipfs_tools.py")

    with open(test_file_path, "w") as f:
        f.write(test_file_content)

    print(f"Generated test file: {test_file_path}")

# Main function
def main():
    print("Generating tests for IPFS tools...")
    generate_test_file()
    print("Done!")

if __name__ == "__main__":
    main()
