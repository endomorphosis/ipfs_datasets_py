# JSON-LD Support

**Version:** 2.0.0  
**Package:** `ipfs_datasets_py.knowledge_graphs.jsonld`

---

## Overview

The JSON-LD module provides support for JSON-LD (JSON for Linking Data) format, enabling knowledge graphs to be serialized and deserialized in the W3C standard Linked Data format. This allows interoperability with the Semantic Web ecosystem.

**Key Features:**
- JSON-LD serialization and deserialization
- @context management
- RDF triple generation
- Schema.org vocabulary support
- Custom vocabulary support
- Validation against JSON-LD specifications

---

## Core Components

### JSONLDTranslator (`translator.py`)

Main translator between knowledge graphs and JSON-LD:

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import JSONLDTranslator

# Initialize translator
translator = JSONLDTranslator()

# Convert knowledge graph to JSON-LD
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()
kg = extractor.extract_knowledge_graph("Alice Smith works at Google.")

# Serialize to JSON-LD
jsonld = translator.to_jsonld(kg, context="https://schema.org/")
print(json.dumps(jsonld, indent=2))

# Deserialize from JSON-LD
kg_restored = translator.from_jsonld(jsonld)
print(f"Restored {len(kg_restored.entities)} entities")
```

**Supported Features:**
- Automatic @context generation
- Custom vocabulary mapping
- Compact/expanded forms
- Named graph support
- Multiple serialization formats

### RDFSerializer (`rdf_serializer.py`)

Serializes knowledge graphs to RDF triples:

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import RDFSerializer

# Initialize serializer
serializer = RDFSerializer(format="turtle")

# Serialize to RDF Turtle format
rdf_turtle = serializer.serialize(kg)
print(rdf_turtle)

# Output example:
# @prefix schema: <https://schema.org/> .
# 
# <#alice> a schema:Person ;
#     schema:name "Alice Smith" ;
#     schema:worksFor <#google> .
# 
# <#google> a schema:Organization ;
#     schema:name "Google" .

# Also supports other formats
rdf_ntriples = serializer.serialize(kg, format="nt")  # N-Triples
rdf_rdfxml = serializer.serialize(kg, format="xml")   # RDF/XML
rdf_jsonld = serializer.serialize(kg, format="json-ld")  # JSON-LD
```

**Supported Formats:**
- Turtle (`.ttl`)
- N-Triples (`.nt`)
- RDF/XML (`.rdf`)
- JSON-LD (`.jsonld`)
- N-Quads (`.nq`)

### ContextManager (`context.py`)

Manages JSON-LD @context definitions:

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import ContextManager

# Initialize with Schema.org
context_mgr = ContextManager(default_vocabulary="https://schema.org/")

# Get context for entity types
context = context_mgr.get_context(["Person", "Organization"])
print(context)
# {
#   "@context": {
#     "@vocab": "https://schema.org/",
#     "Person": "https://schema.org/Person",
#     "Organization": "https://schema.org/Organization",
#     "name": "https://schema.org/name",
#     "worksFor": "https://schema.org/worksFor"
#   }
# }

# Add custom vocabulary
context_mgr.add_vocabulary(
    prefix="myapp",
    namespace="https://myapp.com/vocab/"
)

# Create custom context
custom_context = context_mgr.create_context({
    "Person": "myapp:Person",
    "specialty": "myapp:specialty"
})
```

**Context Features:**
- Multiple vocabulary support
- Prefix management
- Type coercion
- Language tags
- Default vocabulary

### ValidationEngine (`validation.py`)

Validates JSON-LD documents:

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import ValidationEngine

# Initialize validator
validator = ValidationEngine()

# Validate JSON-LD document
jsonld_doc = {
    "@context": "https://schema.org/",
    "@type": "Person",
    "name": "Alice Smith",
    "worksFor": {
        "@type": "Organization",
        "name": "Google"
    }
}

# Validate structure
is_valid = validator.validate(jsonld_doc)
print(f"Valid: {is_valid}")

# Get validation errors
errors = validator.get_errors(jsonld_doc)
for error in errors:
    print(f"Error: {error.message} at {error.path}")

# Validate against schema
is_valid = validator.validate_against_schema(
    jsonld_doc,
    schema_url="https://schema.org/Person"
)
```

**Validation Types:**
- Structural validation (JSON-LD spec)
- Schema validation (Schema.org, custom)
- Type consistency
- Required property checks

### JSONLDTypes (`types.py`)

Type definitions for JSON-LD structures:

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import (
    JSONLDDocument,
    JSONLDContext,
    JSONLDNode,
    JSONLDGraph
)

