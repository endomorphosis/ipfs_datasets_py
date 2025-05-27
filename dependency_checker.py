#!/usr/bin/env python3
"""
Dependency Checker for MCP Server
"""

import sys
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

def test_imports():
    """Test various imports to identify missing dependencies."""
    
    print("🔍 Testing MCP Server Dependencies...")
    
    # Test 1: Check modelcontextprotocol package
    try:
        from modelcontextprotocol.server import FastMCP
        print("✅ modelcontextprotocol package available")
    except ImportError as e:
        print(f"❌ modelcontextprotocol missing: {e}")
        print("   Install with: pip install modelcontextprotocol")
    
    # Test 2: Check basic ipfs_datasets_py imports
    try:
        import ipfs_datasets_py
        print("✅ ipfs_datasets_py package importable")
    except ImportError as e:
        print(f"❌ ipfs_datasets_py import failed: {e}")
    
    # Test 3: Check configs
    try:
        from ipfs_datasets_py.mcp_server.configs import Configs
        print("✅ Configs import successful")
    except ImportError as e:
        print(f"❌ Configs import failed: {e}")
        traceback.print_exc()
    
    # Test 4: Check logger
    try:
        from ipfs_datasets_py.mcp_server.logger import logger
        print("✅ Logger import successful")
    except ImportError as e:
        print(f"❌ Logger import failed: {e}")
        traceback.print_exc()
    
    # Test 5: Check a simple tool
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        print("✅ Sample tool import successful")
    except ImportError as e:
        print(f"❌ Sample tool import failed: {e}")
        traceback.print_exc()
    
    # Test 6: Check datasets library (used by tools)
    try:
        import datasets
        print("✅ Hugging Face datasets library available")
    except ImportError as e:
        print(f"❌ datasets library missing: {e}")
        print("   Install with: pip install datasets")
    
    # Test 7: Check other common dependencies
    deps_to_check = [
        ("requests", "pip install requests"),
        ("aiohttp", "pip install aiohttp"),
        ("pydantic", "pip install pydantic"),
        ("yaml", "pip install PyYAML"),
    ]
    
    for dep, install_cmd in deps_to_check:
        try:
            __import__(dep)
            print(f"✅ {dep} available")
        except ImportError:
            print(f"❌ {dep} missing - {install_cmd}")

if __name__ == "__main__":
    test_imports()
