#!/usr/bin/env python3
"""
Simple diagnostic that writes results to a file
"""

import sys
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

def main():
    results = []
    results.append("=== MCP Server Diagnostic Results ===")
    
    # Test modelcontextprotocol
    try:
        from modelcontextprotocol.server import FastMCP
        results.append("✅ modelcontextprotocol package available")
    except ImportError as e:
        results.append(f"❌ modelcontextprotocol missing: {e}")
    
    # Test configs
    try:
        from ipfs_datasets_py.mcp_server.configs import Configs
        results.append("✅ Configs import successful")
    except Exception as e:
        results.append(f"❌ Configs import failed: {e}")
        results.append(f"Traceback: {traceback.format_exc()}")
    
    # Test datasets
    try:
        import datasets
        results.append("✅ datasets library available")
    except ImportError as e:
        results.append(f"❌ datasets missing: {e}")
    
    # Write results to file
    with open("diagnostic_results.txt", "w") as f:
        for result in results:
            f.write(result + "\n")
    
    return len(results)

if __name__ == "__main__":
    count = main()
    # Also try to print something
    try:
        print(f"Diagnostic complete - {count} results written to diagnostic_results.txt")
    except:
        pass
