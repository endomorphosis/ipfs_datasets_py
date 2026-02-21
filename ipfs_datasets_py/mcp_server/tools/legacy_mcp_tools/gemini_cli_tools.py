#!/usr/bin/env python3
# DEPRECATED: Use ipfs_datasets_py.mcp_server.tools.development_tools instead.
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.gemini_cli_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.development_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.mcp_server.tools.development_tools.gemini_cli_server_tools import (  # noqa: F401
    gemini_cli_status,
    gemini_cli_install,
    gemini_cli_execute,
    gemini_cli_config_set_api_key,
    gemini_cli_test_connection,
    gemini_cli_list_models,
    gemini_generate_text,
    gemini_summarize_text,
    gemini_analyze_code,
    gemini_extract_structured_data,
    gemini_translate_text,
)

gemini_cli_config = gemini_cli_config_set_api_key

__all__ = [
    "gemini_cli_status", "gemini_cli_install", "gemini_cli_execute",
    "gemini_cli_config_set_api_key", "gemini_cli_config",
    "gemini_cli_test_connection", "gemini_cli_list_models",
    "gemini_generate_text", "gemini_summarize_text",
    "gemini_analyze_code", "gemini_extract_structured_data", "gemini_translate_text",
]
