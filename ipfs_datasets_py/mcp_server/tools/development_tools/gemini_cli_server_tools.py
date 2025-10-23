#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Gemini CLI MCP Server Tools

This module provides MCP server tool functions for Google Gemini CLI integration.
These functions are designed to be registered with the MCP server for AI assistant access.
"""

from typing import Dict, Any, List, Optional
import logging
from ipfs_datasets_py.utils.gemini_cli import GeminiCLI

logger = logging.getLogger(__name__)


def gemini_cli_status(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Get Google Gemini CLI installation status and information.
    
    Returns information about the Gemini CLI installation including version
    and API key configuration status.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing status information
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        status = cli.get_status()
        
        return {
            "success": True,
            "status": status
        }
    except Exception as e:
        logger.error(f"Failed to get Gemini CLI status: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_cli_install(
    install_dir: Optional[str] = None,
    force: bool = False
) -> Dict[str, Any]:
    """
    Install Google Gemini CLI via pip.
    
    Args:
        install_dir: Optional custom installation directory path
        force: Force reinstallation even if already installed
    
    Returns:
        Dictionary with installation result
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        success = cli.install(force=force)
        
        if success:
            status = cli.get_status()
            return {
                "success": True,
                "message": "Gemini CLI installed successfully",
                "status": status
            }
        else:
            return {
                "success": False,
                "error": "Installation failed"
            }
    except Exception as e:
        logger.error(f"Failed to install Gemini CLI: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_cli_config_set_api_key(
    api_key: str,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Configure API key for Google Gemini.
    
    Args:
        api_key: Google Gemini API key
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with configuration result
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        success = cli.configure_api_key(api_key)
        
        return {
            "success": success,
            "message": "API key configured successfully" if success else "Failed to configure API key"
        }
    except Exception as e:
        logger.error(f"Failed to configure Gemini API key: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_cli_execute(
    command: List[str],
    install_dir: Optional[str] = None,
    timeout: int = 60,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a Gemini CLI command.
    
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
        
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
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
        logger.error(f"Failed to execute Gemini CLI command: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_cli_test_connection(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Test connection to Google Gemini API.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with test results
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        result = cli.test_connection()
        
        return result
    except Exception as e:
        logger.error(f"Failed to test Gemini connection: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def gemini_cli_list_models(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    List available Google Gemini models.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with model list
    """
    try:
        cli = GeminiCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "Gemini CLI is not installed. Use gemini_cli_install first."
            }
        
        models = cli.list_models()
        
        return {
            "success": True,
            "models": models,
            "count": len(models)
        }
    except Exception as e:
        logger.error(f"Failed to list Gemini models: {e}")
        return {
            "success": False,
            "error": str(e)
        }
