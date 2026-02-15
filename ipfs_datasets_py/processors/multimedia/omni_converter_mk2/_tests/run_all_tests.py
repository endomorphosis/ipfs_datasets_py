#!/usr/bin/env python3
"""
Run all tests for the Omni-Converter.

This script runs all the test modules and outputs results to both console and JSON files.
"""

import os
import sys
import unittest
import json
from datetime import datetime


def run_tests():
    """Run all the test modules and collect results."""
    # Make sure the collected_results directory exists
    os.makedirs('tests/collected_results', exist_ok=True)

    # Create a test loader
    loader = unittest.TestLoader()

    # Load tests from modules
    test_module_names = [
        'test_format_support_coverage',
        'test_processing_success_rate',
        'test_resource_utilization',
        'test_processing_speed',
        'test_error_handling',
        'test_security_effectiveness',
        'test_text_quality'
    ]

    # Discover and run tests
    test_suite = unittest.TestSuite()
    for module_name in test_module_names:
        try:
            # Import the module
            module = __import__(f'tests.{module_name}', fromlist=['*'])
            # Add tests from the module
            module_tests = loader.loadTestsFromModule(module)
            test_suite.addTests(module_tests)
            print(f"Loaded tests from {module_name}")
        except ImportError as e:
            print(f"Error importing {module_name}: {e}")
            continue

    # Run the tests
    print("\nRunning all tests...\n")
    runner = unittest.TextTestRunner(verbosity=2)
    results = runner.run(test_suite)

    # Generate summary report
    summary = {
        'timestamp': datetime.now().isoformat(),
        'tests_run': results.testsRun,
        'errors': len(results.errors),
        'failures': len(results.failures),
        'skipped': len(results.skipped),
        'success': results.wasSuccessful()
    }

    # Save summary to JSON
    with open('tests/collected_results/test_summary.json', 'w') as f:
        json.dump(summary, f, indent=2)

    print("\nTest Summary:")
    print(f"Tests run: {summary['tests_run']}")
    print(f"Errors: {summary['errors']}")
    print(f"Failures: {summary['failures']}")
    print(f"Skipped: {summary['skipped']}")
    print(f"Success: {summary['success']}")
    print(f"\nDetailed results saved to individual JSON files in tests/collected_results/")
    print(f"Summary saved to tests/collected_results/test_summary.json")

    # Return success or failure for exit code
    return 0 if summary['success'] else 1


if __name__ == "__main__":
    # Change directory to project root to ensure correct paths
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)
    
    # Add project root to Python path to ensure imports work
    sys.path.insert(0, project_root)
    
    # Run tests and exit with appropriate code
    sys.exit(run_tests())