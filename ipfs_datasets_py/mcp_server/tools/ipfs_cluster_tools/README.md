# IPFS Cluster Tools

MCP tools for IPFS cluster coordination: pinning content across multiple nodes, monitoring
pin status, and managing replication policies.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `enhanced_ipfs_cluster_tools.py` | `cluster_pin()`, `cluster_unpin()`, `cluster_status()`, `cluster_sync()`, `cluster_recover()`, `list_cluster_peers()` | Pin/unpin across cluster, sync status, recover failed pins, list peers |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.ipfs_cluster_tools import (
    cluster_pin, cluster_status, list_cluster_peers
)

# Pin content cluster-wide with replication factor
result = await cluster_pin(
    cid="QmXxx...",
    replication_factor=3,    # -1 for all nodes
    name="my-dataset-v1"
)

# Check pin status across all nodes
status = await cluster_status(cid="QmXxx...")
# Returns: {"cid": "...", "status": "pinned", "peers": [{"id": "...", "status": "pinned"}]}

# List cluster peers
peers = await list_cluster_peers()
```

## Dependencies

- `ipfs_kit_py` — IPFS cluster client
- IPFS cluster daemon running and accessible

## Notes

For single-node pinning, use [`ipfs_tools/`](../ipfs_tools/) instead.

## Status

| Tool | Status |
|------|--------|
| `enhanced_ipfs_cluster_tools` | ✅ Production ready (requires IPFS cluster) |
