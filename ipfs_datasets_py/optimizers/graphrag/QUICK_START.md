# GraphRAG Optimizer: Quick Start Guide

This guide shows how to generate, validate, and optimize ontologies using the GraphRAG optimizer in 5 minutes.

## Installation

```bash
# Assumes ipfs_datasets_py is installed
pip install ipfs_datasets_py[graphrag]
```

## Basic Usage: Generate an Ontology

```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyOptimizer,
)

# Create generator
generator = OntologyGenerator(use_rule_based=True)

# Extract ontology from text data
data = {
    "text": """
        Alice developed a web crawler that processes documents from Wikipedia.
        The crawler extracts entities like Person, Document, Tool and relationships like
        authorOf, uses, processesFormat, stores.
    """
}

ontology = generator.generate(data)

# Result: 
# {
#   "entities": [
#       {"id": "alice", "type": "Person", "name": "Alice"},
#       {"id": "web_crawler", "type": "Tool", "name": "web crawler"},
#       ...
#   ],
#   "relationships": [
#       {"source": "alice", "target": "web_crawler", "type": "authorOf"},
#       ...
#   ]
# }
```

## Validate Ontology Structure

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyValidator

validator = OntologyValidator()
is_valid, errors = validator.validate(ontology)

if not is_valid:
    print(f"Validation errors: {errors}")
else:
    print("Ontology structure is valid!")
```

## Analyze & Optimize

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyOptimizer

optimizer = OntologyOptimizer()

# Analyze a batch of ontologies
ontologies = [ontology]  # Can have multiple results
report = optimizer.analyze_batch(ontologies)

print(f"Average score: {report.average_score:.2f}")
print(f"Trend: {report.trend}")
print(f"Recommendations:")
for rec in report.recommendations:
    print(f"  - {rec}")

# Result:
# Average score: 0.72
# Trend: baseline
# Recommendations:
#   - Consider using hybrid extraction strategy
#   - Add domain-specific templates
```

## Iterative Optimization (SGD Loop)

```python
# Run multiple optimization cycles
for cycle in range(5):
    # Generate batch of different ontologies
    results = []
    for extraction_strategy in ['rule_based', 'hybrid']:
        gen = OntologyGenerator(use_rule_based=(extraction_strategy == 'rule_based'))
        ont = gen.generate(data)
        results.append(ont)
    
    # Analyze
    report = optimizer.analyze_batch(results)
    
    print(f"Cycle {cycle+1}: avg={report.average_score:.2f}, trend={report.trend}")
    
    # Check convergence
    if report.trend == 'stable' and report.average_score > 0.80:
        print(f"Converged after {cycle+1} cycles!")
        break
```

## Query Optimization

Once you have a stable ontology, optimize queries against it:

```python
from ipfs_datasets_py.optimizers.graphrag import UnifiedGraphRAGQueryOptimizer

optimizer = UnifiedGraphRAGQueryOptimizer(ontology)

query = "Who developed the crawler that processes Wikipedia?"

# Optimize query execution plan
plan = optimizer.optimize_query(query)

print(f"Execution plan generated with {len(plan.get('scenes', []))} scenes")
for scene in plan.get('scenes', []):
    print(f"  - Scene: {scene.get('description')}")
```

## Common Patterns

### Extract Only Specific Entity Types

```python
ontology = generator.generate(
    data,
    entity_types=['Person', 'Tool']  # Only extract these types
)
```

### Merge Multiple Ontologies

```python
ont1 = generator.generate(data1)
ont2 = generator.generate(data2)

merged = generator._merge_ontologies([ont1, ont2])
# Deduplicates by entity ID and merges properties
```

### Identify Success Patterns

```python
successful_ontologies = [ont1, ont2, ont3]  # High-performing examples
patterns = optimizer.identify_patterns(successful_ontologies)

print(f"Common entity types: {patterns['common_entity_types']}")
print(f"Avg entities per ontology: {patterns['avg_entity_count']:.1f}")
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **ImportError: No module 'numpy'** | OntologyGenerator has optional numpy dependency. Install with `pip install ipfs_datasets_py[graphrag]` or use rule-based extraction only. |
| **Empty ontology** | Text may not have extractable entities. Try longer text with clear named entities. |
| **Low validation scores** | Check for missing relationships, poorly formatted entity properties, or domain misalignment. |
| **Timeout on large data** | Use `OntologyOptimizer.analyze_batch_parallel()` for parallel processing. |

## Configuration

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator

# Customize extraction behavior
gen = OntologyGenerator(
    use_rule_based=True,      # Use deterministic regex extraction
    use_llm=False,            # Don't call external LLM (requires ipfs_accelerate_py)
    relationship_threshold=0.7,  # Confidence threshold for relationships
    max_relationships_per_entity=10
)
```

## Next Steps

- **Validation:** See [VALIDATION.md](VALIDATION.md) for detailed validation schemas
- **Advanced:** See [README.md](README.md) for full API documentation
- **Examples:** See [../examples/](../examples/) for multi-domain examples

---

**Last updated:** 2026-02-20  
**Test coverage:** 100+ deterministic tests in `tests/unit/optimizers/graphrag/`
