# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/llm/_embeddings.py'

Files last updated: 1749939340.8993912

Stub file last updated: 2025-07-17 05:33:54

## EmbeddingsInterface

```python
class EmbeddingsInterface:
    """
    Manager for document embeddings.
Handles storage, retrieval, and similarity search for document embeddings.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Any] = None, configs: dict[str, Any] = None):
    """
    Initialize the embeddings manager with dependency injection.

Args:
    resources: Dictionary of resources including embedding functions.
    configs: A pydantic model of configuration parameters.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingsInterface

## clear_cache

```python
def clear_cache(self) -> None:
    """
    Clear the embedding cache.
    """
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingsInterface

## cosine_similarity

```python
def cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
    """
    Calculate cosine similarity between two vectors.

Args:
    vec1: First vector
    vec2: Second vector
    
Returns:
    Cosine similarity score (0-1)
    """
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingsInterface

## get_embedding

```python
def get_embedding(self, doc_id: str) -> Optional[dict[str, Any]]:
    """
    Get a stored embedding by document ID.

Args:
    doc_id: Document identifier
    
Returns:
    Dictionary with embedding and metadata, or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingsInterface

## search_similar

```python
def search_similar(self, query_embedding: list[float], top_k: int = 5) -> list[dict[str, Any]]:
    """
    Search for similar documents by embedding.

Args:
    query_embedding: Query embedding vector
    top_k: Number of top results to return
    
Returns:
    List of documents with similarity scores
    """
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingsInterface

## store_embedding

```python
def store_embedding(self, doc_id: str, embedding: list[float], metadata: Optional[dict[str, Any]] = None) -> bool:
    """
    Store an embedding with optional metadata.

Args:
    doc_id: Unique document identifier
    embedding: Embedding vector
    metadata: Optional metadata about the document
    
Returns:
    True if stored successfully, False otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** EmbeddingsInterface
