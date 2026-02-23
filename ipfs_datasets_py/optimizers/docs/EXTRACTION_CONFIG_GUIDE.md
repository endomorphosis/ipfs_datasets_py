# ExtractionConfig Configuration Guide

_Complete reference for configuring entity extraction in GraphRAG ontology generation._

## Overview

The `ExtractionConfig` dataclass controls all aspects of how the `OntologyGenerator` extracts entities and relationships from text. Use this guide to understand each field and its impact on extraction quality and performance.

## Quick Reference

```python
from ipfs_datasets_py.optimizers.graphrag import ExtractionConfig

# Legal domain (strict extraction)
legal_config = ExtractionConfig(
    domain="legal",
    confidence_threshold=0.85,
    max_entities=500,
    llm_fallback_threshold=0.7
)

# Medical domain (balanced)
medical_config = ExtractionConfig(
    domain="medical",
    confidence_threshold=0.75,
    max_entities=1000,
    stopwords=["patient", "doctor"],  # domain jargon to ignore
)

# General/financial domain (inclusive)
finance_config = ExtractionConfig(
    domain="financial",
    confidence_threshold=0.65,
    max_entities=2000,
    allowed_entity_types=["Person", "Organization", "monetary_amount"]
)
```

## Field Reference

### Core Configuration

#### `domain: str` (default: `"general"`)

The subject domain for extraction. Controls which rule sets and vocabulary are active.

**Valid values:**
- `"legal"` — legal documents, contracts, court filings
- `"medical"` — clinical notes, medical research, health records
- `"financial"` — balance sheets, earnings calls, investment reports
- `"technical"` — code, architecture docs, API documentation
- `"general"` — fallback for mixed or unknown domains

**Impact:**
- Selects domain-specific NER patterns
- Activates keyword sets for domain alignment scoring
- Example: `domain="legal"` enables extraction of `Obligation` and `Court` entity types

**Common use case:**
```python
# Extract from a contract
config = ExtractionConfig(domain="legal")
result = generator.extract_entities(contract_text, config)
```

---

#### `confidence_threshold: float` (default: `0.5`, range: `[0.0, 1.0]`)

Minimum confidence score required to keep an extracted entity.

**Interpretation:**
- `0.0–0.5` → Lenient; includes all uncertain entities
- `0.5–0.7` → Balanced; standard production setting
- `0.7–0.9` → Strict; high-precision extraction
- `0.9–1.0` → Very strict; only highest-confidence entities

**Trade-offs:**
| Threshold | Recall | Precision | Use Case |
|-----------|--------|-----------|----------|
| 0.3 | High | Low | Exploratory analysis, quantity > quality |
| 0.5 | Medium | Medium | Balanced extraction |
| 0.75 | Low | High | Mission-critical data, legal documents |
| 0.95 | Very Low | Very High | Only obvious entities |

**Impact on extraction quality:**
```python
# Lenient (find more entities, less certain)
lenient = ExtractionConfig(confidence_threshold=0.4)
result_lenient = generator.extract_entities(text, lenient)
# → 150 entities (avg confidence: 0.62)

# Strict (find fewer entities, more certain)
strict = ExtractionConfig(confidence_threshold=0.85)
result_strict = generator.extract_entities(text, strict)
# → 45 entities (avg confidence: 0.91)
```

---

#### `max_entities: int` (default: `0` = unlimited, range: `[0, ∞)`)

Maximum number of entities to extract from a document.

**Behavior:**
- `0` → No limit; extract all entities above confidence threshold
- `> 0` → Cap at this number; keep entities with highest confidence first

**When to use:**
- `max_entities=500` → Large documents; prevent memory bloat
- `max_entities=0` → Short text, quality critical
- `max_entities=100` → Real-time performance constraints

**Example:**
```python
# Limit output for speed
config = ExtractionConfig(max_entities=100)
# Even if 500 entities pass confidence threshold,
# only top-100 by confidence are returned
```

---

#### `max_confidence: float` (default: `1.0`, range: `(0.0, 1.0]`)

Cap all entity confidences at this value. Useful for calibrating scores across domains.

**Example:**
```python
# Pessimistic config: cap all scores at 0.8
# (no entity can score 0.9 or 1.0)
pessimistic = ExtractionConfig(
    confidence_threshold=0.5,
    max_confidence=0.8
)
```

---

### Relationship Configuration

#### `infer_relationships: bool` (default: `True`)

Whether to infer relationships between extracted entities.

**When `True`:**
- Uses verb-proximity heuristics to detect relationships
- Scans for co-occurrence patterns
- Infers relationship types (obligates, owns, manages, etc.)

**When `False`:**
- Returns only entities; no relationships
- Faster extraction; simpler results

```python
# Entities only, no relationships
config = ExtractionConfig(infer_relationships=False)

# Full extraction with relationships
config = ExtractionConfig(infer_relationships=True)
```

---

#### `window_size: int` (default: `150`, range: `[50, 1000]`)

Co-occurrence window size (in characters) for relationship inference.

