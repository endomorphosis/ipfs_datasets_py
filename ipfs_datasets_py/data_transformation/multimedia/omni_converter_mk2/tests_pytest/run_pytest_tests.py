#!/usr/bin/env python3
"""
Run pytest tests for the Omni-Converter project.

This script provides a convenient interface for running pytest tests
with various options and reporting capabilities.
"""
import sys
import subprocess
import argparse
from pathlib import Path


def run_pytest(args=None):
    """Run pytest with the specified arguments."""
    cmd = [sys.executable, "-m", "pytest"]
    
    # Add default arguments
    default_args = [
        "tests_pytest/",
        "-v",
        "--tb=short"
    ]
    
    cmd.extend(default_args)
    
    # Add user arguments if provided
    if args:
        cmd.extend(args)
    
    print(f"Running: {' '.join(cmd)}")
    print("-" * 50)
    
    try:
        result = subprocess.run(cmd)
        return result.returncode
    except KeyboardInterrupt:
        print("\n⏸️  Test run interrupted by user")
        return 130


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run pytest tests")
    parser.add_argument("--working-only", action="store_true", 
                       help="Run only working tests (no dependency errors)")
    parser.add_argument("--unit", action="store_true", 
                       help="Run only unit tests")
    parser.add_argument("--integration", action="store_true",
                       help="Run only integration tests")
    parser.add_argument("--markers", action="store_true",
                       help="Show available test markers")
    parser.add_argument("--collect-only", action="store_true",
                       help="Only collect tests, don't run them")
    parser.add_argument("args", nargs="*", help="Additional pytest arguments")
    
    parsed_args = parser.parse_args()
    
    if parsed_args.markers:
        print("Available test markers:")
        print("- unit: Unit tests")
        print("- integration: Integration tests")
        print("- system: System tests")
        print("- performance: Performance tests")
        print("- slow: Slow running tests")
        print("- requires_deps: Tests requiring external dependencies")
        print("- skip_ci: Skip in CI environment")
        return 0
    
    pytest_args = list(parsed_args.args)
    
    if parsed_args.working_only:
        # Run only tests that don't have dependency issues
        pytest_args.extend([
            "tests_pytest/test_basic_setup.py",
            "tests_pytest/test_working_examples.py",
            "tests_pytest/skeleton_tests/"
        ])
    elif parsed_args.unit:
        pytest_args.extend(["-m", "unit"])
    elif parsed_args.integration:
        pytest_args.extend(["-m", "integration"])
    
    if parsed_args.collect_only:
        pytest_args.append("--collect-only")
    
    return run_pytest(pytest_args)


if __name__ == "__main__":
    sys.exit(main())