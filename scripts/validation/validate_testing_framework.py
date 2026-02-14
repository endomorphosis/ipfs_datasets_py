#!/usr/bin/env python3
"""
Simple validation script for MCP Dashboard testing framework.

This script validates that the testing framework is properly set up and can run basic tests.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

def test_imports():
    """Test that all required imports work."""
    try:
        import pytest
        print("✓ pytest available")
    except ImportError:
        print("✗ pytest not available")
        return False
    
    try:
        from playwright.async_api import async_playwright
        print("✓ playwright available")
    except ImportError:
        print("✗ playwright not available")
        return False
    
    try:
        from ipfs_datasets_py.dashboards.mcp_dashboard import MCPDashboard, MCPDashboardConfig
        print("✓ MCP dashboard can be imported")
    except ImportError as e:
        print(f"✗ MCP dashboard import failed: {e}")
        return False
    
    return True

def test_test_files():
    """Test that test files exist and are valid."""
    test_files = [
        "tests/integration/dashboard/comprehensive_mcp_dashboard_test.py",
        "tests/integration/dashboard/test_utilities.py",
        "tests/integration/dashboard/run_mcp_dashboard_tests.py"
    ]
    
    for test_file in test_files:
        file_path = Path(test_file)
        if file_path.exists():
            print(f"✓ {test_file} exists")
        else:
            print(f"✗ {test_file} not found")
            return False
    
    return True

def test_directories():
    """Test that required directories exist."""
    directories = [
        "test_outputs",
        "docs/deployment",
        ".vscode"
    ]
    
    for directory in directories:
        dir_path = Path(directory)
        if dir_path.exists():
            print(f"✓ {directory}/ exists")
        else:
            print(f"✗ {directory}/ not found")
            return False
    
    return True

def test_docker_files():
    """Test that Docker files exist."""
    docker_files = [
        "docker-compose.mcp.yml",
        "ipfs_datasets_py/mcp_server/Dockerfile",
        "ipfs_datasets_py/mcp_server/Dockerfile.dashboard",
        "Dockerfile.testing"
    ]
    
    for docker_file in docker_files:
        file_path = Path(docker_file)
        if file_path.exists():
            print(f"✓ {docker_file} exists")
        else:
            print(f"✗ {docker_file} not found")
            return False
    
    return True

def main():
    """Run validation tests."""
    print("MCP Dashboard Testing Framework Validation")
    print("=" * 50)
    
    tests = [
        ("Import Tests", test_imports),
        ("Test Files", test_test_files),
        ("Directories", test_directories),
        ("Docker Files", test_docker_files)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        print("-" * len(test_name))
        result = test_func()
        results.append((test_name, result))
    
    print("\n" + "=" * 50)
    print("VALIDATION SUMMARY")
    print("=" * 50)
    
    all_passed = True
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{test_name}: {status}")
        if not result:
            all_passed = False
    
    if all_passed:
        print("\n✓ All validation tests passed!")
        print("\nNext steps:")
        print("1. Install Playwright browsers: playwright install chromium")
        print("2. Start MCP dashboard: python -m ipfs_datasets_py.mcp_dashboard")
        print("3. Run tests: python tests/integration/dashboard/run_mcp_dashboard_tests.py --mode smoke")
        sys.exit(0)
    else:
        print("\n✗ Some validation tests failed!")
        print("Please check the errors above and ensure all dependencies are properly installed.")
        sys.exit(1)

if __name__ == "__main__":
    main()