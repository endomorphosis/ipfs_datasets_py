#!/usr/bin/env python3
"""
Test script to demonstrate CLI installation and functionality.

This script tests that the ipfs-datasets CLI tool is properly configured
and can be installed as a console script.
"""

import subprocess
import sys
import os
from pathlib import Path


def run_command(cmd, cwd=None, timeout=30):
    """Run a command and return the result."""
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=timeout,
            cwd=cwd
        )
        return {
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'stdout': '',
            'stderr': 'Command timed out',
            'returncode': -1
        }
    except Exception as e:
        return {
            'success': False,
            'stdout': '',
            'stderr': str(e),
            'returncode': -2
        }


def test_direct_script_execution():
    """Test running the CLI script directly."""
    print("🧪 Testing direct script execution...")
    
    repo_root = Path(__file__).parent
    cli_script = repo_root / "ipfs_datasets_cli.py"
    
    if not cli_script.exists():
        print(f"❌ CLI script not found at {cli_script}")
        return False
    
    # Test help command
    result = run_command(f"python {cli_script} --help", cwd=repo_root)
    if result['success']:
        print("✅ Direct script execution works")
        print(f"   Script location: {cli_script}")
        return True
    else:
        print(f"❌ Direct script execution failed: {result['stderr']}")
        return False


def test_bash_wrapper():
    """Test the bash wrapper script."""
    print("\n🧪 Testing bash wrapper script...")
    
    repo_root = Path(__file__).parent
    wrapper_script = repo_root / "ipfs-datasets"
    
    if not wrapper_script.exists():
        print(f"❌ Bash wrapper not found at {wrapper_script}")
        return False
    
    # Test help command
    result = run_command(f"./ipfs-datasets --help", cwd=repo_root)
    if result['success']:
        print("✅ Bash wrapper works")
        print(f"   Wrapper location: {wrapper_script}")
        return True
    else:
        print(f"❌ Bash wrapper failed: {result['stderr']}")
        return False


def test_package_installation():
    """Test package installation in development mode."""
    print("\n🧪 Testing package installation...")
    
    repo_root = Path(__file__).parent
    
    # Test development installation
    print("   Installing package in development mode...")
    result = run_command("pip install -e .", cwd=repo_root)
    
    if not result['success']:
        print(f"❌ Package installation failed: {result['stderr']}")
        return False
    
    print("✅ Package installed successfully")
    
    # Test if console scripts are available
    print("   Testing console script availability...")
    
    # Test ipfs-datasets command
    result = run_command("ipfs-datasets --help")
    if result['success']:
        print("✅ 'ipfs-datasets' command available")
        console_script_works = True
    else:
        print(f"❌ 'ipfs-datasets' command not available: {result['stderr']}")
        console_script_works = False
    
    # Test ipfs-datasets-cli command
    result = run_command("ipfs-datasets-cli --help")
    if result['success']:
        print("✅ 'ipfs-datasets-cli' command available")
        console_script_works = console_script_works and True
    else:
        print(f"❌ 'ipfs-datasets-cli' command not available: {result['stderr']}")
        console_script_works = False
    
    return console_script_works


def test_cli_functionality():
    """Test basic CLI functionality."""
    print("\n🧪 Testing CLI functionality...")
    
    # Test info status command
    result = run_command("ipfs-datasets info status --format json")
    if result['success']:
        print("✅ CLI 'info status' command works")
        try:
            import json
            data = json.loads(result['stdout'])
            if data.get('status') == 'success':
                print(f"   System operational with {data.get('mcp_tools', {}).get('total_tools', 0)} tools")
        except:
            pass
    else:
        print(f"❌ CLI 'info status' failed: {result['stderr']}")
        return False
    
    # Test tools categories
    result = run_command("ipfs-datasets tools categories --format json")
    if result['success']:
        print("✅ CLI 'tools categories' command works")
        try:
            import json
            data = json.loads(result['stdout'])
            if data.get('status') == 'success':
                print(f"   Found {data.get('total_categories', 0)} tool categories")
        except:
            pass
    else:
        print(f"❌ CLI 'tools categories' failed: {result['stderr']}")
        return False
    
    return True


def main():
    """Main test function."""
    print("🚀 IPFS Datasets CLI Installation Test")
    print("=" * 50)
    
    results = []
    
    # Test 1: Direct script execution
    results.append(test_direct_script_execution())
    
    # Test 2: Bash wrapper
    results.append(test_bash_wrapper())
    
    # Test 3: Package installation
    results.append(test_package_installation())
    
    # Test 4: CLI functionality
    results.append(test_cli_functionality())
    
    # Summary
    print("\n📊 Test Results Summary")
    print("=" * 30)
    
    test_names = [
        "Direct Script Execution",
        "Bash Wrapper",
        "Package Installation",
        "CLI Functionality"
    ]
    
    passed = sum(results)
    total = len(results)
    
    for i, (name, result) in enumerate(zip(test_names, results)):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{i+1}. {name:<25} {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! The CLI tool is properly configured.")
        print("\nTo install system-wide, run:")
        print("   pip install -e .")
        print("\nThen you can use:")
        print("   ipfs-datasets --help")
        print("   ipfs-datasets info status")
        print("   ipfs-datasets tools categories")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check the errors above.")
        
        print("\nTroubleshooting tips:")
        print("1. Make sure you're in the repository root directory")
        print("2. Ensure Python 3.10+ is installed")
        print("3. Try creating a fresh virtual environment")
        print("4. Check that all required files exist (setup.py, pyproject.toml, ipfs_datasets_cli.py)")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)