# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/graphrag_integration.py'

Files last updated: 1748635923.4313796

Stub file last updated: 2025-07-07 02:11:01

## CrossDocumentReasoner

```python
class CrossDocumentReasoner:
    """
    Implements cross-document reasoning capabilities for GraphRAG.

This class provides methods for reasoning across multiple documents
connected by shared entities, enabling more complex information synthesis.
Cross-document reasoning goes beyond simple retrieval to answer complex
queries by connecting information across multiple sources.

Key Features:
- Entity-mediated connections between documents
- Evidence chain discovery and validation
- Multi-document information synthesis
- Confidence scoring with uncertainty assessment
- Knowledge subgraph creation for focused reasoning
- Domain-aware processing for specialized contexts

The cross-document reasoning approach enables:
- Answering questions that require integrating multiple sources
- Identifying complementary or contradictory information
- Discovering non-obvious connections through shared entities
- Generating comprehensive, well-supported answers
- Providing explicit reasoning traces and evidence chains
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GraphRAGFactory

```python
class GraphRAGFactory:
    """
    Factory for creating and composing GraphRAG components.

This class provides methods for creating and composing various
GraphRAG components for different use cases and configurations.
It implements the Factory pattern to simplify the creation of
complex GraphRAG systems with appropriate component integration.

Key Features:
- Component creation with sensible defaults
- Easy composition of multiple components
- Configuration-driven system creation
- Component sharing and reference management
- Integration of complementary features

The factory enables various configurations:
- Basic vector search augmentation with HybridVectorGraphSearch
- LLM-enhanced reasoning with GraphRAGIntegration
- Cross-document reasoning with CrossDocumentReasoner
- Comprehensive query processing with GraphRAGQueryEngine
- Complete GraphRAG systems with all integrated components
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GraphRAGIntegration

```python
class GraphRAGIntegration:
    """
    Integration class for enhancing GraphRAG operations with LLM capabilities.

This class patches VectorAugmentedGraphDataset methods to incorporate
LLM reasoning without directly modifying the original class. It supports
domain-specific processing and performance monitoring. The integration
follows an extension pattern that preserves the original implementation
while adding enhanced capabilities.

Key Features:
- Non-intrusive patching of existing dataset methods
- LLM-enhanced cross-document reasoning
- Domain-specific content processing and adaptation
- Detailed reasoning tracing and visualization
- Performance monitoring and metrics collection
- Semantic validation of LLM outputs
- Confidence scoring and uncertainty assessment

The integration provides several enhancements:
- More sophisticated reasoning across multiple documents
- Domain-aware processing for specialized fields (academic, medical, legal, etc.)
- Detailed explanations of reasoning steps and confidence levels
- Enhanced information synthesis with semantic validation
- Comprehensive performance metrics for system optimization
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GraphRAGQueryEngine

```python
class GraphRAGQueryEngine:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GraphRAGQueryEngine

```python
class GraphRAGQueryEngine:
    """
    Query engine combining vector search and knowledge graph traversal.

This class provides a unified interface for querying across vector stores
and knowledge graphs, supporting multi-model embeddings and advanced query
optimization techniques.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## HybridVectorGraphSearch

```python
class HybridVectorGraphSearch:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## HybridVectorGraphSearch

```python
class HybridVectorGraphSearch:
    """
    Implements hybrid search combining vector similarity with graph traversal.

This class provides mechanisms for augmenting vector-based similarity search
with graph traversal to improve retrieval quality by considering both semantic
similarity and structural relationships. It enables a form of "graph-enhanced RAG"
where traditional vector retrieval is complemented by the rich relational
information in a knowledge graph.

Key Features:
- Combined scoring using both vector similarity and graph traversal
- Configurable weighting between vector and graph components
- Multi-hop graph expansion from seed nodes
- Bidirectional relationship traversal option
- Path-aware relevance scoring with hop distance penalties
- Entity-mediated search for connecting documents through shared entities
- Caching for performance optimization

