# ipfs_datasets_py/mcp_server/tools/security_tools/check_access_permission.py
"""
MCP tool for checking access permissions.

This tool handles checking if a user has permission to access a resource.
"""
import anyio
import json
from typing import Dict, Any, Optional, Union, List

import logging

logger = logging.getLogger(__name__)

try:
    from ipfs_datasets_py import ipfs_datasets as ipfs_datasets  # type: ignore
except (ImportError, ModuleNotFoundError):
    ipfs_datasets = None  # type: ignore

from ipfs_datasets_py.mcp_server.tools.mcp_helpers import (
    mcp_error_response,
    mcp_text_response,
    parse_json_object,
)


async def check_access_permission(
    resource_id: str,
    user_id: Optional[str] = None,
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
    # MCP JSON-string entrypoint (used by unit tests)
    if isinstance(resource_id, str) and user_id is None and (
        not resource_id.strip()
        or resource_id.lstrip().startswith("{")
        or resource_id.lstrip().startswith("[")
        or any(ch.isspace() for ch in resource_id)
    ):
        data, error = parse_json_object(resource_id)
        if error is not None:
            return error

        for field in ("resource_id", "user_id"):
            if not data.get(field):
                return mcp_error_response(f"Missing required field: {field}", error_type="validation")

        if ipfs_datasets is None:
            return mcp_error_response("ipfs_datasets backend is not available")

        try:
            result = ipfs_datasets.check_access_permission(
                resource_id=data["resource_id"],
                user_id=data["user_id"],
                permission_type=data.get("permission_type", "read"),
                resource_type=data.get("resource_type"),
            )
            payload: Dict[str, Any] = {"status": "success"}
            if isinstance(result, dict):
                payload.update(result)
            else:
                payload["result"] = result
            return mcp_text_response(payload)
        except Exception as e:
            return mcp_text_response({"status": "error", "error": str(e)})

    try:
        if user_id is None:
            raise ValueError("user_id must be provided")

        logger.info(f"Checking {permission_type} permission for user {user_id} on resource {resource_id}")

        # Import the security manager
        from ipfs_datasets_py.security import SecurityManager

        # Create a security manager instance
        security_manager = SecurityManager()

        # Check permission
        has_permission = security_manager.check_access(
            resource_id=resource_id,
            access_type=permission_type
        )

        # Return permission information
        return {
            "status": "success",
            "allowed": has_permission,
            "user_id": user_id,
            "resource_id": resource_id,
            "permission_type": permission_type,
            "resource_type": resource_type
        }
    except Exception as e:
        logger.error(f"Error checking access permission: {e}")
        return {
            "status": "error",
            "error": str(e),
            "user_id": user_id,
            "resource_id": resource_id,
            "permission_type": permission_type
        }
