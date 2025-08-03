# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/graphrag_processor.py'

Files last updated: 1751408933.6564565

Stub file last updated: 2025-07-07 02:11:01

## GraphRAGProcessor

```python
class GraphRAGProcessor:
    """
    Core GraphRAG processor for combining vector search with graph traversal.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MockGraphRAGProcessor

```python
class MockGraphRAGProcessor(GraphRAGProcessor):
    """
    Mock GraphRAG processor for testing purposes.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, vector_store = None, knowledge_graph = None, embedding_model = None):
    """
    Initialize GraphRAG processor with vector store and knowledge graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## __init__

```python
def __init__(self):
    """
    Initialize mock processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockGraphRAGProcessor

## create_graphrag_processor

```python
def create_graphrag_processor(vector_store = None, knowledge_graph = None) -> GraphRAGProcessor:
    """
    Create a new GraphRAG processor instance.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_mock_processor

```python
def create_mock_processor() -> MockGraphRAGProcessor:
    """
    Create a mock GraphRAG processor for testing.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## execute_cypher

```python
def execute_cypher(self, graph: Dict[str, Any], query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Execute Cypher query on the graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## execute_gremlin

```python
def execute_gremlin(self, graph: Dict[str, Any], query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Execute Gremlin query on the graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## execute_semantic_query

```python
def execute_semantic_query(self, graph: Dict[str, Any], query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Execute semantic query on the graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## execute_sparql

```python
def execute_sparql(self, graph: Dict[str, Any], query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Execute SPARQL query on the graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## expand_by_graph

```python
def expand_by_graph(self, seed_results: List[Dict[str, Any]], max_depth: int = 2, edge_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Expand results using graph traversal.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## load_graph

```python
def load_graph(self, graph_id: str) -> Dict[str, Any]:
    """
    Load a knowledge graph by ID.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## process_query

```python
def process_query(self, query: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a complete GraphRAG query.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## query

```python
def query(self, query_text: str, top_k: int = 5) -> Dict[str, Any]:
    """
    Simple query method for testing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockGraphRAGProcessor

## rank_results

```python
def rank_results(self, results: List[Dict[str, Any]], vector_weight: float = 0.7, graph_weight: float = 0.3) -> List[Dict[str, Any]]:
    """
    Rank combined results from vector search and graph expansion.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## search_by_vector

```python
def search_by_vector(self, query_vector: List[float], top_k: int = 10, min_score: float = 0.0) -> List[Dict[str, Any]]:
    """
    Perform vector similarity search.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor
