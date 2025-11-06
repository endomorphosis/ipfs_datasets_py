# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/wikipedia_rag_optimizer.py'

Files last updated: 1748635923.4713795

Stub file last updated: 2025-07-07 02:11:02

## UnifiedWikipediaGraphRAGQueryOptimizer

```python
class UnifiedWikipediaGraphRAGQueryOptimizer(UnifiedGraphRAGQueryOptimizer):
    """
    Unified optimizer for Wikipedia-derived knowledge graphs.

This class integrates all Wikipedia-specific optimization components
(optimizer, rewriter, budget manager) into a single unified optimizer
that can be used as a drop-in replacement for the base unified optimizer.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WikipediaCategoryHierarchyManager

```python
class WikipediaCategoryHierarchyManager:
    """
    Manages Wikipedia category hierarchies for optimizing traversal strategies.

This class helps navigate and optimize traversals through Wikipedia's category
structure, which is a key aspect of Wikipedia-derived knowledge graphs.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WikipediaEntityImportanceCalculator

```python
class WikipediaEntityImportanceCalculator:
    """
    Calculates importance scores for Wikipedia entities to prioritize traversal.

This class assigns importance scores to entities in Wikipedia-derived knowledge
graphs based on factors like popularity, connections, reference count, etc.
These scores help prioritize which entities to explore during graph traversal.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WikipediaGraphRAGBudgetManager

```python
class WikipediaGraphRAGBudgetManager(QueryBudgetManager):
    """
    Specialized budget manager for Wikipedia-derived knowledge graphs.

This class extends the base QueryBudgetManager with Wikipedia-specific
budget allocation strategies that consider the unique characteristics
of Wikipedia knowledge structures, particularly their hierarchical nature
and entity relationships.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WikipediaGraphRAGQueryRewriter

```python
class WikipediaGraphRAGQueryRewriter(QueryRewriter):
    """
    Specialized query rewriter for Wikipedia-derived knowledge graphs.

This class extends the base QueryRewriter with optimizations specific to
Wikipedia knowledge structures, implementing more effective query rewriting
strategies tailored to the characteristics of Wikipedia-derived graphs.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WikipediaPathOptimizer

```python
class WikipediaPathOptimizer:
    """
    Optimizes graph traversal paths for Wikipedia-derived knowledge graphs.

This class implements path optimization strategies specific to Wikipedia
knowledge structures, leveraging the hierarchical nature of categories,
the importance of different entity types, and relationship semantics.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WikipediaQueryExpander

```python
class WikipediaQueryExpander:
    """
    Expands queries with relevant Wikipedia topics and categories.

This class implements query expansion techniques specific to Wikipedia knowledge
structures, helping to improve recall by including related topics and categories.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WikipediaRAGQueryOptimizer

```python
class WikipediaRAGQueryOptimizer(GraphRAGQueryOptimizer):
    """
    Specialized query optimizer for Wikipedia-derived knowledge graphs.

This class extends the base GraphRAGQueryOptimizer with optimizations specific
to Wikipedia knowledge structures, leveraging hierarchical categories, entity
importance, and Wikipedia-specific relationship semantics.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## WikipediaRelationshipWeightCalculator

```python
class WikipediaRelationshipWeightCalculator:
    """
    Calculates weights for different Wikipedia relationship types to prioritize traversal.

This class assigns weights to different relationship types found in Wikipedia-derived
knowledge graphs based on their importance for query relevance. These weights are used
to prioritize certain relationship types during graph traversal.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, custom_weights: Optional[Dict[str, float]] = None):
    """
    Initialize the relationship weight calculator.

Args:
    custom_weights (Dict[str, float], optional): Custom relationship weights
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaRelationshipWeightCalculator

## __init__

```python
def __init__(self):
    """
    Initialize the category hierarchy manager.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaCategoryHierarchyManager

## __init__

```python
def __init__(self):
    """
    Initialize the entity importance calculator.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaEntityImportanceCalculator

## __init__

```python
def __init__(self, tracer: Optional[WikipediaKnowledgeGraphTracer] = None):
    """
    Initialize the query expander.

Args:
    tracer (WikipediaKnowledgeGraphTracer, optional): Tracer for explanation
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaQueryExpander

## __init__

```python
def __init__(self):
    """
    Initialize the path optimizer.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaPathOptimizer

