# Core Modules API Reference

## Overview

This document provides a comprehensive API reference for the core business logic modules in `ipfs_datasets_py`. These modules are designed to be reusable by CLI tools, MCP server, direct Python imports, and third-party packages.

## Architecture

```
ipfs_datasets_py/
├── processors/          # Data processing modules
│   └── relationships/   # Relationship and graph analysis
├── caching/            # Caching and performance
├── logic/              # Reasoning and logic
└── core_operations/    # Core dataset operations
```

---

## Processors

### Relationship Analysis Modules

Location: `ipfs_datasets_py/processors/relationships/`

#### EntityExtractor

Extracts entities and relationships from document corpora.

**Import:**
```python
from ipfs_datasets_py.processors.relationships import EntityExtractor
```

**Class:** `EntityExtractor`

**Methods:**

##### `async extract_entities_for_mapping(corpus: Dict[str, Any]) -> List[Dict[str, Any]]`

Extract entities optimized for relationship mapping.

**Parameters:**
- `corpus` (Dict): Dictionary containing document corpus data with 'documents' key

**Returns:**
- List of entity dictionaries with deduplication and mention aggregation

**Example:**
```python
extractor = EntityExtractor()
corpus = {
    "documents": [
        {"title": "Doc 1", "content": "Content here", "date": "2024-01-01"},
        {"title": "Doc 2", "content": "More content", "date": "2024-01-02"}
    ]
}
entities = await extractor.extract_entities_for_mapping(corpus)
print(f"Found {len(entities)} entities")
```

##### `async extract_relationships(corpus: Dict, entities: List[Dict], relationship_types: List[str]) -> List[Dict]`

Extract relationships between entities.

**Parameters:**
- `corpus` (Dict): Document corpus data
- `entities` (List[Dict]): Extracted entities
- `relationship_types` (List[str]): Types to extract (co_occurrence, citation, semantic, temporal)

**Returns:**
- List of relationship dictionaries with strength scores

**Example:**
```python
relationships = await extractor.extract_relationships(
    corpus, 
    entities, 
    ["co_occurrence", "citation"]
)
for rel in relationships:
    print(f"{rel['source_entity']} → {rel['target_entity']}: {rel['strength']}")
```

#### GraphAnalyzer

Analyzes relationship graphs and calculates metrics.

**Import:**
```python
from ipfs_datasets_py.processors.relationships import GraphAnalyzer
```

**Class:** `GraphAnalyzer`

**Methods:**

##### `focus_on_entity(entities: List[Dict], relationships: List[Dict], focus_entity: str, max_depth: int) -> Tuple[List[Dict], List[Dict]]`

Focus relationship mapping around a specific entity.

**Parameters:**
- `entities` (List[Dict]): All entities
- `relationships` (List[Dict]): All relationships
- `focus_entity` (str): Entity ID to focus on
- `max_depth` (int): Maximum relationship depth to include

**Returns:**
- Tuple of (filtered entities, filtered relationships)

**Example:**
```python
analyzer = GraphAnalyzer()
focused_entities, focused_rels = analyzer.focus_on_entity(
    entities, relationships, "entity_1", max_depth=2
)
```

##### `detect_relationship_clusters(entities: List[Dict], relationships: List[Dict]) -> List[Dict]`

Detect clusters of highly connected entities.

**Parameters:**
- `entities` (List[Dict]): Entities list
- `relationships` (List[Dict]): Relationships list

**Returns:**
- List of cluster dictionaries

**Example:**
```python
clusters = analyzer.detect_relationship_clusters(entities, relationships)
for cluster in clusters:
    print(f"Cluster {cluster['cluster_id']}: {cluster['entity_count']} entities, density: {cluster['density']}")
```

##### `calculate_graph_metrics(entities: List[Dict], relationships: List[Dict]) -> Dict[str, Any]`

Calculate comprehensive graph metrics.

**Parameters:**
- `entities` (List[Dict]): Entities list
- `relationships` (List[Dict]): Relationships list

**Returns:**
- Dictionary of graph metrics (entity_count, relationship_count, average_degree, graph_density, etc.)

**Example:**
```python
metrics = analyzer.calculate_graph_metrics(entities, relationships)
print(f"Graph density: {metrics['graph_density']:.2f}")
print(f"Average degree: {metrics['average_degree']:.2f}")
```

#### TimelineGenerator

Generates and analyzes entity timelines.

**Import:**
```python
from ipfs_datasets_py.processors.relationships import TimelineGenerator
```

**Class:** `TimelineGenerator`

**Methods:**

##### `async extract_entity_timeline_events(corpus: Dict, entity_id: str, event_types: List[str]) -> List[Dict]`

Extract timeline events for a specific entity.

**Parameters:**
- `corpus` (Dict): Document corpus data
- `entity_id` (str): Entity to extract timeline for
- `event_types` (List[str]): Event types (mention, action, relationship, property_change)

**Returns:**
- List of timeline event dictionaries

**Example:**
```python
generator = TimelineGenerator()
events = await generator.extract_entity_timeline_events(
    corpus, 
    "entity_1", 
    ["mention", "action"]
)
for event in events:
    print(f"{event['timestamp']}: {event['description']}")
```

