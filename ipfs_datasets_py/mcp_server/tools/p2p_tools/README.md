# P2P Tools

MCP tools for peer-to-peer operations: TaskQueue/cache status, local P2P service management,
and workflow scheduling via the `ipfs_accelerate_py` P2P stack.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `p2p_tools.py` | `p2p_status()`, `p2p_list_peers()`, `p2p_task_status()`, `p2p_cache_status()` | Status and local operations for the in-process libp2p TaskQueue/cache |
| `workflow_scheduler_tools.py` | `schedule_workflow()`, `assign_workflow()`, `get_workflow_assignment()` | Deterministic workflow scheduling via `ipfs_accelerate_py.p2p_workflow_scheduler` |

## Usage

### P2P status

```python
from ipfs_datasets_py.mcp_server.tools.p2p_tools import p2p_status, p2p_list_peers

# Check P2P service status
status = await p2p_status()
# Returns: {"enabled": True, "peer_id": "12D3Koo...", "connected_peers": 5}

# List connected peers
peers = await p2p_list_peers()
# Returns: {"peers": [{"id": "...", "addr": "...", "latency_ms": 12}]}
```

### Workflow scheduling

```python
from ipfs_datasets_py.mcp_server.tools.p2p_tools import schedule_workflow

result = await schedule_workflow(
    workflow_id="embed_legal_corpus",
    params={"dataset": "legal_v2", "model": "all-MiniLM-L6-v2"},
    strategy="round_robin"      # "round_robin" | "least_loaded" | "sticky"
)
# Returns: {"workflow_id": "...", "assigned_peer": "12D3Koo...", "status": "queued"}
```

## Notes

- Tools are safe to register even when the P2P service is disabled; they return informative
  errors rather than crashing
- See [`mcplusplus/`](../mcplusplus/) for the underlying P2P engine modules
- See [`p2p_workflow_tools/`](../p2p_workflow_tools/) for P2P workflow submission tools

## Status

| Tool | Status |
|------|--------|
| `p2p_tools` | ✅ Production ready (safe when P2P disabled) |
| `workflow_scheduler_tools` | ✅ Production ready |
