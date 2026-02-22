# ipfs_datasets_py/mcp_server/tools/auth_tools/enhanced_auth_tools.py
"""
Enhanced auth tools — standalone async MCP functions.

Business logic (MockAuthService) lives in
ipfs_datasets_py.processors.auth.auth_engine.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

# Import engine from core package (re-export for backward compat)
from ipfs_datasets_py.processors.auth.auth_engine import MockAuthService  # noqa: F401

logger = logging.getLogger(__name__)

_DEFAULT_AUTH_SERVICE = MockAuthService()


async def authenticate_user(
    username: str,
    password: str,
    remember_me: bool = False,
) -> Dict[str, Any]:
    """Authenticate a user with username and password, return JWT tokens."""
    if not password:
        return {"status": "error", "error": "Password is required", "code": "MISSING_PASSWORD"}
    result = await _DEFAULT_AUTH_SERVICE.authenticate(username, password)
    if result.get("success"):
        if remember_me and "expires_in" in result:
            result["expires_in"] = 86400 * 7
        return {"status": "success", "authentication": result, "message": "Authentication completed successfully"}
    return {
        "status": "error",
        "error": result.get("error", "Authentication failed"),
        "code": "AUTHENTICATION_FAILED",
        "attempts_remaining": result.get("attempts_remaining"),
        "retry_after": result.get("retry_after"),
    }


async def get_user_info(
    token: str,
    include_permissions: bool = True,
    include_profile: bool = True,
) -> Dict[str, Any]:
    """Get current authenticated user information from JWT token."""
    if not token:
        return {"status": "error", "error": "Token is required", "code": "MISSING_TOKEN"}
    user_info = await _DEFAULT_AUTH_SERVICE.get_user_from_token(token)
    if "error" in user_info:
        return {"status": "error", "error": user_info["error"], "code": "TOKEN_ERROR"}
    response_data: Dict[str, Any] = {"username": user_info["username"], "role": user_info["role"]}
    if include_permissions:
        response_data["permissions"] = user_info.get("permissions", [])
    if include_profile:
        response_data["profile"] = user_info.get("profile", {})
    if "session_info" in user_info:
        response_data["session_info"] = user_info["session_info"]
    return {"status": "success", "user_info": response_data, "message": "User information retrieved successfully"}


async def validate_token(
    token: str,
    action: str = "validate",
    required_permission: Optional[str] = None,
    strict: bool = False,
) -> Dict[str, Any]:
    """Validate, refresh, or decode a JWT token."""
    if not token:
        return {"status": "error", "valid": False, "error": "Token is required", "code": "MISSING_TOKEN"}
    if action == "refresh":
        result = await _DEFAULT_AUTH_SERVICE.refresh_token(token)
        if "error" in result:
            return {"status": "error", "error": result["error"], "code": "REFRESH_FAILED"}
        return {"status": "success", "refresh_result": result, "message": "Token refreshed successfully"}
    if action == "decode":
        result = await _DEFAULT_AUTH_SERVICE.decode_token(token)
        if "error" in result:
            return {"status": "error", "error": result["error"], "code": "DECODE_FAILED"}
        return {"status": "success", "decoded_token": result, "message": "Token decoded successfully"}
    # validate
    validation_result = await _DEFAULT_AUTH_SERVICE.validate_token(token, required_permission)
    if not validation_result["valid"]:
        return {"status": "error", "valid": False, "error": validation_result.get("error", "Token validation failed"), "code": validation_result.get("code", "VALIDATION_FAILED")}
    response: Dict[str, Any] = {"status": "success", "valid": True, "validation_result": validation_result, "message": "Token validated successfully"}
    if strict:
        warnings = []
        if validation_result.get("time_remaining", 0) < 3600:
            warnings.append("Token expires within 1 hour")
        if required_permission and not validation_result.get("has_required_permission"):
            warnings.append(f"Insufficient permissions for {required_permission}")
        if warnings:
            response["warnings"] = warnings
    return response


# Backward-compatible class shims
class EnhancedAuthenticationTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await authenticate_user(parameters["username"], parameters["password"], parameters.get("remember_me", False))


class EnhancedUserInfoTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await get_user_info(parameters["token"], parameters.get("include_permissions", True), parameters.get("include_profile", True))


class EnhancedTokenValidationTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await validate_token(parameters["token"], parameters.get("action", "validate"), parameters.get("required_permission"), parameters.get("strict", False))


__all__ = [
    "authenticate_user",
    "get_user_info",
    "validate_token",
    "EnhancedAuthenticationTool",
    "EnhancedUserInfoTool",
    "EnhancedTokenValidationTool",
    "MockAuthService",
]
