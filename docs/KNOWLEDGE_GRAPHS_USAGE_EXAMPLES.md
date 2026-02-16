# Knowledge Graphs - Comprehensive Usage Examples

**Version:** 1.0.0  
**Last Updated:** 2026-02-16  
**Target Audience:** Developers using the knowledge graphs extraction and query packages

## Table of Contents

1. [Basic Extraction Examples](#basic-extraction-examples)
2. [Advanced Extraction Patterns](#advanced-extraction-patterns)
3. [Query Examples](#query-examples)
4. [Integration Workflows](#integration-workflows)
5. [Production Patterns](#production-patterns)
6. [Troubleshooting](#troubleshooting)

---

## Basic Extraction Examples

### Example 1: Simple Entity and Relationship Extraction

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    Entity, Relationship, KnowledgeGraph
)

# Create entities
person = Entity(
    entity_type="person",
    name="Marie Curie",
    properties={
        "birth_year": "1867",
        "nationality": "Polish",
        "field": "Physics"
    },
    confidence=0.95
)

award = Entity(
    entity_type="award",
    name="Nobel Prize",
    properties={
        "field": "Physics",
        "year": "1903"
    },
    confidence=0.98
)

# Create relationship
won_award = Relationship(
    source_entity=person,
    target_entity=award,
    relationship_type="WON",
    properties={"year": "1903", "shared_with": "Pierre Curie"},
    confidence=0.92
)

# Build knowledge graph
kg = KnowledgeGraph(name="scientists_graph")
kg.add_entity(person)
kg.add_entity(award)
kg.add_relationship(won_award)

# Query the graph
print(f"Entities: {len(kg.entities)}")
print(f"Relationships: {len(kg.relationships)}")

# Export to JSON
json_data = kg.to_json()
print(json_data)
```

### Example 2: Automated Text Extraction

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

# Create extractor
extractor = KnowledgeGraphExtractor()

# Sample text
text = """
Albert Einstein was a theoretical physicist who developed the theory of relativity.
He was born in Germany in 1879 and later moved to Switzerland. Einstein won the
Nobel Prize in Physics in 1921 for his explanation of the photoelectric effect.
He worked at Princeton University and became a U.S. citizen in 1940.
"""

# Extract knowledge graph
kg = extractor.extract_knowledge_graph(text)

# Explore results
print(f"Extracted {len(kg.entities)} entities:")
for entity_id, entity in kg.entities.items():
    print(f"  - {entity.name} ({entity.entity_type})")

print(f"\nExtracted {len(kg.relationships)} relationships:")
for rel_id, rel in kg.relationships.items():
    print(f"  - {rel.source_entity.name} --[{rel.relationship_type}]--> {rel.target_entity.name}")
```

### Example 3: Controlled Extraction with Temperature

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()

text = """
Apple Inc. is an American multinational technology company headquartered in 
Cupertino, California. Steve Jobs, Steve Wozniak, and Ronald Wayne founded 
Apple in 1976. The company produces consumer electronics including the iPhone,
iPad, Mac computers, and Apple Watch. Tim Cook became CEO in 2011.
"""

# Conservative extraction - major facts only
kg_conservative = extractor.extract_knowledge_graph(
    text,
    extraction_temperature=0.2,  # Low - conservative
    structure_temperature=0.3     # Flat structure
)
print(f"Conservative: {len(kg_conservative.entities)} entities")

# Balanced extraction
kg_balanced = extractor.extract_knowledge_graph(
    text,
    extraction_temperature=0.6,  # Medium - balanced
    structure_temperature=0.5
)
print(f"Balanced: {len(kg_balanced.entities)} entities")

# Detailed extraction - extract everything
kg_detailed = extractor.extract_knowledge_graph(
    text,
    extraction_temperature=0.9,  # High - detailed
    structure_temperature=0.8    # Rich hierarchies
)
print(f"Detailed: {len(kg_detailed.entities)} entities")
```

---

## Advanced Extraction Patterns

### Example 4: Wikipedia Integration

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()

try:
    # Extract from Wikipedia page
    kg = extractor.extract_from_wikipedia(
        page_title="Artificial Intelligence",
        extraction_temperature=0.7,
        structure_temperature=0.6
    )
    
    print(f"Extracted {len(kg.entities)} entities from Wikipedia")
    
    # Get entities by type
    persons = kg.get_entities_by_type("person")
    organizations = kg.get_entities_by_type("organization")
    
    print(f"Found {len(persons)} people and {len(organizations)} organizations")
    
    # Save to file
    with open("ai_knowledge_graph.json", "w") as f:
        f.write(kg.to_json())
        
except ValueError as e:
    print(f"Page not found: {e}")
except RuntimeError as e:
    print(f"Extraction failed: {e}")
```

### Example 5: Multi-Document Extraction

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()

# Multiple documents about a topic
documents = [
    {
        "text": "Python is a high-level programming language created by Guido van Rossum.",
        "source": "doc1.txt",
        "date": "2024-01-15"
    },
    {
        "text": "Guido van Rossum started working on Python in 1989 while at CWI in the Netherlands.",
        "source": "doc2.txt",
        "date": "2024-01-16"
    },
    {
        "text": "Python is widely used in data science, web development, and artificial intelligence.",
        "source": "doc3.txt",
        "date": "2024-01-17"
    }
]

# Extract and merge knowledge from all documents
kg = extractor.extract_from_documents(
    documents,
    text_key="text",
    extraction_temperature=0.7,
    structure_temperature=0.5
)

print(f"Merged knowledge graph: {len(kg.entities)} entities, {len(kg.relationships)} relationships")

# Entities will be deduplicated automatically
guido_entities = kg.get_entities_by_name("Guido van Rossum")
print(f"Found {len(guido_entities)} entity/entities for Guido van Rossum")
```

### Example 6: Validation Against Wikidata

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation
)

# Option 1: Manual validation
extractor = KnowledgeGraphExtractor()
kg = extractor.extract_knowledge_graph(
    "Albert Einstein developed the theory of relativity."
)

validation = extractor.validate_against_wikidata(kg, "Albert Einstein")
print(f"Coverage: {validation['coverage']:.2%}")
print(f"Missing facts: {len(validation['missing_relationships'])}")

# Option 2: Automatic validation during extraction
validator = KnowledgeGraphExtractorWithValidation(
    validate_during_extraction=True,
    auto_correct_suggestions=True
)

result = validator.extract_knowledge_graph(
    "Albert Einstein developed the theory of relativity.",
    validation_depth=2  # Validate entities and relationships
)

kg = result["knowledge_graph"]
metrics = result["validation_metrics"]
corrections = result.get("corrections", {})

print(f"Validated KG: {metrics['overall_coverage']:.2%} coverage")

if corrections:
    print("Suggested corrections:")
    for entity_id, correction in corrections.get("entities", {}).items():
        print(f"  Entity {entity_id}: {correction}")
```

### Example 7: Custom Relation Patterns

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

# Define domain-specific patterns
custom_patterns = [
    {
        "name": "develops",
        "pattern": r"(\w+(?:\s+\w+)*)\s+develops?\s+(\w+(?:\s+\w+)*)",
        "source_type": "person",
        "target_type": "technology",
        "confidence": 0.85
    },
    {
        "name": "mentored_by",
        "pattern": r"(\w+(?:\s+\w+)*)\s+(?:was\s+)?mentored\s+by\s+(\w+(?:\s+\w+)*)",
        "source_type": "person",
        "target_type": "person",
        "confidence": 0.90
    },
    {
        "name": "leads_project",
        "pattern": r"(\w+(?:\s+\w+)*)\s+leads?\s+(?:the\s+)?(\w+(?:\s+\w+)*)\s+project",
        "source_type": "person",
        "target_type": "project",
        "confidence": 0.88
    }
]

# Create extractor with custom patterns
extractor = KnowledgeGraphExtractor(relation_patterns=custom_patterns)

text = """
Dr. Sarah Johnson develops innovative AI algorithms. She was mentored by 
Professor Michael Chen. Currently, Dr. Johnson leads the Neural Architecture 
project at Stanford University.
"""

kg = extractor.extract_knowledge_graph(text)

# Custom patterns will be used alongside default patterns
for rel_id, rel in kg.relationships.items():
    print(f"{rel.source_entity.name} --[{rel.relationship_type}]--> {rel.target_entity.name}")
```

### Example 8: Large Document Processing

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()

# Load large document
with open("large_research_paper.txt", "r") as f:
    large_text = f.read()  # e.g., 50,000 characters

print(f"Document size: {len(large_text)} characters")

# Use enhanced extraction with chunking
kg = extractor.extract_enhanced_knowledge_graph(
    large_text,
    use_chunking=True,  # Automatically chunks large texts
    extraction_temperature=0.7,
    structure_temperature=0.6
)

print(f"Extracted: {len(kg.entities)} entities, {len(kg.relationships)} relationships")

# Entities from different chunks are automatically merged
# based on name matching and similarity
```

---

## Query Examples

### Example 9: Basic Graph Querying

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor, KnowledgeGraph
)

# Build a knowledge graph
extractor = KnowledgeGraphExtractor()
kg = extractor.extract_knowledge_graph("""
Marie Curie was born in Poland and moved to France. She won the Nobel Prize
in Physics in 1903 and the Nobel Prize in Chemistry in 1911. Pierre Curie
was her husband and research partner. They worked together at the University
of Paris.
""")

# Query by entity type
persons = kg.get_entities_by_type("person")
print(f"Found {len(persons)} people:")
for person in persons:
    print(f"  - {person.name}")

# Query by entity name
marie = kg.get_entities_by_name("Marie Curie")
if marie:
    marie_entity = marie[0]
    
    # Get all relationships for Marie Curie
    marie_rels = kg.get_relationships_by_entity(marie_entity)
    print(f"\nMarie Curie's relationships: {len(marie_rels)}")
    for rel in marie_rels:
        if rel.source_entity.entity_id == marie_entity.entity_id:
            print(f"  → {rel.relationship_type} → {rel.target_entity.name}")
        else:
            print(f"  ← {rel.relationship_type} ← {rel.source_entity.name}")
```

### Example 10: Path Finding

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()
kg = extractor.extract_knowledge_graph("""
Steve Jobs founded Apple. Apple produces the iPhone. The iPhone uses iOS.
iOS is developed by Apple. Tim Cook is the CEO of Apple. Steve Jobs mentored
Tim Cook.
""")

# Find all entities
entities = list(kg.entities.values())
if len(entities) >= 2:
    # Find path between two entities
    source = entities[0]
    target = entities[-1]
    
    path = kg.find_path(source.entity_id, target.entity_id, max_depth=5)
    
    if path:
        print(f"Path from {source.name} to {target.name}:")
        for i, entity_id in enumerate(path):
            entity = kg.get_entity_by_id(entity_id)
            print(f"  {i+1}. {entity.name}")
    else:
        print("No path found")
```

### Example 11: Graph Merging

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor, KnowledgeGraph
)

extractor = KnowledgeGraphExtractor()

# Extract from different sources
kg1 = extractor.extract_knowledge_graph("Python was created by Guido van Rossum.")
kg2 = extractor.extract_knowledge_graph("Guido van Rossum worked at Google.")
kg3 = extractor.extract_knowledge_graph("Python is used for machine learning.")

# Merge graphs
combined_kg = KnowledgeGraph(name="python_combined")
combined_kg.merge(kg1)
combined_kg.merge(kg2)
combined_kg.merge(kg3)

print(f"Combined graph: {len(combined_kg.entities)} entities")
print(f"Original graphs: {len(kg1.entities)}, {len(kg2.entities)}, {len(kg3.entities)}")

# Entities with same name are automatically merged
guido = combined_kg.get_entities_by_name("Guido van Rossum")
if guido:
    # All relationships from different sources are preserved
    relationships = combined_kg.get_relationships_by_entity(guido[0])
    print(f"Guido van Rossum has {len(relationships)} relationships in merged graph")
```

---

## Integration Workflows

### Example 12: Extraction → Validation → Query Pipeline

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation
)

# Step 1: Extract knowledge graph
extractor = KnowledgeGraphExtractor()
text = """
Ada Lovelace is considered the first computer programmer. She worked with
Charles Babbage on the Analytical Engine in the 1840s. Her notes on the
engine include what is recognized as the first algorithm.
"""

kg = extractor.extract_knowledge_graph(text)
print(f"Step 1 - Extracted: {len(kg.entities)} entities")

# Step 2: Validate and enrich
validator = KnowledgeGraphExtractorWithValidation(
    validate_during_extraction=False  # We already have the KG
)

# Manual validation
validation = extractor.validate_against_wikidata(kg, "Ada Lovelace")
print(f"Step 2 - Validation coverage: {validation['coverage']:.2%}")

# Step 3: Enrich with inferred types
enriched_kg = KnowledgeGraphExtractor.enrich_with_types(kg)
print(f"Step 3 - Enriched graph with type inference")

# Step 4: Query the enriched graph
persons = enriched_kg.get_entities_by_type("person")
technologies = enriched_kg.get_entities_by_type("technology")

print(f"Step 4 - Found {len(persons)} people, {len(technologies)} technologies")

# Step 5: Export for use in other systems
json_output = enriched_kg.to_json()
rdf_output = enriched_kg.export_to_rdf()

with open("ada_lovelace_kg.json", "w") as f:
    f.write(json_output)
print("Step 5 - Exported to JSON and RDF")
```

### Example 13: Batch Processing Pipeline

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
import os
import json

extractor = KnowledgeGraphExtractor()

# Process multiple files
input_dir = "documents/"
output_dir = "knowledge_graphs/"

os.makedirs(output_dir, exist_ok=True)

# Track statistics
stats = {
    "processed": 0,
    "total_entities": 0,
    "total_relationships": 0,
    "errors": []
}

for filename in os.listdir(input_dir):
    if filename.endswith(".txt"):
        filepath = os.path.join(input_dir, filename)
        
        try:
            # Read document
            with open(filepath, "r") as f:
                text = f.read()
            
            # Extract knowledge graph
            kg = extractor.extract_knowledge_graph(text)
            
            # Save output
            output_path = os.path.join(
                output_dir,
                filename.replace(".txt", "_kg.json")
            )
            with open(output_path, "w") as f:
                f.write(kg.to_json())
            
            # Update statistics
            stats["processed"] += 1
            stats["total_entities"] += len(kg.entities)
            stats["total_relationships"] += len(kg.relationships)
            
            print(f"✓ Processed {filename}: {len(kg.entities)} entities")
            
        except Exception as e:
            stats["errors"].append({"file": filename, "error": str(e)})
            print(f"✗ Error processing {filename}: {e}")

# Save statistics
with open(os.path.join(output_dir, "statistics.json"), "w") as f:
    json.dump(stats, f, indent=2)

print(f"\nBatch processing complete:")
print(f"  Processed: {stats['processed']} files")
print(f"  Total entities: {stats['total_entities']}")
print(f"  Total relationships: {stats['total_relationships']}")
print(f"  Errors: {len(stats['errors'])}")
```

### Example 14: Incremental Knowledge Building

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor, KnowledgeGraph
)
import json
import os

extractor = KnowledgeGraphExtractor()

# Knowledge base file
KB_FILE = "company_knowledge_base.json"

# Load existing knowledge base or create new
if os.path.exists(KB_FILE):
    with open(KB_FILE, "r") as f:
        kb = KnowledgeGraph.from_json(f.read())
    print(f"Loaded existing KB: {len(kb.entities)} entities")
else:
    kb = KnowledgeGraph(name="company_kb")
    print("Created new knowledge base")

# New information to add
new_information = [
    "John Smith joined the engineering team in 2023.",
    "The engineering team is developing a new product called ProjectX.",
    "ProjectX uses machine learning algorithms.",
    "Sarah Johnson leads the engineering team."
]

# Incrementally add knowledge
for info in new_information:
    # Extract from new information
    new_kg = extractor.extract_knowledge_graph(info)
    
    # Merge into knowledge base
    kb.merge(new_kg)
    
    print(f"Added: {info[:50]}...")

# Save updated knowledge base
with open(KB_FILE, "w") as f:
    f.write(kb.to_json())

print(f"\nUpdated KB: {len(kb.entities)} entities, {len(kb.relationships)} relationships")

# Query the knowledge base
team_entities = kb.get_entities_by_type("team")
project_entities = kb.get_entities_by_type("project")

print(f"Teams: {len(team_entities)}, Projects: {len(project_entities)}")
```

---

## Production Patterns

### Example 15: Error Handling and Retry Logic

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor,
    KnowledgeGraph
)
import time
from typing import Optional

def extract_with_retry(
    text: str,
    extractor: KnowledgeGraphExtractor,
    max_retries: int = 3,
    retry_delay: int = 2
) -> Optional[KnowledgeGraph]:
    """
    Extract knowledge graph with retry logic.
    """
    for attempt in range(max_retries):
        try:
            kg = extractor.extract_knowledge_graph(text)
            return kg
        except RuntimeError as e:
            if attempt < max_retries - 1:
                print(f"Attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"All {max_retries} attempts failed")
                raise
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None
    
    return None

# Usage
extractor = KnowledgeGraphExtractor()
text = "Some text to extract from..."

kg = extract_with_retry(text, extractor)
if kg:
    print(f"Successfully extracted: {len(kg.entities)} entities")
else:
    print("Extraction failed after retries")
```

### Example 16: Logging and Monitoring

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor
import logging
import time
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('kg_extraction.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MonitoredExtractor:
    """Wrapper for extraction with logging and metrics."""
    
    def __init__(self):
        self.extractor = KnowledgeGraphExtractor()
        self.stats = {
            "total_extractions": 0,
            "total_entities": 0,
            "total_relationships": 0,
            "total_time": 0.0,
            "errors": 0
        }
    
    def extract(self, text: str, **kwargs):
        """Extract with monitoring."""
        start_time = time.time()
        
        try:
            logger.info(f"Starting extraction for text of length {len(text)}")
            
            kg = self.extractor.extract_knowledge_graph(text, **kwargs)
            
            # Update statistics
            elapsed = time.time() - start_time
            self.stats["total_extractions"] += 1
            self.stats["total_entities"] += len(kg.entities)
            self.stats["total_relationships"] += len(kg.relationships)
            self.stats["total_time"] += elapsed
            
            logger.info(
                f"Extraction complete: {len(kg.entities)} entities, "
                f"{len(kg.relationships)} relationships in {elapsed:.2f}s"
            )
            
            return kg
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"Extraction failed: {e}", exc_info=True)
            raise
    
    def get_stats(self):
        """Get extraction statistics."""
        if self.stats["total_extractions"] > 0:
            avg_time = self.stats["total_time"] / self.stats["total_extractions"]
            avg_entities = self.stats["total_entities"] / self.stats["total_extractions"]
        else:
            avg_time = 0
            avg_entities = 0
        
        return {
            **self.stats,
            "avg_time_per_extraction": avg_time,
            "avg_entities_per_extraction": avg_entities
        }

# Usage
extractor = MonitoredExtractor()

texts = [
    "Python is a programming language.",
    "JavaScript was created by Brendan Eich.",
    "Ruby was designed by Yukihiro Matsumoto."
]

for text in texts:
    kg = extractor.extract(text)

# Print statistics
stats = extractor.get_stats()
print("\nExtraction Statistics:")
for key, value in stats.items():
    print(f"  {key}: {value}")
```

### Example 17: Caching for Performance

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor, KnowledgeGraph
)
import hashlib
import json
import os
from typing import Optional

class CachedExtractor:
    """Extractor with file-based caching."""
    
    def __init__(self, cache_dir: str = ".kg_cache"):
        self.extractor = KnowledgeGraphExtractor()
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def _get_cache_key(self, text: str, **kwargs) -> str:
        """Generate cache key from text and parameters."""
        content = text + json.dumps(kwargs, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _get_cache_path(self, cache_key: str) -> str:
        """Get cache file path."""
        return os.path.join(self.cache_dir, f"{cache_key}.json")
    
    def extract(self, text: str, use_cache: bool = True, **kwargs) -> KnowledgeGraph:
        """Extract with caching."""
        cache_key = self._get_cache_key(text, **kwargs)
        cache_path = self._get_cache_path(cache_key)
        
        # Try to load from cache
        if use_cache and os.path.exists(cache_path):
            print(f"Loading from cache: {cache_key[:12]}...")
            with open(cache_path, "r") as f:
                return KnowledgeGraph.from_json(f.read())
        
        # Extract and cache
        print(f"Extracting (cache miss): {cache_key[:12]}...")
        kg = self.extractor.extract_knowledge_graph(text, **kwargs)
        
        # Save to cache
        with open(cache_path, "w") as f:
            f.write(kg.to_json())
        
        return kg
    
    def clear_cache(self):
        """Clear all cached extractions."""
        for filename in os.listdir(self.cache_dir):
            os.remove(os.path.join(self.cache_dir, filename))
        print(f"Cache cleared: {self.cache_dir}")

# Usage
extractor = CachedExtractor()

text = "The quick brown fox jumps over the lazy dog."

# First call - extracts and caches
kg1 = extractor.extract(text)
print(f"First call: {len(kg1.entities)} entities")

# Second call - loads from cache (much faster)
kg2 = extractor.extract(text)
print(f"Second call (cached): {len(kg2.entities)} entities")

# Force re-extraction
kg3 = extractor.extract(text, use_cache=False)
print(f"Third call (no cache): {len(kg3.entities)} entities")
```

---

## Troubleshooting

### Common Issues and Solutions

#### Issue 1: No entities extracted

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()
text = "Some text here"
kg = extractor.extract_knowledge_graph(text)

if len(kg.entities) == 0:
    print("No entities extracted. Try:")
    print("1. Increase extraction_temperature (0.7-0.9)")
    print("2. Check if text has proper nouns/entities")
    print("3. Use rule-based extraction for simple cases")
    
    # Try with higher temperature
    kg = extractor.extract_knowledge_graph(
        text,
        extraction_temperature=0.9,
        structure_temperature=0.8
    )
    print(f"With high temperature: {len(kg.entities)} entities")
```

#### Issue 2: Wikipedia extraction fails

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()

# Handle Wikipedia errors
page_titles = ["Artificial Intelligence", "Nonexistent Page 12345", "Python (programming language)"]

for title in page_titles:
    try:
        kg = extractor.extract_from_wikipedia(title)
        print(f"✓ {title}: {len(kg.entities)} entities")
    except ValueError as e:
        print(f"✗ {title}: Page not found - {e}")
    except RuntimeError as e:
        print(f"✗ {title}: Extraction error - {e}")
    except Exception as e:
        print(f"✗ {title}: Unexpected error - {e}")
```

#### Issue 3: Validation fails

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation
)

# If validation fails, check if entity exists in Wikidata
extractor = KnowledgeGraphExtractor()
kg = extractor.extract_knowledge_graph("Some famous person did something.")

validation = extractor.validate_against_wikidata(kg, "Some famous person")

if "error" in validation:
    print(f"Validation error: {validation['error']}")
    print("Tips:")
    print("- Check entity name spelling")
    print("- Ensure entity exists in Wikidata")
    print("- Try validation with different entity name")
```

---

## Additional Resources

- **API Documentation:** See `KNOWLEDGE_GRAPHS_EXTRACTION_API.md`
- **Architecture:** See `KNOWLEDGE_GRAPHS_QUERY_ARCHITECTURE.md`
- **Test Examples:** See `tests/unit/knowledge_graphs/test_extraction.py`
- **Migration Guide:** Included in API documentation

---

## Contributing Examples

Have a useful example? Please contribute!

1. Follow the example format above
2. Include complete, runnable code
3. Add comments explaining key steps
4. Test your example before submitting

---

**Document Version:** 1.0  
**Last Updated:** 2026-02-16  
**Maintained By:** Knowledge Graphs Team
