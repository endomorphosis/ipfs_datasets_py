#!/usr/bin/env python3

# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.development_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.copilot_cli_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.development_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

# -*- coding: utf-8 -*-
"""
GitHub Copilot CLI MCP Tools

This module provides MCP (Model Context Protocol) tool wrappers for GitHub Copilot CLI functionality,
enabling AI assistants to interact with GitHub Copilot through standardized tool interfaces.

Available tools:
- CopilotCLIStatusTool: Get Copilot CLI installation status
- CopilotCLIInstallTool: Install or update Copilot CLI
- CopilotCLIExplainTool: Get AI explanations for code
- CopilotCLISuggestCommandTool: Get command suggestions from natural language
- CopilotCLISuggestGitTool: Get Git command suggestions
"""

import logging
from typing import Dict, Any, List
from ipfs_datasets_py.mcp_server.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

logger = logging.getLogger(__name__)

class CopilotCLIStatusTool(ClaudeMCPTool):
    """
    Tool for checking GitHub Copilot CLI installation status.
    
    Returns information about the Copilot CLI installation including version
    and GitHub CLI availability.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "copilot_cli_status"
        self.description = "Get GitHub Copilot CLI installation status and information"
        self.category = "development"
        self.tags = ["copilot", "cli", "github", "ai", "status"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "github_cli_path": {
                    "type": "string",
                    "description": "Optional path to GitHub CLI executable",
                    "default": None
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get Copilot CLI status.
        
        Args:
            parameters: Tool parameters with optional github_cli_path
        
        Returns:
            Dictionary with status information
        """
        try:
            github_cli_path = parameters.get("github_cli_path")
            copilot = CopilotCLI(github_cli_path=github_cli_path)
            status = copilot.get_status()
            
            return {
                "success": True,
                "status": status
            }
        except Exception as e:
            logger.error(f"Failed to get Copilot CLI status: {e}")
            return {
                "success": False,
                "error": str(e)
            }

class CopilotCLIInstallTool(ClaudeMCPTool):
    """
    Tool for installing GitHub Copilot CLI extension.
    
    Installs the gh-copilot extension using GitHub CLI.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "copilot_cli_install"
        self.description = "Install or update GitHub Copilot CLI extension"
        self.category = "development"
        self.tags = ["copilot", "cli", "github", "ai", "install"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "github_cli_path": {
                    "type": "string",
                    "description": "Optional path to GitHub CLI executable",
                    "default": None
                },
                "force": {
                    "type": "boolean",
                    "description": "Force reinstall even if already installed",
                    "default": False
                }
            },
            "required": []
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Install Copilot CLI.
        
        Args:
            parameters: Tool parameters with optional github_cli_path and force
        
        Returns:
            Dictionary with installation result
        """
        try:
            github_cli_path = parameters.get("github_cli_path")
            force = parameters.get("force", False)
            
            copilot = CopilotCLI(github_cli_path=github_cli_path)
            result = copilot.install(force=force)
            
            return result
        except Exception as e:
            logger.error(f"Failed to install Copilot CLI: {e}")
            return {
                "success": False,
                "error": str(e)
            }

class CopilotCLIExplainTool(ClaudeMCPTool):
    """
    Tool for getting AI explanations of code using GitHub Copilot CLI.
    
    Uses GitHub Copilot to explain what code does.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "copilot_cli_explain"
        self.description = "Get AI explanation for code snippet using GitHub Copilot CLI"
        self.category = "development"
        self.tags = ["copilot", "cli", "github", "ai", "explain", "code"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Code snippet to explain"
                },
                "language": {
                    "type": "string",
                    "description": "Programming language (optional, auto-detected if not provided)",
                    "default": None
                },
                "github_cli_path": {
                    "type": "string",
                    "description": "Optional path to GitHub CLI executable",
                    "default": None
                }
            },
            "required": ["code"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Explain code using Copilot CLI.
        
        Args:
            parameters: Tool parameters with code, optional language and github_cli_path
        
        Returns:
            Dictionary with explanation
        """
        try:
            code = parameters.get("code")
            language = parameters.get("language")
            github_cli_path = parameters.get("github_cli_path")
            
            if not code:
                return {
                    "success": False,
                    "error": "Code parameter is required"
                }
            
            copilot = CopilotCLI(github_cli_path=github_cli_path)
            result = copilot.explain_code(code, language=language)
            
            return result
        except Exception as e:
            logger.error(f"Failed to explain code with Copilot CLI: {e}")
            return {
                "success": False,
                "error": str(e)
            }

class CopilotCLISuggestCommandTool(ClaudeMCPTool):
    """
    Tool for getting shell command suggestions from natural language.
    
    Uses GitHub Copilot to suggest commands based on what you want to do.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "copilot_cli_suggest_command"
        self.description = "Get shell command suggestions from natural language description using GitHub Copilot CLI"
        self.category = "development"
        self.tags = ["copilot", "cli", "github", "ai", "suggest", "command", "shell"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Natural language description of what you want to do"
                },
                "shell": {
                    "type": "string",
                    "description": "Shell type (bash, powershell, etc.). Auto-detected if not provided.",
                    "default": None
                },
                "github_cli_path": {
                    "type": "string",
                    "description": "Optional path to GitHub CLI executable",
                    "default": None
                }
            },
            "required": ["description"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get command suggestions using Copilot CLI.
        
        Args:
            parameters: Tool parameters with description, optional shell and github_cli_path
        
        Returns:
            Dictionary with command suggestions
        """
        try:
            description = parameters.get("description")
            shell = parameters.get("shell")
            github_cli_path = parameters.get("github_cli_path")
            
            if not description:
                return {
                    "success": False,
                    "error": "Description parameter is required"
                }
            
            copilot = CopilotCLI(github_cli_path=github_cli_path)
            result = copilot.suggest_command(description, shell=shell)
            
            return result
        except Exception as e:
            logger.error(f"Failed to suggest command with Copilot CLI: {e}")
            return {
                "success": False,
                "error": str(e)
            }

class CopilotCLISuggestGitTool(ClaudeMCPTool):
    """
    Tool for getting Git command suggestions from natural language.
    
    Specialized version for Git operations using GitHub Copilot.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "copilot_cli_suggest_git"
        self.description = "Get Git command suggestions from natural language description using GitHub Copilot CLI"
        self.category = "development"
        self.tags = ["copilot", "cli", "github", "ai", "suggest", "git"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "What you want to do with Git"
                },
                "github_cli_path": {
                    "type": "string",
                    "description": "Optional path to GitHub CLI executable",
                    "default": None
                }
            },
            "required": ["description"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get Git command suggestions using Copilot CLI.
        
        Args:
            parameters: Tool parameters with description and optional github_cli_path
        
        Returns:
            Dictionary with Git command suggestions
        """
        try:
            description = parameters.get("description")
            github_cli_path = parameters.get("github_cli_path")
            
            if not description:
                return {
                    "success": False,
                    "error": "Description parameter is required"
                }
            
            copilot = CopilotCLI(github_cli_path=github_cli_path)
            result = copilot.suggest_git_command(description)
            
            return result
        except Exception as e:
            logger.error(f"Failed to suggest Git command with Copilot CLI: {e}")
            return {
                "success": False,
                "error": str(e)
            }

# Export all tools
__all__ = [
    'CopilotCLIStatusTool',
    'CopilotCLIInstallTool',
    'CopilotCLIExplainTool',
    'CopilotCLISuggestCommandTool',
    'CopilotCLISuggestGitTool'
]
