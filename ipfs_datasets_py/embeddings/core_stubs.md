# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/embeddings/core.py'

## AdaptiveBatchProcessor

```python
class AdaptiveBatchProcessor:
    """
    Intelligent batch size optimization based on performance metrics and memory usage
    """
```
## EmbeddingConfig

```python
@dataclass
class EmbeddingConfig:
    """
    Configuration for embedding generation
    """
```
## IPFSEmbeddings

```python
class IPFSEmbeddings:
    """
    Core IPFS Embeddings class providing advanced embedding generation,
vector search, and IPFS integration capabilities.

Migrated from endomorphosis/ipfs_embeddings_py with enhancements for
integration with ipfs_datasets_py.
    """
```
## MemoryMonitor

```python
class MemoryMonitor:
    """
    Monitor system memory usage for adaptive batch sizing
    """
```
## PerformanceMetrics

```python
@dataclass
class PerformanceMetrics:
    """
    Performance metrics for batch processing optimization
    """
```
## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMonitor

## __init__

```python
def __init__(self, max_memory_percent: float = 80.0, min_batch_size: int = 1, max_batch_size: int = 512):
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveBatchProcessor

## __init__

```python
def __init__(self, resources: Dict[str, Any], metadata: Dict[str, Any]):
    """
    Initialize IPFS Embeddings system

Args:
    resources: Dictionary containing endpoint configurations
    metadata: Dictionary containing metadata configuration
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSEmbeddings

## __post_init__

```python
def __post_init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetrics

## _force_garbage_collection

```python
def _force_garbage_collection(self):
    """
    Force garbage collection to free memory
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSEmbeddings

## _generate_batch_embeddings

```python
async def _generate_batch_embeddings(self, texts: List[str], config: EmbeddingConfig) -> List[np.ndarray]:
    """
    Generate embeddings for a batch of texts
    """
```
* **Async:** True
* **Method:** True
* **Class:** IPFSEmbeddings

## _initialize_vector_stores

```python
def _initialize_vector_stores(self):
    """
    Initialize available vector store backends
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSEmbeddings

## _parse_resources

```python
def _parse_resources(self):
    """
    Parse and validate resources configuration
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSEmbeddings

## add_local_endpoint

```python
def add_local_endpoint(self, model: str, device: str, ctx_length: int):
    """
    Add local endpoint to the system
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSEmbeddings

## add_openvino_endpoint

```python
def add_openvino_endpoint(self, model: str, endpoint: str, ctx_length: int):
    """
    Add OpenVINO endpoint to the system
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSEmbeddings

## add_tei_endpoint

```python
def add_tei_endpoint(self, model: str, endpoint: str, ctx_length: int):
    """
    Add TEI endpoint to the system
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSEmbeddings

## generate_embeddings

```python
async def generate_embeddings(self, texts: List[str], config: Optional[EmbeddingConfig] = None) -> np.ndarray:
    """
    Generate embeddings for a list of texts using optimal batching

Args:
    texts: List of texts to embed
    config: Embedding configuration
    
Returns:
    NumPy array of embeddings
    """
```
* **Async:** True
* **Method:** True
* **Class:** IPFSEmbeddings

## get_available_memory_mb

```python
def get_available_memory_mb(self) -> float:
    """
    Get available system memory in MB
    """
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMonitor

## get_memory_aware_batch_size

```python
def get_memory_aware_batch_size(self) -> int:
    """
    Calculate batch size based on available memory
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdaptiveBatchProcessor

## get_memory_percent

```python
def get_memory_percent(self) -> float:
    """
    Get memory usage percentage
    """
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMonitor

## get_memory_usage_mb

```python
def get_memory_usage_mb(self) -> float:
    """
    Get current memory usage in MB
    """
```
* **Async:** False
* **Method:** True
* **Class:** MemoryMonitor

## get_status

```python
def get_status(self) -> Dict[str, Any]:
    """
    Get system status and metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPFSEmbeddings

## ipfs_embeddings_py

```python
def ipfs_embeddings_py(resources: Dict[str, Any], metadata: Dict[str, Any]) -> IPFSEmbeddings:
    """
    Create an IPFSEmbeddings instance (backwards compatibility)

Args:
    resources: Dictionary containing endpoint configurations
    metadata: Dictionary containing metadata configuration
    
Returns:
    IPFSEmbeddings instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## search_similar

```python
async def search_similar(self, query_embedding: np.ndarray, top_k: int = 10, vector_store: str = "qdrant") -> List[Dict[str, Any]]:
    """
    Search for similar embeddings in the specified vector store

Args:
    query_embedding: Query embedding vector
    top_k: Number of results to return
    vector_store: Vector store backend to use
    
Returns:
    List of similar results with scores and metadata
    """
```
* **Async:** True
* **Method:** True
* **Class:** IPFSEmbeddings

## store_embeddings

```python
async def store_embeddings(self, embeddings: np.ndarray, metadata: List[Dict[str, Any]], vector_store: str = "qdrant") -> bool:
    """
    Store embeddings in the specified vector store

Args:
    embeddings: Array of embeddings to store
    metadata: List of metadata dictionaries for each embedding
    vector_store: Vector store backend to use
    
Returns:
    Success status
    """
```
* **Async:** True
* **Method:** True
* **Class:** IPFSEmbeddings
