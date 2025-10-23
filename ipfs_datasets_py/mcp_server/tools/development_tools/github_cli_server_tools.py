#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub CLI MCP Server Tools

This module provides MCP server tool functions for GitHub CLI integration.
These functions are designed to be registered with the MCP server for AI assistant access.
"""

from typing import Dict, Any, List, Optional
import logging
from ipfs_datasets_py.utils.github_cli import GitHubCLI

logger = logging.getLogger(__name__)


def github_cli_status(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Get GitHub CLI installation status and information.
    
    Returns information about the GitHub CLI installation including version,
    installation path, platform, architecture, and authentication status.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary containing status information
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        status = cli.get_status()
        
        return {
            "success": True,
            "status": status
        }
    except Exception as e:
        logger.error(f"Failed to get GitHub CLI status: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_cli_install(
    install_dir: Optional[str] = None,
    force: bool = False,
    version: Optional[str] = None
) -> Dict[str, Any]:
    """
    Install or update GitHub CLI.
    
    Downloads and installs the GitHub CLI for the current platform and architecture.
    
    Args:
        install_dir: Optional custom installation directory path
        force: Force reinstallation even if already installed
        version: Optional specific GitHub CLI version to install (e.g., 'v2.40.0')
    
    Returns:
        Dictionary with installation result
    """
    try:
        cli = GitHubCLI(install_dir=install_dir, version=version)
        success = cli.download_and_install(force=force)
        
        if success:
            status = cli.get_status()
            return {
                "success": True,
                "message": "GitHub CLI installed successfully",
                "status": status
            }
        else:
            return {
                "success": False,
                "error": "Installation failed"
            }
    except Exception as e:
        logger.error(f"Failed to install GitHub CLI: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_cli_execute(
    command: List[str],
    install_dir: Optional[str] = None,
    timeout: int = 60
) -> Dict[str, Any]:
    """
    Execute a GitHub CLI command.
    
    Args:
        command: List of command arguments to pass to GitHub CLI
        install_dir: Optional custom installation directory path
        timeout: Command timeout in seconds (default: 60)
    
    Returns:
        Dictionary with command execution results
    """
    try:
        if not isinstance(command, list):
            return {
                "success": False,
                "error": "command must be a list of strings"
            }
        
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.execute(command, timeout=timeout)
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": command
        }
    except Exception as e:
        logger.error(f"Failed to execute GitHub CLI command: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_cli_auth_login(
    hostname: str = "github.com",
    web: bool = True,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Authenticate with GitHub.
    
    Args:
        hostname: GitHub hostname (default: github.com, can use GitHub Enterprise)
        web: Use web browser for authentication (default: True)
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with authentication result
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.auth_login(hostname=hostname, web=web)
        
        return {
            "success": result.returncode == 0,
            "hostname": hostname,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        logger.error(f"Failed to authenticate with GitHub: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_cli_auth_status(install_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Check GitHub authentication status.
    
    Args:
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with authentication status
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        result = cli.auth_status()
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        logger.error(f"Failed to get GitHub auth status: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def github_cli_repo_list(
    limit: int = 30,
    install_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    List user's GitHub repositories.
    
    Args:
        limit: Maximum number of repositories to list (default: 30)
        install_dir: Optional custom installation directory path
    
    Returns:
        Dictionary with repository list
    """
    try:
        cli = GitHubCLI(install_dir=install_dir)
        
        if not cli.is_installed():
            return {
                "success": False,
                "error": "GitHub CLI is not installed. Use github_cli_install first."
            }
        
        repos = cli.repo_list(limit=limit)
        
        return {
            "success": True,
            "repositories": repos,
            "count": len(repos)
        }
    except Exception as e:
        logger.error(f"Failed to list GitHub repositories: {e}")
        return {
            "success": False,
            "error": str(e)
        }
