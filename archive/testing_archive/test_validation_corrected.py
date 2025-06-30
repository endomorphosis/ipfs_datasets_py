#!/usr/bin/env python3
"""
Corrected validation test that checks for error status responses instead of exceptions.
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
        result = await load_dataset(source="test.py")
        if result.get("status") == "error" and "Python files (.py) are not valid dataset sources" in result.get("message", ""):
            print("✅ PASS: Python file correctly rejected")
            return True
        else:
            print(f"❌ FAIL: Unexpected result: {result}")
            return False
            
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}")
        return False
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        return False

async def test_save_dataset_validation():
    """Test the save_dataset validation fixes."""
    print("\nTesting save_dataset validation...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
        print("✅ save_dataset imported successfully")
        
        # Test Python file destination rejection
        result = await save_dataset(
            dataset_data={"data": [{"text": "test"}]},
            destination="output.py"
        )
        if result.get("status") == "error" and "Cannot save dataset as executable file" in result.get("message", ""):
            print("✅ PASS: Python file destination correctly rejected")
            return True
        else:
            print(f"❌ FAIL: Unexpected result: {result}")
            return False
            
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}")
        return False
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        return False

async def test_process_dataset_validation():
    """Test the process_dataset validation fixes."""
    print("\nTesting process_dataset validation...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
        print("✅ process_dataset imported successfully")
        
        # Test dangerous operation rejection
        result = await process_dataset(
            dataset_source={"data": [{"text": "test"}]},
            operations=[{"type": "exec", "code": "import os"}]
        )
        if result.get("status") == "error" and "not allowed for security reasons" in result.get("message", ""):
            print("✅ PASS: Dangerous operation correctly rejected")
            return True
        else:
            print(f"❌ FAIL: Unexpected result: {result}")
            return False
            
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}")
        return False
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        return False

async def test_tool_imports():
    """Test that all main tools can be imported."""
    print("\nTesting tool imports...")
    
    tools_to_test = [
        ("load_dataset", "ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset"),
        ("save_dataset", "ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset"),
        ("process_dataset", "ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset"),
        ("convert_dataset_format", "ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format"),
    ]
    
    all_passed = True
    for tool_name, module_path in tools_to_test:
        try:
            module = __import__(module_path, fromlist=[tool_name])
            if hasattr(module, tool_name):
                print(f"✅ {tool_name}: Successfully imported")
            else:
                print(f"❌ {tool_name}: Function not found in module")
                all_passed = False
        except ImportError as e:
            print(f"❌ {tool_name}: Import failed - {e}")
            all_passed = False
    
    return all_passed

async def test_empty_source_validation():
    """Test empty source validation."""
    print("\nTesting empty source validation...")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        
        # Test empty source
        result = await load_dataset(source="")
        if result.get("status") == "error":
            print("✅ PASS: Empty source correctly rejected")
            return True
        else:
            print(f"❌ FAIL: Empty source accepted: {result}")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False

async def main():
    print("🧪 Corrected Validation Test")
    print("=" * 50)
    
    results = []
    results.append(await test_tool_imports())
    results.append(await test_load_dataset_validation())
    results.append(await test_save_dataset_validation())
    results.append(await test_process_dataset_validation())
    results.append(await test_empty_source_validation())
    
    print("\n" + "=" * 50)
    print("📊 Summary:")
    
    passed = sum(results)
    total = len(results)
    
    print(f"✅ Passed: {passed}/{total}")
    if passed == total:
        print("🎉 All validation tests passed!")
        print("🔧 Input validation is working correctly!")
    else:
        print("⚠️ Some validation tests failed.")
    
    return passed == total

if __name__ == "__main__":
    asyncio.run(main())
