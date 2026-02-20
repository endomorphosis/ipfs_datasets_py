# Auth Tools

MCP tools for authentication, authorisation, token management, and user administration.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `auth_tools.py` | `validate_token()`, `refresh_token()`, `create_session()`, `check_permission()` | JWT validation, token refresh, session creation, RBAC checks |
| `enhanced_auth_tools.py` | `create_user()`, `list_users()`, `update_user_roles()`, `revoke_token()`, … | Full user management: create/list/update users, multi-factor, token revocation |

## Usage

### Validate a token

```python
from ipfs_datasets_py.mcp_server.tools.auth_tools import validate_token

result = await validate_token(
    token="eyJhbGciOiJIUzI1NiIs...",
    required_scopes=["read:datasets", "write:ipfs"]
)
# Returns: {"valid": True, "user_id": "user_42", "scopes": [...], "expires_at": "..."}
```

### Check permission

```python
from ipfs_datasets_py.mcp_server.tools.auth_tools import check_permission

result = await check_permission(
    user_id="user_42",
    action="dataset.upload",
    resource="my_dataset"
)
# Returns: {"allowed": True, "reason": "user has write:datasets scope"}
```

### User management

```python
from ipfs_datasets_py.mcp_server.tools.auth_tools import create_user, list_users

new_user = await create_user(
    username="alice",
    email="alice@example.com",
    roles=["contributor"]
)

users = await list_users(role="admin")
```

## Core Module

- `ipfs_datasets_py.mcp_server.fastapi_service` — JWT configuration and validation

## Dependencies

- `jose` / `python-jwt` — JWT encoding/decoding (optional; falls back to mock in testing)

## Status

| Tool | Status |
|------|--------|
| `auth_tools` | ✅ Production ready |
| `enhanced_auth_tools` | ✅ Production ready |
