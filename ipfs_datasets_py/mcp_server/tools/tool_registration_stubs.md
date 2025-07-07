# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/tool_registration.py'

## MCPToolRegistry

```python
class MCPToolRegistry:
    """
    Registry for managing and registering MCP tools from the migration.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** MCPToolRegistry

## create_and_register_all_tools

```python
def create_and_register_all_tools() -> MCPToolRegistry:
    """
    Create a new registry and register all migrated tools.

Returns:
    Configured MCPToolRegistry with all tools registered
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_registration_summary

```python
def get_registration_summary(self) -> Dict[str, Any]:
    """
    Get a summary of tool registration.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MCPToolRegistry

## get_tool

```python
def get_tool(self, tool_name: str) -> Optional[BaseMCPTool]:
    """
    Get a tool by name.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MCPToolRegistry

## get_tools_by_category

```python
def get_tools_by_category(self, category: str) -> List[BaseMCPTool]:
    """
    Get all tools in a category.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MCPToolRegistry

## list_all_tools

```python
def list_all_tools(self) -> List[Dict[str, Any]]:
    """
    List all registered tools with metadata.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MCPToolRegistry

## register_all_migrated_tools

```python
def register_all_migrated_tools(registry: MCPToolRegistry) -> Dict[str, Any]:
    """
    Register all migrated tools from the ipfs_embeddings_py integration.

Args:
    registry: The tool registry to register tools with
    
Returns:
    Registration summary with success/failure details
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## register_tool

```python
def register_tool(self, tool: BaseMCPTool) -> bool:
    """
    Register a single MCP tool.

Args:
    tool: The MCP tool to register
    
Returns:
    True if registration successful, False otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** MCPToolRegistry
