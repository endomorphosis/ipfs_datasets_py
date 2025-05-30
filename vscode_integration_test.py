#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
VS Code Integration Test for Development Tools

This script tests if the development tools from claudes_toolbox
are properly integrated with VS Code Copilot Chat through the MCP server.

To use:
1. Make sure .vscode/mcp_settings.json is properly configured
2. Start the IPFS Datasets MCP server with development tools enabled
3. Run this test from VS Code to verify integration
"""

import os
import sys
import json
import time
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_vscode_integration():
    """Test VS Code integration with development tools."""
    print("=" * 50)
    print("VS Code Integration Test for Development Tools")
    print("=" * 50)

    # Step 1: Check VS Code settings
    print("\n1. Checking VS Code MCP settings...")
    vscode_dir = Path(__file__).parent / ".vscode"
    settings_path = vscode_dir / "mcp_settings.json"

    if not settings_path.exists():
        print("❌ Error: VS Code MCP settings file not found!")
        print(f"   Expected path: {settings_path}")
        print("   Please create the file with proper MCP server configuration.")
        return False

    try:
        with open(settings_path, 'r') as f:
            settings = json.load(f)

        if 'mcpServers' not in settings:
            print("❌ Error: mcpServers section missing in MCP settings!")
            return False

        if 'ipfs_datasets' not in settings['mcpServers']:
            print("❌ Error: ipfs_datasets server configuration missing!")
            return False

        print("✅ VS Code MCP settings found and validated")
        print(f"   Server command: {settings['mcpServers']['ipfs_datasets']['command']} {' '.join(settings['mcpServers']['ipfs_datasets']['args'])}")

    except Exception as e:
        print(f"❌ Error reading VS Code settings: {e}")
        return False

    # Step 2: Test MCP server setup
    print("\n2. Testing MCP server setup...")
    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        server = IPFSDatasetsMCPServer()
        print("✅ MCP server imported successfully")
    except Exception as e:
        print(f"❌ Error importing MCP server: {e}")
        return False

    # Step 3: Verify development tools are available
    print("\n3. Verifying development tools availability...")
    try:
        server.register_tools()

        expected_tools = [
            'test_generator',
            'codebase_search',
            'documentation_generator',
            'lint_python_codebase',
            'run_comprehensive_tests'
        ]

        found_tools = [name for name in server.tools.keys() if name in expected_tools]

        if len(found_tools) == len(expected_tools):
            print(f"✅ All {len(expected_tools)} development tools registered successfully")
        else:
            missing = set(expected_tools) - set(found_tools)
            print(f"⚠️ Only {len(found_tools)}/{len(expected_tools)} development tools found")
            print(f"   Missing tools: {missing}")
    except Exception as e:
        print(f"❌ Error registering tools: {e}")
        return False

    # Step 4: Prepare for VS Code integration test
    print("\n4. Preparing for VS Code integration test...")

    # Create a test file that will be used by VS Code Copilot Chat
    test_marker = f"test_marker_{int(time.time())}"
    test_file_path = Path(__file__).parent / "vscode_test_marker.py"

    try:
        with open(test_file_path, 'w') as f:
            f.write(f"""# VS Code Integration Test Marker
# Generated at {time.ctime()}
# Do not modify this file - it's used for VS Code Copilot Chat testing

TEST_MARKER = "{test_marker}"

# When testing with VS Code Copilot Chat, ask it to:
# 1. Search for this marker using codebase_search
# 2. Generate documentation for this file using documentation_generator
# 3. Analyze this file using lint_python_codebase
""")
        print(f"✅ Test marker file created: {test_file_path}")
    except Exception as e:
        print(f"❌ Error creating test file: {e}")
        return False

    # Step 5: Instructions for VS Code test
    print("\n" + "=" * 50)
    print("VS CODE INTEGRATION TEST INSTRUCTIONS")
    print("=" * 50)
    print("""
To complete the VS Code integration test:

1. Start the MCP Server:
   - Open a terminal and run:
     python -m ipfs_datasets_py.mcp_server

2. Open VS Code with the IPFS Datasets Workspace:
   - Make sure VS Code Copilot Chat is installed and authenticated

3. Test each development tool with Copilot Chat:
   - Ask: "Search for the test marker in vscode_test_marker.py using codebase_search"
   - Ask: "Generate documentation for vscode_test_marker.py using documentation_generator"
   - Ask: "Analyze vscode_test_marker.py using lint_python_codebase"
   - Ask: "Create a test for vscode_test_marker.py using test_generator"
   - Ask: "Run tests for the project using run_comprehensive_tests"

4. Record Results:
   - For each tool, note if Copilot Chat successfully used the tool
   - Record any errors or unexpected behavior
""")

    print("\n✅ VS Code integration test setup complete!")
    print(f"Test marker: {test_marker}")

    return True

def create_test_results_template():
    """Create a template for recording test results."""
    results_path = Path(__file__).parent / "vscode_integration_results.md"

    with open(results_path, 'w') as f:
        f.write("""# VS Code Integration Test Results

## Test Environment
- Date: [DATE]
- VS Code Version: [VERSION]
- Copilot Chat Version: [VERSION]
- IPFS Datasets Version: [VERSION]

## Development Tools Test Results

| Tool | Status | Notes |
|------|--------|-------|
| codebase_search | ⬜ | |
| documentation_generator | ⬜ | |
| lint_python_codebase | ⬜ | |
| test_generator | ⬜ | |
| run_comprehensive_tests | ⬜ | |

Legend:
- ✅ Working correctly
- ⚠️ Partially working
- ❌ Not working
- ⬜ Not tested

## Issues Encountered
[Document any issues here]

## Next Steps
[Document next steps here]
""")

    print(f"📝 Test results template created: {results_path}")
    print("   Fill this out after completing the VS Code integration test")

if __name__ == "__main__":
    success = test_vscode_integration()
    create_test_results_template()

    if success:
        print("\n🚀 Ready to proceed with VS Code integration testing!")
        print("Once testing is complete, update the results in vscode_integration_results.md")
    else:
        print("\n⚠️ Please fix the issues before proceeding with VS Code integration testing")

    sys.exit(0 if success else 1)
