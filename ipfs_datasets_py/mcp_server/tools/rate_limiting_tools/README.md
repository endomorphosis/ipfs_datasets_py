# Rate Limiting Tools

MCP tools for API rate limiting: token bucket, sliding window, and per-client quota enforcement.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `rate_limiting_tools.py` | `check_rate_limit()`, `consume_token()`, `get_quota_status()`, `reset_quota()`, `set_rate_limit()` | Token bucket operations, quota status, per-client rate limit configuration |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools import (
    check_rate_limit, consume_token, get_quota_status
)

# Check if a client is within rate limit
result = await check_rate_limit(
    client_id="user_42",
    action="dataset.download",
    tokens_required=1
)
# Returns: {"allowed": True, "remaining_tokens": 47, "reset_at": "2026-02-20T10:00:00Z"}

# Consume a token
await consume_token(client_id="user_42", action="api.call", tokens=1)

# Get quota status for a client
status = await get_quota_status(client_id="user_42")
# Returns: {"used": 53, "limit": 100, "window": "1h", "reset_at": "..."}
```

## Status

| Tool | Status |
|------|--------|
| `rate_limiting_tools` | ✅ Production ready |
