"""
Test initialization and configuration for SymbolicAI Logic Integration tests.

This module sets up the test environment and provides utilities for running
the complete test suite.
"""

import sys
import os
import pytest
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

def run_all_tests():
    """Run all logic integration tests."""
    test_dir = Path(__file__).parent
    
    # Test files to run in order
    test_files = [
        "test_symbolic_bridge.py",
        "test_logic_primitives.py", 
        "test_symbolic_contracts.py",
        "test_modal_logic_extension.py",
        "test_logic_verification.py",
        "test_integration.py"
    ]
    
    print("Running SymbolicAI Logic Integration Test Suite")
    print("=" * 50)
    
    for test_file in test_files:
        test_path = test_dir / test_file
        if test_path.exists():
            print(f"\nRunning {test_file}...")
            print("-" * 30)
            
            # Run the specific test file
            exit_code = pytest.main([
                str(test_path),
                "-v",
                "--tb=short",
                "--no-header",
                "--show-capture=no"
            ])
            
            if exit_code != 0:
                print(f"❌ Tests failed in {test_file}")
                return exit_code
            else:
                print(f"✅ All tests passed in {test_file}")
        else:
            print(f"⚠️  Test file {test_file} not found")
    
    print("\n🎉 All logic integration tests completed successfully!")
    return 0


def run_quick_tests():
    """Run a subset of quick tests for rapid feedback."""
    test_dir = Path(__file__).parent
    
    print("Running Quick Logic Integration Tests")
    print("=" * 40)
    
    # Run only basic functionality tests
    exit_code = pytest.main([
        str(test_dir),
        "-v",
        "-k", "test_initialization or test_create or test_valid",
        "--tb=short",
        "--no-header"
    ])
    
    return exit_code


def run_integration_tests_only():
    """Run only the integration tests."""
    test_dir = Path(__file__).parent
    integration_test = test_dir / "test_integration.py"
    
    print("Running Integration Tests Only")
    print("=" * 35)
    
    if integration_test.exists():
        exit_code = pytest.main([
            str(integration_test),
            "-v",
            "--tb=short"
        ])
        return exit_code
    else:
        print("❌ Integration test file not found")
        return 1


def check_dependencies():
    """Check if all required dependencies are available."""
    print("Checking dependencies...")
    
    required_modules = [
        "pytest",
        "pydantic", 
        "beartype"
    ]
    
    optional_modules = [
        "symai"  # SymbolicAI
    ]
    
    missing_required = []
    missing_optional = []
    
    for module in required_modules:
        try:
            __import__(module)
            print(f"✅ {module} - available")
        except ImportError:
            missing_required.append(module)
            print(f"❌ {module} - missing (required)")
    
    for module in optional_modules:
        try:
            __import__(module)
            print(f"✅ {module} - available")
        except ImportError:
            missing_optional.append(module)
            print(f"⚠️  {module} - missing (optional)")
    
    if missing_required:
        print(f"\n❌ Missing required dependencies: {', '.join(missing_required)}")
        print("Install with: pip install " + " ".join(missing_required))
        return False
    
    if missing_optional:
        print(f"\n⚠️  Missing optional dependencies: {', '.join(missing_optional)}")
        print("Some features may be limited. Install with: pip install " + " ".join(missing_optional))
    
    print("\n✅ All required dependencies are available")
    return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run SymbolicAI Logic Integration Tests")
    parser.add_argument(
        "--mode", 
        choices=["all", "quick", "integration", "check-deps"],
        default="all",
        help="Test mode to run"
    )
    
    args = parser.parse_args()
    
    if args.mode == "check-deps":
        if check_dependencies():
            sys.exit(0)
        else:
            sys.exit(1)
    elif args.mode == "quick":
        sys.exit(run_quick_tests())
    elif args.mode == "integration":
        sys.exit(run_integration_tests_only())
    else:  # all
        if not check_dependencies():
            print("❌ Dependency check failed. Aborting tests.")
            sys.exit(1)
        sys.exit(run_all_tests())
