#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Anthropic Claude CLI Utility

Basic tests for Claude CLI functionality.
"""

import os
import tempfile
from pathlib import Path
import pytest


def test_claude_cli_import():
    """
    GIVEN the claude_cli module
    WHEN importing ClaudeCLI
    THEN it should import successfully
    """
    from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
    assert ClaudeCLI is not None


def test_claude_cli_initialization():
    """
    GIVEN a temporary directory
    WHEN initializing ClaudeCLI
    THEN it should create the instance with correct attributes
    """
    from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = ClaudeCLI(install_dir=tmpdir)
        
        assert cli.install_dir == Path(tmpdir)
        assert cli.cli_module == "anthropic"
        assert cli.api_key_file.parent == Path(tmpdir)


def test_claude_cli_get_status():
    """
    GIVEN a ClaudeCLI instance
    WHEN getting status
    THEN it should return a status dictionary
    """
    from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = ClaudeCLI(install_dir=tmpdir)
        status = cli.get_status()
        
        assert isinstance(status, dict)
        assert 'installed' in status
        assert 'version' in status
        assert 'install_dir' in status
        assert 'config_file' in status
        assert 'api_key_configured' in status
        assert 'package' in status
        assert status['api_key_configured'] is False


def test_claude_cli_custom_directory():
    """
    GIVEN a custom installation directory
    WHEN creating ClaudeCLI instance
    THEN it should use the custom directory
    """
    from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_dir = os.path.join(tmpdir, 'custom_claude')
        cli = ClaudeCLI(install_dir=custom_dir)
        
        assert cli.install_dir == Path(custom_dir)
        assert cli.install_dir.exists()


def test_claude_cli_api_key_configuration():
    """
    GIVEN a ClaudeCLI instance
    WHEN configuring API key
    THEN it should save and retrieve the key
    """
    from ipfs_datasets_py.utils.claude_cli import ClaudeCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = ClaudeCLI(install_dir=tmpdir)
        test_key = "test_api_key_12345"
        
        # Configure API key
        success = cli.configure_api_key(test_key)
        assert success is True
        
        # Retrieve API key
        retrieved_key = cli.get_api_key()
        assert retrieved_key == test_key
        
        # Check status
        status = cli.get_status()
        assert status['api_key_configured'] is True


def test_claude_cli_mcp_tools_import():
    """
    GIVEN the claude_cli_tools module
    WHEN importing MCP tools
    THEN all tools should import successfully
    """
    from ipfs_datasets_py.mcp_tools.tools.claude_cli_tools import (
        ClaudeCLIStatusTool,
        ClaudeCLIInstallTool,
        ClaudeCLIExecuteTool,
        ClaudeCLIConfigTool
    )
    
    assert ClaudeCLIStatusTool is not None
    assert ClaudeCLIInstallTool is not None
    assert ClaudeCLIExecuteTool is not None
    assert ClaudeCLIConfigTool is not None


def test_claude_cli_mcp_tool_initialization():
    """
    GIVEN Claude CLI MCP tools
    WHEN initializing them
    THEN they should have correct names and descriptions
    """
    from ipfs_datasets_py.mcp_tools.tools.claude_cli_tools import (
        ClaudeCLIStatusTool,
        ClaudeCLIInstallTool
    )
    
    status_tool = ClaudeCLIStatusTool()
    assert status_tool.name == "claude_cli_status"
    assert "claude" in status_tool.description.lower()
    
    install_tool = ClaudeCLIInstallTool()
    assert install_tool.name == "claude_cli_install"
    assert "install" in install_tool.description.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
