#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Individual Development Tools Test

This script tests each development tool individually to verify functionality.
"""

import os
import sys
import json
import time
import tempfile
from pathlib import Path
import traceback

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

class ToolTester:
    """Tests individual development tools functionality."""

    def __init__(self, output_dir=None):
        """Initialize the tester.

        Args:
            output_dir: Directory to save test outputs (defaults to temp dir)
        """
        self.output_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="tool_test_"))
        self.output_dir.mkdir(exist_ok=True, parents=True)
        self.results = {}

    def test_codebase_search(self):
        """Test the codebase_search tool."""
        print("\n🔍 Testing codebase_search...")
        try:
            from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search

            # Simple search
            simple_result = codebase_search(
                pattern="def test_",
                path=".",
                max_depth=2,
                format="text"
            )

            # Advanced search with regex
            regex_result = codebase_search(
                pattern=r"class\s+\w+\(.*\):",
                path=".",
                max_depth=2,
                format="json",
                regex=True
            )

            success = (simple_result and regex_result and
                      'success' in simple_result and simple_result['success'] and
                      'success' in regex_result and regex_result['success'])

            if success:
                print("✅ codebase_search: Both simple and regex searches succeeded")
                # Write example output
                with open(self.output_dir / "codebase_search_example.json", 'w') as f:
                    json.dump(regex_result, f, indent=2)
            else:
                print("❌ codebase_search: Search failed")
                print(f"Simple search result: {simple_result}")
                print(f"Regex search result: {regex_result}")

            return success
        except Exception as e:
            print(f"❌ codebase_search error: {e}")
            traceback.print_exc()
            return False

    def test_documentation_generator(self):
        """Test the documentation_generator tool."""
        print("\n📄 Testing documentation_generator...")
        try:
            from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import documentation_generator

            # Generate documentation for this file
            result = documentation_generator(
                input_path=__file__,
                format_type="markdown"
            )

            success = (result and 'success' in result and result['success'] and
                      'documentation' in result and result['documentation'])

            if success:
                print("✅ documentation_generator: Documentation generated successfully")
                # Save the documentation
                with open(self.output_dir / "documentation_example.md", 'w') as f:
                    f.write(result['documentation'])
            else:
                print("❌ documentation_generator: Failed to generate documentation")
                print(f"Result: {result}")

            return success
        except Exception as e:
            print(f"❌ documentation_generator error: {e}")
            traceback.print_exc()
            return False

    def test_lint_python_codebase(self):
        """Test the lint_python_codebase tool."""
        print("\n🔬 Testing lint_python_codebase...")
        try:
            from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase

            # Create a sample file with some lint issues
            lint_test_file = self.output_dir / "lint_test.py"
            with open(lint_test_file, 'w') as f:
                f.write("""
import sys, os
def bad_function( a,b ):
    x = 10
    return None
                """)

            result = lint_python_codebase(
                path=str(lint_test_file),
                fix_issues=False,
                dry_run=True
            )

            success = (result and 'success' in result and result['success'] and
                      'issues' in result)

            if success:
                print("✅ lint_python_codebase: Linting completed successfully")
                print(f"   Found {len(result['issues'])} issues as expected")
                # Save the lint results
                with open(self.output_dir / "lint_results.json", 'w') as f:
                    json.dump(result, f, indent=2)
            else:
                print("❌ lint_python_codebase: Linting failed")
                print(f"Result: {result}")

            return success
        except Exception as e:
            print(f"❌ lint_python_codebase error: {e}")
            traceback.print_exc()
            return False

    def test_test_generator(self):
        """Test the test_generator tool."""
        print("\n🧪 Testing test_generator...")
        try:
            from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator

            # Create a simple file to generate tests for
            test_subject = self.output_dir / "simple_math.py"
            with open(test_subject, 'w') as f:
                f.write("""
def add(a, b):
    \"\"\"Add two numbers together.\"\"\"
    return a + b

