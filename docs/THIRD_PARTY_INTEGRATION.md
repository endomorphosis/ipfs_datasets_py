# Third-Party Integration Guide

## Overview

This guide shows how third-party developers can integrate and use the `ipfs_datasets_py` core modules in their own applications.

## Installation

```bash
pip install ipfs-datasets-py
```

Or install from source:

```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
pip install -e .
```

## Core Modules

The library provides several reusable core modules:

- **Relationship Analysis** (`processors.relationships`): Entity extraction, graph analysis, timeline generation
- **Caching** (`caching`): High-performance caching with multiple strategies
- **Logic** (`logic`): Reasoning and inference systems
- **Core Operations** (`core_operations`): Dataset management operations

## Quick Start Examples

### Example 1: Simple Caching

```python
from ipfs_datasets_py.caching import CacheManager

# Create cache manager
cache = CacheManager()

# Store data
cache.set("user_123", {"name": "Alice", "age": 30}, ttl=3600)

# Retrieve data
result = cache.get("user_123")
if result["hit"]:
    user_data = result["value"]
    print(f"Found user: {user_data['name']}")

# Get cache statistics
stats = cache.get_stats()
print(f"Hit rate: {stats['global_stats']['hit_rate_percent']:.1f}%")
```

### Example 2: Relationship Analysis

```python
import asyncio
from ipfs_datasets_py.processors.relationships import EntityExtractor, GraphAnalyzer

async def analyze_documents(documents):
    # Prepare corpus
    corpus = {"documents": documents}
    
    # Extract entities
    extractor = EntityExtractor()
    entities = await extractor.extract_entities_for_mapping(corpus)
    
    # Extract relationships
    relationships = await extractor.extract_relationships(
        corpus, entities, ["co_occurrence", "citation"]
    )
    
    # Analyze graph
    analyzer = GraphAnalyzer()
    metrics = analyzer.calculate_graph_metrics(entities, relationships)
    clusters = analyzer.detect_relationship_clusters(entities, relationships)
    
    return {
        "entities": len(entities),
        "relationships": len(relationships),
        "clusters": len(clusters),
        "density": metrics["graph_density"]
    }

# Use it
documents = [
    {"title": "Paper 1", "content": "...", "date": "2024-01-01"},
    {"title": "Paper 2", "content": "...", "date": "2024-01-02"}
]

results = asyncio.run(analyze_documents(documents))
print(f"Found {results['entities']} entities in {results['clusters']} clusters")
```

### Example 3: Pattern Detection

```python
import asyncio
from ipfs_datasets_py.processors.relationships import PatternDetector

async def detect_patterns_in_corpus(corpus, confidence=0.7):
    detector = PatternDetector()
    
    # Detect different pattern types
    behavioral = await detector.detect_behavioral_patterns(corpus, confidence)
    relational = await detector.detect_relational_patterns(corpus, confidence)
    temporal = await detector.detect_temporal_pattern_sequences(corpus, "30d", confidence)
    anomalies = await detector.detect_anomaly_patterns(corpus, confidence)
    
    all_patterns = behavioral + relational + temporal + anomalies
    
    # Calculate statistics
    stats = detector.calculate_pattern_statistics(all_patterns)
    
    return all_patterns, stats

# Use it
corpus = {"documents": [...]}
patterns, stats = asyncio.run(detect_patterns_in_corpus(corpus))
print(f"Detected {stats['total_patterns']} patterns")
```

## Integration Patterns

### Pattern 1: Caching Layer for Your API

Add intelligent caching to your API endpoints:

```python
from flask import Flask, jsonify
from ipfs_datasets_py.caching import CacheManager

app = Flask(__name__)
cache = CacheManager()

@app.route('/api/data/<item_id>')
def get_data(item_id):
    # Try cache first
    cached = cache.get(item_id, namespace="api")
    if cached["hit"]:
        return jsonify(cached["value"])
    
    # Fetch from database (expensive operation)
    data = fetch_from_database(item_id)
    
    # Cache for future requests
    cache.set(item_id, data, ttl=300, namespace="api")
    
    return jsonify(data)

def fetch_from_database(item_id):
    # Your expensive database query
    pass
```

### Pattern 2: Document Analysis Pipeline

Build a document analysis pipeline:

```python
import asyncio
from ipfs_datasets_py.processors.relationships import (
    EntityExtractor, GraphAnalyzer, TimelineGenerator
)
from ipfs_datasets_py.caching import CacheManager

class DocumentAnalyzer:
    def __init__(self):
        self.cache = CacheManager()
        self.extractor = EntityExtractor()
        self.analyzer = GraphAnalyzer()
        self.timeline = TimelineGenerator()
    
    async def analyze(self, documents):
        # Build corpus
        corpus = {"documents": documents}
        
        # Check cache
        cache_key = f"analysis_{hash(str(corpus))}"
        cached = self.cache.get(cache_key)
        if cached["hit"]:
            return cached["value"]
        
        # Extract entities
        entities = await self.extractor.extract_entities_for_mapping(corpus)
        
        # Extract relationships
        relationships = await self.extractor.extract_relationships(
            corpus, entities, ["co_occurrence", "semantic"]
        )
        
        # Analyze
        metrics = self.analyzer.calculate_graph_metrics(entities, relationships)
        clusters = self.analyzer.detect_relationship_clusters(entities, relationships)
        
        # Build result
        result = {
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "clusters": clusters,
            "metrics": metrics
        }
        
        # Cache result
        self.cache.set(cache_key, result, ttl=3600)
        
        return result

# Use the analyzer
analyzer = DocumentAnalyzer()
results = asyncio.run(analyzer.analyze(my_documents))
```

### Pattern 3: Multi-Level Caching

Implement sophisticated caching strategies:

```python
from ipfs_datasets_py.caching import CacheManager

class MultiLevelCache:
    def __init__(self):
        self.cache = CacheManager()
        self.l1_namespace = "fast"  # Fast, short TTL
        self.l2_namespace = "slow"  # Slower, long TTL
    
    def get(self, key):
        # Try L1 cache (fast, short-lived)
        result = self.cache.get(key, namespace=self.l1_namespace)
        if result["hit"]:
            return result["value"]
        
        # Try L2 cache (slower, long-lived)
        result = self.cache.get(key, namespace=self.l2_namespace)
        if result["hit"]:
            # Promote to L1
            self.cache.set(key, result["value"], ttl=300, namespace=self.l1_namespace)
            return result["value"]
        
        return None
    
    def set(self, key, value):
        # Set in both levels
        self.cache.set(key, value, ttl=300, namespace=self.l1_namespace)
        self.cache.set(key, value, ttl=3600, namespace=self.l2_namespace)
    
    def optimize(self):
        # Optimize each level with different strategies
        self.cache.optimize(strategy="lru", max_size_mb=50, namespace=self.l1_namespace)
        self.cache.optimize(strategy="lfu", max_size_mb=200, namespace=self.l2_namespace)
```

### Pattern 4: Entity Timeline Tracking

Track entity evolution over time:

```python
import asyncio
from ipfs_datasets_py.processors.relationships import TimelineGenerator, ProvenanceTracker

class EntityTracker:
    def __init__(self):
        self.timeline = TimelineGenerator()
        self.provenance = ProvenanceTracker()
    
    async def track_entity(self, corpus, entity_id):
        # Extract timeline
        events = await self.timeline.extract_entity_timeline_events(
            corpus, entity_id, ["mention", "action", "relationship"]
        )
        
        # Analyze time distribution
        distribution = self.timeline.analyze_time_distribution(events, "day")
        
        # Detect patterns
        patterns = self.timeline.detect_temporal_patterns(events, "day")
        
        # Get provenance
        provenance_chain = await self.provenance.build_provenance_chain(
            corpus, entity_id, max_depth=5
        )
        
        sources = self.provenance.extract_source_documents(corpus, entity_id)
        citations = self.provenance.build_citation_network(corpus, entity_id)
        trust = self.provenance.calculate_trust_metrics(sources, citations)
        
        return {
            "events": events,
            "distribution": distribution,
            "patterns": patterns,
            "provenance": provenance_chain,
            "trust_score": trust["trust_score"]
        }

# Use the tracker
tracker = EntityTracker()
tracking_data = asyncio.run(tracker.track_entity(corpus, "entity_123"))
```

## Best Practices

### 1. Always Use Async/Await

Most analysis methods are async:

```python
import asyncio

async def my_analysis():
    extractor = EntityExtractor()
    entities = await extractor.extract_entities_for_mapping(corpus)
    return entities

# Correct usage
results = asyncio.run(my_analysis())

# Or within async context
async def main():
    results = await my_analysis()
```

### 2. Namespace Your Caches

Use namespaces to organize cached data:

```python
cache = CacheManager()

# User data
cache.set("user_123", data, namespace="users")

# API responses
cache.set("endpoint_result", data, namespace="api")

# Embeddings
cache.cache_embeddings(text, vector, model="bert")  # Uses "embeddings" namespace

# Clear specific namespace
cache.clear("users")
```

### 3. Handle Missing Dependencies Gracefully

Some features require optional dependencies:

```python
try:
    from ipfs_datasets_py.processors.relationships import EntityExtractor
    extractor = EntityExtractor()
except ImportError as e:
    print("Relationship analysis not available. Install with: pip install ipfs-datasets-py[ml]")
    extractor = None
```

### 4. Monitor Cache Performance

Regularly check cache statistics:

```python
cache = CacheManager()

# ... use cache ...

stats = cache.get_stats()
if stats['global_stats']['hit_rate_percent'] < 50:
    print("Warning: Low cache hit rate!")
    # Consider adjusting TTL or cache strategy
```

### 5. Optimize Periodically

Run cache optimization in background tasks:

```python
import threading
import time

def optimize_cache_periodically(cache, interval=3600):
    while True:
        time.sleep(interval)
        result = cache.optimize(strategy="lru", max_age_hours=24)
        print(f"Optimized cache: evicted {result['keys_evicted']} keys")

cache = CacheManager()
optimizer_thread = threading.Thread(
    target=optimize_cache_periodically, 
    args=(cache, 3600),
    daemon=True
)
optimizer_thread.start()
```

## Error Handling

All core modules return structured dictionaries with error information:

```python
# Successful result
{
    "success": True,
    "value": {...},
    "metadata": {...}
}

# Error result
{
    "success": False,
    "error": "Error message here",
    "timestamp": "2024-01-01T00:00:00"
}
```

Always check the `success` field:

```python
result = cache.get("key")
if result.get("success", True):  # Default to True for backward compatibility
    if result["hit"]:
        use_value(result["value"])
else:
    handle_error(result["error"])
```

## Performance Tips

1. **Batch Operations**: Process multiple items in a loop rather than individually
2. **Use TTL Wisely**: Balance between freshness and cache hits
3. **Monitor Memory**: Check cache size with `get_stats()` and optimize regularly
4. **Async Properly**: Don't block async operations with sync code
5. **Cache Strategy**: Choose the right strategy (LRU for recency, LFU for frequency)

## Example Application: Research Paper Analyzer

Complete example application:

```python
import asyncio
from ipfs_datasets_py.processors.relationships import (
    EntityExtractor, GraphAnalyzer, PatternDetector
)
from ipfs_datasets_py.caching import CacheManager

class ResearchPaperAnalyzer:
    def __init__(self):
        self.cache = CacheManager()
        self.extractor = EntityExtractor()
        self.analyzer = GraphAnalyzer()
        self.detector = PatternDetector()
    
    async def analyze_papers(self, papers):
        """Analyze a collection of research papers."""
        # Build corpus
        corpus = {
            "documents": [
                {
                    "title": paper.title,
                    "content": paper.abstract + " " + paper.body,
                    "date": paper.published_date,
                    "source": paper.journal
                }
                for paper in papers
            ]
        }
        
        # Check cache
        cache_key = f"papers_{len(papers)}_{hash(str([p.id for p in papers]))}"
        cached = self.cache.get(cache_key, namespace="papers")
        if cached["hit"]:
            return cached["value"]
        
        # Extract entities (authors, concepts, methods)
        entities = await self.extractor.extract_entities_for_mapping(corpus)
        
        # Find relationships (citations, co-authorship, methodological connections)
        relationships = await self.extractor.extract_relationships(
            corpus, entities, ["citation", "co_occurrence", "semantic"]
        )
        
        # Analyze collaboration network
        metrics = self.analyzer.calculate_graph_metrics(entities, relationships)
        clusters = self.analyzer.detect_relationship_clusters(entities, relationships)
        
        # Detect research patterns
        patterns = await self.detector.detect_behavioral_patterns(corpus, 0.7)
        
        # Build result
        result = {
            "total_papers": len(papers),
            "entities_found": len(entities),
            "relationships": len(relationships),
            "collaboration_clusters": clusters,
            "network_metrics": metrics,
            "research_patterns": patterns,
            "key_authors": [e for e in entities if e["type"] == "PERSON"][:10],
            "main_concepts": [e for e in entities if e["type"] == "ORG"][:10]
        }
        
        # Cache for 1 hour
        self.cache.set(cache_key, result, ttl=3600, namespace="papers")
        
        return result
    
    def get_cache_stats(self):
        """Get cache performance statistics."""
        return self.cache.get_stats(namespace="papers")

# Usage
analyzer = ResearchPaperAnalyzer()
papers = load_papers_from_database()
analysis = asyncio.run(analyzer.analyze_papers(papers))

print(f"Analyzed {analysis['total_papers']} papers")
print(f"Found {analysis['entities_found']} entities")
print(f"Identified {len(analysis['collaboration_clusters'])} collaboration clusters")
```

## Support

- **GitHub**: https://github.com/endomorphosis/ipfs_datasets_py
- **Documentation**: See `docs/CORE_MODULES_API.md`
- **Issues**: https://github.com/endomorphosis/ipfs_datasets_py/issues

## License

See LICENSE file in the repository.