# JSON-LD document
doc = JSONLDDocument(
    context="https://schema.org/",
    graph=[
        JSONLDNode(
            id="alice",
            type="Person",
            properties={"name": "Alice Smith"}
        )
    ]
)
```

---

## Usage Examples

### Example 1: Basic Serialization

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import JSONLDTranslator
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

# Extract knowledge graph
extractor = KnowledgeGraphExtractor()
kg = extractor.extract_knowledge_graph("""
    Alice Smith is a software engineer at Google.
    She has 10 years of experience in machine learning.
""")

# Serialize to JSON-LD
translator = JSONLDTranslator()
jsonld = translator.to_jsonld(kg, context="https://schema.org/")

# Save to file
import json
with open("knowledge_graph.jsonld", "w") as f:
    json.dump(jsonld, f, indent=2)

# Output example:
# {
#   "@context": "https://schema.org/",
#   "@graph": [
#     {
#       "@id": "#alice",
#       "@type": "Person",
#       "name": "Alice Smith",
#       "jobTitle": "software engineer",
#       "worksFor": {
#         "@id": "#google",
#         "@type": "Organization",
#         "name": "Google"
#       }
#     }
#   ]
# }
```

### Example 2: Custom Vocabulary

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import (
    JSONLDTranslator,
    ContextManager
)

# Define custom vocabulary
context_mgr = ContextManager()
context_mgr.add_vocabulary(
    prefix="biotech",
    namespace="https://biotech.example.com/vocab/"
)

# Create custom context
custom_context = {
    "@context": {
        "@vocab": "https://biotech.example.com/vocab/",
        "Protein": "biotech:Protein",
        "interactsWith": "biotech:interactsWith",
        "sequence": "biotech:sequence"
    }
}

# Serialize with custom context
translator = JSONLDTranslator(context_manager=context_mgr)
jsonld = translator.to_jsonld(kg, context=custom_context)
```

### Example 3: RDF Triple Export

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import RDFSerializer

# Initialize serializer
serializer = RDFSerializer()

# Export to Turtle format
turtle = serializer.serialize(kg, format="turtle")
print("Turtle format:")
print(turtle)

# Export to N-Triples
ntriples = serializer.serialize(kg, format="nt")
print("\nN-Triples format:")
print(ntriples)

# Export to RDF/XML
rdfxml = serializer.serialize(kg, format="xml")
with open("graph.rdf", "w") as f:
    f.write(rdfxml)
```

### Example 4: Deserialization and Import

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import JSONLDTranslator

# Load JSON-LD from file
with open("knowledge_graph.jsonld") as f:
    jsonld = json.load(f)

# Deserialize to knowledge graph
translator = JSONLDTranslator()
kg = translator.from_jsonld(jsonld)

# Use the imported graph
print(f"Loaded {len(kg.entities)} entities")
print(f"Loaded {len(kg.relationships)} relationships")

# Query the graph
from ipfs_datasets_py.knowledge_graphs.query import UnifiedQueryEngine

engine = UnifiedQueryEngine()
result = engine.query_graph(kg, "MATCH (n:Person) RETURN n")
```

### Example 5: Validation

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import (
    ValidationEngine,
    JSONLDTranslator
)

# Create JSON-LD document
translator = JSONLDTranslator()
jsonld = translator.to_jsonld(kg)

# Validate
validator = ValidationEngine()
is_valid = validator.validate(jsonld)

if not is_valid:
    errors = validator.get_errors(jsonld)
    print("Validation errors:")
    for error in errors:
        print(f"  - {error.message}")
        print(f"    Path: {error.path}")
        print(f"    Code: {error.code}")
else:
    print("Document is valid JSON-LD")

# Validate against Schema.org
is_schema_valid = validator.validate_against_schema(
    jsonld,
    schema_url="https://schema.org/"
)
print(f"Schema.org valid: {is_schema_valid}")
```

---

## Schema.org Integration

### Using Schema.org Vocabulary

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import JSONLDTranslator

# Automatically maps to Schema.org types
translator = JSONLDTranslator(vocabulary="schema.org")

# Entity types mapped to Schema.org
entity_mapping = {
    "Person": "https://schema.org/Person",
    "Organization": "https://schema.org/Organization",
    "Place": "https://schema.org/Place",
    "Event": "https://schema.org/Event",
    "Product": "https://schema.org/Product"
}

# Relationship types mapped to Schema.org properties
relationship_mapping = {
    "WORKS_AT": "worksFor",
    "LOCATED_IN": "location",
    "FOUNDED_BY": "founder",
    "ATTENDED": "attendee"
}

