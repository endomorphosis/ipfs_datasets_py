# Deontic Logic Module

**Purpose:** Convert legal text and policy documents to deontic logic (obligations, permissions, prohibitions) with domain-specific analysis.

## Quick Start

### Basic Usage

```python
from ipfs_datasets_py.logic.deontic import DeonticConverter

# Create converter with default settings
converter = DeonticConverter()

# Convert legal text to deontic logic
result = converter.convert("The tenant must pay rent by the first of each month")

if result.success:
    print(f"Operators: {result.output.operators}")
    print(f"Obligations: {result.output.obligations}")
    print(f"Confidence: {result.confidence:.2f}")
    # Operators: ['OBLIGATION']
    # Obligations: [{'actor': 'tenant', 'action': 'pay_rent', 'deadline': 'first_of_month'}]
    # Confidence: 0.87
```

### Features

The Deontic converter provides:

- ✅ **Legal Domain Support** - US, EU, UK, International jurisdiction support
- ✅ **Document Types** - Statutes, regulations, contracts, policies, agreements
- ✅ **Deontic Operators** - Obligation (O), Permission (P), Prohibition (F)
- ✅ **Obligation Extraction** - Automatic extraction of duties and requirements
- ✅ **Exception Handling** - Identifies conditions and exceptions
- ✅ **Caching** - Bounded cache with TTL and LRU eviction
- ✅ **ML Confidence** - Quality scoring for extractions
- ✅ **Type Safety** - Full type hints and validation

### Configuration Options

```python
converter = DeonticConverter(
    use_cache=True,              # Enable caching (default: True)
    cache_maxsize=1000,          # Max cache entries (default: 1000)
    cache_ttl=3600,              # Cache TTL in seconds (default: 3600 = 1 hour)
    use_ml=True,                 # ML confidence scoring (default: True)
    enable_monitoring=True,      # Operation monitoring (default: True)
    jurisdiction="us",           # Legal jurisdiction (default: "us")
    document_type="contract",    # Document type (default: "statute")
    extract_obligations=True,    # Extract obligations (default: True)
    include_exceptions=True,     # Include exception clauses (default: True)
    confidence_threshold=0.7,    # Minimum confidence (default: 0.7)
    output_format="json"         # Output format (default: "json")
)
```

### Jurisdiction Support

```python
# US Law
converter = DeonticConverter(jurisdiction="us")

# European Union
converter = DeonticConverter(jurisdiction="eu")

# UK Law
converter = DeonticConverter(jurisdiction="uk")

# International Treaties
converter = DeonticConverter(jurisdiction="international")

# General (domain-agnostic)
converter = DeonticConverter(jurisdiction="general")
```

### Document Types

```python
# Statute/Legislation
converter = DeonticConverter(document_type="statute")

# Regulation/Rule
converter = DeonticConverter(document_type="regulation")

# Contract/Agreement
converter = DeonticConverter(document_type="contract")

# Policy Document
converter = DeonticConverter(document_type="policy")

# General Agreement
converter = DeonticConverter(document_type="agreement")
```

### Batch Processing

```python
# Convert multiple legal clauses efficiently
clauses = [
    "The seller must deliver goods within 30 days",
    "The buyer may inspect goods upon delivery",
    "The tenant shall not sublet without written permission"
]

results = converter.convert_batch(clauses, max_workers=4)

for clause, result in zip(clauses, results):
    if result.success:
        print(f"{clause}")
        print(f"  Operator: {result.output.operators[0]}")
```

### Extracting Obligations

```python
text = """
The contractor must complete work by December 31, 2025.
The client must pay within 15 days of invoice.
Either party may terminate with 30 days notice.
"""

result = converter.convert(text)

for obligation in result.output.obligations:
    print(f"Actor: {obligation['actor']}")
    print(f"Action: {obligation['action']}")
    print(f"Deadline: {obligation.get('deadline', 'N/A')}")
    print()
```

### Exception Handling

```python
text = """
The tenant must pay rent, unless the property is uninhabitable.
The landlord may enter, except in cases of emergency.
"""

result = converter.convert(text)

for formula in result.output.formulas:
    if formula.get('exceptions'):
        print(f"Deontic: {formula['operator']}")
        print(f"Exceptions: {formula['exceptions']}")
```

