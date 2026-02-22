"""
Session management tools for MCP server — thin wrapper.

Business logic (MockSessionManager) lives in the canonical package module:
    ipfs_datasets_py.sessions.session_engine

This file imports MockSessionManager from the canonical location and provides
the three MCP-callable standalone async functions.
"""

import anyio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.sessions.session_engine import MockSessionManager  # noqa: F401

logger = logging.getLogger(__name__)

# Global mock session manager instance
_mock_session_manager = MockSessionManager()


async def create_session(
    session_name: str,
    user_id: str = "default_user",
    session_config: Optional[Dict[str, Any]] = None,
    resource_allocation: Optional[Dict[str, Any]] = None,
    session_manager=None,
) -> Dict[str, Any]:
    """Create and initialize a new embedding service session.

    Args:
        session_name: Human-readable name for the session.
        user_id: User ID creating the session.
        session_config: Configuration parameters for the session.
        resource_allocation: Resource allocation settings.
        session_manager: Optional session manager service.

    Returns:
        Dictionary containing session creation result.
    """
    try:
        if not session_name or not isinstance(session_name, str):
            return {"status": "error", "message": "Session name is required and must be a string"}
        if len(session_name) > 100:
            return {"status": "error", "message": "Session name must be 100 characters or less"}
        if not user_id or not isinstance(user_id, str):
            return {"status": "error", "message": "User ID is required and must be a string"}

        config = session_config or {
            "models": ["sentence-transformers/all-MiniLM-L6-v2"],
            "max_requests_per_minute": 100,
            "max_concurrent_requests": 10,
            "timeout_seconds": 3600,
            "auto_cleanup": True,
        }
        resources = resource_allocation or {
            "memory_limit_mb": 2048,
            "cpu_cores": 1.0,
            "gpu_enabled": False,
        }

        manager = session_manager or _mock_session_manager
        session = await manager.create_session(
            session_name=session_name,
            user_id=user_id,
            session_config=config,
            resource_allocation=resources,
            timeout_seconds=config.get("timeout_seconds", 3600),
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
            "message": f"Session '{session_name}' created successfully",
        }
    except Exception as exc:
        logger.error("Session creation error: %s", exc)
        return {"status": "error", "message": f"Failed to create session: {exc}"}


async def manage_session_state(
    session_id: str,
    action: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Manage session state and lifecycle operations.

    Args:
        session_id: Session ID to manage.
        action: One of ``get``, ``update``, ``pause``, ``resume``, ``extend``, ``delete``.
        **kwargs: Additional parameters for the action.

    Returns:
        Dictionary containing the session management result.
    """
    try:
        if not session_id or not isinstance(session_id, str):
            return {"status": "error", "message": "Session ID is required and must be a string"}

        valid_actions = {"get", "update", "pause", "resume", "extend", "delete"}
        if action not in valid_actions:
            return {
                "status": "error",
                "message": f"Invalid action. Must be one of: {', '.join(sorted(valid_actions))}",
            }

        try:
            uuid.UUID(session_id)
        except ValueError:
            return {"status": "error", "message": "Invalid session ID format"}

        manager = _mock_session_manager

        if action == "get":
            session = await manager.get_session(session_id)
            if not session:
                return {"status": "error", "message": "Session not found"}
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
                    "request_count": session["request_count"],
                },
                "message": "Session retrieved successfully",
            }

        if action == "update":
            session = await manager.update_session(session_id, **kwargs)
            if not session:
                return {"status": "error", "message": "Session not found"}
            return {
                "status": "success",
                "session_id": session_id,
                "updated_fields": list(kwargs.keys()),
                "message": "Session updated successfully",
            }

        if action == "pause":
            session = await manager.update_session(session_id, status="paused")
            if not session:
                return {"status": "error", "message": "Session not found"}
            return {"status": "success", "session_id": session_id, "session_status": "paused",
                    "message": "Session paused successfully"}

        if action == "resume":
            session = await manager.update_session(session_id, status="active")
            if not session:
                return {"status": "error", "message": "Session not found"}
            return {"status": "success", "session_id": session_id, "session_status": "active",
                    "message": "Session resumed successfully"}

        if action == "extend":
            extend_minutes = kwargs.get("extend_minutes", 60)
            if not isinstance(extend_minutes, int) or extend_minutes <= 0:
                return {"status": "error", "message": "extend_minutes must be a positive integer"}
            session = await manager.get_session(session_id)
            if not session:
                return {"status": "error", "message": "Session not found"}
            new_expires_at = session["expires_at"] + timedelta(minutes=extend_minutes)
            await manager.update_session(session_id, expires_at=new_expires_at)
            return {
                "status": "success",
                "session_id": session_id,
                "new_expires_at": new_expires_at.isoformat(),
                "extended_by_minutes": extend_minutes,
                "message": f"Session extended by {extend_minutes} minutes",
            }

        if action == "delete":
            deleted = await manager.delete_session(session_id)
            if not deleted:
                return {"status": "error", "message": "Session not found"}
            return {"status": "success", "session_id": session_id,
                    "message": "Session deleted successfully"}

    except Exception as exc:
        logger.error("Session management error: %s", exc)
        return {"status": "error", "message": f"Session management failed: {exc}"}


async def cleanup_sessions(
    cleanup_type: str = "expired",
    user_id: Optional[str] = None,
    session_manager=None,
) -> Dict[str, Any]:
    """Clean up sessions and release resources.

    Args:
        cleanup_type: One of ``expired``, ``all``, ``by_user``.
        user_id: User ID for user-specific cleanup.
        session_manager: Optional session manager service.

    Returns:
        Dictionary containing cleanup result.
    """
    try:
        valid_types = {"expired", "all", "by_user"}
        if cleanup_type not in valid_types:
            return {
                "status": "error",
                "message": f"Invalid cleanup_type. Must be one of: {', '.join(sorted(valid_types))}",
            }
        if cleanup_type == "by_user" and not user_id:
            return {"status": "error", "message": "user_id is required for by_user cleanup"}

        manager = session_manager or _mock_session_manager

        if cleanup_type == "expired":
            expired_count = await manager.cleanup_expired_sessions()
            return {
                "status": "success",
                "cleanup_type": "expired",
                "sessions_cleaned": expired_count,
                "message": f"Cleaned up {expired_count} expired sessions",
            }

        if cleanup_type == "all":
            sessions = await manager.list_sessions()
            deleted_count = sum(
                1 for s in sessions if await manager.delete_session(s["session_id"])
            )
            return {
                "status": "success",
                "cleanup_type": "all",
                "sessions_cleaned": deleted_count,
                "message": f"Cleaned up {deleted_count} sessions",
            }

        if cleanup_type == "by_user":
            user_sessions = await manager.list_sessions(user_id=user_id)
            deleted_count = sum(
                1 for s in user_sessions if await manager.delete_session(s["session_id"])
            )
            return {
                "status": "success",
                "cleanup_type": "by_user",
                "user_id": user_id,
                "sessions_cleaned": deleted_count,
                "message": f"Cleaned up {deleted_count} sessions for user {user_id}",
            }

    except Exception as exc:
        logger.error("Session cleanup error: %s", exc)
        return {"status": "error", "message": f"Session cleanup failed: {exc}"}
