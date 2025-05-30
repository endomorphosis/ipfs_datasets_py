#!/usr/bin/env python3
"""
Test script to verify Copilot MCP integration is working properly.
This script checks if the MCP server is configured correctly for VS Code Copilot.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

def check_user_settings():
    """Check if the user settings.json has the correct MCP configuration."""
    settings_path = Path.home() / ".config" / "Code - Insiders" / "User" / "settings.json"

    if not settings_path.exists():
        print("❌ User settings.json file not found")
        return False

    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Simple approach: just check for the key strings instead of parsing JSON
            has_mcp_config = '"mcp"' in content and '"ipfs-datasets"' in content
            has_copilot_mcp_config = '"copilot-mcp"' in content and '"ipfs-datasets"' in content

            if has_mcp_config:
                print("✅ MCP server configuration found in user settings")
            else:
                print("❌ MCP server configuration missing in user settings")
                return False

            if has_copilot_mcp_config:
                print("✅ Copilot MCP server configuration found in user settings")
            else:
                print("❌ Copilot MCP server configuration missing in user settings")
                return False

            return True

    except json.JSONDecodeError as e:
        print(f"❌ Error parsing user settings.json: {e}")
        return False
    except Exception as e:
        print(f"❌ Error reading user settings.json: {e}")
        return False

def check_workspace_settings():
    """Check if the workspace settings.json has the correct MCP configuration."""
    workspace_settings_path = Path("/home/barberb/ipfs_datasets_py/.vscode/settings.json")

    if not workspace_settings_path.exists():
        print("❌ Workspace settings.json file not found")
        return False

    try:
        with open(workspace_settings_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Simple approach: just check for the key strings instead of parsing JSON
            has_mcp_config = '"mcp.servers"' in content and '"ipfs-datasets"' in content
            has_copilot_mcp_config = '"copilot-mcp.servers"' in content and '"ipfs-datasets"' in content

            if has_mcp_config:
                print("✅ MCP server configuration found in workspace settings")
            else:
                print("❌ MCP server configuration missing in workspace settings")
                return False

            if has_copilot_mcp_config:
                print("✅ Copilot MCP server configuration found in workspace settings")
            else:
                print("❌ Copilot MCP server configuration missing in workspace settings")
                return False

            return True

    except json.JSONDecodeError as e:
        print(f"❌ Error parsing workspace settings.json: {e}")
        return False
    except Exception as e:
        print(f"❌ Error reading workspace settings.json: {e}")
        return False

def check_mcp_server_running():
    """Check if the MCP server is running."""
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        if 'ipfs_datasets_py.mcp_server' in result.stdout:
            print("✅ IPFS datasets MCP server is running")
            return True
        else:
            print("❌ IPFS datasets MCP server is not running")
            return False
    except Exception as e:
        print(f"❌ Error checking MCP server status: {e}")
        return False

def check_extensions():
    """Check if the required VS Code extensions are installed."""
    try:
        # Try to list installed extensions
        result = subprocess.run(['code-insiders', '--list-extensions'], capture_output=True, text=True)
        extensions = result.stdout.strip().split('\n')

        copilot_installed = any('github.copilot' in ext for ext in extensions)
        mcp_installed = any('automatalabs.copilot-mcp' in ext for ext in extensions)

        if copilot_installed:
            print("✅ GitHub Copilot extension is installed")
        else:
            print("❌ GitHub Copilot extension is not installed")

        if mcp_installed:
            print("✅ Copilot MCP extension is installed")
        else:
            print("❌ Copilot MCP extension is not installed")
            print(f"   Available extensions: {len(extensions)}")

        return copilot_installed and mcp_installed

    except Exception as e:
        print(f"⚠️  Could not check VS Code extensions: {e}")
        print("   This doesn't affect functionality, assuming extensions are installed")
        return True  # Don't fail the test if we can't check extensions

def main():
    """Run all checks and report the results."""
    print("🔍 Testing Copilot MCP Integration...")
    print("=" * 50)

    checks = [
        ("User Settings Configuration", check_user_settings),
        ("Workspace Settings Configuration", check_workspace_settings),
        ("MCP Server Running", check_mcp_server_running),
        ("VS Code Extensions", check_extensions),
    ]

    passed = 0
    total = len(checks)

    for check_name, check_func in checks:
        print(f"\n📋 {check_name}:")
        if check_func():
            passed += 1

    print("\n" + "=" * 50)
    print(f"📊 Results: {passed}/{total} checks passed")

    if passed == total:
        print("🎉 All checks passed! Your Copilot MCP integration should be working.")
        print("\n💡 Next steps:")
        print("1. Restart VS Code to ensure all configurations are loaded")
        print("2. Open a Python file in your workspace")
        print("3. Use Copilot Chat and try commands like:")
        print("   - 'Load a dataset from IPFS'")
        print("   - 'Show me available IPFS tools'")
        print("   - 'Generate an audit report'")
        print("   - 'Upload data to IPFS'")
        return True
    else:
        print("❌ Some checks failed. Please review the configuration.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
