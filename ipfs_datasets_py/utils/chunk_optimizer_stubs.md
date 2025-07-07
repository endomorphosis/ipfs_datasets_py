# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/utils/chunk_optimizer.py'

## ChunkMetrics

```python
@dataclass
class ChunkMetrics:
    """
    Metrics for evaluating chunk quality.
    """
```
## ChunkOptimizer

```python
class ChunkOptimizer:
    """
    Advanced chunk optimization for LLM consumption.
    """
```
## __init__

```python
def __init__(self, max_size: int = 2048, overlap: int = 200, min_size: int = 100):
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _calculate_chunk_metrics

```python
def _calculate_chunk_metrics(self, chunk: Dict[str, Any]) -> ChunkMetrics:
    """
    Calculate quality metrics for a chunk.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _calculate_coherence

```python
def _calculate_coherence(self, content: str) -> float:
    """
    Calculate coherence score based on text flow.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _calculate_completeness

```python
def _calculate_completeness(self, content: str) -> float:
    """
    Calculate completeness score based on sentence endings.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _calculate_length_score

```python
def _calculate_length_score(self, word_count: int) -> float:
    """
    Calculate length score based on optimal range.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _calculate_semantic_density

```python
def _calculate_semantic_density(self, content: str) -> float:
    """
    Calculate semantic density (meaningful content ratio).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _create_chunk_dict

```python
def _create_chunk_dict(self, content: str, token_count: int, paragraphs: List[str], chunk_type: str) -> Dict[str, Any]:
    """
    Create a standardized chunk dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _create_sliding_window_chunks

```python
def _create_sliding_window_chunks(self, text: str) -> List[Dict[str, Any]]:
    """
    Create chunks using sliding window approach.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _create_structure_aware_chunks

```python
def _create_structure_aware_chunks(self, text: str) -> List[Dict[str, Any]]:
    """
    Create chunks that respect document structure.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _get_overlap_content

```python
def _get_overlap_content(self, content: str) -> str:
    """
    Get overlap content for chunk continuity.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _optimize_boundaries

```python
def _optimize_boundaries(self, chunks: List[Dict[str, Any]], full_text: str) -> List[Dict[str, Any]]:
    """
    Optimize chunk boundaries for better coherence.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _optimize_end_boundary

```python
def _optimize_end_boundary(self, content: str) -> str:
    """
    Optimize the end boundary of a chunk.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _split_sentences

```python
def _split_sentences(self, text: str) -> List[str]:
    """
    Split text into sentences.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## merge_small_chunks

```python
def merge_small_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge chunks that are too small.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## optimize_chunks

```python
def optimize_chunks(self, text: str, preserve_structure: bool = True) -> List[Dict[str, Any]]:
    """
    Create optimized chunks with quality scoring.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer
