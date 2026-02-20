#!/usr/bin/env python3

# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.development_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.github_cli_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.development_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

# -*- coding: utf-8 -*-
"""
GitHub CLI MCP Tools

This module provides MCP (Model Context Protocol) tool wrappers for GitHub CLI functionality,
enabling AI assistants to interact with GitHub through standardized tool interfaces.

Available tools:
- GitHubCLIStatusTool: Get GitHub CLI installation status
- GitHubCLIInstallTool: Install or update GitHub CLI
- GitHubCLIExecuteTool: Execute GitHub CLI commands
- GitHubCLIAuthTool: Manage GitHub authentication
- GitHubCLIRepoTool: Manage GitHub repositories
"""

import logging
from typing import Dict, Any, List
from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.utils.github_cli import GitHubCLI

logger = logging.getLogger(__name__)

class GitHubCLIStatusTool(ClaudeMCPTool):
    """
    Tool for checking GitHub CLI installation status.
    
    Returns information about the GitHub CLI installation including version,
    installation path, and authentication status.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "github_cli_status"
        self.description = "Get GitHub CLI installation status and information"
        self.category = "development"
        self.tags = ["github", "cli", "development", "status"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "install_dir": {
                    "type": "string",
                    "description": "Optional custom installation directory path",
                    "default": None
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get GitHub CLI status.
        
        Args:
            parameters: Tool parameters with optional install_dir
        
        Returns:
            Dictionary with status information
        """
        try:
            install_dir = parameters.get("install_dir")
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

class GitHubCLIInstallTool(ClaudeMCPTool):
    """
    Tool for installing or updating GitHub CLI.
    
    Downloads and installs the GitHub CLI for the current platform.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "github_cli_install"
        self.description = "Install or update GitHub CLI"
        self.category = "development"
        self.tags = ["github", "cli", "development", "install"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "install_dir": {
                    "type": "string",
                    "description": "Optional custom installation directory path",
                    "default": None
                },
                "force": {
                    "type": "boolean",
                    "description": "Force reinstallation even if already installed",
                    "default": False
                },
                "version": {
                    "type": "string",
                    "description": "Optional specific GitHub CLI version to install (e.g., 'v2.40.0')",
                    "default": None
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Install GitHub CLI.
        
        Args:
            parameters: Tool parameters with install options
        
        Returns:
            Dictionary with installation result
        """
        try:
            install_dir = parameters.get("install_dir")
            force = parameters.get("force", False)
            version = parameters.get("version")
            
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

class GitHubCLIExecuteTool(ClaudeMCPTool):
    """
    Tool for executing GitHub CLI commands.
    
    Executes arbitrary GitHub CLI commands and returns the results.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "github_cli_execute"
        self.description = "Execute GitHub CLI commands"
        self.category = "development"
        self.tags = ["github", "cli", "development", "execute"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command arguments to pass to GitHub CLI",
                    "minItems": 1
                },
                "install_dir": {
                    "type": "string",
                    "description": "Optional custom installation directory path",
                    "default": None
                },
                "timeout": {
                    "type": "integer",
                    "description": "Command timeout in seconds",
                    "default": 60,
                    "minimum": 1,
                    "maximum": 300
                }
            },
            "required": ["command"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute GitHub CLI command.
        
        Args:
            parameters: Tool parameters with command and options
        
        Returns:
            Dictionary with command execution results
        """
        try:
            command = parameters.get("command", [])
            install_dir = parameters.get("install_dir")
            timeout = parameters.get("timeout", 60)
            
            if not command:
                return {
                    "success": False,
                    "error": "Command parameter is required"
                }
            
            cli = GitHubCLI(install_dir=install_dir)
            
            if not cli.is_installed():
                return {
                    "success": False,
                    "error": "GitHub CLI is not installed. Use github_cli_install tool first."
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

class GitHubCLIAuthTool(ClaudeMCPTool):
    """
    Tool for managing GitHub authentication.
    
    Login to GitHub and check authentication status.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "github_cli_auth"
        self.description = "Manage GitHub authentication (login, status)"
        self.category = "development"
        self.tags = ["github", "cli", "development", "auth", "authentication"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["login", "status"]
                },
                "hostname": {
                    "type": "string",
                    "description": "GitHub hostname (default: github.com, can use GitHub Enterprise)",
                    "default": "github.com"
                },
                "web": {
                    "type": "boolean",
                    "description": "Use web browser for authentication",
                    "default": True
                },
                "install_dir": {
                    "type": "string",
                    "description": "Optional custom installation directory path",
                    "default": None
                }
            },
            "required": ["action"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Manage GitHub authentication.
        
        Args:
            parameters: Tool parameters with action and options
        
        Returns:
            Dictionary with action results
        """
        try:
            action = parameters.get("action")
            hostname = parameters.get("hostname", "github.com")
            web = parameters.get("web", True)
            install_dir = parameters.get("install_dir")
            
            cli = GitHubCLI(install_dir=install_dir)
            
            if not cli.is_installed():
                return {
                    "success": False,
                    "error": "GitHub CLI is not installed. Use github_cli_install tool first."
                }
            
            if action == "login":
                result = cli.auth_login(hostname=hostname, web=web)
                return {
                    "success": result.returncode == 0,
                    "action": "login",
                    "hostname": hostname,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            
            elif action == "status":
                result = cli.auth_status()
                return {
                    "success": result.returncode == 0,
                    "action": "status",
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
                
        except Exception as e:
            logger.error(f"Failed to manage GitHub authentication: {e}")
            return {
                "success": False,
                "error": str(e)
            }

class GitHubCLIRepoTool(ClaudeMCPTool):
    """
    Tool for managing GitHub repositories.
    
    List and interact with repositories.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "github_cli_repo"
        self.description = "Manage GitHub repositories (list, etc.)"
        self.category = "development"
        self.tags = ["github", "cli", "development", "repository", "repo"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["list"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of repositories to list",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 100
                },
                "install_dir": {
                    "type": "string",
                    "description": "Optional custom installation directory path",
                    "default": None
                }
            },
            "required": ["action"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Manage GitHub repositories.
        
        Args:
            parameters: Tool parameters with action and options
        
        Returns:
            Dictionary with action results
        """
        try:
            action = parameters.get("action")
            limit = parameters.get("limit", 30)
            install_dir = parameters.get("install_dir")
            
            cli = GitHubCLI(install_dir=install_dir)
            
            if not cli.is_installed():
                return {
                    "success": False,
                    "error": "GitHub CLI is not installed. Use github_cli_install tool first."
                }
            
            if action == "list":
                repos = cli.repo_list(limit=limit)
                return {
                    "success": True,
                    "action": "list",
                    "repositories": repos,
                    "count": len(repos)
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
                
        except Exception as e:
            logger.error(f"Failed to manage GitHub repositories: {e}")
            return {
                "success": False,
                "error": str(e)
            }
