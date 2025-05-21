# ipfs_datasets_py/mcp_server/tools/security_tools/check_access_permission.py
"""
MCP tool for checking access permissions.

This tool handles checking if a user has permission to access a resource.
"""
import asyncio
from typing import Dict, Any, Optional, Union, List

from ipfs_datasets_py.mcp_server.logger import logger


async def check_access_permission(
    resource_id: str,
    user_id: str,
    permission_type: str = "read",
    resource_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Check if a user has permission to access a resource.

    Args:
        resource_id: ID of the resource to check
        user_id: ID of the user to check permissions for
        permission_type: Type of permission to check ('read', 'write', 'delete', 'share', etc.)
        resource_type: Optional type of the resource

    Returns:
        Dict containing permission information
    """
    try:
        logger.info(f"Checking {permission_type} permission for user {user_id} on resource {resource_id}")
        
        # Import the security manager
        from ipfs_datasets_py.security import SecurityManager
        
        # Create a security manager instance
        security_manager = SecurityManager()
        
        # Check permission
        has_permission = security_manager.check_permission(
            user_id=user_id,
            resource_id=resource_id,
            permission=permission_type,
            resource_type=resource_type
        )
        
        # Get detailed permission info
        permission_info = security_manager.get_permission_details(
            user_id=user_id,
            resource_id=resource_id,
            resource_type=resource_type
        )
        
        # Return permission information
        return {
            "status": "success",
            "has_permission": has_permission,
            "user_id": user_id,
            "resource_id": resource_id,
            "permission_type": permission_type,
            "resource_type": resource_type,
            "permission_details": permission_info
        }
    except Exception as e:
        logger.error(f"Error checking access permission: {e}")
        return {
            "status": "error",
            "message": str(e),
            "user_id": user_id,
            "resource_id": resource_id,
            "permission_type": permission_type
        }