# Serialize with automatic mapping
jsonld = translator.to_jsonld(kg)
# All types/properties use Schema.org vocabulary
```

### Common Schema.org Patterns

```python
# Person with detailed properties
person_jsonld = {
    "@context": "https://schema.org/",
    "@type": "Person",
    "name": "Alice Smith",
    "jobTitle": "Software Engineer",
    "email": "alice@example.com",
    "worksFor": {
        "@type": "Organization",
        "name": "Google",
        "url": "https://www.google.com"
    },
    "alumniOf": {
        "@type": "EducationalOrganization",
        "name": "MIT"
    }
}

# Event with location and attendees
event_jsonld = {
    "@context": "https://schema.org/",
    "@type": "Event",
    "name": "AI Conference 2024",
    "startDate": "2024-06-01",
    "endDate": "2024-06-03",
    "location": {
        "@type": "Place",
        "name": "Convention Center",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "San Francisco",
            "addressRegion": "CA"
        }
    },
    "attendee": [
        {"@type": "Person", "name": "Alice Smith"},
        {"@type": "Person", "name": "Bob Jones"}
    ]
}
```

---

## Advanced Features

### Compact vs Expanded Form

```python
from ipfs_datasets_py.knowledge_graphs.jsonld import JSONLDTranslator

translator = JSONLDTranslator()

# Compact form (with @context)
compact = translator.to_jsonld(kg, form="compact")
# {
#   "@context": "https://schema.org/",
#   "@type": "Person",
#   "name": "Alice"
# }

# Expanded form (fully qualified URIs)
expanded = translator.to_jsonld(kg, form="expanded")
# [{
#   "@type": ["https://schema.org/Person"],
#   "https://schema.org/name": [{"@value": "Alice"}]
# }]

# Flattened form (all nodes at root level)
flattened = translator.to_jsonld(kg, form="flattened")
```

### Named Graphs

```python
# Create named graph
jsonld = {
    "@context": "https://schema.org/",
    "@graph": [
        {
            "@id": "https://example.com/graphs/people",
            "@graph": [
                {"@type": "Person", "name": "Alice"},
                {"@type": "Person", "name": "Bob"}
            ]
        },
        {
            "@id": "https://example.com/graphs/companies",
            "@graph": [
                {"@type": "Organization", "name": "Google"},
                {"@type": "Organization", "name": "Apple"}
            ]
        }
    ]
}
```

### Language Tags

```python
# Multilingual content
jsonld = {
    "@context": "https://schema.org/",
    "@type": "Person",
    "name": {
        "en": "Alice Smith",
        "es": "Alicia Smith",
        "fr": "Alice Smith"
    },
    "description": {
        "@value": "Software Engineer",
        "@language": "en"
    }
}
```

---

## Performance Considerations

### Large Graphs

```python
# Stream serialization for large graphs
translator = JSONLDTranslator(streaming=True)

# Process in chunks
for chunk in translator.to_jsonld_streaming(kg, chunk_size=1000):
    # Process each chunk
    output_file.write(json.dumps(chunk))
```

### Caching Contexts

```python
# Cache frequently used contexts
context_mgr = ContextManager(cache_size=100)
context_mgr.preload_contexts([
    "https://schema.org/",
    "https://www.w3.org/ns/prov#"
])
```

---

## Testing

```bash
# Run JSON-LD tests
pytest tests/knowledge_graphs/test_jsonld/ -v

# Test translator
pytest tests/knowledge_graphs/test_jsonld/test_translator.py -v

# Test RDF serialization
pytest tests/knowledge_graphs/test_jsonld/test_rdf_serializer.py -v

# Test validation
pytest tests/knowledge_graphs/test_jsonld/test_validation.py -v

# Test context management
pytest tests/knowledge_graphs/test_jsonld/test_context.py -v
```

---

## See Also

- **[Extraction Module](../extraction/README.md)** - Knowledge graph extraction
- **[Storage Module](../storage/README.md)** - IPLD storage (similar format)
- **[Migration Module](../migration/README.md)** - Format conversion
- **[USER_GUIDE.md](../../../../docs/knowledge_graphs/USER_GUIDE.md)** - Usage guide
- **[API_REFERENCE.md](../../../../docs/knowledge_graphs/API_REFERENCE.md)** - Complete API
- **[W3C JSON-LD Spec](https://www.w3.org/TR/json-ld11/)** - Official specification
- **[Schema.org](https://schema.org/)** - Vocabulary reference

---

## Status

**Test Coverage:** ~70%  
**Production Ready:** Yes  
**W3C Compliance:** JSON-LD 1.1

**Supported Standards:**
- JSON-LD 1.1 ✅
- RDF 1.1 ✅
- Schema.org vocabulary ✅
- Custom vocabularies ✅

**Roadmap:**
- v2.0: Core JSON-LD support ✅
- v2.1: Full RDF serialization ✅
- v2.2: SHACL validation (Q2 2026)
- v2.3: OWL ontology support (Q3 2026)
