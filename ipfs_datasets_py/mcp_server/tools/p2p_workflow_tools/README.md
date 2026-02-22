# P2P Workflow Tools

MCP tools for submitting and monitoring peer-to-peer workflow execution.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `p2p_workflow_tools.py` | `submit_p2p_workflow()`, `get_p2p_workflow_status()`, `list_p2p_workflows()`, `cancel_p2p_workflow()` | Submit workflows to P2P network, track execution, cancel |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.p2p_workflow_tools import (
    submit_p2p_workflow, get_p2p_workflow_status
)

# Submit a workflow to the P2P network
result = await submit_p2p_workflow(
    workflow_type="distributed_embedding",
    params={
        "dataset": "legal_corpus",
        "model": "all-MiniLM-L6-v2",
        "shard_count": 8
    },
    replication=2               # Run on 2 peers for redundancy
)
workflow_id = result["workflow_id"]

# Track execution
status = await get_p2p_workflow_status(workflow_id=workflow_id)
# Returns: {"status": "running", "progress": 0.6, "completed_shards": 5, "total_shards": 8}
```

## Related

- [`p2p_tools/`](../p2p_tools/) — P2P service status and peer management
- [`mcplusplus/`](../mcplusplus/) — underlying P2P engine modules
- [`workflow_tools/`](../workflow_tools/) — local (non-P2P) workflow orchestration

## Status

| Tool | Status |
|------|--------|
| `p2p_workflow_tools` | ✅ Production ready |
