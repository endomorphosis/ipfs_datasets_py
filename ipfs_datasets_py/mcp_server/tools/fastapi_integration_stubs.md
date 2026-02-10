# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/fastapi_integration.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 01:10:14

## ApiStatus

```python
class ApiStatus(BaseModel):
    """
    API status response.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## BaseModel

```python
class BaseModel:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FastAPI

```python
class FastAPI:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MCPToolsAPI

```python
class MCPToolsAPI:
    """
    FastAPI application for migrated MCP tools.

Provides REST API endpoints for tools migrated into the integrated
`ipfs_datasets_py` stack (router-based embeddings and `vector_stores`).
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ToolExecutionRequest

```python
class ToolExecutionRequest(BaseModel):
    """
    Request model for tool execution.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ToolExecutionResponse

```python
class ToolExecutionResponse(BaseModel):
    """
    Response model for tool execution.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ToolInfo

```python
class ToolInfo(BaseModel):
    """
    Model for tool information.
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
* **Class:** MCPToolsAPI

## _setup_middleware

```python
def _setup_middleware(self):
    """
    Setup middleware for the FastAPI app.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MCPToolsAPI

## _setup_routes

```python
def _setup_routes(self):
    """
    Setup API routes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MCPToolsAPI

## create_api_app

```python
def create_api_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

Returns:
    Configured FastAPI application
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## execute_tool

```python
@self.app.post("/tools/{tool_name}/execute", response_model=ToolExecutionResponse)
async def execute_tool(tool_name: str, request: ToolExecutionRequest, credentials: Optional[HTTPAuthorizationCredentials] = Security(self.security)):
    """
    Execute a specific tool.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## execute_tool_by_request

```python
@self.app.post("/tools/execute", response_model=ToolExecutionResponse)
async def execute_tool_by_request(request: ToolExecutionRequest, credentials: Optional[HTTPAuthorizationCredentials] = Security(self.security)):
    """
    Execute a tool specified in the request body.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_tool_info

```python
@self.app.get("/tools/{tool_name}", response_model=ToolInfo)
async def get_tool_info(tool_name: str):
    """
    Get information about a specific tool.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## health_check

```python
@self.app.get("/health")
async def health_check():
    """
    Health check endpoint.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## list_categories

```python
@self.app.get("/categories")
async def list_categories():
    """
    List all tool categories.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## list_tools

```python
@self.app.get("/tools", response_model=List[ToolInfo])
async def list_tools(category: Optional[str] = None):
    """
    List all available tools, optionally filtered by category.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## root

```python
@self.app.get("/", response_model=ApiStatus)
async def root():
    """
    Get API status and information.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## run_api_server

```python
def run_api_server(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    """
    Run the API server using uvicorn.

Args:
    host: Host to bind to
    port: Port to bind to
    reload: Enable auto-reload for development
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## startup_event

```python
@self.app.on_event("startup")
async def startup_event():
    """
    Initialize tools on startup.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
