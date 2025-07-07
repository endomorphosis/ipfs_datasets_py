# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_tools/tools/embedding_tools.py'

Files last updated: 1751433531.0777135

Stub file last updated: 2025-07-07 01:53:43

## BatchEmbeddingTool

```python
class BatchEmbeddingTool(ClaudeMCPTool):
    """
    Tool for generating embeddings for multiple texts in batch.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EmbeddingGenerationTool

```python
class EmbeddingGenerationTool(ClaudeMCPTool):
    """
    Tool for generating embeddings from text using various models.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MultimodalEmbeddingTool

```python
class MultimodalEmbeddingTool(ClaudeMCPTool):
    """
    Tool for generating embeddings from multimodal content (text, images, audio).
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, embedding_service):
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingGenerationTool

## __init__

```python
def __init__(self, embedding_service):
```
* **Async:** False
* **Method:** True
* **Class:** BatchEmbeddingTool

## __init__

```python
def __init__(self, embedding_service):
```
* **Async:** False
* **Method:** True
* **Class:** MultimodalEmbeddingTool

## execute

```python
async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute embedding generation.
    """
```
* **Async:** True
* **Method:** True
* **Class:** EmbeddingGenerationTool

## execute

```python
async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute batch embedding generation.
    """
```
* **Async:** True
* **Method:** True
* **Class:** BatchEmbeddingTool

## execute

```python
async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute multimodal embedding generation.
    """
```
* **Async:** True
* **Method:** True
* **Class:** MultimodalEmbeddingTool
