# QueryEngine Integration Test - Authoritative Term Definitions

## Dataset Size Classifications

### Dataset Categories
```python
class DatasetSize(Enum):
    TINY = "tiny"       # 1-2 documents, <25 entities, <10 relationships
    SMALL = "small"     # 3-10 documents, 25-100 entities, 10-75 relationships  
    MEDIUM = "medium"   # 11-30 documents, 101-500 entities, 76-250 relationships
    LARGE = "large"     # 31-100 documents, 501-2000 entities, 251-1000 relationships
    XLARGE = "xlarge"   # 100+ documents, 2000+ entities, 1000+ relationships
```

### Document Cross-Reference Definition
A **cross-reference** exists when:
1. Two documents share at least 2 common entities (exact match on entity_id)
2. OR one document explicitly references another via citation/link (metadata.references contains doc_id)
3. OR documents have semantic similarity ≥ 0.8 on document-level embeddings

## Query Complexity Definitions

### Query Complexity Levels
```python
class QueryComplexity(Enum):
    TRIVIAL = "trivial"   # 1-2 words, single entity lookup, no operators
    SIMPLE = "simple"     # 3-5 words, single clause, one query intent  
    MODERATE = "moderate" # 6-10 words, 2-3 entities/concepts, may have one operator
    COMPLEX = "complex"   # 11-20 words, multiple clauses, mixed intents
    ADVANCED = "advanced" # 20+ words, nested conditions, multiple operators
```

### Query Intent Classification
- **Single intent**: Query has one clear purpose (e.g., "Who is Bill Gates?")
- **Mixed intent**: Query combines multiple purposes (e.g., "Show me Microsoft founders and their competitors")
- **Ambiguous intent**: Query lacks clear classification signals (confidence < 0.6)

## Performance Specifications

### Processing Time Thresholds
```python
PERFORMANCE_THRESHOLDS = {
    "trivial_query": 0.5,      # seconds
    "simple_query": 2.0,       # seconds
    "moderate_query": 5.0,     # seconds
    "complex_query": 8.0,      # seconds
    "advanced_query": 12.0,    # seconds
    "graph_traversal": 15.0,   # seconds (max 3 hops)
    "cross_document": 12.0,    # seconds (≤10 documents)
    "absolute_timeout": 30.0,  # seconds (hard limit)
}
```

### Memory Specifications
```python
MEMORY_LIMITS = {
    "baseline_measurement_point": "after_fixture_setup_before_test",
    "peak_increase_allowed": 500,  # MB above baseline
    "leak_detection_threshold": 50, # MB retained after 30s
    "gc_wait_time": 30,            # seconds to wait for garbage collection
}
```

## Cache Specifications

### Cache Key Generation
```python
def generate_cache_key(query_text: str, query_type: str, filters: Dict, max_results: int) -> str:
    """Generate deterministic cache key using SHA256."""
    normalized_query = normalize_query(query_text)
    filter_string = json.dumps(filters, sort_keys=True) if filters else "{}"
    cache_input = f"{normalized_query}|{query_type}|{filter_string}|{max_results}"
    return hashlib.sha256(cache_input.encode()).hexdigest()
```

### Cache Configuration
```python
CACHE_CONFIG = {
    "implementation": "LRU",
    "capacity": 1000,           # items
    "ttl": 3600,                # seconds (1 hour)
    "thread_safety": "threading.RLock",  # reentrant lock per cache instance
    "speedup_threshold": 0.5,   # second query must be ≤50% of first
}
```

## Semantic Processing Definitions

### Relevance Score Ranges
```python
class RelevanceLevel(Enum):
    NONE = (0.0, 0.1)        # No meaningful relevance
    MINIMAL = (0.1, 0.3)     # Barely relevant, below inclusion threshold
    LOW = (0.3, 0.4)         # Marginally relevant, included in results
    MEDIUM = (0.4, 0.7)      # Moderately relevant
    HIGH = (0.7, 0.9)        # Highly relevant
    PERFECT = (0.9, 1.0)     # Near-exact match
```

