# MCP++ (mcplusplus)

The MCP++ directory contains the three engine modules for the distributed peer-to-peer extension
of the MCP server: task queue, peer management, and workflow scheduling. These engines contain
business logic extracted from the original monolithic MCP++ tool files.

## Files

| File | Class | Description |
|------|-------|-------------|
| `taskqueue_engine.py` | `TaskQueueEngine` | P2P task queue: submit, poll, cancel, route tasks across peers |
| `peer_engine.py` | `PeerEngine` | P2P peer management: discovery, health, messaging, peer lists |
| `workflow_engine.py` | `WorkflowEngine` | P2P workflow scheduling: submit workflows, monitor execution, collect results |

> **Note:** These are engine modules, not MCP tool wrappers. MCP tool wrappers that use these
> engines are located in [`../p2p_tools/`](../p2p_tools/) and [`../p2p_workflow_tools/`](../p2p_workflow_tools/).

## Architecture

```
┌─────────────────────────────┐
│   p2p_tools/ (MCP wrappers) │
└─────────────┬───────────────┘
              │ imports
              ▼
┌─────────────────────────────┐
│   mcplusplus/               │
│   ├── taskqueue_engine.py   │◄─── Core task queue logic
│   ├── peer_engine.py        │◄─── Core peer management
│   └── workflow_engine.py    │◄─── Core workflow scheduling
└─────────────────────────────┘
              │ uses
              ▼
┌─────────────────────────────┐
│   ipfs_datasets_py p2p      │
│   (libp2p, accelerate_py)   │
└─────────────────────────────┘
```

## Usage

The engines are designed to be imported directly (outside MCP) for testing and CLI use:

```python
from ipfs_datasets_py.mcp_server.tools.mcplusplus.taskqueue_engine import TaskQueueEngine
from ipfs_datasets_py.mcp_server.tools.mcplusplus.peer_engine import PeerEngine

# Direct engine usage
engine = TaskQueueEngine()
task_id = await engine.submit_task(
    task_type="embedding_generation",
    params={"dataset": "my_corpus"},
    target_peer="peer_abc123"
)

# Check task status
status = await engine.poll_task(task_id)
```

## Related

- [`../p2p_tools/`](../p2p_tools/) — MCP tool wrappers for P2P operations
- [`../p2p_workflow_tools/`](../p2p_workflow_tools/) — MCP tool wrappers for P2P workflow scheduling

## Status

| Engine | Status |
|--------|--------|
| `TaskQueueEngine` | ✅ Production ready |
| `PeerEngine` | ✅ Production ready |
| `WorkflowEngine` | ✅ Production ready |
