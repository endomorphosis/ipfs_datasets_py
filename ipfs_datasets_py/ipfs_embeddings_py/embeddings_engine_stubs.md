# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/ipfs_embeddings_py/embeddings_engine.py'

Files last updated: 1751408933.6564565

Stub file last updated: 2025-07-07 01:05:43

## AdvancedIPFSEmbeddings

```python
class AdvancedIPFSEmbeddings:
    """
    Advanced IPFS embeddings engine with multi-backend support and MCP integration
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ChunkingConfig

```python
@dataclass
class ChunkingConfig:
    """
    Configuration for text chunking
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EmbeddingConfig

```python
@dataclass
class EmbeddingConfig:
    """
    Configuration for embedding operations
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: Dict[str, Any], metadata: Dict[str, Any]):
    """
    Initialize the embeddings engine
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## _generate_http_embeddings

```python
async def _generate_http_embeddings(self, texts: List[str], endpoint: str) -> np.ndarray:
    """
    Generate embeddings using HTTP endpoint
    """
```
* **Async:** True
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## _generate_local_embeddings

```python
async def _generate_local_embeddings(self, texts: List[str], model: str, device: str) -> np.ndarray:
    """
    Generate embeddings using local model
    """
```
* **Async:** True
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## _initialize_endpoints

```python
def _initialize_endpoints(self):
    """
    Initialize endpoints from resource configuration
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## _process_dataset_for_model

```python
async def _process_dataset_for_model(self, dataset, model: str, column: str, dst_path: str) -> Dict[str, Any]:
    """
    Process dataset for a specific model
    """
```
* **Async:** True
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## add_libp2p_endpoint

```python
def add_libp2p_endpoint(self, model: str, endpoint: str, context_length: int):
    """
    Add a LibP2P endpoint
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## add_local_endpoint

```python
def add_local_endpoint(self, model: str, device: str, context_length: int):
    """
    Add a local endpoint
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## add_openvino_endpoint

```python
def add_openvino_endpoint(self, model: str, endpoint: str, context_length: int):
    """
    Add an OpenVINO endpoint
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## add_tei_endpoint

```python
def add_tei_endpoint(self, model: str, endpoint: str, context_length: int):
    """
    Add a TEI (Text Embeddings Inference) endpoint
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## chunk_text

```python
def chunk_text(self, text: str, config: ChunkingConfig) -> List[Tuple[int, int]]:
    """
    Chunk text using specified strategy
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## generate_embeddings

```python
async def generate_embeddings(self, texts: List[str], model: str, endpoint: Optional[str] = None) -> np.ndarray:
    """
    Generate embeddings for a list of texts
    """
```
* **Async:** True
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## get_endpoints

```python
def get_endpoints(self, model: str, endpoint_type: Optional[str] = None) -> List[str]:
    """
    Get available endpoints for a model
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## get_status

```python
def get_status(self) -> Dict[str, Any]:
    """
    Get current status of the embeddings engine
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## index_dataset

```python
async def index_dataset(self, dataset_name: str, split: Optional[str] = None, column: str = "text", dst_path: str = "./embeddings_cache", models: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Index a dataset with embeddings
    """
```
* **Async:** True
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## search_similar

```python
async def search_similar(self, query: str, model: str, top_k: int = 10, index_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search for similar texts using embeddings
    """
```
* **Async:** True
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings

## test_endpoint

```python
async def test_endpoint(self, endpoint: str, model: str) -> bool:
    """
    Test if an endpoint is responsive
    """
```
* **Async:** True
* **Method:** True
* **Class:** AdvancedIPFSEmbeddings
