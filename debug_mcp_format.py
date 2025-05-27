#!/usr/bin/env python3
"""
Check what MCP format VS Code Copilot extension expects
"""

import json
from pathlib import Path

def show_current_config():
    """Show the current MCP configuration in a clean format"""
    
    print("🔍 Current MCP Configuration Analysis")
    print("=" * 50)
    
    # Read user settings
    user_settings_path = Path.home() / ".config" / "Code - Insiders" / "User" / "settings.json"
    
    if user_settings_path.exists():
        try:
            with open(user_settings_path, 'r') as f:
                content = f.read()
                
            print("📋 User Settings Structure:")
            print("-" * 30)
            
            # Show MCP-related configuration
            if '"mcp"' in content:
                print("✅ Found 'mcp' configuration")
            if '"copilot-mcp.servers"' in content:
                print("✅ Found 'copilot-mcp.servers' configuration")
            if '"copilot-mcp"' in content and '"servers"' in content:
                print("⚠️  Found nested 'copilot-mcp.servers' format")
                
            # Extract the relevant sections
            lines = content.split('\n')
            in_mcp = False
            in_copilot_mcp = False
            mcp_lines = []
            copilot_mcp_lines = []
            
            for i, line in enumerate(lines):
                if '"mcp":' in line:
                    in_mcp = True
                elif '"copilot-mcp.servers":' in line:
                    in_copilot_mcp = True
                elif line.strip().startswith('}') and in_mcp:
                    mcp_lines.append(line)
                    in_mcp = False
                elif line.strip().startswith('}') and in_copilot_mcp:
                    copilot_mcp_lines.append(line)
                    in_copilot_mcp = False
                elif in_mcp:
                    mcp_lines.append(line)
                elif in_copilot_mcp:
                    copilot_mcp_lines.append(line)
                    
            if mcp_lines:
                print(f"\n📝 MCP Configuration:")
                for line in mcp_lines[:10]:  # Show first 10 lines
                    print(f"   {line}")
                    
            if copilot_mcp_lines:
                print(f"\n📝 Copilot MCP Configuration:")
                for line in copilot_mcp_lines[:10]:  # Show first 10 lines
                    print(f"   {line}")
                    
        except Exception as e:
            print(f"❌ Error reading settings: {e}")
    
    print(f"\n💡 Recommendations:")
    print("1. The format should be 'copilot-mcp.servers' (flat, not nested)")
    print("2. Each server should have 'command', 'args', 'cwd', and 'env'")
    print("3. Make sure there are no port conflicts between servers")
    print("4. Restart VS Code after making changes")

if __name__ == "__main__":
    show_current_config()