### Semantic Similarity Calculation
```python
def calculate_semantic_similarity(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
    """
    Calculate cosine similarity between two embeddings.
    Uses all-MiniLM-L6-v2 model (384 dimensions).
    """
    return np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))
```

### Inclusion Threshold
**Minimum semantic similarity for result inclusion**: 0.3 (cosine similarity)

## Query Processing Pipeline

### Complete Pipeline Definition
The **complete pipeline** consists of these sequential stages:
```python
PIPELINE_STAGES = [
    "validation",      # Parameter validation and sanitization
    "normalization",   # Query text normalization
    "cache_check",     # Check for cached results
    "type_detection",  # Automatic query type classification
    "preprocessing",   # Type-specific query preparation
    "processing",      # Main query execution
    "filtering",       # Apply user-specified filters
    "ranking",         # Sort by relevance scores
    "limiting",        # Apply max_results limit
    "enrichment",      # Add metadata to results
    "suggestion",      # Generate follow-up suggestions
    "caching",         # Store results in cache
    "response",        # Build QueryResponse object
]
```

### Live Dependencies Definition
**Live dependencies** means ALL of the following are active:
1. Real GraphRAGIntegrator instance with actual data loaded
2. Actual SentenceTransformer model loaded in memory (not mocked)
3. Real IPLDStorage connection (not in-memory mock)
4. No mocked methods in the QueryEngine class itself
5. Actual file I/O for test data (not stubbed)

## Result Quality Metrics

### Meaningful Results Definition
A result is **meaningful** when ALL conditions are met:
1. Relevance score ≥ 0.3
2. Content length ≥ 10 characters
3. Source attribution is valid (not "unknown")
4. Result type matches query intent

### Result Quality Measurement
```python
def calculate_result_quality(results: List[QueryResult], expected: List[Dict]) -> float:
    """
    Calculate F1 score for result quality.
    """
    precision = len(set(r.id for r in results) & set(e['id'] for e in expected)) / len(results)
    recall = len(set(r.id for r in results) & set(e['id'] for e in expected)) / len(expected)
    f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    return f1_score
```

### Human Correlation Measurement
**Pearson correlation** between system relevance scores and human ratings:
- Minimum acceptable: 0.75
- Calculated on test set of 100 query-result pairs
- Human ratings: 1-5 scale converted to 0.0-1.0

## Query Suggestion Specifications

### Suggestion Quality Criteria
```python
def is_valid_suggestion(original_query: str, suggestion: str) -> bool:
    """Validate suggestion quality."""
    # Length constraint
    if len(suggestion) > 200:
        return False
    
    # Difference measurement (Jaccard distance)
    original_tokens = set(original_query.lower().split())
    suggestion_tokens = set(suggestion.lower().split())
    intersection = original_tokens & suggestion_tokens
    union = original_tokens | suggestion_tokens
    jaccard_similarity = len(intersection) / len(union) if union else 0
    
    # Must be at least 30% different
    return jaccard_similarity <= 0.7
```

### Suggestion Relevance Evaluation
A suggestion is **relevant** if:
1. It explores a related concept from the results (entity/relationship mentioned)
2. It refines the original query (adds specificity)
3. It broadens the search scope reasonably (removes over-constraint)

## Error Handling Specifications

### Error Categories and Behavior
```python
ERROR_HANDLING = {
    "transient_errors": {
        "types": ["NetworkTimeout", "TemporaryDBUnavailable", "ModelLoadTimeout"],
        "retry_attempts": 3,
        "backoff_sequence": [1, 2, 4],  # seconds
        "final_action": "raise_original_error"
    },
    "system_errors": {
        "types": ["OutOfMemoryError", "DiskFullError", "ModelCorruption"],
        "retry_attempts": 0,
        "final_action": "immediate_failure_with_context"
    },
    "validation_errors": {
        "types": ["EmptyQuery", "InvalidMaxResults", "MalformedFilters"],
        "retry_attempts": 0,
        "final_action": "immediate_failure_with_guidance"
    }
}
```

