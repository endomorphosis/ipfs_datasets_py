# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/ipfs_tools/get_from_ipfs.py'

Files last updated: 1748635923.4513795

Stub file last updated: 2025-07-07 01:10:14

## get_from_ipfs

```python
async def get_from_ipfs(cid: str, output_path: Optional[str] = None, timeout_seconds: int = 60) -> Dict[str, Any]:
    """
    Get content from IPFS by its CID.

Args:
    cid: The Content Identifier (CID) to retrieve
    output_path: Path where to save the retrieved content (if None, returns content directly)
    timeout_seconds: Timeout for the retrieval operation in seconds

Returns:
    Dict containing information about the retrieved content
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
