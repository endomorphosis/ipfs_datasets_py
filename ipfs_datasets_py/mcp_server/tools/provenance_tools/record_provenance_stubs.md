# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/provenance_tools/record_provenance.py'

Files last updated: 1748635923.4513795

Stub file last updated: 2025-07-07 01:10:14

## record_provenance

```python
async def record_provenance(dataset_id: str, operation: str, inputs: Optional[List[str]] = None, parameters: Optional[Dict[str, Any]] = None, description: Optional[str] = None, agent_id: Optional[str] = None, timestamp: Optional[str] = None, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Record provenance information for a dataset operation.

Args:
    dataset_id: ID of the dataset
    operation: The operation performed on the dataset
    inputs: Optional list of input dataset IDs or sources
    parameters: Optional parameters used in the operation
    description: Optional description of the operation
    agent_id: Optional ID of the agent performing the operation
    timestamp: Optional timestamp for the operation (ISO format)
    tags: Optional tags for categorizing the provenance record

Returns:
    Dict containing information about the recorded provenance
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
