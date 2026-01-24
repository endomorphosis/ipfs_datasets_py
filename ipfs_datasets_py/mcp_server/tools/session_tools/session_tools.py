"""
Session management tools for MCP server.

This module provides tools for creating, managing, and cleaning up
user sessions and their associated resources.
"""

import anyio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union

logger = logging.getLogger(__name__)

# Mock session manager for testing
class MockSessionManager:
    """Mock session manager for testing purposes."""
    
    def __init__(self):
        self.sessions = {}
        self.session_counters = {
            "created": 0,
            "active": 0,
            "expired": 0,
            "cleaned": 0
        }
    
    async def create_session(self, **kwargs) -> Dict[str, Any]:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        
        session_data = {
            "session_id": session_id,
            "user_id": kwargs.get("user_id", "default_user"),
            "session_name": kwargs.get("session_name", f"Session-{session_id[:8]}"),
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(seconds=kwargs.get("timeout_seconds", 3600)),
            "status": "active",
            "config": kwargs.get("session_config", {}),
            "resources": kwargs.get("resource_allocation", {}),
            "last_activity": datetime.now(),
            "request_count": 0
        }
        
        self.sessions[session_id] = session_data
        self.session_counters["created"] += 1
        self.session_counters["active"] += 1
        
        return session_data
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID."""
        session = self.sessions.get(session_id)
        if session and session["status"] == "active":
            # Check expiration
            if datetime.now() > session["expires_at"]:
                session["status"] = "expired"
                self.session_counters["active"] -= 1
                self.session_counters["expired"] += 1
        return session
    
    async def update_session(self, session_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """Update session data."""
        if session_id in self.sessions:
            self.sessions[session_id].update(kwargs)
            self.sessions[session_id]["last_activity"] = datetime.now()
            return self.sessions[session_id]
        return None
    
    async def list_sessions(self, user_id: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List sessions with optional filters."""
        sessions = list(self.sessions.values())
        
        if user_id:
            sessions = [s for s in sessions if s.get("user_id") == user_id]
        
        if status:
            sessions = [s for s in sessions if s.get("status") == status]
        
        return sessions
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        if session_id in self.sessions:
            session = self.sessions.pop(session_id)
            if session["status"] == "active":
                self.session_counters["active"] -= 1
            self.session_counters["cleaned"] += 1
            return True
        return False
    
    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions."""
        now = datetime.now()
        expired_sessions = [
            session_id for session_id, session in self.sessions.items()
            if session["status"] == "active" and now > session["expires_at"]
        ]
        
        for session_id in expired_sessions:
            session = self.sessions[session_id]
            session["status"] = "expired"
            self.session_counters["active"] -= 1
            self.session_counters["expired"] += 1
        
        return len(expired_sessions)

# Global mock session manager instance
_mock_session_manager = MockSessionManager()

async def create_session(session_name: str, user_id: str = "default_user", 
                        session_config: Optional[Dict[str, Any]] = None,
                        resource_allocation: Optional[Dict[str, Any]] = None,
                        session_manager=None) -> Dict[str, Any]:
    """
    Create and initialize a new embedding service session.
    
    Args:
        session_name: Human-readable name for the session
        user_id: User ID creating the session
        session_config: Configuration parameters for the session
        resource_allocation: Resource allocation settings
        session_manager: Optional session manager service
        
    Returns:
        Dictionary containing session creation result
    """
    try:
        # Input validation
        if not session_name or not isinstance(session_name, str):
            return {
                "status": "error",
                "message": "Session name is required and must be a string"
            }
        
        if len(session_name) > 100:
            return {
                "status": "error",
                "message": "Session name must be 100 characters or less"
            }
        
        if not user_id or not isinstance(user_id, str):
            return {
                "status": "error",
                "message": "User ID is required and must be a string"
            }
        
        # Default configuration
        config = session_config or {
            "models": ["sentence-transformers/all-MiniLM-L6-v2"],
            "max_requests_per_minute": 100,
            "max_concurrent_requests": 10,
            "timeout_seconds": 3600,
            "auto_cleanup": True
        }
        
        # Default resource allocation
        resources = resource_allocation or {
            "memory_limit_mb": 2048,
            "cpu_cores": 1.0,
            "gpu_enabled": False
        }
        
        # Use provided session manager or default mock
        manager = session_manager or _mock_session_manager
        
        session = await manager.create_session(
            session_name=session_name,
            user_id=user_id,
            session_config=config,
            resource_allocation=resources,
            timeout_seconds=config.get("timeout_seconds", 3600)
        )
        
        return {
            "status": "success",
            "session_id": session["session_id"],
            "session_name": session["session_name"],
            "user_id": session["user_id"],
            "created_at": session["created_at"].isoformat(),
            "expires_at": session["expires_at"].isoformat(),
            "config": session["config"],
            "resources": session["resources"],
            "message": f"Session '{session_name}' created successfully"
        }
        
    except Exception as e:
        logger.error(f"Session creation error: {e}")
        return {
            "status": "error",
            "message": f"Failed to create session: {str(e)}"
        }

async def manage_session_state(session_id: str, action: str, **kwargs) -> Dict[str, Any]:
    """
    Manage session state and lifecycle operations.
    
    Args:
        session_id: Session ID to manage
        action: Action to perform (get, update, pause, resume, extend, delete)
        **kwargs: Additional parameters for the action
        
    Returns:
        Dictionary containing session management result
    """
    try:
        # Input validation
        if not session_id or not isinstance(session_id, str):
            return {
                "status": "error",
                "message": "Session ID is required and must be a string"
            }
        
        if action not in ["get", "update", "pause", "resume", "extend", "delete"]:
            return {
                "status": "error",
                "message": "Invalid action. Must be one of: get, update, pause, resume, extend, delete"
            }
        
        # Validate session ID format (UUID)
        try:
            uuid.UUID(session_id)
        except ValueError:
            return {
                "status": "error",
                "message": "Invalid session ID format"
            }
        
        # Use mock session manager
        manager = _mock_session_manager
        
        if action == "get":
            session = await manager.get_session(session_id)
            if not session:
                return {
                    "status": "error",
                    "message": "Session not found"
                }
            
            return {
                "status": "success",
                "session": {
                    "session_id": session["session_id"],
                    "session_name": session["session_name"],
                    "user_id": session["user_id"],
                    "status": session["status"],
                    "created_at": session["created_at"].isoformat(),
                    "expires_at": session["expires_at"].isoformat(),
                    "last_activity": session["last_activity"].isoformat(),
                    "request_count": session["request_count"]
                },
                "message": "Session retrieved successfully"
            }
        
        elif action == "update":
            session = await manager.update_session(session_id, **kwargs)
            if not session:
                return {
                    "status": "error",
                    "message": "Session not found"
                }
            
            return {
                "status": "success",
                "session_id": session_id,
                "updated_fields": list(kwargs.keys()),
                "message": "Session updated successfully"
            }
        
        elif action == "pause":
            session = await manager.update_session(session_id, status="paused")
            if not session:
                return {
                    "status": "error",
                    "message": "Session not found"
                }
            
            return {
                "status": "success",
                "session_id": session_id,
                "session_status": "paused",
                "message": "Session paused successfully"
            }
        
        elif action == "resume":
            session = await manager.update_session(session_id, status="active")
            if not session:
                return {
                    "status": "error",
                    "message": "Session not found"
                }
            
            return {
                "status": "success",
                "session_id": session_id,
                "session_status": "active",
                "message": "Session resumed successfully"
            }
        
        elif action == "extend":
            extend_minutes = kwargs.get("extend_minutes", 60)
            if not isinstance(extend_minutes, int) or extend_minutes <= 0:
                return {
                    "status": "error",
                    "message": "extend_minutes must be a positive integer"
                }
            
            session = await manager.get_session(session_id)
            if not session:
                return {
                    "status": "error",
                    "message": "Session not found"
                }
            
            new_expires_at = session["expires_at"] + timedelta(minutes=extend_minutes)
            await manager.update_session(session_id, expires_at=new_expires_at)
            
            return {
                "status": "success",
                "session_id": session_id,
                "new_expires_at": new_expires_at.isoformat(),
                "extended_by_minutes": extend_minutes,
                "message": f"Session extended by {extend_minutes} minutes"
            }
        
        elif action == "delete":
            deleted = await manager.delete_session(session_id)
            if not deleted:
                return {
                    "status": "error",
                    "message": "Session not found"
                }
            
            return {
                "status": "success",
                "session_id": session_id,
                "message": "Session deleted successfully"
            }
        
    except Exception as e:
        logger.error(f"Session management error: {e}")
        return {
            "status": "error",
            "message": f"Session management failed: {str(e)}"
        }

async def cleanup_sessions(cleanup_type: str = "expired", user_id: Optional[str] = None,
                          session_manager=None) -> Dict[str, Any]:
    """
    Clean up sessions and release resources.
    
    Args:
        cleanup_type: Type of cleanup (expired, all, by_user)
        user_id: User ID for user-specific cleanup
        session_manager: Optional session manager service
        
    Returns:
        Dictionary containing cleanup result
    """
    try:
        # Input validation
        if cleanup_type not in ["expired", "all", "by_user"]:
            return {
                "status": "error",
                "message": "Invalid cleanup_type. Must be one of: expired, all, by_user"
            }
        
        if cleanup_type == "by_user" and not user_id:
            return {
                "status": "error",
                "message": "user_id is required for by_user cleanup"
            }
        
        # Use mock session manager
        manager = session_manager or _mock_session_manager
        
        if cleanup_type == "expired":
            # Clean up expired sessions
            expired_count = await manager.cleanup_expired_sessions()
            
            return {
                "status": "success",
                "cleanup_type": "expired",
                "sessions_cleaned": expired_count,
                "message": f"Cleaned up {expired_count} expired sessions"
            }
        
        elif cleanup_type == "all":
            # Get all sessions and delete them
            sessions = await manager.list_sessions()
            deleted_count = 0
            
            for session in sessions:
                if await manager.delete_session(session["session_id"]):
                    deleted_count += 1
            
            return {
                "status": "success",
                "cleanup_type": "all",
                "sessions_cleaned": deleted_count,
                "message": f"Cleaned up {deleted_count} sessions"
            }
        
        elif cleanup_type == "by_user":
            # Get user sessions and delete them
            user_sessions = await manager.list_sessions(user_id=user_id)
            deleted_count = 0
            
            for session in user_sessions:
                if await manager.delete_session(session["session_id"]):
                    deleted_count += 1
            
            return {
                "status": "success",
                "cleanup_type": "by_user",
                "user_id": user_id,
                "sessions_cleaned": deleted_count,
                "message": f"Cleaned up {deleted_count} sessions for user {user_id}"
            }
        
    except Exception as e:
        logger.error(f"Session cleanup error: {e}")
        return {
            "status": "error",
            "message": f"Session cleanup failed: {str(e)}"
        }
