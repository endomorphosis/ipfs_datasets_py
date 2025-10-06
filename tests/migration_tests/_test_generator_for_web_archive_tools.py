#!/usr/bin/env python3
"""
Test Generator for Web Archive Tools

This script generates tests for all web archive tools in the MCP server.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, '.')

def generate_test_for_web_archive_tool(tool_name):
    """Generate a test file for a web archive tool."""
    category = "web_archive_tools"

    test_file_content = f"""#!/usr/bin/env python3
\"\"\"
Test for the {tool_name} MCP tool.
\"\"\"

import unittest
import asyncio
from unittest.mock import patch, MagicMock
import sys
sys.path.insert(0, '.')

from ipfs_datasets_py.mcp_server.tools.{category} import {tool_name}

class Test{tool_name.title().replace('_', '')}(unittest.TestCase):
    \"\"\"Test case for the {tool_name} MCP tool.\"\"\"

    def setUp(self):
        \"\"\"Set up test fixtures.\"\"\"
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        \"\"\"Clean up after tests.\"\"\"
        self.loop.close()

    def async_test(self, coro):
        \"\"\"Helper to run async tests.\"\"\"
        return self.loop.run_until_complete(coro)

    @patch('ipfs_datasets_py.web_archive_utils.WebArchiveProcessor')
    def test_{tool_name}_basic(self, mock_processor_class):
        \"\"\"Test basic functionality of {tool_name}.\"\"\"
        # Setup mock
        mock_processor = MagicMock()
        mock_processor_class.return_value = mock_processor

        # Set up the expected return value based on the tool
        if '{tool_name}' == 'create_warc':
            mock_processor.create_warc.return_value = {{
                'status': 'success',
                'warc_path': '/tmp/test.warc',
                'urls_processed': 1
            }}

            # Call the function under test
            result = {tool_name}('https://example.com', '/tmp/test.warc')

        elif '{tool_name}' == 'extract_links_from_warc':
            mock_processor.extract_links_from_warc.return_value = {{
                'links': ['https://example.com/page1', 'https://example.com/page2']
            }}

            # Call the function under test
            result = {tool_name}('/tmp/test.warc')

        elif '{tool_name}' == 'extract_metadata_from_warc':
            mock_processor.extract_metadata_from_warc.return_value = [
                {{'uri': 'https://example.com', 'metadata': {{'title': 'Example'}}}}
            ]

            # Call the function under test
            result = {tool_name}('/tmp/test.warc')

        elif '{tool_name}' == 'extract_text_from_warc':
            mock_processor.extract_text_from_warc.return_value = [
                {{'uri': 'https://example.com', 'text': 'Example text'}}
            ]

            # Call the function under test
            result = {tool_name}('/tmp/test.warc')

        elif '{tool_name}' == 'index_warc':
            mock_processor.index_warc.return_value = {{
                'status': 'success',
                'indexed_records': 5
            }}

            # Call the function under test
            result = {tool_name}('/tmp/test.warc')

        elif '{tool_name}' == 'extract_dataset_from_cdxj':
            mock_processor.extract_dataset_from_cdxj.return_value = {{
                'status': 'success',
                'records': 5
            }}

            # Call the function under test
            result = {tool_name}('/tmp/test.cdxj')

        else:
            # Generic mock for any other tools
            mock_result = {{'status': 'success'}}
            mock_processor.{tool_name}.return_value = mock_result

            # Call the function under test (adjust parameters as needed)
            result = {tool_name}('/tmp/test.warc')

        # Assertions
        self.assertEqual(result['status'], 'success')

if __name__ == '__main__':
    unittest.main()
"""

    test_file_path = Path(f"test/test_mcp_{tool_name}.py")

    # Create the test directory if it doesn't exist
    test_file_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the test file
    with open(test_file_path, 'w') as f:
        f.write(test_file_content)

    print(f"Generated test file: {test_file_path}")
    return test_file_path

def main():
    """Generate tests for all web archive tools."""
    web_archive_tools_dir = Path("ipfs_datasets_py/mcp_server/tools/web_archive_tools")

    if not web_archive_tools_dir.exists():
        print(f"Error: Web archive tools directory not found at {web_archive_tools_dir}")
        return

    # Find all web archive tool modules
    tool_files = [f for f in web_archive_tools_dir.glob('*.py')
                 if f.is_file() and not f.name.startswith('__')]

    print(f"Found {len(tool_files)} web archive tool files:")
    for tool_file in tool_files:
        tool_name = tool_file.stem
        print(f"- {tool_name}")

        # Check if a test file already exists
        test_file_path = Path(f"test/test_mcp_{tool_name}.py")
        if test_file_path.exists():
            print(f"  Test file already exists: {test_file_path}")
        else:
            # Generate a test file
            generate_test_for_web_archive_tool(tool_name)

if __name__ == "__main__":
    main()