**Interpretation:**
- Entities within `window_size` chars may have a relationship
- Larger window → more relationships detected (higher recall, lower precision)
- Smaller window → fewer relationships, higher confidence

**Default behavior:**
```python
# Window_size=150 means relationships are inferred
# between entities separated by ≤150 characters
# (roughly 20–30 words in English text)

config = ExtractionConfig(window_size=150)
text = "John works at Acme Corp..."
#       └─ ~5 chars apart → likely relationship
```

**Trade-off guide:**
| Window | Recall | Precision | Use Case |
|--------|--------|-----------|----------|
| 50 | Low | High | Adjacent entities only |
| 150 | Medium | Medium | Standard (default) |
| 500 | High | Low | Paragraph-level connections |

---

#### `min_entity_length: int` (default: `2`, range: `[1, ∞)`)

Minimum text length (in characters) for entities.

**Purpose:** Filters out trivial single-character entity matches (like "a", "I").

**Examples:**
```python
# Default: keep entities ≥ 2 characters
config = ExtractionConfig(min_entity_length=2)
# "John" ✓, "a" ✗

# Stricter: enforce minimum 3 characters
config = ExtractionConfig(min_entity_length=3)
# "John" ✓, "Dr" ✗
```

---

### Advanced Filtering

#### `stopwords: List[str]` (default: `[]`)

Custom list of words to exclude from entity text.

**Use case:** Remove common domain jargon that pollutes entity lists.

**Example:**
```python
# Medical domain: exclude common words
medical_config = ExtractionConfig(
    domain="medical",
    stopwords=["patient", "hospital", "drug", "symptom", "treatment"]
)
# If "patient hospital visit" is extracted,
# becomes "visit" after stopword removal
```

---

#### `allowed_entity_types: List[str]` (default: `[]` = allow all types)

Whitelist of entity types to keep. If set, non-matching types are discarded.

**Valid entity types:**
- `"Person"` — individuals, names
- `"Organization"` — companies, institutions  
- `"Location"` — places, geographical features
- `"Date"` — temporal references
- `"Obligation"` — legal duties, requirements (legal domain)
- `"Concept"` — abstract ideas, technical terms

**Example:**
```python
# Only keep people and organizations
config = ExtractionConfig(
    allowed_entity_types=["Person", "Organization"]
)
# If extraction finds [Person, Location, Organization],
# Location is discarded
```

---

#### `custom_rules: Dict[str, List[str]]` (default: `{}`)

Custom regex patterns for domain-specific entity extraction.

**Format:** `{entity_type: [pattern1, pattern2, ...]}`

```python
# Custom patterns for financial domain
finance_config = ExtractionConfig(
    domain="financial",
    custom_rules={
        "StockTicker": [r"\b[A-Z]{1,5}\b(?=\s+stock)", r"\$[A-Z]{1,5}"],
        "Currency": [r"\$[\d,]+(?:\.\d{2})?", r"USD|EUR|GBP"]
    }
)
```

**When used:** Applied AFTER standard extraction; can augment or override defaults.

---

### LLM Fallback

#### `llm_fallback_threshold: float` (default: `0.0` = disabled, range: `[0.0, 1.0]`)

If rule-based extraction confidence is below this threshold, attempt LLM-based extraction as fallback.

**Behavior:**
- `0.0` — Disabled; never use LLM
- `0.3` → Use LLM if rule-based confidence < 0.3
- `0.5` → Always use LLM (since most rule-based results < 0.5)

**Requirements:** Requires `ipfs_accelerate_py` installed and `ENABLE_LLM_EXTRACTION=1` env var

```python
# Hybrid extraction: rules first, LLM fallback
config = ExtractionConfig(
    llm_fallback_threshold=0.6,
    domain="legal"
)
# If rules produce avg confidence < 0.6, 
# LLM passes text to OpenAI/local LLM for re-extraction
```

---

## Domain-Specific Presets

### Legal Extraction

```python
legal_config = ExtractionConfig(
    domain="legal",
    confidence_threshold=0.80,  # High precision
    max_entities=500,
    window_size=250,             # Longer context window
    allowed_entity_types=[
        "Person", "Organization", "Location", "Date", "Obligation", "Court"
    ],
    llm_fallback_threshold=0.65,
    stopwords=["contract", "agreement", "party"]
)
```

**Tuning tips:**
- Increase `window_size` to capture cross-paragraph relationships (contracts are verbose)
- Lower `confidence_threshold` slightly; legal entities are often specific jargon
- Enable LLM fallback for ambiguous clauses

---

### Medical Extraction

```python
medical_config = ExtractionConfig(
    domain="medical",
    confidence_threshold=0.70,  # Balanced
    max_entities=1000,
    window_size=150,
    allowed_entity_types=[
        "Person", "Organization", "Location", "Date", "Concept"
    ],
    stopwords=["patient", "hospital", "clinic", "diagnosis"],
    llm_fallback_threshold=0.50
)
```

