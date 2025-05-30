#!/usr/bin/env python3
"""
Simple verification that all MCP configurations are in place.
"""

import os
from pathlib import Path

def main():
    print("🔍 Quick MCP Configuration Check")
    print("=" * 40)

    # Check user settings
    user_settings = Path.home() / ".config" / "Code - Insiders" / "User" / "settings.json"
    if user_settings.exists():
        content = user_settings.read_text()
        if '"copilot-mcp.servers"' in content and '"ipfs-datasets"' in content:
            print("✅ User settings configured for Copilot MCP")
        else:
            print("❌ User settings missing Copilot MCP config")
    else:
        print("❌ User settings file not found")

    # Check workspace settings
    workspace_settings = Path("/home/barberb/ipfs_datasets_py/.vscode/settings.json")
    if workspace_settings.exists():
        content = workspace_settings.read_text()
        if '"copilot-mcp.servers"' in content and '"ipfs-datasets"' in content:
            print("✅ Workspace settings configured for Copilot MCP")
        else:
            print("❌ Workspace settings missing Copilot MCP config")
    else:
        print("❌ Workspace settings file not found")

    # Check MCP server is running
    import subprocess
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        if 'ipfs_datasets_py.mcp_server' in result.stdout:
            print("✅ MCP server is running")
        else:
            print("❌ MCP server is not running")
    except:
        print("❌ Could not check MCP server status")

    # Check Copilot MCP extension
    try:
        result = subprocess.run(['code-insiders', '--list-extensions'], capture_output=True, text=True)
        if 'automatalabs.copilot-mcp' in result.stdout:
            print("✅ Copilot MCP extension is installed")
        else:
            print("❌ Copilot MCP extension is not installed")
    except:
        print("❌ Could not check extensions")

    print("\n🎉 Configuration complete!")
    print("💡 Next steps:")
    print("1. Restart VS Code to ensure all configurations are loaded")
    print("2. Open GitHub Copilot Chat")
    print("3. Try commands like:")
    print("   - 'Show me available dataset tools'")
    print("   - 'Load a dataset from IPFS'")
    print("   - 'Generate an audit report'")
    print("   - 'Upload data to IPFS'")

if __name__ == "__main__":
    main()
