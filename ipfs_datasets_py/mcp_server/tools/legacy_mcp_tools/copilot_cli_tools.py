#!/usr/bin/env python3
# DEPRECATED: Use ipfs_datasets_py.mcp_server.tools.development_tools instead.
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.copilot_cli_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.development_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.mcp_server.tools.development_tools.copilot_cli_tools import (  # noqa: F401
    copilot_cli_status,
    copilot_cli_install,
    copilot_cli_explain,
    copilot_cli_suggest_command,
    copilot_cli_suggest_git,
)

__all__ = [
    "copilot_cli_status",
    "copilot_cli_install",
    "copilot_cli_explain",
    "copilot_cli_suggest_command",
    "copilot_cli_suggest_git",
]
