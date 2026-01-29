"""
Audit Tools MCP Wrapper

This module provides MCP tool interfaces for audit functionality.
The core implementation is in ipfs_datasets_py.audit

All business logic should reside in the core module, and this file serves
as a thin wrapper to expose that functionality through the MCP interface.
"""

from ipfs_datasets_py.audit import (
    AuditLogger,
    AuditEvent,
    AuditLevel,
    AuditCategory,
)

# Re-export for backward compatibility
__all__ = [
    'AuditLogger',
    'AuditEvent',
    'AuditLevel',
    'AuditCategory',
    'audit_tools',
]


# Main MCP function - thin wrapper around core audit functionality
async def audit_tools(
    target: str = ".",
    action: str = "audit",
    user: str = None,
    details: dict = None
) -> dict:
    """
    A tool for performing audit-related tasks.
    
    This is a thin wrapper that delegates to the core audit module.
    
    Args:
        target: The target to audit (e.g., a file path, a system component)
        action: The audit action to perform
        user: Optional user performing the action
        details: Optional additional details
        
    Returns:
        Dict containing audit results
    """
    try:
        # Get the audit logger instance from core module
        audit_logger = AuditLogger.get_instance()
        
        # Log the audit event using core functionality
        event_id = audit_logger.log(
            level=AuditLevel.INFO,
            category=AuditCategory.OPERATIONAL,
            action=action,
            user=user,
            resource_id=target,
            resource_type="system",
            details=details or {}
        )
        
        return {
            "status": "success",
            "event_id": event_id,
            "message": f"Audit performed on target '{target}'",
            "tool_type": "Audit tool",
            "target": target,
            "action": action
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Audit failed: {str(e)}",
            "tool_type": "Audit tool",
            "target": target
        }

