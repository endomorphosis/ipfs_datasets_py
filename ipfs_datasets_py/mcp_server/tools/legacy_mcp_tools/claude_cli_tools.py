#!/usr/bin/env python3
# DEPRECATED: Use ipfs_datasets_py.mcp_server.tools.development_tools instead.
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.claude_cli_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.development_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.mcp_server.tools.development_tools.claude_cli_server_tools import (  # noqa: F401
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

claude_cli_config = claude_cli_config_set_api_key

__all__ = [
    "claude_cli_status", "claude_cli_install", "claude_cli_execute",
    "claude_cli_config_set_api_key", "claude_cli_config",
    "claude_cli_test_connection", "claude_cli_list_models",
    "claude_analyze_code_quality", "claude_generate_documentation",
    "claude_explain_code", "claude_review_pull_request",
    "claude_generate_tests", "claude_refactor_suggestions",
]
