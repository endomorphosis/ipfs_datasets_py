# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/index_warc.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 01:10:14

## index_warc

```python
async def index_warc(warc_path: str, output_path: Optional[str] = None, encryption_key: Optional[str] = None) -> Dict[str, str]:
    """
    Index a WARC file to IPFS using IPWB.

Args:
    warc_path: Path to the WARC file
    output_path: Path for the output CDXJ file (optional)
    encryption_key: Key for encrypting the archive (optional)

Returns:
    Dict containing:
        - status: "success" or "error"
        - cdxj_path: Path to the created CDXJ file (if successful)
        - error: Error message (if failed)
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
