# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/audit/handlers.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:14:36

## AlertingAuditHandler

```python
class AlertingAuditHandler(AuditHandler):
    """
    Handler that triggers alerts for security-relevant audit events.

Features:
- Configurable alert thresholds and rules
- Multiple alert destinations (email, webhook, etc.)
- Rate limiting to prevent alert storms
- Alert aggregation for related events
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ElasticsearchAuditHandler

```python
class ElasticsearchAuditHandler(AuditHandler):
    """
    Handler that sends audit events to Elasticsearch.

Features:
- Stores events in Elasticsearch for powerful search and visualization
- Support for index naming based on date patterns
- Configurable connection parameters and authentication
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FileAuditHandler

```python
class FileAuditHandler(AuditHandler):
    """
    Handler that writes audit events to a file.

Features:
- Configurable file path with optional rotation
- Support for text and binary (compressed) files
- Customizable formatting of events
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## JSONAuditHandler

```python
class JSONAuditHandler(AuditHandler):
    """
    Handler that writes audit events as JSON objects.

Features:
- One JSON object per line (JSON Lines format)
- Optional pretty printing for human readability
- Support for writing to file or any file-like object
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SyslogAuditHandler

```python
class SyslogAuditHandler(AuditHandler):
    """
    Handler that sends audit events to syslog.

Features:
- Maps audit levels to syslog priorities
- Configurable facility and identity
- Works on Unix-like systems with syslog support
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, name: str, file_path: str, min_level: AuditLevel = AuditLevel.INFO, formatter: Optional[Callable[[AuditEvent], str]] = None, rotate_size_mb: Optional[float] = None, rotate_count: int = 5, use_compression: bool = False, mode: str = "a", encoding: str = "utf-8"):
    """
    Initialize the file audit handler.

Args:
    name: Name of this handler
    file_path: Path to the audit log file
    min_level: Minimum audit level to process
    formatter: Optional formatter function to convert events to strings
    rotate_size_mb: Maximum file size in MB before rotation (None for no rotation)
    rotate_count: Maximum number of rotated files to keep
    use_compression: Whether to compress rotated files
    mode: File open mode ('a' for append, 'w' for write)
    encoding: File encoding for text files
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileAuditHandler

## __init__

```python
def __init__(self, name: str, file_path: Optional[str] = None, file_obj: Optional[TextIO] = None, min_level: AuditLevel = AuditLevel.INFO, pretty: bool = False, rotate_size_mb: Optional[float] = None, rotate_count: int = 5, use_compression: bool = False):
    """
    Initialize the JSON audit handler.

Args:
    name: Name of this handler
    file_path: Path to the audit log file (mutually exclusive with file_obj)
    file_obj: File-like object to write to (mutually exclusive with file_path)
    min_level: Minimum audit level to process
    pretty: Whether to pretty-print JSON for human readability
    rotate_size_mb: Maximum file size in MB before rotation (None for no rotation)
    rotate_count: Maximum number of rotated files to keep
    use_compression: Whether to compress rotated files
    """
```
* **Async:** False
* **Method:** True
* **Class:** JSONAuditHandler

## __init__

```python
def __init__(self, name: str, min_level: AuditLevel = AuditLevel.INFO, formatter: Optional[Callable[[AuditEvent], str]] = None, facility: int = None, identity: str = "ipfs_datasets_audit"):
    """
    Initialize the syslog audit handler.

Args:
    name: Name of this handler
    min_level: Minimum audit level to process
    formatter: Optional formatter function to convert events to strings
    facility: Syslog facility to use
    identity: Identity string for syslog
    """
```
* **Async:** False
* **Method:** True
* **Class:** SyslogAuditHandler

## __init__

```python
def __init__(self, name: str, hosts: List[str], min_level: AuditLevel = AuditLevel.INFO, index_pattern: str = "audit-logs-{date}", username: Optional[str] = None, password: Optional[str] = None, api_key: Optional[Union[str, tuple]] = None, bulk_size: int = 100, bulk_timeout: float = 5.0, **kwargs):
    """
    Initialize the Elasticsearch audit handler.

Args:
    name: Name of this handler
    hosts: List of Elasticsearch hosts
    min_level: Minimum audit level to process
    index_pattern: Index name pattern with optional {date} placeholder
    username: Optional username for authentication
    password: Optional password for authentication
    api_key: Optional API key for authentication
    bulk_size: Number of events to batch before sending
    bulk_timeout: Maximum time to wait before sending incomplete batch
    **kwargs: Additional arguments for Elasticsearch client
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElasticsearchAuditHandler

## __init__

```python
def __init__(self, name: str, min_level: AuditLevel = AuditLevel.WARNING, alert_handlers: Optional[List[Callable[[AuditEvent], None]]] = None, rate_limit_seconds: float = 60.0, aggregation_window_seconds: float = 300.0, alert_rules: Optional[List[Dict[str, Any]]] = None):
    """
    Initialize the alerting audit handler.

Args:
    name: Name of this handler
    min_level: Minimum audit level to trigger alerts
    alert_handlers: List of handler functions for sending alerts
    rate_limit_seconds: Minimum time between alerts of the same type
    aggregation_window_seconds: Time window for aggregating similar alerts
    alert_rules: List of rules for determining when to alert
    """
