# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/provenance_tools/provenance_tools_claudes.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## ClaudesProvenanceTool

```python
class ClaudesProvenanceTool:
    """
    A tool for recording provenance migrated from claudes_toolbox-1.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## provenance_tools_claudes

```python
async def provenance_tools_claudes():
    """
    A tool for recording provenance migrated from claudes_toolbox-1.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## record

```python
def record(self, data_identifier: str, operation: str, metadata: dict) -> str:
    """
    Records provenance information for a data operation.

Args:
    data_identifier: An identifier for the data being operated on.
    operation: The operation being performed (e.g., "process", "add_to_ipfs").
    metadata: A dictionary containing additional provenance metadata.

Returns:
    A string indicating the status of the provenance recording.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ClaudesProvenanceTool
