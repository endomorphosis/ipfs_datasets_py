# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/vector_tools_backup.py'

Files last updated: 1751427003.6081154

Stub file last updated: 2025-07-07 02:11:02

## VectorProcessor

```python
class VectorProcessor:
    """
    Processor for vector operations and transformations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorSimilarityCalculator

```python
class VectorSimilarityCalculator:
    """
    Calculator for vector similarity operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorStore

```python
class VectorStore:
    """
    Vector store for managing embeddings and similarity search.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorTools

```python
class VectorTools:
    """
    Collection of vector utility tools.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, dimension: int = 768):
    """
    Initialize vector store with specified dimension.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorStore

## __init__

```python
def __init__(self, dimension: int = 768):
    """
    Initialize vector processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorProcessor

## __init__

```python
def __init__(self):
    """
    Initialize the calculator.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorSimilarityCalculator

## add_vector

```python
def add_vector(self, vector_id: str, vector: List[float], metadata: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Add a vector to the store.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorStore

## batch_similarity

```python
def batch_similarity(self, vectors: List[List[float]], query_vector: List[float]) -> List[float]:
    """
    Calculate similarities between a query vector and multiple vectors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorSimilarityCalculator

## calculate_similarity

```python
def calculate_similarity(vector1: List[float], vector2: List[float]) -> float:
    """
    Calculate similarity between two vectors.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## cosine_similarity

```python
@staticmethod
def cosine_similarity(vector1: List[float], vector2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorTools

## cosine_similarity

```python
def cosine_similarity(self, vector1: List[float], vector2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorSimilarityCalculator

## create_embedding

```python
def create_embedding(self, text: str) -> List[float]:
    """
    Create a simple embedding for text (mock implementation).
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorProcessor

## create_vector_processor

```python
def create_vector_processor(dimension: int = 768) -> VectorProcessor:
    """
    Create a new vector processor instance.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_vector_store

```python
def create_vector_store(dimension: int = 768) -> VectorStore:
    """
    Create a new vector store instance.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## euclidean_distance

```python
@staticmethod
def euclidean_distance(vector1: List[float], vector2: List[float]) -> float:
    """
    Calculate Euclidean distance between two vectors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorTools

## euclidean_distance

```python
def euclidean_distance(self, vector1: List[float], vector2: List[float]) -> float:
    """
    Calculate Euclidean distance between two vectors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorSimilarityCalculator

## find_most_similar

```python
def find_most_similar(self, vectors: Dict[str, List[float]], query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Find the most similar vectors to a query vector.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorSimilarityCalculator

## normalize_vector

```python
@staticmethod
def normalize_vector(vector: List[float]) -> List[float]:
    """
    Normalize a vector to unit length.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorTools

## process_text_batch

```python
def process_text_batch(self, texts: List[str]) -> Dict[str, Any]:
    """
    Process a batch of texts into embeddings.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorProcessor

## search_similar

```python
def search_similar(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Search for similar vectors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorStore

## vector_magnitude

```python
@staticmethod
def vector_magnitude(vector: List[float]) -> float:
    """
    Calculate the magnitude of a vector.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorTools
