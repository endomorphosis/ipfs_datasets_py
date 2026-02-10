# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/create_warc.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 01:10:14

## create_warc

```python
async def create_warc(url: str, output_path: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create a WARC file from a URL.

Args:
    url: URL to archive
    output_path: Path for the output WARC file (optional)
    options: Options for the archiving tool (optional)
        - agent: "wget" or "squidwarc"
        - depth: crawl depth (for squidwarc)

Returns:
    Dict containing:
        - status: "success" or "error"
        - warc_path: Path to the created WARC file (if successful)
        - error: Error message (if failed)
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
