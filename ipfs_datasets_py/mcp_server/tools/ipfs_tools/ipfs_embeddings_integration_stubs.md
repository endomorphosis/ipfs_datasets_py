# Function and Class stubs from 'ipfs_datasets_py/mcp_server/tools/ipfs_embeddings_integration.py'

Files last updated: 1751577650.7343042

Stub file last updated: 2025-07-07 01:10:14

## PlaceholderClusteringService

```python
class PlaceholderClusteringService:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PlaceholderDistributedVectorService

```python
class PlaceholderDistributedVectorService:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PlaceholderEmbeddingService

```python
class PlaceholderEmbeddingService:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PlaceholderIPFSVectorService

```python
class PlaceholderIPFSVectorService:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PlaceholderVectorService

```python
class PlaceholderVectorService:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## cluster

```python
async def cluster(self, embeddings: list[list[float]]) -> Dict[str, Any]:
```
* **Async:** True
* **Method:** True
* **Class:** PlaceholderClusteringService

## fallback_embedding_tool

```python
async def fallback_embedding_tool(**kwargs):
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## generate_embedding

```python
async def generate_embedding(self, text: str) -> list[float]:
```
* **Async:** True
* **Method:** True
* **Class:** PlaceholderEmbeddingService

## get_distributed_vector

```python
async def get_distributed_vector(self, cid: str) -> Dict[str, Any]:
```
* **Async:** True
* **Method:** True
* **Class:** PlaceholderDistributedVectorService

## register_ipfs_embeddings_tools

```python
async def register_ipfs_embeddings_tools(mcp_server: FastMCP, tools_dict: Dict[str, Any]):
    """
    Registers tools from the pre-migration embeddings integration with the main MCP server.

Uses the migrated tools that are now part of ipfs_datasets_py.

Args:
    mcp_server: The main FastMCP server instance.
    tools_dict: The dictionary to store registered tool functions.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## search

```python
async def search(self, query_embedding: list[float], top_k: int) -> list[Dict[str, Any]]:
```
* **Async:** True
* **Method:** True
* **Class:** PlaceholderVectorService

## store_vector

```python
async def store_vector(self, vector_data: Dict[str, Any]) -> str:
```
* **Async:** True
* **Method:** True
* **Class:** PlaceholderIPFSVectorService
