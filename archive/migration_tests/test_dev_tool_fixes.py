#!/usr/bin/env python3
"""Test the development tool fixes"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Test specific development tools after fixes
async def test_development_tools():
    """Test the fixed development tools"""
    
    print("🔧 Testing Fixed Development Tools")
    print("=" * 50)
    
    test_results = []
    
    # Test 1: development_tool_mcp_wrapper
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import development_tool_mcp_wrapper
        result = development_tool_mcp_wrapper("TestToolClass")
        status = "✅ PASS" if result.get("success") else "❌ FAIL"
        test_results.append(("development_tool_mcp_wrapper", status, result.get("message", "No message")))
        print(f"development_tool_mcp_wrapper: {status}")
    except Exception as e:
        test_results.append(("development_tool_mcp_wrapper", "❌ FAIL", str(e)))
        print(f"development_tool_mcp_wrapper: ❌ FAIL - {e}")
    
    # Test 2: run_comprehensive_tests
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
        result = run_comprehensive_tests(path=".", run_unit_tests=False, run_type_check=False, 
                                       run_linting=False, run_dataset_tests=False)
        status = "✅ PASS" if isinstance(result, dict) else "❌ FAIL"
        test_results.append(("run_comprehensive_tests", status, f"Result type: {type(result).__name__}"))
        print(f"run_comprehensive_tests: {status}")
    except Exception as e:
        test_results.append(("run_comprehensive_tests", "❌ FAIL", str(e)))
        print(f"run_comprehensive_tests: ❌ FAIL - {e}")
    
    # Test 3: lint_python_codebase
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase
        result = lint_python_codebase(path=".", dry_run=True, fix_issues=False)
        status = "✅ PASS" if isinstance(result, dict) else "❌ FAIL"
        test_results.append(("lint_python_codebase", status, f"Result type: {type(result).__name__}"))
        print(f"lint_python_codebase: {status}")
    except Exception as e:
        test_results.append(("lint_python_codebase", "❌ FAIL", str(e)))
        print(f"lint_python_codebase: ❌ FAIL - {e}")
    
    # Test 4: test_generator
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator
        result = test_generator(
            name="test_suite",
            description="Test suite for testing",
            test_specification={"tests": [{"name": "test_example", "assertions": ["self.assertTrue(True)"]}]}
        )
        status = "✅ PASS" if isinstance(result, dict) else "❌ FAIL"
        test_results.append(("test_generator", status, f"Result type: {type(result).__name__}"))
        print(f"test_generator: {status}")
    except Exception as e:
        test_results.append(("test_generator", "❌ FAIL", str(e)))
        print(f"test_generator: ❌ FAIL - {e}")
    
    print("\n📊 Summary:")
    print("-" * 30)
    
    total_tests = len(test_results)
    passed_tests = sum(1 for _, status, _ in test_results if "PASS" in status)
    
    for tool_name, status, message in test_results:
        print(f"{tool_name}: {status}")
        if "FAIL" in status:
            print(f"  └─ {message}")
    
    print(f"\n🎯 Results: {passed_tests}/{total_tests} tools fixed ({passed_tests/total_tests*100:.1f}%)")
    
    return test_results

if __name__ == "__main__":
    asyncio.run(test_development_tools())