The hybrid approach provides several advantages over pure vector or graph search:
- More comprehensive results capturing both semantic and relational relevance
- Ability to find relevant content not discoverable through vector similarity alone
- Enhanced precision through structural context
- Improved recall through relationship-based expansion
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, dataset, llm_processor: Optional[GraphRAGLLMProcessor] = None, performance_monitor: Optional[GraphRAGPerformanceMonitor] = None, validator: Optional[SemanticValidator] = None, validate_outputs: bool = True, enable_tracing: bool = True):
    """
    Initialize GraphRAG integration.

Args:
    dataset: The VectorAugmentedGraphDataset instance to enhance
    llm_processor: Optional LLM processor to use
    performance_monitor: Optional performance monitor
    validator: Optional semantic validator
    tracing_manager: Optional tracing manager
    validate_outputs: Whether to validate and augment LLM outputs
    enable_tracing: Whether to enable detailed reasoning tracing
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegration

## __init__

```python
def __init__(self, dataset, vector_weight: float = 0.6, graph_weight: float = 0.4, max_graph_hops: int = 2, min_score_threshold: float = 0.5, use_bidirectional_traversal: bool = True):
    """
    Initialize hybrid search.

Args:
    dataset: VectorAugmentedGraphDataset instance
    vector_weight: Weight for vector similarity scores (0.0 to 1.0)
    graph_weight: Weight for graph traversal scores (0.0 to 1.0)
    max_graph_hops: Maximum graph traversal hops from seed nodes
    min_score_threshold: Minimum score threshold for results
    use_bidirectional_traversal: Whether to traverse relationships in both directions
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## __init__

```python
def __init__(self, dataset, hybrid_search: Optional[HybridVectorGraphSearch] = None, llm_integration: Optional[GraphRAGIntegration] = None):
    """
    Initialize cross-document reasoner.

Args:
    dataset: VectorAugmentedGraphDataset instance
    hybrid_search: Optional hybrid search instance
    llm_integration: Optional LLM integration instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## __init__

```python
def __init__(self, dataset, vector_stores: Dict[str, Any], graph_store: Any, model_weights: Optional[Dict[str, float]] = None, hybrid_search: Optional[HybridVectorGraphSearch] = None, llm_integration: Optional[GraphRAGIntegration] = None, query_optimizer = None, enable_cross_document_reasoning: bool = True, enable_query_rewriting: bool = True, enable_budget_management: bool = True):
    """
    Initialize the GraphRAG query engine.

Args:
    dataset: The underlying vector-augmented graph dataset
    vector_stores: Dictionary mapping model names to vector stores
    graph_store: Knowledge graph store instance
    model_weights: Optional weights for each model's results
    hybrid_search: Optional hybrid search instance
    llm_integration: Optional LLM integration instance
    query_optimizer: Optional query optimizer instance
    enable_cross_document_reasoning: Whether to enable cross-document reasoning
    enable_query_rewriting: Whether to enable query rewriting
    enable_budget_management: Whether to enable budget management
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryEngine

## _basic_synthesis

```python
def _basic_synthesis(self, query: str, documents: List[Dict[str, Any]], evidence_chains: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Simple information synthesis without LLM.

Args:
    query: User query
    documents: List of relevant documents
    evidence_chains: List of evidence chains

Returns:
    Synthesis results
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## _compute_query_embeddings

```python
def _compute_query_embeddings(self, query_text: str) -> Dict[str, np.ndarray]:
    """
    Compute embeddings for the query across all models.

Args:
    query_text: Query text to embed

Returns:
    Dictionary mapping model names to embeddings
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryEngine

## _compute_similarity

```python
def _compute_similarity(self, query_embedding: np.ndarray, node_embedding: np.ndarray) -> float:
    """
    Compute similarity between query and node embeddings.

Args:
    query_embedding: Query embedding vector
    node_embedding: Node embedding vector

Returns:
    Similarity score
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## _enhanced_synthesize_cross_document_information

```python
def _enhanced_synthesize_cross_document_information(self, query: str, documents: List[Tuple[Any, float]], evidence_chains: List[Dict[str, Any]], reasoning_depth: str) -> Dict[str, Any]:
    """
    Enhanced method for synthesizing information across documents using LLM.

Args:
    query: User query
    documents: List of relevant documents with scores
    evidence_chains: Document evidence chains
    reasoning_depth: Reasoning depth level

Returns:
    Synthesized information
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegration

## _expand_through_graph

```python
def _expand_through_graph(self, seed_results: List[Dict[str, Any]], max_hops: int, relationship_types: Optional[List[str]] = None, entity_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Expand seed results through graph traversal.

Args:
    seed_results: Initial seed results from vector search
    max_hops: Maximum number of hops for traversal
    relationship_types: Types of relationships to traverse
    entity_types: Types of entities to include

Returns:
    List of expanded results with traversal paths
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## _find_connected_document_pairs

```python
def _find_connected_document_pairs(self, connecting_entities: List[Dict[str, Any]], seed_documents: List[Dict[str, Any]], doc_ids: List[str], top_k: int) -> List[Dict[str, Any]]:
    """
    Find document pairs connected by common entities.

Args:
    connecting_entities: List of connecting entities
    seed_documents: List of seed document results
    doc_ids: List of document IDs
    top_k: Number of document pairs to return

Returns:
    List of connected document pairs
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## _find_connecting_entities

```python
def _find_connecting_entities(self, doc_ids: List[str], entity_types: List[str], max_entities: int) -> List[Dict[str, Any]]:
    """
    Find entities connected to multiple documents.

Args:
    doc_ids: List of document IDs
    entity_types: Types of entities to consider
    max_entities: Maximum number of entities to return

Returns:
    List of connecting entities with their connections
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## _get_document_context

```python
def _get_document_context(self, doc_id: str, max_length: int = 500) -> str:
    """
    Get context from a document.

Args:
    doc_id: Document ID
    max_length: Maximum context length

Returns:
    Document context as string
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## _get_graph_info

```python
def _get_graph_info(self) -> Dict[str, Any]:
    """
    Get information about the graph for domain detection.

Returns:
    Dictionary of graph information
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegration

## _get_neighbors

```python
def _get_neighbors(self, node_id: str, relationship_types: Optional[List[str]], entity_types: Optional[List[str]], hop_count: int) -> List[Tuple[str, str, float]]:
    """
    Get neighboring nodes for a given node.

Args:
    node_id: ID of the node
    relationship_types: Types of relationships to traverse
    entity_types: Types of entities to include
    hop_count: Current hop count

Returns:
    List of tuples (neighbor_id, relationship_type, weight)
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## _patch_methods

```python
def _patch_methods(self):
    """
    Patch dataset methods with enhanced versions.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegration

## _perform_vector_search

```python
def _perform_vector_search(self, query_embedding: np.ndarray, top_k: int, min_score: float = 0.0, entity_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Perform vector similarity search to find seed nodes.

Args:
    query_embedding: Query embedding vector
    top_k: Number of results to return
    min_score: Minimum similarity score
    entity_types: Types of entities to include

Returns:
    List of vector search results
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## _perform_vector_search

```python
def _perform_vector_search(self, query_embeddings: Dict[str, np.ndarray], top_k: int = 10, min_relevance: float = 0.5) -> Dict[str, List[Dict[str, Any]]]:
    """
    Perform vector search across all models.

Args:
    query_embeddings: Dictionary mapping model names to embeddings
    top_k: Number of results to return per model
    min_relevance: Minimum relevance score

Returns:
    Dictionary mapping model names to search results
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryEngine

## _record_performance

