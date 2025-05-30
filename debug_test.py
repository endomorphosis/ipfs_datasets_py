#!/usr/bin/env python3
import sys
import traceback
from pathlib import Path

# Add the current directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

def test_run_comprehensive_tests():
    """Test run_comprehensive_tests with debugging info."""
    print("🔄 Testing run_comprehensive_tests...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import TestRunner, run_comprehensive_tests
        from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseDevelopmentTool
        
        # Create a test instance directly
        runner = TestRunner()
        print(f"TestRunner instance: {runner}")
        print(f"Is BaseDevelopmentTool instance: {isinstance(runner, BaseDevelopmentTool)}")
        
        # Check if _execute_core is implemented
        if hasattr(runner, '_execute_core'):
            print(f"Has _execute_core method: Yes")
        else:
            print(f"Has _execute_core method: No")
            
        # Try the wrapper function
        result = run_comprehensive_tests(
            path=".",
            run_unit_tests=True,
            run_type_check=False,
            run_linting=False,
            run_dataset_tests=False,
            verbose=True
        )
        
        print(f"Result type: {type(result)}")
        print(f"Result is a dict: {isinstance(result, dict)}")
        
        if isinstance(result, dict):
            print(f"Result keys: {result.keys()}")
            print(f"Success: {result.get('success')}")
            
        return True

    except Exception as e:
        print(f"❌ run_comprehensive_tests: ERROR - {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_run_comprehensive_tests()
