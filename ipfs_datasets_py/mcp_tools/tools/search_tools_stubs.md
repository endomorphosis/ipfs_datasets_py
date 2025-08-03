# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_tools/tools/search_tools.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 01:53:43

## FacetedSearchTool

```python
class FacetedSearchTool(ClaudeMCPTool):
    """
    Tool for performing faceted search with metadata filtering.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SemanticSearchTool

```python
class SemanticSearchTool(ClaudeMCPTool):
    """
    Tool for performing semantic search on LAION embeddings.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SimilaritySearchTool

```python
class SimilaritySearchTool(ClaudeMCPTool):
    """
    Tool for finding similar embeddings based on a reference embedding.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, vector_service):
```
* **Async:** False
* **Method:** True
* **Class:** SemanticSearchTool

## __init__

```python
def __init__(self, vector_service):
```
* **Async:** False
* **Method:** True
* **Class:** SimilaritySearchTool

## __init__

```python
def __init__(self, vector_service):
```
* **Async:** False
* **Method:** True
* **Class:** FacetedSearchTool

## execute

```python
async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute semantic search on LAION embeddings.
    """
```
* **Async:** True
* **Method:** True
* **Class:** SemanticSearchTool

## execute

```python
async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute similarity search based on embedding vector.
    """
```
* **Async:** True
* **Method:** True
* **Class:** SimilaritySearchTool

## execute

```python
async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute faceted search with filtering and aggregations.
    """
```
* **Async:** True
* **Method:** True
* **Class:** FacetedSearchTool
