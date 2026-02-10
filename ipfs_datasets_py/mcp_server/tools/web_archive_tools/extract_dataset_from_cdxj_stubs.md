# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/web_archive_tools/extract_dataset_from_cdxj.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 01:10:14

## extract_dataset_from_cdxj

```python
async def extract_dataset_from_cdxj(cdxj_path: str, output_format: Literal['arrow', 'huggingface', 'dict'] = "arrow") -> Dict[str, Any]:
    """
    Extract a dataset from a CDXJ index file.

Args:
    cdxj_path: Path to the CDXJ file
    output_format: Output format - "arrow", "huggingface", or "dict"

Returns:
    Dict containing:
        - status: "success" or "error"
        - dataset: The extracted dataset (format depends on output_format)
        - format: The format of the returned dataset
        - error: Error message (if failed)
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
