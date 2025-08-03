# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/vector_tools.py'

Files last updated: 1748635923.4713795

Stub file last updated: 2025-07-07 02:11:02

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
def cosine_similarity(self, vector1: List[float], vector2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorSimilarityCalculator

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
