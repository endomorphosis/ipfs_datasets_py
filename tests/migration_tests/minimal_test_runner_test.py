#!/usr/bin/env python3
"""
Minimal test for TestRunner
"""
import sys
import os
from pathlib import Path
import tempfile

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Setup minimal test file
temp_dir = tempfile.mkdtemp()
test_file = Path(temp_dir) / "test_simple.py"
with open(test_file, 'w') as f:
    f.write("""
import unittest

class SimpleTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(1 + 1, 2)
""")

print(f"Created test file at {test_file}")

try:
    # Try to import and check only TestRunner class
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import TestRunner
    from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseDevelopmentTool
    
    # Create TestRunner
    runner = TestRunner()
    print(f"Created TestRunner instance: {runner}")
    print(f"Is BaseDevelopmentTool: {isinstance(runner, BaseDevelopmentTool)}")
    
    # Basic run test
    import asyncio
    async def run_test():
        try:
            print("Running test directly on temp dir")
            result = await runner.run_comprehensive_tests(
                path=temp_dir,
                run_unit_tests=True,
                run_type_check=False,
                run_linting=False,
                run_dataset_tests=False,
                test_framework="unittest",
                verbose=True
            )
            print(f"Result: {type(result)}")
            print(f"Result details: {result}")
            return True
        except Exception as e:
            print(f"Error running test: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    success = asyncio.run(run_test())
    if success:
        print("SUCCESS: TestRunner works correctly!")
    else:
        print("FAILURE: TestRunner has issues")

except Exception as e:
    print(f"Import or setup error: {e}")
    import traceback
    traceback.print_exc()
