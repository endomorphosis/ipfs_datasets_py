"""
Core Audit Logging Implementation

This module provides the core audit logging functionality, defining the central
AuditLogger class and associated data structures for comprehensive audit logging.
"""

import os
import json
import time
import uuid
import socket
import logging
import datetime
import threading
import traceback
from typing import Dict, List, Any, Optional, Union, Callable, Type, Set
from enum import Enum, auto
from dataclasses import dataclass, field, asdict

# Try to import security module for integration with AuditLogEntry if available
try:
    from ipfs_datasets_py.security import AuditLogEntry
    SECURITY_MODULE_AVAILABLE = True
except ImportError:
    SECURITY_MODULE_AVAILABLE = False


class AuditLevel(Enum):
    """Audit event severity levels."""
    DEBUG = 10
    INFO = 20
    NOTICE = 25  # Significant but normal events
    WARNING = 30
    ERROR = 40
    CRITICAL = 50
    EMERGENCY = 60  # System is unusable


class AuditCategory(Enum):
    """Categories of audit events."""
    AUTHENTICATION = auto()  # User login/logout events
    AUTHORIZATION = auto()   # Permission checks and access control
    DATA_ACCESS = auto()     # Reading data or metadata
    DATA_MODIFICATION = auto()  # Writing, updating, or deleting data
    CONFIGURATION = auto()   # System configuration changes
    RESOURCE = auto()        # Resource creation, deletion, modification
    SECURITY = auto()        # Security-related events
    SYSTEM = auto()          # System-level events
    API = auto()             # API calls and responses
    COMPLIANCE = auto()      # Compliance-related events
    PROVENANCE = auto()      # Data provenance tracking
    OPERATIONAL = auto()     # General operational events
    INTRUSION_DETECTION = auto()  # Possible security breaches
    CUSTOM = auto()          # Custom event categories


