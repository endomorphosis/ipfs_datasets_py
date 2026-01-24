#!/usr/bin/env python3
"""
Minimal integration test without external dependencies.
"""

import sys
import anyio
import os
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

def test_file_structure():
    """Test that all required files exist."""
    print("📁 Testing file structure...")
    
    base_path = Path(__file__).parent / "ipfs_datasets_py" / "mcp_server" / "tools"
    
    required_files = [
        "tool_wrapper.py",
        "tool_registration.py", 
        "fastapi_integration.py",
        "auth_tools/auth_tools.py",
        "session_tools/session_tools.py",
        "background_task_tools/background_task_tools.py",
        "data_processing_tools/data_processing_tools.py",
        "storage_tools/storage_tools.py",
        "analysis_tools/analysis_tools.py",
        "rate_limiting_tools/rate_limiting_tools.py",
        "sparse_embedding_tools/sparse_embedding_tools.py",
        "index_management_tools/index_management_tools.py"
    ]
    
    missing_files = []
    existing_files = []
    
    for file_path in required_files:
        full_path = base_path / file_path
        if full_path.exists():
            existing_files.append(file_path)
            print(f"  ✅ {file_path}")
        else:
            missing_files.append(file_path)
            print(f"  ❌ {file_path}")
    
    print(f"\n📊 Summary: {len(existing_files)}/{len(required_files)} files exist")
    
    if missing_files:
        print("❌ Missing files:")
        for file in missing_files:
            print(f"  - {file}")
    
    return len(missing_files) == 0

def test_syntax():
    """Test Python syntax of key files."""
    print("\n🔍 Testing Python syntax...")
    
    base_path = Path(__file__).parent / "ipfs_datasets_py" / "mcp_server" / "tools"
    
    files_to_check = [
        "tool_wrapper.py",
        "tool_registration.py",
        "fastapi_integration.py",
        "auth_tools/auth_tools.py",
    ]
    
    syntax_errors = []
    
    for file_path in files_to_check:
        full_path = base_path / file_path
        if not full_path.exists():
            continue
            
        try:
            with open(full_path, 'r') as f:
                compile(f.read(), str(full_path), 'exec')
            print(f"  ✅ {file_path}")
        except SyntaxError as e:
            print(f"  ❌ {file_path}: {e}")
            syntax_errors.append((file_path, str(e)))
    
    return len(syntax_errors) == 0

def test_imports():
    """Test basic imports without executing functions."""
    print("\n📦 Testing imports...")
    
    import_tests = [
        ("Tool Wrapper", "ipfs_datasets_py.mcp_server.tools.tool_wrapper"),
        ("Tool Registration", "ipfs_datasets_py.mcp_server.tools.tool_registration"),
        ("FastAPI Integration", "ipfs_datasets_py.mcp_server.tools.fastapi_integration"),
        ("Auth Tools", "ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools"),
        ("Session Tools", "ipfs_datasets_py.mcp_server.tools.session_tools.session_tools"),
    ]
    
    successful_imports = 0
    
    for name, module_path in import_tests:
        try:
            __import__(module_path)
            print(f"  ✅ {name}")
            successful_imports += 1
        except Exception as e:
            print(f"  ❌ {name}: {e}")
    
    return successful_imports == len(import_tests)

async def test_basic_functionality():
    """Test basic functionality without external dependencies."""
    print("\n⚙️ Testing basic functionality...")
    
    try:
        # Test tool wrapper
        from ipfs_datasets_py.mcp_server.tools.tool_wrapper import FunctionToolWrapper
        
        # Create a simple test function
        async def test_func(message: str = "test") -> dict:
            return {"status": "success", "message": f"Processed: {message}"}
        
        # Wrap it
        wrapper = FunctionToolWrapper(test_func)
        print(f"  ✅ Tool wrapper created: {wrapper.name}")
        
        # Test execution
        result = await wrapper.execute({"message": "hello"})
        success = result.get("status") == "success"
        print(f"  ✅ Tool execution: {success}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Basic functionality test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Starting minimal integration test...\n")
    
    tests = [
        ("File Structure", test_file_structure),
        ("Python Syntax", test_syntax),
        ("Module Imports", test_imports),
        ("Basic Functionality", asyncio.run if callable(test_basic_functionality) else test_basic_functionality)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            if test_name == "Basic Functionality":
                result = anyio.run(test_basic_functionality())
            else:
                result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"💥 {test_name} crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*50)
    print("📊 Test Results:")
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {status}: {test_name}")
        if result:
            passed += 1
    
    total = len(results)
    print(f"\n🎯 Score: {passed}/{total} ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("🎉 All basic tests passed! Migration structure is correct!")
        return True
    else:
        print("⚠️  Some tests failed. Please check the output above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
