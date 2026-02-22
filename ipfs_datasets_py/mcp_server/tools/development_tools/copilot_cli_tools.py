#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Copilot CLI MCP Tools — standalone function wrappers.

Business logic delegates to ipfs_datasets_py.utils.cli_tools.Copilot.
"""

import logging
from typing import Any, Dict, Optional

from ipfs_datasets_py.utils.copilot_cli import CopilotCLI  # backward-compat shim → Copilot

logger = logging.getLogger(__name__)


def copilot_cli_status(github_cli_path: Optional[str] = None) -> Dict[str, Any]:
    """Get GitHub Copilot CLI installation status and information."""
    try:
        copilot = CopilotCLI(github_cli_path=github_cli_path)
        return {
            "success": True,
            "installed": copilot.is_installed(),
            "copilot_installed": getattr(copilot, "copilot_installed", False),
        }
    except Exception as e:
        logger.error("Failed to get Copilot CLI status: %s", e)
        return {"success": False, "error": str(e)}


def copilot_cli_install(
    github_cli_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Install or update GitHub Copilot CLI extension."""
    try:
        copilot = CopilotCLI(github_cli_path=github_cli_path)
        success = copilot.install()
        return {"success": success, "message": "Installed successfully" if success else "Installation failed"}
    except Exception as e:
        logger.error("Failed to install Copilot CLI: %s", e)
        return {"success": False, "error": str(e)}


def copilot_cli_explain(
    code: str,
    github_cli_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Get AI explanation for a code snippet using GitHub Copilot CLI."""
    if not code:
        return {"success": False, "error": "code parameter is required"}
    try:
        copilot = CopilotCLI(github_cli_path=github_cli_path)
        explanation = copilot.explain(code)
        return {"success": True, "explanation": explanation, "code": code}
    except Exception as e:
        logger.error("Failed to explain code with Copilot CLI: %s", e)
        return {"success": False, "error": str(e)}


def copilot_cli_suggest_command(
    description: str,
    github_cli_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Get shell command suggestion from a natural language description."""
    if not description:
        return {"success": False, "error": "description parameter is required"}
    try:
        copilot = CopilotCLI(github_cli_path=github_cli_path)
        suggestion = copilot.suggest(description)
        return {"success": True, "suggestion": suggestion, "description": description}
    except Exception as e:
        logger.error("Failed to suggest command with Copilot CLI: %s", e)
        return {"success": False, "error": str(e)}


def copilot_cli_suggest_git(
    description: str,
    github_cli_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Get Git command suggestion from a natural language description."""
    if not description:
        return {"success": False, "error": "description parameter is required"}
    try:
        copilot = CopilotCLI(github_cli_path=github_cli_path)
        suggestion = copilot.suggest(f"git: {description}")
        return {"success": True, "suggestion": suggestion, "description": description}
    except Exception as e:
        logger.error("Failed to suggest Git command with Copilot CLI: %s", e)
        return {"success": False, "error": str(e)}


__all__ = [
    "copilot_cli_status",
    "copilot_cli_install",
    "copilot_cli_explain",
    "copilot_cli_suggest_command",
    "copilot_cli_suggest_git",
]
