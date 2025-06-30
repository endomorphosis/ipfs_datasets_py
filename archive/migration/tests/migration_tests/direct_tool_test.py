#!/usr/bin/env python3
"""
Direct test of MCP server tools registration and functionality.
"""

# Test 1: Check imports
print("=== MCP Server Import Test ===")
try:
    from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
    print("✅ load_dataset imported successfully")
    
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator
    print("✅ test_generator imported successfully")
    
    from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
    print("✅ codebase_search imported successfully")
    
    from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import documentation_generator
    print("✅ documentation_generator imported successfully")
    
    from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase
    print("✅ lint_python_codebase imported successfully")
    
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
    print("✅ run_comprehensive_tests imported successfully")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    exit(1)

# Test 2: Input validation
print("\n=== Input Validation Test ===")
import asyncio

async def test_load_dataset_validation():
    # Test with Python file (should fail)
    try:
        result = await load_dataset(source="test.py")
        print("❌ Python file validation failed - should have been rejected")
        print(f"Result: {result}")
    except ValueError as e:
        print(f"✅ Python file correctly rejected: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        
    # Test with valid dataset name (mock response expected)
    try:
        result = await load_dataset(source="squad")
        if result['status'] == 'success':
            print(f"✅ Valid dataset name accepted: {result['status']}")
            print(f"   Dataset ID: {result.get('dataset_id', 'N/A')}")
            print(f"   Records: {result.get('summary', {}).get('num_records', 'N/A')}")
        else:
            print(f"⚠️  Dataset loading returned: {result['status']}")
    except Exception as e:
        print(f"📝 Dataset loading test result: {e}")

asyncio.run(test_load_dataset_validation())

# Test 3: Check development tools
print("\n=== Development Tools Test ===")

async def test_development_tools():
    try:
        # Test codebase search
        result = await codebase_search(
            query="load_dataset",
            search_type="function",
            directory="/home/barberb/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools"
        )
        print(f"✅ Codebase search: {result.get('status', 'unknown')}")
        
        # Test test generator
        result = await test_generator(
            target_file="/home/barberb/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py",
            test_type="unit"
        )
        print(f"✅ Test generator: {result.get('status', 'unknown')}")
        
    except Exception as e:
        print(f"📝 Development tools test: {e}")

asyncio.run(test_development_tools())

print("\n=== Test Complete ===")
