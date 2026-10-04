#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Copilot MCP tools for the ``gh copilot`` extension.

These wrappers target the GitHub CLI extension surface, not the standalone
local ``copilot`` agent CLI.
"""

import logging
from typing import Any, Dict, Optional

from ipfs_datasets_py.utils.copilot_cli import CopilotCLI  # backward-compat shim → Copilot

logger = logging.getLogger(__name__)


def copilot_cli_status(github_cli_path: Optional[str] = None) -> Dict[str, Any]:
    """Get ``gh copilot`` extension status and installation details."""
    try:
        copilot = CopilotCLI(github_cli_path=github_cli_path)
        return {"success": True, **copilot.get_status()}
    except Exception as e:
        logger.error("Failed to get Copilot CLI status: %s", e)
        return {"success": False, "error": str(e)}


def copilot_cli_install(
    github_cli_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Install or update the ``gh-copilot`` extension."""
    try:
        copilot = CopilotCLI(github_cli_path=github_cli_path)
        return copilot.install()
    except Exception as e:
        logger.error("Failed to install Copilot CLI: %s", e)
        return {"success": False, "error": str(e)}


def copilot_cli_explain(
    code: str,
    github_cli_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Get AI explanation for a code snippet using ``gh copilot explain``."""
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
    """Get shell command suggestion from ``gh copilot suggest``."""
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
    """Get Git command suggestion using the ``gh copilot`` extension."""
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
