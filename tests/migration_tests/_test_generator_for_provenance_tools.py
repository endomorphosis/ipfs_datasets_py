#!/usr/bin/env python3
"""
Test Generator for Provenance Tools

This script generates tests for all provenance tools in the MCP server.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, '.')

def generate_test_for_provenance_tool(tool_name):
    """Generate a test file for a provenance tool."""
    category = "provenance_tools"

    test_file_content = f"""#!/usr/bin/env python3
\"\"\"
Test for the {tool_name} MCP tool.
\"\"\"

import unittest
import anyio
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

    @patch('ipfs_datasets_py.data_provenance_enhanced.EnhancedProvenanceManager')
    def test_{tool_name}_basic(self, mock_provenance_manager_class):
        \"\"\"Test basic functionality of {tool_name}.\"\"\"
        # Setup mock
        mock_manager = MagicMock()
        mock_provenance_manager_class.return_value = mock_manager

        # Set up the expected return value based on the tool
        if '{tool_name}' == 'record_provenance':
            mock_manager.add_record.return_value = "prov_record_123"

            # Call the function under test
            async def run_test():
                result = await {tool_name}(
                    dataset_id="test_dataset",
                    operation="test_operation"
                )
                self.assertEqual(result['status'], 'success')
                self.assertEqual(result['provenance_id'], 'prov_record_123')

            self.async_test(run_test())

        else:
            # Generic mock for any other provenance tools
            mock_manager.{tool_name}.return_value = {{'status': 'success', 'id': 'prov_123'}}

            # Call the function under test
            async def run_test():
                result = await {tool_name}('test_dataset')
                self.assertEqual(result['status'], 'success')

            self.async_test(run_test())

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
    """Generate tests for all provenance tools."""
    provenance_tools_dir = Path("ipfs_datasets_py/mcp_server/tools/provenance_tools")

    if not provenance_tools_dir.exists():
        print(f"Error: Provenance tools directory not found at {provenance_tools_dir}")
        return

    # Find all provenance tool modules
    tool_files = [f for f in provenance_tools_dir.glob('*.py')
                 if f.is_file() and not f.name.startswith('__')]

    print(f"Found {len(tool_files)} provenance tool files:")
    for tool_file in tool_files:
        tool_name = tool_file.stem
        print(f"- {tool_name}")

        # Check if a test file already exists
        test_file_path = Path(f"test/test_mcp_{tool_name}.py")
        if test_file_path.exists():
            print(f"  Test file already exists: {test_file_path}")
        else:
            # Generate a test file
            generate_test_for_provenance_tool(tool_name)

if __name__ == "__main__":
    main()
