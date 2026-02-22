"""
Auth Engine — core authentication business logic.

Domain models and the mock authentication service used by auth tools.
Extracted from mcp_server/tools/auth_tools/enhanced_auth_tools.py.

Reusable by:
- MCP server tools (mcp_server/tools/auth_tools/)
- CLI commands
- Direct Python imports: from ipfs_datasets_py.processors.auth.auth_engine import MockAuthService
"""

import logging
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class MockAuthService:
    """Enhanced mock authentication service for development and testing."""
    
    def __init__(self):
        self.users = {
            "admin": {
                "password": "admin123", 
                "role": "admin", 
                "permissions": ["read", "write", "delete", "manage"],
                "profile": {
                    "email": "admin@example.com",
                    "full_name": "System Administrator",
                    "department": "IT"
                }
            },
            "user": {
                "password": "user123", 
                "role": "user", 
                "permissions": ["read", "write"],
                "profile": {
                    "email": "user@example.com",
                    "full_name": "Regular User",
                    "department": "Research"
                }
            },
            "guest": {
                "password": "guest123", 
                "role": "guest", 
                "permissions": ["read"],
                "profile": {
                    "email": "guest@example.com",
                    "full_name": "Guest User",
                    "department": "External"
                }
            }
        }
        self.tokens = {}
        self.sessions = {}
        self.login_attempts = {}
    
    async def authenticate(self, username: str, password: str) -> Dict[str, Any]:
        """Authenticate user credentials with rate limiting."""
        # Check rate limiting
        attempt_key = f"login_{username}"
        current_time = datetime.now()
        
        if attempt_key in self.login_attempts:
            attempts = self.login_attempts[attempt_key]
            # Reset if more than 15 minutes passed
            if current_time - attempts['last_attempt'] > timedelta(minutes=15):
                attempts = {'count': 0, 'last_attempt': current_time}
            
            if attempts['count'] >= 5:
                return {
                    "success": False, 
                    "error": "Too many login attempts. Please try again later.",
                    "retry_after": 900  # 15 minutes
                }
        else:
            attempts = {'count': 0, 'last_attempt': current_time}
        
        user = self.users.get(username)
        if user and user["password"] == password:
            # Successful login - reset attempts
            self.login_attempts.pop(attempt_key, None)
            
            token = f"bearer_{username}_{str(uuid.uuid4())[:8]}_{int(current_time.timestamp())}"
            session_id = str(uuid.uuid4())
            
            expires_at = current_time + timedelta(hours=24)
            
            self.tokens[token] = {
                "username": username,
                "role": user["role"],
                "permissions": user["permissions"],
                "profile": user["profile"],
                "session_id": session_id,
                "issued_at": current_time,
                "expires_at": expires_at
            }
            
            self.sessions[session_id] = {
                "user": username,
                "token": token,
                "created_at": current_time,
                "last_activity": current_time,
                "active": True
            }
            
            return {
                "success": True,
                "username": username,
                "access_token": token,
                "token_type": "bearer",
                "role": user["role"],
                "permissions": user["permissions"],
                "session_id": session_id,
                "expires_in": 86400,  # 24 hours
                "issued_at": current_time.isoformat(),
                "expires_at": expires_at.isoformat()
            }
        else:
            # Failed login - increment attempts
            attempts['count'] += 1
            attempts['last_attempt'] = current_time
            self.login_attempts[attempt_key] = attempts
            
            return {
                "success": False, 
                "error": "Invalid credentials",
                "attempts_remaining": max(0, 5 - attempts['count'])
            }
    
    async def validate_token(self, token: str, required_permission: Optional[str] = None) -> Dict[str, Any]:
        """Validate JWT token and check permissions."""
        token_data = self.tokens.get(token)
        
        if not token_data:
            return {
                "valid": False,
                "error": "Invalid or expired token",
                "code": "INVALID_TOKEN"
            }
        
        current_time = datetime.now()
        
        # Check expiration
        if current_time > token_data["expires_at"]:
            # Clean up expired token
            self.tokens.pop(token, None)
            session_id = token_data.get("session_id")
            if session_id and session_id in self.sessions:
                self.sessions[session_id]["active"] = False
            
            return {
                "valid": False,
                "error": "Token has expired",
                "code": "TOKEN_EXPIRED",
                "expired_at": token_data["expires_at"].isoformat()
            }
        
        # Update session activity
        session_id = token_data.get("session_id")
        if session_id and session_id in self.sessions:
            self.sessions[session_id]["last_activity"] = current_time
        
        # Check permission if required
        has_permission = True
        if required_permission:
            has_permission = required_permission in token_data.get("permissions", [])
        
        return {
            "valid": True,
            "username": token_data["username"],
            "role": token_data["role"],
            "permissions": token_data["permissions"],
            "session_id": token_data.get("session_id"),
            "has_required_permission": has_permission,
            "expires_at": token_data["expires_at"],
            "time_remaining": int((token_data["expires_at"] - current_time).total_seconds())
        }
    
    async def get_user_from_token(self, token: str) -> Dict[str, Any]:
        """Get user information from token."""
        validation = await self.validate_token(token)
        
        if not validation["valid"]:
            return {"error": validation["error"]}
        
        token_data = self.tokens.get(token)
        if token_data:
            return {
                "username": token_data["username"],
                "role": token_data["role"],
                "permissions": token_data["permissions"],
                "profile": token_data.get("profile", {}),
                "session_info": {
                    "session_id": token_data.get("session_id"),
                    "issued_at": token_data["issued_at"].isoformat(),
                    "expires_at": token_data["expires_at"].isoformat()
                }
            }
        
        return {"error": "Token data not found"}
    
    async def refresh_token(self, token: str) -> Dict[str, Any]:
        """Refresh an access token."""
        validation = await self.validate_token(token)
        
        if not validation["valid"]:
            return {"error": validation["error"]}
        
        token_data = self.tokens.get(token)
        if not token_data:
            return {"error": "Token not found"}
        
        # Generate new token
        current_time = datetime.now()
        new_token = f"bearer_{token_data['username']}_{str(uuid.uuid4())[:8]}_{int(current_time.timestamp())}"
        new_expires_at = current_time + timedelta(hours=24)
        
        # Update token data
        new_token_data = token_data.copy()
        new_token_data.update({
            "issued_at": current_time,
            "expires_at": new_expires_at
        })
        
        # Store new token and remove old one
        self.tokens[new_token] = new_token_data
        self.tokens.pop(token, None)
        
        # Update session
        session_id = token_data.get("session_id")
        if session_id and session_id in self.sessions:
            self.sessions[session_id]["token"] = new_token
            self.sessions[session_id]["last_activity"] = current_time
        
        return {
            "access_token": new_token,
            "token_type": "bearer",
            "expires_in": 86400,
            "issued_at": current_time.isoformat(),
            "expires_at": new_expires_at.isoformat()
        }
    
    async def decode_token(self, token: str) -> Dict[str, Any]:
        """Decode token and return payload."""
        token_data = self.tokens.get(token)
        
        if not token_data:
            return {"error": "Token not found"}
        
        return {
            "user_id": token_data["username"],
            "username": token_data["username"],
            "role": token_data["role"],
            "permissions": token_data["permissions"],
            "iat": int(token_data["issued_at"].timestamp()),
            "exp": int(token_data["expires_at"].timestamp()),
            "session_id": token_data.get("session_id")
        }


