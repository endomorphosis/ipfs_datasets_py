# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/admin_tools/admin_tools.py'

Files last updated: 1751508614.7596843

Stub file last updated: 2025-07-07 01:10:13

## configure_system

```python
async def configure_system(component: str, settings: Dict[str, Any], validate_only: bool = False) -> Dict[str, Any]:
    """
    Configure system components and settings.

Args:
    component: Component to configure (embeddings, vector_store, ipfs, cache)
    settings: Configuration settings to apply
    validate_only: Only validate settings without applying
    
Returns:
    Dict containing configuration results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## manage_endpoints

```python
async def manage_endpoints(action: str, model: Optional[str] = None, endpoint: Optional[str] = None, endpoint_type: Optional[str] = None, ctx_length: Optional[int] = 512) -> Dict[str, Any]:
    """
    Manage API endpoints and configurations.

Args:
    action: Action to perform (add, update, remove, list)
    model: Model name for the endpoint  
    endpoint: Endpoint URL
    endpoint_type: Type of endpoint (libp2p, https, cuda, local, openvino)
    ctx_length: Context length for the model
    
Returns:
    Dict containing operation results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## system_health

```python
async def system_health() -> Dict[str, Any]:
    """
    Check system health status.

Returns:
    Dict containing system health information
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## system_maintenance

```python
async def system_maintenance(operation: str, target: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """
    Perform system maintenance operations.

Args:
    operation: Maintenance operation (restart, cleanup, health_check, backup)
    target: Specific target for the operation (optional)
    force: Force operation even if risky
    
Returns:
    Dict containing operation results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## system_status

```python
async def system_status() -> Dict[str, Any]:
    """
    Get detailed system status information.

Returns:
    Dict containing system status details
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
