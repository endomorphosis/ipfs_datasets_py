"""
Authentication tools for MCP server.

This module provides tools for user authentication, token validation,
and session management operations.
"""

import anyio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union

logger = logging.getLogger(__name__)

# Mock authentication service for testing
class MockAuthService:
    """Mock authentication service for testing purposes."""
    
    def __init__(self):
        self.users = {
            "admin": {"password": "admin123", "role": "admin", "permissions": ["read", "write", "delete", "manage"]},
            "user": {"password": "user123", "role": "user", "permissions": ["read", "write"]},
            "guest": {"password": "guest123", "role": "guest", "permissions": ["read"]}
        }
        self.tokens = {}
    
    async def authenticate(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate user credentials."""
        user = self.users.get(username)
        if user and user["password"] == password:
            token = f"mock_token_{username}_{int(datetime.now().timestamp())}"
            self.tokens[token] = {
                "username": username,
                "role": user["role"],
                "permissions": user["permissions"],
                "expires_at": datetime.now() + timedelta(hours=1)
            }
            return {
                "success": True,
                "username": username,
                "access_token": token,
                "token_type": "bearer",
                "role": user["role"],
                "expires_in": 3600
            }
        return {"success": False, "error": "Invalid credentials"}
    
    async def validate_token(self, token: str, required_permission: Optional[str] = None) -> Dict[str, Any]:
        """Validate JWT token and check permissions."""
        token_data = self.tokens.get(token)
        if not token_data:
            return {"valid": False, "error": "Invalid token"}
        
        if datetime.now() > token_data["expires_at"]:
            return {"valid": False, "error": "Token expired"}
        
        result = {
            "valid": True,
            "username": token_data["username"],
            "role": token_data["role"],
            "permissions": token_data["permissions"],
            "expires_at": token_data["expires_at"]
        }
        
        if required_permission:
            result["has_required_permission"] = required_permission in token_data["permissions"]
        
        return result
    
    async def get_user_from_token(self, token: str) -> Dict[str, Any]:
        """Get user information from token."""
        token_data = self.tokens.get(token)
        if not token_data:
            raise ValueError("Invalid token")
        
        return {
            "username": token_data["username"],
            "role": token_data["role"],
            "permissions": token_data["permissions"]
        }

# Global mock auth service instance
_mock_auth_service = MockAuthService()

async def authenticate_user(username: str, password: str, auth_service=None) -> Dict[str, Any]:
    """
    Authenticate user credentials and return access token.
    
    Args:
        username: Username for authentication
        password: Password for authentication
        auth_service: Optional authentication service
        
    Returns:
        Dictionary containing authentication result with token
    """
    try:
        # Input validation
        if not username or not isinstance(username, str):
            return {
                "status": "error",
                "message": "Username is required and must be a string"
            }
        
        if not password or not isinstance(password, str):
            return {
                "status": "error", 
                "message": "Password is required and must be a string"
            }
        
        if len(username) > 50:
            return {
                "status": "error",
                "message": "Username must be 50 characters or less"
            }
        
        # Use provided auth service or default mock
        service = auth_service or _mock_auth_service
        result = await service.authenticate(username, password)
        
        if result.get("success"):
            return {
                "status": "success",
                "username": result["username"],
                "access_token": result["access_token"],
                "token_type": result["token_type"],
                "role": result["role"],
                "expires_in": result["expires_in"],
                "message": "Authentication successful"
            }
        else:
            return {
                "status": "error",
                "message": result.get("error", "Authentication failed")
            }
            
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return {
            "status": "error",
            "message": f"Authentication failed: {str(e)}"
        }

async def validate_token(token: str, required_permission: Optional[str] = None, 
                        action: str = "validate", auth_service=None) -> Dict[str, Any]:
    """
    Validate JWT token and check user permissions.
    
    Args:
        token: JWT access token to validate
        required_permission: Optional permission to check (read, write, delete, manage)
        action: Action to perform (validate, refresh, decode)
        auth_service: Optional authentication service
        
    Returns:
        Dictionary containing token validation result
    """
    try:
        # Input validation
        if not token or not isinstance(token, str):
            return {
                "status": "error",
                "valid": False,
                "message": "Token is required and must be a string"
            }
        
        if required_permission and required_permission not in ["read", "write", "delete", "manage"]:
            return {
                "status": "error",
                "valid": False,
                "message": "Invalid required_permission. Must be one of: read, write, delete, manage"
            }
        
        if action not in ["validate", "refresh", "decode"]:
            return {
                "status": "error",
                "valid": False,
                "message": "Invalid action. Must be one of: validate, refresh, decode"
            }
        
        # Use provided auth service or default mock
        service = auth_service or _mock_auth_service
        
        if action == "refresh":
            # Mock refresh token functionality
            return {
                "status": "success",
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token",
                "expires_in": 3600,
                "message": "Token refreshed successfully"
            }
        elif action == "decode":
            # Mock decode token functionality
            return {
                "status": "success",
                "user_id": "user123",
                "username": "testuser",
                "exp": (datetime.now() + timedelta(hours=1)).timestamp(),
                "message": "Token decoded successfully"
            }
        else:  # validate
            result = await service.validate_token(token, required_permission)
            
            response = {
                "status": "success" if result.get("valid") else "error",
                "valid": result.get("valid", False)
            }
            
            if result.get("valid"):
                response.update({
                    "username": result.get("username"),
                    "role": result.get("role"),
                    "permissions": result.get("permissions"),
                    "expires_at": result.get("expires_at"),
                    "message": "Token is valid"
                })
                
                if required_permission:
                    response["has_required_permission"] = result.get("has_required_permission", False)
            else:
                response["message"] = result.get("error", "Token validation failed")
            
            return response
            
    except Exception as e:
        logger.error(f"Token validation error: {e}")
        return {
            "status": "error",
            "valid": False,
            "message": f"Token validation failed: {str(e)}"
        }

async def get_user_info(token: str, auth_service=None) -> Dict[str, Any]:
    """
    Get current authenticated user information from JWT token.
    
    Args:
        token: JWT access token
        auth_service: Optional authentication service
        
    Returns:
        Dictionary containing user information
    """
    try:
        # Input validation
        if not token or not isinstance(token, str):
            return {
                "status": "error",
                "message": "Token is required and must be a string"
            }
        
        # Use provided auth service or default mock
        service = auth_service or _mock_auth_service
        user_info = await service.get_user_from_token(token)
        
        return {
            "status": "success",
            "username": user_info["username"],
            "role": user_info["role"],
            "permissions": user_info["permissions"],
            "message": "User information retrieved successfully"
        }
        
    except Exception as e:
        logger.error(f"Get user info error: {e}")
        return {
            "status": "error",
            "message": f"Failed to get user info: {str(e)}"
        }
