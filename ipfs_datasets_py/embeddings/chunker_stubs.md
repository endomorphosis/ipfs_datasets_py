# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/embeddings/chunker.py'

## BaseChunker

```python
class BaseChunker(ABC):
    """
    Base class for text chunking strategies.
    """
```
## Chunker

```python
class Chunker:
    """
    Main chunker class that delegates to specific chunking strategies.
    """
```
## FixedSizeChunker

```python
class FixedSizeChunker(BaseChunker):
    """
    Chunks text into fixed-size pieces with optional overlap.
    """
```
## SemanticChunker

```python
class SemanticChunker(BaseChunker):
    """
    Chunks text based on semantic similarity using embeddings.
    """
```
## SentenceChunker

```python
class SentenceChunker(BaseChunker):
    """
    Chunks text by sentences, grouping them to fit within size limits.
    """
```
## SlidingWindowChunker

```python
class SlidingWindowChunker(BaseChunker):
    """
    Chunks text using a sliding window approach.
    """
```
## __init__

```python
def __init__(self, config: Optional[EmbeddingConfig] = None):
```
* **Async:** False
* **Method:** True
* **Class:** BaseChunker

## __init__

```python
def __init__(self, config: Optional[EmbeddingConfig] = None):
```
* **Async:** False
* **Method:** True
* **Class:** FixedSizeChunker

## __init__

```python
def __init__(self, config: Optional[EmbeddingConfig] = None):
```
* **Async:** False
* **Method:** True
* **Class:** SentenceChunker

## __init__

```python
def __init__(self, config: Optional[EmbeddingConfig] = None):
```
* **Async:** False
* **Method:** True
* **Class:** SlidingWindowChunker

## __init__

```python
def __init__(self, config: Optional[EmbeddingConfig] = None):
```
* **Async:** False
* **Method:** True
* **Class:** SemanticChunker

## __init__

```python
def __init__(self, resources: Optional[Dict] = None, metadata: Optional[Dict] = None):
```
* **Async:** False
* **Method:** True
* **Class:** Chunker

## _create_chunker

```python
def _create_chunker(self) -> BaseChunker:
    """
    Create the appropriate chunker based on strategy.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Chunker

## _initialize_sentence_splitter

```python
def _initialize_sentence_splitter(self):
    """
    Initialize sentence splitter.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SentenceChunker

## _setup_semantic_chunking

```python
def _setup_semantic_chunking(self):
    """
    Setup semantic chunking with embedding model.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticChunker

## _setup_semantic_chunking

```python
async def _setup_semantic_chunking(self, embedding_model_name: str, device: Optional[str] = None, target_devices = None, embed_batch_size: Optional[int] = None):
    """
    Legacy method for setting up semantic chunking.
    """
```
* **Async:** True
* **Method:** True
* **Class:** Chunker

## _split_sentences

```python
def _split_sentences(self, text: str) -> List[str]:
    """
    Split text into sentences.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SentenceChunker

## chunk_semantically

```python
def chunk_semantically(self, text: str, tokenizer: Optional[Tokenizer] = None, **kwargs) -> List[DocumentChunk]:
    """
    Legacy method for semantic chunking.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Chunker

## chunk_text

```python
@abstractmethod
def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
    """
    Chunk text into DocumentChunk objects.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseChunker

## chunk_text

```python
def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
    """
    Chunk text into fixed-size pieces.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FixedSizeChunker

## chunk_text

```python
def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
    """
    Chunk text by sentences.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SentenceChunker

## chunk_text

```python
def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
    """
    Chunk text using sliding window.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SlidingWindowChunker

## chunk_text

```python
def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
    """
    Chunk text using semantic similarity.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SemanticChunker

## chunk_text

```python
def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[DocumentChunk]:
    """
    Chunk text using the configured strategy.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Chunker

## chunk_text_async

```python
@abstractmethod
async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
    """
    Async version of chunk_text.
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseChunker

## chunk_text_async

```python
async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
    """
    Async version of fixed-size chunking.
    """
```
* **Async:** True
* **Method:** True
* **Class:** FixedSizeChunker

## chunk_text_async

```python
async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
    """
    Async version of sentence chunking.
    """
```
* **Async:** True
* **Method:** True
* **Class:** SentenceChunker

## chunk_text_async

```python
async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
    """
    Async version of sliding window chunking.
    """
```
* **Async:** True
* **Method:** True
* **Class:** SlidingWindowChunker

## chunk_text_async

```python
async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
    """
    Async version of semantic chunking.
    """
```
* **Async:** True
* **Method:** True
* **Class:** SemanticChunker

## chunk_text_async

```python
async def chunk_text_async(self, text: str, metadata: Optional[Dict] = None) -> AsyncIterator[DocumentChunk]:
    """
    Async version of text chunking.
    """
```
* **Async:** True
* **Method:** True
* **Class:** Chunker

## delete_endpoint

```python
async def delete_endpoint(self, model_name: str, endpoint: str):
    """
    Delete a model endpoint and free memory.
    """
```
* **Async:** True
* **Method:** True
* **Class:** SemanticChunker

## delete_endpoint

```python
async def delete_endpoint(self, model_name: str, endpoint: str):
    """
    Delete a model endpoint.
    """
```
* **Async:** True
* **Method:** True
* **Class:** Chunker
