# ipfs_datasets_py/mcp_server/tools/audit_tools/record_audit_event.py
"""
MCP tool for recording audit events.

This tool handles recording audit events for security, compliance, and operations tracking.
"""
import asyncio
from typing import Dict, Any, Optional, Union, List

from ipfs_datasets_py.mcp_server.logger import logger


async def record_audit_event(
    action: str,
    resource_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    source_ip: Optional[str] = None,
    severity: str = "info",
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Record an audit event for security, compliance, and operations tracking.

    Args:
        action: The action being audited (e.g., 'dataset.access', 'user.login')
        resource_id: Optional ID of the resource being acted upon
        resource_type: Optional type of the resource being acted upon
        user_id: Optional ID of the user performing the action
        details: Optional additional details about the event
        source_ip: Optional source IP address
        severity: Severity level ('info', 'warning', 'error', 'critical')
        tags: Optional tags for categorizing the event

    Returns:
        Dict containing information about the recorded audit event
    """
    try:
        logger.info(f"Recording audit event: {action}")
        
        # Import the audit logger
        from ipfs_datasets_py.audit import AuditLogger
        
        # Create an audit logger instance
        audit_logger = AuditLogger()
        
        # Prepare the event
        event = {
            "action": action,
            "severity": severity
        }
        
        if resource_id:
            event["resource_id"] = resource_id
        
        if resource_type:
            event["resource_type"] = resource_type
            
        if user_id:
            event["user_id"] = user_id
            
        if details:
            event["details"] = details
            
        if source_ip:
            event["source_ip"] = source_ip
            
        if tags:
            event["tags"] = tags
        
        # Record the audit event
        event_id = audit_logger.log_event(**event)
        
        # Return information about the recorded event
        return {
            "status": "success",
            "event_id": event_id,
            "action": action,
            "timestamp": audit_logger.last_event_timestamp,
            "severity": severity,
            "resource_id": resource_id,
            "resource_type": resource_type
        }
    except Exception as e:
        logger.error(f"Error recording audit event: {e}")
        return {
            "status": "error",
            "message": str(e),
            "action": action
        }
