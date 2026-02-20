"""
Session Management Tools for IPFS Datasets MCP Server (thin wrapper)

Business logic lives in session_engine.
"""

import logging
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import re

from ..tool_wrapper import EnhancedBaseMCPTool
from ..validators import EnhancedParameterValidator
from ...monitoring import EnhancedMetricsCollector
from .session_engine import (  # noqa: F401
    validate_session_id,
    validate_user_id,
    validate_session_type,
    MockSessionManager,
)

logger = logging.getLogger(__name__)


class EnhancedSessionCreationTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for creating and initializing embedding service sessions.
    """

    def __init__(self, session_manager=None):
        super().__init__(
            name="create_session",
            description="Create and initialize new embedding service sessions with configuration and resource allocation",
            category="session_management"
        )
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "session_name": {
                    "type": "string",
                    "description": "Human-readable name for the session",
                    "minLength": 1,
                    "maxLength": 100
                },
                "user_id": {
                    "type": "string",
                    "description": "User identifier for the session",
                    "minLength": 1,
                    "maxLength": 100
                },
                "session_type": {
                    "type": "string",
                    "description": "Type of session",
                    "enum": ["interactive", "batch", "api", "temporary", "embedding", "search"],
                    "default": "interactive"
                },
                "session_config": {
                    "type": "object",
                    "description": "Configuration parameters for the session",
                    "properties": {
                        "models": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of embedding models to load",
                            "minItems": 1,
                            "maxItems": 10
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Session timeout in seconds",
                            "minimum": 60,
                            "maximum": 86400,
                            "default": 3600
                        },
                        "auto_save": {
                            "type": "boolean",
                            "description": "Enable automatic saving",
                            "default": true
                        }
                    }
                },
                "resource_limits": {
                    "type": "object",
                    "description": "Resource limits for the session",
                    "properties": {
                        "max_memory": {
                            "type": "string",
                            "description": "Maximum memory limit",
                            "default": "2GB"
                        },
                        "max_cpu": {
                            "type": "string",
                            "description": "Maximum CPU cores",
                            "default": "2 cores"
                        },
                        "max_storage": {
                            "type": "string",
                            "description": "Maximum storage limit",
                            "default": "10GB"
                        }
                    }
                },
                "metadata": {
                    "type": "object",
                    "description": "Additional metadata for the session"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for session organization"
                }
            },
            "required": ["session_name"]
        }
        
        self.session_manager = session_manager or MockSessionManager()
        self.tags = ["session", "create", "management", "initialization"]

    async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute session creation."""
        try:
            # Validate input parameters
            session_name = self.validator.validate_text_input(
                parameters.get("session_name", ""),
                max_length=100
            )
            
            user_id = parameters.get("user_id", "anonymous_user")
            session_type = parameters.get("session_type", "interactive")
            
            # Validate session type
            if not validate_session_type(session_type):
                return {
                    "status": "error",
                    "error": f"Invalid session type: {session_type}",
                    "code": "INVALID_SESSION_TYPE"
                }
            
            # Validate user ID
            if user_id and not validate_user_id(user_id):
                return {
                    "status": "error",
                    "error": "Invalid user ID format",
                    "code": "INVALID_USER_ID"
                }
            
            # Track session creation request
            self.metrics.record_request("session_creation", {
                "session_type": session_type,
                "user_id": user_id
            })
            
            # Create session
            session_data = await self.session_manager.create_session(
                session_name=session_name,
                user_id=user_id,
                session_type=session_type,
                session_config=parameters.get("session_config", {}),
                resource_limits=parameters.get("resource_limits", {}),
                metadata=parameters.get("metadata", {}),
                tags=parameters.get("tags", [])
            )
            
            self.metrics.record_request("session_creation_success")
            self.logger.info(f"Session created: {session_data['session_id']} for user {user_id}")
            
            return {
                "status": "success",
                "session": session_data,
                "message": f"Session '{session_name}' created successfully"
            }
            
        except Exception as e:
            self.logger.error(f"Session creation error: {e}")
            self.metrics.record_error("session_creation_error", str(e))
            return {
                "status": "error",
                "error": "Session creation failed",
                "code": "CREATION_FAILED",
                "message": str(e)
            }


class EnhancedSessionManagementTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for managing session lifecycle operations.
    """

    def __init__(self, session_manager=None):
        super().__init__(
            name="manage_session",
            description="Manage session lifecycle including get, update, delete, and list operations",
            category="session_management"
        )
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["get", "update", "delete", "list", "cleanup"],
                    "default": "get"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID for get/update/delete operations",
                    "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
                },
                "updates": {
                    "type": "object",
                    "description": "Updates to apply to session (for update action)",
                    "properties": {
                        "session_name": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["active", "paused", "terminated"]
                        },
                        "metadata": {"type": "object"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    }
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for list operation",
                    "properties": {
                        "user_id": {"type": "string"},
                        "status": {"type": "string"},
                        "session_type": {"type": "string"},
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 50
                        }
                    }
                },
                "cleanup_options": {
                    "type": "object",
                    "description": "Options for cleanup operation",
                    "properties": {
                        "max_age_hours": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 168,
                            "default": 24
                        },
                        "dry_run": {
                            "type": "boolean",
                            "default": false
                        }
                    }
                }
            },
            "required": ["action"]
        }
        
        self.session_manager = session_manager or MockSessionManager()
        self.tags = ["session", "management", "lifecycle", "operations"]

    async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute session management operations."""
        try:
            action = parameters.get("action", "get")
            session_id = parameters.get("session_id")
            
            # Track session management request
            self.metrics.record_request("session_management", {"action": action})
            
            if action == "get":
                if not session_id:
                    return {
                        "status": "error",
                        "error": "session_id is required for get action",
                        "code": "MISSING_SESSION_ID"
                    }
                
                if not validate_session_id(session_id):
                    return {
                        "status": "error",
                        "error": "Invalid session ID format",
                        "code": "INVALID_SESSION_ID"
                    }
                
                session = await self.session_manager.get_session(session_id)
                if not session:
                    return {
                        "status": "error",
                        "error": "Session not found",
                        "code": "SESSION_NOT_FOUND"
                    }
                
                return {
                    "status": "success",
                    "session": session,
                    "message": "Session retrieved successfully"
                }
            
            elif action == "update":
                if not session_id:
                    return {
                        "status": "error",
                        "error": "session_id is required for update action",
                        "code": "MISSING_SESSION_ID"
                    }
                
                updates = parameters.get("updates", {})
                if not updates:
                    return {
                        "status": "error",
                        "error": "updates are required for update action",
                        "code": "MISSING_UPDATES"
                    }
                
                session = await self.session_manager.update_session(session_id, **updates)
                if not session:
                    return {
                        "status": "error",
                        "error": "Session not found or update failed",
                        "code": "UPDATE_FAILED"
                    }
                
                self.logger.info(f"Session updated: {session_id}")
                return {
                    "status": "success",
                    "session": session,
                    "message": "Session updated successfully"
                }
            
            elif action == "delete":
                if not session_id:
                    return {
                        "status": "error",
                        "error": "session_id is required for delete action",
                        "code": "MISSING_SESSION_ID"
                    }
                
                deleted_session = await self.session_manager.delete_session(session_id)
                if not deleted_session:
                    return {
                        "status": "error",
                        "error": "Session not found",
                        "code": "SESSION_NOT_FOUND"
                    }
                
                self.logger.info(f"Session deleted: {session_id}")
                return {
                    "status": "success",
                    "session": deleted_session,
                    "message": "Session deleted successfully"
                }
            
            elif action == "list":
                filters = parameters.get("filters", {})
                sessions = await self.session_manager.list_sessions(**filters)
                
                # Apply limit
                limit = filters.get("limit", 50)
                sessions = sessions[:limit]
                
                return {
                    "status": "success",
                    "sessions": sessions,
                    "count": len(sessions),
                    "message": f"Retrieved {len(sessions)} sessions"
                }
            
            elif action == "cleanup":
                cleanup_options = parameters.get("cleanup_options", {})
                max_age_hours = cleanup_options.get("max_age_hours", 24)
                dry_run = cleanup_options.get("dry_run", False)
                
                if dry_run:
                    # Simulate cleanup
                    expired_sessions = []
                    current_time = datetime.now()
                    
                    for session in await self.session_manager.list_sessions():
                        created_at = datetime.fromisoformat(session["created_at"])
                        if (current_time - created_at).total_seconds() > max_age_hours * 3600:
                            expired_sessions.append(session)
                    
                    return {
                        "status": "success",
                        "dry_run": True,
                        "would_cleanup": len(expired_sessions),
                        "sessions": expired_sessions,
                        "message": f"Would cleanup {len(expired_sessions)} sessions"
                    }
                else:
                    expired_sessions = await self.session_manager.cleanup_expired_sessions(max_age_hours)
                    
                    self.logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
                    return {
                        "status": "success",
                        "cleaned_up": len(expired_sessions),
                        "sessions": expired_sessions,
                        "message": f"Cleaned up {len(expired_sessions)} sessions"
                    }
            
            else:
                return {
                    "status": "error",
                    "error": f"Unknown action: {action}",
                    "code": "UNKNOWN_ACTION"
                }
            
        except Exception as e:
            self.logger.error(f"Session management error: {e}")
            self.metrics.record_error("session_management_error", str(e))
            return {
                "status": "error",
                "error": "Session management failed",
                "code": "MANAGEMENT_FAILED",
                "message": str(e)
            }


