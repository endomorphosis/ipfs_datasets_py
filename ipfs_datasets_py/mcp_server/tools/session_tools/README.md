# Session Tools

MCP tools for user session lifecycle management: creation, validation, listing, cleanup,
and enhanced session state management.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `session_engine.py` | `SessionEngine` / `MockSessionManager` | Business logic for session management (not MCP-facing) |
| `session_tools.py` | `create_session()`, `validate_session()`, `list_sessions()`, `terminate_session()` | Session CRUD operations |
| `enhanced_session_tools.py` | `create_session_with_context()`, `update_session_state()`, `get_session_stats()`, … | Enhanced session management with context, state persistence, statistics |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.session_tools import (
    create_session, validate_session, list_sessions
)

# Create a session
session = await create_session(
    user_id="user_42",
    metadata={"client": "python-sdk", "ip": "10.0.0.1"},
    ttl_seconds=3600
)
session_id = session["session_id"]

# Validate an existing session
validation = await validate_session(session_id=session_id)
# Returns: {"valid": True, "user_id": "user_42", "expires_at": "..."}

# List all active sessions
sessions = await list_sessions(user_id="user_42", status="active")
```

### Enhanced session state

```python
from ipfs_datasets_py.mcp_server.tools.session_tools import (
    create_session_with_context, update_session_state
)

session = await create_session_with_context(
    user_id="user_42",
    context={"dataset": "legal_corpus", "current_query": "contract law"}
)

await update_session_state(
    session_id=session["session_id"],
    state={"last_result_count": 42, "current_page": 2}
)
```

## Core Module

- `session_engine.SessionEngine` — session business logic and `MockSessionManager` for tests

## Status

| Tool | Status |
|------|--------|
| `session_tools` | ✅ Production ready |
| `enhanced_session_tools` | ✅ Production ready |
