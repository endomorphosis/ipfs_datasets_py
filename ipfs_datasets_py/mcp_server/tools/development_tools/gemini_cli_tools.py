#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Gemini CLI MCP Tools — thin re-export wrapper.

All business logic lives in gemini_cli_server_tools.py.
This file exposes the same public names for backward compatibility.
"""

from .gemini_cli_server_tools import (  # noqa: F401
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

# Backward-compatible alias for the old name
gemini_cli_config = gemini_cli_config_set_api_key

__all__ = [
    "gemini_cli_status",
    "gemini_cli_install",
    "gemini_cli_execute",
    "gemini_cli_config_set_api_key",
    "gemini_cli_config",
    "gemini_cli_test_connection",
    "gemini_cli_list_models",
    "gemini_generate_text",
    "gemini_summarize_text",
    "gemini_analyze_code",
    "gemini_extract_structured_data",
    "gemini_translate_text",
]