class EnhancedSessionStateTool(EnhancedBaseMCPTool):
    """
    Enhanced tool for monitoring session state and metrics.
    """

    def __init__(self, session_manager=None):
        super().__init__(
            name="get_session_state",
            description="Get comprehensive session state, metrics, and health information",
            category="session_management"
        )
        
        self.input_schema = {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID to get state for",
                    "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
                },
                "include_metrics": {
                    "type": "boolean",
                    "description": "Include performance metrics",
                    "default": true
                },
                "include_resources": {
                    "type": "boolean",
                    "description": "Include resource usage information",
                    "default": true
                },
                "include_health": {
                    "type": "boolean",
                    "description": "Include health check results",
                    "default": true
                }
            },
            "required": ["session_id"]
        }
        
        self.session_manager = session_manager or MockSessionManager()
        self.tags = ["session", "state", "metrics", "monitoring", "health"]

    async def _execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute session state retrieval."""
        try:
            session_id = parameters.get("session_id")
            include_metrics = parameters.get("include_metrics", True)
            include_resources = parameters.get("include_resources", True)
            include_health = parameters.get("include_health", True)
            
            if not validate_session_id(session_id):
                return {
                    "status": "error",
                    "error": "Invalid session ID format",
                    "code": "INVALID_SESSION_ID"
                }
            
            # Track session state request
            self.metrics.record_request("session_state_request")
            
            # Get session data
            session = await self.session_manager.get_session(session_id)
            if not session:
                return {
                    "status": "error",
                    "error": "Session not found",
                    "code": "SESSION_NOT_FOUND"
                }
            
            # Build response
            state_data = {
                "session_id": session_id,
                "basic_info": {
                    "session_name": session.get("session_name"),
                    "user_id": session.get("user_id"),
                    "session_type": session.get("session_type"),
                    "status": session.get("status"),
                    "created_at": session.get("created_at"),
                    "last_activity": session.get("last_activity")
                }
            }
            
            if include_metrics and "metrics" in session:
                metrics = session["metrics"]
                current_time = datetime.now()
                start_time = datetime.fromisoformat(session["created_at"])
                uptime_seconds = (current_time - start_time).total_seconds()
                
                state_data["performance_metrics"] = {
                    **metrics,
                    "uptime_seconds": uptime_seconds,
                    "uptime_human": str(timedelta(seconds=int(uptime_seconds))),
                    "requests_per_minute": metrics.get("requests_count", 0) / max(1, uptime_seconds / 60)
                }
            
            if include_resources and "resource_limits" in session:
                state_data["resource_info"] = {
                    "limits": session["resource_limits"],
                    "current_usage": {
                        "memory": "1.2GB",  # Mock data
                        "cpu": "1.5 cores",
                        "storage": "2.3GB"
                    },
                    "usage_percentage": {
                        "memory": 60,
                        "cpu": 75,
                        "storage": 23
                    }
                }
            
            if include_health:
                # Mock health check results
                health_status = "healthy"
                health_issues = []
                
                # Check for potential issues
                if session.get("status") != "active":
                    health_status = "warning"
                    health_issues.append(f"Session status is {session.get('status')}")
                
                # Check session age
                created_at = datetime.fromisoformat(session["created_at"])
                age_hours = (datetime.now() - created_at).total_seconds() / 3600
                if age_hours > 48:
                    health_status = "warning"
                    health_issues.append("Session is over 48 hours old")
                
                state_data["health_info"] = {
                    "status": health_status,
                    "issues": health_issues,
                    "last_check": datetime.now().isoformat(),
                    "checks_passed": len(health_issues) == 0
                }
            
            # Add configuration info
            if "configuration" in session:
                state_data["configuration"] = session["configuration"]
            
            # Add metadata and tags
            if "metadata" in session:
                state_data["metadata"] = session["metadata"]
            
            if "tags" in session:
                state_data["tags"] = session["tags"]
            
            return {
                "status": "success",
                "session_state": state_data,
                "message": "Session state retrieved successfully"
            }
            
        except Exception as e:
            self.logger.error(f"Session state retrieval error: {e}")
            self.metrics.record_error("session_state_error", str(e))
            return {
                "status": "error",
                "error": "Session state retrieval failed",
                "code": "STATE_RETRIEVAL_FAILED",
                "message": str(e)
            }
