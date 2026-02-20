"""
Session Engine

Business logic for session management, including validation helpers
and the MockSessionManager.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def validate_session_id(session_id: str) -> bool:
    """Validate session ID format (UUID)."""
    if not session_id or not isinstance(session_id, str):
        return False
    try:
        uuid.UUID(session_id)
        return True
    except (ValueError, TypeError):
        return False


def validate_user_id(user_id: str) -> bool:
    """Validate user ID format."""
    if not user_id or not isinstance(user_id, str):
        return False
    return 0 < len(user_id) <= 100


def validate_session_type(session_type: str) -> bool:
    """Validate session type."""
    valid_types = {"interactive", "batch", "api", "temporary", "embedding", "search"}
    return session_type in valid_types


class MockSessionManager:
    """Enhanced mock session manager with production features."""

    def __init__(self) -> None:
        self.sessions: Dict[str, Any] = {}
        self.session_configs: Dict[str, Any] = {}
        self.session_resources: Dict[str, Any] = {}
        self.session_metrics: Dict[str, Any] = {}

    async def create_session(self, **kwargs: Any) -> Dict[str, Any]:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        current_time = datetime.now()
        session_data: Dict[str, Any] = {
            "session_id": session_id,
            "user_id": kwargs.get("user_id", "default_user"),
            "session_name": kwargs.get("session_name", f"Session-{session_id[:8]}"),
            "session_type": kwargs.get("session_type", "interactive"),
            "created_at": current_time.isoformat(),
            "last_activity": current_time.isoformat(),
            "status": "active",
            "configuration": kwargs.get("session_config", {}),
            "resource_limits": kwargs.get(
                "resource_limits",
                {"max_memory": "2GB", "max_cpu": "2 cores",
                 "max_storage": "10GB", "timeout": 3600},
            ),
            "metadata": kwargs.get("metadata", {}),
            "tags": kwargs.get("tags", []),
        }
        self.sessions[session_id] = session_data
        self.session_metrics[session_id] = {
            "requests_count": 0,
            "data_processed": 0,
            "errors_count": 0,
            "start_time": current_time,
            "cpu_time": 0,
            "memory_peak": 0,
        }
        return session_data

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session information."""
        session = self.sessions.get(session_id)
        if session:
            session["last_activity"] = datetime.now().isoformat()
            session["metrics"] = self.session_metrics.get(session_id, {})
        return session

    async def update_session(self, session_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Update session properties."""
        if session_id not in self.sessions:
            return None
        session = self.sessions[session_id]
        session.update(kwargs)
        session["last_activity"] = datetime.now().isoformat()
        if "metrics_update" in kwargs:
            metrics = self.session_metrics.get(session_id, {})
            metrics.update(kwargs["metrics_update"])
            self.session_metrics[session_id] = metrics
        return session

    async def delete_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Delete session and cleanup resources."""
        session = self.sessions.pop(session_id, None)
        self.session_metrics.pop(session_id, None)
        self.session_configs.pop(session_id, None)
        self.session_resources.pop(session_id, None)
        if session:
            session["status"] = "terminated"
            session["deleted_at"] = datetime.now().isoformat()
        return session

    async def list_sessions(self, **filters: Any) -> List[Dict[str, Any]]:
        """List sessions with filtering options."""
        sessions = list(self.sessions.values())
        if "user_id" in filters:
            sessions = [s for s in sessions if s.get("user_id") == filters["user_id"]]
        if "status" in filters:
            sessions = [s for s in sessions if s.get("status") == filters["status"]]
        if "session_type" in filters:
            sessions = [s for s in sessions if s.get("session_type") == filters["session_type"]]
        for session in sessions:
            sid = session["session_id"]
            session["metrics"] = self.session_metrics.get(sid, {})
        return sessions

    async def cleanup_expired_sessions(self, max_age_hours: int = 24) -> List[Dict[str, Any]]:
        """Cleanup expired sessions."""
        current_time = datetime.now()
        expired: List[Dict[str, Any]] = []
        for session_id in list(self.sessions.keys()):
            created_at = datetime.fromisoformat(self.sessions[session_id]["created_at"])
            if (current_time - created_at).total_seconds() > max_age_hours * 3600:
                expired_session = await self.delete_session(session_id)
                if expired_session:
                    expired.append(expired_session)
        return expired