## __init__

```python
def __init__(self, query_stats = None, vector_weight = 0.7, graph_weight = 0.3, cache_enabled = True, cache_ttl = 300.0, cache_size_limit = 100, tracer = None):
    """
    Initialize the Wikipedia RAG Query Optimizer.

Args:
    query_stats: Query statistics tracker
    vector_weight (float): Weight for vector similarity
    graph_weight (float): Weight for graph structure
    cache_enabled (bool): Whether to enable query caching
    cache_ttl (float): Time-to-live for cached results
    cache_size_limit (int): Maximum number of cached queries
    tracer (WikipediaKnowledgeGraphTracer, optional): Tracer for explanation
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaRAGQueryOptimizer

## __init__

```python
def __init__(self):
    """
    Initialize the Wikipedia graph query rewriter.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaGraphRAGQueryRewriter

## __init__

```python
def __init__(self):
    """
    Initialize the Wikipedia-specific budget manager.
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaGraphRAGBudgetManager

## __init__

```python
def __init__(self, rewriter = None, budget_manager = None, base_optimizer = None, graph_info = None, metrics_collector = None, tracer = None):
    """
    Initialize the unified Wikipedia graph optimizer.

Args:
    rewriter: Query rewriter component
    budget_manager: Budget manager component
    base_optimizer: Base optimization component
    graph_info (Dict, optional): Graph structure information
    metrics_collector: Performance metrics collector
    tracer: Tracer for explanation
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedWikipediaGraphRAGQueryOptimizer

## _apply_pattern_optimization

```python
def _apply_pattern_optimization(self, query: Dict[str, Any], pattern_type: str, entities: List[str]) -> Dict[str, Any]:
    """
    Apply pattern-specific optimizations for Wikipedia queries.

Args:
    query (Dict): Query to optimize
    pattern_type (str): Detected pattern type
    entities (List[str]): Extracted entities

Returns:
    Dict: Optimized query
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaGraphRAGQueryRewriter

## _detect_query_pattern

```python
def _detect_query_pattern(self, query_text: str) -> Optional[Tuple[str, List[str]]]:
    """
    Detect Wikipedia-specific query patterns from text.

Args:
    query_text (str): The query text

Returns:
    Optional[Tuple[str, List[str]]]: (pattern_type, entities) or None
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaGraphRAGQueryRewriter

## _normalize_relationship_type

```python
def _normalize_relationship_type(self, relationship_type: str) -> str:
    """
    Normalize relationship type string for consistent lookup.

Args:
    relationship_type (str): The relationship type to normalize

Returns:
    str: Normalized relationship type
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaRelationshipWeightCalculator

## allocate_budget

```python
def allocate_budget(self, query: Dict[str, Any], priority: str = "normal") -> Dict[str, Any]:
    """
    Allocate resources based on query complexity and Wikipedia-specific factors.

Args:
    query (Dict): Query parameters
    priority (str): Priority level ("low", "normal", "high")

Returns:
    Dict: Allocated budget
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaGraphRAGBudgetManager

## assign_category_weights

```python
def assign_category_weights(self, query_vector: np.ndarray, categories: List[str], similarity_scores: Dict[str, float] = None) -> Dict[str, float]:
    """
    Assign weights to categories based on depth and similarity to query.

Args:
    query_vector (np.ndarray): The query vector
    categories (List[str]): List of category names
    similarity_scores (Dict[str, float], optional): Pre-computed similarity scores

Returns:
    Dict[str, float]: Category weights (name -> weight)
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaCategoryHierarchyManager

## calculate_category_depth

```python
def calculate_category_depth(self, category: str, visited: Optional[Set[str]] = None) -> int:
    """
    Calculate the depth of a category in the hierarchy.

Args:
    category (str): The category name
    visited (Set[str], optional): Set of already visited categories to avoid cycles

Returns:
    int: The calculated depth (higher is more specific)
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaCategoryHierarchyManager

## calculate_entity_importance

```python
def calculate_entity_importance(self, entity_data: Dict[str, Any], category_weights: Optional[Dict[str, float]] = None) -> float:
    """
    Calculate importance score for an entity.

Args:
    entity_data (Dict): Entity data with relevant features
    category_weights (Dict[str, float], optional): Category importance weights

Returns:
    float: Entity importance score (0.0-1.0)
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaEntityImportanceCalculator

## calculate_entity_importance

```python
def calculate_entity_importance(self, entity_id: str, graph_processor) -> float:
    """
    Calculate importance score for an entity in a Wikipedia knowledge graph.

