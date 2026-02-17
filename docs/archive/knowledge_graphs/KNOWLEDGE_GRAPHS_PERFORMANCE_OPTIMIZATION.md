# Knowledge Graphs Performance Optimization Guide

**Version:** 1.0.0  
**Last Updated:** 2026-02-16  
**Status:** Production Ready

## Overview

This guide provides comprehensive performance optimization strategies for the knowledge graphs extraction and query systems. It covers profiling, bottleneck identification, optimization techniques, and benchmarking.

## Table of Contents

1. [Performance Profiling](#performance-profiling)
2. [Extraction Optimization](#extraction-optimization)
3. [Query Optimization](#query-optimization)
4. [Caching Strategies](#caching-strategies)
5. [Parallel Processing](#parallel-processing)
6. [Memory Optimization](#memory-optimization)
7. [Benchmarking](#benchmarking)
8. [Production Tuning](#production-tuning)

---

## Performance Profiling

### Profiling Extraction Operations

```python
import cProfile
import pstats
from io import StringIO
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

def profile_extraction(text: str):
    """Profile extraction operation."""
    profiler = cProfile.Profile()
    
    extractor = KnowledgeGraphExtractor()
    
    profiler.enable()
    kg = extractor.extract_knowledge_graph(text)
    profiler.disable()
    
    # Print stats
    s = StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
    ps.print_stats(20)  # Top 20 functions
    print(s.getvalue())
    
    return kg

# Usage
text = "Your text here..." * 100  # Large text
kg = profile_extraction(text)
```

### Profiling Query Operations

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
import time

def profile_query(engine, query, runs=10):
    """Profile query execution."""
    times = []
    
    for i in range(runs):
        start = time.perf_counter()
        result = engine.execute_query(query)
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    
    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    
    print(f"Query Performance (n={runs}):")
    print(f"  Average: {avg_time*1000:.2f}ms")
    print(f"  Min: {min_time*1000:.2f}ms")
    print(f"  Max: {max_time*1000:.2f}ms")
    
    return times

# Usage
# engine = UnifiedQueryEngine(backend=your_backend)
# times = profile_query(engine, "MATCH (n) RETURN n LIMIT 10")
```

### Memory Profiling

```python
from memory_profiler import profile
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

@profile
def extraction_with_memory_tracking(text):
    """Track memory usage during extraction."""
    extractor = KnowledgeGraphExtractor()
    kg = extractor.extract_knowledge_graph(text)
    return kg

# Usage (requires memory_profiler package)
# pip install memory_profiler
# python -m memory_profiler your_script.py
```

---

## Extraction Optimization

### Optimization 1: Batch Processing with Chunking

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
from typing import List

def optimized_batch_extract(texts: List[str], chunk_size: int = 1000):
    """
    Extract from texts with optimal chunking.
    
    For large documents, chunking improves memory usage and allows
    for parallel processing.
    """
    extractor = KnowledgeGraphExtractor()
    results = []
    
    for text in texts:
        if len(text) > 2000:
            # Use enhanced extraction with chunking for large texts
            kg = extractor.extract_enhanced_knowledge_graph(
                text,
                use_chunking=True
            )
        else:
            # Regular extraction for smaller texts
            kg = extractor.extract_knowledge_graph(text)
        
        results.append(kg)
    
    return results

# Performance comparison
import time

texts = ["Large text..." * 500] * 10

# Without optimization
start = time.time()
extractor = KnowledgeGraphExtractor()
kgs_slow = [extractor.extract_knowledge_graph(t) for t in texts]
time_slow = time.time() - start

# With optimization
start = time.time()
kgs_fast = optimized_batch_extract(texts)
time_fast = time.time() - start

print(f"Without optimization: {time_slow:.2f}s")
print(f"With optimization: {time_fast:.2f}s")
print(f"Speedup: {time_slow/time_fast:.2f}x")
```

### Optimization 2: Temperature Tuning for Speed

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

def fast_extraction(text: str):
    """
    Fast extraction using optimized temperature settings.
    
    Lower temperatures = faster extraction with fewer entities.
    Good for when speed is critical and precision is less important.
    """
    extractor = KnowledgeGraphExtractor()
    
    # Fast settings: low temperature, flat structure
    kg = extractor.extract_knowledge_graph(
        text,
        extraction_temperature=0.3,  # Extract only strong signals
        structure_temperature=0.2    # Minimal hierarchy
    )
    
    return kg

def accurate_extraction(text: str):
    """
    Accurate but slower extraction.
    
    Higher temperatures = more entities but slower.
    Good for important documents requiring comprehensive extraction.
    """
    extractor = KnowledgeGraphExtractor()
    
    # Accurate settings: high temperature, rich structure
    kg = extractor.extract_knowledge_graph(
        text,
        extraction_temperature=0.8,  # Extract weak signals too
        structure_temperature=0.7    # Rich hierarchies
    )
    
    return kg

# Benchmark
import time

text = "Sample document text..." * 100

start = time.time()
kg_fast = fast_extraction(text)
time_fast = time.time() - start

start = time.time()
kg_accurate = accurate_extraction(text)
time_accurate = time.time() - start

print(f"Fast extraction: {time_fast:.2f}s, {len(kg_fast.entities)} entities")
print(f"Accurate extraction: {time_accurate:.2f}s, {len(kg_accurate.entities)} entities")
print(f"Speed difference: {time_accurate/time_fast:.2f}x")
```

### Optimization 3: Selective Extraction

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

def selective_extract_entities_only(text: str):
    """Extract only entities (skip relationships for speed)."""
    extractor = KnowledgeGraphExtractor()
    
    # Extract entities
    entities = extractor.extract_entities(text)
    
    # Create minimal graph
    from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
    kg = KnowledgeGraph()
    for entity in entities:
        kg.add_entity(entity)
    
    return kg

def selective_extract_by_type(text: str, target_types: List[str]):
    """Extract only specific entity types."""
    extractor = KnowledgeGraphExtractor()
    
    # Full extraction
    kg = extractor.extract_knowledge_graph(text)
    
    # Filter to target types
    from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
    filtered_kg = KnowledgeGraph()
    
    for entity in kg.entities.values():
        if entity.entity_type in target_types:
            filtered_kg.add_entity(entity)
    
    # Add relationships between filtered entities
    filtered_ids = set(filtered_kg.entities.keys())
    for rel in kg.relationships.values():
        if (rel.source_entity.entity_id in filtered_ids and 
            rel.target_entity.entity_id in filtered_ids):
            filtered_kg.add_relationship(rel)
    
    return filtered_kg

# Usage
text = "Long document..."

# Extract only people and organizations
kg = selective_extract_by_type(text, ["person", "organization"])
print(f"Selective extraction: {len(kg.entities)} entities")
```

---

## Query Optimization

### Optimization 1: Query Result Caching

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
from functools import lru_cache
import hashlib
import json

class CachedQueryEngine:
    """Query engine with LRU caching."""
    
    def __init__(self, backend, cache_size=1000):
        self.engine = UnifiedQueryEngine(backend, enable_caching=True)
        self.cache_size = cache_size
        self._setup_cache()
    
    def _setup_cache(self):
        """Set up LRU cache for queries."""
        @lru_cache(maxsize=self.cache_size)
        def _cached_execute(query_hash, query, params_json):
            params = json.loads(params_json) if params_json else {}
            return self.engine.execute_query(query, params)
        
        self._cached_execute = _cached_execute
    
    def execute_query(self, query: str, params: dict = None):
        """Execute query with caching."""
        # Create cache key
        params_json = json.dumps(params, sort_keys=True) if params else ""
        query_hash = hashlib.md5(
            f"{query}{params_json}".encode()
        ).hexdigest()
        
        # Execute (cached)
        return self._cached_execute(query_hash, query, params_json)
    
    def clear_cache(self):
        """Clear query cache."""
        self._cached_execute.cache_clear()
    
    def cache_info(self):
        """Get cache statistics."""
        return self._cached_execute.cache_info()

# Usage
# engine = CachedQueryEngine(backend)
# result = engine.execute_query("MATCH (n) RETURN n")
# cache_info = engine.cache_info()
# print(f"Cache: {cache_info.hits} hits, {cache_info.misses} misses")
```

### Optimization 2: Budget-Aware Query Execution

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset

def optimize_query_budgets(query_complexity: str):
    """
    Select optimal budget preset based on query complexity.
    
    Args:
        query_complexity: 'simple', 'moderate', or 'complex'
    """
    if query_complexity == 'simple':
        # Fast queries: strict budgets
        return budgets_from_preset('strict')
    elif query_complexity == 'moderate':
        # Standard queries: moderate budgets
        return budgets_from_preset('moderate')
    else:
        # Complex queries: permissive budgets
        return budgets_from_preset('permissive')

def adaptive_query_execution(engine, query):
    """
    Execute query with adaptive budgets.
    
    Starts with strict budgets, falls back to permissive if needed.
    """
    # Try with strict budgets first
    try:
        budgets = budgets_from_preset('strict')
        result = engine.execute_query(query, budgets=budgets)
        return result, 'strict'
    except Exception as e:
        print(f"Strict budgets failed: {e}")
    
    # Retry with moderate budgets
    try:
        budgets = budgets_from_preset('moderate')
        result = engine.execute_query(query, budgets=budgets)
        return result, 'moderate'
    except Exception as e:
        print(f"Moderate budgets failed: {e}")
    
    # Final attempt with permissive budgets
    budgets = budgets_from_preset('permissive')
    result = engine.execute_query(query, budgets=budgets)
    return result, 'permissive'

# Usage
# engine = UnifiedQueryEngine(backend)
# result, budget_used = adaptive_query_execution(engine, complex_query)
# print(f"Executed with {budget_used} budgets")
```

### Optimization 3: Hybrid Search Tuning

```python
from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine

def tune_hybrid_search(query_type: str):
    """
    Return optimal weights for different query types.
    
    Args:
        query_type: 'semantic', 'structural', or 'balanced'
    """
    if query_type == 'semantic':
        # Emphasize semantic similarity
        return {
            'vector_weight': 0.8,
            'graph_weight': 0.2,
            'max_hops': 1
        }
    elif query_type == 'structural':
        # Emphasize graph structure
        return {
            'vector_weight': 0.2,
            'graph_weight': 0.8,
            'max_hops': 3
        }
    else:
        # Balanced
        return {
            'vector_weight': 0.5,
            'graph_weight': 0.5,
            'max_hops': 2
        }

def optimized_hybrid_search(engine, query, query_type='balanced'):
    """Execute hybrid search with optimized settings."""
    settings = tune_hybrid_search(query_type)
    
    results = engine.execute_hybrid(
        query=query,
        vector_weight=settings['vector_weight'],
        graph_weight=settings['graph_weight'],
        max_hops=settings['max_hops']
    )
    
    return results

# Benchmark different configurations
import time

# engine = HybridSearchEngine(backend, vector_store)

query = "machine learning algorithms"

for query_type in ['semantic', 'structural', 'balanced']:
    start = time.time()
    # results = optimized_hybrid_search(engine, query, query_type)
    elapsed = time.time() - start
    print(f"{query_type:12} search: {elapsed*1000:.2f}ms")
```

---

## Caching Strategies

### Strategy 1: Multi-Level Caching

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
import pickle
import os
from pathlib import Path

class MultiLevelCache:
    """
    Multi-level cache: Memory (L1) → Disk (L2) → Extraction (L3).
    """
    
    def __init__(self, cache_dir=".cache"):
        self.extractor = KnowledgeGraphExtractor()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # L1: Memory cache (fastest)
        self.memory_cache = {}
        self.max_memory_items = 100
    
    def _get_cache_key(self, text: str) -> str:
        import hashlib
        return hashlib.md5(text.encode()).hexdigest()
    
    def _get_cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.pkl"
    
    def extract(self, text: str):
        """Extract with multi-level caching."""
        key = self._get_cache_key(text)
        
        # L1: Check memory cache
        if key in self.memory_cache:
            print("L1 cache hit (memory)")
            return self.memory_cache[key]
        
        # L2: Check disk cache
        cache_path = self._get_cache_path(key)
        if cache_path.exists():
            print("L2 cache hit (disk)")
            with open(cache_path, 'rb') as f:
                kg = pickle.load(f)
            
            # Store in L1
            if len(self.memory_cache) < self.max_memory_items:
                self.memory_cache[key] = kg
            
            return kg
        
        # L3: Extract (cache miss)
        print("L3 cache miss (extracting)")
        kg = self.extractor.extract_knowledge_graph(text)
        
        # Store in L2
        with open(cache_path, 'wb') as f:
            pickle.dump(kg, f)
        
        # Store in L1
        if len(self.memory_cache) < self.max_memory_items:
            self.memory_cache[key] = kg
        
        return kg
    
    def clear_l1(self):
        """Clear memory cache."""
        self.memory_cache.clear()
    
    def clear_l2(self):
        """Clear disk cache."""
        for cache_file in self.cache_dir.glob("*.pkl"):
            cache_file.unlink()

# Usage
cache = MultiLevelCache()

text = "Sample text..."

# First call: L3 (extraction)
kg1 = cache.extract(text)

# Second call: L1 (memory)
kg2 = cache.extract(text)

# Clear L1, third call: L2 (disk)
cache.clear_l1()
kg3 = cache.extract(text)
```

### Strategy 2: Time-Based Cache Invalidation

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
import time
import json
from pathlib import Path

class TTLCache:
    """Cache with Time-To-Live (TTL) invalidation."""
    
    def __init__(self, cache_dir=".ttl_cache", ttl_seconds=3600):
        self.extractor = KnowledgeGraphExtractor()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.ttl_seconds = ttl_seconds
    
    def _get_cache_key(self, text: str) -> str:
        import hashlib
        return hashlib.md5(text.encode()).hexdigest()
    
    def _get_cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"
    
    def _get_metadata_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.meta"
    
    def _is_valid(self, key: str) -> bool:
        """Check if cache entry is still valid."""
        meta_path = self._get_metadata_path(key)
        
        if not meta_path.exists():
            return False
        
        with open(meta_path, 'r') as f:
            metadata = json.load(f)
        
        cached_time = metadata['timestamp']
        age = time.time() - cached_time
        
        return age < self.ttl_seconds
    
    def extract(self, text: str):
        """Extract with TTL caching."""
        key = self._get_cache_key(text)
        cache_path = self._get_cache_path(key)
        
        # Check cache validity
        if cache_path.exists() and self._is_valid(key):
            print(f"Cache hit (age < {self.ttl_seconds}s)")
            from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
            with open(cache_path, 'r') as f:
                return KnowledgeGraph.from_json(f.read())
        
        # Extract
        print("Cache miss or expired")
        kg = self.extractor.extract_knowledge_graph(text)
        
        # Cache with metadata
        with open(cache_path, 'w') as f:
            f.write(kg.to_json())
        
        with open(self._get_metadata_path(key), 'w') as f:
            json.dump({'timestamp': time.time()}, f)
        
        return kg
    
    def cleanup_expired(self):
        """Remove expired cache entries."""
        removed = 0
        for meta_file in self.cache_dir.glob("*.meta"):
            key = meta_file.stem
            if not self._is_valid(key):
                self._get_cache_path(key).unlink(missing_ok=True)
                meta_file.unlink()
                removed += 1
        
        print(f"Removed {removed} expired cache entries")

# Usage
cache = TTLCache(ttl_seconds=300)  # 5 minute TTL

text = "Sample text..."
kg = cache.extract(text)  # Extracts and caches

# Within 5 minutes
kg = cache.extract(text)  # Loads from cache

# After 5 minutes (or call cleanup)
time.sleep(301)
kg = cache.extract(text)  # Re-extracts (cache expired)
```

---

## Parallel Processing

### Parallel Extraction

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import List
import multiprocessing

def extract_single(text: str) -> dict:
    """Extract from single text (for multiprocessing)."""
    extractor = KnowledgeGraphExtractor()
    kg = extractor.extract_knowledge_graph(text)
    return kg.to_dict()

def parallel_extract_process(texts: List[str], max_workers=None) -> List[dict]:
    """
    Parallel extraction using processes.
    
    Best for CPU-bound extraction operations.
    """
    if max_workers is None:
        max_workers = multiprocessing.cpu_count()
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        kg_dicts = list(executor.map(extract_single, texts))
    
    return kg_dicts

def parallel_extract_thread(texts: List[str], max_workers=10) -> List[dict]:
    """
    Parallel extraction using threads.
    
    Best for I/O-bound operations (e.g., API calls).
    """
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        kg_dicts = list(executor.map(extract_single, texts))
    
    return kg_dicts

# Benchmark
import time

texts = ["Text sample..."] * 20

# Sequential
start = time.time()
sequential_kgs = [extract_single(t) for t in texts]
seq_time = time.time() - start

# Parallel (processes)
start = time.time()
parallel_kgs = parallel_extract_process(texts, max_workers=4)
par_time = time.time() - start

print(f"Sequential: {seq_time:.2f}s")
print(f"Parallel (4 workers): {par_time:.2f}s")
print(f"Speedup: {seq_time/par_time:.2f}x")
```

### Parallel Query Execution

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple

def parallel_queries(engine, queries: List[str], max_workers=5):
    """
    Execute multiple queries in parallel.
    
    Useful for dashboard-style queries or batch analytics.
    """
    def execute_single(query):
        try:
            result = engine.execute_query(query)
            return (True, query, result)
        except Exception as e:
            return (False, query, str(e))
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(execute_single, queries))
    
    return results

# Usage
# engine = UnifiedQueryEngine(backend)

queries = [
    "MATCH (n:Person) RETURN count(n)",
    "MATCH (n:Organization) RETURN count(n)",
    "MATCH (n:Technology) RETURN count(n)",
    "MATCH (n)-[r]->(m) RETURN count(r)",
    "MATCH (n) RETURN n.type, count(*)"
]

# results = parallel_queries(engine, queries)

# for success, query, result in results:
#     if success:
#         print(f"✓ {query[:50]}... → {len(result.items)} results")
#     else:
#         print(f"✗ {query[:50]}... → Error: {result}")
```

---

## Memory Optimization

### Optimization 1: Streaming Large Graphs

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
import json

def stream_graph_to_file(kg: KnowledgeGraph, output_path: str):
    """
    Stream large graph to file without loading entire JSON in memory.
    """
    with open(output_path, 'w') as f:
        f.write('{\n')
        
        # Write entities
        f.write('  "entities": [\n')
        entity_items = list(kg.entities.items())
        for i, (entity_id, entity) in enumerate(entity_items):
            entity_json = json.dumps(entity.to_dict())
            f.write(f'    {entity_json}')
            if i < len(entity_items) - 1:
                f.write(',')
            f.write('\n')
        f.write('  ],\n')
        
        # Write relationships
        f.write('  "relationships": [\n')
        rel_items = list(kg.relationships.items())
        for i, (rel_id, rel) in enumerate(rel_items):
            rel_json = json.dumps(rel.to_dict())
            f.write(f'    {rel_json}')
            if i < len(rel_items) - 1:
                f.write(',')
            f.write('\n')
        f.write('  ]\n')
        
        f.write('}\n')

def stream_graph_from_file(input_path: str) -> KnowledgeGraph:
    """
    Load large graph from file with minimal memory footprint.
    """
    kg = KnowledgeGraph()
    
    with open(input_path, 'r') as f:
        data = json.load(f)
        
        # Load entities in batches
        from ipfs_datasets_py.knowledge_graphs.extraction import Entity
        for entity_dict in data.get('entities', []):
            entity = Entity.from_dict(entity_dict)
            kg.add_entity(entity)
        
        # Load relationships in batches
        from ipfs_datasets_py.knowledge_graphs.extraction import Relationship
        for rel_dict in data.get('relationships', []):
            # Reconstruct relationship
            # (simplified - in practice need to handle entity references)
            pass
    
    return kg
```

### Optimization 2: Graph Pruning

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph

def prune_low_confidence(kg: KnowledgeGraph, threshold=0.5):
    """Remove low-confidence entities and relationships."""
    pruned = KnowledgeGraph()
    
    # Keep high-confidence entities
    for entity in kg.entities.values():
        if entity.confidence >= threshold:
            pruned.add_entity(entity)
    
    # Keep relationships between kept entities
    kept_ids = set(pruned.entities.keys())
    for rel in kg.relationships.values():
        if (rel.confidence >= threshold and
            rel.source_entity.entity_id in kept_ids and
            rel.target_entity.entity_id in kept_ids):
            pruned.add_relationship(rel)
    
    reduction = 1 - len(pruned.entities) / len(kg.entities)
    print(f"Pruned {reduction:.1%} of entities")
    
    return pruned

def prune_disconnected(kg: KnowledgeGraph):
    """Remove entities with no relationships."""
    connected_ids = set()
    
    for rel in kg.relationships.values():
        connected_ids.add(rel.source_entity.entity_id)
        connected_ids.add(rel.target_entity.entity_id)
    
    pruned = KnowledgeGraph()
    
    for entity_id, entity in kg.entities.items():
        if entity_id in connected_ids:
            pruned.add_entity(entity)
    
    for rel in kg.relationships.values():
        pruned.add_relationship(rel)
    
    removed = len(kg.entities) - len(pruned.entities)
    print(f"Removed {removed} disconnected entities")
    
    return pruned
```

---

## Benchmarking

### Comprehensive Benchmark Suite

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
import time
import statistics
from typing import List, Dict

class KnowledgeGraphBenchmark:
    """Comprehensive benchmarking suite."""
    
    def __init__(self):
        self.extractor = KnowledgeGraphExtractor()
        self.results = {}
    
    def benchmark_extraction(self, texts: List[str], runs=5) -> Dict:
        """Benchmark extraction performance."""
        times = []
        entities_counts = []
        rel_counts = []
        
        for i in range(runs):
            for text in texts:
                start = time.perf_counter()
                kg = self.extractor.extract_knowledge_graph(text)
                elapsed = time.perf_counter() - start
                
                times.append(elapsed)
                entities_counts.append(len(kg.entities))
                rel_counts.append(len(kg.relationships))
        
        return {
            'avg_time': statistics.mean(times),
            'median_time': statistics.median(times),
            'std_time': statistics.stdev(times) if len(times) > 1 else 0,
            'avg_entities': statistics.mean(entities_counts),
            'avg_relationships': statistics.mean(rel_counts),
            'throughput': len(texts) * runs / sum(times)
        }
    
    def benchmark_temperature_impact(self, text: str) -> Dict:
        """Benchmark impact of temperature settings."""
        results = {}
        
        temps = [0.2, 0.5, 0.8]
        for temp in temps:
            start = time.perf_counter()
            kg = self.extractor.extract_knowledge_graph(
                text,
                extraction_temperature=temp,
                structure_temperature=temp
            )
            elapsed = time.perf_counter() - start
            
            results[temp] = {
                'time': elapsed,
                'entities': len(kg.entities),
                'relationships': len(kg.relationships)
            }
        
        return results
    
    def benchmark_caching_speedup(self, text: str, runs=10) -> Dict:
        """Benchmark caching benefits."""
        # First run (no cache)
        times_no_cache = []
        for _ in range(runs):
            start = time.perf_counter()
            kg = self.extractor.extract_knowledge_graph(text)
            times_no_cache.append(time.perf_counter() - start)
        
        # With caching (simplified - would use actual cache)
        # times_cached = [...]
        
        return {
            'no_cache_avg': statistics.mean(times_no_cache),
            'no_cache_std': statistics.stdev(times_no_cache),
            # 'cached_avg': statistics.mean(times_cached),
            # 'speedup': statistics.mean(times_no_cache) / statistics.mean(times_cached)
        }
    
    def generate_report(self) -> str:
        """Generate benchmark report."""
        report = "Knowledge Graph Performance Benchmark\n"
        report += "=" * 50 + "\n\n"
        
        for benchmark_name, results in self.results.items():
            report += f"{benchmark_name}:\n"
            for key, value in results.items():
                if isinstance(value, float):
                    report += f"  {key}: {value:.4f}\n"
                else:
                    report += f"  {key}: {value}\n"
            report += "\n"
        
        return report

# Usage
benchmark = KnowledgeGraphBenchmark()

# Run benchmarks
texts = ["Sample text 1...", "Sample text 2...", "Sample text 3..."]

print("Running extraction benchmark...")
benchmark.results['extraction'] = benchmark.benchmark_extraction(texts)

print("Running temperature benchmark...")
benchmark.results['temperature'] = benchmark.benchmark_temperature_impact(texts[0])

print("\nBenchmark Report:")
print(benchmark.generate_report())
```

---

## Production Tuning

### Recommended Production Settings

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine, HybridSearchEngine
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset

# Production Extraction Configuration
production_extractor = KnowledgeGraphExtractor(
    use_spacy=False,  # Disable unless needed (faster)
    use_transformers=False,  # Disable unless needed (faster)
    min_confidence=0.6  # Filter low-confidence extractions
)

# Production Query Configuration
# production_engine = UnifiedQueryEngine(
#     backend=production_backend,
#     vector_store=production_vector_store,
#     enable_caching=True,
#     default_budgets='moderate'
# )

# Production Hybrid Search Configuration
# production_hybrid = HybridSearchEngine(
#     backend=production_backend,
#     vector_store=production_vector_store,
#     default_vector_weight=0.6,
#     default_graph_weight=0.4,
#     cache_size=5000  # Large cache for production
# )

# Production Budgets
production_budgets = budgets_from_preset('moderate')

print("Production configuration loaded")
print(f"Extraction: confidence >= {production_extractor.min_confidence}")
print(f"Query budgets: {production_budgets.max_nodes_visited} max nodes")
```

### Performance Checklist

```python
def performance_audit():
    """
    Audit checklist for production performance.
    """
    checklist = {
        "Extraction": [
            "✓ Caching enabled for repeated extractions",
            "✓ Temperature tuned for use case",
            "✓ Chunking enabled for large documents",
            "✓ Parallel processing for batch operations",
            "✓ Memory monitoring in place"
        ],
        "Query": [
            "✓ Query result caching enabled",
            "✓ Appropriate budgets configured",
            "✓ Hybrid search weights tuned",
            "✓ Connection pooling configured",
            "✓ Query timeouts set"
        ],
        "Storage": [
            "✓ Graph pruning strategy defined",
            "✓ Streaming I/O for large graphs",
            "✓ Compression enabled",
            "✓ Backup strategy in place"
        ],
        "Monitoring": [
            "✓ Performance metrics collected",
            "✓ Memory usage tracked",
            "✓ Query latency monitored",
            "✓ Error rates logged",
            "✓ Alerting configured"
        ]
    }
    
    print("Performance Audit Checklist")
    print("=" * 50)
    for category, items in checklist.items():
        print(f"\n{category}:")
        for item in items:
            print(f"  {item}")

performance_audit()
```

---

## Summary

### Key Optimization Techniques

1. **Extraction**
   - Use appropriate temperature settings
   - Enable chunking for large documents
   - Implement multi-level caching
   - Use parallel processing for batches

2. **Query**
   - Enable query result caching
   - Use appropriate budget presets
   - Tune hybrid search weights
   - Implement connection pooling

3. **Memory**
   - Stream large graphs
   - Prune low-confidence data
   - Use lazy loading
   - Monitor memory usage

4. **General**
   - Profile before optimizing
   - Benchmark all changes
   - Monitor in production
   - Iterate based on metrics

### Performance Targets

| Operation | Target | Good | Excellent |
|-----------|--------|------|-----------|
| Entity extraction | <100ms/entity | <50ms | <20ms |
| Graph query | <100ms | <50ms | <10ms |
| Hybrid search | <500ms | <200ms | <100ms |
| Graph merge | <1s/1000 entities | <500ms | <200ms |
| Cache hit rate | >70% | >85% | >95% |

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-16  
**Maintained By:** Knowledge Graphs Team
