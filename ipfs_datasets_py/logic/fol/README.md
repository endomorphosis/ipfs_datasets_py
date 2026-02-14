# FOL (First-Order Logic) Module

**Purpose:** Convert natural language text to First-Order Logic with NLP-powered extraction and ML confidence scoring.

## Quick Start

### Basic Usage

```python
from ipfs_datasets_py.logic.fol import FOLConverter

# Create converter with default settings
converter = FOLConverter()

# Convert text to FOL
result = converter.convert("All humans are mortal")

if result.success:
    print(f"Formula: {result.output.formula_string}")
    print(f"Confidence: {result.confidence:.2f}")
    # Formula: ∀x(Human(x) → Mortal(x))
    # Confidence: 0.85
```

### Features

The FOL converter provides:

- ✅ **NLP Extraction** - spaCy-based predicate extraction (with regex fallback)
- ✅ **ML Confidence** - Confidence scoring for conversion quality
- ✅ **Caching** - Bounded cache with TTL and LRU eviction (14x speedup on hits)
- ✅ **Batch Processing** - Convert multiple texts in parallel (5-8x speedup)
- ✅ **Multiple Formats** - Output as JSON, Prolog, or TPTP
- ✅ **Monitoring** - Real-time operation tracking
- ✅ **Type Safety** - Full type hints with mypy validation

### Configuration Options

```python
converter = FOLConverter(
    use_cache=True,          # Enable caching (default: True)
    cache_maxsize=1000,      # Max cache entries (default: 1000)
    cache_ttl=3600,          # Cache TTL in seconds (default: 3600 = 1 hour)
    use_ml=True,             # ML confidence scoring (default: True)
    use_nlp=True,            # spaCy NLP extraction (default: True)
    use_ipfs=False,          # IPFS distributed caching (default: False)
    enable_monitoring=True,  # Operation monitoring (default: True)
    output_format="json",    # Output format: json, prolog, tptp (default: "json")
    confidence_threshold=0.7 # Minimum confidence (default: 0.7)
)
```

### Batch Conversion

```python
# Convert multiple texts efficiently
texts = [
    "All humans are mortal",
    "Socrates is a human",
    "Therefore, Socrates is mortal"
]

results = converter.convert_batch(texts, max_workers=4)

for text, result in zip(texts, results):
    if result.success:
        print(f"{text} → {result.output.formula_string}")
```

### Output Formats

```python
# JSON (default)
converter = FOLConverter(output_format="json")
result = converter.convert("All cats are animals")
# JSON output with formula, predicates, quantifiers

# Prolog
converter = FOLConverter(output_format="prolog")
result = converter.convert("All cats are animals")
# cat(X) :- animal(X).

# TPTP (Theorem Prover format)
converter = FOLConverter(output_format="tptp")
result = converter.convert("All cats are animals")
# fof(axiom1, axiom, ![X]: (cat(X) => animal(X))).
```

### Cache Statistics

```python
# Get detailed cache performance metrics
stats = converter.get_cache_stats()

print(f"Cache type: {stats['cache_type']}")  # "bounded"
print(f"Hit rate: {stats['hit_rate']:.1%}")  # e.g., "85.3%"
print(f"Size: {stats['size']}/{stats['maxsize']}")
print(f"Evictions: {stats['evictions']}")
print(f"Expirations: {stats['expirations']}")

# Cleanup expired entries manually
cleaned = converter.cleanup_expired_cache()
```

### Error Handling

```python
from ipfs_datasets_py.logic.common import ConversionError

result = converter.convert("")

if not result.success:
    print(f"Errors: {result.errors}")
    print(f"Warnings: {result.warnings}")

# Errors: ['Input text cannot be empty']
```

## Architecture

```
fol/
├── __init__.py           # Module exports
├── converter.py          # FOLConverter (unified architecture)
├── text_to_fol.py       # Text-to-FOL conversion logic
└── utils/               # FOL utilities
    ├── predicate_extractor.py      # Regex-based extraction
    ├── nlp_predicate_extractor.py  # spaCy-based extraction
    └── fol_parser.py               # FOL parsing and formatting
```

## Dependencies

**Required:**
- Python 3.12+

**Optional:**
- `spacy` + model - For NLP-based predicate extraction
  ```bash
  pip install spacy
  python -m spacy download en_core_web_sm
  ```
- `scikit-learn` - For ML confidence scoring
- `ipfs_kit_py` - For IPFS distributed caching

## Examples

### Example 1: Legal Text

```python
text = "The tenant must pay rent on the first day of each month"
result = converter.convert(text)

# Formula: Obligation(Tenant, Pay(Rent, FirstDayOfMonth))
# Confidence: 0.82
```

### Example 2: Logical Implication

```python
text = "If it rains, then the ground is wet"
result = converter.convert(text)

# Formula: Rain → WetGround
# Confidence: 0.91
```

### Example 3: Universal Quantification

```python
text = "Every student has a teacher"
result = converter.convert(text)

# Formula: ∀x(Student(x) → ∃y(Teacher(y) ∧ Has(x, y)))
# Confidence: 0.78
```

## Performance

- **Cache hit speedup:** 14x (validated in benchmarks)
- **Batch processing:** 5-8x faster than sequential
- **Conversion time:** ~10-50ms per text (without cache)
- **Memory:** Bounded cache prevents memory leaks
- **Throughput:** ~100-500 conversions/second (cached)

## Testing

```bash
# Run FOL module tests
pytest tests/unit_tests/logic/fol/ -v

# With coverage
pytest tests/unit_tests/logic/fol/ --cov=ipfs_datasets_py.logic.fol
```

## References

- [UNIFIED_CONVERTER_GUIDE.md](../UNIFIED_CONVERTER_GUIDE.md) - Converter architecture
- [CACHING_ARCHITECTURE.md](../CACHING_ARCHITECTURE.md) - Caching strategies
- [FEATURES.md](../FEATURES.md) - Complete feature catalog
- [DOCUMENTATION_INDEX.md](../DOCUMENTATION_INDEX.md) - All documentation

## Migration from Legacy

If you're using the old `text_to_fol` function:

```python
# Old way (deprecated)
from ipfs_datasets_py.logic.fol.text_to_fol import text_to_fol
result = text_to_fol("text")

# New way (recommended)
from ipfs_datasets_py.logic.fol import FOLConverter
converter = FOLConverter()
result = converter.convert("text")
```

See [MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md) for complete migration instructions.
