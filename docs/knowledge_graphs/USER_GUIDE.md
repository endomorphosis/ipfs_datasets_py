# Knowledge Graphs - User Guide

**Version:** 2.0.0  
**Last Updated:** 2026-02-17

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Core Concepts](#core-concepts)
3. [Extraction Workflows](#extraction-workflows)
4. [Query Patterns](#query-patterns)
5. [Storage Options](#storage-options)
6. [Transaction Management](#transaction-management)
7. [Integration Patterns](#integration-patterns)
8. [Production Best Practices](#production-best-practices)
9. [Troubleshooting Guide](#troubleshooting-guide)
10. [Examples Gallery](#examples-gallery)

---

## Quick Start

### Installation

```bash
pip install "ipfs_datasets_py[knowledge_graphs]"
python -m spacy download en_core_web_sm
```

### Basic Usage (3 Steps)

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

# Step 1: Create extractor
extractor = KnowledgeGraphExtractor()

# Step 2: Extract knowledge graph from text
text = "Marie Curie won the Nobel Prize in Physics in 1903."
kg = extractor.extract_knowledge_graph(text)

# Step 3: Query the graph
persons = kg.get_entities_by_type("person")
for person in persons:
    print(f"Person: {person.name}")
```

### Temperature Settings

Control extraction detail level with temperature (0.0-1.0):

```python
# Conservative extraction (0.2-0.3) - Legal/factual data
kg = extractor.extract_knowledge_graph(text, extraction_temperature=0.3)

# Balanced extraction (0.5-0.6) - Mixed content  
kg = extractor.extract_knowledge_graph(text, extraction_temperature=0.6)

# Detailed extraction (0.8-0.9) - Research/exploratory
kg = extractor.extract_knowledge_graph(text, extraction_temperature=0.9)
```

---

## Core Concepts

### Entities

Entities represent real-world objects or concepts in the knowledge graph.

**Structure:**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import Entity

entity = Entity(
    entity_type="person",              # Classification
    name="Marie Curie",                # Primary identifier
    properties={                        # Additional metadata
        "birth_year": "1867",
        "nationality": "Polish",
        "field": "Physics"
    },
    confidence=0.95                     # Extraction confidence (0.0-1.0)
)
```

**Common Entity Types:**
- `person` - Individuals
- `organization` - Companies, institutions
- `location` - Places, addresses
- `technology` - Tools, frameworks, platforms
- `event` - Occurrences, milestones
- `concept` - Abstract ideas

### Relationships

Relationships connect entities and describe their interactions.

**Structure:**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import Relationship

relationship = Relationship(
    source="Marie Curie",              # Source entity
    target="Nobel Prize",              # Target entity
    relationship_type="WON",           # Semantic connection
    properties={                        # Context
        "year": "1903",
        "shared_with": "Henri Becquerel"
    },
    confidence=0.92                     # Relationship confidence
)
```

**Common Relationship Types:**
- `WORKS_AT`, `WORKED_AT` - Employment
- `CREATED`, `DEVELOPED` - Authorship/creation
- `WON`, `RECEIVED` - Awards/recognition
- `LOCATED_IN` - Geographic relationships
- `PART_OF`, `BELONGS_TO` - Hierarchical relationships

### Knowledge Graphs

Knowledge graphs are containers for entities and relationships.

**Basic Operations:**
```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraph

# Create graph
kg = KnowledgeGraph(name="scientists_graph")

# Add entities
kg.add_entity(entity)

# Add relationships
kg.add_relationship(relationship)

# Query operations
persons = kg.get_entities_by_type("person")
rels = kg.get_relationships_by_entity(entity)
path = kg.find_path(source_id, target_id, max_depth=5)

# Merge graphs (with automatic deduplication)
kg.merge(other_kg)
```

### Graph Structure

```
┌─────────────────┐      WON(1903)      ┌──────────────┐
│  Marie Curie    │───────────────────>│ Nobel Prize  │
│  (person)       │                     │  (award)     │
└─────────────────┘                     └──────────────┘
        │
        │ WORKED_AT(1906)
        ▼
┌─────────────────┐
│ Univ. of Paris  │
│ (organization)  │
└─────────────────┘
```

### IPLD Storage Model

Knowledge graphs are stored using IPLD (InterPlanetary Linked Data):

- **Content-addressed:** Each graph has a unique CID (Content Identifier)
- **Immutable:** Graphs cannot be modified after storage
- **Verifiable:** CIDs enable cryptographic verification
- **Distributed:** Graphs can be stored across IPFS network

---

## Extraction Workflows

### 1. Basic Extraction

#### Manual Creation
```python
from ipfs_datasets_py.knowledge_graphs.extraction import Entity, KnowledgeGraph

# Create entities manually
person = Entity(
    entity_type="person",
    name="Marie Curie",
    properties={"birth_year": "1867"},
    confidence=0.95
)

# Create graph
kg = KnowledgeGraph(name="scientists_graph")
kg.add_entity(person)
```

#### Automated Extraction
```python
extractor = KnowledgeGraphExtractor()
text = """
Marie Curie was a physicist who won the Nobel Prize in 1903.
She worked at the University of Paris.
"""

# Auto-detect entities and relationships
kg = extractor.extract_knowledge_graph(text)

print(f"Extracted {len(kg.entities)} entities")
print(f"Extracted {len(kg.relationships)} relationships")

for entity in kg.entities:
    print(f"- {entity.name} ({entity.entity_type})")
```

### 2. Extraction with Validation

Validate extracted entities against external knowledge bases (e.g., Wikidata):

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractorWithValidation
)

# Enable validation during extraction
validator = KnowledgeGraphExtractorWithValidation(
    validate_during_extraction=True
)

# Extract and validate
result = validator.extract_knowledge_graph(
    text,
    validation_depth=2  # Depth of validation checks
)

kg = result["knowledge_graph"]
metrics = result["validation_metrics"]
corrections = result.get("corrections", {})

print(f"Validation coverage: {metrics['overall_coverage']:.2%}")
print(f"Entities validated: {len(corrections)}")
```

### 3. Batch Extraction

Process multiple documents and merge results:

```python
# Prepare documents
documents = [
    {"text": "Marie Curie won Nobel Prize...", "source": "bio1.txt"},
    {"text": "Albert Einstein developed...", "source": "bio2.txt"},
    {"text": "Isaac Newton discovered...", "source": "bio3.txt"}
]

# Extract from all documents
kg = extractor.extract_from_documents(
    documents,
    text_key="text"  # Key containing text in each document
)

# Entities automatically deduplicated by name
print(f"Total unique entities: {len(kg.entities)}")
```

### 4. Large Document Processing

Handle documents that exceed memory or token limits:

```python
# Read large document
with open("large_document.txt") as f:
    large_text = f.read()

# Extract with automatic chunking
kg = extractor.extract_enhanced_knowledge_graph(
    large_text,
    use_chunking=True,         # Enable automatic chunking
    extraction_temperature=0.7,
    structure_temperature=0.6
)

# Chunks automatically merged by name similarity
print(f"Processed document with {len(large_text)} characters")
print(f"Extracted {len(kg.entities)} entities")
```

### 5. Wikipedia Integration

Extract knowledge from Wikipedia pages:

```python
# Extract from Wikipedia
kg = extractor.extract_from_wikipedia(
    page_title="Artificial Intelligence",
    extraction_temperature=0.7
)

print(f"Extracted from Wikipedia: {kg.name}")
print(f"Entities: {len(kg.entities)}")

# Handle errors
try:
    kg = extractor.extract_from_wikipedia("NonexistentPage")
except ValueError as e:
    print(f"Error: {e}")  # Page not found
```

### 6. Custom Relation Patterns

Define custom relationship extraction rules:

```python
# Define custom patterns
custom_patterns = [
    {
        "name": "develops",
        "pattern": r"(\w+)\s+develops?\s+(\w+)",
        "source_type": "person",
        "target_type": "technology",
        "confidence": 0.85
    },
    {
        "name": "founded",
        "pattern": r"(\w+)\s+founded\s+(\w+)",
        "source_type": "person",
        "target_type": "organization",
        "confidence": 0.90
    }
]

# Create extractor with custom patterns
extractor = KnowledgeGraphExtractor(relation_patterns=custom_patterns)

text = "Guido van Rossum developed Python. Elon Musk founded SpaceX."
kg = extractor.extract_knowledge_graph(text)

for rel in kg.relationships.values():
    print(f"{rel.source} --[{rel.relationship_type}]--> {rel.target}")
```

---

## Query Patterns

### 1. Basic Queries

```python
# Query by entity type
persons = kg.get_entities_by_type("person")
for person in persons:
    print(f"Person: {person.name}")

# Query by entity name
entities = kg.get_entities_by_name("Marie Curie")
for entity in entities:
    print(f"Found: {entity.name} ({entity.entity_type})")

# Query relationships for an entity
rels = kg.get_relationships_by_entity(entity)
for rel in rels:
    print(f"{rel.source} --[{rel.relationship_type}]--> {rel.target}")
```

### 2. Path Finding (Graph Traversal)

Find connections between entities:

```python
# Find path between two entities
path = kg.find_path(
    source_entity_id="marie_curie_id",
    target_entity_id="albert_einstein_id",
    max_depth=5
)

if path:
    print("Connection found:")
    for entity_id in path:
        entity = kg.entities[entity_id]
        print(f"  → {entity.name}")
else:
    print("No connection found")
```

### 3. Graph Merging (Multi-Source Queries)

Combine knowledge graphs from multiple sources:

```python
# Extract from different sources
kg1 = extractor.extract_knowledge_graph("Python created by Guido...")
kg2 = extractor.extract_knowledge_graph("Guido worked at Google...")
kg3 = extractor.extract_knowledge_graph("Google acquired YouTube...")

# Merge all graphs
combined = KnowledgeGraph(name="combined_knowledge")
combined.merge(kg1)
combined.merge(kg2)
combined.merge(kg3)

# Query combined knowledge
guido = combined.get_entities_by_name("Guido")[0]
rels = combined.get_relationships_by_entity(guido)

print(f"Facts about Guido: {len(rels)} relationships")
```

### 4. Cypher Queries (Advanced)

Execute Neo4j-compatible Cypher queries:

```python
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

# Create query engine
engine = UnifiedQueryEngine(backend=your_backend)

# Execute Cypher query
results = engine.execute_cypher("""
    MATCH (p:Person)-[r:WORKED_AT]->(o:Organization)
    WHERE p.name = 'Marie Curie'
    RETURN p, r, o
""")

for record in results:
    print(f"Person: {record['p'].name}")
    print(f"Organization: {record['o'].name}")
```

### 5. Hybrid Search (Vector + Graph)

Combine vector similarity with graph structure:

```python
from ipfs_datasets_py.knowledge_graphs.query import HybridSearchEngine

# Create hybrid search engine
hybrid = HybridSearchEngine(
    graph=kg,
    vector_store=vector_store
)

# Search with both vector and graph signals
results = hybrid.search(
    query="Nobel Prize winners in Physics",
    top_k=10,
    hybrid_weight=0.7  # 70% vector, 30% graph
)

for result in results:
    print(f"{result.entity.name} (score: {result.score:.3f})")
```

---

## Storage Options

### 1. In-Memory Storage

Simple and fast for development:

```python
# Create graph (stored in memory)
kg = KnowledgeGraph(name="my_graph")
kg.add_entity(entity)
kg.add_relationship(relationship)

# Access is instant but not persistent
```

### 2. JSON Serialization

Save and load graphs as JSON:

```python
# Export to JSON
json_data = kg.to_json()

# Save to file
with open("knowledge_graph.json", "w") as f:
    f.write(json_data)

# Load from JSON
with open("knowledge_graph.json") as f:
    json_data = f.read()
    
kg_loaded = KnowledgeGraph.from_json(json_data)
print(f"Loaded {len(kg_loaded.entities)} entities")
```

### 3. IPLD/IPFS Backend (Production)

Store graphs on IPFS for distributed, verifiable storage:

```python
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

# Create IPLD backend
backend = IPLDBackend(ipfs_client=ipfs_client)

# Store graph (returns CID)
cid = backend.store(kg, codec="dag-cbor")
print(f"Stored at CID: {cid}")

# Retrieve graph
kg_retrieved = backend.retrieve(cid)
print(f"Retrieved {len(kg_retrieved.entities)} entities")
```

### 4. Caching for Performance

Implement caching to avoid redundant extraction:

```python
import hashlib
import os
import json

class CachedExtractor:
    def __init__(self, cache_dir="kg_cache"):
        self.cache_dir = cache_dir
        self.extractor = KnowledgeGraphExtractor()
        os.makedirs(cache_dir, exist_ok=True)
    
    def extract(self, text, use_cache=True):
        # Generate cache key
        cache_key = hashlib.sha256(text.encode()).hexdigest()
        cache_path = os.path.join(self.cache_dir, f"{cache_key}.json")
        
        # Check cache
        if use_cache and os.path.exists(cache_path):
            with open(cache_path) as f:
                return KnowledgeGraph.from_json(f.read())
        
        # Extract and cache
        kg = self.extractor.extract_knowledge_graph(text)
        with open(cache_path, "w") as f:
            f.write(kg.to_json())
        
        return kg

# Usage
cached_extractor = CachedExtractor()
kg = cached_extractor.extract(text)  # First call: extracts
kg = cached_extractor.extract(text)  # Second call: uses cache (instant)
```

### 5. Redis Caching (High-Throughput)

For production systems with high throughput:

```python
import redis

class RedisKnowledgeCache:
    def __init__(self):
        self.redis = redis.Redis(host='localhost', port=6379, db=0)
        self.extractor = KnowledgeGraphExtractor()
    
    def get_or_extract(self, text, ttl=3600):
        cache_key = f"kg:{hashlib.sha256(text.encode()).hexdigest()}"
        
        # Try cache
        cached = self.redis.get(cache_key)
        if cached:
            return KnowledgeGraph.from_json(cached.decode())
        
        # Extract and cache
        kg = self.extractor.extract_knowledge_graph(text)
        self.redis.setex(cache_key, ttl, kg.to_json())
        return kg
```

---

## Transaction Management

### 1. Incremental Updates with Versioning

Track changes over time:

```python
class IncrementalKnowledgeGraph:
    def __init__(self, name):
        self.name = name
        self.versions = {0: KnowledgeGraph(name=name)}
        self.current_version = 0
    
    def update(self, new_kg, description=""):
        # Merge new knowledge
        self.versions[self.current_version].merge(new_kg)
        self.current_version += 1
        
        print(f"Updated to version {self.current_version}: {description}")
    
    def rollback(self, version):
        if version in self.versions:
            self.current_version = version
            return self.versions[version]
        raise ValueError(f"Version {version} not found")
    
    def get_current(self):
        return self.versions[self.current_version]

# Usage
incremental = IncrementalKnowledgeGraph("research_kb")
incremental.update(kg1, "Added initial papers")
incremental.update(kg2, "Added related work")
incremental.rollback(1)  # Revert to previous version
```

### 2. Checkpoint-Based Processing

Save progress during long-running operations:

```python
import os
import json

def process_large_batch(file_paths, checkpoint_file="checkpoint.json"):
    extractor = KnowledgeGraphExtractor()
    combined_kg = KnowledgeGraph(name="batch_result")
    
    # Load checkpoint if exists
    processed_files = set()
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file) as f:
            checkpoint = json.load(f)
            combined_kg = KnowledgeGraph.from_dict(checkpoint["kg"])
            processed_files = set(checkpoint["processed"])
    
    # Process files
    for i, file_path in enumerate(file_paths):
        if file_path in processed_files:
            continue
        
        # Extract and merge
        with open(file_path) as f:
            kg = extractor.extract_knowledge_graph(f.read())
            combined_kg.merge(kg)
        
        processed_files.add(file_path)
        
        # Save checkpoint every 10 files
        if (i + 1) % 10 == 0:
            with open(checkpoint_file, "w") as f:
                json.dump({
                    "kg": combined_kg.to_dict(),
                    "processed": list(processed_files)
                }, f)
            print(f"Checkpoint saved: {i+1}/{len(file_paths)} files")
    
    return combined_kg
```

### 3. ACID Transactions

Use transaction manager for atomic operations:

```python
from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager

# Create transaction manager
tx_manager = TransactionManager(backend=backend)

# Begin transaction
tx = tx_manager.begin_transaction()

try:
    # Perform operations
    tx.add_entity(entity1)
    tx.add_entity(entity2)
    tx.add_relationship(relationship)
    
    # Commit changes
    tx_manager.commit(tx)
    print("Transaction committed successfully")
    
except Exception as e:
    # Rollback on error
    tx_manager.rollback(tx)
    print(f"Transaction rolled back: {e}")
```

---

## Integration Patterns

### 1. Extract → Validate → Query Pipeline

```python
# Step 1: Extract knowledge graph
kg = extractor.extract_knowledge_graph(text)

# Step 2: Validate against external sources
validation = extractor.validate_against_wikidata(kg, "Marie Curie")
coverage = validation['coverage']

if coverage < 0.5:
    print(f"Warning: Low validation coverage ({coverage:.2%})")

# Step 3: Enrich with type information
enriched_kg = KnowledgeGraphExtractor.enrich_with_types(kg)

# Step 4: Query enriched graph
persons = enriched_kg.get_entities_by_type("person")
for person in persons:
    rels = enriched_kg.get_relationships_by_entity(person)
    print(f"{person.name}: {len(rels)} relationships")
```

### 2. Real-Time Knowledge Building

Build a continuously-updated knowledge graph:

```python
class KnowledgeGraphSystem:
    def __init__(self):
        self.kg = KnowledgeGraph(name="live_knowledge")
        self.extractor = KnowledgeGraphExtractor()
    
    def add_document(self, text, metadata=None):
        # Extract from new document
        doc_kg = self.extractor.extract_knowledge_graph(text)
        
        # Merge into main graph
        self.kg.merge(doc_kg)
        
        return {
            "entities_added": len(doc_kg.entities),
            "relationships_added": len(doc_kg.relationships),
            "total_entities": len(self.kg.entities)
        }
    
    def query_entity(self, name):
        entities = self.kg.get_entities_by_name(name)
        if not entities:
            return None
        
        entity = entities[0]
        rels = self.kg.get_relationships_by_entity(entity)
        
        return {
            "entity": entity,
            "relationships": rels,
            "related_count": len(rels)
        }
    
    def find_connection(self, name1, name2):
        entities1 = self.kg.get_entities_by_name(name1)
        entities2 = self.kg.get_entities_by_name(name2)
        
        if not entities1 or not entities2:
            return None
        
        path = self.kg.find_path(entities1[0].id, entities2[0].id, max_depth=5)
        
        return {
            "connected": path is not None,
            "path_length": len(path) if path else None,
            "path_entities": [self.kg.entities[id] for id in path] if path else []
        }

# Usage
system = KnowledgeGraphSystem()
system.add_document("Marie Curie won Nobel Prize...")
system.add_document("Albert Einstein developed relativity...")
connection = system.find_connection("Marie Curie", "Albert Einstein")
```

### 3. Parallel Extraction

Process multiple documents in parallel:

```python
from concurrent.futures import ProcessPoolExecutor
import multiprocessing

def extract_from_file(file_path):
    extractor = KnowledgeGraphExtractor()
    with open(file_path) as f:
        text = f.read()
    kg = extractor.extract_knowledge_graph(text)
    return kg.to_dict()

def parallel_extraction(file_paths, max_workers=None):
    if max_workers is None:
        max_workers = multiprocessing.cpu_count()
    
    # Extract in parallel
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(extract_from_file, file_paths))
    
    # Merge results
    combined = KnowledgeGraph(name="parallel_combined")
    for kg_dict in results:
        kg = KnowledgeGraph.from_dict(kg_dict)
        combined.merge(kg)
    
    return combined

# Usage
file_paths = ["doc1.txt", "doc2.txt", "doc3.txt", "doc4.txt"]
kg = parallel_extraction(file_paths, max_workers=4)
print(f"Processed {len(file_paths)} files in parallel")
print(f"Total entities: {len(kg.entities)}")
```

### 4. Multi-Source Knowledge Fusion

Combine knowledge from multiple sources with conflict resolution:

```python
class MultiSourceKnowledgeFusion:
    def __init__(self):
        self.source_graphs = {}
        self.extractor = KnowledgeGraphExtractor()
    
    def add_source(self, source_id, text, metadata=None):
        kg = self.extractor.extract_knowledge_graph(text)
        kg.metadata = metadata or {}
        kg.metadata['source_id'] = source_id
        self.source_graphs[source_id] = kg
    
    def fuse(self, conflict_resolution="vote"):
        fused = KnowledgeGraph(name="fused_knowledge")
        
        for source_id, kg in self.source_graphs.items():
            # Merge with source tracking
            for entity in kg.entities.values():
                entity.properties['source'] = source_id
            fused.merge(kg)
        
        return fused

# Usage
fusion = MultiSourceKnowledgeFusion()
fusion.add_source("wikipedia", wiki_text)
fusion.add_source("news", news_text)
fusion.add_source("research", paper_text)
fused_kg = fusion.fuse()
```

---

## Production Best Practices

### 1. Error Handling & Retry Logic

```python
import time

def extract_with_retry(text, extractor, max_retries=3, retry_delay=2):
    """Extract with exponential backoff retry logic."""
    for attempt in range(max_retries):
        try:
            return extractor.extract_knowledge_graph(text)
        except RuntimeError as e:
            if attempt < max_retries - 1:
                print(f"Attempt {attempt + 1} failed, retrying...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"All {max_retries} attempts failed")
                raise
        except ValueError as e:
            # Don't retry on validation errors
            print(f"Validation error: {e}")
            raise

# Usage
try:
    kg = extract_with_retry(text, extractor)
except Exception as e:
    print(f"Extraction failed: {e}")
```

### 2. Logging & Monitoring

```python
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MonitoredExtractor:
    def __init__(self):
        self.extractor = KnowledgeGraphExtractor()
        self.stats = {
            "total_extractions": 0,
            "total_time": 0.0,
            "total_entities": 0,
            "total_relationships": 0,
            "errors": 0
        }
    
    def extract(self, text, **kwargs):
        start = time.time()
        
        try:
            kg = self.extractor.extract_knowledge_graph(text, **kwargs)
            elapsed = time.time() - start
            
            # Update stats
            self.stats["total_extractions"] += 1
            self.stats["total_time"] += elapsed
            self.stats["total_entities"] += len(kg.entities)
            self.stats["total_relationships"] += len(kg.relationships)
            
            # Log
            logger.info(
                f"Extraction successful: "
                f"{len(kg.entities)} entities, "
                f"{len(kg.relationships)} relationships, "
                f"{elapsed:.2f}s"
            )
            
            return kg
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Extraction failed: {e}")
            raise
    
    def get_stats(self):
        avg_time = (self.stats["total_time"] / self.stats["total_extractions"] 
                    if self.stats["total_extractions"] > 0 else 0)
        return {
            **self.stats,
            "avg_extraction_time": avg_time
        }

# Usage
monitored = MonitoredExtractor()
for text in documents:
    kg = monitored.extract(text)

print(f"Statistics: {monitored.get_stats()}")
```

### 3. Temperature Settings by Use Case

```python
# Conservative: Legal documents, contracts
legal_extractor = KnowledgeGraphExtractor()
kg = legal_extractor.extract_knowledge_graph(
    legal_text,
    extraction_temperature=0.2  # Only extract clear, explicit facts
)

# Balanced: News articles, documentation
news_extractor = KnowledgeGraphExtractor()
kg = news_extractor.extract_knowledge_graph(
    news_text,
    extraction_temperature=0.6  # Balance between precision and recall
)

# Detailed: Research papers, exploratory analysis
research_extractor = KnowledgeGraphExtractor()
kg = research_extractor.extract_knowledge_graph(
    research_text,
    extraction_temperature=0.9  # Extract all possible relationships
)
```

### 4. Validation Best Practices

```python
# Always validate entities with low confidence
for entity in kg.entities.values():
    if entity.confidence < 0.7:
        validation = extractor.validate_against_wikidata(kg, entity.name)
        
        if validation['coverage'] < 0.5:
            logger.warning(
                f"Low validation for {entity.name}: "
                f"{validation['coverage']:.2%} coverage"
            )
            
            # Consider removing or flagging low-confidence entities
            entity.properties['needs_review'] = True
```

### 5. Resource Monitoring

```python
import psutil
import os

class ResourceMonitor:
    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.initial_memory = self.get_memory_usage()
    
    def get_memory_usage(self):
        return self.process.memory_info().rss / 1024 / 1024  # MB
    
    def get_cpu_percent(self):
        return self.process.cpu_percent(interval=1)
    
    def log_resources(self, stage):
        memory = self.get_memory_usage()
        cpu = self.get_cpu_percent()
        memory_delta = memory - self.initial_memory
        
        logger.info(
            f"{stage}: Memory={memory:.1f}MB (+{memory_delta:.1f}MB), "
            f"CPU={cpu:.1f}%"
        )

# Usage
monitor = ResourceMonitor()
monitor.log_resources("Start")

kg = extractor.extract_knowledge_graph(large_text)
monitor.log_resources("After extraction")

combined_kg.merge(kg)
monitor.log_resources("After merge")
```

---

## Troubleshooting Guide

### Common Issues and Solutions

| Issue | Possible Causes | Solutions |
|-------|----------------|-----------|
| **No entities extracted** | • Text has no proper nouns<br>• Temperature too low<br>• spaCy model not loaded | • Increase extraction_temperature (0.7-0.9)<br>• Check text has entities<br>• Run `python -m spacy download en_core_web_sm` |
| **Wikipedia extraction fails** | • Page doesn't exist<br>• Spelling error in title<br>• Network issues | • Verify page exists on Wikipedia<br>• Try alternate spellings<br>• Use try-except for ValueErrors |
| **Validation fails** | • Entity not in Wikidata<br>• Name spelling different<br>• Validation service down | • Check entity exists in Wikidata<br>• Try variations of entity name<br>• Validation is optional, can skip |
| **Low confidence scores** | • Ambiguous text<br>• Conservative temperature<br>• Complex relationships | • Increase temperature<br>• Validate against external sources<br>• Review extraction patterns |
| **Memory issues** | • Processing too many docs<br>• Large document size<br>• Not clearing graphs | • Use chunking for large docs<br>• Process in smaller batches<br>• Delete graphs when done |
| **Slow extraction** | • No caching<br>• Single-threaded<br>• High temperature | • Implement caching (Redis/file)<br>• Use parallel processing<br>• Lower temperature (0.3-0.5) |
| **Merge conflicts** | • Duplicate entity names<br>• Different entity types<br>• Conflicting relationships | • Entities merged by name<br>• Review entity types<br>• Use confidence to resolve |

### Exception Handling

```python
from ipfs_datasets_py.knowledge_graphs.exceptions import (
    ExtractionError,
    ValidationError,
    StorageError
)

try:
    kg = extractor.extract_knowledge_graph(text)
except ValueError as e:
    # Invalid input or Wikipedia page not found
    print(f"Input error: {e}")
except RuntimeError as e:
    # Extraction API failure or internal error
    print(f"Extraction failed: {e}")
except Exception as e:
    # Unexpected errors
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise
```

### Debugging Tips

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Inspect extraction results
kg = extractor.extract_knowledge_graph(text)
print(f"Entities: {len(kg.entities)}")
print(f"Relationships: {len(kg.relationships)}")

# Check entity details
for entity in kg.entities.values():
    print(f"Entity: {entity.name}")
    print(f"  Type: {entity.entity_type}")
    print(f"  Confidence: {entity.confidence:.2f}")
    print(f"  Properties: {entity.properties}")

# Check relationship details
for rel in kg.relationships.values():
    print(f"Relationship: {rel.source} --[{rel.relationship_type}]--> {rel.target}")
    print(f"  Confidence: {rel.confidence:.2f}")
    print(f"  Properties: {rel.properties}")
```

### Performance Tuning

```python
# Profile extraction time
import time

start = time.time()
kg = extractor.extract_knowledge_graph(text)
elapsed = time.time() - start

print(f"Extraction time: {elapsed:.2f}s")
print(f"Entities per second: {len(kg.entities) / elapsed:.1f}")

# Optimize for speed
fast_extractor = KnowledgeGraphExtractor()
kg = fast_extractor.extract_knowledge_graph(
    text,
    extraction_temperature=0.3,  # Lower = faster
    use_chunking=False           # Skip chunking if not needed
)

# Optimize for detail
detailed_extractor = KnowledgeGraphExtractor()
kg = detailed_extractor.extract_knowledge_graph(
    text,
    extraction_temperature=0.9,  # Higher = more entities/relationships
    use_chunking=True            # Handle large documents
)
```

---

## Examples Gallery

### Example 1: Scientific Paper Processing

```python
# Extract knowledge from research paper
paper_text = """
Deep learning is a subset of machine learning based on artificial neural networks.
Geoffrey Hinton, Yann LeCun, and Yoshua Bengio pioneered deep learning research.
In 2012, AlexNet won the ImageNet competition, demonstrating the power of deep CNNs.
"""

kg = extractor.extract_knowledge_graph(paper_text, extraction_temperature=0.8)

# Query extracted knowledge
technologies = kg.get_entities_by_type("technology")
persons = kg.get_entities_by_type("person")

print("Technologies:")
for tech in technologies:
    print(f"  - {tech.name}")

print("\nPioneers:")
for person in persons:
    print(f"  - {person.name}")
```

**Expected Output:**
```
Technologies:
  - Deep learning
  - Machine learning
  - Artificial neural networks
  - AlexNet
  - ImageNet

Pioneers:
  - Geoffrey Hinton
  - Yann LeCun
  - Yoshua Bengio
```

### Example 2: Company Information Extraction

```python
# Extract company relationships
company_text = """
Apple Inc. was founded by Steve Jobs, Steve Wozniak, and Ronald Wayne in 1976.
The company is headquartered in Cupertino, California.
Tim Cook became CEO of Apple in 2011.
"""

kg = extractor.extract_knowledge_graph(company_text, extraction_temperature=0.6)

# Find all relationships involving Apple
apple_entities = kg.get_entities_by_name("Apple")
if apple_entities:
    apple = apple_entities[0]
    rels = kg.get_relationships_by_entity(apple)
    
    print(f"Facts about {apple.name}:")
    for rel in rels:
        print(f"  - {rel.relationship_type}: {rel.target}")
```

**Expected Output:**
```
Facts about Apple:
  - FOUNDED_BY: Steve Jobs
  - FOUNDED_BY: Steve Wozniak
  - FOUNDED_BY: Ronald Wayne
  - LOCATED_IN: Cupertino
  - LED_BY: Tim Cook
```

### Example 3: Historical Event Timeline

```python
# Extract events and dates
history_text = """
World War II began in 1939 and ended in 1945.
The United Nations was established in 1945 to promote international cooperation.
The Cold War lasted from 1947 to 1991.
"""

kg = extractor.extract_knowledge_graph(history_text, extraction_temperature=0.7)

# Extract events with dates
events = kg.get_entities_by_type("event")
for event in sorted(events, key=lambda e: e.properties.get('year', '9999')):
    year = event.properties.get('year', 'Unknown')
    print(f"{year}: {event.name}")
```

**Expected Output:**
```
1939: World War II began
1945: World War II ended
1945: United Nations established
1947: Cold War started
1991: Cold War ended
```

### Example 4: Multi-Document Knowledge Base

```python
# Build knowledge base from multiple documents
documents = [
    "Python was created by Guido van Rossum in 1991.",
    "Guido van Rossum worked at Google from 2005 to 2012.",
    "Google was founded by Larry Page and Sergey Brin in 1998."
]

# Extract and merge
combined_kg = KnowledgeGraph(name="tech_history")
for text in documents:
    kg = extractor.extract_knowledge_graph(text)
    combined_kg.merge(kg)

# Query combined knowledge
print(f"Total entities: {len(combined_kg.entities)}")
print(f"Total relationships: {len(combined_kg.relationships)}")

# Find connection between Python and Google
python_entities = combined_kg.get_entities_by_name("Python")
google_entities = combined_kg.get_entities_by_name("Google")

if python_entities and google_entities:
    path = combined_kg.find_path(python_entities[0].id, google_entities[0].id)
    if path:
        print(f"\nConnection found (path length: {len(path)}):")
        for entity_id in path:
            entity = combined_kg.entities[entity_id]
            print(f"  → {entity.name}")
```

**Expected Output:**
```
Total entities: 6
Total relationships: 5

Connection found (path length: 3):
  → Python
  → Guido van Rossum
  → Google
```

### Example 5: Real-World Production Pipeline

```python
import os
import json
from datetime import datetime

class ProductionKnowledgeSystem:
    def __init__(self, cache_dir="kg_cache", output_dir="kg_output"):
        self.cache_dir = cache_dir
        self.output_dir = output_dir
        self.extractor = CachedExtractor(cache_dir)
        self.monitor = ResourceMonitor()
        self.stats = {
            "documents_processed": 0,
            "total_entities": 0,
            "total_relationships": 0,
            "start_time": datetime.now()
        }
        
        os.makedirs(output_dir, exist_ok=True)
    
    def process_directory(self, input_dir, output_file="knowledge_graph.json"):
        combined_kg = KnowledgeGraph(name="production_kg")
        
        # Get all text files
        file_paths = [
            os.path.join(input_dir, f) 
            for f in os.listdir(input_dir) 
            if f.endswith('.txt')
        ]
        
        logger.info(f"Processing {len(file_paths)} files...")
        
        # Process each file
        for i, file_path in enumerate(file_paths):
            try:
                with open(file_path) as f:
                    text = f.read()
                
                # Extract with retry and caching
                kg = extract_with_retry(text, self.extractor, max_retries=3)
                
                # Merge into combined graph
                combined_kg.merge(kg)
                
                # Update stats
                self.stats["documents_processed"] += 1
                self.stats["total_entities"] = len(combined_kg.entities)
                self.stats["total_relationships"] = len(combined_kg.relationships)
                
                # Log progress
                if (i + 1) % 10 == 0:
                    self.monitor.log_resources(f"After {i+1} files")
                    logger.info(f"Progress: {i+1}/{len(file_paths)} files")
                
            except Exception as e:
                logger.error(f"Failed to process {file_path}: {e}")
                continue
        
        # Save final graph
        output_path = os.path.join(self.output_dir, output_file)
        with open(output_path, "w") as f:
            f.write(combined_kg.to_json())
        
        # Compute final stats
        elapsed = (datetime.now() - self.stats["start_time"]).total_seconds()
        self.stats["total_time"] = elapsed
        self.stats["avg_time_per_doc"] = elapsed / self.stats["documents_processed"]
        
        # Save stats
        stats_path = os.path.join(self.output_dir, "stats.json")
        with open(stats_path, "w") as f:
            json.dump({k: str(v) for k, v in self.stats.items()}, f, indent=2)
        
        logger.info(f"Processing complete: {output_path}")
        logger.info(f"Stats: {json.dumps(self.stats, indent=2, default=str)}")
        
        return combined_kg

# Usage
system = ProductionKnowledgeSystem()
kg = system.process_directory("documents/", "final_knowledge_graph.json")
```

---

## 11. Future Roadmap

### Planned Enhancements (v2.1-3.0)

The following features are planned for future releases based on user feedback and emerging requirements:

#### v2.1.0 - Enhanced Query Capabilities (Q2 2026)

**1. NOT Operator Support in Cypher**
- **Location:** `cypher/compiler.py:387`
- **Description:** Full support for NOT operator in WHERE clauses
- **Benefits:** More expressive query filtering
- **Timeline:** Q2 2026
- **Example:**
  ```python
  # Future capability
  query = "MATCH (p:Person) WHERE NOT p.age > 30 RETURN p"
  ```

**2. Relationship Creation in Cypher**
- **Location:** `cypher/compiler.py:510`
- **Description:** CREATE clause support for dynamic relationship creation
- **Benefits:** Graph modification capabilities via Cypher
- **Timeline:** Q2 2026
- **Example:**
  ```python
  # Future capability
  query = "MATCH (a:Person), (b:Person) CREATE (a)-[:KNOWS]->(b)"
  ```

#### v2.5.0 - Advanced Extraction (Q3-Q4 2026)

**3. Neural Relationship Extraction**
- **Location:** `extraction/extractor.py:733`
- **Description:** Deep learning models for relationship extraction
- **Benefits:** Higher precision on complex relationships
- **Timeline:** Q3 2026
- **Models:** BERT, RoBERTa, or custom transformers

**4. Aggressive Extraction with spaCy Dependency Parsing**
- **Location:** `extraction/extractor.py:870`
- **Description:** Full dependency tree analysis for complex sentences
- **Benefits:** Extract relationships from complex syntactic structures
- **Timeline:** Q3 2026

**5. Semantic Role Labeling (SRL) for Relationship Inference**
- **Location:** `extraction/extractor.py:893`
- **Description:** Advanced SRL for implicit relationship discovery
- **Benefits:** Understand agent, patient, theme roles
- **Timeline:** Q4 2026
- **Libraries:** AllenNLP, spaCy SRL extensions

#### v3.0.0 - Cross-Document Intelligence (Q1 2027)

**6. Multi-Hop Graph Traversal**
- **Location:** `cross_document_reasoning.py:483`
- **Description:** Indirect connection discovery across documents
- **Benefits:** Find non-obvious relationships (friend-of-friend, transitive)
- **Timeline:** Q1 2027
- **Algorithms:** BFS, DFS, PageRank, community detection

**7. LLM Integration for Advanced Reasoning**
- **Location:** `cross_document_reasoning.py:686`
- **Description:** Large Language Model API integration
- **Benefits:** Advanced semantic understanding and reasoning
- **Timeline:** Q1 2027
- **Providers:** OpenAI, Anthropic, or local models (Llama, Mistral)
- **Use Cases:**
  - Complex query interpretation
  - Semantic similarity beyond embeddings
  - Natural language explanations
  - Zero-shot entity/relationship classification

### Feature Request Process

**How to Request a Feature:**
1. Check existing roadmap above
2. Open a GitHub issue with label `enhancement`
3. Provide:
   - Use case description
   - Expected behavior
   - Example code/queries
   - Performance requirements

**Priority Criteria:**
- User demand (votes/comments)
- Implementation complexity
- Compatibility with existing API
- Performance impact

### Experimental Features

Some features may be available as experimental APIs before full release:

```python
from ipfs_datasets_py.knowledge_graphs.experimental import (
    NeuralExtractor,  # v2.5.0-alpha
    SRLRelationshipExtractor,  # v2.5.0-alpha
    LLMReasoningEngine,  # v3.0.0-alpha
)

# Enable experimental features at your own risk
extractor = NeuralExtractor(model="roberta-base", experimental=True)
```

**Note:** Experimental APIs may change between versions without deprecation warnings.

### Deprecation Policy

- Features marked deprecated in v2.x will be removed in v3.0
- Minimum 6-month deprecation notice
- Migration guides provided for all breaking changes
- See [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) for details

---

## Further Reading

- [API_REFERENCE.md](API_REFERENCE.md) - Complete API documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture and design patterns
- [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) - Migration paths and known limitations
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development guidelines

---

**Last Updated:** 2026-02-17  
**Version:** 2.0.0  
**Status:** Production-Ready
