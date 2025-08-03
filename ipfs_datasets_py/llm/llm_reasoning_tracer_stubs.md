# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/llm/llm_reasoning_tracer.py'

Files last updated: 1751428797.8980403

Stub file last updated: 2025-07-07 02:15:51

## LLMReasoningTracer

```python
class LLMReasoningTracer:
    """
    Tracer for GraphRAG reasoning using LLMs.

This is a mock implementation that defines the interfaces but leaves
the actual LLM integration for future work.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ReasoningEdge

```python
@dataclass
class ReasoningEdge:
    """
    An edge in a reasoning trace.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ReasoningNode

```python
@dataclass
class ReasoningNode:
    """
    A node in a reasoning trace.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ReasoningNodeType

```python
class ReasoningNodeType(Enum):
    """
    Types of reasoning nodes in a reasoning trace.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ReasoningTrace

```python
@dataclass
class ReasoningTrace:
    """
    A complete reasoning trace.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WikipediaKnowledgeGraphTracer

```python
class WikipediaKnowledgeGraphTracer:
    """
    Specialized tracer for Wikipedia knowledge graph extraction and validation.

This class provides tracing capabilities specific to Wikipedia knowledge graphs,
with support for:
- Entity extraction tracing
- Relationship extraction tracing
- SPARQL validation against Wikidata
- Extraction confidence scoring
- Visualization of extraction steps
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, storage_dir: Optional[str] = None, llm_provider: str = "mock", llm_config: Optional[Dict[str, Any]] = None):
    """
    Initialize the reasoning tracer.

Args:
    storage_dir: Directory for storing traces
    llm_provider: LLM provider to use ("mock" for now, future: "openai", "anthropic", etc.)
    llm_config: Configuration for the LLM provider
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## __init__

```python
def __init__(self, enable_wikidata_validation: bool = True):
    """
    Initialize Wikipedia knowledge graph tracer.

Args:
    enable_wikidata_validation: Whether to enable validation against Wikidata
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## _get_html_visualization

```python
def _get_html_visualization(self, trace: ReasoningTrace) -> str:
    """
    Get an HTML visualization of the trace.

Args:
    trace: Reasoning trace

Returns:
    HTML visualization
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## _get_mermaid_visualization

```python
def _get_mermaid_visualization(self, trace: ReasoningTrace) -> str:
    """
    Get a Mermaid diagram visualization of the trace.

Args:
    trace: Reasoning trace

Returns:
    Mermaid diagram code
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## _get_node_prefix

```python
def _get_node_prefix(self, node_type: ReasoningNodeType) -> str:
    """
    Get prefix for node ID based on type.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## _get_text_visualization

