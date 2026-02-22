"""
Dashboard processors package for ipfs_datasets_py.

Provides dashboard error reporting and event handling.

Reusable by:
- MCP server tools (mcp_server/tools/dashboard_tools/)
- CLI commands
- Direct Python imports
"""
from .js_error_reporter_engine import JavaScriptErrorReporter, get_js_error_reporter  # noqa: F401

__all__ = [
    "JavaScriptErrorReporter",
    "get_js_error_reporter",
]
