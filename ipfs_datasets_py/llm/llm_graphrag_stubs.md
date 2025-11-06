# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/llm/llm_graphrag.py'

Files last updated: 1751437214.7733295

Stub file last updated: 2025-07-07 02:15:51

## DomainSpecificProcessor

```python
class DomainSpecificProcessor:
    """
    Tailors reasoning for specific knowledge domains.

This class provides domain-specific processing for GraphRAG tasks,
adapting the reasoning approach and prompt templates to different
knowledge domains and content types.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GraphRAGLLMProcessor

```python
class GraphRAGLLMProcessor:
    """
    Processor for enhancing GraphRAG operations with LLM capabilities.

This class serves as the integration layer between the VectorAugmentedGraphDataset
and the LLM interface, providing methods for using LLMs to enhance
various GraphRAG operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GraphRAGPerformanceMonitor

```python
class GraphRAGPerformanceMonitor:
    """
    Tracks and optimizes LLM performance in GraphRAG tasks.

This class monitors the performance of LLM interactions in GraphRAG tasks,
collects metrics, and provides insights for optimization.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ReasoningEnhancer

```python
class ReasoningEnhancer:
    """
    Enhances cross-document reasoning with LLM capabilities.

This class provides a bridge between the VectorAugmentedGraphDataset's
cross_document_reasoning method and LLM-powered analysis.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, max_history: int = 1000):
    """
    Initialize performance monitor.

Args:
    max_history: Maximum number of interactions to track
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPerformanceMonitor

## __init__

```python
def __init__(self, adaptive_prompting: AdaptivePrompting, default_domain: str = "academic"):
    """
    Initialize domain-specific processor.

Args:
    adaptive_prompting: Adaptive prompting module
    default_domain: Default domain to use if detection fails
    """
```
* **Async:** False
* **Method:** True
* **Class:** DomainSpecificProcessor

## __init__

```python
def __init__(self, llm_interface: Optional[LLMInterface] = None, prompt_library: Optional[PromptLibrary] = None, performance_monitor: Optional[GraphRAGPerformanceMonitor] = None, query_optimizer: Optional['UnifiedGraphRAGQueryOptimizer'] = None):
    """
    Initialize GraphRAG LLM processor.

Args:
    llm_interface: LLM interface to use (creates default if None)
    prompt_library: Prompt library for managing templates
    performance_monitor: Monitor for tracking performance
    query_optimizer: Query optimizer for GraphRAG operations
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## __init__

```python
def __init__(self, llm_processor: Optional[GraphRAGLLMProcessor] = None, performance_recorder: Optional[Callable[[str, Dict[str, Any]], None]] = None, query_optimizer: Optional['UnifiedGraphRAGQueryOptimizer'] = None):
    """
    Initialize reasoning enhancer.

Args:
    llm_processor: LLM processor to use (creates default if None)
    performance_recorder: Optional function to record performance metrics
    query_optimizer: Query optimizer for GraphRAG operations
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningEnhancer

## _create_domain_detector

```python
def _create_domain_detector(self, domain: str, info: Dict[str, Any]) -> Callable[[Dict[str, Any]], float]:
    """
    Create domain detection function.

Args:
    domain: Domain name
    info: Domain information

Returns:
    Function that detects domain applicability
    """
```
* **Async:** False
* **Method:** True
* **Class:** DomainSpecificProcessor

## _create_template_selector

```python
def _create_template_selector(self, domain: str, info: Dict[str, Any]) -> Callable[[Dict[str, Any]], Tuple[str, Optional[str]]]:
    """
    Create template selection function.

Args:
    domain: Domain name
    info: Domain information

Returns:
    Function that selects templates based on domain
    """
```
* **Async:** False
* **Method:** True
* **Class:** DomainSpecificProcessor

## _enhance_result_for_domain

```python
def _enhance_result_for_domain(self, result: Dict[str, Any], domain: str, reasoning_depth: str) -> Dict[str, Any]:
    """
    Enhance result based on domain and reasoning depth.

Args:
    result: Original result
    domain: Domain name
    reasoning_depth: Reasoning depth level

Returns:
    Enhanced result
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## _format_connections_for_llm

```python
def _format_connections_for_llm(self, connections: List[Dict[str, Any]], reasoning_depth: str) -> str:
    """
    Format document connections for LLM prompt.

Args:
    connections: List of document connections
    reasoning_depth: Reasoning depth level

Returns:
    Formatted connection text
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningEnhancer

## _format_documents_for_domain

```python
def _format_documents_for_domain(self, documents: List[Dict[str, Any]], domain: str) -> str:
    """
    Format documents based on domain.

Args:
    documents: List of documents
    domain: Domain name

Returns:
    Formatted document text
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## _get_cross_document_reasoning_schema