@dataclass
class AuditEvent:
    """
    Comprehensive audit event structure capturing all relevant information.

    This class defines the structure of audit events with rich metadata
    for security analysis, compliance reporting, and operational monitoring.
    """
    event_id: str
    timestamp: str
    level: AuditLevel
    category: AuditCategory
    action: str
    user: Optional[str] = None
    resource_id: Optional[str] = None
    resource_type: Optional[str] = None
    status: str = "success"
    details: Dict[str, Any] = field(default_factory=dict)
    client_ip: Optional[str] = None
    session_id: Optional[str] = None
    process_id: Optional[int] = None
    hostname: Optional[str] = None
    application: str = "ipfs_datasets_py"
    duration_ms: Optional[int] = None
    source_module: Optional[str] = None
    source_function: Optional[str] = None
    related_events: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    version: str = "1.0"

    def __post_init__(self):
        """Initialize default values if not provided."""
        if not self.event_id:
            self.event_id = str(uuid.uuid4())

        if not self.timestamp:
            self.timestamp = datetime.datetime.utcnow().isoformat() + 'Z'

        if not self.hostname:
            self.hostname = socket.gethostname()

        if not self.process_id:
            self.process_id = os.getpid()

    def to_dict(self) -> Dict[str, Any]:
        """Convert the audit event to a dictionary."""
        event_dict = asdict(self)
        # Convert enum values to strings for serialization
        event_dict['level'] = self.level.name
        event_dict['category'] = self.category.name
        return event_dict

    def to_json(self, pretty=False) -> str:
        """Serialize the audit event to JSON."""
        if pretty:
            return json.dumps(self.to_dict(), indent=2)
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AuditEvent':
        """Create an AuditEvent from a dictionary."""
        # Convert string values back to enums
        if 'level' in data and isinstance(data['level'], str):
            data['level'] = AuditLevel[data['level']]
        if 'category' in data and isinstance(data['category'], str):
            data['category'] = AuditCategory[data['category']]
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> 'AuditEvent':
        """Create an AuditEvent from a JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_security_audit_entry(cls, entry: Any) -> 'AuditEvent':
        """
        Create an AuditEvent from a security module AuditLogEntry.

        This provides backwards compatibility with existing audit entries.
        """
        if not SECURITY_MODULE_AVAILABLE:
            raise ImportError("Security module is not available")

        # Map entry fields to AuditEvent fields
        return cls(
            event_id=entry.event_id,
            timestamp=entry.timestamp,
            level=AuditLevel.INFO,  # Default level
            category=AuditCategory.SECURITY,  # Default category
            action=entry.action,
            user=entry.user,
            resource_id=entry.resource_id,
            resource_type=entry.resource_type,
            status="success" if entry.success else "failure",
            details=entry.details,
            client_ip=entry.source_ip,
        )

    def to_security_audit_entry(self) -> Any:
        """
        Convert this AuditEvent to a security module AuditLogEntry.

        This provides backwards compatibility with existing security module.
        """
        if not SECURITY_MODULE_AVAILABLE:
            raise ImportError("Security module is not available")

        from ipfs_datasets_py.security import AuditLogEntry
        return AuditLogEntry(
            event_id=self.event_id,
            timestamp=self.timestamp,
            event_type=f"{self.category.name.lower()}_{self.action}",
            user=self.user or "system",
            resource_id=self.resource_id,
            resource_type=self.resource_type,
            action=self.action,
            status=self.status,
            details=self.details,
            source_ip=self.client_ip,
            success=self.status == "success"
        )


class AuditHandler:
    """
    Base class for audit event handlers.

    Audit handlers are responsible for processing audit events, typically by
    storing them to a destination (file, database, log service) or performing
    actions like generating alerts.
    """

    def __init__(self, name: str, min_level: AuditLevel = AuditLevel.INFO,
                 formatter: Optional[Callable[[AuditEvent], str]] = None):
        """
        Initialize the audit handler.

        Args:
            name: Name of this handler
            min_level: Minimum audit level to process
            formatter: Optional formatter function to convert events to strings
        """
        self.name = name
        self.min_level = min_level
        self.formatter = formatter
        self.enabled = True

    def handle(self, event: AuditEvent) -> bool:
        """
        Process an audit event.

        Args:
            event: The audit event to process

        Returns:
            bool: Whether the event was successfully handled
        """
        if not self.enabled:
            return False

        if event.level.value < self.min_level.value:
            return False

        return self._handle_event(event)

    def _handle_event(self, event: AuditEvent) -> bool:
        """
        Internal method to handle the event. Must be implemented by subclasses.

        Args:
            event: The audit event to process

        Returns:
            bool: Whether the event was successfully handled
        """
        raise NotImplementedError("Subclasses must implement _handle_event")

    def format_event(self, event: AuditEvent) -> str:
        """
        Format an audit event as a string.

        Args:
            event: The audit event to format

        Returns:
            str: The formatted event
        """
        if self.formatter:
            return self.formatter(event)

        # Default format is JSON
        return event.to_json()

    def close(self) -> None:
        """Close the handler, releasing any resources."""
        pass


class AuditLogger:
    """
    Central audit logging facility.

    This class is the main interface for recording audit events throughout
    the application. It manages a collection of handlers that process events
    in different ways (e.g., writing to files, databases, or sending alerts).
    It also supports event listeners for real-time integration with other systems.
    """

    _instance = None

    @classmethod
    def get_instance(cls) -> 'AuditLogger':
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        """Initialize the audit logger."""
        self.handlers: List[AuditHandler] = []
        self.enabled = True
        self.default_user = None
        self.default_application = "ipfs_datasets_py"
        self.session_id = str(uuid.uuid4())
        self.client_ip = None
        self.min_level = AuditLevel.INFO
        self.included_categories: Set[AuditCategory] = set()  # Empty means include all
        self.excluded_categories: Set[AuditCategory] = set()
        self._lock = threading.RLock()
        self._thread_local = threading.local()

        # Event listeners for integration with other systems
        # Map from category to list of listener functions
        self.event_listeners: Dict[Optional[AuditCategory], List[Callable[[AuditEvent], None]]] = {
            None: []  # Global listeners for all categories
        }

        # Try to determine client IP
        try:
            hostname = socket.gethostname()
            self.client_ip = socket.gethostbyname(hostname)
        except:
            self.client_ip = "127.0.0.1"

    def add_handler(self, handler: AuditHandler) -> None:
        """
        Add a handler to the audit logger.

        Args:
            handler: The handler to add
        """
        with self._lock:
            self.handlers.append(handler)

    def remove_handler(self, handler_name: str) -> bool:
        """
        Remove a handler by name.

        Args:
            handler_name: Name of the handler to remove

        Returns:
            bool: Whether a handler was removed
        """
        with self._lock:
            for i, handler in enumerate(self.handlers):
                if handler.name == handler_name:
                    handler.close()
                    self.handlers.pop(i)
                    return True
            return False

    def set_context(self, user: Optional[str] = None,
                  session_id: Optional[str] = None,
                  client_ip: Optional[str] = None,
                  application: Optional[str] = None) -> None:
        """
        Set context for future audit events.

        Thread-local context that will be included in all audit events
        logged from the current thread.

        Args:
            user: User identifier
            session_id: Session identifier
            client_ip: Client IP address
            application: Application name
        """
        if not hasattr(self._thread_local, 'context'):
            self._thread_local.context = {}

        if user is not None:
            self._thread_local.context['user'] = user
        if session_id is not None:
            self._thread_local.context['session_id'] = session_id
        if client_ip is not None:
            self._thread_local.context['client_ip'] = client_ip
        if application is not None:
            self._thread_local.context['application'] = application

    def clear_context(self) -> None:
        """Clear the thread-local context."""
        if hasattr(self._thread_local, 'context'):
            delattr(self._thread_local, 'context')

    def _apply_context(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply thread-local context to event data."""
        result = event_data.copy()

        # Apply global defaults
        if 'user' not in result or result['user'] is None:
            result['user'] = self.default_user
        if 'application' not in result or result['application'] is None:
            result['application'] = self.default_application
        if 'session_id' not in result or result['session_id'] is None:
            result['session_id'] = self.session_id
        if 'client_ip' not in result or result['client_ip'] is None:
            result['client_ip'] = self.client_ip

        # Apply thread-local context if available
        if hasattr(self._thread_local, 'context'):
            for key, value in self._thread_local.context.items():
                if key not in result or result[key] is None:
                    result[key] = value

        return result

    def log(self, level: AuditLevel, category: AuditCategory, action: str,
           user: Optional[str] = None, resource_id: Optional[str] = None,
           resource_type: Optional[str] = None, status: str = "success",
           details: Optional[Dict[str, Any]] = None,
           client_ip: Optional[str] = None, session_id: Optional[str] = None,
           **kwargs) -> Optional[str]:
        """
        Log an audit event.

        This is the main method for recording audit events through the audit logger.

        Args:
            level: Severity level of the event
            category: Category of the event
            action: Action being performed
            user: User performing the action
            resource_id: ID of the resource being acted upon
            resource_type: Type of the resource being acted upon
            status: Status of the action ("success", "failure", etc.)
            details: Additional details about the event
            client_ip: IP address of the client
            session_id: Session ID
            **kwargs: Additional fields for the audit event

        Returns:
            str: The ID of the recorded event, or None if not recorded
        """
        if not self.enabled:
            return None

        if level.value < self.min_level.value:
            return None

        if self.included_categories and category not in self.included_categories:
            return None

        if category in self.excluded_categories:
            return None

        # Create base event data
        event_data = {
            'event_id': kwargs.get('event_id', str(uuid.uuid4())),
            'timestamp': kwargs.get('timestamp', datetime.datetime.utcnow().isoformat() + 'Z'),
            'level': level,
            'category': category,
            'action': action,
            'user': user,
            'resource_id': resource_id,
            'resource_type': resource_type,
            'status': status,
            'details': details or {},
            'client_ip': client_ip,
            'session_id': session_id,
            # Add any additional fields from kwargs
            **{k: v for k, v in kwargs.items() if k not in [
                'event_id', 'timestamp', 'level', 'category', 'action',
                'user', 'resource_id', 'resource_type', 'status', 'details',
                'client_ip', 'session_id'
            ]}
        }

        # Apply context
        event_data = self._apply_context(event_data)

        # Create the audit event
        event = AuditEvent(**event_data)

        # Get stack frame information
        stack = traceback.extract_stack()
        # Skip the current frame and AuditLogger methods
        frame = None
        for f in reversed(stack[:-1]):
            if 'audit_logger.py' not in f.filename:
                frame = f
                break

        if frame:
            event.source_module = os.path.basename(frame.filename)
            event.source_function = frame.name

        # Dispatch to handlers
        with self._lock:
            for handler in self.handlers:
                try:
                    handler.handle(event)
                except Exception as e:
                    logging.error(f"Error in audit handler {handler.name}: {str(e)}")

            # Notify event listeners
            self.notify_listeners(event)

        return event.event_id

    # Convenience methods for different audit levels

    def debug(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
        """Log a DEBUG level audit event."""
        return self.log(AuditLevel.DEBUG, category, action, **kwargs)

    def info(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
        """Log an INFO level audit event."""
        return self.log(AuditLevel.INFO, category, action, **kwargs)

    def notice(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
        """Log a NOTICE level audit event."""
        return self.log(AuditLevel.NOTICE, category, action, **kwargs)

    def warning(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
        """Log a WARNING level audit event."""
        return self.log(AuditLevel.WARNING, category, action, **kwargs)

    def error(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
        """Log an ERROR level audit event."""
        return self.log(AuditLevel.ERROR, category, action, **kwargs)

    def critical(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
        """Log a CRITICAL level audit event."""
        return self.log(AuditLevel.CRITICAL, category, action, **kwargs)

    def emergency(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
        """Log an EMERGENCY level audit event."""
        return self.log(AuditLevel.EMERGENCY, category, action, **kwargs)

    # Convenience methods for different categories

    def auth(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
        """Log an authentication event."""
        return self.log(level, AuditCategory.AUTHENTICATION, action, **kwargs)

    def authz(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
        """Log an authorization event."""
        return self.log(level, AuditCategory.AUTHORIZATION, action, **kwargs)

    def data_access(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
        """Log a data access event."""
        return self.log(level, AuditCategory.DATA_ACCESS, action, **kwargs)

    def data_modify(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
        """Log a data modification event."""
        return self.log(level, AuditCategory.DATA_MODIFICATION, action, **kwargs)

    def system(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
        """Log a system event."""
        return self.log(level, AuditCategory.SYSTEM, action, **kwargs)

    def security(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
        """Log a security event."""
        return self.log(level, AuditCategory.SECURITY, action, **kwargs)

    def compliance(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
        """Log a compliance event."""
        return self.log(level, AuditCategory.COMPLIANCE, action, **kwargs)

    def add_event_listener(self,
                     listener: Callable[[AuditEvent], None],
                     category: Optional[AuditCategory] = None) -> None:
        """
        Add an event listener for audit events.

        Event listeners are called in real-time when audit events are logged.
        They can be used to integrate with other systems like data provenance tracking.

        Args:
            listener: Callback function that takes an AuditEvent parameter
            category: Optional category to filter events (None for all categories)
        """
        with self._lock:
            if category not in self.event_listeners:
                self.event_listeners[category] = []
            self.event_listeners[category].append(listener)

    def remove_event_listener(self,
                           listener: Callable[[AuditEvent], None],
                           category: Optional[AuditCategory] = None) -> bool:
        """
        Remove an event listener.

        Args:
            listener: The listener function to remove
            category: The category the listener was registered for

        Returns:
            bool: Whether the listener was successfully removed
        """
        with self._lock:
            if category not in self.event_listeners:
                return False

            try:
                self.event_listeners[category].remove(listener)
                return True
            except ValueError:
                return False

    def notify_listeners(self, event: AuditEvent) -> None:
        """
        Notify all relevant listeners about an audit event.

        Args:
            event: The audit event to notify about
        """
        with self._lock:
            # Call global listeners (category=None)
            for listener in self.event_listeners.get(None, []):
                try:
                    listener(event)
                except Exception as e:
                    logging.error(f"Error in audit event listener: {str(e)}")

            # Call category-specific listeners
            for listener in self.event_listeners.get(event.category, []):
                try:
                    listener(event)
                except Exception as e:
                    logging.error(f"Error in audit event listener for category {event.category.name}: {str(e)}")

    def reset(self) -> None:
        """Reset the audit logger, closing all handlers and clearing listeners."""
        with self._lock:
            for handler in self.handlers:
                handler.close()
            self.handlers = []
            self.event_listeners = {None: []}

    def configure(self, config: Dict[str, Any]) -> None:
        """
        Configure the audit logger from a configuration dictionary.

        Args:
            config: Configuration dictionary
        """
        with self._lock:
            if 'enabled' in config:
                self.enabled = config['enabled']

            if 'min_level' in config:
                level_name = config['min_level']
                if isinstance(level_name, str):
                    self.min_level = AuditLevel[level_name]
                else:
                    self.min_level = level_name

            if 'default_user' in config:
                self.default_user = config['default_user']

            if 'default_application' in config:
                self.default_application = config['default_application']

            if 'included_categories' in config:
                self.included_categories = set()
                for cat in config['included_categories']:
                    if isinstance(cat, str):
                        self.included_categories.add(AuditCategory[cat])
                    else:
                        self.included_categories.add(cat)

            if 'excluded_categories' in config:
                self.excluded_categories = set()
                for cat in config['excluded_categories']:
                    if isinstance(cat, str):
                        self.excluded_categories.add(AuditCategory[cat])
                    else:
                        self.excluded_categories.add(cat)


# Initialize global audit logger instance
def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    return AuditLogger.get_instance()


# Global instance
audit_logger = get_audit_logger()
