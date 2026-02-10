#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSCode CLI MCP Tools

This module provides MCP (Model Context Protocol) tool wrappers for VSCode CLI functionality,
enabling AI assistants to interact with VSCode through standardized tool interfaces.

Available tools:
- VSCodeCLIStatusTool: Get VSCode CLI installation status
- VSCodeCLIInstallTool: Install or update VSCode CLI
- VSCodeCLIExecuteTool: Execute VSCode CLI commands
- VSCodeCLIExtensionsTool: Manage VSCode extensions
- VSCodeCLITunnelTool: Manage VSCode tunnel functionality
"""

import logging
from typing import Dict, Any, List
from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.utils.vscode_cli import VSCodeCLI

logger = logging.getLogger(__name__)


class VSCodeCLIStatusTool(ClaudeMCPTool):
    """
    Tool for checking VSCode CLI installation status.
    
    Returns information about the VSCode CLI installation including version,
    installation path, and installed extensions.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "vscode_cli_status"
        self.description = "Get VSCode CLI installation status and information"
        self.category = "development"
        self.tags = ["vscode", "cli", "development", "status"]
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
        Get VSCode CLI status.
        
        Args:
            parameters: Tool parameters with optional install_dir
        
        Returns:
            Dictionary with status information
        """
        try:
            install_dir = parameters.get("install_dir")
            cli = VSCodeCLI(install_dir=install_dir)
            status = cli.get_status()
            
            return {
                "success": True,
                "status": status
            }
        except Exception as e:
            logger.error(f"Failed to get VSCode CLI status: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class VSCodeCLIInstallTool(ClaudeMCPTool):
    """
    Tool for installing or updating VSCode CLI.
    
    Downloads and installs the VSCode CLI for the current platform.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "vscode_cli_install"
        self.description = "Install or update VSCode CLI"
        self.category = "development"
        self.tags = ["vscode", "cli", "development", "install"]
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
                "commit": {
                    "type": "string",
                    "description": "Optional specific VSCode commit ID to install",
                    "default": None
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Install VSCode CLI.
        
        Args:
            parameters: Tool parameters with install options
        
        Returns:
            Dictionary with installation result
        """
        try:
            install_dir = parameters.get("install_dir")
            force = parameters.get("force", False)
            commit = parameters.get("commit")
            
            cli = VSCodeCLI(install_dir=install_dir, commit=commit)
            success = cli.download_and_install(force=force)
            
            if success:
                status = cli.get_status()
                return {
                    "success": True,
                    "message": "VSCode CLI installed successfully",
                    "status": status
                }
            else:
                return {
                    "success": False,
                    "error": "Installation failed"
                }
        except Exception as e:
            logger.error(f"Failed to install VSCode CLI: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class VSCodeCLIExecuteTool(ClaudeMCPTool):
    """
    Tool for executing VSCode CLI commands.
    
    Executes arbitrary VSCode CLI commands and returns the results.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "vscode_cli_execute"
        self.description = "Execute VSCode CLI commands"
        self.category = "development"
        self.tags = ["vscode", "cli", "development", "execute"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command arguments to pass to VSCode CLI",
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
        Execute VSCode CLI command.
        
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
            
            cli = VSCodeCLI(install_dir=install_dir)
            
            if not cli.is_installed():
                return {
                    "success": False,
                    "error": "VSCode CLI is not installed. Use vscode_cli_install tool first."
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
            logger.error(f"Failed to execute VSCode CLI command: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class VSCodeCLIExtensionsTool(ClaudeMCPTool):
    """
    Tool for managing VSCode extensions.
    
    List, install, and uninstall VSCode extensions.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "vscode_cli_extensions"
        self.description = "Manage VSCode extensions (list, install, uninstall)"
        self.category = "development"
        self.tags = ["vscode", "cli", "development", "extensions"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["list", "install", "uninstall"]
                },
                "extension_id": {
                    "type": "string",
                    "description": "Extension ID for install/uninstall actions"
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
        Manage VSCode extensions.
        
        Args:
            parameters: Tool parameters with action and options
        
        Returns:
            Dictionary with action results
        """
        try:
            action = parameters.get("action")
            extension_id = parameters.get("extension_id")
            install_dir = parameters.get("install_dir")
            
            cli = VSCodeCLI(install_dir=install_dir)
            
            if not cli.is_installed():
                return {
                    "success": False,
                    "error": "VSCode CLI is not installed. Use vscode_cli_install tool first."
                }
            
            if action == "list":
                extensions = cli.list_extensions()
                return {
                    "success": True,
                    "action": "list",
                    "extensions": extensions,
                    "count": len(extensions)
                }
            
            elif action == "install":
                if not extension_id:
                    return {
                        "success": False,
                        "error": "extension_id is required for install action"
                    }
                success = cli.install_extension(extension_id)
                return {
                    "success": success,
                    "action": "install",
                    "extension_id": extension_id,
                    "message": f"Extension {extension_id} {'installed' if success else 'failed to install'}"
                }
            
            elif action == "uninstall":
                if not extension_id:
                    return {
                        "success": False,
                        "error": "extension_id is required for uninstall action"
                    }
                success = cli.uninstall_extension(extension_id)
                return {
                    "success": success,
                    "action": "uninstall",
                    "extension_id": extension_id,
                    "message": f"Extension {extension_id} {'uninstalled' if success else 'failed to uninstall'}"
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
                
        except Exception as e:
            logger.error(f"Failed to manage VSCode extensions: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class VSCodeCLITunnelTool(ClaudeMCPTool):
    """
    Tool for managing VSCode tunnel functionality.
    
    Login to tunnel service and manage tunnel installation.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "vscode_cli_tunnel"
        self.description = "Manage VSCode tunnel (login, install service)"
        self.category = "development"
        self.tags = ["vscode", "cli", "development", "tunnel", "remote"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["login", "install_service"]
                },
                "provider": {
                    "type": "string",
                    "description": "Auth provider for login (github or microsoft)",
                    "enum": ["github", "microsoft"],
                    "default": "github"
                },
                "tunnel_name": {
                    "type": "string",
                    "description": "Optional tunnel name for service installation"
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
        Manage VSCode tunnel.
        
        Args:
            parameters: Tool parameters with action and options
        
        Returns:
            Dictionary with action results
        """
        try:
            action = parameters.get("action")
            provider = parameters.get("provider", "github")
            tunnel_name = parameters.get("tunnel_name")
            install_dir = parameters.get("install_dir")
            
            cli = VSCodeCLI(install_dir=install_dir)
            
            if not cli.is_installed():
                return {
                    "success": False,
                    "error": "VSCode CLI is not installed. Use vscode_cli_install tool first."
                }
            
            if action == "login":
                result = cli.tunnel_user_login(provider=provider)
                return {
                    "success": result.returncode == 0,
                    "action": "login",
                    "provider": provider,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            
            elif action == "install_service":
                result = cli.tunnel_service_install(name=tunnel_name)
                return {
                    "success": result.returncode == 0,
                    "action": "install_service",
                    "tunnel_name": tunnel_name,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
                
        except Exception as e:
            logger.error(f"Failed to manage VSCode tunnel: {e}")
            return {
                "success": False,
                "error": str(e)
            }
