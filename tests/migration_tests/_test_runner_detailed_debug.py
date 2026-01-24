#!/usr/bin/env python3
"""
Debug the TestRunner implementation
"""
import anyio
import sys
import traceback
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

if __name__ == "__main__":
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import TestRunner
        from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseDevelopmentTool, development_tool_mcp_wrapper
        
        print("Creating TestRunner instance...")
        runner = TestRunner()
        print(f"Runner created: {runner}")
        print(f"Is BaseDevelopmentTool: {isinstance(runner, BaseDevelopmentTool)}")
        
        # Check if abstract methods are implemented
        print("\nChecking methods...")
        if hasattr(runner, '_execute_core'):
            print("✅ _execute_core method exists")
        else:
            print("❌ _execute_core method missing")
            
        # Test direct execution
        print("\nTesting direct execution...")
        params = {
            "path": ".",
            "run_unit_tests": False,
            "run_type_check": False,
            "run_linting": False,
            "run_dataset_tests": False,
            "test_framework": "pytest",
            "coverage": False,
            "verbose": True,
            "save_results": False,
            "output_formats": ["json"]
        }
        
        async def test_execute():
            print("Calling _execute_core...")
            result = await runner._execute_core(**params)
            print(f"Result type: {type(result)}")
            print(f"Result has keys: {result.keys() if isinstance(result, dict) else None}")
            return result
        
        result = anyio.run(test_execute())
        print("\nExecution successful!")
        
        # Test the wrapper function
        print("\nTesting wrapper function...")
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
        
        wrapper_result = run_comprehensive_tests(**params)
        print(f"Wrapper result type: {type(wrapper_result)}")
        print(f"Is same type as TestRunner: {isinstance(wrapper_result, type(runner))}")
        
        print("\nAll tests completed successfully!")
        
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
