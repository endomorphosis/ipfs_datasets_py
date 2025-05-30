#!/usr/bin/env python3
"""
Test Generator for Security Tools

This script generates tests for all security tools in the MCP server.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, '.')

def generate_test_for_security_tool(tool_name):
    """Generate a test file for a security tool."""
    category = "security_tools"

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

    @patch('ipfs_datasets_py.security.SecurityManager')
    def test_{tool_name}_basic(self, mock_security_manager_class):
        \"\"\"Test basic functionality of {tool_name}.\"\"\"
        # Setup mock
        mock_security_manager = MagicMock()
        mock_security_manager_class.return_value = mock_security_manager

        # Set up the expected return value based on the tool
        if '{tool_name}' == 'check_access_permission':
            mock_security_manager.check_access.return_value = True

            # Call the function under test
            async def run_test():
                result = await {tool_name}('test_resource', 'test_user')
                self.assertEqual(result['status'], 'success')
                self.assertEqual(result['allowed'], True)

            self.async_test(run_test())
        else:
            # Generic mock for any other tools
            mock_result = {{'status': 'success'}}
            mock_security_manager.{tool_name}.return_value = mock_result

            # Call the function under test (adjust parameters as needed)
            async def run_test():
                result = await {tool_name}('test_resource')
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
    """Generate tests for all security tools."""
    security_tools_dir = Path("ipfs_datasets_py/mcp_server/tools/security_tools")

    if not security_tools_dir.exists():
        print(f"Error: Security tools directory not found at {security_tools_dir}")
        return

    # Find all security tool modules
    tool_files = [f for f in security_tools_dir.glob('*.py')
                 if f.is_file() and not f.name.startswith('__')]

    print(f"Found {len(tool_files)} security tool files:")
    for tool_file in tool_files:
        tool_name = tool_file.stem
        print(f"- {tool_name}")

        # Check if a test file already exists
        test_file_path = Path(f"test/test_mcp_{tool_name}.py")
        if test_file_path.exists():
            print(f"  Test file already exists: {test_file_path}")
        else:
            # Generate a test file
            generate_test_for_security_tool(tool_name)

if __name__ == "__main__":
    main()