def subtract(a, b):
    \"\"\"Subtract b from a.\"\"\"
    return a - b

class Calculator:
    def multiply(self, a, b):
        \"\"\"Multiply two numbers.\"\"\"
        return a * b
                """)

            # Create test specification
            test_spec = {
                "name": "test_simple_math",
                "test_class": "TestSimpleMath",
                "tests": [
                    {
                        "name": "test_add",
                        "description": "Test add function",
                        "assertions": ["assert add(2, 3) == 5"]
                    },
                    {
                        "name": "test_subtract",
                        "description": "Test subtract function",
                        "assertions": ["assert subtract(5, 3) == 2"]
                    }
                ]
            }

            result = test_generator(
                name="test_simple_math",
                description="Test for simple math functions",
                test_specification=json.dumps(test_spec),
                output_dir=str(self.output_dir),
                harness="pytest"
            )

            success = (result and 'success' in result and result['success'] and
                      'test_code' in result and result['test_code'])

            if success:
                print("✅ test_generator: Test generation completed successfully")
                # Save the generated test
                with open(self.output_dir / "generated_test.py", 'w') as f:
                    f.write(result['test_code'])
            else:
                print("❌ test_generator: Test generation failed")
                print(f"Result: {result}")

            return success
        except Exception as e:
            print(f"❌ test_generator error: {e}")
            traceback.print_exc()
            return False

    def test_run_comprehensive_tests(self):
        """Test the run_comprehensive_tests tool."""
        print("\n🔄 Testing run_comprehensive_tests...")
        try:
            from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests

            # Create a simple test file
            test_file = self.output_dir / "test_simple.py"
            with open(test_file, 'w') as f:
                f.write("""
import unittest

class SimpleTests(unittest.TestCase):
    def test_addition(self):
        self.assertEqual(1 + 1, 2)

    def test_string(self):
        self.assertEqual("hello" + " world", "hello world")
                """)

            result = run_comprehensive_tests(
                path=str(self.output_dir),
                run_unit_tests=True,
                run_type_check=False,
                run_linting=False,
                run_dataset_tests=False,
                test_framework="unittest",
                verbose=True,
                output_formats=["json"]
            )

            success = (result and 'success' in result and result['success'])

            if success:
                print("✅ run_comprehensive_tests: Tests ran successfully")
                # Save the test results
                with open(self.output_dir / "test_results.json", 'w') as f:
                    json.dump(result, f, indent=2)
            else:
                print("❌ run_comprehensive_tests: Test run failed")
                print(f"Result: {result}")

            return success
        except Exception as e:
            print(f"❌ run_comprehensive_tests error: {e}")
            traceback.print_exc()
            return False

    def run_all_tests(self):
        """Run all tool tests and report results."""
        print("=" * 50)
        print("Running Individual Development Tools Tests")
        print("=" * 50)

        # Run all tests
        self.results['codebase_search'] = self.test_codebase_search()
        self.results['documentation_generator'] = self.test_documentation_generator()
        self.results['lint_python_codebase'] = self.test_lint_python_codebase()
        self.results['test_generator'] = self.test_test_generator()
        self.results['run_comprehensive_tests'] = self.test_run_comprehensive_tests()

        # Display summary
        print("\n" + "=" * 50)
        print("Development Tools Test Summary")
        print("=" * 50)

        all_passed = True
        for tool, passed in self.results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{tool}: {status}")
            all_passed = all_passed and passed

        overall_status = "✅ All tests PASSED" if all_passed else "❌ Some tests FAILED"
        print(f"\nOverall Status: {overall_status}")
        print(f"Test outputs saved to: {self.output_dir}")

        return all_passed

if __name__ == "__main__":
    # Create output directory in the current directory
    output_dir = Path(__file__).parent / "tool_test_results"

    tester = ToolTester(output_dir=output_dir)
    success = tester.run_all_tests()

    sys.exit(0 if success else 1)
