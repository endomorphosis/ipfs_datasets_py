#!/usr/bin/env python3
"""
Simplified test for run_comprehensive_tests
"""
import sys
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    print("Importing run_comprehensive_tests...")
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
    
    # Create a temporary test directory
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Created temp dir: {temp_dir}")
        
        # Create a simple test file
        test_file = Path(temp_dir) / "test_simple.py"
        with open(test_file, 'w') as f:
            f.write("""
import unittest

class SimpleTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(1 + 1, 2)
""")
        print(f"Created test file: {test_file}")
        
        # Try to run the tests
        print("Running run_comprehensive_tests...")
        result = run_comprehensive_tests(
            path=temp_dir,
            run_unit_tests=True,
            run_type_check=False,
            run_linting=False,
            run_dataset_tests=False,
            test_framework="unittest",
            verbose=True
        )
        
        # Print result information
        print(f"Result type: {type(result)}")
        if isinstance(result, dict):
            print(f"Result keys: {list(result.keys())}")
            print(f"Success: {result.get('success')}")
            if 'result' in result:
                print(f"Result contents type: {type(result.get('result'))}")
                if isinstance(result.get('result'), dict):
                    print(f"Result contents keys: {list(result.get('result').keys())}")
        
        print("\nTest completed successfully!")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
