# GraphRAG Ontology Generation — Quick Start

Goal: extract a small ontology (entities + relationships) from text in ~5–10 minutes.

## Prerequisites

- Python environment with `ipfs_datasets_py` installed (editable install is fine).
- A short text snippet to extract from.

## 1) Create a generator + context

```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionStrategy,
    DataType,
)

generator = OntologyGenerator()

ctx = OntologyGenerationContext(
    data_source="quickstart",
    data_type=DataType.TEXT,
    domain="legal",
    extraction_strategy=ExtractionStrategy.RULE_BASED,
)
```

## 2) Extract entities + relationships from text

```python
text = """
Alice Smith must pay Bob Johnson $10,000 by December 31, 2025.
Payment shall be made to XYZ Corporation's bank account.
""".strip()

result = generator.extract_entities(text, ctx)

print(f"Entities: {len(result.entities)}")
print(f"Relationships: {len(result.relationships)}")

for e in result.entities:
    print(f"- {e.id}: {e.text} ({e.type}, conf={e.confidence:.2f})")

for r in result.relationships:
    print(f"- {r.id}: {r.type} {r.source_id} -> {r.target_id} (conf={r.confidence:.2f})")
```

## 3) (Optional) Filter to higher-confidence entities

```python
filtered = result.filter_by_confidence(0.7)
print(f"Filtered entities: {len(filtered.entities)}")
print(f"Filtered relationships: {len(filtered.relationships)}")
```

## 4) Next steps

- More complete examples: `docs/USAGE_EXAMPLES.md` (GraphRAG → Ontology Generation)
- Configuration details: `docs/EXTRACTION_CONFIG_GUIDE.md`
- CLI usage: `docs/quickstart/cli_quick_start.md`
