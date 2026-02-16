# Knowledge Graphs Extraction API Documentation

**Version:** 0.1.0  
**Last Updated:** 2026-02-16  
**Status:** Production Ready

## Overview

The `extraction/` package provides a modular, maintainable structure for extracting knowledge graphs from unstructured text. It includes classes for entities, relationships, graphs, and extraction logic with optional validation.

## Package Structure

```
ipfs_datasets_py.knowledge_graphs.extraction/
├── __init__.py           # Public API exports
├── types.py              # Shared types and constants
├── entities.py           # Entity class
├── relationships.py      # Relationship class  
├── graph.py              # KnowledgeGraph container
├── extractor.py          # KnowledgeGraphExtractor
└── validator.py          # KnowledgeGraphExtractorWithValidation
```

## Installation & Import

### Recommended (New)

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation
)
```

### Legacy (Still Supported)

```python
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation
)
```

Both import paths work identically with 100% backward compatibility.

---

## Entity Class

### Description

Represents an entity (node) in a knowledge graph with type, name, and properties.

### Constructor

```python
Entity(
    entity_id: str = None,           # Auto-generated if not provided
    entity_type: str = "entity",     # Type of entity
    name: str = "",                  # Entity name
    properties: Dict[str, Any] = {},  # Additional properties
    confidence: float = 1.0,          # Confidence score (0.0-1.0)
    source_text: str = None           # Source text snippet
)
```

### Methods

#### `to_dict() -> Dict[str, Any]`

Convert entity to dictionary representation.

**Returns:** Dictionary with entity attributes

**Example:**
```python
entity = Entity(entity_type="person", name="Alice")
entity_dict = entity.to_dict()
# {
#     "entity_id": "uuid...",
#     "entity_type": "person",
#     "name": "Alice",
#     "properties": {},
#     "confidence": 1.0
# }
```

#### `from_dict(data: Dict[str, Any]) -> Entity` (classmethod)

Create entity from dictionary representation.

**Parameters:**
- `data` (Dict): Dictionary with entity attributes

**Returns:** Entity instance

**Example:**
```python
data = {
    "entity_id": "e1",
    "entity_type": "organization",
    "name": "Microsoft",
    "properties": {"founded": "1975"},
    "confidence": 0.9
}
entity = Entity.from_dict(data)
```

### Usage Examples

```python
# Create entity with minimal attributes
person = Entity(entity_type="person", name="John Doe")

# Create entity with all attributes
company = Entity(
    entity_id="org1",
    entity_type="organization",
    name="Apple Inc.",
    properties={"founded": "1976", "location": "Cupertino"},
    confidence=0.95,
    source_text="Apple Inc. was founded in 1976"
)

# Serialize and deserialize
entity_dict = company.to_dict()
restored = Entity.from_dict(entity_dict)
```

---

## Relationship Class

### Description

Represents a relationship (edge) between two entities in a knowledge graph.

### Constructor

```python
Relationship(
    source_entity: Entity,                    # Source entity
    target_entity: Entity,                    # Target entity
    relationship_type: str,                   # Type of relationship
    properties: Dict[str, Any] = {},          # Additional properties
    relationship_id: str = None,              # Auto-generated if not provided
    confidence: float = 1.0,                  # Confidence score (0.0-1.0)
    source_text: str = None,                  # Source text snippet
    bidirectional: bool = False               # Is relationship bidirectional
)
```

### Methods

#### `to_dict() -> Dict[str, Any]`

Convert relationship to dictionary representation.

**Returns:** Dictionary with relationship attributes

#### `from_dict(data: Dict[str, Any]) -> Relationship` (classmethod)

Create relationship from dictionary representation.

**Parameters:**
- `data` (Dict): Dictionary with relationship attributes

**Returns:** Relationship instance

### Usage Examples

```python
# Create entities
person = Entity(entity_type="person", name="Steve Jobs")
company = Entity(entity_type="organization", name="Apple Inc.")

# Create relationship
founded = Relationship(
    source_entity=person,
    target_entity=company,
    relationship_type="FOUNDED",
    properties={"year": "1976"},
    confidence=0.9
)

