# Task Guide: Entity Extraction

This guide explains how to improve entity extraction quality in the GraphRAG pipeline. It focuses on practical tuning of `ExtractionConfig`, custom rules, and validation steps for reliable results.

## Quick Start

```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionConfig,
    DataType,
    ExtractionStrategy,
)

config = ExtractionConfig(
    confidence_threshold=0.6,
    max_entities=200,
    min_entity_length=2,
    allowed_entity_types=["Person", "Organization", "Location"],
)

generator = OntologyGenerator(config.to_dict())
context = OntologyGenerationContext(
    data_source="report.txt",
    data_type=DataType.TEXT,
    domain="general",
    extraction_strategy=ExtractionStrategy.HYBRID,
    config=config,
)

ontology = generator.generate_ontology(open("report.txt").read(), context)
print(len(ontology.get("entities", [])))
```

## Core Quality Levers

### 1) Confidence Thresholds
- `confidence_threshold`: Remove low-confidence entities.
- `max_confidence`: Clamp entity confidence to avoid outliers.

Recommended:
- Start at `0.5` to retain recall.
- Raise toward `0.7` to improve precision.

### 2) Entity Limits and Length
- `max_entities`: Prevent over-extraction.
- `min_entity_length`: Drop single-character tokens.

Recommended:
- For long documents, set `max_entities` to 200-400.
- Use `min_entity_length=2` or `3` for legal/technical text.

### 3) Allowed Types
- `allowed_entity_types`: Whitelist entity categories.

Example:
```python
config = ExtractionConfig(allowed_entity_types=["Person", "Organization"]) 
```

This reduces noise and improves downstream relationship inference.

## Domain Vocabulary

Use `domain_vocab` to bias entity typing. It maps type -> list of keywords.

```python
config = ExtractionConfig(
    domain_vocab={
        "Legal": ["contract", "agreement", "clause"],
        "Medical": ["diagnosis", "patient", "treatment"],
    }
)
```

## Custom Rules

Use `custom_rules` to add deterministic extraction patterns.

```python
config = ExtractionConfig(
    custom_rules=[
        (r"\b[A-Z]{2,4}-\d{3}\b", "CaseID"),
        (r"\bSection\s+\d+\b", "LegalSection"),
    ]
)
```

Rules run alongside the default extractor and help catch domain-specific tokens.

## LLM Fallback Strategy

If you configure an LLM backend, enable fallback for low-confidence cases.

```python
config = ExtractionConfig(
    llm_fallback_threshold=0.35,
)

generator = OntologyGenerator(
    config.to_dict(),
    llm_backend=my_llm_client,
)
```

Notes:
- Set `llm_fallback_threshold=0.0` to disable.
- Use a low threshold to avoid over-calling the LLM.

## Stopwords and Noise Control

Use `stopwords` to remove common noise tokens.

```python
config = ExtractionConfig(
    stopwords=["the", "and", "section"],
)
```

## Validation Checklist

After extraction, validate these invariants:

1. **Entity IDs are unique**
2. **Confidence in [0.0, 1.0]**
3. **Relationship endpoints exist in entities**
4. **Expected types appear in results**

## Debugging Tips

- If no entities appear, lower `confidence_threshold`.
- If too many appear, raise `confidence_threshold` or use `allowed_entity_types`.
- If entities are too short, raise `min_entity_length`.
- If you need domain-specific tokens, add `custom_rules` or `domain_vocab`.

## Suggested Defaults by Domain

| Domain | confidence_threshold | min_entity_length | allowed_entity_types |
|---|---:|---:|---|
| General | 0.5 | 2 | [] |
| Legal | 0.6 | 3 | ["Person", "Organization", "Legal", "Date"] |
| Medical | 0.55 | 3 | ["Person", "Medical", "Medication"] |
| Technical | 0.5 | 2 | ["Concept", "Organization", "Technical"] |

## Related References

- `EXTRACTION_CONFIG_GUIDE.md`
- `ipfs_datasets_py/optimizers/graphrag/ontology_generator.py`
- `ipfs_datasets_py/optimizers/graphrag/ontology_types.py`
