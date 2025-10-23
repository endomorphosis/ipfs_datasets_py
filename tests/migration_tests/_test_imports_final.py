#!/usr/bin/env python3
"""
Test imports with fixed __init__.py
"""
import sys
import os
import pytest

sys.path.insert(0, '.')


def test_config_import():
    """Test that config can be imported and instantiated."""
    from ipfs_datasets_py.config import config as Config
    config_instance = Config()
    assert config_instance is not None


def test_base_tool_import():
    """Test that BaseDevelopmentTool can be imported."""
    from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseDevelopmentTool
    assert BaseDevelopmentTool is not None


@pytest.mark.parametrize("tool_name,module_path,function_or_class_name", [
    ("test_generator", "ipfs_datasets_py.mcp_server.tools.development_tools.test_generator", "test_generator"),
    ("documentation_generator", "ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator", "documentation_generator"),
    ("codebase_search", "ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search", "codebase_search"),
    ("LintingTools", "ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools", "LintingTools"),
    ("TestRunner", "ipfs_datasets_py.mcp_server.tools.development_tools.test_runner", "TestRunner"),
])
def test_individual_tool_imports(tool_name, module_path, function_or_class_name):
    """Test that individual tools can be imported and instantiated."""
    module = __import__(module_path, fromlist=[function_or_class_name])
    tool_func_or_class = getattr(module, function_or_class_name)
    assert tool_func_or_class is not None
    
    # For functions, just check callable; for classes, try to instantiate
    if callable(tool_func_or_class) and not hasattr(tool_func_or_class, '__bases__'):
        # It's a function
        assert callable(tool_func_or_class)
    else:
        # It's a class, try to instantiate
        tool_instance = tool_func_or_class()
        assert tool_instance is not None
