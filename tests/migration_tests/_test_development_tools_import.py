#!/usr/bin/env python3
"""Test development tools import functionality."""

import sys
from pathlib import Path
import pytest

# Add current directory to path
sys.path.insert(0, str(Path.cwd()))


def test_base_tool_import():
    """Test that base_tool can be imported."""
    from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import BaseDevelopmentTool
    assert BaseDevelopmentTool is not None


def test_config_import():
    """Test that config can be imported."""
    from ipfs_datasets_py.mcp_server.tools.development_tools.config import get_config
    assert get_config is not None


def test_test_generator_import():
    """Test that test_generator can be imported."""
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator
    assert test_generator is not None


def test_codebase_search_import():
    """Test that codebase_search can be imported."""
    from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
    assert codebase_search is not None


def test_documentation_generator_import():
    """Test that documentation_generator can be imported."""
    from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import documentation_generator
    assert documentation_generator is not None


def test_linting_tools_import():
    """Test that linting_tools can be imported."""
    from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase
    assert lint_python_codebase is not None


def test_test_runner_import():
    """Test that test_runner can be imported."""
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
    assert run_comprehensive_tests is not None


def test_tool_discovery():
    """Test the tool discovery mechanism."""
    from ipfs_datasets_py.mcp_server.server import import_tools_from_directory
    tools_path = Path('ipfs_datasets_py/mcp_server/tools/development_tools')
    tools = import_tools_from_directory(tools_path)
    assert isinstance(tools, dict)
    assert len(tools) > 0
