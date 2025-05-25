# ipfs_datasets_py/mcp_server/tools/audit_tools/__init__.py
"""
Audit tools for the MCP server.

These tools allow AI assistants to work with audit logging through the MCP protocol.
"""

from .generate_audit_report import generate_audit_report
from .record_audit_event import record_audit_event

__all__ = [
    "generate_audit_report",
    "record_audit_event"
]