# Serialize
rel_dict = founded.to_dict()
```

---

## KnowledgeGraph Class

### Description

Container for entities and relationships with efficient indexing and querying.

### Constructor

```python
KnowledgeGraph(name: str = "knowledge_graph")
```

### Properties

- `entities` (Dict[str, Entity]): Dictionary of entities indexed by ID
- `relationships` (Dict[str, Relationship]): Dictionary of relationships indexed by ID
- `name` (str): Name of the knowledge graph

### Methods

#### `add_entity(entity: Entity) -> Entity`

Add entity to the graph.

**Parameters:**
- `entity` (Entity): Entity to add

**Returns:** The added entity

**Example:**
```python
kg = KnowledgeGraph()
entity = Entity(name="Alice", entity_type="person")
kg.add_entity(entity)
```

#### `add_relationship(relationship: Relationship) -> Relationship`

Add relationship to the graph.

**Parameters:**
- `relationship` (Relationship): Relationship to add

**Returns:** The added relationship

#### `get_entity_by_id(entity_id: str) -> Optional[Entity]`

Retrieve entity by ID.

**Parameters:**
- `entity_id` (str): Entity ID

**Returns:** Entity instance or None

#### `get_entities_by_type(entity_type: str) -> List[Entity]`

Retrieve all entities of a given type.

**Parameters:**
- `entity_type` (str): Type of entities to retrieve

**Returns:** List of entities

#### `get_entities_by_name(name: str) -> List[Entity]`

Retrieve entities by name.

**Parameters:**
- `name` (str): Entity name to search for

**Returns:** List of matching entities

#### `get_relationships_by_entity(entity: Entity) -> List[Relationship]`

Get all relationships involving an entity.

**Parameters:**
- `entity` (Entity): Entity to search for

**Returns:** List of relationships

#### `find_path(source_id: str, target_id: str, max_depth: int = 5) -> Optional[List[str]]`

Find path between two entities using DFS.

**Parameters:**
- `source_id` (str): Source entity ID
- `target_id` (str): Target entity ID
- `max_depth` (int): Maximum search depth (default: 5)

**Returns:** List of entity IDs forming the path, or None

#### `merge(other: 'KnowledgeGraph')`

Merge another graph into this one.

**Parameters:**
- `other` (KnowledgeGraph): Graph to merge

#### `to_dict() -> Dict[str, Any]`

Convert graph to dictionary representation.

**Returns:** Dictionary with entities and relationships

#### `from_dict(data: Dict[str, Any]) -> 'KnowledgeGraph'` (classmethod)

Create graph from dictionary.

**Parameters:**
- `data` (Dict): Dictionary representation

**Returns:** KnowledgeGraph instance

#### `to_json() -> str`

Convert graph to JSON string.

**Returns:** JSON string representation

#### `from_json(json_str: str) -> 'KnowledgeGraph'` (classmethod)

Create graph from JSON string.

**Parameters:**
- `json_str` (str): JSON string

**Returns:** KnowledgeGraph instance

#### `export_to_rdf() -> str`

Export graph to RDF format.

**Returns:** RDF representation as string

### Usage Examples

```python
# Create graph
kg = KnowledgeGraph(name="company_graph")

# Add entities
person = Entity(name="Steve Jobs", entity_type="person")
company = Entity(name="Apple Inc.", entity_type="organization")
kg.add_entity(person)
kg.add_entity(company)

# Add relationship
rel = Relationship(
    source_entity=person,
    target_entity=company,
    relationship_type="FOUNDED"
)
kg.add_relationship(rel)

# Query
persons = kg.get_entities_by_type("person")
rels = kg.get_relationships_by_entity(person)

# Find path
path = kg.find_path(person.entity_id, company.entity_id)

# Serialize
kg_dict = kg.to_dict()
json_str = kg.to_json()
rdf_str = kg.export_to_rdf()

# Deserialize
restored = KnowledgeGraph.from_dict(kg_dict)
from_json = KnowledgeGraph.from_json(json_str)