```
* **Async:** False
* **Method:** True
* **Class:** AlertingAuditHandler

## _check_rate_limit

```python
def _check_rate_limit(self, alert_type: str) -> bool:
    """
    Check if an alert of the given type is rate-limited.

Args:
    alert_type: Type of alert to check

Returns:
    bool: Whether the alert is allowed (not rate-limited)
    """
```
* **Async:** False
* **Method:** True
* **Class:** AlertingAuditHandler

## _connect

```python
def _connect(self) -> None:
    """
    Connect to Elasticsearch.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElasticsearchAuditHandler

## _flush_buffer

```python
def _flush_buffer(self) -> bool:
    """
    Flush the event buffer to Elasticsearch.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElasticsearchAuditHandler

## _get_index_name

```python
def _get_index_name(self) -> str:
    """
    Get the current index name based on pattern.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElasticsearchAuditHandler

## _handle_event

```python
def _handle_event(self, event: AuditEvent) -> bool:
    """
    Write the audit event to file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileAuditHandler

## _handle_event

```python
def _handle_event(self, event: AuditEvent) -> bool:
    """
    Write the audit event as JSON.
    """
```
* **Async:** False
* **Method:** True
* **Class:** JSONAuditHandler

## _handle_event

```python
def _handle_event(self, event: AuditEvent) -> bool:
    """
    Send the audit event to syslog.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SyslogAuditHandler

## _handle_event

```python
def _handle_event(self, event: AuditEvent) -> bool:
    """
    Send the audit event to Elasticsearch.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElasticsearchAuditHandler

## _handle_event

```python
def _handle_event(self, event: AuditEvent) -> bool:
    """
    Process the audit event and send alerts if needed.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AlertingAuditHandler

## _match_rule

```python
def _match_rule(self, event: AuditEvent, rule: Dict[str, Any]) -> bool:
    """
    Check if an event matches a rule.

Args:
    event: The audit event to check
    rule: Rule specification

Returns:
    bool: Whether the event matches the rule
    """
```
* **Async:** False
* **Method:** True
* **Class:** AlertingAuditHandler

## _open_file

```python
def _open_file(self) -> None:
    """
    Open the audit log file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileAuditHandler

## _open_file

```python
def _open_file(self) -> None:
    """
    Open the audit log file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** JSONAuditHandler

## _process_aggregation

```python
def _process_aggregation(self, event: AuditEvent) -> List[AuditEvent]:
    """
    Process event aggregation according to rules.

Args:
    event: The audit event to process

Returns:
    List[AuditEvent]: Events that should trigger alerts
    """
```
* **Async:** False
* **Method:** True
* **Class:** AlertingAuditHandler

## _rotate_file

```python
def _rotate_file(self) -> None:
    """
    Rotate the audit log file if it exceeds the maximum size.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileAuditHandler

## _rotate_file

```python
def _rotate_file(self) -> None:
    """
    Rotate the audit log file if it exceeds the maximum size.
    """
```
* **Async:** False
* **Method:** True
* **Class:** JSONAuditHandler

## add_alert_handler

```python
def add_alert_handler(self, handler: Callable[[AuditEvent], None]) -> None:
    """
    Add a handler function for sending alerts.

Args:
    handler: Function that takes an AuditEvent and sends an alert
    """
```
* **Async:** False
* **Method:** True
* **Class:** AlertingAuditHandler

## add_alert_rule

```python
def add_alert_rule(self, rule: Dict[str, Any]) -> None:
    """
    Add a rule for determining when to alert.

Args:
    rule: Rule specification (e.g., {"category": "AUTHENTICATION", "action": "login_failed", "min_count": 5})
    """
```
* **Async:** False
* **Method:** True
* **Class:** AlertingAuditHandler

## close

```python
def close(self) -> None:
    """
    Close the file handler.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileAuditHandler

## close

```python
def close(self) -> None:
    """
    Close the file handler if we own it.
    """
```
* **Async:** False
* **Method:** True
* **Class:** JSONAuditHandler

## close

```python
def close(self) -> None:
    """
    Close the syslog connection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SyslogAuditHandler

## close

```python
def close(self) -> None:
    """
    Flush remaining events and close the Elasticsearch connection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElasticsearchAuditHandler

## close

```python
def close(self) -> None:
    """
    Clean up resources.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AlertingAuditHandler
