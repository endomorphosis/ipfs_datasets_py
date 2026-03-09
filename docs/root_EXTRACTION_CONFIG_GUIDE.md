# ExtractionConfig Guide

A detailed reference for configuring entity and relationship extraction in GraphRAG ontology generation.

## Overview

`ExtractionConfig` is a dataclass that controls how the `OntologyGenerator` extracts entities and relationships from text, validates extracted data, and handles fallback scenarios. It enables fine-grained control over the extraction pipeline without modifying code.

**Location**: `ipfs_datasets_py/optimizers/graphrag/__init__.py`  
**Class**: `ExtractionConfig` (dataclass with validation)

---

## Configuration Fields

### Confidence Threshold Parameters

#### `confidence_threshold: float = 0.5`
**Range**: `[0.0, 1.0]`  
**Default**: `0.5`

Minimum confidence score for extracted entities to be included in results. Entities with confidence below this threshold are filtered out during extraction.

**Usage**:
```python
config = ExtractionConfig(confidence_threshold=0.7)  # Only high-confidence entities
```

**Impact**:
- **Higher values** (0.7+): Stricter extraction, fewer entities but higher precision
- **Lower values** (0.3-): More lenient, more entities captured but lower precision
- **Recommended for**: Legal/medical domains use 0.7+, general text use 0.5

---

#### `max_confidence: float = 1.0`
**Range**: `(0.0, 1.0]`  
**Default**: `1.0`

Maximum allowed confidence value for entities. If an entity exceeds this, its confidence is clamped.

**Usage**:
```python
config = ExtractionConfig(max_confidence=0.95)  # Never super-confident
```

**Impact**:
- Prevents overconfidence in extraction results
- Useful for conservative scoring in safety-critical domains

---

#### `llm_fallback_threshold: float = 0.0`
**Range**: `[0.0, 1.0]`  
**Default**: `0.0` (disabled)

If rule-based extraction confidence is below this threshold, attempt LLM-based extraction as fallback.

**Usage**:
```python
config = ExtractionConfig(llm_fallback_threshold=0.4)  # Use LLM if rule-based < 0.4
```

**Requirements**:
- `ipfs_accelerate_py` must be installed (pip install ipfs_accelerate_py)
- LLM backend must be configured in OntologyGenerator

**Impact**:
- **0.0**: LLM fallback disabled (default, faster)
- **0.3-0.4**: LLM fallback for low-confidence rule-based results
- **High values (>0.7)**: Almost always use LLM (slower but better quality)

---

### Extraction Window Parameters

#### `window_size: int = 1000`
**Range**: `≥ 1`  
**Default**: `1000`

When using context window extraction, size of each text window in characters.

**Usage**:
```python
config = ExtractionConfig(window_size=2000)  # Larger windows for more context
```

**Impact**:
- **Larger values** (2000+): More context per window, better relationship detection but slower
- **Smaller values** (500-): Faster processing, more windows needed for large texts
- **Typical range**: 500-2000 characters

---

#### `window_overlap: int = 100`
**Range**: `[0, window_size)`  
**Default**: `100`

Overlap between consecutive windows to capture entities/relationships at boundaries.

**Usage**:
```python
config = ExtractionConfig(window_size=1000, window_overlap=200)  # 20% overlap
```

**Impact**:
- **Higher overlap**: Fewer missed entities at boundaries but more processing
- **0 overlap**: No redundancy, faster but may miss boundary entities
- **Typical**: 10-20% of window_size

---

### Entity Filtering Parameters

#### `min_entity_length: int = 2`
**Range**: `≥ 1`  
**Default**: `2`

Minimum character length for extracted entities. Entities shorter than this are discarded.

**Usage**:
```python
config = ExtractionConfig(min_entity_length=3)  # No 1-2 char entities
```

**Impact**:
- **Lower values** (1-2): More entities captured, including initials/abbreviations
- **Higher values** (5+): Fewer, longer entities only
- **Recommended**: 2-3 for most domains

---

#### `max_entities_per_document: int = 0` (unlimited)
**Range**: `≥ 0`  
**Default**: `0` (no limit)

Maximum number of entities to extract from a single document. Set to 0 for unlimited.

**Usage**:
```python
config = ExtractionConfig(max_entities_per_document=500)  # Cap at 500 entities
```

**Impact**:
- Prevents memory issues on very large documents
- Helps with consistent output sizes
- 0 = unlimited (may process many entities from large texts)

---

#### `max_relationships_per_document: int = 0` (unlimited)
**Range**: `≥ 0`  
**Default**: `0` (no limit)

Maximum number of relationships to infer between entities.

**Usage**:
```python
config = ExtractionConfig(max_relationships_per_document=1000)  # Cap at 1000 rels
```

**Impact**:
- Controls complexity of the entity graph
- Prevents dense, hard-to-interpret ontologies
- 0 = unlimited

---

#### `allowed_entity_types: List[str] = []` (all allowed)
**Default**: `[]` (empty list means all types allowed)

Whitelist of entity types to extract. Only entities matching these types are kept.

**Usage**:
```python
config = ExtractionConfig(allowed_entity_types=['person', 'organization', 'location'])
# Only extracts entities of these types; others are filtered out
```

**Common Types**:
- `person`: People, characters
- `organization`: Companies, agencies, groups
- `location`: Places, geographic features
- `date`: Dates and time periods
- `concept`: Abstract ideas, principles
- `obligation`: Legal duties, requirements
- `event`: Activities, incidents

**Impact**:
- Empty list (default) = all types allowed
- Non-empty list = strict type filtering
- Useful for domain-specific extraction

---

#### `stopwords: Set[str] = set()` (no stopwords)
**Default**: `set()` (empty set)

Words to exclude from entity extraction. Case-insensitive matching.

**Usage**:
```python
config = ExtractionConfig(stopwords={'the', 'a', 'an', 'and', 'or'})
# "the organization" → extracts "organization" only
```

**Impact**:
- Reduces noise from common/irrelevant words
- Case-insensitive (applied after lowercasing)
- Useful for domain-specific filtering

---

### Custom Extraction Rules

#### `custom_rules: Dict[str, List[str]] = {}`
**Type**: Dictionary mapping domain names to rule lists  
**Default**: `{}`

Domain-specific extraction rules for rule-based extraction engine.

**Usage**:
```python
config = ExtractionConfig(custom_rules={
    'legal': [
        r'(?:party|plaintiff|defendant)\s+[A-Z][a-z]+',
        r'section\s+\d+(?:\.\d+)*'
    ],
    'medical': [
        r'(?:diagnosis|treatment|medication):\s+[A-Za-z\s]+',
        r'(?:ICD-10|CPT)\s+[0-9A-Z\-]+'
    ]
})
```

**Format**:
- Key: domain name (matches extraction domain parameter)
- Value: list of regex patterns to match entities
- Patterns are compiled and applied in order

**Impact**:
- Extends the default rule set from `_extract_rule_based()`
- Domain matching is exact (case-insensitive by convention)
- Rules are union'd with defaults (not replacing them)

---

### Feature Flags & Behavior Control

#### `use_llm_backend: bool = False`
**Default**: `False`

Enable/disable LLM-based extraction fallback (when available).

**Usage**:
```python
config = ExtractionConfig(use_llm_backend=True)  # Enable LLM extraction
```

**Requirements**:
- `ipfs_accelerate_py` must be installed
- LLM API keys configured in environment

**Impact**:
- When True + low rule-based confidence: Attempts LLM extraction
- Much slower than rule-based alone
- Better results for complex text

---

### Configuration Preset Methods

#### `ExtractionConfig.apply_defaults_for_domain(domain: str)`

Mutate the config in-place with domain-appropriate defaults.

**Usage**:
```python
config = ExtractionConfig()
config.apply_defaults_for_domain('legal')
# Now has: confidence_threshold=0.75, min_entity_length=3, etc.
```

**Domain Presets**:

**legal**: $\mathsmalltext{\textbf{High confidence, minimal noise}}$
- `confidence_threshold`: 0.75
- `min_entity_length`: 3
- `max_entities`: 1000
- `allowed_entity_types`: [person, organization, location, obligation, concept]
- `stopwords`: Common legal terminology filters

**medical**: $\mathsmalltext{\textbf{Moderate confidence, standardized terms}}$
- `confidence_threshold`: 0.70
- `min_entity_length`: 2
- `allowed_entity_types`: [person, organization, concept, event]
- Custom rules for medical abbreviations (ICD, CPT codes)

**technical**: $\mathsmalltext{\textbf{Low confidence OK, capture variations}}$
- `confidence_threshold`: 0.50
- `min_entity_length`: 1
- `allowed_entity_types`: [concept, organization, event]
- Custom rules for code identifiers, versions

**general**: $\mathsmalltext{\textbf{Balanced approach}}$
- `confidence_threshold`: 0.50
- `min_entity_length`: 2
- `max_entities`: 500
- All entity types allowed

---

## Validation

### `ExtractionConfig.validate() -> List[str]`

Returns list of validation errors. Raises `ValueError` if any constraint violated.

**Constraints**:
- `confidence_threshold ∈ [0.0, 1.0]`
- `max_confidence ∈ (0.0, 1.0]`
- `confidence_threshold ≤ max_confidence`
- `llm_fallback_threshold ∈ [0.0, 1.0]`
- `window_size ≥ 1`
- `window_overlap < window_size`
- `min_entity_length ≥ 1`
- `max_entities_per_document ≥ 0`
- `max_relationships_per_document ≥ 0`