```python
def _get_cross_document_reasoning_schema(self, domain: str, reasoning_depth: str) -> Dict[str, Any]:
    """
    Get cross document reasoning schema for a specific domain and reasoning depth.

Args:
    domain: Domain name
    reasoning_depth: Reasoning depth level

Returns:
    JSON schema for cross document reasoning
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## _get_evidence_chain_schema

```python
def _get_evidence_chain_schema(self, domain: str) -> Dict[str, Any]:
    """
    Get evidence chain schema for a specific domain.

Args:
    domain: Domain name

Returns:
    JSON schema for evidence chain analysis
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## _initialize_domain_rules

```python
def _initialize_domain_rules(self) -> None:
    """
    Initialize domain detection rules.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DomainSpecificProcessor

## _is_domain_applicable

```python
def _is_domain_applicable(self, context: Dict[str, Any], domain: str) -> bool:
    """
    Check if domain is applicable to context.

Args:
    context: Context dictionary
    domain: Domain to check

Returns:
    True if domain is applicable
    """
```
* **Async:** False
* **Method:** True
* **Class:** DomainSpecificProcessor

## analyze_evidence_chain

```python
def analyze_evidence_chain(self, doc1: Dict[str, Any], doc2: Dict[str, Any], entity: Dict[str, Any], doc1_context: str, doc2_context: str, graph_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Analyze evidence chain between two documents connected by an entity.

Args:
    doc1: First document metadata
    doc2: Second document metadata
    entity: Connecting entity metadata
    doc1_context: Relevant context from first document
    doc2_context: Relevant context from second document
    graph_info: Additional information about the graph

Returns:
    Analysis of the evidence chain
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## analyze_transitive_relationships

```python
def analyze_transitive_relationships(self, relationship_chain: str) -> Dict[str, Any]:
    """
    Analyze transitive relationships in an entity chain.

Args:
    relationship_chain: Description of entity relationship chain

Returns:
    Analysis of transitive relationships
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## detect_domain

```python
def detect_domain(self, context: Dict[str, Any]) -> str:
    """
    Detect domain from context.

Args:
    context: Context dictionary

Returns:
    Detected domain or default domain
    """
```
* **Async:** False
* **Method:** True
* **Class:** DomainSpecificProcessor

## detector

```python
def detector(context: Dict[str, Any]) -> float:
    """
    Detect domain applicability.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## enhance_context_with_domain

```python
def enhance_context_with_domain(self, context: Dict[str, Any], domain: Optional[str] = None) -> Dict[str, Any]:
    """
    Enhance context with domain-specific information.

Args:
    context: Context dictionary
    domain: Domain to use (detected if None)

Returns:
    Enhanced context
    """
```
* **Async:** False
* **Method:** True
* **Class:** DomainSpecificProcessor

## enhance_cross_document_reasoning

