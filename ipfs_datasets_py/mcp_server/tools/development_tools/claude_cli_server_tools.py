#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anthropic Claude CLI MCP Server Tools

This module provides MCP server tool functions for Anthropic Claude CLI integration.
These functions are designed to be registered with the MCP server for AI assistant access.
"""

from typing import Dict, Any, List, Optional
import logging
from ipfs_datasets_py.utils.claude_cli import ClaudeCLI

logger = logging.getLogger(__name__)


def claude_cli_status(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Get Anthropic Claude CLI installation status and information.
    
    Returns information about the Claude CLI installation including version
    and API key configuration status.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing status information
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        status = cli.get_status()
        
        return {
            "success": True,
            "status": status
        }
    except Exception as e:
        logger.error(f"Failed to get Claude CLI status: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_cli_install(
    install_dir: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Install Anthropic Claude CLI via pip.
    
    Args:
        install_dir: Optional custom installation directory path
        force: Force reinstallation even if already installed
    
    Returns:
        Dictionary with installation result
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        success = cli.install(force=force)
        
        if success:
            status = cli.get_status()
            return {
                "success": True,
                "message": "Claude CLI installed successfully",
                "status": status
            }
        else:
            return {
                "success": False,
                "error": "Installation failed"
            }
    except Exception as e:
        logger.error(f"Failed to install Claude CLI: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_cli_config_set_api_key(
    api_key: str,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Configure API key for Anthropic Claude.
    
    Args:
        api_key: Anthropic Claude API key
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with configuration result
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        success = cli.configure_api_key(api_key)
        
        return {
            "success": success,
            "message": "API key configured successfully" if success else "Failed to configure API key"
        }
    except Exception as e:
        logger.error(f"Failed to configure Claude API key: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_cli_execute(
    command: List[str],
    install_dir: Optional[str] = None,
    timeout: int = 60,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a Claude CLI command.
    
    Args:
        command: List of command arguments (e.g., ['chat', 'Hello world'])
        install_dir: Optional custom installation directory path
        timeout: Command timeout in seconds (default: 60)
        api_key: Optional API key to use (overrides configured key)
    
    Returns:
        Dictionary with command execution results
    """
    try:
        if not isinstance(command, list):
            return {
                "success": False,
                "error": "command must be a list of strings"
            }
        
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        result = cli.execute(command, timeout=timeout, api_key=api_key)
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command
        }
    except Exception as e:
        logger.error(f"Failed to execute Claude CLI command: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_cli_test_connection(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Test connection to Anthropic Claude API.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with test results
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        result = cli.test_connection()
        
        return result
    except Exception as e:
        logger.error(f"Failed to test Claude connection: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def claude_cli_list_models(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    List available Anthropic Claude models.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with model list
    """
    try:
        cli = ClaudeCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Claude CLI is not installed. Use claude_cli_install first."
            }
        
        models = cli.list_models()
        
        return {
            "success": True,
            "models": models,
            "count": len(models)
        }
    except Exception as e:
        logger.error(f"Failed to list Claude models: {e}")
        return {
            "success": False,
            "error": str(e)
        }
