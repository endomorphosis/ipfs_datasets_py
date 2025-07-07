# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/dataset_tools/process_dataset.py'

Files last updated: 1751504011.1471517

Stub file last updated: 2025-07-07 01:10:13

## process_dataset

```python
async def process_dataset(dataset_source: Union[str, dict, Any], operations: List[Dict[str, Any]], output_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Process a dataset with a series of operations.

This tool applies transformations, filters, and other operations to datasets.
It supports various dataset input types and operation chains.

Args:
    dataset_source: The dataset to process. Can be:
                   - Dataset ID string (references a loaded dataset)
                   - Dictionary containing dataset data
                   - Dataset object (HuggingFace Dataset)
                   NOTE: Must contain valid data, not executable code.
    operations: List of operation dictionaries. Each operation should have:
               - "type": Operation type ("filter", "map", "select", "sort", etc.)
               - Additional parameters specific to the operation type
               Examples:
               [{"type": "filter", "column": "text", "condition": "length > 100"},
                {"type": "select", "columns": ["id", "text"]},
                {"type": "map", "function": "lambda x: x.upper()", "column": "text"}]
    output_id: Optional ID for the resulting dataset (used for naming/reference)

Returns:
    Dict containing:
    - status: "success" or "error"
    - dataset_id: ID of the processed dataset
    - operations_applied: Number of operations successfully applied
    - summary: Information about record counts and changes
    - message: Error message if status is "error"

Raises:
    ValueError: If dataset_source is invalid or operations are malformed
    TypeError: If operation parameters are of wrong type
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
