#!/usr/bin/env python3

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from ipfs_datasets_py.mcp_server.server import import_tools_from_directory

tools_path = Path('ipfs_datasets_py/mcp_server/tools/development_tools')
tools = import_tools_from_directory(tools_path)

expected_mcp_functions = [
    'test_generator',
    'codebase_search',
    'documentation_generator',
    'lint_python_codebase',
    'run_comprehensive_tests'
]

print("MCP Function Discovery Test")
print("=" * 40)

for func_name in expected_mcp_functions:
    if func_name in tools:
        print(f"✓ {func_name} - FOUND")
    else:
        print(f"✗ {func_name} - MISSING")

print(f"\nSummary:")
print(f"Expected: {len(expected_mcp_functions)}")
print(f"Found: {len([f for f in expected_mcp_functions if f in tools])}")
print(f"Discovery working: {len([f for f in expected_mcp_functions if f in tools]) == len(expected_mcp_functions)}")
