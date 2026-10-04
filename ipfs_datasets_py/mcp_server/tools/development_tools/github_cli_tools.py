#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub CLI MCP Tools — thin re-export wrapper.

All business logic lives in github_cli_server_tools.py.
This file exposes the same public names for backward compatibility.
"""

from .github_cli_server_tools import (  # noqa: F401
    github_cli_status,
    github_cli_install,
    github_cli_execute,
    github_cli_auth_login,
    github_cli_auth_status,
    github_cli_repo_list,
    github_get_repo_info,
    github_get_repo_issues,
    github_get_pull_requests,
    github_search_repos,
    github_get_user_info,
    github_create_issue,
    github_create_pull_request,
    github_update_pull_request,
)

__all__ = [
    "github_cli_status",
    "github_cli_install",
    "github_cli_execute",
    "github_cli_auth_login",
    "github_cli_auth_status",
    "github_cli_repo_list",
    "github_get_repo_info",
    "github_get_repo_issues",
    "github_get_pull_requests",
    "github_search_repos",
    "github_get_user_info",
    "github_create_issue",
    "github_create_pull_request",
    "github_update_pull_request",
]
