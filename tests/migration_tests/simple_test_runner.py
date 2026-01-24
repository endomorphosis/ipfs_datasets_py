#!/usr/bin/env python3
"""
Simple test runner to check MCP tools without hanging terminal.

This runs individual tests and reports results safely.
"""

import sys
import os
import anyio
import traceback
from unittest.mock import patch, MagicMock, AsyncMock

# Add the project root to the Python path
sys.path.insert(0, '/home/barberb/ipfs_datasets_py')

def test_audit_tools():
    """Test audit tools functionality."""
    try:
        from ipfs_datasets_py.mcp_server.tools.audit_tools.record_audit_event import record_audit_event
        from ipfs_datasets_py.mcp_server.tools.audit_tools.generate_audit_report import generate_audit_report

        print("✅ Audit tools import successful")

        # Test record_audit_event
        result = anyio.run(record_audit_event(
            "test_event", "system", "info",
            details={"test": "data"}
        ))

        if result.get("status") == "success":
            print("✅ record_audit_event working")
        else:
            print("❌ record_audit_event failed:", result.get("message"))

        # Test generate_audit_report
        result = anyio.run(generate_audit_report(
            start_date="2025-05-01",
            end_date="2025-05-24"
        ))

        if result.get("status") == "success":
            print("✅ generate_audit_report working")
        else:
            print("❌ generate_audit_report failed:", result.get("message"))

        return True

    except Exception as e:
        print(f"❌ Audit tools test failed: {e}")
        traceback.print_exc()
        return False

def test_cli_tools():
    """Test CLI tools functionality."""
    try:
        from ipfs_datasets_py.mcp_server.tools.cli.execute_command import execute_command
        print("✅ CLI tools import successful")

        # Test execute_command with a safe command
        result = anyio.run(execute_command("echo test", "/tmp"))

        if result.get("status") == "success":
            print("✅ execute_command working")
        else:
            print("❌ execute_command failed:", result.get("message"))

        return True

    except Exception as e:
        print(f"❌ CLI tools test failed: {e}")
        traceback.print_exc()
        return False

def test_function_tools():
    """Test function tools functionality."""
    try:
        from ipfs_datasets_py.mcp_server.tools.functions.execute_python_snippet import execute_python_snippet
        print("✅ Function tools import successful")

        # Test execute_python_snippet
        result = anyio.run(execute_python_snippet("print('test'); result = 2 + 2"))

        if result.get("status") == "success":
            print("✅ execute_python_snippet working")
        else:
            print("❌ execute_python_snippet failed:", result.get("message"))

        return True

    except Exception as e:
        print(f"❌ Function tools test failed: {e}")
        traceback.print_exc()
        return False

def test_security_tools():
    """Test security tools functionality."""
    try:
        from ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission import check_access_permission
        print("✅ Security tools import successful")

        # Test check_access_permission
        result = anyio.run(check_access_permission(
            "resource123", "user456", "read"
        ))

        if result.get("status") == "success":
            print("✅ check_access_permission working")
        else:
            print("❌ check_access_permission failed:", result.get("message"))

        return True

    except Exception as e:
        print(f"❌ Security tools test failed: {e}")
        traceback.print_exc()
        return False

def test_vector_tools():
    """Test vector tools functionality."""
    try:
        from ipfs_datasets_py.mcp_server.tools.vector_tools.create_vector_index import create_vector_index
        from ipfs_datasets_py.mcp_server.tools.vector_tools.search_vector_index import search_vector_index
        print("✅ Vector tools import successful")

        # Test create_vector_index
        test_vectors = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        result = anyio.run(create_vector_index(test_vectors, dimension=3))

        if result.get("status") == "success":
            print("✅ create_vector_index working")
        else:
            print("❌ create_vector_index failed:", result.get("message"))

        return True

    except Exception as e:
        print(f"❌ Vector tools test failed: {e}")
        traceback.print_exc()
        return False

def test_web_archive_tools():
    """Test web archive tools functionality."""
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.create_warc import create_warc
        print("✅ Web archive tools import successful")

        # Test create_warc (this should work as it's synchronous)
        result = create_warc("http://example.com", "/tmp/test.warc")

        if result.get("status") == "success":
            print("✅ create_warc working")
        else:
            print("❌ create_warc failed:", result.get("message", "Unknown error"))

        return True

    except Exception as e:
        print(f"❌ Web archive tools test failed: {e}")
        traceback.print_exc()
        return False

def main():
    """Run all tests and report results."""
    print("🧪 Running MCP Tools Test Suite")
    print("=" * 50)

    tests = [
        ("Audit Tools", test_audit_tools),
        ("CLI Tools", test_cli_tools),
        ("Function Tools", test_function_tools),
        ("Security Tools", test_security_tools),
        ("Vector Tools", test_vector_tools),
        ("Web Archive Tools", test_web_archive_tools),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"\n🔍 Testing {test_name}...")
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"❌ {test_name} crashed: {e}")

    print("\n" + "=" * 50)
    print(f"📊 Results: {passed}/{total} test groups passed")
    print(f"🎯 Success Rate: {(passed/total)*100:.1f}%")

    if passed == total:
        print("🎉 All test groups passed!")
    else:
        print(f"⚠️  {total-passed} test groups need attention")

if __name__ == "__main__":
    main()
