#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Copilot Agent Task MCP Tools

This module provides MCP (Model Context Protocol) tool wrappers for GitHub Copilot
Agent Task functionality (gh agent-task commands), enabling AI assistants to create,
list, and manage GitHub Copilot Coding Agent tasks through standardized tool interfaces.

This uses the OFFICIAL method for invoking GitHub Copilot Coding Agent:
- gh agent-task create: Create new agent tasks
- gh agent-task list: List existing agent tasks
- gh agent-task view: View agent task details

Documentation:
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
- https://docs.github.com/en/copilot/concepts/agents/coding-agent/agent-management

Available tools:
- CopilotAgentTaskCreateTool: Create a new GitHub Copilot agent task
- CopilotAgentTaskListTool: List GitHub Copilot agent tasks
- CopilotAgentTaskViewTool: View details of a specific agent task
"""

import logging
from typing import Dict, Any, Optional
from ipfs_datasets_py.mcp_tools.tool_registry import ClaudeMCPTool
from ipfs_datasets_py.utils.copilot_cli import CopilotCLI

logger = logging.getLogger(__name__)


class CopilotAgentTaskCreateTool(ClaudeMCPTool):
    """
    Tool for creating GitHub Copilot agent tasks (official method).
    
    Uses gh agent-task create to invoke the GitHub Copilot Coding Agent,
    which is the official method documented by GitHub.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "copilot_agent_task_create"
        self.description = (
            "Create a GitHub Copilot agent task using gh agent-task create (official method). "
            "The agent will analyze the task, create a plan, and implement changes in a PR."
        )
        self.category = "development"
        self.tags = ["copilot", "agent", "github", "ai", "coding-agent", "automation"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Description of the task for the agent to work on"
                },
                "base_branch": {
                    "type": "string",
                    "description": "Base branch for the pull request (optional, uses default if not provided)",
                    "default": None
                },
                "follow": {
                    "type": "boolean",
                    "description": "Follow agent session logs after creation",
                    "default": False
                },
                "repo": {
                    "type": "string",
                    "description": "Repository in [HOST/]OWNER/REPO format (optional, uses current repo if not provided)",
                    "default": None
                },
                "github_cli_path": {
                    "type": "string",
                    "description": "Optional path to GitHub CLI executable",
                    "default": None
                }
            },
            "required": ["task_description"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a GitHub Copilot agent task.
        
        Args:
            parameters: Tool parameters with task_description and optional settings
        
        Returns:
            Dictionary with agent task creation result
        """
        try:
            task_description = parameters.get("task_description")
            if not task_description:
                return {
                    "success": False,
                    "error": "task_description parameter is required"
                }
            
            base_branch = parameters.get("base_branch")
            follow = parameters.get("follow", False)
            repo = parameters.get("repo")
            github_cli_path = parameters.get("github_cli_path")
            
            # Use CopilotCLI utility
            copilot = CopilotCLI(github_cli_path=github_cli_path)
            result = copilot.create_agent_task(
                task_description=task_description,
                base_branch=base_branch,
                follow=follow,
                repo=repo
            )
            
            return result
        except Exception as e:
            logger.error(f"Failed to create agent task: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class CopilotAgentTaskListTool(ClaudeMCPTool):
    """
    Tool for listing GitHub Copilot agent tasks.
    
    Lists recent agent tasks in the repository using gh agent-task list.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "copilot_agent_task_list"
        self.description = (
            "List GitHub Copilot agent tasks in a repository. "
            "Shows recent agent tasks and their status."
        )
        self.category = "development"
        self.tags = ["copilot", "agent", "github", "ai", "coding-agent", "list"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of tasks to list (default: 30)",
                    "default": 30,
                    "minimum": 1,
                    "maximum": 100
                },
                "repo": {
                    "type": "string",
                    "description": "Repository in [HOST/]OWNER/REPO format (optional, uses current repo if not provided)",
                    "default": None
                },
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
        List GitHub Copilot agent tasks.
        
        Args:
            parameters: Tool parameters with optional limit, repo, and github_cli_path
        
        Returns:
            Dictionary with list of agent tasks
        """
        try:
            limit = parameters.get("limit", 30)
            repo = parameters.get("repo")
            github_cli_path = parameters.get("github_cli_path")
            
            # Use CopilotCLI utility
            copilot = CopilotCLI(github_cli_path=github_cli_path)
            result = copilot.list_agent_tasks(limit=limit, repo=repo)
            
            return result
        except Exception as e:
            logger.error(f"Failed to list agent tasks: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class CopilotAgentTaskViewTool(ClaudeMCPTool):
    """
    Tool for viewing GitHub Copilot agent task details.
    
    Views details of a specific agent task using gh agent-task view.
    """
    
    def __init__(self):
        super().__init__()
        self.name = "copilot_agent_task_view"
        self.description = (
            "View details of a specific GitHub Copilot agent task. "
            "Shows task status, logs, and execution details."
        )
        self.category = "development"
        self.tags = ["copilot", "agent", "github", "ai", "coding-agent", "view"]
        self.input_schema = {
            "type": "object",
            "properties": {
                "task_identifier": {
                    "type": "string",
                    "description": "Task identifier (PR number, session ID, or URL)"
                },
                "repo": {
                    "type": "string",
                    "description": "Repository in [HOST/]OWNER/REPO format (optional, uses current repo if not provided)",
                    "default": None
                },
                "github_cli_path": {
                    "type": "string",
                    "description": "Optional path to GitHub CLI executable",
                    "default": None
                }
            },
            "required": ["task_identifier"]
        }
    
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        View GitHub Copilot agent task details.
        
        Args:
            parameters: Tool parameters with task_identifier and optional settings
        
        Returns:
            Dictionary with agent task details
        """
        try:
            task_identifier = parameters.get("task_identifier")
            if not task_identifier:
                return {
                    "success": False,
                    "error": "task_identifier parameter is required"
                }
            
            repo = parameters.get("repo")
            github_cli_path = parameters.get("github_cli_path")
            
            # Use CopilotCLI utility
            copilot = CopilotCLI(github_cli_path=github_cli_path)
            result = copilot.view_agent_task(task_identifier=task_identifier, repo=repo)
            
            return result
        except Exception as e:
            logger.error(f"Failed to view agent task: {e}")
            return {
                "success": False,
                "error": str(e)
            }


# Export all tools
__all__ = [
    'CopilotAgentTaskCreateTool',
    'CopilotAgentTaskListTool',
    'CopilotAgentTaskViewTool'
]