**Usage**:
```python
config = ExtractionConfig(confidence_threshold=1.5)  # Invalid
errors = config.validate()  # Returns: ['confidence_threshold must be in [0.0, 1.0]']
```

---

## Serialization

### `ExtractionConfig.to_dict() -> Dict[str, Any]`

Convert config to plain dictionary (all settings serialized).

**Usage**:
```python
config = ExtractionConfig(confidence_threshold=0.7, min_entity_length=3)
config_dict = config.to_dict()
# {'confidence_threshold': 0.7, 'min_entity_length': 3, ...}
```

---

### `ExtractionConfig.from_dict(d: Dict[str, Any]) -> ExtractionConfig`

Deserialize config from dictionary (inverse of `to_dict`).

**Usage**:
```python
config_dict = {'confidence_threshold': 0.7, 'min_entity_length': 3}
config = ExtractionConfig.from_dict(config_dict)
```

---

### `ExtractionConfig.to_json() -> str`

JSON serialization (full round-trip with `from_json`).

**Usage**:
```python
config_json = config.to_json()
# Re-load from JSON
new_config = ExtractionConfig.from_json(config_json)
assert config == new_config
```

---

### `ExtractionConfig.to_yaml() -> str`

YAML serialization (readable format for config files).

**Usage**:
```yaml
# config.yaml
confidence_threshold: 0.7
min_entity_length: 3
allowed_entity_types:
  - person
  - organization
window_size: 1500
```

Then load:
```python
config = ExtractionConfig.from_yaml(open('config.yaml').read())
```

---

### `ExtractionConfig.to_toml() -> str`

TOML serialization (another human-readable format).

---

## Utility Methods

### `ExtractionConfig.copy() -> ExtractionConfig`

Create a shallow copy of the config.

---

### `ExtractionConfig.clone() -> ExtractionConfig`

Create a deep copy of the config (safer for nested structures).

---

### `ExtractionConfig.merge(other: "ExtractionConfig") -> "ExtractionConfig"`

Merge two configs, with `other` values taking precedence.

**Usage**:
```python
base = ExtractionConfig(confidence_threshold=0.5)
override = ExtractionConfig(confidence_threshold=0.8)
merged = base.merge(override)
# Result: confidence_threshold=0.8 (from override)
```

---

### `ExtractionConfig.is_strict() -> bool`

Check if config is strict (confidence_threshold ≥ 0.8).

```python
config = ExtractionConfig(confidence_threshold=0.8)
config.is_strict()  # True
```

---

### `ExtractionConfig.is_looser_than(other: "ExtractionConfig") -> bool`

Check if this config is more lenient than another.

```python
lenient = ExtractionConfig(confidence_threshold=0.3)
strict = ExtractionConfig(confidence_threshold=0.8)
lenient.is_looser_than(strict)  # True
```

---

### `ExtractionConfig.scale_thresholds(factor: float) -> "ExtractionConfig"`

Return a copy with all thresholds scaled by a factor.

**Usage**:
```python
config = ExtractionConfig(confidence_threshold=0.5)
looser = config.scale_thresholds(0.9)  # confidence_threshold becomes 0.45
stricter = config.scale_thresholds(1.1)  # confidence_threshold becomes 0.55
```

---

### `ExtractionConfig.describe() -> str`

Return human-readable summary of the config.

**Usage**:
```python
config = ExtractionConfig(confidence_threshold=0.7, min_entity_length=3)
print(config.describe())
# Output:
# ExtractionConfig:
#   confidence_threshold=0.70 (strict)
#   max_confidence=1.00
#   llm_fallback_threshold=0.00 (disabled)
#   window_size=1000
#   window_overlap=100
#   min_entity_length=3
#   max_entities_per_document=0 (unlimited)
#   max_relationships_per_document=0 (unlimited)
#   allowed_entity_types=[] (all allowed)
#   stopwords=set() (disabled)
#   custom_rules={} (no custom rules)
#   use_llm_backend=False
```

---

## Common Patterns

### Pattern 1: High-Confidence Legal Extraction

```python
config = ExtractionConfig(
    confidence_threshold=0.80,
    min_entity_length=3,
    max_entities_per_document=500,
    allowed_entity_types=['person', 'organization', 'location', 'obligation'],
    stopwords={'the', 'a', 'an', 'and', 'or'},
)
config.apply_defaults_for_domain('legal')
```

**Result**: High precision, low recall; suitable for contract analysis.

---

### Pattern 2: Exploratory General Extraction

```python
config = ExtractionConfig(
    confidence_threshold=0.3,
    window_size=500,
    window_overlap=50,
)
```

