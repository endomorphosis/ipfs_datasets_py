# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py'

Files last updated: 1751504011.1471517

Stub file last updated: 2025-07-07 01:10:13

## load_dataset

```python
async def load_dataset(source: str, format: Optional[str] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Load a dataset from a source.

This tool loads datasets from Hugging Face Hub, local directories, or files.
It supports various dataset formats like JSON, CSV, Parquet, and others.

Args:
    source: Source identifier of the dataset. Can be:
            - Hugging Face dataset name (e.g., "squad", "glue/mnli")
            - Local directory path containing dataset files
            - Local file path (JSON, CSV, Parquet, etc.)
            - URL to a dataset file
            NOTE: Python (.py) files are not valid dataset sources.
    format: Format of the dataset. Supported formats: json, csv, parquet, text, etc.
            If not provided, format will be auto-detected.
    options: Additional options for loading the dataset (split, streaming, etc.)

Returns:
    Dict containing:
    - status: "success" or "error"
    - dataset_id: Identifier for the loaded dataset
    - metadata: Dataset metadata including description and features
    - summary: Dataset summary with record count, schema, source, and format
    - message: Error message if status is "error"

Raises:
    ValueError: If source is a Python file or invalid format
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
