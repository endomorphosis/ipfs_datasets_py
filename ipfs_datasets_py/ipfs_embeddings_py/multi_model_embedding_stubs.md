# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/ipfs_embeddings_py/multi_model_embedding.py'

Files last updated: 1748635923.4313796

Stub file last updated: 2025-07-07 01:05:43

## MultiModelEmbeddingGenerator

```python
class MultiModelEmbeddingGenerator:
    """
    Generates embeddings using multiple models for comprehensive representation.

This class manages multiple embedding models to generate diverse vector
representations of text, supporting different models for different types
of embeddings (e.g., sentence, document, query-specific).

Key features:
- Support for multiple embedding models with different characteristics
- Efficient chunking strategies for long documents
- IPFS/IPLD integration for persistent storage of embeddings
- Batched processing for efficiency
- Model fusion capabilities
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, model_configs: Optional[List[Dict[str, Any]]] = None, device: str = "cpu", cache_dir: Optional[str] = None, enable_model_fusion: bool = False):
    """
    Initialize the embedding generator with multiple models.

Args:
    model_configs: List of model configurations with format:
        [{"name": "model_name", "dimension": dim, "type": "model_type"}, ...]
        Default models will be used if not provided
    device: Device to run models on ("cpu", "cuda", "mps")
    cache_dir: Directory to cache models and tokenizers
    enable_model_fusion: Whether to enable model fusion for improved embeddings
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## _batch_encode

```python
def _batch_encode(self, model_name: str, chunks: List[str], batch_size: int, normalize: bool) -> List[np.ndarray]:
    """
    Encode text chunks in batches.

Args:
    model_name: Name of model to use
    chunks: List of text chunks
    batch_size: Batch size for processing
    normalize: Whether to normalize embeddings

Returns:
    List of embedding vectors
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## _chunk_text

```python
def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Split text into chunks with overlap.

Args:
    text: Text to split
    chunk_size: Size of each chunk
    overlap: Overlap between chunks

Returns:
    List of text chunks
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## _fuse_embeddings

```python
def _fuse_embeddings(self, model_embeddings: Dict[str, List[np.ndarray]]) -> List[np.ndarray]:
    """
    Fuse embeddings from multiple models.

Args:
    model_embeddings: Dictionary of model name to embeddings

Returns:
    List of fused embeddings
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## _load_models

```python
def _load_models(self):
    """
    Load the specified models and tokenizers.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## _mean_pooling

```python
def _mean_pooling(self, model_output, attention_mask):
    """
    Perform mean pooling on token embeddings.

Args:
    model_output: Output from the transformer model
    attention_mask: Attention mask from tokenizer

Returns:
    Pooled embeddings
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## _split_embeddings

```python
def _split_embeddings(self, embeddings: List[np.ndarray], chunks: List[str], texts: List[str]) -> List[List[np.ndarray]]:
    """
    Split embeddings back to correspond to original texts.

Args:
    embeddings: List of chunk embeddings
    chunks: List of all text chunks
    texts: Original list of texts

Returns:
    List of embeddings lists, one per original text
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## from_config

```python
@classmethod
def from_config(cls, config_path: str) -> "MultiModelEmbeddingGenerator":
    """
    Create a MultiModelEmbeddingGenerator from a configuration file.

Args:
    config_path: Path to configuration file

Returns:
    Configured MultiModelEmbeddingGenerator instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## generate_embeddings

```python
def generate_embeddings(self, text: Union[str, List[str]], model_names: Optional[List[str]] = None, chunk_size: int = 512, overlap: int = 50, batch_size: int = 8, normalize: bool = True) -> Dict[str, List[np.ndarray]]:
    """
    Generate embeddings for text using all configured models or specified models.

Args:
    text: Text or list of texts to generate embeddings for
    model_names: List of model names to use; uses all if None
    chunk_size: Size of text chunks for processing
    overlap: Overlap between chunks
    batch_size: Batch size for processing
    normalize: Whether to normalize the embeddings to unit length

Returns:
    Dictionary mapping model names to lists of embeddings
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## get_model_dimensions

```python
def get_model_dimensions(self) -> Dict[str, int]:
    """
    Get dimensions for each model.

Returns:
    Dictionary mapping model names to dimensions
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## get_stats

```python
def get_stats(self) -> Dict[str, Any]:
    """
    Get statistics about the embedding generator.

Returns:
    Dictionary of statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## load_from_ipfs

```python
def load_from_ipfs(self, cids: Dict[str, str], ipfs_client = None) -> Dict[str, List[np.ndarray]]:
    """
    Load embeddings from IPFS.

Args:
    cids: Dictionary mapping model names to CIDs
    ipfs_client: Optional IPFS client instance

Returns:
    Dictionary mapping model names to lists of embeddings
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator

## store_on_ipfs

```python
def store_on_ipfs(self, embeddings: Dict[str, List[np.ndarray]], metadata: Optional[Dict[str, Any]] = None, ipfs_client = None) -> Dict[str, str]:
    """
    Store embeddings on IPFS using IPLD.

Args:
    embeddings: Dictionary of model name to embeddings
    metadata: Additional metadata to store
    ipfs_client: Optional IPFS client instance

Returns:
    Dictionary mapping model names to CIDs
    """
```
* **Async:** False
* **Method:** True
* **Class:** MultiModelEmbeddingGenerator
