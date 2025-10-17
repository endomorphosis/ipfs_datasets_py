#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test VSCode CLI Utility

Basic tests for VSCode CLI functionality.
"""

import os
import tempfile
from pathlib import Path
import pytest


def test_vscode_cli_import():
    """
    GIVEN the vscode_cli module
    WHEN importing VSCodeCLI
    THEN it should import successfully
    """
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    assert VSCodeCLI is not None


def test_vscode_cli_initialization():
    """
    GIVEN a temporary directory
    WHEN initializing VSCodeCLI
    THEN it should create the instance with correct attributes
    """
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = VSCodeCLI(install_dir=tmpdir)
        
        assert cli.install_dir == Path(tmpdir)
        assert cli.platform_name in ['linux', 'darwin', 'windows']
        assert cli.arch in ['x64', 'arm64']
        assert not cli.is_installed()


def test_vscode_cli_get_download_url():
    """
    GIVEN a VSCodeCLI instance
    WHEN getting the download URL
    THEN it should return a valid URL string
    """
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = VSCodeCLI(install_dir=tmpdir)
        url = cli.get_download_url()
        
        assert isinstance(url, str)
        assert 'vscode' in url.lower()
        assert 'download' in url.lower()


def test_vscode_cli_get_status():
    """
    GIVEN a VSCodeCLI instance
    WHEN getting status
    THEN it should return a status dictionary
    """
    from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = VSCodeCLI(install_dir=tmpdir)
        status = cli.get_status()
        
        assert isinstance(status, dict)
        assert 'installed' in status
        assert 'version' in status
        assert 'install_dir' in status
        assert 'executable' in status
        assert 'platform' in status
        assert 'architecture' in status
        assert 'extensions' in status
        assert status['installed'] is False


def test_create_vscode_cli():
    """
    GIVEN the create_vscode_cli function
    WHEN calling it
    THEN it should return a VSCodeCLI instance
    """
    from ipfs_datasets_py.utils.vscode_cli import create_vscode_cli, VSCodeCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = create_vscode_cli(install_dir=tmpdir)
        
        assert isinstance(cli, VSCodeCLI)


def test_mcp_tool_import():
    """
    GIVEN the vscode_cli_tools module
    WHEN importing MCP tools
    THEN they should import successfully
    """
    from ipfs_datasets_py.mcp_tools.tools.vscode_cli_tools import (
        VSCodeCLIStatusTool,
        VSCodeCLIInstallTool,
        VSCodeCLIExecuteTool,
        VSCodeCLIExtensionsTool,
        VSCodeCLITunnelTool
    )
    
    assert VSCodeCLIStatusTool is not None
    assert VSCodeCLIInstallTool is not None
    assert VSCodeCLIExecuteTool is not None
    assert VSCodeCLIExtensionsTool is not None
    assert VSCodeCLITunnelTool is not None


def test_mcp_tool_initialization():
    """
    GIVEN VSCode MCP tool classes
    WHEN initializing them
    THEN they should have correct attributes
    """
    from ipfs_datasets_py.mcp_tools.tools.vscode_cli_tools import VSCodeCLIStatusTool
    
    tool = VSCodeCLIStatusTool()
    
    assert tool.name == "vscode_cli_status"
    assert tool.description
    assert tool.category == "development"
    assert "vscode" in tool.tags


def test_mcp_server_tools_import():
    """
    GIVEN the MCP server vscode_cli_tools module
    WHEN importing tool functions
    THEN they should import successfully
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.vscode_cli_tools import (
            vscode_cli_status,
            vscode_cli_install,
            vscode_cli_execute,
            vscode_cli_list_extensions,
            vscode_cli_install_extension,
            vscode_cli_uninstall_extension,
            vscode_cli_tunnel_login,
            vscode_cli_tunnel_install_service
        )
        
        assert callable(vscode_cli_status)
        assert callable(vscode_cli_install)
        assert callable(vscode_cli_execute)
        assert callable(vscode_cli_list_extensions)
        assert callable(vscode_cli_install_extension)
        assert callable(vscode_cli_uninstall_extension)
        assert callable(vscode_cli_tunnel_login)
        assert callable(vscode_cli_tunnel_install_service)
    except ImportError as e:
        pytest.skip(f"MCP server dependencies not available: {e}")


def test_mcp_server_tool_status():
    """
    GIVEN the vscode_cli_status function
    WHEN calling it
    THEN it should return a status dictionary
    """
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.vscode_cli_tools import vscode_cli_status
        
        with tempfile.TemporaryDirectory() as tmpdir:
            result = vscode_cli_status(install_dir=tmpdir)
            
            assert isinstance(result, dict)
            assert 'success' in result
            assert result['success'] is True
            assert 'status' in result
            assert result['status']['installed'] is False
    except ImportError as e:
        pytest.skip(f"MCP server dependencies not available: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
