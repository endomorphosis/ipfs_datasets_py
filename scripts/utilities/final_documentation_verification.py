#!/usr/bin/env python3
"""
Final documentation verification script.
Tests current state of all MCP tools and validates documentation accuracy.
"""

import sys
import os
import anyio
import traceback
from typing import Dict, Any, List

# Add the project root to Python path
sys.path.insert(0, "/home/barberb/ipfs_datasets_py")


def test_security_validations():
    """Test the security validations that were recently added."""
    print("🛡️ Testing Security Validations")
    print("-" * 40)

    try:
        # Test load_dataset validation
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset

        # This should fail (Python file rejection)
        try:
            result = anyio.run(load_dataset("malicious.py"))
            # Check if it returned an error status instead of raising
            if isinstance(result, dict) and result.get("status") == "error":
                if "Python files" in result.get("message", ""):
                    print("✅ load_dataset: Correctly rejects Python files (via error response)")
                else:
                    print(f"❌ load_dataset: Wrong error message: {result.get('message')}")
                    return False
            else:
                print("❌ load_dataset: Should have rejected Python file")
                return False
        except ValueError as e:
            if "Python files" in str(e):
                print("✅ load_dataset: Correctly rejects Python files (via exception)")
            else:
                print(f"❌ load_dataset: Wrong error: {e}")
                return False
        except Exception as e:
            print(f"❌ load_dataset: Unexpected error: {e}")
            return False

        # Test save_dataset validation
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

        try:
            result = anyio.run(save_dataset({"test": "data"}, "malicious.py"))
            # Check if it returned an error status instead of raising
            if isinstance(result, dict) and result.get("status") == "error":
                if "executable file" in result.get("message", ""):
                    print(
                        "✅ save_dataset: Correctly rejects executable files (via error response)"
                    )
                else:
                    print(f"❌ save_dataset: Wrong error message: {result.get('message')}")
                    return False
            else:
                print("❌ save_dataset: Should have rejected executable file")
                return False
        except ValueError as e:
            if "executable file" in str(e):
                print("✅ save_dataset: Correctly rejects executable files (via exception)")
            else:
                print(f"❌ save_dataset: Wrong error: {e}")
                return False
        except Exception as e:
            print(f"❌ save_dataset: Unexpected error: {e}")
            return False

        # Test process_dataset validation
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset

        try:
            result = anyio.run(
                process_dataset({"test": "data"}, [{"type": "exec", "code": "malicious_code"}])
            )
            # Check if it returned an error status instead of raising
            if isinstance(result, dict) and result.get("status") == "error":
                if "not allowed for security" in result.get("message", ""):
                    print(
                        "✅ process_dataset: Correctly blocks dangerous operations (via error response)"
                    )
                else:
                    print(f"❌ process_dataset: Wrong error message: {result.get('message')}")
                    return False
            else:
                print("❌ process_dataset: Should have rejected exec operation")
                return False
        except ValueError as e:
            if "not allowed for security" in str(e):
                print("✅ process_dataset: Correctly blocks dangerous operations (via exception)")
            else:
                print(f"❌ process_dataset: Wrong error: {e}")
                return False
        except Exception as e:
            print(f"❌ process_dataset: Unexpected error: {e}")
            return False

        print("✅ All security validations working correctly!")
        return True

    except Exception as e:
        print(f"❌ Security validation test failed: {e}")
        traceback.print_exc()
        return False


def test_server_imports():
    """Test that the MCP server can be imported and instantiated."""
    print("\n🔧 Testing Server Imports")
    print("-" * 40)

    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

        print("✅ Server class import: SUCCESS")

        server = IPFSDatasetsMCPServer()
        print("✅ Server instantiation: SUCCESS")

        # Test development tools import
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import TestRunner

        print("✅ TestRunner import: SUCCESS")

        from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import (
            TestGeneratorTool,
        )

        print("✅ TestGeneratorTool import: SUCCESS")

        return True

    except Exception as e:
        print(f"❌ Server import test failed: {e}")
        traceback.print_exc()
        return False


def verify_documentation_accuracy():
    """Verify that documentation reflects current state."""
    print("\n📋 Verifying Documentation Accuracy")
    print("-" * 40)

    checks = []

    # Check README.md
    try:
        with open("/home/barberb/ipfs_datasets_py/README.md", "r") as f:
            readme_content = f.read()

        if "95% Complete" in readme_content:
            print("✅ README.md: Status correctly shows 95% complete")
            checks.append(True)
        else:
            print("❌ README.md: Status not updated")
            checks.append(False)

        if "Security" in readme_content and "input validation" in readme_content:
            print("✅ README.md: Security enhancements mentioned")
            checks.append(True)
        else:
            print("❌ README.md: Security enhancements not documented")
            checks.append(False)

    except Exception as e:
        print(f"❌ README.md check failed: {e}")
        checks.append(False)

    # Check MCP_SERVER.md
    try:
        with open("/home/barberb/ipfs_datasets_py/MCP_SERVER.md", "r") as f:
            mcp_content = f.read()

        if "95% Complete" in mcp_content:
            print("✅ MCP_SERVER.md: Status correctly shows 95% complete")
            checks.append(True)
        else:
            print("❌ MCP_SERVER.md: Status not updated")
            checks.append(False)

        if "Security Enhancements" in mcp_content:
            print("✅ MCP_SERVER.md: Security section added")
            checks.append(True)
        else:
            print("❌ MCP_SERVER.md: Security section missing")
            checks.append(False)

    except Exception as e:
        print(f"❌ MCP_SERVER.md check failed: {e}")
        checks.append(False)

    return all(checks)


def main():
    """Run all documentation verification tests."""
    print("🔍 Final Documentation Verification")
    print("=" * 50)

    results = []

    # Test security validations
    results.append(test_security_validations())

    # Test server imports
    results.append(test_server_imports())

    # Verify documentation accuracy
    results.append(verify_documentation_accuracy())

    print("\n" + "=" * 50)
    print("📊 VERIFICATION SUMMARY")
    print("=" * 50)

    if all(results):
        print("🎉 ALL TESTS PASSED!")
        print("✅ Security validations working")
        print("✅ Server imports successful")
        print("✅ Documentation accurate and up-to-date")
        print("\n🎯 Ready for VS Code MCP server restart!")
        print("📋 Action: Press Ctrl+Shift+P → 'MCP: Restart All Servers'")
        return True
    else:
        print("❌ Some tests failed")
        for i, result in enumerate(results):
            test_names = ["Security Validations", "Server Imports", "Documentation Accuracy"]
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status}: {test_names[i]}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
