#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Gemini CLI MCP Tools

This module provides MCP (Model Context Protocol) tool wrappers for Google Gemini CLI functionality,
enabling AI assistants to interact with Gemini API through standardized tool interfaces.

Available tools:
- GeminiCLIStatusTool: Get Gemini CLI installation status
- GeminiCLIInstallTool: Install Gemini CLI
- GeminiCLIExecuteTool: Execute Gemini CLI commands
- GeminiCLIConfigTool: Configure API key and settings
"""

import logging
from typing import Dict, Any, List
from ipfs_datasets_py.mcp_tools.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.utils.gemini_cli import GeminiCLI

logger = logging.getLogger(__name__)


class GeminiCLIStatusTool(ClaudeMCPTool):
    """
    Tool for checking Gemini CLI installation status.
    
    Returns information about the Gemini CLI installation including version
    and API key configuration status.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "gemini_cli_status"
        self.description = "Get Google Gemini CLI installation status and information"
        self.category = "ai"
        self.tags = ["gemini", "cli", "ai", "status", "google"]
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
        Get Gemini CLI status.
        
        Args:
            parameters: Tool parameters with optional install_dir
        
        Returns:
            Dictionary with status information
        """
        try:
            install_dir = parameters.get("install_dir")
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


class GeminiCLIInstallTool(ClaudeMCPTool):
    """
    Tool for installing Gemini CLI.
    
    Installs the Google Gemini CLI via pip.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "gemini_cli_install"
        self.description = "Install Google Gemini CLI"
        self.category = "ai"
        self.tags = ["gemini", "cli", "ai", "install", "google"]
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
        Install Gemini CLI.
        
        Args:
            parameters: Tool parameters with install options
        
        Returns:
            Dictionary with installation result
        """
        try:
            install_dir = parameters.get("install_dir")
            force = parameters.get("force", False)
            
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


class GeminiCLIExecuteTool(ClaudeMCPTool):
    """
    Tool for executing Gemini CLI commands.
    
    Executes Gemini CLI commands and returns the results.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "gemini_cli_execute"
        self.description = "Execute Google Gemini CLI commands"
        self.category = "ai"
        self.tags = ["gemini", "cli", "ai", "execute", "google"]
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
        Execute Gemini CLI command.
        
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
            
            cli = GeminiCLI(install_dir=install_dir)
            
            if not cli.is_installed():
                return {
                    "success": False,
                    "error": "Gemini CLI is not installed. Use gemini_cli_install tool first."
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


class GeminiCLIConfigTool(ClaudeMCPTool):
    """
    Tool for configuring Gemini CLI.
    
    Configure API key and test connection.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "gemini_cli_config"
        self.description = "Configure Google Gemini CLI (API key, test connection)"
        self.category = "ai"
        self.tags = ["gemini", "cli", "ai", "config", "google"]
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
        Configure Gemini CLI.
        
        Args:
            parameters: Tool parameters with action and options
        
        Returns:
            Dictionary with action results
        """
        try:
            action = parameters.get("action")
            api_key = parameters.get("api_key")
            install_dir = parameters.get("install_dir")
            
            cli = GeminiCLI(install_dir=install_dir)
            
            if not cli.is_installed():
                return {
                    "success": False,
                    "error": "Gemini CLI is not installed. Use gemini_cli_install tool first."
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
            logger.error(f"Failed to configure Gemini CLI: {e}")
            return {
                "success": False,
                "error": str(e)
            }
