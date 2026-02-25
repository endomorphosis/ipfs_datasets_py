# ExtractionConfig Guide

This guide explains how to configure GraphRAG extraction with
`ipfs_datasets_py.optimizers.graphrag.ontology_generator.ExtractionConfig`.

## Quick Start

```python
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerationContext,
    ExtractionConfig,
    DataType,
    ExtractionStrategy,
)

context = OntologyGenerationContext(
    data_source="contract.txt",
    data_type=DataType.TEXT,
    domain="legal",
    extraction_strategy=ExtractionStrategy.RULE_BASED,
    config=ExtractionConfig(
        confidence_threshold=0.6,
        max_entities=250,
        max_relationships=400,
        sentence_window=2,
        min_entity_length=3,
    ),
)
```

## Field Reference

- `confidence_threshold`:
  - Minimum confidence to keep an entity/relationship.
  - Typical values: `0.5` (balanced), `0.7+` (stricter precision).
- `max_entities`:
  - Hard cap on extracted entities (`0` means unlimited).
  - Use a cap to prevent runaway extraction on very long inputs.
- `max_relationships`:
  - Hard cap on inferred relationships (`0` means unlimited).
- `window_size`:
  - Co-occurrence window for relationship inference.
  - Smaller windows reduce noisy links.
- `sentence_window`:
  - Maximum sentence distance for relationship inference.
  - `0` means same-sentence only.
- `include_properties`:
  - Toggle extraction of property predicates for downstream logic.
- `domain_vocab`:
  - Domain-specific vocabulary map for entity typing hints.
- `custom_rules`:
  - Extra regex rules as `(pattern, entity_type)` tuples.
- `llm_fallback_threshold`:
  - If rule-based confidence drops below this threshold and an LLM backend is configured,
    extraction can fall back to LLM.
  - `0.0` disables this fallback.
- `min_entity_length`:
  - Minimum character length for entity text.
  - Useful for filtering single-character noise.

## Preset Examples

- Fast baseline:
  - `confidence_threshold=0.5`, `sentence_window=0`, `max_entities=200`
- Higher precision:
  - `confidence_threshold=0.75`, `sentence_window=0`, `min_entity_length=3`
- Relationship-heavy discovery:
  - `confidence_threshold=0.5`, `sentence_window=2`, `max_relationships=1000`

## Tuning Workflow

1. Start from a conservative baseline (`confidence_threshold=0.6`).
2. Run on a representative corpus and inspect false positives/negatives.
3. Tighten threshold and `min_entity_length` for precision issues.
4. Increase `sentence_window` only when recall for cross-sentence relations is needed.
5. Add `domain_vocab` and `custom_rules` for recurring domain entities.

## Notes

- `OntologyGenerationContext(config=...)` accepts dicts and typed configs.
- For reproducibility, keep config snapshots in test fixtures or benchmark reports.
