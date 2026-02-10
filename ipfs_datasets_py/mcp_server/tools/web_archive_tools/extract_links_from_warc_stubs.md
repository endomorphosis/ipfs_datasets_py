# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/extract_links_from_warc.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 01:10:14

## extract_links_from_warc

```python
async def extract_links_from_warc(warc_path: str) -> Dict[str, Any]:
    """
    Extract links from a WARC file.

Args:
    warc_path: Path to the WARC file

Returns:
    Dict containing:
        - status: "success" or "error"
        - links: List of records with source and target URIs (if successful)
        - error: Error message (if failed)
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
