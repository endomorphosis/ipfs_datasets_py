#!/usr/bin/env python3
"""Fix lizardpersons function tools by creating test functions/programs"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def fix_lizardpersons_tools():
    """Fix lizardpersons tools by creating required test files"""
    
    print("🔧 Fixing Lizardpersons Function Tools")
    print("=" * 50)
    
    # Create a test function in the functions directory
    functions_dir = Path("ipfs_datasets_py/mcp_server/tools/lizardpersons_function_tools/functions")
    functions_dir.mkdir(exist_ok=True)
    
    # Create a test function file
    test_function_file = functions_dir / "test_function_name.py"
    test_function_content = '''"""Test function for MCP tool testing"""

def test_function(input_data="test"):
    """A simple test function"""
    return {
        "status": "success",
        "result": f"Processed: {input_data}",
        "function": "test_function_name"
    }

if __name__ == "__main__":
    print(test_function("hello world"))
'''
    
    with open(test_function_file, "w") as f:
        f.write(test_function_content)
    
    print(f"✅ Created test function: {test_function_file}")
    
    # Create a test CLI program
    cli_dir = Path("ipfs_datasets_py/mcp_server/tools/lizardpersons_function_tools/cli")
    cli_dir.mkdir(exist_ok=True)
    
    test_program_file = cli_dir / "test_program_name.py"
    test_program_content = '''#!/usr/bin/env python3
"""Test CLI program for MCP tool testing"""

import sys
import json

def main():
    """Main function for test program"""
    args = sys.argv[1:] if len(sys.argv) > 1 else ["default"]
    
    result = {
        "status": "success",
        "program": "test_program_name",
        "args": args,
        "result": f"Processed args: {args}"
    }
    
    print(json.dumps(result))
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''
    
    with open(test_program_file, "w") as f:
        f.write(test_program_content)
    
    # Make it executable
    test_program_file.chmod(0o755)
    
    print(f"✅ Created test CLI program: {test_program_file}")
    
    # Test the lizardpersons tools
    results = []
    
    print("\n🧪 Testing Fixed Lizardpersons Tools:")
    
    # Test 1: use_function_as_tool
    try:
        from ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.meta_tools.use_function_as_tool import use_function_as_tool
        result = use_function_as_tool(
            function_name="test_function_name", 
            functions_docstring="Test function for MCP testing",
            kwargs_dict={"input_data": "test_input"}
        )
        status = "✅ PASS" if isinstance(result, dict) and not result.get("error") else "❌ FAIL"
        results.append(("use_function_as_tool", status, f"Result: {result.get('status', 'success')}"))
        print(f"use_function_as_tool: {status}")
    except Exception as e:
        results.append(("use_function_as_tool", "❌ FAIL", str(e)))
        print(f"use_function_as_tool: ❌ FAIL - {e}")
    
    # Test 2: use_cli_program_as_tool
    try:
        from ipfs_datasets_py.mcp_server.tools.lizardpersons_function_tools.meta_tools.use_cli_program_as_tool import use_cli_program_as_tool
        result = use_cli_program_as_tool(
            program_name="test_program_name", 
            cli_arguments=["test", "args"]
        )
        status = "✅ PASS" if isinstance(result, dict) and not result.get("error") else "❌ FAIL"
        results.append(("use_cli_program_as_tool", status, f"Result: {result.get('status', 'success')}"))
        print(f"use_cli_program_as_tool: {status}")
    except Exception as e:
        results.append(("use_cli_program_as_tool", "❌ FAIL", str(e)))
        print(f"use_cli_program_as_tool: ❌ FAIL - {e}")
    
    print(f"\n📊 Lizardpersons Tools Test Results:")
    passed = sum(1 for _, status, _ in results if "PASS" in status)
    total = len(results)
    print(f"  Passed: {passed}/{total} ({passed/total*100:.1f}%)")
    
    for tool_name, status, message in results:
        print(f"  {status} {tool_name}: {message}")
    
    return results

if __name__ == "__main__":
    fix_lizardpersons_tools()
