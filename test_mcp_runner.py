#!/usr/bin/env python3
"""
Simple test runner for MCP tools without requiring pytest or virtual environment.
"""

import os
import sys
import unittest
import importlib.util
from pathlib import Path

def run_test_file(test_file_path):
    """Run a single test file and return results."""
    try:
        # Load the test module
        spec = importlib.util.spec_from_file_location("test_module", test_file_path)
        test_module = importlib.util.module_from_spec(spec)
        sys.modules["test_module"] = test_module
        spec.loader.exec_module(test_module)

        # Find test classes
        test_classes = []
        for name in dir(test_module):
            obj = getattr(test_module, name)
            if isinstance(obj, type) and issubclass(obj, unittest.TestCase) and obj != unittest.TestCase:
                test_classes.append(obj)

        if not test_classes:
            return f"No test classes found in {test_file_path}"

        # Run tests
        results = []
        for test_class in test_classes:
            suite = unittest.TestLoader().loadTestsFromTestCase(test_class)
            runner = unittest.TextTestRunner(stream=open(os.devnull, 'w'), verbosity=0)
            result = runner.run(suite)

            test_name = test_class.__name__
            if result.wasSuccessful():
                results.append(f"✓ {test_name}: {result.testsRun} tests passed")
            else:
                failures = len(result.failures)
                errors = len(result.errors)
                results.append(f"✗ {test_name}: {failures} failures, {errors} errors out of {result.testsRun} tests")

                # Show first error/failure for debugging
                if result.failures:
                    results.append(f"  First failure: {result.failures[0][1].split(chr(10))[0]}")
                elif result.errors:
                    results.append(f"  First error: {result.errors[0][1].split(chr(10))[0]}")

        return "\n".join(results)

    except Exception as e:
        return f"✗ Failed to run {test_file_path}: {str(e)}"

def main():
    """Run all MCP tool tests."""
    print("Running IPFS Datasets MCP Tool Tests")
    print("=" * 50)

    # Add project root to Python path
    project_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_root))

    # Find all MCP test files
    test_dir = project_root / "test"
    mcp_test_files = list(test_dir.glob("test_mcp_*.py"))

    if not mcp_test_files:
        print("No MCP test files found!")
        return False

    print(f"Found {len(mcp_test_files)} MCP test files")
    print()

    total_files = len(mcp_test_files)
    successful_files = 0

    for test_file in sorted(mcp_test_files):
        print(f"Testing {test_file.name}...")
        result = run_test_file(test_file)
        print(result)

        if "✓" in result and "✗" not in result:
            successful_files += 1
        print()

    print("=" * 50)
    print(f"Summary: {successful_files}/{total_files} test files passed successfully")

    return successful_files == total_files

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
