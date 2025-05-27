#!/usr/bin/env python3
"""
Test Generator for Vector Tools

This script generates tests for all vector tools in the MCP server.
"""

import os
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.insert(0, '.')

def generate_test_for_vector_tool(tool_name):
    """Generate a test file for a vector tool."""
    category = "vector_tools"
    
    test_file_content = f"""#!/usr/bin/env python3
\"\"\"
Test for the {tool_name} MCP tool.
\"\"\"

import unittest
import asyncio
from unittest.mock import patch, MagicMock
import numpy as np
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
    
    @patch('ipfs_datasets_py.ipfs_knn_index.IPFSKnnIndex')
    def test_{tool_name}_basic(self, mock_knn_index_class):
        \"\"\"Test basic functionality of {tool_name}.\"\"\"
        # Setup mock
        mock_index = MagicMock()
        mock_knn_index_class.return_value = mock_index
        
        # Set up the expected return value based on the tool
        if '{tool_name}' == 'create_vector_index':
            mock_index.add_vectors.return_value = ['id1', 'id2']
            mock_index.index_id = 'test_index_id'
            
            # Call the function under test
            async def run_test():
                vectors = np.array([[1.0, 2.0], [3.0, 4.0]])
                result = await {tool_name}(vectors)
                self.assertEqual(result['status'], 'success')
                self.assertEqual(result['index_id'], 'test_index_id')
            
            self.async_test(run_test())
            
        elif '{tool_name}' == 'search_vector_index':
            mock_index.search.return_value = [
                {{'id': 'id1', 'score': 0.95, 'metadata': {{}}}},
                {{'id': 'id2', 'score': 0.85, 'metadata': {{}}}}
            ]
            
            # Call the function under test
            async def run_test():
                query_vector = np.array([1.0, 2.0])
                result = await {tool_name}('test_index_id', query_vector)
                self.assertEqual(result['status'], 'success')
                self.assertEqual(len(result['matches']), 2)
            
            self.async_test(run_test())
            
        else:
            # Generic mock for any other tools
            async def run_test():
                result = await {tool_name}(np.array([[1.0, 2.0]]))
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
    """Generate tests for all vector tools."""
    vector_tools_dir = Path("ipfs_datasets_py/mcp_server/tools/vector_tools")
    
    if not vector_tools_dir.exists():
        print(f"Error: Vector tools directory not found at {vector_tools_dir}")
        return
    
    # Find all vector tool modules
    tool_files = [f for f in vector_tools_dir.glob('*.py') 
                 if f.is_file() and not f.name.startswith('__')]
    
    print(f"Found {len(tool_files)} vector tool files:")
    for tool_file in tool_files:
        tool_name = tool_file.stem
        print(f"- {tool_name}")
        
        # Check if a test file already exists
        test_file_path = Path(f"test/test_mcp_{tool_name}.py")
        if test_file_path.exists():
            print(f"  Test file already exists: {test_file_path}")
        else:
            # Generate a test file
            generate_test_for_vector_tool(tool_name)

if __name__ == "__main__":
    main()
