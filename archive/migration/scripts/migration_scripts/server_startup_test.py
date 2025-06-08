#!/usr/bin/env python3
"""
Start MCP server and test tools.
"""
import sys
import time
import subprocess
import requests
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path.cwd()))

def start_server_and_test():
    """Start the MCP server and test the tools."""
    print("🚀 Starting MCP Server and Testing Tools")
    print("=" * 60)
    
    # Start server in background
    print("\n1. Starting MCP server...")
    try:
        # Use Popen to start in background
        server_process = subprocess.Popen([
            sys.executable, '-m', 'ipfs_datasets_py.mcp_server',
            '--http', '--host', '127.0.0.1', '--port', '8000'
        ], cwd='/home/barberb/ipfs_datasets_py')
        
        print(f"   Server started with PID: {server_process.pid}")
        
        # Wait a moment for server to start
        time.sleep(3)
        
        # Check if server is responding
        try:
            response = requests.get('http://127.0.0.1:8000/health', timeout=5)
            print(f"   ✅ Server responding: {response.status_code}")
        except Exception as e:
            print(f"   ⚠️ Server health check failed: {e}")
        
        # Test tools through HTTP API
        print("\n2. Testing tools via HTTP API...")
        test_results = []
        
        # Test 1: Codebase search
        try:
            response = requests.post('http://127.0.0.1:8000/call_tool', 
                                   json={
                                       'tool_name': 'codebase_search',
                                       'arguments': {
                                           'search_pattern': 'import',
                                           'path': '.',
                                           'max_depth': 1
                                       }
                                   }, timeout=10)
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ codebase_search: {result.get('status', 'unknown')}")
                test_results.append(('codebase_search', True))
            else:
                print(f"   ❌ codebase_search: HTTP {response.status_code}")
                test_results.append(('codebase_search', False))
        except Exception as e:
            print(f"   ❌ codebase_search: {e}")
            test_results.append(('codebase_search', False))
        
        # Test 2: Test generator
        try:
            response = requests.post('http://127.0.0.1:8000/call_tool',
                                   json={
                                       'tool_name': 'test_generator',
                                       'arguments': {
                                           'test_file': 'test_example.py',
                                           'class_name': 'TestExample',
                                           'functions': ['test_basic']
                                       }
                                   }, timeout=10)
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ test_generator: {result.get('status', 'unknown')}")
                test_results.append(('test_generator', True))
            else:
                print(f"   ❌ test_generator: HTTP {response.status_code}")
                test_results.append(('test_generator', False))
        except Exception as e:
            print(f"   ❌ test_generator: {e}")
            test_results.append(('test_generator', False))
        
        # Test 3: Documentation generator
        try:
            response = requests.post('http://127.0.0.1:8000/call_tool',
                                   json={
                                       'tool_name': 'documentation_generator',
                                       'arguments': {
                                           'python_file': './example.py',
                                           'output_file': 'temp_docs.md'
                                       }
                                   }, timeout=10)
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ documentation_generator: {result.get('status', 'unknown')}")
                test_results.append(('documentation_generator', True))
            else:
                print(f"   ❌ documentation_generator: HTTP {response.status_code}")
                test_results.append(('documentation_generator', False))
        except Exception as e:
            print(f"   ❌ documentation_generator: {e}")
            test_results.append(('documentation_generator', False))
        
        # Stop server
        print(f"\n3. Stopping server (PID: {server_process.pid})...")
        server_process.terminate()
        server_process.wait(timeout=10)
        print("   ✅ Server stopped")
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 60)
        
        successful_tests = sum(1 for _, success in test_results if success)
        total_tests = len(test_results)
        
        print(f"HTTP API Tests: {successful_tests}/{total_tests} passed")
        for tool_name, success in test_results:
            status = "✅" if success else "❌"
            print(f"  {status} {tool_name}")
        
        if successful_tests == total_tests:
            print("\n🎉 ALL TESTS PASSED! MCP server and tools are working!")
            return True
        else:
            print(f"\n⚠️ {total_tests - successful_tests} tests failed")
            return False
            
    except Exception as e:
        print(f"❌ Error during server startup/testing: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = start_server_and_test()
    
    if success:
        print("\n✅ VERIFICATION COMPLETE: Server and tools working after cleanup!")
    else:
        print("\n❌ VERIFICATION FAILED: Issues detected with server or tools.")
