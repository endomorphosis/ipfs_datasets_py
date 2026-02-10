# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/embedding_tools/advanced_embedding_generation.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 02:26:16

## generate_batch_embeddings

```python
async def generate_batch_embeddings(texts: List[str], model_name: str = "sentence-transformers/all-MiniLM-L6-v2", normalize: bool = True, batch_size: int = 32, use_gpu: bool = False, max_texts: int = 100, **kwargs) -> Dict[str, Any]:
    """
    Generate embeddings for multiple texts in batch with optimization.

Args:
    texts: List of texts to generate embeddings for
    model_name: Name of the embedding model to use
    normalize: Whether to normalize embedding vectors
    batch_size: Batch size for processing
    use_gpu: Whether to use GPU acceleration
    max_texts: Maximum number of texts to process in one call
    **kwargs: Additional parameters for embedding generation

Returns:
    Dict containing batch embedding results and metadata
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## generate_embedding

```python
async def generate_embedding(text: str, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", normalize: bool = True, batch_size: int = 32, use_gpu: bool = False, **kwargs) -> Dict[str, Any]:
    """
    Generate a single embedding for text using the integrated IPFS embeddings core.

Args:
    text: Text to generate embedding for
    model_name: Name of the embedding model to use
    normalize: Whether to normalize the embedding vector
    batch_size: Batch size for processing
    use_gpu: Whether to use GPU acceleration
    **kwargs: Additional parameters for embedding generation

Returns:
    Dict containing embedding results and metadata
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## generate_embeddings_from_file

```python
async def generate_embeddings_from_file(file_path: str, output_path: Optional[str] = None, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", batch_size: int = 32, chunk_size: Optional[int] = None, max_length: Optional[int] = None, output_format: str = "json", **kwargs) -> Dict[str, Any]:
    """
    Generate embeddings from a text file with chunking and batch processing.

Args:
    file_path: Path to input text file
    output_path: Path to save embeddings (optional)
    model_name: Name of the embedding model to use
    batch_size: Batch size for processing
    chunk_size: Size of text chunks (optional)
    max_length: Maximum text length per chunk
    output_format: Output format (json, parquet, hdf5)
    **kwargs: Additional parameters

Returns:
    Dict containing file processing results and metadata
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
