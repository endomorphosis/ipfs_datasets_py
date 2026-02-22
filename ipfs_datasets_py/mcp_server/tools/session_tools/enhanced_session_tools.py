"""
Enhanced Session Management Tools — thin standalone-function wrappers.

Business logic is in ipfs_datasets_py.sessions.session_engine (via the local
session_engine.py shim).  Each function below replaces a class that previously
extended EnhancedBaseMCPTool.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.sessions.session_engine import (
    MockSessionManager,
    validate_session_id,
    validate_session_type,
    validate_user_id,
)

logger = logging.getLogger(__name__)

_session_manager = MockSessionManager()


# ---------------------------------------------------------------------------
# 1.  create_session  (was EnhancedSessionCreationTool)
# ---------------------------------------------------------------------------

async def create_session(
    session_name: str = "",
    user_id: str = "anonymous_user",
    session_type: str = "interactive",
    session_config: Optional[Dict[str, Any]] = None,
    resource_limits: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create and initialise a new session."""
    try:
        if session_name and len(session_name) > 100:
            return {"status": "error", "error": "session_name too long (max 100 chars)", "code": "INVALID_NAME"}
        if not validate_session_type(session_type):
            return {"status": "error", "error": f"Invalid session type: {session_type}", "code": "INVALID_SESSION_TYPE"}
        if user_id and not validate_user_id(user_id):
            return {"status": "error", "error": "Invalid user ID format", "code": "INVALID_USER_ID"}

        session_data = await _session_manager.create_session(
            session_name=session_name,
            user_id=user_id,
            session_type=session_type,
            session_config=session_config or {},
            resource_limits=resource_limits or {},
            metadata=metadata or {},
            tags=tags or [],
        )
        logger.info("Session created: %s for user %s", session_data["session_id"], user_id)
        return {"status": "success", "session": session_data, "message": f"Session '{session_name}' created successfully"}

    except Exception as exc:
        logger.error("Session creation error: %s", exc)
        return {"status": "error", "error": "Session creation failed", "code": "CREATION_FAILED", "message": str(exc)}


# ---------------------------------------------------------------------------
# 2.  manage_session  (was EnhancedSessionManagementTool)
# ---------------------------------------------------------------------------

