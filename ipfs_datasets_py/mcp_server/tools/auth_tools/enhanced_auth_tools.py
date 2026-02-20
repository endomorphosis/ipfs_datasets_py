# ipfs_datasets_py/mcp_server/tools/auth_tools/enhanced_auth_tools.py
"""
Enhanced authentication tools (thin MCP wrapper).

Business logic (MockAuthService) lives in
ipfs_datasets_py.processors.auth.auth_engine.

MCP tool classes below delegate to MockAuthService.
"""

import logging
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from ..tool_wrapper import EnhancedBaseMCPTool
from ..validators import EnhancedParameterValidator
from ...monitoring import EnhancedMetricsCollector

# Import engine from core package (re-export for backward compat)
from ipfs_datasets_py.processors.auth.auth_engine import (  # noqa: F401
    MockAuthService,
)

logger = logging.getLogger(__name__)

class EnhancedAuthenticationTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for user authentication and JWT token management.
    """
    
    def __init__(self, auth_service=None):
        super().__init__(
            name="authenticate_user",
            description="Authenticate user credentials and return JWT access token with session management",
            category="authentication"
        )
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "Username for authentication",
                    "minLength": 1,
                    "maxLength": 50,
                    "pattern": "^[a-zA-Z0-9._-]+$"
                },
                "password": {
                    "type": "string",
                    "description": "Password for authentication",
                    "minLength": 1
                },
                "remember_me": {
                    "type": "boolean",
                    "description": "Extended session duration",
                    "default": False
                }
            },
            "required": ["username", "password"]
        }
        
        self.auth_service = auth_service or MockAuthService()
        self.tags = ["auth", "login", "jwt", "security", "session"]

    async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute user authentication."""
        try:
            # Validate input parameters
            username = self.validator.validate_text_input(
                parameters.get("username", ""),
                max_length=50
            )
            password = parameters.get("password", "")
            remember_me = parameters.get("remember_me", False)
            
            if not password:
                return {
                    "success": False,
                    "error": "Password is required",
                    "code": "MISSING_PASSWORD"
                }
            
            # Track authentication attempt
            self.metrics.record_request("authentication_attempt", {"username": username})
            
            # Authenticate user
            result = await self.auth_service.authenticate(username, password)
            
            if result.get("success"):
                self.metrics.record_request("authentication_success", {"username": username})
                self.logger.info(f"User {username} authenticated successfully")
                
                # Extend session if remember_me is True
                if remember_me and "expires_in" in result:
                    result["expires_in"] = 86400 * 7  # 7 days
                
                return {
                    "status": "success",
                    "authentication": result,
                    "message": "Authentication completed successfully"
                }
            else:
                self.metrics.record_request("authentication_failure", {"username": username})
                self.logger.warning(f"Authentication failed for user {username}: {result.get('error')}")
                
                return {
                    "status": "error",
                    "error": result.get("error", "Authentication failed"),
                    "code": "AUTHENTICATION_FAILED",
                    "attempts_remaining": result.get("attempts_remaining"),
                    "retry_after": result.get("retry_after")
                }
                
        except Exception as e:
            self.logger.error(f"Authentication error: {e}")
            self.metrics.record_error("authentication_error", str(e))
            return {
                "status": "error",
                "error": "Authentication service error",
                "code": "SERVICE_ERROR",
                "message": str(e)
            }


class EnhancedUserInfoTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for retrieving current user information from JWT token.
    """
    
    def __init__(self, auth_service=None):
        super().__init__(
            name="get_user_info",
            description="Get current authenticated user information and profile from JWT token",
            category="authentication"
        )
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "JWT access token",
                    "minLength": 1
                },
                "include_permissions": {
                    "type": "boolean",
                    "description": "Include user permissions in response",
                    "default": True
                },
                "include_profile": {
                    "type": "boolean",
                    "description": "Include user profile information",
                    "default": True
                }
            },
            "required": ["token"]
        }
        
        self.auth_service = auth_service or MockAuthService()
        self.tags = ["auth", "user", "jwt", "profile", "info"]

    async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute user info retrieval."""
        try:
            token = parameters.get("token", "")
            include_permissions = parameters.get("include_permissions", True)
            include_profile = parameters.get("include_profile", True)
            
            if not token:
                return {
                    "status": "error",
                    "error": "Token is required",
                    "code": "MISSING_TOKEN"
                }
            
            # Track user info request
            self.metrics.record_request("user_info_request")
            
            # Get user info from token
            user_info = await self.auth_service.get_user_from_token(token)
            
            if "error" in user_info:
                return {
                    "status": "error",
                    "error": user_info["error"],
                    "code": "TOKEN_ERROR"
                }
            
            # Filter response based on parameters
            response_data = {
                "username": user_info["username"],
                "role": user_info["role"]
            }
            
            if include_permissions:
                response_data["permissions"] = user_info.get("permissions", [])
            
            if include_profile:
                response_data["profile"] = user_info.get("profile", {})
            
            if "session_info" in user_info:
                response_data["session_info"] = user_info["session_info"]
            
            self.metrics.record_request("user_info_success")
            
            return {
                "status": "success",
                "user_info": response_data,
                "message": "User information retrieved successfully"
            }
            
        except Exception as e:
            self.logger.error(f"User info retrieval error: {e}")
            self.metrics.record_error("user_info_error", str(e))
            return {
                "status": "error",
                "error": "User info service error",
                "code": "SERVICE_ERROR",
                "message": str(e)
            }


class EnhancedTokenValidationTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for validating JWT tokens and checking permissions.
    """
    
    def __init__(self, auth_service=None):
        super().__init__(
            name="validate_token",
            description="Validate JWT token, check permissions, and manage token lifecycle",
            category="authentication"
        )
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "token": {
                    "type": "string",
                    "description": "JWT access token to validate",
                    "minLength": 1
                },
                "required_permission": {
                    "type": "string",
                    "description": "Required permission to check (optional)",
                    "enum": ["read", "write", "delete", "manage"]
                },
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["validate", "refresh", "decode"],
                    "default": "validate"
                },
                "strict": {
                    "type": "boolean",
                    "description": "Strict validation mode",
                    "default": False
                }
            },
            "required": ["token"]
        }
        
        self.auth_service = auth_service or MockAuthService()
        self.token_service = self.auth_service  # Alias for compatibility
        self.tags = ["auth", "jwt", "validation", "permissions", "security"]

    async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute token validation."""
        try:
            token = parameters.get("token", "")
            required_permission = parameters.get("required_permission")
            action = parameters.get("action", "validate")
            strict = parameters.get("strict", False)
            
            if not token:
                return {
                    "status": "error",
                    "error": "Token is required",
                    "code": "MISSING_TOKEN"
                }
            
            # Track validation request
            self.metrics.record_request("token_validation", {"action": action})
            
            if action == "refresh":
                result = await self.auth_service.refresh_token(token)
                if "error" in result:
                    return {
                        "status": "error",
                        "error": result["error"],
                        "code": "REFRESH_FAILED"
                    }
                
                self.metrics.record_request("token_refresh_success")
                return {
                    "status": "success",
                    "refresh_result": result,
                    "message": "Token refreshed successfully"
                }
                
            elif action == "decode":
                result = await self.auth_service.decode_token(token)
                if "error" in result:
                    return {
                        "status": "error",
                        "error": result["error"],
                        "code": "DECODE_FAILED"
                    }
                
                self.metrics.record_request("token_decode_success")
                return {
                    "status": "success",
                    "decoded_token": result,
                    "message": "Token decoded successfully"
                }
                
            else:  # validate
                validation_result = await self.auth_service.validate_token(token, required_permission)
                
                if not validation_result["valid"]:
                    self.metrics.record_request("token_validation_failed")
                    return {
                        "status": "error",
                        "valid": False,
                        "error": validation_result.get("error", "Token validation failed"),
                        "code": validation_result.get("code", "VALIDATION_FAILED")
                    }
                
                # Successful validation
                self.metrics.record_request("token_validation_success")
                
                response = {
                    "status": "success",
                    "valid": True,
                    "validation_result": validation_result,
                    "message": "Token validated successfully"
                }
                
                # Add security warnings in strict mode
                if strict:
                    warnings = []
                    time_remaining = validation_result.get("time_remaining", 0)
                    
                    if time_remaining < 3600:  # Less than 1 hour
                        warnings.append("Token expires within 1 hour")
                    
                    if required_permission and not validation_result.get("has_required_permission"):
                        warnings.append(f"Insufficient permissions for {required_permission}")
                    
                    if warnings:
                        response["warnings"] = warnings
                
                return response
                
        except Exception as e:
            self.logger.error(f"Token validation error: {e}")
            self.metrics.record_error("token_validation_error", str(e))
            return {
                "status": "error",
                "valid": False,
                "error": "Token validation service error",
                "code": "SERVICE_ERROR",
                "message": str(e)
            }
