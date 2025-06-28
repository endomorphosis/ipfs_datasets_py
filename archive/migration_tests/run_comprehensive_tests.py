"""
Comprehensive test suite for PDF processing and MCP tools.
This file runs all corrected and working tests.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

def run_test_file(test_file: str) -> bool:
    """Run a specific test file and return success status."""
    try:
        print(f"\n=== Running {test_file} ===")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v"],
            capture_output=True,
            text=True,
            cwd="/home/barberb/ipfs_datasets_py"
        )
        
        if result.returncode == 0:
            print(f"✓ {test_file} PASSED")
            return True
        else:
            print(f"✗ {test_file} FAILED")
            if result.stdout:
                print("STDOUT:", result.stdout[-500:])  # Last 500 chars
            if result.stderr:
                print("STDERR:", result.stderr[-500:])  # Last 500 chars
            return False
    except Exception as e:
        print(f"✗ {test_file} FAILED with exception: {e}")
        return False

def run_script_test(script_file: str) -> bool:
    """Run a script test and return success status."""
    try:
        print(f"\n=== Running {script_file} ===")
        result = subprocess.run(
            [sys.executable, script_file],
            capture_output=True,
            text=True,
            cwd="/home/barberb/ipfs_datasets_py"
        )
        
        if result.returncode == 0:
            print(f"✓ {script_file} PASSED")
            return True
        else:
            print(f"✗ {script_file} FAILED")
            if result.stdout:
                print("STDOUT:", result.stdout[-500:])
            if result.stderr:
                print("STDERR:", result.stderr[-500:])
            return False
    except Exception as e:
        print(f"✗ {script_file} FAILED with exception: {e}")
        return False

def main():
    """Run comprehensive test suite."""
    print("=== PDF Processing and MCP Tools Test Suite ===")
    print("Running corrected and validated tests...\n")
    
    # Test files that should work
    test_files = [
        "test_pdf_processing_corrected.py",
        "test_mcp_tools_corrected.py"
    ]
    
    # Script tests that should work
    script_tests = [
        "test_basic_functionality.py",
        "test_simple_integration.py"
    ]
    
    all_results = []
    
    # Run pytest-based tests
    for test_file in test_files:
        if Path(test_file).exists():
            result = run_test_file(test_file)
            all_results.append(result)
        else:
            print(f"⚠️  Test file {test_file} not found")
            all_results.append(False)
    
    # Run script-based tests
    for script_test in script_tests:
        if Path(script_test).exists():
            result = run_script_test(script_test)
            all_results.append(result)
        else:
            print(f"⚠️  Script test {script_test} not found")
            all_results.append(False)
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(all_results)
    total = len(all_results)
    
    print(f"Total tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {total - passed}")
    print(f"Success rate: {passed/total*100:.1f}%")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! 🎉")
        print("\nThe PDF processing pipeline and MCP tools are working correctly.")
        print("Key features validated:")
        print("  ✓ PDF processor initialization and basic functionality")
        print("  ✓ LLM optimizer and OCR engine components")
        print("  ✓ MCP tool imports and execution")
        print("  ✓ Error handling and graceful degradation")
        print("  ✓ Integration between components")
        return 0
    else:
        print(f"\n⚠️  {total - passed} tests failed")
        print("See individual test outputs above for details.")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
