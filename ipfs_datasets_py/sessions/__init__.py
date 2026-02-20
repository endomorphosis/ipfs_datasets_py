"""
Session management package for ipfs_datasets_py.

Provides session lifecycle management, validation, and the MockSessionManager
used in development/testing.

Reusable by:
- MCP server tools (mcp_server/tools/session_tools/)
- CLI commands
- Direct Python imports
"""
from .session_engine import (
    validate_session_id,
    validate_user_id,
    validate_session_type,
    MockSessionManager,
)

__all__ = [
    "validate_session_id",
    "validate_user_id",
    "validate_session_type",
    "MockSessionManager",
]