```python
def _record_performance(self, operation: str, metrics: Dict[str, Any]) -> None:
    """
    Record performance metrics.

Args:
    operation: Name of the operation
    metrics: Performance metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegration

## _score_and_rank_results

```python
def _score_and_rank_results(self, query_embedding: np.ndarray, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Score and rank the combined results.

Args:
    query_embedding: Original query embedding
    results: Combined results from vector search and graph traversal

Returns:
    Ranked results
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## _synthesize_with_llm

```python
def _synthesize_with_llm(self, query: str, documents: List[Dict[str, Any]], evidence_chains: List[Dict[str, Any]], reasoning_depth: str) -> Dict[str, Any]:
    """
    Synthesize information using LLM integration.

Args:
    query: User query
    documents: List of relevant documents
    evidence_chains: List of evidence chains
    reasoning_depth: Reasoning depth level

Returns:
    Synthesis results
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## create_complete_integration

```python
@staticmethod
def create_complete_integration(dataset, vector_weight: float = 0.6, graph_weight: float = 0.4, max_graph_hops: int = 2, validate_outputs: bool = True, enable_tracing: bool = True) -> Tuple[HybridVectorGraphSearch, GraphRAGIntegration, CrossDocumentReasoner]:
    """
    Create a complete GraphRAG integration with hybrid search, LLM enhancement,
and cross-document reasoning.

Args:
    dataset: VectorAugmentedGraphDataset instance
    vector_weight: Weight for vector similarity scores
    graph_weight: Weight for graph traversal scores
    max_graph_hops: Maximum graph traversal hops
    validate_outputs: Whether to validate outputs
    enable_tracing: Whether to enable tracing

Returns:
    Tuple of (HybridVectorGraphSearch, GraphRAGIntegration, CrossDocumentReasoner)
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGFactory

## create_cross_document_reasoner

```python
@staticmethod
def create_cross_document_reasoner(dataset, hybrid_search: Optional[HybridVectorGraphSearch] = None, llm_integration: Optional[GraphRAGIntegration] = None) -> CrossDocumentReasoner:
    """
    Create a cross-document reasoner.

Args:
    dataset: VectorAugmentedGraphDataset instance
    hybrid_search: Optional hybrid search instance
    llm_integration: Optional LLM integration instance

Returns:
    CrossDocumentReasoner instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGFactory

## create_graphrag_system

```python
@staticmethod
def create_graphrag_system(dataset, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create a complete GraphRAG system with configuration options.

Args:
    dataset: VectorAugmentedGraphDataset instance
    config: Configuration options for the GraphRAG system
           (vector_weight, graph_weight, max_graph_hops, etc.)

Returns:
    Dictionary of GraphRAG components
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGFactory

## create_hybrid_search

```python
@staticmethod
def create_hybrid_search(dataset, vector_weight: float = 0.6, graph_weight: float = 0.4, max_graph_hops: int = 2, min_score_threshold: float = 0.5, use_bidirectional_traversal: bool = True) -> HybridVectorGraphSearch:
    """
    Create a hybrid vector + graph search for a dataset.

Args:
    dataset: VectorAugmentedGraphDataset instance
    vector_weight: Weight for vector similarity scores
    graph_weight: Weight for graph traversal scores
    max_graph_hops: Maximum graph traversal hops
    min_score_threshold: Minimum score threshold
    use_bidirectional_traversal: Whether to traverse in both directions

Returns:
    HybridVectorGraphSearch instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGFactory

## create_knowledge_subgraph

```python
def create_knowledge_subgraph(self, evidence_chains: List[Dict[str, Any]]) -> KnowledgeGraph:
    """
    Create a focused knowledge graph from evidence chains.

Args:
    evidence_chains: List of evidence chains

Returns:
    KnowledgeGraph representing the evidence network
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## create_llm_integration

```python
@staticmethod
def create_llm_integration(dataset, validate_outputs: bool = True, llm_processor: Optional[GraphRAGLLMProcessor] = None, performance_monitor: Optional[GraphRAGPerformanceMonitor] = None, validator: Optional[SemanticValidator] = None, enable_tracing: bool = True) -> GraphRAGIntegration:
    """
    Create an LLM-enhanced integration for a dataset.

Args:
    dataset: VectorAugmentedGraphDataset instance
    validate_outputs: Whether to validate outputs
    llm_processor: Optional LLM processor
    performance_monitor: Optional performance monitor
    validator: Optional semantic validator
    tracing_manager: Optional tracing manager
    enable_tracing: Whether to enable tracing

Returns:
    GraphRAGIntegration instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGFactory

## create_query_engine

```python
@staticmethod
def create_query_engine(dataset, vector_stores: Dict[str, Any], graph_store: Any, model_weights: Optional[Dict[str, float]] = None, query_optimizer = None, hybrid_search: Optional[HybridVectorGraphSearch] = None, llm_integration: Optional[GraphRAGIntegration] = None, enable_cross_document_reasoning: bool = True, enable_query_rewriting: bool = True, enable_budget_management: bool = True) -> GraphRAGQueryEngine:
    """
    Create a GraphRAG query engine.

Args:
    dataset: VectorAugmentedGraphDataset instance
    vector_stores: Dictionary mapping model names to vector stores
    graph_store: Knowledge graph store instance
    model_weights: Optional weights for each model's results
    query_optimizer: Optional query optimizer instance
    hybrid_search: Optional hybrid search instance
    llm_integration: Optional LLM integration instance
    enable_cross_document_reasoning: Whether to enable cross-document reasoning
    enable_query_rewriting: Whether to enable query rewriting
    enable_budget_management: Whether to enable budget management

Returns:
    GraphRAGQueryEngine instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGFactory

## enhance_dataset_with_hybrid_search

```python
def enhance_dataset_with_hybrid_search(dataset, vector_weight: float = 0.6, graph_weight: float = 0.4, max_graph_hops: int = 2, min_score_threshold: float = 0.5, use_bidirectional_traversal: bool = True) -> HybridVectorGraphSearch:
    """
    Enhance a dataset with hybrid vector + graph search capabilities.

Args:
    dataset: VectorAugmentedGraphDataset instance
    vector_weight: Weight for vector similarity scores (0.0 to 1.0)
    graph_weight: Weight for graph traversal scores (0.0 to 1.0)
    max_graph_hops: Maximum graph traversal hops from seed nodes
    min_score_threshold: Minimum score threshold for results
    use_bidirectional_traversal: Whether to traverse relationships in both directions

Returns:
    HybridVectorGraphSearch instance attached to the dataset
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## enhance_dataset_with_llm

```python
def enhance_dataset_with_llm(dataset, validate_outputs: bool = True, llm_processor: Optional[GraphRAGLLMProcessor] = None, performance_monitor: Optional[GraphRAGPerformanceMonitor] = None, validator: Optional[SemanticValidator] = None, enable_tracing: bool = True) -> GraphRAGIntegration:
    """
    Enhance a VectorAugmentedGraphDataset with LLM capabilities.

Args:
    dataset: VectorAugmentedGraphDataset instance
    validate_outputs: Whether to validate and enhance LLM outputs
    llm_processor: Optional LLM processor to use
    performance_monitor: Optional performance monitor
    validator: Optional semantic validator
    tracing_manager: Optional tracing manager
    enable_tracing: Whether to enable detailed reasoning tracing

Returns:
    The same dataset instance with enhanced capabilities
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## entity_mediated_search

```python
def entity_mediated_search(self, query_embedding: np.ndarray, entity_types: List[str], top_k: int = 10, max_connecting_entities: int = 5) -> List[Dict[str, Any]]:
    """
    Perform entity-mediated search to find connected documents.

This search method finds documents that share common entities,
enabling cross-document reasoning.

Args:
    query_embedding: Query embedding vector
    entity_types: Types of entities to consider as connectors
    top_k: Number of final results to return
    max_connecting_entities: Maximum number of connecting entities to use

Returns:
    List of connected document pairs with connecting entities
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## example_graphrag_usage

```python
def example_graphrag_usage(dataset, query: str) -> Dict[str, Any]:
    """
    Example function demonstrating a complete GraphRAG workflow.

This function shows a comprehensive workflow for using the GraphRAG system:
1. Initialize the GraphRAG components with factory
2. Convert query to embeddings (potentially using multiple models)
3. Perform hybrid search combining vector similarity and graph traversal
4. Find evidence chains for cross-document reasoning through entity-mediated connections
5. Synthesize information across documents using cross-document reasoning
6. Generate visualizations and explanations of the reasoning process

Args:
    dataset: VectorAugmentedGraphDataset instance
    query: User query as string

Returns:
    Dictionary containing:
    - query: Original query
    - search_results: Results from hybrid search
    - evidence_chains: Connections between documents via shared entities
    - reasoning_result: Cross-document reasoning result with synthesized answer
    - subgraph_entity_count: Number of entities in the knowledge subgraph
    - subgraph_relationship_count: Number of relationships in the knowledge subgraph
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## explain_query_result

```python
def explain_query_result(self, result: Dict[str, Any], explanation_type: str = "summary", target_audience: str = "general") -> Dict[str, Any]:
    """
    Generate an explanation for a query result.

Args:
    result: Query result to explain
    explanation_type: Type of explanation ('summary', 'detailed', 'technical')
    target_audience: Target audience ('general', 'technical', 'expert')

Returns:
    Explanation data
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryEngine

## explain_trace

```python
def explain_trace(self, trace_id: str, explanation_type: str = "summary", target_audience: str = "general") -> Dict[str, Any]:
    """
    Generate an explanation for a reasoning trace.

Args:
    trace_id: ID of the trace to explain
    explanation_type: Type of explanation ('summary', 'detailed', 'critical_path', 'confidence')
    target_audience: Target audience ('general', 'technical', 'expert')

Returns:
    Explanation data
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegration

## find_evidence_chains

```python
def find_evidence_chains(self, query_embedding: np.ndarray, entity_types: List[str] = ['concept', 'entity', 'topic'], max_docs: int = 10, max_entities: int = 5, min_doc_score: float = 0.6) -> List[Dict[str, Any]]:
    """
    Find evidence chains connecting documents.

Args:
    query_embedding: Query embedding vector
    entity_types: Types of entities to consider as connectors
    max_docs: Maximum number of documents to consider
    max_entities: Maximum number of connecting entities to use
    min_doc_score: Minimum document relevance score

Returns:
    List of evidence chains with connected documents and entities
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## get_metrics

```python
def get_metrics(self) -> Dict[str, Any]:
    """
    Get search performance metrics.

Returns:
    Dictionary of search metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## get_metrics

```python
def get_metrics(self) -> Dict[str, Any]:
    """
    Get cross-document reasoning metrics.

Returns:
    Dictionary of metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## get_metrics

```python
def get_metrics(self) -> Dict[str, Any]:
    """
    Get query engine metrics.

Returns:
    Dictionary of metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryEngine

## get_performance_metrics

```python
def get_performance_metrics(self) -> Dict[str, Any]:
    """
    Get performance metrics for the integration.

Returns:
    Dictionary of performance metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegration

## get_reasoning_trace

```python
def get_reasoning_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a reasoning trace by ID.
Args:
    trace_id: ID of the trace to get

Returns:
    Trace data or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegration

## get_recent_traces

```python
def get_recent_traces(self, limit: int = 10, query_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get a list of recent reasoning traces.
Args:
    limit: Maximum number of traces to return
    query_filter: Optional filter by query text

Returns:
    List of trace summaries
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegration

## hybrid_search

```python
def hybrid_search(self, query_embedding: np.ndarray, top_k: int = 10, relationship_types: Optional[List[str]] = None, entity_types: Optional[List[str]] = None, min_vector_score: float = 0.0, rerank_with_llm: bool = False) -> List[Dict[str, Any]]:
    """
    Perform hybrid vector + graph search.

Args:
    query_embedding: Query embedding vector
    top_k: Number of results to return
    relationship_types: Types of relationships to traverse
    entity_types: Types of entities to include
    min_vector_score: Minimum vector similarity score
    rerank_with_llm: Whether to rerank results with LLM

Returns:
    List of search results with scores and traversal paths
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridVectorGraphSearch

## query

```python
def query(self, query_text: str, query_embeddings: Optional[Dict[str, np.ndarray]] = None, top_k: int = 10, include_vector_results: bool = True, include_graph_results: bool = True, include_cross_document_reasoning: bool = True, entity_types: Optional[List[str]] = None, relationship_types: Optional[List[str]] = None, min_relevance: float = 0.5, max_graph_hops: int = 2, reasoning_depth: str = "moderate", return_trace: bool = False) -> Dict[str, Any]:
    """
    Perform a GraphRAG query combining vector search and graph traversal.

Args:
    query_text: Natural language query text
    query_embeddings: Optional pre-computed embeddings for each model
    top_k: Number of results to return
    include_vector_results: Whether to include vector search results
    include_graph_results: Whether to include graph traversal results
    include_cross_document_reasoning: Whether to include cross-document reasoning
    entity_types: Types of entities to include in traversal
    relationship_types: Types of relationships to traverse
    min_relevance: Minimum relevance score for results
    max_graph_hops: Maximum graph traversal hops
    reasoning_depth: Reasoning depth for cross-document reasoning
    return_trace: Whether to return reasoning trace

Returns:
    Dictionary containing query results, potentially including:
    - vector_results: Results from vector search
    - graph_results: Results from graph traversal
    - hybrid_results: Combined results from hybrid search
    - evidence_chains: Cross-document evidence chains
    - reasoning_result: Result of cross-document reasoning
    - trace_id: ID of the reasoning trace if return_trace is True
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryEngine

## reason_across_documents

```python
def reason_across_documents(self, query: str, query_embedding: np.ndarray, reasoning_depth: str = "moderate", entity_types: List[str] = ['concept', 'entity', 'topic'], max_docs: int = 10, max_evidence_chains: int = 5) -> Dict[str, Any]:
    """
    Reason across multiple documents to answer a query.

Args:
    query: User query
    query_embedding: Query embedding vector
    reasoning_depth: Reasoning depth ('basic', 'moderate', 'deep')
    entity_types: Types of entities to consider as connectors
    max_docs: Maximum number of documents to consider
    max_evidence_chains: Maximum number of evidence chains to use

Returns:
    Reasoning results with answer and explanation
    """
```
* **Async:** False
* **Method:** True
* **Class:** CrossDocumentReasoner

## visualize_query_result

```python
def visualize_query_result(self, result: Dict[str, Any], format: str = "text") -> Dict[str, Any]:
    """
    Generate a visualization of a query result.

Args:
    result: Query result to visualize
    format: Visualization format ('text', 'html', 'mermaid')

Returns:
    Visualization data
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryEngine

## visualize_trace

```python
def visualize_trace(self, trace_id: str, format: str = "text") -> Dict[str, Any]:
    """
    Generate a visualization of a reasoning trace.

Args:
    trace_id: ID of the trace to visualize
    format: Visualization format ('text', 'html', 'mermaid')

Returns:
    Visualization data
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegration
