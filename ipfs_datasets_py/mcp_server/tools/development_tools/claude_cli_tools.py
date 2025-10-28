#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anthropic Claude CLI MCP Tools

This module provides MCP (Model Context Protocol) tool wrappers for Anthropic Claude CLI functionality,
enabling AI assistants to interact with Claude API through standardized tool interfaces.

Available tools:
- ClaudeCLIStatusTool: Get Claude CLI installation status
- ClaudeCLIInstallTool: Install Claude CLI
- ClaudeCLIExecuteTool: Execute Claude CLI commands
- ClaudeCLIConfigTool: Configure API key and settings
"""

import logging
from typing import Dict, Any, List
from ipfs_datasets_py.mcp_tools.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.utils.claude_cli import ClaudeCLI

logger = logging.getLogger(__name__)


class ClaudeCLIStatusTool(ClaudeMCPTool):
    """
    Tool for checking Claude CLI installation status.
    
    Returns information about the Claude CLI installation including version
    and API key configuration status.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "claude_cli_status"
        self.description = "Get Anthropic Claude CLI installation status and information"
        self.category = "ai"
        self.tags = ["claude", "cli", "ai", "status", "anthropic"]
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
        Get Claude CLI status.
        
        Args:
            parameters: Tool parameters with optional install_dir
        
        Returns:
            Dictionary with status information
        """
        try:
            install_dir = parameters.get("install_dir")
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


class ClaudeCLIInstallTool(ClaudeMCPTool):
    """
    Tool for installing Claude CLI.
    
    Installs the Anthropic Claude CLI via pip.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "claude_cli_install"
        self.description = "Install Anthropic Claude CLI"
        self.category = "ai"
        self.tags = ["claude", "cli", "ai", "install", "anthropic"]
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
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Install Claude CLI.
        
        Args:
            parameters: Tool parameters with install options
        
        Returns:
            Dictionary with installation result
        """
        try:
            install_dir = parameters.get("install_dir")
            force = parameters.get("force", False)
            
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


class ClaudeCLIExecuteTool(ClaudeMCPTool):
    """
    Tool for executing Claude CLI commands.
    
    Executes Claude CLI commands and returns the results.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "claude_cli_execute"
        self.description = "Execute Anthropic Claude CLI commands"
        self.category = "ai"
        self.tags = ["claude", "cli", "ai", "execute", "anthropic"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command arguments (e.g., ['chat', 'Hello world'])",
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
                },
                "api_key": {
                    "type": "string",
                    "description": "Optional API key (overrides configured key)",
                    "default": None
                }
            },
            "required": ["command"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Claude CLI command.
        
        Args:
            parameters: Tool parameters with command and options
        
        Returns:
            Dictionary with command execution results
        """
        try:
            command = parameters.get("command", [])
            install_dir = parameters.get("install_dir")
            timeout = parameters.get("timeout", 60)
            api_key = parameters.get("api_key")
            
            if not command:
                return {
                    "success": False,
                    "error": "Command parameter is required"
                }
            
            cli = ClaudeCLI(install_dir=install_dir)
            
            if not cli.is_installed():
                return {
                    "success": False,
                    "error": "Claude CLI is not installed. Use claude_cli_install tool first."
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


class ClaudeCLIConfigTool(ClaudeMCPTool):
    """
    Tool for configuring Claude CLI.
    
    Configure API key and test connection.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "claude_cli_config"
        self.description = "Configure Anthropic Claude CLI (API key, test connection)"
        self.category = "ai"
        self.tags = ["claude", "cli", "ai", "config", "anthropic"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["set_api_key", "test_connection", "list_models"]
                },
                "api_key": {
                    "type": "string",
                    "description": "API key for set_api_key action"
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
        Configure Claude CLI.
        
        Args:
            parameters: Tool parameters with action and options
        
        Returns:
            Dictionary with action results
        """
        try:
            action = parameters.get("action")
            api_key = parameters.get("api_key")
            install_dir = parameters.get("install_dir")
            
            cli = ClaudeCLI(install_dir=install_dir)
            
            if not cli.is_installed():
                return {
                    "success": False,
                    "error": "Claude CLI is not installed. Use claude_cli_install tool first."
                }
            
            if action == "set_api_key":
                if not api_key:
                    return {
                        "success": False,
                        "error": "api_key parameter is required for set_api_key action"
                    }
                success = cli.configure_api_key(api_key)
                return {
                    "success": success,
                    "action": "set_api_key",
                    "message": "API key configured successfully" if success else "Failed to configure API key"
                }
            
            elif action == "test_connection":
                test_result = cli.test_connection()
                return {
                    "success": test_result['success'],
                    "action": "test_connection",
                    "response": test_result.get('response'),
                    "error": test_result.get('error')
                }
            
            elif action == "list_models":
                models = cli.list_models()
                return {
                    "success": True,
                    "action": "list_models",
                    "models": models,
                    "count": len(models)
                }
            
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}"
                }
                
        except Exception as e:
            logger.error(f"Failed to configure Claude CLI: {e}")
            return {
                "success": False,
                "error": str(e)
            }
