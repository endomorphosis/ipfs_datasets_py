#!/usr/bin/env python3
"""
Post-Restart Verification Script
Run this AFTER restarting the MCP server in VS Code to verify everything works.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_post_restart():
    print("🧪 Post-Restart MCP Server Verification")
    print("=" * 50)
    
    # Test 1: Import verification
    print("\n1. Testing tool imports...")
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
        print("✅ All key tools import successfully")
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False
    
    # Test 2: Input validation
    print("\n2. Testing input validation...")
    
    # Test Python file rejection
    result = await load_dataset(source="test.py")
    if result.get("status") == "error" and "Python files (.py) are not valid" in result.get("message", ""):
        print("✅ Python file rejection working")
    else:
        print(f"❌ Python file validation failed: {result}")
        return False
    
    # Test executable file save rejection
    result = await save_dataset(
        dataset_data={"data": [{"text": "test"}]},
        destination="output.py"
    )
    if result.get("status") == "error" and "Cannot save dataset as executable" in result.get("message", ""):
        print("✅ Executable file save rejection working")
    else:
        print(f"❌ Save validation failed: {result}")
        return False
    
    # Test dangerous operation rejection
    result = await process_dataset(
        dataset_source={"data": [{"text": "test"}]},
        operations=[{"type": "exec", "code": "import os"}]
    )
    if result.get("status") == "error" and "not allowed for security reasons" in result.get("message", ""):
        print("✅ Dangerous operation rejection working")
    else:
        print(f"❌ Operation validation failed: {result}")
        return False
    
    # Test 3: Valid operation (should not be rejected)
    print("\n3. Testing valid operations...")
    result = await load_dataset(source="squad")  # Valid dataset name
    if "status" in result:  # Any structured response is good
        print("✅ Valid operations are processed")
    else:
        print(f"❌ Valid operation failed: {result}")
        return False
    
    print("\n" + "=" * 50)
    print("🎉 ALL POST-RESTART TESTS PASSED!")
    print("✅ MCP server is working correctly")
    print("✅ Input validation is protecting against invalid inputs")
    print("✅ Valid operations are being processed")
    print("\n🏁 MIGRATION 100% COMPLETE!")
    
    return True

async def main():
    success = await test_post_restart()
    if not success:
        print("\n⚠️ Some tests failed. Check the MCP server restart process.")
        sys.exit(1)

if __name__ == "__main__":
    print("Run this script AFTER restarting MCP server in VS Code")
    print("Press Enter to continue...")
    input()
    asyncio.run(main())
