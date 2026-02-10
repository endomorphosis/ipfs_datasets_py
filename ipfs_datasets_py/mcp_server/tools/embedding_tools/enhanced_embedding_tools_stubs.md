# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/embedding_tools/enhanced_embedding_tools.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 02:26:16

## chunk_text

```python
async def chunk_text(text: str, chunk_size: int = 512, chunk_overlap: int = 50, method: str = "fixed", n_sentences: int = 8, step_size: int = 256) -> Dict[str, Any]:
    """
    Chunk text using various strategies for embedding.

Args:
    text: Text to chunk
    chunk_size: Size of each chunk in characters
    chunk_overlap: Overlap between chunks
    method: Chunking method (fixed, semantic, sliding_window)
    n_sentences: Number of sentences per chunk (for semantic)
    step_size: Step size for sliding window
    
Returns:
    Dictionary with chunked text results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## create_embeddings

```python
async def create_embeddings(texts: Union[str, List[str]], model: str = "thenlper/gte-small", endpoint_type: str = "local", endpoint_url: Optional[str] = None, batch_size: int = 32, max_length: int = 512, device: str = "cpu") -> Dict[str, Any]:
    """
    Create embeddings for given texts using specified model and endpoint.

Args:
    texts: Single text or list of texts to embed
    model: Model name for embedding generation
    endpoint_type: Type of endpoint (local, tei, openvino, libp2p)
    endpoint_url: URL for remote endpoints
    batch_size: Batch size for processing
    max_length: Maximum token length
    device: Device to use for local endpoints
    
Returns:
    Dictionary with embedding results and metadata
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## index_dataset

```python
async def index_dataset(dataset_name: str, split: Optional[str] = None, column: str = "text", output_path: str = "./embeddings_cache", models: Optional[List[str]] = None, chunk_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Index a dataset with embeddings for similarity search.

Args:
    dataset_name: Name of the dataset to index
    split: Dataset split to use (train, test, validation)
    column: Text column to embed
    output_path: Path to save embeddings
    models: List of models to use for embedding
    chunk_config: Text chunking configuration
    
Returns:
    Dictionary with indexing results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## manage_endpoints

```python
async def manage_endpoints(action: str, model: str, endpoint: str, endpoint_type: str = "tei", context_length: int = 512) -> Dict[str, Any]:
    """
    Manage embedding endpoints (add, remove, test).

Args:
    action: Action to perform (add, remove, test, list)
    model: Model name
    endpoint: Endpoint URL or device
    endpoint_type: Type of endpoint (tei, openvino, libp2p, local)
    context_length: Maximum context length
    
Returns:
    Dictionary with endpoint management results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## search_embeddings

```python
async def search_embeddings(query: str, index_path: str, model: str = "thenlper/gte-small", top_k: int = 10, threshold: float = 0.0) -> Dict[str, Any]:
    """
    Search for similar texts using pre-computed embeddings.

Args:
    query: Query text to search for
    index_path: Path to the embeddings index file
    model: Model used for the index
    top_k: Number of top results to return
    threshold: Minimum similarity threshold
    
Returns:
    Dictionary with search results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
