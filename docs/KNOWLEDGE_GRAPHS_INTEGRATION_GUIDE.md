# Knowledge Graphs Integration Guide

**Version:** 1.0.0  
**Last Updated:** 2026-02-16  
**Status:** Production Ready

## Overview

This guide demonstrates how to integrate the `extraction/` and `query/` packages to build complete knowledge graph applications. It covers end-to-end workflows from data ingestion to querying and analysis.

## Table of Contents

1. [Quick Start Integration](#quick-start-integration)
2. [Full Pipeline Examples](#full-pipeline-examples)
3. [Production Workflows](#production-workflows)
4. [Performance Optimization](#performance-optimization)
5. [Advanced Integration Patterns](#advanced-integration-patterns)
6. [Monitoring and Debugging](#monitoring-and-debugging)
7. [Best Practices](#best-practices)

---

## Quick Start Integration

### Basic Extraction → Query Workflow

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor, KnowledgeGraph
)
from ipfs_datasets_py.knowledge_graphs.query import (
    UnifiedQueryEngine, HybridSearchEngine
)

# Step 1: Extract knowledge graph from text
extractor = KnowledgeGraphExtractor()
text = """
Marie Curie was a physicist and chemist who conducted pioneering research 
on radioactivity. She won the Nobel Prize in Physics in 1903 and the Nobel 
Prize in Chemistry in 1911. She worked at the University of Paris.
"""

kg = extractor.extract_knowledge_graph(text)
print(f"Extracted: {len(kg.entities)} entities, {len(kg.relationships)} relationships")

# Step 2: Set up query engine
# Note: In production, you'd have a backend (IPLD, Neo4j, etc.)
# This example shows the API structure
# engine = UnifiedQueryEngine(backend=your_backend)

# Step 3: Query the knowledge graph
persons = kg.get_entities_by_type("person")
for person in persons:
    print(f"Person: {person.name}")
    rels = kg.get_relationships_by_entity(person)
    for rel in rels:
        print(f"  → {rel.relationship_type} → {rel.target_entity.name}")
```

### Extract → Validate → Query Pipeline

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation
)

# Step 1: Extract with validation
validator = KnowledgeGraphExtractorWithValidation(
    validate_during_extraction=True,
    auto_correct_suggestions=True
)

text = "Albert Einstein developed the theory of relativity in 1905."

result = validator.extract_knowledge_graph(
    text,
    validation_depth=2  # Validate entities and relationships
)

kg = result["knowledge_graph"]
validation = result["validation_results"]
metrics = result["validation_metrics"]

print(f"Extraction: {len(kg.entities)} entities")
print(f"Validation coverage: {metrics['overall_coverage']:.2%}")

# Step 2: Apply corrections if needed
corrections = result.get("corrections", {})
if corrections:
    corrected_kg = validator.apply_validation_corrections(kg, corrections)
    print(f"Applied {len(corrections)} corrections")
else:
    corrected_kg = kg

# Step 3: Query validated graph
validated_persons = corrected_kg.get_entities_by_type("person")
print(f"Found {len(validated_persons)} validated persons")
```

---

## Full Pipeline Examples

### Example 1: Document Collection → Knowledge Graph → Query System

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine
from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset
import os

# Configuration
INPUT_DIR = "documents/"
GRAPH_FILE = "knowledge_graph.json"

# Step 1: Extract knowledge from multiple documents
extractor = KnowledgeGraphExtractor()
combined_kg = None

print("Phase 1: Extraction")
print("-" * 50)

for filename in os.listdir(INPUT_DIR):
    if not filename.endswith(".txt"):
        continue
    
    filepath = os.path.join(INPUT_DIR, filename)
    with open(filepath, "r") as f:
        text = f.read()
    
    # Extract knowledge graph
    doc_kg = extractor.extract_knowledge_graph(text)
    print(f"✓ {filename}: {len(doc_kg.entities)} entities")
    
    # Merge into combined graph
    if combined_kg is None:
        combined_kg = doc_kg
    else:
        combined_kg.merge(doc_kg)

print(f"\nCombined graph: {len(combined_kg.entities)} entities, "
      f"{len(combined_kg.relationships)} relationships")

# Step 2: Enrich with type inference
print("\nPhase 2: Enrichment")
print("-" * 50)

enriched_kg = KnowledgeGraphExtractor.enrich_with_types(combined_kg)
print(f"✓ Types inferred for entities")

# Step 3: Validate (optional but recommended)
print("\nPhase 3: Validation (optional)")
print("-" * 50)

# For important entities, validate against Wikidata
key_entities = enriched_kg.get_entities_by_type("person")[:5]  # Top 5 persons
for entity in key_entities:
    validation = extractor.validate_against_wikidata(enriched_kg, entity.name)
    coverage = validation.get("coverage", 0.0)
    print(f"✓ {entity.name}: {coverage:.1%} validated")

# Step 4: Export for querying
print("\nPhase 4: Export")
print("-" * 50)

with open(GRAPH_FILE, "w") as f:
    f.write(enriched_kg.to_json())
print(f"✓ Saved to {GRAPH_FILE}")

# Step 5: Set up query engine (with backend)
print("\nPhase 5: Query Setup")
print("-" * 50)

# In production, load into backend:
# backend = IPLDBackend()
# backend.load_graph(enriched_kg)
# engine = UnifiedQueryEngine(backend=backend)

# For demonstration, query the in-memory graph:
print(f"✓ Query engine ready")

# Step 6: Execute queries
print("\nPhase 6: Querying")
print("-" * 50)

# Query 1: Find all relationships
all_rels = list(enriched_kg.relationships.values())
print(f"Query 1: Found {len(all_rels)} relationships")

# Query 2: Find paths between entities
entities_list = list(enriched_kg.entities.values())
if len(entities_list) >= 2:
    source = entities_list[0]
    target = entities_list[-1]
    path = enriched_kg.find_path(source.entity_id, target.entity_id, max_depth=5)
    if path:
        print(f"Query 2: Path from {source.name} to {target.name}: {len(path)} steps")
    else:
        print(f"Query 2: No path found")

# Query 3: Entity type distribution
entity_types = {}
for entity in enriched_kg.entities.values():
    entity_types[entity.entity_type] = entity_types.get(entity.entity_type, 0) + 1

print(f"Query 3: Entity type distribution:")
for etype, count in sorted(entity_types.items(), key=lambda x: x[1], reverse=True):
    print(f"  {etype}: {count}")

print("\n" + "=" * 50)
print("Pipeline complete!")
```

### Example 2: Real-Time Knowledge Building System

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
import json
import time
from typing import Dict, List

class KnowledgeGraphSystem:
    """
    Real-time knowledge graph building and querying system.
    """
    
    def __init__(self, storage_file: str = "live_kg.json"):
        self.extractor = KnowledgeGraphExtractor()
        self.storage_file = storage_file
        self.kg = self._load_or_create()
        self.stats = {
            "documents_processed": 0,
            "entities_added": 0,
            "relationships_added": 0,
            "last_update": None
        }
    
    def _load_or_create(self):
        """Load existing graph or create new one."""
        if os.path.exists(self.storage_file):
            with open(self.storage_file, "r") as f:
                from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
                return KnowledgeGraph.from_json(f.read())
        else:
            from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
            return KnowledgeGraph(name="live_knowledge_graph")
    
    def add_document(self, text: str, metadata: Dict = None):
        """Add document to knowledge graph."""
        # Extract knowledge
        doc_kg = self.extractor.extract_knowledge_graph(text)
        
        # Track stats before merge
        entities_before = len(self.kg.entities)
        rels_before = len(self.kg.relationships)
        
        # Merge into main graph
        self.kg.merge(doc_kg)
        
        # Update stats
        self.stats["documents_processed"] += 1
        self.stats["entities_added"] += len(self.kg.entities) - entities_before
        self.stats["relationships_added"] += len(self.kg.relationships) - rels_before
        self.stats["last_update"] = time.time()
        
        # Save
        self._save()
        
        return {
            "new_entities": len(self.kg.entities) - entities_before,
            "new_relationships": len(self.kg.relationships) - rels_before
        }
    
    def query_entity(self, name: str):
        """Query entity by name."""
        entities = self.kg.get_entities_by_name(name)
        if not entities:
            return None
        
        entity = entities[0]
        relationships = self.kg.get_relationships_by_entity(entity)
        
        return {
            "entity": entity.to_dict(),
            "relationships": [rel.to_dict() for rel in relationships],
            "related_entities": [
                rel.target_entity.to_dict() 
                if rel.source_entity.entity_id == entity.entity_id 
                else rel.source_entity.to_dict()
                for rel in relationships
            ]
        }
    
    def query_type(self, entity_type: str):
        """Query all entities of a type."""
        entities = self.kg.get_entities_by_type(entity_type)
        return [e.to_dict() for e in entities]
    
    def find_connection(self, name1: str, name2: str):
        """Find connection between two entities."""
        entities1 = self.kg.get_entities_by_name(name1)
        entities2 = self.kg.get_entities_by_name(name2)
        
        if not entities1 or not entities2:
            return None
        
        path = self.kg.find_path(
            entities1[0].entity_id,
            entities2[0].entity_id,
            max_depth=5
        )
        
        if not path:
            return None
        
        path_entities = [self.kg.get_entity_by_id(eid) for eid in path]
        return {
            "path_length": len(path),
            "entities": [e.to_dict() for e in path_entities if e]
        }
    
    def get_stats(self):
        """Get system statistics."""
        return {
            **self.stats,
            "total_entities": len(self.kg.entities),
            "total_relationships": len(self.kg.relationships),
            "entity_types": len(set(e.entity_type for e in self.kg.entities.values()))
        }
    
    def _save(self):
        """Save graph to disk."""
        with open(self.storage_file, "w") as f:
            f.write(self.kg.to_json())

# Usage
system = KnowledgeGraphSystem()

# Add documents
docs = [
    "Python is a programming language created by Guido van Rossum.",
    "Guido van Rossum worked at Google and Dropbox.",
    "Python is widely used in machine learning and data science."
]

print("Adding documents...")
for doc in docs:
    result = system.add_document(doc)
    print(f"  Added: {result['new_entities']} entities, {result['new_relationships']} relationships")

# Query
print("\nQuerying...")
python_info = system.query_entity("Python")
if python_info:
    print(f"Python: {len(python_info['relationships'])} relationships")

# Find connections
connection = system.find_connection("Python", "Guido van Rossum")
if connection:
    print(f"Connection found: {connection['path_length']} hops")

# Stats
stats = system.get_stats()
print(f"\nStats:")
print(f"  Documents: {stats['documents_processed']}")
print(f"  Entities: {stats['total_entities']}")
print(f"  Relationships: {stats['total_relationships']}")
```

### Example 3: Hybrid Search Integration

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine
import numpy as np

# Step 1: Build knowledge graph
extractor = KnowledgeGraphExtractor()
text = """
Artificial Intelligence is a field of computer science focused on creating 
intelligent machines. Machine learning is a subset of AI. Deep learning is 
a subset of machine learning using neural networks. Popular frameworks include 
TensorFlow and PyTorch. Applications include computer vision, natural language 
processing, and robotics.
"""

kg = extractor.extract_knowledge_graph(text)
print(f"Knowledge graph: {len(kg.entities)} entities")

# Step 2: Create simple vector store (for demonstration)
# In production, use FAISS, Qdrant, or similar
class SimpleVectorStore:
    def __init__(self):
        self.vectors = {}
        self.metadata = {}
    
    def add(self, entity_id, vector, metadata):
        self.vectors[entity_id] = vector
        self.metadata[entity_id] = metadata
    
    def search(self, query_vector, k=10):
        # Simple cosine similarity
        scores = []
        for entity_id, vector in self.vectors.items():
            similarity = np.dot(query_vector, vector) / (
                np.linalg.norm(query_vector) * np.linalg.norm(vector) + 1e-8
            )
            scores.append((entity_id, similarity, self.metadata[entity_id]))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:k]

# Create embeddings (simplified - in production use real embeddings)
vector_store = SimpleVectorStore()
for entity_id, entity in kg.entities.items():
    # Simplified: use random vector (in production, use real embedding model)
    vector = np.random.rand(128)  # 128-dim vector
    vector_store.add(entity_id, vector, {"name": entity.name, "type": entity.entity_type})

print(f"Vector store: {len(vector_store.vectors)} vectors")

# Step 3: Hybrid search (combine vector similarity with graph structure)
def hybrid_search(query: str, kg, vector_store, alpha=0.6):
    """
    Hybrid search combining vector similarity and graph structure.
    
    Args:
        query: Search query
        kg: Knowledge graph
        vector_store: Vector store
        alpha: Weight for vector scores (0-1), graph weight = 1-alpha
    """
    # Vector search
    query_vector = np.random.rand(128)  # Simplified
    vector_results = vector_store.search(query_vector, k=20)
    
    # Graph expansion from top vector results
    seed_entities = [kg.get_entity_by_id(r[0]) for r in vector_results[:5]]
    seed_entities = [e for e in seed_entities if e]  # Filter None
    
    # Expand in graph
    expanded_entities = set()
    for entity in seed_entities:
        expanded_entities.add(entity.entity_id)
        relationships = kg.get_relationships_by_entity(entity)
        for rel in relationships[:10]:  # Limit expansion
            if rel.source_entity.entity_id != entity.entity_id:
                expanded_entities.add(rel.source_entity.entity_id)
            else:
                expanded_entities.add(rel.target_entity.entity_id)
    
    # Combine scores
    vector_scores = {r[0]: r[1] for r in vector_results}
    graph_scores = {eid: 1.0 / (i + 1) for i, eid in enumerate(expanded_entities)}
    
    # Hybrid scoring
    all_entities = set(vector_scores.keys()) | set(graph_scores.keys())
    hybrid_scores = []
    for eid in all_entities:
        v_score = vector_scores.get(eid, 0.0)
        g_score = graph_scores.get(eid, 0.0)
        combined = alpha * v_score + (1 - alpha) * g_score
        
        entity = kg.get_entity_by_id(eid)
        if entity:
            hybrid_scores.append((entity, combined, v_score, g_score))
    
    hybrid_scores.sort(key=lambda x: x[1], reverse=True)
    return hybrid_scores[:10]

# Execute hybrid search
results = hybrid_search("machine learning neural networks", kg, vector_store, alpha=0.7)

print("\nHybrid Search Results:")
print("-" * 60)
for entity, score, v_score, g_score in results:
    print(f"{entity.name:30} | Combined: {score:.3f} | Vector: {v_score:.3f} | Graph: {g_score:.3f}")
```

---

## Production Workflows

### Workflow 1: Continuous Knowledge Ingestion

```python
import time
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KnowledgeGraphBuilder(FileSystemEventHandler):
    """Watch directory and build knowledge graph from new files."""
    
    def __init__(self, output_file="continuous_kg.json"):
        self.extractor = KnowledgeGraphExtractor()
        self.output_file = output_file
        self.kg = self._load_or_create()
    
    def _load_or_create(self):
        if os.path.exists(self.output_file):
            from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
            with open(self.output_file, "r") as f:
                return KnowledgeGraph.from_json(f.read())
        else:
            from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
            return KnowledgeGraph(name="continuous_kg")
    
    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith('.txt'):
            return
        
        logger.info(f"Processing new file: {event.src_path}")
        
        try:
            with open(event.src_path, "r") as f:
                text = f.read()
            
            # Extract and merge
            doc_kg = self.extractor.extract_knowledge_graph(text)
            entities_before = len(self.kg.entities)
            self.kg.merge(doc_kg)
            new_entities = len(self.kg.entities) - entities_before
            
            # Save
            with open(self.output_file, "w") as f:
                f.write(self.kg.to_json())
            
            logger.info(
                f"Added {new_entities} new entities. "
                f"Total: {len(self.kg.entities)} entities, "
                f"{len(self.kg.relationships)} relationships"
            )
        
        except Exception as e:
            logger.error(f"Error processing {event.src_path}: {e}")

# Usage
watch_dir = "./documents"
event_handler = KnowledgeGraphBuilder()
observer = Observer()
observer.schedule(event_handler, watch_dir, recursive=False)

print(f"Watching {watch_dir} for new documents...")
print("Press Ctrl+C to stop")

observer.start()
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    observer.stop()
observer.join()

print("Stopped watching")
```

### Workflow 2: Batch Processing with Error Recovery

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
import json
import logging
from typing import List, Dict
from dataclasses import dataclass
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ProcessingResult:
    success: bool
    file_path: str
    entities: int = 0
    relationships: int = 0
    error: str = None

class BatchProcessor:
    """Process multiple documents with error recovery."""
    
    def __init__(self, checkpoint_file="processing_checkpoint.json"):
        self.extractor = KnowledgeGraphExtractor()
        self.checkpoint_file = checkpoint_file
        self.processed_files = self._load_checkpoint()
    
    def _load_checkpoint(self):
        if os.path.exists(self.checkpoint_file):
            with open(self.checkpoint_file, "r") as f:
                return set(json.load(f))
        return set()
    
    def _save_checkpoint(self):
        with open(self.checkpoint_file, "w") as f:
            json.dump(list(self.processed_files), f)
    
    def process_batch(
        self, 
        file_paths: List[str],
        output_file: str,
        skip_processed: bool = True
    ) -> Dict:
        """Process batch of files with checkpointing."""
        results = []
        combined_kg = None
        
        for i, file_path in enumerate(file_paths):
            # Skip if already processed
            if skip_processed and file_path in self.processed_files:
                logger.info(f"[{i+1}/{len(file_paths)}] Skipping {file_path} (already processed)")
                continue
            
            logger.info(f"[{i+1}/{len(file_paths)}] Processing {file_path}")
            
            try:
                # Read file
                with open(file_path, "r") as f:
                    text = f.read()
                
                # Extract
                doc_kg = self.extractor.extract_knowledge_graph(text)
                
                # Merge
                if combined_kg is None:
                    from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
                    combined_kg = KnowledgeGraph(name="batch_kg")
                
                combined_kg.merge(doc_kg)
                
                # Mark as processed
                self.processed_files.add(file_path)
                self._save_checkpoint()
                
                # Record result
                result = ProcessingResult(
                    success=True,
                    file_path=file_path,
                    entities=len(doc_kg.entities),
                    relationships=len(doc_kg.relationships)
                )
                results.append(result)
                
                logger.info(f"  ✓ Success: {len(doc_kg.entities)} entities")
                
            except Exception as e:
                logger.error(f"  ✗ Error: {e}")
                logger.debug(traceback.format_exc())
                
                result = ProcessingResult(
                    success=False,
                    file_path=file_path,
                    error=str(e)
                )
                results.append(result)
        
        # Save combined graph
        if combined_kg:
            with open(output_file, "w") as f:
                f.write(combined_kg.to_json())
            logger.info(f"Saved combined graph to {output_file}")
        
        # Summary
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        
        summary = {
            "total_files": len(file_paths),
            "processed": len(successful),
            "failed": len(failed),
            "skipped": len(file_paths) - len(results),
            "total_entities": len(combined_kg.entities) if combined_kg else 0,
            "total_relationships": len(combined_kg.relationships) if combined_kg else 0,
            "failed_files": [r.file_path for r in failed]
        }
        
        return summary

# Usage
import glob

processor = BatchProcessor()
file_paths = glob.glob("documents/*.txt")

print(f"Processing {len(file_paths)} files...")
summary = processor.process_batch(file_paths, "batch_output.json")

print("\nBatch Processing Summary:")
print(f"  Processed: {summary['processed']}")
print(f"  Failed: {summary['failed']}")
print(f"  Skipped: {summary['skipped']}")
print(f"  Total Entities: {summary['total_entities']}")
print(f"  Total Relationships: {summary['total_relationships']}")

if summary['failed_files']:
    print(f"\nFailed files:")
    for file_path in summary['failed_files']:
        print(f"  - {file_path}")
```

---

## Performance Optimization

### Optimization 1: Parallel Extraction

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

def extract_from_file(file_path: str) -> tuple:
    """Extract knowledge graph from file (for parallel processing)."""
    try:
        extractor = KnowledgeGraphExtractor()
        
        with open(file_path, "r") as f:
            text = f.read()
        
        kg = extractor.extract_knowledge_graph(text)
        
        return (True, file_path, kg.to_dict(), None)
    
    except Exception as e:
        return (False, file_path, None, str(e))

def parallel_extract(file_paths: List[str], max_workers: int = None):
    """Extract knowledge graphs in parallel."""
    if max_workers is None:
        max_workers = multiprocessing.cpu_count()
    
    print(f"Processing {len(file_paths)} files with {max_workers} workers...")
    
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(extract_from_file, fp): fp for fp in file_paths}
        
        for future in as_completed(futures):
            success, file_path, kg_dict, error = future.result()
            
            if success:
                print(f"✓ {file_path}")
                results.append(kg_dict)
            else:
                print(f"✗ {file_path}: {error}")
    
    # Merge all graphs
    from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
    combined = KnowledgeGraph(name="parallel_combined")
    
    for kg_dict in results:
        kg = KnowledgeGraph.from_dict(kg_dict)
        combined.merge(kg)
    
    return combined

# Usage
import glob

files = glob.glob("documents/*.txt")
combined_kg = parallel_extract(files, max_workers=4)

print(f"\nCombined: {len(combined_kg.entities)} entities, "
      f"{len(combined_kg.relationships)} relationships")
```

### Optimization 2: Caching with Redis

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
import hashlib
import redis
import json

class CachedExtractor:
    """Extractor with Redis caching."""
    
    def __init__(self, redis_url="redis://localhost:6379"):
        self.extractor = KnowledgeGraphExtractor()
        self.redis_client = redis.from_url(redis_url)
        self.cache_prefix = "kg_extract:"
    
    def _get_cache_key(self, text: str) -> str:
        """Generate cache key from text hash."""
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"{self.cache_prefix}{text_hash}"
    
    def extract(self, text: str, use_cache: bool = True):
        """Extract with caching."""
        cache_key = self._get_cache_key(text)
        
        # Try cache
        if use_cache:
            cached = self.redis_client.get(cache_key)
            if cached:
                print("Cache hit!")
                from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
                return KnowledgeGraph.from_json(cached.decode())
        
        # Extract
        print("Cache miss - extracting...")
        kg = self.extractor.extract_knowledge_graph(text)
        
        # Cache result (with 1 hour expiry)
        self.redis_client.setex(cache_key, 3600, kg.to_json())
        
        return kg
    
    def clear_cache(self):
        """Clear all cached extractions."""
        keys = self.redis_client.keys(f"{self.cache_prefix}*")
        if keys:
            self.redis_client.delete(*keys)
            print(f"Cleared {len(keys)} cached items")

# Usage (requires Redis running)
# extractor = CachedExtractor()
# kg = extractor.extract("Some text...")  # Extracts and caches
# kg2 = extractor.extract("Some text...")  # Loads from cache
```

---

## Advanced Integration Patterns

### Pattern 1: Multi-Source Knowledge Fusion

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor,
    KnowledgeGraph
)
from typing import Dict, List

class MultiSourceKnowledgeFusion:
    """Fuse knowledge from multiple sources with provenance tracking."""
    
    def __init__(self):
        self.extractor = KnowledgeGraphExtractor()
        self.source_graphs = {}  # source_id -> KnowledgeGraph
        self.provenance = {}  # entity_id -> List[source_ids]
    
    def add_source(self, source_id: str, text: str, metadata: Dict = None):
        """Add knowledge from a source."""
        # Extract
        kg = self.extractor.extract_knowledge_graph(text)
        
        # Store source graph
        self.source_graphs[source_id] = kg
        
        # Track provenance
        for entity_id in kg.entities:
            if entity_id not in self.provenance:
                self.provenance[entity_id] = []
            self.provenance[entity_id].append(source_id)
        
        return kg
    
    def fuse(self, conflict_resolution="vote") -> KnowledgeGraph:
        """
        Fuse knowledge from all sources.
        
        Args:
            conflict_resolution: Strategy for conflicts
                - "vote": Use most common value
                - "latest": Use latest source
                - "confidence": Use highest confidence
        """
        fused = KnowledgeGraph(name="fused_knowledge")
        
        # Merge all source graphs
        for source_id, kg in self.source_graphs.items():
            fused.merge(kg)
        
        return fused
    
    def get_entity_provenance(self, entity_name: str) -> List[str]:
        """Get sources that mention an entity."""
        for entity_id, sources in self.provenance.items():
            entity = None
            for kg in self.source_graphs.values():
                entity = kg.get_entity_by_id(entity_id)
                if entity and entity.name == entity_name:
                    return sources
        return []

# Usage
fusion = MultiSourceKnowledgeFusion()

# Add sources
fusion.add_source("wikipedia", "Python is a programming language...")
fusion.add_source("documentation", "Python was created by Guido van Rossum...")
fusion.add_source("tutorial", "Python is used for web development...")

# Fuse knowledge
fused_kg = fusion.fuse()
print(f"Fused: {len(fused_kg.entities)} entities")

# Check provenance
sources = fusion.get_entity_provenance("Python")
print(f"Python mentioned in: {sources}")
```

### Pattern 2: Incremental Updates

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph
import time

class IncrementalKnowledgeGraph:
    """Knowledge graph with versioning and incremental updates."""
    
    def __init__(self, name: str = "incremental_kg"):
        self.current_version = 0
        self.versions = {0: KnowledgeGraph(name=name)}
        self.changelog = []
    
    def update(self, new_kg: KnowledgeGraph, description: str = ""):
        """Add new knowledge and create version."""
        # Merge into current version
        current = self.versions[self.current_version]
        entities_before = len(current.entities)
        rels_before = len(current.relationships)
        
        current.merge(new_kg)
        
        # Calculate changes
        entities_added = len(current.entities) - entities_before
        rels_added = len(current.relationships) - rels_before
        
        # Create new version
        self.current_version += 1
        self.versions[self.current_version] = current
        
        # Log change
        self.changelog.append({
            "version": self.current_version,
            "timestamp": time.time(),
            "description": description,
            "entities_added": entities_added,
            "relationships_added": rels_added
        })
        
        return self.current_version
    
    def get_version(self, version: int = None):
        """Get specific version (or current if None)."""
        if version is None:
            version = self.current_version
        return self.versions.get(version)
    
    def get_changelog(self):
        """Get version changelog."""
        return self.changelog
    
    def rollback(self, version: int):
        """Rollback to previous version."""
        if version not in self.versions:
            raise ValueError(f"Version {version} does not exist")
        
        self.current_version = version
        return self.versions[version]

# Usage
ikg = IncrementalKnowledgeGraph()

from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
extractor = KnowledgeGraphExtractor()

# Version 1
kg1 = extractor.extract_knowledge_graph("Python is a language.")
ikg.update(kg1, "Initial knowledge")

# Version 2
kg2 = extractor.extract_knowledge_graph("Python was created in 1991.")
ikg.update(kg2, "Added creation date")

# Version 3
kg3 = extractor.extract_knowledge_graph("Python is used in data science.")
ikg.update(kg3, "Added applications")

# View changelog
print("Changelog:")
for entry in ikg.get_changelog():
    print(f"  v{entry['version']}: {entry['description']} "
          f"(+{entry['entities_added']} entities)")

# Rollback
ikg.rollback(1)
print(f"Rolled back to version 1")
```

---

## Monitoring and Debugging

### Monitoring Extraction Performance

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
import time
import psutil
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MonitoredExtractor:
    """Extractor with performance monitoring."""
    
    def __init__(self):
        self.extractor = KnowledgeGraphExtractor()
        self.metrics = {
            "extractions": 0,
            "total_time": 0.0,
            "total_entities": 0,
            "total_relationships": 0,
            "errors": 0
        }
    
    def extract(self, text: str, **kwargs):
        """Extract with monitoring."""
        # Get initial memory
        process = psutil.Process()
        mem_before = process.memory_info().rss / 1024 / 1024  # MB
        
        # Extract
        start = time.time()
        try:
            kg = self.extractor.extract_knowledge_graph(text, **kwargs)
            elapsed = time.time() - start
            
            # Update metrics
            self.metrics["extractions"] += 1
            self.metrics["total_time"] += elapsed
            self.metrics["total_entities"] += len(kg.entities)
            self.metrics["total_relationships"] += len(kg.relationships)
            
            # Log
            mem_after = process.memory_info().rss / 1024 / 1024
            mem_delta = mem_after - mem_before
            
            logger.info(
                f"Extraction complete: {len(kg.entities)} entities, "
                f"{len(kg.relationships)} relationships in {elapsed:.2f}s "
                f"(memory: +{mem_delta:.1f}MB)"
            )
            
            return kg
            
        except Exception as e:
            self.metrics["errors"] += 1
            logger.error(f"Extraction failed: {e}")
            raise
    
    def get_stats(self):
        """Get performance statistics."""
        avg_time = (self.metrics["total_time"] / self.metrics["extractions"] 
                    if self.metrics["extractions"] > 0 else 0)
        avg_entities = (self.metrics["total_entities"] / self.metrics["extractions"] 
                        if self.metrics["extractions"] > 0 else 0)
        
        return {
            **self.metrics,
            "avg_time": avg_time,
            "avg_entities": avg_entities,
            "entities_per_second": avg_entities / avg_time if avg_time > 0 else 0
        }

# Usage
extractor = MonitoredExtractor()

texts = ["Text 1...", "Text 2...", "Text 3..."]
for text in texts:
    kg = extractor.extract(text)

stats = extractor.get_stats()
print("\nPerformance Statistics:")
for key, value in stats.items():
    print(f"  {key}: {value}")
```

---

## Best Practices

### 1. Always Use Error Handling

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()

try:
    kg = extractor.extract_knowledge_graph(text)
except RuntimeError as e:
    print(f"Extraction failed: {e}")
    # Handle or retry
except Exception as e:
    print(f"Unexpected error: {e}")
    # Log and handle
```

### 2. Validate Important Knowledge

```python
# For critical data, always validate
if entity.confidence < 0.7:
    validation = extractor.validate_against_wikidata(kg, entity.name)
    if validation['coverage'] < 0.5:
        print(f"Warning: Low validation for {entity.name}")
```

### 3. Use Appropriate Temperature Settings

```python
# Conservative for factual data
kg = extractor.extract_knowledge_graph(
    legal_text,
    extraction_temperature=0.2,
    structure_temperature=0.3
)

# Aggressive for exploratory analysis
kg = extractor.extract_knowledge_graph(
    research_paper,
    extraction_temperature=0.9,
    structure_temperature=0.8
)
```

### 4. Implement Checkpointing

```python
# Save progress regularly
if batch_count % 10 == 0:
    with open("checkpoint.json", "w") as f:
        f.write(combined_kg.to_json())
```

### 5. Monitor Resource Usage

```python
import psutil

process = psutil.Process()
print(f"Memory: {process.memory_info().rss / 1024 / 1024:.1f}MB")
print(f"CPU: {process.cpu_percent()}%")
```

---

## Additional Resources

- **Extraction API:** `KNOWLEDGE_GRAPHS_EXTRACTION_API.md`
- **Query API:** `KNOWLEDGE_GRAPHS_QUERY_API.md`
- **Usage Examples:** `KNOWLEDGE_GRAPHS_USAGE_EXAMPLES.md`
- **Architecture:** `KNOWLEDGE_GRAPHS_QUERY_ARCHITECTURE.md`

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-16  
**Maintained By:** Knowledge Graphs Team
