#!/usr/bin/env python3
"""
Simple test script for the IPFS Datasets CLI tool.
Tests basic functionality and ensures the CLI is working correctly.
"""

import subprocess
import sys
import json
from pathlib import Path


def run_cli_command(args, expect_success=True):
    """Run a CLI command and return the result."""
    cmd = ["python", "ipfs_datasets_cli.py"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if expect_success and result.returncode != 0:
            print(f"❌ Command failed: {' '.join(cmd)}")
            print(f"stderr: {result.stderr}")
            return None
        return result
    except subprocess.TimeoutExpired:
        print(f"❌ Command timed out: {' '.join(cmd)}")
        return None
    except Exception as e:
        print(f"❌ Command error: {e}")
        return None


def test_cli_basic():
    """Test basic CLI functionality."""
    print("🧪 Testing IPFS Datasets CLI...")

    # Test help
    print("  📋 Testing help...")
    result = run_cli_command(["--help"])
    if result and "ipfs-datasets-cli" in result.stdout:
        print("  ✅ Help command works")
    else:
        print("  ❌ Help command failed")
        return False

    # Test info status
    print("  ℹ️  Testing info status...")
    result = run_cli_command(["info", "status"])
    if result and "Success!" in result.stdout:
        print("  ✅ Info status works")
    else:
        print("  ❌ Info status failed")
        return False

    # Test info status JSON
    print("  📊 Testing JSON output...")
    result = run_cli_command(["--format", "json", "info", "status"])
    if result:
        try:
            data = json.loads(result.stdout)
            if data.get("status") == "success":
                print("  ✅ JSON output works")
            else:
                print("  ❌ JSON output invalid")
                return False
        except json.JSONDecodeError:
            print("  ❌ JSON output parsing failed")
            return False
    else:
        print("  ❌ JSON output command failed")
        return False

    # Test list tools
    print("  🔧 Testing list tools...")
    result = run_cli_command(["info", "list-tools"])
    if result and ("tool categories" in result.stdout.lower() or "Success!" in result.stdout):
        print("  ✅ List tools works")
    else:
        print("  ❌ List tools failed")
        return False

    # Test invalid command (should fail gracefully)
    print("  🚫 Testing invalid command...")
    result = run_cli_command(["invalid", "command"], expect_success=False)
    if result and result.returncode != 0:
        print("  ✅ Invalid command handled correctly")
    else:
        print("  ❌ Invalid command not handled properly")
        return False

    print("✅ All CLI tests passed!")
    return True


def test_wrapper_script():
    """Test the wrapper script."""
    wrapper_path = Path("ipfs-datasets")
    if not wrapper_path.exists():
        print("⚠️  Wrapper script not found, skipping wrapper test")
        return True

    print("🧪 Testing wrapper script...")
    try:
        result = subprocess.run(
            ["./ipfs-datasets", "info", "status"], capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and "Success!" in result.stdout:
            print("✅ Wrapper script works")
            return True
        else:
            print("❌ Wrapper script failed")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Wrapper script error: {e}")
        return False


def main():
    """Main test function."""
    print("🚀 Starting IPFS Datasets CLI Tests")
    print("=" * 50)

    # Change to the correct directory
    script_dir = Path(__file__).parent
    if script_dir != Path.cwd():
        print(f"📁 Changing to directory: {script_dir}")
        import os

        os.chdir(script_dir)

    success = True

    # Test basic CLI
    if not test_cli_basic():
        success = False

    print()

    # Test wrapper script
    if not test_wrapper_script():
        success = False

    print()
    print("=" * 50)
    if success:
        print("🎉 All tests passed! CLI is working correctly.")
        sys.exit(0)
    else:
        print("💥 Some tests failed. Please check the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
