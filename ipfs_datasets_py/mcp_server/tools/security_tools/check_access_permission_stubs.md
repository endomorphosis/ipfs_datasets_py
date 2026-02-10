# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/security_tools/check_access_permission.py'

Files last updated: 1748635923.4513795

Stub file last updated: 2025-07-07 01:10:14

## check_access_permission

```python
async def check_access_permission(resource_id: str, user_id: str, permission_type: str = "read", resource_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Check if a user has permission to access a resource.

Args:
    resource_id: ID of the resource to check
    user_id: ID of the user to check permissions for
    permission_type: Type of permission to check ('read', 'write', 'delete', 'share', etc.)
    resource_type: Optional type of the resource

Returns:
    Dict containing permission information
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
