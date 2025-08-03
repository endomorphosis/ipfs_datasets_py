# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/cross_document_reasoning.py'

Files last updated: 1751513961.5442855

Stub file last updated: 2025-07-07 02:11:01

## CrossDocReasoning

```python
@dataclass
class CrossDocReasoning:
    """
    Represents a cross-document reasoning process.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## CrossDocumentReasoner

```python
class CrossDocumentReasoner:
    """
    Implements cross-document reasoning for GraphRAG.

This class provides the capability to reason across multiple documents
by finding entity-mediated connections and generating synthesized answers
based on connected information.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DocumentNode

```python
@dataclass
class DocumentNode:
    """
    Represents a document or chunk of text in the reasoning process.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EntityMediatedConnection

```python
@dataclass
class EntityMediatedConnection:
    """
    Represents a connection between documents mediated by an entity.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## InformationRelationType

```python
class InformationRelationType(Enum):
    """
    Types of relations between pieces of information across documents.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, query_optimizer: Optional[UnifiedGraphRAGQueryOptimizer] = None, reasoning_tracer: Optional[LLMReasoningTracer] = None, llm_service: Optional[Any] = None, min_connection_strength: float = 0.6, max_reasoning_depth: int = 3, enable_contradictions: bool = True, entity_match_threshold: float = 0.85):
    """
    Initialize the cross-document reasoner.

Args:
    query_optimizer: RAG query optimizer for efficient graph traversal
    reasoning_tracer: Tracer for recording reasoning steps
    llm_service: LLM service for answer generation and reasoning
    min_connection_strength: Minimum strength for entity-mediated connections
    max_reasoning_depth: Maximum depth for reasoning processes
    enable_contradictions: Whether to look for contradicting information
    entity_match_threshold: Threshold for matching entities across documents
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## _determine_relation

```python
def _determine_relation(self, entity_id: str, source_doc_id: str, target_doc_id: str, documents: List[DocumentNode], knowledge_graph: Any) -> Tuple[InformationRelationType, float]:
    """
    Determine the relation type between two documents regarding an entity.

Args:
    entity_id: The entity ID
    source_doc_id: The source document ID
    target_doc_id: The target document ID
    documents: List of all documents
    knowledge_graph: Knowledge graph

Returns:
    Tuple of (relation_type, connection_strength)
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## _find_entity_connections

```python
def _find_entity_connections(self, documents: List[DocumentNode], knowledge_graph: Optional[Any], max_hops: int = 2) -> List[EntityMediatedConnection]:
    """
    Find entity-mediated connections between documents.

Args:
    documents: List of documents
    knowledge_graph: Knowledge graph for entity information
    max_hops: Maximum number of hops for graph traversal

Returns:
    List of EntityMediatedConnection objects
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## _generate_traversal_paths

```python
def _generate_traversal_paths(self, documents: List[DocumentNode], entity_connections: List[EntityMediatedConnection], reasoning_depth: str) -> List[List[str]]:
    """
    Generate document traversal paths for reasoning.

Args:
    documents: List of documents
    entity_connections: List of entity-mediated connections
    reasoning_depth: Reasoning depth

Returns:
    List of document traversal paths (lists of document IDs)
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## _get_relevant_documents

```python
def _get_relevant_documents(self, query: str, query_embedding: Optional[np.ndarray], input_documents: Optional[List[Dict[str, Any]]], vector_store: Optional[Any], max_documents: int = 10, min_relevance: float = 0.6) -> List[DocumentNode]:
    """
    Get relevant documents for the query.

Args:
    query: The query string
    query_embedding: The query embedding vector
    input_documents: Optional input documents
    vector_store: Vector store for similarity search
    max_documents: Maximum number of documents to return
    min_relevance: Minimum relevance score

Returns:
    List of DocumentNode objects
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## _synthesize_answer

```python
def _synthesize_answer(self, query: str, documents: List[DocumentNode], entity_connections: List[EntityMediatedConnection], traversal_paths: List[List[str]], reasoning_depth: str) -> Tuple[str, float]:
    """
    Synthesize an answer based on connected information.

Args:
    query: The query string
    documents: List of documents
    entity_connections: List of entity-mediated connections
    traversal_paths: List of document traversal paths
    reasoning_depth: Reasoning depth

Returns:
    Tuple of (answer, confidence)
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## dfs

```python
def dfs(current_doc, path, depth):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## example_usage

```python
def example_usage():
    """
    Example usage of the cross-document reasoner.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## explain_reasoning

```python
def explain_reasoning(self, reasoning_id: str) -> Dict[str, Any]:
    """
    Generate an explanation of the reasoning process.

Args:
    reasoning_id: ID of the reasoning process

Returns:
    Dict with explanation
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## get_statistics

```python
def get_statistics(self) -> Dict[str, Any]:
    """
    Get statistics about cross-document reasoning.

Returns:
    Dict with statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## reason_across_documents

```python
def reason_across_documents(self, query: str, query_embedding: Optional[np.ndarray] = None, input_documents: Optional[List[Dict[str, Any]]] = None, vector_store: Optional[Any] = None, knowledge_graph: Optional[Any] = None, reasoning_depth: str = "moderate", max_documents: int = 10, min_relevance: float = 0.6, max_hops: int = 2, return_trace: bool = False) -> Dict[str, Any]:
    """
    Perform cross-document reasoning to answer a query.

This method connects information across multiple documents through
shared entities, identifies complementary or contradictory information,
and generates a synthesized answer with confidence scores.

Args:
    query: Natural language query
    query_embedding: Query embedding vector (optional, will be computed if not provided)
    input_documents: Optional list of documents to start with
    vector_store: Vector store for similarity search
    knowledge_graph: Knowledge graph for entity and relationship information
    reasoning_depth: Depth of reasoning ("basic", "moderate", or "deep")
    max_documents: Maximum number of documents to consider
    min_relevance: Minimum relevance score for documents
    max_hops: Maximum hops for graph traversal
    return_trace: Whether to return the full reasoning trace

Returns:
    Dict containing:
        - answer: Synthesized answer to the query
        - documents: List of relevant documents used
        - entity_connections: List of entity-mediated connections
        - confidence: Confidence score
        - reasoning_trace: Optional reasoning trace
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner
