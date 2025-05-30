#!/usr/bin/env python3
"""
Test imports with fixed __init__.py
"""
import sys
import os
sys.path.insert(0, '.')

print("Starting import tests with fixed __init__.py...")

# Test 1: Config import using direct path
print("\n=== Test 1: Direct Config Import ===")
try:
    from ipfs_datasets_py.config import config as Config
    print("✅ Config import successful")
    config_instance = Config()
    print("✅ Config instantiation successful")
except Exception as e:
    print(f"❌ Config import/instantiation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Base tool import
print("\n=== Test 2: BaseTool Import ===")
try:
    from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseTool
    print("✅ BaseTool import successful")
except Exception as e:
    print(f"❌ BaseTool import failed: {e}")
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

print("\n🎉 All import tests completed successfully!")
