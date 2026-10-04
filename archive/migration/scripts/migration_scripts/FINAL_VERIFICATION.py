#!/usr/bin/env python3
"""
Final MCP Server Verification and Restart Instructions
"""

import sys
from pathlib import Path


def verify_server_readiness():
    print("🔍 Final MCP Server Verification")
    print("=" * 50)

    all_good = True

    # Check VS Code configuration
    config_path = Path(".vscode/mcp_config.json")
    if config_path.exists():
        print("✅ VS Code MCP configuration: Found")
        try:
            import json

            with open(config_path) as f:
                config = json.load(f)
            if "mcpServers" in config and "ipfs-datasets" in config["mcpServers"]:
                print("✅ MCP server configuration: Valid")
            else:
                print("❌ MCP server configuration: Invalid structure")
                all_good = False
        except Exception as e:
            print(f"❌ MCP configuration error: {e}")
            all_good = False
    else:
        print("❌ VS Code MCP configuration: Missing")
        all_good = False

    # Check requirements.txt
    req_path = Path("requirements.txt")
    if req_path.exists():
        print("✅ requirements.txt: Found")
    else:
        print("❌ requirements.txt: Missing")
        all_good = False

    # Check server module
    try:
        sys.path.insert(0, str(Path.cwd()))
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

        print("✅ MCP server module: Imports successfully")
    except Exception as e:
        print(f"❌ MCP server module: Import failed - {e}")
        all_good = False

    # Check key tools
    tool_checks = [
        ("load_dataset", "ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset"),
        ("save_dataset", "ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset"),
        ("process_dataset", "ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset"),
        ("test_generator", "ipfs_datasets_py.mcp_server.tools.development_tools.test_generator"),
    ]

    for tool_name, module_path in tool_checks:
        try:
            module = __import__(module_path, fromlist=[tool_name])
            if hasattr(module, tool_name):
                print(f"✅ {tool_name}: Available")
            else:
                print(f"❌ {tool_name}: Function not found")
                all_good = False
        except Exception as e:
            print(f"❌ {tool_name}: Import failed - {e}")
            all_good = False

    print("\n" + "=" * 50)

    if all_good:
        print("🎉 ALL CHECKS PASSED!")
        print("\n🔄 READY TO RESTART MCP SERVER")
        print_restart_instructions()
    else:
        print("⚠️ Some issues found - please address before restart")

    return all_good


def print_restart_instructions():
    print("\n📋 VS CODE MCP SERVER RESTART INSTRUCTIONS:")
    print("=" * 50)

    print("\n1. RESTART MCP SERVER:")
    print("   • Press Ctrl+Shift+P (or Cmd+Shift+P on Mac)")
    print("   • Type: 'MCP: Restart All Servers'")
    print("   • Press Enter")
    print("   • Watch for any error messages in VS Code terminal")

    print("\n2. VERIFY SERVER IS RUNNING:")
    print("   • Open a new chat window in VS Code")
    print("   • Ask: 'What MCP tools are available?'")
    print("   • Should see tools like load_dataset, save_dataset, etc.")

    print("\n3. TEST INPUT VALIDATION:")
    print("   • Ask: 'Load dataset from test.py'")
    print("   • Expected: Error about Python files not being valid")
    print("   • Ask: 'Save dataset to output.py'")
    print("   • Expected: Error about executable file destinations")

    print("\n4. SUCCESS INDICATORS:")
    print("   ✓ Server restarts without errors")
    print("   ✓ 9+ MCP tools are listed")
    print("   ✓ Input validation rejects invalid requests")
    print("   ✓ Can successfully use tools for valid operations")

    print("\n🏁 MIGRATION COMPLETE WHEN ALL ABOVE WORK!")


if __name__ == "__main__":
    verify_server_readiness()
