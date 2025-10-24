#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Google Gemini CLI Utility

Basic tests for Gemini CLI functionality.
"""

import os
import tempfile
from pathlib import Path
import pytest


def test_gemini_cli_import():
    """
    GIVEN the gemini_cli module
    WHEN importing GeminiCLI
    THEN it should import successfully
    """
    from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
    assert GeminiCLI is not None


def test_gemini_cli_initialization():
    """
    GIVEN a temporary directory
    WHEN initializing GeminiCLI
    THEN it should create the instance with correct attributes
    """
    from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = GeminiCLI(install_dir=tmpdir)
        
        assert cli.install_dir == Path(tmpdir)
        assert cli.cli_module == "google-generativeai"
        assert cli.api_key_file.parent == Path(tmpdir)


def test_gemini_cli_get_status():
    """
    GIVEN a GeminiCLI instance
    WHEN getting status
    THEN it should return a status dictionary
    """
    from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = GeminiCLI(install_dir=tmpdir)
        status = cli.get_status()
        
        assert isinstance(status, dict)
        assert 'installed' in status
        assert 'version' in status
        assert 'install_dir' in status
        assert 'config_file' in status
        assert 'api_key_configured' in status
        assert 'package' in status
        assert status['api_key_configured'] is False


def test_gemini_cli_custom_directory():
    """
    GIVEN a custom installation directory
    WHEN creating GeminiCLI instance
    THEN it should use the custom directory
    """
    from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_dir = os.path.join(tmpdir, 'custom_gemini')
        cli = GeminiCLI(install_dir=custom_dir)
        
        assert cli.install_dir == Path(custom_dir)
        assert cli.install_dir.exists()


def test_gemini_cli_api_key_configuration():
    """
    GIVEN a GeminiCLI instance
    WHEN configuring API key
    THEN it should save and retrieve the key
    """
    from ipfs_datasets_py.utils.gemini_cli import GeminiCLI
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cli = GeminiCLI(install_dir=tmpdir)
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


def test_gemini_cli_mcp_tools_import():
    """
    GIVEN the gemini_cli_tools module
    WHEN importing MCP tools
    THEN all tools should import successfully
    """
    from ipfs_datasets_py.mcp_tools.tools.gemini_cli_tools import (
        GeminiCLIStatusTool,
        GeminiCLIInstallTool,
        GeminiCLIExecuteTool,
        GeminiCLIConfigTool
    )
    
    assert GeminiCLIStatusTool is not None
    assert GeminiCLIInstallTool is not None
    assert GeminiCLIExecuteTool is not None
    assert GeminiCLIConfigTool is not None


def test_gemini_cli_mcp_tool_initialization():
    """
    GIVEN Gemini CLI MCP tools
    WHEN initializing them
    THEN they should have correct names and descriptions
    """
    from ipfs_datasets_py.mcp_tools.tools.gemini_cli_tools import (
        GeminiCLIStatusTool,
        GeminiCLIInstallTool
    )
    
    status_tool = GeminiCLIStatusTool()
    assert status_tool.name == "gemini_cli_status"
    assert "gemini" in status_tool.description.lower()
    
    install_tool = GeminiCLIInstallTool()
    assert install_tool.name == "gemini_cli_install"
    assert "install" in install_tool.description.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
