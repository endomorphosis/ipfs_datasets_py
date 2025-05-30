#!/usr/bin/env python3
"""
Quick import test for tools that were previously failing.
"""

import sys
import traceback
sys.path.insert(0, '.')

def test_import(module_path, function_name):
    """Test importing a specific function from a module."""
    try:
        print(f"Testing import: {module_path}.{function_name}")
        module = __import__(module_path, fromlist=[function_name])
        func = getattr(module, function_name)
        print(f"✓ Successfully imported {function_name}")
        return True
    except Exception as e:
        print(f"✗ Failed to import {function_name}: {e}")
        print(f"  Traceback: {traceback.format_exc()}")
        return False

if __name__ == "__main__":
    imports_to_test = [
        ("ipfs_datasets_py.mcp_server.tools.security_tools", "calculate_hash"),
        ("ipfs_datasets_py.mcp_server.tools.vector_tools", "create_vector_index"),
        ("ipfs_datasets_py.mcp_server.tools.graph_tools", "create_knowledge_graph"),
        ("ipfs_datasets_py.mcp_server.tools.provenance_tools", "track_lineage"),
        ("ipfs_datasets_py.mcp_server.tools.ipfs_tools", "get_from_ipfs"),
    ]

    success_count = 0
    for module_path, function_name in imports_to_test:
        if test_import(module_path, function_name):
            success_count += 1

    print(f"\nSummary: {success_count}/{len(imports_to_test)} imports successful")
