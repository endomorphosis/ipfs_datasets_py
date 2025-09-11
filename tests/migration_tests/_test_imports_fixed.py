#!/usr/bin/env python3
"""
Test imports one by one to identify which specific import is hanging
"""
import sys
import os
sys.path.insert(0, '.')

print("Starting import tests...")

# Test 1: Basic config import
print("\n=== Test 1: config Import ===")
try:
    from ipfs_datasets_py.config import config
    print("✅ config import successful")
    config = config()
    print("✅ config instantiation successful")
except Exception as e:
    print(f"❌ config import/instantiation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Base tool import
print("\n=== Test 2: BaseDevelopmentTool Import ===")
try:
    from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseDevelopmentTool
    print("✅ BaseDevelopmentTool import successful")
except Exception as e:
    print(f"❌ BaseDevelopmentTool import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Individual tool imports
tools_to_test = [
    ("TestGenerator", "ipfs_datasets_py.mcp_server.tools.development_tools.test_generator", "TestGenerator"),
    ("DocumentationGenerator", "ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator", "DocumentationGenerator"),
    ("CodebaseSearch", "ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search", "CodebaseSearch"),
    ("LintingTools", "ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools", "LintingTools"),
    ("TestRunner", "ipfs_datasets_py.mcp_server.tools.development_tools.test_runner", "TestRunner"),
]

for tool_name, module_path, class_name in tools_to_test:
    print(f"\n=== Test: {tool_name} Import ===")
    try:
        module = __import__(module_path, fromlist=[class_name])
        tool_class = getattr(module, class_name)
        print(f"✅ {tool_name} import successful")
        
        # Try to instantiate
        tool_instance = tool_class()
        print(f"✅ {tool_name} instantiation successful")
    except Exception as e:
        print(f"❌ {tool_name} import/instantiation failed: {e}")
        import traceback
        traceback.print_exc()
        # Continue with other tools instead of exiting

print("\n🎉 Import tests completed!")
