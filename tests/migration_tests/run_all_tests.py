#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Comprehensive test runner for MCP server tools.
"""

import os
import sys
import pytest
import json
from datetime import datetime

def main():
    # Run all tests
    print("Running all MCP tools tests...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"mcp_tools_test_results_{timestamp}.json")

    # Check if there are any test files
    test_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test")
    test_files = [f for f in os.listdir(test_dir) if f.startswith("test_") and f.endswith(".py")]

    if not test_files:
        print("No test files found in the test directory.")
        return 1

    print(f"Found {len(test_files)} test files.")

    # Check if pytest-json-report is installed
    try:
        import pytest_json_report
        has_json_report = True
    except ImportError:
        has_json_report = False
        print("WARNING: pytest-json-report not installed, detailed reports won't be available")

    # Prepare pytest arguments
    pytest_args = ["-v", "test/"]

    # Add json report if available
    if has_json_report:
        pytest_args.extend(["--json-report", f"--json-report-file={report_path}"])

    # Run pytest
    print(f"Running pytest with args: {pytest_args}")
    exit_code = pytest.main(pytest_args)

    # Load and print test summary
    if has_json_report:
        try:
            if os.path.exists(report_path):
                with open(report_path, "r") as f:
                    report = json.load(f)

                summary = report["summary"]
                print("\n" + "=" * 50)
                print("MCP TOOLS TEST SUMMARY")
                print("=" * 50)
                print(f"Total tests: {summary['total']}")
                print(f"Passed: {summary['passed']}")
                print(f"Failed: {summary['failed']}")
                print(f"Skipped: {summary.get('skipped', 0)}")
                print(f"Error: {summary.get('error', 0)}")
                print(f"Time elapsed: {summary['duration']}s")
                print("=" * 50)

                # Print failures
                if summary['failed'] > 0:
                    print("\nFAILURES:")
                    for test_path, tests in report["tests"].items():
                        for test in tests:
                            if test.get("outcome") == "failed":
                                print(f"\n{test['nodeid']}")
                                print(f"  {test['call']['longrepr']}")
            else:
                print(f"No test report found at {report_path}")
        except Exception as e:
            print(f"Error reading test report: {e}")
    else:
        print("\nNo detailed test report available. Install pytest-json-report for detailed reporting.")

    return exit_code

if __name__ == "__main__":
    sys.exit(main())
