#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test GitHub CLI Utility

Basic tests for GitHub CLI functionality.
"""

import os
import tempfile
from pathlib import Path
import pytest


def test_github_cli_import():
    """
    GIVEN the github_cli module
    WHEN importing GitHubCLI
    THEN it should import successfully
    """
    from ipfs_datasets_py.utils.github_cli import GitHubCLI
    assert GitHubCLI is not None


def test_github_cli_initialization():
    """
    GIVEN a temporary directory
    WHEN initializing GitHubCLI
    THEN it should create the instance with correct attributes
    """
    from ipfs_datasets_py.utils.github_cli import GitHubCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = GitHubCLI(install_dir=tmpdir)
        
        assert cli.install_dir == Path(tmpdir)
        assert cli.platform_name in ['linux', 'darwin', 'windows']
        assert cli.arch in ['x64', 'arm64']
        assert not cli.is_installed()


def test_github_cli_get_download_url():
    """
    GIVEN a GitHubCLI instance
    WHEN getting the download URL
    THEN it should return a valid URL string
    """
    from ipfs_datasets_py.utils.github_cli import GitHubCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = GitHubCLI(install_dir=tmpdir)
        url = cli.get_download_url()
        
        assert isinstance(url, str)
        assert 'github.com' in url.lower()
        assert 'cli/cli' in url.lower()


def test_github_cli_get_status():
    """
    GIVEN a GitHubCLI instance
    WHEN getting status
    THEN it should return a status dictionary
    """
    from ipfs_datasets_py.utils.github_cli import GitHubCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = GitHubCLI(install_dir=tmpdir)
        status = cli.get_status()
        
        assert isinstance(status, dict)
        assert 'installed' in status
        assert 'version' in status
        assert 'install_dir' in status
        assert 'executable' in status
        assert 'platform' in status
        assert 'architecture' in status
        assert 'auth_status' in status
        assert status['installed'] is False


def test_github_cli_custom_directory():
    """
    GIVEN a custom installation directory
    WHEN creating GitHubCLI instance
    THEN it should use the custom directory
    """
    from ipfs_datasets_py.utils.github_cli import GitHubCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_dir = os.path.join(tmpdir, 'custom_github')
        cli = GitHubCLI(install_dir=custom_dir)
        
        assert cli.install_dir == Path(custom_dir)
        assert cli.install_dir.exists()


def test_github_cli_mcp_tools_import():
    """
    GIVEN the github_cli_tools module
    WHEN importing MCP tools
    THEN all tools should import successfully
    """
    from ipfs_datasets_py.mcp_tools.tools.github_cli_tools import (
        GitHubCLIStatusTool,
        GitHubCLIInstallTool,
        GitHubCLIExecuteTool,
        GitHubCLIAuthTool,
        GitHubCLIRepoTool
    )
    
    assert GitHubCLIStatusTool is not None
    assert GitHubCLIInstallTool is not None
    assert GitHubCLIExecuteTool is not None
    assert GitHubCLIAuthTool is not None
    assert GitHubCLIRepoTool is not None


def test_github_cli_mcp_tool_initialization():
    """
    GIVEN GitHub CLI MCP tools
    WHEN initializing them
    THEN they should have correct names and descriptions
    """
    from ipfs_datasets_py.mcp_tools.tools.github_cli_tools import (
        GitHubCLIStatusTool,
        GitHubCLIInstallTool
    )
    
    status_tool = GitHubCLIStatusTool()
    assert status_tool.name == "github_cli_status"
    assert "github" in status_tool.description.lower()
    
    install_tool = GitHubCLIInstallTool()
    assert install_tool.name == "github_cli_install"
    assert "install" in install_tool.description.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
