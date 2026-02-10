# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/embedding_tools/advanced_search.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 01:10:14

## hybrid_search

```python
async def hybrid_search(query: str, vector_store_id: str, lexical_weight: float = 0.3, semantic_weight: float = 0.7, top_k: int = 10, rerank_results: bool = True, **kwargs) -> Dict[str, Any]:
    """
    Perform hybrid search combining lexical and semantic search methods.

Args:
    query: Search query text
    vector_store_id: ID of the vector store to search
    lexical_weight: Weight for lexical/keyword search component
    semantic_weight: Weight for semantic/embedding search component
    top_k: Number of top results to return
    rerank_results: Whether to apply reranking to final results
    **kwargs: Additional search parameters

Returns:
    Dict containing hybrid search results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## multi_modal_search

```python
async def multi_modal_search(query: Optional[str] = None, image_query: Optional[str] = None, vector_store_id: str = None, model_name: str = "clip-ViT-B-32", top_k: int = 10, modality_weights: Optional[Dict[str, float]] = None, **kwargs) -> Dict[str, Any]:
    """
    Perform multi-modal search combining text and image queries.

Args:
    query: Text query (optional)
    image_query: Image query path or URL (optional)
    vector_store_id: ID of the vector store to search
    model_name: Multi-modal model to use
    top_k: Number of top results to return
    modality_weights: Weights for different modalities
    **kwargs: Additional search parameters

Returns:
    Dict containing multi-modal search results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## search_with_filters

```python
async def search_with_filters(query: str, vector_store_id: str, filters: Dict[str, Any], top_k: int = 10, search_method: str = "semantic", **kwargs) -> Dict[str, Any]:
    """
    Perform filtered search with metadata and content constraints.

Args:
    query: Search query text
    vector_store_id: ID of the vector store to search
    filters: Metadata filters to apply
    top_k: Number of top results to return
    search_method: Search method to use (semantic, lexical, hybrid)
    **kwargs: Additional search parameters

Returns:
    Dict containing filtered search results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## semantic_search

```python
async def semantic_search(query: str, vector_store_id: str, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", top_k: int = 10, similarity_threshold: float = 0.7, include_metadata: bool = True, **kwargs) -> Dict[str, Any]:
    """
    Perform semantic search using embedding similarity.

Args:
    query: Search query text
    vector_store_id: ID of the vector store to search
    model_name: Embedding model to use for query encoding
    top_k: Number of top results to return
    similarity_threshold: Minimum similarity score for results
    include_metadata: Whether to include document metadata
    **kwargs: Additional search parameters

Returns:
    Dict containing search results and metadata
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
