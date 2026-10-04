#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anthropic Claude CLI MCP Tools — thin re-export wrapper.

All business logic lives in claude_cli_server_tools.py.
This file exposes the same public names for backward compatibility.
"""

from .claude_cli_server_tools import (  # noqa: F401
    claude_cli_status,
    claude_cli_install,
    claude_cli_execute,
    claude_cli_config_set_api_key,
    claude_cli_test_connection,
    claude_cli_list_models,
    claude_analyze_code_quality,
    claude_generate_documentation,
    claude_explain_code,
    claude_review_pull_request,
    claude_generate_tests,
    claude_refactor_suggestions,
)

# Backward-compatible alias for the old `claude_cli_config` name
claude_cli_config = claude_cli_config_set_api_key

__all__ = [
    "claude_cli_status",
    "claude_cli_install",
    "claude_cli_execute",
    "claude_cli_config_set_api_key",
    "claude_cli_config",
    "claude_cli_test_connection",
    "claude_cli_list_models",
    "claude_analyze_code_quality",
    "claude_generate_documentation",
    "claude_explain_code",
    "claude_review_pull_request",
    "claude_generate_tests",
    "claude_refactor_suggestions",
]
