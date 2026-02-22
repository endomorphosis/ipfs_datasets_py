# IPFS Tools

Core MCP tools for interacting with IPFS — pinning content, retrieving files, and working with
CAR (Content Addressable aRchive) format. These are thin wrappers around the IPFS client.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `pin_to_ipfs.py` | `pin_to_ipfs()` | Pin a file, directory, or raw content to IPFS |
| `get_from_ipfs.py` | `get_from_ipfs()` | Retrieve content from IPFS by CID |
| `ipfs_tools_claudes.py` | Multiple | Extended IPFS utilities (CID conversion, CAR packing/unpacking) |

## Usage

### Pin content to IPFS

```python
from ipfs_datasets_py.mcp_server.tools.ipfs_tools import pin_to_ipfs

# Pin a file
result = await pin_to_ipfs(
    content="/path/to/file.parquet",
    pin_name="my-dataset-v1"   # Optional label
)
# Returns: {"status": "success", "cid": "QmXxx...", "size_bytes": 12345}

# Pin raw bytes / string
result = await pin_to_ipfs(
    content='{"key": "value"}',
    content_type="json"
)
```

### Get content from IPFS

```python
from ipfs_datasets_py.mcp_server.tools.ipfs_tools import get_from_ipfs

result = await get_from_ipfs(
    cid="QmXxx...",
    output_path="/tmp/retrieved_file"  # Optional: save to disk
)
# Returns: {"status": "success", "content": "...", "cid": "QmXxx..."}
```

## Core Module

All business logic delegates to:
- `ipfs_datasets_py.ipfs_datasets` — core IPFS client
- `ipfs_datasets_py.core_operations.ipfs_pinner.IPFSPinner`

## Dependencies

**Required:**
- Standard library: `json`, `os`, `pathlib`

**Optional (graceful degradation if missing):**
- `ipfs_datasets_py` / `ipfs_kit_py` — for IPFS node operations
- `ipfshttpclient` — direct IPFS HTTP API client
- `requests` — HTTP fallback

If the IPFS daemon is not running, operations return an error with a clear message rather than crashing.

## Notes

- All CIDs are returned in CIDv1 base32 format by default
- Content larger than the configured threshold is automatically chunked
- Pinning ensures content is not garbage-collected by the local IPFS node
- Use `ipfs_cluster_tools` for cluster-wide pinning across multiple nodes

## Status

| Tool | Status |
|------|--------|
| `pin_to_ipfs` | ✅ Production ready (requires IPFS daemon) |
| `get_from_ipfs` | ✅ Production ready (requires IPFS daemon) |
