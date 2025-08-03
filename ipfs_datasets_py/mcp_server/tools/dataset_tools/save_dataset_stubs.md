# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/dataset_tools/save_dataset.py'

Files last updated: 1748635923.4413795

Stub file last updated: 2025-07-07 01:10:13

## save_dataset

```python
async def save_dataset(dataset_data: Union[str, Dict[str, Any]], destination: str, format: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Save a dataset to a destination.

This tool saves datasets to local files, IPFS, or other storage systems.
It supports various output formats and validation of destination paths.

Args:
    dataset_data: The dataset to save. Can be:
                 - Dataset ID string (references a loaded dataset)
                 - Dictionary containing dataset content
                 NOTE: Must be valid dataset content, not executable code.
    destination: Destination path where to save the dataset. Can be:
                - Local file path (e.g., "/path/to/dataset.json")
                - Directory path (files will be created inside)
                - IPFS CID or path (when using IPFS storage)
                NOTE: Should not be an executable file path.
    format: Output format for the dataset. Supported formats:
           - "json": JSON format (default)
           - "csv": Comma-separated values
           - "parquet": Apache Parquet format
           - "arrow": Apache Arrow format
           - "car": IPLD CAR format for IPFS
    options: Additional options for saving (compression, metadata, etc.)

Returns:
    Dict containing:
    - status: "success" or "error"
    - dataset_id: Identifier of the saved dataset
    - destination: Where the dataset was saved
    - format: Format used for saving
    - size: Size information about the saved dataset
    - message: Error message if status is "error"

Raises:
    ValueError: If destination is invalid or dataset_data is malformed
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
