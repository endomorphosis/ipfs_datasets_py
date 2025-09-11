#!/usr/bin/env python3

import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path.cwd()))

print("Starting development tools import test...")

try:
    print("1. Testing base_tool import...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseDevelopmentTool
    print("   ✓ base_tool imported")

    print("2. Testing config import...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.config import get_config
    print("   ✓ config imported")

    print("3. Testing test_generator import...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator
    print("   ✓ test_generator imported")

    print("4. Testing codebase_search import...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
    print("   ✓ codebase_search imported")

    print("5. Testing documentation_generator import...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import documentation_generator
    print("   ✓ documentation_generator imported")

    print("6. Testing linting_tools import...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase
    print("   ✓ lint_python_codebase imported")

    print("7. Testing test_runner import...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
    print("   ✓ run_comprehensive_tests imported")

    print("\n✓ All development tools imported successfully!")

    # Test the tool discovery mechanism
    print("\n8. Testing tool discovery...")
    from ipfs_datasets_py.mcp_server.server import import_tools_from_directory
    tools_path = Path('ipfs_datasets_py/mcp_server/tools/development_tools')
    tools = import_tools_from_directory(tools_path)
    print(f"   Found {len(tools)} tools:")
    for tool_name in sorted(tools.keys()):
        print(f"     - {tool_name}")

    print("\n✓ All tests completed successfully!")

except Exception as e:
    print(f"\n✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
