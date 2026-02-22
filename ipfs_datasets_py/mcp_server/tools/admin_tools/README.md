# Admin Tools

MCP tools for server administration, endpoint management, and system configuration.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `admin_tools.py` | `manage_endpoints()`, `system_maintenance()`, `configure_system()`, `system_health()`, `system_status()` | Lightweight mock implementations for local testing |
| `enhanced_admin_tools.py` | `list_registered_tools()`, `reload_tools()`, `get_system_info()`, `manage_users()`, … | Production admin operations: tool registry management, user management, system configuration |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.admin_tools import (
    system_health, system_status, manage_endpoints
)

# System health snapshot
health = await system_health()
# Returns: {"status": "healthy", "uptime_seconds": 3600, "memory_mb": 512, ...}

# List and manage endpoints
result = await manage_endpoints(action="list")
# Returns: {"endpoints": [{"name": "...", "status": "active"}]}

# System maintenance (e.g. clear caches)
result = await system_maintenance(action="clear_caches")
```

## Core Module

- `ipfs_datasets_py.mcp_server` — server registry and configuration

## Status

| Tool | Status |
|------|--------|
| `admin_tools` | ✅ Production ready (mock implementations for testing) |
| `enhanced_admin_tools` | ✅ Production ready |
