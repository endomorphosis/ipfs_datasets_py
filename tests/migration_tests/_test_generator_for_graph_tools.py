#!/usr/bin/env python3
"""
Test Generator for Graph Tools

This script generates tests for all graph tools in the MCP server.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, '.')

def generate_test_for_graph_tool(tool_name):
    """Generate a test file for a graph tool."""
    category = "graph_tools"

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

    @patch('ipfs_datasets_py.rag.rag_query_optimizer.GraphRAGProcessor')
    def test_{tool_name}_basic(self, mock_graph_processor_class):
        \"\"\"Test basic functionality of {tool_name}.\"\"\"
        # Setup mock
        mock_processor = MagicMock()
        mock_graph_processor_class.return_value = mock_processor

        # Set up the expected return value based on the tool
        if '{tool_name}' == 'query_knowledge_graph':
            mock_processor.query_graph.return_value = {{
                'results': [
                    {{'subject': 'entity1', 'predicate': 'relates_to', 'object': 'entity2'}},
                    {{'subject': 'entity2', 'predicate': 'type', 'object': 'Person'}}
                ]
            }}

            # Call the function under test
            async def run_test():
                result = await {tool_name}('test_graph', 'MATCH (n) RETURN n LIMIT 10')
                self.assertEqual(result['status'], 'success')
                self.assertIn('results', result)
                self.assertEqual(len(result['results']), 2)

            self.async_test(run_test())

        else:
            # Generic mock for any other tools
            mock_processor.{tool_name.replace('knowledge_graph', 'graph')}.return_value = {{
                'status': 'success',
                'graph_id': 'test_graph_id'
            }}

            # Call the function under test
            async def run_test():
                result = await {tool_name}('test_input')
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
    """Generate tests for all graph tools."""
    graph_tools_dir = Path("ipfs_datasets_py/mcp_server/tools/graph_tools")

    if not graph_tools_dir.exists():
        print(f"Error: Graph tools directory not found at {graph_tools_dir}")
        return

    # Find all graph tool modules
    tool_files = [f for f in graph_tools_dir.glob('*.py')
                 if f.is_file() and not f.name.startswith('__')]

    print(f"Found {len(tool_files)} graph tool files:")
    for tool_file in tool_files:
        tool_name = tool_file.stem
        print(f"- {tool_name}")

        # Check if a test file already exists
        test_file_path = Path(f"test/test_mcp_{tool_name}.py")
        if test_file_path.exists():
            print(f"  Test file already exists: {test_file_path}")
        else:
            # Generate a test file
            generate_test_for_graph_tool(tool_name)

if __name__ == "__main__":
    main()
