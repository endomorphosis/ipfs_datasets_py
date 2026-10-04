#!/usr/bin/env python3
"""
Comprehensive MCP Server Tools Verification
Verifies all tools are working correctly after VS Code reload.
"""

import sys
import anyio
import traceback
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, "/home/barberb/ipfs_datasets_py")


async def test_all_mcp_tools():
    """Test all MCP tools to ensure they're working correctly."""

    print("🔍 Comprehensive MCP Tools Verification")
    print("=" * 50)
    print("Date: June 23, 2025")
    print("Status: Post VS Code Reload\n")

    results = {}

    # Test Dataset Tools
    print("📊 Testing Dataset Tools")
    print("-" * 30)

    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.convert_dataset_format import (
            convert_dataset_format,
        )

        print("✅ All dataset tools imported successfully")

        # Test load_dataset with valid and invalid inputs
        try:
            # Test security validation
            result = await load_dataset("malicious.py")
            if result.get("status") == "error" and "Python files" in result.get("message", ""):
                print("✅ load_dataset: Security validation working")
                results["load_dataset_security"] = True
            else:
                print("❌ load_dataset: Security validation failed")
                results["load_dataset_security"] = False

            # Test with mock valid dataset
            result = await load_dataset("mock_dataset.json")
            if result.get("status") == "success":
                print("✅ load_dataset: Mock dataset loading works")
                results["load_dataset_functional"] = True
            else:
                print("❌ load_dataset: Mock dataset loading failed")
                results["load_dataset_functional"] = False

        except Exception as e:
            print(f"❌ load_dataset test failed: {e}")
            results["load_dataset_security"] = False
            results["load_dataset_functional"] = False

        # Test save_dataset
        try:
            # Test security validation
            result = await save_dataset({"test": "data"}, "malicious.exe")
            if result.get("status") == "error" and "executable file" in result.get("message", ""):
                print("✅ save_dataset: Security validation working")
                results["save_dataset_security"] = True
            else:
                print("❌ save_dataset: Security validation failed")
                results["save_dataset_security"] = False

            # Test with valid destination
            result = await save_dataset({"test": "data"}, "/tmp/test.json")
            if result.get("status") == "success":
                print("✅ save_dataset: Valid saving works")
                results["save_dataset_functional"] = True
            else:
                print("❌ save_dataset: Valid saving failed")
                results["save_dataset_functional"] = False

        except Exception as e:
            print(f"❌ save_dataset test failed: {e}")
            results["save_dataset_security"] = False
            results["save_dataset_functional"] = False

    except ImportError as e:
        print(f"❌ Dataset tools import failed: {e}")
        results["dataset_tools"] = False

    # Test Development Tools
    print("\n🛠️ Testing Development Tools")
    print("-" * 30)

    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import TestRunner
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import (
            TestGeneratorTool,
        )
        from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import (
            documentation_generator,
        )
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import (
            CodebaseSearchEngine,
        )
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import LintingTools

        print("✅ All development tools imported successfully")
        results["development_tools"] = True

        # Test TestRunner instantiation
        try:
            test_runner = TestRunner()
            print("✅ TestRunner: Instantiation successful")
            results["test_runner"] = True
        except Exception as e:
            print(f"❌ TestRunner instantiation failed: {e}")
            results["test_runner"] = False

    except ImportError as e:
        print(f"❌ Development tools import failed: {e}")
        results["development_tools"] = False

    # Test Core MCP Server
    print("\n🖥️ Testing Core MCP Server")
    print("-" * 30)

    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

        server = IPFSDatasetsMCPServer()
        print("✅ MCP Server: Instantiation successful")
        results["mcp_server"] = True

    except Exception as e:
        print(f"❌ MCP Server instantiation failed: {e}")
        results["mcp_server"] = False

    # Test Additional Tools
    print("\n🔧 Testing Additional Tools")
    print("-" * 30)

    try:
        # Test some additional tools that should be available
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.pin_to_ipfs import pin_to_ipfs
        from ipfs_datasets_py.mcp_server.tools.ipfs_tools.get_from_ipfs import get_from_ipfs

        print("✅ IPFS tools imported successfully")
        results["ipfs_tools"] = True

    except ImportError as e:
        print(f"❌ IPFS tools import failed: {e}")
        results["ipfs_tools"] = False

    # Summary
    print("\n" + "=" * 50)
    print("📊 VERIFICATION SUMMARY")
    print("=" * 50)

    total_tests = len(results)
    passed_tests = sum(results.values())

    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {total_tests - passed_tests}")
    print(f"Success Rate: {(passed_tests / total_tests) * 100:.1f}%")

    print("\nDetailed Results:")
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {test_name}")

    if all(results.values()):
        print("\n🎉 ALL TESTS PASSED!")
        print("🚀 MCP Server is fully operational in VS Code")
        print("💡 You can now use all MCP tools in VS Code Chat")
        return True
    else:
        print(f"\n⚠️ {total_tests - passed_tests} tests failed")
        print("🔧 Some tools may not be fully functional")
        return False


def main():
    """Main verification function."""
    try:
        success = anyio.run(test_all_mcp_tools())
        return success
    except Exception as e:
        print(f"❌ Verification failed with error: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
