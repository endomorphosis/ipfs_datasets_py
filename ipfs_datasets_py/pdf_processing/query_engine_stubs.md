# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 21:47:52

## QueryEngine

```python
class QueryEngine:
    """
    Advanced query engine for PDF knowledge base.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryResponse

```python
@dataclass
class QueryResponse:
    """
    Complete query response.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryResult

```python
@dataclass
class QueryResult:
    """
    Single query result item.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SemanticSearchResult

```python
@dataclass
class SemanticSearchResult:
    """
    Result from semantic search.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, graphrag_integrator: GraphRAGIntegrator, storage: Optional[IPLDStorage] = None, embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """
    Initialize the query engine.

Args:
    graphrag_integrator: GraphRAG integration system
    storage: IPLD storage instance
    embedding_model: Model for semantic search
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _detect_query_type

```python
def _detect_query_type(self, query: str) -> str:
    """
    Auto-detect query type based on query patterns.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _extract_entity_names_from_query

```python
def _extract_entity_names_from_query(self, query: str) -> List[str]:
    """
    Extract potential entity names from query text.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _generate_query_suggestions

```python
async def _generate_query_suggestions(self, query: str, results: List[QueryResult]) -> List[str]:
    """
    Generate query suggestions based on results.
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _get_entity_documents

```python
def _get_entity_documents(self, entity: Entity) -> List[str]:
    """
    Get document IDs where entity appears.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _get_relationship_documents

```python
def _get_relationship_documents(self, relationship: Relationship) -> List[str]:
    """
    Get document IDs where relationship appears.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _normalize_query

```python
def _normalize_query(self, query: str) -> str:
    """
    Normalize query text for processing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _process_cross_document_query

```python
async def _process_cross_document_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process cross-document analysis queries.
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _process_document_query

```python
async def _process_document_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process document-level queries.
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _process_entity_query

```python
async def _process_entity_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process entity-focused queries.
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _process_graph_traversal_query

```python
async def _process_graph_traversal_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process graph traversal queries (paths, connections, etc.).
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _process_relationship_query

```python
async def _process_relationship_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process relationship-focused queries.
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _process_semantic_query

```python
async def _process_semantic_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process semantic search queries.
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## get_query_analytics

```python
async def get_query_analytics(self) -> Dict[str, Any]:
    """
    Get analytics about query patterns and performance.
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## query

```python
async def query(self, query_text: str, query_type: Optional[str] = None, filters: Optional[Dict[str, Any]] = None, max_results: int = 20) -> QueryResponse:
    """
    Process a natural language query.

Args:
    query_text: Natural language query
    query_type: Specific query type or auto-detect
    filters: Additional filters (document_id, entity_type, etc.)
    max_results: Maximum number of results
    
Returns:
    QueryResponse with results and metadata
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine
