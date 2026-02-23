# Cross-Document Lineage Tracking

**Version:** 2.1.0  
**Package:** `ipfs_datasets_py.knowledge_graphs.lineage`  
**Last Updated:** 2026-02-20

---

## Overview

The Lineage module provides cross-document entity tracking and relationship lineage across multiple knowledge graphs. It enables tracking how entities evolve across documents, identifying duplicate entities, and building comprehensive entity profiles from multiple sources.

**Key Features:**
- Cross-document entity linking
- Entity evolution tracking
- Duplicate detection and resolution
- Lineage visualization
- Provenance tracking
- Temporal entity analysis
- Cross-document lineage (moved from root in v2.1.0)

## Module Contents

| File | Description |
|------|-------------|
| `core.py` | `LineageTracker` — main cross-document lineage tracker |
| `enhanced.py` | Enhanced lineage with provenance |
| `metrics.py` | Lineage quality metrics |
| `types.py` | Lineage data types |
| `visualization.py` | Lineage visualization helpers |
| `cross_document.py` | `CrossDocumentLineage` — moved from root (v2.1.0) |
| `cross_document_enhanced.py` | `CrossDocumentLineageEnhanced` — moved from root (v2.1.0) |

> **Migration note:** Old imports like `from ipfs_datasets_py.knowledge_graphs.cross_document_lineage import ...`
> still work but emit a `DeprecationWarning`. Prefer:
> `from ipfs_datasets_py.knowledge_graphs.lineage.cross_document import ...`

---

## Core Components

### LineageTracker (`core.py`)

Main tracker for cross-document entity lineage:

```python
from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker

# Initialize tracker
tracker = LineageTracker()

# Track entities from multiple documents
doc1_kg = extractor.extract_knowledge_graph("doc1.txt")
tracker.add_document("doc1", doc1_kg)

doc2_kg = extractor.extract_knowledge_graph("doc2.txt")
tracker.add_document("doc2", doc2_kg)

# Find entity across documents
lineage = tracker.get_entity_lineage("Alice")
print(f"Alice appears in {len(lineage.documents)} documents")

# Get merged entity profile
profile = tracker.get_merged_profile("Alice")
print(f"Combined attributes: {profile.attributes}")
```

**Tracking Features:**
- Document-level entity tracking
- Automatic entity linking
- Attribute aggregation
- Confidence scoring
- Temporal ordering

### EnhancedLineageTracker (`enhanced.py`)

Advanced tracker with ML-based entity resolution:

```python
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker

# Initialize with ML models
tracker = EnhancedLineageTracker(
    similarity_threshold=0.8,
    use_embeddings=True
)

# Add documents
tracker.add_document("paper1", kg1)
tracker.add_document("paper2", kg2)

# Resolve entity aliases
aliases = tracker.find_aliases("Dr. Smith")
print(f"Aliases: {aliases}")  # ["John Smith", "J. Smith", "Smith, J."]

# Get entity clusters (duplicates)
clusters = tracker.get_entity_clusters()
for cluster in clusters:
    print(f"Cluster: {cluster.canonical_name}")
    print(f"  Variants: {cluster.variants}")
    print(f"  Confidence: {cluster.confidence}")
```

**Advanced Features:**
- ML-based entity resolution
- Fuzzy name matching
- Embedding-based similarity
- Automated alias detection
- Clustering algorithms

### LineageMetrics (`metrics.py`)

Metrics and analytics for lineage data:

```python
from ipfs_datasets_py.knowledge_graphs.lineage import LineageMetrics

metrics = LineageMetrics(tracker)

# Get entity statistics
stats = metrics.get_entity_stats()
print(f"Total entities: {stats.total}")
print(f"Unique entities: {stats.unique}")
print(f"Duplicate rate: {stats.duplicate_rate:.2%}")

# Get document overlap
overlap = metrics.get_document_overlap("doc1", "doc2")
print(f"Shared entities: {overlap.shared_entities}")
print(f"Jaccard similarity: {overlap.jaccard:.3f}")

# Get temporal metrics
temporal = metrics.get_temporal_metrics("Alice")
print(f"First seen: {temporal.first_seen}")
print(f"Last seen: {temporal.last_seen}")
print(f"Appearances: {temporal.appearance_count}")
```

**Metric Types:**
- Entity statistics
- Document overlap analysis
- Temporal patterns
- Confidence distributions
- Resolution quality metrics

### LineageVisualizer (`visualization.py`)

Visualization of entity lineage:

```python
from ipfs_datasets_py.knowledge_graphs.lineage import LineageVisualizer

visualizer = LineageVisualizer(tracker)

# Visualize entity timeline
visualizer.plot_entity_timeline("Alice", output="alice_timeline.png")

# Visualize document overlap
visualizer.plot_document_overlap(output="overlap_matrix.png")

# Visualize entity evolution
visualizer.plot_entity_evolution("Alice", output="alice_evolution.png")

# Generate lineage graph
visualizer.generate_lineage_graph("Alice", output="alice_lineage.png")
```

**Visualization Types:**
- Entity timelines
- Document overlap matrices
- Entity evolution charts
- Lineage graphs
- Cluster dendrograms

### LineageTypes (`types.py`)

Type definitions for lineage data:

```python
from ipfs_datasets_py.knowledge_graphs.lineage import (
    EntityLineage,
    EntityProfile,
    DocumentLink,
    LineageMetadata
)

# EntityLineage: Cross-document entity tracking
lineage = EntityLineage(
    entity_id="alice_123",
    canonical_name="Alice Smith",
    variants=["Alice", "A. Smith", "Alice S."],
    documents=["doc1", "doc2", "doc3"],
    confidence=0.95
)

# EntityProfile: Merged entity attributes
profile = EntityProfile(
    name="Alice Smith",
    attributes={
        "age": 30,
        "occupation": "Engineer",
        "location": "NYC"
    },
    sources=["doc1", "doc2"],
    confidence_by_attribute={"age": 1.0, "occupation": 0.9}
)
```

---

## Usage Examples

### Example 1: Basic Cross-Document Tracking

```python
from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

# Setup
tracker = LineageTracker()
extractor = KnowledgeGraphExtractor()

# Extract from multiple documents
documents = {
    "bio": "Alice Smith is an engineer at Google.",
    "paper": "A. Smith published a paper on AI.",
    "article": "Alice S. received an award."
}

for doc_id, text in documents.items():
    kg = extractor.extract_knowledge_graph(text)
    tracker.add_document(doc_id, kg)

# Get entity lineage
lineage = tracker.get_entity_lineage("Alice")
print(f"Entity: {lineage.canonical_name}")
print(f"Appears in: {', '.join(lineage.documents)}")
print(f"Variants: {', '.join(lineage.variants)}")
print(f"Confidence: {lineage.confidence:.2f}")
```

### Example 2: Entity Resolution with ML

```python
from ipfs_datasets_py.knowledge_graphs.lineage import EnhancedLineageTracker

# Initialize with embeddings
tracker = EnhancedLineageTracker(
    similarity_threshold=0.85,
    use_embeddings=True,
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# Add documents
for doc_id, kg in knowledge_graphs.items():
    tracker.add_document(doc_id, kg)

# Find all mentions of an entity (including aliases)
mentions = tracker.find_all_mentions("John Smith")
for mention in mentions:
    print(f"Document: {mention.document_id}")
    print(f"  Name variant: {mention.name}")
    print(f"  Confidence: {mention.confidence:.3f}")

# Get canonical entity
canonical = tracker.resolve_entity("J. Smith")
print(f"Canonical name: {canonical.name}")
print(f"Known aliases: {canonical.aliases}")
```

### Example 3: Duplicate Detection

```python
from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker

tracker = LineageTracker()

# Add documents
tracker.add_document("doc1", kg1)
tracker.add_document("doc2", kg2)

# Find duplicates
duplicates = tracker.find_duplicates(threshold=0.8)

for duplicate_set in duplicates:
    print(f"Duplicate entity group:")
    for entity in duplicate_set.entities:
        print(f"  - {entity.name} (doc: {entity.document_id})")
    print(f"  Confidence: {duplicate_set.confidence:.2f}")
    
    # Merge duplicates
    merged = tracker.merge_duplicates(duplicate_set)
    print(f"  Merged as: {merged.canonical_name}")
```

### Example 4: Temporal Analysis

```python
from ipfs_datasets_py.knowledge_graphs.lineage import (
    LineageTracker,
    LineageMetrics
)
from datetime import datetime

tracker = LineageTracker()

# Add documents with timestamps
tracker.add_document("2020-paper", kg1, timestamp=datetime(2020, 1, 1))
tracker.add_document("2021-article", kg2, timestamp=datetime(2021, 6, 1))
tracker.add_document("2022-book", kg3, timestamp=datetime(2022, 12, 1))

# Get temporal metrics
metrics = LineageMetrics(tracker)
temporal = metrics.get_temporal_metrics("Alice")

print(f"First mention: {temporal.first_seen}")
print(f"Latest mention: {temporal.last_seen}")
print(f"Appearances: {temporal.appearance_count}")
print(f"Active period: {temporal.active_period_days} days")

# Get entity evolution
evolution = tracker.get_entity_evolution("Alice")
for snapshot in evolution:
    print(f"{snapshot.timestamp}: {snapshot.attributes}")
```

### Example 5: Provenance Tracking

```python
from ipfs_datasets_py.knowledge_graphs.lineage import LineageTracker

tracker = LineageTracker(track_provenance=True)

# Add documents with provenance metadata
tracker.add_document(
    "wikipedia",
    kg1,
    metadata={
        "source": "Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Alice_Smith",
        "retrieved": "2024-01-01",
        "confidence": 0.9
    }
)

tracker.add_document(
    "linkedin",
    kg2,
    metadata={
        "source": "LinkedIn",
        "url": "https://linkedin.com/in/alice-smith",
        "retrieved": "2024-01-02",
        "confidence": 0.95
    }
)

# Get entity with provenance
profile = tracker.get_merged_profile("Alice", include_provenance=True)

print(f"Entity: {profile.name}")
print("Attributes with sources:")
for attr, value in profile.attributes.items():
    sources = profile.provenance[attr]
    print(f"  {attr}: {value}")
    print(f"    Sources: {', '.join(s.source for s in sources)}")
    print(f"    Confidence: {max(s.confidence for s in sources):.2f}")
```

---

## Configuration

### Similarity Thresholds

```python
# Conservative (fewer false positives)
tracker = LineageTracker(
    name_similarity_threshold=0.95,
    attribute_similarity_threshold=0.9
)

# Balanced
tracker = LineageTracker(
    name_similarity_threshold=0.85,
    attribute_similarity_threshold=0.8
)

# Aggressive (more matches, some false positives)
tracker = LineageTracker(
    name_similarity_threshold=0.7,
    attribute_similarity_threshold=0.6
)
```

### Resolution Strategies

```python
from ipfs_datasets_py.knowledge_graphs.lineage import (
    LineageTracker,
    ResolutionStrategy
)

# Use embeddings for semantic similarity
tracker = LineageTracker(
    resolution_strategy=ResolutionStrategy.EMBEDDINGS,
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

# Use fuzzy string matching
tracker = LineageTracker(
    resolution_strategy=ResolutionStrategy.FUZZY_MATCHING
)

# Use hybrid approach
tracker = LineageTracker(
    resolution_strategy=ResolutionStrategy.HYBRID,
    fuzzy_weight=0.3,
    embedding_weight=0.7
)
```

---

## Performance Considerations

### Large Document Sets

```python
# Efficient: Incremental processing
tracker = LineageTracker(batch_size=100)

for i, (doc_id, kg) in enumerate(documents.items()):
    tracker.add_document(doc_id, kg)
    
    if (i + 1) % 100 == 0:
        # Periodic resolution
        tracker.resolve_pending()
        print(f"Processed {i + 1} documents")

# Final resolution
tracker.resolve_all()
```

### Memory Management

```python
# Use streaming for large datasets
tracker = LineageTracker(
    cache_size=1000,  # Keep last 1000 entities in memory
    disk_cache=True   # Store rest on disk
)
```

---

## Testing

```bash
# Run lineage tests
pytest tests/knowledge_graphs/test_lineage/ -v

# Test core tracking
pytest tests/knowledge_graphs/test_lineage/test_core.py -v

# Test enhanced resolution
pytest tests/knowledge_graphs/test_lineage/test_enhanced.py -v

# Test metrics
pytest tests/knowledge_graphs/test_lineage/test_metrics.py -v
```

---

## See Also

- **[Extraction Module](../extraction/README.md)** - Knowledge graph extraction
- **[Query Module](../query/README.md)** - Graph querying
- **[USER_GUIDE.md](../../../../docs/knowledge_graphs/USER_GUIDE.md)** - Usage guide
- **[API_REFERENCE.md](../../../../docs/knowledge_graphs/API_REFERENCE.md)** - Complete API

---

## Status

**Test Coverage:** ~75%  
**Production Ready:** Yes  
**Performance:** <100ms per document (typical)

**Roadmap:**
- v2.0: Core lineage tracking ✅
- v2.1: ML-based resolution ✅
- v2.2: Advanced visualization (Q1 2026)
- v2.3: Distributed tracking (Q2 2026)
