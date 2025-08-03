# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_tools/tools/vector_store_tools.py'

Files last updated: 1751499305.4302874

Stub file last updated: 2025-07-07 01:53:43

## VectorIndexTool

```python
class VectorIndexTool(ClaudeMCPTool):
    """
    Tool for managing vector indexes in the MCP (Model Context Protocol) framework.
This tool provides functionality to create, update, delete, and retrieve information
about vector indexes used for efficient similarity search and retrieval operations.

Attributes:
    name (str): The tool name identifier ("manage_vector_index").
    description (str): Human-readable description of the tool's purpose.
    input_schema (dict): JSON schema defining the tool's input parameters.
    vector_service: The vector service instance used for index operations.

Methods:
    __init__(vector_service): Initialize the tool with a vector service instance.
    execute(action, index_name, config=None): Execute vector index management operations.

Parameters:
    action (str): The operation to perform - one of "create", "update", "delete", or "info".
    index_name (str): Name of the vector index to operate on (1-100 characters).
    config (dict, optional): Configuration parameters for index creation/update including:
        - dimension (int): Vector dimension size (minimum 1)
        - metric (str): Distance metric ("cosine", "euclidean", or "dot")
        - index_type (str): Index implementation ("faiss", "hnswlib", or "annoy")

Returns:
    dict: Operation result containing action, index_name, result data, and success status.

Raises:
    ValueError: If vector_service is None during initialization.
    Exception: If vector index operation fails during execution.

Example:
    >>> tool = VectorIndexTool(vector_service)
    >>> result = await tool.execute("create", "my_index", {
    ...     "dimension": 768,
    ...     "metric": "cosine",
    ...     "index_type": "faiss"
    ... })
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorMetadataTool

```python
class VectorMetadataTool(ClaudeMCPTool):
    """
    Tool for managing vector metadata.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorRetrievalTool

```python
class VectorRetrievalTool(ClaudeMCPTool):
    """
    Tool for retrieving vectors from storage.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, vector_service):
    """
    Initialize the VectorIndexTool with a vector service.

This tool provides functionality to create, update, delete, and get information
about vector indexes for efficient similarity search operations.

Attributes initialized:
    name (str): The name of the tool, set to "manage_vector_index".
    description (str): Description of the tool's functionality.
    input_schema (dict): JSON schema defining the tool's input parameters including:
        - action: The operation to perform (create, update, delete, info)
        - index_name: Name of the vector index (1-100 characters)
        - config: Optional configuration object with dimension, metric, and index_type
    vector_service: The vector service instance for managing vector indexes.

Args:
    vector_service: The vector service instance used for managing vector indexes.
                   Must not be None.

Raises:
    ValueError: If vector_service is None.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorIndexTool

## __init__

```python
def __init__(self, vector_service):
```
* **Async:** False
* **Method:** True
* **Class:** VectorRetrievalTool

## __init__

```python
def __init__(self, vector_service):
```
* **Async:** False
* **Method:** True
* **Class:** VectorMetadataTool

## add_embeddings_to_store_tool

```python
async def add_embeddings_to_store_tool(store_id: str, embeddings: List[List[float]], metadata: Optional[List[Dict[str, Any]]] = None, ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Add embeddings to an existing vector store.

Args:
    store_id: ID of the vector store
    embeddings: List of embedding vectors
    metadata: Optional metadata for each embedding
    ids: Optional IDs for embeddings
    
Returns:
    Dictionary with addition results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## create_vector_store_tool

```python
async def create_vector_store_tool(store_path: str, dimension: int, provider: str = "faiss", index_type: str = "flat", config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create a vector store with specified configuration.

Args:
    store_path: Path where the vector store will be saved
    dimension: Vector dimension for the store
    provider: Vector store provider (faiss, pinecone, chroma, etc.)
    index_type: Type of index to create
    config: Additional configuration options
    
Returns:
    Dict containing creation results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## delete_from_vector_store_tool

```python
async def delete_from_vector_store_tool(store_id: str, ids: Optional[List[str]] = None, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Delete vectors from a vector store.

Args:
    store_id: ID of the vector store
    ids: List of vector IDs to delete
    filters: Optional filters for bulk deletion
    
Returns:
    Dictionary with deletion results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## execute

```python
async def execute(self, action: str, index_name: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute vector index management operation.
    """
```
* **Async:** True
* **Method:** True
* **Class:** VectorIndexTool

## execute

```python
async def execute(self, collection: str = "default", ids: Optional[List[str]] = None, filters: Optional[Dict[str, Any]] = None, limit: int = 100) -> Dict[str, Any]:
    """
    Execute vector retrieval operation.
    """
```
* **Async:** True
* **Method:** True
* **Class:** VectorRetrievalTool

## execute

```python
async def execute(self, action: str, collection: str = "default", vector_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute vector metadata management operation.
    """
```
* **Async:** True
* **Method:** True
* **Class:** VectorMetadataTool

## get_vector_store_stats_tool

```python
async def get_vector_store_stats_tool(store_id: str) -> Dict[str, Any]:
    """
    Get statistics for a vector store.

Args:
    store_id: ID of the vector store
    
Returns:
    Dictionary with store statistics
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## optimize_vector_store_tool

```python
async def optimize_vector_store_tool(store_id: str) -> Dict[str, Any]:
    """
    Optimize a vector store for better performance.

Args:
    store_id: ID of the vector store
    
Returns:
    Dictionary with optimization results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## search_vector_store_tool

```python
async def search_vector_store_tool(store_id: str, query_vector: List[float], top_k: int = 10, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Search vectors in a vector store.

Args:
    store_id: ID of the vector store
    query_vector: Query vector for search
    top_k: Number of results to return
    filters: Optional filters for search
    
Returns:
    Dictionary with search results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
