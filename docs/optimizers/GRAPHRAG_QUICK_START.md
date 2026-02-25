# GraphRAG Optimizer Quick Start Guide

This guide provides a quick introduction to using the GraphRAG optimizer for knowledge graph ontology generation and optimization.

For extraction tuning details, see
[`EXTRACTION_CONFIG_GUIDE.md`](./EXTRACTION_CONFIG_GUIDE.md).

## What is GraphRAG?

The GraphRAG optimizer automatically generates and refines knowledge graph ontologies from arbitrary data sources. It uses:
- **Entity extraction** to identify key concepts
- **Relationship inference** to discover connections
- **Iterative refinement** via critic feedback and LLM-based agents
- **Multi-modal support** for text, PDFs, JSON, CSV, and more

## Installation

GraphRAG is part of the ipfs_datasets_py optimizers package:

```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyCritic,
    OntologyOptimizer,
    OntologyHarness,
)
```

## Basic Usage

### 1. Generate an Ontology from Text

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator, OntologyGenerationContext

# Create generator with AI model backend
generator = OntologyGenerator(
    ipfs_accelerate_config={
        'model': 'bert-base-uncased',
        'task': 'ner'
    }
)

# Define input data
text_data = """
The Python programming language was created by Guido van Rossum.
Python emphasizes code readability and uses significant whitespace.
"""

# Create context
context = OntologyGenerationContext(
    data=text_data,
    domain='software_engineering',
    extraction_strategy='ai',
)

# Generate ontology
ontology = generator.generate(context)

print(f"Extracted {len(ontology['entities'])} entities")
print(f"Inferred {len(ontology['relationships'])} relationships")
```

### 2. Evaluate Ontology Quality

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyCritic

# Create critic
critic = OntologyCritic(llm_backend=your_llm_backend)

# Evaluate ontology
score = critic.evaluate_ontology(ontology, context)

print(f"Overall score: {score.overall_score:.2f}")
print(f"Completeness: {score.dimensions['completeness']:.2f}")
print(f"Consistency: {score.dimensions['consistency']:.2f}")

# Get recommendations
for rec in score.recommendations[:3]:
    print(f"- {rec}")
```

### 3. Iterative Refinement with Harness

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyHarness

# Create harness (integrates generator + critic + optimizer)
harness = OntologyHarness(
    generator_config={'model': 'bert-base-uncased'},
    critic_backend=your_llm_backend,
)

# Run optimization loop
final_ontology = harness.optimize(
    data=text_data,
    domain='software_engineering',
    iterations=5,
    score_threshold=0.85,
)

print(f"Final ontology score: {final_ontology['score']}")
```

## Advanced Features

### Configure Extraction Parameters

```python
from ipfs_datasets_py.optimizers.graphrag import ExtractionConfig

config = ExtractionConfig(
    extraction_strategy='hybrid',  # 'rule_based', 'ai', or 'hybrid'
    min_confidence=0.7,
    max_entities=100,
    entity_types=['person', 'organization', 'technology'],
    relationship_types=['created_by', 'uses', 'related_to'],
)

ontology = generator.generate(context, config=config)
```

### Use Refinement Agent for Feedback

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyRefinementAgent

# Create refinement agent
agent = OntologyRefinementAgent(
    llm_backend=your_llm_backend,
    strict_validation=True,  # Enable strict schema validation
)

# Get structured feedback
feedback = agent.propose_feedback(ontology, score, context)

# Apply feedback to refine ontology
refined_ontology = generator.generate_with_feedback(
    context,
    feedback=feedback
)
```

### Stream Large Documents

```python
from ipfs_datasets_py.optimizers.graphrag import StreamingExtractor

extractor = StreamingExtractor(
    chunk_size=1024,
    overlap=128,
)

# Process document in chunks
for chunk_ontology in extractor.stream_extract(large_document, context):
    # Merge chunk ontologies incrementally
    merged_ontology = extractor.merge_ontologies([merged_ontology, chunk_ontology])
```

## Configuration Reference

### Key OntologyGenerator Parameters

- **ipfs_accelerate_config**: AI model configuration for entity extraction
- **extraction_strategy**: 'rule_based', 'ai', or 'hybrid'
- **min_confidence**: Minimum confidence threshold (0.0-1.0)
- **max_entities**: Maximum entities to extract (default: unlimited)

### Key OntologyCritic Dimensions

Each dimension is scored 0.0-1.0:
- **completeness** (22%): Coverage of key concepts
- **consistency** (22%): Internal logical consistency  
- **clarity** (14%): Clear definitions
- **granularity** (14%): Appropriate detail level
- **relationship_coherence** (13%): Quality of relationships
- **domain_alignment** (15%): Domain-specific accuracy

### Feedback Schema (OntologyRefinementAgent)

Structured feedback dict with these keys:
- `entities_to_remove`: List of entity IDs to delete
- `entities_to_merge`: List of [id1, id2] pairs to merge
- `relationships_to_remove`: List of relationship IDs to delete  
- `relationships_to_add`: List of relationship dicts to add
- `type_corrections`: Dict mapping entity_id -> new_type
- `confidence_floor`: Minimum confidence threshold (float)

## CLI Usage

Generate ontologies from the command line:

```bash
# Using unified optimizer CLI
python -m ipfs_datasets_py.optimizers.cli graphrag generate \
    --input data.txt \
    --domain medical \
    --output ontology.json

# Using direct GraphRAG CLI
python -m ipfs_datasets_py.optimizers.graphrag.cli \
    --input research_paper.pdf \
    --strategy hybrid \
    --min-confidence 0.8
```

## Examples by Data Type

### Text Input
```python
context = OntologyGenerationContext(
    data="Your text here...",
    domain='general',
)
```

### PDF Input
```python
from ipfs_datasets_py.processors import pdf

pdf_text = pdf.extract_text('document.pdf')
context = OntologyGenerationContext(
    data=pdf_text,
    domain='legal',
)
```

### JSON/Structured Data
```python
import json

data = json.load(open('data.json'))
context = OntologyGenerationContext(
    data=json.dumps(data),
    domain='database',
    extraction_strategy='rule_based',  # Works well with structured data
)
```

## Troubleshooting

### Low Extraction Quality
- Try switching from 'ai' to 'hybrid' extraction strategy
- Lower min_confidence threshold (e.g., 0.5 instead of 0.7)
- Add domain-specific entity_types to ExtractionConfig

### Slow Performance
- Use StreamingExtractor for large documents
- Reduce max_entities limit
- Use 'rule_based' strategy for structured data

### Feedback Schema Errors
- Enable strict_validation=True on OntologyRefinementAgent to see detailed errors
- Validate feedback dict with validate_feedback_schema() helper

## Next Steps

- **API Reference**: See [API_REFERENCE_GRAPHRAG.md](../../docs/API_REFERENCE_GRAPHRAG.md) for complete API docs
- **Configuration**: See [EXTRACTION_CONFIG_GUIDE.md](./EXTRACTION_CONFIG_GUIDE.md) for ExtractionConfig details
- **Architecture**: See [ONTOLOGY_PIPELINE_ARCHITECTURE_ASCII.md](./ONTOLOGY_PIPELINE_ARCHITECTURE_ASCII.md) for pipeline flow and component wiring
- **Selection Guide**: See [SELECTION_GUIDE.md](SELECTION_GUIDE.md) to choose between GraphRAG/Logic/Agentic optimizers
- **Examples**: Check `tests/unit/optimizers/graphrag/` for working test examples
