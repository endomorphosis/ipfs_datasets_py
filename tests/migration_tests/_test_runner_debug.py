#!/usr/bin/env python3
"""
Basic test script for TestRunner

This will help us debug the issue with run_comprehensive_tests
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

if __name__ == "__main__":
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
    try:
        print("Calling run_comprehensive_tests...")
        tool = run_comprehensive_tests(
            path=".",
            run_unit_tests=False,
            run_type_check=False,
            run_linting=False,
            run_dataset_tests=False,
            verbose=True
        )
        print(f"Return value type: {type(tool)}")
        print("Test completed successfully!")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
