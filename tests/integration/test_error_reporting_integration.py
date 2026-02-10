#!/usr/bin/env python3
"""
Test script to verify error reporting integration with MCP server.
"""
import os
import sys
import tempfile
from pathlib import Path
import pytest

# Set up test environment
@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch):
    """Isolate env mutations to this module's tests."""
    monkeypatch.setenv('ERROR_REPORTING_ENABLED', 'true')
    # This won't actually create issues without a real token.
    monkeypatch.setenv('GITHUB_TOKEN', 'test-token')
    monkeypatch.setenv('GITHUB_REPOSITORY', 'test-owner/test-repo')

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_error_reporting_import():
    """Test that error reporting can be imported."""
    print("Testing error reporting import...")
    try:
        from ipfs_datasets_py.error_reporting import error_reporter, ErrorReportingConfig
        print("✅ Error reporting imported successfully")
        
        # Check configuration
        config = error_reporter.config
        print(f"  - Enabled: {config.enabled}")
        print(f"  - GitHub repo: {config.github_repo}")
        print(f"  - Max per hour: {config.max_issues_per_hour}")
        print(f"  - Max per day: {config.max_issues_per_day}")
        return True
    except Exception as e:
        print(f"❌ Failed to import error reporting: {e}")
        return False

def test_error_handler_singleton():
    """Test that error handler is a singleton."""
    print("\nTesting error handler singleton pattern...")
    try:
        from ipfs_datasets_py.error_reporting import ErrorHandler
        
        handler1 = ErrorHandler()
        handler2 = ErrorHandler()
        
        if handler1 is handler2:
            print("✅ Error handler singleton pattern works")
            return True
        else:
            print("❌ Error handler is not a singleton")
            return False
    except Exception as e:
        print(f"❌ Singleton test failed: {e}")
        return False

def test_error_signature():
    """Test error signature generation."""
    print("\nTesting error signature generation...")
    try:
        from ipfs_datasets_py.error_reporting import GitHubIssueCreator, ErrorReportingConfig
        
        config = ErrorReportingConfig()
        creator = GitHubIssueCreator(config)
        
        error1 = ValueError("Test error")
        error2 = ValueError("Test error")
        
        sig1 = creator._get_error_signature(error1, {'stack_trace': 'test'})
        sig2 = creator._get_error_signature(error2, {'stack_trace': 'test'})
        
        if sig1 == sig2:
            print(f"✅ Error signatures are consistent: {sig1[:16]}...")
            return True
        else:
            print(f"❌ Error signatures differ: {sig1[:16]}... vs {sig2[:16]}...")
            return False
    except Exception as e:
        print(f"❌ Signature test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_mcp_server_integration():
    """Test MCP server integration."""
    print("\nTesting MCP server integration...")
    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer, ERROR_REPORTING_AVAILABLE
        
        if not ERROR_REPORTING_AVAILABLE:
            print("❌ Error reporting not available in MCP server")
            return False
        
        print("✅ Error reporting available in MCP server")
        
        # Try to create server instance (won't start it)
        server = IPFSDatasetsMCPServer()
        print("✅ MCP server instance created with error reporting")
        
        return True
    except Exception as e:
        print(f"❌ MCP server integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_decorator():
    """Test error reporting decorator."""
    print("\nTesting error reporting decorator...")
    try:
        from ipfs_datasets_py.error_reporting import error_reporter
        
        call_count = [0]
        
        @error_reporter.wrap_function("Test Function")
        def test_func():
            call_count[0] += 1
            return "success"
        
        result = test_func()
        
        if result == "success" and call_count[0] == 1:
            print("✅ Decorator works for successful function")
        else:
            print(f"❌ Decorator failed: result={result}, call_count={call_count[0]}")
            return False
        
        # Test error case (without actually reporting)
        @error_reporter.wrap_function("Test Error Function")
        def error_func():
            raise ValueError("Test error")
        
        try:
            error_func()
            print("❌ Decorator should have raised exception")
            return False
        except ValueError as e:
            if str(e) == "Test error":
                print("✅ Decorator re-raises exceptions correctly")
                return True
            else:
                print(f"❌ Wrong exception: {e}")
                return False
    
    except Exception as e:
        print(f"❌ Decorator test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_context_manager():
    """Test error reporting context manager."""
    print("\nTesting error reporting context manager...")
    try:
        from ipfs_datasets_py.error_reporting import error_reporter
        
        # Test success case
        with error_reporter.context_manager("Test Context"):
            x = 1 + 1
        
        print("✅ Context manager works for successful code")
        
        # Test error case
        try:
            with error_reporter.context_manager("Test Error Context"):
                raise ValueError("Test error")
            print("❌ Context manager should have raised exception")
            return False
        except ValueError as e:
            if str(e) == "Test error":
                print("✅ Context manager re-raises exceptions correctly")
                return True
            else:
                print(f"❌ Wrong exception: {e}")
                return False
    
    except Exception as e:
        print(f"❌ Context manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("=" * 80)
    print("Error Reporting Integration Tests")
    print("=" * 80)
    
    tests = [
        test_error_reporting_import,
        test_error_handler_singleton,
        test_error_signature,
        test_mcp_server_integration,
        test_decorator,
        test_context_manager,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test raised exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 80)
    print("Test Summary")
    print("=" * 80)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("✅ All tests passed!")
        return 0
    else:
        print(f"❌ {total - passed} test(s) failed")
        return 1

if __name__ == '__main__':
    sys.exit(main())
