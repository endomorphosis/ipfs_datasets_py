# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/audit/audit_logger.py'

Files last updated: 1748635923.4113796

Stub file last updated: 2025-07-07 02:14:36

## AuditCategory

```python
class AuditCategory(Enum):
    """
    Categories of audit events.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AuditEvent

```python
@dataclass
class AuditEvent:
    """
    Comprehensive audit event structure capturing all relevant information.

This class defines the structure of audit events with rich metadata
for security analysis, compliance reporting, and operational monitoring.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AuditHandler

```python
class AuditHandler:
    """
    Base class for audit event handlers.

Audit handlers are responsible for processing audit events, typically by
storing them to a destination (file, database, log service) or performing
actions like generating alerts.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AuditLevel

```python
class AuditLevel(Enum):
    """
    Audit event severity levels.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AuditLogger

```python
class AuditLogger:
    """
    Central audit logging facility.

This class is the main interface for recording audit events throughout
the application. It manages a collection of handlers that process events
in different ways (e.g., writing to files, databases, or sending alerts).
It also supports event listeners for real-time integration with other systems.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, name: str, min_level: AuditLevel = AuditLevel.INFO, formatter: Optional[Callable[[AuditEvent], str]] = None):
    """
    Initialize the audit handler.

Args:
    name: Name of this handler
    min_level: Minimum audit level to process
    formatter: Optional formatter function to convert events to strings
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditHandler

## __init__

```python
def __init__(self):
    """
    Initialize the audit logger.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## __post_init__

```python
def __post_init__(self):
    """
    Initialize default values if not provided.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditEvent

## _apply_context

```python
def _apply_context(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply thread-local context to event data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## _handle_event

```python
def _handle_event(self, event: AuditEvent) -> bool:
    """
    Internal method to handle the event. Must be implemented by subclasses.

Args:
    event: The audit event to process

Returns:
    bool: Whether the event was successfully handled
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditHandler

## add_event_listener

```python
def add_event_listener(self, listener: Callable[[AuditEvent], None], category: Optional[AuditCategory] = None) -> None:
    """
    Add an event listener for audit events.

Event listeners are called in real-time when audit events are logged.
They can be used to integrate with other systems like data provenance tracking.

Args:
    listener: Callback function that takes an AuditEvent parameter
    category: Optional category to filter events (None for all categories)
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## add_handler

```python
def add_handler(self, handler: AuditHandler) -> None:
    """
    Add a handler to the audit logger.

Args:
    handler: The handler to add
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## auth

```python
def auth(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
    """
    Log an authentication event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## authz

```python
def authz(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
    """
    Log an authorization event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## clear_context

```python
def clear_context(self) -> None:
    """
    Clear the thread-local context.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## close

```python
def close(self) -> None:
    """
    Close the handler, releasing any resources.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditHandler

## compliance

```python
def compliance(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
    """
    Log a compliance event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## configure

```python
def configure(self, config: Dict[str, Any]) -> None:
    """
    Configure the audit logger from a configuration dictionary.

Args:
    config: Configuration dictionary
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## critical

```python
def critical(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
    """
    Log a CRITICAL level audit event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## data_access

```python
def data_access(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
    """
    Log a data access event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## data_modify

```python
def data_modify(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
    """
    Log a data modification event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## debug

```python
def debug(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
    """
    Log a DEBUG level audit event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## emergency

```python
def emergency(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
    """
    Log an EMERGENCY level audit event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## error

```python
def error(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
    """
    Log an ERROR level audit event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## format_event

```python
def format_event(self, event: AuditEvent) -> str:
    """
    Format an audit event as a string.

Args:
    event: The audit event to format

Returns:
    str: The formatted event
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditHandler

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "AuditEvent":
    """
    Create an AuditEvent from a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditEvent

## from_json

```python
@classmethod
def from_json(cls, json_str: str) -> "AuditEvent":
    """
    Create an AuditEvent from a JSON string.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditEvent

## from_security_audit_entry

```python
@classmethod
def from_security_audit_entry(cls, entry: Any) -> "AuditEvent":
    """
    Create an AuditEvent from a security module AuditLogEntry.

This provides backwards compatibility with existing audit entries.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditEvent

## get_audit_logger

```python
def get_audit_logger() -> AuditLogger:
    """
    Get the global audit logger instance.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_instance

```python
@classmethod
def get_instance(cls) -> "AuditLogger":
    """
    Get the singleton instance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## handle

```python
def handle(self, event: AuditEvent) -> bool:
    """
    Process an audit event.

Args:
    event: The audit event to process

Returns:
    bool: Whether the event was successfully handled
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditHandler

## info

```python
def info(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
    """
    Log an INFO level audit event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## log

```python
def log(self, level: AuditLevel, category: AuditCategory, action: str, user: Optional[str] = None, resource_id: Optional[str] = None, resource_type: Optional[str] = None, status: str = "success", details: Optional[Dict[str, Any]] = None, client_ip: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> Optional[str]:
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
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## notice

```python
def notice(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
    """
    Log a NOTICE level audit event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## notify_listeners

```python
def notify_listeners(self, event: AuditEvent) -> None:
    """
    Notify all relevant listeners about an audit event.

Args:
    event: The audit event to notify about
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## remove_event_listener

```python
def remove_event_listener(self, listener: Callable[[AuditEvent], None], category: Optional[AuditCategory] = None) -> bool:
    """
    Remove an event listener.

Args:
    listener: The listener function to remove
    category: The category the listener was registered for

Returns:
    bool: Whether the listener was successfully removed
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## remove_handler

```python
def remove_handler(self, handler_name: str) -> bool:
    """
    Remove a handler by name.

Args:
    handler_name: Name of the handler to remove

Returns:
    bool: Whether a handler was removed
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## reset

```python
def reset(self) -> None:
    """
    Reset the audit logger, closing all handlers and clearing listeners.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## security

```python
def security(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
    """
    Log a security event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## set_context

```python
def set_context(self, user: Optional[str] = None, session_id: Optional[str] = None, client_ip: Optional[str] = None, application: Optional[str] = None) -> None:
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
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## system

```python
def system(self, action: str, level: AuditLevel = AuditLevel.INFO, **kwargs) -> Optional[str]:
    """
    Log a system event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert the audit event to a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditEvent

## to_json

```python
def to_json(self, pretty = False) -> str:
    """
    Serialize the audit event to JSON.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditEvent

## to_security_audit_entry

```python
def to_security_audit_entry(self) -> Any:
    """
    Convert this AuditEvent to a security module AuditLogEntry.

This provides backwards compatibility with existing security module.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditEvent

## warning

```python
def warning(self, category: AuditCategory, action: str, **kwargs) -> Optional[str]:
    """
    Log a WARNING level audit event.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditLogger
