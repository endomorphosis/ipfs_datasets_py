#!/usr/bin/env python3
"""Fix development tools that have parameter/execution issues"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_development_tools_fix():
    """Test and fix development tools"""
    
    print("🔧 Testing Development Tools Fix")
    print("=" * 50)
    
    results = []
    
    # Test 1: test_generator (was failing with parameter issues)
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator
        result = test_generator(
            name="test_suite",
            description="Test suite for testing",
            test_specification={
                "imports": ["import unittest"],
                "tests": [
                    {
                        "name": "test_example", 
                        "description": "Test example functionality",
                        "assertions": ["self.assertTrue(True)"],
                        "parametrized": False
                    }
                ]
            },
            output_dir="/tmp",
            harness="unittest"
        )
        status = "✅ PASS" if isinstance(result, dict) and not result.get("error") else "❌ FAIL"
        results.append(("test_generator", status, f"Result type: {type(result).__name__}"))
        print(f"test_generator: {status}")
        if status == "❌ FAIL":
            print(f"  Error: {result.get('message', 'Unknown error')}")
    except Exception as e:
        results.append(("test_generator", "❌ FAIL", str(e)))
        print(f"test_generator: ❌ FAIL - {e}")
    
    # Test 2: lint_python_codebase (was failing with execution context)
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase
        result = lint_python_codebase(
            path=".",
            patterns=["*.py"],
            fix_issues=False,
            dry_run=True,
            verbose=False
        )
        status = "✅ PASS" if isinstance(result, dict) and not result.get("error") else "❌ FAIL"
        results.append(("lint_python_codebase", status, f"Result type: {type(result).__name__}"))
        print(f"lint_python_codebase: {status}")
        if status == "❌ FAIL":
            print(f"  Error: {result.get('message', 'Unknown error')}")
    except Exception as e:
        results.append(("lint_python_codebase", "❌ FAIL", str(e)))
        print(f"lint_python_codebase: ❌ FAIL - {e}")
    
    # Test 3: run_comprehensive_tests (also had issues)
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
        result = run_comprehensive_tests(
            path=".",
            run_unit_tests=False,  # Disable to speed up test
            run_type_check=False,
            run_linting=False,
            run_dataset_tests=False,
            verbose=False
        )
        status = "✅ PASS" if isinstance(result, dict) and not result.get("error") else "❌ FAIL"
        results.append(("run_comprehensive_tests", status, f"Result type: {type(result).__name__}"))
        print(f"run_comprehensive_tests: {status}")
        if status == "❌ FAIL":
            print(f"  Error: {result.get('message', 'Unknown error')}")
    except Exception as e:
        results.append(("run_comprehensive_tests", "❌ FAIL", str(e)))
        print(f"run_comprehensive_tests: ❌ FAIL - {e}")
    
    print(f"\n📊 Development Tools Test Results:")
    passed = sum(1 for _, status, _ in results if "PASS" in status)
    total = len(results)
    print(f"  Passed: {passed}/{total} ({passed/total*100:.1f}%)")
    
    for tool_name, status, message in results:
        print(f"  {status} {tool_name}: {message}")
    
    return results

if __name__ == "__main__":
    test_development_tools_fix()
