#!/usr/bin/env python3
"""
Quick validation test for the MCP server fixes.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

async def test_load_dataset_validation():
    """Test the load_dataset validation fixes."""
    print("Testing load_dataset validation...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        print("✅ load_dataset imported successfully")
        
        # Test Python file rejection
        try:
            result = await load_dataset(source="test.py")
            print("❌ FAIL: Python file was accepted")
            return False
        except ValueError as e:
            if "Python files (.py) are not valid dataset sources" in str(e):
                print("✅ PASS: Python file correctly rejected")
                return True
            else:
                print(f"⚠️ WARNING: Rejected but unexpected message: {e}")
                return False
        except Exception as e:
            print(f"❌ ERROR: Unexpected exception: {e}")
            return False
            
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}")
        return False

async def test_save_dataset_validation():
    """Test the save_dataset validation fixes."""
    print("\nTesting save_dataset validation...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
        print("✅ save_dataset imported successfully")
        
        # Test Python file destination rejection
        try:
            result = await save_dataset(
                dataset_data={"data": [{"text": "test"}]},
                destination="output.py"
            )
            print("❌ FAIL: Python file destination was accepted")
            return False
        except ValueError as e:
            if "Cannot save dataset as executable file" in str(e):
                print("✅ PASS: Python file destination correctly rejected")
                return True
            else:
                print(f"⚠️ WARNING: Rejected but unexpected message: {e}")
                return False
        except Exception as e:
            print(f"❌ ERROR: Unexpected exception: {e}")
            return False
            
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}")
        return False

async def test_process_dataset_validation():
    """Test the process_dataset validation fixes."""
    print("\nTesting process_dataset validation...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
        print("✅ process_dataset imported successfully")
        
        # Test dangerous operation rejection
        try:
            result = await process_dataset(
                dataset_source={"data": [{"text": "test"}]},
                operations=[{"type": "exec", "code": "import os"}]
            )
            print("❌ FAIL: Dangerous operation was accepted")
            return False
        except ValueError as e:
            if "not allowed for security reasons" in str(e):
                print("✅ PASS: Dangerous operation correctly rejected")
                return True
            else:
                print(f"⚠️ WARNING: Rejected but unexpected message: {e}")
                return False
        except Exception as e:
            print(f"❌ ERROR: Unexpected exception: {e}")
            return False
            
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}")
        return False

async def main():
    print("🧪 Quick Validation Test")
    print("=" * 40)
    
    results = []
    results.append(await test_load_dataset_validation())
    results.append(await test_save_dataset_validation())
    results.append(await test_process_dataset_validation())
    
    print("\n" + "=" * 40)
    print("📊 Summary:")
    
    passed = sum(results)
    total = len(results)
    
    print(f"✅ Passed: {passed}/{total}")
    if passed == total:
        print("🎉 All validation tests passed!")
    else:
        print("⚠️ Some validation tests failed.")
    
    return passed == total

if __name__ == "__main__":
    asyncio.run(main())
