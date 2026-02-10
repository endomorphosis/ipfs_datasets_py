# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/audit_tools/record_audit_event.py'

Files last updated: 1751408933.6764565

Stub file last updated: 2025-07-07 01:10:13

## record_audit_event

```python
async def record_audit_event(action: str, resource_id: Optional[str] = None, resource_type: Optional[str] = None, user_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None, source_ip: Optional[str] = None, severity: str = "info", tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Record an audit event for security, compliance, and operations tracking.

Args:
    action: The action being audited (e.g., 'dataset.access', 'user.login')
    resource_id: Optional ID of the resource being acted upon
    resource_type: Optional type of the resource being acted upon
    user_id: Optional ID of the user performing the action
    details: Optional additional details about the event
    source_ip: Optional source IP address
    severity: Severity level ('info', 'warning', 'error', 'critical')
    tags: Optional tags for categorizing the event

Returns:
    Dict containing information about the recorded audit event
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