```python
def enhance_cross_document_reasoning(self, query: str, documents: List[Dict[str, Any]], connections: List[Dict[str, Any]], reasoning_depth: str, graph_info: Optional[Dict[str, Any]] = None, query_vector: Optional[np.ndarray] = None, doc_trace_ids: Optional[List[str]] = None, root_cids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Enhance cross-document reasoning results with LLM synthesis.

Args:
    query: User query
    documents: List of relevant documents
    connections: List of document connections
    reasoning_depth: Reasoning depth level
    graph_info: Additional information about the graph
    query_vector: Query embedding vector for optimizer
    doc_trace_ids: Document trace IDs for Wikipedia knowledge graphs
    root_cids: Root CIDs for IPLD-based knowledge graphs

Returns:
    Enhanced reasoning results
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningEnhancer

## enhance_document_connections

```python
def enhance_document_connections(self, doc1: Dict[str, Any], doc2: Dict[str, Any], entity: Dict[str, Any], doc1_context: str, doc2_context: str, reasoning_depth: str, graph_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Enhance document connection analysis with LLM reasoning.

Args:
    doc1: First document metadata
    doc2: Second document metadata
    entity: Connecting entity metadata
    doc1_context: Relevant context from first document
    doc2_context: Relevant context from second document
    reasoning_depth: Reasoning depth level
    graph_info: Additional information about the graph

Returns:
    Enhanced connection analysis
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningEnhancer

## expand_by_graph

```python
def expand_by_graph(self, entities: List[Dict[str, Any]], max_depth: int = 2, edge_types: Optional[List[str]] = None, **kwargs) -> List[Dict[str, Any]]:
    """
    Perform graph expansion using the initialized graph store.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## generate_deep_inference

```python
def generate_deep_inference(self, entity: Dict[str, Any], doc1: Dict[str, Any], doc2: Dict[str, Any], doc1_info: str, doc2_info: str, relation_type: str, knowledge_gaps: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate deep inferences from document relationships.

Args:
    entity: Entity metadata
    doc1: First document metadata
    doc2: Second document metadata
    doc1_info: Information from first document
    doc2_info: Information from second document
    relation_type: Type of relationship between documents
    knowledge_gaps: Identified knowledge gaps

Returns:
    Generated inferences
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## get_domain_info

```python
def get_domain_info(self, domain: str) -> Dict[str, Any]:
    """
    Get information about a domain.

Args:
    domain: Domain name

Returns:
    Domain information
    """
```
* **Async:** False
* **Method:** True
* **Class:** DomainSpecificProcessor

## get_error_summary

```python
def get_error_summary(self) -> Dict[str, int]:
    """
    Get summary of errors.

Returns:
    Dictionary of error messages and their counts
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPerformanceMonitor

## get_latency_percentiles

```python
def get_latency_percentiles(self, model: Optional[str] = None, task: Optional[str] = None) -> Dict[str, float]:
    """
    Get latency percentiles.

Args:
    model: Filter by model name
    task: Filter by task type

Returns:
    Dictionary of percentiles and their values
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPerformanceMonitor

## get_model_metrics

```python
def get_model_metrics(self, model: Optional[str] = None) -> Dict[str, Any]:
    """
    Get metrics for a specific model or all models.

Args:
    model: Specific model to get metrics for (all if None)

Returns:
    Model metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPerformanceMonitor

## get_recent_interactions

```python
def get_recent_interactions(self, count: int = 10, task: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get recent interactions.

Args:
    count: Number of interactions to retrieve
    task: Filter by task type

Returns:
    List of recent interactions
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPerformanceMonitor

## get_task_metrics

```python
def get_task_metrics(self, task: Optional[str] = None) -> Dict[str, Any]:
    """
    Get metrics for a specific task or all tasks.

Args:
    task: Specific task to get metrics for (all if None)

Returns:
    Task metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPerformanceMonitor

## identify_knowledge_gaps

```python
def identify_knowledge_gaps(self, entity: Dict[str, Any], doc1_info: str, doc2_info: str) -> Dict[str, Any]:
    """
    Identify knowledge gaps between documents about an entity.

Args:
    entity: Entity metadata
    doc1_info: Information from first document
    doc2_info: Information from second document

Returns:
    Identified knowledge gaps
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## optimize_and_reason

```python
def optimize_and_reason(self, query: str, query_vector: np.ndarray, documents: List[Dict[str, Any]], connections: List[Dict[str, Any]], reasoning_depth: str = "moderate", graph_info: Optional[Dict[str, Any]] = None, doc_trace_ids: Optional[List[str]] = None, root_cids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Perform optimized cross-document reasoning using both query optimization and LLM synthesis.

This is a convenience method that combines query optimization and cross-document reasoning
in a single call, providing a streamlined interface for GraphRAG operations.

Args:
    query: User query text
    query_vector: Query embedding vector
    documents: List of relevant documents
    connections: List of document connections
    reasoning_depth: Reasoning depth level (basic, moderate, deep)
    graph_info: Additional information about the graph
    doc_trace_ids: Document trace IDs for Wikipedia knowledge graphs
    root_cids: Root CIDs for IPLD-based knowledge graphs

Returns:
    Dict: Enhanced reasoning results with optimization information
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningEnhancer

## rank_results

```python
def rank_results(self, results: List[Dict[str, Any]], vector_weight: float = 0.7, graph_weight: float = 0.3, **kwargs) -> List[Dict[str, Any]]:
    """
    Rank combined results from vector search and graph expansion.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## record_interaction

```python
def record_interaction(self, task: str, model: str, input_tokens: int, output_tokens: int, latency: float, success: bool, error_msg: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Record an LLM interaction.

Args:
    task: Type of task performed
    model: Name of the model used
    input_tokens: Number of input tokens
    output_tokens: Number of output tokens
    latency: Time taken for the interaction
    success: Whether the interaction was successful
    error_msg: Error message if unsuccessful
    metadata: Additional metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGPerformanceMonitor

## search_by_vector

```python
def search_by_vector(self, vector: np.ndarray, top_k: int = 5, min_score: float = 0.5, **kwargs) -> List[Dict[str, Any]]:
    """
    Perform vector search using the initialized vector store.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor

## selector

```python
def selector(context: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """
    Select template based on domain.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## synthesize_cross_document_reasoning

```python
def synthesize_cross_document_reasoning(self, query: str, documents: List[Dict[str, Any]], connections: str, reasoning_depth: str, graph_info: Optional[Dict[str, Any]] = None, query_vector: Optional[np.ndarray] = None, doc_trace_ids: Optional[List[str]] = None, root_cids: Optional[List[str]] = None, skip_cache: bool = False) -> Dict[str, Any]:
    """
    Synthesize information across documents to answer a query, potentially using query optimization.

Args:
    query: User query
    documents: List of relevant documents
    connections: Description of document connections
    reasoning_depth: Reasoning depth level
    graph_info: Additional information about the graph
    query_vector: Query embedding vector for optimizer
    doc_trace_ids: Document trace IDs for Wikipedia knowledge graphs
    root_cids: Root CIDs for IPLD-based knowledge graphs

Returns:
    Synthesized answer
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGLLMProcessor
