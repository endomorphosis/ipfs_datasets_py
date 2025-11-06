# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/extract_text_from_warc.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 01:10:14

## extract_text_from_warc

```python
async def extract_text_from_warc(warc_path: str) -> Dict[str, Any]:
    """
    Extract text content from a WARC file.

Args:
    warc_path: Path to the WARC file

Returns:
    Dict containing:
        - status: "success" or "error"
        - records: List of records with URI and text content (if successful)
        - error: Error message (if failed)
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
