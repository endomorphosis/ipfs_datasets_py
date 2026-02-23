# Optimizers Module - Quick Start Guide

This guide provides a rapid introduction to the optimizers module, focusing on the GraphRAG ontology generation pipeline.

## Overview

The optimizers module provides a complete end-to-end pipeline for generating and optimizing knowledge graph ontologies from arbitrary data sources. The architecture follows a standard flow:

```
Data Input → Extraction → Evaluation → Refinement → Validation → Output
```

## Key Components

### 1. OntologyGenerator
Extracts entities and relationships from raw data using configurable strategies.

**Usage:**
```python
from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator, OntologyGenerationContext

generator = OntologyGenerator()
context = OntologyGenerationContext(
    data_source="document.txt",
    data_type="text",
    domain="legal",
    extraction_strategy="rule_based",
)

extraction = generator.extract_entities("Your text here", context)
print(f"Found {len(extraction.entities)} entities")
print(f"Found {len(extraction.relationships)} relationships")
```

**Extraction Strategies:**
- `RULE_BASED`: Fast pattern-based extraction (default)
- `LLM_BASED`: AI-powered extraction (if configured)
- `HYBRID`: Combination of both

**Performance Characteristics:**
- Legal documents: ~840 μs
- Technical documents: ~1,169 μs
- Financial documents: ~1,820 μs

### 2. OntologyCritic
Evaluates the quality and completeness of generated ontologies.

**Usage:**
```python
from ipfs_datasets_py.optimizers.graphrag import OntologyCritic

critic = OntologyCritic()
ontology = {...}  # from extraction
score = critic.evaluate_ontology(ontology, context)

print(f"Overall score: {score.overall}")
print(f"Entity coverage: {score.entity_coverage}")
print(f"Relationship coverage: {score.relationship_coverage}")
```

### 3. OntologyMediator
Refines ontologies based on critic feedback.

**Usage:**
```python
from ipfs_datasets_py.optimizers.graphrag import OntologyMediator

mediator = OntologyMediator()
refined = mediator.refine_ontology(ontology, score, context)

# Multi-pass refinement
for i in range(3):
    refined = mediator.refine_ontology(refined, score, context)
    score = critic.evaluate_ontology(refined, context)
```

### 4. OntologyPipeline
Single-entry-point orchestrating the complete pipeline.

**Usage:**
```python
from ipfs_datasets_py.optimizers.graphrag import OntologyPipeline

pipeline = OntologyPipeline(
    domain="legal",
    enable_tracing=True,  # Enable OpenTelemetry tracing
)

result = pipeline.run(
    data="Document text...",
    context=context,
    refine=True,
    refine_mode="rule_based",
)

print(f"Final ontology: {result['ontology']}")
print(f"Final score: {result['score']}")
```

## Configuration

### ExtractionConfig
Fine-grained control over extraction behavior:

```python
from ipfs_datasets_py.optimizers.graphrag import ExtractionConfig

config = ExtractionConfig(
    confidence_threshold=0.7,    # Keep entities with 70%+ confidence
    max_entities=500,            # Cap at 500 entities
    max_relationships=1000,      # Cap at 1000 relationships
    window_size=3,               # 3-word context window for relationships
    min_entity_length=2,         # Minimum 2-character entities
    domain_vocab=["legal", "entity", "obligation"],  # Domain-specific terms
)
```

## Performance Insights

### Extraction Strategy Scaling
- **10 entities**: ~800 μs
- **25 entities**: ~3,700 μs (4.6x)
- **50 entities**: ~9,100 μs (11.3x)
- **100 entities**: ~23,500 μs (29.2x)

This O(n²) scaling is expected for relationship inference (comparing all entity pairs).

### Type Confidence Scoring Overhead
Different relationship types have different scoring complexity:
- Specific legal types (e.g., "obligates"): 925 μs
- Clear semantic types (e.g., "employs"): 249 μs
- Ambiguous types (e.g., "part_of"): 1,097 μs

Ambiguous types require additional pattern discrimination, increasing overhead.

### End-to-End Pipeline Performance
Single pass (extract + evaluate + refine):
- Small document (300 tokens): ~3-5ms
- Medium document (1k tokens): ~8-12ms
- Large document (3k tokens): ~20-30ms

## Observability & Monitoring

### OpenTelemetry Tracing
Enable distributed tracing for pipeline visibility:

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyPipeline

pipeline = OntologyPipeline(enable_tracing=True)
result = pipeline.run(data, context)

# Emits spans:
# - ontology_pipeline.extract (with entity_count, relationship_count)
# - ontology_pipeline.evaluate (with phase: initial/refine/post_refine/final)
# - ontology_pipeline.refine (with actions_applied, final_score)
# - ontology_pipeline.adapt (refinement adaptation)
# - ontology_pipeline.batch (batch processing)
```

### Profiling
Enable JSON profiling output for performance analysis:

```python
from ipfs_datasets_py.optimizers.common.profiling import ProfilingConfig, profile_method

# Global profiling configuration
ProfilingConfig.enable = True
ProfilingConfig.track_memory = True

# Use @profile_method decorator on functions
@profile_method(group="extraction")
def extract_entities(text, context):
    ...
```

### Structured Logging
All pipeline events emit standardized JSON logs with schema versioning:

```python
# Logs include:
{
    "event_type": "extraction_complete",
    "timestamp": "2026-02-23T10:15:30Z",
    "entity_count": 42,
    "relationship_count": 87,
    "confidence_avg": 0.78,
    "processing_time_ms": 125,
    "schema_version": 2,
}
```

## Testing & Benchmarking

### Run Benchmarks
Comprehensive performance benchmarks included:

```bash
# Relationship scaling benchmark
pytest ipfs_datasets_py/benchmarks/bench_infer_relationships_scaling.py -v