async def manage_session(
    action: str = "get",
    session_id: Optional[str] = None,
    updates: Optional[Dict[str, Any]] = None,
    filters: Optional[Dict[str, Any]] = None,
    cleanup_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Manage session lifecycle (get, update, delete, list, cleanup)."""
    try:
        if action == "get":
            if not session_id:
                return {"status": "error", "error": "session_id is required for get action", "code": "MISSING_SESSION_ID"}
            if not validate_session_id(session_id):
                return {"status": "error", "error": "Invalid session ID format", "code": "INVALID_SESSION_ID"}
            session = await _session_manager.get_session(session_id)
            if not session:
                return {"status": "error", "error": "Session not found", "code": "SESSION_NOT_FOUND"}
            return {"status": "success", "session": session, "message": "Session retrieved successfully"}

        elif action == "update":
            if not session_id:
                return {"status": "error", "error": "session_id is required for update action", "code": "MISSING_SESSION_ID"}
            if not validate_session_id(session_id):
                return {"status": "error", "error": "Invalid session ID format", "code": "INVALID_SESSION_ID"}
            session = await _session_manager.update_session(session_id, **(updates or {}))
            if not session:
                return {"status": "error", "error": "Session not found", "code": "SESSION_NOT_FOUND"}
            return {"status": "success", "session": session, "message": "Session updated successfully"}

        elif action == "delete":
            if not session_id:
                return {"status": "error", "error": "session_id is required for delete action", "code": "MISSING_SESSION_ID"}
            if not validate_session_id(session_id):
                return {"status": "error", "error": "Invalid session ID format", "code": "INVALID_SESSION_ID"}
            deleted = await _session_manager.delete_session(session_id)
            if not deleted:
                return {"status": "error", "error": "Session not found", "code": "SESSION_NOT_FOUND"}
            return {"status": "success", "session_id": session_id, "message": "Session deleted successfully"}

        elif action == "list":
            sessions = await _session_manager.list_sessions(**(filters or {}))
            return {"status": "success", "sessions": sessions, "count": len(sessions), "message": f"Found {len(sessions)} sessions"}

        elif action == "cleanup":
            opts = cleanup_options or {}
            max_age_hours = opts.get("max_age_hours", 24)
            dry_run = opts.get("dry_run", False)
            if not dry_run:
                expired = await _session_manager.cleanup_expired_sessions(max_age_hours=max_age_hours)
            else:
                expired = []
            return {"status": "success", "cleaned_up": len(expired), "dry_run": dry_run, "message": f"Cleaned up {len(expired)} expired sessions"}

        else:
            return {"status": "error", "error": f"Unknown action: {action}", "code": "UNKNOWN_ACTION",
                    "valid_actions": ["get", "update", "delete", "list", "cleanup"]}

    except Exception as exc:
        logger.error("Session management error: %s", exc)
        return {"status": "error", "error": "Session management failed", "code": "MANAGEMENT_FAILED", "message": str(exc)}


# ---------------------------------------------------------------------------
# 3.  get_session_state  (was EnhancedSessionStateTool)
# ---------------------------------------------------------------------------

async def get_session_state(
    session_id: str,
    include_metrics: bool = True,
    include_resources: bool = True,
    include_health: bool = True,
) -> Dict[str, Any]:
    """Get comprehensive session state, metrics, and health information."""
    try:
        if not validate_session_id(session_id):
            return {"status": "error", "error": "Invalid session ID format", "code": "INVALID_SESSION_ID"}

        session = await _session_manager.get_session(session_id)
        if not session:
            return {"status": "error", "error": "Session not found", "code": "SESSION_NOT_FOUND"}

        state_data: Dict[str, Any] = {
            "session_id": session_id,
            "basic_info": {
                "session_name": session.get("session_name"),
                "user_id": session.get("user_id"),
                "session_type": session.get("session_type"),
                "status": session.get("status"),
                "created_at": session.get("created_at"),
                "last_activity": session.get("last_activity"),
            },
        }

        if include_metrics:
            state_data["metrics"] = {
                "total_requests": session.get("request_count", 0),
                "successful_requests": session.get("success_count", 0),
                "failed_requests": session.get("error_count", 0),
                "average_response_time": session.get("avg_response_time", 0.0),
                "data_processed_mb": session.get("data_processed_mb", 0.0),
            }

        if include_resources:
            state_data["resource_usage"] = {
                "memory_mb": session.get("memory_mb", 0),
                "cpu_percent": session.get("cpu_percent", 0.0),
                "active_connections": session.get("active_connections", 0),
                "storage_mb": session.get("storage_mb", 0),
            }

        if include_health:
            health_status = "healthy"
            health_issues: List[str] = []
            if session.get("status") != "active":
                health_status = "warning"
                health_issues.append(f"Session status is {session.get('status')}")
            try:
                created_at = datetime.fromisoformat(session["created_at"])
                age_hours = (datetime.now() - created_at).total_seconds() / 3600
                if age_hours > 48:
                    health_status = "warning"
                    health_issues.append("Session is over 48 hours old")
            except (KeyError, ValueError):
                pass
            state_data["health_info"] = {
                "status": health_status,
                "issues": health_issues,
                "last_check": datetime.now().isoformat(),
                "checks_passed": len(health_issues) == 0,
            }

        if "metadata" in session:
            state_data["metadata"] = session["metadata"]
        if "tags" in session:
            state_data["tags"] = session["tags"]

        return {"status": "success", "session_state": state_data, "message": "Session state retrieved successfully"}

    except Exception as exc:
        logger.error("Session state retrieval error: %s", exc)
        return {"status": "error", "error": "Session state retrieval failed", "code": "STATE_RETRIEVAL_FAILED", "message": str(exc)}


# ---------------------------------------------------------------------------
# Backward-compatible class shims
# ---------------------------------------------------------------------------

class EnhancedSessionCreationTool:
    """Backward-compatible shim — delegates to :func:`create_session`."""
    name = "create_session"
    async def execute(self, **kw): return await create_session(**kw)  # type: ignore[misc]


class EnhancedSessionManagementTool:
    """Backward-compatible shim — delegates to :func:`manage_session`."""
    name = "manage_session"
    async def execute(self, **kw): return await manage_session(**kw)  # type: ignore[misc]


class EnhancedSessionStateTool:
    """Backward-compatible shim — delegates to :func:`get_session_state`."""
    name = "get_session_state"
    async def execute(self, **kw): return await get_session_state(**kw)  # type: ignore[misc]