##### `analyze_time_distribution(events: List[Dict], granularity: str) -> Dict[str, Any]`

Analyze time distribution of events.

**Parameters:**
- `events` (List[Dict]): Timeline events
- `granularity` (str): Time granularity (hour, day, week, month)

**Returns:**
- Dictionary containing time distribution analysis

**Example:**
```python
distribution = generator.analyze_time_distribution(events, "day")
print(f"Peak activity: {distribution['peak_activity_time']}")
```

#### PatternDetector

Detects patterns in entity behavior and relationships.

**Import:**
```python
from ipfs_datasets_py.processors.relationships import PatternDetector
```

**Class:** `PatternDetector`

**Methods:**

##### `async detect_behavioral_patterns(corpus: Dict, confidence_threshold: float) -> List[Dict]`

Detect behavioral patterns in entity activities.

**Parameters:**
- `corpus` (Dict): Document corpus data
- `confidence_threshold` (float): Minimum confidence (0.0-1.0)

**Returns:**
- List of detected behavioral pattern dictionaries

**Example:**
```python
detector = PatternDetector()
patterns = await detector.detect_behavioral_patterns(corpus, 0.7)
for pattern in patterns:
    print(f"{pattern['pattern_name']}: {pattern['confidence']:.2f}")
```

##### `async detect_relational_patterns(corpus: Dict, confidence_threshold: float) -> List[Dict]`

Detect relational patterns between entities.

##### `async detect_temporal_pattern_sequences(corpus: Dict, time_window: str, confidence_threshold: float) -> List[Dict]`

Detect temporal sequence patterns.

##### `async detect_anomaly_patterns(corpus: Dict, confidence_threshold: float) -> List[Dict]`

Detect anomaly patterns in entity behavior.

##### `calculate_pattern_statistics(patterns: List[Dict]) -> Dict[str, Any]`

Calculate statistics about detected patterns.

**Example:**
```python
stats = detector.calculate_pattern_statistics(patterns)
print(f"Total patterns: {stats['total_patterns']}")
print(f"Average confidence: {stats['average_confidence']:.2f}")
```

#### ProvenanceTracker

Tracks data provenance and information lineage.

**Import:**
```python
from ipfs_datasets_py.processors.relationships import ProvenanceTracker
```

**Class:** `ProvenanceTracker`

**Methods:**

##### `async build_provenance_chain(corpus: Dict, entity_id: str, max_depth: int) -> List[Dict]`

Build provenance chain for an entity.

**Parameters:**
- `corpus` (Dict): Document corpus data
- `entity_id` (str): Entity to track provenance for
- `max_depth` (int): Maximum depth of provenance tracking

**Returns:**
- List of provenance chain entries

**Example:**
```python
tracker = ProvenanceTracker()
chain = await tracker.build_provenance_chain(corpus, "entity_1", 5)
for entry in chain:
    print(f"Depth {entry['depth']}: {entry['source_id']} (confidence: {entry['confidence']})")
```

##### `extract_source_documents(corpus: Dict, entity_id: str) -> List[Dict]`

Extract source documents for an entity.

##### `track_information_transformations(corpus: Dict, entity_id: str) -> List[Dict]`

Track information transformations for an entity.

##### `build_citation_network(corpus: Dict, entity_id: str) -> List[Dict]`

Build citation network for an entity.

##### `calculate_trust_metrics(source_documents: List[Dict], citation_network: List[Dict]) -> Dict[str, Any]`

Calculate trust metrics for provenance.

**Example:**
```python
sources = tracker.extract_source_documents(corpus, "entity_1")
citations = tracker.build_citation_network(corpus, "entity_1")
metrics = tracker.calculate_trust_metrics(sources, citations)
print(f"Trust score: {metrics['trust_score']:.2f}")
print(f"Trust level: {metrics['trust_level']}")
```

---

## Caching

### CacheManager

General-purpose cache manager with multiple optimization strategies.

**Import:**
```python
from ipfs_datasets_py.caching import CacheManager
```

**Class:** `CacheManager`

**Methods:**

##### `__init__()`

Initialize the CacheManager with in-memory storage.

**Example:**
```python
cache = CacheManager()
```

##### `get(key: str, namespace: str = "default") -> Dict[str, Any]`

Get value from cache.

**Parameters:**
- `key` (str): Cache key
- `namespace` (str): Cache namespace (default: "default")

**Returns:**
- Dictionary with success status and value (if found)

**Example:**
```python
result = cache.get("my_key", namespace="app")
if result["hit"]:
    print(f"Cache hit: {result['value']}")
else:
    print(f"Cache miss: {result['reason']}")
```

##### `set(key: str, value: Any, ttl: Optional[int] = None, namespace: str = "default") -> Dict[str, Any]`

Set value in cache.

**Parameters:**
- `key` (str): Cache key
- `value` (Any): Value to store
- `ttl` (Optional[int]): Time to live in seconds
- `namespace` (str): Cache namespace

**Returns:**
- Dictionary with success status

