#!/usr/bin/env python3
# DEPRECATED: Use ipfs_datasets_py.mcp_server.tools.development_tools instead.
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.vscode_cli_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.development_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.mcp_server.tools.development_tools.vscode_cli_tools import (  # noqa: F401
    vscode_cli_status,
    vscode_cli_install,
    vscode_cli_execute,
    vscode_cli_list_extensions,
    vscode_cli_install_extension,
    vscode_cli_uninstall_extension,
    vscode_cli_tunnel_login,
    vscode_cli_tunnel_install_service,
)

__all__ = [
    "vscode_cli_status",
    "vscode_cli_install",
    "vscode_cli_execute",
    "vscode_cli_list_extensions",
    "vscode_cli_install_extension",
    "vscode_cli_uninstall_extension",
    "vscode_cli_tunnel_login",
    "vscode_cli_tunnel_install_service",
]
