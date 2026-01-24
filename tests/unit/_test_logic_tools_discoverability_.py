#!/usr/bin/env python3
"""
Test to verify that FOL and Deontic Logic tools are properly discoverable by the MCP server.
"""

import anyio
import sys
from pathlib import Path

# Add the package to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from ipfs_datasets_py.mcp_server.tools.dataset_tools import text_to_fol, legal_text_to_deontic

async def test_tool_discovery():
    """Test that logic tools can be imported and have proper signatures."""
    
    print("🔍 Testing Logic Tool Discoverability")
    print("=" * 50)
    
    # Test FOL tool discovery
    print("1. Testing FOL Tool Discovery:")
    try:
        assert callable(text_to_fol), "text_to_fol is not callable"
        assert hasattr(text_to_fol, '__doc__'), "text_to_fol has no docstring"
        assert hasattr(text_to_fol, '__annotations__'), "text_to_fol has no type annotations"
        
        # Check the docstring contains important information
        docstring = text_to_fol.__doc__ or ""
        assert "FOL" in docstring or "First-Order Logic" in docstring, "Docstring doesn't mention FOL"
        
        print("   ✅ text_to_fol tool is properly discoverable")
        print(f"   📝 Docstring preview: {docstring[:100]}...")
        
    except Exception as e:
        print(f"   ❌ FOL tool discovery failed: {e}")
        return False
    
    # Test Deontic tool discovery
    print("\n2. Testing Deontic Logic Tool Discovery:")
    try:
        assert callable(legal_text_to_deontic), "legal_text_to_deontic is not callable"
        assert hasattr(legal_text_to_deontic, '__doc__'), "legal_text_to_deontic has no docstring"
        assert hasattr(legal_text_to_deontic, '__annotations__'), "legal_text_to_deontic has no type annotations"
        
        # Check the docstring contains important information
        docstring = legal_text_to_deontic.__doc__ or ""
        assert "deontic" in docstring.lower() or "legal" in docstring.lower(), "Docstring doesn't mention deontic/legal"
        
        print("   ✅ legal_text_to_deontic tool is properly discoverable")
        print(f"   📝 Docstring preview: {docstring[:100]}...")
        
    except Exception as e:
        print(f"   ❌ Deontic tool discovery failed: {e}")
        return False
    
    # Test actual tool execution
    print("\n3. Testing Tool Execution:")
    try:
        # Quick FOL test
        fol_result = await text_to_fol("All cats are animals")
        assert fol_result.get("status") == "success", "FOL tool execution failed"
        print("   ✅ FOL tool executes successfully")
        
        # Quick Deontic test  
        deontic_result = await legal_text_to_deontic("Citizens must vote")
        assert deontic_result.get("status") == "success", "Deontic tool execution failed"
        print("   ✅ Deontic tool executes successfully")
        
    except Exception as e:
        print(f"   ❌ Tool execution failed: {e}")
        return False
    
    print("\n🎉 All logic tools are properly discoverable and functional!")
    return True

async def test_mcp_tool_registration():
    """Test that tools are properly registered in the dataset_tools module."""
    
    print("\n🔧 Testing MCP Tool Registration")
    print("=" * 50)
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools import __all__
        
        # Check if tools are in __all__
        assert "text_to_fol" in __all__, "text_to_fol not in __all__"
        assert "legal_text_to_deontic" in __all__, "legal_text_to_deontic not in __all__"
        
        print("✅ Logic tools are properly registered in dataset_tools.__all__")
        print(f"📋 Available tools: {__all__}")
        
        return True
        
    except Exception as e:
        print(f"❌ Tool registration test failed: {e}")
        return False

async def test_mcp_server_discovery():
    """Test that the MCP server can discover these tools."""
    
    print("\n🖥️  Testing MCP Server Tool Discovery")
    print("=" * 50)
    
    try:
        # Try to import the server components
        from ipfs_datasets_py.mcp_server.server import import_tools_from_directory
        from pathlib import Path
        
        # Test tool discovery from the dataset_tools directory
        dataset_tools_path = Path("ipfs_datasets_py/mcp_server/tools/dataset_tools")
        tools = import_tools_from_directory(dataset_tools_path)
        
        # Check if our logic tools are discovered
        tool_names = list(tools.keys())
        
        # Look for our logic tools
        fol_found = any("fol" in name.lower() for name in tool_names)
        deontic_found = any("deontic" in name.lower() or "legal" in name.lower() for name in tool_names)
        
        print(f"🔍 Discovered {len(tools)} tools from dataset_tools directory:")
        for tool_name in sorted(tool_names):
            marker = "🎯" if "fol" in tool_name.lower() or "deontic" in tool_name.lower() or "legal" in tool_name.lower() else "  "
            print(f"   {marker} {tool_name}")
        
        if fol_found:
            print("✅ FOL tools discovered by MCP server")
        else:
            print("⚠️  FOL tools not found in server discovery")
            
        if deontic_found:
            print("✅ Deontic logic tools discovered by MCP server")  
        else:
            print("⚠️  Deontic logic tools not found in server discovery")
        
        return fol_found and deontic_found
        
    except Exception as e:
        print(f"❌ MCP server discovery test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all logic tool discoverability tests."""
    
    print("🧪 Logic Tools Discoverability Test Suite")
    print("=" * 60)
    
    # Run all tests
    results = []
    
    results.append(await test_tool_discovery())
    results.append(await test_mcp_tool_registration())
    results.append(await test_mcp_server_discovery())
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print("\n" + "=" * 60)
    print("📊 Discoverability Test Summary:")
    print(f"Tests Passed: {passed}/{total}")
    
    if passed == total:
        print("🏆 All logic tools are properly discoverable and integrated!")
        return 0
    else:
        print("⚠️  Some discoverability issues found.")
        return 1

if __name__ == "__main__":
    exit_code = anyio.run(main())
    sys.exit(exit_code)
