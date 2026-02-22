# Security Tools

MCP tools for access control and permission checking.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `check_access_permission.py` | `check_access_permission()` | Check if a user/service has permission to access a resource |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.security_tools import check_access_permission

result = await check_access_permission(
    principal="user_42",
    action="dataset.write",
    resource="legal_corpus_v2",
    context={"ip": "192.168.1.1", "session_id": "abc123"}
)
# Returns: {"allowed": True, "reason": "user has write:datasets scope", "policy": "rbac_v2"}
```

## Related

- [`auth_tools/`](../auth_tools/) — authentication, token validation, user management
- [`audit_tools/`](../audit_tools/) — recording access events for compliance

## Status

| Tool | Status |
|------|--------|
| `check_access_permission` | ✅ Production ready |
