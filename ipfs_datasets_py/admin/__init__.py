"""
System administration package for ipfs_datasets_py.

Provides service management, system info, and admin operations.

Reusable by:
- MCP server tools (mcp_server/tools/admin_tools/)
- CLI commands
- Direct Python imports
"""
from .admin_engine import (
    ServiceStatus,
    MaintenanceMode,
    SystemInfo,
    MockAdminService,
)

__all__ = [
    "ServiceStatus",
    "MaintenanceMode",
    "SystemInfo",
    "MockAdminService",
]