**Result**: Many entities, rapid feedback; good for prototyping.

---

### Pattern 3: Medical Domain with LLM Fallback

```python
config = ExtractionConfig(
    confidence_threshold=0.60,
    llm_fallback_threshold=0.50,  # Use LLM if rule-based < 0.50
    allowed_entity_types=['concept', 'organization', 'person'],
    use_llm_backend=True,
)
config.apply_defaults_for_domain('medical')
```

**Result**: Balanced precision/recall with LLM backup for uncertain cases.

---

### Pattern 4: Large Document Streaming

```python
config = ExtractionConfig(
    window_size=2000,
    window_overlap=200,
    max_entities_per_document=1000,
    max_relationships_per_document=5000,
)
```

**Result**: Efficient processing of large texts with context window sliding.

---

## Testing & Validation

### Test Your Config

```python
from ipfs_datasets_py.optimizers.graphrag import OntologyGenerator, ExtractionConfig

# Create and validate config
config = ExtractionConfig(confidence_threshold=0.7, min_entity_length=3)
errors = config.validate()
assert len(errors) == 0, f"Config has errors: {errors}"

# Use with OntologyGenerator
generator = OntologyGenerator()
context = OntologyGenerationContext(extraction_config=config)
result = generator.extract_entities("Your text here...", context)

# Inspect results
print(f"Extracted {len(result.entities)} entities")
print(f"Extraction confidence: {result.confidence:.2f}")
```

---

## Troubleshooting

### Problem: Too Few Entities Extracted

**Causes**:
- `confidence_threshold` too high (try 0.5)
- `min_entity_length` too high (try 2)
- `allowed_entity_types` too restrictive

**Solution**:
```python
config = ExtractionConfig(
    confidence_threshold=0.5,
    min_entity_length=2,
    allowed_entity_types=[]  # Allow all types
)
```

---

### Problem: Too Many Low-Quality Entities

**Causes**:
- `confidence_threshold` too low
- `min_entity_length` too low

**Solution**:
```python
config = ExtractionConfig(
    confidence_threshold=0.75,  # Higher threshold
    min_entity_length=3,  # Longer entities
    stopwords={'the', 'a', 'and', 'or'}  # Filter noise
)
```

---

### Problem: Extraction Timeout on Large Documents

**Causes**:
- `max_entities_per_document` not set (processing all entities)
- `window_size` too large

**Solution**:
```python
config = ExtractionConfig(
    max_entities_per_document=500,  # Cap entities
    window_size=1000,  # Smaller windows
    window_overlap=50,  # Less overlap
)
```

---

### Problem: LLM Fallback Not Triggering

**Causes**:
- `llm_fallback_threshold` = 0 (disabled by default)
- LLM backend not installed/configured

**Solution**:
```python
config = ExtractionConfig(
    llm_fallback_threshold=0.4,  # Enable fallback
    use_llm_backend=True,
)
# Ensure ipfs_accelerate_py is installed and LLM keys configured
```

---

## Best Practices

1. **Validate your config** before using it:
   ```python
   errors = config.validate()
   assert not errors, f"Config errors: {errors}"
   ```

2. **Use domain presets** as starting points:
   ```python
   config = ExtractionConfig()
   config.apply_defaults_for_domain('legal')
   # Then customize as needed
   ```

3. **Test with small documents first** to tune parameters before large runs.

4. **Document your config choice** with comments explaining why specific thresholds were chosen.

5. **Round-trip serialize** to ensure configuration reproducibility:
   ```python
   saved_dict = config.to_dict()
   reloaded = ExtractionConfig.from_dict(saved_dict)
   assert config == reloaded
   ```

6. **Use `describe()`** to log config details for debugging extraction results.

---

## API Reference Summary

| Method | Purpose |
|--------|---------|
| `validate()` | Check config constraints |
| `to_dict()` / `from_dict()` | Dict serialization |
| `to_json()` / `from_json()` | JSON serialization |
| `to_yaml()` / `from_yaml()` | YAML serialization |
| `to_toml()` / `from_toml()` | TOML serialization |
| `copy()` / `clone()` | Copy config |
| `merge(other)` | Merge two configs |
| `apply_defaults_for_domain(d)` | Apply domain presets |
| `scale_thresholds(f)` | Scale all thresholds |
| `describe()` | Get human-readable summary |
| `is_strict()` | Check if threshold ≥ 0.8 |
| `is_looser_than(other)` | Compare with another config |

---

## See Also

- [OntologyGenerator API](ipfs_datasets_py/optimizers/graphrag/ontology_generator.py)
- [Entity Extraction Examples](tests/unit/optimizers/graphrag/)
- [Ontology Generation Architecture](ipfs_datasets_py/optimizers/ARCHITECTURE.md)