**Tuning tips:**
- Medical jargon is dense; use larger `max_entities`
- Include `Concept` type for disease/treatment terms
- Moderate LLM fallback threshold (good for complex case notes)

---

### Financial Extraction

```python
finance_config = ExtractionConfig(
    domain="financial",
    confidence_threshold=0.65,  # Inclusive
    max_entities=2000,
    window_size=200,
    allowed_entity_types=[
        "Person", "Organization", "Location", "Date", "Concept"
    ],
    custom_rules={
        "Currency": [r"\$[\d,]+(?:\.\d{2})?", r"millions?|billions?"]
    },
    llm_fallback_threshold=0.40
)
```

**Tuning tips:**
- Higher `max_entities` for earnings transcripts (lots of metrics)
- Add custom rules for financial terms (ticker symbols, currencies)
- LLM fallback helps with complex financial language

---

## Configuration Methods

### Load from Dictionary

```python
config_dict = {
    "domain": "legal",
    "confidence_threshold": 0.8,
    "max_entities": 500
}
config = ExtractionConfig.from_dict(config_dict)
```

### Load from YAML

```yaml
# config.yaml
domain: legal
confidence_threshold: 0.8
max_entities: 500
stopwords:
  - agreement
  - party
```

```python
import yaml
with open("config.yaml") as f:
    config_dict = yaml.safe_load(f)
config = ExtractionConfig.from_dict(config_dict)
```

### Merge Configurations

```python
base = ExtractionConfig(domain="legal")
overrides = ExtractionConfig(confidence_threshold=0.9)
merged = base.merge(overrides)
# Result: domain="legal", confidence_threshold=0.9
```

---

## Validation & Error Handling

### Validate Configuration

```python
from ipfs_datasets_py.optimizers.graphrag import ExtractionConfig

config = ExtractionConfig(
    confidence_threshold=1.5  # Invalid!
)

try:
    config.validate()
except ValueError as e:
    print(f"Config error: {e}")
    # → "confidence_threshold must be in [0, 1], got 1.5"
```

---

## Best Practices

1. **Start with domain preset** — Use `domain="legal"` etc. before fine-tuning
2. **Set `confidence_threshold` based on precision needs** — Legal (0.8+), general (0.5–0.7)
3. **Limit `max_entities` in production** — Prevent runaway extraction on long documents
4. **Test `window_size` for relationship quality** — Adjust based on your text structure
5. **Use `stopwords` conservatively** — Only remove truly noisy domain terms
6. **Enable LLM fallback sparingly** —  Only for high-stakes extraction, costs money/latency

---

## Examples

### Example 1: Quick Default Extraction

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator, ExtractionConfig

generator = OntologyGenerator()
text = "Apple Inc. CEO Tim Cook announced Q3 results in Cupertino."

# Use defaults
result = generator.extract_entities(text, ExtractionConfig())
print(result)
# → EntityExtractionResult(
#     entities=[Entity(text="Apple Inc.", type="Organization", confidence=0.95),
#               Entity(text="Tim Cook", type="Person", confidence=0.93),
#               Entity(text="Cupertino", type="Location", confidence=0.88)],
#     relationships=[...],
#     overall_confidence=0.92,
#     metadata={...}
# )
```

### Example 2: Strict Legal Contract Extraction

```python
config = ExtractionConfig(
    domain="legal",
    confidence_threshold=0.85,
    window_size=250,
    max_entities=300,
    allowed_entity_types=["Person", "Organization", "Obligation"]
)

contract = """
Party A (Acme Corp, a Delaware corporation) agrees to pay
Party B (John Smith) $50,000 USD for services rendered...
"""

result = generator.extract_entities(contract, config)
# → High-precision extraction; only high-confidence entities
```

### Example 3: Exploratory Medical Text Mining

```python
config = ExtractionConfig(
    domain="medical",
    confidence_threshold=0.40,  # Lenient
    max_entities=2000,
    infer_relationships=True,
    llm_fallback_threshold=0.50
)

medical_note = "Patient presents with fever and cough..."
result = generator.extract_entities(medical_note, config)
# → Exploratory; finds all entities including weak signals
```

---

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| Too few entities extracted | `confidence_threshold` too high | Lower to 0.5–0.7 |
| Too many low-quality entities | `confidence_threshold` too low | Raise to 0.7–0.8 |
| Slow extraction | `max_entities` unset or very high | Set `max_entities=1000` |
| Missing domain-specific terms | No `custom_rules` defined | Add patterns to `custom_rules` |
| Relationships between distant entities | `window_size` too large | Reduce to 100–150 |
| LLM fallback not triggering | `llm_fallback_threshold` not set | Set to 0.5–0.7 |

---

## See Also

- [OntologyGenerator API Reference](./API_REFERENCE_GRAPHRAG.md) — Full class documentation
- [Extraction Examples](./COMPLAINT_ANALYSIS_EXAMPLES.md) — Real-world usage patterns
- [Performance Tuning](./PERFORMANCE_GUIDE.md) — Optimize for speed vs. quality