**Example:**
```python
cache.set("my_key", {"data": "value"}, ttl=3600, namespace="app")
```

##### `delete(key: str, namespace: str = "default") -> Dict[str, Any]`

Delete value from cache.

##### `clear(namespace: str = "default") -> Dict[str, Any]`

Clear cache for namespace (use "all" for all namespaces).

**Example:**
```python
cache.clear("app")  # Clear app namespace
cache.clear("all")  # Clear all namespaces
```

##### `get_stats(namespace: Optional[str] = None) -> Dict[str, Any]`

Get cache statistics.

**Example:**
```python
stats = cache.get_stats()
print(f"Hit rate: {stats['global_stats']['hit_rate_percent']:.1f}%")
print(f"Total keys: {stats['global_stats']['total_keys']}")
```

##### `list_keys(namespace: Optional[str] = None) -> Dict[str, Any]`

List cache keys with metadata.

##### `optimize(strategy: str = "lru", max_size_mb: Optional[int] = None, max_age_hours: Optional[int] = None, namespace: Optional[str] = None) -> Dict[str, Any]`

Optimize cache performance.

**Parameters:**
- `strategy` (str): Optimization strategy (lru, lfu, size_based, age_based)
- `max_size_mb` (Optional[int]): Maximum cache size in MB
- `max_age_hours` (Optional[int]): Maximum age for entries in hours
- `namespace` (Optional[str]): Optional namespace to optimize

**Example:**
```python
# Remove old entries
result = cache.optimize(strategy="age_based", max_age_hours=24)
print(f"Evicted {result['keys_evicted']} old keys")

# Limit cache size
result = cache.optimize(strategy="lru", max_size_mb=100)
print(f"Evicted {result['keys_evicted']} keys to stay under size limit")
```

##### `cache_embeddings(text: str, embeddings: List[float], model: str = "default", ttl: Optional[int] = None) -> Dict[str, Any]`

Cache embeddings for text.

**Example:**
```python
embeddings = [0.1, 0.2, 0.3, ...]  # Your embedding vector
cache.cache_embeddings("sample text", embeddings, model="bert-base", ttl=86400)
```

##### `get_cached_embeddings(text: str, model: str = "default") -> Dict[str, Any]`

Get cached embeddings for text.

**Example:**
```python
result = cache.get_cached_embeddings("sample text", model="bert-base")
if result["cache_hit"]:
    embeddings = result["embeddings"]
```

---

## Complete Example: Relationship Analysis Pipeline

```python
import asyncio
from ipfs_datasets_py.processors.relationships import (
    EntityExtractor,
    GraphAnalyzer,
    TimelineGenerator,
    PatternDetector,
    ProvenanceTracker
)
from ipfs_datasets_py.caching import CacheManager

async def analyze_corpus(corpus):
    # Initialize components
    cache = CacheManager()
    extractor = EntityExtractor()
    analyzer = GraphAnalyzer()
    timeline_gen = TimelineGenerator()
    detector = PatternDetector()
    tracker = ProvenanceTracker()
    
    # Extract entities (with caching)
    cache_key = "entities_" + str(hash(str(corpus)))
    cached = cache.get(cache_key)
    
    if cached["hit"]:
        entities = cached["value"]
    else:
        entities = await extractor.extract_entities_for_mapping(corpus)
        cache.set(cache_key, entities, ttl=3600)
    
    # Extract relationships
    relationships = await extractor.extract_relationships(
        corpus, entities, ["co_occurrence", "citation"]
    )
    
    # Analyze graph
    clusters = analyzer.detect_relationship_clusters(entities, relationships)
    metrics = analyzer.calculate_graph_metrics(entities, relationships)
    
    # Analyze timeline for first entity
    if entities:
        entity_id = entities[0]["id"]
        events = await timeline_gen.extract_entity_timeline_events(
            corpus, entity_id, ["mention", "action"]
        )
        distribution = timeline_gen.analyze_time_distribution(events, "day")
    
    # Detect patterns
    patterns = await detector.detect_behavioral_patterns(corpus, 0.7)
    
    # Track provenance
    if entities:
        provenance = await tracker.build_provenance_chain(corpus, entity_id, 3)
        trust = tracker.calculate_trust_metrics(
            tracker.extract_source_documents(corpus, entity_id),
            tracker.build_citation_network(corpus, entity_id)
        )
    
    return {
        "entities": entities,
        "relationships": relationships,
        "clusters": clusters,
        "metrics": metrics,
        "patterns": patterns
    }

# Run analysis
corpus = {
    "documents": [
        {"title": "Doc 1", "content": "Content...", "date": "2024-01-01"},
        {"title": "Doc 2", "content": "More...", "date": "2024-01-02"}
    ]
}
results = asyncio.run(analyze_corpus(corpus))
```

---

## Notes

- All async methods should be called with `await` or using `asyncio.run()`
- Corpus data structure should include a "documents" key with list of document dictionaries
- Each document should have at minimum: title, content, and date fields
- Cache namespaces allow logical separation of cached data
- TTL values are in seconds
- All functions include error handling and return structured dictionaries