## Deontic Operators

### Obligation (O)

Represents **duties** and **requirements**:

```python
text = "The tenant must pay rent"
# O(tenant, pay_rent)
```

**Keywords:** must, shall, required to, obligated to, duty to

### Permission (P)

Represents **rights** and **allowances**:

```python
text = "The tenant may have pets"
# P(tenant, have_pets)
```

**Keywords:** may, can, allowed to, permitted to, has the right to

### Prohibition (F)

Represents **bans** and **restrictions**:

```python
text = "The tenant shall not smoke indoors"
# F(tenant, smoke_indoors)
```

**Keywords:** must not, shall not, prohibited from, forbidden to, may not

## Examples

### Example 1: Rental Agreement

```python
text = """
1. The tenant shall pay $1,500 rent monthly by the first.
2. The landlord must maintain heating and plumbing.
3. The tenant may not sublet without written permission.
4. Either party may terminate with 60 days notice.
"""

result = converter.convert(text)

# Extracted:
# O(tenant, pay_rent($1500, monthly, first))
# O(landlord, maintain(heating, plumbing))
# F(tenant, sublet) ∨ P(tenant, sublet | written_permission)
# P(tenant, terminate(60_days_notice))
# P(landlord, terminate(60_days_notice))
```

### Example 2: Employment Contract

```python
text = "The employee must work 40 hours per week and may not disclose confidential information"

result = converter.convert(text)

# O(employee, work(40_hours, weekly))
# F(employee, disclose(confidential_info))
```

### Example 3: Software License

```python
text = """
You may use, copy, and modify the software.
You must include this license in all copies.
You may not use the software for commercial purposes.
"""

result = converter.convert(text)

# P(user, use(software))
# P(user, copy(software))
# P(user, modify(software))
# O(user, include(license, copies))
# F(user, commercial_use(software))
```

## Cache Statistics

```python
# Get detailed cache performance
stats = converter.get_cache_stats()

print(f"Cache type: {stats['cache_type']}")
print(f"Hit rate: {stats['hit_rate']:.1%}")
print(f"Jurisdiction: {stats['jurisdiction']}")
print(f"Document type: {stats['document_type']}")

# Cleanup expired entries
cleaned = converter.cleanup_expired_cache()
```

## Architecture

```
deontic/
├── __init__.py                    # Module exports
├── converter.py                   # DeonticConverter (unified architecture)
├── legal_text_to_deontic.py      # Legal text conversion logic
└── utils/                         # Deontic utilities
    ├── deontic_operators.py       # Operator extraction
    ├── obligation_extractor.py    # Obligation identification
    └── deontic_parser.py          # Parsing and formatting
```

## Performance

- **Cache hit speedup:** 14x (validated in benchmarks)
- **Batch processing:** 5-8x faster than sequential
- **Conversion time:** ~15-60ms per clause (without cache)
- **Memory:** Bounded cache prevents memory leaks
- **Throughput:** ~50-200 conversions/second (cached)

## Testing

```bash
# Run deontic module tests
pytest tests/unit_tests/logic/deontic/ -v

# With coverage
pytest tests/unit_tests/logic/deontic/ --cov=ipfs_datasets_py.logic.deontic
```

## References

- [UNIFIED_CONVERTER_GUIDE.md](../UNIFIED_CONVERTER_GUIDE.md) - Converter architecture
- [CACHING_ARCHITECTURE.md](../CACHING_ARCHITECTURE.md) - Caching strategies
- [FEATURES.md](../FEATURES.md) - Complete feature catalog
- [DOCUMENTATION_INDEX.md](../DOCUMENTATION_INDEX.md) - All documentation

## Migration from Legacy

If you're using the old `legal_text_to_deontic` function:

```python
# Old way (deprecated)
from ipfs_datasets_py.logic.deontic.legal_text_to_deontic import legal_text_to_deontic
result = legal_text_to_deontic("text")

# New way (recommended)
from ipfs_datasets_py.logic.deontic import DeonticConverter
converter = DeonticConverter()
result = converter.convert("text")
```

See [MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md) for complete migration instructions.