# Merge graphs
other_kg = KnowledgeGraph()
# ... add entities/relationships ...
kg.merge(other_kg)
```

---

## KnowledgeGraphExtractor Class

### Description

Extracts knowledge graphs from text using rule-based and model-based approaches.

### Constructor

```python
KnowledgeGraphExtractor(
    use_spacy: bool = False,                            # Use spaCy for NER
    use_transformers: bool = False,                     # Use Transformers for NER
    relation_patterns: Optional[List[Dict]] = None,     # Custom patterns
    min_confidence: float = 0.5,                        # Min confidence threshold
    use_tracer: bool = True                             # Enable tracing
)
```

### Methods

#### `extract_entities(text: str) -> List[Entity]`

Extract entities from text.

**Parameters:**
- `text` (str): Input text

**Returns:** List of extracted entities

#### `extract_relationships(text: str, entities: List[Entity]) -> List[Relationship]`

Extract relationships from text given entities.

**Parameters:**
- `text` (str): Input text
- `entities` (List[Entity]): Previously extracted entities

**Returns:** List of extracted relationships

#### `extract_knowledge_graph(text: str, extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> KnowledgeGraph`

Extract complete knowledge graph from text.

**Parameters:**
- `text` (str): Input text
- `extraction_temperature` (float): Controls detail level (0.0-1.0)
  - Low (0.1-0.3): Major concepts only
  - Medium (0.4-0.7): Balanced extraction
  - High (0.8-1.0): Detailed extraction
- `structure_temperature` (float): Controls structural complexity (0.0-1.0)
  - Low (0.1-0.3): Flat structure
  - Medium (0.4-0.7): Balanced hierarchy
  - High (0.8-1.0): Rich hierarchies

**Returns:** KnowledgeGraph instance

#### `extract_enhanced_knowledge_graph(text: str, use_chunking: bool = True, extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> KnowledgeGraph`

Extract with enhanced processing (chunking for large texts).

**Parameters:**
- `text` (str): Input text
- `use_chunking` (bool): Process in chunks (default: True)
- `extraction_temperature` (float): Detail level
- `structure_temperature` (float): Structural complexity

**Returns:** KnowledgeGraph instance

#### `extract_from_documents(documents: List[Dict[str, str]], text_key: str = "text", extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> KnowledgeGraph`

Extract from multiple documents.

**Parameters:**
- `documents` (List[Dict]): List of document dictionaries
- `text_key` (str): Key for text field (default: "text")
- `extraction_temperature` (float): Detail level
- `structure_temperature` (float): Structural complexity

**Returns:** Merged KnowledgeGraph

#### `extract_from_wikipedia(page_title: str, extraction_temperature: float = 0.7, structure_temperature: float = 0.5) -> KnowledgeGraph`

Extract from Wikipedia page.

**Parameters:**
- `page_title` (str): Wikipedia page title
- `extraction_temperature` (float): Detail level
- `structure_temperature` (float): Structural complexity

**Returns:** KnowledgeGraph instance

**Raises:**
- `ValueError`: If page not found
- `RuntimeError`: If extraction fails

#### `validate_against_wikidata(kg: KnowledgeGraph, entity_name: str) -> Dict[str, Any]`

Validate graph against Wikidata.

**Parameters:**
- `kg` (KnowledgeGraph): Graph to validate
- `entity_name` (str): Main entity name

**Returns:** Validation results dictionary

#### `enrich_with_types(kg: KnowledgeGraph) -> KnowledgeGraph` (staticmethod)

Infer entity types based on relationships.

**Parameters:**
- `kg` (KnowledgeGraph): Graph to enrich

**Returns:** Enriched KnowledgeGraph

### Usage Examples

```python
# Create extractor
extractor = KnowledgeGraphExtractor()

# Extract from simple text
text = "Steve Jobs founded Apple Inc. in 1976."
kg = extractor.extract_knowledge_graph(text)

# Extract with temperature control
kg_detailed = extractor.extract_knowledge_graph(
    text,
    extraction_temperature=0.9,  # Detailed
    structure_temperature=0.8     # Rich structure
)

# Extract from Wikipedia
kg_wiki = extractor.extract_from_wikipedia("Artificial Intelligence")

# Extract from multiple documents
documents = [
    {"text": "Document 1 text...", "title": "Doc 1"},
    {"text": "Document 2 text...", "title": "Doc 2"}
]
kg_multi = extractor.extract_from_documents(documents)

# Enrich types
kg_enriched = KnowledgeGraphExtractor.enrich_with_types(kg)

# Validate
validation = extractor.validate_against_wikidata(kg_wiki, "Artificial Intelligence")
coverage = validation.get("coverage", 0.0)
```

---

## KnowledgeGraphExtractorWithValidation Class

### Description

Enhanced extractor with integrated SPARQL validation against Wikidata.

### Constructor

```python
KnowledgeGraphExtractorWithValidation(
    use_spacy: bool = False,
    use_transformers: bool = False,
    relation_patterns: Optional[List[Dict]] = None,
    min_confidence: float = 0.5,
    use_tracer: bool = True,
    sparql_endpoint_url: str = "https://query.wikidata.org/sparql",
    validate_during_extraction: bool = True,
    auto_correct_suggestions: bool = False,
    cache_validation_results: bool = True
)
```

### Methods

#### `extract_knowledge_graph(text: str, extraction_temperature: float = 0.7, structure_temperature: float = 0.5, validation_depth: int = 1) -> Dict[str, Any]`

Extract and validate knowledge graph.

**Parameters:**
- `text` (str): Input text
- `extraction_temperature` (float): Detail level
- `structure_temperature` (float): Structural complexity
- `validation_depth` (int): Validation depth (1=entities, 2=relationships)

**Returns:** Dictionary with:
  - `knowledge_graph`: Extracted graph
  - `validation_results`: Validation data
  - `validation_metrics`: Coverage metrics
  - `corrections`: Suggested corrections (if enabled)

#### `extract_from_wikipedia(page_title: str, extraction_temperature: float = 0.7, structure_temperature: float = 0.5, validation_depth: int = 2, focus_validation_on_main_entity: bool = True) -> Dict[str, Any]`

Extract and validate from Wikipedia.

**Parameters:**
- `page_title` (str): Wikipedia page title
- `extraction_temperature` (float): Detail level
- `structure_temperature` (float): Structural complexity
- `validation_depth` (int): Validation depth
- `focus_validation_on_main_entity` (bool): Focus validation on main entity

**Returns:** Dictionary with graph and validation results

#### `extract_from_documents(documents: List[Dict[str, str]], text_key: str = "text", extraction_temperature: float = 0.7, structure_temperature: float = 0.5, validation_depth: int = 1) -> Dict[str, Any]`

Extract and validate from multiple documents.

**Parameters:**
- `documents` (List[Dict]): Document list
- `text_key` (str): Text field key
- `extraction_temperature` (float): Detail level
- `structure_temperature` (float): Structural complexity
- `validation_depth` (int): Validation depth

**Returns:** Dictionary with graph and validation results

#### `apply_validation_corrections(kg: KnowledgeGraph, corrections: Dict[str, Any]) -> KnowledgeGraph`

Apply validation corrections to graph.

**Parameters:**
- `kg` (KnowledgeGraph): Graph to correct
- `corrections` (Dict): Correction suggestions

**Returns:** Corrected KnowledgeGraph

### Usage Examples

```python
# Create validation extractor
extractor = KnowledgeGraphExtractorWithValidation(
    validate_during_extraction=True,
    auto_correct_suggestions=True
)

# Extract with validation
text = "Albert Einstein developed the theory of relativity."
result = extractor.extract_knowledge_graph(
    text,
    validation_depth=2  # Validate entities and relationships
)

kg = result["knowledge_graph"]
validation = result.get("validation_results", {})
metrics = result.get("validation_metrics", {})
corrections = result.get("corrections", {})

print(f"Coverage: {metrics.get('overall_coverage', 0):.2%}")

# Apply corrections if needed
if corrections:
    corrected_kg = extractor.apply_validation_corrections(kg, corrections)

# Extract from Wikipedia with validation
result_wiki = extractor.extract_from_wikipedia(
    "Marie Curie",
    validation_depth=2,
    focus_validation_on_main_entity=True
)

kg_wiki = result_wiki["knowledge_graph"]
coverage = result_wiki["validation_metrics"]["overall_coverage"]
```

---

## Advanced Topics

### Temperature Parameters

Temperature parameters control the extraction process:

**Extraction Temperature** (0.0-1.0):
- **0.1-0.3 (Conservative)**: Extract only major concepts with strong evidence
- **0.4-0.7 (Balanced)**: Standard extraction with good precision/recall balance
- **0.8-1.0 (Aggressive)**: Extract detailed concepts, properties, weak relationships

**Structure Temperature** (0.0-1.0):
- **0.1-0.3 (Flat)**: Simple structures, few relationship types
- **0.4-0.7 (Hierarchical)**: Balanced multi-level structures
- **0.8-1.0 (Complex)**: Rich hierarchies, diverse relationships

### Custom Relation Patterns

Define custom patterns for relationship extraction:

```python
custom_patterns = [
    {
        "name": "employs",
        "pattern": r"(\w+(?:\s+\w+)*)\s+employs\s+(\w+(?:\s+\w+)*)",
        "source_type": "organization",
        "target_type": "person",
        "confidence": 0.85
    }
]

extractor = KnowledgeGraphExtractor(relation_patterns=custom_patterns)
```

### Validation and Quality

```python
# Basic validation
extractor = KnowledgeGraphExtractor()
kg = extractor.extract_knowledge_graph(text)
validation = extractor.validate_against_wikidata(kg, "Main Entity")

coverage = validation.get("coverage", 0.0)
missing = validation.get("missing_relationships", [])
additional = validation.get("additional_relationships", [])

# Advanced validation
extractor_val = KnowledgeGraphExtractorWithValidation(
    validate_during_extraction=True,
    auto_correct_suggestions=True
)

result = extractor_val.extract_knowledge_graph(text, validation_depth=2)
if result.get("corrections"):
    kg_corrected = extractor_val.apply_validation_corrections(
        result["knowledge_graph"],
        result["corrections"]
    )
```

---

## Migration Guide

### From Old Imports

```python
# Old (still works)
from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
    Entity, Relationship, KnowledgeGraph,
    KnowledgeGraphExtractor
)

# New (recommended)
from ipfs_datasets_py.knowledge_graphs.extraction import (
    Entity, Relationship, KnowledgeGraph,
    KnowledgeGraphExtractor
)
```

### No Code Changes Required

All functionality remains identical. Simply update imports when convenient.

---

## Performance Considerations

### Large Texts

For texts > 2000 characters, use enhanced extraction with chunking:

```python
extractor = KnowledgeGraphExtractor()
kg = extractor.extract_enhanced_knowledge_graph(
    large_text,
    use_chunking=True  # Processes in 1000-char chunks with overlap
)
```

### Multiple Documents

When processing multiple documents, extract once and merge:

```python
documents = [{"text": doc1}, {"text": doc2}, {"text": doc3}]
kg = extractor.extract_from_documents(documents)
```

### Validation Performance

SPARQL validation queries Wikidata - consider caching:

```python
extractor = KnowledgeGraphExtractorWithValidation(
    cache_validation_results=True  # Cache validation results
)
```

---

## Error Handling

```python
from ipfs_datasets_py.knowledge_graphs.extraction import (
    KnowledgeGraphExtractor
)

extractor = KnowledgeGraphExtractor()

try:
    kg = extractor.extract_from_wikipedia("Nonexistent Page")
except ValueError as e:
    print(f"Page not found: {e}")
except RuntimeError as e:
    print(f"Extraction failed: {e}")
```

---

## Best Practices

1. **Use Type Hints**: All classes support full type hints
2. **Validate Important Data**: Use validation extractor for critical knowledge
3. **Tune Temperatures**: Adjust based on your precision/recall requirements
4. **Cache Results**: Enable caching for repeated validations
5. **Handle Errors**: Wrap Wikipedia extraction in try/except blocks
6. **Use Chunking**: Enable for texts > 2000 characters
7. **Enrich Types**: Call `enrich_with_types()` after extraction

---

## Testing

Comprehensive test suite available in `tests/unit/knowledge_graphs/test_extraction.py`:

```bash
pytest tests/unit/knowledge_graphs/test_extraction.py
```

---

## Support & Contributing

- **Documentation**: `docs/KNOWLEDGE_GRAPHS_EXTRACTION_API.md` (this file)
- **Source Code**: `ipfs_datasets_py/knowledge_graphs/extraction/`
- **Tests**: `tests/unit/knowledge_graphs/test_extraction.py`
- **Issues**: Report via GitHub issues

---

## Changelog

### Version 0.1.0 (2026-02-16)
- Initial modular extraction package
- Extracted Entity, Relationship, KnowledgeGraph classes
- Extracted KnowledgeGraphExtractor and KnowledgeGraphExtractorWithValidation
- 100% backward compatibility maintained
- Comprehensive test suite (855 lines)
- Full API documentation

---

**End of API Documentation**