Args:
    entity_id (str): Entity ID
    graph_processor: Graph processor instance

Returns:
    float: Entity importance score (0.0-1.0)
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaRAGQueryOptimizer

## create_appropriate_optimizer

```python
def create_appropriate_optimizer(graph_processor = None, graph_type: Optional[str] = None, metrics_collector: Optional[QueryMetricsCollector] = None, tracer: Optional[WikipediaKnowledgeGraphTracer] = None) -> UnifiedGraphRAGQueryOptimizer:
    """
    Create an appropriate optimizer based on the detected graph type.

Args:
    graph_processor: Graph processor instance
    graph_type (str, optional): Explicitly specified graph type
    metrics_collector: Performance metrics collector
    tracer: Tracer for explanation

Returns:
    UnifiedGraphRAGQueryOptimizer: Appropriate optimizer instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## detect_graph_type

```python
def detect_graph_type(graph_processor) -> str:
    """
    Detect if a graph is Wikipedia-derived based on entity/relationship patterns.

Args:
    graph_processor: Graph processor to analyze

Returns:
    str: "wikipedia" if Wikipedia-derived, "ipld" if IPLD graph, or "unknown"
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## expand_query

```python
def expand_query(self, query_vector: np.ndarray, query_text: str, vector_store: Any, category_hierarchy: WikipediaCategoryHierarchyManager, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Expand a query with related Wikipedia topics and categories.

Args:
    query_vector (np.ndarray): The original query vector
    query_text (str): The original query text
    vector_store: Vector store for similarity search
    category_hierarchy: Category hierarchy manager
    trace_id (str, optional): Trace ID for logging

Returns:
    Dict: Expanded query parameters
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaQueryExpander

## get_edge_traversal_cost

```python
def get_edge_traversal_cost(self, edge_type: str) -> float:
    """
    Get traversal cost for an edge type.

Args:
    edge_type (str): The type of relationship edge

Returns:
    float: Traversal cost factor
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaPathOptimizer

## get_filtered_high_value_relationships

```python
def get_filtered_high_value_relationships(self, relationship_types: List[str], min_weight: float = 0.7) -> List[str]:
    """
    Filter relationship types to only include those with weight >= min_weight.

Args:
    relationship_types (List[str]): List of relationship types
    min_weight (float): Minimum weight threshold

Returns:
    List[str]: Filtered list of high-value relationship types
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaRelationshipWeightCalculator

## get_prioritized_relationship_types

```python
def get_prioritized_relationship_types(self, relationship_types: List[str]) -> List[str]:
    """
    Sort relationship types by their weights in descending order.

Args:
    relationship_types (List[str]): List of relationship types

Returns:
    List[str]: Relationship types sorted by weight (highest first)
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaRelationshipWeightCalculator

## get_related_categories

```python
def get_related_categories(self, category: str, max_distance: int = 2) -> List[Tuple[str, int]]:
    """
    Get categories related to the given category within the specified distance.

Args:
    category (str): The source category
    max_distance (int): Maximum traversal distance

Returns:
    List[Tuple[str, int]]: List of (category_name, distance) pairs
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaCategoryHierarchyManager

## get_relationship_weight

```python
def get_relationship_weight(self, relationship_type: str) -> float:
    """
    Get the weight for a specific relationship type.

Args:
    relationship_type (str): The type of relationship

Returns:
    float: Weight value for the relationship
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaRelationshipWeightCalculator

## learn_from_query_results

```python
def learn_from_query_results(self, query_id: str, results: List[Dict[str, Any]], time_taken: float, plan: Dict[str, Any]) -> None:
    """
    Learn from query execution results to improve future optimizations.

Args:
    query_id (str): ID of the executed query
    results (List[Dict]): Query results
    time_taken (float): Query execution time
    plan (Dict): The query plan used
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaRAGQueryOptimizer

## optimize_query

```python
def optimize_query(self, query_vector: np.ndarray, max_vector_results: int = 5, max_traversal_depth: int = 2, edge_types: Optional[List[str]] = None, min_similarity: float = 0.5, query_text: Optional[str] = None, graph_processor = None, vector_store = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate an optimized query plan for Wikipedia knowledge graphs.

Args:
    query_vector (np.ndarray): Query vector
    max_vector_results (int): Maximum number of initial vector similarity matches
    max_traversal_depth (int): Maximum traversal depth
    edge_types (List[str], optional): Types of edges to follow
    min_similarity (float): Minimum similarity score
    query_text (str, optional): Original query text
    graph_processor: Graph processor instance
    vector_store: Vector store instance
    trace_id (str, optional): Trace ID for logging

Returns:
    Dict: Optimized query parameters
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaRAGQueryOptimizer

## optimize_query

```python
def optimize_query(self, query: Dict[str, Any], graph_processor = None, vector_store = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Optimize a query for Wikipedia knowledge graphs.

Args:
    query (Dict): Query parameters
    graph_processor: Graph processor instance
    vector_store: Vector store instance
    trace_id (str, optional): Trace ID for logging

Returns:
    Dict: Optimized query plan
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedWikipediaGraphRAGQueryOptimizer

## optimize_traversal_path

```python
def optimize_traversal_path(self, start_entities: List[Dict[str, Any]], relationship_types: List[str], max_depth: int, budget: Dict[str, Any]) -> Dict[str, Any]:
    """
    Optimize a traversal path based on Wikipedia-specific considerations.

Args:
    start_entities (List[Dict]): Starting entities for traversal
    relationship_types (List[str]): Types of relationships to traverse
    max_depth (int): Maximum traversal depth
    budget (Dict): Resource budget constraints

Returns:
    Dict: Optimized traversal plan
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaPathOptimizer

## optimize_wikipedia_query

```python
def optimize_wikipedia_query(query: Dict[str, Any], graph_processor = None, vector_store = None, tracer: Optional[WikipediaKnowledgeGraphTracer] = None, metrics_collector: Optional[QueryMetricsCollector] = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Optimize a query for Wikipedia-derived knowledge graphs.

This is the main entry point for using the Wikipedia-specific optimizations.

Args:
    query (Dict): Query parameters
    graph_processor: Graph processor instance
    vector_store: Vector store instance
    tracer: Tracer for explanation
    metrics_collector: Performance metrics collector
    trace_id (str, optional): Trace ID for logging

Returns:
    Dict: Optimized query plan
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## rank_entities_by_importance

```python
def rank_entities_by_importance(self, entities: List[Dict[str, Any]], category_weights: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """
    Rank entities by their calculated importance.

Args:
    entities (List[Dict]): List of entity data dictionaries
    category_weights (Dict[str, float], optional): Category importance weights

Returns:
    List[Dict]: Entities sorted by importance (highest first)
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaEntityImportanceCalculator

## register_category_connection

```python
def register_category_connection(self, parent_category: str, child_category: str) -> None:
    """
    Register a connection between two categories.

Args:
    parent_category (str): The parent category
    child_category (str): The child category
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaCategoryHierarchyManager

## rewrite_query

```python
def rewrite_query(self, query: Dict[str, Any], graph_info: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Rewrite a query with optimizations for Wikipedia knowledge graphs.

Args:
    query (Dict): Original query parameters
    graph_info (Dict, optional): Graph structure information

Returns:
    Dict: Rewritten query with Wikipedia-specific optimizations
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaGraphRAGQueryRewriter

## suggest_early_stopping

```python
def suggest_early_stopping(self, results: List[Dict[str, Any]], budget_consumed_ratio: float) -> bool:
    """
    Provide Wikipedia-specific early stopping suggestions.

Args:
    results (List[Dict]): Current results
    budget_consumed_ratio (float): Portion of budget consumed

Returns:
    bool: Whether to stop early
    """
```
* **Async:** False
* **Method:** True
* **Class:** WikipediaGraphRAGBudgetManager