### Clean Failure Definition
A **clean failure** means:
1. No partial results returned (all or nothing)
2. All resources released (file handles, memory, locks)
3. Cache state remains consistent (no corruption)
4. Clear error message with context
5. System state reset to pre-query condition

## Graph Traversal Specifications

### Path Scoring Formula
```python
def calculate_path_score(path: List[str], relationships: List[Dict]) -> float:
    """
    Calculate path score for graph traversal.
    """
    distance_score = 1.0 / len(path)  # Inverse of path length
    
    # Relationship relevance weights
    REL_WEIGHTS = {
        "founded": 1.0,
        "works_at": 0.9,
        "competitor_of": 0.8,
        "acquired_by": 0.7,
        "partners_with": 0.6,
        "default": 0.5
    }
    
    relevance_score = sum(REL_WEIGHTS.get(r['type'], REL_WEIGHTS['default']) 
                          for r in relationships) / len(relationships)
    
    # Combined score (equal weighting)
    return (distance_score + relevance_score) / 2.0
```

### Document Interaction Definition
**Document interactions** are measured by:
1. **Entity overlap**: Jaccard similarity of entity sets between documents
2. **Semantic similarity**: Cosine similarity of document embeddings
3. **Explicit references**: Direct citations or links between documents
4. **Topic coherence**: LDA topic distribution similarity

Combined score: `0.3 * entity_overlap + 0.3 * semantic_sim + 0.2 * references + 0.2 * topic_coherence`

## Test Data Specifications

### Known Test Dataset Definition
The **known test dataset** consists of:
```python
KNOWN_TEST_DATASET = {
    "documents": 10,  # Exactly 10 PDF documents
    "entities": 200,  # Verified list of 200 unique entities
    "relationships": 150,  # 150 verified relationships
    "ground_truth": {
        "query_answers": 50,  # 50 queries with expected results
        "entity_types": ["Person", "Organization", "Location", "Date", "Technology"],
        "relationship_types": ["founded", "works_at", "located_in", "acquired_by", "develops"],
    },
    "verification_method": "manual_expert_annotation",  # Human expert validated
    "annotation_agreement": 0.85,  # Inter-annotator agreement score
}
```

### Slow Processing Scenario
```python
@pytest.fixture
def slow_processing_scenario():
    """
    Create conditions that stress the system near timeout limits.
    """
    return {
        "dataset_size": DatasetSize.LARGE,
        "query_complexity": QueryComplexity.ADVANCED,
        "graph_depth": 3,  # Maximum hop traversal
        "cross_documents": 10,  # Maximum documents to analyze
        "no_cache": True,  # Disable caching to force full processing
        "artificial_delay": 0,  # No artificial delays - natural slowness only
    }
```

## Processing Behavior Specifications

### Early Termination vs Post-Processing
**"Processing stops at result limit"** means:
- Query processor terminates enumeration once max_results are found
- No additional results are generated beyond the limit
- Implemented via generator with counter or LIMIT clause in queries
- NOT post-processing filtering of a larger result set

### Parameter Correction Guidance
Error messages must include:
1. Parameter name that failed validation
2. Expected type/format
3. Actual value received
4. One valid example
5. Link to documentation section (if applicable)

Example:
```
ValueError: Invalid max_results parameter
  Expected: positive integer (1-1000)
  Received: -5
  Example: max_results=20
  See: docs/api#query-parameters
```

## Concurrency Specifications

### Thread Safety Implementation
```python
class CacheThreadSafety:
    """Thread-safe cache using fine-grained locking."""
    def __init__(self):
        self._cache = {}
        self._lock = threading.RLock()  # Reentrant lock
        self._key_locks = {}  # Per-key locks for fine-grained control
    
    def get(self, key: str):
        with self._lock:  # Quick check
            if key in self._cache:
                return self._cache[key]
        return None
```

### Concurrent Execution Success Criteria
1. All queries complete without deadlocks
2. Results identical to sequential execution (ignoring order)
3. Cache hit detection remains accurate
4. No race conditions in shared resources
5. Total time ≤ 1.5x longest individual query