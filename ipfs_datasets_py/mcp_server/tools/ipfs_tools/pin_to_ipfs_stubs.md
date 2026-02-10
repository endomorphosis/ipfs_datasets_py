# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/ipfs_tools/pin_to_ipfs.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 01:10:14

## pin_to_ipfs

```python
async def pin_to_ipfs(content_source: Union[str, Dict[str, Any]], recursive: bool = True, wrap_with_directory: bool = False, hash_algo: str = "sha2-256") -> Dict[str, Any]:
    """
    Pin a file, directory, or data to IPFS.

Args:
    content_source: Path to the file/directory to pin, or data dict to pin
    recursive: Whether to add the directory recursively
    wrap_with_directory: Whether to wrap the file(s) in a directory
    hash_algo: The hash algorithm to use

Returns:
    Dict containing information about the pinned content
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