# Type confidence scoring benchmark
pytest ipfs_datasets_py/benchmarks/bench_relationship_type_confidence_scoring.py -v

# Extraction strategy performance
pytest ipfs_datasets_py/benchmarks/bench_extraction_strategy_performance.py -v

# End-to-end pipeline benchmark
pytest ipfs_datasets_py/benchmarks/bench_end_to_end_pipeline_performance.py -v
```

### Test Suite
Comprehensive unit and integration tests:

```bash
# All optimizers tests
pytest ipfs_datasets_py/tests/unit/optimizers/graphrag/ -v

# E2E pipeline tests
pytest ipfs_datasets_py/tests/unit/optimizers/graphrag/test_ontology_pipeline_e2e.py -v
```

## Common Patterns

### Full Optimization Loop
```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyCritic,
    OntologyMediator,
    OntologyGenerationContext,
)

# Setup
generator = OntologyGenerator()
critic = OntologyCritic()
mediator = OntologyMediator()

context = OntologyGenerationContext(
    data_source="doc.txt",
    data_type="text",
    domain="business",
)

# Extraction phase
extraction = generator.extract_entities(data, context)
ontology = {
    "entities": extraction.entities,
    "relationships": extraction.relationships,
}

# Evaluation phase
score = critic.evaluate_ontology(ontology, context)

# Refinement phase (multiple passes)
best_ontology = ontology
best_score = score

for iteration in range(3):
    refined = mediator.refine_ontology(best_ontology, best_score, context)
    refined_score = critic.evaluate_ontology(refined, context)
    
    if refined_score.overall > best_score.overall:
        best_ontology = refined
        best_score = refined_score

print(f"Final optimized ontology")
print(f"Score: {best_score}")
```

### Batch Processing
```python
pipeline = OntologyPipeline()

documents = [doc1, doc2, doc3, ...]
contexts = [ctx1, ctx2, ctx3, ...]

results = pipeline.run_batch(documents, contexts)
# Returns list of (ontology, score) tuples
```

## Architecture Diagram

```
┌─────────────────━──────────────────┐
│     Raw Data Input (text/PDF)      │
└─────────────────┬──────────────────┘
                  │
                  ▼
        ┌──────────────────┐
        │ OntologyGenerator│  (Extraction)
        │  - RULE_BASED    │
        │  - LLM_BASED     │
        │  - HYBRID        │
        └────────┬─────────┘
                 │
                 ▼ ({ entities, relationships })
        ┌──────────────────┐
        │ OntologyCritic   │  (Evaluation)
        │  - Coverage      │
        │  - Quality       │
        │  - Completeness  │
        └────────┬─────────┘
                 │
                 ▼ (quality_score)
        ┌──────────────────┐
        │ OntologyMediator │  (Refinement)
        │  - Merge records │
        │  - Apply feedback│
        │  - Optimize      │
        └────────┬─────────┘
                 │
                 ▼ (improved_ontology)
        ┌──────────────────┐
        │ Validation Layer │  (Optional)
        │  - Schema checks │
        │  - Consistency   │
        └────────┬─────────┘
                 │
                 ▼
        ┌──────────────────┐
        │  Output Ontology │  (JSON/RDF/etc)
        └──────────────────┘

Observability (side effects):
- OpenTelemetry spans → distributed tracing
- Structured JSON logs → event stream
- Profiling metrics → performance analysis
```

## Advanced Configuration

### Domain-Specific Tuning
```python
# Legal document optimization
legal_context = OntologyGenerationContext(
    data_source="contract.pdf",
    data_type="pdf",
    domain="legal",
    extraction_strategy="hybrid",  # Combine rule-based + LLM
)

# Financial document optimization
finance_context = OntologyGenerationContext(
    data_source="financial_report.pdf",
    data_type="pdf",
    domain="finance",
   extraction_strategy="rule_based",
)
```

### Custom Extraction Strategies
See [CONFIGURATION_GUIDE.md](../CONFIGURATION.md) for detailed configuration options and advanced tuning.

## Troubleshooting

### Low Entity Confidence
- Lower `confidence_threshold` in ExtractionConfig
- Try `HYBRID` or `LLM_BASED` extraction strategies
- Increase `window_size` for relationship inference

### Missing Relationships
- Increase `max_relationships` limit
- Enable `include_properties` in ExtractConfig
- Review domain-specific patterns for your domain

### Performance Issues
- Reduce `max_entities` to process smaller ontologies
- Use profiling to identify bottlenecks
- Consider batch processing for multiple documents

## References

- [CONFIGURATION_GUIDE.md](../CONFIGURATION.md) — Detailed ExtractionConfig options
- [ARCHITECTURE.md](../ARCHITECTURE.md) — System design and component interactions
- [benchmarks/](../../benchmarks/) — Performance benchmarks
- [tests/](../../tests/unit/optimizers/) — Test suite and examples

## Contributing

To extend the optimizers module:

1. Add new extraction strategies in `ontology_generator.py`
2. Enhance critic evaluations in `ontology_critic.py`
3. Add refinement strategies in `ontology_mediator.py`
4. Update benchmarks for performance changes
5. Add tests for new functionality

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for full guidelines.

---

**Last Updated:** 2026-02-23  
**Status:** Production Ready  
**Version:** 2.0.0