```python
def _get_text_visualization(self, trace: ReasoningTrace) -> str:
    """
    Get a text visualization of the trace.

Args:
    trace: Reasoning trace

Returns:
    Text visualization
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## add_edge

```python
def add_edge(self, source_id: str, target_id: str, edge_type: str, weight: float = 1.0, metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Add an edge to the reasoning trace.

Args:
    source_id: ID of the source node
    target_id: ID of the target node
    edge_type: Type of the edge
    weight: Weight of the edge (0.0 to 1.0)
    metadata: Additional metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningTrace

## add_node

```python
def add_node(self, node_type: ReasoningNodeType, content: str, source: Optional[str] = None, confidence: float = 1.0, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Add a node to the reasoning trace.

Args:
    node_type: Type of the reasoning node
    content: Content of the node
    source: Optional source of the node
    confidence: Confidence score (0.0 to 1.0)
    metadata: Additional metadata

Returns:
    str: ID of the created node
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningTrace

## analyze_trace

```python
def analyze_trace(self, trace: ReasoningTrace) -> Dict[str, Any]:
    """
    Analyze a reasoning trace.

Args:
    trace: The reasoning trace

Returns:
    Dict[str, Any]: Analysis results
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## create_example_trace

```python
def create_example_trace() -> ReasoningTrace:
    """
    Create an example reasoning trace for demonstration.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_extraction_trace

```python
def create_extraction_trace(self, document_title: str, text_snippet: str) -> str:
    """
    Create a new extraction trace for a Wikipedia document.

Args:
    document_title: Title of the Wikipedia document
    text_snippet: Text snippet being processed

Returns:
    Trace ID
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## create_trace

```python
def create_trace(self, query: str, metadata: Optional[Dict[str, Any]] = None) -> ReasoningTrace:
    """
    Create a new reasoning trace.

Args:
    query: Query text
    metadata: Additional metadata

Returns:
    ReasoningTrace: The created trace
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## export_trace

```python
def export_trace(self, trace_id: str, format: str = "json") -> str:
    """
    Export a trace to a specific format.

Args:
    trace_id: Trace ID
    format: Export format (json, mermaid, html)

Returns:
    Exported trace
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## export_visualization

```python
def export_visualization(self, trace: ReasoningTrace, output_format: str = "json", output_file: Optional[str] = None) -> Any:
    """
    Export a visualization of a reasoning trace.

Args:
    trace: The reasoning trace
    output_format: Format of the visualization
    output_file: Path to the output file

Returns:
    Any: The visualization data or file path
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "ReasoningTrace":
    """
    Create from dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningTrace

## generate_explanation

```python
def generate_explanation(self, trace: ReasoningTrace, detail_level: str = "medium", max_tokens: int = 1000) -> str:
    """
    Generate a natural language explanation of a reasoning trace.

Args:
    trace: The reasoning trace
    detail_level: Level of detail ("low", "medium", "high")
    max_tokens: Maximum number of tokens in the explanation

Returns:
    str: Natural language explanation
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## get_explanation

```python
def get_explanation(self, detail_level: str = "medium") -> str:
    """
    Generate a natural language explanation of the reasoning trace.

Args:
    detail_level: Level of detail ("low", "medium", "high")

Returns:
    str: Natural language explanation
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningTrace

## get_trace

```python
def get_trace(self, trace_id: str) -> Optional[ReasoningTrace]:
    """
    Get a reasoning trace by ID.

Args:
    trace_id: ID of the trace

Returns:
    Optional[ReasoningTrace]: The trace or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## get_trace

```python
def get_trace(self, trace_id: str) -> Optional[ReasoningTrace]:
    """
    Get a trace by ID.

Args:
    trace_id: Trace ID

Returns:
    Trace or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## get_trace_visualization

```python
def get_trace_visualization(self, trace_id: str, format: str = "text") -> str:
    """
    Get a visualization of the trace.

Args:
    trace_id: Trace ID
    format: Visualization format (text, html, mermaid)

Returns:
    Visualization string
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## load

```python
@classmethod
def load(cls, filename: str) -> "ReasoningTrace":
    """
    Load a reasoning trace from a file.

Args:
    filename: Path to the trace file

Returns:
    ReasoningTrace: The loaded trace
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningTrace

## load_trace

```python
def load_trace(self, trace_id: str) -> Optional[ReasoningTrace]:
    """
    Load a reasoning trace from disk.

Args:
    trace_id: ID of the trace

Returns:
    Optional[ReasoningTrace]: The loaded trace or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## save

```python
def save(self, directory: str) -> str:
    """
    Save the reasoning trace to a file.

Args:
    directory: Directory to save the trace

Returns:
    str: Path to the saved file
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningTrace

## save_trace

```python
def save_trace(self, trace: ReasoningTrace) -> str:
    """
    Save a reasoning trace to disk.

Args:
    trace: The reasoning trace

Returns:
    str: Path to the saved file
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary for serialization.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ReasoningTrace

## trace_conclusion

```python
def trace_conclusion(self, trace: ReasoningTrace, conclusion_text: str, supporting_node_ids: List[str], confidence: float = 1.0) -> str:
    """
    Trace a conclusion reached during reasoning.

Args:
    trace: The reasoning trace
    conclusion_text: Text of the conclusion
    supporting_node_ids: IDs of the nodes that support this conclusion
    confidence: Confidence in the conclusion

Returns:
    str: ID of the created conclusion node
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## trace_contradiction

```python
def trace_contradiction(self, trace: ReasoningTrace, contradiction_text: str, conflicting_node_ids: List[str], confidence: float = 1.0) -> str:
    """
    Trace a contradiction found during reasoning.

Args:
    trace: The reasoning trace
    contradiction_text: Text describing the contradiction
    conflicting_node_ids: IDs of the nodes in conflict
    confidence: Confidence in the contradiction

Returns:
    str: ID of the created contradiction node
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## trace_document_access

```python
def trace_document_access(self, trace: ReasoningTrace, document_content: str, document_id: str, relevance_score: float, parent_node_id: Optional[str] = None) -> str:
    """
    Trace access to a document during reasoning.

Args:
    trace: The reasoning trace
    document_content: Content of the document
    document_id: Identifier for the document
    relevance_score: Relevance score to the query
    parent_node_id: ID of the node that led to this document

Returns:
    str: ID of the created document node
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## trace_entity_access

```python
def trace_entity_access(self, trace: ReasoningTrace, entity_name: str, entity_id: str, entity_type: str, relevance_score: float, parent_node_id: Optional[str] = None) -> str:
    """
    Trace access to an entity during reasoning.

Args:
    trace: The reasoning trace
    entity_name: Name of the entity
    entity_id: Identifier for the entity
    entity_type: Type of the entity
    relevance_score: Relevance score to the query
    parent_node_id: ID of the node that led to this entity

Returns:
    str: ID of the created entity node
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## trace_entity_extraction

```python
def trace_entity_extraction(self, trace_id: str, entity_text: str, entity_type: str, confidence: float, source_text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Trace the extraction of an entity.

Args:
    trace_id: Trace ID
    entity_text: Extracted entity text
    entity_type: Type of the entity
    confidence: Extraction confidence score
    source_text: Source text from which the entity was extracted
    metadata: Additional entity metadata

Returns:
    Node ID of the entity in the trace
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## trace_evidence

```python
def trace_evidence(self, trace: ReasoningTrace, evidence_text: str, source_node_id: str, confidence: float = 1.0) -> str:
    """
    Trace evidence found during reasoning.

Args:
    trace: The reasoning trace
    evidence_text: Text of the evidence
    source_node_id: ID of the node that provided this evidence
    confidence: Confidence in the evidence

Returns:
    str: ID of the created evidence node
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## trace_inference

```python
def trace_inference(self, trace: ReasoningTrace, inference_text: str, source_node_ids: List[str], confidence: float = 1.0) -> str:
    """
    Trace an inference made during reasoning.

Args:
    trace: The reasoning trace
    inference_text: Text of the inference
    source_node_ids: IDs of the nodes that led to this inference
    confidence: Confidence in the inference

Returns:
    str: ID of the created inference node
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## trace_integration_decision

```python
def trace_integration_decision(self, trace_id: str, entity_or_relation_id: str, decision: str, confidence: float, reasoning: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Trace a decision about integrating an entity or relationship.

Args:
    trace_id: Trace ID
    entity_or_relation_id: Entity or relationship node ID
    decision: Integration decision (include, exclude, modify)
    confidence: Decision confidence score
    reasoning: Reasoning behind the decision
    metadata: Additional decision metadata

Returns:
    Node ID of the decision node in the trace
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## trace_relationship

```python
def trace_relationship(self, trace: ReasoningTrace, source_node_id: str, target_node_id: str, relationship_type: str, confidence: float = 1.0, metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Trace a relationship between nodes during reasoning.

Args:
    trace: The reasoning trace
    source_node_id: ID of the source node
    target_node_id: ID of the target node
    relationship_type: Type of the relationship
    confidence: Confidence in the relationship
    metadata: Additional metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMReasoningTracer

## trace_relationship_extraction

```python
def trace_relationship_extraction(self, trace_id: str, relationship_type: str, source_entity_id: str, target_entity_id: str, confidence: float, source_text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Trace the extraction of a relationship.

Args:
    trace_id: Trace ID
    relationship_type: Type of the relationship
    source_entity_id: Source entity node ID
    target_entity_id: Target entity node ID
    confidence: Extraction confidence score
    source_text: Source text from which the relationship was extracted
    metadata: Additional relationship metadata

Returns:
    Node ID of the relationship in the trace
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## trace_sparql_validation

```python
def trace_sparql_validation(self, trace_id: str, relationship_id: str, sparql_query: str, validation_result: bool, confidence: float, result_count: int, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Trace the validation of a relationship using SPARQL against Wikidata.

Args:
    trace_id: Trace ID
    relationship_id: Relationship node ID to validate
    sparql_query: SPARQL query used for validation
    validation_result: Whether validation succeeded
    confidence: Validation confidence score
    result_count: Number of results returned by the query
    metadata: Additional validation metadata

Returns:
    Node ID of the validation node in the trace
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer

## trace_wikidata_validation

```python
def trace_wikidata_validation(self, trace_id: str, entity_id: str, wikidata_id: Optional[str], validation_result: bool, confidence: float, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Trace the validation of an entity against Wikidata.

Args:
    trace_id: Trace ID
    entity_id: Entity node ID to validate
    wikidata_id: Wikidata ID if found, None otherwise
    validation_result: Whether validation succeeded
    confidence: Validation confidence score
    metadata: Additional validation metadata

Returns:
    Node ID of the validation node in the trace
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaKnowledgeGraphTracer
