# MCP Server Tools Testing Guide

This guide provides instructions on how to test the Model Context Protocol (MCP) server tools in the ipfs_datasets_py library.

## Overview of MCP Tools

The ipfs_datasets_py library exposes various functionality through the Model Context Protocol (MCP) server. This allows the library's features to be accessible through a standard protocol interface.

Based on our analysis, the MCP server includes the following tool categories:

1. **dataset_tools (4 tools)**
   - load_dataset
   - save_dataset
   - process_dataset
   - convert_dataset_format

2. **ipfs_tools (2 tools)**
   - get_from_ipfs
   - pin_to_ipfs

3. **vector_tools (2 tools)**
   - create_vector_index
   - search_vector_index

4. **graph_tools (1 tool)**
   - query_knowledge_graph

5. **audit_tools (2 tools)**
   - record_audit_event
   - generate_audit_report

6. **security_tools (1 tool)**
   - check_access_permission

7. **provenance_tools (1 tool)**
   - record_provenance

8. **web_archive_tools (6 tools)**
   - create_warc
   - index_warc
   - extract_dataset_from_cdxj
   - extract_text_from_warc
   - extract_links_from_warc
   - extract_metadata_from_warc

9. **cli (1 tool)**
   - execute_command

10. **functions (1 tool)**
    - execute_python_snippet

## Testing Approaches

There are several ways to test the MCP tools:

### 1. Using the MCP Server Test Script

The existing `test_mcp_server.py` file in the MCP server directory can be used to test the server and its tools. This script starts the MCP server and tests the tools through the Model Context Protocol.

```bash
python ipfs_datasets_py/mcp_server/test_mcp_server.py
```

### 2. Testing MCP Tool Coverage

The `test_mcp_api_coverage.py` script checks if all expected library features are exposed as MCP tools.

```bash
python test_mcp_api_coverage.py
```

### 3. Direct Tool Testing

You can test individual tools directly by importing them and calling their functions. However, note that many of these functions are asynchronous and need to be run in an async context.

Example for testing a dataset tool:

```python
import asyncio
from ipfs_datasets_py.mcp_server.tools.dataset_tools import load_dataset

async def test_load_dataset():
    result = await load_dataset(source="path/to/dataset.json", format="json")
    print(result)

asyncio.run(test_load_dataset())
```

### 4. Mock-Based Unit Testing

For proper unit testing, you'll want to use mocks to avoid dependencies on external services like IPFS. Here's an example approach:

```python
import unittest
from unittest.mock import patch, MagicMock
import asyncio

class DatasetToolsTest(unittest.TestCase):
    @patch('ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset.datasets')
    async def test_load_dataset(self, mock_datasets):
        from ipfs_datasets_py.mcp_server.tools.dataset_tools import load_dataset
        
        # Set up mock
        mock_dataset = MagicMock()
        mock_datasets.load_dataset.return_value = mock_dataset
        
        # Call function
        result = await load_dataset("test_dataset", format="json")
        
        # Assertions
        self.assertEqual(result["status"], "success")
        mock_datasets.load_dataset.assert_called_once_with("test_dataset", format="json")

# Run with asyncio
def run_tests():
    unittest.main()

if __name__ == "__main__":
    run_tests()
```

## Implementing New Tests

To implement tests for currently untested tools:

1. **Identify untested tools**: Run the API coverage test to see which tools need testing.
2. **Create test files**: Create test files for each tool category (e.g., `test_web_archive_tools.py`).
3. **Implement unit tests**: Write tests that mock external dependencies and verify the tool's functionality.
4. **Run tests**: Execute the tests to ensure they pass.

## Testing Web Archive Tools Example

Here's a detailed example for testing web archive tools:

```python
import unittest
from unittest.mock import patch, MagicMock
import asyncio
import os
from pathlib import Path

class WebArchiveToolsTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("/tmp/web_archive_test")
        os.makedirs(self.test_dir, exist_ok=True)
        self.warc_path = self.test_dir / "test.warc"
        self.cdxj_path = self.test_dir / "test.cdxj"
    
    def tearDown(self):
        import shutil
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
    
    async def test_create_warc(self):
        with patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor') as mock_class:
            # Set up mock
            mock_processor = MagicMock()
            mock_class.return_value = mock_processor
            mock_processor.create_warc.return_value = str(self.warc_path)
            
            # Import tool (do this inside the test to keep patch context)
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools import create_warc
            
            # Call function
            result = await create_warc(
                url="https://example.com",
                output_path=str(self.warc_path)
            )
            
            # Assertions
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["warc_path"], str(self.warc_path))
            mock_processor.create_warc.assert_called_once()

# Run async tests
def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(WebArchiveToolsTest)
    
    # Create a test runner that will run the async tests
    class AsyncioTestRunner:
        def run(self, test):
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(test)
    
    runner = AsyncioTestRunner()
    result = runner.run(suite)
    
    print(f"Ran {result.testsRun} tests with {len(result.errors)} errors and {len(result.failures)} failures")

if __name__ == "__main__":
    run_tests()
```

## Conclusion

Thoroughly testing MCP tools ensures that all library features are properly exposed through the Model Context Protocol. By following the approaches in this guide, you can verify that the MCP server correctly implements the interface to the ipfs_datasets_py library functionality.
