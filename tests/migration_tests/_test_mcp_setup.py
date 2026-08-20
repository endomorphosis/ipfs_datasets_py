#!/usr/bin/env python3
"""
Test script to verify MCP server setup and configuration.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_imports():
    """Test all necessary imports."""
    print("🧪 Testing MCP Server Setup...")

    try:
        print("  ✓ Testing basic Python imports...")
        import json
        import anyio

        print("  ✓ Basic imports successful")

        print("  ✓ Testing project imports...")
        from ipfs_datasets_py.mcp_server.configs import Configs, load_config_from_yaml

        print("  ✓ MCP configs imported")

        from ipfs_datasets_py.mcp_server.simple_server import SimpleIPFSDatasetsMCPServer

        print("  ✓ Simple MCP server imported")

        print("  ✓ Testing tool imports...")
        from ipfs_datasets_py.mcp_server.tools import dataset_tools

        print("  ✓ Dataset tools imported")

        return True

    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_server_creation():
    """Test server creation and tool registration."""
    try:
        print("  ✓ Testing server creation...")
        from ipfs_datasets_py.mcp_server.simple_server import SimpleIPFSDatasetsMCPServer
        from ipfs_datasets_py.mcp_server.configs import load_config_from_yaml

        configs = load_config_from_yaml(None)
        server = SimpleIPFSDatasetsMCPServer(configs)
        print("  ✓ Server created successfully")

        print("  ✓ Testing tool registration...")
        server.register_tools()
        print(f"  ✓ {len(server.tools)} tools registered successfully")

        # List some tools
        tool_names = list(server.tools.keys())[:5]
        print(f"  ✓ Sample tools: {tool_names}")

        return True

    except Exception as e:
        print(f"  ✗ Server creation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_vs_code_config():
    """Test VS Code configuration files."""
    try:
        print("  ✓ Testing VS Code configuration...")

        vscode_dir = Path(".vscode")
        if vscode_dir.exists():
            print("  ✓ .vscode directory exists")
        else:
            print("  ✗ .vscode directory not found")
            return False

        settings_file = vscode_dir / "settings.json"
        if settings_file.exists():
            print("  ✓ settings.json exists")
            with open(settings_file) as f:
                import json

                settings = json.load(f)
                if "mcp.servers" in settings:
                    print("  ✓ MCP servers configured")
                if "copilot-mcp.servers" in settings:
                    print("  ✓ Copilot MCP servers configured")
        else:
            print("  ✗ settings.json not found")
            return False

        startup_script = Path("start_mcp_server.sh")
        if startup_script.exists():
            print("  ✓ MCP startup script exists")
        else:
            print("  ✗ MCP startup script not found")
            return False

        return True

    except Exception as e:
        print(f"  ✗ VS Code config test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("🚀 IPFS Datasets MCP Server Setup Verification")
    print("=" * 50)

    success_count = 0
    total_tests = 3

    # Test 1: Imports
    print("\n📦 Test 1: Module Imports")
    if test_imports():
        success_count += 1

    # Test 2: Server Creation
    print("\n🛠️  Test 2: Server Creation")
    if test_server_creation():
        success_count += 1

    # Test 3: VS Code Configuration
    print("\n⚙️  Test 3: VS Code Configuration")
    if test_vs_code_config():
        success_count += 1

    # Summary
    print("\n" + "=" * 50)
    print(f"📊 Test Summary: {success_count}/{total_tests} tests passed")

    if success_count == total_tests:
        print("🎉 All tests passed! MCP server is ready for VS Code Copilot")
        print("\n🚀 Next steps:")
        print("  1. Start MCP server: ./start_mcp_server.sh")
        print("  2. Open VS Code Copilot Chat")
        print("  3. Ask: 'What IPFS dataset tools are available?'")
        return True
    else:
        print(f"❌ {total_tests - success_count} tests failed. Please check the errors above.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
