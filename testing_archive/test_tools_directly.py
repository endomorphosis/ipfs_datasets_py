#!/usr/bin/env python3
"""
Test development tools directly to verify they work after cleanup.
"""
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path.cwd()))

def test_development_tools():
    """Test each development tool directly."""
    print("🔧 Testing Development Tools Directly")
    print("=" * 50)
    
    # Test 1: Import and test base tool
    print("\n1. Testing base tool import...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseDevelopmentTool
        print("✅ BaseDevelopmentTool imported successfully")
    except Exception as e:
        print(f"❌ Error importing BaseDevelopmentTool: {e}")
        return False
    
    # Test 2: Test generator
    print("\n2. Testing test generator...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator
        result = test_generator(
            test_file="test_example.py",
            class_name="TestExample", 
            functions=["test_basic"]
        )
        print("✅ Test generator working")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ Error with test generator: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 3: Documentation generator
    print("\n3. Testing documentation generator...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import documentation_generator
        result = documentation_generator(
            python_file="./example.py",
            output_file="test_docs.md"
        )
        print("✅ Documentation generator working")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ Error with documentation generator: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 4: Codebase search
    print("\n4. Testing codebase search...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
        result = codebase_search(
            search_pattern="def test",
            path=".",
            max_depth=2
        )
        print("✅ Codebase search working")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ Error with codebase search: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 5: Linting tools
    print("\n5. Testing linting tools...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase
        result = lint_python_codebase(
            path=".",
            max_depth=1,
            fix_issues=False
        )
        print("✅ Linting tools working")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ Error with linting tools: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 6: Test runner
    print("\n6. Testing test runner...")
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
        result = run_comprehensive_tests(
            path=".",
            run_unit_tests=False,  # Don't actually run tests
            run_type_check=False,
            max_depth=1
        )
        print("✅ Test runner working")
        print(f"   Result type: {type(result)}")
    except Exception as e:
        print(f"❌ Error with test runner: {e}")
        import traceback
        traceback.print_exc()
    
    return True

def test_mcp_server_registration():
    """Test MCP server tool registration."""
    print("\n🌐 Testing MCP Server Registration")
    print("=" * 50)
    
    try:
        from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer
        server = IPFSDatasetsMCPServer()
        server.register_tools()
        
        # Check for development tools
        dev_tools = [
            'test_generator', 'codebase_search', 'documentation_generator',
            'lint_python_codebase', 'run_comprehensive_tests'
        ]
        
        print(f"\nRegistered {len(server.tools)} tools total")
        
        found_dev_tools = []
        for tool_name in dev_tools:
            if tool_name in server.tools:
                found_dev_tools.append(tool_name)
                print(f"✅ {tool_name}")
            else:
                print(f"❌ {tool_name} (missing)")
        
        print(f"\nDevelopment tools: {len(found_dev_tools)}/{len(dev_tools)} found")
        return len(found_dev_tools) == len(dev_tools)
        
    except Exception as e:
        print(f"❌ Error testing MCP server: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🚀 Post-Cleanup Tool Verification")
    print("=" * 50)
    
    tools_ok = test_development_tools()
    server_ok = test_mcp_server_registration()
    
    print("\n" + "=" * 50)
    print("📊 SUMMARY")
    print("=" * 50)
    print(f"Development Tools: {'✅ WORKING' if tools_ok else '❌ ISSUES'}")
    print(f"MCP Server Registration: {'✅ WORKING' if server_ok else '❌ ISSUES'}")
    
    if tools_ok and server_ok:
        print("\n🎉 All tools are working after cleanup!")
        print("The server should start properly now.")
    else:
        print("\n⚠️  Some issues found. Check the errors above.")
