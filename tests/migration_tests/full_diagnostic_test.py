#!/usr/bin/env python3
"""
Full diagnostic test for TestRunner
"""
import asyncio
import sys
import traceback
import os
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def print_separator():
    print("\n" + "=" * 70 + "\n")

async def run_test():
    print("STARTING DETAILED DIAGNOSTIC TEST")
    print_separator()
    
    try:
        # Step 1: Import the required modules
        print("Step 1: Importing modules...")
        
        # Import TestRunner and related classes
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import (
            TestRunner, 
            run_comprehensive_tests,
            TestExecutor,
            DatasetTestRunner
        )
        from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import (
            BaseDevelopmentTool, 
            development_tool_mcp_wrapper
        )
        
        print("✅ Successfully imported all modules")
        print_separator()
        
        # Step 2: Test the TestRunner class instantiation
        print("Step 2: Testing TestRunner instantiation...")
        runner = TestRunner()
        print(f"✅ Created TestRunner instance: {runner}")
        print(f"✅ Is BaseDevelopmentTool instance: {isinstance(runner, BaseDevelopmentTool)}")
        print_separator()
        
        # Step 3: Create a simple test file
        print("Step 3: Creating test environment...")
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Created temporary directory: {temp_dir}")
            
            # Create a simple test file
            test_file = Path(temp_dir) / "test_simple.py"
            with open(test_file, 'w') as f:
                f.write("""
import unittest

class SimpleTests(unittest.TestCase):
    def test_addition(self):
        self.assertEqual(1 + 1, 2)

    def test_string(self):
        self.assertEqual("hello" + " world", "hello world")
                """)
            print(f"✅ Created test file at {test_file}")
            print_separator()
            
            # Step 4: Test direct TestRunner.run_comprehensive_tests
            print("Step 4: Testing TestRunner.run_comprehensive_tests method directly...")
            params = {
                "path": temp_dir,
                "run_unit_tests": True,
                "run_type_check": False,
                "run_linting": False,
                "run_dataset_tests": False,
                "test_framework": "unittest",
                "coverage": False,
                "verbose": True,
                "save_results": False,
                "output_formats": ["json"]
            }
            
            try:
                print("Calling TestRunner.run_comprehensive_tests...")
                result = await runner.run_comprehensive_tests(**params)
                print(f"✅ Direct method call succeeded")
                print(f"✅ Result type: {type(result)}")
                if isinstance(result, dict):
                    print(f"✅ Result keys: {result.keys()}")
            except Exception as e:
                print(f"❌ Error in TestRunner.run_comprehensive_tests: {e}")
                traceback.print_exc()
            print_separator()
            
            # Step 5: Test TestRunner._execute_core
            print("Step 5: Testing TestRunner._execute_core method...")
            try:
                print("Calling TestRunner._execute_core...")
                result = await runner._execute_core(**params)
                print(f"✅ _execute_core call succeeded")
                print(f"✅ Result type: {type(result)}")
                if isinstance(result, dict):
                    print(f"✅ Result keys: {result.keys()}")
            except Exception as e:
                print(f"❌ Error in TestRunner._execute_core: {e}")
                traceback.print_exc()
            print_separator()
            
            # Step 6: Test decorated function
            print("Step 6: Testing decorated run_comprehensive_tests function...")
            try:
                print("Calling run_comprehensive_tests...")
                result = run_comprehensive_tests(**params)
                print(f"✅ run_comprehensive_tests call succeeded")
                print(f"✅ Result type: {type(result)}")
                if hasattr(result, 'execute'):
                    print(f"✅ Result has execute method")
                else:
                    print(f"❌ Result does not have execute method")
            except Exception as e:
                print(f"❌ Error in run_comprehensive_tests: {e}")
                traceback.print_exc()
            print_separator()
            
            # Step 7: Test the end-to-end test function
            print("Step 7: Testing end_to_end_dev_tools_test.test_run_comprehensive_tests...")
            try:
                print("Importing and calling test_run_comprehensive_tests...")
                from end_to_end_dev_tools_test import test_run_comprehensive_tests
                success = test_run_comprehensive_tests()
                if success:
                    print(f"✅ test_run_comprehensive_tests succeeded")
                else:
                    print(f"❌ test_run_comprehensive_tests failed")
            except Exception as e:
                print(f"❌ Error in test_run_comprehensive_tests: {e}")
                traceback.print_exc()
            
            print_separator()
            print("DIAGNOSTIC TEST COMPLETE")

    except Exception as e:
        print(f"❌ Unhandled error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_test())
